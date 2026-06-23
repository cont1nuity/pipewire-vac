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
