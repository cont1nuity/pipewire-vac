# tests/test_configui.py
import tomllib
import config, configui

GOOD = ('[[cable]]\nname="Game"\nchannels="5.1"\ntarget="Master"\n'
        '[[cable]]\nname="Master"\ntarget="auto"\n')

def test_dump_config_roundtrips(tmp_path):
    p = tmp_path / "c.toml"; p.write_text(GOOD)
    cfg = config.load(str(p))
    back = tomllib.loads(configui.dump_config(cfg))
    assert [c["name"] for c in back["cable"]] == ["Game", "Master"]
    assert back["cable"][0]["channels"] == "5.1"
    assert back["cable"][0]["target"] == "Master"

def test_dump_config_reloads_clean(tmp_path):
    p = tmp_path / "c.toml"; p.write_text(GOOD)
    cfg = config.load(str(p))
    p.write_text(configui.dump_config(cfg))
    config.load(str(p))                  # serialized output is valid TOML + schema-clean

def test_dump_config_preserves_sources(tmp_path):
    text = ('[[cable]]\nname="VoiceMix"\nchannels="stereo"\ntarget="auto"\n'
            'sources=["mic0","mic1"]\n')
    p = tmp_path / "c.toml"; p.write_text(text)
    cfg = config.load(str(p))
    back = tomllib.loads(configui.dump_config(cfg))
    assert back["cable"][0]["sources"] == ["mic0", "mic1"]
    p.write_text(configui.dump_config(cfg)); config.load(str(p))   # reloads clean

def test_mic_picker_roundtrips_label_and_special_cases():
    l2n = {"Built-in Audio Analog Stereo (physical)": "alsa_input.pci.analog-stereo"}
    n2l = {v: k for k, v in l2n.items()}
    # display: sources list -> label (a mic row always has a source -> empty defaults to auto)
    assert configui.mic_display([], n2l) == configui.MIC_AUTO
    assert configui.mic_display(["auto"], n2l) == configui.MIC_AUTO
    assert configui.mic_display(["alsa_input.pci.analog-stereo"], n2l).endswith("(physical)")
    assert configui.mic_display(["a", "b"], n2l) == configui.MIC_MULTI
    assert configui.mic_display(["unplugged.mic"], n2l) == "unplugged.mic"   # unknown -> raw name
    # save: label -> sources list
    assert configui.mic_to_sources(configui.MIC_AUTO, [], l2n) == ["auto"]
    assert configui.mic_to_sources("Built-in Audio Analog Stereo (physical)", [], l2n) == \
        ["alsa_input.pci.analog-stereo"]
    # MULTI preserved verbatim — the data-loss guard for a TOML-set 2+ mic list
    assert configui.mic_to_sources(configui.MIC_MULTI, ["a", "b"], l2n) == ["a", "b"]

def test_target_picker_maps_label_and_none():
    l2n = {"Built-in Audio Analog Stereo (physical)": "alsa_output.pci.analog-stereo"}
    n2l = {v: k for k, v in l2n.items()}
    # display: stored -> label
    assert configui.target_display("", n2l) == configui.TARGET_NONE
    assert configui.target_display("auto", n2l) == "auto"
    assert configui.target_display("Master", n2l) == "Master"           # cable name passes through
    assert configui.target_display("alsa_output.pci.analog-stereo", n2l).endswith("(physical)")
    # store: label -> stored
    assert configui.target_store(configui.TARGET_NONE, l2n) == ""
    assert configui.target_store("auto", l2n) == "auto"
    assert configui.target_store("Master", l2n) == "Master"
    assert configui.target_store("Built-in Audio Analog Stereo (physical)", l2n) == \
        "alsa_output.pci.analog-stereo"

def test_dump_config_roundtrips_app_rules(tmp_path):
    text = GOOD + '[[app]]\nmatch="spotify|vlc"\ntarget="Master"\n'
    p = tmp_path / "c.toml"; p.write_text(text)
    cfg = config.load(str(p))
    back = tomllib.loads(configui.dump_config(cfg))
    assert back["app"] == [{"match": "spotify|vlc", "target": "Master"}]
    p.write_text(configui.dump_config(cfg)); config.load(str(p))   # reloads clean
