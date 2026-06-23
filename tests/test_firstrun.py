# tests/test_firstrun.py
import os, pytest, firstrun

def test_check_tools_missing_exits(monkeypatch):
    monkeypatch.setattr(firstrun.shutil, "which", lambda name: None)
    with pytest.raises(SystemExit):
        firstrun._check_tools()

def test_check_tools_present_ok(monkeypatch):
    monkeypatch.setattr(firstrun.shutil, "which", lambda name: "/usr/bin/" + name)
    firstrun._check_tools()   # no exception

def test_ensure_config_passthrough_when_arg_given(tmp_path):
    p = tmp_path / "explicit.toml"; p.write_text("")
    assert firstrun._ensure_config(str(p)) == str(p)

def test_ensure_config_seeds_from_example(tmp_path, monkeypatch):
    target = tmp_path / "config.toml"
    monkeypatch.setattr(firstrun.paths, "config_path", lambda: str(target))
    out = firstrun._ensure_config(None)
    assert out == str(target)
    assert os.path.exists(target)                 # example was copied in
    assert "[[cable]]" in target.read_text()       # it's the real v2 example
