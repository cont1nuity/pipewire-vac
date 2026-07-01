# tests/test_paths.py
import os, importlib

def test_config_path_prefers_repo_local(tmp_path, monkeypatch):
    import paths
    # When a repo-local config.toml exists, it wins over the XDG home.
    repo_cfg = os.path.join(paths.ROOT, "config.toml")
    existed = os.path.exists(repo_cfg)
    try:
        open(repo_cfg, "a").close()
        assert paths.config_path() == repo_cfg
    finally:
        if not existed:
            os.remove(repo_cfg)

def test_packaged_is_bool():
    import paths
    assert isinstance(paths.PACKAGED, bool)


# --- self-install target resolution (dbus-free: lives in paths, unit-testable without tray) ---

def test_is_ephemeral(tmp_path, monkeypatch):
    import paths
    dl = tmp_path / "Downloads"; dl.mkdir()
    monkeypatch.setattr(paths, "EPHEMERAL_DIRS", [str(dl)])
    assert paths._is_ephemeral(str(dl / "app.AppImage"))            # inside a throwaway dir
    assert not paths._is_ephemeral(str(tmp_path / "Apps" / "app.AppImage"))   # a deliberate home

def test_install_target_relocates_ephemeral(tmp_path, monkeypatch):
    import paths
    dl = tmp_path / "Downloads"; dl.mkdir()
    inst = tmp_path / "share" / "PipeWire-VAC.AppImage"
    monkeypatch.setattr(paths, "EPHEMERAL_DIRS", [str(dl)])
    monkeypatch.setattr(paths, "INSTALL_APPIMAGE", str(inst))
    monkeypatch.setenv("APPIMAGE", str(dl / "PipeWire-VAC-v1.0.4-x86_64.AppImage"))
    assert paths.install_target() == str(inst)                     # throwaway -> our install path

def test_install_target_adopts_deliberate(tmp_path, monkeypatch):
    import paths
    dl = tmp_path / "Downloads"; dl.mkdir()
    placed = tmp_path / "Applications" / "PipeWire-VAC.AppImage"
    placed.parent.mkdir(); placed.write_bytes(b"x")
    monkeypatch.setattr(paths, "EPHEMERAL_DIRS", [str(dl)])
    monkeypatch.setenv("APPIMAGE", str(placed))
    assert paths.install_target() == os.path.realpath(str(placed))  # deliberate home -> adopt in place

def test_install_target_dev_run(monkeypatch):
    import paths
    monkeypatch.delenv("APPIMAGE", raising=False)                  # source/dev run
    t = paths.install_target()
    assert t == os.path.join(paths.ROOT, "start.sh") + " --daemon"
