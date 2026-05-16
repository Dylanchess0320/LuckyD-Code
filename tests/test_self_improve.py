"""Smoke tests for self_improve.py.

Covers ImprovementTracker (pure-git helpers mocked), ImprovementReport
(dataclass defaults), and get_improvement_prompt (all known areas).

No live git or filesystem I/O — all subprocess calls are mocked.
"""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from luckyd_code.self_improve import (
    ImprovementReport,
    ImprovementTracker,
    SELF_IMPROVE_PROMPT,
    get_improvement_prompt,
)


# ── get_improvement_prompt ────────────────────────────────────────────────────


class TestGetImprovementPrompt:
    """Covers every branch in get_improvement_prompt, including the else fallback."""

    KNOWN_AREAS = ["web", "cli", "tools", "refactor", "perf", "cleanup"]

    def test_all_known_areas_return_non_empty_string(self):
        for area in self.KNOWN_AREAS:
            result = get_improvement_prompt(area)
            assert isinstance(result, str), f"Area '{area}' returned non-str"
            assert len(result) > 20, f"Area '{area}' returned suspiciously short prompt"

    def test_unknown_area_returns_fallback(self):
        result = get_improvement_prompt("unknown_area_xyz")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_empty_area_returns_fallback(self):
        result = get_improvement_prompt("")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_refactor_prompt_mentions_key_concepts(self):
        result = get_improvement_prompt("refactor")
        lower = result.lower()
        assert "long function" in lower or "nesting" in lower or "refactor" in lower

    def test_cleanup_prompt_mentions_todo(self):
        result = get_improvement_prompt("cleanup")
        lower = result.lower()
        assert "todo" in lower or "clean" in lower

    def test_web_prompt_mentions_web_ui(self):
        result = get_improvement_prompt("web")
        lower = result.lower()
        assert "web" in lower or "ui" in lower

    def test_cli_prompt_mentions_cli(self):
        result = get_improvement_prompt("cli")
        lower = result.lower()
        assert "cli" in lower

    def test_tools_prompt_mentions_tools(self):
        result = get_improvement_prompt("tools")
        lower = result.lower()
        assert "tool" in lower

    def test_perf_prompt_mentions_performance(self):
        result = get_improvement_prompt("perf")
        lower = result.lower()
        assert "performance" in lower or "optim" in lower or "cache" in lower

    def test_all_areas_return_distinct_prompts(self):
        prompts = [get_improvement_prompt(area) for area in self.KNOWN_AREAS]
        # Every area must produce a unique prompt
        assert len(set(prompts)) == len(self.KNOWN_AREAS)


# ── SELF_IMPROVE_PROMPT ───────────────────────────────────────────────────────


class TestSelfImprovePrompt:
    """The module-level prompt constant must be non-trivial."""

    def test_prompt_is_non_empty_string(self):
        assert isinstance(SELF_IMPROVE_PROMPT, str)
        assert len(SELF_IMPROVE_PROMPT) > 100

    def test_prompt_mentions_syntax_check(self):
        """The mandatory syntax-check step must be documented in the prompt."""
        assert "syntax" in SELF_IMPROVE_PROMPT.lower()

    def test_prompt_mentions_step_protocol(self):
        """The multi-step protocol headers must be present."""
        assert "STEP" in SELF_IMPROVE_PROMPT


# ── ImprovementReport ─────────────────────────────────────────────────────────


class TestImprovementReport:
    """ImprovementReport is a simple dataclass — verify defaults and mutability."""

    def test_default_construction(self):
        report = ImprovementReport()
        assert report.branch == ""
        assert report.start_hash == ""
        assert report.end_hash == ""
        assert report.files_changed == []
        assert report.diff_summary == ""
        assert report.commit_hash == ""
        assert report.error is None

    def test_field_assignment(self):
        report = ImprovementReport(
            branch="main",
            start_hash="abc123",
            end_hash="def456",
            files_changed=["foo.py", "bar.py"],
            diff_summary="--- foo.py ...",
            commit_hash="ghi789",
            error=None,
        )
        assert report.branch == "main"
        assert report.files_changed == ["foo.py", "bar.py"]
        assert report.commit_hash == "ghi789"

    def test_error_field_can_hold_string(self):
        report = ImprovementReport(error="Verification failed for foo.py")
        assert "Verification" in report.error

    def test_files_changed_is_independent_per_instance(self):
        """Mutable default (list) must not be shared between instances."""
        r1 = ImprovementReport()
        r2 = ImprovementReport()
        r1.files_changed.append("x.py")
        assert r2.files_changed == []

    def test_dataclass_has_expected_fields(self):
        field_names = {f.name for f in fields(ImprovementReport)}
        expected = {
            "branch", "start_hash", "end_hash", "files_changed",
            "diff_summary", "commit_hash", "error",
        }
        assert expected.issubset(field_names)


# ── ImprovementTracker ────────────────────────────────────────────────────────


class _FAKE_GIT_OUTPUTS:
    """Central registry of fake git responses used across tracker tests."""
    BRANCH = "main"
    SHORT_HASH = "abc1234"
    STATUS_CLEAN = ""
    STATUS_DIRTY = " M luckyd_code/foo.py\n M luckyd_code/bar.py"
    DIFF_EMPTY = ""
    DIFF_SMALL = "diff --git a/foo.py b/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-old\n+new"
    CHANGED_FILES = "luckyd_code/foo.py"


