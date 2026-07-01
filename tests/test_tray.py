# tests/test_tray.py — pure (no dbus/network/Tk) helpers behind the AppImage update check.
import io
import json
import os

import paths
import tray


def test_ver_tuple():
    assert tray._ver_tuple("v1.2.0") == (1, 2, 0)
    assert tray._ver_tuple("1.10.3") == (1, 10, 3)
    assert tray._ver_tuple("dev") is None          # non-release -> never nagged
    assert tray._ver_tuple("1.2.0") < tray._ver_tuple("1.2.1")


def test_write_preserves_other_lines_and_comments(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("[features]\nself_heal = true  # keep me\ncheck_updates = true\n")
    tray.write_check_updates(str(p), False)
    txt = p.read_text()
    assert "check_updates = false" in txt
    assert "# keep me" in txt and "self_heal = true" in txt
    assert tray.read_check_updates(str(p)) is False


def test_write_inserts_key_into_existing_features(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("[features]\nself_heal = true\n")
    tray.write_check_updates(str(p), False)
    assert tray.read_check_updates(str(p)) is False
    assert "self_heal = true" in p.read_text()


def test_write_creates_features_table_when_absent(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("config_version = 2\n[[cable]]\nname = 'Game'\n")
    tray.write_check_updates(str(p), True)
    assert "[features]" in p.read_text()
    assert tray.read_check_updates(str(p)) is True


def test_read_defaults_true(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("config_version = 2\n")           # no [features] -> default on
    assert tray.read_check_updates(str(p)) is True
    assert tray.read_check_updates("") is True      # no path -> default on


class _Resp(io.BytesIO):                            # minimal urlopen() context-manager stand-in
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
        return False


def test_self_update_swaps_appimage_atomically(tmp_path, monkeypatch):
    app = tmp_path / "PipeWire-VAC-1.0.2-x86_64.AppImage"
    app.write_bytes(b"OLD")
    api = {"tag_name": "v1.0.3", "assets": [
        {"name": "PipeWire-VAC-1.0.3-x86_64.AppImage.zsync", "browser_download_url": "z"},
        {"name": "PipeWire-VAC-1.0.3-x86_64.AppImage", "browser_download_url": "http://x/app"}]}

    def fake_urlopen(req, timeout=None):
        return _Resp(json.dumps(api).encode() if req.full_url.startswith("http") and "/app" not in req.full_url
                     else b"NEW")
    monkeypatch.setattr(tray.urllib.request, "urlopen", fake_urlopen)

    ver = tray.download_latest_appimage(str(app), api_url="http://api/latest")
    assert ver == "v1.0.3"
    assert app.read_bytes() == b"NEW"               # swapped in place...
    assert app.stat().st_mode & 0o111               # ...and executable
    assert not (tmp_path / (app.name + ".new")).exists()   # no leftover temp


def test_self_update_leaves_no_temp_on_download_failure(tmp_path, monkeypatch):
    app = tmp_path / "app.AppImage"
    app.write_bytes(b"OLD")
    api = {"tag_name": "v9", "assets": [
        {"name": "app.AppImage", "browser_download_url": "http://x/app"}]}

    def fake_urlopen(req, timeout=None):
        if "/app" in req.full_url:
            raise OSError("network down")           # asset download fails
        return _Resp(json.dumps(api).encode())
    monkeypatch.setattr(tray.urllib.request, "urlopen", fake_urlopen)

    import pytest
    with pytest.raises(OSError):
        tray.download_latest_appimage(str(app), api_url="http://api/latest")
    assert app.read_bytes() == b"OLD"               # original untouched
    assert not (tmp_path / (app.name + ".new")).exists()   # half-written temp cleaned up


# --- self-install: relocate a throwaway copy / adopt a deliberately-placed one + repoint autostart ---

def _isolate(tmp_path, monkeypatch, dl, inst):
    """Point the ephemeral set at one dir, INSTALL_APPIMAGE + autostart entry into tmp_path."""
    monkeypatch.setattr(paths, "EPHEMERAL_DIRS", [str(dl)])
    monkeypatch.setattr(paths, "INSTALL_APPIMAGE", str(inst))
    monkeypatch.setattr(tray, "AUTOSTART_ENTRY", str(tmp_path / "autostart" / "pipewire-vac.desktop"))


def test_maybe_self_install_relocates_and_repoints(tmp_path, monkeypatch):
    dl = tmp_path / "Downloads"; dl.mkdir()
    inst = tmp_path / "share" / "PipeWire-VAC.AppImage"
    _isolate(tmp_path, monkeypatch, dl, inst)
    thrown = dl / "PipeWire-VAC-v1.0.4-x86_64.AppImage"
    thrown.write_bytes(b"#!/bin/sh\ntrue\n"); os.chmod(thrown, 0o755)
    monkeypatch.setenv("APPIMAGE", str(thrown))
    tray.autostart_enable()                          # login entry exists (points at the resolved target)
    tray.maybe_self_install()                        # relocate the Downloads copy -> install dir
    assert inst.exists(), "a throwaway copy must be relocated"
    assert tray.launch_cmd() == str(inst)
    assert str(inst) in open(tray.AUTOSTART_ENTRY).read()   # autostart repointed at the install path


def test_maybe_self_install_adopts_in_place(tmp_path, monkeypatch):
    dl = tmp_path / "Downloads"; dl.mkdir()
    inst = tmp_path / "share" / "PipeWire-VAC.AppImage"
    _isolate(tmp_path, monkeypatch, dl, inst)
    placed = tmp_path / "Applications" / "PipeWire-VAC.AppImage"
    placed.parent.mkdir(); placed.write_bytes(b"#!/bin/sh\ntrue\n"); os.chmod(placed, 0o755)
    real = os.path.realpath(str(placed))
    monkeypatch.setenv("APPIMAGE", str(placed))
    tray.autostart_enable()
    tray.maybe_self_install()                        # not ephemeral -> adopt in place, no copy
    assert not inst.exists(), "a deliberately-placed AppImage is adopted, not duplicated"
    assert tray.launch_cmd() == real
    assert real in open(tray.AUTOSTART_ENTRY).read()


def test_maybe_self_install_noop_without_appimage(tmp_path, monkeypatch):
    dl = tmp_path / "Downloads"; dl.mkdir()
    inst = tmp_path / "share" / "PipeWire-VAC.AppImage"
    _isolate(tmp_path, monkeypatch, dl, inst)
    monkeypatch.delenv("APPIMAGE", raising=False)    # dev/source run
    tray.maybe_self_install()                        # no-op — nothing copied, no autostart written
    assert not inst.exists()
    assert not os.path.exists(tray.AUTOSTART_ENTRY)
