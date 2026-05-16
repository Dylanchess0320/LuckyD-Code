"""Tests for backup.py — git-based snapshot system."""

from __future__ import annotations

from unittest.mock import patch, call
import pytest

from luckyd_code.backup import (
    BACKUP_TAG_PREFIX,
    _git,
    _is_git_repo,
    _has_changes,
    _current_branch,
    _short_hash,
    create_backup,
    list_backups,
    restore_backup,
    format_backup_list,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_prefix_is_luckyd(self):
        assert BACKUP_TAG_PREFIX == "luckyd-backup/"

    def test_prefix_not_dsc(self):
        assert "dsc" not in BACKUP_TAG_PREFIX


# ---------------------------------------------------------------------------
# _git helper
# ---------------------------------------------------------------------------

class TestGitHelper:
    def test_returns_tuple(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "main\n"
            mock_run.return_value.stderr = ""
            code, out, err = _git("rev-parse", "--abbrev-ref", "HEAD")
        assert code == 0
        assert out == "main"
        assert err == ""

    def test_git_not_found_returns_error(self):
        with patch("subprocess.run", side_effect=FileNotFoundError("no git")):
            code, out, err = _git("status")
        assert code == 1
        assert "git not found" in err

    def test_exception_returns_error(self):
        with patch("subprocess.run", side_effect=OSError("permission denied")):
            code, out, err = _git("status")
        assert code == 1
        assert "permission denied" in err

    def test_passes_cwd(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = ""
            mock_run.return_value.stderr = ""
            _git("status", cwd="/tmp")
        assert mock_run.call_args.kwargs["cwd"] == "/tmp"


# ---------------------------------------------------------------------------
# _is_git_repo
# ---------------------------------------------------------------------------

class TestIsGitRepo:
    def test_true_when_git_succeeds(self):
        with patch("luckyd_code.backup._git", return_value=(0, "true", "")):
            assert _is_git_repo() is True

    def test_false_when_git_fails(self):
        with patch("luckyd_code.backup._git", return_value=(128, "", "not a repo")):
            assert _is_git_repo() is False


# ---------------------------------------------------------------------------
# _has_changes
# ---------------------------------------------------------------------------

class TestHasChanges:
    def test_true_when_porcelain_has_output(self):
        with patch("luckyd_code.backup._git", return_value=(0, " M luckyd_code/foo.py", "")):
            assert _has_changes() is True

    def test_false_when_porcelain_is_empty(self):
        with patch("luckyd_code.backup._git", return_value=(0, "", "")):
            assert _has_changes() is False

    def test_false_when_porcelain_is_whitespace(self):
        with patch("luckyd_code.backup._git", return_value=(0, "   ", "")):
            assert _has_changes() is False


# ---------------------------------------------------------------------------
# _current_branch / _short_hash
# ---------------------------------------------------------------------------

class TestCurrentBranchAndHash:
    def test_current_branch_returns_name(self):
        with patch("luckyd_code.backup._git", return_value=(0, "feature/my-branch", "")):
            assert _current_branch() == "feature/my-branch"

    def test_current_branch_fallback(self):
        with patch("luckyd_code.backup._git", return_value=(128, "", "error")):
            assert _current_branch() == "unknown"

    def test_short_hash_returns_hash(self):
        with patch("luckyd_code.backup._git", return_value=(0, "abc1234", "")):
            assert _short_hash() == "abc1234"

    def test_short_hash_fallback(self):
        with patch("luckyd_code.backup._git", return_value=(1, "", "error")):
            assert _short_hash() == "unknown"


# ---------------------------------------------------------------------------
# create_backup
# ---------------------------------------------------------------------------

class TestCreateBackup:
    def _mock_git(self, responses: dict):
        """Build a side_effect that returns different responses per git subcommand."""
        def _side_effect(*args, cwd=None):
            key = args[0] if args else ""
            # Match on first argument (the git subcommand)
            return responses.get(key, (0, "", ""))
        return _side_effect

    def test_not_a_git_repo(self):
        with patch("luckyd_code.backup._is_git_repo", return_value=False):
            result = create_backup()
        assert result["ok"] is False
        assert "git repository" in result["error"]

    def test_nothing_to_commit(self):
        with patch("luckyd_code.backup._is_git_repo", return_value=True), \
             patch("luckyd_code.backup._has_changes", return_value=False), \
             patch("luckyd_code.backup._short_hash", return_value="abc1234"):
            result = create_backup()
        assert result["ok"] is True
        assert "abc1234" in result["message"]
        assert "clean" in result["message"]

    def test_successful_backup_with_tag(self):
        git_responses = {
            "add":    (0, "", ""),
            "commit": (0, "", ""),
            "tag":    (0, "", ""),
        }
        with patch("luckyd_code.backup._is_git_repo", return_value=True), \
             patch("luckyd_code.backup._has_changes", return_value=True), \
             patch("luckyd_code.backup._short_hash", return_value="def5678"), \
             patch("luckyd_code.backup._git", side_effect=self._mock_git(git_responses)):
            result = create_backup(message="before refactor")
        assert result["ok"] is True
        assert "def5678" in result["message"]
        assert result["tag"].startswith("luckyd-backup/")

    def test_git_add_failure(self):
        git_responses = {"add": (1, "", "permission denied")}
        with patch("luckyd_code.backup._is_git_repo", return_value=True), \
             patch("luckyd_code.backup._has_changes", return_value=True), \
             patch("luckyd_code.backup._git", side_effect=self._mock_git(git_responses)):
            result = create_backup()
        assert result["ok"] is False
        assert "git add failed" in result["error"]

    def test_git_commit_failure(self):
        git_responses = {
            "add":    (0, "", ""),
            "commit": (1, "", "nothing to commit"),
        }
        with patch("luckyd_code.backup._is_git_repo", return_value=True), \
             patch("luckyd_code.backup._has_changes", return_value=True), \
             patch("luckyd_code.backup._git", side_effect=self._mock_git(git_responses)):
            result = create_backup()
        assert result["ok"] is False
        assert "git commit failed" in result["error"]

    def test_uses_default_label_when_no_message(self):
        calls = []
        def _fake_git(*args, cwd=None):
            calls.append(args)
            if args[0] == "commit":
                assert "pre-operation snapshot" in args[2]
            return (0, "abc", "")
        with patch("luckyd_code.backup._is_git_repo", return_value=True), \
             patch("luckyd_code.backup._has_changes", return_value=True), \
             patch("luckyd_code.backup._short_hash", return_value="abc"), \
             patch("luckyd_code.backup._git", side_effect=_fake_git):
            create_backup()  # no message


# ---------------------------------------------------------------------------
# list_backups
# ---------------------------------------------------------------------------

class TestListBackups:
    def test_returns_entries_from_tags(self):
        tag_output = (
            "luckyd-backup/20260101_120000|abc1234|2026-01-01\n"
            "luckyd-backup/20260101_110000|def5678|2026-01-01\n"
        )
        with patch("luckyd_code.backup._git", return_value=(0, tag_output.strip(), "")):
            entries = list_backups()
        assert len(entries) == 2
        assert entries[0]["n"] == 1
        assert entries[0]["hash"] == "abc1234"
        assert entries[0]["tag"].startswith("luckyd-backup/")

    def test_falls_back_to_commit_log(self):
        # First call (tag list) returns nothing; second call (log) has commits
        log_output = "abc1234|2026-01-01|[dsc-backup] snapshot (2026-01-01 12:00:00)"
        responses = [
            (0, "", ""),          # tag list returns empty
            (0, log_output, ""),  # log grep returns result
        ]
        with patch("luckyd_code.backup._git", side_effect=responses):
            entries = list_backups()
        assert len(entries) == 1
        assert entries[0]["hash"] == "abc1234"

    def test_returns_empty_when_no_backups(self):
        with patch("luckyd_code.backup._git", return_value=(0, "", "")):
            entries = list_backups()
        assert entries == []

    def test_respects_limit(self):
        lines = "\n".join(
            f"luckyd-backup/2026010{i}_120000|hash{i}|2026-01-0{i}"
            for i in range(1, 8)
        )
        with patch("luckyd_code.backup._git", return_value=(0, lines, "")):
            entries = list_backups(limit=3)
        assert len(entries) == 3

    def test_handles_two_part_lines(self):
        tag_output = "luckyd-backup/20260101_120000|abc1234"
        with patch("luckyd_code.backup._git", return_value=(0, tag_output, "")):
            entries = list_backups()
        assert len(entries) == 1
        assert entries[0]["date"] == ""


# ---------------------------------------------------------------------------
# restore_backup
# ---------------------------------------------------------------------------

class TestRestoreBackup:
    def test_not_a_git_repo(self):
        with patch("luckyd_code.backup._is_git_repo", return_value=False):
            result = restore_backup("luckyd-backup/20260101_120000")
        assert result["ok"] is False
        assert "No git repository" in result["error"]

    def test_resolves_numeric_ref(self):
        backups = [
            {"n": 1, "tag": "luckyd-backup/20260101_120000", "hash": "abc1234",
             "date": "2026-01-01", "subject": "snapshot"},
        ]
        checkout_calls = []
        def _fake_git(*args, cwd=None):
            if args[0] == "checkout":
                checkout_calls.append(args)
            return (0, "", "")
        with patch("luckyd_code.backup._is_git_repo", return_value=True), \
             patch("luckyd_code.backup._has_changes", return_value=False), \
             patch("luckyd_code.backup.list_backups", return_value=backups), \
             patch("luckyd_code.backup._git", side_effect=_fake_git):
            result = restore_backup("1")
        assert result["ok"] is True
        assert any("luckyd-backup/20260101_120000" in str(c) for c in checkout_calls)

    def test_numeric_ref_not_found(self):
        with patch("luckyd_code.backup._is_git_repo", return_value=True), \
             patch("luckyd_code.backup.list_backups", return_value=[]):
            result = restore_backup("99")
        assert result["ok"] is False
        assert "#99" in result["error"]

    def test_successful_restore_no_dirty_state(self):
        with patch("luckyd_code.backup._is_git_repo", return_value=True), \
             patch("luckyd_code.backup._has_changes", return_value=False), \
             patch("luckyd_code.backup._git", return_value=(0, "", "")):
            result = restore_backup("luckyd-backup/20260101_120000")
        assert result["ok"] is True
        assert "luckyd-backup/20260101_120000" in result["message"]

    def test_stashes_dirty_state_before_restore(self):
        stash_calls = []
        def _fake_git(*args, cwd=None):
            if args[0] == "stash":
                stash_calls.append(args)
            return (0, "", "")
        with patch("luckyd_code.backup._is_git_repo", return_value=True), \
             patch("luckyd_code.backup._has_changes", return_value=True), \
             patch("luckyd_code.backup._git", side_effect=_fake_git):
            result = restore_backup("luckyd-backup/20260101_120000")
        assert result["ok"] is True
        assert any(c[1] == "push" for c in stash_calls)
        assert "stashed" in result["message"]

    def test_checkout_failure_recovers_stash(self):
        call_log = []
        def _fake_git(*args, cwd=None):
            call_log.extend(args)
            if args[0] == "checkout":
                return (1, "", "pathspec did not match")
            return (0, "", "")
        with patch("luckyd_code.backup._is_git_repo", return_value=True), \
             patch("luckyd_code.backup._has_changes", return_value=True), \
             patch("luckyd_code.backup._git", side_effect=_fake_git):
            result = restore_backup("luckyd-backup/20260101_120000")
        assert result["ok"] is False
        assert "pop" in call_log


# ---------------------------------------------------------------------------
# format_backup_list
# ---------------------------------------------------------------------------

class TestFormatBackupList:
    def test_empty_list(self):
        out = format_backup_list([])
        assert "No backups" in out

    def test_single_entry(self):
        backups = [
            {"n": 1, "tag": "luckyd-backup/20260101_120000", "hash": "abc1234",
             "date": "2026-01-01", "subject": "pre-operation snapshot"},
        ]
        out = format_backup_list(backups)
        assert "#1" in out
        assert "abc1234" in out
        assert "2026-01-01" in out

    def test_multiple_entries(self):
        backups = [
            {"n": 1, "tag": "luckyd-backup/20260101_120000", "hash": "aaa", "date": "2026-01-01", "subject": "snap1"},
            {"n": 2, "tag": "luckyd-backup/20260101_110000", "hash": "bbb", "date": "2026-01-01", "subject": "snap2"},
        ]
        out = format_backup_list(backups)
        assert "#1" in out
        assert "#2" in out
        assert "aaa" in out
        assert "bbb" in out

    def test_includes_restore_hint(self):
        backups = [{"n": 1, "tag": "", "hash": "abc", "date": "", "subject": "snap"}]
        out = format_backup_list(backups)
        assert "restore" in out.lower()

    def test_skips_subject_when_it_is_tag_name(self):
        backups = [{"n": 1, "tag": "luckyd-backup/ts", "hash": "abc",
                    "date": "2026-01-01", "subject": "luckyd-backup/ts"}]
        out = format_backup_list(backups)
        # subject should not be printed twice
        assert out.count("luckyd-backup/ts") == 1
