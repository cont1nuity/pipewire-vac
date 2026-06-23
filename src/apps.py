# src/apps.py — app->cable auto-assignment: match an app's audio stream and move it once.
#
# Move-once, then hands off: a matching stream is routed to its target once per appearance,
# tracked as {sink-input index: target last applied} in the caller's `moved` dict. A manual
# pavucontrol drag doesn't change the computed target, so we leave it; editing the rule's
# target re-applies. A `match = "default"` rule catches anything no specific rule matched.
# Structure-only, same philosophy as the one-time cable unmute. See the 2026-06-23 spec.
import pwgraph

# Alias name -> curated '|'-list of substrings. Single source of truth (the GUI reads the keys
# for its match dropdown). Alias parts match app-name/binary only, never media.name.
ALIASES = {
    "browser": "firefox|waterfox|librewolf|floorp|zen|chrom|brave|opera|vivaldi|edge|falkon|epiphany",
    "game":    "wine|proton|.exe|steam_app|gamescope|lutris",
    "media":   "vlc|mpv|mplayer|smplayer|celluloid|totem|kodi|spotify|rhythmbox|clementine|strawberry|audacious|deadbeef|elisa|lollypop",
    "voice":   "discord|vesktop|webcord|teamspeak|ts3client|mumble|skype|zoom|slack|telegram|signal-desktop|element",
}


def matches(match_str, si):
    """Case-insensitive substring match. '|' separates alternatives; an alias name expands to
    its curated list. Literal parts match app/binary/media; alias parts match app/binary only
    (so a song title in media.name can't trip the 'media'/'voice' alias)."""
    full, appbin = [], []
    for part in match_str.split("|"):
        p = part.strip().lower()
        if not p:
            continue
        if p in ALIASES:
            appbin += ALIASES[p].split("|")
        else:
            full.append(p)
    a, b, m = si["app"].lower(), si["binary"].lower(), si["media"].lower()
    return (any(n in a or n in b or n in m for n in full)
            or any(n in a or n in b for n in appbin))


def _is_default(rule):
    return rule["match"].strip().lower() == "default"

def _match_target(rules, si):
    """First specific rule (config order) whose match hits this stream, else None."""
    for r in rules:
        if matches(r["match"], si):
            return r["target"]
    return None

def route_once(cfg, moved, pw=pwgraph):
    """Auto-assign app streams to their target sink. `moved` is a dict {sink-input index:
    target we last moved it to} the caller persists across polls (mutated here).

    Move-once, then hands off: a stream is moved only when its computed target differs from
    what we last applied. A manual pavucontrol drag doesn't change the computed target, so we
    leave it; editing the rule's target DOES, so we re-apply. A `match = "default"` rule is the
    catch-all for any stream no specific rule matched (position-independent). Returns the count
    moved this call."""
    rules = cfg.get("app", [])
    if not rules:
        return 0
    specific = [r for r in rules if not _is_default(r)]
    default = next((r["target"] for r in rules if _is_default(r)), None)
    inputs = pw.list_sink_inputs()
    live = {si["index"] for si in inputs}
    for i in list(moved):                     # forget streams that died (also handles index reuse)
        if i not in live:
            del moved[i]
    n = 0
    for si in inputs:
        target = _match_target(specific, si)
        if target is None:
            target = default                  # fall back to the catch-all, if any
        if target is None or moved.get(si["index"]) == target:
            continue                          # nothing matched, or this target already applied
        pw.move_sink_input(si["index"], target)
        moved[si["index"]] = target
        n += 1
    return n
