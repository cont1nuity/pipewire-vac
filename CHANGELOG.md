# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project uses
[Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-06-23

First public release.

### Added
- **Config-driven virtual cables** — declare null-sink cables in a single TOML file; each
  cable's `target` (another cable, a physical sink, `auto`, or `""`) derives the links.
- **Self-healing daemon** — re-reads the config and reconciles the live PipeWire graph every
  ~2s, so a cable torn down by a device hiccup heals within a couple of seconds.
- **Structure-only routing** — creates / links (shared channels only, no downmix) / unmutes
  once; never sets volume, pins the default device, or touches the microphone.
- **Virtual microphones** — wire a hardware mic into a cable via `sources`; the cable's monitor
  becomes a virtual mic many apps can select at once (mono fans out to stereo).
- **App auto-routing** — optional `[[app]]` rules move a matching app's stream into a cable once
  per launch, with `browser` / `game` / `media` / `voice` aliases and a `default` catch-all.
- **Tray + settings editor** — an optional `StatusNotifierItem` tray and a row-based Tk editor.
- **Single-file AppImage** — relocatable CPython + dbus-next + the app; the host needs only the
  PipeWire CLI tools.
- **AppImage auto-update** — the AppImage carries embedded update-information; the tray offers a
  manual "Check for updates…" and an automatic startup check (toggle in the tray / `[features]
  check_updates`) that hands off to AppImageUpdate for an in-place delta update, or opens the
  Releases page.
