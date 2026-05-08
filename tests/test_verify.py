"""Tests for verify.py — AST-based consistency checks, syntax verification."""


from luckyd_code.verify import (
    verify_syntax,
    verify_consistency,
    VerificationResult,
    pipeline_all_passed,
    pipeline_feedback,
)


# ── verify_syntax ──────────────────────────────────────────────────

class TestVerifySyntax:
    """Syntax checking with py_compile and compile() fallback."""

    def test_valid_syntax(self, tmp_path):
        f = tmp_path / "ok.py"
        f.write_text("x = 1\ny = 2\nprint(x + y)\n")
        result = verify_syntax(str(f))
        assert result.passed
        assert result.stage == "syntax"

    def test_invalid_syntax_missing_colon(self, tmp_path):
        f = tmp_path / "bad.py"
        f.write_text("def foo()\n    pass\n")  # missing colon
        result = verify_syntax(str(f))
        assert not result.passed
        assert result.stage == "syntax"
        assert result.fix_hint is not None

    def test_invalid_syntax_indentation_error(self, tmp_path):
        f = tmp_path / "indent.py"
        f.write_text("if True:\nprint('bad indent')\n")
        result = verify_syntax(str(f))
        assert not result.passed

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.py"
        f.write_text("")
        result = verify_syntax(str(f))
        assert result.passed  # empty file is valid syntax

    def test_syntax_error_includes_line_number(self, tmp_path):
        f = tmp_path / "broken.py"
        f.write_text("x = \n")  # incomplete assignment
        result = verify_syntax(str(f))
        assert not result.passed
        # Should mention the error
        assert len(result.message) > 0


# ── verify_consistency ─────────────────────────────────────────────

class TestVerifyConsistency:
    """AST-based project convention checks."""

    def test_clean_file_passes(self, tmp_path):
        f = tmp_path / "clean.py"
        f.write_text(
            "def add(a: int, b: int) -> int:\n"
            "    return a + b\n"
        )
        result = verify_consistency(str(f), str(tmp_path))
        assert result is not None
        assert result.passed

    def test_bare_except_fails(self, tmp_path):
        f = tmp_path / "bare_except.py"
        f.write_text(
            "try:\n"
            "    x = 1 / 0\n"
            "except:\n"           # bare except
            "    pass\n"
        )
        result = verify_consistency(str(f), str(tmp_path))
        assert result is not None
        assert not result.passed
        assert "bare except" in result.raw_output.lower()

    def test_except_exception_passes(self, tmp_path):
        """except Exception: is fine."""
        f = tmp_path / "fine_except.py"
        f.write_text(
            "try:\n"
            "    x = 1 / 0\n"
            "except Exception:\n"
            "    pass\n"
        )
        result = verify_consistency(str(f), str(tmp_path))
        assert result is not None
        assert result.passed

    def test_except_baseexception_flags(self, tmp_path):
        f = tmp_path / "base_exc.py"
        f.write_text(
            "try:\n"
            "    x = 1 / 0\n"
            "except BaseException:\n"
            "    pass\n"
        )
        result = verify_consistency(str(f), str(tmp_path))
        assert result is not None
        assert not result.passed
        assert "baseexception" in result.raw_output.lower()

    def test_mutable_default_list_fails(self, tmp_path):
        f = tmp_path / "mutable.py"
        f.write_text(
            "def append_to(items: list = []):\n"
            "    items.append(1)\n"
            "    return items\n"
        )
        result = verify_consistency(str(f), str(tmp_path))
        assert result is not None
        assert not result.passed
        assert "mutable default" in result.raw_output.lower()

    def test_mutable_default_dict_fails(self, tmp_path):
        f = tmp_path / "mutable_dict.py"
        f.write_text(
            "def configure(opts: dict = {}):\n"
            "    return opts\n"
        )
        result = verify_consistency(str(f), str(tmp_path))
        assert result is not None
        assert not result.passed

    def test_none_default_passes(self, tmp_path):
        """Default of None is fine (standard pattern)."""
        f = tmp_path / "none_default.py"
        f.write_text(
            "def append_to(items=None):\n"
            "    if items is None:\n"
            "        items = []\n"
            "    items.append(1)\n"
            "    return items\n"
        )
        result = verify_consistency(str(f), str(tmp_path))
        assert result is not None
        assert result.passed

    def test_non_python_file_returns_none(self, tmp_path):
        f = tmp_path / "readme.txt"
        f.write_text("hello world")
        result = verify_consistency(str(f), str(tmp_path))
        assert result is None

    def test_nonexistent_file_returns_none(self, tmp_path):
        f = tmp_path / "ghost.py"
        result = verify_consistency(str(f), str(tmp_path))
        assert result is None

    def test_syntax_error_in_file_returns_none(self, tmp_path):
        """If the file can't be parsed, returns None (delegates to syntax check)."""
        f = tmp_path / "broken.py"
        f.write_text("def broken(\n")  # unclosed paren — SyntaxError
        result = verify_consistency(str(f), str(tmp_path))
        assert result is None

    def test_init_py_with_normal_imports_passes(self, tmp_path):
        """__init__.py with normal imports should not trigger false positives."""
        f = tmp_path / "__init__.py"
        f.write_text(
            "from .foo import Bar\n"
            "from .baz import Qux\n"
        )
        # Need a matching package name for the circular check
        result = verify_consistency(str(f), str(tmp_path))
        # May pass or be None depending on circular import detection
        assert result is None or result.passed

    def test_multiple_issues_reported(self, tmp_path):
        f = tmp_path / "multi_issue.py"
        f.write_text(
            "def a(x=[]):\n"          # mutable default
            "    try:\n"
            "        pass\n"
            "    except:\n"           # bare except
            "        pass\n"
            "def b(y={}):\n"         # another mutable default
            "    return y\n"
        )
        result = verify_consistency(str(f), str(tmp_path))
        assert result is not None
        assert not result.passed
        # Should find at least 3 issues (2 mutable defaults + 1 bare except)
        assert "3" in result.message or "Found" in result.message


