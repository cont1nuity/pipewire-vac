# tests/test_daemon.py
import pytest, daemon

def test_interesting_triggers_on_sink_source_and_new_stream():
    # heal: a cable / physical target / mic appears or goes away
    assert daemon._interesting("Event 'new' on sink #42\n")
    assert daemon._interesting("Event 'remove' on sink #42\n")
    assert daemon._interesting("Event 'new' on source #7\n")
    assert daemon._interesting("Event 'remove' on source #7\n")
    # route: a new playback stream to auto-assign
    assert daemon._interesting("Event 'new' on sink-input #123\n")

def test_interesting_ignores_the_leak_storm_and_noise():
    # the actual leak driver — clients connecting/disconnecting constantly — must NEVER wake us
    assert not daemon._interesting("Event 'new' on client #158\n")
    assert not daemon._interesting("Event 'remove' on client #158\n")
    assert not daemon._interesting("Event 'new' on source-output #99\n")   # capture taps (VU meters)
    assert not daemon._interesting("Event 'change' on sink #42\n")          # volume/mute — structure-only
    assert not daemon._interesting("Event 'change' on sink-input #123\n")
    assert not daemon._interesting("Event 'remove' on sink-input #123\n")   # stream gone -> nothing to do
    assert not daemon._interesting("garbage line without quotes\n")
    # sink-input must not be misread as sink
    assert not daemon._interesting("Event 'change' on sink-input #5\n")

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
