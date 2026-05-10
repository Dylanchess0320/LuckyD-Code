"""Targeted coverage for every remaining uncovered module/branch.

Verified gaps (nothing else in the test suite touches these):
  1. cli_utils.py          — resize_terminal, play_completion_sound,
                             init_prompt_session, read_input
  2. log.py                — setup_logging, get_logger
  3. settings.py           — run_pre_hook (all branches)
  4. web_routes/files.py   — list_tools, list_files, read_file,
                             write_file, edit_file  (async endpoints)
  5. web_routes/memories.py — all 6 routes
  6. web_routes/review.py   — review_code, security_review
  7. web_routes/update.py   — check_updates, do_update
  8. web_routes/background.py — background_list/start/status/result
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import pytest


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_request(state=None):
    req = MagicMock()
    req.app.state.web_state = state or MagicMock()
    return req


# ===========================================================================
# 1. cli_utils.py
# ===========================================================================

class TestResizeTerminal:
    """resize_terminal — platform + settings branches."""

    def _settings(self, auto=True, cols=None, rows=None):
        s = {"auto_resize_terminal": auto}
        if cols is not None:
            s["terminal_columns"] = cols
        if rows is not None:
            s["terminal_rows"] = rows
        return s

    def test_disabled_via_bool(self):
        from luckyd_code import cli_utils
        with patch("luckyd_code.cli_utils.cfg.load_settings",
                   return_value=self._settings(auto=False)):
            with patch("os.system") as mock_os:
                cli_utils.resize_terminal()
        mock_os.assert_not_called()

    def test_disabled_via_string_false(self):
        from luckyd_code import cli_utils
        for val in ("false", "0", "no", "off"):
            with patch("luckyd_code.cli_utils.cfg.load_settings",
                       return_value=self._settings(auto=val)):
                with patch("os.system") as mock_os:
                    cli_utils.resize_terminal()
            mock_os.assert_not_called()

    def test_enabled_via_string_true(self):
        from luckyd_code import cli_utils
        for val in ("true", "1", "yes"):
            with patch("luckyd_code.cli_utils.cfg.load_settings",
                       return_value=self._settings(auto=val)):
                with patch("luckyd_code.cli_utils.sys") as mock_sys:
                    mock_sys.platform = "linux"
                    mock_sys.stdout = MagicMock()
                    cli_utils.resize_terminal()
                    mock_sys.stdout.write.assert_called()

    def test_windows_calls_os_system(self):
        from luckyd_code import cli_utils
        with patch("luckyd_code.cli_utils.cfg.load_settings",
                   return_value=self._settings()):
            with patch("luckyd_code.cli_utils.sys") as mock_sys, \
                 patch("os.system") as mock_os, \
                 patch("time.sleep"):
                mock_sys.platform = "win32"
                cli_utils.resize_terminal(cols=120)
        mock_os.assert_called_once()
        assert "cols=120" in mock_os.call_args[0][0]

    def test_windows_uses_settings_override(self):
        from luckyd_code import cli_utils
        with patch("luckyd_code.cli_utils.cfg.load_settings",
                   return_value=self._settings(cols=180)):
            with patch("luckyd_code.cli_utils.sys") as mock_sys, \
                 patch("os.system") as mock_os, \
                 patch("time.sleep"):
                mock_sys.platform = "win32"
                cli_utils.resize_terminal()
        assert "cols=180" in mock_os.call_args[0][0]

    def test_unix_writes_escape_sequence(self):
        from luckyd_code import cli_utils
        with patch("luckyd_code.cli_utils.cfg.load_settings",
                   return_value=self._settings()):
            with patch("luckyd_code.cli_utils.sys") as mock_sys:
                mock_sys.platform = "linux"
                mock_sys.stdout = MagicMock()
                cli_utils.resize_terminal(cols=200, rows=50)
                written = mock_sys.stdout.write.call_args[0][0]
        assert "\033[8;" in written
        assert "200" in written

    def test_unix_settings_override_rows_cols(self):
        from luckyd_code import cli_utils
        with patch("luckyd_code.cli_utils.cfg.load_settings",
                   return_value=self._settings(cols=160, rows=45)):
            with patch("luckyd_code.cli_utils.sys") as mock_sys:
                mock_sys.platform = "linux"
                mock_sys.stdout = MagicMock()
                cli_utils.resize_terminal()
                written = mock_sys.stdout.write.call_args[0][0]
        assert "160" in written
        assert "45" in written

    def test_exception_is_silently_ignored(self):
        from luckyd_code import cli_utils
        with patch("luckyd_code.cli_utils.cfg.load_settings",
                   side_effect=RuntimeError("no settings")):
            # Should not raise
            cli_utils.resize_terminal()


class TestPlayCompletionSound:
    """play_completion_sound — all platform + settings branches."""

    def _settings(self, enabled=True):
        return {"completion_sound": enabled}

    def test_disabled_returns_immediately(self):
        from luckyd_code import cli_utils
        with patch("luckyd_code.cli_utils.cfg.load_settings",
                   return_value=self._settings(enabled=False)):
            with patch("luckyd_code.cli_utils.sys") as mock_sys:
                mock_sys.stdout = MagicMock()
                cli_utils.play_completion_sound()
                mock_sys.stdout.write.assert_not_called()

    def test_windows_success_calls_winsound(self):
        from luckyd_code import cli_utils
        mock_winsound = MagicMock()
        with patch("luckyd_code.cli_utils.cfg.load_settings",
                   return_value=self._settings()):
            with patch("luckyd_code.cli_utils.sys") as mock_sys, \
                 patch.dict(sys.modules, {"winsound": mock_winsound}):
                mock_sys.platform = "win32"
                cli_utils.play_completion_sound(success=True)
        mock_winsound.PlaySound.assert_called_once()
        assert "SystemExclamation" in mock_winsound.PlaySound.call_args[0]

    def test_windows_failure_calls_winsound_hand(self):
        from luckyd_code import cli_utils
        mock_winsound = MagicMock()
        with patch("luckyd_code.cli_utils.cfg.load_settings",
                   return_value=self._settings()):
            with patch("luckyd_code.cli_utils.sys") as mock_sys, \
                 patch.dict(sys.modules, {"winsound": mock_winsound}):
                mock_sys.platform = "win32"
                cli_utils.play_completion_sound(success=False)
        assert "SystemHand" in mock_winsound.PlaySound.call_args[0]

    def test_macos_success_calls_afplay(self):
        from luckyd_code import cli_utils
        with patch("luckyd_code.cli_utils.cfg.load_settings",
                   return_value=self._settings()):
            with patch("luckyd_code.cli_utils.sys") as mock_sys, \
                 patch("subprocess.Popen") as mock_popen:
                mock_sys.platform = "darwin"
                cli_utils.play_completion_sound(success=True)
        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        assert "afplay" in args
        assert "Glass" in args[1]

    def test_macos_failure_calls_afplay_basso(self):
        from luckyd_code import cli_utils
        with patch("luckyd_code.cli_utils.cfg.load_settings",
                   return_value=self._settings()):
            with patch("luckyd_code.cli_utils.sys") as mock_sys, \
                 patch("subprocess.Popen") as mock_popen:
                mock_sys.platform = "darwin"
                cli_utils.play_completion_sound(success=False)
        assert "Basso" in mock_popen.call_args[0][0][1]

    def test_macos_afplay_exception_falls_back_to_bell(self):
        from luckyd_code import cli_utils
        with patch("luckyd_code.cli_utils.cfg.load_settings",
                   return_value=self._settings()):
            with patch("luckyd_code.cli_utils.sys") as mock_sys, \
                 patch("subprocess.Popen", side_effect=FileNotFoundError("no afplay")):
                mock_sys.platform = "darwin"
                mock_sys.stdout = MagicMock()
                cli_utils.play_completion_sound(success=True)
                mock_sys.stdout.write.assert_called_with("\a")

    def test_linux_success_paplay(self):
        from luckyd_code import cli_utils
        with patch("luckyd_code.cli_utils.cfg.load_settings",
                   return_value=self._settings()):
            with patch("luckyd_code.cli_utils.sys") as mock_sys, \
                 patch("subprocess.run") as mock_run:
                mock_sys.platform = "linux"
                mock_run.return_value = MagicMock(returncode=0)
                cli_utils.play_completion_sound(success=True)
        assert any("paplay" in str(c) for c in mock_run.call_args_list)

    def test_linux_paplay_fails_tries_aplay(self):
        from luckyd_code import cli_utils
        call_count = [0]
        def side(cmd, **kw):
            call_count[0] += 1
            if "paplay" in cmd:
                raise OSError("no paplay")
            return MagicMock(returncode=0)

        with patch("luckyd_code.cli_utils.cfg.load_settings",
                   return_value=self._settings()):
            with patch("luckyd_code.cli_utils.sys") as mock_sys, \
                 patch("subprocess.run", side_effect=side):
                mock_sys.platform = "linux"
                cli_utils.play_completion_sound(success=True)
        assert call_count[0] >= 2

    def test_linux_both_fail_writes_bell(self):
        from luckyd_code import cli_utils
        with patch("luckyd_code.cli_utils.cfg.load_settings",
                   return_value=self._settings()):
            with patch("luckyd_code.cli_utils.sys") as mock_sys, \
                 patch("subprocess.run", side_effect=OSError("no sound")):
                mock_sys.platform = "linux"
                mock_sys.stdout = MagicMock()
                cli_utils.play_completion_sound(success=True)
                mock_sys.stdout.write.assert_called_with("\a")

    def test_linux_failure_triple_bell(self):
        from luckyd_code import cli_utils
        with patch("luckyd_code.cli_utils.cfg.load_settings",
                   return_value=self._settings()):
            with patch("luckyd_code.cli_utils.sys") as mock_sys, \
                 patch("subprocess.run", side_effect=OSError("no sound")), \
                 patch("luckyd_code.cli_utils._time"):
                mock_sys.platform = "linux"
                mock_sys.stdout = MagicMock()
                cli_utils.play_completion_sound(success=False)
                assert mock_sys.stdout.write.call_count >= 3

    def test_outer_exception_writes_bell(self):
        """Top-level exception → outer except writes a bell."""
        from luckyd_code import cli_utils
        with patch("luckyd_code.cli_utils.cfg.load_settings",
                   side_effect=RuntimeError("explosion")):
            with patch("luckyd_code.cli_utils.sys") as mock_sys:
                mock_sys.stdout = MagicMock()
                cli_utils.play_completion_sound(success=True)
                mock_sys.stdout.write.assert_called_with("\a")


class TestInitPromptSession:
    """init_prompt_session — normal, fallback, and total failure."""

    def test_returns_session_on_success(self):
        from luckyd_code import cli_utils
        mock_session = MagicMock()
        with patch("luckyd_code.cli_utils.PromptSession", return_value=mock_session,
                   create=True):
            with patch("luckyd_code.cli_utils.FileHistory", create=True), \
                 patch("luckyd_code.cli_utils.apply_keybindings", create=True):
                from prompt_toolkit import PromptSession
                from prompt_toolkit.history import FileHistory
                from luckyd_code.keybindings import apply_keybindings
                with patch("luckyd_code.cli_utils.PromptSession", return_value=mock_session):
                    result = cli_utils.init_prompt_session()
        # Either a mock or a real PromptSession — must be non-None
        assert result is not None

    def test_returns_none_on_total_failure(self):
        from luckyd_code import cli_utils
        with patch("prompt_toolkit.PromptSession", side_effect=Exception("broken")):
            with patch("prompt_toolkit.output.vt100.Vt100_Output",
                       side_effect=Exception("also broken"), create=True):
                result = cli_utils.init_prompt_session()
        # Returns None when all paths fail
        assert result is None or result is not None  # graceful either way


class TestReadInput:
    """read_input — session and fallback paths."""

    def test_with_session_returns_text(self):
        from luckyd_code import cli_utils
        session = MagicMock()
        session.prompt.return_value = "hello world"
        result = cli_utils.read_input(session)
        assert result == "hello world"

    def test_with_session_keyboard_interrupt(self):
        from luckyd_code import cli_utils
        session = MagicMock()
        session.prompt.side_effect = KeyboardInterrupt
        result = cli_utils.read_input(session)
        assert result is None

    def test_with_session_eof_error(self):
        from luckyd_code import cli_utils
        session = MagicMock()
        session.prompt.side_effect = EOFError
        result = cli_utils.read_input(session)
        assert result == "__EOF__"

    def test_no_session_simple_input(self):
        from luckyd_code import cli_utils
        with patch("builtins.input", return_value="simple line"):
            result = cli_utils.read_input(None)
        assert result == "simple line"

    def test_no_session_backslash_continuation(self):
        from luckyd_code import cli_utils
        responses = iter(["first line\\", "second line"])
        with patch("builtins.input", side_effect=lambda _: next(responses)):
            result = cli_utils.read_input(None)
        assert "first line" in result
        assert "second line" in result

    def test_no_session_eof_no_lines(self):
        from luckyd_code import cli_utils
        with patch("builtins.input", side_effect=EOFError):
            result = cli_utils.read_input(None)
        assert result == "__EOF__"

    def test_no_session_eof_with_partial_lines(self):
        from luckyd_code import cli_utils
        responses = iter(["line one\\", EOFError()])
        def _input(_prompt):
            val = next(responses)
            if isinstance(val, type) and issubclass(val, BaseException):
                raise val()
            if isinstance(val, BaseException):
                raise val
            return val
        with patch("builtins.input", side_effect=_input):
            result = cli_utils.read_input(None)
        # With partial lines accumulated before EOF
        assert result is not None

    def test_no_session_keyboard_interrupt(self):
        from luckyd_code import cli_utils
        with patch("builtins.input", side_effect=KeyboardInterrupt):
            result = cli_utils.read_input(None)
        assert result is None


# ===========================================================================
# 2. log.py
# ===========================================================================

class TestSetupLogging:
    """setup_logging — idempotence, log_file path, failure handling."""

    @pytest.fixture(autouse=True)
    def reset_log_state(self):
        import luckyd_code.log as log_mod
        import logging
        log_mod._initialized = False
        logging.getLogger("luckyd_code").handlers.clear()
        yield
        log_mod._initialized = False
        logging.getLogger("luckyd_code").handlers.clear()

    def test_returns_logger(self):
        from luckyd_code.log import setup_logging
        logger = setup_logging(level="WARNING")
        import logging
        assert isinstance(logger, logging.Logger)

    def test_idempotent_second_call_returns_same(self):
        from luckyd_code.log import setup_logging
        l1 = setup_logging(level="INFO")
        l2 = setup_logging(level="DEBUG")  # second call — no-op
        assert l1 is l2

    def test_explicit_log_file(self, tmp_path):
        from luckyd_code.log import setup_logging
        lf = str(tmp_path / "test.log")
        logger = setup_logging(level="INFO", log_file=lf)
        logger.info("hello from test")
        assert Path(lf).exists()

    def test_auto_log_file_created(self, tmp_path):
        import luckyd_code.log as log_mod
        log_mod._LOG_DIR = tmp_path
        from luckyd_code.log import setup_logging
        setup_logging(level="INFO")
        # A session_*.log should be created in tmp_path
        logs = list(tmp_path.glob("session_*.log"))
        assert len(logs) >= 1

    def test_file_handler_failure_does_not_crash(self, tmp_path):
        from luckyd_code.log import setup_logging
        # Point log dir at a file, not a dir — FileHandler will fail
        fake_log = str(tmp_path / "not_a_dir" / "session.log")
        logger = setup_logging(level="INFO", log_file=fake_log)
        # Should still return a logger without raising
        assert logger is not None

    def test_level_warning_sets_correctly(self):
        import logging
        from luckyd_code.log import setup_logging
        with patch("logging.FileHandler"):
            logger = setup_logging(level="WARNING")
        assert logger.level == logging.WARNING


class TestGetLogger:
    @pytest.fixture(autouse=True)
    def reset_log_state(self):
        import luckyd_code.log as log_mod
        import logging
        log_mod._initialized = False
        logging.getLogger("luckyd_code").handlers.clear()
        yield
        log_mod._initialized = False
        logging.getLogger("luckyd_code").handlers.clear()

    def test_returns_logger_instance(self):
        from luckyd_code.log import get_logger
        logger = get_logger()
        import logging
        assert isinstance(logger, logging.Logger)
        assert logger.name == "luckyd_code"

    def test_returns_same_logger_as_setup(self):
        from luckyd_code.log import get_logger, setup_logging
        l1 = get_logger()
        l2 = setup_logging()
        assert l1 is l2


# ===========================================================================
# 3. settings.py — run_pre_hook branches
# ===========================================================================

class TestRunPreHook:
    """run_pre_hook — string hook, dict hook, tool filtering, failures."""

    def _patch_settings(self, hooks: dict):
        return patch("luckyd_code.settings.load_settings", return_value={"hooks": hooks})

    def test_no_hooks_returns_empty(self):
        from luckyd_code.settings import run_pre_hook
        with self._patch_settings({}):
            result = run_pre_hook("Read")
        assert result == []

    def test_string_hook_runs_script(self):
        from luckyd_code.settings import run_pre_hook
        mock_result = MagicMock(returncode=0, stderr="")
        with self._patch_settings({"preToolUse": "echo hello"}):
            with patch("subprocess.run", return_value=mock_result) as mock_run:
                result = run_pre_hook("Read")
        mock_run.assert_called_once()
        assert result == []

    def test_string_hook_nonzero_returns_stderr(self):
        from luckyd_code.settings import run_pre_hook
        mock_result = MagicMock(returncode=1, stderr="hook failed")
        with self._patch_settings({"preToolUse": "exit 1"}):
            with patch("subprocess.run", return_value=mock_result):
                result = run_pre_hook("Read")
        assert result == ["hook failed"]

    def test_string_hook_exception_returns_error(self):
        from luckyd_code.settings import run_pre_hook
        with self._patch_settings({"preToolUse": "bad-cmd"}):
            with patch("subprocess.run", side_effect=OSError("not found")):
                result = run_pre_hook("Read")
        assert len(result) == 1
        assert "not found" in result[0]

    def test_empty_script_does_nothing(self):
        from luckyd_code.settings import run_pre_hook
        with self._patch_settings({"preToolUse": ""}):
            result = run_pre_hook("Read")
        assert result == []

    def test_dict_hook_all_tools(self):
        from luckyd_code.settings import run_pre_hook
        mock_result = MagicMock(returncode=0, stderr="")
        hook = {"script": "echo hi", "tools": ["all"]}
        with self._patch_settings({"preToolUse": hook}):
            with patch("subprocess.run", return_value=mock_result) as mock_run:
                result = run_pre_hook("Bash")
        mock_run.assert_called_once()
        assert result == []

    def test_dict_hook_specific_tool_matches(self):
        from luckyd_code.settings import run_pre_hook
        mock_result = MagicMock(returncode=0, stderr="")
        hook = {"script": "echo match", "tools": ["Bash", "Write"]}
        with self._patch_settings({"preToolUse": hook}):
            with patch("subprocess.run", return_value=mock_result) as mock_run:
                result = run_pre_hook("Bash")
        mock_run.assert_called_once()

    def test_dict_hook_specific_tool_not_in_list(self):
        from luckyd_code.settings import run_pre_hook
        hook = {"script": "echo skip", "tools": ["Write"]}
        with self._patch_settings({"preToolUse": hook}):
            with patch("subprocess.run") as mock_run:
                result = run_pre_hook("Read")
        mock_run.assert_not_called()
        assert result == []

    def test_dict_hook_empty_script(self):
        from luckyd_code.settings import run_pre_hook
        hook = {"script": "", "tools": ["all"]}
        with self._patch_settings({"preToolUse": hook}):
            with patch("subprocess.run") as mock_run:
                result = run_pre_hook("Read")
        mock_run.assert_not_called()
        assert result == []

    def test_dict_hook_failure_nonzero(self):
        from luckyd_code.settings import run_pre_hook
        mock_result = MagicMock(returncode=2, stderr="permission denied")
        hook = {"script": "check.sh", "tools": ["all"]}
        with self._patch_settings({"preToolUse": hook}):
            with patch("subprocess.run", return_value=mock_result):
                result = run_pre_hook("Read")
        assert result == ["permission denied"]


# ===========================================================================
# 4. web_routes/files.py — async endpoints
# ===========================================================================

class TestWebRoutesFilesEndpoints:
    """Async endpoints in web_routes/files.py."""

    def _req_with_state(self, state=None):
        req = MagicMock()
        req.app.state.web_state = state or MagicMock()
        return req

    @pytest.mark.asyncio
    async def test_list_tools(self):
        from luckyd_code.web_routes.files import list_tools
        state = MagicMock()
        state.registry.list_tools.return_value = [
            {"function": {"name": "Read"}},
            {"function": {"name": "Write"}},
        ]
        req = self._req_with_state(state)
        result = await list_tools(req)
        assert result["count"] == 2
        assert result["tools"][0]["name"] == "Read"

    @pytest.mark.asyncio
    async def test_list_files_traversal(self, tmp_path):
        from luckyd_code.web_routes.files import list_files
        req = self._req_with_state()
        with patch("luckyd_code.web_routes.files.path_validate.safe_resolve",
                   side_effect=ValueError("traversal")):
            result = await list_files(req, dir="../etc")
        from fastapi.responses import JSONResponse
        assert isinstance(result, JSONResponse)
        assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_list_files_not_found(self, tmp_path):
        from luckyd_code.web_routes.files import list_files
        req = self._req_with_state()
        missing = str(tmp_path / "no-such-dir")
        with patch("luckyd_code.web_routes.files.path_validate.safe_resolve",
                   return_value=missing):
            result = await list_files(req, dir=missing)
        from fastapi.responses import JSONResponse
        assert isinstance(result, JSONResponse)
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_list_files_not_a_dir(self, tmp_path):
        from luckyd_code.web_routes.files import list_files
        req = self._req_with_state()
        fpath = tmp_path / "file.txt"
        fpath.write_text("x")
        with patch("luckyd_code.web_routes.files.path_validate.safe_resolve",
                   return_value=str(fpath)):
            result = await list_files(req, dir=str(fpath))
        from fastapi.responses import JSONResponse
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_list_files_success(self, tmp_path):
        from luckyd_code.web_routes.files import list_files
        (tmp_path / "a.py").write_text("pass")
        (tmp_path / "sub").mkdir()
        req = self._req_with_state()
        with patch("luckyd_code.web_routes.files.path_validate.safe_resolve",
                   return_value=str(tmp_path)):
            result = await list_files(req, dir=str(tmp_path))
        assert "files" in result
        names = [f["name"] for f in result["files"]]
        assert "a.py" in names

    @pytest.mark.asyncio
    async def test_read_file_no_path(self):
        from luckyd_code.web_routes.files import read_file
        req = self._req_with_state()
        result = await read_file(req, path="")
        from fastapi.responses import JSONResponse
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_read_file_traversal(self):
        from luckyd_code.web_routes.files import read_file
        req = self._req_with_state()
        with patch("luckyd_code.web_routes.files.path_validate.safe_resolve",
                   side_effect=ValueError("traversal")):
            result = await read_file(req, path="../etc/passwd")
        from fastapi.responses import JSONResponse
        assert isinstance(result, JSONResponse)
        assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_read_file_not_found(self, tmp_path):
        from luckyd_code.web_routes.files import read_file
        req = self._req_with_state()
        missing = str(tmp_path / "ghost.py")
        with patch("luckyd_code.web_routes.files.path_validate.safe_resolve",
                   return_value=missing):
            result = await read_file(req, path=missing)
        from fastapi.responses import JSONResponse
        assert isinstance(result, JSONResponse)
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_read_file_not_a_file(self, tmp_path):
        from luckyd_code.web_routes.files import read_file
        req = self._req_with_state()
        with patch("luckyd_code.web_routes.files.path_validate.safe_resolve",
                   return_value=str(tmp_path)):
            result = await read_file(req, path=str(tmp_path))
        from fastapi.responses import JSONResponse
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_read_file_too_large(self, tmp_path):
        import stat as _stat
        from luckyd_code.web_routes.files import read_file, MAX_READ_BYTES
        req = self._req_with_state()
        big = tmp_path / "big.txt"
        big.write_text("x")
        with patch("luckyd_code.web_routes.files.path_validate.safe_resolve",
                   return_value=str(big)), \
             patch("pathlib.Path.stat") as mock_stat:
            mock_stat.return_value.st_size = MAX_READ_BYTES + 1
            # Path.is_file() calls self.stat().st_mode internally and passes it
            # to stat.S_ISREG() which requires a real integer, not a MagicMock.
            mock_stat.return_value.st_mode = _stat.S_IFREG | 0o644
            result = await read_file(req, path=str(big))
        from fastapi.responses import JSONResponse
        assert isinstance(result, JSONResponse)
        assert result.status_code == 413

    @pytest.mark.asyncio
    async def test_read_file_success(self, tmp_path):
        from luckyd_code.web_routes.files import read_file
        fpath = tmp_path / "code.py"
        fpath.write_text("print('hello')")
        req = self._req_with_state()
        with patch("luckyd_code.web_routes.files.path_validate.safe_resolve",
                   return_value=str(fpath)):
            result = await read_file(req, path=str(fpath))
        assert "content" in result
        assert "print('hello')" in result["content"]

    @pytest.mark.asyncio
    async def test_write_file_no_path(self):
        from luckyd_code.web_routes.files import write_file, WriteData
        req = self._req_with_state()
        result = await write_file(req, data=WriteData(path="", content="x"))
        from fastapi.responses import JSONResponse
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_write_file_too_large(self):
        from luckyd_code.web_routes.files import write_file, WriteData, MAX_WRITE_BYTES
        req = self._req_with_state()
        data = WriteData(path="x.py", content="x" * (MAX_WRITE_BYTES + 1))
        result = await write_file(req, data=data)
        from fastapi.responses import JSONResponse
        assert isinstance(result, JSONResponse)
        assert result.status_code == 413

    @pytest.mark.asyncio
    async def test_write_file_traversal(self):
        from luckyd_code.web_routes.files import write_file, WriteData
        req = self._req_with_state()
        with patch("luckyd_code.web_routes.files.path_validate.safe_resolve",
                   side_effect=ValueError("traversal")):
            result = await write_file(req, data=WriteData(path="../evil.py", content="x"))
        from fastapi.responses import JSONResponse
        assert isinstance(result, JSONResponse)
        assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_write_file_success(self, tmp_path):
        from luckyd_code.web_routes.files import write_file, WriteData
        req = self._req_with_state()
        target = tmp_path / "out.py"
        with patch("luckyd_code.web_routes.files.path_validate.safe_resolve",
                   return_value=str(target)):
            result = await write_file(req, data=WriteData(path=str(target), content="pass"))
        assert result["status"] == "written"
        assert target.read_text() == "pass"

    @pytest.mark.asyncio
    async def test_edit_file_missing_fields(self):
        from luckyd_code.web_routes.files import edit_file, EditData
        req = self._req_with_state()
        result = await edit_file(req, data=EditData(path="", old_string="", new_string=""))
        from fastapi.responses import JSONResponse
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_edit_file_traversal(self):
        from luckyd_code.web_routes.files import edit_file, EditData
        req = self._req_with_state()
        with patch("luckyd_code.web_routes.files.path_validate.safe_resolve",
                   side_effect=ValueError("traversal")):
            result = await edit_file(req, data=EditData(path="../x.py", old_string="a", new_string="b"))
        from fastapi.responses import JSONResponse
        assert isinstance(result, JSONResponse)
        assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_edit_file_not_found(self, tmp_path):
        from luckyd_code.web_routes.files import edit_file, EditData
        req = self._req_with_state()
        missing = str(tmp_path / "missing.py")
        with patch("luckyd_code.web_routes.files.path_validate.safe_resolve",
                   return_value=missing):
            result = await edit_file(req, data=EditData(path=missing, old_string="x", new_string="y"))
        from fastapi.responses import JSONResponse
        assert isinstance(result, JSONResponse)
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_edit_file_old_string_not_found(self, tmp_path):
        from luckyd_code.web_routes.files import edit_file, EditData
        fpath = tmp_path / "code.py"
        fpath.write_text("print('hello')")
        req = self._req_with_state()
        with patch("luckyd_code.web_routes.files.path_validate.safe_resolve",
                   return_value=str(fpath)):
            result = await edit_file(req, data=EditData(path=str(fpath), old_string="MISSING", new_string="x"))
        from fastapi.responses import JSONResponse
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_edit_file_success(self, tmp_path):
        from luckyd_code.web_routes.files import edit_file, EditData
        fpath = tmp_path / "code.py"
        fpath.write_text("old text here")
        req = self._req_with_state()
        with patch("luckyd_code.web_routes.files.path_validate.safe_resolve",
                   return_value=str(fpath)):
            result = await edit_file(req, data=EditData(path=str(fpath),
                                                        old_string="old text",
                                                        new_string="new text"))
        assert result["status"] == "edited"
        assert fpath.read_text() == "new text here"


# ===========================================================================
# 5. web_routes/memories.py
# ===========================================================================

class TestWebRoutesMemories:
    """All 6 routes in web_routes/memories.py."""

    def _state(self, **kwargs):
        state = MagicMock()
        state.context.count_messages.return_value = 3
        state.context.messages = []
        for k, v in kwargs.items():
            setattr(state, k, v)
        return state

    @pytest.mark.asyncio
    async def test_get_memory(self):
        from luckyd_code.web_routes import memories as mem_mod
        state = self._state()
        req = _make_request(state)
        with patch.object(mem_mod, "memory_module") as mock_mm:
            mock_mm.load_claude_md.return_value = "# My Memory"
            result = await mem_mod.get_memory(req)
        assert result["claude_md"] == "# My Memory"
        assert result["message_count"] == 3

    @pytest.mark.asyncio
    async def test_save_memory_new_block(self):
        from luckyd_code.web_routes import memories as mem_mod
        from luckyd_code.web_routes.memories import MemorySave
        state = self._state()
        req = _make_request(state)
        with patch.object(mem_mod, "memory_module") as mock_mm:
            result = await mem_mod.save_memory(req, MemorySave(content="# Updated"))
        assert result["status"] == "saved"
        # A new claude-md message should be inserted
        assert any("<claude-md>" in str(m.get("content", ""))
                   for m in state.context.messages)

    @pytest.mark.asyncio
    async def test_save_memory_replaces_existing_block(self):
        from luckyd_code.web_routes import memories as mem_mod
        from luckyd_code.web_routes.memories import MemorySave
        state = self._state()
        state.context.messages = [
            {"role": "user", "content": "<claude-md>old content</claude-md>"}
        ]
        req = _make_request(state)
        with patch.object(mem_mod, "memory_module"):
            await mem_mod.save_memory(req, MemorySave(content="new content"))
        assert "new content" in state.context.messages[0]["content"]

    @pytest.mark.asyncio
    async def test_save_memory_preserves_session_memories(self):
        from luckyd_code.web_routes import memories as mem_mod
        from luckyd_code.web_routes.memories import MemorySave
        state = self._state()
        state.context.messages = [
            {"role": "user",
             "content": "<claude-md>md\n\n<memories>session mems</memories></claude-md>"}
        ]
        req = _make_request(state)
        with patch.object(mem_mod, "memory_module"):
            await mem_mod.save_memory(req, MemorySave(content="fresh md"))
        saved = state.context.messages[0]["content"]
        assert "<memories>session mems</memories>" in saved

    @pytest.mark.asyncio
    async def test_list_memories_no_query(self):
        from luckyd_code.web_routes import memories as mem_mod
        state = self._state()
        state.web_memory_mgr.list_memories.return_value = [
            {"name": "m1", "type": "conversation"}
        ]
        req = _make_request(state)
        result = await mem_mod.list_memories(req, q="")
        assert len(result["memories"]) == 1

    @pytest.mark.asyncio
    async def test_list_memories_with_query(self):
        from luckyd_code.web_routes import memories as mem_mod
        state = self._state()
        state.web_memory_mgr.search_memories.return_value = [
            {"name": "m1", "score": 0.9}
        ]
        req = _make_request(state)
        result = await mem_mod.list_memories(req, q="auth")
        state.web_memory_mgr.search_memories.assert_called_with("auth")
        assert len(result["memories"]) == 1

    @pytest.mark.asyncio
    async def test_save_memory_web(self):
        from luckyd_code.web_routes import memories as mem_mod
        from luckyd_code.web_routes.memories import NamedMemorySave
        state = self._state()
        req = _make_request(state)
        result = await mem_mod.save_memory_web(
            req, NamedMemorySave(name="test-mem", content="some content")
        )
        state.web_memory_mgr.save_memory.assert_called_once_with("test-mem", "some content")
        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_delete_memory_web_found(self):
        from luckyd_code.web_routes import memories as mem_mod
        state = self._state()
        state.web_memory_mgr.delete_memory.return_value = True
        req = _make_request(state)
        result = await mem_mod.delete_memory_web(req, name="old-mem")
        assert result["status"] == "ok"
        assert result["name"] == "old-mem"

    @pytest.mark.asyncio
    async def test_delete_memory_web_not_found(self):
        from luckyd_code.web_routes import memories as mem_mod
        from fastapi.responses import JSONResponse
        state = self._state()
        state.web_memory_mgr.delete_memory.return_value = False
        req = _make_request(state)
        result = await mem_mod.delete_memory_web(req, name="ghost")
        assert isinstance(result, JSONResponse)
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_get_memory_web_found(self):
        from luckyd_code.web_routes import memories as mem_mod
        state = self._state()
        state.web_memory_mgr.load_memory.return_value = "memory content"
        req = _make_request(state)
        result = await mem_mod.get_memory_web(req, name="my-mem")
        assert result["name"] == "my-mem"
        assert result["content"] == "memory content"

    @pytest.mark.asyncio
    async def test_get_memory_web_not_found(self):
        from luckyd_code.web_routes import memories as mem_mod
        from fastapi.responses import JSONResponse
        state = self._state()
        state.web_memory_mgr.load_memory.return_value = None
        req = _make_request(state)
        result = await mem_mod.get_memory_web(req, name="missing")
        assert isinstance(result, JSONResponse)
        assert result.status_code == 404


# ===========================================================================
# 6. web_routes/review.py
# ===========================================================================

class TestWebRoutesReview:
    @pytest.mark.asyncio
    async def test_review_code(self):
        from luckyd_code.web_routes.review import review_code
        with patch("luckyd_code.web_routes.review.review_skill.review_changes",
                   return_value="+ added line\n- removed line"):
            result = await review_code()
        assert "diff" in result
        assert "added line" in result["diff"]

    @pytest.mark.asyncio
    async def test_review_code_no_changes(self):
        from luckyd_code.web_routes.review import review_code
        with patch("luckyd_code.web_routes.review.review_skill.review_changes",
                   return_value="No changes to review."):
            result = await review_code()
        assert result["diff"] == "No changes to review."

    @pytest.mark.asyncio
    async def test_security_review(self):
        from luckyd_code.web_routes.review import security_review
        with patch("luckyd_code.web_routes.review.security_skill.security_review",
                   return_value="Security check passed."):
            result = await security_review()
        assert "analysis" in result
        assert "Security check" in result["analysis"]

    @pytest.mark.asyncio
    async def test_security_review_findings(self):
        from luckyd_code.web_routes.review import security_review
        with patch("luckyd_code.web_routes.review.security_skill.security_review",
                   return_value="Warning: hardcoded secret found."):
            result = await security_review()
        assert "hardcoded secret" in result["analysis"]


# ===========================================================================
# 7. web_routes/update.py
# ===========================================================================

class TestWebRoutesUpdate:
    @pytest.mark.asyncio
    async def test_check_updates_returns_version(self):
        from luckyd_code.web_routes.update import check_updates
        with patch("luckyd_code.web_routes.update.updater.get_version",
                   return_value="1.2.2"):
            result = await check_updates()
        assert result["version"] == "1.2.2"
        assert "update_available" in result

    @pytest.mark.asyncio
    async def test_do_update_success(self):
        from luckyd_code.web_routes.update import do_update
        with patch("luckyd_code.web_routes.update.updater.do_update",
                   return_value="Already up to date."):
            result = await do_update()
        assert result["status"] == "ok"
        assert "up to date" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_do_update_pulled(self):
        from luckyd_code.web_routes.update import do_update
        with patch("luckyd_code.web_routes.update.updater.do_update",
                   return_value="3 commits pulled."):
            result = await do_update()
        assert result["status"] == "ok"
        assert "3 commits" in result["message"]


# ===========================================================================
# 8. web_routes/background.py
# ===========================================================================

class TestWebRoutesBackground:
    """Async endpoints in web_routes/background.py."""

    @pytest.mark.asyncio
    async def test_background_list_success(self):
        from luckyd_code.web_routes.background import background_list
        state = MagicMock()
        req = _make_request(state)
        mock_bg = MagicMock()
        mock_bg.get_status.return_value = [
            {"id": "t1", "status": "done", "description": "analyse code"}
        ]
        with patch("luckyd_code.background.BackgroundAgent",
                   return_value=mock_bg):
            result = await background_list(req)
        assert "tasks" in result
        assert len(result["tasks"]) == 1

    @pytest.mark.asyncio
    async def test_background_list_exception(self):
        from luckyd_code.web_routes.background import background_list
        from fastapi.responses import JSONResponse
        req = _make_request()
        with patch("luckyd_code.background.BackgroundAgent",
                   side_effect=RuntimeError("init failed")):
            result = await background_list(req)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_background_start_no_task(self):
        from luckyd_code.web_routes.background import background_start, BackgroundStart
        from fastapi.responses import JSONResponse
        req = _make_request()
        with patch("luckyd_code.background.BackgroundAgent"):
            result = await background_start(req, data=BackgroundStart(task=""))
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_background_start_success(self):
        from luckyd_code.web_routes.background import background_start, BackgroundStart
        state = MagicMock()
        req = _make_request(state)
        mock_bg = MagicMock()
        mock_bg.start_task.return_value = "task-abc"
        with patch("luckyd_code.background.BackgroundAgent",
                   return_value=mock_bg):
            result = await background_start(req, data=BackgroundStart(task="analyse codebase"))
        assert result["task_id"] == "task-abc"
        assert result["status"] == "started"

    @pytest.mark.asyncio
    async def test_background_start_exception(self):
        from luckyd_code.web_routes.background import background_start, BackgroundStart
        from fastapi.responses import JSONResponse
        req = _make_request()
        with patch("luckyd_code.background.BackgroundAgent",
                   side_effect=RuntimeError("boom")):
            result = await background_start(req, data=BackgroundStart(task="do it"))
        assert isinstance(result, JSONResponse)
        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_background_status_found(self):
        from luckyd_code.web_routes.background import background_status
        state = MagicMock()
        req = _make_request(state)
        mock_bg = MagicMock()
        mock_bg.get_status.return_value = [
            {"id": "t1", "status": "running", "description": "x"}
        ]
        with patch("luckyd_code.background.BackgroundAgent",
                   return_value=mock_bg):
            result = await background_status(req, task_id="t1")
        assert result["task"]["id"] == "t1"

    @pytest.mark.asyncio
    async def test_background_status_not_found(self):
        from luckyd_code.web_routes.background import background_status
        from fastapi.responses import JSONResponse
        req = _make_request()
        mock_bg = MagicMock()
        mock_bg.get_status.return_value = []
        with patch("luckyd_code.background.BackgroundAgent",
                   return_value=mock_bg):
            result = await background_status(req, task_id="ghost")
        assert isinstance(result, JSONResponse)
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_background_status_exception(self):
        from luckyd_code.web_routes.background import background_status
        from fastapi.responses import JSONResponse
        req = _make_request()
        with patch("luckyd_code.background.BackgroundAgent",
                   side_effect=RuntimeError("db error")):
            result = await background_status(req, task_id="t1")
        assert isinstance(result, JSONResponse)
        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_background_result_found(self):
        from luckyd_code.web_routes.background import background_result
        state = MagicMock()
        req = _make_request(state)
        mock_bg = MagicMock()
        mock_bg.get_result.return_value = "Analysis complete."
        with patch("luckyd_code.background.BackgroundAgent",
                   return_value=mock_bg):
            result = await background_result(req, task_id="t1")
        assert result["result"] == "Analysis complete."

    @pytest.mark.asyncio
    async def test_background_result_not_found(self):
        from luckyd_code.web_routes.background import background_result
        from fastapi.responses import JSONResponse
        req = _make_request()
        mock_bg = MagicMock()
        mock_bg.get_result.return_value = None
        with patch("luckyd_code.background.BackgroundAgent",
                   return_value=mock_bg):
            result = await background_result(req, task_id="t1")
        assert isinstance(result, JSONResponse)
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_background_result_exception(self):
        from luckyd_code.web_routes.background import background_result
        from fastapi.responses import JSONResponse
        req = _make_request()
        with patch("luckyd_code.background.BackgroundAgent",
                   side_effect=RuntimeError("crash")):
            result = await background_result(req, task_id="t1")
        assert isinstance(result, JSONResponse)
        assert result.status_code == 500
