# cc-logger — Claude Code Session Logger

## Description

This project uses cc-logger, a PostToolUse hook that automatically captures every tool invocation into structured session logs. Logs are written to `./logs/<timestamp>_<sessionId>/` as both `session.md` (human-readable) and `session.json` (machine-readable).

**You do NOT need to trigger logging manually — it fires on every tool call automatically.**

## What You Should Know

- Log files live in `./logs/` — one subfolder per session
- Each session folder contains `session.md` and `session.json`
- Sensitive data (API keys, tokens, passwords) is auto-redacted before writing
- Set `NO_CC_LOGS=1` in your environment to disable logging for a session

## What You SHOULD Do

1. **At session start**, if asked about logging, check that `./logs/` exists and the hook is active by reading `.claude/settings.json`
2. **When asked "what did we do?" or "summarize this session"**, read the current session's `session.md` from `./logs/` and produce a clean narrative summary — do NOT dump raw Markdown
3. **When asked to search past sessions**, use Glob on `./logs/*/session.md` then Grep for the relevant tool, file, or keyword
4. **When asked about costs**, parse `session.json` files for token counts and format a cost estimate
5. **When asked to clean up logs**, confirm with the user before deleting — logs may be needed for audit purposes

## What You Should NOT Do

- Do NOT write to log files manually — the hook owns them
- Do NOT delete log files unless the user explicitly confirms
- Do NOT summarize session logs unprompted — wait for the user to ask
- Do NOT log sensitive values — they are redacted automatically, do not try to "restore" them

## File Paths

- Config: `.claude-logger.json`
- Hook script: `.claude/hooks/log_session.py`
- Hook registration: `.claude/settings.json`
- Log output: `./logs/<YYYYMMDD_HHMMSS_sessionId>/session.md` and `session.json`
- Example logs: `./examples/sessions/`

## Trigger Phrases

Respond to: "what did we do", "show session log", "summarize this session",
"search past sessions", "how long did that take", "what tools were used",
"what files did Claude touch", "show me the audit trail", "what did this cost"

## Installation (for new projects)

```bash
curl -fsSL https://raw.githubusercontent.com/amit-prabhakar01/cc-logger/main/install.sh | sh
```

Or manually:
1. Copy `.claude/hooks/log_session.py` to your project
2. Merge hook config into `.claude/settings.json`
3. Optionally copy `.claude-logger.json` and customize

## Requirements

- Python 3.8+
- Write access to project root (for `./logs/` directory)
