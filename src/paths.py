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


# --------------------------------------------------------------- self-install (AppImage)
# A per-app XDG data dir where we park our own AppImage when we had to relocate a throwaway copy
# (a fresh download in ~/Downloads), so the original can be deleted without breaking autostart.
# Nothing else watches a per-app subdir of ~/.local/share (appimaged/Shelly scan ~/.local/bin;
# AppImageLauncher uses ~/Applications), so no tool moves/renames/double-manages it. A STABLE
# filename (dist AppImages are versioned) keeps autostart + self-update valid. An AppImage a tool
# already parked in a real home is adopted there instead (see tray.maybe_self_install).
XDG_DATA         = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), APP)
INSTALL_APPIMAGE = os.path.join(XDG_DATA, "PipeWire-VAC.AppImage")

EPHEMERAL_DIRS = None   # None -> the default throwaway set below; a list overrides it (tests)


def _ephemeral_dirs():
    home = os.path.expanduser("~")
    return EPHEMERAL_DIRS if EPHEMERAL_DIRS is not None else [
        os.environ.get("XDG_DOWNLOAD_DIR") or os.path.join(home, "Downloads"),
        os.path.join(home, "Desktop"), "/tmp", "/var/tmp", "/media", "/mnt", "/run/media"]


def _is_ephemeral(path):
    """True if `path` is in a throwaway/download location — the AppImage just landed there, so we
    relocate it. A deliberate home (a tool's install dir, a folder the user chose) is False, so we
    adopt it in place instead of duplicating. ponytail: tune the list in _ephemeral_dirs."""
    rp = os.path.realpath(path)
    return any(rp == os.path.realpath(s) or rp.startswith(os.path.realpath(s) + os.sep)
               for s in _ephemeral_dirs())


def install_target():
    """The persistent path a login should launch: our private INSTALL_APPIMAGE when we're running
    from a throwaway copy (maybe_self_install relocates it there), the current $APPIMAGE when it
    already lives in a real home (adopt in place — don't fight a tool that installed it), else the
    repo start.sh --daemon on a dev/source run (start.sh w/o --daemon is one-shot)."""
    src = os.environ.get("APPIMAGE")
    if not src:
        return os.path.join(ROOT, "start.sh") + " --daemon"
    return INSTALL_APPIMAGE if _is_ephemeral(src) else os.path.realpath(src)
