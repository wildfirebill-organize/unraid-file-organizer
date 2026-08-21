# Roadmap

Ideas and planned work for Unraid File Organizer. Nothing here is committed —
priorities shift based on feedback. Want something sooner?
[Open an issue](https://github.com/wildfirebill-organize/unraid-file-organizer/issues) or
[contribute](CONTRIBUTING.md).

## ✅ Shipped

- [x] Allow-list / never-touch location model with hard system-path protection
- [x] Tiered classifier: extensions → filename patterns → PE/APK binary analysis
- [x] Dry-run-first plan & apply workflow with JSONL journal and undo
- [x] Duplicate safety (rename/skip)
- [x] Local LLM assist via Ollama for low-confidence files
- [x] GHCR release pipeline
- [x] Scheduled dry-run scans with digests and webhook notifications
- [x] Custom regex rules that outrank built-in heuristics
- [x] Per-category destination overrides from the UI
- [x] Notifications (generic / Discord / ntfy)
- [x] Scan history dashboard with per-scan trend chart
- [x] Content-aware duplicate detection (size → head → full hash) with quarantine action
- [x] Folder-level intelligence — portable app/game dirs move as units
- [x] Media library mode — Plex/Jellyfin-style TV & movie routing
- [x] Multi-arch images (amd64 + arm64)
- [x] Folder-level intelligence, phase 2 — nested units, launcher artifacts, engine data
- [x] Media library enhancements — multi-episode, anime numbering, release-scene movies, ep titles
- [x] ROM & console classification — 40+ consoles, zipped ROMs (content peek), folder-name hints
- [x] Homebrew and emulator detection with dedicated destinations
- [x] CA-compatible template ships in-repo (`templates/unraid-file-organizer/`)

## 🎯 Next Up

- [ ] **Community Applications listing** — submit the template to the official CA app feed

## 🔭 Exploring

- [ ] **Duplicate auto-pilot** — policy-based quarantine (e.g. always keep newest) without per-group review
- [ ] **i18n** — interface translations

## 🧊 Not Planned (for now)

- Cloud storage backends (this is a local-NAS tool by design)
- Automatic moves without any human confirmation step
