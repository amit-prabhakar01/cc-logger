#!/usr/bin/env python3
"""
cc-logger · PostToolUse + Stop Hook
=====================================
Automatically captures every Claude Code tool invocation into structured
session logs — one folder per session containing session.md and session.json.
Also fires on the Stop event to append a session summary at session end.

Usage:  Triggered automatically via .claude/settings.json hooks.
Escape: Set NO_CC_LOGS=1 in environment to disable logging for a session.

Python 3.8+ compatible · MIT License · https://github.com/amit-prabhakar01/cc-logger
"""

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CONFIG_FILENAME   = ".claude-logger.json"
LOG_DIR_NAME      = "logs"
SCHEMA_VERSION    = "1"
DEFAULT_MAX_INLINE_CHARS = 3000
DEFAULT_MIN_TOOL_CALLS   = 1

# P2: Grep added to default exclusion list (high volume, low signal)
DEFAULT_EXCLUDE_TOOLS = ["Read", "Glob", "Grep"]

# ---------------------------------------------------------------------------
# Sensitive data redaction — always on, cannot be disabled
# ---------------------------------------------------------------------------

REDACT_PATTERNS: List[re.Pattern] = [
    re.compile(r'(?i)(api[_-]?key|apikey)\s*[=:]\s*\S+'),
    re.compile(r'(?i)(secret|password|passwd|pwd)\s*[=:]\s*\S+'),
    re.compile(r'(?i)(token|auth)\s*[=:]\s*\S+'),
    re.compile(r'(?i)bearer\s+[A-Za-z0-9\-._~+/]+=*'),   # Authorization: Bearer <token>
    re.compile(r'(?i)aws_access_key_id\s*[=:]\s*\S+'),
    re.compile(r'(?i)aws_secret_access_key\s*[=:]\s*\S+'),
    re.compile(r'[A-Za-z0-9+/]{40,}={0,2}'),              # base64 secrets
    re.compile(r'sk-[A-Za-z0-9\-]{15,}'),                  # OpenAI/Anthropic-style keys (sk-proj-..., sk-ant-...)
    re.compile(r'ghp_[A-Za-z0-9]{36}'),                    # GitHub PATs
    re.compile(r'xoxb-[A-Za-z0-9\-]+'),                    # Slack tokens
]

REDACT_REPLACEMENT = "[REDACTED]"

# P3: Config validation schema
CONFIG_SCHEMA = {
    "enabled":          bool,
    "filtering":        dict,
    "output":           dict,
    "excludeTools":     list,
    "includeTools":     list,
    "maxInlineChars":   int,
    "minToolCallsToWrite": int,
    "_comment":         str,
}


def redact(text: str) -> str:
    for pattern in REDACT_PATTERNS:
        text = pattern.sub(REDACT_REPLACEMENT, text)
    return text


