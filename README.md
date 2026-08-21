<h1 align="center">🗂️ Unraid File Organizer</h1>

<p align="center">
<strong>Smart, safe, self-hosted file organization for your Unraid server</strong><br>
Automatic file classification · Allow-list safety model · Dry-run first · Local LLM assist · 100% offline
</p>

<p align="center">
<a href="#-quick-start-docker">Install</a> ·
<a href="#-how-it-works">How it works</a> ·
<a href="#️-configuration">Configuration</a> ·
<a href="#-faq">FAQ</a> ·
<a href="ROADMAP.md">Roadmap</a>
</p>

<p align="center">
<a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/License-MIT-f15a2c.svg"></a>
<img alt="Platform" src="https://img.shields.io/badge/platform-Unraid%20%7C%20Docker-3a4048">
<img alt="Python" src="https://img.shields.io/badge/python-3.12+-4a90d9">
<img alt="PRs Welcome" src="https://img.shields.io/badge/PRs-welcome-48b568">
</p>

---

**Unraid File Organizer** is a self-hosted Docker web app that cleans up messy NAS shares.
It scans the folders you allow, intelligently classifies every file — Windows installers,
Android APKs, Linux binaries, OS ISOs, media, archives, documents — and moves each one to a
sensible destination like `apps/windows/media/` or `isos/windows/`. Nothing is touched
without your explicit permission, nothing moves without a preview, and every move can be undone.

Perfect for taming a downloads share that has accumulated years of random installers,
ISOs, APKs, and media files.

## ✨ Features

| | Feature | Description |
|---|---|---|
| ☑️ | **Allow-list locations** | Checkbox per folder — checked folders may be organized, unchecked are never scanned |
| 🚫 | **Never-touch list** | Protected paths skipped everywhere; `/boot`, `/mnt/user/system`, and docker appdata are hard-forbidden |
| 🧠 | **Smart classification** | PE-header string analysis tells a music player `.exe` from a network tool; APK manifests, ISO OS-type detection, media/archive/document typing |
| 👀 | **Dry-run by default** | Every plan is previewed before anything moves |
| ↩️ | **One-click undo** | Full JSONL operation journal reverses any applied batch |
| 🔁 | **Duplicate safety** | Never overwrites — renames `file (1).ext` or skips per policy |
| 🤖 | **Optional local LLM assist** | Ollama re-classifies low-confidence files using embedded binary strings — private, no cloud |
| 📏 | **Custom rules** | Regex rules (filename or path) that force category, intent, and destination — outranking built-in heuristics |
| ⏰ | **Scheduled scans** | Automatic dry-run digests on a schedule — see what's ready to move without lifting a finger |
| 🔔 | **Webhook notifications** | Digests and apply summaries to Discord, ntfy, or any JSON webhook |
| 🧬 | **Duplicate detection** | Three-stage hash pipeline finds identical files across shares — quarantine the copies, keep the original |
| 📁 | **Folder-level intelligence** | Portable app/game directories — including nested installs, Steam/emu markers, and engine data files — move whole, never file-by-file |
| 🎬 | **Media library mode** | `S01E02`, multi-ep ranges, anime numbering (`[Group] Show - 05`), and release-scene movies all route into Plex/Jellyfin layouts |
| 📈 | **Scan history** | Trend chart of every scan — watch the mess shrink over time |
| 🌙 | **Dark UI** | Unraid-style single-page interface with confidence bars and category filters |

## 🚀 Quick Start (Docker)

```bash
git clone https://github.com/wildfirebill-organize/unraid-file-organizer.git
cd unraid-file-organizer
mkdir -p /mnt/user/appdata/unraid-organizer
docker compose up -d --build
```

Open **`http://<server-ip>:8787`**, then:

1. Add your messy folder (e.g. `/mnt/user/downloads`) under **Allowed Locations** and tick its checkbox
2. Click **Scan** — files appear grouped by type with confidence scores
3. Click **Build Plan** to preview every proposed move
4. Keep **Dry Run** on until you trust the plan, then flip it off and **Apply Plan**

Prefer releases over git? Images are published to GHCR on every release:

```bash
docker pull ghcr.io/wildfirebill-organize/unraid-file-organizer:latest
```

## 🧠 How It Works

Classification runs in tiers, fastest first:

