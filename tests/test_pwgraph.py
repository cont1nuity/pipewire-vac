# tests/test_pwgraph.py
import os, types, pwgraph
FIX = os.path.join(os.path.dirname(__file__), "fixtures")

def _fake_run(out):
    return lambda cmd: types.SimpleNamespace(stdout=out, stderr="", returncode=0)

def test_list_sinks_parses_names(monkeypatch):
    text = open(os.path.join(FIX, "sinks.txt")).read()
    monkeypatch.setattr(pwgraph, "run", _fake_run(text))
    names = pwgraph.list_sinks()
    # column 2 of `pactl list short sinks` is the node name
    assert all("\t" not in n for n in names)
    assert len(names) >= 1

def test_first_physical_skips_our_sinks_and_monitors():
    sinks = {"Master", "Game", "alsa_output.pci-0000_6c_00.6.analog-stereo"}
    ours  = {"Master", "Game", "Voice", "Media"}
    assert pwgraph.first_physical_sink(sinks, ours) == "alsa_output.pci-0000_6c_00.6.analog-stereo"

def test_first_physical_source_prefers_input_skips_monitor(monkeypatch):
    short = ("0\talsa_output.pci-0000_6c_00.6.analog-stereo.monitor\tPipeWire\t-\tIDLE\n"
             "1\talsa_input.pci-0000_6c_00.6.analog-stereo\tPipeWire\t-\tIDLE\n")
    monkeypatch.setattr(pwgraph, "run", _fake_run(short))
    assert pwgraph.first_physical_source() == "alsa_input.pci-0000_6c_00.6.analog-stereo"

def test_unload_null_sink_finds_module_and_unloads(monkeypatch):
    modules = (
        'Module #10\n\tName: module-null-sink\n'
        '\tArgument: sink_name=Game sink_properties=device.description="Game" channel_map=front-left,front-right\n'
        'Module #11\n\tName: module-null-sink\n'
        '\tArgument: sink_name=Master sink_properties=device.description="Master" channel_map=front-left,front-right\n'
        'Module #12\n\tName: module-loopback\n\tArgument: sink_name=Master\n'   # not a null-sink -> ignored
    )
    calls = []
    def run(cmd):
        calls.append(cmd)
        return types.SimpleNamespace(stdout=modules if "modules" in cmd else "", stderr="", returncode=0)
    monkeypatch.setattr(pwgraph, "run", run)
    pwgraph.unload_null_sink("Master")
    assert ["pactl", "unload-module", "11"] in calls

def test_unload_null_sink_noop_when_absent(monkeypatch):
    calls = []
    def run(cmd):
        calls.append(cmd)
        return types.SimpleNamespace(stdout="Module #10\n\tName: module-null-sink\n\tArgument: sink_name=Game\n",
                                     stderr="", returncode=0)
    monkeypatch.setattr(pwgraph, "run", run)
    pwgraph.unload_null_sink("Nonexistent")
    assert not any("unload-module" in c for c in calls)   # no match -> nothing unloaded

def test_source_labels_pairs_name_desc_and_drops_monitor(monkeypatch):
    text = ('Source #0\n\tName: alsa_output.pci-0000_6c_00.6.analog-stereo.monitor\n'
            '\tDescription: Monitor of Built-in Audio\n'
            'Source #1\n\tName: alsa_input.pci-0000_6c_00.6.analog-stereo\n'
            '\tDescription: Built-in Audio Analog Stereo\n')
    monkeypatch.setattr(pwgraph, "run", _fake_run(text))
    assert pwgraph.source_labels() == [
        ("alsa_input.pci-0000_6c_00.6.analog-stereo", "Built-in Audio Analog Stereo")]

def _fake_pactl_list(monkeypatch):
    """Dispatch `pactl list <X>` to the matching fixture file."""
    si = open(os.path.join(FIX, "sink-inputs.txt")).read()
    cl = open(os.path.join(FIX, "clients.txt")).read()
    def run(cmd):
        out = cl if "clients" in cmd else si if "sink-inputs" in cmd else ""
        return types.SimpleNamespace(stdout=out, stderr="", returncode=0)
    monkeypatch.setattr(pwgraph, "run", run)

def test_list_sink_inputs_parses_props(monkeypatch):
    _fake_pactl_list(monkeypatch)
    items = {si["index"]: si for si in pwgraph.list_sink_inputs()}
    assert items[123] == {"index": 123, "app": "Firefox", "binary": "firefox", "media": "AudioStream"}

def test_list_sink_inputs_fills_anonymous_from_client(monkeypatch):
    _fake_pactl_list(monkeypatch)
    items = {si["index"]: si for si in pwgraph.list_sink_inputs()}
    # stream #200 carries no application.* — name/binary come from its owning Client #90
    assert items[200]["app"] == "spotify"
    assert items[200]["binary"] == "spotify"
    assert items[200]["media"] == "audio-src"

def test_move_sink_input_calls_pactl(monkeypatch):
    calls = []
    monkeypatch.setattr(pwgraph, "run", lambda cmd: calls.append(cmd))
    pwgraph.move_sink_input(200, "Media")
    assert calls == [["pactl", "move-sink-input", "200", "Media"]]
