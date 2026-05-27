# Changelog

All notable changes to cc-logger are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

### Planned for v1.1
- File diffs for Edit/Write tool calls
- Git state snapshot (branch, HEAD) at session start/end
- Token and cost estimation
- Session summary block appended at session end
- Webhook on session end (Slack, Notion, custom)
- Log rotation policies

---

## [1.0.0] — 2026-05-25

### Added
- `PostToolUse` hook via `.claude/settings.json`
- `log_session.py` — Python 3.8+ hook script (~220 lines)
- Dual output: `session.md` (Markdown) + `session.json` (JSON) per session
- Folder-per-session layout: `logs/YYYYMMDD_HHMMSS_<sessionId>/`
- `schema_version: "1"` in all JSON files for downstream stability
- Always-on sensitive data redaction (API keys, tokens, passwords, PATs)
- `NO_CC_LOGS=1` escape hatch for secrets-sensitive sessions
- Tool filtering via `.claude-logger.json` (`excludeTools`, `includeTools`)
- Idempotent `install.sh` — merge-safe, backs up existing `settings.json`
- `Makefile` with `install`, `test`, `lint`, `logs-clean` targets
- `SKILL.md` for Claude Skill packaging
- Example session logs in `examples/sessions/`
- GitHub CI workflow testing Python 3.8, 3.10, 3.12
- Issue templates: bug report, feature request, share-your-log showcase
- Config presets: `config/minimal.yaml`, `config/verbose.yaml`

### Security
- Redaction runs before any byte is written to disk
- Recursive redaction on nested JSON objects and lists
- Configurable via `REDACT_PATTERNS` in hook script (extending, not disabling)

### Non-goals (explicitly deferred)
- Web dashboard (v2)
- CLI viewer (v2)
- VS Code extension (v2)
- Network calls in the hook hot path (by design — offline-first)
