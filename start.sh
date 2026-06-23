#!/usr/bin/env bash
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
[ -f "$DIR/.venv/bin/activate" ] && . "$DIR/.venv/bin/activate"
exec python3 "$DIR/src/main.py" "$@"
