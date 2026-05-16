"""Tests for tools/shell_detect.py."""

import os
import sys
from unittest.mock import patch

import pytest

from luckyd_code.tools.shell_detect import (
    ShellInfo,
    _find_git_bash,
    _find_wsl,
    _is_windows_store_stub,
    detect_shell,
    resolve_shell,
)


class TestIsWindowsStoreStub:
    def test_detects_windowsapps_path(self):
        path = r"C:\Users\user\AppData\Local\Microsoft\WindowsApps\bash.exe"
        assert _is_windows_store_stub(path) is True

    def test_detects_lowercase(self):
        path = r"c:\users\user\appdata\local\microsoft\windowsapps\bash.exe"
        assert _is_windows_store_stub(path) is True

    def test_detects_forward_slashes(self):
        path = "C:/Users/user/AppData/Local/Microsoft/WindowsApps/bash.exe"
        assert _is_windows_store_stub(path) is True

    def test_real_git_bash_not_stub(self):
        path = r"C:\Program Files\Git\bin\bash.exe"
        assert _is_windows_store_stub(path) is False

    def test_unix_path_not_stub(self):
        assert _is_windows_store_stub("/usr/bin/bash") is False


class TestDetectShell:
    @pytest.mark.skipif(sys.platform == "win32", reason="Unix only")
    def test_unix_returns_unix_like(self):
        result = detect_shell()
        assert result.unix_like is True
        assert result.path != ""
        assert isinstance(result.name, str)

    @pytest.mark.skipif(sys.platform == "win32", reason="Unix only")
    def test_unix_uses_shell_env(self, monkeypatch):
        monkeypatch.setenv("SHELL", "/bin/bash")
        with patch("shutil.which", return_value="/bin/bash"):
            result = detect_shell()
        assert result.unix_like is True

    @pytest.mark.skipif(sys.platform == "win32", reason="Unix only")
    def test_unix_falls_back_when_which_fails(self, monkeypatch):
        monkeypatch.setenv("SHELL", "/bin/nonexistent_shell")
        with patch("shutil.which", return_value=None):
            result = detect_shell()
        assert result.unix_like is True

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
    def test_windows_returns_shellinfo(self):
        result = detect_shell()
        assert isinstance(result, ShellInfo)
        assert result.name in ("git_bash", "wsl", "cmd")


class TestFindGitBash:
    def test_returns_none_when_not_found(self):
        with patch("shutil.which", return_value=None):
            with patch("os.path.isfile", return_value=False):
                result = _find_git_bash()
        assert result is None

    def test_skips_windows_store_stub(self):
        stub = r"C:\Users\user\AppData\Local\Microsoft\WindowsApps\bash.exe"
        with patch("shutil.which", return_value=stub):
            with patch("os.path.isfile", return_value=False):
                result = _find_git_bash()
        assert result is None

    def test_returns_path_from_which(self):
        real_path = r"C:\Program Files\Git\bin\bash.exe"
        with patch("shutil.which", return_value=real_path):
            result = _find_git_bash()
        assert result == real_path

    def test_falls_back_to_candidate_paths(self):
        with patch("shutil.which", return_value=None):
            with patch("os.path.isfile", side_effect=lambda p: "Program Files\\Git" in p):
                result = _find_git_bash()
        assert result is not None


class TestFindWsl:
    def test_returns_none_when_not_found(self):
        with patch("shutil.which", return_value=None):
            result = _find_wsl()
        assert result is None

    def test_returns_path_when_found(self):
        with patch("shutil.which", return_value="/usr/bin/wsl"):
            result = _find_wsl()
        assert result == "/usr/bin/wsl"


class TestResolveShell:
    def test_auto_returns_shellinfo(self):
        result = resolve_shell("auto")
        assert isinstance(result, ShellInfo)

    def test_unknown_setting_falls_through_to_auto(self):
        result = resolve_shell("nonexistent_shell")
        assert isinstance(result, ShellInfo)

    def test_cmd_override(self):
        with patch("luckyd_code.tools.shell_detect._find_wsl", return_value=None):
            result = resolve_shell("cmd")
        assert isinstance(result, ShellInfo)

    def test_git_bash_override_when_not_found(self):
        with patch("luckyd_code.tools.shell_detect._find_git_bash", return_value=None):
            # Falls through to auto
            result = resolve_shell("git_bash")
        assert isinstance(result, ShellInfo)

    def test_git_bash_override_when_found(self):
        fake_path = r"C:\Program Files\Git\bin\bash.exe"
        with patch("luckyd_code.tools.shell_detect._find_git_bash", return_value=fake_path):
            result = resolve_shell("git_bash")
        assert result.name == "git_bash"
        assert result.unix_like is True

    def test_wsl_override_when_found(self):
        with patch("luckyd_code.tools.shell_detect._find_wsl", return_value="/usr/bin/wsl"):
            result = resolve_shell("wsl")
        assert result.name == "wsl"
        assert result.unix_like is True


class TestShellInfo:
    def test_dataclass_fields(self):
        s = ShellInfo(name="bash", path="/bin/bash", args=[], unix_like=True, description="Bash")
        assert s.name == "bash"
        assert s.unix_like is True
        assert s.args == []
