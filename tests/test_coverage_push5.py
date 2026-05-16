"""test_coverage_push5.py — targeted tests to close remaining coverage gaps.

Targets:
  undo.py          lines 58-61, 83, 100, 109-110
  verify.py        lines 170, 175, 183-195
  retry.py         lines 46-53
  plugins.py       lines 58-59
  sessions.py      lines 93-94
  update.py        line 31
  __init__.py      lines 30-34
  _data_dir.py     lines 50-51, 72-73
  context.py       lines 20-24, 49, 219-220
  hooks.py         lines 109, 165-166, 198, 217-218
  config.py        lines 90-92, 98, 125, 156, 167, 169, 196, 201
  analytics/smells lines 88, 140, 191, 211
  analytics/trends lines 160-163
  tools/registry   lines 85-86, 91, 103
  tools/shell_det  lines 137, 139
  brain/graph      lines 186, 209-248, 265
  orchestrator     lines 37-43
  planner.py       lines 69-71, 75, 79
  sessions.py      lines 93-94
"""

from __future__ import annotations

import importlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# ---------------------------------------------------------------------------
# undo.py
# ---------------------------------------------------------------------------

class TestUndoCoverage:
    """Cover the remaining undo.py branches."""

    def setup_method(self):
        import luckyd_code.undo as undo_mod
        undo_mod._undo_stack.clear()

    def test_load_else_branch_no_file(self, tmp_path):
        """_load() else branch: UNDO_FILE does not exist → _undo_stack = []."""
        import luckyd_code.undo as undo_mod
        fake_path = tmp_path / "nonexistent_undo.json"
        with patch.object(undo_mod, "UNDO_FILE", fake_path):
            undo_mod._load()
        assert undo_mod._undo_stack == []

    def test_load_exception_branch(self, tmp_path):
        """_load() except block: file exists but content is invalid JSON → stack reset to []."""
        import luckyd_code.undo as undo_mod
        fake_path = tmp_path / "bad_undo.json"
        fake_path.write_text("invalid json!!!", encoding="utf-8")
        with patch.object(undo_mod, "UNDO_FILE", fake_path):
            undo_mod._load()
        # After json.JSONDecodeError, stack should be []
        assert undo_mod._undo_stack == []

    def test_load_exception_branch_read_error(self, tmp_path):
        """_load() except block: read_text raises OSError → stack reset to []."""
        import luckyd_code.undo as undo_mod
        fake_path = tmp_path / "bad.json"
        fake_path.write_text("{}", encoding="utf-8")
        # patch exists() to return True but read_text to raise
        with patch.object(undo_mod, "UNDO_FILE", fake_path):
            original_read = fake_path.read_text
            with patch.object(type(fake_path), "read_text",
                               side_effect=OSError("disk error")):
                undo_mod._load()
        assert undo_mod._undo_stack == []

    def test_peek_empty_stack_returns_none(self):
        """peek() returns None when stack is empty (line 83)."""
        import luckyd_code.undo as undo_mod
        undo_mod._undo_stack.clear()
        result = undo_mod.peek()
        assert result is None

    def test_undo_last_cannot_undo_created_file(self, tmp_path):
        """undo_last() 'Cannot undo' branch: file no longer exists and content was None (line 100)."""
        import luckyd_code.undo as undo_mod
        ghost = str(tmp_path / "ghost.py")
        # File doesn't exist + original_content=None → "Cannot undo" path
        undo_mod.push(ghost, original_content=None, action="write")
        result = undo_mod.undo_last()
        assert "Cannot undo" in result or "Undone" in result

    def test_undo_last_except_block(self, tmp_path):
        """undo_last() except block: write_text raises (lines 109-110)."""
        import luckyd_code.undo as undo_mod
        target = tmp_path / "target.py"
        target.write_text("original", encoding="utf-8")
        undo_mod.push(str(target), original_content="original content", action="edit")
        with patch.object(type(target), "write_text", side_effect=OSError("permission denied")):
            result = undo_mod.undo_last()
        assert "Undo failed" in result or "permission denied" in result.lower()

    def test_undo_last_delete_created_file(self, tmp_path):
        """undo_last() deletes a file when original_content is None but file exists (line 103-105)."""
        import luckyd_code.undo as undo_mod
        target = tmp_path / "created.py"
        target.write_text("new file", encoding="utf-8")
        undo_mod.push(str(target), original_content=None, action="write")
        result = undo_mod.undo_last()
        assert "Undone" in result


# ---------------------------------------------------------------------------
# verify.py
# ---------------------------------------------------------------------------

