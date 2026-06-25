# src/daemon.py — long-lived self-healing reconciler.
# Reconcile is TRIGGERED by one persistent `pactl subscribe` (a single PulseAudio client for the
# daemon's life) on real changes — NOT a per-interval subprocess poll. Why: the old 2s poll
# spawned short-lived pactl/pw-link clients every tick, and wireplumber 0.5.x leaks a GWeakRef per
# short-lived client connect → ~8h of churn exhausts GLib's ceiling and wedges the whole audio
# session. We react only to sink/source add+remove (a cable, physical target, or mic changed) and
# a new sink-input (a stream to auto-route); the Client/source-output churn that feeds the leak —
# and the lower-level PipeWire Node/Link chatter that `pw-mon` would surface (capture taps,
# transient links) — never reaches the Pulse abstraction, so steady state spawns ZERO short-lived
# clients. A slow SAFETY_POLL is the only timed fallback (a missed event, a dead subscribe, or the
# rare pure pw-link teardown that has no Pulse event). reconcile is idempotent + create-if-missing,
# so a self-triggered pass converges immediately.
import os, sys, time, signal, fcntl, tempfile, subprocess, threading
import config, firstrun, main, apps

SAFETY_POLL = 60.0      # s — backstop reconcile when subscribe reports nothing (heal is event-driven)
DEBOUNCE = 0.3          # s — coalesce a burst of events into one reconcile (hotplug, multi-stream app)
MONITOR_RESPAWN = 5.0   # s — wait before respawning `pactl subscribe` if it dies / is unavailable


def _interesting(line):
    """True if a `pactl subscribe` event line should trigger a reconcile+route. Reacts to sink/
    source new+remove (our cables, the 'auto' physical target, a mic hotplug) and a new sink-input
    (a stream to auto-route). IGNORES client/source-output/module/card churn and 'change' (volume/
    mute) events — the short-lived-client storm that drives the wireplumber leak must never wake us.
    Line shape: `Event 'new' on sink-input #123`."""
    parts = line.split("'")
    if len(parts) < 2:
        return False
    typ = parts[1]                                        # new | remove | change
    fac = line.rsplit(" on ", 1)[-1].split(" #", 1)[0].strip()   # sink | source | sink-input | client …
    if fac in ("sink", "source") and typ in ("new", "remove"):
        return True
    return fac == "sink-input" and typ == "new"


def _monitor(dirty):
    """Thread target: ONE persistent `pactl subscribe` whose interesting events set `dirty`.
    A single long-lived client is NOT a leak driver (the leak is per short-lived CONNECT). Blocks
    on readline (no busy-poll). On death it pokes `dirty` (graph may have drifted) and respawns;
    if pactl is unavailable the SAFETY_POLL still heals, just slower."""
    while True:
        try:
            proc = subprocess.Popen(["pactl", "subscribe"], stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, text=True, bufsize=1)
        except Exception:
            time.sleep(MONITOR_RESPAWN); continue         # no pactl -> rely on the safety poll
        for line in proc.stdout:                          # blocks until a line or EOF
            if _interesting(line):
                dirty.set()
        dirty.set(); time.sleep(MONITOR_RESPAWN)          # subscribe exited -> reconcile once, respawn

def single_instance():
    """One daemon per user. The kernel drops this flock on ANY exit (incl. SIGKILL),
    and the pid written in lets other tools find/restart us (Phase 3)."""
    rt = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    f = open(os.path.join(rt, "pipewire-vac.lock"), "a+")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.seek(0); sys.exit("PipeWire VAC already running (pid %s)" % f.read().strip())
    f.seek(0); f.truncate(); f.write(str(os.getpid())); f.flush()
    return f                          # KEEP open for the process lifetime

def _spawn_tray(cfgpath):
    """Best-effort: launch the tray as a separate process. It's garnish — never let a
    missing bus / dbus error take down the daemon. The tray dies with us (PDEATHSIG)."""
    if not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        return None                                  # headless / no session bus -> no tray
    try:
        tray = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tray.py")
        err = open(os.path.join(tempfile.gettempdir(), "pipewire-vac-tray.err"), "wb")
        return subprocess.Popen([sys.executable, tray, "--pid", str(os.getpid()),
                                 "--config", cfgpath or "", "--version", main.VERSION],
                                stdout=err, stderr=err)
    except Exception as e:
        print(f"daemon: tray spawn failed ({e}); continuing trayless", file=sys.stderr)
        return None

def _load_or_keep(cfgpath, last):
    """Reload config; on a missing/unparseable file keep the last-good one (don't crash
    mid-edit). This is what lets config edits apply live with no restart."""
    try:
        return config.load(cfgpath)
    except Exception as e:
        print(f"daemon: config reload failed ({e}); keeping last-good", file=sys.stderr)
        return last

def run_daemon(config_arg=None):
    cfgpath = firstrun.preflight(config_arg)
    lock = single_instance()          # noqa: F841 — held for process lifetime
    cfg = config.load(cfgpath)

    moved = {}                        # {sink-input index: target last applied} — move-once ledger
    summary = main.reconcile_once(cfg)
    print(f"daemon: initial reconcile — {summary or 'no physical sink yet'}", file=sys.stderr)
    apps.route_once(cfg, moved)       # cables exist now -> route matching app streams once
    _spawn_tray(cfgpath)              # garnish; daemon runs fine if it fails

    if not cfg["features"].get("self_heal", True):
        print("daemon: self_heal=false — idle (holding lock)", file=sys.stderr)
        signal.pause()                # block forever; SIGTERM ends it, kernel frees the lock
        return 0

    dirty = threading.Event()
    threading.Thread(target=_monitor, args=(dirty,), daemon=True).start()
    while True:                       # event-driven: reconcile on a real sink/source/stream change,
        if dirty.wait(SAFETY_POLL):   #   else every SAFETY_POLL as a backstop. No per-tick subprocess.
            time.sleep(DEBOUNCE)      # let a burst settle so it coalesces into one reconcile
        dirty.clear()
        cfg = _load_or_keep(cfgpath, cfg)   # pick up config edits live; keep last-good on error
        main.reconcile_once(cfg)            # heals torn-down cables/links (idempotent)
        apps.route_once(cfg, moved)         # auto-assign any newly-appeared app streams

if __name__ == "__main__":
    sys.exit(run_daemon())
