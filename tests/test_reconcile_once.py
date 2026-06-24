# tests/test_reconcile_once.py
import config, main, state

def _cfg():
    c = config._merge(config.DEFAULTS, {"cable": [
        {"name": "Game", "target": "Master"}, {"name": "Master", "target": "auto"}]})
    c["cable"] = [config._merge(config._CABLE_DEFAULTS, x) for x in c["cable"]]
    return c

def test_reconcile_once_creates_and_marks(tmp_path, monkeypatch):
    monkeypatch.setattr(state.paths, "XDG_STATE", str(tmp_path))
    monkeypatch.setattr(main.pwgraph, "snapshot", lambda our: {"sinks": {"HW"}})
    monkeypatch.setattr(main.pwgraph, "first_physical_sink", lambda sinks, our: "HW")
    recorded = []
    monkeypatch.setattr(main.routing, "apply", lambda acts, pw: recorded.extend(acts))
    summary = main.reconcile_once(_cfg())
    assert summary == {"cables": 2, "created": 2, "removed": 0}
    assert any(a[0] == "create_sink" and a[1] == "Master" for a in recorded)
    assert any(a[0] == "unmute" for a in recorded)
    assert state.load() == {"Game", "Master"}          # ledger updated

def test_reconcile_once_unloads_and_forgets_removed_cable(tmp_path, monkeypatch):
    monkeypatch.setattr(state.paths, "XDG_STATE", str(tmp_path))
    state.mark({"Game", "Master", "Old"})               # "Old" was a cable we created once
    monkeypatch.setattr(main.pwgraph, "snapshot", lambda our: {"sinks": {"Game", "Master", "Old"}})
    monkeypatch.setattr(main.pwgraph, "first_physical_sink", lambda sinks, our: "HW")
    recorded = []
    monkeypatch.setattr(main.routing, "apply", lambda acts, pw: recorded.extend(acts))
    summary = main.reconcile_once(_cfg())               # config now has Game + Master, not "Old"
    assert ("unload", "Old") in recorded
    assert summary["removed"] == 1
    assert state.load() == {"Game", "Master"}           # "Old" forgotten -> re-add unmutes again

def test_reconcile_once_unmute_only_first_time(tmp_path, monkeypatch):
    monkeypatch.setattr(state.paths, "XDG_STATE", str(tmp_path))
    state.mark({"Game", "Master"})                      # pretend already initialized
    monkeypatch.setattr(main.pwgraph, "snapshot", lambda our: {"sinks": set()})
    monkeypatch.setattr(main.pwgraph, "first_physical_sink", lambda sinks, our: "HW")
    recorded = []
    monkeypatch.setattr(main.routing, "apply", lambda acts, pw: recorded.extend(acts))
    main.reconcile_once(_cfg())
    assert any(a[0] == "create_sink" for a in recorded)
    assert not any(a[0] == "unmute" for a in recorded)  # respect prior init across recreation

def test_reconcile_once_skips_on_failed_read(tmp_path, monkeypatch):
    # pactl wedged/timed out (snapshot ok=False): a blind read makes every cable look missing.
    # Re-creating on it is what leaked duplicate null-sinks and wedged the whole audio stack.
    monkeypatch.setattr(state.paths, "XDG_STATE", str(tmp_path))
    monkeypatch.setattr(main.pwgraph, "snapshot", lambda our: {"sinks": set(), "ok": False})
    recorded = []
    monkeypatch.setattr(main.routing, "apply", lambda acts, pw: recorded.extend(acts))
    summary = main.reconcile_once(_cfg())
    assert recorded == []                                # NOTHING applied — no create_sink storm
    assert summary == {"cables": 0, "created": 0, "removed": 0}

def test_reconcile_once_never_unmutes_a_preexisting_cable(tmp_path, monkeypatch):
    monkeypatch.setattr(state.paths, "XDG_STATE", str(tmp_path))
    # both cables already exist (e.g. the old bash script made them) and the ledger is empty
    monkeypatch.setattr(main.pwgraph, "snapshot", lambda our: {"sinks": {"Game", "Master"}})
    monkeypatch.setattr(main.pwgraph, "first_physical_sink", lambda sinks, our: "HW")
    recorded = []
    monkeypatch.setattr(main.routing, "apply", lambda acts, pw: recorded.extend(acts))
    main.reconcile_once(_cfg())
    assert not any(a[0] == "unmute" for a in recorded)   # never unmute a cable we didn't create
    assert state.load() == {"Game", "Master"}            # but record them, so a later restart +
                                                          # recreate won't unmute them either
