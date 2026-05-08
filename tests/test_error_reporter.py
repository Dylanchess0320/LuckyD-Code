"""Tests for error_reporter.py — safe, opt-in error telemetry."""

from __future__ import annotations

import json
import os
import platform
import sys
import webbrowser
from unittest.mock import patch

import pytest

from luckyd_code.error_reporter import (
    _sanitize_line,
    _clean_path,
    sanitize_traceback,
    already_reported,
    _error_fingerprint,
    _get_reporting_mode,
    _ask_and_open,
    _log_to_file,
    capture_unhandled,
    capture_and_log_only,
    build_issue_url,
    _seen_hashes,
)


# -----------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_global_state():
    """Wipe _seen_hashes before & after each test."""
    _seen_hashes.clear()
    yield
    _seen_hashes.clear()


@pytest.fixture
def sample_exc():
    try:
        raise ValueError(
            "API key 'sk-abcdefghijklmnopqrstuvwxyz123456' not accepted"
        )
    except ValueError as e:
        return e


@pytest.fixture
def deep_exc():
    """Exception with a multi-level traceback."""
    def inner():
        d = {}
        return d["missing_key"]
    try:
        inner()
    except KeyError as e:
        return e


# -----------------------------------------------------------------------
# _sanitize_line
# -----------------------------------------------------------------------


class TestSanitizeLine:
    def test_removes_key_value_pair(self):
        result = _sanitize_line("DEEPSEEK_API_KEY=sk-abcdef12345 extra")
        assert "sk-abcdef12345" not in result
        assert "[REDACTED]" in result
        assert "extra" in result  # non-secret text preserved

    def test_removes_bare_key(self):
        result = _sanitize_line("Error with DEEPSEEK_API_KEY setup")
        assert "[REDACTED]" in result
        assert "DEEPSEEK_API_KEY" not in result

    def test_passes_clean_lines_through(self):
        line = "import os; print('hello')"
        assert _sanitize_line(line) == line

    def test_handles_generic_secret(self):
        result = _sanitize_line("GITHUB_TOKEN=ghp_12345secret")
        assert "ghp_12345secret" not in result
        assert "[REDACTED]" in result


# -----------------------------------------------------------------------
# _clean_path
# -----------------------------------------------------------------------


class TestCleanPath:
    def test_cwd_prefix(self, temp_project_dir):
        from luckyd_code._data_dir import project_data_path
        p = project_data_path("foo", "bar.py")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("")

        # Should detect it as <cwd>/...
        result = _clean_path(str(p))
        assert "<cwd>" in result or p.name in result

    def test_home_prefix(self):
        home = os.path.expanduser("~")
        f = os.path.join(home, "test_file.py")
        result = _clean_path(f)
        assert "test_file.py" in result

    def test_site_packages(self):
        path = "/usr/lib/python3.12/site-packages/requests/api.py"
        result = _clean_path(path)
        assert "<venv>" in result
        assert "site-packages" in result

    def test_unrecognised_falls_back_to_basename(self):
        result = _clean_path("/some/random/path/module.py")
        assert result == "module.py"


# -----------------------------------------------------------------------
# sanitize_traceback
# -----------------------------------------------------------------------


class TestSanitizeTraceback:
    def test_strips_secrets(self, sample_exc):
        data = sanitize_traceback(sample_exc)
        # The key value must be redacted
        assert "abcdefghijklmnopqrstuvwxyz" not in data["traceback"]
        assert "abcdefghijklmnopqrstuvwxyz" not in data["error_message"]
        assert "[REDACTED]" in data["traceback"]

    def test_includes_metadata(self, sample_exc):
        data = sanitize_traceback(sample_exc)
        assert data["error_type"] == "ValueError"
        assert data["python_version"] == sys.version.split()[0]
        assert data["os"] == platform.platform()
        assert data["app_version"] != ""

    def test_cleans_file_paths(self, deep_exc):
        data = sanitize_traceback(deep_exc)
        tb = data["traceback"]
        # Should not contain absolute CWD path
        cwd = os.getcwd()
        assert cwd not in tb