def redact_recursive(obj: Any, depth: int = 0) -> Any:
    if depth > 8:
        return obj
    if isinstance(obj, str):
        return redact(obj)
    if isinstance(obj, dict):
        return {
            k: (REDACT_REPLACEMENT if any(
                re.search(p, k, re.I)
                for p in [r'password', r'secret', r'token', r'api.?key', r'auth']
            ) else redact_recursive(v, depth + 1))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [redact_recursive(item, depth + 1) for item in obj]
    return obj


# ---------------------------------------------------------------------------
# Configuration loading + P3: validation
# ---------------------------------------------------------------------------

def load_config(project_root: Path) -> Dict[str, Any]:
    """Load .claude-logger.json with sane defaults. Warns on bad values."""
    defaults: Dict[str, Any] = {
        "enabled":             True,
        "excludeTools":        DEFAULT_EXCLUDE_TOOLS,
        "includeTools":        [],
        "maxInlineChars":      DEFAULT_MAX_INLINE_CHARS,
        "minToolCallsToWrite": DEFAULT_MIN_TOOL_CALLS,
    }
    config_path = project_root / CONFIG_FILENAME
    if not config_path.exists():
        return defaults

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            user_config = json.load(f)
    except json.JSONDecodeError as e:
        print(f"cc-logger: invalid JSON in {CONFIG_FILENAME}: {e}", file=sys.stderr)
        return defaults
    except Exception as e:
        print(f"cc-logger: could not read {CONFIG_FILENAME}: {e}", file=sys.stderr)
        return defaults

    # P3: validate known keys
    for key, val in user_config.items():
        if key in CONFIG_SCHEMA:
            expected = CONFIG_SCHEMA[key]
            if not isinstance(val, expected):
                print(
                    f"cc-logger: config warning — '{key}' should be {expected.__name__}, "
                    f"got {type(val).__name__}. Using default.",
                    file=sys.stderr
                )
        elif not key.startswith("_"):
            print(f"cc-logger: config warning — unknown key '{key}' (ignored).", file=sys.stderr)

    defaults.update(user_config)

    # Flatten nested "filtering" and "output" blocks so both config shapes work
    if "filtering" in defaults and isinstance(defaults["filtering"], dict):
        filt = defaults["filtering"]
        if "excludeTools" in filt:
            defaults["excludeTools"] = filt["excludeTools"]
        if "includeTools" in filt:
            defaults["includeTools"] = filt["includeTools"]

    if "output" in defaults and isinstance(defaults["output"], dict):
        out = defaults["output"]
        if "maxInlineChars" in out:
            defaults["maxInlineChars"] = out["maxInlineChars"]
        if "minToolCallsToWrite" in out:
            defaults["minToolCallsToWrite"] = out["minToolCallsToWrite"]

    return defaults


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def resolve_project_root(transcript_path: str) -> Path:
    p = Path(transcript_path)
    return p.parent.parent.parent


def get_session_folder_name(session_id: str) -> str:
    """
    YYYYMMDD_HHMMSS_<md5hash8>
    MD5 hash avoids prefix collisions even on non-UUID session IDs.
    """
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    short_id = hashlib.md5(session_id.encode()).hexdigest()[:8]
    return f"{ts}_{short_id}"


# ---------------------------------------------------------------------------
# P5: Git state capture
# ---------------------------------------------------------------------------

def get_git_state(cwd: str) -> Dict[str, str]:
    """Capture current git branch and HEAD commit SHA. Returns empty dict if not a git repo."""
    state: Dict[str, str] = {}
    try:
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd, capture_output=True, text=True, timeout=3
        ).stdout.strip()
        head = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=cwd, capture_output=True, text=True, timeout=3
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=cwd, capture_output=True, text=True, timeout=3
        ).stdout.strip()
        if branch:
            state["branch"] = branch
        if head:
            state["head"] = head
        state["dirty_files"] = str(len(dirty.splitlines())) if dirty else "0"
    except Exception:
        pass
    return state


def get_git_diff_stat(cwd: str) -> str:
    """Get git diff --stat since session start (best effort)."""
    try:
        result = subprocess.run(
            ["git", "diff", "--stat", "HEAD"],
            cwd=cwd, capture_output=True, text=True, timeout=3
        )
        stat = result.stdout.strip()
        return stat.splitlines()[-1] if stat else ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Tool-specific formatters
# ---------------------------------------------------------------------------

TOOL_ICONS = {
    "Bash": "⚡", "Edit": "✏️", "Write": "📝", "MultiEdit": "✏️",
    "Read": "👁️", "Grep": "🔍", "Glob": "📂", "Agent": "🤖",
    "WebFetch": "🌐", "WebSearch": "🔎", "TodoWrite": "✅",
}


def format_tool_input(tool_name: str, tool_input: Any, max_chars: int) -> str:
    if not tool_input:
        return "_No input_\n"
    tool_input = redact_recursive(tool_input)
    raw_json = json.dumps(tool_input, indent=2, default=str)

    if tool_name == "Bash":
        cmd = tool_input.get("command", "") if isinstance(tool_input, dict) else str(tool_input)
        return f"**Command:** `{redact(cmd)}`\n"
    elif tool_name in ("Edit", "MultiEdit", "Write"):
        path = tool_input.get("file_path", tool_input.get("path", "")) if isinstance(tool_input, dict) else ""
        md = f"**File:** `{path}`\n"
        if isinstance(tool_input, dict) and "old_string" in tool_input:
            md += "\n<details><summary>Edit diff</summary>\n\n```diff\n"
            for line in str(tool_input.get("old_string", "")).splitlines()[:20]:
                md += f"- {line}\n"
            for line in str(tool_input.get("new_string", "")).splitlines()[:20]:
                md += f"+ {line}\n"
            md += "```\n</details>\n"
        return md
    elif tool_name in ("Grep", "Glob"):
        pattern = tool_input.get("pattern", "") if isinstance(tool_input, dict) else ""
        path    = tool_input.get("path", ".") if isinstance(tool_input, dict) else "."
        return f"**Pattern:** `{pattern}` in `{path}`\n"
    elif tool_name == "Agent":
        prompt = str(tool_input.get("prompt", ""))[:200] if isinstance(tool_input, dict) else str(tool_input)[:200]
        suffix = "..." if len(str(tool_input.get("prompt", "") if isinstance(tool_input, dict) else "")) > 200 else ""
        return f"**Prompt:** {prompt}{suffix}\n"
    else:
        snippet = raw_json[:max_chars]
        if len(raw_json) > max_chars:
            snippet += f"\n... ({len(raw_json) - max_chars} more chars)"
        return f"```json\n{snippet}\n```\n"


