"""Tests to boost coverage across low-coverage modules.

Targets: skills, tasks, permissions, update, git/auto_commit,
         memory/user, brain/retriever, tools (game_gen, project_gen,
         readme_gen, git_worktree, brain_tools), web routes (brain, background).
"""

import json
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

# =============================================================================
# skills/review.py  (currently 18%)
# =============================================================================

class TestReviewSkill:
    def test_returns_diff_when_present(self):
        from luckyd_code.skills.review import review_changes
        mock = MagicMock(); mock.stdout = "diff --git a/foo.py b/foo.py\n+added"
        with patch("subprocess.run", return_value=mock):
            result = review_changes()
        assert "Changes to review" in result

    def test_falls_back_to_cached_diff(self):
        from luckyd_code.skills.review import review_changes
        no_diff = MagicMock(); no_diff.stdout = ""
        has_diff = MagicMock(); has_diff.stdout = "diff --cached content"
        with patch("subprocess.run", side_effect=[no_diff, has_diff]):
            result = review_changes()
        assert "Changes to review" in result

    def test_no_changes(self):
        from luckyd_code.skills.review import review_changes
        empty = MagicMock(); empty.stdout = ""
        with patch("subprocess.run", return_value=empty):
            result = review_changes()
        assert result == "No changes to review."

    def test_exception_handling(self):
        from luckyd_code.skills.review import review_changes
        with patch("subprocess.run", side_effect=Exception("git not found")):
            result = review_changes()
        assert "Error" in result


# =============================================================================
# skills/security.py  (currently 22%)
# =============================================================================

class TestSecuritySkill:
    def test_returns_diff_when_present(self):
        from luckyd_code.skills.security import security_review
        # A clean diff (no security patterns) still returns a scan result
        mock = MagicMock(); mock.stdout = "diff --git a/auth.py\n+x = 1"
        with patch("subprocess.run", return_value=mock):
            result = security_review()
        assert "security" in result.lower() or "✅" in result

    def test_no_changes(self):
        from luckyd_code.skills.security import security_review
        empty = MagicMock(); empty.stdout = ""
        with patch("subprocess.run", return_value=empty):
            result = security_review()
        assert "No pending changes" in result

    def test_exception_handling(self):
        from luckyd_code.skills.security import security_review
        with patch("subprocess.run", side_effect=Exception("no git")):
            result = security_review()
        assert "Error" in result


# =============================================================================
# tasks/manager.py  (currently 23%)
# =============================================================================

class TestTaskManager:
    @pytest.fixture(autouse=True)
    def _patch_db(self, tmp_path):
        db = tmp_path / "tasks.json"
        with patch("luckyd_code.tasks.manager._get_db_path", return_value=db):
            yield

    def test_create_and_list(self):
        from luckyd_code.tasks.manager import create_task, list_tasks
        t = create_task("Write tests")
        assert t.id
        assert t.status == "pending"
        listing = list_tasks()
        assert "Write tests" in listing

    def test_list_empty(self):
        from luckyd_code.tasks.manager import list_tasks
        assert list_tasks() == "No tasks."

    def test_list_filter_by_status(self):
        from luckyd_code.tasks.manager import create_task, list_tasks, update_task
        create_task("Task A")
        t2 = create_task("Task B")
        update_task(t2.id, status="completed")
        result = list_tasks(status="completed")
        assert "Task B" in result
        assert "Task A" not in result

    def test_list_no_matching_status(self):
        from luckyd_code.tasks.manager import create_task, list_tasks
        create_task("Task A")
        result = list_tasks(status="deleted")
        assert result == "No matching tasks."

    def test_update_task_status(self):
        from luckyd_code.tasks.manager import create_task, update_task
        t = create_task("Do something")
        msg = update_task(t.id, status="in_progress")
        assert "updated" in msg

    def test_update_task_subject_and_description(self):
        from luckyd_code.tasks.manager import create_task, update_task, get_task
        t = create_task("Old name")
        update_task(t.id, subject="New name", description="new desc")
        loaded = get_task(t.id)
        assert loaded.subject == "New name"

    def test_update_nonexistent_task(self):
        from luckyd_code.tasks.manager import update_task
        result = update_task("nonexistent", status="done")
        assert "Error" in result

    def test_get_task(self):
        from luckyd_code.tasks.manager import create_task, get_task
        t = create_task("Get me", description="desc here")
        loaded = get_task(t.id)
        assert loaded is not None
        assert loaded.subject == "Get me"

    def test_get_nonexistent_task(self):
        from luckyd_code.tasks.manager import get_task
        assert get_task("notreal") is None

    def test_create_with_blocked_by(self):
        from luckyd_code.tasks.manager import create_task
        t = create_task("Blocked", blocked_by=["abc123"])
        assert "abc123" in t.blocked_by

    def test_blocked_by_shown_in_listing(self):
        from luckyd_code.tasks.manager import create_task, list_tasks
        create_task("Blocked task", blocked_by=["dep001"])
        result = list_tasks()
        assert "dep001" in result

    def test_task_to_dict(self):
        from luckyd_code.tasks.manager import Task
        t = Task("Test", "desc", "abc123")
        d = t.to_dict()
        assert d["id"] == "abc123"
        assert d["subject"] == "Test"
        assert d["status"] == "pending"

    def test_load_tasks_corrupt_json(self, tmp_path):
        from luckyd_code.tasks.manager import list_tasks
        db = tmp_path / "tasks.json"
        db.write_text("not-valid-json")
        with patch("luckyd_code.tasks.manager._get_db_path", return_value=db):
            result = list_tasks()
        assert result == "No tasks."

    def test_load_tasks_non_dict_json(self, tmp_path):
        from luckyd_code.tasks.manager import list_tasks
        db = tmp_path / "tasks.json"
        db.write_text(json.dumps([1, 2, 3]))
        with patch("luckyd_code.tasks.manager._get_db_path", return_value=db):
            result = list_tasks()
        assert result == "No tasks."


# =============================================================================
# permissions/__init__.py + manager.py  (currently 0%)
# =============================================================================

