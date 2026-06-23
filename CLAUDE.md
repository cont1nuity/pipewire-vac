# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A config-driven, self-healing Python app ("PipeWire VAC") that builds VoiceMeeter/VAC-style
virtual audio routing on PipeWire (TOML cables → reconciler → tray + editor → AppImage). It
started as a single Bash script and was rewritten; the only runtime dep is `dbus-next` (tray),
plus the PipeWire CLI tools it shells out to (`pactl`, `pw-link`, `wpctl`).

## Active direction

The bash script has been rewritten into a config-driven, self-healing Python app (TOML cables
→ reconciler → tray + editor → AppImage). **All of Phases 1–4 are built.** The routing model is
structure-only; the component docs under `docs/components/` are the authority for cables and
app routing.

**Component docs** — `docs/components/` describes *what each component does and its invariants*
(the "what/how"), grouped by component, not per file. Start at
**`docs/components/README.md`** (the component map + shared concepts) and read the relevant leaf
before changing a component. This CLAUDE.md is the overview. When a component's behavior
changes, revise its doc as a full revision in the same commit.

**What's built (all phases) — per-component detail in `docs/components/`:**

- **Routing engine** — TOML-driven, surgical (create-if-missing) cable reconcile; the daemon
  polls `reconcile_once` every 2s so a torn-down cable heals within ~2s. Structure-only: create /
  link (shared channels only, no downmix) / unmute-once; never volume, default, or mic. The one
  teardown is unloading a null-sink it created once that cable leaves the config (ledger-tracked);
  it never removes links or sinks it didn't make. → [`routing-engine.md`](docs/components/routing-engine.md),
  [`daemon.md`](docs/components/daemon.md).
- **App auto-assignment** — optional `[[app]]` rules move a matching app's stream into a cable,
  move-once then hands off, with `browser`/`game`/`media`/`voice` aliases + a `default`
  catch-all. → [`app-routing.md`](docs/components/app-routing.md).
- **UI** — a `StatusNotifierItem` tray (dbus-next) + a row-based Tk config editor, both optional
  processes the daemon spawns. → [`ui.md`](docs/components/ui.md).
- **Packaging** — a single AppImage (relocatable CPython + dbus-next + Tcl/Tk + `src/`),
  `VERSION` stamped at build. → [`packaging.md`](docs/components/packaging.md).

`qpwgraph` and a `daemonctl.py` restart layer were **dropped** — the daemon re-reads config
every poll, so no restart is needed.

**Deployment (current):** the **AppImage** is the live system, launched at login by an XDG
autostart entry (`~/.config/autostart/pipewire-vac.desktop`, created via the tray's "Start at
login"; KDE+systemd runs it as `app-pipewire-vac@autostart.service`). Its daemon owns the
cables and spawns the tray. **No systemd service of our own** — the autostart entry launches
the AppImage daemon directly. (An orphaned copy of the retired bash script sits at
`~/.config/pipewire/virtual-cables.sh`, run by nothing.)

**Why polling, not events:** an event-driven (`pw-dump --monitor`) build was written and
hardware-tested first; it needed a thread + a fixed-window debounce *just* to avoid a
reconcile storm (live audio keeps the graph chattering, so a "wait for a quiet gap"
debounce starves). All that machinery bought ~200ms heal vs ~2s. Not worth it — the poll
loop is half the code. Upgrade path (`pw-dump --monitor`) is noted in `daemon.py` if
sub-second heal is ever needed.

## Routing topology

Config-driven now (each cable's `target` derives the links). The default `config.example.toml`
ships the classic shape — Game/Voice/Media → Master → physical — but it's just data:

```
Game / Voice / Media   (cables, target = "Master")
        │  monitor_<ch>  →  Master:playback_<ch>   (pw-link, matching channels only)
        ▼
Master                 (cable, target = "auto" → first hardware output)
        │  monitor_<ch>  →  alsa_output.…:playback_<ch>
        ▼
alsa_output.pci-0000_6c_00.6.analog-stereo  (physical headset)
```

## Running / testing a change

**Python app (Phase 1):** logic is unit-tested offline; final wiring is verified on hardware.

```bash
.venv/bin/pytest                    # 54 tests; pure config/routing/state/apps logic, no hardware
python3 src/main.py --selftest      # offline reconcile self-check, touches no hardware
cp config.example.toml config.toml  # dev config (gitignored); edit cable targets if needed
./start.sh                          # apply to the live graph (idempotent, create-if-missing)
pactl list short sinks              # expect Game, Voice, Media, Master + physical sink
qpwgraph                            # visual check of the pw-link graph
```

**Bash script (retired):** the original `virtual-cables.sh` system was replaced by the Python
AppImage (see Deployment). The script file is no longer in the repo. An orphaned copy at
`~/.config/pipewire/virtual-cables.sh` runs nothing.

## Constraints that bite if ignored

The load-bearing PipeWire invariants live with the code and its history — see
[`routing-engine.md`](docs/components/routing-engine.md) ("the pwgraph chokepoint"). The
essentials:

- **Match sinks by name, never module ID** (IDs change every boot); **always pass
  `channel_map=`** (without it sinks are mono and the `monitor_FL`/`playback_FR` ports don't
  exist, so `pw-link` fails with "port not found").
- **Structure-only.** The app creates/links/unmutes-once and **never** pins the default sink,
  sets volume, or touches the mic. It does **not** tear down links or sinks it didn't make; the
  sole teardown is unloading a null-sink it created once that cable is removed from config
  (`(snap ∩ initialized) − desired`, then dropped from the ledger). The old bash "sanity-reset"
  (unmute/volume/pin-defaults) was deliberately **removed** — don't reintroduce it.
- A cable's `target` resolves `"auto"` to the first physical output; on new hardware rediscover
  sinks/sources with `pactl list short sinks` / `sources`.
