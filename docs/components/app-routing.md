# App auto-assignment

Automatically routes a matching application's audio stream into a cable (or any sink) —
Spotify → Media, Discord → Voice, the game → Game. **Move-once, then hands off:** a stream is
moved exactly once per appearance, after which manual moves stick. Built on the same
`pwgraph` primitives as the [routing engine](routing-engine.md).

**Modules:** `src/apps.py` (+ `pwgraph.list_sink_inputs` / `move_sink_input`)

## Config

An optional `[[app]]` array, each rule `match` + `target`. No rules ⇒ the feature is dormant.
`target` is free-form (a cable name or any physical sink). A stream matching more than one
*specific* rule takes the **first in config order**. A reserved `match = "default"` rule is a
**position-independent catch-all** for anything no specific rule claimed. Validation (in
`config.py`) requires non-empty `match` + `target`.

## Matching (`apps.matches`)

Case-insensitive substring match. `|` separates
alternatives (`"discord|mumble"`). An alias name expands to a curated list — `ALIASES` holds
`browser` / `game` / `media` / `voice` and is the single source of truth (the editor reads
`list(apps.ALIASES)` for its Match dropdown). **Literal** parts match `application.name` /
`.process.binary` / `media.name`; **alias** parts match name/binary only, so a song title in
`media.name` can't trip the `media`/`voice` alias.

## Move-once ledger (`apps.route_once`)

`route_once(cfg, moved, pw=pwgraph)` is the whole engine. `moved` is a
`{sink-input index: target last applied}` dict the daemon owns across polls. Each poll:

1. Prune `moved` of indices no longer live (a stream that died is forgotten — this also handles
   index reuse, so a restarted app routes fresh).
2. For each stream compute its target (first specific match, else the `default` catch-all).
3. Move it **only if** `moved.get(index) != target`, then record the new target.

That `!=` guard is the line between a **manual drag** (rule's computed target unchanged → left
alone) and a **config edit** (target changed → re-routed to the new target on the next poll). No
current-sink lookup is needed: re-moving a stream to where it already is is a harmless no-op.

## pwgraph additions

- `list_sink_inputs()` — parses `pactl list sink-inputs` + `pactl list clients`, filling
  `app`/`binary` from the owning **client** for anonymous streams (e.g. Spotify via its own
  PipeWire loop, where the name lives on the client, not the stream).
- `move_sink_input(index, sink)` — `pactl move-sink-input`; a bad sink is ignored.

## Daemon integration

The daemon ([daemon.md](daemon.md)) owns `moved = {}` for its lifetime and calls
`apps.route_once(cfg, moved)` right after `reconcile_once` each poll (so target cables exist
first). It's implicitly gated by `features.self_heal`: with self-heal off the daemon idles after
the startup pass, so only apps present at startup are routed. `reconcile_once` stays cable-only.

See also: [routing-engine.md](routing-engine.md), [daemon.md](daemon.md)
