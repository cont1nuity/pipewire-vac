# src/paths.py — single source of truth for locations. Nothing else hardcodes a path.
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # src/ -> repo root

APP        = "pipewire-vac"
XDG_CONFIG = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), APP)
XDG_STATE  = os.path.join(os.environ.get("XDG_STATE_HOME")  or os.path.expanduser("~/.local/state"), APP)

# Packaged when the AppImage runtime set APPDIR, OR when the code dir is read-only (squashfs mount).
PACKAGED = bool(os.environ.get("APPDIR")) or not os.access(ROOT, os.W_OK)

def config_path():
    """Live config: repo-local config.toml if present (dev), else the XDG home (packaged)."""
    repo = os.path.join(ROOT, "config.toml")
    return repo if os.path.exists(repo) else os.path.join(XDG_CONFIG, "config.toml")
