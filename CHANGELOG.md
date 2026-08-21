# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.4.4] - 2026-08-21

### Added

- **Version visibility** — `GET /api/version` reports app version, uid, and
  whether `/config` is writable; the UI header shows a version badge that turns
  red with "config READ-ONLY" when saves cannot work; startup log line includes
  the same diagnostics.
- Entrypoint warns loudly at startup if `/config` remains unwritable after chown.

Use this release to confirm you are actually running the fixed image: if the
header badge does not say v1.4.4, the container was not recreated from the new
image.

## [1.4.3] - 2026-08-21

### Fixed

- **Config not saving on Unraid** — the container now starts as root, takes
  ownership of the `/config` volume (Docker creates it root-owned), then drops
  to the unprivileged app user via gosu. Previously every settings write hit
  PermissionError and the UI silently reverted to an empty config.
- Config-save failures now surface the real reason (HTTP 500 with detail)
  instead of an opaque error; UI error toasts last longer.

## [1.4.2] - 2026-08-21

### Added

- `ORGANIZER_OLLAMA_URL` environment variable sets the default Ollama URL for
  LLM Assist at deploy time (CA template exposes it as a Variable; compose
  passes it through). Falls back to the previous built-in default when unset.

### Changed

- Clearing the Ollama URL field in Settings now keeps the stored/env-provided
  value instead of re-forcing `host.docker.internal`
- docker-compose: removed the `extra_hosts` host-gateway workaround

## [1.4.1] - 2026-08-21

### Changed

- CI: bumped all workflow actions to Node 24 runtime majors
  (checkout v5, setup-buildx v4, setup-qemu v4, login v4, metadata v6,
  build-push v7) — clears GitHub's Node 20 deprecation warnings

## [1.4.0] - 2026-08-20

### Added

- **Folder-level intelligence, phase 2**
  - Nested units: exe+dll clusters one level deep (`MyApp/bin/app.exe`) are
    detected and moved whole; the primary executable is chosen by size across
    the flattened view
  - Launcher artifacts: known platform markers (steam_api/steam_appid,
    unityplayer, codex/cream/ali213 emu configs, GOG/Heroic files) mark a
    folder as a unit even when too small for the classic file-count rule
  - Engine data: an exe next to engine archives (.pck/.pak/.bsa/.ba2/.vpk/.wad…)
    is recognized as a game unit
  - Detection is depth-capped (20 subdirs / 800 entries) to stay cheap on huge trees

- **Media library enhancements**
  - Multi-episode files: `Show S01E02-E03.mkv` routes by first episode and
    records the range
  - Anime absolute numbering: `[Group] Cowboy Bebop - 05 [1080p].mkv` →
    `TV Shows/Cowboy Bebop/Season 01/`; release-group bracket prefixes stripped
  - Keyword episodes: `Naruto Shippuden Episode 220.mp4`
  - Release-scene movies without parentheses: `Blade.Runner.2049.2017.1080p.x264.mkv`
    → `Movies/Blade Runner 2049 (2017)/` (bare year must be followed only by
    quality tags)
  - Episode titles extracted from post-pattern remainders into scan details

### Fixed

- Anime/dash pattern no longer misreads 4-digit years as episode numbers
  (`Blade Runner - 2049 (2017)` stays a movie) via digit-boundary lookaheads

## [1.3.0] - 2026-08-20

### Added

- **Scan history dashboard** — every scan (manual and scheduled) is journaled;
  UI shows recent scans plus an SVG trend chart of movable files per scan
- **Duplicate detection** — three-stage hash pipeline (size → 64 KB head → full MD5)
  across allowed roots; groups show a suggested original to keep and total
  reclaimable space; selected duplicates can be moved to
  `/mnt/user/quarantine/duplicates/` through the journalled engine (undo-able)
- **Folder-level intelligence** — directories that look like portable apps/games
  (an `.exe` plus several `.dll`s) are detected as units, classified by their
  primary executable's intent, and moved whole — the scanner never descends into them
