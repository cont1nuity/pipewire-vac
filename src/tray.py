"""System-tray icon for the PipeWire VAC self-healing daemon.

org.kde.StatusNotifierItem + com.canonical.dbusmenu directly over D-Bus (dbus-next, pure
python) — no Qt/GTK, so the AppImage stays small and it works on any SNI host (KDE, GNOME
w/ extension, ...). Spawned by daemon.py as a SEPARATE process; dies with the daemon
(PR_SET_PDEATHSIG + pid poll) and exits silently when there is no session bus, watcher, or
dbus_next — the daemon runs fine trayless.

Menu: version (disabled), Settings… (row-based editor), Edit config file (raw), Start at
login (checkbox), 'Check for updates automatically' + 'Check for updates…' (AppImage runs only
— hands off to AppImageUpdate if present, else opens the Releases page), Quit (stops the
daemon). Left click opens Settings. The icon is a themed name (audio-headphones) — no asset
shipped.

Usage (by daemon.py): tray.py --pid <daemon-pid> --config <path> --version <v>
"""
import asyncio
import os
import re
import shutil
import signal
import struct
import subprocess
import sys
import urllib.request
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths
from paths import ROOT, XDG_STATE

APP_ID = paths.APP                       # internal id (config dir / lock / SNI) = "pipewire-vac"
APP_NAME = "PipeWire VAC"
RELEASES_URL = "https://github.com/cont1nuity/pipewire-vac/releases/latest"
ITEM_PATH = "/StatusNotifierItem"
MENU_PATH = "/MenuBar"
WATCHER = "org.kde.StatusNotifierWatcher"
ICON_NAME = "audio-headphones"          # default; main() upgrades to our installed icon
VERSION = "dev"                          # set from --version (passed by the daemon)

# menu item ids
MI_INFO, MI_SETTINGS, MI_EDIT, MI_AUTOSTART, MI_AUTOUPD, MI_SEP, MI_UPDATE, MI_RESTART, MI_QUIT = \
    1, 2, 3, 4, 5, 6, 7, 8, 9


def die_with_parent():
    """PR_SET_PDEATHSIG — the kernel SIGTERMs us if the daemon dies for ANY reason."""
    try:
        import ctypes
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGTERM, 0, 0, 0)
    except Exception:
        pass


def opt(a, name, default=""):
    if name in a:
        i = a.index(name); v = a[i + 1]; del a[i:i + 2]; return v
    return default


