# src/config.py — load + validate the v2 TOML (cables with name/channels/target).
import tomllib
from routing import LAYOUTS

class ConfigError(Exception):
    pass

DEFAULTS = {
    "config_version": 2,
    "cable": [],
    "app": [],
    "features": {"self_heal": True},
}
_CABLE_DEFAULTS = {"channels": "stereo", "target": "auto", "sources": []}

def _merge(base, over):
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out

def load(path):
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    cfg = _merge(DEFAULTS, raw)
    cfg["cable"] = [_cable_defaults(c) for c in cfg.get("cable", [])]
    _validate(cfg)
    return cfg

def _cable_defaults(c):
    out = _merge(_CABLE_DEFAULTS, c)
    if "target" not in c and c.get("sources"):
        out["target"] = ""        # a source-only cable (virtual mic) doesn't echo to an output
    return out

def _validate(cfg):
    names = []
    for c in cfg["cable"]:
        name = c.get("name")
        if not name:
            raise ConfigError("every [[cable]] needs a name")
        if name in names:
            raise ConfigError(f"duplicate cable name: {name}")
        names.append(name)
        if c["channels"] not in LAYOUTS:
            raise ConfigError(f"unknown channels {c['channels']!r} for {name} "
                              f"(use one of: {', '.join(LAYOUTS)})")
        if c["target"] == name:
            raise ConfigError(f"cable {name} cannot target itself")
        if not isinstance(c.get("sources", []), list):
            raise ConfigError(f"cable {name}: sources must be a list of capture-source names")
    _check_cycles(cfg["cable"])
    for r in cfg["app"]:
        if not r.get("match"):
            raise ConfigError("every [[app]] needs a non-empty match")
        if not r.get("target"):
            raise ConfigError(f"[[app]] {r['match']!r} needs a target")

def _check_cycles(cables):
    """Reject cycles among cable->cable targets. cable->hardware/'auto' targets are leaves."""
    target = {c["name"]: c["target"] for c in cables}
    for start in target:
        seen, node = set(), start
        while node in target:              # node is a cable that points somewhere
            if node in seen:
                raise ConfigError(f"target cycle involving cable {node!r}")
            seen.add(node)
            node = target[node]            # follow to its target (cable name, or hardware/'auto' -> ends)
