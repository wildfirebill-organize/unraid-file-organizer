# Contributing to Unraid File Organizer

Thanks for your interest in improving this project! This guide covers the
development setup, testing, and PR process.

## Development Setup

Requirements: Python 3.12+ (3.14 works too), pip.

```bash
git clone https://github.com/wildfirebill-organize/unraid-file-organizer.git
cd unraid-file-organizer
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8787
```

Open http://localhost:8787. Without libmagic installed, MIME detection is
skipped automatically — everything else works.

### Running Tests

```bash
python smoke_test.py
```

The smoke test builds a fake messy directory tree and verifies end-to-end:
classification accuracy, allow/disallow enforcement, plan building,
apply/undo round-trip, and LLM response parsing (no Ollama required).

If you add a feature, extend `smoke_test.py` to cover it.

## Project Layout

```
app/
├── api/routes.py          # REST endpoints
├── core/
│   ├── config.py          # JSON config persistence + hard-forbidden paths
│   └── file_classifier.py # Tiered classifier + destination mapping
├── models/models.py       # Pydantic models
├── services/
│   ├── scanner.py         # Directory walking, allow/disallow pruning
│   ├── organizer.py       # Plan builder, apply engine, journal, undo
│   └── llm_classifier.py  # Optional Ollama second-opinion tier
└── templates/index.html   # Single-page UI (vanilla JS)
```

## Ground Rules

1. **Safety first** — any change must preserve: dry-run default, never-overwrite,
   hard-forbidden path enforcement, and undo capability.
2. **No comments unless asked** — match existing code style (the codebase is comment-light).
3. **Fail soft** — optional features (LLM, MIME) must degrade gracefully when unavailable.
4. **Validate LLM output** — anything from a model passes through enum validation before use.

## Workflow

1. Fork / create a feature branch (`feat/my-feature`)
2. Make changes + extend tests
3. Run `python smoke_test.py` — all checks must pass
4. If you touched `.github/workflows/`, validate with [actionlint](https://github.com/rhysd/actionlint):
   ```bash
   actionlint -shellcheck= -pyflakes= .github/workflows/*.yml
   ```
5. Open a PR describing what changed and why

## Reporting Bugs

Open an issue with the bug report template. Include: Unraid version, Docker
version, relevant log output, and steps to reproduce. **Never paste file paths
containing personal data or secrets.**

## Feature Ideas

Check the [roadmap](ROADMAP.md) first — if your idea isn't listed, open a
feature request issue and make the case.
