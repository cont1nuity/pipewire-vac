# UI (tray + editor)

Two **separate, optional** GUI processes the daemon launches. Both are garnish — the daemon
routes audio fine without either, and each fails gracefully (no session bus, no Tk) without
affecting it.

**Modules:** `src/tray.py` `src/configui.py`

## Tray (`tray.py`)

A `org.kde.StatusNotifierItem` + `com.canonical.dbusmenu` icon over **dbus-next** (pure-Python,
the only runtime dependency — no Qt/GTK, so it works on any SNI host and keeps the AppImage
small). Two D-Bus objects: `Sni` at `/StatusNotifierItem` and `Menu` at `/MenuBar`; it registers
with `org.kde.StatusNotifierWatcher`, then polls the daemon pid every ~2s and exits if it dies.

**Menu:** *version (disabled) / Settings… / Edit config file / Start at login (checkbox) / Quit*.
Left-click (`Activate`) opens Settings via `open_config_ui()` (launches [configui](#config-editor-configuipy);
falls back to raw TOML if Tk is missing). "Start at login" toggles the XDG autostart entry;
"Quit" stops the daemon.

**Icon:** the custom audio-routing graphic `packaging/pipewire-vac.png` is embedded as an
`IconPixmap` — `_png_to_argb` decodes the PNG to ARGB with a tiny stdlib decoder (no Pillow, all
five scanline filters) and the item serves `IconName=""` so the host draws the pixmap directly.
A *named* theme icon was tried first; **Plasma wouldn't resolve a custom name** (blank tray),
hence the pixmap. Falls back to themed `audio-headphones` only if the PNG is missing/undecodable.

**Lifecycle:** args `--pid` (daemon to watch) / `--config` / `--version`. An `ImportError` on
dbus-next or a missing session bus is caught → prints to stderr, exits 0. Dies with the daemon
via `PR_SET_PDEATHSIG`.

## Config editor (`configui.py`)

A row-based Tk settings editor with two sections, mirroring each other (add / remove / ✕):

- **Cables** — output cables: Name, Channels (readonly combobox), Target (editable combobox of
  `(no output)` = `""` + `auto` + physical sinks + cable names). `(no output)` makes a capture-only
  record/stream **bus** that other cables route into and a recorder captures.
- **Microphones** — virtual mics, i.e. a cable with a `sources` entry: Name, Channels, Source
  (a capture device), Target (same options; `(no output)` is the capture-only default). Apps
  capture the cable's monitor; Target optionally *also* sends it to an output. Cables are split
  into these two sections by whether they have `sources`.
- All **device dropdowns** show friendly descriptions with a `(physical)` suffix (via
  `pwgraph.sink_labels` / `source_labels`) but **store the stable node name** (or `auto`/`""`).
  Duplicate descriptions are disambiguated with the node name; a `sources` list of 2+ mics shows
  read-only as `(multiple — edit in TOML)` and is preserved verbatim. The label↔name and
  source/target mappings are pure module functions (`target_display`/`target_store`/`mic_display`/
  `mic_to_sources`), unit-tested without Tk.
- **App routing** — one row per `[[app]]` rule: Match (editable combobox seeded with the four
  aliases + `default` — that's the hint), Target (editable combobox of cables + physical sinks,
  no `auto`). See [app-routing.md](app-routing.md).

`save()` collects the rows, runs `config._validate`, and `dump_config()` regenerates
`config.toml` (comments dropped); the daemon applies the new structure on its next poll. The
editor makes **no graph-mutating** calls — only read-only `pwgraph.sink_labels` (Target
dropdowns) and `pwgraph.source_labels` (Source picker) queries. It's importable without Tk so
`dump_config` and the mapping helpers stay unit-testable. Launched by the tray's Settings… or directly (`python src/configui.py`).

See also: [daemon.md](daemon.md), [routing-engine.md](routing-engine.md), [app-routing.md](app-routing.md)