class TestPermissions:
    def test_safe_tool_always_allowed(self):
        from luckyd_code.permissions import check_permission
        with patch("luckyd_code.permissions.manager._load_allowlist", return_value=set()):
            assert check_permission("Read") is True

    def test_tool_in_allowlist_allowed(self):
        from luckyd_code.permissions import check_permission
        with patch("luckyd_code.permissions.manager._load_allowlist", return_value={"Bash"}):
            assert check_permission("Bash") is True

    def test_medium_risk_prompts_and_allows(self):
        from luckyd_code.permissions import check_permission
        with patch("luckyd_code.permissions.manager._load_allowlist", return_value=set()):
            with patch("luckyd_code.permissions.manager._prompt_user", return_value=True):
                assert check_permission("Write") is True

    def test_high_risk_prompts_and_denies(self):
        from luckyd_code.permissions import check_permission
        with patch("luckyd_code.permissions.manager._load_allowlist", return_value=set()):
            with patch("luckyd_code.permissions.manager._prompt_user", return_value=False):
                assert check_permission("Bash") is False

    def test_unknown_tool_treated_as_high_risk(self):
        from luckyd_code.permissions import check_permission
        with patch("luckyd_code.permissions.manager._load_allowlist", return_value=set()):
            with patch("luckyd_code.permissions.manager._prompt_user", return_value=False):
                assert check_permission("UnknownTool") is False

    def test_tool_risks_exported(self):
        from luckyd_code.permissions import TOOL_RISKS
        assert "Read" in TOOL_RISKS
        assert TOOL_RISKS["Read"] == "safe"
        assert TOOL_RISKS["Bash"] == "high"

    def test_prompt_user_always_allow(self, tmp_path):
        from luckyd_code.permissions.manager import _prompt_user
        settings = tmp_path / "s.json"
        with patch("luckyd_code.permissions.manager._get_settings_path", return_value=settings):
            with patch("luckyd_code.permissions.manager._load_allowlist", return_value=set()):
                with patch("builtins.input", return_value="y"):
                    result = _prompt_user("Write", "medium")
        assert result is True

    def test_prompt_user_allow_once(self):
        from luckyd_code.permissions.manager import _prompt_user
        with patch("builtins.input", return_value="a"):
            result = _prompt_user("Edit", "medium")
        assert result is True

    def test_prompt_user_deny(self):
        from luckyd_code.permissions.manager import _prompt_user
        with patch("builtins.input", return_value="n"):
            result = _prompt_user("Bash", "high")
        assert result is False

    def test_prompt_user_skip(self):
        from luckyd_code.permissions.manager import _prompt_user
        with patch("builtins.input", return_value="s"):
            result = _prompt_user("Bash", "high")
        assert result is False

    def test_prompt_user_eoferror(self):
        from luckyd_code.permissions.manager import _prompt_user
        with patch("builtins.input", side_effect=EOFError):
            result = _prompt_user("Bash", "high")
        assert result is False

    def test_prompt_user_too_many_invalid(self):
        from luckyd_code.permissions.manager import _prompt_user
        with patch("builtins.input", return_value="zzz"):
            result = _prompt_user("Bash", "high")
        assert result is False

    def test_load_allowlist_missing_file(self, tmp_path):
        from luckyd_code.permissions.manager import _load_allowlist
        missing = tmp_path / "no.json"
        with patch("luckyd_code.permissions.manager._get_settings_path", return_value=missing):
            assert _load_allowlist() == set()

    def test_load_allowlist_corrupt_json(self, tmp_path):
        from luckyd_code.permissions.manager import _load_allowlist
        bad = tmp_path / "bad.json"
        bad.write_text("not-json")
        with patch("luckyd_code.permissions.manager._get_settings_path", return_value=bad):
            assert _load_allowlist() == set()


# =============================================================================
# update.py  (currently 20%)
# =============================================================================

class TestUpdate:
    def test_get_version(self):
        from luckyd_code.update import get_version
        v = get_version()
        assert isinstance(v, str) and len(v) > 0

    def test_check_for_updates_behind(self):
        from luckyd_code.update import check_for_updates
        fetch = MagicMock(returncode=0, stdout="")
        count = MagicMock(returncode=0, stdout="3\n")
        with patch("subprocess.run", side_effect=[fetch, count]):
            result = check_for_updates()
        assert "3 commit" in result

    def test_check_for_updates_up_to_date(self):
        from luckyd_code.update import check_for_updates
        fetch = MagicMock(returncode=0, stdout="")
        count = MagicMock(returncode=0, stdout="0\n")
        remote = MagicMock(returncode=0, stdout="origin  https://github.com/foo")
        with patch("subprocess.run", side_effect=[fetch, count, remote]):
            result = check_for_updates()
        assert "Up to date" in result

    def test_check_for_updates_no_remote(self):
        from luckyd_code.update import check_for_updates
        fetch = MagicMock(returncode=0, stdout="")
        count = MagicMock(returncode=0, stdout="0\n")
        remote = MagicMock(returncode=0, stdout="")
        with patch("subprocess.run", side_effect=[fetch, count, remote]):
            result = check_for_updates()
        assert "Not a git" in result or "remote" in result.lower()

    def test_check_for_updates_exception(self):
        from luckyd_code.update import check_for_updates
        with patch("subprocess.run", side_effect=Exception("no git")):
            result = check_for_updates()
        assert "Cannot check" in result

    def test_do_update_no_changes(self):
        from luckyd_code.update import do_update
        status = MagicMock(returncode=0, stdout="")
        pull = MagicMock(returncode=0, stdout="Already up to date.", stderr="")
        with patch("subprocess.run", side_effect=[status, pull]):
            result = do_update()
        assert "Already up to date" in result or result

    def test_do_update_with_changes_stashes(self):
        from luckyd_code.update import do_update
        status = MagicMock(returncode=0, stdout=" M file.py\n")
        stash = MagicMock(returncode=0, stdout="Saved")
        pull = MagicMock(returncode=0, stdout="Updating abc..def", stderr="")
        pop = MagicMock(returncode=0, stdout="")
        with patch("subprocess.run", side_effect=[status, stash, pull, pop]):
            result = do_update()
        assert result  # should have some non-empty result

    def test_do_update_exception(self):
        from luckyd_code.update import do_update
        with patch("subprocess.run", side_effect=Exception("git gone")):
            result = do_update()
        assert "Update failed" in result