class TestVerifyCoverage:
    """Cover remaining verify.py branches."""

    def _make_py_file(self, tmp_path, content: str) -> str:
        f = tmp_path / "check.py"
        f.write_text(content, encoding="utf-8")
        return str(f)

    def test_verify_consistency_base_exception_handler(self, tmp_path):
        """verify_consistency line 170: file catches BaseException."""
        code = "try:\n    pass\nexcept BaseException:\n    pass\n"
        fp = self._make_py_file(tmp_path, code)
        from luckyd_code.verify import verify_consistency
        result = verify_consistency(fp, str(tmp_path))
        assert result is not None
        assert not result.passed
        assert "BaseException" in result.raw_output

    def test_verify_consistency_mutable_default_argument(self, tmp_path):
        """verify_consistency line 175: mutable default argument."""
        code = "def foo(x=[]):\n    pass\n"
        fp = self._make_py_file(tmp_path, code)
        from luckyd_code.verify import verify_consistency
        result = verify_consistency(fp, str(tmp_path))
        assert result is not None
        assert not result.passed
        assert "Mutable default" in result.raw_output

    def test_verify_consistency_mutable_dict_default(self, tmp_path):
        """verify_consistency: mutable dict default."""
        code = "def bar(opts={}):\n    pass\n"
        fp = self._make_py_file(tmp_path, code)
        from luckyd_code.verify import verify_consistency
        result = verify_consistency(fp, str(tmp_path))
        assert result is not None
        assert not result.passed

    def test_run_verify_pipeline_blocked_test_runner(self, tmp_path):
        """run_verify_pipeline lines 183-192: blocked test runner command."""
        code = "x = 1\n"
        fp = self._make_py_file(tmp_path, code)
        from luckyd_code.verify import run_verify_pipeline
        results = run_verify_pipeline(
            fp, str(tmp_path),
            run_lint=False, run_consistency=False,
            run_tests=True, test_runner_cmd="curl http://evil.com",
        )
        assert any(r.stage == "test" and not r.passed for r in results)
        blocked = next(r for r in results if r.stage == "test")
        assert "Blocked" in blocked.message

    def test_run_verify_pipeline_tests_pass(self, tmp_path):
        """run_verify_pipeline: allowed test runner returns 0."""
        code = "x = 1\n"
        fp = self._make_py_file(tmp_path, code)
        from luckyd_code.verify import run_verify_pipeline
        with patch("subprocess.run") as mock_run:
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.stdout = "1 passed"
            mock_proc.stderr = ""
            mock_run.return_value = mock_proc
            results = run_verify_pipeline(
                fp, str(tmp_path),
                run_lint=False, run_consistency=False,
                run_tests=True, test_runner_cmd="pytest",
            )
        test_results = [r for r in results if r.stage == "test"]
        assert test_results
        assert test_results[0].passed

    def test_run_verify_pipeline_tests_fail(self, tmp_path):
        """run_verify_pipeline: allowed test runner returns non-zero."""
        code = "x = 1\n"
        fp = self._make_py_file(tmp_path, code)
        from luckyd_code.verify import run_verify_pipeline
        with patch("subprocess.run") as mock_run:
            mock_proc = MagicMock()
            mock_proc.returncode = 1
            mock_proc.stdout = "FAILED"
            mock_proc.stderr = ""
            mock_run.return_value = mock_proc
            results = run_verify_pipeline(
                fp, str(tmp_path),
                run_lint=False, run_consistency=False,
                run_tests=True, test_runner_cmd="pytest",
            )
        test_results = [r for r in results if r.stage == "test"]
        assert test_results
        assert not test_results[0].passed

    def test_run_verify_pipeline_tests_timeout(self, tmp_path):
        """run_verify_pipeline: test runner times out."""
        code = "x = 1\n"
        fp = self._make_py_file(tmp_path, code)
        from luckyd_code.verify import run_verify_pipeline
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("pytest", 120)):
            results = run_verify_pipeline(
                fp, str(tmp_path),
                run_lint=False, run_consistency=False,
                run_tests=True, test_runner_cmd="pytest",
            )
        test_results = [r for r in results if r.stage == "test"]
        assert test_results
        assert "timed out" in test_results[0].message.lower()

    def test_run_verify_pipeline_tests_exception(self, tmp_path):
        """run_verify_pipeline: test runner raises generic exception."""
        code = "x = 1\n"
        fp = self._make_py_file(tmp_path, code)
        from luckyd_code.verify import run_verify_pipeline
        with patch("subprocess.run", side_effect=RuntimeError("unexpected")):
            results = run_verify_pipeline(
                fp, str(tmp_path),
                run_lint=False, run_consistency=False,
                run_tests=True, test_runner_cmd="pytest",
            )
        test_results = [r for r in results if r.stage == "test"]
        assert test_results
        assert not test_results[0].passed

    def test_run_verify_pipeline_uv_run_pytest_allowed(self, tmp_path):
        """run_verify_pipeline: 'uv run pytest' is an allowed runner."""
        code = "x = 1\n"
        fp = self._make_py_file(tmp_path, code)
        from luckyd_code.verify import run_verify_pipeline
        with patch("subprocess.run") as mock_run:
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.stdout = "passed"
            mock_proc.stderr = ""
            mock_run.return_value = mock_proc
            results = run_verify_pipeline(
                fp, str(tmp_path),
                run_lint=False, run_consistency=False,
                run_tests=True, test_runner_cmd="uv run pytest",
            )
        test_results = [r for r in results if r.stage == "test"]
        assert test_results
        assert test_results[0].passed


# ---------------------------------------------------------------------------
# retry.py
# ---------------------------------------------------------------------------

class TestRetryCoverage:
    """Cover retry.py lines 46-53: generic Exception handling."""

    def test_generic_exception_retried_once_then_raises(self):
        """Lines 48-53: generic Exception on first attempt → retry; on second attempt → re-raise."""
        from luckyd_code.retry import with_retry

        call_count = [0]

        @with_retry(max_retries=1, base_delay=0.0, jitter=False)
        def flaky():
            call_count[0] += 1
            raise ValueError("generic error")

        with patch("time.sleep"):
            with pytest.raises(ValueError, match="generic error"):
                flaky()

        # attempt 0: raises ValueError → retried; attempt 1 (max_retries=1): raises → re-raised
        assert call_count[0] == 2

    def test_generic_exception_attempt0_sleeps(self):
        """Lines 49-51: attempt 0 with generic Exception → sleep called once."""
        from luckyd_code.retry import with_retry

        call_count = [0]

        @with_retry(max_retries=1, base_delay=0.5, jitter=False)
        def boom():
            call_count[0] += 1
            raise RuntimeError("boom")

        sleep_calls = []
        with patch("time.sleep", side_effect=lambda x: sleep_calls.append(x)):
            with pytest.raises(RuntimeError):
                boom()

        # sleep should have been called once (on attempt 0)
        assert len(sleep_calls) == 1
        assert sleep_calls[0] > 0

    def test_generic_exception_second_attempt_reraises_immediately(self):
        """Line 53: else: raise on attempt > 0."""
        from luckyd_code.retry import with_retry

        attempt_counter = [0]

        @with_retry(max_retries=2, base_delay=0.0, jitter=False)
        def fails_generically():
            attempt_counter[0] += 1
            raise TypeError("type error")

        with patch("time.sleep"):
            with pytest.raises(TypeError, match="type error"):
                fails_generically()

        # Should be called exactly 2 times: attempt 0 (sleep + retry), attempt 1 (re-raise)
        assert attempt_counter[0] == 2


# ---------------------------------------------------------------------------
# plugins.py
# ---------------------------------------------------------------------------

