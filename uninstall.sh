#!/usr/bin/env bash
# cc-logger uninstaller · https://github.com/amit-prabhakar01/cc-logger
# Removes the hook script, settings.json entries, and config file.
# Logs are NEVER deleted automatically — see note at end.
#
# Usage:
#   bash uninstall.sh           — remove project-level install (current directory)
#   bash uninstall.sh --global  — remove machine-wide install
#   bash uninstall.sh --purge   — also delete all session logs (project mode only)
#   bash uninstall.sh --global --purge  — remove global install AND delete ~/.cc-logger/
#
set -euo pipefail

GREEN="\033[0;32m"
YELLOW="\033[0;33m"
RED="\033[0;31m"
CYAN="\033[0;36m"
NC="\033[0m"

ok()   { echo -e "${GREEN}  ✓${NC} $1"; }
warn() { echo -e "${YELLOW}  ⚠${NC}  $1"; }
info() { echo -e "${CYAN}  ·${NC} $1"; }
fail() { echo -e "${RED}  ✗${NC} $1"; exit 1; }

# ── Parse arguments ──────────────────────────────────────────────────────────
GLOBAL=false
PURGE=false
for arg in "$@"; do
  case $arg in
    --global|-g) GLOBAL=true ;;
    --purge|-p)  PURGE=true  ;;
  esac
done

echo ""
echo "  cc-logger · Uninstaller"
echo "  ─────────────────────────────────────────"
if [ "$GLOBAL" = true ]; then
  echo "  Mode: GLOBAL (removing machine-wide install)"
else
  echo "  Mode: PROJECT (removing install from current directory)"
fi
[ "$PURGE" = true ] && echo "  Purge: YES — session logs will be deleted" || \
  echo "  Purge: NO  — session logs will be kept"
echo ""

# ── Resolve paths ─────────────────────────────────────────────────────────────
if [ "$GLOBAL" = true ]; then
  HOOKS_DIR="$HOME/.claude/hooks"
  SETTINGS_FILE="$HOME/.claude/settings.json"
  CONFIG_FILE="$HOME/.claude-logger.json"
  CENTRAL_LOG_DIR="$HOME/.cc-logger"
else
  HOOKS_DIR=".claude/hooks"
  SETTINGS_FILE=".claude/settings.json"
  CONFIG_FILE=".claude-logger.json"
  LOCAL_LOG_DIR="logs"
fi

# ── Detect Python for JSON editing ───────────────────────────────────────────
PYTHON=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || true)
if [ -z "$PYTHON" ]; then
  fail "Python is required for JSON editing. Please remove hooks from ${SETTINGS_FILE} manually."
fi

# ── Remove hook script ────────────────────────────────────────────────────────
HOOK_SCRIPT="${HOOKS_DIR}/log_session.py"
if [ -f "$HOOK_SCRIPT" ]; then
  rm "$HOOK_SCRIPT"
  ok "Removed hook script: ${HOOK_SCRIPT}"
else
  info "Hook script not found (already removed?): ${HOOK_SCRIPT}"
fi

# Remove hooks dir if now empty
if [ -d "$HOOKS_DIR" ] && [ -z "$(ls -A "$HOOKS_DIR" 2>/dev/null)" ]; then
  rmdir "$HOOKS_DIR"
  ok "Removed empty hooks directory: ${HOOKS_DIR}"
fi

# ── Remove hook entries from settings.json ────────────────────────────────────
if [ -f "$SETTINGS_FILE" ]; then
  if grep -q "log_session.py" "$SETTINGS_FILE" 2>/dev/null; then
    # Back up before modifying
    cp "$SETTINGS_FILE" "${SETTINGS_FILE}.uninstall.bak"
    info "Backed up settings to: ${SETTINGS_FILE}.uninstall.bak"

    $PYTHON - << PYEOF
import json, sys

try:
    with open("$SETTINGS_FILE", "r") as f:
        settings = json.load(f)
except Exception as e:
    print(f"cc-logger uninstall: cannot read settings.json: {e}", file=sys.stderr)
    sys.exit(0)

hooks = settings.get("hooks", {})

def remove_log_session_entries(hook_list):
    """Remove any hook entry whose command references log_session.py."""
    cleaned = []
    for entry in hook_list:
        inner = entry.get("hooks", [])
        inner_clean = [h for h in inner if "log_session.py" not in h.get("command", "")]
        if inner_clean:
            cleaned.append({**entry, "hooks": inner_clean})
        # If inner_clean is empty, the whole entry is dropped
    return cleaned

