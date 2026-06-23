# tests/test_state.py
import state

def test_state_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(state.paths, "XDG_STATE", str(tmp_path))
    assert state.load() == set()
    state.mark({"Game", "Voice"})
    assert state.load() == {"Game", "Voice"}
    state.mark({"Game"})                 # subset -> no change
    assert state.load() == {"Game", "Voice"}
    state.mark({"Media"})
    assert state.load() == {"Game", "Voice", "Media"}

def test_state_drop_forgets_torn_down_cable(tmp_path, monkeypatch):
    monkeypatch.setattr(state.paths, "XDG_STATE", str(tmp_path))
    state.mark({"Game", "Voice", "Master"})
    state.drop({"Voice"})                 # cable removed from config -> forgotten
    assert state.load() == {"Game", "Master"}
    state.drop({"Nope"})                  # absent -> no-op
    assert state.load() == {"Game", "Master"}

def test_state_corrupt_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(state.paths, "XDG_STATE", str(tmp_path))
    (tmp_path / "state.json").write_text("{ broken")
    assert state.load() == set()
