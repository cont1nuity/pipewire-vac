#!/usr/bin/env bash
# Setup for PipeWire VAC. Run as your normal user — no root, no system packages.
# Needs Python 3.11+ (stdlib tomllib) and PipeWire's CLI tools (pactl, pw-link) on PATH.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

# 1) Python venv + dep. dbus-next is the only one (the tray) and is optional — the daemon
#    runs fine without it. The settings editor also wants Tk (stdlib tkinter, e.g.
#    `pacman -S tk` / `apt install python3-tk`); it falls back to raw-file editing without it.
echo ">> creating venv + installing dbus-next"
python3 -m venv .venv
. .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet dbus-next
echo "   venv ready at $DIR/.venv"

# 2) dev config: seed from the example on first install; ask before overwriting.
if [ -f config.toml ]; then
  read -r -p ">> config.toml already exists — overwrite with config.example.toml? [y/N] " ans
  case "$ans" in
    [yY]*) cp config.example.toml config.toml; echo "   overwritten." ;;
    *)     echo "   keeping your config.toml." ;;
  esac
else
  cp config.example.toml config.toml
  echo ">> created config.toml from config.example.toml — edit cable targets to taste"
fi

cat <<EOF

Done. Then:
  ./start.sh                          # reconcile the live graph once (idempotent), then exit
  ./start.sh --daemon                 # stay running and self-heal
  .venv/bin/pytest                    # run the test suite
  python3 src/main.py --selftest      # offline reconcile self-check (no hardware)

Edit config.toml to taste (cables, targets, app rules). The daemon re-reads it
every poll, so changes apply live — no restart.
EOF
