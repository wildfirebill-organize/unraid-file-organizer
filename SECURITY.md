# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.1.x   | ✅ |
| 1.0.x   | ✅ (security fixes only) |
| < 1.0   | ❌ |

## Reporting a Vulnerability

This tool moves files on your NAS — safety bugs are security bugs.

If you discover a vulnerability (especially anything that could cause the
organizer to touch paths outside its allow-list, overwrite files, or execute
unintended code), please report it responsibly:

1. **Do not** open a public issue
2. Use GitHub's [private vulnerability reporting](https://github.com/wildfirebill-organize/unraid-file-organizer/security/advisories/new)
3. Include: affected version, reproduction steps, and impact assessment

You can expect an initial response within 7 days. Fixes will be released as a
patch version with a changelog entry crediting the reporter (unless anonymity
is requested).

## Security Design Notes

- The container runs as a non-root user
- System paths (`/boot`, `/etc`, `/usr`, `/mnt/user/system`, `/mnt/cache/appdata`, …)
  are hard-forbidden at three layers: config validation, scanner pruning, and plan building
- LLM output is validated against fixed enums before influencing any file operation
- All moves are journaled to a local JSONL file; nothing is sent off-machine