def format_tool_response(tool_name: str, tool_response: Any, max_chars: int) -> str:
    if tool_response is None:
        return "_No response_\n"
    tool_response = redact_recursive(tool_response)

    if tool_name == "Bash":
        output    = tool_response.get("output", "") if isinstance(tool_response, dict) else str(tool_response)
        exit_code = tool_response.get("exit_code", 0) if isinstance(tool_response, dict) else 0
        output    = redact(output)
        lines     = output.splitlines()
        n         = len(lines)
        if len(output) > max_chars:
            head = "\n".join(lines[:15])
            tail = "\n".join(lines[-5:]) if n > 20 else ""
            display = head + (f"\n... ({n - 20} lines omitted) ...\n{tail}" if tail else "")
        else:
            display = output
        return f"<details><summary>Output ({n} lines) · exit {exit_code}</summary>\n\n```\n{display}\n```\n</details>\n"

    if tool_name == "Agent" and isinstance(tool_response, dict):
        if tool_response.get("status") == "async_launched":
            return f"**Status:** Background agent launched · ID: `{tool_response.get('agent_id','?')}`\n"
        final_text = str(tool_response.get("final_text", ""))
        preview    = final_text[:500] + ("..." if len(final_text) > 500 else "")
        usage      = tool_response.get("usage", {})
        md = f"**Result:** {preview}\n"
        if usage:
            md += f"\n**Tokens:** {usage.get('input_tokens',0)} in / {usage.get('output_tokens',0)} out\n"
        return md

    raw = json.dumps(tool_response, indent=2, default=str)
    snippet = raw[:max_chars]
    if len(raw) > max_chars:
        snippet += f"\n... ({len(raw) - max_chars} more chars)"
    return f"```json\n{snippet}\n```\n"


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

def get_and_increment_call_index(session_dir: Path) -> int:
    counter_file = session_dir / ".call_index"
    try:
        idx = int(counter_file.read_text().strip()) + 1 if counter_file.exists() else 1
        counter_file.write_text(str(idx))
        return idx
    except Exception:
        return 0


def get_or_create_session_dir(logs_root: Path, session_id: str) -> Path:
    """
    Find existing session dir or create a new one.
    Uses MD5 hash suffix — collision-proof even for non-UUID session IDs.
    """
    short_id = hashlib.md5(session_id.encode()).hexdigest()[:8]
    if logs_root.exists():
        for entry in logs_root.iterdir():
            if entry.is_dir() and entry.name.endswith(short_id):
                return entry
    folder_name = get_session_folder_name(session_id)
    session_dir = logs_root / folder_name
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


# ---------------------------------------------------------------------------
# Markdown writer — PostToolUse
# ---------------------------------------------------------------------------

def write_markdown_entry(session_dir: Path, payload: Dict[str, Any],
                         call_index: int, config: Dict[str, Any]) -> None:
    md_file   = session_dir / "session.md"
    tool_name = payload.get("tool_name", "Unknown")
    timestamp = datetime.now(tz=timezone.utc).strftime("%H:%M:%S")
    icon      = TOOL_ICONS.get(tool_name, "🔧")
    max_chars = config.get("maxInlineChars", DEFAULT_MAX_INLINE_CHARS)

    input_md    = format_tool_input(tool_name, payload.get("tool_input"), max_chars)
    response_md = format_tool_response(tool_name, payload.get("tool_response"), max_chars)

    entry  = f"\n## [{timestamp}] {icon} {tool_name} · Call #{call_index}\n\n"
    entry += input_md + "\n"
    entry += response_md + "\n"
    entry += "---\n"

    if not md_file.exists():
        session_id  = payload.get("session_id", "unknown")
        cwd         = payload.get("cwd", "unknown")
        started     = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        git         = get_git_state(cwd)
        branch_line = f"| Branch | `{git.get('branch','—')}` |\n" if git else ""
        head_line   = f"| Commit | `{git.get('head','—')}` |\n" if git else ""
        header = (
            f"# cc-logger Session · {started}\n\n"
            f"| Field | Value |\n"
            f"|-------|-------|\n"
            f"| Session ID | `{session_id[:16]}...` |\n"
            f"| Working Dir | `{cwd}` |\n"
            f"{branch_line}{head_line}"
            f"\n---\n"
        )
        md_file.write_text(header, encoding="utf-8")

    with open(md_file, "a", encoding="utf-8") as f:
        f.write(entry)


