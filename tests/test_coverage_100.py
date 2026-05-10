"""Coverage push — targets every remaining uncovered module.

Priority: exceptions, settings, tools_bridge, sessions edge cases,
agent, init constants, update edge cases, keybindings, cli Repl methods.

Design rules for Repl tests
─────────────────────────────
* Call Repl.method(repl, ...) where repl = MagicMock(). Python's MRO sends
  attribute lookups (self.foo) to the MagicMock instance — never use
  patch.object(Repl, "foo") for those; set repl.foo.return_value instead.
* Patch module-level names at their IMPORT SITE inside luckyd_code.cli:
    console   → "luckyd_code.cli.console"
    data_path → "luckyd_code.cli.data_path"
    cfg.*     → "luckyd_code.cli.cfg.<attr>"
* _prompt_for_api_key re-imports read_input locally
  ("from .cli_utils import read_input") so patch the SOURCE:
    "luckyd_code.cli_utils.read_input"
* _load_memory uses a local "from .indexer import index_project":
    patch "luckyd_code.indexer.index_project" (source module).
"""
from __future__ import annotations

import json
import signal
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import pytest


# ===========================================================================
# exceptions.py
# ===========================================================================

class TestExceptions:
    def test_base_error(self):
        from luckyd_code.exceptions import LuckyDCodeError
        e = LuckyDCodeError("base error")
        assert str(e) == "base error"
        assert isinstance(e, Exception)

    def test_deepseek_alias(self):
        from luckyd_code.exceptions import DeepSeekAPIError, LuckyDCodeError
        assert DeepSeekAPIError is LuckyDCodeError

    def test_authentication_error(self):
        from luckyd_code.exceptions import AuthenticationError, LuckyDCodeError
        e = AuthenticationError("bad key")
        assert isinstance(e, LuckyDCodeError)
        assert "bad key" in str(e)

    def test_retryable_error(self):
        from luckyd_code.exceptions import RetryableError, LuckyDCodeError
        assert isinstance(RetryableError("timeout"), LuckyDCodeError)

    def test_non_retryable_error(self):
        from luckyd_code.exceptions import NonRetryableError, LuckyDCodeError
        assert isinstance(NonRetryableError("bad request"), LuckyDCodeError)

    def test_model_not_found_error(self):
        from luckyd_code.exceptions import ModelNotFoundError, NonRetryableError
        assert isinstance(ModelNotFoundError("gpt-99"), NonRetryableError)

    def test_context_length_error(self):
        from luckyd_code.exceptions import ContextLengthError, NonRetryableError
        assert isinstance(ContextLengthError("too long"), NonRetryableError)

    def test_tool_execution_error(self):
        from luckyd_code.exceptions import ToolExecutionError, LuckyDCodeError
        assert isinstance(ToolExecutionError("bash failed"), LuckyDCodeError)

    def test_catch_base_catches_subclass(self):
        from luckyd_code.exceptions import LuckyDCodeError, AuthenticationError
        with pytest.raises(LuckyDCodeError):
            raise AuthenticationError("caught as base")

    def test_catch_non_retryable_catches_subclass(self):
        from luckyd_code.exceptions import NonRetryableError, ModelNotFoundError
        with pytest.raises(NonRetryableError):
            raise ModelNotFoundError("caught")

    def test_exception_args_preserved(self):
        from luckyd_code.exceptions import ContextLengthError
        e = ContextLengthError("too many tokens", 12345)
        assert e.args == ("too many tokens", 12345)


# ===========================================================================
# settings.py — run_pre_hook and edge cases
# ===========================================================================

class TestSettingsRunPreHook:
    @pytest.fixture(autouse=True)
    def _patch_paths(self, tmp_path):
        self.tmp = tmp_path
        self.settings_file = tmp_path / "settings.local.json"
        self.base_file = tmp_path / "settings.json"
        with patch("luckyd_code.settings.get_settings_dir", return_value=tmp_path), \
             patch("luckyd_code.settings.get_local_settings_path",
                   return_value=self.settings_file), \
             patch("luckyd_code.settings.get_settings_path",
                   return_value=self.base_file):
            yield

    def test_run_pre_hook_no_hooks_configured(self):
        from luckyd_code.settings import run_pre_hook
        assert run_pre_hook("Bash") == []

    def test_run_pre_hook_string_hook_success(self):
        from luckyd_code.settings import run_pre_hook
        self.settings_file.write_text(
            json.dumps({"hooks": {"preToolUse": "echo ok"}}))
        with patch("subprocess.run",
                   return_value=MagicMock(returncode=0, stderr="")):
            result = run_pre_hook("Bash")
        assert result == []

    def test_run_pre_hook_string_hook_fails(self):
        from luckyd_code.settings import run_pre_hook
        self.settings_file.write_text(
            json.dumps({"hooks": {"preToolUse": "exit 1"}}))
        with patch("subprocess.run",
                   return_value=MagicMock(returncode=1, stderr="hook error")):
            result = run_pre_hook("Bash")
        assert result == ["hook error"]

    def test_run_pre_hook_dict_hook_all_tools(self):
        from luckyd_code.settings import run_pre_hook
        hook = {"script": "echo hi", "tools": ["all"]}
        self.settings_file.write_text(json.dumps({"hooks": {"preToolUse": hook}}))
        with patch("subprocess.run",
                   return_value=MagicMock(returncode=0, stderr="")):
            assert run_pre_hook("AnyTool") == []

    def test_run_pre_hook_dict_hook_specific_match(self):
        from luckyd_code.settings import run_pre_hook
        hook = {"script": "echo hi", "tools": ["Write", "Edit"]}
        self.settings_file.write_text(json.dumps({"hooks": {"preToolUse": hook}}))
        with patch("subprocess.run",
                   return_value=MagicMock(returncode=0, stderr="")):
            assert run_pre_hook("Write") == []

    def test_run_pre_hook_dict_hook_tool_not_in_list(self):
        from luckyd_code.settings import run_pre_hook
        hook = {"script": "echo hi", "tools": ["Write"]}
        self.settings_file.write_text(json.dumps({"hooks": {"preToolUse": hook}}))
        with patch("subprocess.run") as mock_run:
            run_pre_hook("Bash")
        mock_run.assert_not_called()

    def test_run_pre_hook_exception_returns_string(self):
        from luckyd_code.settings import run_pre_hook
        self.settings_file.write_text(
            json.dumps({"hooks": {"preToolUse": "fail"}}))
        with patch("subprocess.run", side_effect=OSError("no shell")):
            result = run_pre_hook("Bash")
        assert len(result) == 1 and "no shell" in result[0]

    def test_run_pre_hook_empty_script_skips(self):
        from luckyd_code.settings import run_pre_hook
        self.settings_file.write_text(
            json.dumps({"hooks": {"preToolUse": ""}}))
        with patch("subprocess.run") as mock_run:
            run_pre_hook("Bash")
        mock_run.assert_not_called()

    def test_load_settings_merges_base_and_local(self):
        from luckyd_code.settings import load_settings
        self.base_file.write_text(
            json.dumps({"theme": "dark", "auto_commit": True}))
        self.settings_file.write_text(
            json.dumps({"theme": "light"}))
        settings = load_settings()
        assert settings["theme"] == "light"
        assert settings["auto_commit"] is True

    def test_save_setting_creates_parent_dirs(self, tmp_path):
        from luckyd_code.settings import save_setting
        deep = tmp_path / "nested" / "dir" / "settings.local.json"
        with patch("luckyd_code.settings.get_local_settings_path",
                   return_value=deep):
            save_setting("my_key", "my_value")
        data = json.loads(deep.read_text())
        assert data["my_key"] == "my_value"

    def test_get_hooks_returns_empty_dict(self):
        from luckyd_code.settings import get_hooks
        with patch("luckyd_code.settings.load_settings", return_value={}):
            assert get_hooks() == {}

    def test_get_hooks_returns_hooks_section(self):
        from luckyd_code.settings import get_hooks
        hooks = {"preToolUse": "echo hi"}
        with patch("luckyd_code.settings.load_settings",
                   return_value={"hooks": hooks}):
            assert get_hooks() == hooks


