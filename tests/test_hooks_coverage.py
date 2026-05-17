"""Tests for luckyd_code.hooks — covers uncovered branches.

Target uncovered lines (from cov_out.txt):
  78       _get_hook_scripts: event not in HOOK_EVENTS guard
  106,109  run_hook: tool filter skips non-matching tools
  125-126  _get_hook_scripts: dict hook config with "script" key
  165-166  _execute_script: subprocess.TimeoutExpired
  174-175  _execute_script: FileNotFoundError
  198      _execute_script: generic Exception
  217-218  _run_python_script: TimeoutExpired
  224-225  _run_python_script: generic Exception
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from luckyd_code.hooks import HookRunner, HookResult, get_hook_runner, HOOK_EVENTS


# ────────────────────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────────────────────

def _runner_with_settings(hooks_cfg: dict) -> HookRunner:
    runner = HookRunner.__new__(HookRunner)
    runner.settings = {"hooks": hooks_cfg}
    return runner


# ────────────────────────────────────────────────────────────────────────────
# _get_hook_scripts — branch coverage
# ────────────────────────────────────────────────────────────────────────────

class TestGetHookScripts:
    def test_unknown_event_returns_empty_list(self):
        """Line 78: event not in HOOK_EVENTS → returns []."""
        runner = _runner_with_settings({"badEvent": "echo hi"})
        result = runner._get_hook_scripts("badEvent")
        assert result == []

    def test_known_event_with_string_script(self):
        runner = _runner_with_settings({"preChat": "echo hello"})
        result = runner._get_hook_scripts("preChat")
        assert len(result) == 1
        assert result[0]["script"] == "echo hello"

    def test_known_event_with_empty_string_returns_empty(self):
        runner = _runner_with_settings({"preChat": ""})
        result = runner._get_hook_scripts("preChat")
        assert result == []

    def test_known_event_with_dict_with_script_key(self):
        """Lines 125-126: dict hook config containing 'script' key."""
        cfg = {"script": "echo from dict", "tools": ["Read"]}
        runner = _runner_with_settings({"preToolUse": cfg})
        result = runner._get_hook_scripts("preToolUse")
        assert len(result) == 1
        assert result[0]["script"] == "echo from dict"
        assert result[0]["tools"] == ["Read"]

    def test_known_event_with_dict_without_script_key(self):
        """Dict hook without 'script' → treated as named hooks dict → returns values."""
        cfg = {"hook1": {"script": "echo one"}, "hook2": {"script": "echo two"}}
        runner = _runner_with_settings({"preChat": cfg})
        result = runner._get_hook_scripts("preChat")
        assert len(result) == 2

    def test_known_event_with_list_config(self):
        hooks_list = [
            {"script": "echo a", "tools": ["all"]},
            {"script": "echo b", "tools": ["Write"]},
        ]
        runner = _runner_with_settings({"postToolUse": hooks_list})
        result = runner._get_hook_scripts("postToolUse")
        assert result == hooks_list

    def test_unknown_type_returns_empty(self):
        runner = _runner_with_settings({"preChat": 42})  # integer — invalid
        result = runner._get_hook_scripts("preChat")
        assert result == []


# ────────────────────────────────────────────────────────────────────────────
# run_hook — tool filter
# ────────────────────────────────────────────────────────────────────────────

class TestRunHookToolFilter:
    def test_hook_skipped_when_tool_not_in_filter(self):
        """Lines 106, 109: tool_filter doesn't include the running tool → skip."""
        cfg = [{"script": "echo should_be_skipped", "tools": ["Write"]}]
        runner = _runner_with_settings({"preToolUse": cfg})
        with patch.object(runner, "_execute_script") as mock_exec:
            results = runner.run_hook("preToolUse", context={"tool_name": "Read"})
        mock_exec.assert_not_called()
        assert results == []

    def test_hook_runs_when_tool_matches_filter(self):
        cfg = [{"script": "echo matched", "tools": ["Read"]}]
        runner = _runner_with_settings({"preToolUse": cfg})
        fake_result = HookResult(success=True, output="matched")
        with patch.object(runner, "_execute_script", return_value=fake_result) as mock_exec:
            results = runner.run_hook("preToolUse", context={"tool_name": "Read"})
        mock_exec.assert_called_once()
        assert results == [fake_result]

    def test_hook_runs_when_all_in_filter(self):
        """'all' in tool_filter → always run regardless of tool_name."""
        cfg = [{"script": "echo always", "tools": ["all"]}]
        runner = _runner_with_settings({"preToolUse": cfg})
        fake_result = HookResult(success=True, output="always")
        with patch.object(runner, "_execute_script", return_value=fake_result):
            results = runner.run_hook("preToolUse", context={"tool_name": "Bash"})
        assert len(results) == 1

    def test_unknown_event_returns_error_result(self):
        runner = _runner_with_settings({})
        results = runner.run_hook("unknownEvent", context={})
        assert len(results) == 1
        assert results[0].success is False
        assert "Unknown hook event" in (results[0].error or "")

    def test_hook_with_empty_script_is_skipped(self):
        runner = _runner_with_settings({"preChat": [{"script": "", "tools": ["all"]}]})
        with patch.object(runner, "_execute_script") as mock_exec:
            results = runner.run_hook("preChat")
        mock_exec.assert_not_called()
        assert results == []


