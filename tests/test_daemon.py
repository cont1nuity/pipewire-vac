# tests/test_daemon.py
import pytest, daemon

def test_single_instance_grants_then_blocks(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    first = daemon.single_instance()                 # acquires the lock
    assert (tmp_path / "pipewire-vac.lock").exists()
    with pytest.raises(SystemExit):
        daemon.single_instance()                     # second instance is refused
    first.close()                                    # releases for other tests

def test_single_instance_writes_pid(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    f = daemon.single_instance()
    assert (tmp_path / "pipewire-vac.lock").read_text().strip().isdigit()
    f.close()

def test_load_or_keep_falls_back_on_bad_toml(tmp_path):
    import config
    good = tmp_path / "c.toml"; good.write_text('[[cable]]\nname="Game"\n')
    last = config.load(str(good))
    bad = tmp_path / "bad.toml"; bad.write_text('this = = nonsense')
    assert daemon._load_or_keep(str(bad), last) is last           # parse error -> keep last-good
    assert daemon._load_or_keep(str(good), None)["cable"][0]["name"] == "Game"