# -----------------------------------------------------------------------
# Deduplication
# -----------------------------------------------------------------------


class TestDeduplication:
    def test_first_call_returns_false(self, sample_exc):
        assert already_reported(sample_exc) is False

    def test_second_call_returns_true(self, sample_exc):
        already_reported(sample_exc)
        assert already_reported(sample_exc) is True

    def test_different_errors_return_false(self, sample_exc, deep_exc):
        already_reported(sample_exc)
        assert already_reported(deep_exc) is False

    def test_fingerprint_is_stable(self, sample_exc):
        fp1 = _error_fingerprint(sample_exc)
        fp2 = _error_fingerprint(sample_exc)
        assert fp1 == fp2


# -----------------------------------------------------------------------
# build_issue_url
# -----------------------------------------------------------------------


class TestBuildIssueUrl:
    def test_contains_github_base_url(self, sample_exc):
        data = sanitize_traceback(sample_exc)
        url = build_issue_url(data)
        assert url.startswith("https://github.com/Dylanchess0320/LuckyD-Code/issues/new")

    def test_contains_error_type(self, sample_exc):
        data = sanitize_traceback(sample_exc)
        url = build_issue_url(data)
        assert "ValueError" in url

    def test_url_is_valid(self, sample_exc):
        data = sanitize_traceback(sample_exc)
        url = build_issue_url(data)
        # Should not raise on parsing
        import urllib.parse
        parts = urllib.parse.urlparse(url)
        assert parts.scheme == "https"
        assert parts.netloc == "github.com"


# -----------------------------------------------------------------------
# _get_reporting_mode
# -----------------------------------------------------------------------


class TestGetReportingMode:
    def test_default_is_ask(self, monkeypatch):
        monkeypatch.setattr(
            "luckyd_code.error_reporter._get_reporting_mode",
            lambda: "ask",
        )
        # Actually call the real one via a clean path
        from luckyd_code import settings
        with patch.object(settings, "load_settings", return_value={}):
            assert _get_reporting_mode() == "ask"

    def test_off_mode(self, monkeypatch):
        from luckyd_code import settings
        with patch.object(settings, "load_settings", return_value={"error_reporting": "off"}):
            assert _get_reporting_mode() == "off"

    def test_log_mode(self, monkeypatch):
        from luckyd_code import settings
        with patch.object(settings, "load_settings", return_value={"error_reporting": "log"}):
            assert _get_reporting_mode() == "log"


# -----------------------------------------------------------------------
# _log_to_file
# -----------------------------------------------------------------------


class TestLogToFile:
    def test_creates_file(self, temp_data_dir, sample_exc):
        # temp_data_dir ensures data_path() resolves to the temp location
        fpath = _log_to_file(sample_exc)
        assert fpath.exists()
        data = json.loads(fpath.read_text())
        assert data["error_type"] == "ValueError"

    def test_no_secrets_in_file(self, temp_data_dir, sample_exc):
        fpath = _log_to_file(sample_exc)
        content = fpath.read_text()
        assert "abcdefghijklmnopqrstuvwxyz" not in content
        assert "[REDACTED]" in content


# -----------------------------------------------------------------------
# _ask_and_open
# -----------------------------------------------------------------------