changed = False
for event in list(hooks.keys()):
    original = hooks[event]
    cleaned  = remove_log_session_entries(original)
    if cleaned != original:
        hooks[event] = cleaned
        changed = True
    # Remove the event key entirely if no entries remain
    if not hooks[event]:
        del hooks[event]
        changed = True

if changed:
    settings["hooks"] = hooks
    # Remove "hooks" key entirely if empty
    if not settings["hooks"]:
        del settings["hooks"]
    with open("$SETTINGS_FILE", "w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")
    print("  ✓ Hook entries removed from settings.json")
else:
    print("  · No cc-logger entries found in settings.json (nothing changed)")
PYEOF
  else
    info "No cc-logger entries in ${SETTINGS_FILE} (already clean)"
  fi
else
  info "settings.json not found: ${SETTINGS_FILE}"
fi

# ── Remove config file ────────────────────────────────────────────────────────
if [ -f "$CONFIG_FILE" ]; then
  rm "$CONFIG_FILE"
  ok "Removed config: ${CONFIG_FILE}"
else
  info "Config file not found: ${CONFIG_FILE}"
fi

# ── Project-mode extras: gitignore cleanup ────────────────────────────────────
if [ "$GLOBAL" = false ]; then
  GITIGNORE=".gitignore"
  if [ -f "$GITIGNORE" ] && grep -q "cc-logger session logs" "$GITIGNORE" 2>/dev/null; then
    # Remove the cc-logger block from .gitignore using Python (portable sed alternative)
    $PYTHON - << 'PYEOF'
import re
with open(".gitignore", "r") as f:
    content = f.read()
# Remove the cc-logger block (comment + logs/ lines)
cleaned = re.sub(
    r'\n?# cc-logger session logs\nlogs/\n!logs/\.gitkeep\n?',
    '',
    content
)
with open(".gitignore", "w") as f:
    f.write(cleaned)
print("  ✓ Removed cc-logger entries from .gitignore")
PYEOF
  fi

  # Remove logs/.gitkeep placeholder (but leave actual log folders for the user)
  if [ -f "logs/.gitkeep" ]; then
    rm "logs/.gitkeep"
    ok "Removed logs/.gitkeep"
  fi
fi

# ── Purge logs ────────────────────────────────────────────────────────────────
if [ "$PURGE" = true ]; then
  if [ "$GLOBAL" = true ]; then
    if [ -d "$CENTRAL_LOG_DIR" ]; then
      echo ""
      warn "This will permanently delete ALL session logs in: ${CENTRAL_LOG_DIR}"
      printf "  Type 'yes' to confirm: "
      read -r confirmation
      if [ "$confirmation" = "yes" ]; then
        rm -rf "$CENTRAL_LOG_DIR"
        ok "Deleted central log directory: ${CENTRAL_LOG_DIR}"
      else
        info "Skipped log deletion (confirmation not given)"
      fi
    else
      info "Central log directory not found: ${CENTRAL_LOG_DIR}"
    fi
  else
    if [ -d "$LOCAL_LOG_DIR" ]; then
      echo ""
      warn "This will permanently delete ALL session logs in: ${LOCAL_LOG_DIR}/"
      printf "  Type 'yes' to confirm: "
      read -r confirmation
      if [ "$confirmation" = "yes" ]; then
        rm -rf "$LOCAL_LOG_DIR"
        ok "Deleted local log directory: ${LOCAL_LOG_DIR}/"
      else
        info "Skipped log deletion (confirmation not given)"
      fi
    else
      info "Local log directory not found: ${LOCAL_LOG_DIR}/"
    fi
  fi
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "  cc-logger has been uninstalled."
echo ""

if [ "$PURGE" = false ]; then
  if [ "$GLOBAL" = true ]; then
    echo "  Your session logs are still in: ~/.cc-logger/"
    echo "  Delete them with: rm -rf ~/.cc-logger/"
    echo "  Or re-run with:   bash uninstall.sh --global --purge"
  else
    if [ -d "logs" ] && [ "$(ls -A logs 2>/dev/null)" ]; then
      echo "  Your session logs are still in: ./logs/"
      echo "  Delete them with: rm -rf logs/"
      echo "  Or re-run with:   bash uninstall.sh --purge"
    fi
  fi
  echo ""
fi

# ── Detect running Claude Code ────────────────────────────────────────────────
CLAUDE_RUNNING=false
if pgrep -x "claude" > /dev/null 2>&1; then CLAUDE_RUNNING=true; fi
if pgrep -x "Claude" > /dev/null 2>&1; then CLAUDE_RUNNING=true; fi

if [ "$CLAUDE_RUNNING" = true ]; then
  warn "Claude Code is running — start a NEW session for hook removal to take effect."
  echo ""
fi
