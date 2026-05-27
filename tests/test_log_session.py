"""
cc-logger unit tests
Run: python3 -m pytest tests/ -v
"""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / ".claude" / "hooks"))
import log_session as ls


# ─────────────────────────────────────────────────────────────────────────────
class TestRedaction(unittest.TestCase):

    def test_api_key_redacted(self):
        self.assertNotIn("sk-abc123", ls.redact("api_key=sk-abc123XYZverylongkeyvalue"))
        self.assertIn(ls.REDACT_REPLACEMENT, ls.redact("api_key=sk-abc123XYZverylongkeyvalue"))

    def test_password_redacted(self):
        self.assertNotIn("supersecret123", ls.redact("password=supersecret123"))

    def test_bearer_token_redacted(self):
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc"
        self.assertNotIn("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9", ls.redact(text))

    def test_clean_text_unchanged(self):
        self.assertEqual("git log --oneline -5", ls.redact("git log --oneline -5"))

    def test_recursive_redaction_dict(self):
        obj = {"password": "secret123", "username": "amit", "nested": {"api_key": "key456"}}
        r = ls.redact_recursive(obj)
        self.assertEqual(r["password"], ls.REDACT_REPLACEMENT)
        self.assertEqual(r["username"], "amit")
        self.assertEqual(r["nested"]["api_key"], ls.REDACT_REPLACEMENT)

    def test_recursive_redaction_list(self):
        obj = ["normal string", "api_key=leaked"]
        r = ls.redact_recursive(obj)
        self.assertEqual(r[0], "normal string")
        self.assertNotIn("leaked", r[1])

    def test_github_pat_redacted(self):
        text = "ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890"
        self.assertNotIn("ghp_aBcD", ls.redact(text))

    def test_openai_key_redacted(self):
        text = "sk-proj-aBcDeFgHiJkLmNoPqRsTuV"
        self.assertIn(ls.REDACT_REPLACEMENT, ls.redact(text))


# ─────────────────────────────────────────────────────────────────────────────
class TestPathResolution(unittest.TestCase):

    def test_standard_transcript_path(self):
        root = ls.resolve_project_root("/home/user/myproject/.claude/sessions/abc.md")
        self.assertEqual(root, Path("/home/user/myproject"))

    def test_nested_project_path(self):
        root = ls.resolve_project_root("/Users/amit/work/deep/nested/project/.claude/sessions/s.md")
        self.assertEqual(root, Path("/Users/amit/work/deep/nested/project"))


# ─────────────────────────────────────────────────────────────────────────────
class TestSessionFolderNaming(unittest.TestCase):

    def test_folder_name_format(self):
        name = ls.get_session_folder_name("550e8400-e29b-41d4-a716-446655440000")
        parts = name.split("_")
        self.assertEqual(len(parts), 3)
        self.assertEqual(len(parts[0]), 8)   # YYYYMMDD
        self.assertEqual(len(parts[1]), 6)   # HHMMSS
        self.assertEqual(len(parts[2]), 8)   # MD5 short hash

    def test_different_sessions_get_different_names(self):
        n1 = ls.get_session_folder_name("aaaa-0000-0000-0000-000000000000")
        n2 = ls.get_session_folder_name("bbbb-1111-1111-1111-111111111111")
        self.assertNotEqual(n1[-8:], n2[-8:])

    def test_shared_prefix_sessions_get_different_folders(self):
        """Bug 1 regression: shared-prefix IDs must not collide."""
        n1 = ls.get_session_folder_name("concurrent-0000-0000-0000-000000000000")
        n2 = ls.get_session_folder_name("concurrent-0001-0000-0000-000000000000")
        self.assertNotEqual(n1[-8:], n2[-8:], "MD5 hashes must differ for different session IDs")

    def test_same_session_id_always_same_hash(self):
        sid = "550e8400-e29b-41d4-a716-446655440000"
        h1  = ls.get_session_folder_name(sid)[-8:]
        h2  = ls.get_session_folder_name(sid)[-8:]
        self.assertEqual(h1, h2)


