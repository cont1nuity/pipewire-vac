# tests/test_apps.py — matching + move-once routing (no hardware; pw is injected).
import apps


def _si(index=1, app="", binary="", media=""):
    return {"index": index, "app": app, "binary": binary, "media": media}


# ---- matches() ---------------------------------------------------------------

def test_literal_matches_app_binary_or_media():
    assert apps.matches("spotify", _si(app="Spotify"))
    assert apps.matches("firefox", _si(binary="/usr/bin/firefox"))
    assert apps.matches("audio-src", _si(media="audio-src"))
    assert not apps.matches("spotify", _si(app="Firefox", binary="firefox", media="a song"))


def test_alternatives_split_on_pipe():
    assert apps.matches("discord|mumble", _si(app="Mumble"))
    assert not apps.matches("discord|mumble", _si(app="Slack"))


def test_match_is_case_insensitive():
    assert apps.matches("SPOTIFY", _si(app="spotify"))


def test_alias_expands_to_curated_list():
    assert apps.matches("voice", _si(binary="/usr/bin/discord"))
    assert apps.matches("browser", _si(app="Firefox"))
    assert apps.matches("media", _si(binary="vlc"))
    assert apps.matches("game", _si(binary="Z:/games/foo.exe"))


def test_alias_does_not_match_media_name():
    # a song titled "discord" must not trip the voice alias (alias matches app/binary only)
    assert not apps.matches("voice", _si(media="discord live set"))


# ---- route_once() ------------------------------------------------------------

class FakePw:
    def __init__(self, inputs):
        self._inputs = inputs
        self.moves = []

    def list_sink_inputs(self):
        return self._inputs

    def move_sink_input(self, index, sink):
        self.moves.append((index, sink))


def _cfg(rules):
    return {"app": rules}


def test_matching_stream_moved_once_then_hands_off():
    pw = FakePw([_si(index=7, app="Spotify")])
    moved = {}
    cfg = _cfg([{"match": "spotify", "target": "Media"}])

    assert apps.route_once(cfg, moved, pw) == 1
    assert pw.moves == [(7, "Media")]
    # second poll: same stream, same target already applied -> no further move
    assert apps.route_once(cfg, moved, pw) == 0
    assert pw.moves == [(7, "Media")]


def test_target_change_reapplies_to_existing_stream():
    pw = FakePw([_si(index=7, app="Spotify")])
    moved = {}
    apps.route_once(_cfg([{"match": "spotify", "target": "Media"}]), moved, pw)
    assert pw.moves == [(7, "Media")]
    # config edited: same running stream, rule target Media -> Voice -> re-apply
    apps.route_once(_cfg([{"match": "spotify", "target": "Voice"}]), moved, pw)
    assert pw.moves == [(7, "Media"), (7, "Voice")]
    # ...and once re-applied, it hands off again at the new target
    assert apps.route_once(_cfg([{"match": "spotify", "target": "Voice"}]), moved, pw) == 0


def test_disappeared_stream_is_pruned_so_reused_index_routes_again():
    cfg = _cfg([{"match": "spotify", "target": "Media"}])
    moved = {}
    pw = FakePw([_si(index=7, app="Spotify")])
    apps.route_once(cfg, moved, pw)            # moves 7, moved={7: "Media"}

    pw._inputs = []                            # stream 7 gone
    apps.route_once(cfg, moved, pw)            # prune -> moved={}
    assert moved == {}

    pw._inputs = [_si(index=7, app="Spotify")]  # index 7 reused by a fresh stream
    pw.moves = []
    assert apps.route_once(cfg, moved, pw) == 1
    assert pw.moves == [(7, "Media")]


def test_non_matching_stream_not_moved():
    pw = FakePw([_si(index=3, app="Firefox")])
    assert apps.route_once(_cfg([{"match": "spotify", "target": "Media"}]), {}, pw) == 0
    assert pw.moves == []


def test_no_rules_is_noop():
    pw = FakePw([_si(index=3, app="Firefox")])
    assert apps.route_once({}, {}, pw) == 0
    assert pw.moves == []


def test_first_matching_rule_wins():
    pw = FakePw([_si(index=5, app="Discord")])
    cfg = _cfg([
        {"match": "discord", "target": "Voice"},
        {"match": "discord", "target": "Media"},
    ])
    apps.route_once(cfg, {}, pw)
    assert pw.moves == [(5, "Voice")]


# ---- "default" catch-all -----------------------------------------------------

def test_default_rule_routes_unmatched_streams():
    pw = FakePw([_si(index=9, app="SomeRandomApp")])
    cfg = _cfg([
        {"match": "spotify", "target": "Media"},
        {"match": "default", "target": "Master"},
    ])
    apps.route_once(cfg, {}, pw)
    assert pw.moves == [(9, "Master")]


def test_specific_rule_takes_precedence_over_default():
    pw = FakePw([_si(index=7, app="Spotify"), _si(index=9, app="Random")])
    cfg = _cfg([
        {"match": "spotify", "target": "Media"},
        {"match": "default", "target": "Master"},
    ])
    apps.route_once(cfg, {}, pw)
    assert sorted(pw.moves) == [(7, "Media"), (9, "Master")]


def test_default_is_position_independent():
    # 'default' listed FIRST must still only catch the unmatched, not everything
    pw = FakePw([_si(index=7, app="Spotify")])
    cfg = _cfg([
        {"match": "default", "target": "Master"},
        {"match": "spotify", "target": "Media"},
    ])
    apps.route_once(cfg, {}, pw)
    assert pw.moves == [(7, "Media")]


def test_no_default_leaves_unmatched_alone():
    pw = FakePw([_si(index=9, app="Random")])
    apps.route_once(_cfg([{"match": "spotify", "target": "Media"}]), {}, pw)
    assert pw.moves == []