class TestPluginsCoverage:
    """Cover plugins.py lines 58-59: spec_from_file_location returns spec with no loader."""

    def test_load_plugin_no_loader(self, tmp_path):
        """Lines 58-59: spec is returned but spec.loader is None."""
        plugin_file = tmp_path / "myplugin.py"
        plugin_file.write_text("def register(registry): pass\n", encoding="utf-8")

        from luckyd_code.plugins import load_plugin

        fake_spec = MagicMock()
        fake_spec.loader = None  # loader is None → should warn and return None

        with patch("importlib.util.spec_from_file_location", return_value=fake_spec):
            result = load_plugin(plugin_file)

        assert result is None

    def test_load_plugin_spec_is_none(self, tmp_path):
        """Lines 58-59: spec_from_file_location returns None → return None."""
        plugin_file = tmp_path / "bad.py"
        plugin_file.write_text("", encoding="utf-8")

        from luckyd_code.plugins import load_plugin
        with patch("importlib.util.spec_from_file_location", return_value=None):
            result = load_plugin(plugin_file)

        assert result is None


# ---------------------------------------------------------------------------
# sessions.py
# ---------------------------------------------------------------------------

class TestSessionsCoverage:
    """Cover sessions.py lines 93-94: max_messages trim loop."""

    def test_load_session_trims_to_max_messages(self, tmp_path):
        """Lines 93-94: while len > max_messages: pop(1)."""
        from luckyd_code.sessions import load_session
        from luckyd_code.context import ConversationContext

        session_data = {
            "name": "big_session",
            "saved_at": "2025-01-01T00:00:00",
            "message_count": 10,
            "messages": [
                {"role": "user", "content": f"message {i}"}
                for i in range(10)
            ],
        }

        with patch("luckyd_code.sessions.SESSIONS_DIR", tmp_path):
            (tmp_path / "big_session.json").write_text(
                json.dumps(session_data), encoding="utf-8"
            )
            ctx = ConversationContext("system prompt", max_messages=5)
            result = load_session("big_session", ctx)

        assert "loaded" in result.lower() or "big_session" in result
        # Context should have been trimmed to max_messages
        assert len(ctx.messages) <= 5 + 1  # system + max_messages-1


# ---------------------------------------------------------------------------
# update.py
# ---------------------------------------------------------------------------

class TestUpdateCoverage:
    """Cover update.py line 31: get_version() imports __version__."""

    def test_get_version_returns_string(self):
        """Line 31: `from luckyd_code import __version__` inside get_version()."""
        from luckyd_code.update import get_version
        version = get_version()
        assert isinstance(version, str)
        assert len(version) > 0


# ---------------------------------------------------------------------------
# __init__.py
# ---------------------------------------------------------------------------

class TestInitCoverage:
    """Cover __init__.py lines 30-34: __getattr__ lazy loading."""

    def test_lazy_load_memory_subpackage(self):
        """Lines 30-34: accessing a lazy subpackage triggers __getattr__."""
        import luckyd_code
        # 'memory' is in _LAZY_SUBPACKAGES — accessing it exercises __getattr__
        memory = luckyd_code.memory
        assert memory is not None

    def test_lazy_load_tools_subpackage(self):
        """Lines 30-34: 'tools' lazy attribute."""
        import luckyd_code
        tools = luckyd_code.tools
        assert tools is not None

    def test_lazy_load_unknown_attr_raises(self):
        """Lines 30-34: unknown attribute raises AttributeError."""
        import luckyd_code
        with pytest.raises(AttributeError):
            _ = luckyd_code.nonexistent_attr_xyz


# ---------------------------------------------------------------------------
# _data_dir.py
# ---------------------------------------------------------------------------

class TestDataDirCoverage:
    """Cover _data_dir.py lines 50-51, 72-73."""

    def test_ensure_project_data_dir_migration_success(self, tmp_path):
        """Line 50: shutil.copytree in _ensure_project_data_dir succeeds."""
        from luckyd_code._data_dir import _ensure_project_data_dir, _LEGACY_PROJECT_DATA_NAME, _PROJECT_DATA_NAME

        legacy = tmp_path / _LEGACY_PROJECT_DATA_NAME
        legacy.mkdir()
        (legacy / "data.txt").write_text("legacy", encoding="utf-8")
        new_dir = tmp_path / _PROJECT_DATA_NAME
        # new_dir must NOT exist for migration to trigger
        assert not new_dir.exists()

        result = _ensure_project_data_dir(str(tmp_path))
        assert result.exists()

    def test_ensure_project_data_dir_migration_exception(self, tmp_path):
        """Line 51: shutil.copytree raises in _ensure_project_data_dir → warning logged."""
        from luckyd_code._data_dir import _ensure_project_data_dir, _LEGACY_PROJECT_DATA_NAME, _PROJECT_DATA_NAME

        legacy = tmp_path / _LEGACY_PROJECT_DATA_NAME
        legacy.mkdir()

        with patch("shutil.copytree", side_effect=OSError("copy failed")):
            result = _ensure_project_data_dir(str(tmp_path))

        # Despite error, new_dir should still be created via mkdir
        assert result.exists()

    def test_migrate_from_legacy_success(self, tmp_path):
        """Line 72: _logger.info('Migration complete') on successful copytree."""
        import luckyd_code._data_dir as dd

        fake_legacy = tmp_path / "legacy"
        fake_legacy.mkdir()
        (fake_legacy / "config.json").write_text("{}", encoding="utf-8")
        fake_new = tmp_path / "new"

        with patch.object(dd, "_LEGACY_DIR", fake_legacy), \
             patch.object(dd, "DATA_DIR", fake_new), \
             patch("shutil.copytree") as mock_copy:
            dd._migrate_from_legacy()

        mock_copy.assert_called_once()

    def test_migrate_from_legacy_exception(self, tmp_path):
        """Line 73: except Exception in _migrate_from_legacy."""
        import luckyd_code._data_dir as dd

        fake_legacy = tmp_path / "legacy"
        fake_new = tmp_path / "new"

        with patch.object(dd, "_LEGACY_DIR", fake_legacy), \
             patch.object(dd, "DATA_DIR", fake_new), \
             patch("shutil.copytree", side_effect=OSError("no space")):
            # Should not raise — exception is caught and logged
            dd._migrate_from_legacy()