# ---------------------------------------------------------------------------
# P1: Markdown writer — Stop event (session summary)
# ---------------------------------------------------------------------------

def write_markdown_summary(session_dir: Path, payload: Dict[str, Any]) -> None:
    """Append a session summary block when the Stop hook fires."""
    md_file = session_dir / "session.md"
    if not md_file.exists():
        return

    # Load JSON for stats
    json_file = session_dir / "session.json"
    data: Dict[str, Any] = {}
    if json_file.exists():
        try:
            data = json.loads(json_file.read_text())
        except Exception:
            pass

    cwd         = payload.get("cwd", "")
    ended_at    = datetime.now(tz=timezone.utc)
    ended_str   = ended_at.strftime("%Y-%m-%d %H:%M:%S UTC")

    # Duration
    duration_str = "—"
    started_at_str = data.get("started_at", "")
    if started_at_str:
        try:
            started_at = datetime.fromisoformat(started_at_str.replace("Z", "+00:00"))
            delta = ended_at - started_at
            mins, secs = divmod(int(delta.total_seconds()), 60)
            duration_str = f"{mins}m {secs}s"
        except Exception:
            pass

    total_calls   = data.get("summary", {}).get("total_tool_calls", "—")
    files_mod     = data.get("summary", {}).get("files_modified", [])
    cmds_run      = data.get("summary", {}).get("commands_run", [])
    git_diff      = get_git_diff_stat(cwd) if cwd else ""

    files_list = "\n".join(f"  - `{f}`" for f in files_mod) if files_mod else "  _(none)_"
    cmds_list  = "\n".join(f"  - `{c}`" for c in cmds_run[:10]) if cmds_run else "  _(none)_"

    summary = (
        f"\n---\n\n"
        f"## Session Summary\n\n"
        f"| Metric | Value |\n"
        f"|--------|-------|\n"
        f"| Ended | {ended_str} |\n"
        f"| Duration | {duration_str} |\n"
        f"| Total tool calls | {total_calls} |\n"
        f"| Files modified | {len(files_mod)} |\n"
        f"| Commands run | {len(cmds_run)} |\n"
    )
    if git_diff:
        summary += f"| Git delta | `{git_diff}` |\n"

    summary += f"\n**Files modified:**\n{files_list}\n"
    summary += f"\n**Commands run:**\n{cmds_list}\n"
    summary += f"\n---\n*Logged by [cc-logger](https://github.com/amit-prabhakar01/cc-logger)*\n"

    with open(md_file, "a", encoding="utf-8") as f:
        f.write(summary)

    # Update JSON with end time and duration
    if data:
        data["ended_at"]  = ended_at.isoformat()
        data["duration"]  = duration_str
        if git_diff:
            data["summary"]["git_diff_stat"] = git_diff
        try:
            json_file.write_text(json.dumps(data, indent=2, default=str))
        except Exception:
            pass


# ---------------------------------------------------------------------------
# JSON writer — PostToolUse
# ---------------------------------------------------------------------------

def load_or_init_json(session_dir: Path, payload: Dict[str, Any]) -> Dict[str, Any]:
    json_file = session_dir / "session.json"
    if json_file.exists():
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    cwd = payload.get("cwd", "unknown")
    git = get_git_state(cwd)  # P5: capture git state at session start

    return {
        "schema_version": SCHEMA_VERSION,
        "session_id":     payload.get("session_id", "unknown"),
        "started_at":     datetime.now(tz=timezone.utc).isoformat(),
        "working_dir":    cwd,
        "git":            git,           # P5: branch, head, dirty_files
        "tool_calls":     [],
        "summary": {
            "total_tool_calls": 0,
            "files_modified":   [],
            "commands_run":     [],
        },
    }


