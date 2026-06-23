# src/state.py — the "initialized" ledger. Records which cables have had their one-time
# unmute, so a recreation (pipewire restart / self-heal) never re-unmutes a cable the user
# muted on purpose. This is the whole mechanism behind "set once, never re-force".
import os, json
import paths

def _path():
    return os.path.join(paths.XDG_STATE, "state.json")

def load():
    """Set of cable names already initialized. Missing/corrupt file -> empty set."""
    try:
        with open(_path()) as f:
            return set(json.load(f).get("initialized", []))
    except (OSError, ValueError):
        return set()

def mark(names):
    """Union `names` into the ledger and persist. No-op if nothing new."""
    names = set(names)
    current = load()
    if names <= current:
        return
    _write(current | names)

def drop(names):
    """Remove `names` from the ledger (a cable torn down because it left the config), so a later
    re-add gets its one-time unmute again. No-op if none are present."""
    names = set(names)
    current = load()
    if not (names & current):
        return
    _write(current - names)

def _write(names):
    p = _path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        json.dump({"initialized": sorted(names)}, f)
