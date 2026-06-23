# src/daemon.py — long-lived self-healing reconciler.
# Polls the graph on a fixed interval and re-reconciles. Dead simple: no event
# monitor, no threads, no pw-dump — a torn-down cable is rebuilt within POLL seconds.
import os, sys, time, signal, fcntl, tempfile, subprocess
import config, firstrun, main, apps

POLL = 2.0   # seconds between reconciles == the heal-latency ceiling. Raise to idle quieter.

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

    while True:                       # ponytail: poll, not event-driven. reconcile is
        time.sleep(POLL)              #   idempotent, so re-running it every POLL self-heals.
        cfg = _load_or_keep(cfgpath, cfg)   # pick up config edits live; keep last-good on error
        main.reconcile_once(cfg)            # Upgrade path: pw-dump --monitor for sub-second heal.
        apps.route_once(cfg, moved)         # auto-assign any newly-appeared app streams

if __name__ == "__main__":
    sys.exit(run_daemon())
