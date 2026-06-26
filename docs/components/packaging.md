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
3. **`pip install dbus-next` + `certifi`** into the bundled interpreter (manylinux wheel →
   self-contained; certifi ships the CA roots the update check's HTTPS needs — see gotchas).
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
- **Export `SSL_CERT_FILE`** (→ the bundled `certifi/cacert.pem`, located relative to `APPDIR`) —
  the bundled manylinux CPython's OpenSSL looks for certs at its build path (`/opt/_internal/…`),
  absent on the target, so the tray's HTTPS update check (`latest_release_version`, a `urllib` HEAD
  to GitHub) otherwise fails `CERTIFICATE_VERIFY_FAILED` every poll and the update notice never
  fires. zsync2/AppImageUpdate brings its own CA discovery, so the *manual* "Check for updates…"
  click still worked — only the *automatic* Python check was broken. We **bundle `certifi`** (step 3)
  rather than probe the host store, so the AppImage stays self-contained on any distro; an existing
  `SSL_CERT_FILE` still wins (corporate TLS-inspecting proxies whose root isn't in the Mozilla store).

## Deliberately minimal

A minimal bundle — **no** libusb, **no** fonts, **no** Pillow
(the tray decodes its PNG with a stdlib decoder — see [ui.md](ui.md)). Tcl/Tk ships in the
python-appimage bundle (the editor falls back to raw-TOML editing if absent). Build host needs
`rsvg-convert` to pre-render the SVG → PNG at build time so the runtime doesn't.

## Auto-update & releases

`build-appimage.sh` packs the AppImage with embedded **update-information**
(`gh-releases-zsync|cont1nuity|pipewire-vac|latest|PipeWire-VAC-*-x86_64.AppImage.zsync`) and, when
`zsync` (apt) is on PATH, emits the matching `.zsync` next to the AppImage (appimagetool runs from
`$DIST` so both land together). A tagged push (`v*`) runs `.github/workflows/release.yml`: it builds
on `ubuntu-22.04`, composes release notes from the matching `CHANGELOG.md` section
(`packaging/changelog-section.sh`), and creates/updates the GitHub release with the AppImage +
`.zsync`. The tray then updates in place (see [ui.md](ui.md)): via AppImageUpdate's zsync delta if
that tool is installed, else by a pure-Python full-asset download + atomic swap. The embedded
update-info and `.zsync` are only used by the AppImageUpdate path — the pure-Python fallback ignores
them and just pulls the whole `*.AppImage` from the release. We deliberately **don't bundle**
appimageupdatetool: its self-contained build is ~35 MB (dynamically linked against a large
libappimageupdate/icu/rsvg/zsync closure), which would ~triple the deliverable to buy zsync deltas
the pure-Python path doesn't need — the safety-critical step (atomic rename of the running image) is
identical either way.

See also: [ui.md](ui.md), [daemon.md](daemon.md)
