# Components

Per-component documentation for PipeWire VAC. Each doc below describes **what one component
does and the invariants it holds** — the "what/how". This layer sits between CLAUDE.md's
overview and the code.

The app is ~12 flat modules in `src/`, grouped here into five components.

## Component map

| Component | Doc | Modules |
|---|---|---|
| Routing engine | [routing-engine.md](routing-engine.md) | `config` `routing` `pwgraph` `state` `main` |
| App auto-assignment | [app-routing.md](app-routing.md) | `apps` |
| Daemon & lifecycle | [daemon.md](daemon.md) | `daemon` `firstrun` `paths` |
| UI (tray + editor) | [ui.md](ui.md) | `tray` `configui` |
| Packaging | [packaging.md](packaging.md) | `packaging/build-appimage.sh` |

## Shared concepts

These cut across every component; the individual docs assume them.

### Structure-only philosophy

The app manages **structure**, never values. It creates a missing cable, links it to its
target, and unmutes it **once** on first creation. It never sets volume, re-asserts mute, pins
the system default sink/source, or touches the mic — WirePlumber restores per-sink state and
pavucontrol owns the rest. A user's manual change always wins. App routing follows the same
rule: a stream is moved once per appearance, then left alone (see [app-routing.md](app-routing.md)).

### The pwgraph chokepoint

`src/pwgraph.py` is the **only** module that shells out to PipeWire (`pactl` / `pw-link`).
Everything funnels through `pwgraph.run(cmd)`, which tests monkeypatch. Two load-bearing
rules: match sinks by **name**, never module ID (IDs change every boot); always pass
`channel_map=` (without it sinks are mono and the `monitor_FL`/`playback_FR` ports don't exist).

### The reconcile flow

`main.reconcile_once(cfg)` is one structural pass: snapshot the live graph → compute the
desired sinks+links → diff into actions → apply → record the unmute ledger. It is **idempotent**
— re-running it is the self-heal. The daemon ([daemon.md](daemon.md)) calls it on a
`pactl subscribe` event (or a 60s safety-poll backstop), then calls `apps.route_once` for app
assignment. The reconcile is pure (no PipeWire calls in `routing.py`); only `pwgraph` and `state`
have side effects.

## Maintaining these docs

When a component's behavior changes, **revise its doc as a full revision, not a changelog**, in
the same commit as the code. Keep the component-map table above current when a module moves
between components or a component is added/removed. Each leaf doc lists its `src/` modules —
keep that accurate.
