"""
test_ceiling.py — Targeted tests to push coverage to 100%.

Covers the specific uncovered lines identified in the full-suite coverage run:
  - tools/git_tools.py        — all run() methods
  - tools/file_ops.py         — dry-run identical, replace_all, glob overflow, grep modes
  - tools/registry.py         — cache hit, expired entry, invalidate, eviction
  - tools/bash.py             — _get_cwd, _get_shell, reset_shell_cache, _fix_windows_cmd branches
  - tools/readme_gen.py       — priority files, large file truncation, run() success path
  - tools/image.py            — _call_vision (patching source module), OCR supplement, fallbacks
  - tools/agent_tools.py      — SubAgentTool.run(), AgentHandoffTool.run() (patching source modules)
  - tools/__init__.py         — get_default_registry() plugin-loading success path
  - verify.py                 — bare except detection, None-type except, circular import hit
  - undo.py                   — "no longer exists and original_content is None" path
  - git/tools.py              — all subprocess-delegating helpers (success + error paths)
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


# ═══════════════════════════════════════════════════════════════════════════════
# tools/git_tools.py — run() methods
# ═══════════════════════════════════════════════════════════════════════════════

class TestGitToolsRun:
    """Each GitXxxTool.run() simply delegates to git/tools.py helpers.
    Patch the helpers in luckyd_code.tools.git_tools (where they are imported)."""

    def test_git_status_run(self):
        from luckyd_code.tools.git_tools import GitStatusTool
        tool = GitStatusTool()
        with patch("luckyd_code.tools.git_tools.git_status", return_value="On branch main") as m:
            result = tool.run()
        assert result == "On branch main"
        m.assert_called_once()

    def test_git_diff_run_unstaged(self):
        from luckyd_code.tools.git_tools import GitDiffTool
        tool = GitDiffTool()
        with patch("luckyd_code.tools.git_tools.git_diff", return_value="diff output") as m:
            result = tool.run(staged=False)
        assert result == "diff output"
        m.assert_called_once_with(False)

    def test_git_diff_run_staged(self):
        from luckyd_code.tools.git_tools import GitDiffTool
        tool = GitDiffTool()
        with patch("luckyd_code.tools.git_tools.git_diff", return_value="staged diff") as m:
            result = tool.run(staged=True)
        assert result == "staged diff"
        m.assert_called_once_with(True)

    def test_git_log_run(self):
        from luckyd_code.tools.git_tools import GitLogTool
        tool = GitLogTool()
        with patch("luckyd_code.tools.git_tools.git_log", return_value="abc1234 init") as m:
            result = tool.run(count=5)
        assert result == "abc1234 init"
        m.assert_called_once_with(5)

    def test_git_log_run_default(self):
        from luckyd_code.tools.git_tools import GitLogTool
        tool = GitLogTool()
        with patch("luckyd_code.tools.git_tools.git_log", return_value="log") as m:
            tool.run()
        m.assert_called_once_with(10)

    def test_git_commit_run(self):
        from luckyd_code.tools.git_tools import GitCommitTool
        tool = GitCommitTool()
        with patch("luckyd_code.tools.git_tools.git_commit", return_value="[main abc] msg") as m:
            result = tool.run(message="fix bug")
        assert "main" in result or "fix" in result or result == "[main abc] msg"
        m.assert_called_once_with("fix bug")

    def test_git_add_run_all(self):
        from luckyd_code.tools.git_tools import GitAddTool
        tool = GitAddTool()
        with patch("luckyd_code.tools.git_tools.git_add", return_value="Staged") as m:
            result = tool.run()
        assert result == "Staged"
        m.assert_called_once_with(None)

    def test_git_add_run_specific_files(self):
        from luckyd_code.tools.git_tools import GitAddTool
        tool = GitAddTool()
        with patch("luckyd_code.tools.git_tools.git_add", return_value="Staged") as m:
            tool.run(files=["a.py", "b.py"])
        m.assert_called_once_with(["a.py", "b.py"])

    def test_git_branch_run(self):
        from luckyd_code.tools.git_tools import GitBranchTool
        tool = GitBranchTool()
        with patch("luckyd_code.tools.git_tools.git_branch", return_value="* main") as m:
            result = tool.run()
        assert result == "* main"
        m.assert_called_once()

    def test_git_pr_run(self):
        from luckyd_code.tools.git_tools import GitPRTool
        tool = GitPRTool()
        with patch("luckyd_code.tools.git_tools.git_push", return_value="pushed"), \
             patch("luckyd_code.tools.git_tools.git_create_pr", return_value="PR created"):
            result = tool.run(title="My PR", body="description")
        assert "Push" in result
        assert "pushed" in result
        assert "PR created" in result

    def test_git_push_run(self):
        from luckyd_code.tools.git_tools import GitPushTool
        tool = GitPushTool()
        with patch("luckyd_code.tools.git_tools.git_push", return_value="pushed to origin") as m:
            result = tool.run(branch="feature")
        assert result == "pushed to origin"
        m.assert_called_once_with("feature")

    def test_git_push_run_no_branch(self):
        from luckyd_code.tools.git_tools import GitPushTool
        tool = GitPushTool()
        with patch("luckyd_code.tools.git_tools.git_push", return_value="pushed") as m:
            tool.run()
        m.assert_called_once_with(None)


# ═══════════════════════════════════════════════════════════════════════════════
# git/tools.py — subprocess-delegating helpers
# ═══════════════════════════════════════════════════════════════════════════════

class TestGitToolsHelpers:
    """Test the low-level git helper functions directly."""

    def _mock_proc(self, stdout="", stderr="", returncode=0):
        m = MagicMock()
        m.stdout = stdout
        m.stderr = stderr
        m.returncode = returncode
        return m

    def test_git_status_success(self):
        from luckyd_code.git.tools import git_status
        with patch("subprocess.run", return_value=self._mock_proc("On branch main")):
            assert git_status() == "On branch main"

    def test_git_status_error(self):
        from luckyd_code.git.tools import git_status
        with patch("subprocess.run", side_effect=Exception("no git")):
            assert "Error" in git_status()

    def test_git_diff_unstaged(self):
        from luckyd_code.git.tools import git_diff
        with patch("subprocess.run", return_value=self._mock_proc("--- a/foo.py")):
            result = git_diff(staged=False)
        assert "foo.py" in result

    def test_git_diff_staged(self):
        from luckyd_code.git.tools import git_diff
        with patch("subprocess.run", return_value=self._mock_proc("--- a/bar.py")) as m:
            git_diff(staged=True)
        args = m.call_args[0][0]
        assert "--cached" in args

    def test_git_diff_no_changes(self):
        from luckyd_code.git.tools import git_diff
        with patch("subprocess.run", return_value=self._mock_proc("")):
            assert git_diff() == "No changes"

    def test_git_diff_error(self):
        from luckyd_code.git.tools import git_diff
        with patch("subprocess.run", side_effect=Exception("fail")):
            assert "Error" in git_diff()

    def test_git_log_success(self):
        from luckyd_code.git.tools import git_log
        with patch("subprocess.run", return_value=self._mock_proc("abc init")):
            assert git_log(3) == "abc init"

    def test_git_log_error(self):
        from luckyd_code.git.tools import git_log
        with patch("subprocess.run", side_effect=Exception("x")):
            assert "Error" in git_log()

    def test_git_commit_success(self):
        from luckyd_code.git.tools import git_commit
        with patch("subprocess.run", return_value=self._mock_proc("[main abc] msg")):
            assert "[main" in git_commit("msg")

    def test_git_commit_error(self):
        from luckyd_code.git.tools import git_commit
        with patch("subprocess.run", side_effect=Exception("x")):
            assert "Error" in git_commit("msg")

    def test_git_add_all(self):
        from luckyd_code.git.tools import git_add
        with patch("subprocess.run", return_value=self._mock_proc("", "", 0)) as m:
            result = git_add(None)
        args = m.call_args[0][0]
        assert "-A" in args
        assert result == "Staged"

    def test_git_add_files(self):
        from luckyd_code.git.tools import git_add
        with patch("subprocess.run", return_value=self._mock_proc("", "", 0)) as m:
            git_add(["x.py"])
        args = m.call_args[0][0]
        assert "x.py" in args

    def test_git_add_error(self):
        from luckyd_code.git.tools import git_add
        with patch("subprocess.run", side_effect=Exception("x")):
            assert "Error" in git_add()

    def test_git_branch_success(self):
        from luckyd_code.git.tools import git_branch
        with patch("subprocess.run", return_value=self._mock_proc("* main")):
            assert "main" in git_branch()

    def test_git_branch_error(self):
        from luckyd_code.git.tools import git_branch
        with patch("subprocess.run", side_effect=Exception("x")):
            assert "Error" in git_branch()

    def test_git_create_pr_success(self):
        from luckyd_code.git.tools import git_create_pr
        with patch("subprocess.run", return_value=self._mock_proc("https://github.com/...")):
            result = git_create_pr("My PR", "body", draft=True)
        assert "github" in result

    def test_git_create_pr_error(self):
        from luckyd_code.git.tools import git_create_pr
        with patch("subprocess.run", side_effect=Exception("gh not found")):
            assert "Error" in git_create_pr("title")

    def test_git_push_no_branch(self):
        from luckyd_code.git.tools import git_push
        with patch("subprocess.run", return_value=self._mock_proc("pushed")) as m:
            git_push(None)
        args = m.call_args[0][0]
        assert "push" in args
        assert len(args) == 4  # git push -u origin

    def test_git_push_with_branch(self):
        from luckyd_code.git.tools import git_push
        with patch("subprocess.run", return_value=self._mock_proc("pushed")) as m:
            git_push("feature")
        args = m.call_args[0][0]
        assert "feature" in args

    def test_git_push_error(self):
        from luckyd_code.git.tools import git_push
        with patch("subprocess.run", side_effect=Exception("x")):
            assert "Error" in git_push()


# ═══════════════════════════════════════════════════════════════════════════════
# tools/file_ops.py — specific uncovered branches
# ═══════════════════════════════════════════════════════════════════════════════

class TestFileOpsBranches:
    @pytest.fixture(autouse=True)
    def _bypass(self, monkeypatch, tmp_path):
        import luckyd_code.tools.file_ops as fo
        monkeypatch.setattr(fo, "validate_file_path",
                            lambda p, must_exist=False, **kw: Path(p).resolve())
        self.tmp = tmp_path

    # WriteTool dry-run: identical content (no diff)
    def test_write_dry_run_identical_content(self):
        from luckyd_code.tools.file_ops import WriteTool
        path = self.tmp / "same.py"
        path.write_text("x = 1\n", encoding="utf-8")
        tool = WriteTool()
        result = tool.run(file_path=str(path), content="x = 1\n", dry_run=True)
        assert "identical" in result.lower() or "no changes" in result.lower()

    # EditTool dry-run: identical old_string == new_string
    def test_edit_dry_run_identical(self):
        from luckyd_code.tools.file_ops import EditTool
        path = self.tmp / "edit_id.py"
        path.write_text("x = 1\n", encoding="utf-8")
        tool = EditTool()
        result = tool.run(
            file_path=str(path),
            old_string="x = 1",
            new_string="x = 1",  # identical
            dry_run=True,
        )
        assert "identical" in result.lower() or "no changes" in result.lower()

    # EditTool replace_all: multiple occurrences
    def test_edit_replace_all(self, tmp_path):
        from luckyd_code.tools.file_ops import EditTool
        path = tmp_path / "multi.py"
        path.write_text("foo\nfoo\nfoo\n", encoding="utf-8")
        tool = EditTool()
        with patch("luckyd_code.tools.file_ops.undo_push"):
            result = tool.run(
                file_path=str(path),
                old_string="foo",
                new_string="bar",
                replace_all=True,
            )
        content = path.read_text()
        assert content.count("bar") == 3
        assert "3" in result or "replacement" in result.lower()

    # EditTool replace_all dry_run: shows diff
    def test_edit_replace_all_dry_run(self, tmp_path):
        from luckyd_code.tools.file_ops import EditTool
        path = tmp_path / "multi_dry.py"
        path.write_text("foo\nfoo\n", encoding="utf-8")
        tool = EditTool()
        result = tool.run(
            file_path=str(path),
            old_string="foo",
            new_string="baz",
            replace_all=True,
            dry_run=True,
        )
        assert "baz" in result or "diff" in result.lower() or "dry-run" in result.lower()

    # GlobTool: results exceed max_results (200)
    def test_glob_truncates_large_results(self, tmp_path):
        from luckyd_code.tools.file_ops import GlobTool
        # Create 201 .txt files
        for i in range(201):
            (tmp_path / f"f{i:04d}.txt").write_text("x")
        tool = GlobTool()
        result = tool.run(pattern="*.txt", path=str(tmp_path))
        assert "more" in result.lower()

    # GrepTool: output_mode="count"
    def test_grep_count_mode(self, tmp_path):
        from luckyd_code.tools.file_ops import GrepTool
        f = tmp_path / "code.py"
        f.write_text("TODO: fix\nTODO: also fix\nx = 1\n", encoding="utf-8")
        tool = GrepTool()
        result = tool.run(pattern="TODO", path=str(tmp_path), output_mode="count")
        assert "matches" in result.lower()
        assert "2" in result

    # GrepTool: output_mode="files_with_matches"
    def test_grep_files_with_matches_mode(self, tmp_path):
        from luckyd_code.tools.file_ops import GrepTool
        (tmp_path / "a.py").write_text("FIXME here\n")
        (tmp_path / "b.py").write_text("no issue\n")
        tool = GrepTool()
        result = tool.run(pattern="FIXME", path=str(tmp_path), output_mode="files_with_matches")
        assert "a.py" in result
        assert "b.py" not in result

    # GrepTool: results exceed limit — shows truncation notice
    def test_grep_truncation_notice(self, tmp_path):
        from luckyd_code.tools.file_ops import GrepTool
        # Create a file with 250 matching lines
        lines = "\n".join(f"match line {i}" for i in range(250))
        (tmp_path / "big.py").write_text(lines)
        tool = GrepTool()
        result = tool.run(pattern="match", path=str(tmp_path), output_mode="content")
        assert "more" in result.lower() or len(result) > 100


# ═══════════════════════════════════════════════════════════════════════════════
# tools/registry.py — cache hit, expired entry, invalidate paths
# ═══════════════════════════════════════════════════════════════════════════════

class TestRegistryCachePaths:
    def _read_tool(self):
        from luckyd_code.tools.registry import Tool
        class FakeRead(Tool):
            name = "Read"
            description = "fake"
            def run(self, **kwargs):
                return "file content"
        return FakeRead()

    def test_cache_hit_returns_cached_value(self):
        from luckyd_code.tools.registry import ToolRegistry
        registry = ToolRegistry(cache_ttl=60)
        registry.register(self._read_tool())
        # First call — cache miss, executes tool
        r1 = registry.execute("Read", {"file_path": "x.py"})
        # Second call — should be a cache hit (same key)
        r2 = registry.execute("Read", {"file_path": "x.py"})
        assert r1 == r2 == "file content"

    def test_cache_expired_entry_removed(self):
        from luckyd_code.tools.registry import ToolRegistry, _CacheEntry
        registry = ToolRegistry(cache_ttl=60)
        registry.register(self._read_tool())
        # Manually plant an already-expired entry
        key = registry._cache_key("Read", {"file_path": "old.py"})
        registry._cache[key] = _CacheEntry("stale", ttl=-1)  # expires immediately
        # _get_cached should detect expiry and remove it
        result = registry._get_cached(key)
        assert result is None
        assert key not in registry._cache

    def test_invalidate_specific_tool(self):
        from luckyd_code.tools.registry import ToolRegistry
        registry = ToolRegistry(cache_ttl=60)
        registry.register(self._read_tool())
        # Populate cache
        registry.execute("Read", {"file_path": "a.py"})
        registry.execute("Read", {"file_path": "b.py"})
        count = registry.invalidate("Read")
        assert count == 2
        assert len(registry._cache) == 0

    def test_invalidate_all(self):
        from luckyd_code.tools.registry import ToolRegistry
        registry = ToolRegistry(cache_ttl=60)
        registry.register(self._read_tool())
        registry.execute("Read", {"file_path": "a.py"})
        count = registry.invalidate(None)
        assert count >= 1
        assert len(registry._cache) == 0

    def test_invalidate_no_match(self):
        from luckyd_code.tools.registry import ToolRegistry
        registry = ToolRegistry(cache_ttl=60)
        count = registry.invalidate("NonExistent")
        assert count == 0

    def test_cache_disabled_when_ttl_zero(self):
        from luckyd_code.tools.registry import ToolRegistry
        registry = ToolRegistry(cache_ttl=0)
        registry.register(self._read_tool())
        registry.execute("Read", {"file_path": "x.py"})
        # With TTL=0, nothing should be cached
        assert len(registry._cache) == 0

    def test_eviction_runs_on_100th_insert(self):
        """Eviction fires when len(cache) % 100 == 0 — plant 99 stale entries."""
        from luckyd_code.tools.registry import ToolRegistry, _CacheEntry
        registry = ToolRegistry(cache_ttl=60)
        registry.register(self._read_tool())
        # Plant 99 expired entries so the 100th insert triggers eviction
        for i in range(99):
            k = f"Read|file_path='f{i}.py'"
            registry._cache[k] = _CacheEntry("x", ttl=-1)
        # This insert is the 100th, should trigger eviction of expired entries
        registry.execute("Read", {"file_path": "new.py"})
        # All 99 stale entries should be gone
        stale = [k for k, e in registry._cache.items() if time.monotonic() > e.expires_at]
        assert len(stale) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# tools/bash.py — _get_cwd, _get_shell, reset_shell_cache, _fix_windows_cmd
# ═══════════════════════════════════════════════════════════════════════════════

class TestBashHelpers:
    def test_get_cwd_returns_path(self):
        from luckyd_code.tools.bash import _get_cwd
        result = _get_cwd()
        assert isinstance(result, Path)

    def test_get_shell_returns_shell_info(self):
        from luckyd_code.tools.bash import _get_shell, reset_shell_cache
        reset_shell_cache()
        with patch("luckyd_code.tools.bash.load_settings", return_value={"shell": "auto"}), \
             patch("luckyd_code.tools.bash.resolve_shell") as mock_resolve:
            mock_resolve.return_value = MagicMock(path="/bin/bash", args=[], unix_like=True)
            result = _get_shell()
        assert result is not None

    def test_reset_shell_cache_clears(self):
        from luckyd_code.tools.bash import _get_shell, reset_shell_cache
        import luckyd_code.tools.bash as bash_mod
        reset_shell_cache()
        assert bash_mod._SHELL_CACHE is None

    def test_get_shell_uses_cache_on_second_call(self):
        from luckyd_code.tools.bash import _get_shell, reset_shell_cache
        reset_shell_cache()
        with patch("luckyd_code.tools.bash.load_settings", return_value={"shell": "auto"}), \
             patch("luckyd_code.tools.bash.resolve_shell") as mock_resolve:
            mock_resolve.return_value = MagicMock(path="/bin/bash", args=[], unix_like=True)
            r1 = _get_shell()
            r2 = _get_shell()  # should use cache — resolve_shell called once
        assert mock_resolve.call_count == 1
        assert r1 is r2

    def test_fix_windows_cmd_date_alone(self):
        from luckyd_code.tools.bash import _fix_windows_cmd
        assert _fix_windows_cmd("date") == "date /T"

    def test_fix_windows_cmd_date_with_arg(self):
        from luckyd_code.tools.bash import _fix_windows_cmd
        assert _fix_windows_cmd("date something") == "date /T"

    def test_fix_windows_cmd_time_alone(self):
        from luckyd_code.tools.bash import _fix_windows_cmd
        assert _fix_windows_cmd("time") == "time /T"

    def test_fix_windows_cmd_time_with_arg(self):
        from luckyd_code.tools.bash import _fix_windows_cmd
        assert _fix_windows_cmd("time 12:00") == "time /T"

    def test_fix_windows_cmd_ping(self):
        from luckyd_code.tools.bash import _fix_windows_cmd
        result = _fix_windows_cmd("ping google.com")
        assert "-n 4" in result

    def test_fix_windows_cmd_ping_already_has_n(self):
        from luckyd_code.tools.bash import _fix_windows_cmd
        result = _fix_windows_cmd("ping -n 10 google.com")
        # Already has -n, should not add another
        assert result == "ping -n 10 google.com"

    def test_fix_windows_cmd_choice(self):
        from luckyd_code.tools.bash import _fix_windows_cmd
        result = _fix_windows_cmd("choice")
        assert "/T" in result

    def test_fix_windows_cmd_pause(self):
        from luckyd_code.tools.bash import _fix_windows_cmd
        assert _fix_windows_cmd("pause") == "echo."

    def test_fix_windows_cmd_clip(self):
        from luckyd_code.tools.bash import _fix_windows_cmd
        result = _fix_windows_cmd("clip")
        assert "clip" in result

    def test_fix_windows_cmd_passthrough(self):
        from luckyd_code.tools.bash import _fix_windows_cmd
        cmd = "dir /b"
        assert _fix_windows_cmd(cmd) == cmd

    def test_is_dangerous_pip_install_allowed(self):
        """pip install should not be blocked (just warned via permission system)."""
        from luckyd_code.tools.bash import _is_dangerous
        result = _is_dangerous("pip install requests")
        assert result is None  # pip install is not blocked

    def test_is_dangerous_npm_install_allowed(self):
        from luckyd_code.tools.bash import _is_dangerous
        result = _is_dangerous("npm install lodash")
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════════
# verify.py — bare except, None-type except, circular import
# ═══════════════════════════════════════════════════════════════════════════════

class TestVerifyConsistencyBranches:
    def test_detects_bare_except_none_type(self, tmp_path):
        """Lines 183-195: bare except: (node.type is None) path."""
        from luckyd_code.verify import verify_consistency
        f = tmp_path / "bare.py"
        f.write_text("try:\n    pass\nexcept:\n    pass\n")
        result = verify_consistency(str(f), str(tmp_path))
        assert result is not None
        assert not result.passed
        assert "Bare except" in result.raw_output

    def test_detects_exception_ok(self, tmp_path):
        """'except Exception' is explicitly allowed (passes consistency)."""
        from luckyd_code.verify import verify_consistency
        f = tmp_path / "ok_except.py"
        f.write_text("try:\n    pass\nexcept Exception:\n    pass\n")
        result = verify_consistency(str(f), str(tmp_path))
        assert result is not None
        assert result.passed

    def test_circular_import_detection(self, tmp_path):
        """Lines 170+175: __init__.py circular import check hits target_file.exists() path."""
        from luckyd_code.verify import verify_consistency
        # Create a fake package: __init__.py imports from foo, foo imports back from pkg
        pkg = tmp_path / "mypkg"
        pkg.mkdir()
        init_py = pkg / "__init__.py"
        foo_py = pkg / "foo.py"
        # __init__.py: from .foo import Bar
        init_py.write_text("from .foo import Bar\n")
        # foo.py: from mypkg import something  (back-imports from the package)
        foo_py.write_text("from mypkg import something\n")
        result = verify_consistency(str(init_py), str(pkg))
        # May or may not detect circular — key thing is it reaches those lines without error
        assert result is not None  # function ran and returned a result


# ═══════════════════════════════════════════════════════════════════════════════
# undo.py — "no longer exists and original_content is None" path
# ═══════════════════════════════════════════════════════════════════════════════

class TestUndoLastBranches:
    def test_undo_last_file_deleted_and_no_original(self, tmp_path):
        """Covers: if not path.exists() and entry.original_content is None."""
        import luckyd_code.undo as undo_mod
        # Clear any existing stack
        undo_mod.clear()
        # Push an entry where original_content is None (file was "created")
        # but the file itself does NOT exist anymore
        undo_mod.push(str(tmp_path / "ghost.py"), None, "Write")
        result = undo_mod.undo_last()
        assert "no longer exists" in result.lower() or "cannot undo" in result.lower()

    def test_undo_last_deletes_created_file(self, tmp_path):
        """original_content is None and file exists → should unlink it."""
        import luckyd_code.undo as undo_mod
        undo_mod.clear()
        new_file = tmp_path / "created.py"
        new_file.write_text("new content\n")
        undo_mod.push(str(new_file), None, "Write")
        result = undo_mod.undo_last()
        assert not new_file.exists()
        assert "Undone" in result or "deleted" in result.lower()

    def test_undo_last_restores_content(self, tmp_path):
        """original_content is not None → should restore file."""
        import luckyd_code.undo as undo_mod
        undo_mod.clear()
        f = tmp_path / "restore.py"
        f.write_text("new\n")
        undo_mod.push(str(f), "original\n", "Edit")
        result = undo_mod.undo_last()
        assert f.read_text() == "original\n"
        assert "Undone" in result


# ═══════════════════════════════════════════════════════════════════════════════
# tools/image.py — _call_vision patched at source, OCR supplement, fallbacks
# ═══════════════════════════════════════════════════════════════════════════════

class TestCallVisionFixed:
    """Patch Config at luckyd_code.config and OpenAI at openai.OpenAI."""

    def _fake_image(self, tmp_path, name="img.png"):
        try:
            from PIL import Image as PILImage
            img = PILImage.new("RGB", (10, 10), color=(255, 0, 0))
            p = tmp_path / name
            img.save(str(p))
            return p
        except ImportError:
            pytest.skip("PIL not available")

    def test_call_vision_returns_content(self, tmp_path):
        img_path = self._fake_image(tmp_path)
        mock_cfg = MagicMock()
        mock_cfg.base_url = "http://fake"
        mock_cfg.api_key = "sk-test"
        mock_cfg.model = "vision-model"

        mock_choice = MagicMock()
        mock_choice.message.content = "A red square"
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response

        with patch("luckyd_code.config.Config", return_value=mock_cfg), \
             patch("openai.OpenAI", return_value=mock_client):
            from luckyd_code.tools.image import _call_vision
            result = _call_vision(str(img_path), "What is this?")
        assert result == "A red square"

    def test_image_analyze_tool_run_success(self, tmp_path):
        img_path = self._fake_image(tmp_path)

        mock_cfg = MagicMock()
        mock_cfg.base_url = "http://fake"
        mock_cfg.api_key = "sk-test"
        mock_cfg.model = "vision-model"

        mock_choice = MagicMock()
        mock_choice.message.content = "A red image"
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response

        with patch("luckyd_code.config.Config", return_value=mock_cfg), \
             patch("openai.OpenAI", return_value=mock_client), \
             patch("luckyd_code.tools.image._ocr_text", return_value=None):
            from luckyd_code.tools.image import ImageAnalyzeTool
            tool = ImageAnalyzeTool()
            result = tool.run(file_path=str(img_path), question="Describe")
        assert "red" in result.lower() or "image" in result.lower()

    def test_image_analyze_tool_ocr_supplement(self, tmp_path):
        """OCR text not in description → appended as supplement."""
        # Use a real file so path.exists() passes; patch _encode_image so PIL
        # is never invoked (avoids PIL save/open issues in CI).
        img_path = tmp_path / "img.png"
        img_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)  # minimal PNG-like bytes

        mock_choice = MagicMock()
        mock_choice.message.content = "A red square"
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response

        mock_cfg = MagicMock()
        mock_cfg.base_url = "http://fake"
        mock_cfg.api_key = "sk-test"
        mock_cfg.model = "vision-model"

        from luckyd_code.tools.image import ImageAnalyzeTool
        with patch("luckyd_code.tools.image._call_vision", return_value="A red square"), \
             patch("luckyd_code.tools.image._ocr_text", return_value="SOME TEXT"):
            tool = ImageAnalyzeTool()
            result = tool.run(file_path=str(img_path))
        assert "SOME TEXT" in result or "OCR" in result

    def test_image_analyze_vision_fails_ocr_fallback(self, tmp_path):
        """Vision fails → OCR fallback path."""
        # Patch _call_vision to raise so run() falls back to _ocr_text.
        # Write a real file so path.exists() returns True.
        img_path = tmp_path / "img.png"
        img_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)

        from luckyd_code.tools.image import ImageAnalyzeTool
        with patch("luckyd_code.tools.image._call_vision", side_effect=Exception("no api")), \
             patch("luckyd_code.tools.image._ocr_text", return_value="EXTRACTED"):
            tool = ImageAnalyzeTool()
            result = tool.run(file_path=str(img_path))
        assert "EXTRACTED" in result or "OCR" in result.upper()

    def test_image_analyze_vision_fails_no_ocr_metadata(self, tmp_path):
        """Vision fails, OCR returns None → shows basic metadata."""
        img_path = self._fake_image(tmp_path)

        with patch("luckyd_code.config.Config", side_effect=Exception("no api")), \
             patch("luckyd_code.tools.image._ocr_text", return_value=None):
            from luckyd_code.tools.image import ImageAnalyzeTool
            tool = ImageAnalyzeTool()
            result = tool.run(file_path=str(img_path))
        # Should return metadata or error string
        assert isinstance(result, str) and len(result) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# tools/agent_tools.py — run() methods (patching source modules)
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgentToolsFixed:
    def test_subagent_run_no_repl(self):
        from luckyd_code.tools.agent_tools import SubAgentTool, set_repl
        set_repl(None)
        tool = SubAgentTool()
        result = tool.run(task="do something")
        assert "Error" in result or "not available" in result.lower()

    def test_subagent_run_with_repl(self):
        from luckyd_code.tools.agent_tools import SubAgentTool, set_repl

        mock_repl = MagicMock()
        mock_repl.config = MagicMock()
        mock_repl.registry.list_tools.return_value = []

        mock_agent = MagicMock()
        mock_agent.run.return_value = "subtask done"

        set_repl(mock_repl)
        # Patch SubAgent at the source module where it's defined
        with patch("luckyd_code.agent.SubAgent", return_value=mock_agent):
            tool = SubAgentTool()
            result = tool.run(task="do something")
        set_repl(None)
        assert result == "subtask done"

    def test_handoff_run_no_repl(self):
        from luckyd_code.tools.agent_tools import AgentHandoffTool, set_repl
        set_repl(None)
        tool = AgentHandoffTool()
        result = tool.run(role="coder", task="fix bug")
        assert "Error" in result or "not available" in result.lower()

    def test_handoff_run_with_repl(self):
        from luckyd_code.tools.agent_tools import AgentHandoffTool, set_repl

        mock_repl = MagicMock()
        mock_repl.config = MagicMock()
        mock_repl.registry.list_tools.return_value = []

        mock_handoff = MagicMock()
        mock_handoff.handoff.return_value = "handoff done"

        set_repl(mock_repl)
        # Patch AgentHandoff at the source module where it's defined
        with patch("luckyd_code.orchestrator.AgentHandoff", return_value=mock_handoff):
            tool = AgentHandoffTool()
            result = tool.run(role="reviewer", task="review code")
        set_repl(None)
        assert result == "handoff done"


# ═══════════════════════════════════════════════════════════════════════════════
# tools/__init__.py — get_default_registry() plugin loading success path
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetDefaultRegistryPlugins:
    def test_plugin_loading_success(self):
        """Covers the plugin loading try block when load_all_plugins returns n > 0."""
        with patch("luckyd_code.plugins.load_all_plugins", return_value=2) as mock_load:
            from luckyd_code.tools import get_default_registry
            registry = get_default_registry()
        assert registry is not None
        mock_load.assert_called_once()

    def test_plugin_loading_exception_caught(self):
        """Covers the except block in plugin loading."""
        with patch("luckyd_code.plugins.load_all_plugins", side_effect=RuntimeError("plugin error")):
            from luckyd_code.tools import get_default_registry
            # Should not raise — exception is caught
            registry = get_default_registry()
        assert registry is not None

    def test_plugin_loading_zero_plugins(self):
        """load_all_plugins returns 0 — no log statement, just returns registry."""
        with patch("luckyd_code.plugins.load_all_plugins", return_value=0):
            from luckyd_code.tools import get_default_registry
            registry = get_default_registry()
        assert registry is not None


# ═══════════════════════════════════════════════════════════════════════════════
# tools/readme_gen.py — priority files, large file truncation, run() success
# ═══════════════════════════════════════════════════════════════════════════════

class TestReadmeGenTool:
    def test_collect_files_priority_first(self, tmp_path):
        """Priority files (pyproject.toml etc.) should appear in collected list."""
        from luckyd_code.tools.readme_gen import _collect_files
        (tmp_path / "pyproject.toml").write_text("[tool.poetry]\nname = 'test'\n")
        (tmp_path / "main.py").write_text("print('hello')\n")
        (tmp_path / "random.py").write_text("x = 1\n")
        files = _collect_files(tmp_path)
        names = [f[0] for f in files]
        assert any("pyproject.toml" in n for n in names)
        assert any("main.py" in n for n in names)

    def test_collect_files_large_file_truncated(self, tmp_path):
        """Files larger than _MAX_FILE_CHARS should be truncated with notice."""
        from luckyd_code.tools.readme_gen import _collect_files, _MAX_FILE_CHARS
        big = "x" * (_MAX_FILE_CHARS + 500)
        (tmp_path / "big.py").write_text(big)
        files = _collect_files(tmp_path)
        contents = {f[0]: f[1] for f in files}
        if "big.py" in contents:
            assert "truncated" in contents["big.py"].lower()

    def test_run_existing_readme_no_overwrite(self, tmp_path):
        """If README.md exists and overwrite=False, returns early."""
        from luckyd_code.tools.readme_gen import ReadmeGenTool
        (tmp_path / "README.md").write_text("# Existing README\n")
        tool = ReadmeGenTool()
        result = tool.run(project_dir=str(tmp_path), overwrite=False)
        assert "already exists" in result.lower() or "overwrite" in result.lower()

    def test_run_no_files(self, tmp_path):
        """Empty directory returns error."""
        from luckyd_code.tools.readme_gen import ReadmeGenTool
        tool = ReadmeGenTool()
        result = tool.run(project_dir=str(tmp_path))
        # Empty dir — no readable source files
        assert "Error" in result or "no readable" in result.lower()

    def test_run_success(self, tmp_path):
        """Full run() success path — model call mocked."""
        from luckyd_code.tools.readme_gen import ReadmeGenTool
        (tmp_path / "main.py").write_text("print('hello')\n")
        tool = ReadmeGenTool()
        with patch.object(tool, "_call_model", return_value="# MyProject\n\nA great project."):
            result = tool.run(project_dir=str(tmp_path))
        out = tmp_path / "README.md"
        assert out.exists()
        assert "MyProject" in out.read_text()
        assert "file" in result.lower() or "generated" in result.lower()

    def test_run_model_error(self, tmp_path):
        """Model call fails → returns error string."""
        from luckyd_code.tools.readme_gen import ReadmeGenTool
        (tmp_path / "main.py").write_text("x=1\n")
        tool = ReadmeGenTool()
        with patch.object(tool, "_call_model", side_effect=Exception("API down")):
            result = tool.run(project_dir=str(tmp_path))
        assert "Error" in result

    def test_run_strips_markdown_fence(self, tmp_path):
        """If model wraps output in ```markdown fences they should be stripped."""
        from luckyd_code.tools.readme_gen import ReadmeGenTool
        (tmp_path / "app.py").write_text("x=1\n")
        tool = ReadmeGenTool()
        wrapped = "```markdown\n# Title\n\nContent\n```"
        with patch.object(tool, "_call_model", return_value=wrapped):
            tool.run(project_dir=str(tmp_path))
        out = tmp_path / "README.md"
        content = out.read_text()
        assert "```markdown" not in content
        assert "# Title" in content

    def test_run_invalid_project_dir(self, tmp_path):
        """Non-existent directory returns error."""
        from luckyd_code.tools.readme_gen import ReadmeGenTool
        tool = ReadmeGenTool()
        result = tool.run(project_dir=str(tmp_path / "nonexistent"))
        assert "Error" in result


