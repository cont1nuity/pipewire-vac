# src/firstrun.py — preflight. The three things that go wrong on a fresh machine,
# each with an exact instruction on stderr (systemd routes it to the journal).
import os, sys, shutil
import paths

REQUIRED_TOOLS = ["pactl", "pw-link", "pw-dump"]

def _check_tools():
    missing = [t for t in REQUIRED_TOOLS if shutil.which(t) is None]
    if missing:
        sys.exit("missing required tools: %s — install PipeWire's CLI utilities"
                 % ", ".join(missing))

def _ensure_config(config_arg):
    """Resolve the config path. With no explicit --config, fall back to the XDG home,
    seeding it from config.example.toml on first run so the daemon never crash-loops
    on a missing file."""
    if config_arg:
        return config_arg
    path = paths.config_path()
    if not os.path.exists(path):
        example = os.path.join(paths.ROOT, "config.example.toml")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        shutil.copyfile(example, path)
        print(f"seeded default config at {path} (edit cable targets for this machine)",
              file=sys.stderr)
    return path

def preflight(config_arg=None):
    import main                       # for the shared PipeWire wait loop
    _check_tools()
    if not main._wait_for_pipewire():
        sys.exit("PipeWire not ready after retries")
    return _ensure_config(config_arg)
