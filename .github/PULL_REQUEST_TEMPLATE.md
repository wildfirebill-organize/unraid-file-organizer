## What does this PR do?

<!-- One or two sentences: what changed and why -->

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Refactor (no behavior change)
- [ ] Docs only

## Safety checklist

This tool moves files on people's NAS. Any behavior-changing PR must preserve:

- [ ] Dry-run remains the default
- [ ] No existing file is ever overwritten (rename/skip only)
- [ ] Hard-forbidden paths (`/boot`, `/mnt/user/system`, `/mnt/cache/appdata`, …) stay blocked at config, scanner, AND planner layers
- [ ] Undo still reverses every applied operation
- [ ] Optional features (LLM, MIME detection) degrade gracefully when unavailable
- [ ] LLM/model output is enum-validated before influencing any move

## Testing

- [ ] `python smoke_test.py` passes
- [ ] Extended `smoke_test.py` to cover the new behavior
- [ ] If workflows changed: `actionlint -shellcheck= -pyflakes= .github/workflows/*.yml` passes
