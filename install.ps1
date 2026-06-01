<#
.SYNOPSIS
    cc-logger global installer for Windows.

.DESCRIPTION
    Installs the cc-logger hook globally so every Claude Code session on this
    machine — in any project, VS Code, Cursor, or terminal — is logged
    automatically to %USERPROFILE%\.cc-logger\<project>\<session>\.

.EXAMPLE
    # One-liner (run from PowerShell):
    iwr -useb https://raw.githubusercontent.com/amit-prabhakar01/cc-logger/main/install.ps1 | iex

    # Or if you have cloned the repo:
    .\install.ps1
#>

$ErrorActionPreference = "Stop"

$REPO_URL = "https://raw.githubusercontent.com/amit-prabhakar01/cc-logger/main"
$HOME_DIR  = $env:USERPROFILE
$HOOKS_DIR = Join-Path $HOME_DIR ".claude\hooks"
$SETTINGS  = Join-Path $HOME_DIR ".claude\settings.json"
$CONFIG    = Join-Path $HOME_DIR ".claude-logger.json"
$LOG_ROOT  = Join-Path $HOME_DIR ".cc-logger"

function Write-Ok   { param($msg) Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Warn { param($msg) Write-Host "  [!!] $msg" -ForegroundColor Yellow }
function Write-Info { param($msg) Write-Host "   ·  $msg"  -ForegroundColor Cyan }
function Write-Fail { param($msg) Write-Host "  [X] $msg"  -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "  cc-logger - Claude Code Session Logger" -ForegroundColor Cyan
Write-Host "  ----------------------------------------" -ForegroundColor Cyan
Write-Host "  Mode: GLOBAL (logs all Claude Code sessions on this machine)"
Write-Host ""

# ── FIX 1: Safe script directory resolution ──────────────────────────────────
# $MyInvocation.MyCommand.Path is null when the script is piped via iex.
# Fall back to the current directory in that case.
if ($MyInvocation.MyCommand.Path) {
    $SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
} else {
    $SCRIPT_DIR = $PWD.Path
}

# ── Detect Python 3.8+ ───────────────────────────────────────────────────────
$PYTHON = $null
foreach ($cmd in @("python3", "python")) {
    try {
        $ver = & $cmd -c "import sys; print(sys.version_info.major * 10 + sys.version_info.minor)" 2>$null
        if ($LASTEXITCODE -eq 0 -and [int]$ver -ge 38) { $PYTHON = $cmd; break }
    } catch {}
}
if (-not $PYTHON) {
    Write-Fail "Python 3.8+ is required but not found. Install from https://python.org and retry."
}

$PY_VER = & $PYTHON -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
Write-Ok "Python $PY_VER found ($PYTHON)"

# ── FIX 2: Get Python's own path — most reliable cross-environment approach ──
# Using sys.executable is more reliable than (Get-Command).Source across
# different Python distributions (Anaconda, Microsoft Store, pyenv, etc.)
$PYTHON_PATH = & $PYTHON -c "import sys; print(sys.executable)"
if (-not $PYTHON_PATH -or -not (Test-Path $PYTHON_PATH)) {
    Write-Fail "Could not determine Python executable path. Is Python in your PATH?"
}
Write-Info "Python executable: $PYTHON_PATH"

# ── Create hooks directory ────────────────────────────────────────────────────
New-Item -ItemType Directory -Force -Path $HOOKS_DIR | Out-Null
Write-Ok "$HOOKS_DIR ready"

# ── Copy or download hook script ──────────────────────────────────────────────
$HOOK_SCRIPT = Join-Path $HOOKS_DIR "log_session.py"
$LOCAL_HOOK  = Join-Path $SCRIPT_DIR ".claude\hooks\log_session.py"

if (Test-Path $LOCAL_HOOK) {
    Copy-Item $LOCAL_HOOK -Destination $HOOK_SCRIPT -Force
    Write-Ok "Hook script copied from local repo"
} else {
    try {
        Invoke-WebRequest -Uri "$REPO_URL/.claude/hooks/log_session.py" `
                          -OutFile $HOOK_SCRIPT -UseBasicParsing
        Write-Ok "Hook script downloaded"
    } catch {
        Write-Fail "Could not download hook script: $_"
    }
}

# ── FIX 3: Pass paths to Python via environment variables ────────────────────
# Embedding Windows paths (with backslashes and spaces) directly into a Python
# here-string causes SyntaxErrors. Using env vars avoids all quoting issues.
$env:CC_LOGGER_SETTINGS   = $SETTINGS
$env:CC_LOGGER_PYTHON     = $PYTHON_PATH
$env:CC_LOGGER_HOOK_SCRIPT = $HOOK_SCRIPT

$MERGE_SCRIPT = @'
import json, sys, os, shutil

settings_file = os.environ["CC_LOGGER_SETTINGS"]
python_path   = os.environ["CC_LOGGER_PYTHON"]
hook_script   = os.environ["CC_LOGGER_HOOK_SCRIPT"]

# Build the hook command — quoted paths handle spaces in usernames/dirs
hook_cmd = '"{}" "{}"'.format(python_path, hook_script)

os.makedirs(os.path.dirname(settings_file), exist_ok=True)

if os.path.exists(settings_file):
    shutil.copy(settings_file, settings_file + ".bak")
    try:
        with open(settings_file, "r", encoding="utf-8") as f:
            settings = json.load(f)
    except Exception as e:
        print("WARN: could not parse existing settings.json ({}), starting fresh".format(e), file=sys.stderr)
        settings = {}
else:
    settings = {}

settings.setdefault("hooks", {})

# PostToolUse — add only if not already registered
settings["hooks"].setdefault("PostToolUse", [])
existing_matchers = [e.get("matcher") for e in settings["hooks"]["PostToolUse"]]
if "*" not in existing_matchers:
    settings["hooks"]["PostToolUse"].append({
        "matcher": "*",
        "hooks": [{"type": "command", "command": hook_cmd}]
    })

# Stop — add only if not already registered
settings["hooks"].setdefault("Stop", [])
stop_cmds = [
    h.get("command", "")
    for e in settings["hooks"]["Stop"]
    for h in e.get("hooks", [])
]
if hook_cmd not in stop_cmds:
    settings["hooks"]["Stop"].append({
        "hooks": [{"type": "command", "command": hook_cmd}]
    })

with open(settings_file, "w", encoding="utf-8") as f:
    json.dump(settings, f, indent=2)
    f.write("\n")

print("OK")
'@

try {
    $result = & $PYTHON -c $MERGE_SCRIPT 2>&1
    if ($result -match "^OK") {
        Write-Ok "Hooks registered in $SETTINGS"
    } else {
        Write-Fail "Failed to update settings.json: $result"
    }
} catch {
    Write-Fail "Failed to update settings.json: $_"
} finally {
    # Clean up env vars
    Remove-Item Env:\CC_LOGGER_SETTINGS    -ErrorAction SilentlyContinue
    Remove-Item Env:\CC_LOGGER_PYTHON      -ErrorAction SilentlyContinue
    Remove-Item Env:\CC_LOGGER_HOOK_SCRIPT -ErrorAction SilentlyContinue
}

# ── Write global config ───────────────────────────────────────────────────────
if (-not (Test-Path $CONFIG)) {
    $LOCAL_CFG = Join-Path $SCRIPT_DIR ".claude-logger.json"
    if (Test-Path $LOCAL_CFG) {
        Copy-Item $LOCAL_CFG -Destination $CONFIG -Force
    } else {
        $cfg = [ordered]@{
            "_comment"  = "cc-logger config. Project .claude-logger.json overrides this."
            "enabled"   = $true
            "filtering" = [ordered]@{
                "excludeTools" = @("Read", "Glob", "Grep")
                "includeTools" = @()
            }
            "output"    = [ordered]@{
                "maxInlineChars"      = 3000
                "minToolCallsToWrite" = 1
            }
        }
        $cfg | ConvertTo-Json -Depth 4 | Set-Content $CONFIG -Encoding UTF8
    }
    Write-Ok "Created $CONFIG"
} else {
    Write-Ok "$CONFIG already present (skipping)"
}

# ── Create central log root ───────────────────────────────────────────────────
New-Item -ItemType Directory -Force -Path $LOG_ROOT | Out-Null
Write-Ok "Central log root: $LOG_ROOT"

# ── Summary ───────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  cc-logger installed successfully." -ForegroundColor Green
Write-Host ""
Write-Host "  Hook:   $HOOK_SCRIPT"
Write-Host "  Config: $CONFIG"
Write-Host "  Logs:   $LOG_ROOT\<project>\<session>\"
Write-Host ""

$claudeRunning = Get-Process -Name "claude","Claude" -ErrorAction SilentlyContinue
if ($claudeRunning) {
    Write-Warn "Claude Code is running — start a NEW session for hooks to take effect."
    Write-Host "     cc-logger will automatically recover tool calls from the current"
    Write-Host "     session when the new session begins."
} else {
    Write-Host "  Start a Claude Code session — your first log appears automatically."
    Write-Host "  (If Claude Code is already open, start a new session first.)"
}
Write-Host ""
Write-Host "  Disable logging anytime:  `$env:NO_CC_LOGS = '1'"
Write-Host "  Uninstall:                .\uninstall.ps1"
Write-Host ""
