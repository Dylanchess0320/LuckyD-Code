"""Targeted coverage for every remaining uncovered module/branch.

Verified gaps (nothing in the rest of the suite touches these):
  1. cli_utils.py          — resize_terminal, play_completion_sound,
                             init_prompt_session, read_input
  2. log.py                — setup_logging (all branches), get_logger
  3. settings.py           — run_pre_hook (all branches)
  4. web_routes/files.py   — list_tools, list_files, read_file,
                             write_file, edit_file
  5. web_routes/memories.py — all 6 routes
  6. web_routes/review.py   — review_code, security_review
  7. web_routes/update.py   — check_updates, do_update
  8. web_routes/background.py — background_list/start/status/result

Patching rules applied throughout:
  - NEVER patch("sys.stdout") or patch("sys.platform") globally — that
    kills pytest's capture teardown.  Always patch through the module:
    patch("luckyd_code.cli_utils.sys").
  - subprocess imported *inside* functions is patched at the top-level
    module since local `import subprocess` resolves from sys.modules.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import pytest


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------

def _make_request(state=None):
    req = MagicMock()
    req.app.state.web_state = state or MagicMock()
    return req


# ===========================================================================
# 1. cli_utils.py — resize_terminal
# ===========================================================================

class TestResizeTerminal:

    def test_disabled_bool_false(self):
        from luckyd_code import cli_utils
        with patch("luckyd_code.cli_utils.cfg.load_settings",
                   return_value={"auto_resize_terminal": False}):
            with patch("luckyd_code.cli_utils.os") as mock_os:
                cli_utils.resize_terminal()
        mock_os.system.assert_not_called()

    @pytest.mark.parametrize("val", ["false", "0", "no", "off"])
    def test_disabled_string_values(self, val):
        from luckyd_code import cli_utils
        with patch("luckyd_code.cli_utils.cfg.load_settings",
                   return_value={"auto_resize_terminal": val}):
            with patch("luckyd_code.cli_utils.os") as mock_os:
                cli_utils.resize_terminal()
        mock_os.system.assert_not_called()

    @pytest.mark.parametrize("val", ["true", "1", "yes"])
    def test_enabled_string_values(self, val):
        from luckyd_code import cli_utils
        with patch("luckyd_code.cli_utils.cfg.load_settings",
                   return_value={"auto_resize_terminal": val}):
            with patch("luckyd_code.cli_utils.sys") as mock_sys, \
                 patch("luckyd_code.cli_utils.os"):
                mock_sys.platform = "linux"
                mock_sys.stdout = MagicMock()
                cli_utils.resize_terminal()
            mock_sys.stdout.write.assert_called()

    def test_windows_calls_mode_con(self):
        from luckyd_code import cli_utils
        with patch("luckyd_code.cli_utils.cfg.load_settings", return_value={}):
            with patch("luckyd_code.cli_utils.sys") as mock_sys, \
                 patch("luckyd_code.cli_utils.os") as mock_os, \
                 patch("time.sleep"):
                mock_sys.platform = "win32"
                cli_utils.resize_terminal(cols=120)
        mock_os.system.assert_called_once()
        assert "cols=120" in mock_os.system.call_args[0][0]

    def test_windows_settings_override_cols(self):
        from luckyd_code import cli_utils
        with patch("luckyd_code.cli_utils.cfg.load_settings",
                   return_value={"terminal_columns": 180}):
            with patch("luckyd_code.cli_utils.sys") as mock_sys, \
                 patch("luckyd_code.cli_utils.os") as mock_os, \
                 patch("time.sleep"):
                mock_sys.platform = "win32"
                cli_utils.resize_terminal()
        assert "cols=180" in mock_os.system.call_args[0][0]

    def test_unix_writes_escape_sequence(self):
        from luckyd_code import cli_utils
        with patch("luckyd_code.cli_utils.cfg.load_settings", return_value={}):
            with patch("luckyd_code.cli_utils.sys") as mock_sys:
                mock_sys.platform = "linux"
                mock_sys.stdout = MagicMock()
                cli_utils.resize_terminal(cols=200, rows=50)
        written = mock_sys.stdout.write.call_args[0][0]
        assert "\033[8;" in written
        assert "200" in written
        assert "50" in written

    def test_unix_settings_override_rows_cols(self):
        from luckyd_code import cli_utils
        with patch("luckyd_code.cli_utils.cfg.load_settings",
                   return_value={"terminal_columns": 160, "terminal_rows": 45}):
            with patch("luckyd_code.cli_utils.sys") as mock_sys:
                mock_sys.platform = "linux"
                mock_sys.stdout = MagicMock()
                cli_utils.resize_terminal()
        written = mock_sys.stdout.write.call_args[0][0]
        assert "160" in written
        assert "45" in written

    def test_exception_silently_ignored(self):
        from luckyd_code import cli_utils
        with patch("luckyd_code.cli_utils.cfg.load_settings",
                   side_effect=RuntimeError("settings exploded")):
            cli_utils.resize_terminal()  # must not raise


# ===========================================================================
# 1b. cli_utils.py — play_completion_sound
# ===========================================================================

class TestPlayCompletionSound:

    def test_disabled_returns_immediately(self):
        from luckyd_code import cli_utils
        with patch("luckyd_code.cli_utils.cfg.load_settings",
                   return_value={"completion_sound": False}):
            with patch("luckyd_code.cli_utils.sys") as mock_sys:
                mock_sys.stdout = MagicMock()
                cli_utils.play_completion_sound()
        mock_sys.stdout.write.assert_not_called()

    def test_windows_success_plays_exclamation(self):
        from luckyd_code import cli_utils
        mock_winsound = MagicMock()
        with patch("luckyd_code.cli_utils.cfg.load_settings", return_value={}), \
             patch("luckyd_code.cli_utils.sys") as mock_sys, \
             patch.dict(sys.modules, {"winsound": mock_winsound}):
            mock_sys.platform = "win32"
            cli_utils.play_completion_sound(success=True)
        mock_winsound.PlaySound.assert_called_once()
        assert "SystemExclamation" in mock_winsound.PlaySound.call_args[0]

    def test_windows_failure_plays_hand(self):
        from luckyd_code import cli_utils
        mock_winsound = MagicMock()
        with patch("luckyd_code.cli_utils.cfg.load_settings", return_value={}), \
             patch("luckyd_code.cli_utils.sys") as mock_sys, \
             patch.dict(sys.modules, {"winsound": mock_winsound}):
            mock_sys.platform = "win32"
            cli_utils.play_completion_sound(success=False)
        assert "SystemHand" in mock_winsound.PlaySound.call_args[0]

    def test_macos_success_calls_afplay_glass(self):
        from luckyd_code import cli_utils
        with patch("luckyd_code.cli_utils.cfg.load_settings", return_value={}), \
             patch("luckyd_code.cli_utils.sys") as mock_sys, \
             patch("subprocess.Popen") as mock_popen:
            mock_sys.platform = "darwin"
            cli_utils.play_completion_sound(success=True)
        mock_popen.assert_called_once()
        assert "Glass" in mock_popen.call_args[0][0][1]

    def test_macos_failure_calls_afplay_basso(self):
        from luckyd_code import cli_utils
        with patch("luckyd_code.cli_utils.cfg.load_settings", return_value={}), \
             patch("luckyd_code.cli_utils.sys") as mock_sys, \
             patch("subprocess.Popen") as mock_popen:
            mock_sys.platform = "darwin"
            cli_utils.play_completion_sound(success=False)
        assert "Basso" in mock_popen.call_args[0][0][1]

    def test_macos_afplay_fails_falls_back_to_bell(self):
        from luckyd_code import cli_utils
        with patch("luckyd_code.cli_utils.cfg.load_settings", return_value={}), \
             patch("luckyd_code.cli_utils.sys") as mock_sys, \
             patch("subprocess.Popen", side_effect=FileNotFoundError("no afplay")):
            mock_sys.platform = "darwin"
            mock_sys.stdout = MagicMock()
            cli_utils.play_completion_sound(success=True)
        mock_sys.stdout.write.assert_called_with("\a")

    def test_linux_success_tries_paplay(self):
        from luckyd_code import cli_utils
        with patch("luckyd_code.cli_utils.cfg.load_settings", return_value={}), \
             patch("luckyd_code.cli_utils.sys") as mock_sys, \
             patch("subprocess.run") as mock_run:
            mock_sys.platform = "linux"
            mock_run.return_value = MagicMock(returncode=0)
            cli_utils.play_completion_sound(success=True)
        first_call = mock_run.call_args_list[0][0][0]
        assert "paplay" in first_call

    def test_linux_paplay_fails_tries_aplay(self):
        from luckyd_code import cli_utils
        calls = []
        def _run(cmd, **kw):
            calls.append(cmd)
            if "paplay" in cmd:
                raise OSError("no paplay")
            return MagicMock(returncode=0)
        with patch("luckyd_code.cli_utils.cfg.load_settings", return_value={}), \
             patch("luckyd_code.cli_utils.sys") as mock_sys, \
             patch("subprocess.run", side_effect=_run):
            mock_sys.platform = "linux"
            cli_utils.play_completion_sound(success=True)
        assert any("aplay" in str(c) for c in calls)

    def test_linux_all_sound_fails_writes_bell(self):
        from luckyd_code import cli_utils
        with patch("luckyd_code.cli_utils.cfg.load_settings", return_value={}), \
             patch("luckyd_code.cli_utils.sys") as mock_sys, \
             patch("subprocess.run", side_effect=OSError("no sound")):
            mock_sys.platform = "linux"
            mock_sys.stdout = MagicMock()
            cli_utils.play_completion_sound(success=True)
        mock_sys.stdout.write.assert_called_with("\a")

    def test_linux_failure_writes_triple_bell(self):
        from luckyd_code import cli_utils
        with patch("luckyd_code.cli_utils.cfg.load_settings", return_value={}), \
             patch("luckyd_code.cli_utils.sys") as mock_sys, \
             patch("luckyd_code.cli_utils._time") as mock_time, \
             patch("subprocess.run", side_effect=OSError("no sound")):
            mock_sys.platform = "linux"
            mock_sys.stdout = MagicMock()
            cli_utils.play_completion_sound(success=False)
        assert mock_sys.stdout.write.call_count >= 3

    def test_outer_exception_writes_bell(self):
        from luckyd_code import cli_utils
        with patch("luckyd_code.cli_utils.cfg.load_settings",
                   side_effect=RuntimeError("explosion")):
            with patch("luckyd_code.cli_utils.sys") as mock_sys:
                mock_sys.stdout = MagicMock()
                cli_utils.play_completion_sound(success=True)
        mock_sys.stdout.write.assert_called_with("\a")


# ===========================================================================
# 1c. cli_utils.py — init_prompt_session
# ===========================================================================

class TestInitPromptSession:

    def test_returns_session_normally(self):
        from luckyd_code import cli_utils
        result = cli_utils.init_prompt_session()
        # Either a real PromptSession or None — just must not crash
        # On CI with a tty it returns a session; on piped stdin may return None
        assert result is None or hasattr(result, "prompt")

    def test_returns_none_when_all_paths_fail(self):
        from luckyd_code import cli_utils
        with patch("prompt_toolkit.PromptSession",
                   side_effect=Exception("tty broken")), \
             patch("prompt_toolkit.output.vt100.Vt100_Output",
                   side_effect=Exception("vt100 broken"), create=True):
            result = cli_utils.init_prompt_session()
        assert result is None


# ===========================================================================
# 1d. cli_utils.py — read_input
# ===========================================================================

class TestReadInput:

    def test_with_session_returns_text(self):
        from luckyd_code import cli_utils
        session = MagicMock()
        session.prompt.return_value = "hello world"
        assert cli_utils.read_input(session) == "hello world"

    def test_with_session_keyboard_interrupt_returns_none(self):
        from luckyd_code import cli_utils
        session = MagicMock()
        session.prompt.side_effect = KeyboardInterrupt
        assert cli_utils.read_input(session) is None

    def test_with_session_eof_returns_sentinel(self):
        from luckyd_code import cli_utils
        session = MagicMock()
        session.prompt.side_effect = EOFError
        assert cli_utils.read_input(session) == "__EOF__"

    def test_no_session_simple_line(self):
        from luckyd_code import cli_utils
        with patch("builtins.input", return_value="simple line"):
            assert cli_utils.read_input(None) == "simple line"

    def test_no_session_backslash_continuation(self):
        from luckyd_code import cli_utils
        responses = iter(["first\\", "second"])
        with patch("builtins.input", side_effect=lambda _: next(responses)):
            result = cli_utils.read_input(None)
        assert "first" in result
        assert "second" in result

    def test_no_session_eof_no_lines_returns_sentinel(self):
        from luckyd_code import cli_utils
        with patch("builtins.input", side_effect=EOFError):
            assert cli_utils.read_input(None) == "__EOF__"

    def test_no_session_eof_with_accumulated_lines(self):
        from luckyd_code import cli_utils
        responses = iter(["line one\\", EOFError()])
        def _inp(_prompt):
            v = next(responses)
            if isinstance(v, EOFError):
                raise v
            return v
        with patch("builtins.input", side_effect=_inp):
            result = cli_utils.read_input(None)
        assert result is not None

    def test_no_session_keyboard_interrupt_returns_none(self):
        from luckyd_code import cli_utils
        with patch("builtins.input", side_effect=KeyboardInterrupt):
            assert cli_utils.read_input(None) is None


# ===========================================================================
# 2. log.py — setup_logging + get_logger
# ===========================================================================

class TestSetupLogging:

    @pytest.fixture(autouse=True)
    def _reset(self):
        import luckyd_code.log as m
        import logging
        m._initialized = False
        logging.getLogger("luckyd_code").handlers.clear()
        yield
        m._initialized = False
        logging.getLogger("luckyd_code").handlers.clear()

    def test_returns_logger_instance(self):
        import logging
        from luckyd_code.log import setup_logging
        logger = setup_logging(level="WARNING")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "luckyd_code"

    def test_sets_correct_level(self):
        import logging
        from luckyd_code.log import setup_logging
        logger = setup_logging(level="WARNING")
        assert logger.level == logging.WARNING

    def test_idempotent_second_call_no_op(self):
        from luckyd_code.log import setup_logging
        l1 = setup_logging(level="INFO")
        l2 = setup_logging(level="DEBUG")  # second call — ignored
        assert l1 is l2

    def test_explicit_log_file_is_created(self, tmp_path):
        from luckyd_code.log import setup_logging
        lf = str(tmp_path / "run.log")
        setup_logging(level="INFO", log_file=lf)
        assert Path(lf).exists()

    def test_auto_log_file_created_in_log_dir(self, tmp_path):
        from luckyd_code.log import setup_logging
        with patch("luckyd_code.log._LOG_DIR", tmp_path):
            setup_logging(level="INFO")
        assert any(tmp_path.glob("session_*.log"))

    def test_bad_log_file_path_does_not_crash(self):
        from luckyd_code.log import setup_logging
        # Point at a path whose parent doesn't exist — FileHandler will fail
        bad = "/no/such/dir/run.log"
        logger = setup_logging(level="INFO", log_file=bad)
        assert logger is not None  # warning emitted but no exception


class TestGetLogger:

    @pytest.fixture(autouse=True)
    def _reset(self):
        import luckyd_code.log as m
        import logging
        m._initialized = False
        logging.getLogger("luckyd_code").handlers.clear()
        yield
        m._initialized = False
        logging.getLogger("luckyd_code").handlers.clear()

    def test_returns_luckyd_logger(self):
        import logging
        from luckyd_code.log import get_logger
        logger = get_logger()
        assert isinstance(logger, logging.Logger)
        assert logger.name == "luckyd_code"

    def test_same_object_as_setup_logging(self):
        from luckyd_code.log import get_logger, setup_logging
        assert get_logger() is setup_logging()


# ===========================================================================
# 3. settings.py — run_pre_hook
# ===========================================================================

class TestRunPreHook:

    def _patch(self, hooks: dict):
        return patch("luckyd_code.settings.load_settings",
                     return_value={"hooks": hooks})

    def test_no_hooks_returns_empty(self):
        from luckyd_code.settings import run_pre_hook
        with self._patch({}):
            assert run_pre_hook("Read") == []

    def test_empty_string_script_skipped(self):
        from luckyd_code.settings import run_pre_hook
        with self._patch({"preToolUse": ""}):
            with patch("subprocess.run") as mock_run:
                result = run_pre_hook("Read")
        mock_run.assert_not_called()
        assert result == []

    def test_string_hook_runs_script(self):
        from luckyd_code.settings import run_pre_hook
        ok = MagicMock(returncode=0, stderr="")
        with self._patch({"preToolUse": "echo hi"}):
            with patch("subprocess.run", return_value=ok) as mock_run:
                result = run_pre_hook("Read")
        mock_run.assert_called_once()
        assert result == []

    def test_string_hook_nonzero_returns_stderr(self):
        from luckyd_code.settings import run_pre_hook
        fail = MagicMock(returncode=1, stderr="hook failed")
        with self._patch({"preToolUse": "exit 1"}):
            with patch("subprocess.run", return_value=fail):
                result = run_pre_hook("Read")
        assert result == ["hook failed"]

    def test_string_hook_exception_returns_error(self):
        from luckyd_code.settings import run_pre_hook
        with self._patch({"preToolUse": "bad-cmd"}):
            with patch("subprocess.run", side_effect=OSError("not found")):
                result = run_pre_hook("Read")
        assert len(result) == 1
        assert "not found" in result[0]

    def test_dict_hook_all_tools_runs(self):
        from luckyd_code.settings import run_pre_hook
        ok = MagicMock(returncode=0, stderr="")
        hook = {"script": "echo hi", "tools": ["all"]}
        with self._patch({"preToolUse": hook}):
            with patch("subprocess.run", return_value=ok) as mock_run:
                result = run_pre_hook("Bash")
        mock_run.assert_called_once()
        assert result == []

    def test_dict_hook_specific_tool_matches(self):
        from luckyd_code.settings import run_pre_hook
        ok = MagicMock(returncode=0, stderr="")
        hook = {"script": "check.sh", "tools": ["Bash", "Write"]}
        with self._patch({"preToolUse": hook}):
            with patch("subprocess.run", return_value=ok) as mock_run:
                run_pre_hook("Bash")
        mock_run.assert_called_once()

    def test_dict_hook_tool_not_in_list_skipped(self):
        from luckyd_code.settings import run_pre_hook
        hook = {"script": "echo skip", "tools": ["Write"]}
        with self._patch({"preToolUse": hook}):
            with patch("subprocess.run") as mock_run:
                result = run_pre_hook("Read")
        mock_run.assert_not_called()
        assert result == []

    def test_dict_hook_empty_script_skipped(self):
        from luckyd_code.settings import run_pre_hook
        hook = {"script": "", "tools": ["all"]}
        with self._patch({"preToolUse": hook}):
            with patch("subprocess.run") as mock_run:
                result = run_pre_hook("Bash")
        mock_run.assert_not_called()
        assert result == []

    def test_dict_hook_nonzero_returns_stderr(self):
        from luckyd_code.settings import run_pre_hook
        fail = MagicMock(returncode=2, stderr="permission denied")
        hook = {"script": "check.sh", "tools": ["all"]}
        with self._patch({"preToolUse": hook}):
            with patch("subprocess.run", return_value=fail):
                result = run_pre_hook("Read")
        assert result == ["permission denied"]


# ===========================================================================
# 4. web_routes/files.py — async endpoints
# ===========================================================================

class TestWebRoutesFilesEndpoints:

    def _req(self, state=None):
        return _make_request(state)

    def _patch_resolve(self, return_value=None, side_effect=None):
        if side_effect:
            return patch("luckyd_code.web_routes.files.path_validate.safe_resolve",
                         side_effect=side_effect)
        return patch("luckyd_code.web_routes.files.path_validate.safe_resolve",
                     return_value=return_value)

    # list_tools
    @pytest.mark.asyncio
    async def test_list_tools(self):
        from luckyd_code.web_routes.files import list_tools
        state = MagicMock()
        state.registry.list_tools.return_value = [
            {"function": {"name": "Read"}},
            {"function": {"name": "Write"}},
        ]
        result = await list_tools(self._req(state))
        assert result["count"] == 2
        assert result["tools"][0]["name"] == "Read"

    # list_files
    @pytest.mark.asyncio
    async def test_list_files_traversal_blocked(self):
        from luckyd_code.web_routes.files import list_files
        from fastapi.responses import JSONResponse
        with self._patch_resolve(side_effect=ValueError("traversal")):
            result = await list_files(self._req(), dir="../etc")
        assert isinstance(result, JSONResponse)
        assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_list_files_not_found(self, tmp_path):
        from luckyd_code.web_routes.files import list_files
        from fastapi.responses import JSONResponse
        missing = str(tmp_path / "no-dir")
        with self._patch_resolve(return_value=missing):
            result = await list_files(self._req(), dir=missing)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_list_files_not_a_directory(self, tmp_path):
        from luckyd_code.web_routes.files import list_files
        from fastapi.responses import JSONResponse
        f = tmp_path / "file.txt"
        f.write_text("x")
        with self._patch_resolve(return_value=str(f)):
            result = await list_files(self._req(), dir=str(f))
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_list_files_success(self, tmp_path):
        from luckyd_code.web_routes.files import list_files
        (tmp_path / "app.py").write_text("pass")
        (tmp_path / "sub").mkdir()
        with self._patch_resolve(return_value=str(tmp_path)):
            result = await list_files(self._req(), dir=str(tmp_path))
        assert "files" in result
        names = [f["name"] for f in result["files"]]
        assert "app.py" in names

    # read_file
    @pytest.mark.asyncio
    async def test_read_file_no_path(self):
        from luckyd_code.web_routes.files import read_file
        from fastapi.responses import JSONResponse
        result = await read_file(self._req(), path="")
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_read_file_traversal_blocked(self):
        from luckyd_code.web_routes.files import read_file
        from fastapi.responses import JSONResponse
        with self._patch_resolve(side_effect=ValueError("traversal")):
            result = await read_file(self._req(), path="../etc/passwd")
        assert isinstance(result, JSONResponse)
        assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_read_file_not_found(self, tmp_path):
        from luckyd_code.web_routes.files import read_file
        from fastapi.responses import JSONResponse
        missing = str(tmp_path / "ghost.py")
        with self._patch_resolve(return_value=missing):
            result = await read_file(self._req(), path=missing)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_read_file_is_directory(self, tmp_path):
        from luckyd_code.web_routes.files import read_file
        from fastapi.responses import JSONResponse
        with self._patch_resolve(return_value=str(tmp_path)):
            result = await read_file(self._req(), path=str(tmp_path))
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_read_file_too_large(self, tmp_path):
        from luckyd_code.web_routes.files import read_file, MAX_READ_BYTES
        from fastapi.responses import JSONResponse
        f = tmp_path / "big.bin"
        f.write_bytes(b"x")
        with self._patch_resolve(return_value=str(f)):
            # Override stat to report a huge size
            orig_stat = Path.stat

            def _fake_stat(self_):
                orig_stat(self_)  # call real stat so we know file exists
                # Return an object whose st_size exceeds limit.
                # pathlib internally reads st_mode from stat results, so we
                # must include it alongside st_size.
                class _S:
                    st_size = MAX_READ_BYTES + 1
                    st_mode = 0o100644  # regular file (not a directory)
                    st_mtime = 0.0
                    st_ctime = 0.0
                    st_atime = 0.0
                    st_ino = 0
                    st_dev = 0
                    st_nlink = 1
                    st_uid = 0
                    st_gid = 0
                return _S()

            with patch("pathlib.Path.stat", _fake_stat):
                result = await read_file(self._req(), path=str(f))
        assert isinstance(result, JSONResponse)
        assert result.status_code == 413

    @pytest.mark.asyncio
    async def test_read_file_success(self, tmp_path):
        from luckyd_code.web_routes.files import read_file
        f = tmp_path / "code.py"
        f.write_text("print('hello')")
        with self._patch_resolve(return_value=str(f)):
            result = await read_file(self._req(), path=str(f))
        assert result["content"] == "print('hello')"

    # write_file
    @pytest.mark.asyncio
    async def test_write_file_no_path(self):
        from luckyd_code.web_routes.files import write_file, WriteData
        from fastapi.responses import JSONResponse
        result = await write_file(self._req(), data=WriteData(path="", content="x"))
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_write_file_too_large(self):
        from luckyd_code.web_routes.files import write_file, WriteData, MAX_WRITE_BYTES
        from fastapi.responses import JSONResponse
        big = WriteData(path="x.py", content="x" * (MAX_WRITE_BYTES + 1))
        result = await write_file(self._req(), data=big)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 413

    @pytest.mark.asyncio
    async def test_write_file_traversal_blocked(self):
        from luckyd_code.web_routes.files import write_file, WriteData
        from fastapi.responses import JSONResponse
        with self._patch_resolve(side_effect=ValueError("traversal")):
            result = await write_file(self._req(),
                                      data=WriteData(path="../evil.py", content="x"))
        assert isinstance(result, JSONResponse)
        assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_write_file_success(self, tmp_path):
        from luckyd_code.web_routes.files import write_file, WriteData
        target = tmp_path / "out.py"
        with self._patch_resolve(return_value=str(target)):
            result = await write_file(self._req(),
                                      data=WriteData(path=str(target), content="pass"))
        assert result["status"] == "written"
        assert target.read_text() == "pass"

    # edit_file
    @pytest.mark.asyncio
    async def test_edit_file_missing_required_fields(self):
        from luckyd_code.web_routes.files import edit_file, EditData
        from fastapi.responses import JSONResponse
        result = await edit_file(self._req(),
                                 data=EditData(path="", old_string="", new_string=""))
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_edit_file_traversal_blocked(self):
        from luckyd_code.web_routes.files import edit_file, EditData
        from fastapi.responses import JSONResponse
        with self._patch_resolve(side_effect=ValueError("traversal")):
            result = await edit_file(self._req(),
                                     data=EditData(path="../x.py",
                                                   old_string="a", new_string="b"))
        assert isinstance(result, JSONResponse)
        assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_edit_file_not_found(self, tmp_path):
        from luckyd_code.web_routes.files import edit_file, EditData
        from fastapi.responses import JSONResponse
        missing = str(tmp_path / "missing.py")
        with self._patch_resolve(return_value=missing):
            result = await edit_file(self._req(),
                                     data=EditData(path=missing,
                                                   old_string="x", new_string="y"))
        assert isinstance(result, JSONResponse)
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_edit_file_old_string_not_present(self, tmp_path):
        from luckyd_code.web_routes.files import edit_file, EditData
        from fastapi.responses import JSONResponse
        f = tmp_path / "code.py"
        f.write_text("print('hello')")
        with self._patch_resolve(return_value=str(f)):
            result = await edit_file(self._req(),
                                     data=EditData(path=str(f),
                                                   old_string="NOT_THERE",
                                                   new_string="x"))
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_edit_file_success(self, tmp_path):
        from luckyd_code.web_routes.files import edit_file, EditData
        f = tmp_path / "code.py"
        f.write_text("old text here")
        with self._patch_resolve(return_value=str(f)):
            result = await edit_file(self._req(),
                                     data=EditData(path=str(f),
                                                   old_string="old text",
                                                   new_string="new text"))
        assert result["status"] == "edited"
        assert f.read_text() == "new text here"


# ===========================================================================
# 5. web_routes/memories.py
# ===========================================================================

class TestWebRoutesMemories:

    def _state(self):
        state = MagicMock()
        state.context.count_messages.return_value = 3
        state.context.messages = []
        return state

    @pytest.mark.asyncio
    async def test_get_memory(self):
        from luckyd_code.web_routes import memories as mem_mod
        state = self._state()
        with patch.object(mem_mod, "memory_module") as mm:
            mm.load_claude_md.return_value = "# My Memory"
            result = await mem_mod.get_memory(_make_request(state))
        assert result["claude_md"] == "# My Memory"
        assert result["message_count"] == 3

    @pytest.mark.asyncio
    async def test_save_memory_inserts_new_block(self):
        from luckyd_code.web_routes import memories as mem_mod
        from luckyd_code.web_routes.memories import MemorySave
        state = self._state()
        with patch.object(mem_mod, "memory_module"):
            result = await mem_mod.save_memory(_make_request(state),
                                               MemorySave(content="# Updated"))
        assert result["status"] == "saved"
        assert any("<claude-md>" in str(m.get("content", ""))
                   for m in state.context.messages)

    @pytest.mark.asyncio
    async def test_save_memory_replaces_existing_block(self):
        from luckyd_code.web_routes import memories as mem_mod
        from luckyd_code.web_routes.memories import MemorySave
        state = self._state()
        state.context.messages = [
            {"role": "user", "content": "<claude-md>old</claude-md>"}
        ]
        with patch.object(mem_mod, "memory_module"):
            await mem_mod.save_memory(_make_request(state),
                                      MemorySave(content="new"))
        assert "new" in state.context.messages[0]["content"]
        assert "old" not in state.context.messages[0]["content"]

    @pytest.mark.asyncio
    async def test_save_memory_preserves_session_memories(self):
        from luckyd_code.web_routes import memories as mem_mod
        from luckyd_code.web_routes.memories import MemorySave
        state = self._state()
        state.context.messages = [{
            "role": "user",
            "content": "<claude-md>old\n\n<memories>saved</memories></claude-md>"
        }]
        with patch.object(mem_mod, "memory_module"):
            await mem_mod.save_memory(_make_request(state),
                                      MemorySave(content="fresh"))
        saved = state.context.messages[0]["content"]
        assert "<memories>saved</memories>" in saved

    @pytest.mark.asyncio
    async def test_list_memories_no_query(self):
        from luckyd_code.web_routes import memories as mem_mod
        state = self._state()
        state.web_memory_mgr.list_memories.return_value = [{"name": "m1"}]
        result = await mem_mod.list_memories(_make_request(state), q="")
        assert len(result["memories"]) == 1

    @pytest.mark.asyncio
    async def test_list_memories_with_query(self):
        from luckyd_code.web_routes import memories as mem_mod
        state = self._state()
        state.web_memory_mgr.search_memories.return_value = [{"name": "m1", "score": 0.9}]
        result = await mem_mod.list_memories(_make_request(state), q="auth")
        state.web_memory_mgr.search_memories.assert_called_with("auth")
        assert len(result["memories"]) == 1

    @pytest.mark.asyncio
    async def test_save_memory_web(self):
        from luckyd_code.web_routes import memories as mem_mod
        from luckyd_code.web_routes.memories import NamedMemorySave
        state = self._state()
        result = await mem_mod.save_memory_web(
            _make_request(state),
            NamedMemorySave(name="test-mem", content="some content")
        )
        state.web_memory_mgr.save_memory.assert_called_once_with("test-mem", "some content")
        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_delete_memory_web_found(self):
        from luckyd_code.web_routes import memories as mem_mod
        state = self._state()
        state.web_memory_mgr.delete_memory.return_value = True
        result = await mem_mod.delete_memory_web(_make_request(state), name="old-mem")
        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_delete_memory_web_not_found(self):
        from luckyd_code.web_routes import memories as mem_mod
        from fastapi.responses import JSONResponse
        state = self._state()
        state.web_memory_mgr.delete_memory.return_value = False
        result = await mem_mod.delete_memory_web(_make_request(state), name="ghost")
        assert isinstance(result, JSONResponse)
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_get_memory_web_found(self):
        from luckyd_code.web_routes import memories as mem_mod
        state = self._state()
        state.web_memory_mgr.load_memory.return_value = "memory content"
        result = await mem_mod.get_memory_web(_make_request(state), name="my-mem")
        assert result["content"] == "memory content"

    @pytest.mark.asyncio
    async def test_get_memory_web_not_found(self):
        from luckyd_code.web_routes import memories as mem_mod
        from fastapi.responses import JSONResponse
        state = self._state()
        state.web_memory_mgr.load_memory.return_value = None
        result = await mem_mod.get_memory_web(_make_request(state), name="missing")
        assert isinstance(result, JSONResponse)
        assert result.status_code == 404


# ===========================================================================
# 6. web_routes/review.py
# ===========================================================================

class TestWebRoutesReview:

    @pytest.mark.asyncio
    async def test_review_code_returns_diff(self):
        from luckyd_code.web_routes.review import review_code
        with patch("luckyd_code.web_routes.review.review_skill.review_changes",
                   return_value="+ added\n- removed"):
            result = await review_code()
        assert "diff" in result
        assert "added" in result["diff"]

    @pytest.mark.asyncio
    async def test_review_code_no_changes(self):
        from luckyd_code.web_routes.review import review_code
        with patch("luckyd_code.web_routes.review.review_skill.review_changes",
                   return_value="No changes to review."):
            result = await review_code()
        assert result["diff"] == "No changes to review."

    @pytest.mark.asyncio
    async def test_security_review_returns_analysis(self):
        from luckyd_code.web_routes.review import security_review
        with patch("luckyd_code.web_routes.review.security_skill.security_review",
                   return_value="All clear."):
            result = await security_review()
        assert result["analysis"] == "All clear."

    @pytest.mark.asyncio
    async def test_security_review_with_findings(self):
        from luckyd_code.web_routes.review import security_review
        with patch("luckyd_code.web_routes.review.security_skill.security_review",
                   return_value="Warning: hardcoded secret."):
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
    async def test_do_update_pulled_commits(self):
        from luckyd_code.web_routes.update import do_update
        with patch("luckyd_code.web_routes.update.updater.do_update",
                   return_value="3 files changed."):
            result = await do_update()
        assert result["status"] == "ok"
        assert "3 files" in result["message"]


# ===========================================================================
# 8. web_routes/background.py
# ===========================================================================

class TestWebRoutesBackground:

    @pytest.mark.asyncio
    async def test_background_list_success(self):
        from luckyd_code.web_routes.background import background_list
        state = MagicMock()
        mock_bg = MagicMock()
        mock_bg.get_status.return_value = [{"id": "t1", "status": "done"}]
        with patch("luckyd_code.background.BackgroundAgent",
                   return_value=mock_bg):
            result = await background_list(_make_request(state))
        assert result["tasks"][0]["id"] == "t1"

    @pytest.mark.asyncio
    async def test_background_list_exception_returns_500(self):
        from luckyd_code.web_routes.background import background_list
        from fastapi.responses import JSONResponse
        with patch("luckyd_code.background.BackgroundAgent",
                   side_effect=RuntimeError("init failed")):
            result = await background_list(_make_request())
        assert isinstance(result, JSONResponse)
        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_background_start_empty_task_returns_400(self):
        from luckyd_code.web_routes.background import background_start, BackgroundStart
        from fastapi.responses import JSONResponse
        mock_bg = MagicMock()
        with patch("luckyd_code.background.BackgroundAgent",
                   return_value=mock_bg):
            result = await background_start(_make_request(), BackgroundStart(task=""))
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_background_start_success(self):
        from luckyd_code.web_routes.background import background_start, BackgroundStart
        state = MagicMock()
        mock_bg = MagicMock()
        mock_bg.start_task.return_value = "task-abc"
        with patch("luckyd_code.background.BackgroundAgent",
                   return_value=mock_bg):
            result = await background_start(_make_request(state),
                                            BackgroundStart(task="analyse code"))
        assert result["task_id"] == "task-abc"
        assert result["status"] == "started"

    @pytest.mark.asyncio
    async def test_background_start_exception_returns_500(self):
        from luckyd_code.web_routes.background import background_start, BackgroundStart
        from fastapi.responses import JSONResponse
        with patch("luckyd_code.background.BackgroundAgent",
                   side_effect=RuntimeError("boom")):
            result = await background_start(_make_request(),
                                            BackgroundStart(task="do it"))
        assert isinstance(result, JSONResponse)
        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_background_status_found(self):
        from luckyd_code.web_routes.background import background_status
        state = MagicMock()
        mock_bg = MagicMock()
        mock_bg.get_status.return_value = [{"id": "t1", "status": "running"}]
        with patch("luckyd_code.background.BackgroundAgent",
                   return_value=mock_bg):
            result = await background_status(_make_request(state), task_id="t1")
        assert result["task"]["id"] == "t1"

    @pytest.mark.asyncio
    async def test_background_status_not_found_returns_404(self):
        from luckyd_code.web_routes.background import background_status
        from fastapi.responses import JSONResponse
        mock_bg = MagicMock()
        mock_bg.get_status.return_value = []
        with patch("luckyd_code.background.BackgroundAgent",
                   return_value=mock_bg):
            result = await background_status(_make_request(), task_id="ghost")
        assert isinstance(result, JSONResponse)
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_background_status_exception_returns_500(self):
        from luckyd_code.web_routes.background import background_status
        from fastapi.responses import JSONResponse
        with patch("luckyd_code.background.BackgroundAgent",
                   side_effect=RuntimeError("db error")):
            result = await background_status(_make_request(), task_id="t1")
        assert isinstance(result, JSONResponse)
        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_background_result_found(self):
        from luckyd_code.web_routes.background import background_result
        state = MagicMock()
        mock_bg = MagicMock()
        mock_bg.get_result.return_value = "Analysis complete."
        with patch("luckyd_code.background.BackgroundAgent",
                   return_value=mock_bg):
            result = await background_result(_make_request(state), task_id="t1")
        assert result["result"] == "Analysis complete."

    @pytest.mark.asyncio
    async def test_background_result_not_available_returns_404(self):
        from luckyd_code.web_routes.background import background_result
        from fastapi.responses import JSONResponse
        mock_bg = MagicMock()
        mock_bg.get_result.return_value = None
        with patch("luckyd_code.background.BackgroundAgent",
                   return_value=mock_bg):
            result = await background_result(_make_request(), task_id="t1")
        assert isinstance(result, JSONResponse)
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_background_result_exception_returns_500(self):
        from luckyd_code.web_routes.background import background_result
        from fastapi.responses import JSONResponse
        with patch("luckyd_code.background.BackgroundAgent",
                   side_effect=RuntimeError("crash")):
            result = await background_result(_make_request(), task_id="t1")
        assert isinstance(result, JSONResponse)
        assert result.status_code == 500
