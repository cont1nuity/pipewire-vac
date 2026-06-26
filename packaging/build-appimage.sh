#!/bin/bash
# Build the PipeWire VAC AppImage.
#
# Self-contained result: a relocatable CPython (python-appimage manylinux build) + dbus-next
# (the tray) + the runtime payload (src/, config.example.toml). The target host needs NO
# python install — only the PipeWire CLI tools (pactl, pw-link), which every
# PipeWire system already ships.
#
# Deliberately minimal: NO USB/libusb, NO fonts, NO Tcl/Tk (we ship no Tkinter editor),
# NO Pillow (the tray uses a themed audio-headphones IconName, so nothing is rendered into
# the bundle but the .desktop icon).
#
# Build-host needs: bash, curl, rsvg-convert (icon pre-render; build time only).
# Downloads are cached in build/cache/ so repeat builds run offline.
#
# Usage:   packaging/build-appimage.sh [VERSION]
#          default VERSION: `git describe --tags --dirty`, else "dev". CI on a tag gets the tag.
#          VERSION is stamped into the payload (src/main.py: shown by --version and in the tray).
# Output:  dist/PipeWire-VAC-<VERSION>-x86_64.AppImage
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="${1:-${VERSION:-}}"
[ -n "$VERSION" ] || VERSION=$(git -C "$ROOT" describe --tags --dirty 2>/dev/null || echo dev)
ARCH=x86_64
PYTAG=python3.12                  # 3.11+ for stdlib tomllib
BUILD="$ROOT/build/appimage"; CACHE="$ROOT/build/cache"; DIST="$ROOT/dist"
APPDIR="$BUILD/AppDir"
mkdir -p "$BUILD" "$CACHE" "$DIST"; rm -rf "$APPDIR"

fetch() {  # fetch <url> <dest> — cached
    [ -f "$2" ] && return 0
    echo ">> fetching $(basename "$2")"
    curl -fL --retry 3 -o "$2.part" "$1" && mv "$2.part" "$2"
}

# 1) toolchain: python-appimage (relocatable manylinux CPython) + appimagetool
REL_JSON=$(curl -fsSL "https://api.github.com/repos/niess/python-appimage/releases/tags/$PYTAG")
PY_URL=$(printf '%s' "$REL_JSON" \
         | grep -o "\"browser_download_url\": *\"[^\"]*manylinux2014_$ARCH\.AppImage\"" \
         | awk -F'"' 'NR==1{print $4}')
[ -n "$PY_URL" ] || { echo "ERROR: no manylinux2014 $PYTAG asset on python-appimage"; exit 1; }
PY_AI="$CACHE/$(basename "$PY_URL")"; fetch "$PY_URL" "$PY_AI"
AIT="$CACHE/appimagetool-$ARCH.AppImage"
fetch "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-$ARCH.AppImage" "$AIT"
chmod +x "$PY_AI" "$AIT"

# 2) unpack the python AppImage -> AppDir (--appimage-extract needs no FUSE)
(cd "$BUILD" && "$PY_AI" --appimage-extract >/dev/null)
mv "$BUILD/squashfs-root" "$APPDIR"
PY="$(find "$APPDIR/usr/bin" -name 'python3.[0-9]*' | sort | head -1)"
[ -x "$PY" ] || { echo "ERROR: bundled python not found in AppDir"; exit 1; }
echo ">> bundled interpreter: $("$PY" --version)"

# 3) python deps into the bundle (manylinux wheel — self-contained)
"$PY" -m pip install --quiet --upgrade pip
"$PY" -m pip install --quiet dbus-next       # the tray (StatusNotifierItem)
"$PY" -m pip install --quiet certifi         # bundled CA roots (Mozilla store) for the HTTPS update check
"$PY" -c "import tkinter" 2>/dev/null \
    && echo ">> tkinter import OK in bundle (settings editor enabled)" \
    || echo ">> WARNING: tkinter not importable — settings UI will fall back to raw editing"

# 4) runtime payload
PAY="$APPDIR/opt/pipewire-vac"; mkdir -p "$PAY"
cp -r "$ROOT/src" "$PAY/src"
find "$PAY/src" -name __pycache__ -type d -prune -exec rm -rf {} +
sed -i "s/^VERSION = .*/VERSION = \"$VERSION\"/" "$PAY/src/main.py"   # --version + tray show this
cp "$ROOT/config.example.toml" "$PAY/"
cp "$ROOT/packaging/pipewire-vac.png" "$PAY/"   # tray decodes this into its IconPixmap
[ -f "$ROOT/LICENSE" ] && cp "$ROOT/LICENSE" "$PAY/" || true