# ────────────────────────────────────────────────────────────────────────────
# _execute_script — timeout, FileNotFoundError, generic Exception
# ────────────────────────────────────────────────────────────────────────────

class TestExecuteScriptBranches:
    def test_timeout_returns_failure_result(self):
        """Lines 165-166: subprocess.TimeoutExpired → HookResult(success=False)."""
        runner = _runner_with_settings({})
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 30)):
            result = runner._execute_script("sleep 60", "preChat")
        assert result.success is False
        assert "timed out" in result.error.lower()

    def test_file_not_found_returns_failure_result(self):
        """Lines 174-175: FileNotFoundError → HookResult(success=False)."""
        runner = _runner_with_settings({})
        with patch("subprocess.run", side_effect=FileNotFoundError("no such file")):
            result = runner._execute_script("/nonexistent/hook.sh", "preChat")
        assert result.success is False
        assert "not found" in result.error.lower()

    def test_generic_exception_returns_failure_result(self):
        """Line 198 approx: generic Exception → HookResult(success=False)."""
        runner = _runner_with_settings({})
        with patch("subprocess.run", side_effect=PermissionError("access denied")):
            result = runner._execute_script("protected_script.sh", "preChat")
        assert result.success is False
        assert "error" in result.error.lower()

    def test_success_with_output_returns_success_result(self):
        runner = _runner_with_settings({})
        mock_proc = MagicMock()
        mock_proc.stdout = "hook output"
        mock_proc.stderr = ""
        mock_proc.returncode = 0
        with patch("subprocess.run", return_value=mock_proc):
            result = runner._execute_script("echo hook output", "postChat")
        assert result.success is True
        assert "hook output" in result.output

    def test_nonzero_returncode_with_stderr_is_failure(self):
        runner = _runner_with_settings({})
        mock_proc = MagicMock()
        mock_proc.stdout = ""
        mock_proc.stderr = "script failed"
        mock_proc.returncode = 1
        with patch("subprocess.run", return_value=mock_proc):
            result = runner._execute_script("bad_script.sh", "postChat")
        assert result.success is False


# ────────────────────────────────────────────────────────────────────────────
# _run_python_script — timeout, generic Exception
# ────────────────────────────────────────────────────────────────────────────

class TestRunPythonScriptBranches:
    def test_python_timeout_returns_failure(self):
        """Lines 217-218: TimeoutExpired in _run_python_script."""
        runner = _runner_with_settings({})
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("python", 30)):
            result = runner._run_python_script(Path("hook.py"), "preChat", {})
        assert result.success is False
        assert "timed out" in result.error.lower()

    def test_python_generic_exception_returns_failure(self):
        """Lines 224-225: generic Exception in _run_python_script."""
        runner = _runner_with_settings({})
        with patch("subprocess.run", side_effect=OSError("can't run")):
            result = runner._run_python_script(Path("hook.py"), "preChat", {})
        assert result.success is False
        assert "error" in result.error.lower()

    def test_python_script_successful_output(self):
        runner = _runner_with_settings({})
        mock_proc = MagicMock()
        mock_proc.stdout = "from python hook"
        mock_proc.stderr = ""
        mock_proc.returncode = 0
        with patch("subprocess.run", return_value=mock_proc):
            result = runner._run_python_script(Path("hook.py"), "postChat", {})
        assert result.success is True


# ────────────────────────────────────────────────────────────────────────────
# _parse_script_output — JSON first-line protocol
# ────────────────────────────────────────────────────────────────────────────

class TestParseScriptOutput:
    def test_json_allow_false_blocks(self):
        runner = _runner_with_settings({})
        result = runner._parse_script_output(
            '{"allow": false}\nextra output', 0, "", "preToolUse"
        )
        assert result.allow is False

    def test_json_env_updates(self):
        runner = _runner_with_settings({})
        result = runner._parse_script_output(
            '{"env": {"MY_VAR": "hello"}}\nrest', 0, "", "preChat"
        )
        assert result.env_updates == {"MY_VAR": "hello"}

    def test_malformed_json_is_treated_as_plain_output(self):
        runner = _runner_with_settings({})
        result = runner._parse_script_output(
            '{bad json}\nsome output', 0, "", "preChat"
        )
        # Falls back to plain text — allow stays True
        assert result.allow is True
        assert result.success is True

    def test_non_json_first_line_plain_output(self):
        runner = _runner_with_settings({})
        result = runner._parse_script_output("Hello world", 0, "", "postChat")
        assert result.success is True
        assert result.output == "Hello world"


# ────────────────────────────────────────────────────────────────────────────
# get_hook_runner singleton
# ────────────────────────────────────────────────────────────────────────────

class TestGetHookRunnerSingleton:
    def test_returns_hook_runner_instance(self):
        import luckyd_code.hooks as hooks_mod
        hooks_mod._hook_runner = None  # reset
        with patch("luckyd_code.hooks.load_settings", return_value={}):
            runner = get_hook_runner()
        assert isinstance(runner, HookRunner)

    def test_same_instance_returned_on_second_call(self):
        import luckyd_code.hooks as hooks_mod
        hooks_mod._hook_runner = None  # reset
        with patch("luckyd_code.hooks.load_settings", return_value={}):
            r1 = get_hook_runner()
            r2 = get_hook_runner()
        assert r1 is r2