- **Media library mode** — optional Plex/Jellyfin-style routing:
  `Show S01E02.mkv → <root>/TV Shows/Show/Season 01/`,
  `Movie (2010).mp4 → <root>/Movies/Movie (2010)/`; supports `S01E02` and `1x02`
  episode formats plus year-suffixed movies; custom rules still take precedence
- **Multi-arch images** — GHCR releases now publish `linux/amd64` and `linux/arm64`

## [1.2.0] - 2026-08-20

### Added

- **Custom rules** — user-defined regex rules (filename or full path) that force
  category/intent/destination; first match wins, outranks all built-in heuristics,
  and marks matched files as trusted (confidence ≥ 0.95)
- **Per-category destination overrides** — remap any category's destination from the UI
  without code edits (`media_audio=/mnt/user/media/music`)
- **Scheduled scans** — background dry-run scans on an hourly interval producing a
  digest (movable counts, size, sample moves); scheduled scans never move files;
  "Run now" button for on-demand digests
- **Webhook notifications** — scan digests and apply summaries via generic JSON,
  Discord, or ntfy webhooks, with a send-test button
- Rule/LLM badges in scan results table
- Config validation for rule regexes, categories, intents, notification types

### Changed

- Scheduler runs from FastAPI lifespan; version bumped to 1.2.0

## [1.1.0] - 2026-08-20

### Added

- **Local LLM Assist** — optional Ollama-backed second-opinion tier that re-classifies
  files scoring below the confidence threshold (random-named executables, cryptic media names)
- LLM responses validated against known categories/intents; unsure replies ignored;
  Ollama outages degrade silently to deterministic results
- `GET /api/llm/status` endpoint and "Test connection" button in settings
- PE string samples retained (truncated) in scan payloads as LLM evidence
- `host.docker.internal:host-gateway` mapping in compose for out-of-the-box Ollama connectivity

### Changed

- Scanner details payload now keeps a trimmed `strings_sample` instead of dropping it

## [1.0.0] - 2026-08-20

### Added

- Initial release
- Web UI with checkbox allow-list locations and never-touch disallow list
- Hard-forbidden system paths (`/boot`, `/mnt/user/system`, `/mnt/cache/appdata`, …)
  enforced at config, scanner, and planner layers
- Tiered smart classifier:
  - extension & MIME typing
  - filename pattern matching incl. OS-specific ISO detection (`isos/windows/`,
    `isos/linux_debian/`, …)
  - Windows PE header string analysis for intent detection (music player vs network
    tool vs game vs utility)
  - Android APK manifest inspection
- Plan builder with min-confidence filter, duplicate rename/skip policy,
  deterministic conflict resolution
- Apply engine with dry-run default, JSONL operation journal, one-click undo
- Dark Unraid-style single-page interface with category chips, search,
  confidence bars, and plan preview
- Docker deployment (Dockerfile + compose) and release-only GHCR workflow

[Unreleased]: https://github.com/wildfirebill-organize/unraid-file-organizer/compare/v1.4.4...HEAD
[1.4.4]: https://github.com/wildfirebill-organize/unraid-file-organizer/compare/v1.4.3...v1.4.4
[1.4.3]: https://github.com/wildfirebill-organize/unraid-file-organizer/compare/v1.4.2...v1.4.3
[1.4.2]: https://github.com/wildfirebill-organize/unraid-file-organizer/compare/v1.4.1...v1.4.2
[1.4.1]: https://github.com/wildfirebill-organize/unraid-file-organizer/compare/v1.4.0...v1.4.1
[1.4.0]: https://github.com/wildfirebill-organize/unraid-file-organizer/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/wildfirebill-organize/unraid-file-organizer/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/wildfirebill-organize/unraid-file-organizer/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/wildfirebill-organize/unraid-file-organizer/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/wildfirebill-organize/unraid-file-organizer/releases/tag/v1.0.0