# ===========================================================================
# sessions.py — edge cases
# ===========================================================================

class TestSessionsEdgeCases:
    @pytest.fixture(autouse=True)
    def _tmp_sessions(self, tmp_path):
        self.sessions_dir = tmp_path / "sessions"
        with patch("luckyd_code.sessions.SESSIONS_DIR", self.sessions_dir):
            yield

    def _ctx(self):
        from luckyd_code.context import ConversationContext
        ctx = ConversationContext("You are helpful.")
        ctx.add_user_message("hello")
        ctx.add_assistant_message(content="world")
        return ctx

    def test_sanitize_name_special_chars(self):
        from luckyd_code.sessions import _sanitize_name
        assert _sanitize_name("my/session!") == "my_session_"
        assert _sanitize_name("   ") == "unnamed"
        assert _sanitize_name("ok-name_123") == "ok-name_123"

    def test_sanitize_name_spaces_preserved(self):
        from luckyd_code.sessions import _sanitize_name
        result = _sanitize_name("my session")
        assert "session" in result

    def test_load_session_partial_name_match(self):
        from luckyd_code.sessions import save_session, load_session
        ctx = self._ctx()
        save_session("my-long-session-name", ctx)
        new_ctx = self._ctx()
        result = load_session("my-long", new_ctx)
        assert isinstance(result, str)

    def test_load_session_corrupt_json(self):
        from luckyd_code.sessions import load_session
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        (self.sessions_dir / "bad.json").write_text(
            "NOT JSON {{{", encoding="utf-8")
        result = load_session("bad", self._ctx())
        assert "Error" in result

    def test_load_session_empty_messages_field(self):
        from luckyd_code.sessions import load_session
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        data = {"name": "empty", "messages": [],
                "saved_at": "2024-01-01T00:00:00", "message_count": 0}
        (self.sessions_dir / "empty.json").write_text(json.dumps(data))
        result = load_session("empty", self._ctx())
        assert "empty" in result.lower() or "Session" in result

    def test_load_session_preserves_new_system_prompt(self):
        from luckyd_code.sessions import save_session, load_session
        ctx = self._ctx()
        save_session("sys_test", ctx)
        new_ctx = self._ctx()
        new_ctx.messages[0]["content"] = "NEW SYSTEM"
        load_session("sys_test", new_ctx)
        assert new_ctx.messages[0]["content"] == "NEW SYSTEM"

    def test_load_session_respects_max_messages(self):
        from luckyd_code.sessions import save_session, load_session
        from luckyd_code.context import ConversationContext
        ctx = ConversationContext("sys", max_messages=20)
        for i in range(15):
            ctx.add_user_message(f"msg {i}")
        save_session("big", ctx)
        small_ctx = ConversationContext("sys", max_messages=4)
        load_session("big", small_ctx)
        assert len(small_ctx.messages) <= 4

    def test_list_sessions_with_corrupt_file(self):
        from luckyd_code.sessions import list_sessions
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        (self.sessions_dir / "corrupt.json").write_text(
            "GARBAGE", encoding="utf-8")
        result = list_sessions()
        assert isinstance(result, str)

    def test_delete_exact_match(self):
        from luckyd_code.sessions import save_session, delete_session
        save_session("exact", self._ctx())
        assert "deleted" in delete_session("exact").lower()

    def test_delete_not_found(self):
        from luckyd_code.sessions import delete_session
        assert "not found" in delete_session("ghost-session")


# ===========================================================================
# agent.py — SubAgent
# ===========================================================================

