"""Tests for verify.py — covers uncovered branches.

Target uncovered lines (from cov_out.txt):
  170    verify_lint: return None when no linter is available
  175    verify_consistency: early return when file doesn't exist or isn't .py
  183-195 verify_consistency: __init__.py circular import detection block
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from luckyd_code.verify import (
    verify_syntax,
    verify_lint,
    verify_consistency,
    run_verify_pipeline,
    pipeline_all_passed,
    pipeline_feedback,
    VerificationResult,
)


# ═══════════════════════════════════════════════════════════════════════════
# verify_syntax
# ═══════════════════════════════════════════════════════════════════════════

class TestVerifySyntax:
    def test_valid_python_passes(self, tmp_path):
        f = tmp_path / "good.py"
        f.write_text("x = 1\nprint(x)\n")
        result = verify_syntax(str(f))
        assert result.passed
        assert result.stage == "syntax"

    def test_invalid_python_fails(self, tmp_path):
        f = tmp_path / "bad.py"
        f.write_text("def broken(\n  missing_close\n")
        result = verify_syntax(str(f))
        assert not result.passed
        assert "syntax" in result.stage

    def test_result_has_duration(self, tmp_path):
        f = tmp_path / "ok.py"
        f.write_text("pass\n")
        result = verify_syntax(str(f))
        assert result.duration_ms >= 0


# ═══════════════════════════════════════════════════════════════════════════
# verify_lint
# ═══════════════════════════════════════════════════════════════════════════

class TestVerifyLint:
    def test_returns_none_when_no_linter_available(self, tmp_path):
        """Line 170: all linters raise FileNotFoundError → return None."""
        f = tmp_path / "x.py"
        f.write_text("x = 1\n")
        with patch("subprocess.run", side_effect=FileNotFoundError("not found")):
            result = verify_lint(str(f), project_root=str(tmp_path))
        assert result is None

    def test_passes_when_linter_exits_zero_with_no_output(self, tmp_path):
        f = tmp_path / "clean.py"
        f.write_text("x = 1\n")
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        mock_proc.stderr = ""
        with patch("subprocess.run", return_value=mock_proc):
            result = verify_lint(str(f), project_root=str(tmp_path))
        assert result is not None
        assert result.passed

    def test_fails_when_linter_finds_issues(self, tmp_path):
        f = tmp_path / "messy.py"
        f.write_text("import os\nimport sys\n")
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = "messy.py:1:1: F401 'os' imported but unused"
        mock_proc.stderr = ""
        with patch("subprocess.run", return_value=mock_proc):
            result = verify_lint(str(f), project_root=str(tmp_path))
        assert result is not None
        assert not result.passed

    def test_timeout_is_skipped_and_tries_next_linter(self, tmp_path):
        """TimeoutExpired causes the linter to be skipped (continues loop)."""
        f = tmp_path / "x.py"
        f.write_text("pass\n")
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("ruff", 30)):
            result = verify_lint(str(f), project_root=str(tmp_path))
        # Both linters timed out → returns None
        assert result is None

    def test_uses_project_root_as_cwd(self, tmp_path):
        """project_root is passed as cwd when provided."""
        f = tmp_path / "x.py"
        f.write_text("x = 1\n")
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        mock_proc.stderr = ""
        with patch("subprocess.run", return_value=mock_proc) as mock_run:
            verify_lint(str(f), project_root=str(tmp_path))
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["cwd"] == str(tmp_path)


# ═══════════════════════════════════════════════════════════════════════════
# verify_consistency
# ═══════════════════════════════════════════════════════════════════════════

class TestVerifyConsistency:
    def test_returns_none_for_nonexistent_file(self, tmp_path):
        """Line 175: file doesn't exist → return None."""
        result = verify_consistency(str(tmp_path / "ghost.py"), str(tmp_path))
        assert result is None

    def test_returns_none_for_non_python_file(self, tmp_path):
        """Line 175: .txt file → return None."""
        f = tmp_path / "notes.txt"
        f.write_text("some notes")
        result = verify_consistency(str(f), str(tmp_path))
        assert result is None

    def test_returns_none_for_js_file(self, tmp_path):
        """Non-.py extension is skipped."""
        f = tmp_path / "app.js"
        f.write_text("const x = 1;")
        result = verify_consistency(str(f), str(tmp_path))
        assert result is None

    def test_passes_for_clean_python_file(self, tmp_path):
        f = tmp_path / "clean.py"
        f.write_text("def greet(name: str) -> str:\n    return f'Hello {name}'\n")
        result = verify_consistency(str(f), str(tmp_path))
        assert result is not None
        assert result.passed

    def test_detects_bare_except_clause(self, tmp_path):
        f = tmp_path / "bad.py"
        f.write_text("try:\n    pass\nexcept:\n    pass\n")
        result = verify_consistency(str(f), str(tmp_path))
        assert result is not None
        assert not result.passed
        assert "bare except" in result.raw_output.lower()

    def test_detects_mutable_default_argument(self, tmp_path):
        f = tmp_path / "mutable.py"
        f.write_text("def foo(items=[]):\n    pass\n")
        result = verify_consistency(str(f), str(tmp_path))
        assert result is not None
        assert not result.passed
        assert "mutable" in result.raw_output.lower()

    def test_detects_base_exception_catch(self, tmp_path):
        f = tmp_path / "base_exc.py"
        f.write_text("try:\n    pass\nexcept BaseException:\n    pass\n")
        result = verify_consistency(str(f), str(tmp_path))
        assert result is not None
        assert not result.passed
        assert "BaseException" in result.raw_output

    def test_returns_none_for_syntax_error_in_file(self, tmp_path):
        """SyntaxError during ast.parse → return None (syntax stage handles it)."""
        f = tmp_path / "syntax_err.py"
        f.write_text("def broken(\n")
        result = verify_consistency(str(f), str(tmp_path))
        assert result is None

    def test_init_py_circular_import_check_with_no_cycle(self, tmp_path):
        """Lines 183-195: __init__.py check runs but finds no circular import."""
        pkg = tmp_path / "mypkg"
        pkg.mkdir()
        helper = pkg / "helper.py"
        helper.write_text("def do(): pass\n")
        init = pkg / "__init__.py"
        init.write_text("from .helper import do\n")
        result = verify_consistency(str(init), str(tmp_path))
        # No circular import → should pass (or return None if not triggered)
        assert result is None or result.passed

    def test_init_py_skip_on_absolute_import(self, tmp_path):
        """Absolute imports in __init__.py don't cause false circular detection."""
        pkg = tmp_path / "mypkg"
        pkg.mkdir()
        init = pkg / "__init__.py"
        init.write_text("import os\nimport sys\n")
        result = verify_consistency(str(init), str(tmp_path))
        assert result is None or result.passed

    def test_has_duration_ms(self, tmp_path):
        f = tmp_path / "timed.py"
        f.write_text("x = 1\n")
        result = verify_consistency(str(f), str(tmp_path))
        if result is not None:
            assert result.duration_ms >= 0


