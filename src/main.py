# src/main.py — entry point. Wait for PipeWire, load config, reconcile once, apply, exit.
import sys, time, argparse
import paths, config, pwgraph, routing, state

VERSION = "dev"   # stamped by packaging/build-appimage.sh (keep the `VERSION = ` prefix)

def _wait_for_pipewire(tries=10, delay=1.0):
    for _ in range(tries):
        if pwgraph.run(["pactl", "info"]).returncode == 0:
            return True
        time.sleep(delay)
    return False

def _our_names(cfg):
    return {c["name"] for c in cfg["cable"]}

def _selftest():
    cfg = config._merge(config.DEFAULTS, {"cable": [
        {"name": "Game", "target": "Master"}, {"name": "Master", "target": "auto"}]})
    cfg["cable"] = [config._merge(config._CABLE_DEFAULTS, c) for c in cfg["cable"]]
    d = routing.desired_state(cfg, physical_auto="HW")
    acts = routing.reconcile(d, {"sinks": set()}, initialized=set())
    ok = any(a[0] == "create_sink" and a[1] == "Master" for a in acts)
    print(f"selftest: {len(acts)} actions planned, master_created={ok}")
    return 0 if ok else 1

def reconcile_once(cfg):
    """One full structural reconcile against the live graph. Creates missing cables, links
    each to its target, unmutes each once (ledger-tracked). Never touches volume/default/mic."""
    our = _our_names(cfg)
    snap = pwgraph.snapshot(our)
    physical_auto = pwgraph.first_physical_sink(snap["sinks"], our)
    initialized = state.load()

    srcs = {s for c in cfg["cable"] for s in c.get("sources", [])}
    physical_source_auto = pwgraph.first_physical_source() if "auto" in srcs else None
    resolved = {physical_source_auto if s == "auto" else s for s in srcs} - {None}
    source_ports = pwgraph.source_ports(resolved)   # one pw-link call; {} when no sources configured
    d = routing.desired_state(cfg, physical_auto, source_ports, physical_source_auto)
    acts = routing.reconcile(d, snap, initialized)
    routing.apply(acts, pwgraph)

    names = {s["name"] for s in d["sinks"]}
    created = names - snap["sinks"]
    removed = {a[1] for a in acts if a[0] == "unload"}   # cables we tore down (left the config)
    state.mark(names)        # record every cable that exists now (created OR already present):
                             # we unmute only a cable we create from nothing, never one that
                             # already existed — its mute is the user's, not ours to clear.
    if removed:
        state.drop(removed)  # forget torn-down cables so a re-add unmutes once again
    return {"cables": len(d["sinks"]), "created": len(created), "removed": len(removed)}

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--daemon", action="store_true")
    ap.add_argument("--version", action="store_true")
    args = ap.parse_args(argv)

    if args.version:
        print(f"PipeWire VAC {VERSION}")
        return 0

    if args.selftest:
        return _selftest()

    if args.daemon:
        import daemon
        return daemon.run_daemon(args.config)

    import firstrun
    cfgpath = firstrun.preflight(args.config)
    cfg = config.load(cfgpath)
    summary = reconcile_once(cfg)
    print(f"Routing reconciled: {summary['cables']} cables, {summary['created']} created"
          + (f", {summary['removed']} removed" if summary['removed'] else ""))
    return 0

if __name__ == "__main__":
    sys.exit(main())
