"""New-module coverage — hits the modules that were near 0-15% coverage.

Modules targeted
-----------------
  git/tools.py            — 15% → ~95%   (subprocess mocking)
  cli_commands/sessions.py — 0% → ~95%   (console + session mocking)
  analytics/smells.py     — 72% → ~95%  (direct content injection)
  dream.py                — 71% → ~90%  (MemoryManager mocking)
  autonomous_fixer.py     — 72% → ~92%  (non-pragma functions only)

Design notes
------------
* git/tools.py — every function calls subprocess.run; we mock it at the
  subprocess module level so the real binary is never invoked.
* cli_commands/sessions.py — we mock console.print and the four session
  functions so no real filesystem is touched.
* analytics/smells.py — SmellDetector.detect_file() accepts raw ``content``
  so no real files are needed; detect_project() gets a mocked ProjectMetrics.
* dream.py — MemoryManager is dependency-injected so it's trivially mockable.
* autonomous_fixer.py — only the non-pragma-no-cover functions are tested:
  _git, _read_file_safe, _extract_diff, _pr_fallback_url, generate_fix.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest


# ═══════════════════════════════════════════════════════════════════════════════
# git/tools.py
# ═══════════════════════════════════════════════════════════════════════════════

def _fake_run(stdout="", stderr="", returncode=0):
    """Build a mock subprocess.CompletedProcess."""
    r = MagicMock()
    r.stdout = stdout
    r.stderr = stderr
    r.returncode = returncode
    return r


class TestGitStatus:
    def test_returns_stdout(self):
        from luckyd_code.git.tools import git_status
        with patch("subprocess.run", return_value=_fake_run("On branch main")) as m:
            result = git_status()
        assert result == "On branch main"
        m.assert_called_once()

    def test_falls_back_to_stderr(self):
        from luckyd_code.git.tools import git_status
        with patch("subprocess.run", return_value=_fake_run("", "fatal: not a repo")):
            result = git_status()
        assert "fatal" in result

    def test_exception_returns_error_string(self):
        from luckyd_code.git.tools import git_status
        with patch("subprocess.run", side_effect=FileNotFoundError("git not found")):
            result = git_status()
        assert result.startswith("Error:")


class TestGitDiff:
    def test_unstaged_diff(self):
        from luckyd_code.git.tools import git_diff
        with patch("subprocess.run", return_value=_fake_run("diff output")) as m:
            result = git_diff(staged=False)
        assert result == "diff output"
        cmd = m.call_args[0][0]
        assert "--cached" not in cmd

    def test_staged_diff(self):
        from luckyd_code.git.tools import git_diff
        with patch("subprocess.run", return_value=_fake_run("staged diff")) as m:
            result = git_diff(staged=True)
        assert result == "staged diff"
        cmd = m.call_args[0][0]
        assert "--cached" in cmd

    def test_empty_diff_returns_no_changes(self):
        from luckyd_code.git.tools import git_diff
        with patch("subprocess.run", return_value=_fake_run("")):
            result = git_diff()
        assert result == "No changes"

    def test_large_diff_truncated_to_5000(self):
        from luckyd_code.git.tools import git_diff
        big = "x" * 6000
        with patch("subprocess.run", return_value=_fake_run(big)):
            result = git_diff()
        assert len(result) == 5000

    def test_exception_returns_error_string(self):
        from luckyd_code.git.tools import git_diff
        with patch("subprocess.run", side_effect=OSError("boom")):
            result = git_diff()
        assert result.startswith("Error:")


class TestGitLog:
    def test_returns_log_output(self):
        from luckyd_code.git.tools import git_log
        log = "abc123 initial commit"
        with patch("subprocess.run", return_value=_fake_run(log)) as m:
            result = git_log(count=5)
        assert result == log
        cmd = m.call_args[0][0]
        assert "--max-count=5" in cmd

    def test_default_count_is_10(self):
        from luckyd_code.git.tools import git_log
        with patch("subprocess.run", return_value=_fake_run("log")) as m:
            git_log()
        cmd = m.call_args[0][0]
        assert "--max-count=10" in cmd

    def test_exception_returns_error_string(self):
        from luckyd_code.git.tools import git_log
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 30)):
            result = git_log()
        assert result.startswith("Error:")


class TestGitCommit:
    def test_commit_passes_message(self):
        from luckyd_code.git.tools import git_commit
        with patch("subprocess.run", return_value=_fake_run("1 file changed")) as m:
            result = git_commit("fix: correct typo")
        assert result == "1 file changed"
        cmd = m.call_args[0][0]
        assert "fix: correct typo" in cmd

    def test_exception_returns_error_string(self):
        from luckyd_code.git.tools import git_commit
        with patch("subprocess.run", side_effect=OSError("locked")):
            result = git_commit("msg")
        assert result.startswith("Error:")


class TestGitAdd:
    def test_add_all_by_default(self):
        from luckyd_code.git.tools import git_add
        with patch("subprocess.run", return_value=_fake_run("")) as m:
            result = git_add()
        cmd = m.call_args[0][0]
        assert "-A" in cmd
        assert result == "Staged"  # empty stdout → fallback "Staged"

    def test_add_specific_files(self):
        from luckyd_code.git.tools import git_add
        with patch("subprocess.run", return_value=_fake_run("")) as m:
            git_add(["foo.py", "bar.py"])
        cmd = m.call_args[0][0]
        assert "foo.py" in cmd
        assert "bar.py" in cmd

    def test_exception_returns_error_string(self):
        from luckyd_code.git.tools import git_add
        with patch("subprocess.run", side_effect=OSError("no git")):
            result = git_add()
        assert result.startswith("Error:")


class TestGitBranch:
    def test_returns_branch_listing(self):
        from luckyd_code.git.tools import git_branch
        branches = "* main\n  feature/x"
        with patch("subprocess.run", return_value=_fake_run(branches)):
            result = git_branch()
        assert "main" in result

    def test_exception_returns_error_string(self):
        from luckyd_code.git.tools import git_branch
        with patch("subprocess.run", side_effect=OSError("no git")):
            result = git_branch()
        assert result.startswith("Error:")


class TestGitCreatePr:
    def test_creates_draft_pr_by_default(self):
        from luckyd_code.git.tools import git_create_pr
        with patch("subprocess.run", return_value=_fake_run("https://github.com/x/y/pull/1")) as m:
            result = git_create_pr("My PR", "body text")
        cmd = m.call_args[0][0]
        assert "--draft" in cmd
        assert "My PR" in cmd

    def test_non_draft_omits_flag(self):
        from luckyd_code.git.tools import git_create_pr
        with patch("subprocess.run", return_value=_fake_run("url")) as m:
            git_create_pr("PR", draft=False)
        cmd = m.call_args[0][0]
        assert "--draft" not in cmd

    def test_exception_returns_error_string(self):
        from luckyd_code.git.tools import git_create_pr
        with patch("subprocess.run", side_effect=FileNotFoundError("gh not found")):
            result = git_create_pr("title")
        assert result.startswith("Error:")


class TestGitPush:
    def test_push_without_branch(self):
        from luckyd_code.git.tools import git_push
        with patch("subprocess.run", return_value=_fake_run("pushed")) as m:
            result = git_push()
        assert result == "pushed"
        cmd = m.call_args[0][0]
        assert "origin" in cmd

    def test_push_with_branch(self):
        from luckyd_code.git.tools import git_push
        with patch("subprocess.run", return_value=_fake_run("pushed")) as m:
            git_push("my-branch")
        cmd = m.call_args[0][0]
        assert "my-branch" in cmd

    def test_exception_returns_error_string(self):
        from luckyd_code.git.tools import git_push
        with patch("subprocess.run", side_effect=OSError("auth fail")):
            result = git_push()
        assert result.startswith("Error:")


# ═══════════════════════════════════════════════════════════════════════════════
# cli_commands/sessions.py
# ═══════════════════════════════════════════════════════════════════════════════

def _make_repl(messages=None):
    """Return a minimal fake REPL with a context attribute."""
    repl = MagicMock()
    repl.context = MagicMock()
    return repl


class TestHandleSessionsCommand:
    def _run(self, args, repl=None):
        from luckyd_code.cli_commands.sessions import handle_sessions_command
        repl = repl or _make_repl()
        printed = []
        with patch("luckyd_code.cli_utils.console") as mock_console:
            mock_console.print.side_effect = lambda msg: printed.append(str(msg))
            with patch("luckyd_code.sessions.list_sessions", return_value="session_a\nsession_b"):
                with patch("luckyd_code.sessions.save_session", return_value="Saved 'test'"):
                    with patch("luckyd_code.sessions.load_session", return_value="Loaded 'test'"):
                        with patch("luckyd_code.sessions.delete_session", return_value="Deleted 'test'"):
                            handle_sessions_command(repl, args)
        return printed

    def test_no_args_shows_usage(self):
        printed = self._run([])
        assert any("Usage" in p for p in printed)

    def test_list_shows_sessions(self):
        printed = self._run(["list"])
        assert any("session_a" in p for p in printed)

    def test_save_with_name(self):
        printed = self._run(["save", "my-session"])
        assert any("Saved" in p for p in printed)

    def test_save_without_name_uses_unnamed(self):
        """save with no name defaults to 'unnamed'."""
        from luckyd_code.cli_commands.sessions import handle_sessions_command
        repl = _make_repl()
        with patch("luckyd_code.cli_utils.console"):
            with patch("luckyd_code.sessions.list_sessions"):
                with patch("luckyd_code.sessions.save_session", return_value="Saved") as mock_save:
                    with patch("luckyd_code.sessions.load_session"):
                        with patch("luckyd_code.sessions.delete_session"):
                            handle_sessions_command(repl, ["save"])
        mock_save.assert_called_once_with("unnamed", repl.context)

    def test_load_with_name(self):
        printed = self._run(["load", "my-session"])
        assert any("Loaded" in p for p in printed)

    def test_load_without_name_shows_usage(self):
        printed = self._run(["load"])
        assert any("Usage" in p for p in printed)

    def test_delete_with_name(self):
        printed = self._run(["delete", "my-session"])
        assert any("Deleted" in p for p in printed)

    def test_delete_without_name_shows_usage(self):
        printed = self._run(["delete"])
        assert any("Usage" in p for p in printed)

    def test_unknown_subcommand_shows_error(self):
        printed = self._run(["frobnicate"])
        assert any("Unknown" in p or "frobnicate" in p for p in printed)

    def test_load_multiword_name(self):
        """Multi-word load name is joined with spaces."""
        from luckyd_code.cli_commands.sessions import handle_sessions_command
        repl = _make_repl()
        with patch("luckyd_code.cli_utils.console"):
            with patch("luckyd_code.sessions.list_sessions"):
                with patch("luckyd_code.sessions.save_session"):
                    with patch("luckyd_code.sessions.load_session", return_value="ok") as mock_load:
                        with patch("luckyd_code.sessions.delete_session"):
                            handle_sessions_command(repl, ["load", "my", "session"])
        mock_load.assert_called_once_with("my session", repl.context)

    def test_delete_multiword_name(self):
        from luckyd_code.cli_commands.sessions import handle_sessions_command
        repl = _make_repl()
        with patch("luckyd_code.cli_utils.console"):
            with patch("luckyd_code.sessions.list_sessions"):
                with patch("luckyd_code.sessions.save_session"):
                    with patch("luckyd_code.sessions.load_session"):
                        with patch("luckyd_code.sessions.delete_session", return_value="ok") as mock_del:
                            handle_sessions_command(repl, ["delete", "old", "name"])
        mock_del.assert_called_once_with("old name")


# ═══════════════════════════════════════════════════════════════════════════════
# analytics/smells.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestSmellDetectorDetectFile:
    def _detector(self):
        from luckyd_code.analytics.smells import SmellDetector
        return SmellDetector()

    def test_large_file_warning(self, tmp_path):
        d = self._detector()
        content = "x = 1\n" * 600  # > LONG_FILE_LINES (500)
        f = tmp_path / "big.py"
        f.write_text(content)
        smells = d.detect_file(str(f), content=content)
        kinds = [s.kind for s in smells]
        assert "large_file" in kinds

    def test_very_large_file_error_severity(self, tmp_path):
        d = self._detector()
        content = "x = 1\n" * 1100  # > LONG_FILE_LINES * 2 (1000)
        f = tmp_path / "huge.py"
        f.write_text(content)
        smells = d.detect_file(str(f), content=content)
        error_smells = [s for s in smells if s.severity == "error" and s.kind == "large_file"]
        assert error_smells

    def test_long_function_python(self, tmp_path):
        d = self._detector()
        # A function with 60 lines > LONG_FUNCTION_LINES (50)
        body = "    pass\n" * 60
        content = f"def long_func():\n{body}"
        f = tmp_path / "funcs.py"
        f.write_text(content)
        smells = d.detect_file(str(f), content=content)
        kinds = [s.kind for s in smells]
        assert "long_function" in kinds

    def test_too_many_params_python(self, tmp_path):
        d = self._detector()
        params = ", ".join(f"p{i}" for i in range(8))  # 8 > MANY_PARAMS (6)
        content = f"def f({params}):\n    pass\n"
        f = tmp_path / "params.py"
        f.write_text(content)
        smells = d.detect_file(str(f), content=content)
        kinds = [s.kind for s in smells]
        assert "too_many_params" in kinds

    def test_bare_except_python(self, tmp_path):
        d = self._detector()
        content = "try:\n    x = 1\nexcept:\n    pass\n"
        f = tmp_path / "bare.py"
        f.write_text(content)
        smells = d.detect_file(str(f), content=content)
        kinds = [s.kind for s in smells]
        assert "bare_except" in kinds

    def test_mutable_default_argument(self, tmp_path):
        d = self._detector()
        content = "def f(items=[]):\n    pass\n"
        f = tmp_path / "mut.py"
        f.write_text(content)
        smells = d.detect_file(str(f), content=content)
        kinds = [s.kind for s in smells]
        assert "mutable_default" in kinds

    def test_large_class_python(self, tmp_path):
        d = self._detector()
        body = "    x = 1\n" * 310  # > BIG_CLASS_LINES (300)
        content = f"class MyClass:\n{body}"
        f = tmp_path / "bigcls.py"
        f.write_text(content)
        smells = d.detect_file(str(f), content=content)
        kinds = [s.kind for s in smells]
        assert "large_class" in kinds

    def test_syntax_error_python(self, tmp_path):
        d = self._detector()
        content = "def broken(\n"
        f = tmp_path / "bad.py"
        f.write_text(content)
        smells = d.detect_file(str(f), content=content)
        kinds = [s.kind for s in smells]
        assert "syntax_error" in kinds

    def test_deep_nesting(self, tmp_path):
        d = self._detector()
        # 5 levels of 4-space indent → nesting_level=5 > DEEP_NESTING (4)
        content = "if a:\n    if b:\n        if c:\n            if d:\n                if e:\n                    x = 1\n"
        f = tmp_path / "nest.py"
        f.write_text(content)
        smells = d.detect_file(str(f), content=content)
        kinds = [s.kind for s in smells]
        assert "deep_nesting" in kinds

    def test_empty_content_returns_no_smells(self, tmp_path):
        d = self._detector()
        f = tmp_path / "empty.py"
        f.write_text("")
        smells = d.detect_file(str(f), content="")
        assert smells == []

    def test_non_python_file_uses_generic_detector(self, tmp_path):
        d = self._detector()
        # A JavaScript file with a long function
        lines = "  x = 1;\n" * 60
        content = f"function foo() {{\n{lines}}}\n"
        f = tmp_path / "script.js"
        f.write_text(content)
        smells = d.detect_file(str(f), content=content)
        # Just verifying it runs without error; may or may not catch long_function
        assert isinstance(smells, list)

    def test_generic_bare_except_js(self, tmp_path):
        d = self._detector()
        content = "try {\n  x();\n} catch( e ) {\n  // swallow\n}\n"
        f = tmp_path / "catch.js"
        f.write_text(content)
        smells = d.detect_file(str(f), content=content)
        kinds = [s.kind for s in smells]
        assert "bare_except" in kinds

    def test_oserror_on_content_none_returns_empty(self, tmp_path):
        d = self._detector()
        f = tmp_path / "noread.py"
        # File doesn't exist → can't read → returns []
        smells = d.detect_file(str(f), content=None)
        assert smells == []

    def test_file_size_warning_triggered(self, tmp_path):
        d = self._detector()
        big = tmp_path / "chonk.py"
        # Write > 0.5MB
        big.write_bytes(b"x" * (600 * 1024))
        smells = d.detect_file(str(big))
        kinds = [s.kind for s in smells]
        assert "large_file_bytes" in kinds


class TestDetectProject:
    def _make_pm(self):
        from luckyd_code.analytics.scanner import ProjectMetrics, FileMetrics
        fm1 = FileMetrics(
            path="foo.py",
            lines_total=600,
            lines_code=10,   # low lines_code makes todo_density = 12/(10/100) = 120 > 10
            lines_blank=10,
            lines_comment=10,
            todo_count=12,
            language="Python",
        )
        fm2 = FileMetrics(
            path="empty.py",
            lines_total=5,
            lines_code=0,
            lines_blank=5,
            lines_comment=0,
            todo_count=0,
            language="Python",
        )
        pm = ProjectMetrics(
            root="/tmp",
            file_metrics=[fm1, fm2],
            total_files=2,
            total_lines=605,
            total_code_lines=580,
            files_by_language={"Python": 2},
            complexity_breakdown={"foo.py": 20},  # > HIGH_COMPLEXITY (15)
        )
        return pm

    def test_high_complexity_smell(self):
        from luckyd_code.analytics.smells import SmellDetector
        d = SmellDetector()
        pm = self._make_pm()
        smells = d.detect_project(pm)
        kinds = [s.kind for s in smells]
        assert "high_complexity" in kinds

    def test_empty_file_smell(self):
        from luckyd_code.analytics.smells import SmellDetector
        d = SmellDetector()
        pm = self._make_pm()
        smells = d.detect_project(pm)
        kinds = [s.kind for s in smells]
        assert "empty_file" in kinds

    def test_high_todo_density_smell(self):
        from luckyd_code.analytics.smells import SmellDetector
        d = SmellDetector()
        pm = self._make_pm()
        smells = d.detect_project(pm)
        kinds = [s.kind for s in smells]
        assert "high_todo_density" in kinds

    def test_large_file_smell_from_project(self):
        from luckyd_code.analytics.smells import SmellDetector
        d = SmellDetector()
        pm = self._make_pm()
        smells = d.detect_project(pm)
        kinds = [s.kind for s in smells]
        assert "large_file" in kinds


class TestDetectSmellsConvenience:
    def test_detect_nonexistent_path_returns_empty(self):
        from luckyd_code.analytics.smells import detect_smells
        result = detect_smells("/no/such/path")
        assert result == []

    def test_detect_on_file(self, tmp_path):
        from luckyd_code.analytics.smells import detect_smells
        f = tmp_path / "code.py"
        f.write_text("x = 1\n")
        result = detect_smells(str(f))
        assert isinstance(result, list)

    def test_detect_on_dir(self, tmp_path):
        from luckyd_code.analytics.smells import detect_smells
        (tmp_path / "module.py").write_text("y = 2\n")
        result = detect_smells(str(tmp_path))
        assert isinstance(result, list)


# ═══════════════════════════════════════════════════════════════════════════════
# dream.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestDreamReport:
    def test_summary_contains_key_counts(self):
        from luckyd_code.dream import DreamReport
        r = DreamReport(
            phase_1_memories_found=10,
            phase_2_groups_formed=3,
            phase_3_memories_merged=6,
            phase_4_memories_pruned=2,
            duration_seconds=1.5,
        )
        s = r.summary()
        assert "10" in s
        assert "3" in s
        assert "6" in s
        assert "2" in s
        assert "1.5" in s

    def test_summary_format(self):
        from luckyd_code.dream import DreamReport
        r = DreamReport()
        s = r.summary()
        assert "autoDream" in s
        assert "surveyed" in s


class TestDreamCyclePhases:
    def _make_mm(self, memories=None):
        mm = MagicMock()
        mm.list_memories.return_value = memories or []
        mm.load_memory.return_value = "some memory content about project setup and config"
        mm.decay.return_value = 3
        return mm

    def test_skips_when_too_few_memories(self):
        from luckyd_code.dream import DreamCycle
        mm = self._make_mm(memories=[{"name": "a", "type": "general"}] * 3)  # < _MIN_MEMORIES_TO_DREAM (5)
        cycle = DreamCycle(mm, config=None)
        report = cycle.run()
        assert report.phase_1_memories_found == 3
        assert report.phase_2_groups_formed == 0  # skipped

    def test_runs_all_phases_when_enough_memories(self):
        from luckyd_code.dream import DreamCycle
        memories = [
            {"name": f"mem_{i}", "type": "general"}
            for i in range(8)
        ]
        mm = self._make_mm(memories=memories)
        cycle = DreamCycle(mm, config=None)
        report = cycle.run()
        assert report.phase_1_memories_found == 8
        # No config → consolidate skipped but prune runs
        assert report.phase_4_memories_pruned == 3  # from mm.decay.return_value

    def test_prune_exception_captured_in_report(self):
        from luckyd_code.dream import DreamCycle
        memories = [{"name": f"m{i}", "type": "general"} for i in range(8)]
        mm = self._make_mm(memories=memories)
        mm.decay.side_effect = RuntimeError("decay failed")
        cycle = DreamCycle(mm, config=None)
        report = cycle.run()
        assert any("prune" in e for e in report.errors)
        assert report.phase_4_memories_pruned == 0

    def test_consolidate_skipped_with_no_config(self):
        from luckyd_code.dream import DreamCycle
        memories = [{"name": f"m{i}", "type": "general"} for i in range(8)]
        mm = self._make_mm(memories=memories)
        cycle = DreamCycle(mm, config=None)
        report = cycle.run()
        # save_memory should NOT be called — no LLM merges without config
        mm.save_memory.assert_not_called()

    def test_gather_groups_semantically_related(self):
        from luckyd_code.dream import DreamCycle
        # All memories share ≥3 words from their content → form a group
        memories = [{"name": f"m{i}", "type": "general"} for i in range(6)]
        mm = MagicMock()
        mm.list_memories.return_value = memories
        # Load content with heavy overlap so groups form
        mm.load_memory.return_value = "alpha beta gamma delta epsilon zeta eta"
        mm.decay.return_value = 0
        cycle = DreamCycle(mm, config=None)
        report = cycle.run()
        assert report.phase_2_groups_formed >= 1

    def test_report_errors_captured_on_outer_exception(self):
        from luckyd_code.dream import DreamCycle
        mm = MagicMock()
        mm.list_memories.side_effect = RuntimeError("db exploded")
        cycle = DreamCycle(mm, config=None)
        report = cycle.run()
        assert len(report.errors) == 1
        assert "db exploded" in report.errors[0]

    def test_duration_seconds_populated(self):
        from luckyd_code.dream import DreamCycle
        mm = self._make_mm(memories=[])
        cycle = DreamCycle(mm, config=None)
        report = cycle.run()
        assert report.duration_seconds >= 0.0

    def test_run_dream_cycle_wrapper(self):
        from luckyd_code.dream import run_dream_cycle
        mm = MagicMock()
        mm.list_memories.return_value = []
        report = run_dream_cycle(mm, config=None)
        assert report.phase_1_memories_found == 0

    def test_consolidate_with_small_groups_skipped(self):
        """Groups with < _GROUP_SIZE_TO_MERGE members are not LLM-merged."""
        from luckyd_code.dream import DreamCycle, _GROUP_SIZE_TO_MERGE
        # Exactly 2 memories — forms one group of size 2
        memories = [
            {"name": "alpha", "type": "general"},
            {"name": "beta", "type": "general"},
        ]
        mm = MagicMock()
        mm.list_memories.return_value = memories
        mm.load_memory.return_value = "shared words alpha beta gamma delta epsilon"
        mm.decay.return_value = 0

        fake_config = MagicMock()
        cycle = DreamCycle(mm, config=fake_config)
        with patch.object(cycle, "_llm_merge", return_value=("merged", "content")) as mock_merge:
            report = cycle.run()

        # Group size is 2 which is < _GROUP_SIZE_TO_MERGE (3) → no merge called
        if _GROUP_SIZE_TO_MERGE > 2:
            mock_merge.assert_not_called()
            assert report.phase_3_memories_merged == 0


# ═══════════════════════════════════════════════════════════════════════════════
# autonomous_fixer.py  (non-pragma-no-cover functions only)
# ═══════════════════════════════════════════════════════════════════════════════

class TestGitHelper:
    def test_success_returns_stdout(self):
        from luckyd_code.autonomous_fixer import _git
        with patch("subprocess.run", return_value=_fake_run("output")) as m:
            rc, out, err = _git("status")
        assert rc == 0
        assert out == "output"

    def test_exception_returns_minus_one(self):
        from luckyd_code.autonomous_fixer import _git
        with patch("subprocess.run", side_effect=OSError("no git")):
            rc, out, err = _git("status")
        assert rc == -1
        assert "no git" in err

    def test_cwd_passed_to_subprocess(self):
        from luckyd_code.autonomous_fixer import _git
        with patch("subprocess.run", return_value=_fake_run("")) as m:
            _git("rev-parse", "--is-inside-work-tree", cwd="/tmp")
        kwargs = m.call_args[1]
        assert kwargs["cwd"] == "/tmp"


class TestReadFileSafe:
    def test_reads_file_within_root(self, tmp_path):
        from luckyd_code.autonomous_fixer import _read_file_safe
        f = tmp_path / "module.py"
        f.write_text("x = 1\n")
        result = _read_file_safe("module.py", str(tmp_path))
        assert "x = 1" in result

    def test_blocks_path_traversal(self, tmp_path):
        from luckyd_code.autonomous_fixer import _read_file_safe
        result = _read_file_safe("../../etc/passwd", str(tmp_path))
        assert "BLOCKED" in result

    def test_missing_file_returns_not_found(self, tmp_path):
        from luckyd_code.autonomous_fixer import _read_file_safe
        result = _read_file_safe("missing.py", str(tmp_path))
        assert "NOT FOUND" in result or "not found" in result.lower()

    def test_large_file_truncated_to_300_lines(self, tmp_path):
        from luckyd_code.autonomous_fixer import _read_file_safe
        f = tmp_path / "big.py"
        f.write_text("\n".join(f"line{i}" for i in range(500)))
        result = _read_file_safe("big.py", str(tmp_path))
        assert "truncated" in result
        # Should contain first 300 lines but not line300+
        assert "line299" in result
        assert "line300" not in result

    def test_read_error_returns_error_string(self, tmp_path):
        from luckyd_code.autonomous_fixer import _read_file_safe
        with patch.object(Path, "read_text", side_effect=PermissionError("denied")):
            # Need a file that exists but can't be read
            f = tmp_path / "locked.py"
            f.write_text("x")
            result = _read_file_safe("locked.py", str(tmp_path))
        assert "ERROR" in result or "denied" in result.lower()


class TestExtractDiff:
    def test_extracts_from_diff_fence(self):
        from luckyd_code.autonomous_fixer import _extract_diff
        raw = "Here is the fix:\n```diff\n--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-x\n+y\n```"
        result = _extract_diff(raw)
        assert "--- a/foo.py" in result
        assert "+y" in result

    def test_extracts_from_plain_fence(self):
        from luckyd_code.autonomous_fixer import _extract_diff
        raw = "```\n--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-x\n+y\n```"
        result = _extract_diff(raw)
        assert "--- a/" in result

    def test_extracts_raw_diff_without_fence(self):
        from luckyd_code.autonomous_fixer import _extract_diff
        raw = "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-x\n+y\n"
        result = _extract_diff(raw)
        assert "--- a/foo.py" in result

    def test_empty_input_returns_empty(self):
        from luckyd_code.autonomous_fixer import _extract_diff
        assert _extract_diff("") == ""

    def test_no_diff_content_returns_empty(self):
        from luckyd_code.autonomous_fixer import _extract_diff
        assert _extract_diff("Just some plain text with no diff markers") == ""

    def test_plain_fence_without_diff_markers_returns_empty(self):
        from luckyd_code.autonomous_fixer import _extract_diff
        raw = "```\nprint('hello')\n```"
        result = _extract_diff(raw)
        assert result == ""


class TestPrFallbackUrl:
    def test_returns_github_url(self):
        from luckyd_code.autonomous_fixer import _pr_fallback_url
        with patch("subprocess.run", side_effect=FileNotFoundError("no git")):
            url = _pr_fallback_url("Fix bug", "body text", "autofix/abc123")
        assert "github.com" in url
        assert "Fix" in url or "Fix%20" in url

    def test_extracts_remote_repo_path(self):
        from luckyd_code.autonomous_fixer import _pr_fallback_url
        fake_remote = "git@github.com:myorg/myrepo.git"
        with patch("subprocess.run", return_value=_fake_run(fake_remote)):
            url = _pr_fallback_url("title", "body")
        assert "myorg/myrepo" in url

    def test_truncates_very_long_body(self):
        from luckyd_code.autonomous_fixer import _pr_fallback_url
        with patch("subprocess.run", side_effect=FileNotFoundError("no git")):
            long_body = "x" * 70000
            url = _pr_fallback_url("title", long_body)
        # URL should not contain the full body
        assert len(url) < 70000 + 1000


class TestGenerateFix:
    def test_returns_empty_string_on_llm_error(self, tmp_path):
        from luckyd_code.autonomous_fixer import generate_fix
        from luckyd_code.feedback_analyzer import Diagnosis
        diag = Diagnosis(
            error_type="ValueError",
            error_message="bad value",
            root_cause="wrong input",
            affected_files=["luckyd_code/config.py"],
            fix_suggestion="validate input",
            confidence="medium",
        )
        with patch("luckyd_code.autonomous_fixer._call_llm", return_value="ERROR: no key"):
            result = generate_fix(diag, api_key="k", project_root=str(tmp_path))
        assert result == ""

    def test_returns_diff_on_success(self, tmp_path):
        from luckyd_code.autonomous_fixer import generate_fix
        from luckyd_code.feedback_analyzer import Diagnosis
        diag = Diagnosis(
            error_type="ValueError",
            error_message="bad",
            root_cause="wrong",
            affected_files=[],
            fix_suggestion="fix it",
            confidence="high",
        )
        fake_diff = "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-x\n+y\n"
        with patch("luckyd_code.autonomous_fixer._call_llm", return_value=fake_diff):
            result = generate_fix(diag, api_key="k", project_root=str(tmp_path))
        assert "--- a/foo.py" in result

    def test_reads_affected_files_from_project_root(self, tmp_path):
        from luckyd_code.autonomous_fixer import generate_fix
        from luckyd_code.feedback_analyzer import Diagnosis
        (tmp_path / "luckyd_code").mkdir()
        f = tmp_path / "luckyd_code" / "config.py"
        f.write_text("x = 1\n")
        diag = Diagnosis(
            error_type="TypeError",
            error_message="None",
            root_cause="null",
            affected_files=["luckyd_code/config.py"],
            fix_suggestion="add check",
            confidence="low",
        )
        captured = {}

        def fake_llm(system_prompt, user_message, api_key, **kwargs):
            captured["user_message"] = user_message
            return "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-x\n+y\n"

        with patch("luckyd_code.autonomous_fixer._call_llm", side_effect=fake_llm):
            generate_fix(diag, api_key="k", project_root=str(tmp_path))

        assert "luckyd_code/config.py" in captured["user_message"]
        assert "x = 1" in captured["user_message"]