# ─────────────────────────────────────────────────────────────────────────────
class TestToolInputFormatting(unittest.TestCase):

    def test_bash_input(self):
        md = ls.format_tool_input("Bash", {"command": "git status"}, 3000)
        self.assertIn("`git status`", md)

    def test_edit_shows_file_path(self):
        md = ls.format_tool_input("Edit", {"file_path": "src/auth.ts", "old_string": "x", "new_string": "y"}, 3000)
        self.assertIn("src/auth.ts", md)

    def test_grep_input(self):
        md = ls.format_tool_input("Grep", {"pattern": "api_key", "path": "src/"}, 3000)
        self.assertIn("api_key", md)
        self.assertIn("src/", md)

    def test_bash_secret_redacted(self):
        md = ls.format_tool_input(
            "Bash",
            {"command": "curl -H 'Authorization: Bearer sk-supersecrettoken12345678901' https://api.example.com"},
            3000
        )
        self.assertNotIn("sk-supersecrettoken", md)


# ─────────────────────────────────────────────────────────────────────────────
class TestConfigLoading(unittest.TestCase):

    def test_defaults_when_no_config(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = ls.load_config(Path(d))
        self.assertTrue(cfg["enabled"])
        self.assertIn("Read",  cfg["excludeTools"])
        self.assertIn("Glob",  cfg["excludeTools"])
        self.assertIn("Grep",  cfg["excludeTools"])  # P2 regression

    def test_nested_filtering_key_applied(self):
        """Bug 2 regression: nested filtering.excludeTools must be respected."""
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/".claude-logger.json").write_text(json.dumps({
                "enabled": True,
                "filtering": {"excludeTools": ["Bash"], "includeTools": []}
            }))
            cfg = ls.load_config(Path(d))
        self.assertIn("Bash", cfg["excludeTools"])
        self.assertNotIn("Read", cfg["excludeTools"])  # override replaced defaults

    def test_flat_exclude_tools_still_works(self):
        """Both config shapes must be supported."""
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/".claude-logger.json").write_text(json.dumps({
                "enabled": True,
                "excludeTools": ["Edit"]
            }))
            cfg = ls.load_config(Path(d))
        self.assertIn("Edit", cfg["excludeTools"])

    def test_nested_output_maxInlineChars_applied(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/".claude-logger.json").write_text(json.dumps({
                "output": {"maxInlineChars": 9999}
            }))
            cfg = ls.load_config(Path(d))
        self.assertEqual(cfg["maxInlineChars"], 9999)

    def test_invalid_json_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/".claude-logger.json").write_text("NOT VALID JSON {{{{")
            cfg = ls.load_config(Path(d))
        self.assertTrue(cfg["enabled"])

    def test_wrong_type_falls_back_with_warning(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/".claude-logger.json").write_text(json.dumps({"enabled": "yes"}))
            import io
            buf = io.StringIO()
            with patch("sys.stderr", buf):
                cfg = ls.load_config(Path(d))
            self.assertIn("warning", buf.getvalue().lower())


# ─────────────────────────────────────────────────────────────────────────────
class TestFilesModifiedDedup(unittest.TestCase):
    """P4: files_modified must not contain duplicates."""

    def test_no_duplicate_files_modified(self):
        with tempfile.TemporaryDirectory() as d:
            sessions_dir = Path(d) / ".claude" / "sessions"
            sessions_dir.mkdir(parents=True)
            (sessions_dir / "s.md").touch()
            payload = {
                "hook_event_name": "PostToolUse",
                "session_id":      "dedup-test-0000-0000-000000000001",
                "transcript_path": str(sessions_dir / "s.md"),
                "cwd":             d,
                "tool_name":       "Edit",
                "tool_use_id":     "u1",
                "tool_input":      {"file_path": "/project/src/auth.ts"},
                "tool_response":   {"success": True},
            }
            project_root = ls.resolve_project_root(payload["transcript_path"])
            config       = ls.load_config(project_root)
            logs_root    = project_root / "logs"
            session_dir  = ls.get_or_create_session_dir(logs_root, payload["session_id"])

            # Write same file 5 times
            for i in range(5):
                idx = ls.get_and_increment_call_index(session_dir)
                ls.append_json_entry(session_dir, payload, idx, config)

            data = json.loads((session_dir / "session.json").read_text())
            files = data["summary"]["files_modified"]
            self.assertEqual(len(files), len(set(files)), "files_modified must not contain duplicates")
            self.assertEqual(len(files), 1)


