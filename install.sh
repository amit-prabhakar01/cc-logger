#!/usr/bin/env bash
# cc-logger installer · https://github.com/amit-prabhakar01/cc-logger
# Idempotent: safe to run multiple times. Merges into existing settings.json.
set -euo pipefail

REPO_URL="https://raw.githubusercontent.com/amit-prabhakar01/cc-logger/main"
GREEN="\033[0;32m"
YELLOW="\033[0;33m"
RED="\033[0;31m"
NC="\033[0m"

ok()   { echo -e "${GREEN}  ✓${NC} $1"; }
warn() { echo -e "${YELLOW}  ⚠${NC}  $1"; }
fail() { echo -e "${RED}  ✗${NC} $1"; exit 1; }

echo ""
echo "  cc-logger · Claude Code Session Logger"
echo "  ----------------------------------------"
echo ""

# --- Check Python 3.8+ ---
PYTHON=$(command -v python3 || command -v python || true)
if [ -z "$PYTHON" ]; then
  fail "Python 3.8+ is required but not found. Install Python and retry."
fi

PY_VERSION=$($PYTHON -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$($PYTHON -c "import sys; print(sys.version_info.major)")
PY_MINOR=$($PYTHON -c "import sys; print(sys.version_info.minor)")
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 8 ]; }; then
  fail "Python 3.8+ required. Found: $PY_VERSION"
fi
ok "Python $PY_VERSION found"

# --- Create .claude/hooks/ directory ---
mkdir -p .claude/hooks
ok ".claude/hooks/ ready"

# --- Download or copy hook script ---
HOOK_SRC=""
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -f "$SCRIPT_DIR/.claude/hooks/log_session.py" ]; then
  # Local install (running from cloned repo)
  cp "$SCRIPT_DIR/.claude/hooks/log_session.py" .claude/hooks/log_session.py
  ok "Hook script copied from local repo"
elif command -v curl >/dev/null 2>&1; then
  curl -fsSL "$REPO_URL/.claude/hooks/log_session.py" -o .claude/hooks/log_session.py
  ok "Hook script downloaded"
elif command -v wget >/dev/null 2>&1; then
  wget -q "$REPO_URL/.claude/hooks/log_session.py" -O .claude/hooks/log_session.py
  ok "Hook script downloaded"
else
  fail "curl or wget required to download the hook script."
fi
chmod +x .claude/hooks/log_session.py

# --- Merge hook into .claude/settings.json ---
SETTINGS_FILE=".claude/settings.json"
CC_LOGGER_HOOK='{"type":"command","command":"python3 ${CLAUDE_PROJECT_DIR}/.claude/hooks/log_session.py"}'

if [ -f "$SETTINGS_FILE" ]; then
  # Back up existing settings
  cp "$SETTINGS_FILE" "${SETTINGS_FILE}.bak"
  ok "Backed up existing settings.json → settings.json.bak"

  # Check if hook is already registered
  if grep -q "log_session.py" "$SETTINGS_FILE" 2>/dev/null; then
    ok "Hook already registered in settings.json (skipping)"
  else
    # Use Python to safely merge (handles comments, preserves existing hooks)
    $PYTHON - <<PYEOF
import json, sys

with open("$SETTINGS_FILE", "r") as f:
    settings = json.load(f)

settings.setdefault("hooks", {})
settings["hooks"].setdefault("PostToolUse", [])

new_entry = {
    "matcher": "*",
    "hooks": [{"type": "command", "command": "python3 \${CLAUDE_PROJECT_DIR}/.claude/hooks/log_session.py"}]
}

# Avoid duplicate matchers
existing_matchers = [e.get("matcher") for e in settings["hooks"]["PostToolUse"]]
if "*" not in existing_matchers:
    settings["hooks"]["PostToolUse"].append(new_entry)

with open("$SETTINGS_FILE", "w") as f:
    json.dump(settings, f, indent=2)
    f.write("\n")
PYEOF
    ok "Hook merged into existing settings.json"
  fi
else
  # Create fresh settings.json
  cat > "$SETTINGS_FILE" << 'JSON'
{
  "$schema": "https://json.schemastore.org/claude-code-settings.json",
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "python3 ${CLAUDE_PROJECT_DIR}/.claude/hooks/log_session.py"
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 ${CLAUDE_PROJECT_DIR}/.claude/hooks/log_session.py"
          }
        ]
      }
    ]
  }
}
JSON
  ok "Created .claude/settings.json"
fi

# --- Write default config if not present ---
if [ ! -f ".claude-logger.json" ]; then
  if [ -f "$SCRIPT_DIR/.claude-logger.json" ]; then
    cp "$SCRIPT_DIR/.claude-logger.json" .claude-logger.json
  else
    cat > .claude-logger.json << 'JSON'
{
  "enabled": true,
  "filtering": {
    "excludeTools": ["Read", "Glob"],
    "includeTools": []
  },
  "output": {
    "maxInlineChars": 3000,
    "minToolCallsToWrite": 1
  }
}
JSON
  fi
  ok "Created .claude-logger.json (edit to customize)"
else
  ok ".claude-logger.json already present (skipping)"
fi

# --- Update .gitignore ---
GITIGNORE=".gitignore"
if [ -f "$GITIGNORE" ]; then
  if ! grep -q "^logs/" "$GITIGNORE" 2>/dev/null; then
    echo "" >> "$GITIGNORE"
    echo "# cc-logger session logs" >> "$GITIGNORE"
    echo "logs/" >> "$GITIGNORE"
    echo "!logs/.gitkeep" >> "$GITIGNORE"
    ok "Added logs/ to .gitignore"
  else
    ok "logs/ already in .gitignore"
  fi
else
  printf "# cc-logger session logs\nlogs/\n!logs/.gitkeep\n" > "$GITIGNORE"
  ok "Created .gitignore with logs/ exclusion"
fi

# --- Create logs/.gitkeep ---
mkdir -p logs
touch logs/.gitkeep

echo ""
echo "  cc-logger installed."
echo ""
echo "  Hook:   .claude/hooks/log_session.py"
echo "  Config: .claude-logger.json"
echo "  Logs:   ./logs/<session>/"
echo ""
echo "  Start a Claude Code session — your first log appears automatically."
echo "  Disable logging anytime: export NO_CC_LOGS=1"
echo ""