# =============================================================================
# git/auto_commit.py  (currently 52%)
# =============================================================================

class TestAutoCommit:
    def test_collect_write(self):
        from luckyd_code.git.auto_commit import collect_modified_paths
        tcs = [{"id": "tc1", "function": {"name": "Write", "arguments": "{}"}}]
        args = {"tc1": {"file_path": "/some/file.py"}}
        assert "/some/file.py" in collect_modified_paths(tcs, args)

    def test_collect_edit(self):
        from luckyd_code.git.auto_commit import collect_modified_paths
        tcs = [{"id": "tc2", "function": {"name": "Edit", "arguments": "{}"}}]
        args = {"tc2": {"file_path": "/edit/me.py"}}
        assert "/edit/me.py" in collect_modified_paths(tcs, args)

    def test_collect_deduplicates(self):
        from luckyd_code.git.auto_commit import collect_modified_paths
        tcs = [
            {"id": "t1", "function": {"name": "Write", "arguments": "{}"}},
            {"id": "t2", "function": {"name": "Edit",  "arguments": "{}"}},
        ]
        args = {"t1": {"file_path": "same.py"}, "t2": {"file_path": "same.py"}}
        paths = collect_modified_paths(tcs, args)
        assert paths.count("same.py") == 1

    def test_collect_ignores_non_write(self):
        from luckyd_code.git.auto_commit import collect_modified_paths
        tcs = [{"id": "t1", "function": {"name": "Bash", "arguments": "{}"}}]
        assert collect_modified_paths(tcs, {"t1": {"command": "ls"}}) == []

    def test_auto_commit_disabled(self):
        from luckyd_code.git.auto_commit import auto_commit
        assert auto_commit("test", ["/a.py"], enabled=False) is None

    def test_auto_commit_no_paths(self):
        from luckyd_code.git.auto_commit import auto_commit
        assert auto_commit("test", []) is None

    def test_auto_commit_not_in_git(self):
        from luckyd_code.git.auto_commit import auto_commit
        with patch("luckyd_code.git.auto_commit._in_git_repo", return_value=False):
            assert auto_commit("test", ["/a.py"]) is None

    def test_auto_commit_stage_fails(self):
        from luckyd_code.git.auto_commit import auto_commit
        with patch("luckyd_code.git.auto_commit._in_git_repo", return_value=True):
            with patch("luckyd_code.git.auto_commit._stage_files", return_value=False):
                assert auto_commit("test", ["/a.py"]) is None

    def test_auto_commit_no_staged_changes(self):
        from luckyd_code.git.auto_commit import auto_commit
        with patch("luckyd_code.git.auto_commit._in_git_repo", return_value=True):
            with patch("luckyd_code.git.auto_commit._stage_files", return_value=True):
                with patch("luckyd_code.git.auto_commit._has_staged_changes", return_value=False):
                    assert auto_commit("test", ["/a.py"]) is None

    def test_auto_commit_success(self):
        from luckyd_code.git.auto_commit import auto_commit
        with patch("luckyd_code.git.auto_commit._in_git_repo", return_value=True):
            with patch("luckyd_code.git.auto_commit._stage_files", return_value=True):
                with patch("luckyd_code.git.auto_commit._has_staged_changes", return_value=True):
                    with patch("luckyd_code.git.auto_commit._commit", return_value="abc1234"):
                        assert auto_commit("add feature", ["/a.py"]) == "abc1234"

    def test_make_commit_message_basic(self):
        from luckyd_code.git.auto_commit import _make_commit_message
        msg = _make_commit_message("fix the broken auth flow")
        assert msg.startswith("agent:")
        assert "fix the broken auth flow" in msg

    def test_make_commit_message_truncates(self):
        from luckyd_code.git.auto_commit import _make_commit_message
        long = "x" * 200
        msg = _make_commit_message(long)
        # subject part should be <= 72 chars
        subject = msg[len("agent: "):]
        assert len(subject) <= 72

    def test_in_git_repo_false(self):
        from luckyd_code.git.auto_commit import _in_git_repo
        mock = MagicMock(); mock.returncode = 128
        with patch("subprocess.run", return_value=mock):
            assert _in_git_repo() is False

    def test_in_git_repo_exception(self):
        from luckyd_code.git.auto_commit import _in_git_repo
        with patch("subprocess.run", side_effect=Exception("no git")):
            assert _in_git_repo() is False

    def test_stage_files_empty(self):
        from luckyd_code.git.auto_commit import _stage_files
        assert _stage_files([]) is False

    def test_stage_files_failure(self):
        from luckyd_code.git.auto_commit import _stage_files
        mock = MagicMock(); mock.returncode = 1; mock.stderr = "error"
        with patch("subprocess.run", return_value=mock):
            assert _stage_files(["/a.py"]) is False

    def test_stage_files_exception(self):
        from luckyd_code.git.auto_commit import _stage_files
        with patch("subprocess.run", side_effect=Exception("fail")):
            assert _stage_files(["/a.py"]) is False

    def test_stage_files_success(self):
        from luckyd_code.git.auto_commit import _stage_files
        mock = MagicMock(); mock.returncode = 0
        with patch("subprocess.run", return_value=mock):
            assert _stage_files(["/a.py"]) is True

    def test_has_staged_true(self):
        from luckyd_code.git.auto_commit import _has_staged_changes
        mock = MagicMock(); mock.returncode = 1
        with patch("subprocess.run", return_value=mock):
            assert _has_staged_changes() is True

    def test_has_staged_false(self):
        from luckyd_code.git.auto_commit import _has_staged_changes
        mock = MagicMock(); mock.returncode = 0
        with patch("subprocess.run", return_value=mock):
            assert _has_staged_changes() is False

    def test_has_staged_exception(self):
        from luckyd_code.git.auto_commit import _has_staged_changes
        with patch("subprocess.run", side_effect=Exception("fail")):
            assert _has_staged_changes() is False

    def test_commit_success(self):
        from luckyd_code.git.auto_commit import _commit
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = "[main abc1234] agent: fix bug\n 1 file changed"
        with patch("subprocess.run", return_value=mock):
            sha = _commit("agent: fix bug")
        assert sha is not None

    def test_commit_failure(self):
        from luckyd_code.git.auto_commit import _commit
        mock = MagicMock(); mock.returncode = 1; mock.stderr = "nothing to commit"
        with patch("subprocess.run", return_value=mock):
            assert _commit("msg") is None

    def test_commit_exception(self):
        from luckyd_code.git.auto_commit import _commit
        with patch("subprocess.run", side_effect=Exception("fail")):
            assert _commit("msg") is None


