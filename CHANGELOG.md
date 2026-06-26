# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project uses
[Semantic Versioning](https://semver.org/).

## [1.0.3] - 2026-06-26

### Fixed
- **Automatic update checks now work.** The bundled CPython (python-appimage manylinux build) ships
  no CA-certificate store, and its OpenSSL hunts for one at a build-time path (`/opt/_internal/…`)
  that is absent on the target — so the tray's HTTPS update check (`latest_release_version`, a
  `urllib` HEAD to GitHub) failed `CERTIFICATE_VERIFY_FAILED` on every poll, *silently*, and no
  update notification ever appeared. The build now bundles `certifi` (the Mozilla CA roots) into the
  interpreter and AppRun exports `SSL_CERT_FILE` pointing at the in-mount `cacert.pem`, so the check
  verifies and the tray surfaces new releases. `zsync2`/AppImageUpdate brings its own CA discovery,
  so the *manual* "Check for updates…" click already worked — only the automatic check was broken.
  An existing `SSL_CERT_FILE` still wins (corporate TLS-inspecting proxies whose root isn't in the
  Mozilla store).
  - **Note:** AppImages built before this release carry the broken AppRun and can't be fixed in
    place. Update to 1.0.3 once via the tray's "Check for updates…" (or a manual download);
    automatic checks work from 1.0.3 onward.

## [1.0.2] - 2026-06-25

### Fixed
- **The daemon no longer feeds a WirePlumber resource leak.** The 2 s poll re-asserted every cable
  link with `pw-link` and re-listed sinks/streams with `pactl` on *every* tick — dozens of
  short-lived PipeWire clients per second, all day. WirePlumber 0.5.x leaks a GWeakRef per
  short-lived client connection, so the churn slowly exhausted GLib's weak-ref ceiling (~8 h) and
  wedged the whole audio session until WirePlumber was restarted. Two changes stop the churn at the
  source:
  - The reconciler reads existing links once (`pw-link -l`) and creates only the links actually
    missing, instead of firing `pw-link` for every link on every poll.
  - The daemon is now **event-driven**: it reconciles on real PulseAudio events from one persistent
    `pactl subscribe` (a sink/source appearing or disappearing, a new stream to auto-route) and
    ignores the client/volume churn, with a 60 s safety-poll backstop. In steady state it spawns
    **zero** short-lived clients, and a torn-down cable now heals near-instantly instead of within
    ~2 s.

## [1.0.1] - 2026-06-24

### Fixed
- **Audio-stack wedge from a leaked null-sink.** A transient empty/failed `pactl list short
  sinks` read made every cable look missing, so the reconciler re-loaded each `module-null-sink`.
  Duplicate modules piled up in pipewire-pulse, bloated the graph, and eventually wedged the whole
  audio server — killing every app's audio, *and* stalling unrelated apps (e.g. Electron/GTK
  AppImages) that open a PulseAudio context at startup. The leaked modules live in the server, so
  killing the daemon didn't help; only restarting the audio services did. The reconciler now skips
  the poll on a failed read instead of creating cables on a blind one.
- **A wedged `pactl`/`pw-link` no longer freezes the heal loop.** Every PipeWire CLI call now has
  a 5 s timeout; a timeout is treated as a failed read (above) rather than blocking the 2 s
  reconcile forever.

### Added
- **"Restart audio (PipeWire)" tray entry** — one click runs `systemctl --user restart pipewire
  pipewire-pulse wireplumber`; the daemon re-creates its cables on the next poll, so routing
  self-heals. This is the correct recovery for a wedged server (killing the daemon isn't).

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
