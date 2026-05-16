"""Tests for verify.py — full pipeline coverage."""

import os
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from luckyd_code.verify import (
    VerificationResult,
    verify_syntax,
    verify_lint,
    verify_consistency,
    run_verify_pipeline,
    pipeline_all_passed,
    pipeline_feedback,
)


class TestVerificationResultToAgentFeedback:
    def test_passed_feedback(self):
        r = VerificationResult(passed=True, stage="syntax", message="OK", duration_ms=5.0)
        feedback = r.to_agent_feedback()
        assert "✓" in feedback
        assert "syntax" in feedback

    def test_failed_feedback_with_hint(self):
        r = VerificationResult(
            passed=False, stage="syntax", message="Error on line 5",
            fix_hint="Fix the colon", raw_output="SyntaxError: ..."
        )
        feedback = r.to_agent_feedback()
        assert "✗" in feedback
        assert "Fix the colon" in feedback
        assert "SyntaxError" in feedback

    def test_failed_feedback_without_hint(self):
        r = VerificationResult(passed=False, stage="lint", message="Issues found")
        feedback = r.to_agent_feedback()
        assert "✗" in feedback
        assert "Fix:" not in feedback

    def test_failed_feedback_raw_output_truncated(self):
        long_output = "x" * 2000
        r = VerificationResult(passed=False, stage="lint", message="err", raw_output=long_output)
        feedback = r.to_agent_feedback()
        assert len(feedback) < 5000


class TestVerifyLint:
    def test_returns_none_when_no_linter(self, tmp_path):
        f = tmp_path / "code.py"
        f.write_text("x = 1\n")
        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = verify_lint(str(f), project_root=str(tmp_path))
        assert result is None

    def test_passes_when_no_issues(self, tmp_path):
        f = tmp_path / "code.py"
        f.write_text("x = 1\n")
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = ""
        mock.stderr = ""
        with patch("subprocess.run", return_value=mock):
            result = verify_lint(str(f), project_root=str(tmp_path))
        assert result is not None
        assert result.passed is True
        assert result.stage == "lint"

    def test_fails_when_issues_found(self, tmp_path):
        f = tmp_path / "code.py"
        f.write_text("x=1\n")
        mock = MagicMock()
        mock.returncode = 1
        mock.stdout = "E301 missing blank line"
        mock.stderr = ""
        with patch("subprocess.run", return_value=mock):
            result = verify_lint(str(f), project_root=str(tmp_path))
        assert result is not None
        assert result.passed is False
        assert "E301" in result.raw_output

    def test_timeout_falls_through_to_next_linter(self, tmp_path):
        f = tmp_path / "code.py"
        f.write_text("x = 1\n")
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("ruff", 30)):
            result = verify_lint(str(f), project_root=str(tmp_path))
        assert result is None


