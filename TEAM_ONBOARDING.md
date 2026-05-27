# cc-logger — Team Setup Guide

> Automatically logs every Claude Code session so your team has a clear record of what the AI did, which files it touched, and what commands it ran.

---

## What it does

Every time you use Claude Code, cc-logger quietly writes two files into a `logs/` folder in your project:

- `session.md` — human-readable log you can open and read instantly
- `session.json` — machine-readable log for scripts or dashboards

You do nothing differently. Just use Claude Code as normal — the logs appear automatically.

---

## Install (one command, ~30 seconds)

Open your terminal, `cd` into your project folder, then run:

```bash
curl -fsSL https://raw.githubusercontent.com/amit-prabhakar01/cc-logger/main/install.sh | sh
```

That's it. The next Claude Code session you run will produce a log.

**Requirements:** Python 3.8 or higher (check with `python3 --version`). No other dependencies.

---

## Using with VS Code

If you use the Claude Code extension inside VS Code, cc-logger works automatically — no extra setup. Logs appear in the `logs/` folder inside your workspace. You can open `session.md` in VS Code's Markdown preview to read it with formatting.

**Windows users only:** If the hook doesn't fire, open `.claude/settings.json` in your project and change `python3` to `python` in the command line.

---

## Where to find your logs

After a Claude Code session, look in your project folder:

```
your-project/
└── logs/
    └── 20260527_143022_a3f9b2e1/   ← one folder per session
        ├── session.md               ← open this to read the session
        └── session.json             ← use this for scripts
```

The folder name is the date and time the session started. Most recent session = last folder alphabetically.

---

## Privacy — what gets logged and what doesn't

| Logged | Not logged |
|--------|-----------|
| Commands Claude ran (`git status`, `npm test`, etc.) | Your conversation with Claude (prompts and replies) |
| Files Claude edited or created | Your Anthropic account or login details |
| Git branch and commit at session start | API keys, tokens, passwords (these are auto-redacted) |
| Timestamps and session duration | Anything outside tool calls |

Your working directory path is included in the log (e.g. `/Users/yourname/projects/api-server`). This means your **OS username appears in the log file**. Keep this in mind if logs are stored in a shared location.

---

## Turn it off for a session

If you're working with credentials or sensitive data and don't want a log:

```bash
export NO_CC_LOGS=1
claude         # this session won't be logged
unset NO_CC_LOGS
```

---

## Customize what gets logged

Drop a `.claude-logger.json` file in your project root to adjust behaviour:

```json
{
  "enabled": true,
  "filtering": {
    "excludeTools": ["Read", "Glob", "Grep"],
    "includeTools": []
  },
  "output": {
    "maxInlineChars": 3000,
    "minToolCallsToWrite": 1
  }
}
```

Common tweaks:
- **Exclude noisy tools:** add `"Bash"` to `excludeTools` for a minimal timeline
- **Log only specific tools:** put tool names in `includeTools` (this overrides `excludeTools`)
- **Disable entirely:** set `"enabled": false`

---

## Logs are local — they never leave your machine

cc-logger writes files to your local `logs/` folder only. Nothing is sent anywhere. The `logs/` folder is added to `.gitignore` automatically so logs are not committed to your repo.

---

## Questions or issues

Open an issue at: **https://github.com/amit-prabhakar01/cc-logger/issues**