# ── VerificationResult ─────────────────────────────────────────────

class TestVerificationResult:
    """Data model and formatting."""

    def test_passed_formatting(self):
        r = VerificationResult(
            passed=True, stage="syntax", message="OK", duration_ms=12.5,
        )
        feedback = r.to_agent_feedback()
        assert "verify" in feedback
        assert "passed" in feedback.lower() or "✓" in feedback
        assert "12" in feedback  # duration is mentioned

    def test_failed_formatting(self):
        r = VerificationResult(
            passed=False, stage="lint", message="3 issues",
            fix_hint="Run ruff --fix", raw_output="E501 line too long",
            duration_ms=99.0,
        )
        feedback = r.to_agent_feedback()
        assert "FAILED" in feedback
        assert "3 issues" in feedback
        assert "ruff --fix" in feedback
        assert "E501" in feedback

    def test_failed_without_fix_hint(self):
        r = VerificationResult(
            passed=False, stage="test", message="tests failed",
            raw_output="FAIL: test_foo",
        )
        feedback = r.to_agent_feedback()
        assert "FAILED" in feedback
        assert "test_foo" in feedback


# ── pipeline_all_passed ────────────────────────────────────────────

class TestPipelineAllPassed:
    """Pipeline gating logic."""

    def test_all_mandatory_passed(self):
        results = [
            VerificationResult(passed=True, stage="syntax", message="ok"),
            VerificationResult(passed=True, stage="lint", message="ok"),
            VerificationResult(passed=True, stage="consistency", message="ok"),
        ]
        assert pipeline_all_passed(results) is True

    def test_syntax_failure_blocks(self):
        results = [
            VerificationResult(passed=False, stage="syntax", message="bad"),
            VerificationResult(passed=True, stage="lint", message="ok"),
        ]
        assert pipeline_all_passed(results) is False

    def test_lint_failure_does_not_block(self):
        """Lint is optional — it shouldn't block the pipeline."""
        results = [
            VerificationResult(passed=True, stage="syntax", message="ok"),
            VerificationResult(passed=False, stage="lint", message="style"),
        ]
        assert pipeline_all_passed(results) is True

    def test_consistency_failure_blocks(self):
        results = [
            VerificationResult(passed=True, stage="syntax", message="ok"),
            VerificationResult(passed=False, stage="consistency", message="circular"),
        ]
        assert pipeline_all_passed(results) is False

    def test_empty_results(self):
        assert pipeline_all_passed([]) is True


# ── pipeline_feedback ──────────────────────────────────────────────

class TestPipelineFeedback:
    """Aggregated feedback formatting."""

    def test_all_passed_formatting(self):
        results = [
            VerificationResult(passed=True, stage="syntax", message="ok"),
            VerificationResult(passed=True, stage="lint", message="clean"),
        ]
        fb = pipeline_feedback(results)
        assert "2/2" in fb
        assert "passed" in fb.lower()

    def test_mixed_formatting(self):
        results = [
            VerificationResult(passed=True, stage="syntax", message="ok"),
            VerificationResult(passed=False, stage="lint", message="issues",
                               fix_hint="fix it"),
        ]
        fb = pipeline_feedback(results)
        assert "1/2" in fb
        assert "FAILED" in fb
        assert "fix it" in fb

    def test_empty_returns_empty(self):
        assert pipeline_feedback([]) == ""