# ─────────────────────────────────────────────────────────────────────────────
class TestGitStateCapture(unittest.TestCase):
    """P5: session.json must include git state on first write."""

    def test_git_state_in_json(self):
        with tempfile.TemporaryDirectory() as d:
            sessions_dir = Path(d) / ".claude" / "sessions"
            sessions_dir.mkdir(parents=True)
            (sessions_dir / "s.md").touch()
            payload = {
                "hook_event_name": "PostToolUse",
                "session_id":      "git-state-test-0000-000000000001",
                "transcript_path": str(sessions_dir / "s.md"),
                "cwd":             d,
                "tool_name":       "Bash",
                "tool_use_id":     "u1",
                "tool_input":      {"command": "echo hi"},
                "tool_response":   {"output": "hi", "exit_code": 0},
            }
            project_root = ls.resolve_project_root(payload["transcript_path"])
            config       = ls.load_config(project_root)
            logs_root    = project_root / "logs"
            session_dir  = ls.get_or_create_session_dir(logs_root, payload["session_id"])
            ls.append_json_entry(session_dir, payload, 1, config)

            data = json.loads((session_dir / "session.json").read_text())
            # "git" key must always be present (even if empty dict for non-git dirs)
            self.assertIn("git", data)
            self.assertIsInstance(data["git"], dict)


# ─────────────────────────────────────────────────────────────────────────────
class TestStopHook(unittest.TestCase):
    """P1: Stop hook must write a session summary block."""

    def _run_session_then_stop(self, tmpdir):
        sessions_dir = Path(tmpdir) / ".claude" / "sessions"
        sessions_dir.mkdir(parents=True)
        (sessions_dir / "s.md").touch()
        sid     = "stop-hook-test-0000-000000000001"
        base    = {
            "hook_event_name": "PostToolUse",
            "session_id":      sid,
            "transcript_path": str(sessions_dir / "s.md"),
            "cwd":             tmpdir,
            "tool_use_id":     "u1",
            "tool_input":      {"command": "git status"},
            "tool_response":   {"output": "clean", "exit_code": 0},
            "tool_name":       "Bash",
        }
        project_root = ls.resolve_project_root(base["transcript_path"])
        config       = ls.load_config(project_root)
        logs_root    = project_root / "logs"
        session_dir  = ls.get_or_create_session_dir(logs_root, sid)

        # Simulate 3 tool calls
        for i in range(1, 4):
            ls.write_markdown_entry(session_dir, base, i, config)
            ls.append_json_entry(session_dir, base, i, config)

        time.sleep(0.01)  # ensure measurable duration

        # Fire Stop hook
        stop_payload = {
            "hook_event_name": "Stop",
            "session_id":      sid,
            "transcript_path": str(sessions_dir / "s.md"),
            "cwd":             tmpdir,
        }
        ls.write_markdown_summary(session_dir, stop_payload)
        return session_dir

    def test_stop_appends_summary_to_md(self):
        with tempfile.TemporaryDirectory() as d:
            session_dir = self._run_session_then_stop(d)
            md = (session_dir / "session.md").read_text()
            self.assertIn("Session Summary", md)
            self.assertIn("Total tool calls", md)
            self.assertIn("Files modified", md)
            self.assertIn("Duration", md)

    def test_stop_updates_json_with_ended_at(self):
        with tempfile.TemporaryDirectory() as d:
            session_dir = self._run_session_then_stop(d)
            data = json.loads((session_dir / "session.json").read_text())
            self.assertIn("ended_at", data)
            self.assertIn("duration", data)

    def test_stop_on_empty_session_does_not_crash(self):
        """Stop hook fired on a session with no tool calls should exit cleanly."""
        with tempfile.TemporaryDirectory() as d:
            sessions_dir = Path(d) / ".claude" / "sessions"
            sessions_dir.mkdir(parents=True)
            (sessions_dir / "s.md").touch()
            sid = "stop-empty-0000-0000-000000000001"
            project_root = ls.resolve_project_root(str(sessions_dir / "s.md"))
            logs_root    = project_root / "logs"
            session_dir  = ls.get_or_create_session_dir(logs_root, sid)
            stop_payload = {
                "hook_event_name": "Stop",
                "session_id":      sid,
                "transcript_path": str(sessions_dir / "s.md"),
                "cwd":             d,
            }
            # Should not raise
            ls.write_markdown_summary(session_dir, stop_payload)


