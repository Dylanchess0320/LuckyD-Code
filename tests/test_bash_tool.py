"""Tests for tools/bash.py — safety guards and command rewriting."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from luckyd_code.tools.bash import (
    BLOCKED_PATTERNS,
    INTERACTIVE_COMMANDS,
    BashTool,
    _fix_unix_ping,
    _fix_windows_cmd,
    _is_dangerous,
    reset_shell_cache,
)


class TestIsDangerous:
    def test_allows_safe_command(self):
        assert _is_dangerous("ls -la") is None

    def test_blocks_rm_rf_root(self):
        result = _is_dangerous("rm -rf /")
        assert result is not None
        assert "blocked" in result.lower()

    def test_blocks_fork_bomb(self):
        result = _is_dangerous(":(){ :|:& };:")
        assert result is not None

    def test_blocks_mkfs(self):
        result = _is_dangerous("mkfs.ext4 /dev/sdb")
        assert result is not None

    def test_blocks_dd(self):
        result = _is_dangerous("dd if=/dev/zero of=/dev/sda")
        assert result is not None

    def test_blocks_vim(self):
        result = _is_dangerous("vim file.py")
        assert result is not None

    def test_blocks_ssh(self):
        result = _is_dangerous("ssh user@host")
        assert result is not None

    def test_blocks_nano(self):
        result = _is_dangerous("nano config.txt")
        assert result is not None

    def test_allows_echo(self):
        assert _is_dangerous("echo hello") is None

    def test_allows_pytest(self):
        assert _is_dangerous("pytest tests/") is None

    def test_case_insensitive(self):
        result = _is_dangerous("RM -RF /")
        assert result is not None

    def test_blocks_sudo(self):
        result = _is_dangerous("sudo apt install vim")
        assert result is not None

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
    def test_blocks_windows_date_on_windows(self):
        result = _is_dangerous("date")
        assert result is not None


class TestFixWindowsCmd:
    def test_date_alone(self):
        assert _fix_windows_cmd("date") == "date /T"

    def test_date_case_insensitive(self):
        assert _fix_windows_cmd("DATE") == "date /T"

    def test_date_already_has_flag(self):
        result = _fix_windows_cmd("date /T")
        assert result == "date /T"

    def test_time_alone(self):
        assert _fix_windows_cmd("time") == "time /T"

    def test_pause(self):
        assert _fix_windows_cmd("pause") == "echo."

    def test_choice(self):
        assert _fix_windows_cmd("choice") == "choice /N /T 0 /D Y"

    def test_clip(self):
        assert _fix_windows_cmd("clip") == "echo.| clip"

    def test_ping_without_n(self):
        result = _fix_windows_cmd("ping google.com")
        assert "-n 4" in result
        assert "google.com" in result

    def test_ping_with_n_flag_unchanged(self):
        result = _fix_windows_cmd("ping -n 10 google.com")
        assert "-n 4" not in result

    def test_safe_command_unchanged(self):
        assert _fix_windows_cmd("dir /W") == "dir /W"

    def test_echo_unchanged(self):
        assert _fix_windows_cmd("echo hello") == "echo hello"


class TestFixUnixPing:
    def test_adds_c_flag(self):
        result = _fix_unix_ping("ping google.com")
        assert "-c 4" in result
        assert "google.com" in result

    def test_already_has_c_flag(self):
        result = _fix_unix_ping("ping -c 10 google.com")
        assert "-c 4" not in result

    def test_non_ping_unchanged(self):
        cmd = "curl https://example.com"
        assert _fix_unix_ping(cmd) == cmd

    def test_ping_with_host_only(self):
        result = _fix_unix_ping("ping 8.8.8.8")
        assert "-c 4" in result


class TestResetShellCache:
    def test_clears_cache(self):
        import luckyd_code.tools.bash as bash_mod
        bash_mod._SHELL_CACHE = MagicMock()
        reset_shell_cache()
        assert bash_mod._SHELL_CACHE is None


class TestBashToolMeta:
    def test_name(self):
        assert BashTool.name == "Bash"

    def test_permission_risk(self):
        assert BashTool.permission_risk == "high"

    def test_parameters_has_command(self):
        assert "command" in BashTool.parameters["properties"]

    def test_command_is_required(self):
        assert "command" in BashTool.parameters["required"]

    def test_description_exists(self):
        assert BashTool.description

    def test_is_dangerous_returns_error_string_on_block(self):
        tool = BashTool()
        # _is_dangerous is called inside run(), but we test it directly
        result = _is_dangerous("rm -rf /")
        assert isinstance(result, str)
        assert len(result) > 0
