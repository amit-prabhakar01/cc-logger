# cc-logger uninstaller for Windows (PowerShell)
# https://github.com/amit-prabhakar01/cc-logger
#
# Usage:
#   .\uninstall.ps1              — remove project-level install (current directory)
#   .\uninstall.ps1 -Global      — remove machine-wide install
#   .\uninstall.ps1 -Purge       — also delete session logs
#   .\uninstall.ps1 -Global -Purge
#
# One-liner (run from your project directory):
#   iwr -useb https://raw.githubusercontent.com/amit-prabhakar01/cc-logger/main/uninstall.ps1 | iex
#
[CmdletBinding()]
param(
    [switch]$Global,
    [switch]$Purge
)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Ok($msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Info($msg) { Write-Host "   ·   $msg" -ForegroundColor Cyan }
function Warn($msg) { Write-Host "  [!]  $msg" -ForegroundColor Yellow }
function Fail($msg) { Write-Host "  [X]  $msg" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "  cc-logger · Uninstaller (Windows)" -ForegroundColor White
Write-Host "  ────────────────────────────────────────────" -ForegroundColor DarkGray
if ($Global) { Write-Host "  Mode: GLOBAL (removing machine-wide install)" -ForegroundColor Cyan }
else         { Write-Host "  Mode: PROJECT (removing install from current directory)" -ForegroundColor Cyan }
if ($Purge)  { Write-Host "  Purge: YES — session logs will be deleted" -ForegroundColor Yellow }
else         { Write-Host "  Purge: NO  — session logs will be kept" -ForegroundColor Gray }
Write-Host ""

# ── Detect Python ─────────────────────────────────────────────────────────────
$PYTHON = $null
foreach ($cmd in @("python3", "python")) {
    try {
        $ver = & $cmd -c "import sys; print(sys.version_info.major)" 2>$null
        if ($ver -ge 3) { $PYTHON = $cmd; break }
    } catch { }
}
if (-not $PYTHON) {
    Fail "Python 3 is required for JSON editing. Remove hook entries from settings.json manually."
}

# ── Resolve paths ─────────────────────────────────────────────────────────────
if ($Global) {
    $HooksDir       = Join-Path $env:USERPROFILE ".claude\hooks"
    $SettingsFile   = Join-Path $env:USERPROFILE ".claude\settings.json"
    $ConfigFile     = Join-Path $env:USERPROFILE ".claude-logger.json"
    $CentralLogDir  = Join-Path $env:USERPROFILE ".cc-logger"
} else {
    $HooksDir       = ".claude\hooks"
    $SettingsFile   = ".claude\settings.json"
    $ConfigFile     = ".claude-logger.json"
    $LocalLogDir    = "logs"
}

$HookScript = Join-Path $HooksDir "log_session.py"

# ── Remove hook script ────────────────────────────────────────────────────────
if (Test-Path $HookScript) {
    Remove-Item $HookScript -Force
    Ok "Removed hook script: $HookScript"
} else {
    Info "Hook script not found (already removed?): $HookScript"
}

# Remove hooks dir if now empty
if (Test-Path $HooksDir) {
    $remaining = Get-ChildItem $HooksDir -ErrorAction SilentlyContinue
    if (-not $remaining) {
        Remove-Item $HooksDir -Force
        Ok "Removed empty hooks directory: $HooksDir"
    }
}

# ── Remove hook entries from settings.json ────────────────────────────────────
if (Test-Path $SettingsFile) {
    $content = Get-Content $SettingsFile -Raw -ErrorAction SilentlyContinue
    if ($content -match "log_session\.py") {
        # Back up
        $backup = "$SettingsFile.uninstall.bak"
        Copy-Item $SettingsFile $backup -Force
        Info "Backed up settings to: $backup"

        # Use embedded Python to safely edit the JSON
        $settingsPath = $SettingsFile -replace "\\", "\\\\"
        $pyScript = @"
import json, sys

try:
    with open(r'$SettingsFile', 'r') as f:
        settings = json.load(f)
except Exception as e:
    print(f'Cannot read settings.json: {e}', file=sys.stderr)
    sys.exit(0)

hooks = settings.get('hooks', {})

def clean_entries(hook_list):
    cleaned = []
    for entry in hook_list:
        inner = entry.get('hooks', [])
        inner_clean = [h for h in inner if 'log_session.py' not in h.get('command', '')]
        if inner_clean:
            cleaned.append({**entry, 'hooks': inner_clean})
    return cleaned

changed = False
for event in list(hooks.keys()):
    original = hooks[event]
    cleaned  = clean_entries(original)
    if cleaned != original:
        hooks[event] = cleaned
        changed = True
    if not hooks[event]:
        del hooks[event]
        changed = True

if changed:
    settings['hooks'] = hooks
    if not settings.get('hooks'):
        settings.pop('hooks', None)
    with open(r'$SettingsFile', 'w') as f:
        json.dump(settings, f, indent=2)
        f.write('\n')
    print('  [OK] Hook entries removed from settings.json')
else:
    print('   ·   No cc-logger entries found in settings.json')
"@
        & $PYTHON -c $pyScript
    } else {
        Info "No cc-logger entries in settings.json (already clean)"
    }
} else {
    Info "settings.json not found: $SettingsFile"
}

# ── Remove config file ────────────────────────────────────────────────────────
if (Test-Path $ConfigFile) {
    Remove-Item $ConfigFile -Force
    Ok "Removed config: $ConfigFile"
} else {
    Info "Config file not found: $ConfigFile"
}

# ── Project-mode: clean .gitignore ────────────────────────────────────────────
if (-not $Global) {
    if ((Test-Path ".gitignore") -and ((Get-Content ".gitignore" -Raw) -match "cc-logger session logs")) {
        $pyClean = @'
import re
with open(".gitignore", "r") as f:
    content = f.read()
cleaned = re.sub(
    r'\n?# cc-logger session logs\nlogs/\n!logs/\.gitkeep\n?',
    '',
    content
)
with open(".gitignore", "w") as f:
    f.write(cleaned)
print("  [OK] Removed cc-logger entries from .gitignore")
'@
        & $PYTHON -c $pyClean
    }

    if (Test-Path "logs\.gitkeep") {
        Remove-Item "logs\.gitkeep" -Force
        Ok "Removed logs/.gitkeep"
    }
}

# ── Purge logs ────────────────────────────────────────────────────────────────
if ($Purge) {
    if ($Global) {
        if (Test-Path $CentralLogDir) {
            Write-Host ""
            Warn "This will permanently delete ALL session logs in: $CentralLogDir"
            $confirm = Read-Host "  Type 'yes' to confirm"
            if ($confirm -eq "yes") {
                Remove-Item $CentralLogDir -Recurse -Force
                Ok "Deleted central log directory: $CentralLogDir"
            } else {
                Info "Skipped log deletion (confirmation not given)"
            }
        } else {
            Info "Central log directory not found: $CentralLogDir"
        }
    } else {
        if (Test-Path $LocalLogDir) {
            Write-Host ""
            Warn "This will permanently delete ALL session logs in: $LocalLogDir\"
            $confirm = Read-Host "  Type 'yes' to confirm"
            if ($confirm -eq "yes") {
                Remove-Item $LocalLogDir -Recurse -Force
                Ok "Deleted local log directory: $LocalLogDir\"
            } else {
                Info "Skipped log deletion (confirmation not given)"
            }
        } else {
            Info "Local log directory not found: $LocalLogDir"
        }
    }
}

# ── Summary ───────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  cc-logger has been uninstalled." -ForegroundColor Green
Write-Host ""

if (-not $Purge) {
    if ($Global) {
        Write-Host "  Your session logs are still in: $env:USERPROFILE\.cc-logger\" -ForegroundColor Gray
        Write-Host "  Delete them with: Remove-Item -Recurse -Force `$env:USERPROFILE\.cc-logger" -ForegroundColor Gray
        Write-Host "  Or re-run with:   .\uninstall.ps1 -Global -Purge" -ForegroundColor Gray
    } else {
        if ((Test-Path "logs") -and (Get-ChildItem "logs" -ErrorAction SilentlyContinue)) {
            Write-Host "  Your session logs are still in: .\logs\" -ForegroundColor Gray
            Write-Host "  Delete them with: Remove-Item -Recurse -Force logs" -ForegroundColor Gray
            Write-Host "  Or re-run with:   .\uninstall.ps1 -Purge" -ForegroundColor Gray
        }
    }
    Write-Host ""
}

# ── Detect running Claude Code ────────────────────────────────────────────────
$claudeRunning = Get-Process -Name "claude","Claude" -ErrorAction SilentlyContinue
if ($claudeRunning) {
    Warn "Claude Code is running — start a NEW session for hook removal to take effect."
    Write-Host ""
}