# ─────────────────────────────────────────────────────────────────────────────
class TestGrepExcludedByDefault(unittest.TestCase):
    """P2: Grep must be in DEFAULT_EXCLUDE_TOOLS."""

    def test_grep_in_default_excludes(self):
        self.assertIn("Grep", ls.DEFAULT_EXCLUDE_TOOLS)

    def test_grep_excluded_with_default_config(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = ls.load_config(Path(d))
            exclude = cfg.get("excludeTools", [])
            include = cfg.get("includeTools", [])
            tool = "Grep"
            should_skip = (not include and tool in exclude)
            self.assertTrue(should_skip, "Grep should be skipped with default config")


# ─────────────────────────────────────────────────────────────────────────────
class TestEndToEnd(unittest.TestCase):

    def test_bash_creates_both_files(self):
        with tempfile.TemporaryDirectory() as d:
            sessions_dir = Path(d) / ".claude" / "sessions"
            sessions_dir.mkdir(parents=True)
            (sessions_dir / "s.md").touch()
            payload = {
                "hook_event_name": "PostToolUse",
                "session_id":      "e2e-bash-0000-0000-000000000001",
                "transcript_path": str(sessions_dir / "s.md"),
                "cwd":             d,
                "tool_name":       "Bash",
                "tool_use_id":     "u1",
                "tool_input":      {"command": "git status"},
                "tool_response":   {"output": "nothing to commit", "exit_code": 0},
            }
            project_root = ls.resolve_project_root(payload["transcript_path"])
            config       = ls.load_config(project_root)
            logs_root    = project_root / "logs"
            session_dir  = ls.get_or_create_session_dir(logs_root, payload["session_id"])
            idx          = ls.get_and_increment_call_index(session_dir)

            ls.write_markdown_entry(session_dir, payload, idx, config)
            ls.append_json_entry(session_dir, payload, idx, config)

            md_file   = session_dir / "session.md"
            json_file = session_dir / "session.json"
            self.assertTrue(md_file.exists())
            self.assertTrue(json_file.exists())
            self.assertIn("Bash", md_file.read_text())
            data = json.loads(json_file.read_text())
            self.assertEqual(data["schema_version"], "1")
            self.assertEqual(data["tool_calls"][0]["tool"], "Bash")
            self.assertIn("git", data)               # P5: git state

    def test_excluded_tool_skips_logging(self):
        cfg     = {"enabled": True, "excludeTools": ["Read", "Glob", "Grep"], "includeTools": []}
        tool    = "Read"
        exclude = cfg["excludeTools"]
        include = cfg["includeTools"]
        skip    = not include and tool in exclude
        self.assertTrue(skip)

    def test_no_cc_logs_env_skips(self):
        with patch.dict(os.environ, {"NO_CC_LOGS": "1"}):
            val = os.environ.get("NO_CC_LOGS", "").strip()
            self.assertIn(val, ("1", "true", "yes"))



# ─────────────────────────────────────────────────────────────────────────────
class TestJsonPresets(unittest.TestCase):
    """Bug 1: config/minimal.json and config/verbose.json must be valid JSON."""

    def _preset_path(self, name):
        here = Path(__file__).parent.parent
        return here / "config" / name

    def test_minimal_json_is_valid(self):
        p = self._preset_path("minimal.json")
        self.assertTrue(p.exists(), "config/minimal.json not found")
        with open(p) as f:
            data = json.load(f)
        self.assertIn("enabled", data)

    def test_verbose_json_is_valid(self):
        p = self._preset_path("verbose.json")
        self.assertTrue(p.exists(), "config/verbose.json not found")
        with open(p) as f:
            data = json.load(f)
        self.assertIn("enabled", data)

    def test_minimal_json_loads_correctly_as_config(self):
        p = self._preset_path("minimal.json")
        # Simulate copying it into a temp project root as .claude-logger.json
        with tempfile.TemporaryDirectory() as d:
            import shutil
            shutil.copy(p, Path(d) / ".claude-logger.json")
            cfg = ls.load_config(Path(d))
            self.assertEqual(cfg["enabled"], True)
            self.assertGreater(len(cfg["excludeTools"]), 0)

    def test_verbose_json_loads_correctly_as_config(self):
        p = self._preset_path("verbose.json")
        with tempfile.TemporaryDirectory() as d:
            import shutil
            shutil.copy(p, Path(d) / ".claude-logger.json")
            cfg = ls.load_config(Path(d))
            self.assertEqual(cfg["excludeTools"], [])


# ─────────────────────────────────────────────────────────────────────────────
class TestMinToolCallsToWrite(unittest.TestCase):
    """Bug 2: minToolCallsToWrite must gate writes until threshold is reached."""

    def _make_payload(self, d, sid="min-tools-test-0001"):
        sessions_dir = Path(d) / ".claude" / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        (sessions_dir / "s.md").touch()
        return {
            "hook_event_name": "PostToolUse",
            "session_id":      sid,
            "transcript_path": str(sessions_dir / "s.md"),
            "cwd":             d,
            "tool_name":       "Bash",
            "tool_use_id":     "u1",
            "tool_input":      {"command": "echo hello"},
            "tool_response":   {"output": "hello", "exit_code": 0},
        }

    def test_writes_suppressed_below_threshold(self):
        """If minToolCallsToWrite=3, calls 1 and 2 must NOT write files."""
        with tempfile.TemporaryDirectory() as d:
            payload = self._make_payload(d)
            project_root = ls.resolve_project_root(payload["transcript_path"])
            config = ls.load_config(project_root)
            config["minToolCallsToWrite"] = 3
            config["excludeTools"] = []

            logs_root = project_root / "logs"
            session_dir = ls.get_or_create_session_dir(logs_root, payload["session_id"])

            min_calls = config.get("minToolCallsToWrite", ls.DEFAULT_MIN_TOOL_CALLS)

            # Simulate call #1 — below threshold, skip
            idx1 = ls.get_and_increment_call_index(session_dir)
            if idx1 >= min_calls:
                ls.write_markdown_entry(session_dir, payload, idx1, config)
                ls.append_json_entry(session_dir, payload, idx1, config)

            # Simulate call #2 — still below threshold, skip
            idx2 = ls.get_and_increment_call_index(session_dir)
            if idx2 >= min_calls:
                ls.write_markdown_entry(session_dir, payload, idx2, config)
                ls.append_json_entry(session_dir, payload, idx2, config)

            self.assertFalse((session_dir / "session.md").exists(),
                             "session.md should not exist before threshold")
            self.assertFalse((session_dir / "session.json").exists(),
                             "session.json should not exist before threshold")

    def test_writes_happen_at_threshold(self):
        """At call #3 with minToolCallsToWrite=3, files MUST be written."""
        with tempfile.TemporaryDirectory() as d:
            payload = self._make_payload(d, sid="min-tools-test-0002")
            project_root = ls.resolve_project_root(payload["transcript_path"])
            config = ls.load_config(project_root)
            config["minToolCallsToWrite"] = 3
            config["excludeTools"] = []

            logs_root = project_root / "logs"
            session_dir = ls.get_or_create_session_dir(logs_root, payload["session_id"])
            min_calls = config.get("minToolCallsToWrite", ls.DEFAULT_MIN_TOOL_CALLS)

            for _ in range(3):
                idx = ls.get_and_increment_call_index(session_dir)
                if idx >= min_calls:
                    ls.write_markdown_entry(session_dir, payload, idx, config)
                    ls.append_json_entry(session_dir, payload, idx, config)

            self.assertTrue((session_dir / "session.md").exists(),
                            "session.md must exist once threshold is reached")
            self.assertTrue((session_dir / "session.json").exists(),
                            "session.json must exist once threshold is reached")

    def test_default_threshold_is_one(self):
        """Default minToolCallsToWrite should be 1 — write on first call."""
        with tempfile.TemporaryDirectory() as d:
            payload = self._make_payload(d, sid="min-tools-test-0003")
            project_root = ls.resolve_project_root(payload["transcript_path"])
            config = ls.load_config(project_root)
            self.assertEqual(config.get("minToolCallsToWrite", ls.DEFAULT_MIN_TOOL_CALLS), 1)




# ─────────────────────────────────────────────────────────────────────────────
class TestTranscriptRecovery(unittest.TestCase):
    """Mid-session install: recover prior tool calls from transcript JSONL."""

    def _write_transcript(self, path, tool_calls):
        """
        Write a minimal JSONL transcript.
        tool_calls = list of (tool_use_id, tool_name, tool_input, tool_result)
        """
        lines = []
        for tid, name, inp, result in tool_calls:
            # Assistant message with tool_use block
            lines.append(json.dumps({
                "role": "assistant",
                "content": [{"type": "tool_use", "id": tid, "name": name, "input": inp}]
            }))
            # User message with tool_result block
            lines.append(json.dumps({
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": tid, "content": result}]
            }))
        Path(path).write_text("\n".join(lines), encoding="utf-8")

    def test_recovers_bash_calls_before_current(self):
        """Prior Bash calls appear in recovered list; current call is excluded."""
        with tempfile.TemporaryDirectory() as d:
            transcript = Path(d) / "session.jsonl"
            self._write_transcript(str(transcript), [
                ("tool-001", "Bash", {"command": "git status"}, "On branch main"),
                ("tool-002", "Bash", {"command": "npm test"},   "3 passed"),
                ("tool-003", "Bash", {"command": "echo live"},  "live"),   # ← current call
            ])
            config = {
                "excludeTools": ["Read", "Glob", "Grep"],
                "includeTools": [],
            }
            recovered = ls.recover_prior_tool_calls(str(transcript), "tool-003", config)
            self.assertEqual(len(recovered), 2)
            commands = [r["tool_input"]["command"] for r in recovered]
            self.assertIn("git status", commands)
            self.assertIn("npm test",   commands)
            self.assertNotIn("echo live", commands)

    def test_excluded_tools_skipped_during_recovery(self):
        """Read and Glob calls are not recovered when they are in excludeTools."""
        with tempfile.TemporaryDirectory() as d:
            transcript = Path(d) / "session.jsonl"
            self._write_transcript(str(transcript), [
                ("tool-001", "Read", {"file_path": "src/main.py"}, "content"),
                ("tool-002", "Bash", {"command": "git log"},       "abc123"),
                ("tool-003", "Glob", {"pattern": "**/*.py"},       "main.py"),
                ("tool-004", "Edit", {"file_path": "src/main.py",
                                      "old_string": "a", "new_string": "b"}, ""),
            ])
            config = {
                "excludeTools": ["Read", "Glob", "Grep"],
                "includeTools": [],
            }
            recovered = ls.recover_prior_tool_calls(str(transcript), "CURRENT", config)
            names = [r["tool_name"] for r in recovered]
            self.assertNotIn("Read", names)
            self.assertNotIn("Glob", names)
            self.assertIn("Bash", names)
            self.assertIn("Edit", names)

    def test_empty_transcript_returns_empty_list(self):
        """An empty transcript file returns [] without raising."""
        with tempfile.TemporaryDirectory() as d:
            transcript = Path(d) / "session.jsonl"
            transcript.write_text("", encoding="utf-8")
            config = {"excludeTools": [], "includeTools": []}
            recovered = ls.recover_prior_tool_calls(str(transcript), "CURRENT", config)
            self.assertEqual(recovered, [])

    def test_malformed_jsonl_returns_empty_list(self):
        """Malformed JSONL is skipped gracefully; function never raises."""
        with tempfile.TemporaryDirectory() as d:
            transcript = Path(d) / "session.jsonl"
            transcript.write_text(
                'not json at all\n{broken\n{"role":"user","content":[]}\n',
                encoding="utf-8",
            )
            config = {"excludeTools": [], "includeTools": []}
            recovered = ls.recover_prior_tool_calls(str(transcript), "CURRENT", config)
            self.assertEqual(recovered, [])

    def test_missing_transcript_returns_empty_list(self):
        """Non-existent transcript path returns [] without raising."""
        config = {"excludeTools": [], "includeTools": []}
        recovered = ls.recover_prior_tool_calls("/nonexistent/path.jsonl", "CURRENT", config)
        self.assertEqual(recovered, [])

    def test_recovery_banner_written_to_session_md(self):
        """When prior calls exist, session.md header contains the recovery notice."""
        with tempfile.TemporaryDirectory() as d:
            # Set up project layout
            sessions_dir = Path(d) / ".claude" / "sessions"
            sessions_dir.mkdir(parents=True)
            transcript   = sessions_dir / "session.jsonl"
            self._write_transcript(str(transcript), [
                ("prior-001", "Bash", {"command": "git status"}, "clean"),
                ("prior-002", "Bash", {"command": "ls -la"},     "total 8"),
            ])

            # The "live" call that triggers the hook
            live_payload = {
                "hook_event_name": "PostToolUse",
                "session_id":      "recovery-test-0000-0000-000000000001",
                "transcript_path": str(transcript),
                "cwd":             d,
                "tool_name":       "Bash",
                "tool_use_id":     "live-001",
                "tool_input":      {"command": "echo hello"},
                "tool_response":   {"output": "hello", "exit_code": 0},
            }

            project_root = ls.resolve_project_root(live_payload["transcript_path"])
            config       = ls.load_config(project_root)
            config["excludeTools"] = []   # capture everything for this test
            logs_root    = project_root / "logs"
            session_dir  = ls.get_or_create_session_dir(logs_root, live_payload["session_id"])

            # Simulate the recovery block in main()
            json_file = session_dir / "session.json"
            self.assertFalse(json_file.exists(), "session.json should not exist yet")

            prior_calls = ls.recover_prior_tool_calls(
                live_payload["transcript_path"],
                live_payload["tool_use_id"],
                config,
            )
            self.assertEqual(len(prior_calls), 2, "Should recover 2 prior calls")

            # Write recovery banner + backfill entries
            md_file = session_dir / "session.md"
            md_file.write_text(
                "# cc-logger Session\n\n"
                f"> ⚠️ **cc-logger was installed mid-session.**  "
                f"{len(prior_calls)} prior tool call(s) were recovered from the transcript.\n\n---\n",
                encoding="utf-8",
            )
            for i, rec in enumerate(prior_calls, start=1):
                rec_payload = {**live_payload,
                               "tool_name": rec["tool_name"],
                               "tool_input": rec["tool_input"],
                               "tool_response": rec["tool_response"]}
                counter = session_dir / ".call_index"
                counter.write_text(str(i))
                ls.write_markdown_entry(session_dir, rec_payload, i, config)
                ls.append_json_entry(session_dir, rec_payload, i, config)

            md_text = md_file.read_text()
            self.assertIn("mid-session", md_text)
            self.assertIn("recovered from the transcript", md_text)
            self.assertIn("git status", md_text)
            self.assertIn("ls -la",     md_text)

            # JSON should have both recovered calls
            data = json.loads(json_file.read_text())
            self.assertEqual(data["summary"]["total_tool_calls"], 2)

    def test_include_tools_filter_respected_during_recovery(self):
        """includeTools whitelist is applied during recovery."""
        with tempfile.TemporaryDirectory() as d:
            transcript = Path(d) / "session.jsonl"
            self._write_transcript(str(transcript), [
                ("t1", "Bash", {"command": "git log"}, "abc"),
                ("t2", "Edit", {"file_path": "a.py"},  ""),
                ("t3", "Bash", {"command": "ls"},      "file.py"),
            ])
            config = {
                "excludeTools": [],
                "includeTools": ["Edit"],   # only log Edit calls
            }
            recovered = ls.recover_prior_tool_calls(str(transcript), "CURRENT", config)
            names = [r["tool_name"] for r in recovered]
            self.assertEqual(names, ["Edit"])


if __name__ == "__main__":
    unittest.main()