# =============================================================================
# memory/user.py  (currently 42%)
# =============================================================================

class TestUserMemory:
    @pytest.fixture
    def mem(self, tmp_path):
        from luckyd_code.memory.user import UserMemory
        m = UserMemory()
        m._mem_dir = tmp_path / "memories"
        m._mem_dir.mkdir()
        return m

    def test_save_and_load(self, mem):
        mem.save("pref", "I prefer dark mode", importance=8)
        assert mem.load("pref") == "I prefer dark mode"

    def test_load_nonexistent(self, mem):
        assert mem.load("missing") is None

    def test_delete_existing(self, mem):
        mem.save("note", "some note")
        assert mem.delete("note") is True

    def test_delete_nonexistent(self, mem):
        assert mem.delete("ghost") is False

    def test_list_all(self, mem):
        mem.save("a", "alpha")
        mem.save("b", "beta")
        names = [i["name"] for i in mem.list_all()]
        assert "a" in names and "b" in names

    def test_list_all_empty(self, mem):
        assert mem.list_all() == []

    def test_keyword_search_finds_match(self, mem):
        mem.save("coding", "I love Python programming")
        results = mem._keyword_search("Python", k=5)
        assert len(results) > 0
        assert results[0]["name"] == "coding"

    def test_keyword_search_no_match(self, mem):
        mem.save("food", "I enjoy tacos")
        assert mem._keyword_search("Python", k=5) == []

    def test_get_relevant_empty(self, mem):
        assert mem.get_relevant("anything") == ""

    def test_get_relevant_returns_xml(self, mem):
        mem.save("hobby", "I play guitar")
        result = mem.get_relevant("guitar")
        assert "<user_memories>" in result

    def test_decay_archives_old_low_importance(self, mem):
        mem.save("old", "stale memory", importance=2)
        filepath = mem._mem_dir / "old.md"
        old_time = time.time() - (35 * 86400)
        filepath.write_text(
            f"<!-- importance:2 saved:{old_time:.0f} accessed:{old_time:.0f} count:0 -->\nstale memory",
            encoding="utf-8"
        )
        assert mem.decay() == 1

    def test_decay_keeps_high_importance(self, mem):
        mem.save("important", "critical info", importance=9)
        filepath = mem._mem_dir / "important.md"
        old_time = time.time() - (35 * 86400)
        filepath.write_text(
            f"<!-- importance:9 saved:{old_time:.0f} accessed:{old_time:.0f} count:0 -->\ncritical info",
            encoding="utf-8"
        )
        assert mem.decay() == 0

    def test_strip_meta(self):
        from luckyd_code.memory.user import UserMemory
        raw = "<!-- importance:5 saved:0 accessed:0 count:0 -->\nActual content"
        assert UserMemory._strip_meta(raw) == "Actual content"

    def test_strip_meta_no_meta(self):
        from luckyd_code.memory.user import UserMemory
        assert UserMemory._strip_meta("Plain content") == "Plain content"

    def test_read_meta_missing_file(self, tmp_path):
        from luckyd_code.memory.user import UserMemory
        meta = UserMemory._read_meta(tmp_path / "nonexistent.md")
        assert meta["importance"] == 5

    def test_sanitize(self):
        from luckyd_code.memory.user import _sanitize
        assert _sanitize("hello world!") == "hello_world"  # strip('_') removes trailing underscore
        assert _sanitize("") == "unnamed"

    def test_make_snippet_with_match(self):
        from luckyd_code.memory.user import _make_snippet
        content = "The quick brown fox jumps over the lazy dog"
        assert "fox" in _make_snippet(content, "fox")

    def test_make_snippet_no_match(self):
        from luckyd_code.memory.user import _make_snippet
        assert len(_make_snippet("The quick brown fox", "elephant")) > 0

    def test_get_user_memory_singleton(self):
        import luckyd_code.memory.user as user_mod
        user_mod._user_memory = None
        with patch.object(user_mod, "_get_user_mem_dir"):
            m1 = user_mod.get_user_memory()
            m2 = user_mod.get_user_memory()
        assert m1 is m2

    def test_search_falls_back_to_keyword(self, mem):
        mem.save("py", "Python is great")
        # Force semantic to fail
        with patch.object(mem, "_semantic_search", side_effect=ImportError("no st")):
            results = mem.search("Python", k=3)
        assert len(results) > 0


# =============================================================================
# brain/retriever.py — unit-testable paths
# =============================================================================

class TestRetrieverRRF:
    @pytest.fixture
    def retriever(self):
        from luckyd_code.brain.retriever import Retriever
        r = Retriever()
        mock_idx = MagicMock()
        mock_idx.is_available = False
        mock_idx.chunks = []
        mock_idx.stats = {}
        r._indexer = mock_idx
        mock_graph = MagicMock()
        mock_graph.nodes = {}
        mock_graph.stats = {}
        r._graph = mock_graph
        return r

    def test_rrf_merge_both_lists(self, retriever):
        vec  = [{"chunk_id": "a", "score": 0.9}, {"chunk_id": "b", "score": 0.7}]
        bm25 = [{"chunk_id": "b", "score": 5.0}, {"chunk_id": "c", "score": 3.0}]
        merged = retriever._rrf_merge(vec, bm25, k=3)
        ids = [r["chunk_id"] for r in merged]
        assert "b" in ids  # appears in both, should rank high
        assert len(merged) <= 3

    def test_rrf_merge_single_list(self, retriever):
        vec = [{"chunk_id": "x", "score": 0.5}]
        merged = retriever._rrf_merge(vec, [], k=5)
        assert len(merged) == 1
        assert merged[0]["chunk_id"] == "x"

    def test_rrf_merge_respects_k(self, retriever):
        vec  = [{"chunk_id": str(i), "score": 0.1} for i in range(10)]
        bm25 = [{"chunk_id": str(i), "score": 1.0} for i in range(10)]
        assert len(retriever._rrf_merge(vec, bm25, k=3)) <= 3

    def test_stats_returns_dict(self, retriever):
        retriever._indexer.stats = {"chunks": 5, "files": 2, "languages": {"python": 5}}
        result = retriever.stats()
        assert "vector" in result and "graph" in result

    def test_search_returns_empty_when_nothing(self, retriever):
        with patch.object(retriever, "_bm25_search", return_value=[]):
            with patch.object(retriever, "_fallback_search", return_value=[]):
                assert retriever.search("anything") == []

    def test_search_uses_bm25_fallback(self, retriever):
        bm25_result = [{"chunk_id": "z", "file_path": "f.py", "score": 2.0}]
        with patch.object(retriever, "_bm25_search", return_value=bm25_result):
            results = retriever.search("something")
        assert results == bm25_result


