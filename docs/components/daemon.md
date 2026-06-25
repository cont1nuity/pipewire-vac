# Daemon & lifecycle

The long-lived process and its bootstrap: preflight checks, a single-instance lock, the initial
reconcile, spawning the tray, and the event-driven loop that drives self-heal + app routing. Plus
the path-resolution that lets every module run from any working directory or an AppImage.

**Modules:** `src/daemon.py` `src/firstrun.py` `src/paths.py`

## The event-driven loop (`daemon.py`)

`run_daemon(config_arg=None)`: `firstrun.preflight` → `single_instance()` lock → load config →
initial `main.reconcile_once(cfg)` → `apps.route_once(cfg, moved)` → spawn tray. Then, if
`features.self_heal` is **off**, `signal.pause()` (idle, holding the lock); otherwise start the
`_monitor` thread and loop: `dirty.wait(SAFETY_POLL)` → (on an event, `time.sleep(DEBOUNCE)` to
coalesce a burst) → reload-or-keep config → `reconcile_once` → `route_once`. The daemon owns the
`moved = {}` app-routing ledger for its lifetime (see [app-routing.md](app-routing.md)).

**Why event-driven, not a timer poll.** The reconcile is triggered by **one persistent
`pactl subscribe`** (a single PulseAudio client for the daemon's life), not a per-tick subprocess.
The old 2s poll spawned short-lived `pactl`/`pw-link` clients *every tick*, and WirePlumber 0.5.x
**leaks a GWeakRef per short-lived client connect** — sustained churn exhausts GLib's ceiling in
~8h and wedges the whole audio session. `_monitor` reads the subscribe stream and `_interesting()`
sets `dirty` only on **sink/source new+remove** (a cable, the `auto` physical target, or a mic
changed) and a **new sink-input** (a stream to auto-route). It deliberately ignores
`client`/`source-output`/`module`/`card` churn and `change` (volume/mute) events — the
short-lived-client storm that *is* the leak, plus the lower-level PipeWire Node/Link chatter that
`pw-mon` would surface (capture taps, transient links), never reaches the Pulse abstraction. So
**steady state spawns zero short-lived clients.** `SAFETY_POLL` (60s) is the only timed fallback:
a missed event, a dead subscribe, or the rare pure `pw-link` teardown that has no Pulse event
(sink-level teardown *does* fire an event and heals immediately). reconcile is idempotent +
create-if-missing, so a self-triggered pass (our own `pw-link` → no event anyway) converges at
once. `_monitor` respawns `pactl subscribe` if it dies; if `pactl` is unavailable the `SAFETY_POLL`
still heals, just slower.

## Single-instance lock

`single_instance()` takes an exclusive `flock` on `$XDG_RUNTIME_DIR/pipewire-vac.lock` and
writes its pid in. The kernel drops the lock on **any** exit (including SIGKILL); a second
instance fails the non-blocking lock and exits with the running pid. Keep the returned fd open
for the process lifetime.

## Live config reload (`_load_or_keep`)

Each reconcile (event-triggered or the safety poll) reloads the config; on a missing/unparseable
file it keeps the last-good one (logs to stderr) instead of crashing mid-edit. This is what makes
editor saves apply live with **no restart** — the next reconcile reads the new structure (within
`SAFETY_POLL` even if no graph event intervenes).

## Tray spawn (`_spawn_tray`)

Best-effort `subprocess.Popen` of `tray.py` with `--pid/--config/--version`; skipped when there's
no `DBUS_SESSION_BUS_ADDRESS` (headless). The tray is garnish — a failed spawn never takes the
daemon down (see [ui.md](ui.md)); it dies with the daemon via PDEATHSIG.

## Preflight (`firstrun.py`)

`preflight(config_arg)` runs three bootstrap checks, each a silent success or a hard exit with an
exact stderr message (systemd journals them — no GUI prompts): `_check_tools()` (require `pactl`,
`pw-link`), `_wait_for_pipewire()` (poll `pactl info` with retries), and
`_ensure_config()` (seed `$XDG_CONFIG/config.toml` from `config.example.toml` on first run —
**never** overwrites an existing config). Returns the resolved config path.

## Paths (`paths.py`)

The single source of truth for filesystem locations (stdlib `os` only) so nothing else hardcodes
a path. `PACKAGED` is true when the AppImage runtime set `APPDIR` **or** `ROOT` isn't writable
(read-only squashfs). `config_path()` prefers a repo-local `config.toml` (dev) and falls back to
`$XDG_CONFIG/config.toml` (packaged).

See also: [routing-engine.md](routing-engine.md), [ui.md](ui.md), [app-routing.md](app-routing.md)
