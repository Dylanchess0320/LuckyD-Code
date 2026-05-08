"""Tests for autonomous_fixer.py — code fix generation and validation."""

from __future__ import annotations

from unittest.mock import patch, MagicMock


from luckyd_code.feedback_analyzer import Diagnosis
from luckyd_code.autonomous_fixer import (
    FixResult,
    generate_fix,
    _extract_diff,
    apply_fix_in_worktree,
    validate_fix,
    create_pr,
    full_autonomous_pipeline,
)


# ------------------------------------------------------------------ #
#  Diff extraction
# ------------------------------------------------------------------ #

class TestExtractDiff:
    def test_extracts_fenced_diff(self):
        raw = """Here is the fix:

```diff
--- a/luckyd_code/foo.py
+++ b/luckyd_code/foo.py
@@ -1,3 +1,3 @@
-old
+new
```

That fixes it."""
        result = _extract_diff(raw)
        assert "--- a/" in result
        assert "+++ b/" in result
        assert "old" in result
        assert "new" in result
        assert "Here is the fix" not in result

    def test_extracts_any_fenced_block_with_diff_markers(self):
        raw = """Sure, here you go:

```
--- a/x.py
+++ b/x.py
@@ -1 +1 @@
-bad
+good
```"""
        result = _extract_diff(raw)
        assert "--- a/x.py" in result

    def test_extracts_bare_diff(self):
        raw = """--- a/file.py
+++ b/file.py
@@ -1,1 +1,1 @@
-x
+y"""
        result = _extract_diff(raw)
        assert result == raw

    def test_empty_response(self):
        assert _extract_diff("") == ""

    def test_no_diff_in_response(self):
        raw = "I cannot fix this bug. It's too complex."
        assert _extract_diff(raw) == ""


# ------------------------------------------------------------------ #
#  Fix generation (mocked LLM)
# ------------------------------------------------------------------ #

class TestGenerateFix:
    def test_generates_diff_from_diagnosis(self, tmp_path):
        diagnosis = Diagnosis(
            error_type="TypeError",
            error_message="NoneType + int",
            root_cause="A None value was not checked before addition",
            affected_files=["luckyd_code/foo.py"],
            fix_suggestion="Add None check",
            confidence="high",
        )

        # Create a dummy affected file
        (tmp_path / "luckyd_code").mkdir(parents=True, exist_ok=True)
        (tmp_path / "luckyd_code" / "foo.py").write_text("x = None\nreturn x + 1", encoding="utf-8")

        with patch("luckyd_code.autonomous_fixer._call_llm") as mock_llm:
            mock_llm.return_value = """```diff
--- a/luckyd_code/foo.py
+++ b/luckyd_code/foo.py
@@ -1,2 +1,3 @@
-x = None
-return x + 1
+if x is not None:
+    return x + 1
+return 0
```"""

            diff = generate_fix(
                diagnosis,
                api_key="fake-key",
                project_root=str(tmp_path),
            )
            assert "x is not None" in diff
            assert "luckyd_code/foo.py" in diff

    def test_returns_empty_on_llm_error(self, tmp_path):
        diagnosis = Diagnosis(
            error_type="Error",
            error_message="boom",
            root_cause="unknown",
            affected_files=[],
            fix_suggestion="",
            confidence="low",
        )

        with patch("luckyd_code.autonomous_fixer._call_llm") as mock_llm:
            mock_llm.return_value = "ERROR: timeout"

            diff = generate_fix(
                diagnosis,
                api_key="fake-key",
                project_root=str(tmp_path),
            )
            assert diff == ""


# ------------------------------------------------------------------ #
#  Apply fix (git worktree)
# ------------------------------------------------------------------ #

class TestApplyFixInWorktree:
    def test_rejects_empty_diff(self, tmp_path):
        path, err = apply_fix_in_worktree("", str(tmp_path))
        assert path == ""
        assert "Empty diff" in err

    def test_rejects_non_git_repo(self, tmp_path):
        # tmp_path is not a git repo
        with patch("luckyd_code.autonomous_fixer._git") as mock_git:
            # Simulate git saying "not a git repo"
            mock_git.return_value = (128, "", "fatal: not a git repository")

            path, err = apply_fix_in_worktree(
                "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-old\n+new",
                str(tmp_path),
            )
            assert path == ""
            assert "Not in a git" in err


# ------------------------------------------------------------------ #
#  Validate fix
# ------------------------------------------------------------------ #

class TestValidateFix:
    def test_passes_when_tests_succeed(self, tmp_path):
        with patch("luckyd_code.autonomous_fixer._git") as mock_git:
            mock_git.return_value = (0, "luckyd_code/mod.py", "")

            with patch("py_compile.compile") as mock_compile:
                mock_compile.return_value = None

                with patch("subprocess.run") as mock_run:
                    mock_run.return_value = MagicMock(
                        returncode=0,
                        stdout="All tests passed",
                        stderr="",
                    )

                    passed, output = validate_fix(str(tmp_path))
                    assert passed
                    assert "OK" in output

    def test_fails_on_syntax_error(self, tmp_path):
        with patch("luckyd_code.autonomous_fixer._git") as mock_git:
            mock_git.return_value = (0, "luckyd_code/broken.py", "")

            with patch("py_compile.compile") as mock_compile:
                mock_compile.side_effect = Exception("Syntax error in broken.py")

                passed, output = validate_fix(str(tmp_path))
                assert not passed
                assert "FAIL" in output

    def test_fails_when_tests_fail(self, tmp_path):
        with patch("luckyd_code.autonomous_fixer._git") as mock_git:
            mock_git.return_value = (0, "luckyd_code/mod.py", "")

            with patch("py_compile.compile") as mock_compile:
                mock_compile.return_value = None

                with patch("subprocess.run") as mock_run:
                    mock_run.return_value = MagicMock(
                        returncode=1,
                        stdout="1 failed",
                        stderr="AssertionError",
                    )

                    passed, output = validate_fix(str(tmp_path))
                    assert not passed
                    assert "FAIL" in output


