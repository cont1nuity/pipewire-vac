# tests/test_pwgraph_actions.py
import types, pwgraph

class Recorder:
    def __init__(self): self.calls = []
    def __call__(self, cmd):
        self.calls.append(cmd)
        return types.SimpleNamespace(stdout="", stderr="", returncode=0)

def test_create_null_sink_command(monkeypatch):
    rec = Recorder(); monkeypatch.setattr(pwgraph, "run", rec)
    pwgraph.create_null_sink("Master", "Master", "front-left,front-right")
    cmd = rec.calls[0]
    assert cmd[:3] == ["pactl", "load-module", "module-null-sink"]
    assert "sink_name=Master" in cmd
    assert 'sink_properties=device.description="Master"' in cmd
    assert "channel_map=front-left,front-right" in cmd

def test_mute_off_is_zero(monkeypatch):
    rec = Recorder(); monkeypatch.setattr(pwgraph, "run", rec)
    pwgraph.set_sink_mute("Game", False)
    assert rec.calls[0] == ["pactl", "set-sink-mute", "Game", "0"]