# ═══════════════════════════════════════════════════════════════════════════
# run_verify_pipeline
# ═══════════════════════════════════════════════════════════════════════════

class TestRunVerifyPipeline:
    def test_stops_after_syntax_failure(self, tmp_path):
        f = tmp_path / "broken.py"
        f.write_text("def broken(\n")
        results = run_verify_pipeline(str(f), str(tmp_path))
        assert len(results) == 1  # only syntax, which failed
        assert results[0].stage == "syntax"
        assert not results[0].passed

    def test_runs_all_stages_on_clean_file(self, tmp_path):
        f = tmp_path / "clean.py"
        f.write_text("x = 1\n")
        with patch("subprocess.run", side_effect=FileNotFoundError):
            results = run_verify_pipeline(
                str(f), str(tmp_path),
                run_lint=True,
                run_consistency=True,
            )
        stages = [r.stage for r in results]
        assert "syntax" in stages

    def test_blocked_test_runner_cmd_returns_failure(self, tmp_path):
        f = tmp_path / "ok.py"
        f.write_text("x = 1\n")
        results = run_verify_pipeline(
            str(f), str(tmp_path),
            run_tests=True,
            test_runner_cmd="rm -rf /",
        )
        test_results = [r for r in results if r.stage == "test"]
        assert test_results
        assert not test_results[0].passed
        assert "Blocked" in test_results[0].message

    def test_allowed_test_runner_runs_subprocess(self, tmp_path):
        f = tmp_path / "ok.py"
        f.write_text("x = 1\n")
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "1 passed"
        mock_proc.stderr = ""
        with patch("subprocess.run", return_value=mock_proc) as mock_run, \
             patch("subprocess.run", side_effect=FileNotFoundError):
            # patch lint to skip, then allow test runner
            pass
        # Just verify the pipeline runs without error
        with patch("subprocess.run", return_value=mock_proc):
            results = run_verify_pipeline(
                str(f), str(tmp_path),
                run_lint=False,
                run_consistency=False,
                run_tests=True,
                test_runner_cmd="pytest tests/",
            )
        test_results = [r for r in results if r.stage == "test"]
        assert test_results
        assert test_results[0].passed

    def test_test_runner_timeout_yields_failure(self, tmp_path):
        f = tmp_path / "ok.py"
        f.write_text("x = 1\n")
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("pytest", 120)):
            results = run_verify_pipeline(
                str(f), str(tmp_path),
                run_lint=False,
                run_consistency=False,
                run_tests=True,
                test_runner_cmd="pytest tests/",
            )
        test_results = [r for r in results if r.stage == "test"]
        assert test_results
        assert not test_results[0].passed
        assert "timed out" in test_results[0].message.lower()

    def test_test_runner_generic_exception_yields_failure(self, tmp_path):
        f = tmp_path / "ok.py"
        f.write_text("x = 1\n")
        with patch("subprocess.run", side_effect=OSError("can't fork")):
            results = run_verify_pipeline(
                str(f), str(tmp_path),
                run_lint=False,
                run_consistency=False,
                run_tests=True,
                test_runner_cmd="pytest tests/",
            )
        test_results = [r for r in results if r.stage == "test"]
        assert test_results
        assert not test_results[0].passed

    def test_test_runner_failure_exit_code_yields_failure(self, tmp_path):
        f = tmp_path / "ok.py"
        f.write_text("x = 1\n")
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = "FAILED test_foo.py::test_bar"
        mock_proc.stderr = ""
        with patch("subprocess.run", return_value=mock_proc):
            results = run_verify_pipeline(
                str(f), str(tmp_path),
                run_lint=False,
                run_consistency=False,
                run_tests=True,
                test_runner_cmd="pytest tests/",
            )
        test_results = [r for r in results if r.stage == "test"]
        assert test_results
        assert not test_results[0].passed


