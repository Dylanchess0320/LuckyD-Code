"""Tests for the lifecycle hooks system (hooks.py)."""

from unittest.mock import patch


from luckyd_code.hooks import (
    HOOK_EVENTS,
    HookResult,
    HookRunner,
    get_hook_runner,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_runner(hooks: dict) -> HookRunner:
    """Create a HookRunner with an injected settings dict."""
    runner = HookRunner.__new__(HookRunner)
    runner.settings = {"hooks": hooks}
    return runner


# ---------------------------------------------------------------------------
# HookResult
# ---------------------------------------------------------------------------

class TestHookResult:
    def test_defaults(self):
        r = HookResult()
        assert r.success is True
        assert r.allow is True
        assert r.output == ""
        assert r.error is None
        assert r.env_updates == {}

    def test_custom_values(self):
        r = HookResult(success=False, output="out", error="err", allow=False,
                       env_updates={"K": "v"})
        assert r.success is False
        assert r.allow is False
        assert r.env_updates == {"K": "v"}


# ---------------------------------------------------------------------------
# HOOK_EVENTS list
# ---------------------------------------------------------------------------

class TestHookEvents:
    def test_required_events_present(self):
        required = {
            "preToolUse", "postToolUse", "preChat",
            "postChat", "onSessionStart", "onSessionEnd",
        }
        assert required.issubset(set(HOOK_EVENTS))


# ---------------------------------------------------------------------------
# HookRunner._get_hook_scripts
# ---------------------------------------------------------------------------

class TestGetHookScripts:
    def test_string_hook(self):
        runner = _make_runner({"preChat": "echo hello"})
        scripts = runner._get_hook_scripts("preChat")
        assert scripts == [{"script": "echo hello", "tools": ["all"]}]

    def test_empty_string_returns_empty(self):
        runner = _make_runner({"preChat": ""})
        assert runner._get_hook_scripts("preChat") == []

    def test_dict_with_script_key(self):
        cfg = {"script": "echo hi", "tools": ["Read"]}
        runner = _make_runner({"preToolUse": cfg})
        scripts = runner._get_hook_scripts("preToolUse")
        assert scripts == [cfg]

    def test_list_of_dicts(self):
        hooks = [
            {"script": "echo a", "tools": ["all"]},
            {"script": "echo b", "tools": ["Write"]},
        ]
        runner = _make_runner({"postToolUse": hooks})
        assert runner._get_hook_scripts("postToolUse") == hooks

    def test_missing_event_returns_empty(self):
        runner = _make_runner({})
        assert runner._get_hook_scripts("preChat") == []

    def test_unknown_event_still_returns_empty(self):
        runner = _make_runner({"bogusEvent": "echo hi"})
        assert runner._get_hook_scripts("bogusEvent") == []


# ---------------------------------------------------------------------------
# HookRunner.run_hook — unknown event
# ---------------------------------------------------------------------------

class TestRunHookUnknownEvent:
    def test_unknown_event_returns_error(self):
        runner = _make_runner({})
        results = runner.run_hook("notAnEvent")
        assert len(results) == 1
        assert results[0].success is False
        assert "Unknown hook event" in (results[0].error or "")

    def test_no_hooks_configured_returns_empty_list(self):
        runner = _make_runner({})
        results = runner.run_hook("preChat")
        assert results == []


# ---------------------------------------------------------------------------
# HookRunner.run_hook — tool filter
# ---------------------------------------------------------------------------

class TestToolFilter:
    def test_tool_filter_skips_non_matching(self):
        hooks = [{"script": "echo hi", "tools": ["Write"]}]
        runner = _make_runner({"preToolUse": hooks})
        results = runner.run_hook("preToolUse", context={"tool_name": "Read"})
        assert results == []

    def test_all_filter_always_runs(self):
        hooks = [{"script": "echo hi", "tools": ["all"]}]
        runner = _make_runner({"preToolUse": hooks})
        with patch.object(runner, "_execute_script",
                          return_value=HookResult(success=True, output="hi")):
            results = runner.run_hook("preToolUse", context={"tool_name": "Read"})
        assert len(results) == 1

    def test_matching_tool_runs(self):
        hooks = [{"script": "echo hi", "tools": ["Read"]}]
        runner = _make_runner({"preToolUse": hooks})
        with patch.object(runner, "_execute_script",
                          return_value=HookResult(success=True, output="hi")):
            results = runner.run_hook("preToolUse", context={"tool_name": "Read"})
        assert len(results) == 1


# ---------------------------------------------------------------------------
# HookRunner._execute_script — shell hooks
# ---------------------------------------------------------------------------

class TestExecuteScript:
    def test_successful_echo(self):
        runner = _make_runner({})
        result = runner._execute_script("echo hello", "preChat")
        assert result.success is True
        assert "hello" in result.output

    def test_nonzero_exit_captures_stderr(self):
        runner = _make_runner({})
        result = runner._execute_script(
            "python -c \"import sys; sys.stderr.write('err'); sys.exit(1)\"",
            "preChat",
        )
        assert result.success is False
        assert result.error is not None

    def test_json_allow_false_blocks(self):
        runner = _make_runner({})
        script = 'python -c "import json; print(json.dumps({\'allow\': False}))"'
        result = runner._execute_script(script, "preToolUse")
        assert result.allow is False

    def test_json_env_updates(self):
        runner = _make_runner({})
        script = 'python -c "import json; print(json.dumps({\'env\': {\'MY_VAR\': \'42\'}}))"'
        result = runner._execute_script(script, "preChat")
        assert result.env_updates == {"MY_VAR": "42"}

    def test_timeout_returns_error(self):
        import subprocess
        runner = _make_runner({})
        with patch("subprocess.run",
                   side_effect=subprocess.TimeoutExpired("sleep", 30)):
            result = runner._execute_script("sleep 9999", "preChat")
        assert result.success is False
        assert "timed out" in (result.error or "").lower()

    def test_command_not_found(self):
        runner = _make_runner({})
        with patch("subprocess.run",
                   side_effect=FileNotFoundError("not found")):
            result = runner._execute_script(
                "nonexistent_command_xyz", "preChat"
            )
        assert result.success is False
        assert result.error is not None


# ---------------------------------------------------------------------------
# HookRunner._run_python_script
# ---------------------------------------------------------------------------

class TestRunPythonScript:
    def test_simple_python_hook(self, tmp_path):
        script = tmp_path / "hook.py"
        script.write_text('print("python hook ran")', encoding="utf-8")
        runner = _make_runner({})
        result = runner._run_python_script(script, "preChat", {})
        assert result.success is True
        assert "python hook ran" in result.output

    def test_python_hook_json_allow(self, tmp_path):
        script = tmp_path / "block.py"
        script.write_text(
            'import json; print(json.dumps({"allow": False}))',
            encoding="utf-8",
        )
        runner = _make_runner({})
        result = runner._run_python_script(script, "preToolUse", {})
        assert result.allow is False

    def test_python_hook_timeout(self, tmp_path):
        import subprocess
        script = tmp_path / "slow.py"
        script.write_text("import time; time.sleep(999)", encoding="utf-8")
        runner = _make_runner({})
        with patch("subprocess.run",
                   side_effect=subprocess.TimeoutExpired("python", 30)):
            result = runner._run_python_script(script, "preChat", {})
        assert result.success is False
        assert "timed out" in (result.error or "").lower()


# ---------------------------------------------------------------------------
# Python-script dispatch via run_hook
# ---------------------------------------------------------------------------

class TestPythonScriptDispatch:
    def test_py_extension_routes_to_python_runner(self, tmp_path):
        script = tmp_path / "hook.py"
        script.write_text('print("dispatched")', encoding="utf-8")

        runner = _make_runner({"preChat": str(script)})
        results = runner.run_hook("preChat")
        assert len(results) == 1
        assert results[0].success is True
        assert "dispatched" in results[0].output


# ---------------------------------------------------------------------------
# get_hook_runner singleton
# ---------------------------------------------------------------------------

class TestGetHookRunnerSingleton:
    def test_returns_hook_runner(self):
        with patch("luckyd_code.hooks.load_settings", return_value={}):
            import luckyd_code.hooks as hooks_mod
            hooks_mod._hook_runner = None   # reset singleton
            runner = get_hook_runner()
            assert isinstance(runner, HookRunner)

    def test_singleton_caching(self):
        with patch("luckyd_code.hooks.load_settings", return_value={}):
            import luckyd_code.hooks as hooks_mod
            hooks_mod._hook_runner = None
            r1 = get_hook_runner()
            r2 = get_hook_runner()
            assert r1 is r2
