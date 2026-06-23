# Packaging

Builds a single-file **AppImage** — relocatable CPython + dbus-next + Tcl/Tk + `src/` — so the
user downloads and runs one file with no Python install on the target (only the PipeWire CLI
tools it shells out to, plus the udev-free PipeWire stack). Output:
`dist/PipeWire-VAC-<VERSION>-x86_64.AppImage`.

**Modules:** `packaging/build-appimage.sh` (+ assets `pipewire-vac.svg` / `.png`)

## Recipe (ordered)

1. **Fetch toolchain** — `python-appimage` (manylinux relocatable CPython) + `appimagetool`,
   cached under `build/cache/` so rebuilds run offline.
2. **Extract** the Python AppImage to `AppDir/` (`--appimage-extract`, no FUSE).
3. **`pip install dbus-next`** into the bundled interpreter (manylinux wheel → self-contained).
4. **Copy payload** — `src/`, `config.example.toml`, `pipewire-vac.png` into
   `AppDir/opt/pipewire-vac/`; **sed-stamp `VERSION`** into the bundled `src/main.py`.
5. **Write `AppRun`** (see gotchas).
6. **Desktop + icon** — one `.desktop` and one icon at the AppDir root (stray `python*.png/svg`
   and `usr/share/applications/` are removed to avoid conflicts).
7. **Pack** with `appimagetool`.

## VERSION stamping

Default `git describe --tags --dirty` (else `"dev"`); overridable as
`packaging/build-appimage.sh [VERSION]`. The mechanism is a `sed` in-place replacement of the
`VERSION = "..."` line in the bundled `main.py` before packing — surfaced by `--version` and in
the tray.

## AppRun gotchas

Three things, each of which cost a debugging session:

- **Exec the real Python ELF under `opt/`, not python-appimage's `usr/bin/python3.x`** — that's
  a bash wrapper that calls python *without* `exec`, so it lingers as a second process.
- **Export `APPDIR`** so `paths.PACKAGED` trips and the app reads `~/.config` / writes
  `~/.local/state` instead of the read-only mount.
- **Re-export `TCL_LIBRARY` / `TK_LIBRARY`** (the files are already bundled) so the Tk config
  editor works; AppRun replaces python-appimage's, which set them. AppRun execs `main.py --daemon`.

## Deliberately minimal

A minimal bundle — **no** libusb, **no** fonts, **no** Pillow
(the tray decodes its PNG with a stdlib decoder — see [ui.md](ui.md)). Tcl/Tk ships in the
python-appimage bundle (the editor falls back to raw-TOML editing if absent). Build host needs
`rsvg-convert` to pre-render the SVG → PNG at build time so the runtime doesn't.

See also: [ui.md](ui.md), [daemon.md](daemon.md)