class TestVerifyConsistency:
    def test_non_python_file_returns_none(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("hello")
        result = verify_consistency(str(f), str(tmp_path))
        assert result is None

    def test_nonexistent_file_returns_none(self, tmp_path):
        result = verify_consistency(str(tmp_path / "nope.py"), str(tmp_path))
        assert result is None

    def test_clean_file_passes(self, tmp_path):
        f = tmp_path / "clean.py"
        f.write_text("def foo(x):\n    return x\n")
        result = verify_consistency(str(f), str(tmp_path))
        assert result is not None
        assert result.passed is True

    def test_syntax_error_returns_none(self, tmp_path):
        f = tmp_path / "bad.py"
        f.write_text("def foo(\n")
        result = verify_consistency(str(f), str(tmp_path))
        assert result is None

    def test_detects_base_exception(self, tmp_path):
        f = tmp_path / "bad.py"
        f.write_text("try:\n    pass\nexcept BaseException:\n    pass\n")
        result = verify_consistency(str(f), str(tmp_path))
        assert result is not None
        assert result.passed is False
        assert "BaseException" in result.raw_output

    def test_detects_mutable_default_list(self, tmp_path):
        f = tmp_path / "bad.py"
        f.write_text("def foo(x=[]):\n    return x\n")
        result = verify_consistency(str(f), str(tmp_path))
        assert result is not None
        assert result.passed is False
        assert "Mutable default" in result.raw_output

    def test_detects_mutable_default_dict(self, tmp_path):
        f = tmp_path / "bad.py"
        f.write_text("def foo(x={}):\n    return x\n")
        result = verify_consistency(str(f), str(tmp_path))
        assert result is not None
        assert result.passed is False


class TestRunVerifyPipeline:
    def test_syntax_failure_stops_pipeline(self, tmp_path):
        f = tmp_path / "bad.py"
        f.write_text("def foo(\n")
        results = run_verify_pipeline(str(f), str(tmp_path))
        assert len(results) == 1
        assert results[0].stage == "syntax"
        assert not results[0].passed

    def test_valid_file_runs_consistency(self, tmp_path):
        f = tmp_path / "ok.py"
        f.write_text("x = 1\n")
        with patch("luckyd_code.verify.verify_lint", return_value=None):
            results = run_verify_pipeline(str(f), str(tmp_path), run_lint=False)
        stages = [r.stage for r in results]
        assert "syntax" in stages
        assert "consistency" in stages

    def test_lint_skipped_when_disabled(self, tmp_path):
        f = tmp_path / "ok.py"
        f.write_text("x = 1\n")
        results = run_verify_pipeline(str(f), str(tmp_path), run_lint=False, run_consistency=False)
        stages = [r.stage for r in results]
        assert "lint" not in stages

    def test_test_runner_blocked_when_not_allowed(self, tmp_path):
        f = tmp_path / "ok.py"
        f.write_text("x = 1\n")
        results = run_verify_pipeline(
            str(f), str(tmp_path),
            run_lint=False, run_consistency=False,
            run_tests=True, test_runner_cmd="rm -rf /"
        )
        test_results = [r for r in results if r.stage == "test"]
        assert len(test_results) == 1
        assert not test_results[0].passed
        assert "Blocked" in test_results[0].message

    def test_test_runner_passes(self, tmp_path):
        f = tmp_path / "ok.py"
        f.write_text("x = 1\n")
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "1 passed"
        mock_proc.stderr = ""
        with patch("subprocess.run", return_value=mock_proc):
            results = run_verify_pipeline(
                str(f), str(tmp_path),
                run_lint=False, run_consistency=False,
                run_tests=True, test_runner_cmd="pytest"
            )
        test_results = [r for r in results if r.stage == "test"]
        assert len(test_results) == 1
        assert test_results[0].passed

    def test_test_runner_fails(self, tmp_path):
        f = tmp_path / "ok.py"
        f.write_text("x = 1\n")
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = "FAILED"
        mock_proc.stderr = ""
        with patch("subprocess.run", return_value=mock_proc):
            results = run_verify_pipeline(
                str(f), str(tmp_path),
                run_lint=False, run_consistency=False,
                run_tests=True, test_runner_cmd="pytest"
            )
        test_results = [r for r in results if r.stage == "test"]
        assert not test_results[0].passed

    def test_test_runner_timeout(self, tmp_path):
        f = tmp_path / "ok.py"
        f.write_text("x = 1\n")
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("pytest", 120)):
            results = run_verify_pipeline(
                str(f), str(tmp_path),
                run_lint=False, run_consistency=False,
                run_tests=True, test_runner_cmd="pytest"
            )
        test_results = [r for r in results if r.stage == "test"]
        assert not test_results[0].passed
        assert "timed out" in test_results[0].message

    def test_test_runner_exception(self, tmp_path):
        f = tmp_path / "ok.py"
        f.write_text("x = 1\n")
        with patch("subprocess.run", side_effect=OSError("no such file")):
            results = run_verify_pipeline(
                str(f), str(tmp_path),
                run_lint=False, run_consistency=False,
                run_tests=True, test_runner_cmd="pytest"
            )
        test_results = [r for r in results if r.stage == "test"]
        assert not test_results[0].passed

    def test_allowed_test_runners(self, tmp_path):
        f = tmp_path / "ok.py"
        f.write_text("x = 1\n")
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        mock_proc.stderr = ""
        for runner in ["pytest", "python -m pytest", "python -m unittest", "tox", "uv run pytest"]:
            with patch("subprocess.run", return_value=mock_proc):
                results = run_verify_pipeline(
                    str(f), str(tmp_path),
                    run_lint=False, run_consistency=False,
                    run_tests=True, test_runner_cmd=runner
                )
            test_results = [r for r in results if r.stage == "test"]
            assert test_results[0].passed, f"Runner '{runner}' should be allowed"