def _make_tracker(cwd: str) -> ImprovementTracker:
    """Return a tracker with all git calls mocked so no real git is needed."""
    with patch("luckyd_code.self_improve._git") as mock_git:
        mock_git.side_effect = lambda *args, **kwargs: {
            ("rev-parse", "--abbrev-ref", "HEAD"): _FAKE_GIT_OUTPUTS.BRANCH,
            ("rev-parse", "--short", "HEAD"): _FAKE_GIT_OUTPUTS.SHORT_HASH,
        }.get(args[:3], "")  # default empty for unknown calls
        tracker = ImprovementTracker(cwd=cwd)
    return tracker


class TestImprovementTrackerInit:
    """ImprovementTracker.__init__ sets branch and start_hash from git."""

    def test_init_sets_branch_and_start_hash(self, tmp_path):
        with patch("luckyd_code.self_improve._git") as mock_git:
            mock_git.side_effect = lambda *args, **kwargs: (
                _FAKE_GIT_OUTPUTS.BRANCH if "--abbrev-ref" in args else _FAKE_GIT_OUTPUTS.SHORT_HASH
            )
            tracker = ImprovementTracker(cwd=str(tmp_path))

        assert tracker._branch == _FAKE_GIT_OUTPUTS.BRANCH
        assert tracker._start_hash == _FAKE_GIT_OUTPUTS.SHORT_HASH
        assert tracker.cwd == str(tmp_path)
        assert tracker._stash_made is False
        assert isinstance(tracker._changes_before, set)

    def test_init_defaults_cwd_to_current_directory(self):
        """When cwd=None, the tracker uses Path.cwd()."""
        with patch("luckyd_code.self_improve._git", return_value="main"):
            tracker = ImprovementTracker(cwd=None)
        assert Path(tracker.cwd).is_absolute()


class TestImprovementTrackerReport:
    """ImprovementTracker.report() with all git calls mocked."""

    def test_report_no_changes_returns_report(self, tmp_path):
        """When there are no file changes, report returns an ImprovementReport."""
        with patch("luckyd_code.self_improve._git") as mock_git:
            def side_effect(*args, **kwargs):
                cmd = args[:3]
                if "--abbrev-ref" in args:
                    return _FAKE_GIT_OUTPUTS.BRANCH
                if "--short" in args:
                    return _FAKE_GIT_OUTPUTS.SHORT_HASH
                if "diff" in args and "--name-only" in args:
                    return ""  # no changed files
                if "diff" in args and "--cached" in args:
                    return ""
                if "diff" in args:
                    return ""
                return ""
            mock_git.side_effect = side_effect

            tracker = ImprovementTracker(cwd=str(tmp_path))
            report = tracker.report(commit=False)

        assert isinstance(report, ImprovementReport)
        assert report.files_changed == []
        assert report.commit_hash == ""
        assert report.error is None

    def test_report_with_changed_file_lists_it(self, tmp_path):
        """When diff --name-only returns a file, it appears in files_changed."""
        changed_file = "luckyd_code/foo.py"

        with patch("luckyd_code.self_improve._git") as mock_git:
            def side_effect(*args, **kwargs):
                if "--abbrev-ref" in args:
                    return _FAKE_GIT_OUTPUTS.BRANCH
                if "--short" in args:
                    return _FAKE_GIT_OUTPUTS.SHORT_HASH
                if "diff" in args and "--name-only" in args:
                    return changed_file
                if "diff" in args and "--stat" in args:
                    return f"{changed_file} | 3 ++-\n 1 file changed"
                return ""
            mock_git.side_effect = side_effect

            tracker = ImprovementTracker(cwd=str(tmp_path))
            report = tracker.report(commit=False)

        assert changed_file in report.files_changed

    def test_report_summary_contains_branch(self, tmp_path):
        """The diff_summary field must include the branch name."""
        with patch("luckyd_code.self_improve._git") as mock_git:
            mock_git.side_effect = lambda *args, **kwargs: (
                _FAKE_GIT_OUTPUTS.BRANCH if "--abbrev-ref" in args else
                _FAKE_GIT_OUTPUTS.SHORT_HASH if "--short" in args else ""
            )
            tracker = ImprovementTracker(cwd=str(tmp_path))
            report = tracker.report(commit=False)

        assert _FAKE_GIT_OUTPUTS.BRANCH in report.diff_summary

    def test_report_skips_commit_when_no_new_files(self, tmp_path):
        """report(commit=True) with no new files must not call git commit."""
        committed = []

        def side_effect(*args, **kwargs):
            if "commit" in args:
                committed.append(args)
            if "--abbrev-ref" in args:
                return _FAKE_GIT_OUTPUTS.BRANCH
            if "--short" in args:
                return _FAKE_GIT_OUTPUTS.SHORT_HASH
            return ""

        with patch("luckyd_code.self_improve._git", side_effect=side_effect):
            tracker = ImprovementTracker(cwd=str(tmp_path))
            report = tracker.report(commit=True, commit_msg="auto-fix")

        assert committed == [], "git commit must not be called when no files changed"
        assert report.commit_hash == ""


# ── _git helper (module-level) ────────────────────────────────────────────────


class TestGitHelper:
    """_git() must never raise — it returns an error string on failure."""

    def test_git_returns_string_on_success(self, tmp_path):
        from luckyd_code.self_improve import _git
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="main\n", returncode=0)
            result = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=str(tmp_path))
        assert result == "main"

    def test_git_returns_error_string_on_exception(self, tmp_path):
        from luckyd_code.self_improve import _git
        with patch("subprocess.run", side_effect=OSError("git not found")):
            result = _git("rev-parse", "HEAD", cwd=str(tmp_path))
        assert result.startswith("<error:")

    def test_git_strips_trailing_newline(self, tmp_path):
        from luckyd_code.self_improve import _git
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="abc123\n", returncode=0)
            result = _git("rev-parse", "--short", "HEAD", cwd=str(tmp_path))
        assert result == "abc123"