# ------------------------------------------------------------------ #
#  PR creation
# ------------------------------------------------------------------ #

class TestCreatePr:
    def test_returns_empty_when_no_push_access(self, tmp_path):
        """Regular users can't push to the repo — create_pr should return empty string
        so the diff flows into the GitHub issue body instead."""
        diagnosis = Diagnosis(
            error_type="ValueError",
            error_message="bad value",
            root_cause="Invalid input",
            affected_files=["luckyd_code/foo.py"],
            fix_suggestion="Validate input",
            confidence="high",
        )

        with patch("luckyd_code.autonomous_fixer._git") as mock_git:
            # Simulate push failure (no repo access)
            mock_git.return_value = (1, "", "remote: Permission denied")

            url = create_pr(
                "autofix/test-branch",
                diagnosis,
                "--- a/x.py\n+++ b/x.py\n-old\n+new",
                test_passed=True,
                test_output="All tests passed",
                project_root=str(tmp_path),
            )
            # Regular users can't push — returns empty so diff goes to issue body
            assert url == ""


# ------------------------------------------------------------------ #
#  Full pipeline
# ------------------------------------------------------------------ #

class TestFullAutonomousPipeline:
    def test_returns_failure_on_diagnosis_error(self):
        exc = ValueError("test error")

        with patch("luckyd_code.feedback_analyzer.analyze_error") as mock_analyze:
            mock_analyze.return_value = None

            result = full_autonomous_pipeline(
                exc,
                api_key="fake-key",
                project_root="/tmp",
            )
            assert not result.success
            assert "LLM diagnosis failed" in result.error

    def test_returns_failure_on_fix_generation_error(self):
        exc = ValueError("test error")
        diagnosis = Diagnosis(
            error_type="ValueError",
            error_message="test error",
            root_cause="test",
            affected_files=["x.py"],
            fix_suggestion="fix",
            confidence="high",
        )

        with patch("luckyd_code.feedback_analyzer.analyze_error") as mock_analyze:
            mock_analyze.return_value = diagnosis

            with patch("luckyd_code.autonomous_fixer.generate_fix") as mock_gen:
                mock_gen.return_value = ""

                result = full_autonomous_pipeline(
                    exc,
                    api_key="fake-key",
                    project_root="/tmp",
                )
                assert not result.success
                assert "LLM fix generation failed" in result.error

    def test_full_success_flow(self):
        exc = ValueError("test error")
        diagnosis = Diagnosis(
            error_type="ValueError",
            error_message="test error",
            root_cause="test",
            affected_files=["x.py"],
            fix_suggestion="fix",
            confidence="high",
        )
        test_diff = "--- a/x.py\n+++ b/x.py\n-old\n+new"
        test_output = "All tests passed"

        with patch("luckyd_code.feedback_analyzer.analyze_error") as mock_analyze:
            mock_analyze.return_value = diagnosis

            with patch("luckyd_code.autonomous_fixer.generate_fix") as mock_gen:
                mock_gen.return_value = test_diff

                with patch("luckyd_code.autonomous_fixer.apply_fix_in_worktree") as mock_apply:
                    mock_apply.return_value = ("/tmp/proj", "autofix/branch-1")

                    with patch("luckyd_code.autonomous_fixer.validate_fix") as mock_val:
                        mock_val.return_value = (True, test_output)

                        with patch("luckyd_code.autonomous_fixer.create_pr") as mock_pr:
                            mock_pr.return_value = "https://github.com/user/repo/pull/1"

                            result = full_autonomous_pipeline(
                                exc,
                                api_key="fake-key",
                                project_root="/tmp",
                                create_pr_flag=True,
                            )

                            assert result.success
                            assert result.diff == test_diff
                            assert result.test_output == test_output
                            assert "pull/1" in result.pr_url
                            assert result.branch_name == "autofix/branch-1"


# ------------------------------------------------------------------ #
#  FixResult dataclass
# ------------------------------------------------------------------ #

class TestFixResult:
    def test_defaults(self):
        diagnosis = Diagnosis(
            error_type="Error",
            error_message="msg",
            root_cause="",
            affected_files=[],
            fix_suggestion="",
            confidence="low",
        )
        r = FixResult(diagnosis=diagnosis, success=False)
        assert not r.success
        assert r.branch_name == ""
        assert r.pr_url == ""
        assert r.diff == ""
        assert r.test_output == ""
        assert r.error == ""

    def test_success_result(self):
        diagnosis = Diagnosis(
            error_type="TypeError",
            error_message="bad type",
            root_cause="type coercion missing",
            affected_files=["mod.py"],
            fix_suggestion="Add isinstance check",
            confidence="high",
        )
        r = FixResult(
            diagnosis=diagnosis,
            success=True,
            branch_name="autofix/abc",
            pr_url="https://github.com/org/repo/pull/99",
            diff="--- a/mod.py\n+++ b/mod.py\n-old\n+new",
            test_output="42 passed",
        )
        assert r.success
        assert "mod.py" in r.diff
        assert "99" in r.pr_url