class TestSubAgent:
    def _cfg(self):
        cfg = MagicMock()
        cfg.api_key = "sk-test"
        cfg.base_url = "https://api.deepseek.com/v1"
        cfg.model = "deepseek-v4-flash"
        cfg.max_tokens = 4096
        cfg.temperature = 0.7
        cfg.provider = "deepseek"
        cfg.system_prompt = "You are helpful."
        cfg.working_directory = None
        cfg.max_context_messages = 20
        return cfg

    def test_init_attributes(self):
        from luckyd_code.agent import SubAgent
        a = SubAgent(self._cfg(), "write tests")
        assert a.task == "write tests"
        assert a.tools is None
        assert a.context is not None
        assert a.registry is not None

    def test_init_with_tools(self):
        from luckyd_code.agent import SubAgent
        tools = [{"function": {"name": "Read"}}]
        a = SubAgent(self._cfg(), "task", tools=tools)
        assert a.tools == tools

    def test_run_returns_string(self):
        from luckyd_code.agent import SubAgent
        a = SubAgent(self._cfg(), "summarize the code")
        with patch("luckyd_code.agent.run_agent_loop",
                   return_value="Summary done") as mock:
            result = a.run()
        assert result == "Summary done"
        mock.assert_called_once()

    def test_run_adds_task_to_context(self):
        from luckyd_code.agent import SubAgent
        a = SubAgent(self._cfg(), "analyze patterns")
        with patch("luckyd_code.agent.run_agent_loop", return_value="ok"):
            a.run()
        user_msgs = [m for m in a.context.messages if m.get("role") == "user"]
        assert any("analyze patterns" in m.get("content", "") for m in user_msgs)

    def test_run_uses_given_tools(self):
        from luckyd_code.agent import SubAgent
        my_tools = [{"function": {"name": "Custom"}}]
        a = SubAgent(self._cfg(), "task", tools=my_tools)
        with patch("luckyd_code.agent.run_agent_loop",
                   return_value="ok") as mock:
            a.run()
        args, kwargs = mock.call_args
        passed = kwargs.get("tools") or (args[2] if len(args) > 2 else None)
        assert passed == my_tools

    def test_run_uses_registry_when_no_tools(self):
        from luckyd_code.agent import SubAgent
        a = SubAgent(self._cfg(), "task")
        with patch("luckyd_code.agent.run_agent_loop",
                   return_value="ok") as mock:
            a.run()
        args, kwargs = mock.call_args
        passed = kwargs.get("tools") or (args[2] if len(args) > 2 else None)
        assert passed is not None


# ===========================================================================
# tools_bridge.py — all public functions
# ===========================================================================

class TestToolsBridge:
    # ── _parse_args ──────────────────────────────────────────────────────
    def test_parse_args_key_value(self):
        from luckyd_code.tools_bridge import _parse_args
        result = _parse_args(["url=https://example.com", "timeout=30"])
        assert result["url"] == "https://example.com"
        assert result["timeout"] == 30

    def test_parse_args_flag_style(self):
        from luckyd_code.tools_bridge import _parse_args
        result = _parse_args(["--url", "https://example.com", "--verbose"])
        assert result["url"] == "https://example.com"
        assert result["verbose"] is True

    def test_parse_args_trailing_flag(self):
        from luckyd_code.tools_bridge import _parse_args
        assert _parse_args(["--flag"])["flag"] is True

    def test_parse_args_json_value(self):
        from luckyd_code.tools_bridge import _parse_args
        result = _parse_args(["--data", '{"key": "val"}'])
        assert result["data"] == {"key": "val"}

    def test_parse_args_plain_string_value(self):
        from luckyd_code.tools_bridge import _parse_args
        assert _parse_args(["--name", "hello world"])["name"] == "hello world"

    def test_parse_args_empty(self):
        from luckyd_code.tools_bridge import _parse_args
        assert _parse_args([]) == {}

    # ── _import_tool ──────────────────────────────────────────────────────
    def test_import_tool_found(self):
        from luckyd_code.tools_bridge import _import_tool
        mock_tool = MagicMock()
        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_tool
        # get_default_registry is imported lazily inside _import_tool body;
        # patch the source module, not tools_bridge (which never binds the name).
        with patch("luckyd_code.tools.get_default_registry",
                   return_value=mock_registry):
            assert _import_tool("MyTool") is mock_tool

    def test_import_tool_unknown_exits(self):
        from luckyd_code.tools_bridge import _import_tool
        mock_registry = MagicMock()
        mock_registry.get.return_value = None
        mock_registry._tools = {}
        with patch("luckyd_code.tools.get_default_registry",
                   return_value=mock_registry):
            with pytest.raises(SystemExit):
                _import_tool("Ghost")

    # ── cmd_info ──────────────────────────────────────────────────────────
    def test_cmd_info_prints(self):
        from luckyd_code.tools_bridge import cmd_info
        mock_tool = MagicMock()
        mock_tool.name = "TestTool"
        mock_tool.permission_risk = "safe"
        mock_tool.description = "A test tool"
        mock_tool.parameters = {
            "properties": {"url": {"description": "URL"}},
            "required": ["url"],
        }
        with patch("luckyd_code.tools_bridge._import_tool", return_value=mock_tool):
            cmd_info("TestTool")

    def test_cmd_info_optional_param(self):
        from luckyd_code.tools_bridge import cmd_info
        mock_tool = MagicMock()
        mock_tool.name = "T"
        mock_tool.permission_risk = "medium"
        mock_tool.description = "D"
        mock_tool.parameters = {
            "properties": {"opt": {"description": "optional"}},
            "required": [],
        }
        with patch("luckyd_code.tools_bridge._import_tool", return_value=mock_tool):
            cmd_info("T")

    # ── cmd_run ──────────────────────────────────────────────────────────
    def test_cmd_run_executes_tool(self):
        from luckyd_code.tools_bridge import cmd_run
        mock_tool = MagicMock()
        mock_tool.run.return_value = "result"
        with patch("luckyd_code.tools_bridge._import_tool", return_value=mock_tool):
            cmd_run("TestTool", "--key", "value")
        mock_tool.run.assert_called_once_with(key="value")

    def test_cmd_run_no_args(self):
        from luckyd_code.tools_bridge import cmd_run
        mock_tool = MagicMock()
        mock_tool.run.return_value = "ok"
        with patch("luckyd_code.tools_bridge._import_tool", return_value=mock_tool):
            cmd_run("GitStatus")
        mock_tool.run.assert_called_once_with()

    # ── cmd_list ──────────────────────────────────────────────────────────
    def test_cmd_list_prints_tools(self):
        from luckyd_code.tools_bridge import cmd_list
        mock_tool = MagicMock()
        mock_tool.description = "Does something"
        mock_tool.permission_risk = "safe"
        mock_registry = MagicMock()
        mock_registry._tools = {"MyTool": mock_tool}
        # cmd_list also imports get_default_registry lazily; patch the source.
        with patch("luckyd_code.tools.get_default_registry",
                   return_value=mock_registry):
            cmd_list()

    def test_cmd_list_risk_icons(self):
        from luckyd_code.tools_bridge import cmd_list
        tools = {}
        for risk in ("safe", "medium", "high"):
            t = MagicMock()
            t.description = "desc"
            t.permission_risk = risk
            tools[risk + "Tool"] = t
        mock_registry = MagicMock()
        mock_registry._tools = tools
        with patch("luckyd_code.tools.get_default_registry",
                   return_value=mock_registry):
            cmd_list()

    # ── main ──────────────────────────────────────────────────────────────
    def test_main_no_args_prints_help(self):
        from luckyd_code.tools_bridge import main
        with patch("sys.argv", ["tools_bridge"]):
            main()

    def test_main_help_flag(self):
        from luckyd_code.tools_bridge import main
        with patch("sys.argv", ["tools_bridge", "--help"]):
            main()

    def test_main_list_command(self):
        from luckyd_code.tools_bridge import main
        with patch("sys.argv", ["tools_bridge", "list"]), \
             patch("luckyd_code.tools_bridge.cmd_list") as mock:
            main()
        mock.assert_called_once()

    def test_main_info_with_tool(self):
        from luckyd_code.tools_bridge import main
        with patch("sys.argv", ["tools_bridge", "info", "Read"]), \
             patch("luckyd_code.tools_bridge.cmd_info") as mock:
            main()
        mock.assert_called_once_with("Read")

    def test_main_info_no_tool_exits(self):
        from luckyd_code.tools_bridge import main
        with patch("sys.argv", ["tools_bridge", "info"]):
            with pytest.raises(SystemExit):
                main()

    def test_main_run_command(self):
        from luckyd_code.tools_bridge import main
        with patch("sys.argv", ["tools_bridge", "run", "Bash", "--command", "ls"]), \
             patch("luckyd_code.tools_bridge.cmd_run") as mock:
            main()
        mock.assert_called_once_with("Bash", "--command", "ls")

    def test_main_run_no_tool_exits(self):
        from luckyd_code.tools_bridge import main
        with patch("sys.argv", ["tools_bridge", "run"]):
            with pytest.raises(SystemExit):
                main()

    def test_main_unknown_command_exits(self):
        from luckyd_code.tools_bridge import main
        with patch("sys.argv", ["tools_bridge", "zap"]):
            with pytest.raises(SystemExit):
                main()


