#!/usr/bin/env bash
# cc-logger installer · https://github.com/amit-prabhakar01/cc-logger
# Idempotent: safe to run multiple times. Merges into existing settings.json.
#
# Usage:
#   bash install.sh           — project-level install (current directory)
#   bash install.sh --global  — machine-wide install (all projects, all IDEs)
#
set -euo pipefail

REPO_URL="https://raw.githubusercontent.com/amit-prabhakar01/cc-logger/main"
GREEN="\033[0;32m"
YELLOW="\033[0;33m"
RED="\033[0;31m"
NC="\033[0m"

ok()   { echo -e "${GREEN}  ✓${NC} $1"; }
warn() { echo -e "${YELLOW}  ⚠${NC}  $1"; }
fail() { echo -e "${RED}  ✗${NC} $1"; exit 1; }

# ── Parse arguments ──────────────────────────────────────────────────────────
GLOBAL=false
for arg in "$@"; do
  case $arg in
    --global|-g) GLOBAL=true ;;
  esac
done

echo ""
echo "  cc-logger · Claude Code Session Logger"
echo "  ----------------------------------------"
if [ "$GLOBAL" = true ]; then
  echo "  Mode: GLOBAL (logs all Claude Code sessions on this machine)"
else
  echo "  Mode: PROJECT (logs sessions in this project only)"
fi
echo ""

# ── Detect Python 3.8+ ───────────────────────────────────────────────────────
PYTHON=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || true)
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

# ── Resolve paths based on mode ──────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$GLOBAL" = true ]; then
  HOOKS_DIR="$HOME/.claude/hooks"
  SETTINGS_FILE="$HOME/.claude/settings.json"
  CONFIG_FILE="$HOME/.claude-logger.json"
  # Use the resolved Python binary path so the hook works from any shell
  PYTHON_BIN="$(command -v python3 2>/dev/null || command -v python)"
  HOOK_CMD="${PYTHON_BIN} ${HOOKS_DIR}/log_session.py"
else
  HOOKS_DIR=".claude/hooks"
  SETTINGS_FILE=".claude/settings.json"
  CONFIG_FILE=".claude-logger.json"
  HOOK_CMD="python3 \${CLAUDE_PROJECT_DIR}/.claude/hooks/log_session.py"
fi

# ── Install hook script ───────────────────────────────────────────────────────
mkdir -p "$HOOKS_DIR"
ok "${HOOKS_DIR}/ ready"

if [ -f "$SCRIPT_DIR/.claude/hooks/log_session.py" ]; then
  cp "$SCRIPT_DIR/.claude/hooks/log_session.py" "${HOOKS_DIR}/log_session.py"
  ok "Hook script copied from local repo"
elif command -v curl >/dev/null 2>&1; then
  curl -fsSL "$REPO_URL/.claude/hooks/log_session.py" -o "${HOOKS_DIR}/log_session.py"
  ok "Hook script downloaded"
elif command -v wget >/dev/null 2>&1; then
  wget -q "$REPO_URL/.claude/hooks/log_session.py" -O "${HOOKS_DIR}/log_session.py"
  ok "Hook script downloaded"
else
  fail "curl or wget required to download the hook script."
fi
chmod +x "${HOOKS_DIR}/log_session.py"

# ── Merge hooks into settings.json ────────────────────────────────────────────
if [ -f "$SETTINGS_FILE" ]; then
  cp "$SETTINGS_FILE" "${SETTINGS_FILE}.bak"
  ok "Backed up existing settings.json → settings.json.bak"

  if grep -q "log_session.py" "$SETTINGS_FILE" 2>/dev/null; then
    ok "Hook already registered in settings.json (skipping)"
  else
    $PYTHON - << PYEOF
import json, sys

with open("$SETTINGS_FILE", "r") as f:
    settings = json.load(f)

settings.setdefault("hooks", {})

hook_cmd = "$HOOK_CMD"

# PostToolUse
settings["hooks"].setdefault("PostToolUse", [])
existing = [e.get("matcher") for e in settings["hooks"]["PostToolUse"]]
if "*" not in existing:
    settings["hooks"]["PostToolUse"].append({
        "matcher": "*",
        "hooks": [{"type": "command", "command": hook_cmd}]
    })

