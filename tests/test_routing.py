# tests/test_routing.py
import routing, config

def _cfg(cables):
    base = config._merge(config.DEFAULTS, {"cable": cables})
    base["cable"] = [config._merge(config._CABLE_DEFAULTS, c) for c in base["cable"]]
    return base

def test_desired_links_stereo_chain():
    cfg = _cfg([{"name": "Game", "target": "Master"}, {"name": "Master", "target": "auto"}])
    d = routing.desired_state(cfg, physical_auto="HW")
    assert ("Game:monitor_FL", "Master:playback_FL") in d["links"]
    assert ("Game:monitor_FR", "Master:playback_FR") in d["links"]
    assert ("Master:monitor_FL", "HW:playback_FL") in d["links"]
    assert {s["name"] for s in d["sinks"]} == {"Game", "Master"}

def test_desired_5_1_has_six_links():
    cfg = _cfg([{"name": "Surround", "channels": "5.1", "target": "HWdev"}])
    d = routing.desired_state(cfg, physical_auto=None)
    sufs = {inp.split(":")[1].replace("playback_", "") for _out, inp in d["links"]}
    assert sufs == {"FL", "FR", "FC", "LFE", "RL", "RR"}
    assert len(d["links"]) == 6

def test_auto_without_physical_skips_links_but_still_creates():
    cfg = _cfg([{"name": "Master", "target": "auto"}])
    d = routing.desired_state(cfg, physical_auto=None)
    assert d["links"] == []
    assert d["sinks"][0]["name"] == "Master"

def test_stereo_source_matches_channels():
    cfg = _cfg([{"name": "VoiceMix", "channels": "stereo", "target": "auto", "sources": ["mic"]}])
    d = routing.desired_state(cfg, physical_auto="HW", source_ports={"mic": ["FL", "FR"]})
    assert ("mic:capture_FL", "VoiceMix:playback_FL") in d["links"]
    assert ("mic:capture_FR", "VoiceMix:playback_FR") in d["links"]

def test_mono_source_fans_out_to_stereo_cable():
    cfg = _cfg([{"name": "VoiceMix", "channels": "stereo", "target": "auto", "sources": ["mic"]}])
    d = routing.desired_state(cfg, physical_auto="HW", source_ports={"mic": ["MONO"]})
    assert ("mic:capture_MONO", "VoiceMix:playback_FL") in d["links"]
    assert ("mic:capture_MONO", "VoiceMix:playback_FR") in d["links"]

def test_mono_source_into_mono_cable_no_fanout():
    cfg = _cfg([{"name": "Mono", "channels": "mono", "target": "auto", "sources": ["mic"]}])
    d = routing.desired_state(cfg, physical_auto="HW", source_ports={"mic": ["MONO"]})
    src_links = [l for l in d["links"] if l[0] == "mic:capture_MONO"]
    assert src_links == [("mic:capture_MONO", "Mono:playback_MONO")]

def test_absent_source_emits_no_links():
    cfg = _cfg([{"name": "VoiceMix", "channels": "stereo", "target": "auto", "sources": ["mic"]}])
    d = routing.desired_state(cfg, physical_auto="HW", source_ports={})   # mic not present
    assert not any(out.startswith("mic:") for out, _ in d["links"])

def test_source_auto_resolves_to_physical_mic():
    cfg = _cfg([{"name": "VoiceMix", "channels": "stereo", "target": "auto", "sources": ["auto"]}])
    d = routing.desired_state(cfg, physical_auto="HW", source_ports={"realmic": ["FL", "FR"]},
                              physical_source_auto="realmic")
    assert ("realmic:capture_FL", "VoiceMix:playback_FL") in d["links"]
    assert ("realmic:capture_FR", "VoiceMix:playback_FR") in d["links"]

def test_source_auto_without_physical_mic_skips():
    cfg = _cfg([{"name": "VoiceMix", "channels": "stereo", "target": "auto", "sources": ["auto"]}])
    d = routing.desired_state(cfg, physical_auto="HW", physical_source_auto=None)
    assert not any("capture_" in out for out, _ in d["links"])

def test_reconcile_creates_and_unmutes_once():
    cfg = _cfg([{"name": "Game", "target": "auto"}])
    d = routing.desired_state(cfg, physical_auto="HW")
    fresh = routing.reconcile(d, {"sinks": set()}, initialized=set())
    assert ("create_sink", "Game", "front-left,front-right") in fresh
    assert ("unmute", "Game") in fresh
    # already initialized -> recreate but DON'T re-unmute (respect a deliberate mute)
    again = routing.reconcile(d, {"sinks": set()}, initialized={"Game"})
    assert ("create_sink", "Game", "front-left,front-right") in again
    assert not any(a[0] == "unmute" for a in again)

def test_reconcile_unloads_cable_removed_from_config():
    # "Old" was ours (in initialized) and still present, but no longer in the config -> unload it
    cfg = _cfg([{"name": "Game", "target": "auto"}])
    d = routing.desired_state(cfg, physical_auto="HW")
    acts = routing.reconcile(d, {"sinks": {"Game", "Old"}}, initialized={"Game", "Old"})
    assert ("unload", "Old") in acts
    assert not any(a[0] == "unload" and a[1] == "Game" for a in acts)   # still desired -> kept

def test_reconcile_never_unloads_foreign_sink():
    # a present sink we never created (not in initialized) is left alone, even if not in config
    cfg = _cfg([{"name": "Game", "target": "auto"}])
    d = routing.desired_state(cfg, physical_auto="HW")
    acts = routing.reconcile(d, {"sinks": {"Game", "SomeAppSink"}}, initialized={"Game"})
    assert not any(a[0] == "unload" for a in acts)

def test_reconcile_existing_not_recreated():
    cfg = _cfg([{"name": "Game", "target": "auto"}])
    d = routing.desired_state(cfg, physical_auto="HW")
    acts = routing.reconcile(d, {"sinks": {"Game"}}, initialized=set())
    assert not any(a[0] == "create_sink" for a in acts)
    assert not any(a[0] == "unmute" for a in acts)

def test_apply_dispatches():
    calls = []
    class PW:
        def create_null_sink(self, *a): calls.append(("create",) + a)
        def set_sink_mute(self, *a):    calls.append(("mute",) + a)
        def link(self, *a):             calls.append(("link",) + a)
    class PW2(PW):
        def unload_null_sink(self, *a): calls.append(("unload",) + a)
    routing.apply([("create_sink", "Game", "front-left,front-right"),
                   ("unmute", "Game"), ("link", "a", "b"), ("unload", "Old")], PW2())
    assert ("create", "Game", "Game", "front-left,front-right") in calls
    assert ("mute", "Game", False) in calls
    assert ("link", "a", "b") in calls
    assert ("unload", "Old") in calls
