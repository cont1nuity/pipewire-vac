# tests/test_config.py
import pytest, config

GOOD = """
[[cable]]
name = "Game"
target = "Master"
[[cable]]
name = "Master"
target = "auto"
"""

def _write(tmp_path, text):
    p = tmp_path / "c.toml"; p.write_text(text); return str(p)

def test_defaults_fill_in(tmp_path):
    cfg = config.load(_write(tmp_path, GOOD))
    assert cfg["cable"][0]["channels"] == "stereo"     # default
    assert cfg["cable"][0]["target"] == "Master"
    assert cfg["cable"][1]["target"] == "auto"
    assert cfg["features"]["self_heal"] is True

def test_sourced_cable_defaults_to_no_output(tmp_path):
    # a virtual mic (has sources, no explicit target) must NOT default to "auto" -> no echo
    mic = '[[cable]]\nname="VoiceMix"\nsources=["auto"]\n'
    cfg = config.load(_write(tmp_path, mic))
    assert cfg["cable"][0]["target"] == ""
    # an explicit target on a sourced cable is still honored (mic that also outputs)
    both = '[[cable]]\nname="StreamMix"\nsources=["auto"]\ntarget="Master"\n[[cable]]\nname="Master"\ntarget="auto"\n'
    cfg = config.load(_write(tmp_path, both))
    assert cfg["cable"][0]["target"] == "Master"

def test_duplicate_cable_names_rejected(tmp_path):
    dup = '[[cable]]\nname="Game"\n[[cable]]\nname="Game"\n'
    with pytest.raises(config.ConfigError):
        config.load(_write(tmp_path, dup))

def test_bad_channels_rejected(tmp_path):
    bad = '[[cable]]\nname="Game"\nchannels="surround-9.1"\n'
    with pytest.raises(config.ConfigError):
        config.load(_write(tmp_path, bad))

def test_self_target_rejected(tmp_path):
    bad = '[[cable]]\nname="Game"\ntarget="Game"\n'
    with pytest.raises(config.ConfigError):
        config.load(_write(tmp_path, bad))

def test_cycle_rejected(tmp_path):
    cyc = '[[cable]]\nname="A"\ntarget="B"\n[[cable]]\nname="B"\ntarget="A"\n'
    with pytest.raises(config.ConfigError):
        config.load(_write(tmp_path, cyc))

def test_chain_to_hardware_is_not_a_cycle(tmp_path):
    ok = '[[cable]]\nname="A"\ntarget="B"\n[[cable]]\nname="B"\ntarget="auto"\n'
    config.load(_write(tmp_path, ok))      # 'auto' is a leaf -> no cycle

def test_app_rules_load_and_default_empty(tmp_path):
    cfg = config.load(_write(tmp_path, GOOD))
    assert cfg["app"] == []                # default when no [[app]] tables
    withapp = GOOD + '[[app]]\nmatch="spotify"\ntarget="Master"\n'
    cfg = config.load(_write(tmp_path, withapp))
    assert cfg["app"] == [{"match": "spotify", "target": "Master"}]

def test_app_empty_match_rejected(tmp_path):
    bad = GOOD + '[[app]]\nmatch=""\ntarget="Master"\n'
    with pytest.raises(config.ConfigError):
        config.load(_write(tmp_path, bad))

def test_app_missing_target_rejected(tmp_path):
    bad = GOOD + '[[app]]\nmatch="spotify"\n'
    with pytest.raises(config.ConfigError):
        config.load(_write(tmp_path, bad))