def _png_to_argb(data):
    """Decode an 8-bit RGBA, non-interlaced PNG to (width, height, ARGB32 big-endian bytes).
    Minimal stdlib decoder (handles all 5 scanline filters) — that's what rsvg-convert emits.
    Embedded directly as the tray pixmap so the host draws it; no icon-theme lookup."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    pos, width, height, idat = 8, 0, 0, bytearray()
    while pos < len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        ctype = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + length]
        if ctype == b"IHDR":
            width, height = struct.unpack(">II", chunk[:8])
        elif ctype == b"IDAT":
            idat += chunk
        elif ctype == b"IEND":
            break
        pos += 12 + length
    raw = zlib.decompress(bytes(idat))
    bpp, stride = 4, width * 4
    prev = bytearray(stride)
    argb = bytearray()
    i = 0
    for _y in range(height):
        ft = raw[i]; i += 1
        line = bytearray(raw[i:i + stride]); i += stride
        if ft == 1:
            for x in range(bpp, stride): line[x] = (line[x] + line[x - bpp]) & 0xff
        elif ft == 2:
            for x in range(stride): line[x] = (line[x] + prev[x]) & 0xff
        elif ft == 3:
            for x in range(stride):
                a = line[x - bpp] if x >= bpp else 0
                line[x] = (line[x] + ((a + prev[x]) >> 1)) & 0xff
        elif ft == 4:
            for x in range(stride):
                a = line[x - bpp] if x >= bpp else 0
                b = prev[x]
                c = prev[x - bpp] if x >= bpp else 0
                p = a + b - c; pa = abs(p - a); pb = abs(p - b); pc = abs(p - c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else (b if pb <= pc else c))) & 0xff
        for x in range(0, stride, 4):
            argb += bytes((line[x + 3], line[x], line[x + 1], line[x + 2]))   # RGBA -> ARGB
        prev = line
    return width, height, bytes(argb)


def _icon_pixmap():
    """Our icon as an SNI a(iiay) pixmap. [] if the PNG is missing/undecodable (falls back to name)."""
    for png in (os.path.join(ROOT, "packaging", "pipewire-vac.png"),   # dev checkout
                os.path.join(ROOT, "pipewire-vac.png")):               # packaged payload
        if os.path.exists(png):
            try:
                w, h, argb = _png_to_argb(open(png, "rb").read())
                return [[w, h, argb]]
            except Exception:
                break
    return []


# --------------------------------------------------------------- autostart (opt-in)

AUTOSTART_ENTRY = os.path.join(
    os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
    "autostart", APP_ID + ".desktop")


def launch_cmd():
    """What a login should start: the AppImage running us ($APPIMAGE) or the repo start.sh."""
    appimage = os.environ.get("APPIMAGE")
    if appimage:
        return appimage
    return os.path.join(ROOT, "start.sh") + " --daemon"


def autostart_enabled():
    return os.path.exists(AUTOSTART_ENTRY)


def autostart_enable():
    cmd = launch_cmd()
    os.makedirs(os.path.dirname(AUTOSTART_ENTRY), exist_ok=True)
    with open(AUTOSTART_ENTRY, "w") as f:
        f.write("[Desktop Entry]\nType=Application\nName=%s\n"
                "Comment=Self-healing PipeWire virtual audio cables\n"
                "Exec=%s\nIcon=%s\nTerminal=false\nX-GNOME-Autostart-enabled=true\n"
                % (APP_NAME, cmd, ICON_NAME))


def autostart_disable():
    try:
        os.unlink(AUTOSTART_ENTRY)
    except FileNotFoundError:
        pass


# ----------------------------------------------------------- D-Bus service objects

try:
    from dbus_next import Variant, PropertyAccess                  # noqa: E402
    from dbus_next.aio import MessageBus                           # noqa: E402
    from dbus_next.service import (ServiceInterface, method,       # noqa: E402
                                   dbus_property, signal as dbus_signal)
except ImportError as _e:                     # tray is optional — daemon runs without it
    print("tray unavailable: %s (pip/pacman: dbus-next)" % _e, file=sys.stderr)
    sys.exit(0)


class Sni(ServiceInterface):
    def __init__(self, pixmap, tooltip_text):
        super().__init__("org.kde.StatusNotifierItem")
        self._pixmap = pixmap
        self._tip = tooltip_text
        self.on_activate = lambda: None

    @dbus_property(access=PropertyAccess.READ)
    def Category(self) -> "s":
        return "ApplicationStatus"

    @dbus_property(access=PropertyAccess.READ)
    def Id(self) -> "s":
        return APP_ID

    @dbus_property(access=PropertyAccess.READ)
    def Title(self) -> "s":
        return APP_NAME

    @dbus_property(access=PropertyAccess.READ)
    def Status(self) -> "s":
        return "Active"

    @dbus_property(access=PropertyAccess.READ)
    def WindowId(self) -> "i":
        return 0

    @dbus_property(access=PropertyAccess.READ)
    def IconName(self) -> "s":
        return "" if self._pixmap else ICON_NAME     # empty -> host uses the pixmap

    @dbus_property(access=PropertyAccess.READ)
    def IconPixmap(self) -> "a(iiay)":
        return self._pixmap

    @dbus_property(access=PropertyAccess.READ)
    def OverlayIconName(self) -> "s":
        return ""

    @dbus_property(access=PropertyAccess.READ)
    def OverlayIconPixmap(self) -> "a(iiay)":
        return []

    @dbus_property(access=PropertyAccess.READ)
    def AttentionIconName(self) -> "s":
        return ""

    @dbus_property(access=PropertyAccess.READ)
    def AttentionIconPixmap(self) -> "a(iiay)":
        return []

    @dbus_property(access=PropertyAccess.READ)
    def ToolTip(self) -> "(sa(iiay)ss)":
        return ["" if self._pixmap else ICON_NAME, self._pixmap, APP_NAME, self._tip]

    @dbus_property(access=PropertyAccess.READ)
    def ItemIsMenu(self) -> "b":
        return False                          # left click = Activate (quick-open config)

    @dbus_property(access=PropertyAccess.READ)
    def Menu(self) -> "o":
        return MENU_PATH

    @method()
    def Activate(self, x: "i", y: "i"):
        self.on_activate()

    @method()
    def SecondaryActivate(self, x: "i", y: "i"):
        self.on_activate()

    @method()
    def ContextMenu(self, x: "i", y: "i"):
        pass                                  # the host renders /MenuBar itself

    @method()
    def Scroll(self, delta: "i", orientation: "s"):
        pass

    @dbus_signal()
    def NewIcon(self):
        pass

    @dbus_signal()
    def NewToolTip(self):
        pass

    @dbus_signal()
    def NewStatus(self) -> "s":
        return "Active"


# ------------------------------------------------------- update check (AppImage only)

def read_check_updates(cfgpath):
    """[features] check_updates (default True). Best-effort — any parse problem falls back to True."""
    if not cfgpath:
        return True
    try:
        import tomllib as _t
    except ModuleNotFoundError:
        return True
    try:
        with open(cfgpath, "rb") as fh:
            return bool(_t.load(fh).get("features", {}).get("check_updates", True))
    except Exception:
        return True


def write_check_updates(cfgpath, value):
    """Flip [features] check_updates in place, touching only that one line so comments/layout
    survive. Creates the key — and the [features] table — if absent. (configui.py has the full
    comment-preserving writer but pulls in Tk; the tray stays Tk-free, hence this.)"""
    if not cfgpath:
        return
    val = "true" if value else "false"
    try:
        with open(cfgpath) as fh:
            lines = fh.read().split("\n")
    except Exception:
        return
    out, in_features, done = [], False, False
    for ln in lines:
        s = ln.strip()
        if s.startswith("[") and s.endswith("]"):
            if in_features and not done:            # leaving [features] without the key -> add it
                out.append("check_updates = %s" % val)
                done = True
            in_features = (s == "[features]")
        elif in_features and not done and re.match(r"check_updates\s*=", s):
            indent = ln[:len(ln) - len(ln.lstrip())]
            cmt = re.search(r"\s#.*$", ln)          # keep any trailing comment
            out.append("%scheck_updates = %s%s" % (indent, val, cmt.group(0) if cmt else ""))
            done = True
            continue
        out.append(ln)
    if not done:
        if not in_features:
            out.append("[features]")
        out.append("check_updates = %s" % val)
    try:
        with open(cfgpath, "w") as fh:
            fh.write("\n".join(out))
    except Exception:
        pass


def _ver_tuple(s):
    """'v1.2.0' / '1.2.0' -> (1, 2, 0); None for non-release strings like 'dev' (never nagged)."""
    m = re.match(r"v?(\d+(?:\.\d+)*)", s or "")
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def latest_release_version():
    """Latest release tag WITHOUT the GitHub API (no token, no rate limit): a HEAD on
    /releases/latest 302-redirects to /releases/tag/vX.Y.Z — read the tag off the final URL."""
    req = urllib.request.Request(RELEASES_URL, method="HEAD", headers={"User-Agent": APP_ID})
    with urllib.request.urlopen(req, timeout=6) as resp:
        final = resp.geturl()
    m = re.search(r"/tag/(v?[0-9][0-9.]*)", final)
    return m.group(1) if m else None


def notify(summary, body):
    """Desktop notification via libnotify if present; skipped silently otherwise (the tray menu
    still shows the update either way)."""
    ns = shutil.which("notify-send")
    if not ns:
        return
    try:
        subprocess.Popen([ns, "-a", APP_NAME, summary, body], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


class Menu(ServiceInterface):
    """com.canonical.dbusmenu menu ('Check for updates…' items appear only for AppImage runs)."""

    def __init__(self, cfgpath, daemon_pid, quit_ev):
        super().__init__("com.canonical.dbusmenu")
        self.revision = 1
        self.cfgpath = cfgpath or paths.config_path()
        self.daemon_pid = daemon_pid
        self.quit_ev = quit_ev
        self._cfgui = None                    # the running settings-editor process, if any
        self.update_available = None          # latest version string, once a newer release is seen
        self.check_updates = read_check_updates(self.cfgpath)

    # ---- menu model ----

    def _props(self, mid):
        home = os.path.expanduser("~")
        shown = self.cfgpath.replace(home, "~", 1) if self.cfgpath.startswith(home) else self.cfgpath
        if mid == MI_INFO:
            return {"label": Variant("s", "%s — version %s" % (APP_NAME, VERSION)),
                    "enabled": Variant("b", False)}
        if mid == MI_SETTINGS:
            return {"label": Variant("s", "Settings…")}
        if mid == MI_EDIT:
            return {"label": Variant("s", "Edit config file: %s" % shown)}
        if mid == MI_AUTOSTART:
            return {"label": Variant("s", "Start at login"),
                    "toggle-type": Variant("s", "checkmark"),
                    "toggle-state": Variant("i", 1 if autostart_enabled() else 0)}
        if mid == MI_AUTOUPD:
            return {"label": Variant("s", "Check for updates automatically"),
                    "toggle-type": Variant("s", "checkmark"),
                    "toggle-state": Variant("i", 1 if self.check_updates else 0)}
        if mid == MI_SEP:
            return {"type": Variant("s", "separator")}
        if mid == MI_RESTART:
            return {"label": Variant("s", "Restart audio (PipeWire)")}
        if mid == MI_UPDATE:
            lbl = ("Update available: %s — install now" % self.update_available
                   if self.update_available else "Check for updates…")
            return {"label": Variant("s", lbl)}
        if mid == MI_QUIT:
            return {"label": Variant("s", "Quit (stop routing)")}
        return {"children-display": Variant("s", "submenu")}        # root

    def _layout(self):
        appimage = bool(os.environ.get("APPIMAGE"))   # update items only make sense for the AppImage
        ids = [MI_INFO, MI_SETTINGS, MI_EDIT, MI_AUTOSTART]
        if appimage:
            ids.append(MI_AUTOUPD)
        ids.append(MI_SEP)
        if appimage:
            ids.append(MI_UPDATE)
        ids.append(MI_RESTART)
        ids.append(MI_QUIT)
        kids = [Variant("(ia{sv}av)", [mid, self._props(mid), []]) for mid in ids]
        return [0, self._props(0), kids]

    # ---- actions ----

    def open_config(self):
        try:
            subprocess.Popen(["xdg-open", self.cfgpath], start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    def open_config_ui(self):
        """Launch the row-based settings editor (configui.py) under the same interpreter that
        runs us. Single-instance; falls back to opening the raw TOML when tkinter is absent."""
        if self._cfgui is not None and self._cfgui.poll() is None:
            return                                  # editor already open
        gui = os.path.join(os.path.dirname(os.path.abspath(__file__)), "configui.py")
        import importlib.util
        try:
            have_tk = importlib.util.find_spec("tkinter") is not None
        except Exception:
            have_tk = False
        if os.path.exists(gui) and have_tk:
            try:
                self._cfgui = subprocess.Popen([sys.executable, gui, "--config", self.cfgpath],
                                               start_new_session=True,
                                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except Exception:
                pass
        self.open_config()                          # fallback: xdg-open the raw TOML

    def restart_audio(self):
        """Recovery shortcut: bounce the user audio stack. The daemon's poll re-creates our
        cables within POLL seconds, so routing heals itself afterward — nothing to do here."""
        try:
            subprocess.Popen(["systemctl", "--user", "restart",
                              "pipewire", "pipewire-pulse", "wireplumber"],
                             start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    def _clicked(self, mid):
        if mid == MI_SETTINGS:
            self.open_config_ui()
        elif mid == MI_EDIT:
            self.open_config()
        elif mid == MI_AUTOSTART:
            (autostart_disable if autostart_enabled() else autostart_enable)()
            self._refresh()
        elif mid == MI_AUTOUPD:
            self.check_updates = not self.check_updates
            write_check_updates(self.cfgpath, self.check_updates)
            self._refresh()
        elif mid == MI_UPDATE:
            self._check_updates()
        elif mid == MI_RESTART:
            self.restart_audio()
        elif mid == MI_QUIT:
            try:
                os.kill(self.daemon_pid, signal.SIGTERM)
            except Exception:
                pass
            self.quit_ev.set()

    def _refresh(self):
        """Tell the host the menu changed (bump revision + re-emit) so labels/checkmarks repaint."""
        self.revision += 1
        self.ItemsPropertiesUpdated()
        self.LayoutUpdated()

    def _check_updates(self):
        """AppImage only: hand off to AppImageUpdate for an in-place delta update if the tool is
        installed, else open the Releases page. The AppImage carries embedded update-information
        (baked by packaging/build-appimage.sh), so the updater needs only the AppImage path."""
        appimage = os.environ.get("APPIMAGE")
        tool = shutil.which("appimageupdatetool") or shutil.which("AppImageUpdate")
        target = [tool, appimage] if (appimage and tool) else ["xdg-open", RELEASES_URL]
        try:
            subprocess.Popen(target, start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    def set_update_available(self, version):
        """Called by the startup check when a newer release exists: relabel the update item."""
        self.update_available = version
        self._refresh()

    # ---- com.canonical.dbusmenu ----

    @dbus_property(access=PropertyAccess.READ)
    def Version(self) -> "u":
        return 3

    @dbus_property(access=PropertyAccess.READ)
    def TextDirection(self) -> "s":
        return "ltr"

    @dbus_property(access=PropertyAccess.READ)
    def Status(self) -> "s":
        return "normal"

    @dbus_property(access=PropertyAccess.READ)
    def IconThemePath(self) -> "as":
        return []

    @method()
    def GetLayout(self, parent: "i", depth: "i", names: "as") -> "u(ia{sv}av)":
        return [self.revision, self._layout()]

    @method()
    def GetGroupProperties(self, ids: "ai", names: "as") -> "a(ia{sv})":
        ids = ids or [0, MI_INFO, MI_SETTINGS, MI_EDIT, MI_AUTOSTART, MI_AUTOUPD, MI_SEP,
                      MI_UPDATE, MI_RESTART, MI_QUIT]
        return [[i, self._props(i)] for i in ids]

    @method()
    def GetProperty(self, mid: "i", name: "s") -> "v":
        return self._props(mid).get(name, Variant("s", ""))

    @method()
    def Event(self, mid: "i", event_id: "s", data: "v", timestamp: "u"):
        if event_id == "clicked":
            self._clicked(mid)

    @method()
    def EventGroup(self, events: "a(isvu)") -> "ai":
        for mid, event_id, _data, _ts in events:
            if event_id == "clicked":
                self._clicked(mid)
        return []

    @method()
    def AboutToShow(self, mid: "i") -> "b":
        return False

    @method()
    def AboutToShowGroup(self, ids: "ai") -> "aiai":
        return [[], []]

    @dbus_signal()
    def ItemsPropertiesUpdated(self) -> "a(ia{sv})a(ias)":
        return [[[m, self._props(m)] for m in (MI_AUTOSTART, MI_AUTOUPD, MI_UPDATE)], []]

    @dbus_signal()
    def LayoutUpdated(self) -> "ui":
        return [self.revision, 0]


# ----------------------------------------------------------------------- main

async def _check_for_update(menu):
    """Best-effort update check, off the dbus loop. Waits a short settle delay (network/DNS/session
    bus come up at login), then polls: if the latest GitHub release is newer than the running
    version, relabel the tray item + announce it once. Keeps re-checking, so an even newer release
    published while the daemon idles for days announces again (once each). A one-shot boot check used
    to lose a network-not-ready-at-login race *silently*; this retries on failure. Failures log to
    stderr (tray.err) instead of vanishing."""
    notified = None                             # newest version already announced this boot (each once)
    delay = 20                                  # settle: let network/DNS/session bus come up after login
    while not menu.quit_ev.is_set():
        try:
            await asyncio.wait_for(menu.quit_ev.wait(), delay)
            return                              # quitting
        except asyncio.TimeoutError:
            pass
        try:
            latest = await asyncio.to_thread(latest_release_version)
            cur, new = _ver_tuple(VERSION), _ver_tuple(latest)
            if new and cur and new > cur:
                menu.set_update_available(latest)
                if latest != notified:          # first sighting of this release (or an even newer one)
                    notify(APP_NAME, "Update available: %s — open the tray to install" % latest)
                    notified = latest           # ...announce once; keep polling for a newer one
            delay = 6 * 3600                    # re-check in 6 h (catches a newer release mid-session)
        except Exception as e:
            print("update-check failed (will retry): %r" % e, file=sys.stderr, flush=True)
            delay = 60                          # transient (network not up yet) -> retry in 1 min


async def amain(daemon_pid, cfgpath):
    bus = await MessageBus().connect()
    quit_ev = asyncio.Event()
    menu = Menu(cfgpath, daemon_pid, quit_ev)
    sni = Sni(_icon_pixmap(), "version %s — config: %s" % (VERSION, menu.cfgpath))
    sni.on_activate = menu.open_config_ui
    bus.export(MENU_PATH, menu)
    bus.export(ITEM_PATH, sni)
    intr = await bus.introspect(WATCHER, "/StatusNotifierWatcher")
    watcher = bus.get_proxy_object(WATCHER, "/StatusNotifierWatcher", intr) \
                 .get_interface("org.kde.StatusNotifierWatcher")
    await watcher.call_register_status_notifier_item(bus.unique_name)
    if os.environ.get("APPIMAGE") and menu.check_updates:   # AppImage-only, honors the toggle
        asyncio.create_task(_check_for_update(menu))
    while not quit_ev.is_set():
        try:
            os.kill(daemon_pid, 0)            # daemon gone -> tray goes too
        except OSError:
            break
        try:
            await asyncio.wait_for(quit_ev.wait(), 2.0)
        except asyncio.TimeoutError:
            pass


def main():
    global VERSION
    die_with_parent()
    a = sys.argv[1:]
    daemon_pid = int(opt(a, "--pid", "0") or "0")
    cfgpath = opt(a, "--config")
    VERSION = opt(a, "--version", "dev") or "dev"
    if not daemon_pid:
        sys.exit("usage: tray.py --pid <daemon-pid> [--config PATH] [--version V]")
    asyncio.run(amain(daemon_pid, cfgpath))


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as e:                    # no bus / no watcher / no dbus_next
        print("tray unavailable: %s" % e, file=sys.stderr)
        sys.exit(0)