# =============================================================================
# tools/git_worktree.py  (currently 27%)
# =============================================================================

class TestGitWorktreeTool:
    @pytest.fixture
    def tool(self):
        from luckyd_code.tools.git_worktree import GitWorktreeTool
        return GitWorktreeTool()

    def test_list_action(self, tool):
        mock = MagicMock(); mock.stdout = "/path/to/worktree  abc [main]"; mock.stderr = ""
        with patch("subprocess.run", return_value=mock):
            assert "worktree" in tool.run(action="list")

    def test_create_no_path(self, tool):
        assert "Error" in tool.run(action="create")

    def test_create_with_path(self, tool):
        mock = MagicMock(); mock.stdout = "Preparing worktree"; mock.stderr = ""
        with patch("subprocess.run", return_value=mock):
            assert tool.run(action="create", path="/tmp/wt")

    def test_create_with_branch(self, tool):
        mock = MagicMock(); mock.stdout = "Preparing"; mock.stderr = ""
        with patch("subprocess.run", return_value=mock) as m:
            tool.run(action="create", path="/tmp/wt", branch="feature/x")
        assert "-b" in m.call_args[0][0]

    def test_remove_no_path(self, tool):
        assert "Error" in tool.run(action="remove")

    def test_remove_with_path(self, tool):
        mock = MagicMock(); mock.stdout = ""; mock.stderr = "Removed"
        with patch("subprocess.run", return_value=mock):
            assert tool.run(action="remove", path="/tmp/wt") is not None

    def test_unknown_action(self, tool):
        assert "Unknown action" in tool.run(action="explode")

    def test_timeout_error(self, tool):
        import subprocess
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 30)):
            assert "timed out" in tool.run(action="list")

    def test_generic_exception(self, tool):
        with patch("subprocess.run", side_effect=Exception("no git")):
            assert "Error" in tool.run(action="list")


# =============================================================================
# tools/game_gen.py  (currently 27%)
# =============================================================================

class TestGameGenTool:
    @pytest.fixture
    def tool(self):
        from luckyd_code.tools.game_gen import GameGenTool
        return GameGenTool()

    def test_invalid_difficulty(self, tool):
        assert "Error" in tool.run(description="a game", difficulty="impossible")

    def test_invalid_output_format(self, tool):
        assert "Error" in tool.run(description="a game", output_format="zip")

    def test_model_exception(self, tool, tmp_path):
        with patch.object(tool, "_generate_source", side_effect=Exception("API down")):
            assert "Error" in tool.run(description="a game", output_dir=str(tmp_path))

    def test_generates_py_file(self, tool, tmp_path):
        src = 'import pygame\ndef main(): pass\nif __name__ == "__main__": main()'
        with patch.object(tool, "_generate_source", return_value=src):
            result = tool.run(description="simple game", output_format="py", output_dir=str(tmp_path))
        assert "Game generated" in result
        assert any(f.suffix == ".py" for f in tmp_path.iterdir())

    def test_strips_markdown_fences(self, tool, tmp_path):
        fenced = "```python\nimport pygame\n```"
        with patch.object(tool, "_generate_source", return_value=fenced):
            assert "Game generated" in tool.run(description="game", output_format="py", output_dir=str(tmp_path))

    def test_theme_color_substituted(self, tool, tmp_path):
        with patch.object(tool, "_generate_source", return_value="THEME_COLOR = '#THEME_COLOR#'"):
            tool.run(description="game", theme_color="#FF0000", output_format="py", output_dir=str(tmp_path))
        content = next(tmp_path.glob("*.py")).read_text()
        assert "#FF0000" in content and "#THEME_COLOR#" not in content

    def test_diff_mult_substituted(self, tool, tmp_path):
        with patch.object(tool, "_generate_source", return_value="DIFF_MULT = #DIFF_MULT#"):
            tool.run(description="game", difficulty="hard", output_format="py", output_dir=str(tmp_path))
        content = next(tmp_path.glob("*.py")).read_text()
        assert "1.4" in content

    def test_exe_format_compile_fail(self, tool, tmp_path):
        with patch.object(tool, "_generate_source", return_value="import pygame"):
            with patch("luckyd_code.tools.game_gen.compile_exe", return_value=(False, "no pyinstaller")):
                assert "Compilation failed" in tool.run(description="game", output_format="exe", output_dir=str(tmp_path))

    def test_exe_format_compile_success(self, tool, tmp_path):
        with patch.object(tool, "_generate_source", return_value="import pygame"):
            with patch("luckyd_code.tools.game_gen.compile_exe", return_value=(True, str(tmp_path / "Game.exe"))):
                assert "Standalone" in tool.run(description="game", output_format="exe", output_dir=str(tmp_path))

    def test_resolve_pyinstaller_not_found(self):
        from luckyd_code.tools.game_gen import _resolve_pyinstaller
        with patch("shutil.which", return_value=None):
            with patch("subprocess.run", side_effect=Exception("not found")):
                assert _resolve_pyinstaller() is None

    def test_resolve_pyinstaller_on_path(self):
        from luckyd_code.tools.game_gen import _resolve_pyinstaller
        with patch("shutil.which", return_value="/usr/bin/pyinstaller"):
            assert _resolve_pyinstaller() == "found"

    def test_generate_source_fallback_on_api_error(self, tool):
        with patch.object(tool, "_generate_source_api", side_effect=Exception("down")):
            with patch.object(tool, "_generate_source_fallback", return_value="import pygame"):
                assert "pygame" in tool._generate_source("a game", "normal")


