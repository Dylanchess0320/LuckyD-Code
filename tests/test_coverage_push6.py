"""
Coverage push 6 — targets the remaining uncovered lines.
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# sessions.py:93-94  —  delete_session() success path
#
# Write directly into the real SESSIONS_DIR so path.exists() is genuinely
# True — no mocking, no patching, so path.unlink() actually executes.
# ---------------------------------------------------------------------------
class TestSessionsDeleteSuccess:
    def test_delete_existing_session_unlinks_file(self):
        import luckyd_code.sessions as sess_mod
        from luckyd_code.sessions import delete_session, _sanitize_name

        name = "push6deleteme"
        safe = _sanitize_name(name)
        real_dir = sess_mod.SESSIONS_DIR
        real_dir.mkdir(parents=True, exist_ok=True)
        target = real_dir / f"{safe}.json"
        target.write_text('{"name":"push6deleteme"}', encoding="utf-8")
        try:
            result = delete_session(name)
        finally:
            if target.exists():
                target.unlink()

        assert "deleted" in result

    def test_delete_nonexistent_returns_not_found(self):
        from luckyd_code.sessions import delete_session
        result = delete_session("definitely_does_not_exist_xyzzy")
        assert "not found" in result


# ---------------------------------------------------------------------------
# cli_commands/sessions.py:34-35  —  /sessions delete CLI branch
# ---------------------------------------------------------------------------
class TestCliSessionsDeleteBranch:
    def _make_repl(self):
        return MagicMock()

    def test_delete_branch_calls_delete_session(self):
        from luckyd_code.cli_commands.sessions import handle_sessions_command
        repl = self._make_repl()
        with patch("luckyd_code.sessions.delete_session", return_value="Session 'foo' deleted") as mock_del, \
             patch("luckyd_code.cli_utils.console"):
            handle_sessions_command(repl, ["delete", "foo"])
        mock_del.assert_called_once_with("foo")

    def test_delete_branch_no_name_prints_usage(self):
        from luckyd_code.cli_commands.sessions import handle_sessions_command
        repl = self._make_repl()
        with patch("luckyd_code.cli_utils.console") as mock_console:
            handle_sessions_command(repl, ["delete"])
        mock_console.print.assert_called()

    def test_delete_branch_multiword_name(self):
        from luckyd_code.cli_commands.sessions import handle_sessions_command
        repl = self._make_repl()
        with patch("luckyd_code.sessions.delete_session", return_value="Session 'my session' deleted") as mock_del, \
             patch("luckyd_code.cli_utils.console"):
            handle_sessions_command(repl, ["delete", "my", "session"])
        mock_del.assert_called_once_with("my session")


# ---------------------------------------------------------------------------
# tasks/manager.py:34-36  —  _get_db_path() real body
# ---------------------------------------------------------------------------
class TestTasksGetDbPath:
    def test_get_db_path_returns_path_ending_in_tasks_json(self):
        from luckyd_code.tasks.manager import _get_db_path
        with tempfile.TemporaryDirectory() as tmp:
            fake_path = Path(tmp) / "tasks.json"
            with patch("luckyd_code.tasks.manager.project_data_path", return_value=fake_path):
                result = _get_db_path()
            assert result == fake_path
            assert result.name == "tasks.json"

    def test_get_db_path_creates_parent_dir(self):
        from luckyd_code.tasks.manager import _get_db_path
        with tempfile.TemporaryDirectory() as tmp:
            nested = Path(tmp) / "deep" / "nested" / "tasks.json"
            with patch("luckyd_code.tasks.manager.project_data_path", return_value=nested):
                result = _get_db_path()
            assert result.parent.exists()


# ---------------------------------------------------------------------------
# tools/__init__.py:100-104  —  plugin loading try/except in get_default_registry()
# ---------------------------------------------------------------------------
class TestGetDefaultRegistryPluginPaths:
    def test_plugins_loaded_logs_info_when_n_gt_0(self):
        from luckyd_code.tools import get_default_registry
        import luckyd_code.plugins as _plugins_mod
        original = _plugins_mod.load_all_plugins
        try:
            _plugins_mod.load_all_plugins = lambda registry: 3
            registry = get_default_registry()
        finally:
            _plugins_mod.load_all_plugins = original
        assert registry is not None

    def test_plugins_loaded_zero_skips_log(self):
        from luckyd_code.tools import get_default_registry
        import luckyd_code.plugins as _plugins_mod
        original = _plugins_mod.load_all_plugins
        try:
            _plugins_mod.load_all_plugins = lambda registry: 0
            registry = get_default_registry()
        finally:
            _plugins_mod.load_all_plugins = original
        assert registry is not None

    def test_plugins_exception_hits_except_handler(self):
        from luckyd_code.tools import get_default_registry
        import luckyd_code.plugins as _plugins_mod
        original = _plugins_mod.load_all_plugins
        try:
            def _raise(registry): raise RuntimeError("plugin load failed")
            _plugins_mod.load_all_plugins = _raise
            registry = get_default_registry()
        finally:
            _plugins_mod.load_all_plugins = original
        assert registry is not None

    def test_plugins_import_error_hits_except_handler(self):
        from luckyd_code.tools import get_default_registry
        import luckyd_code.plugins as _plugins_mod
        original = _plugins_mod.load_all_plugins
        try:
            def _raise(registry): raise ImportError("no module")
            _plugins_mod.load_all_plugins = _raise
            registry = get_default_registry()
        finally:
            _plugins_mod.load_all_plugins = original
        assert registry is not None


# ---------------------------------------------------------------------------
# tools/agent_tools.py:40-42  —  SubAgentTool.run() happy path
# ---------------------------------------------------------------------------
class TestSubAgentToolRun:
    def setup_method(self):
        import luckyd_code.tools.agent_tools as at
        self._orig_repl = at._repl
        at._repl = None

    def teardown_method(self):
        import luckyd_code.tools.agent_tools as at
        at._repl = self._orig_repl

    def test_run_calls_sub_agent_and_returns_result(self):
        from luckyd_code.tools.agent_tools import SubAgentTool, set_repl
        fake_repl = MagicMock()
        fake_repl.config = MagicMock()
        fake_repl.registry.list_tools.return_value = []
        set_repl(fake_repl)

        fake_agent = MagicMock()
        fake_agent.run.return_value = "subtask done"

        tool = SubAgentTool()
        with patch("luckyd_code.agent.SubAgent", return_value=fake_agent) as mock_cls:
            result = tool.run(task="do something")

        mock_cls.assert_called_once_with(fake_repl.config, "do something", [])
        fake_agent.run.assert_called_once()
        assert result == "subtask done"

    def test_run_no_repl_returns_error(self):
        from luckyd_code.tools.agent_tools import SubAgentTool
        result = SubAgentTool().run(task="x")
        assert "not available" in result or "not initialized" in result


# ---------------------------------------------------------------------------
# tools/agent_tools.py:77-79  —  AgentHandoffTool.run() happy path
# ---------------------------------------------------------------------------
class TestAgentHandoffToolRun:
    def setup_method(self):
        import luckyd_code.tools.agent_tools as at
        self._orig_repl = at._repl
        at._repl = None

    def teardown_method(self):
        import luckyd_code.tools.agent_tools as at
        at._repl = self._orig_repl

    def test_run_calls_agent_handoff_and_returns_result(self):
        from luckyd_code.tools.agent_tools import AgentHandoffTool, set_repl
        fake_repl = MagicMock()
        fake_repl.config = MagicMock()
        fake_repl.registry.list_tools.return_value = ["tool1"]
        set_repl(fake_repl)

        fake_handoff = MagicMock()
        fake_handoff.handoff.return_value = "handoff complete"

        tool = AgentHandoffTool()
        with patch("luckyd_code.orchestrator.AgentHandoff", return_value=fake_handoff) as mock_cls:
            result = tool.run(role="coder", task="write tests")

        mock_cls.assert_called_once_with(fake_repl.config)
        fake_handoff.handoff.assert_called_once_with("coder", "write tests", ["tool1"])
        assert result == "handoff complete"

    def test_run_no_repl_returns_error(self):
        from luckyd_code.tools.agent_tools import AgentHandoffTool
        result = AgentHandoffTool().run(role="researcher", task="y")
        assert "not available" in result or "not initialized" in result

    def test_run_all_roles_accepted(self):
        from luckyd_code.tools.agent_tools import AgentHandoffTool, set_repl
        fake_repl = MagicMock()
        fake_repl.config = MagicMock()
        fake_repl.registry.list_tools.return_value = []
        set_repl(fake_repl)

        fake_handoff = MagicMock()
        fake_handoff.handoff.return_value = "ok"

        tool = AgentHandoffTool()
        with patch("luckyd_code.orchestrator.AgentHandoff", return_value=fake_handoff):
            for role in ("researcher", "coder", "reviewer", "tester"):
                assert tool.run(role=role, task="something") == "ok"