def append_json_entry(session_dir: Path, payload: Dict[str, Any],
                      call_index: int, config: Dict[str, Any]) -> None:
    json_file  = session_dir / "session.json"
    data       = load_or_init_json(session_dir, payload)
    tool_name  = payload.get("tool_name", "Unknown")
    tool_input = redact_recursive(payload.get("tool_input", {}))
    tool_resp  = redact_recursive(payload.get("tool_response", {}))

    input_summary: Dict[str, Any] = {}
    if tool_name == "Bash" and isinstance(tool_input, dict):
        cmd = redact(tool_input.get("command", ""))
        input_summary["command"] = cmd
        # P4: use a set to avoid duplicates in commands_run
        if cmd and cmd not in data["summary"]["commands_run"]:
            data["summary"]["commands_run"].append(cmd)
    elif tool_name in ("Edit", "Write", "MultiEdit") and isinstance(tool_input, dict):
        fp = tool_input.get("file_path", tool_input.get("path", ""))
        input_summary["file_path"] = fp
        # P4: deduplicate files_modified
        if fp and fp not in data["summary"]["files_modified"]:
            data["summary"]["files_modified"].append(fp)
    elif tool_name in ("Grep", "Glob") and isinstance(tool_input, dict):
        input_summary["pattern"] = tool_input.get("pattern", "")
    else:
        raw = json.dumps(tool_input, default=str)
        input_summary["raw"] = raw[:500] + ("..." if len(raw) > 500 else "")

    response_summary: Dict[str, Any] = {}
    if tool_name == "Bash" and isinstance(tool_resp, dict):
        out = tool_resp.get("output", "")
        response_summary["exit_code"]    = tool_resp.get("exit_code", 0)
        response_summary["output_lines"] = len(out.splitlines()) if out else 0
    elif tool_name == "Agent" and isinstance(tool_resp, dict):
        usage = tool_resp.get("usage", {})
        response_summary["status"] = tool_resp.get("status", "completed")
        if usage:
            response_summary["usage"] = usage
    else:
        raw = json.dumps(tool_resp, default=str)
        response_summary["raw"] = raw[:200] + ("..." if len(raw) > 200 else "")

    data["tool_calls"].append({
        "index":     call_index,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "tool":      tool_name,
        "input":     input_summary,
        "response":  response_summary,
    })
    data["summary"]["total_tool_calls"] = len(data["tool_calls"])

    # P4: final dedup pass on lists (safety net for concurrent writes)
    data["summary"]["files_modified"] = list(dict.fromkeys(data["summary"]["files_modified"]))
    data["summary"]["commands_run"]   = list(dict.fromkeys(data["summary"]["commands_run"]))

    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main() -> None:
    # Escape hatch
    if os.environ.get("NO_CC_LOGS", "").strip() in ("1", "true", "yes"):
        sys.exit(0)

    # Read hook payload
    try:
        payload: Dict[str, Any] = json.load(sys.stdin)
    except Exception as e:
        print(f"cc-logger: failed to parse hook input: {e}", file=sys.stderr)
        sys.exit(0)

    session_id      = payload.get("session_id", "")
    transcript_path = payload.get("transcript_path", "")
    hook_event      = payload.get("hook_event_name", "PostToolUse")
    tool_name       = payload.get("tool_name", "")

    if not session_id or not transcript_path:
        sys.exit(0)

    try:
        project_root = resolve_project_root(transcript_path)
        config       = load_config(project_root)

        if not config.get("enabled", True):
            sys.exit(0)

        logs_root   = project_root / LOG_DIR_NAME
        session_dir = get_or_create_session_dir(logs_root, session_id)

        # P1: Stop event → write session summary and exit
        if hook_event == "Stop":
            write_markdown_summary(session_dir, payload)
            sys.exit(0)

        # PostToolUse → apply tool filters
        exclude = config.get("excludeTools", DEFAULT_EXCLUDE_TOOLS)
        include = config.get("includeTools", [])
        if include and tool_name not in include:
            sys.exit(0)
        if not include and tool_name in exclude:
            sys.exit(0)

        call_index = get_and_increment_call_index(session_dir)

        # Enforce minToolCallsToWrite — only write once the threshold is reached
        min_calls = config.get("minToolCallsToWrite", DEFAULT_MIN_TOOL_CALLS)
        if call_index < min_calls:
            sys.exit(0)

        write_markdown_entry(session_dir, payload, call_index, config)
        append_json_entry(session_dir, payload, call_index, config)

    except Exception as e:
        try:
            error_log = Path(transcript_path).parent.parent.parent / "logs" / ".cc-logger-errors.log"
            error_log.parent.mkdir(parents=True, exist_ok=True)
            with open(error_log, "a", encoding="utf-8") as f:
                f.write(f"{datetime.now(tz=timezone.utc).isoformat()} ERROR [{hook_event}]: {e}\n")
        except Exception:
            pass

    sys.exit(0)


if __name__ == "__main__":
    main()