# =============================================================================
# tools/project_gen.py  (currently 23%)
# =============================================================================

class TestProjectGenTool:
    @pytest.fixture
    def tool(self):
        from luckyd_code.tools.project_gen import ProjectGenTool
        return ProjectGenTool()

    def test_model_json_error(self, tool, tmp_path):
        with patch.object(tool, "_call_model", side_effect=json.JSONDecodeError("bad", "", 0)):
            result = tool.run(description="a project", output_dir=str(tmp_path))
        assert "Error" in result and "JSON" in result

    def test_model_exception(self, tool, tmp_path):
        with patch.object(tool, "_call_model", side_effect=Exception("network")):
            assert "Error" in tool.run(description="a project", output_dir=str(tmp_path))

    def test_model_no_files(self, tool, tmp_path):
        with patch.object(tool, "_call_model", return_value={"project_name": "p", "files": []}):
            assert "Error" in tool.run(description="a project", output_dir=str(tmp_path))

    def test_generates_files(self, tool, tmp_path):
        scaffold = {
            "project_name": "my-app", "stack": "Python",
            "files": [
                {"path": "main.py", "content": "print('hello')"},
                {"path": "README.md", "content": "# My App"},
            ],
            "install": "pip install -r requirements.txt",
            "run": "python main.py", "notes": "",
        }
        with patch.object(tool, "_call_model", return_value=scaffold):
            result = tool.run(description="hello world app", output_dir=str(tmp_path))
        assert "my-app" in result
        assert (tmp_path / "my-app" / "main.py").exists()

    def test_output_includes_notes(self, tool, tmp_path):
        scaffold = {
            "project_name": "noted-app", "stack": "Python",
            "files": [{"path": "main.py", "content": "x=1"}],
            "install": "pip install .", "run": "python main.py",
            "notes": "Don't forget to set API_KEY",
        }
        with patch.object(tool, "_call_model", return_value=scaffold):
            assert "Don't forget" in tool.run(description="noted app", output_dir=str(tmp_path))

    def test_call_model_strips_fences(self, tool):
        raw = '```json\n{"project_name": "x", "files": []}\n```'
        with patch.object(tool, "_call_model_direct", return_value=raw):
            result = tool._call_model("any")
        assert result["project_name"] == "x"

    def test_file_with_no_path_skipped(self, tool, tmp_path):
        scaffold = {
            "project_name": "skip-test", "stack": "Python",
            "files": [{"path": "", "content": "x=1"}, {"path": "main.py", "content": "x=1"}],
            "install": "", "run": "", "notes": "",
        }
        with patch.object(tool, "_call_model", return_value=scaffold):
            result = tool.run(description="test", output_dir=str(tmp_path))
        assert "skip-test" in result


# =============================================================================
# tools/readme_gen.py  (currently 22%)
# =============================================================================

class TestReadmeGenTool:
    @pytest.fixture
    def tool(self):
        from luckyd_code.tools.readme_gen import ReadmeGenTool
        return ReadmeGenTool()

    def test_nonexistent_directory(self, tool, tmp_path):
        assert "Error" in tool.run(project_dir=str(tmp_path / "missing"))

    def test_readme_exists_no_overwrite(self, tool, tmp_path):
        (tmp_path / "README.md").write_text("# Existing")
        (tmp_path / "main.py").write_text("x=1")
        assert "already exists" in tool.run(project_dir=str(tmp_path), overwrite=False)

    def test_no_source_files(self, tool, tmp_path):
        assert "Error" in tool.run(project_dir=str(tmp_path))

    def test_model_exception(self, tool, tmp_path):
        (tmp_path / "main.py").write_text("print('hi')")
        with patch.object(tool, "_call_model", side_effect=Exception("down")):
            assert "Error" in tool.run(project_dir=str(tmp_path))

    def test_generates_readme(self, tool, tmp_path):
        (tmp_path / "main.py").write_text("from fastapi import FastAPI")
        with patch.object(tool, "_call_model", return_value="# My Project\n\nGreat."):
            result = tool.run(project_dir=str(tmp_path))
        assert "generated" in result.lower()
        assert (tmp_path / "README.md").exists()

    def test_strips_markdown_wrapper(self, tool, tmp_path):
        (tmp_path / "main.py").write_text("x=1")
        with patch.object(tool, "_call_model", return_value="```markdown\n# Title\n\nContent\n```"):
            tool.run(project_dir=str(tmp_path))
        assert (tmp_path / "README.md").read_text().startswith("# Title")

    def test_overwrite_existing(self, tool, tmp_path):
        (tmp_path / "README.md").write_text("# Old")
        (tmp_path / "main.py").write_text("x=1")
        with patch.object(tool, "_call_model", return_value="# New README"):
            result = tool.run(project_dir=str(tmp_path), overwrite=True)
        assert "generated" in result.lower()
        assert (tmp_path / "README.md").read_text() == "# New README"

    def test_custom_output_path(self, tool, tmp_path):
        (tmp_path / "app.py").write_text("x=1")
        out = tmp_path / "DOCS.md"
        with patch.object(tool, "_call_model", return_value="# Docs"):
            tool.run(project_dir=str(tmp_path), output_path=str(out))
        assert out.exists()

    def test_collect_files_priority(self, tmp_path):
        from luckyd_code.tools.readme_gen import _collect_files
        (tmp_path / "main.py").write_text("import fastapi")
        files = _collect_files(tmp_path)
        names = [r for r, _ in files]
        assert any("main.py" in n for n in names)

    def test_collect_files_skips_binary(self, tmp_path):
        from luckyd_code.tools.readme_gen import _collect_files
        (tmp_path / "image.png").write_bytes(b"\x89PNG")
        (tmp_path / "app.py").write_text("x=1")
        names = [r for r, _ in _collect_files(tmp_path)]
        assert not any("image.png" in n for n in names)

    def test_write_error_returns_error(self, tool, tmp_path):
        (tmp_path / "main.py").write_text("x=1")
        with patch.object(tool, "_call_model", return_value="# README"):
            with patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
                result = tool.run(project_dir=str(tmp_path))
        assert "Error" in result