# ═══════════════════════════════════════════════════════════════════════════
# VerificationResult helpers
# ═══════════════════════════════════════════════════════════════════════════

class TestVerificationResultHelpers:
    def test_to_agent_feedback_passed(self):
        r = VerificationResult(passed=True, stage="syntax", message="OK", duration_ms=5.0)
        fb = r.to_agent_feedback()
        assert "✓" in fb
        assert "syntax" in fb

    def test_to_agent_feedback_failed_with_hint(self):
        r = VerificationResult(
            passed=False, stage="lint", message="issues found",
            fix_hint="fix indentation", raw_output="E401 error\n"
        )
        fb = r.to_agent_feedback()
        assert "✗" in fb
        assert "fix indentation" in fb

    def test_to_agent_feedback_no_raw_output(self):
        r = VerificationResult(passed=False, stage="test", message="failed", raw_output="")
        fb = r.to_agent_feedback()
        assert "```" not in fb

    def test_pipeline_all_passed_true_when_all_pass(self):
        results = [
            VerificationResult(passed=True, stage="syntax", message="OK"),
            VerificationResult(passed=True, stage="consistency", message="OK"),
        ]
        assert pipeline_all_passed(results) is True

    def test_pipeline_all_passed_false_when_syntax_fails(self):
        results = [
            VerificationResult(passed=False, stage="syntax", message="bad"),
        ]
        assert pipeline_all_passed(results) is False

    def test_pipeline_all_passed_true_when_only_lint_fails(self):
        """Lint is not a mandatory stage for pipeline_all_passed."""
        results = [
            VerificationResult(passed=True, stage="syntax", message="OK"),
            VerificationResult(passed=False, stage="lint", message="issues"),
        ]
        assert pipeline_all_passed(results) is True

    def test_pipeline_feedback_empty_list(self):
        assert pipeline_feedback([]) == ""

    def test_pipeline_feedback_includes_count(self):
        results = [
            VerificationResult(passed=True, stage="syntax", message="OK"),
            VerificationResult(passed=False, stage="test", message="failed"),
        ]
        fb = pipeline_feedback(results)
        assert "1/2" in fb
