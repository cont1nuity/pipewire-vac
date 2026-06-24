# Routing engine

The core: load the TOML config, compute the desired PipeWire graph, apply it surgically
(create-if-missing; the only teardown is unloading a cable removed from config), and track a
one-time unmute. This is the cable half of the system; app routing builds on the same `pwgraph`
primitives (see [app-routing.md](app-routing.md)).

**Modules:** `src/config.py` `src/routing.py` `src/pwgraph.py` `src/state.py` `src/main.py`

## Config (`config.py`)

Loads and validates the schema-v2 TOML. `load(path)` merges `DEFAULTS`
(`config_version`, `cable=[]`, `app=[]`, `features.self_heal=True`) over the file, applies
`_CABLE_DEFAULTS` (`channels="stereo"`, `target="auto"`) per cable, then `_validate`.

A `[[cable]]` is `name` / `channels` (mono | stereo | 2.1 | 5.1 | 7.1) / `target` (another
cable, a physical sink, `"auto"` → first physical output, or `""` → no output) / optional
`sources` (hardware capture devices wired **into** the cable — its monitor becomes a virtual
mic). A cable with `sources` and no explicit `target` defaults to `""` (a capture-only mic
shouldn't echo to an output); set a target to *also* send it somewhere. Validation rejects:
missing or duplicate cable names, unknown channel layouts, a cable targeting itself, `sources`
that isn't a list, and target **cycles** (`_check_cycles` walks cable→cable targets;
hardware/`auto`/`""` are leaves). `[[app]]` rules are validated here too (non-empty `match` +
`target`) — see [app-routing.md](app-routing.md).

## Graph discovery & actions (`pwgraph.py`)

The sole PipeWire chokepoint (see [README](README.md#the-pwgraph-chokepoint)). Reads:
`list_sinks()`, `first_physical_sink(sinks, our)` / `first_physical_source()` (resolve `"auto"`
for a target / a `sources` entry; prefer `alsa_output.`/`alsa_input.` etc., exclude our cables +
`.monitor`), `snapshot(our)`, `source_ports(names)` (one `pw-link -o` → each capture source's
live port suffixes, for virtual-mic links), and `sink_labels(our)` / `source_labels()` (friendly
device descriptions for the settings UI dropdowns).
`snapshot(our)` returns `{"sinks", "ok"}` — `ok` is false when the `pactl` sink listing failed
(non-zero exit or timeout). That flag is load-bearing: an empty/failed listing makes every cable
look missing, and creating on it re-loads a duplicate `module-null-sink` each poll — leaked
modules that bloat the graph until the whole audio server wedges (the modules live in
pipewire-pulse, so only a `systemctl restart` clears them). `run()` therefore wraps every call
with a **5 s timeout**, returning rc=124 on a hang so a wedged `pactl`/`pw-link` is treated as a
failed read rather than freezing the 2 s heal loop forever.
Actions (all via `run()`): `create_null_sink(name, description, channel_map)`,
`set_sink_mute(name, on)`, `link(out_port, in_port)` (idempotent — `pw-link` ignores dup/missing
ports), `unload_null_sink(name)` (finds the owning module via `pactl list modules` and unloads
it — the one teardown). `list_sink_inputs()` and `move_sink_input()` exist for app routing.

## Desired state & reconcile (`routing.py`)

Pure computation — **no PipeWire calls**, so it unit-tests offline. `LAYOUTS` maps each channel
name to its channel-map string; `SUFFIX` maps channels to PipeWire port suffixes (`FL`, `FR`,
`FC`, `LFE`, `RL`, `RR`, `SL`, `SR`, `MONO`).

- `desired_state(cfg, physical_auto)` → `{"sinks": [...], "links": [...]}`. For each cable it
  emits one sink and, for its target, one link **per channel both ends share** (`monitor_<suf>`
  → `target:playback_<suf>`). Mismatched layouts carry only the shared channels — **no downmix**.
  For each `sources` entry it emits a capture→cable link (`_source_links`), using the source's
  **live-detected** capture ports (`source_ports`, passed in like `physical_auto`): a stereo mic
  links channel-for-channel; a single-port mono mic **fans out** to front L/R on a stereo+ cable
  (the lone exception to "shared channels only"). A `sources` entry of `"auto"` resolves to
  `physical_source_auto` (first physical mic, also passed in). An absent source (no ports yet, or
  `"auto"` with no mic) emits nothing and heals on a later poll. Source links are additive — never
  set the default source or mic gain (structure-only).
- `reconcile(desired, snap, initialized)` → action list. Create a sink only if missing; emit
  `("unmute", name)` only when the name is **not** in `initialized` (set-once); always emit the
  links (fire-and-forget). It also emits `("unload", name)` for each cable in
  `(snap ∩ initialized) − desired` — a null-sink **we** created (present + ledger-tracked) that
  the user removed from config. Sinks we didn't make (not in `initialized`) are never touched.
- `apply(actions, pw)` dispatches `create_sink` / `unmute` / `link` / `unload` to `pwgraph`.
  `reconcile_once` then `state.drop`s the unloaded names so a re-add unmutes once again.

## One-time unmute ledger (`state.py`)

`~/.local/state/pipewire-vac/state.json` — `{"initialized": ["Game", "Master", ...]}`.
`load()` returns the set (empty on missing/corrupt); `mark(names)` unions and persists;
`drop(names)` removes them (a cable torn down because it left the config). This is what makes
unmute **set-once**: a recreated cable (pipewire restart, self-heal) is never re-unmuted, so a
cable the user muted on purpose stays muted. The ledger is also the "did we create this?" signal
the teardown uses — only a sink whose name is in it gets unloaded when it leaves the config.

## Orchestration (`main.py`)

`reconcile_once(cfg)` runs one full pass: `our = cable names` → `snapshot` → **bail if
`snap["ok"]` is false** (a blind read; skip rather than re-create — see `pwgraph.py` above) →
resolve `physical_auto` → load the `initialized` ledger → `desired_state` → `reconcile` → `apply` →
`state.mark(all cable names)`; returns `{"cables", "created"}`. `mark` records **every** cable
that should exist (not just new ones), so a later recreation won't re-unmute. `main` also holds
`VERSION` (stamped at build) and the CLI: `--selftest` (offline reconcile self-check, touches no
hardware) and `--daemon` (hands off to [daemon.md](daemon.md)).

See also: [app-routing.md](app-routing.md), [daemon.md](daemon.md)