class TestAskAndOpen:
    def test_user_declines(self, sample_exc):
        with patch("builtins.input", return_value="n"):
            result = _ask_and_open(sample_exc)
        assert result is False

    def test_user_accepts_default(self, sample_exc):
        with patch("builtins.input", return_value=""):
            with patch.object(webbrowser, "open_new_tab") as mock_open:
                # Prevent autonomous pipeline from running (no live API calls)
                with patch("luckyd_code.error_reporter._get_autonomous_mode", return_value="off"):
                    result = _ask_and_open(sample_exc)
        assert result is True
        mock_open.assert_called_once()
        url = mock_open.call_args[0][0]
        assert "github.com" in url

    def test_user_accepts_yes(self, sample_exc):
        with patch("builtins.input", return_value="yes"):
            with patch.object(webbrowser, "open_new_tab") as mock_open:
                with patch("luckyd_code.error_reporter._get_autonomous_mode", return_value="off"):
                    result = _ask_and_open(sample_exc)
        assert result is True
        mock_open.assert_called_once()

    def test_eof_returns_false(self, sample_exc):
        with patch("builtins.input", side_effect=EOFError):
            result = _ask_and_open(sample_exc)
        assert result is False

    def test_keyboard_interrupt_returns_false(self, sample_exc):
        with patch("builtins.input", side_effect=KeyboardInterrupt):
            result = _ask_and_open(sample_exc)
        assert result is False

    def test_webbrowser_failure_prints_url(self, sample_exc):
        with patch("builtins.input", return_value="y"):
            with patch.object(webbrowser, "open_new_tab", side_effect=Exception("browser fail")):
                with patch("luckyd_code.error_reporter._get_autonomous_mode", return_value="off"):
                    result = _ask_and_open(sample_exc)
        # Returns False because the browser could not be opened
        assert result is False


# -----------------------------------------------------------------------
# capture_unhandled (top-level API)
# -----------------------------------------------------------------------


class TestCaptureUnhandled:
    def test_off_mode_does_nothing(self, sample_exc):
        from luckyd_code import settings
        with patch.object(settings, "load_settings", return_value={"error_reporting": "off"}):
            result = capture_unhandled(sample_exc)
        assert result is False

    def test_log_mode_writes_file(self, temp_data_dir, sample_exc):
        from luckyd_code import settings
        with patch.object(settings, "load_settings", return_value={"error_reporting": "log"}):
            result = capture_unhandled(sample_exc)
        assert result is True

    def test_ask_mode_calls_ask_and_open(self, sample_exc):
        from luckyd_code import settings
        with patch.object(settings, "load_settings", return_value={"error_reporting": "ask"}):
            with patch("luckyd_code.error_reporter._ask_and_open", return_value=True) as mock:
                result = capture_unhandled(sample_exc)
        assert result is True
        mock.assert_called_once_with(sample_exc)

    def test_dedup_in_ask_mode(self, sample_exc):
        from luckyd_code import settings
        with patch.object(settings, "load_settings", return_value={"error_reporting": "ask"}):
            with patch("luckyd_code.error_reporter._ask_and_open", return_value=True) as mock:
                capture_unhandled(sample_exc)
                capture_unhandled(sample_exc)
        # Only called once due to dedup
        assert mock.call_count == 1


# -----------------------------------------------------------------------
# capture_and_log_only
# -----------------------------------------------------------------------


class TestCaptureAndLogOnly:
    def test_logs_error(self, sample_exc):
        from luckyd_code.log import get_logger
        with patch.object(get_logger(), "error") as mock_log:
            capture_and_log_only(sample_exc)
        mock_log.assert_called_once()


# -----------------------------------------------------------------------
# Edge cases
# -----------------------------------------------------------------------


class TestEdgeCases:
    def test_syntax_error(self):
        try:
            eval("x === y")
        except SyntaxError as e:
            data = sanitize_traceback(e)
        assert data["error_type"] == "SyntaxError"

    def test_import_error(self):
        try:
            import non_existent_module_xyz  # noqa
        except ModuleNotFoundError as e:
            data = sanitize_traceback(e)
        assert data["error_type"] == "ModuleNotFoundError"

    def test_empty_traceback(self):
        """Exception with no traceback (e.g. raised manually with no stack)."""
        exc = RuntimeError("bare error")
        exc.__traceback__ = None
        data = sanitize_traceback(exc)
        assert data["error_type"] == "RuntimeError"
        assert data["error_message"] == "bare error"

    def test_very_long_message(self):
        exc = ValueError("x" * 5000)
        data = sanitize_traceback(exc)
        url = build_issue_url(data)
        # The URL should be at least somewhat manageable
        assert len(url) < 10000