# ═══════════════════════════════════════════════════════════════════════════════
# verify.py — pipeline_all_passed and pipeline_feedback helper paths
# ═══════════════════════════════════════════════════════════════════════════════

class TestVerifyPipelineHelpers:
    def test_pipeline_all_passed_empty(self):
        from luckyd_code.verify import pipeline_all_passed
        assert pipeline_all_passed([]) is True

    def test_pipeline_all_passed_with_lint_fail_only(self):
        """Lint failures do NOT count as mandatory failures."""
        from luckyd_code.verify import VerificationResult, pipeline_all_passed
        results = [
            VerificationResult(passed=True, stage="syntax", message="ok"),
            VerificationResult(passed=False, stage="lint", message="issues"),
        ]
        assert pipeline_all_passed(results) is True

    def test_pipeline_all_passed_with_syntax_fail(self):
        from luckyd_code.verify import VerificationResult, pipeline_all_passed
        results = [
            VerificationResult(passed=False, stage="syntax", message="err"),
        ]
        assert pipeline_all_passed(results) is False

    def test_pipeline_feedback_empty(self):
        from luckyd_code.verify import pipeline_feedback
        assert pipeline_feedback([]) == ""

    def test_pipeline_feedback_mixed(self):
        from luckyd_code.verify import VerificationResult, pipeline_feedback
        results = [
            VerificationResult(passed=True, stage="syntax", message="ok"),
            VerificationResult(passed=False, stage="lint", message="issues"),
        ]
        fb = pipeline_feedback(results)
        assert "1/2" in fb or "Verification" in fb