# Stop
settings["hooks"].setdefault("Stop", [])
stop_cmds = [
    h.get("command","")
    for e in settings["hooks"]["Stop"]
    for h in e.get("hooks",[])
]
if hook_cmd not in stop_cmds:
    settings["hooks"]["Stop"].append({
        "hooks": [{"type": "command", "command": hook_cmd}]
    })

with open("$SETTINGS_FILE", "w") as f:
    json.dump(settings, f, indent=2)
    f.write("\n")
PYEOF
    ok "Hooks merged into existing settings.json"
  fi
else
  # Fresh settings.json — write directly using Python so path interpolation is safe
  $PYTHON - << PYEOF
import json

hook_cmd = "$HOOK_CMD"
settings = {
    "\$schema": "https://json.schemastore.org/claude-code-settings.json",
    "hooks": {
        "PostToolUse": [{
            "matcher": "*",
            "hooks": [{"type": "command", "command": hook_cmd}]
        }],
        "Stop": [{
            "hooks": [{"type": "command", "command": hook_cmd}]
        }]
    }
}
with open("$SETTINGS_FILE", "w") as f:
    json.dump(settings, f, indent=2)
    f.write("\n")
PYEOF
  ok "Created $SETTINGS_FILE"
fi

# ── Write config file ─────────────────────────────────────────────────────────
if [ ! -f "$CONFIG_FILE" ]; then
  if [ "$GLOBAL" = true ] && [ -f "$SCRIPT_DIR/.claude-logger.json" ]; then
    cp "$SCRIPT_DIR/.claude-logger.json" "$CONFIG_FILE"
  elif [ "$GLOBAL" = false ] && [ -f "$SCRIPT_DIR/.claude-logger.json" ]; then
    cp "$SCRIPT_DIR/.claude-logger.json" "$CONFIG_FILE"
  else
    cat > "$CONFIG_FILE" << 'JSON'
{
  "_comment": "cc-logger config — edit to customise. Project .claude-logger.json overrides this.",
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
JSON
  fi
  ok "Created $CONFIG_FILE"
else
  ok "$CONFIG_FILE already present (skipping)"
fi

# ── Project-level extras (gitignore, logs dir) ────────────────────────────────
if [ "$GLOBAL" = false ]; then
  GITIGNORE=".gitignore"
  if [ -f "$GITIGNORE" ]; then
    if ! grep -q "^logs/" "$GITIGNORE" 2>/dev/null; then
      printf "\n# cc-logger session logs\nlogs/\n!logs/.gitkeep\n" >> "$GITIGNORE"
      ok "Added logs/ to .gitignore"
    else
      ok "logs/ already in .gitignore"
    fi
  else
    printf "# cc-logger session logs\nlogs/\n!logs/.gitkeep\n" > "$GITIGNORE"
    ok "Created .gitignore with logs/ exclusion"
  fi
  mkdir -p logs && touch logs/.gitkeep
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "  cc-logger installed."
echo ""
if [ "$GLOBAL" = true ]; then
  echo "  Hook:    ${HOOKS_DIR}/log_session.py"
  echo "  Config:  ${CONFIG_FILE}  (project .claude-logger.json overrides this)"
  echo "  Logs:    ~/.cc-logger/<project-name>/<session>/"
  echo "           (or customise with \"centralLogDir\" in ${CONFIG_FILE})"
else
  echo "  Hook:    .claude/hooks/log_session.py"
  echo "  Config:  .claude-logger.json"
  echo "  Logs:    ./logs/<session>/"
fi
echo ""

# Check for running Claude Code (exact binary name match)
CLAUDE_RUNNING=false
if pgrep -x "claude" > /dev/null 2>&1; then CLAUDE_RUNNING=true; fi
if pgrep -x "Claude" > /dev/null 2>&1; then CLAUDE_RUNNING=true; fi

if [ "$CLAUDE_RUNNING" = true ]; then
  warn "Claude Code is running — start a NEW session for hooks to take effect."
  echo "     cc-logger will automatically recover any tool calls that"
  echo "     happened before this install when the new session begins."
  echo ""
else
  echo "  Start a Claude Code session — your first log appears automatically."
  echo "  (If Claude Code is already open, start a new session first.)"
  echo ""
fi

echo "  Disable logging anytime: export NO_CC_LOGS=1"
echo ""