# =============================================================================
# tools/brain_tools.py  (currently 26%)
# =============================================================================

class TestBrainTools:
    def test_brain_search_empty_index(self):
        from luckyd_code.tools.brain_tools import BrainSearchTool
        tool = BrainSearchTool()
        mock_r = MagicMock(); mock_r.search.return_value = []
        mock_g = MagicMock(); mock_g.nodes = {}
        with patch("luckyd_code.tools.brain_tools._get_retriever", return_value=mock_r):
            with patch("luckyd_code.tools.brain_tools._get_graph", return_value=mock_g):
                result = tool.run(query="authentication")
        assert "rebuild" in result.lower() or "No results" in result

    def test_brain_search_with_results(self):
        from luckyd_code.tools.brain_tools import BrainSearchTool
        tool = BrainSearchTool()
        mock_r = MagicMock()
        mock_r.search.return_value = [
            {"file_path": "auth.py", "start_line": 10, "end_line": 25,
             "score": 0.92, "name": "login", "type": "function", "language": "python"}
        ]
        with patch("luckyd_code.tools.brain_tools._get_retriever", return_value=mock_r):
            result = tool.run(query="login function")
        assert "auth.py" in result and "login" in result

    def test_brain_search_with_file_filter(self):
        from luckyd_code.tools.brain_tools import BrainSearchTool
        tool = BrainSearchTool()
        mock_r = MagicMock(); mock_r.search.return_value = []
        mock_g = MagicMock(); mock_g.nodes = {"x": {}}
        with patch("luckyd_code.tools.brain_tools._get_retriever", return_value=mock_r):
            with patch("luckyd_code.tools.brain_tools._get_graph", return_value=mock_g):
                result = tool.run(query="login", file_filter="auth.py")
        assert isinstance(result, str)

    def test_brain_status_not_available(self):
        from luckyd_code.tools.brain_tools import BrainStatusTool
        tool = BrainStatusTool()
        mock_r = MagicMock()
        mock_r.stats.return_value = {
            "vector": {"available": False, "chunks": 0, "files": 0, "languages": {}, "last_indexed": 0},
            "graph": {"nodes": 0, "edges": 0, "files_parsed": 0},
        }
        with patch("luckyd_code.tools.brain_tools._get_retriever", return_value=mock_r):
            result = tool.run()
        assert "Vector Index" in result and "Not available" in result

    def test_brain_status_available(self):
        from luckyd_code.tools.brain_tools import BrainStatusTool
        tool = BrainStatusTool()
        mock_r = MagicMock()
        mock_r.stats.return_value = {
            "vector": {
                "available": True, "chunks": 120, "files": 10,
                "languages": {"python": 10}, "last_indexed": 1700000000,
            },
            "graph": {"nodes": 50, "edges": 20, "files_parsed": 10},
        }
        with patch("luckyd_code.tools.brain_tools._get_retriever", return_value=mock_r):
            assert "120" in tool.run()

    def test_brain_status_with_stale(self):
        from luckyd_code.tools.brain_tools import BrainStatusTool
        tool = BrainStatusTool()
        mock_r = MagicMock()
        mock_r.stats.return_value = {
            "vector": {
                "available": True, "chunks": 5, "files": 1,
                "languages": {}, "last_indexed": 1700000000,
            },
            "stale_files": 3,
            "graph": {"nodes": 0, "edges": 0, "files_parsed": 0},
        }
        with patch("luckyd_code.tools.brain_tools._get_retriever", return_value=mock_r):
            result = tool.run()
        assert "5" in result


# =============================================================================
# web_routes/brain.py + background.py  (18% / 27%)
# =============================================================================