# 5) AppRun: exec the bundled interpreter's REAL ELF directly. python-appimage's
#    usr/bin/python3.* is a bash WRAPPER (calls python without exec) — exec'ing it would
#    leave the wrapper alive (two processes for one daemon). APPDIR is exported so
#    paths.PACKAGED trips.
PYELF=$(find "$APPDIR/opt" -path '*/bin/python3.[0-9]*' -type f | awk 'NR==1')
[ -x "$PYELF" ] || { echo "ERROR: bundled python ELF not found under opt/"; exit 1; }
PYREL="${PYELF#"$APPDIR"/}"
# Tcl/Tk script libraries: Tk() (the settings editor, src/configui.py) needs them. The
# python-appimage bundle ships them; locate them relative to APPDIR and re-export, so the
# GUI works and gracefully falls back to raw editing if a layout change ever drops them.
TCL_EXPORTS=""
_initcl=$(find "$APPDIR/usr/share" "$APPDIR/usr/lib" -name init.tcl -path '*tcl8*' 2>/dev/null | awk 'NR==1' || true)
_tktcl=$(find "$APPDIR/usr/share" "$APPDIR/usr/lib" -name tk.tcl -path '*tk8*' 2>/dev/null | awk 'NR==1' || true)
if [ -n "$_initcl" ] && [ -n "$_tktcl" ]; then
    TCL_REL="${_initcl%/init.tcl}"; TCL_REL="${TCL_REL#"$APPDIR"/}"
    TK_REL="${_tktcl%/tk.tcl}";     TK_REL="${TK_REL#"$APPDIR"/}"
    TCL_EXPORTS=$(printf 'export TCL_LIBRARY="$APPDIR/%s"\nexport TK_LIBRARY="$APPDIR/%s"\nexport TKPATH="$APPDIR/%s"' \
                  "$TCL_REL" "$TK_REL" "$TK_REL")
    echo ">> Tcl/Tk found — settings editor enabled from the AppImage"
else
    echo ">> NOTE: no Tcl/Tk in bundle — settings UI will fall back to raw editing"
fi
# Bundled CA roots (certifi): locate cacert.pem relative to APPDIR so AppRun points the
# interpreter's OpenSSL at the in-mount file — self-contained, no host-path assumptions.
CACERT=$(find "$APPDIR" -path '*/certifi/cacert.pem' -type f 2>/dev/null | awk 'NR==1' || true)
[ -n "$CACERT" ] || { echo "ERROR: bundled certifi cacert.pem not found (pip install certifi failed?)"; exit 1; }
CACERT_REL="${CACERT#"$APPDIR"/}"
echo ">> bundled CA roots: $CACERT_REL"
rm -f "$APPDIR/AppRun"
cat > "$APPDIR/AppRun" <<EOF
#!/bin/bash
HERE="\$(dirname "\$(readlink -f "\$0")")"
export APPDIR="\${APPDIR:-\$HERE}"
# TLS CA bundle: the bundled manylinux CPython's OpenSSL hunts for certs at its build-time
# path (/opt/_internal/...), absent on the target, so the tray's HTTPS update check fails
# CERTIFICATE_VERIFY_FAILED and the update notice never fires. Point it at the CA roots we
# bundle (certifi) so the AppImage is self-contained on any distro; an env override still wins
# (e.g. a corporate TLS-inspecting proxy whose root isn't in the Mozilla store).
export SSL_CERT_FILE="\${SSL_CERT_FILE:-\$APPDIR/$CACERT_REL}"
$TCL_EXPORTS
exec "\$HERE/$PYREL" "\$HERE/opt/pipewire-vac/src/main.py" --daemon "\$@"
EOF
chmod +x "$APPDIR/AppRun"

# 6) desktop entry + icon (appimagetool wants exactly one .desktop + icon at the root)
rm -f "$APPDIR"/*.desktop "$APPDIR"/.DirIcon "$APPDIR"/python*.png "$APPDIR"/python*.svg
rm -rf "$APPDIR/usr/share/applications" "$APPDIR/usr/share/metainfo"
cat > "$APPDIR/pipewire-vac.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=PipeWire VAC
Comment=Self-healing PipeWire virtual audio cables
Exec=pipewire-vac
Icon=pipewire-vac
Terminal=false
Categories=AudioVideo;Audio;Mixer;
X-AppImage-Version=$VERSION
EOF
rsvg-convert -w 256 -h 256 "$ROOT/packaging/pipewire-vac.svg" -o "$APPDIR/pipewire-vac.png"
ln -sf pipewire-vac.png "$APPDIR/.DirIcon"

# 7) pack — embed AppImage update-information so AppImageUpdate can delta-update in place from the
#    latest GitHub release. appimagetool writes <basename>.zsync into its CWD (NOT next to $OUT),
#    so run it from $DIST to keep both artifacts together. zsyncmake (apt 'zsync') must be on PATH
#    for the .zsync — the release workflow installs it; a local build without it still embeds the
#    update-info but skips the .zsync.
OUT="$DIST/PipeWire-VAC-$VERSION-$ARCH.AppImage"
UPDATE_INFO="gh-releases-zsync|cont1nuity|pipewire-vac|latest|PipeWire-VAC-*-$ARCH.AppImage.zsync"
rm -f "$OUT" "$OUT.zsync"     # unlink first: overwriting a RUNNING AppImage fails with ETXTBSY
( cd "$DIST" && ARCH=$ARCH "$AIT" --appimage-extract-and-run -u "$UPDATE_INFO" "$APPDIR" "$OUT" )
[ -f "$OUT.zsync" ] || echo ">> note: no .zsync produced (install 'zsync' to enable delta updates)"
echo ""
echo ">> built $OUT"
echo ">> run it:  chmod +x $OUT && $OUT"
echo "   (starts the self-healing daemon + tray; config seeds at ~/.config/pipewire-vac/config.toml)"
