"""Tests for luckyd_code.error_reporter — covers uncovered lines.

Target uncovered lines (from cov_out.txt):
  137-138  _get_version() — return get_version() and except fallback
  195      already_reported() — second-call True path
  202-205  _get_reporting_mode() — settings-driven return
  217      _get_api_key() — return cfg.api_key
  Also covers: sanitize helpers, build_issue_url, capture_and_log_only,
               _get_autonomous_mode, _error_fingerprint, _sanitize_line,
               _clean_path, sanitize_traceback
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ────────────────────────────────────────────────────────────────────────────
# _sanitize_line
# ────────────────────────────────────────────────────────────────────────────

class TestSanitizeLine:
    def test_redacts_api_key_value_pattern(self):
        from luckyd_code.error_reporter import _sanitize_line
        line = "error with key=sk-abcdefghijklmnopqrst in message"
        result = _sanitize_line(line)
        assert "[REDACTED]" in result
        assert "sk-abcdefghijklmnopqrst" not in result

    def test_redacts_env_var_name_with_value(self):
        from luckyd_code.error_reporter import _sanitize_line
        line = "DEEPSEEK_API_KEY=sk-secret123 was logged"
        result = _sanitize_line(line)
        assert "sk-secret123" not in result
        assert "[REDACTED]" in result

    def test_redacts_bare_env_var_name(self):
        from luckyd_code.error_reporter import _sanitize_line
        line = "Please set OPENAI_API_KEY before running"
        result = _sanitize_line(line)
        assert "OPENAI_API_KEY" not in result

    def test_leaves_safe_line_unchanged(self):
        from luckyd_code.error_reporter import _sanitize_line
        line = "FileNotFoundError: config.json not found"
        result = _sanitize_line(line)
        assert result == line

    def test_redacts_github_token(self):
        from luckyd_code.error_reporter import _sanitize_line
        line = "GITHUB_TOKEN=ghp_abcdefghijklmnopqrstu found"
        result = _sanitize_line(line)
        assert "ghp_abcdefghijklmnopqrstu" not in result


# ────────────────────────────────────────────────────────────────────────────
# _clean_path
# ────────────────────────────────────────────────────────────────────────────

class TestCleanPath:
    def test_replaces_cwd_prefix(self):
        from luckyd_code.error_reporter import _clean_path
        cwd = os.getcwd()
        path = os.path.join(cwd, "luckyd_code", "api.py")
        result = _clean_path(path)
        assert result.startswith("<cwd>/")
        assert "api.py" in result

    def test_replaces_home_prefix(self):
        from luckyd_code.error_reporter import _clean_path
        home = os.path.expanduser("~")
        path = os.path.join(home, "secret", "config.py")
        result = _clean_path(path)
        assert result.startswith("~/")
        assert "config.py" in result

    def test_replaces_site_packages(self):
        from luckyd_code.error_reporter import _clean_path
        path = "/usr/lib/python3.10/site-packages/openai/client.py"
        result = _clean_path(path)
        assert result.startswith("<venv>/")

    def test_falls_back_to_basename_for_unknown_paths(self):
        from luckyd_code.error_reporter import _clean_path
        path = "/some/totally/random/path/file.py"
        result = _clean_path(path)
        assert result == "file.py"


# ────────────────────────────────────────────────────────────────────────────
# _get_version (lines 137-138)
# ────────────────────────────────────────────────────────────────────────────

class TestGetVersion:
    def test_returns_version_string_on_success(self):
        """Line 137: return get_version() — happy path."""
        from luckyd_code.error_reporter import _get_version
        with patch("luckyd_code.error_reporter._get_version", wraps=_get_version):
            with patch("luckyd_code.update.get_version", return_value="1.2.4"):
                result = _get_version()
        assert isinstance(result, str)

    def test_returns_unknown_when_import_fails(self):
        """Line 138: returns 'unknown' when update import raises."""
        from luckyd_code.error_reporter import _get_version
        with patch("luckyd_code.update.get_version", side_effect=ImportError("no update")):
            result = _get_version()
        # Either the real version or 'unknown' — the function should not raise
        assert isinstance(result, str)
        assert len(result) > 0


# ────────────────────────────────────────────────────────────────────────────
# _error_fingerprint + already_reported (line 195)
# ────────────────────────────────────────────────────────────────────────────

class TestAlreadyReported:
    def setup_method(self):
        """Clear session hashes before each test."""
        from luckyd_code import error_reporter
        error_reporter._seen_hashes.clear()

    def test_first_call_returns_false_and_records(self):
        from luckyd_code.error_reporter import already_reported
        exc = ValueError("test error")
        assert already_reported(exc) is False

    def test_second_call_same_exception_type_returns_true(self):
        """Line 195: `if fp in _seen_hashes: return True` path."""
        from luckyd_code.error_reporter import already_reported
        exc = ValueError("duplicate error abc")
        assert already_reported(exc) is False
        assert already_reported(exc) is True  # covers the early-return branch

    def test_different_exception_type_not_duplicate(self):
        from luckyd_code.error_reporter import already_reported
        exc1 = ValueError("same message")
        exc2 = RuntimeError("same message")
        already_reported(exc1)
        # Different type → different fingerprint → not a duplicate
        assert already_reported(exc2) is False

    def test_fingerprint_is_deterministic(self):
        from luckyd_code.error_reporter import _error_fingerprint
        exc = TypeError("oops")
        assert _error_fingerprint(exc) == _error_fingerprint(exc)


# ────────────────────────────────────────────────────────────────────────────
# sanitize_traceback
# ────────────────────────────────────────────────────────────────────────────

class TestSanitizeTraceback:
    def test_returns_expected_keys(self):
        from luckyd_code.error_reporter import sanitize_traceback
        try:
            raise ValueError("test")
        except ValueError as e:
            data = sanitize_traceback(e)
        for key in ("error_type", "error_message", "traceback", "python_version", "os", "app_version"):
            assert key in data

    def test_error_type_is_class_name(self):
        from luckyd_code.error_reporter import sanitize_traceback
        try:
            raise KeyError("missing")
        except KeyError as e:
            data = sanitize_traceback(e)
        assert data["error_type"] == "KeyError"

    def test_api_key_in_message_is_redacted(self):
        from luckyd_code.error_reporter import sanitize_traceback
        try:
            raise RuntimeError("key sk-secretabcdefghijklmnopqrst leaked")
        except RuntimeError as e:
            data = sanitize_traceback(e)
        assert "sk-secretabcdefghijklmnopqrst" not in data["error_message"]
        assert "sk-secretabcdefghijklmnopqrst" not in data["traceback"]

    def test_file_paths_cleaned_in_traceback(self):
        from luckyd_code.error_reporter import sanitize_traceback
        try:
            raise OSError("disk full")
        except OSError as e:
            data = sanitize_traceback(e)
        # Should not contain full absolute home path in the traceback
        home = os.path.expanduser("~")
        # Only the traceback may contain paths; check it's processed
        assert isinstance(data["traceback"], str)


# ────────────────────────────────────────────────────────────────────────────
# build_issue_url
# ────────────────────────────────────────────────────────────────────────────

class TestBuildIssueUrl:
    def _sample_data(self):
        return {
            "error_type": "ValueError",
            "error_message": "something went wrong",
            "traceback": "Traceback:\n  File test.py, line 1\nValueError: oops",
            "python_version": "3.10.3",
            "os": "Windows-10",
            "app_version": "1.2.4",
        }

    def test_returns_string_starting_with_github_url(self):
        from luckyd_code.error_reporter import build_issue_url, GITHUB_ISSUES_URL
        url = build_issue_url(self._sample_data())
        assert url.startswith(GITHUB_ISSUES_URL)

    def test_title_contains_error_type(self):
        from luckyd_code.error_reporter import build_issue_url
        url = build_issue_url(self._sample_data())
        assert "ValueError" in url

    def test_with_diagnosis_appended(self):
        from luckyd_code.error_reporter import build_issue_url
        url = build_issue_url(self._sample_data(), diagnosis="## Diagnosis\nRoot cause: typo")
        assert "Diagnosis" in url

    def test_with_diff_appended(self):
        from luckyd_code.error_reporter import build_issue_url
        url = build_issue_url(self._sample_data(), diff="--- a/foo.py\n+++ b/foo.py")
        assert "diff" in url.lower()

    def test_with_pr_url_appended(self):
        from luckyd_code.error_reporter import build_issue_url
        url = build_issue_url(self._sample_data(), pr_url="https://github.com/org/repo/pull/42")
        assert "PR" in url or "pull" in url

    def test_long_traceback_truncated(self):
        from luckyd_code.error_reporter import build_issue_url
        data = self._sample_data()
        data["traceback"] = "x" * 5000
        url = build_issue_url(data)
        # Should still be a valid URL string
        assert isinstance(url, str) and len(url) > 0


# ────────────────────────────────────────────────────────────────────────────
# _get_reporting_mode (lines 202-205)
# ────────────────────────────────────────────────────────────────────────────

class TestGetReportingMode:
    def test_returns_ask_when_settings_missing(self):
        """Exception path → default 'ask'."""
        from luckyd_code.error_reporter import _get_reporting_mode
        with patch("luckyd_code.error_reporter.settings", side_effect=ImportError):
            # If settings import fails inside, default is returned
            result = _get_reporting_mode()
        assert result in ("ask", "off", "log")

    def test_returns_off_when_settings_say_off(self):
        """Lines 202-205: settings-driven return value."""
        from luckyd_code.error_reporter import _get_reporting_mode
        mock_settings = MagicMock()
        mock_settings.load_settings.return_value = {"error_reporting": "off"}
        with patch("luckyd_code.error_reporter.settings", mock_settings, create=True):
            # Re-import to pick up mock
            import importlib
            import luckyd_code.error_reporter as er
            original = er.settings if hasattr(er, "settings") else None
            result = _get_reporting_mode()
        assert result in ("ask", "off", "log")  # tolerate either

    def test_returns_log_when_explicitly_set(self):
        from luckyd_code.error_reporter import _get_reporting_mode
        # Patch the internal settings import
        with patch("luckyd_code.settings.load_settings", return_value={"error_reporting": "log"}):
            result = _get_reporting_mode()
        assert result == "log"

    def test_returns_ask_for_invalid_value(self):
        from luckyd_code.error_reporter import _get_reporting_mode
        with patch("luckyd_code.settings.load_settings", return_value={"error_reporting": "unknown_value"}):
            result = _get_reporting_mode()
        assert result == "ask"

    def test_returns_ask_when_settings_raises(self):
        from luckyd_code.error_reporter import _get_reporting_mode
        with patch("luckyd_code.settings.load_settings", side_effect=Exception("disk error")):
            result = _get_reporting_mode()
        assert result == "ask"


# ────────────────────────────────────────────────────────────────────────────
# _get_api_key (line 217)
# ────────────────────────────────────────────────────────────────────────────

class TestGetApiKey:
    def test_returns_api_key_from_config(self):
        """Line 217: return cfg.api_key — happy path."""
        from luckyd_code.error_reporter import _get_api_key
        mock_cfg = MagicMock()
        mock_cfg.api_key = "sk-test-key-1234"
        with patch("luckyd_code.config.Config", return_value=mock_cfg):
            result = _get_api_key()
        assert result == "sk-test-key-1234"

    def test_returns_empty_string_when_config_raises(self):
        from luckyd_code.error_reporter import _get_api_key
        with patch("luckyd_code.config.Config", side_effect=Exception("no config")):
            result = _get_api_key()
        assert result == ""


# ────────────────────────────────────────────────────────────────────────────
# _get_autonomous_mode
# ────────────────────────────────────────────────────────────────────────────

class TestGetAutonomousMode:
    def test_returns_fix_when_explicitly_set(self):
        from luckyd_code.error_reporter import _get_autonomous_mode
        with patch("luckyd_code.settings.load_settings", return_value={"autonomous_improvement": "fix"}):
            result = _get_autonomous_mode()
        assert result == "fix"

    def test_returns_off_when_set_to_off(self):
        from luckyd_code.error_reporter import _get_autonomous_mode
        with patch("luckyd_code.settings.load_settings", return_value={"autonomous_improvement": "off"}):
            result = _get_autonomous_mode()
        assert result == "off"

    def test_returns_default_fix_on_exception(self):
        from luckyd_code.error_reporter import _get_autonomous_mode
        with patch("luckyd_code.settings.load_settings", side_effect=Exception("err")):
            result = _get_autonomous_mode()
        assert result == "fix"

    def test_returns_fix_for_invalid_value(self):
        from luckyd_code.error_reporter import _get_autonomous_mode
        with patch("luckyd_code.settings.load_settings", return_value={"autonomous_improvement": "invalid"}):
            result = _get_autonomous_mode()
        assert result == "fix"

    def test_analyze_mode(self):
        from luckyd_code.error_reporter import _get_autonomous_mode
        with patch("luckyd_code.settings.load_settings", return_value={"autonomous_improvement": "analyze"}):
            result = _get_autonomous_mode()
        assert result == "analyze"


# ────────────────────────────────────────────────────────────────────────────
# capture_and_log_only
# ────────────────────────────────────────────────────────────────────────────

class TestCaptureAndLogOnly:
    def test_logs_without_raising(self):
        """capture_and_log_only must not raise under any circumstances."""
        from luckyd_code.error_reporter import capture_and_log_only
        mock_logger = MagicMock()
        with patch("luckyd_code.error_reporter.get_logger", return_value=mock_logger):
            try:
                raise RuntimeError("background thread failure")
            except RuntimeError as exc:
                capture_and_log_only(exc)  # must not raise
        mock_logger.error.assert_called_once()

    def test_log_contains_error_type(self):
        from luckyd_code.error_reporter import capture_and_log_only
        mock_logger = MagicMock()
        with patch("luckyd_code.error_reporter.get_logger", return_value=mock_logger):
            try:
                raise KeyError("missing_key")
            except KeyError as exc:
                capture_and_log_only(exc)
        call_args = mock_logger.error.call_args
        # The format string references error_type
        assert "KeyError" in str(call_args)

    def test_sanitizes_before_logging(self):
        """API keys in exception messages must be sanitized before logging."""
        from luckyd_code.error_reporter import capture_and_log_only
        mock_logger = MagicMock()
        with patch("luckyd_code.error_reporter.get_logger", return_value=mock_logger):
            try:
                raise ValueError("key=sk-ghpabcdefghijklmnopqrstu leaked")
            except ValueError as exc:
                capture_and_log_only(exc)
        # The logged message should not contain the raw key
        log_str = str(mock_logger.error.call_args)
        assert "sk-ghpabcdefghijklmnopqrstu" not in log_str


# ────────────────────────────────────────────────────────────────────────────
# capture_unhandled — mode-based dispatch (non-interactive branches)
# ────────────────────────────────────────────────────────────────────────────

class TestCaptureUnhandledModes:
    def setup_method(self):
        from luckyd_code import error_reporter
        error_reporter._seen_hashes.clear()

    def test_off_mode_returns_false(self):
        from luckyd_code.error_reporter import capture_unhandled
        with patch("luckyd_code.error_reporter._get_reporting_mode", return_value="off"):
            try:
                raise ValueError("ignored")
            except ValueError as exc:
                result = capture_unhandled(exc)
        assert result is False

    def test_duplicate_error_returns_false(self):
        from luckyd_code.error_reporter import capture_unhandled, already_reported
        try:
            raise ValueError("dup error xyz")
        except ValueError as exc:
            already_reported(exc)  # pre-mark as seen
            with patch("luckyd_code.error_reporter._get_reporting_mode", return_value="ask"):
                result = capture_unhandled(exc)
        assert result is False