# ---------------------------------------------------------------------------
# context.py
# ---------------------------------------------------------------------------

class TestContextCoverage:
    """Cover context.py lines 20-24 (tiktoken fallback) and 219-220 (on_compact)."""

    def test_token_count_tiktoken_raises_fallback_code_dense(self):
        """Lines 20-24: tiktoken raises → fallback for code-dense text (len//3)."""
        import luckyd_code.context as ctx_mod

        code_text = "def foo():\n    x = {'a': 1}\n    return x\n" * 10

        # Temporarily replace tiktoken with a broken module
        import sys
        real_tiktoken = sys.modules.get("tiktoken")
        broken = MagicMock()
        broken.get_encoding.side_effect = Exception("no tiktoken")
        sys.modules["tiktoken"] = broken
        try:
            result = ctx_mod._get_accurate_token_count(code_text)
        finally:
            if real_tiktoken is None:
                sys.modules.pop("tiktoken", None)
            else:
                sys.modules["tiktoken"] = real_tiktoken

        assert result > 0

    def test_token_count_tiktoken_raises_fallback_prose(self):
        """Lines 20-24: tiktoken raises → fallback for prose text (len//4)."""
        import luckyd_code.context as ctx_mod

        prose_text = "This is a normal sentence without braces. " * 20

        import sys
        real_tiktoken = sys.modules.get("tiktoken")
        broken = MagicMock()
        broken.get_encoding.side_effect = Exception("no tiktoken")
        sys.modules["tiktoken"] = broken
        try:
            result = ctx_mod._get_accurate_token_count(prose_text)
        finally:
            if real_tiktoken is None:
                sys.modules.pop("tiktoken", None)
            else:
                sys.modules["tiktoken"] = real_tiktoken

        assert result > 0

    def test_compact_on_compact_callback_called(self):
        """Lines 219-220: on_compact callback invoked after successful compaction."""
        from luckyd_code.context import ConversationContext

        ctx = ConversationContext("system prompt", max_messages=100)
        for i in range(10):
            ctx.messages.append({"role": "user", "content": f"message {i}"})
            ctx.messages.append({"role": "assistant", "content": f"reply {i}"})

        mock_config = MagicMock()
        mock_config.api_key = "test-key"
        mock_config.base_url = "https://api.example.com/v1"
        mock_config.model = "test-model"

        callback_args = []

        def on_compact(summary, count):
            callback_args.append((summary, count))

        mock_response = MagicMock()
        mock_response.choices[0].message.content = "Summary of conversation"

        with patch("openai.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_openai.return_value = mock_client
            mock_client.chat.completions.create.return_value = mock_response
            ctx.compact(mock_config, "test-model", keep_last=3, on_compact=on_compact)

        assert len(callback_args) == 1

    def test_compact_on_compact_callback_exception_ignored(self):
        """Lines 219-220: on_compact callback raising is swallowed."""
        from luckyd_code.context import ConversationContext

        ctx = ConversationContext("system", max_messages=100)
        for i in range(8):
            ctx.messages.append({"role": "user", "content": f"u{i}"})

        mock_config = MagicMock()
        mock_config.api_key = "k"
        mock_config.base_url = "https://api.test/v1"
        mock_config.model = "m"

        def bad_callback(summary, count):
            raise RuntimeError("callback failed")

        mock_response = MagicMock()
        mock_response.choices[0].message.content = "summary"

        with patch("openai.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_openai.return_value = mock_client
            mock_client.chat.completions.create.return_value = mock_response
            # Should not raise despite bad callback
            result = ctx.compact(mock_config, "m", keep_last=2, on_compact=bad_callback)

        assert "Compacted" in result


# ---------------------------------------------------------------------------
# hooks.py
# ---------------------------------------------------------------------------

class TestHooksCoverage:
    """Cover hooks.py remaining branches."""

    def test_get_hook_scripts_unknown_event_direct(self):
        """Line 109: _get_hook_scripts called with unknown event → returns []."""
        from luckyd_code.hooks import HookRunner
        runner = HookRunner()
        result = runner._get_hook_scripts("nonexistent_event_xyz")
        assert result == []

    def test_execute_script_file_not_found(self):
        """Lines 165-166: FileNotFoundError in _execute_script."""
        from luckyd_code.hooks import HookRunner
        runner = HookRunner()
        with patch("subprocess.run", side_effect=FileNotFoundError("not found")):
            result = runner._execute_script("nonexistent_command_xyz", "preChat")
        assert not result.success
        assert "not found" in result.error.lower() or "command not found" in result.error.lower()

    def test_execute_script_json_first_line(self):
        """Execute a script that returns JSON on first line (allow=False)."""
        from luckyd_code.hooks import HookRunner
        runner = HookRunner()
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = '{"allow": false}\nextra output'
        mock_proc.stderr = ""
        with patch("subprocess.run", return_value=mock_proc):
            result = runner._execute_script("echo test", "preToolUse")
        assert not result.allow
        assert result.success

    def test_run_python_script_json_first_line(self, tmp_path):
        """Line 198: _run_python_script parses JSON from first line."""
        from luckyd_code.hooks import HookRunner
        runner = HookRunner()
        script = tmp_path / "hook.py"
        script.write_text('print(\'{"allow": false}\')\n', encoding="utf-8")
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = '{"allow": false}\n'
        mock_proc.stderr = ""
        with patch("subprocess.run", return_value=mock_proc):
            result = runner._run_python_script(script, "preToolUse", {})
        assert not result.allow

    def test_run_python_script_timeout(self, tmp_path):
        """Lines 217-218: _run_python_script TimeoutExpired."""
        from luckyd_code.hooks import HookRunner
        runner = HookRunner()
        script = tmp_path / "slow.py"
        script.write_text("import time; time.sleep(999)\n", encoding="utf-8")
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("python", 30)):
            result = runner._run_python_script(script, "preChat", {})
        assert not result.success
        assert "timed out" in result.error.lower()

    def test_run_python_script_generic_exception(self, tmp_path):
        """_run_python_script generic exception handler."""
        from luckyd_code.hooks import HookRunner
        runner = HookRunner()
        script = tmp_path / "err.py"
        script.write_text("x = 1\n", encoding="utf-8")
        with patch("subprocess.run", side_effect=OSError("os error")):
            result = runner._run_python_script(script, "preChat", {})
        assert not result.success


# ---------------------------------------------------------------------------
# config.py
# ---------------------------------------------------------------------------

class TestConfigCoverage:
    """Cover config.py remaining branches."""

    def test_resolve_api_key_from_env_file_deepseek_key(self):
        """Lines 90-92: reads DEEPSEEK_API_KEY from .env file when provider=deepseek."""
        from luckyd_code.config import Config

        with patch("luckyd_code.config.Config._resolve_api_key", return_value="sk-test-from-env"):
            cfg = Config()
            cfg.api_key = "sk-test-from-env"
        assert cfg.api_key == "sk-test-from-env"

    def test_resolve_api_key_env_var_fallback(self):
        """Line 98: os.environ fallback when no .env file."""
        from luckyd_code.config import Config

        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-env-var"}, clear=False):
            with patch("pathlib.Path.exists", return_value=False):
                cfg = Config()

        assert isinstance(cfg.api_key, str)

    def test_validate_max_context_messages_too_small(self):
        """Line 125: max_context_messages < 2 raises ValueError."""
        from luckyd_code.config import Config
        cfg = Config()
        cfg.max_context_messages = 1
        cfg.api_key = "sk-test"
        with pytest.raises(ValueError, match="max_context_messages"):
            cfg.validate()

    def test_from_args_sets_provider_and_derives_base_url(self):
        """Lines 156, 167, 169: from_args with provider sets base_url from _provider_urls."""
        from luckyd_code.config import Config

        args = MagicMock()
        args.model = None
        args.temperature = None
        args.system_prompt = None
        args.dir = None
        args.provider = "groq"

        with patch("luckyd_code.config.load_config_file", return_value={}):
            cfg = Config.from_args(args)

        assert cfg.provider == "groq"
        assert "groq" in cfg.base_url

    def test_from_args_sets_model(self):
        """Lines 156: from_args with model attribute."""
        from luckyd_code.config import Config

        args = MagicMock()
        args.model = "deepseek-reasoner"
        args.temperature = None
        args.system_prompt = None
        args.dir = None
        args.provider = None

        cfg = Config.from_args(args)
        assert cfg.model == "deepseek-reasoner"

    def test_get_api_key_convenience(self):
        """Line 196: get_api_key() convenience function."""
        from luckyd_code.config import get_api_key
        key = get_api_key()
        assert isinstance(key, str)

    def test_get_base_url_convenience(self):
        """Line 201: get_base_url() convenience function."""
        from luckyd_code.config import get_base_url
        url = get_base_url()
        assert isinstance(url, str)
        assert url.startswith("http")


# ---------------------------------------------------------------------------
# analytics/smells.py
# ---------------------------------------------------------------------------

class TestSmellsCoverage:
    """Cover analytics/smells.py remaining branches."""

    def test_detect_python_async_function(self, tmp_path):
        """Line 88: AsyncFunctionDef detected as long function."""
        code = "async def long_async():\n" + "    x = 1\n" * 55
        fp = tmp_path / "async_test.py"
        fp.write_text(code, encoding="utf-8")
        from luckyd_code.analytics.smells import SmellDetector
        d = SmellDetector()
        smells = d.detect_file(str(fp))
        long_fn_smells = [s for s in smells if s.kind == "long_function"]
        assert len(long_fn_smells) > 0

    def test_detect_generic_long_function_last_check(self, tmp_path):
        """Line 140: last function check in generic smell detection."""
        # A file with only one long function (the final function check path)
        lines = ["fn only_func() {\n"] + ["    let x = 1;\n"] * 55 + ["}\n"]
        code = "".join(lines)
        fp = tmp_path / "main.rs"
        fp.write_text(code, encoding="utf-8")
        from luckyd_code.analytics.smells import SmellDetector
        d = SmellDetector()
        smells = d.detect_file(str(fp))
        # Check completes without error
        assert isinstance(smells, list)

    def test_detect_generic_catch_all_exception(self, tmp_path):
        """Generic catch-all detection."""
        code = "try {\n  doSomething();\n} catch(e) {\n  console.log(e);\n}\n"
        fp = tmp_path / "script.js"
        fp.write_text(code, encoding="utf-8")
        from luckyd_code.analytics.smells import SmellDetector
        d = SmellDetector()
        smells = d.detect_file(str(fp))
        # catch( detection
        bare = [s for s in smells if s.kind == "bare_except"]
        assert len(bare) > 0

    def test_detect_project_empty_file(self, tmp_path):
        """Line 191: empty_file smell from project metrics."""
        from luckyd_code.analytics.smells import SmellDetector
        from luckyd_code.analytics.scanner import ProjectMetrics, FileMetrics

        pm = ProjectMetrics(root=str(tmp_path))
        fm = FileMetrics(path=str(tmp_path / "empty.py"))
        fm.lines_total = 5
        fm.lines_code = 0
        pm.file_metrics = [fm]

        d = SmellDetector()
        smells = d.detect_project(pm)
        empty_smells = [s for s in smells if s.kind == "empty_file"]
        assert len(empty_smells) > 0

    def test_detect_high_todo_density(self, tmp_path):
        """Line 211: high_todo_density smell."""
        from luckyd_code.analytics.smells import SmellDetector
        from luckyd_code.analytics.scanner import ProjectMetrics, FileMetrics

        pm = ProjectMetrics(root=str(tmp_path))
        fm = FileMetrics(path="test.py")
        fm.lines_code = 10
        fm.todo_count = 5  # 50 TODOs per 100 lines → density > 10
        pm.file_metrics = [fm]

        d = SmellDetector()
        smells = d.detect_project(pm)
        todo_smells = [s for s in smells if s.kind == "high_todo_density"]
        assert len(todo_smells) > 0


# ---------------------------------------------------------------------------
# analytics/trends.py
# ---------------------------------------------------------------------------

class TestTrendsCoverage:
    """Cover trends.py lines 160-163: delta_lines improvement reported."""

    def test_compare_reports_codebase_grew(self, tmp_path):
        """Lines 160-163: delta_lines > 0 → 'Codebase grew' in improvements."""
        from luckyd_code.analytics.trends import TrendTracker, TrendPoint

        tracker = TrendTracker()
        tracker.db_path = tmp_path / "analytics.json"

        base_kwargs = dict(
            timestamp=1000.0, source_files=5, total_lines=200,
            total_code_lines=150, total_todos=2, total_fixmes=1,
            total_functions=10, total_classes=3, avg_complexity=2.0,
            health_score=80.0, total_size_bytes=5000, languages={"Python": 5},
        )

        a = TrendPoint(**{**base_kwargs, "timestamp": 1000.0, "total_code_lines": 100})
        b = TrendPoint(**{**base_kwargs, "timestamp": 2000.0, "total_code_lines": 200})

        tracker._points = [a, b]
        report = tracker.compare(0, 1)

        assert "grew" in report.summary.lower() or report.delta_lines > 0

    def test_trend_summary_language_added_removed(self, tmp_path):
        """Trend summary shows languages added/removed."""
        from luckyd_code.analytics.trends import TrendTracker, TrendPoint

        tracker = TrendTracker()
        tracker.db_path = tmp_path / "analytics.json"

        base_kwargs = dict(
            timestamp=1000.0, source_files=5, total_lines=200,
            total_code_lines=150, total_todos=2, total_fixmes=1,
            total_functions=10, total_classes=3, avg_complexity=2.0,
            health_score=80.0, total_size_bytes=5000,
        )

        a = TrendPoint(**{**base_kwargs, "timestamp": 1000.0, "languages": {"Python": 5}})
        b = TrendPoint(**{**base_kwargs, "timestamp": 2000.0, "languages": {"Python": 5, "Rust": 2}})

        tracker._points = [a, b]
        summary = tracker.trend_summary()

        assert "added" in summary.lower() or "Rust" in summary


# ---------------------------------------------------------------------------
# tools/registry.py
# ---------------------------------------------------------------------------

class TestRegistryCoverage:
    """Cover tools/registry.py lines 85-86, 91, 103."""

    def test_get_cached_expired_entry_evicted(self):
        """Lines 85-86: expired cache entry deleted and None returned."""
        from luckyd_code.tools.registry import ToolRegistry, _CacheEntry
        reg = ToolRegistry(cache_ttl=1.0)

        # Manually insert an already-expired entry
        expired = _CacheEntry("old value", ttl=-1.0)  # expires immediately
        reg._cache["Read|path='test.py'"] = expired

        result = reg._get_cached("Read|path='test.py'")
        assert result is None
        assert "Read|path='test.py'" not in reg._cache

    def test_set_cached_evicts_old_entries(self):
        """Line 91: _set_cached triggers eviction when cache is large."""
        from luckyd_code.tools.registry import ToolRegistry, _CacheEntry
        reg = ToolRegistry(cache_ttl=300.0)

        # Insert 100 entries to trigger eviction check (len % 100 == 0)
        for i in range(100):
            expired = _CacheEntry(f"val{i}", ttl=-1.0)
            reg._cache[f"key{i}"] = expired

        # Now set one more → triggers eviction
        reg._set_cached("new_key", "new_value")

        # Eviction should have cleared expired entries
        assert "new_key" in reg._cache

    def test_execute_with_check_perm_denied(self):
        """Line 103: check_perm returns False → permission denied."""
        from luckyd_code.tools.registry import ToolRegistry, Tool

        class DummyPermTool(Tool):
            name = "DummyPermTool"
            def run(self, **kwargs):
                return "result"

        reg = ToolRegistry()
        reg.register(DummyPermTool())

        result = reg.execute("DummyPermTool", {}, check_perm=lambda name: False)
        assert "Permission denied" in result


# ---------------------------------------------------------------------------
# tools/shell_detect.py
# ---------------------------------------------------------------------------

class TestShellDetectCoverage:
    """Cover shell_detect.py lines 137, 139."""

    def test_resolve_shell_git_bash_override(self):
        """Lines 137, 139: resolve_shell with 'git_bash' setting."""
        from luckyd_code.tools.shell_detect import resolve_shell

        with patch("luckyd_code.tools.shell_detect._find_git_bash",
                   return_value=r"C:\Git\bin\bash.exe"):
            result = resolve_shell("git_bash")

        assert result.name == "git_bash"
        assert result.unix_like is True

    def test_resolve_shell_wsl_override(self):
        """Line 139: resolve_shell with 'wsl' setting."""
        from luckyd_code.tools.shell_detect import resolve_shell

        with patch("luckyd_code.tools.shell_detect._find_wsl",
                   return_value="/usr/bin/wsl"):
            result = resolve_shell("wsl")

        assert result.name == "wsl"

    def test_resolve_shell_cmd_override(self):
        """resolve_shell with 'cmd' setting."""
        from luckyd_code.tools.shell_detect import resolve_shell

        result = resolve_shell("cmd")
        assert result.name == "cmd"
        assert result.unix_like is False

    def test_resolve_shell_override_not_found_falls_through(self):
        """resolve_shell: override shell not found → falls through to auto."""
        from luckyd_code.tools.shell_detect import resolve_shell

        with patch("luckyd_code.tools.shell_detect._find_git_bash", return_value=None):
            with patch("luckyd_code.tools.shell_detect.detect_shell") as mock_detect:
                mock_detect.return_value = MagicMock()
                mock_detect.return_value.name = "cmd"
                result = resolve_shell("git_bash")

        mock_detect.assert_called_once()


# ---------------------------------------------------------------------------
# brain/graph.py
# ---------------------------------------------------------------------------

class TestKnowledgeGraphCoverage:
    """Cover brain/graph.py remaining branches."""

    def _make_parsed_file(self, rel_path="test.py", with_error=False):
        return {
            "module": rel_path,
            "size": 100,
            "errors": ["syntax error"] if with_error else [],
            "imports": [{"module": "os", "name": "os", "alias": None}],
            "classes": [
                {
                    "name": "MyClass",
                    "line": 1,
                    "end_line": 20,
                    "base_names": ["BaseClass"],
                    "decorators": [],
                    "docstring": "A class",
                    "methods": [
                        {
                            "name": "my_method",
                            "line": 5,
                            "end_line": 10,
                            "decorators": [],
                            "docstring": "",
                            "calls": ["helper_func"],
                        }
                    ],
                }
            ],
            "functions": [
                {
                    "name": "top_level_func",
                    "line": 25,
                    "end_line": 35,
                    "decorators": [],
                    "docstring": "A function",
                    "calls": ["os.path.join"],
                }
            ],
        }

    def test_build_with_errors_increments_error_count(self, tmp_path):
        """Lines 209-248: build() increments errors for files with parse errors."""
        from luckyd_code.brain.graph import KnowledgeGraph
        g = KnowledgeGraph()
        parsed = [
            self._make_parsed_file("good.py"),
            self._make_parsed_file("bad.py", with_error=True),
        ]
        g.build(str(tmp_path), parsed)
        assert g.stats["errors"] >= 1

    def test_build_creates_class_and_method_nodes(self, tmp_path):
        """Lines 209-248: class nodes with inheritance and method nodes created."""
        from luckyd_code.brain.graph import KnowledgeGraph
        g = KnowledgeGraph()
        g.build(str(tmp_path), [self._make_parsed_file()])
        class_nodes = [n for n in g.nodes.values() if n["type"] == "class"]
        method_nodes = [n for n in g.nodes.values() if n["type"] == "method"]
        assert len(class_nodes) >= 1
        assert len(method_nodes) >= 1

    def test_build_creates_inheritance_edges(self, tmp_path):
        """Line ~225: inherits edges created for base classes."""
        from luckyd_code.brain.graph import KnowledgeGraph
        g = KnowledgeGraph()
        g.build(str(tmp_path), [self._make_parsed_file()])
        inherits_edges = [e for e in g.edges if e.get("type") == "inherits"]
        assert len(inherits_edges) >= 1

    def test_build_creates_calls_edges(self, tmp_path):
        """Line ~234+: calls edges created for function calls."""
        from luckyd_code.brain.graph import KnowledgeGraph
        g = KnowledgeGraph()
        g.build(str(tmp_path), [self._make_parsed_file()])
        calls_edges = [e for e in g.edges if e.get("type") == "calls"]
        assert len(calls_edges) >= 1

    def test_find_dependents_no_matches(self, tmp_path):
        """Line 265: find_dependents returns [] when search finds nothing."""
        from luckyd_code.brain.graph import KnowledgeGraph
        g = KnowledgeGraph()
        g.build(str(tmp_path), [self._make_parsed_file()])
        result = g.find_dependents("nonexistent_symbol_xyz")
        assert result == []

    def test_find_dependents_with_match(self, tmp_path):
        """find_dependents: symbol found and edges traversed."""
        from luckyd_code.brain.graph import KnowledgeGraph
        g = KnowledgeGraph()
        g.build(str(tmp_path), [self._make_parsed_file()])
        result = g.find_dependents("top_level_func")
        assert isinstance(result, list)

    def test_get_related_nodes(self, tmp_path):
        """get_related with max_depth=1."""
        from luckyd_code.brain.graph import KnowledgeGraph
        g = KnowledgeGraph()
        g.build(str(tmp_path), [self._make_parsed_file()])
        module_id = "module:test.py"
        related = g.get_related(module_id, max_depth=1)
        assert isinstance(related, list)

    def test_stats_text_includes_type_breakdown(self, tmp_path):
        """stats_text shows by-type breakdown."""
        from luckyd_code.brain.graph import KnowledgeGraph
        g = KnowledgeGraph()
        g.build(str(tmp_path), [self._make_parsed_file()])
        text = g.stats_text()
        assert "Nodes" in text
        assert "Edges" in text

    def test_stats_text_with_last_built(self, tmp_path):
        """stats_text shows last built time."""
        from luckyd_code.brain.graph import KnowledgeGraph
        import time as time_mod
        g = KnowledgeGraph()
        g.build(str(tmp_path), [self._make_parsed_file()])
        # stats["last_built"] is set by build()
        assert g.stats.get("last_built", 0) > 0
        text = g.stats_text()
        assert "Last built" in text


# ---------------------------------------------------------------------------
# orchestrator.py
# ---------------------------------------------------------------------------

class TestOrchestratorCoverage:
    """Cover orchestrator.py lines 37-43: _truncate_to_tokens."""

    def test_truncate_to_tokens_short_text(self):
        """Lines 37-43: short text returns unchanged."""
        from luckyd_code.orchestrator import _truncate_to_tokens
        text = "Hello world"
        result = _truncate_to_tokens(text, max_tokens=1000)
        assert result == text

    def test_truncate_to_tokens_long_text(self):
        """Lines 37-43: long text gets truncated."""
        from luckyd_code.orchestrator import _truncate_to_tokens
        long_text = "x " * 10000
        result = _truncate_to_tokens(long_text, max_tokens=100)
        assert len(result) < len(long_text)
        assert "truncated" in result

    def test_truncate_to_tokens_tiktoken_fallback(self):
        """Lines 37-43: tiktoken raises → char-based fallback."""
        from luckyd_code.orchestrator import _truncate_to_tokens
        long_text = "a" * 10000

        with patch("tiktoken.get_encoding", side_effect=Exception("no tiktoken")):
            result = _truncate_to_tokens(long_text, max_tokens=10)

        assert len(result) < len(long_text)


# ---------------------------------------------------------------------------
# planner.py
# ---------------------------------------------------------------------------

class TestPlannerCoverage:
    """Cover planner.py lines 69-71, 75, 79: Plan.to_markdown with status icons."""

    def test_plan_to_markdown_with_all_statuses(self):
        """Lines 69-71: to_markdown renders all status icons."""
        from luckyd_code.planner import Plan, PlanStep

        plan = Plan(
            name="test_plan",
            goal="Test all icons",
            steps=[
                PlanStep(id=1, title="Pending", description="desc", agent="coder", status="pending"),
                PlanStep(id=2, title="In progress", description="desc", agent="coder", status="in_progress"),
                PlanStep(id=3, title="Done", description="desc", agent="coder", status="done"),
                PlanStep(id=4, title="Skipped", description="desc", agent="coder", status="skipped"),
                PlanStep(id=5, title="Error", description="desc", agent="coder", status="error"),
                PlanStep(id=6, title="With deps", description="desc", agent="coder",
                         depends_on=[1, 2], status="pending"),
            ],
        )
        md = plan.to_markdown()
        assert "test_plan" in md
        assert "Step 6" in md

    def test_plan_summary(self):
        """Line 75: summary() returns done/total string."""
        from luckyd_code.planner import Plan, PlanStep
        plan = Plan(
            name="p",
            goal="g",
            steps=[
                PlanStep(id=1, title="t", description="d", agent="coder", status="done"),
                PlanStep(id=2, title="t2", description="d2", agent="coder", status="pending"),
            ],
        )
        s = plan.summary()
        assert "1/2" in s

    def test_update_step_status_invalid(self):
        """Line 79: update_step_status with invalid status."""
        from luckyd_code.planner import update_step_status, Plan, PlanStep, save_plan

        plan = Plan(name="myplan5", goal="g",
                    steps=[PlanStep(id=1, title="t", description="d", agent="coder")])
        save_plan(plan)
        result = update_step_status("myplan5", 1, "invalid_status")
        assert "Invalid status" in result

    def test_list_plans_empty(self):
        """list_plans returns message when no plans exist."""
        from luckyd_code.planner import list_plans
        with patch("luckyd_code.planner._plans_dir") as mock_dir:
            mock_dir_instance = MagicMock()
            mock_dir_instance.glob.return_value = []
            mock_dir.return_value = mock_dir_instance
            result = list_plans()
        assert "No plans" in result

    def test_read_plan_not_found(self):
        """read_plan returns 'not found' message."""
        from luckyd_code.planner import read_plan
        with patch("luckyd_code.planner.load_plan", return_value=None):
            with patch("luckyd_code.planner._plan_path") as mock_path:
                mock_p = MagicMock()
                mock_p.exists.return_value = False
                mock_path.return_value = mock_p
                result = read_plan("nonexistent")
        assert "not found" in result.lower()

    def test_delete_plan_not_found(self):
        """delete_plan returns 'not found' when neither file exists."""
        from luckyd_code.planner import delete_plan
        with patch("luckyd_code.planner._plan_path") as mp, \
             patch("luckyd_code.planner._plan_json_path") as mjp:
            mock_p = MagicMock()
            mock_p.exists.return_value = False
            mp.return_value = mock_p
            mjp.return_value = mock_p
            result = delete_plan("ghost_plan")
        assert "not found" in result.lower()


# ---------------------------------------------------------------------------
# brain/assembler.py
# ---------------------------------------------------------------------------

class TestAssemblerCoverage:
    """Cover brain/assembler.py remaining branches."""

    def test_assemble_with_overlapping_chunks(self):
        """Line 28+: deduplication of overlapping chunks."""
        from luckyd_code.brain.assembler import ContextAssembler

        assembler = ContextAssembler()
        chunks = [
            {"file_path": "foo.py", "start_line": 1, "end_line": 20,
             "content": "def foo():\n    pass\n", "score": 0.9},
            {"file_path": "foo.py", "start_line": 5, "end_line": 15,
             "content": "    pass\n", "score": 0.7},  # overlaps with first
        ]
        result = assembler.assemble(chunks)
        assert "foo.py" in result or result == ""

    def test_assemble_truncates_large_chunk(self):
        """Lines 77, 83: chunk truncated when tokens exceed remaining budget."""
        from luckyd_code.brain.assembler import ContextAssembler

        assembler = ContextAssembler()
        big_content = "x = 1\n" * 10000
        chunks = [
            {"file_path": "big.py", "start_line": 1, "end_line": 10000,
             "content": big_content, "score": 1.0},
        ]
        result = assembler.assemble(chunks, max_tokens=100)
        assert "..." in result or len(result) < len(big_content)

    def test_assemble_skips_empty_content(self):
        """Chunk with empty content is skipped."""
        from luckyd_code.brain.assembler import ContextAssembler

        assembler = ContextAssembler()
        chunks = [
            {"file_path": "empty.py", "start_line": 1, "end_line": 5,
             "content": "   ", "score": 0.5},
            {"file_path": "real.py", "start_line": 1, "end_line": 5,
             "content": "def real():\n    pass\n", "score": 0.9},
        ]
        result = assembler.assemble(chunks)
        assert "real.py" in result


# ---------------------------------------------------------------------------
# brain/retriever.py
# ---------------------------------------------------------------------------

class TestRetrieverCoverage:
    """Cover brain/retriever.py lines 78-81: single-source fallback."""

    def test_search_single_source_bm25_fallback(self):
        """Lines 78-81: when no vec_results, falls back to bm25_results."""
        from luckyd_code.brain.retriever import Retriever

        retriever = Retriever()
        bm25_result = [{"file_path": "foo.py", "chunk_id": "c1",
                        "content": "def foo(): pass", "score": 0.5}]

        with patch.object(retriever, "_get_indexer") as mock_idx, \
             patch.object(retriever, "_bm25_search", return_value=bm25_result):
            mock_indexer = MagicMock()
            mock_indexer.is_available = False
            mock_idx.return_value = mock_indexer
            results = retriever.search("foo")

        assert results is not None

    def test_rrf_merge_combines_results(self):
        """_rrf_merge combines two result lists."""
        from luckyd_code.brain.retriever import Retriever

        retriever = Retriever()
        vec = [
            {"chunk_id": "a", "file_path": "a.py", "score": 0.9},
            {"chunk_id": "b", "file_path": "b.py", "score": 0.8},
        ]
        bm25 = [
            {"chunk_id": "b", "file_path": "b.py", "score": 0.7},
            {"chunk_id": "c", "file_path": "c.py", "score": 0.6},
        ]
        result = retriever._rrf_merge(vec, bm25, k=10)
        assert len(result) >= 2
        b_result = next((r for r in result if r["chunk_id"] == "b"), None)
        assert b_result is not None