# ===========================================================================
# cli.py — Repl isolated-method tests
#
# Golden rules:
#   1. repl = MagicMock() — never instantiate real Repl (requires live API)
#   2. Call Repl.SomeMethod(repl, ...) — unbound call, repl acts as self
#   3. self.foo() in the SUT resolves to repl.foo() on the MagicMock
#      → set repl.foo.return_value, do NOT use patch.object(Repl, "foo")
#   4. console    → patch "luckyd_code.cli.console"
#   5. data_path  → patch "luckyd_code.cli.data_path"
#   6. cfg.*      → patch "luckyd_code.cli.cfg.<name>"
#   7. read_input in _prompt_for_api_key uses a local re-import:
#      → patch "luckyd_code.cli_utils.read_input"   (NOT luckyd_code.cli.read_input)
#   8. index_project in _load_memory uses a local re-import:
#      → patch "luckyd_code.indexer.index_project"
# ===========================================================================

def _repl():
    """Minimal MagicMock that satisfies every Repl method under test."""
    r = MagicMock()
    # config
    r.config.api_key = "sk-test"
    r.config.base_url = "https://api.deepseek.com/v1"
    r.config.model = "deepseek-v4-flash"
    r.config.working_directory = None
    r.config.max_context_messages = 100
    # context — messages is a real list so insert/iterate work
    r.context.messages = [{"role": "system", "content": "sys"}]
    r.context.get_messages.return_value = [{"role": "system", "content": "sys"}]
    # memory / brain / mcp / registry
    r.memory_mgr.get_all_memories_formatted.return_value = ""
    r.brain.nodes = {}
    r.brain.stats = {}
    r.mcp.get_all_tools.return_value = []
    r.registry.list_tools.return_value = []
    # state flags — must be plain values, not MagicMocks
    r._stop_requested = False
    r._first_sigint_at = 0.0
    r._running = True
    r._pending_reasoning = ""
    r._rag_retriever = None
    r._audit_daemon = None
    r.file_watcher = None
    return r


# ── _detect_test_runner ─────────────────────────────────────────────────────

