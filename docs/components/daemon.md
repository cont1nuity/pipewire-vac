# Daemon & lifecycle

The long-lived process and its bootstrap: preflight checks, a single-instance lock, the initial
reconcile, spawning the tray, and the poll loop that drives self-heal + app routing. Plus the
path-resolution that lets every module run from any working directory or an AppImage.

**Modules:** `src/daemon.py` `src/firstrun.py` `src/paths.py`

## The poll loop (`daemon.py`)

`run_daemon(config_arg=None)`: `firstrun.preflight` → `single_instance()` lock → load config →
initial `main.reconcile_once(cfg)` → `apps.route_once(cfg, moved)` → spawn tray. Then, if
`features.self_heal` is **off**, `signal.pause()` (idle, holding the lock); otherwise loop every
`POLL` (2s): reload-or-keep config, `reconcile_once`, `route_once`. The daemon owns the
`moved = {}` app-routing ledger for its lifetime (see [app-routing.md](app-routing.md)).

**No threads, no event monitor, no `pw-dump`** — reconcile is idempotent, so re-running it on a
timer *is* the self-heal. A torn-down cable is rebuilt within ~2s. (Upgrade path to
`pw-dump --monitor` for sub-second heal is noted in the code; deliberately not taken.)

## Single-instance lock

`single_instance()` takes an exclusive `flock` on `$XDG_RUNTIME_DIR/pipewire-vac.lock` and
writes its pid in. The kernel drops the lock on **any** exit (including SIGKILL); a second
instance fails the non-blocking lock and exits with the running pid. Keep the returned fd open
for the process lifetime.

## Live config reload (`_load_or_keep`)

Each poll reloads the config; on a missing/unparseable file it keeps the last-good one (logs to
stderr) instead of crashing mid-edit. This is what makes editor saves apply live with **no
restart** — the next poll just reads the new structure.

## Tray spawn (`_spawn_tray`)

Best-effort `subprocess.Popen` of `tray.py` with `--pid/--config/--version`; skipped when there's
no `DBUS_SESSION_BUS_ADDRESS` (headless). The tray is garnish — a failed spawn never takes the
daemon down (see [ui.md](ui.md)); it dies with the daemon via PDEATHSIG.

## Preflight (`firstrun.py`)

`preflight(config_arg)` runs three bootstrap checks, each a silent success or a hard exit with an
exact stderr message (systemd journals them — no GUI prompts): `_check_tools()` (require `pactl`,
`pw-link`, `pw-dump`), `_wait_for_pipewire()` (poll `pactl info` with retries), and
`_ensure_config()` (seed `$XDG_CONFIG/config.toml` from `config.example.toml` on first run —
**never** overwrites an existing config). Returns the resolved config path.

## Paths (`paths.py`)

The single source of truth for filesystem locations (stdlib `os` only) so nothing else hardcodes
a path. `PACKAGED` is true when the AppImage runtime set `APPDIR` **or** `ROOT` isn't writable
(read-only squashfs); when packaged, `LOGS` moves to `XDG_STATE`. `config_path()` prefers a
repo-local `config.toml` (dev) and falls back to `$XDG_CONFIG/config.toml` (packaged).

See also: [routing-engine.md](routing-engine.md), [ui.md](ui.md), [app-routing.md](app-routing.md)
