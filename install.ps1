<#
.SYNOPSIS
    cc-logger global installer for Windows.

.DESCRIPTION
    Installs the cc-logger hook globally so every Claude Code session on this
    machine — in any project, VS Code, Cursor, or terminal — is logged
    automatically to %USERPROFILE%\.cc-logger\<project>\<session>\.

.EXAMPLE
    # Run from PowerShell (Admin not required):
    iwr -useb https://raw.githubusercontent.com/amit-prabhakar01/cc-logger/main/install.ps1 | iex

    # Or if you have cloned the repo:
    .\install.ps1
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$REPO_URL = "https://raw.githubusercontent.com/amit-prabhakar01/cc-logger/main"
$HOME_DIR  = $env:USERPROFILE
$HOOKS_DIR = Join-Path $HOME_DIR ".claude\hooks"
$SETTINGS  = Join-Path $HOME_DIR ".claude\settings.json"
$CONFIG    = Join-Path $HOME_DIR ".claude-logger.json"
$LOG_ROOT  = Join-Path $HOME_DIR ".cc-logger"

function Write-Ok   { param($msg) Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Warn { param($msg) Write-Host "  [!!] $msg" -ForegroundColor Yellow }
function Write-Fail { param($msg) Write-Host "  [X]  $msg" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "  cc-logger · Claude Code Session Logger" -ForegroundColor Cyan
Write-Host "  ----------------------------------------" -ForegroundColor Cyan
Write-Host "  Mode: GLOBAL (logs all Claude Code sessions on this machine)"
Write-Host ""

# ── Detect Python ─────────────────────────────────────────────────────────────
$PYTHON = $null
foreach ($cmd in @("python3", "python")) {
    try {
        $ver = & $cmd -c "import sys; print(sys.version_info.major * 10 + sys.version_info.minor)" 2>$null
        if ([int]$ver -ge 38) { $PYTHON = $cmd; break }
    } catch {}
}
if (-not $PYTHON) {
    Write-Fail "Python 3.8+ is required but not found. Install from https://python.org and retry."
}
$PY_VER = & $PYTHON -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
Write-Ok "Python $PY_VER found ($PYTHON)"

# ── Create hooks directory ────────────────────────────────────────────────────
New-Item -ItemType Directory -Force -Path $HOOKS_DIR | Out-Null
Write-Ok "$HOOKS_DIR ready"

# ── Copy or download hook script ──────────────────────────────────────────────
$HOOK_SCRIPT = Join-Path $HOOKS_DIR "log_session.py"
$SCRIPT_DIR  = Split-Path -Parent $MyInvocation.MyCommand.Path
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
        Write-Fail "Could not download hook script. Check your internet connection."
    }
}

# ── Build hook command (full path, no env vars) ───────────────────────────────
$PYTHON_PATH = (Get-Command $PYTHON).Source
$HOOK_CMD    = "`"$PYTHON_PATH`" `"$HOOK_SCRIPT`""

# ── Merge hooks into settings.json using embedded Python ─────────────────────
$MERGE_SCRIPT = @"
import json, sys, os

settings_file = r'$SETTINGS'
hook_cmd      = r'$HOOK_CMD'.replace('`"', '"')

os.makedirs(os.path.dirname(settings_file), exist_ok=True)

if os.path.exists(settings_file):
    import shutil
    shutil.copy(settings_file, settings_file + '.bak')
    with open(settings_file) as f:
        settings = json.load(f)
else:
    settings = {}

settings.setdefault('hooks', {})

# PostToolUse
settings['hooks'].setdefault('PostToolUse', [])
existing = [e.get('matcher') for e in settings['hooks']['PostToolUse']]
if '*' not in existing:
    settings['hooks']['PostToolUse'].append({
        'matcher': '*',
        'hooks': [{'type': 'command', 'command': hook_cmd}]
    })

# Stop
settings['hooks'].setdefault('Stop', [])
stop_cmds = [h.get('command','')
             for e in settings['hooks']['Stop']
             for h in e.get('hooks',[])]
if hook_cmd not in stop_cmds:
    settings['hooks']['Stop'].append({
        'hooks': [{'type': 'command', 'command': hook_cmd}]
    })

with open(settings_file, 'w') as f:
    json.dump(settings, f, indent=2)
    f.write('\n')

print('OK')
"@

$result = & $PYTHON -c $MERGE_SCRIPT
if ($result -eq "OK") {
    Write-Ok "Hooks registered in $SETTINGS"
} else {
    Write-Fail "Failed to update settings.json: $result"
}

# ── Write global config ───────────────────────────────────────────────────────
if (-not (Test-Path $CONFIG)) {
    $LOCAL_CFG = Join-Path $SCRIPT_DIR ".claude-logger.json"
    if (Test-Path $LOCAL_CFG) {
        Copy-Item $LOCAL_CFG -Destination $CONFIG -Force
    } else {
        $cfg = @{
            "_comment"  = "cc-logger config. Project .claude-logger.json overrides this."
            "enabled"   = $true
            "filtering" = @{ "excludeTools" = @("Read","Glob","Grep"); "includeTools" = @() }
            "output"    = @{ "maxInlineChars" = 3000; "minToolCallsToWrite" = 1 }
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
Write-Host "  cc-logger installed." -ForegroundColor Green
Write-Host ""
Write-Host "  Hook:    $HOOK_SCRIPT"
Write-Host "  Config:  $CONFIG  (project .claude-logger.json overrides this)"
Write-Host "  Logs:    $LOG_ROOT\<project-name>\<session>\"
Write-Host ""

# Check if Claude is running
$claudeRunning = Get-Process -Name "claude","Claude" -ErrorAction SilentlyContinue
if ($claudeRunning) {
    Write-Warn "Claude Code is running — start a NEW session for hooks to take effect."
    Write-Host "     cc-logger will automatically recover any tool calls that"
    Write-Host "     happened before this install when the new session begins."
} else {
    Write-Host "  Start a Claude Code session — your first log appears automatically."
    Write-Host "  (If Claude Code is already open, start a new session first.)"
}
Write-Host ""
Write-Host "  Disable logging anytime: `$env:NO_CC_LOGS = '1'"
Write-Host ""