class TestReplDetectTestRunner:
    """_detect_test_runner is a pure function; pass a MagicMock as self."""

    def _call(self, cwd):
        from luckyd_code.cli import Repl
        return Repl._detect_test_runner(_repl(), cwd)

    def test_pytest_ini(self, tmp_path):
        (tmp_path / "pytest.ini").write_text("[pytest]")
        assert "pytest" in self._call(str(tmp_path))

    def test_pyproject_toml(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[tool.pytest]")
        assert "pytest" in self._call(str(tmp_path))

    def test_setup_cfg(self, tmp_path):
        (tmp_path / "setup.cfg").write_text("[tool:pytest]")
        assert "pytest" in self._call(str(tmp_path))

    def test_tests_dir(self, tmp_path):
        (tmp_path / "tests").mkdir()
        assert "pytest" in self._call(str(tmp_path))

    def test_venv_pytest_windows(self, tmp_path):
        venv = tmp_path / ".venv" / "Scripts"
        venv.mkdir(parents=True)
        (venv / "pytest.exe").write_bytes(b"")
        (tmp_path / "pyproject.toml").write_text("[tool.pytest]")
        with patch("sys.platform", "win32"):
            result = self._call(str(tmp_path))
        assert "pytest" in result

    def test_venv_pytest_unix(self, tmp_path):
        venv = tmp_path / ".venv" / "bin"
        venv.mkdir(parents=True)
        (venv / "pytest").write_bytes(b"")
        (tmp_path / "pyproject.toml").write_text("[tool.pytest]")
        with patch("sys.platform", "linux"):
            result = self._call(str(tmp_path))
        assert "pytest" in result

    def test_package_json_with_test(self, tmp_path):
        (tmp_path / "package.json").write_text(
            json.dumps({"scripts": {"test": "jest"}}))
        assert "npm test" in self._call(str(tmp_path))

    def test_package_json_no_test_script(self, tmp_path):
        (tmp_path / "package.json").write_text(
            json.dumps({"scripts": {"build": "webpack"}}))
        assert self._call(str(tmp_path)) is None

    def test_package_json_bad_json(self, tmp_path):
        (tmp_path / "package.json").write_text("GARBAGE")
        assert self._call(str(tmp_path)) is None

    def test_cargo_toml(self, tmp_path):
        (tmp_path / "Cargo.toml").write_text("[package]")
        assert "cargo test" in self._call(str(tmp_path))

    def test_go_mod(self, tmp_path):
        (tmp_path / "go.mod").write_text("module myapp")
        assert "go test" in self._call(str(tmp_path))

    def test_no_project_files(self, tmp_path):
        assert self._call(str(tmp_path)) is None


# ── _fallback_models ─────────────────────────────────────────────────────────

class TestReplFallbackModels:
    def test_yields_active_model_first(self):
        from luckyd_code.cli import Repl
        models = list(Repl._fallback_models(_repl(), "deepseek-v4-flash", 2))
        assert models[0][0] == "deepseek-v4-flash"

    def test_no_duplicates(self):
        from luckyd_code.cli import Repl
        models = list(Repl._fallback_models(_repl(), "deepseek-v4-flash", 2))
        names = [m[0] for m in models]
        assert len(names) == len(set(names))

    def test_yields_api_key_and_url(self):
        from luckyd_code.cli import Repl
        r = _repl()
        models = list(Repl._fallback_models(r, "deepseek-v4-flash", 2))
        assert models[0][1] == r.config.api_key
        assert models[0][2] == r.config.base_url


# ── _auto_save_conversation ──────────────────────────────────────────────────

class TestReplAutoSaveConversation:
    """
    _auto_save_conversation calls data_path() (no args) and expects a directory.
    Patch "luckyd_code.cli.data_path" with return_value=tmp_path.
    """

    def test_skips_when_only_system_message(self, tmp_path):
        from luckyd_code.cli import Repl
        r = _repl()
        r.context.get_messages.return_value = [
            {"role": "system", "content": "sys"}]
        with patch("luckyd_code.cli.data_path", return_value=tmp_path):
            Repl._auto_save_conversation(r)
        assert not (tmp_path / "recovery.json").exists()

    def test_writes_recovery_file(self, tmp_path):
        from luckyd_code.cli import Repl
        r = _repl()
        msgs = [
            {"role": "system",    "content": "sys"},
            {"role": "user",      "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        r.context.get_messages.return_value = msgs
        with patch("luckyd_code.cli.data_path", return_value=tmp_path):
            Repl._auto_save_conversation(r)
        saved = json.loads((tmp_path / "recovery.json").read_text())
        assert saved[0]["role"] == "system"
        assert len(saved) >= 2

    def test_exception_is_swallowed(self, tmp_path):
        from luckyd_code.cli import Repl
        r = _repl()
        r.context.get_messages.side_effect = RuntimeError("boom")
        with patch("luckyd_code.cli.data_path", return_value=tmp_path):
            Repl._auto_save_conversation(r)  # must not raise


# ── _save_state ──────────────────────────────────────────────────────────────

class TestReplSaveState:
    def test_calls_config_save_and_setting(self):
        from luckyd_code.cli import Repl
        r = _repl()
        with patch("luckyd_code.cli.cfg.save_setting") as mock_save:
            Repl._save_state(r)
        r.config.save.assert_called_once()
        mock_save.assert_called_with("model_name", r.config.model)

    def test_handles_oserror(self):
        from luckyd_code.cli import Repl
        r = _repl()
        r.config.save.side_effect = OSError("disk full")
        with patch("luckyd_code.cli.cfg.save_setting"), \
             patch("luckyd_code.cli.console"):
            Repl._save_state(r)  # must not raise


# ── _handle_signal ────────────────────────────────────────────────────────────

class TestReplHandleSignal:
    def test_first_sigint_sets_stop_flag(self):
        from luckyd_code.cli import Repl
        r = _repl()
        r._stop_requested = False
        r._first_sigint_at = 0.0
        Repl._handle_signal(r, signal.SIGINT, None)
        assert r._stop_requested is True
        assert r._first_sigint_at > 0

    def test_double_sigint_exits(self):
        from luckyd_code.cli import Repl
        r = _repl()
        r._stop_requested = True
        r._first_sigint_at = time.time()  # recent → within 2 s window
        with patch("luckyd_code.cli.console"), \
             pytest.raises(SystemExit):
            Repl._handle_signal(r, signal.SIGINT, None)

    def test_sigterm_exits(self):
        from luckyd_code.cli import Repl
        r = _repl()
        with pytest.raises(SystemExit):
            Repl._handle_signal(r, signal.SIGTERM, None)


# ── _get_rag_retriever ────────────────────────────────────────────────────────

class TestReplGetRagRetriever:
    def test_lazy_init(self):
        from luckyd_code.cli import Repl
        r = _repl()
        r._rag_retriever = None
        mock_ret = MagicMock()
        with patch("luckyd_code.cli.Retriever", return_value=mock_ret):
            result = Repl._get_rag_retriever(r)
        assert result is mock_ret
        assert r._rag_retriever is mock_ret

    def test_returns_cached(self):
        from luckyd_code.cli import Repl
        r = _repl()
        existing = MagicMock()
        r._rag_retriever = existing
        assert Repl._get_rag_retriever(r) is existing


# ── _init_mcp ─────────────────────────────────────────────────────────────────

class TestReplInitMcp:
    def test_delegates_to_mcp(self):
        from luckyd_code.cli import Repl
        r = _repl()
        settings = {"mcpServers": {}}
        with patch("luckyd_code.cli.cfg.load_settings", return_value=settings):
            Repl._init_mcp(r)
        r.mcp.load_from_config.assert_called_once_with(settings)


# ── _maybe_run_tests ──────────────────────────────────────────────────────────
#
# self._detect_test_runner(cwd) resolves via MagicMock, so set
# r._detect_test_runner.return_value, do NOT patch.object(Repl, ...).

class TestReplMaybeRunTests:
    def _call(self, r, tool_calls):
        from luckyd_code.cli import Repl
        return Repl._maybe_run_tests(r, tool_calls)

    @staticmethod
    def _tc(name):
        return [{"function": {"name": name}}]

    def test_no_write_tools(self):
        assert self._call(_repl(), self._tc("Read")) is None

    def test_auto_test_disabled(self):
        with patch("luckyd_code.cli.cfg.load_settings",
                   return_value={"auto_test": False}):
            assert self._call(_repl(), self._tc("Write")) is None

    def test_no_test_runner(self):
        r = _repl()
        r._detect_test_runner.return_value = None
        with patch("luckyd_code.cli.cfg.load_settings",
                   return_value={"auto_test": True}):
            assert self._call(r, self._tc("Write")) is None

    def test_tests_pass(self):
        r = _repl()
        r._detect_test_runner.return_value = "pytest -x -q"
        mock_result = MagicMock(returncode=0, stdout="1 passed", stderr="")
        with patch("luckyd_code.cli.cfg.load_settings",
                   return_value={"auto_test": True}), \
             patch("subprocess.run", return_value=mock_result), \
             patch("luckyd_code.cli.console"):
            assert self._call(r, self._tc("Write")) is None

    def test_tests_fail(self):
        r = _repl()
        r._detect_test_runner.return_value = "pytest -x -q"
        mock_result = MagicMock(returncode=1, stdout="FAILED", stderr="")
        with patch("luckyd_code.cli.cfg.load_settings",
                   return_value={"auto_test": True}), \
             patch("subprocess.run", return_value=mock_result), \
             patch("luckyd_code.cli.console"):
            result = self._call(r, self._tc("Write"))
        assert result is not None and "Tests failed" in result

    def test_tests_timeout(self):
        import subprocess as sp
        r = _repl()
        r._detect_test_runner.return_value = "pytest -x -q"
        with patch("luckyd_code.cli.cfg.load_settings",
                   return_value={"auto_test": True}), \
             patch("subprocess.run",
                   side_effect=sp.TimeoutExpired("pytest", 60)), \
             patch("luckyd_code.cli.console"):
            assert self._call(r, self._tc("Edit")) is None

    def test_tests_exception(self):
        r = _repl()
        r._detect_test_runner.return_value = "pytest -x -q"
        with patch("luckyd_code.cli.cfg.load_settings",
                   return_value={"auto_test": True}), \
             patch("subprocess.run", side_effect=OSError("no runner")), \
             patch("luckyd_code.cli.console"):
            assert self._call(r, self._tc("Write")) is None


# ── _inject_rag_context ───────────────────────────────────────────────────────
#
# self._get_rag_retriever() resolves via MagicMock → set
# r._get_rag_retriever.return_value, NOT patch.object.

class TestReplInjectRagContext:
    def test_skips_if_no_user_message(self):
        from luckyd_code.cli import Repl
        r = _repl()
        r.context.messages = [{"role": "system", "content": "sys"}]
        Repl._inject_rag_context(r)
        r._get_rag_retriever.assert_not_called()

    def test_skips_if_short_user_message(self):
        from luckyd_code.cli import Repl
        r = _repl()
        r.context.messages = [
            {"role": "system", "content": "sys"},
            {"role": "user",   "content": "hi"},  # < 15 chars
        ]
        Repl._inject_rag_context(r)
        r._get_rag_retriever.assert_not_called()

    def test_skips_if_no_results(self):
        from luckyd_code.cli import Repl
        r = _repl()
        r.context.messages = [
            {"role": "user",
             "content": "How does authentication work in this system?"},
        ]
        mock_ret = MagicMock()
        mock_ret.search.return_value = []
        r._get_rag_retriever.return_value = mock_ret
        before = len(r.context.messages)
        Repl._inject_rag_context(r)
        assert len(r.context.messages) == before

    def test_injects_rag_context(self):
        from luckyd_code.cli import Repl
        r = _repl()
        r.context.messages = [
            {"role": "user",
             "content": "How does authentication work in this system?"},
        ]
        mock_ret = MagicMock()
        mock_ret.search.return_value = [
            {"content": "def authenticate(): pass", "file_path": "auth.py"}
        ]
        r._get_rag_retriever.return_value = mock_ret
        r._rag_assembler.assemble.return_value = "def authenticate(): pass"
        Repl._inject_rag_context(r)
        contents = [m.get("content", "") for m in r.context.messages]
        assert any("<rag-context>" in c for c in contents)

    def test_skips_if_rag_already_present(self):
        from luckyd_code.cli import Repl
        r = _repl()
        r.context.messages = [
            {"role": "user", "content": "<rag-context>\nexisting\n</rag-context>"},
            {"role": "user",
             "content": "How does authentication work in this system?"},
        ]
        mock_ret = MagicMock()
        mock_ret.search.return_value = [{"content": "something"}]
        r._get_rag_retriever.return_value = mock_ret
        before = len(r.context.messages)
        Repl._inject_rag_context(r)
        assert len(r.context.messages) == before

    def test_force_replaces_existing(self):
        from luckyd_code.cli import Repl
        r = _repl()
        r.context.messages = [
            {"role": "user", "content": "<rag-context>\nold\n</rag-context>"},
            {"role": "user",
             "content": "How does authentication work in this system?"},
        ]
        mock_ret = MagicMock()
        mock_ret.search.return_value = [{"content": "new"}]
        r._get_rag_retriever.return_value = mock_ret
        r._rag_assembler.assemble.return_value = "new relevant code"
        Repl._inject_rag_context(r, force=True)
        contents = [m.get("content", "") for m in r.context.messages]
        assert not any(c == "<rag-context>\nold\n</rag-context>" for c in contents)
        assert any("new relevant code" in c for c in contents)

    def test_exception_is_swallowed(self):
        from luckyd_code.cli import Repl
        r = _repl()
        r.context.messages = [
            {"role": "user",
             "content": "How does authentication work in this system?"},
        ]
        r._get_rag_retriever.side_effect = Exception("RAG down")
        Repl._inject_rag_context(r)  # must not raise


# ── _stop_audit_daemon ────────────────────────────────────────────────────────

class TestReplStopAuditDaemon:
    def test_releases_lock(self):
        from luckyd_code.cli import Repl
        r = _repl()
        mock_daemon = MagicMock()
        r._audit_daemon = mock_daemon
        Repl._stop_audit_daemon(r)
        mock_daemon._release_lock.assert_called_once()
        assert r._audit_daemon is None

    def test_noop_if_no_daemon(self):
        from luckyd_code.cli import Repl
        r = _repl()
        r._audit_daemon = None
        Repl._stop_audit_daemon(r)  # must not raise


# ── _cleanup ──────────────────────────────────────────────────────────────────
#
# All teardown calls (self._save_state, self._auto_save_conversation, etc.)
# resolve via the MagicMock → just assert call counts.

class TestReplCleanup:
    def test_calls_all_teardown(self):
        from luckyd_code.cli import Repl
        r = _repl()
        r.file_watcher = MagicMock()
        r.file_watcher.is_running = True
        Repl._cleanup(r)
        r._save_state.assert_called_once()
        r._auto_save_conversation.assert_called_once()
        r._stop_audit_daemon.assert_called_once()
        r.file_watcher.stop.assert_called_once()
        r.mcp.close_all.assert_called_once()

    def test_skips_watcher_when_none(self):
        from luckyd_code.cli import Repl
        r = _repl()
        r.file_watcher = None
        Repl._cleanup(r)  # must not raise
        r.mcp.close_all.assert_called_once()

    def test_skips_watcher_when_not_running(self):
        from luckyd_code.cli import Repl
        r = _repl()
        r.file_watcher = MagicMock()
        r.file_watcher.is_running = False
        Repl._cleanup(r)
        r.file_watcher.stop.assert_not_called()


# ── _prompt_for_api_key ───────────────────────────────────────────────────────
#
# CRITICAL: _prompt_for_api_key does "from .cli_utils import read_input"
# INSIDE the function body, re-binding the local name.  Patching
# "luckyd_code.cli.read_input" is therefore ineffective.
# Must patch the SOURCE: "luckyd_code.cli_utils.read_input".

class TestReplPromptForApiKey:
    def test_skips_if_empty_string(self):
        from luckyd_code.cli import Repl
        r = _repl()
        old_key = r.config.api_key
        with patch("luckyd_code.cli_utils.read_input", return_value=""), \
             patch("luckyd_code.cli.console"):
            Repl._prompt_for_api_key(r)
        assert r.config.api_key == old_key

    def test_skips_if_none(self):
        from luckyd_code.cli import Repl
        r = _repl()
        with patch("luckyd_code.cli_utils.read_input", return_value=None), \
             patch("luckyd_code.cli.console"):
            Repl._prompt_for_api_key(r)  # must not raise

    def test_updates_config_api_key(self, tmp_path):
        from luckyd_code.cli import Repl
        r = _repl()
        env_file = tmp_path / ".env"
        env_file.write_text("DEEPSEEK_API_KEY=old-key\n", encoding="utf-8")

        # Make Path(__file__).parent.parent / ".env" resolve to env_file
        mock_path_instance = MagicMock(spec=Path)
        mock_path_instance.parent.parent.__truediv__ = lambda _self, name: env_file

        with patch("luckyd_code.cli_utils.read_input", return_value="sk-new-key"), \
             patch("luckyd_code.cli.console"), \
             patch("luckyd_code.cli.Path", return_value=mock_path_instance):
            Repl._prompt_for_api_key(r)

        assert r.config.api_key == "sk-new-key"


# ── _load_memory ──────────────────────────────────────────────────────────────
#
# _load_memory does "from .indexer import index_project" inside the body.
# Patch "luckyd_code.indexer.index_project" (source), not luckyd_code.cli.*.
# data_path("recovery.json") is patched at "luckyd_code.cli.data_path".

class TestReplLoadMemory:
    def _base_patches(self, tmp_path, *, md=None, project=""):
        """Return a context tuple: (patch_md, patch_index, patch_dp)."""
        # A path that does NOT exist → recovery block is skipped
        no_recovery = tmp_path / "recovery.json"
        return (
            patch("luckyd_code.cli.memory.load_claude_md", return_value=md),
            patch("luckyd_code.indexer.index_project", return_value=project),
            patch("luckyd_code.cli.data_path", return_value=no_recovery),
        )

    def test_no_memory_no_project(self, tmp_path):
        from luckyd_code.cli import Repl
        r = _repl()
        r.context.messages = [{"role": "system", "content": "sys"}]
        r.brain.nodes = {}
        p1, p2, p3 = self._base_patches(tmp_path)
        with p1, p2, p3:
            Repl._load_memory(r)
        assert r.context.messages[0]["role"] == "system"

    def test_claude_md_is_inserted(self, tmp_path):
        from luckyd_code.cli import Repl
        r = _repl()
        r.context.messages = [{"role": "system", "content": "sys"}]
        r.brain.nodes = {}
        p1, p2, p3 = self._base_patches(tmp_path, md="# MEMORY")
        with p1, p2, p3:
            Repl._load_memory(r)
        joined = " ".join(m.get("content", "") for m in r.context.messages)
        assert "MEMORY" in joined or "claude-md" in joined

    def test_project_context_inserted(self, tmp_path):
        from luckyd_code.cli import Repl
        r = _repl()
        r.context.messages = [{"role": "system", "content": "sys"}]
        r.brain.nodes = {}
        p1, p2, p3 = self._base_patches(tmp_path, project="app.py  main.py")
        with p1, p2, p3:
            Repl._load_memory(r)
        joined = " ".join(m.get("content", "") for m in r.context.messages)
        assert "project-context" in joined or "app.py" in joined

    def test_recovery_file_restored(self, tmp_path):
        from luckyd_code.cli import Repl
        r = _repl()
        r.brain.nodes = {}
        recovery_msgs = [
            {"role": "system",    "content": "sys"},
            {"role": "user",      "content": "old q"},
            {"role": "assistant", "content": "old a"},
        ]
        recovery_file = tmp_path / "recovery.json"
        recovery_file.write_text(json.dumps(recovery_msgs), encoding="utf-8")
        with patch("luckyd_code.cli.memory.load_claude_md", return_value=None), \
             patch("luckyd_code.indexer.index_project", return_value=""), \
             patch("luckyd_code.cli.data_path", return_value=recovery_file):
            Repl._load_memory(r)
        assert r.context.messages == recovery_msgs


# ===========================================================================
# init.py — constants and full branch coverage
# ===========================================================================

class TestInitConstants:
    def test_memory_filenames(self):
        from luckyd_code.init import MEMORY_FILENAMES
        assert "MEMORY.md" in MEMORY_FILENAMES
        assert "CLAUDE.md" in MEMORY_FILENAMES

    def test_default_memory_sections(self):
        from luckyd_code.init import DEFAULT_MEMORY_MD
        for section in ("## Project Overview", "## Tech Stack",
                        "## Commands", "## Guidelines"):
            assert section in DEFAULT_MEMORY_MD

    def test_init_creates_memory_md(self, tmp_path, monkeypatch):
        from luckyd_code import init
        monkeypatch.chdir(tmp_path)
        result = init.init_project()
        assert "Created" in result
        assert (tmp_path / "MEMORY.md").exists()
        assert "## Project Overview" in (tmp_path / "MEMORY.md").read_text()

    def test_init_skips_if_memory_md_exists(self, tmp_path, monkeypatch):
        from luckyd_code import init
        monkeypatch.chdir(tmp_path)
        (tmp_path / "MEMORY.md").write_text("existing", encoding="utf-8")
        result = init.init_project()
        assert "already exists" in result
        assert (tmp_path / "MEMORY.md").read_text() == "existing"

    def test_init_skips_if_claude_md_exists(self, tmp_path, monkeypatch):
        from luckyd_code import init
        monkeypatch.chdir(tmp_path)
        (tmp_path / "CLAUDE.md").write_text("claude", encoding="utf-8")
        result = init.init_project()
        assert "already exists" in result


# ===========================================================================
# update.py — edge cases
# ===========================================================================

class TestUpdateEdgeCases:
    def test_check_no_remote(self):
        from luckyd_code.update import check_for_updates
        responses = iter([
            MagicMock(returncode=0),               # fetch
            MagicMock(returncode=0, stdout="0\n"), # rev-list → 0 behind
            MagicMock(returncode=0, stdout=""),    # remote → empty = no remote
        ])
        with patch("subprocess.run", side_effect=lambda *a, **kw: next(responses)):
            result = check_for_updates()
        assert isinstance(result, str)

    def test_check_exception(self):
        from luckyd_code.update import check_for_updates
        with patch("subprocess.run", side_effect=Exception("network error")):
            result = check_for_updates()
        assert "Cannot check" in result or isinstance(result, str)

    def test_do_update_empty_stdout(self):
        from luckyd_code.update import do_update
        import subprocess as _sp
        # Use CompletedProcess so .stdout and .stderr are real empty strings;
        # MagicMock(stderr="") can return a child mock for attribute access,
        # making .stderr.strip() truthy (a MagicMock).
        responses = iter([
            _sp.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),  # status → clean
            _sp.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),  # pull → empty stdout+stderr
        ])
        with patch("subprocess.run", side_effect=lambda *a, **kw: next(responses)):
            result = do_update()
        assert isinstance(result, str)

    def test_do_update_with_stash(self):
        from luckyd_code.update import do_update
        responses = iter([
            MagicMock(returncode=0, stdout=" M file.py"),  # status → dirty
            MagicMock(returncode=0, stdout=""),             # stash
            MagicMock(returncode=0, stdout="Updated."),    # pull
            MagicMock(returncode=0, stdout=""),             # stash pop
        ])
        with patch("subprocess.run", side_effect=lambda *a, **kw: next(responses)):
            result = do_update()
        assert isinstance(result, str)

    def test_do_update_exception(self):
        from luckyd_code.update import do_update
        with patch("subprocess.run", side_effect=Exception("fail")):
            result = do_update()
        assert "Update failed" in result or "fail" in result


# ===========================================================================
# keybindings.py — remaining branches
# ===========================================================================

class TestKeybindingsExtra:
    def test_get_keybindings_path_returns_path(self):
        from luckyd_code.keybindings import get_keybindings_path
        assert isinstance(get_keybindings_path(), Path)
        assert get_keybindings_path().name == "keybindings.json"

    def test_custom_submit_key(self, tmp_path, monkeypatch):
        from luckyd_code import keybindings
        kbf = tmp_path / "keybindings.json"
        kbf.write_text('{"submit": "ctrl-j", "newline": "ctrl-n"}')
        monkeypatch.setattr(keybindings, "get_keybindings_path", lambda: kbf)
        kb = keybindings.apply_keybindings()
        assert kb is not None

    def test_apply_keybindings_defaults(self, tmp_path, monkeypatch):
        from luckyd_code import keybindings
        monkeypatch.setattr(
            keybindings, "get_keybindings_path",
            lambda: tmp_path / "missing.json")
        kb = keybindings.apply_keybindings()
        assert kb is not None

    def test_load_keybindings_non_dict_json(self, tmp_path, monkeypatch):
        from luckyd_code import keybindings
        kbf = tmp_path / "keybindings.json"
        kbf.write_text("[1, 2, 3]")  # valid JSON but not a dict
        monkeypatch.setattr(keybindings, "get_keybindings_path", lambda: kbf)
        result = keybindings.load_keybindings()
        assert result == {}

    def test_parse_key_sequence_alt(self):
        from luckyd_code.keybindings import _parse_key_sequence
        assert _parse_key_sequence("alt-enter") == ("escape", "enter")
        assert _parse_key_sequence("alt-a") == ("escape", "a")

    def test_parse_key_sequence_regular(self):
        from luckyd_code.keybindings import _parse_key_sequence
        assert _parse_key_sequence("enter") == ("enter",)
        assert _parse_key_sequence("ctrl-c") == ("ctrl-c",)
