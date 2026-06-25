# src/pwgraph.py — the ONLY module that touches PipeWire. One door in, one door out.
import subprocess

def run(cmd):
    """Single chokepoint for every PipeWire CLI call. Tests monkeypatch this.
    timeout: a wedged pactl/pw-link must NOT freeze the 2s heal loop forever — on timeout we
    return rc=124 so callers treat it as a failed read (snapshot below refuses to create on it)."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, "", "timeout")

def _names(stdout):
    out = set()
    for line in stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[1]:
            out.add(parts[1])
    return out

def list_sinks():    return _names(run(["pactl", "list", "short", "sinks"]).stdout)
def list_sources():  return _names(run(["pactl", "list", "short", "sources"]).stdout)

def _qval(line):  # `key = "value"` -> value
    return line.split("=", 1)[1].strip().strip('"')

def _int(s):
    try:    return int(s.strip())
    except ValueError: return -1

def _client_names():
    """{client index: [app, binary]} from `pactl list clients`."""
    cur, names = None, {}
    for raw in run(["pactl", "list", "clients"]).stdout.splitlines():
        line = raw.strip()
        if line.startswith("Client #"):
            cur = _int(line.split("#")[1]); names[cur] = ["", ""]
        elif cur is None:
            continue
        elif line.startswith("application.name ="):           names[cur][0] = _qval(line)
        elif line.startswith("application.process.binary ="): names[cur][1] = _qval(line)
    return names

def list_sink_inputs():
    """[{index, app, binary, media}] from `pactl list sink-inputs`. An anonymous stream (no
    application.* of its own — e.g. Spotify via its own PipeWire loop) inherits name/binary
    from its owning Client, so matching still works."""
    clients = _client_names()
    cur, items = None, []
    for raw in run(["pactl", "list", "sink-inputs"]).stdout.splitlines():
        line = raw.strip()
        if line.startswith("Sink Input #"):
            cur = {"index": _int(line.split("#")[1]), "app": "", "binary": "", "media": "", "_client": None}
            items.append(cur)
        elif cur is None:
            continue
        elif line.startswith("Client:"):                      cur["_client"] = _int(line.split(":", 1)[1])
        elif line.startswith("application.name ="):           cur["app"] = _qval(line)
        elif line.startswith("application.process.binary ="): cur["binary"] = _qval(line)
        elif line.startswith("media.name ="):                 cur["media"] = _qval(line)
    for si in items:
        ca, cb = clients.get(si.pop("_client"), ["", ""])
        si["app"] = si["app"] or ca
        si["binary"] = si["binary"] or cb
    return items

def first_physical_sink(sinks, our_names):
    """Resolve a target of 'auto' to a real hardware output. Prefer alsa_output./bluez_output.
    (actual devices); fall back to any non-cable, non-monitor sink so it still works on odd
    naming. Excludes our own cables and monitors."""
    cands = [n for n in sorted(sinks) if n not in our_names and not n.endswith(".monitor")]
    for n in cands:
        if n.startswith(("alsa_output.", "bluez_output.")):
            return n
    return cands[0] if cands else None

def first_physical_source():
    """Resolve a source of 'auto' to a real capture device (mic). Prefer alsa_input./bluez_input.;
    exclude monitors (a sink's .monitor also appears as a source). Read-only discovery — like
    first_physical_sink, it NEVER sets the system default source."""
    cands = [n for n in sorted(list_sources()) if not n.endswith(".monitor")]
    for n in cands:
        if n.startswith(("alsa_input.", "bluez_input.")):
            return n
    return cands[0] if cands else None

def _name_desc(stdout):
    """[(name, description)] from a `pactl list sinks|sources` dump (Name: precedes Description:
    in each device block)."""
    name, out = None, []
    for raw in stdout.splitlines():
        line = raw.strip()
        if line.startswith("Name:"):
            name = line.split(":", 1)[1].strip()
        elif line.startswith("Description:") and name:
            out.append((name, line.split(":", 1)[1].strip())); name = None
    return out

def source_labels():
    """[(name, description)] for real capture devices (mics) — excludes .monitor sources. The
    description is the friendly label shown in the UI mic picker; the name is what gets stored."""
    return [(n, d) for n, d in _name_desc(run(["pactl", "list", "sources"]).stdout)
            if not n.endswith(".monitor")]

def sink_labels(our_names):
    """[(name, description)] for physical output sinks — excludes our cables and monitors. The
    description is the friendly label shown in the Target dropdowns; the name is what gets stored."""
    return [(n, d) for n, d in _name_desc(run(["pactl", "list", "sinks"]).stdout)
            if n not in our_names and not n.endswith(".monitor")]

def source_ports(names):
    """{name: [capture-port suffix, ...]} for the given capture sources, from one `pw-link -o`
    listing (output ports = sources' capture ports). e.g. {'mic': ['FL','FR']} or {'mic':
    ['MONO']}. Empty list for a source not currently present. Lets routing match a stereo mic
    channel-for-channel and fan a single-port mono mic out — without the user declaring layout."""
    res = {n: [] for n in names}
    if not names:
        return res
    for raw in run(["pw-link", "-o"]).stdout.splitlines():
        port = raw.strip()
        for n in names:
            pre = f"{n}:capture_"
            if port.startswith(pre):
                res[n].append(port[len(pre):])
    return res

def _links(stdout):
    """Existing graph links as a set of (output_port, input_port), parsed from one `pw-link -l`.
    A top-level line is a port; an indented `|-> X` is current(output)->X(input), `|<- Y` is
    Y(output)->current(input). Port names may contain spaces, so we keep everything after the
    arrow. Either arrow alone would catch every link; parsing both just dedupes into the set."""
    links, cur = set(), None
    for raw in stdout.splitlines():
        if not raw.strip():
            continue
        if not raw.startswith(" "):
            cur = raw.strip()
        elif cur is not None:
            s = raw.strip()
            if   s.startswith("|-> "): links.add((cur, s[4:]))
            elif s.startswith("|<- "): links.add((s[4:], cur))
    return links

def snapshot(our_names):
    # "ok" lets the reconciler distinguish "pactl answered with these sinks" from "pactl didn't
    # answer" (wedged/timed out -> rc!=0). Creating cables on a blind read is how we leaked
    # duplicate null-sinks: an empty/failed listing made every cable look missing -> re-load.
    # "links"/"links_ok": one pw-link -l read so reconcile fires pw-link ONLY for missing links
    # instead of every link every poll — that blind re-fire was ~N short-lived PipeWire clients
    # per poll (a wireplumber GWeakRef-leak driver). links_ok=False (read failed) falls back to
    # fire-all, same as before, since we then can't tell what's wired.
    r = run(["pactl", "list", "short", "sinks"])
    lr = run(["pw-link", "-l"])
    return {"sinks": _names(r.stdout), "ok": r.returncode == 0,
            "links": _links(lr.stdout), "links_ok": lr.returncode == 0}

# --- actions (all route through run()) ---
def create_null_sink(name, description, channel_map):
    run(["pactl", "load-module", "module-null-sink",
         f"sink_name={name}",
         f'sink_properties=device.description="{description}"',
         f"channel_map={channel_map}"])

def set_sink_mute(name, on): run(["pactl", "set-sink-mute", name, "1" if on else "0"])
def link(out_port, in_port): run(["pw-link", out_port, in_port])  # nonzero == already linked / no port; ignored
def move_sink_input(index, sink): run(["pactl", "move-sink-input", str(index), sink])  # bad sink ignored

def _null_sink_module(name):
    """Module index of the module-null-sink whose sink_name == `name`, else None."""
    idx, is_null = None, False
    for raw in run(["pactl", "list", "modules"]).stdout.splitlines():
        line = raw.strip()
        if line.startswith("Module #"):
            idx, is_null = _int(line.split("#")[1]), False
        elif line.startswith("Name:"):
            is_null = "module-null-sink" in line
        elif line.startswith("Argument:") and is_null and f"sink_name={name}" in line.split():
            return idx
    return None

def unload_null_sink(name):
    """Unload the module-null-sink that owns sink `name` (reverses create_null_sink). No-op if not
    found. The app's ONE teardown — used only to remove a cable deleted from config; the heal loop
    never tears down links or sinks it didn't create."""
    idx = _null_sink_module(name)
    if idx is not None:
        run(["pactl", "unload-module", str(idx)])