1. **Extension & MIME typing** — instant categories for media, archives, documents
2. **Filename pattern matching** — OS-specific ISO detection (`ubuntu-*`, `win11*`, `macos*`)
3. **Binary analysis** — Windows PE headers are string-scanned to separate music players
   from network tools from games; Android APKs are inspected via their manifest
4. **LLM assist (optional)** — files still below your confidence threshold get a second
   opinion from a local Ollama model reasoning over filename, size, MIME, and extracted strings

Every result carries a **confidence score**; you set the minimum threshold that must be met
before a file is eligible to move.

### Destination layout

```
/mnt/user/
├── apps/
│   ├── windows/{media,network,utilities,development}/
│   └── android/{media,network,utilities}/
├── games/windows/
├── isos/{windows,linux_debian,linux_arch,linux_redhat,macos,android}/
├── media/{music,videos,photos}/
├── documents/
├── archives/
└── quarantine/
```

Customize destinations by editing `_suggest_location()` in
[`app/core/file_classifier.py`](app/core/file_classifier.py).

## 🤖 Optional: Local LLM Assist

Random-named files (`a7f3k9.exe`) defeat rule-based classifiers. Enable LLM Assist and a
local Ollama model gets a second look at just those stragglers:

```bash
docker run -d --name ollama --restart unless-stopped \
  -p 11434:11434 -v /mnt/user/appdata/ollama:/root/.ollama ollama/ollama
docker exec ollama ollama pull qwen2.5:3b
```

Then enable **Settings → 🤖 LLM Assist** in the organizer UI and hit *Test connection*.

- Only low-confidence files are sent, capped per scan — scans stay fast
- Model replies are validated against known categories; unsure answers are ignored
- Ollama down? Scans proceed with deterministic results
- **Nothing ever leaves your network**

## ⚙️ Configuration

All settings live in the UI and persist to `/config/config.json`.

| Setting | Default | Description |
|---|---|---|
| Allowed Locations | — | Folders the organizer may scan and move files from |
| Never Touch | system defaults | Paths skipped even inside allowed roots |
| Dry Run | `on` | Preview moves without touching files |
| Minimum Confidence | `0.60` | Files below this score are never moved |
| Duplicate Policy | `rename` | Rename or skip when destination exists |
| LLM Assist | `off` | Ollama fallback for low-confidence files |

Operation journal: `/config/operations.log.jsonl`

## 🛡️ Safety Model

| Rule | Enforcement |
|---|---|
| Only scan/move inside checked managed paths | Scanner + planner |
| Skip disallowed & system paths everywhere | Hard prefix list + user list |
| Never overwrite existing files | Rename or skip policy |
| Dry run default | `dry_run: true` |
| Full audit trail | JSONL journal + one-click undo |

## ❓ FAQ

<details>
<summary><b>Can it move my files without asking?</b></summary>
No. Files only move after you build a plan and explicitly apply it with dry-run off — and undo reverses any batch.
</details>

<details>
<summary><b>Will it touch appdata, VM disks, or the flash drive?</b></summary>
Never. <code>/boot</code>, <code>/mnt/user/system</code>, <code>/mnt/cache/appdata</code>, and anything on your Never-Touch list are hard-blocked at multiple layers.
</details>

<details>
<summary><b>Does it rename media like Sonarr/Radarr?</b></summary>
Media Library Mode routes files into Plex/Jellyfin folder layouts (<code>TV Shows/Show/Season 01/</code>, <code>Movies/Movie (Year)/</code>) but keeps original filenames — it's an organizer, not a renamer.
</details>

<details>
<summary><b>Do I need a GPU for LLM assist?</b></summary>
No. Small models (3B class) run fine on CPU; they're only invoked for the handful of files rules couldn't classify.
</details>

<details>
<summary><b>Does it work outside Unraid?</b></summary>
Yes — anywhere Docker runs and you can mount directories. Destination defaults just assume an Unraid-style layout.
</details>

## 🗺️ Project Docs

- [Changelog](CHANGELOG.md) — release history
- [Roadmap](ROADMAP.md) — what's next
- [Contributing](CONTRIBUTING.md) — dev setup & PR guide
- [Code of Conduct](CODE_OF_CONDUCT.md)
- [Security Policy](SECURITY.md)

## 📄 License

[MIT](LICENSE) © wildfirebill

---

## AI Assistance Disclosure

This project was developed with the assistance of AI coding tools (opencode running open-source models) for tasks such as code generation, review, refactoring, and documentation. All AI-generated code and content is human-reviewed before merging.