if sys.version_info < (3, 15):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from luckyd_code.web_routes.brain import router as brain_router
    from luckyd_code.web_routes.background import router as bg_router

    def _brain_client():
        app = FastAPI()
        app.include_router(brain_router)
        state = MagicMock(); state.knowledge_graph = None
        app.state.web_state = state
        return TestClient(app)

    def _bg_client():
        app = FastAPI()
        app.include_router(bg_router)
        state = MagicMock(); state.config = MagicMock()
        app.state.web_state = state
        return TestClient(app)

    class TestBrainRoutes:
        # Names are bound at import time in web_routes.brain (module-level imports),
        # so we patch there — not in the source luckyd_code.brain module.
        def test_brain_status_empty(self):
            c = _brain_client()
            mock_kg = MagicMock(); mock_kg.nodes = {}; mock_kg.stats = {}
            mock_idx = MagicMock(); mock_idx.load.return_value = False
            with patch("luckyd_code.web_routes.brain.KnowledgeGraph", return_value=mock_kg):
                with patch("luckyd_code.web_routes.brain.VectorIndexer", return_value=mock_idx):
                    resp = c.get("/api/brain")
            assert resp.status_code == 200
            assert resp.json()["status"] == "empty"

        def test_brain_status_with_data(self):
            c = _brain_client()
            mock_kg = MagicMock()
            mock_kg.nodes = {"sym": {}}
            mock_kg.stats = {"node_count": 5, "edge_count": 3, "files_parsed": 2, "last_built": 1700000000}
            mock_idx = MagicMock(); mock_idx.load.return_value = False
            with patch("luckyd_code.web_routes.brain.KnowledgeGraph", return_value=mock_kg):
                with patch("luckyd_code.web_routes.brain.VectorIndexer", return_value=mock_idx):
                    resp = c.get("/api/brain")
            assert resp.status_code == 200
            assert resp.json()["symbols"] == 5

        def test_brain_status_with_rag(self):
            c = _brain_client()
            mock_kg = MagicMock(); mock_kg.nodes = {"x": {}}; mock_kg.stats = {"node_count": 1, "edge_count": 0, "files_parsed": 1}
            mock_idx = MagicMock(); mock_idx.load.return_value = True
            mock_r = MagicMock(); mock_r.stats.return_value = {"vector": {"chunks": 10, "files": 2}}
            with patch("luckyd_code.web_routes.brain.KnowledgeGraph", return_value=mock_kg):
                with patch("luckyd_code.web_routes.brain.VectorIndexer", return_value=mock_idx):
                    with patch("luckyd_code.web_routes.brain.Retriever", return_value=mock_r):
                        resp = c.get("/api/brain")
            assert resp.status_code == 200
            assert "rag_chunks" in resp.json()

        def test_brain_search_no_query(self):
            c = _brain_client()
            assert c.get("/api/brain/search").json()["results"] == []

        def test_brain_search_with_query(self):
            c = _brain_client()
            mock_r = MagicMock()
            mock_r.search.return_value = [{"content": "def login():", "file": "auth.py", "score": 0.9}]
            with patch("luckyd_code.web_routes.brain.Retriever", return_value=mock_r):
                resp = c.get("/api/brain/search?q=login&max_results=3")
            assert resp.status_code == 200
            assert len(resp.json()["results"]) == 1

        def test_brain_search_exception(self):
            c = _brain_client()
            with patch("luckyd_code.web_routes.brain.Retriever", side_effect=Exception("boom")):
                assert c.get("/api/brain/search?q=login").status_code == 500

        def test_brain_stats(self):
            c = _brain_client()
            mock_r = MagicMock(); mock_r.stats.return_value = {"vector": {}, "graph": {}}
            with patch("luckyd_code.web_routes.brain.Retriever", return_value=mock_r):
                assert c.get("/api/brain/stats").status_code == 200

        def test_brain_stats_exception(self):
            c = _brain_client()
            with patch("luckyd_code.web_routes.brain.Retriever", side_effect=Exception("fail")):
                assert c.get("/api/brain/stats").status_code == 500

        def test_brain_dependents_no_symbol(self):
            c = _brain_client()
            assert c.get("/api/brain/dependents").status_code == 400

        def test_brain_dependents_with_symbol(self):
            c = _brain_client()
            mock_kg = MagicMock(); mock_kg.find_dependents.return_value = ["mod_a", "mod_b"]
            with patch("luckyd_code.web_routes.brain.KnowledgeGraph", return_value=mock_kg):
                resp = c.get("/api/brain/dependents?symbol=MyClass")
            assert resp.status_code == 200
            assert resp.json()["count"] == 2

        def test_brain_dependents_exception(self):
            c = _brain_client()
            with patch("luckyd_code.web_routes.brain.KnowledgeGraph", side_effect=Exception("fail")):
                assert c.get("/api/brain/dependents?symbol=X").status_code == 500

        def test_brain_rebuild(self):
            c = _brain_client()
            mock_result = {"chunks": 50, "files": 5, "node_count": 20, "files_parsed": 5}
            with patch("luckyd_code.web_routes.brain.rebuild_project", return_value=mock_result):
                resp = c.post("/api/brain/rebuild")
            assert resp.status_code == 200
            assert resp.json()["chunks"] == 50

    class TestBackgroundRoutes:
        # Routes use lazy imports (from ..background import BackgroundAgent) inside
        # function bodies, so we patch the source module.
        def test_background_list(self):
            c = _bg_client()
            mock_bg = MagicMock(); mock_bg.get_status.return_value = [{"id": "t1", "status": "running"}]
            with patch("luckyd_code.background.BackgroundAgent", return_value=mock_bg):
                resp = c.get("/api/background")
            assert resp.status_code == 200
            assert "tasks" in resp.json()

        def test_background_list_exception(self):
            c = _bg_client()
            with patch("luckyd_code.background.BackgroundAgent", side_effect=Exception("fail")):
                assert c.get("/api/background").status_code == 500

        def test_background_start_no_task(self):
            c = _bg_client()
            mock_bg = MagicMock()
            with patch("luckyd_code.background.BackgroundAgent", return_value=mock_bg):
                assert c.post("/api/background/start", json={"task": ""}).status_code == 400

        def test_background_start_success(self):
            c = _bg_client()
            mock_bg = MagicMock(); mock_bg.start_task.return_value = "task-abc"
            with patch("luckyd_code.background.BackgroundAgent", return_value=mock_bg):
                resp = c.post("/api/background/start", json={"task": "do something"})
            assert resp.status_code == 200
            assert resp.json()["task_id"] == "task-abc"

        def test_background_start_exception(self):
            c = _bg_client()
            with patch("luckyd_code.background.BackgroundAgent", side_effect=Exception("fail")):
                assert c.post("/api/background/start", json={"task": "do something"}).status_code == 500

        def test_background_status_found(self):
            c = _bg_client()
            mock_bg = MagicMock(); mock_bg.get_status.return_value = [{"id": "t1", "status": "done"}]
            with patch("luckyd_code.background.BackgroundAgent", return_value=mock_bg):
                resp = c.get("/api/background/status/t1")
            assert resp.status_code == 200
            assert resp.json()["task"]["status"] == "done"

        def test_background_status_not_found(self):
            c = _bg_client()
            mock_bg = MagicMock(); mock_bg.get_status.return_value = []
            with patch("luckyd_code.background.BackgroundAgent", return_value=mock_bg):
                assert c.get("/api/background/status/missing").status_code == 404

        def test_background_result_found(self):
            c = _bg_client()
            mock_bg = MagicMock(); mock_bg.get_result.return_value = "task output"
            with patch("luckyd_code.background.BackgroundAgent", return_value=mock_bg):
                resp = c.get("/api/background/result/t1")
            assert resp.status_code == 200
            assert resp.json()["result"] == "task output"

        def test_background_result_not_found(self):
            c = _bg_client()
            mock_bg = MagicMock(); mock_bg.get_result.return_value = None
            with patch("luckyd_code.background.BackgroundAgent", return_value=mock_bg):
                assert c.get("/api/background/result/missing").status_code == 404

        def test_background_result_exception(self):
            c = _bg_client()
            with patch("luckyd_code.background.BackgroundAgent", side_effect=Exception("fail")):
                assert c.get("/api/background/result/t1").status_code == 500
