# PipeWire VAC

VoiceMeeter / Virtual-Audio-Cable-style routing for **PipeWire** on Linux — defined in a small
TOML file and kept alive by a self-healing daemon.

Declare a few virtual cables, say where each one's audio should go, and the app builds the graph:
null sinks your apps can play into, linked through to your headset. It **only** manages that
structure — it never touches your volume, your default device, or your microphone gain. Those stay
yours (and WirePlumber's / pavucontrol's).

```
Game / Voice / Media   (cables, target = "Master")
        │  monitor_<ch>  →  Master:playback_<ch>   (matching channels only, no downmix)
        ▼
Master                 (cable, target = "auto" → first hardware output)
        │  monitor_<ch>  →  alsa_output.…:playback_<ch>
        ▼
your headset / speakers (physical sink)
```

That shape is just the default config — it's all data. Point cables at each other or at any physical
sink to build whatever bus layout you want.

## Features

- **Virtual cables** — each is a null sink apps can select in pavucontrol. Chain them
  (`target = "Master"`) or send them straight to hardware (`target = "auto"`).
- **Virtual microphone** — wire a hardware mic *into* a cable (`sources = ["auto"]`); the cable's
  monitor becomes a mic many apps can select at once, leaving your real mic default untouched. A
  mono mic fans out to stereo.
- **Record / stream buses** — a cable with no target (`target = ""`) is a capture-only bus other
  cables route into, for OBS or a recorder.
- **App auto-routing** *(optional)* — `[[app]]` rules move a matching app's stream into a cable
  once on each launch (`browser`/`game`/`media`/`voice` aliases + a `default` catch-all), then your
  manual moves stick.
- **Self-healing** — the daemon re-reads the config and reconciles the graph every ~2s, so a
  cable torn down by a device hiccup heals within a couple of seconds. No restart, no service.
- **Tray + settings editor** — an optional `StatusNotifierItem` tray and a row-based config editor.
- **Single AppImage** — bundles CPython + dbus-next + the app; the target host needs only the
  PipeWire CLI tools every PipeWire system already ships.

## Requirements

- A running **PipeWire** stack with its CLI tools: `pactl`, `pw-link`, `pw-dump` (and `wpctl`).
- **Python 3.11+** (for stdlib `tomllib`) when running from source.
- **`dbus-next`** — the only third-party Python dependency, and only for the tray.

The AppImage bundles Python and `dbus-next`, so it needs none of the above except the PipeWire CLI.

## Install & run

**From source:**

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp config.example.toml config.toml      # edit cable targets to taste
./start.sh                              # reconcile the live graph once (idempotent), then exit
./start.sh --daemon                     # stay running and self-heal
```

On first run with no `--config`, a config is seeded at `~/.config/pipewire-vac/config.toml`.

**AppImage:**

```bash
packaging/build-appimage.sh             # → dist/PipeWire-VAC-<version>-x86_64.AppImage
```

Launch it once; use the tray's **"Start at login"** to add the XDG autostart entry. From then on the
AppImage daemon owns your cables and spawns the tray at login.

## Configuration

Everything lives in one TOML file — see **[`config.example.toml`](config.example.toml)** for the
full annotated reference. The essentials:

```toml
[[cable]]
name     = "Game"        # shown in pavucontrol; apps target this
channels = "stereo"      # mono | stereo | 2.1 | 5.1 | 7.1
target   = "Master"      # another cable, a physical sink name, "auto", or "" (no output)

[[cable]]
name    = "VoiceMix"
sources = ["auto"]       # wire a hardware mic in → this cable's monitor is now a virtual mic

[[app]]
match  = "media"         # alias, a "discord|mumble" name fragment, or "default"
target = "Media"

[features]
self_heal = true         # false = reconcile once at login, then idle
```

## How it works

The app is **structure-only and surgical**. Each poll it reconciles the live graph toward the
config: it *creates* missing cables, *links* only the channels both ends share, and *unmutes* each
cable exactly once (tracked in a small state ledger, so it never re-clears a mute you set). It does
**not** set volume, pin the default sink/source, or touch your mic. The single teardown it performs
is unloading a null sink it created, once that cable leaves the config.

Polling (not events) is deliberate: an event-driven build needed a thread plus a debounce just to
survive the constant graph chatter of live audio, for ~200ms-vs-2s faster healing. Not worth half
the code. See [`docs/components/daemon.md`](docs/components/daemon.md) for the upgrade path.

## Development

```bash
.venv/bin/pytest                # offline unit tests (config / routing / state / apps), no hardware
python3 src/main.py --selftest  # offline reconcile self-check, touches no hardware
```

Component docs live under **[`docs/components/`](docs/components/README.md)** — what each part does
and its invariants.

## License

[GPL-3.0](LICENSE) © cont1nuity
