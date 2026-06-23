# src/routing.py — desired state vs actual, minimal diff. No PipeWire calls here; that's pwgraph.
# A cable is a null sink; its monitor links to its `target` (another cable or a physical output).
# A cable may also pull hardware capture devices IN via `sources` — its monitor then doubles as
# a virtual mic apps can select. Output and source links are the same pw-link, opposite direction.

# Channel layout -> pactl channel_map string. Single source of truth for valid layouts.
LAYOUTS = {
    "mono":   "mono",
    "stereo": "front-left,front-right",
    "2.1":    "front-left,front-right,lfe",
    "5.1":    "front-left,front-right,front-center,lfe,rear-left,rear-right",
    "7.1":    "front-left,front-right,front-center,lfe,rear-left,rear-right,side-left,side-right",
}
# channel position -> pw-link port suffix.
# VERIFY against real `pw-link -l` output per layout before trusting (esp. LFE, mono->MONO).
SUFFIX = {
    "front-left": "FL", "front-right": "FR", "front-center": "FC", "lfe": "LFE",
    "rear-left": "RL", "rear-right": "RR", "side-left": "SL", "side-right": "SR", "mono": "MONO",
}


def _suffixes(channel_map):
    return [SUFFIX[c.strip()] for c in channel_map.split(",")]


def _source_links(src, cable_name, cable_channels, src_sufs):
    """Wire a hardware capture device into a cable, given the source's actual capture-port
    suffixes (`src_sufs`, detected live — most analog mics are stereo FL/FR, USB mics often a
    single port). A single-port mic into a stereo+ cable fans out to the front L/R pair; anything
    else links the channels the source and cable share (no downmix). Empty `src_sufs` (source not
    present yet) yields no links — it heals on a later poll once the device appears."""
    if not src_sufs:
        return []
    cable_sufs = _suffixes(LAYOUTS[cable_channels])
    if len(src_sufs) == 1 and cable_channels != "mono":           # mono mic -> fan to front L/R
        port = src_sufs[0]
        return [(f"{src}:capture_{port}", f"{cable_name}:playback_{s}")
                for s in ("FL", "FR") if s in cable_sufs]
    return [(f"{src}:capture_{s}", f"{cable_name}:playback_{s}")  # match shared channels
            for s in src_sufs if s in cable_sufs]


def desired_state(cfg, physical_auto, source_ports=None, physical_source_auto=None):
    """sinks to create + links to make. `physical_auto` resolves a cable whose target is 'auto'
    (first physical output); None means no physical sink is present. `source_ports` is
    {source_name: [capture suffixes]} from pwgraph.source_ports — runtime-detected, like
    physical_auto; default {} means no capture sources are wired. `physical_source_auto` resolves
    a `sources = ["auto"]` entry to the first physical mic (None → that entry is skipped)."""
    source_ports = source_ports or {}
    cables = cfg["cable"]
    sinks = [{"name": c["name"], "channel_map": LAYOUTS[c["channels"]]} for c in cables]

    links = []
    for c in cables:
        tgt = physical_auto if c["target"] == "auto" else c["target"]
        if not tgt:                       # auto with no physical sink -> leave this cable unwired
            continue
        for suf in _suffixes(LAYOUTS[c["channels"]]):
            links.append((f'{c["name"]}:monitor_{suf}', f"{tgt}:playback_{suf}"))

    for c in cables:                          # hardware captures wired INTO a cable (virtual mic)
        for src in c.get("sources", []):
            name = physical_source_auto if src == "auto" else src
            if not name:                      # 'auto' with no physical mic -> skip, heals later
                continue
            links += _source_links(name, c["name"], c["channels"], source_ports.get(name, []))
    return {"sinks": sinks, "links": links}


def reconcile(desired, snap, initialized):
    """Surgical, create-if-missing. One-time unmute on a cable's first-ever creation (name not yet
    in `initialized`). The sole teardown: unload a cable WE created (in `initialized`, present in
    `snap`) once it's gone from the config — never a link or a sink we didn't make."""
    actions = []
    desired_names = {s["name"] for s in desired["sinks"]}
    for s in desired["sinks"]:
        if s["name"] not in snap["sinks"]:             # create-if-missing; never teardown
            actions.append(("create_sink", s["name"], s["channel_map"]))
            if s["name"] not in initialized:           # set-once: unmute only on first-ever create
                actions.append(("unmute", s["name"]))
    for out, inp in desired["links"]:
        actions.append(("link", out, inp))             # fire-and-forget; pw-link ignores dup/missing
    for name in sorted((snap["sinks"] & initialized) - desired_names):
        actions.append(("unload", name))               # ours + present + removed from config
    return actions


def apply(actions, pw):
    for a in actions:
        k = a[0]
        if   k == "create_sink": pw.create_null_sink(a[1], a[1], a[2])   # description = name
        elif k == "unmute":      pw.set_sink_mute(a[1], False)
        elif k == "link":        pw.link(a[1], a[2])
        elif k == "unload":      pw.unload_null_sink(a[1])
