# tests/test_tray.py — pure (no dbus/network/Tk) helpers behind the AppImage update check.
import tray


def test_ver_tuple():
    assert tray._ver_tuple("v1.2.0") == (1, 2, 0)
    assert tray._ver_tuple("1.10.3") == (1, 10, 3)
    assert tray._ver_tuple("dev") is None          # non-release -> never nagged
    assert tray._ver_tuple("1.2.0") < tray._ver_tuple("1.2.1")


def test_write_preserves_other_lines_and_comments(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("[features]\nself_heal = true  # keep me\ncheck_updates = true\n")
    tray.write_check_updates(str(p), False)
    txt = p.read_text()
    assert "check_updates = false" in txt
    assert "# keep me" in txt and "self_heal = true" in txt
    assert tray.read_check_updates(str(p)) is False


def test_write_inserts_key_into_existing_features(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("[features]\nself_heal = true\n")
    tray.write_check_updates(str(p), False)
    assert tray.read_check_updates(str(p)) is False
    assert "self_heal = true" in p.read_text()


def test_write_creates_features_table_when_absent(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("config_version = 2\n[[cable]]\nname = 'Game'\n")
    tray.write_check_updates(str(p), True)
    assert "[features]" in p.read_text()
    assert tray.read_check_updates(str(p)) is True


def test_read_defaults_true(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("config_version = 2\n")           # no [features] -> default on
    assert tray.read_check_updates(str(p)) is True
    assert tray.read_check_updates("") is True      # no path -> default on
