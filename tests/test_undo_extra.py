"""Additional tests for luckyd_code/undo.py.

The existing test_undo.py covers push/pop/peek/clear and the main undo_last
paths. This file adds coverage for the remaining uncovered lines:

  - UndoEntry.from_dict() — used by _load(), not exercised by push/pop alone
  - get_history()         — not tested at all
  - count()               — not tested at all
  - _save() exception path — when disk write fails
  - _load() corrupt JSON  — malformed undo.json should reset to empty stack
  - undo_last() "Cannot undo" path — file was created but is now gone
  - undo_last() "Undo failed" path — exception during write-back
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

import luckyd_code.undo as undo_mod
from luckyd_code.undo import (
    UndoEntry,
    clear,
    count,
    get_history,
    pop,
    push,
    undo_last,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _drain():
    """Pop every entry from the stack and return them."""
    entries = []
    while True:
        e = pop()
        if e is None:
            break
        entries.append(e)
    return entries


# ---------------------------------------------------------------------------
# UndoEntry.from_dict
# ---------------------------------------------------------------------------

class TestUndoEntryFromDict:

    def test_from_dict_full(self):
        d = {"file_path": "/a/b.py", "original_content": "old code", "action": "Write"}
        entry = UndoEntry.from_dict(d)
        assert entry.file_path == "/a/b.py"
        assert entry.original_content == "old code"
        assert entry.action == "Write"

    def test_from_dict_none_content(self):
        """original_content=None means the file was created (no prior state)."""
        d = {"file_path": "/new.py", "original_content": None, "action": "Create"}
        entry = UndoEntry.from_dict(d)
        assert entry.original_content is None
        assert entry.file_path == "/new.py"

    def test_from_dict_empty_dict_uses_defaults(self):
        entry = UndoEntry.from_dict({})
        assert entry.file_path == ""
        assert entry.original_content is None
        assert entry.action == ""

    def test_from_dict_roundtrip(self):
        """to_dict → from_dict should produce an equivalent entry."""
        original = UndoEntry("/src/main.py", "original source", "Edit")
        restored = UndoEntry.from_dict(original.to_dict())
        assert restored.file_path == original.file_path
        assert restored.original_content == original.original_content
        assert restored.action == original.action


# ---------------------------------------------------------------------------
# get_history
# ---------------------------------------------------------------------------

class TestGetHistory:

    def setup_method(self):
        clear()

    def test_empty_stack_returns_empty_list(self):
        assert get_history() == []

    def test_single_entry(self):
        push("/a.py", "content", "Write")
        history = get_history()
        assert len(history) == 1
        assert history[0]["file"] == "/a.py"
        assert history[0]["action"] == "Write"

    def test_multiple_entries_returned_in_reverse_order(self):
        """get_history returns most-recent first (reversed stack)."""
        push("/a.py", "old a", "Edit")
        push("/b.py", "old b", "Write")
        push("/c.py", None, "Create")
        history = get_history()
        assert len(history) == 3
        # Most recent first
        assert history[0]["file"] == "/c.py"
        assert history[1]["file"] == "/b.py"
        assert history[2]["file"] == "/a.py"

    def test_capped_at_20_entries(self):
        """get_history shows at most 20 entries regardless of stack size."""
        for i in range(25):
            push(f"/file{i}.py", f"content {i}", "Edit")
        history = get_history()
        assert len(history) == 20

    def test_history_keys_are_file_and_action(self):
        push("/x.py", "c", "Delete")
        history = get_history()
        assert "file" in history[0]
        assert "action" in history[0]
        assert list(history[0].keys()) == ["file", "action"]

    def test_history_does_not_expose_content(self):
        """Sensitive original_content should not appear in get_history output."""
        push("/secret.py", "top secret code", "Edit")
        history = get_history()
        assert "original_content" not in history[0]
        assert "top secret code" not in str(history[0])


# ---------------------------------------------------------------------------
# count
# ---------------------------------------------------------------------------

class TestCount:

    def setup_method(self):
        clear()

    def test_empty_stack_returns_zero(self):
        assert count() == 0

    def test_count_after_single_push(self):
        push("/a.py", "c", "Edit")
        assert count() == 1

    def test_count_after_multiple_pushes(self):
        for i in range(5):
            push(f"/file{i}.py", f"c{i}", "Edit")
        assert count() == 5

    def test_count_decreases_after_pop(self):
        push("/a.py", "c", "Edit")
        push("/b.py", "d", "Write")
        assert count() == 2
        pop()
        assert count() == 1

    def test_count_zero_after_clear(self):
        push("/a.py", "c", "Edit")
        push("/b.py", "d", "Write")
        clear()
        assert count() == 0


# ---------------------------------------------------------------------------
# _save() exception path
# ---------------------------------------------------------------------------

class TestSaveException:

    def setup_method(self):
        clear()

    def test_save_exception_does_not_crash(self):
        """If the disk write fails, _save() logs a warning but never raises."""
        with patch("luckyd_code.undo.json.dumps", side_effect=TypeError("unserializable")):
            # _save() is called inside push() — it must not propagate the error
            push("/a.py", "content", "Edit")
        # If we reach here without an exception the test passes

    def test_save_exception_logged_as_warning(self):
        """The exception should be logged at WARNING level."""
        with patch("luckyd_code.undo.json.dumps", side_effect=TypeError("bad")):
            with patch.object(undo_mod._logger, "warning") as mock_warn:
                undo_mod._save()
        mock_warn.assert_called_once()

    def test_stack_state_preserved_even_if_save_fails(self):
        """The in-memory stack should still update even if persistence fails."""
        push("/a.py", "content", "Edit")
        with patch("luckyd_code.undo.json.dumps", side_effect=TypeError("bad")):
            push("/b.py", "more", "Write")
        # Both entries are in memory even though the second _save() failed
        assert count() == 2


# ---------------------------------------------------------------------------
# _load() — corrupt / missing JSON
# ---------------------------------------------------------------------------

class TestLoadFromDisk:

    def test_corrupt_json_resets_stack(self, tmp_path, monkeypatch):
        """A malformed undo.json should result in an empty stack, not a crash."""
        corrupt = tmp_path / "undo.json"
        corrupt.write_text("{ this is not valid json !!! }", encoding="utf-8")
        monkeypatch.setattr(undo_mod, "UNDO_FILE", corrupt)
        monkeypatch.setattr(undo_mod, "_undo_stack", [])
        undo_mod._load()
        assert undo_mod._undo_stack == []

    def test_missing_file_resets_stack(self, tmp_path, monkeypatch):
        """If undo.json doesn't exist yet, _load() should produce an empty stack."""
        missing = tmp_path / "does_not_exist.json"
        monkeypatch.setattr(undo_mod, "UNDO_FILE", missing)
        monkeypatch.setattr(undo_mod, "_undo_stack", [])
        undo_mod._load()
        assert undo_mod._undo_stack == []

    def test_valid_json_restores_entries(self, tmp_path, monkeypatch):
        """A valid undo.json should be loaded into _undo_stack correctly."""
        data = [
            {"file_path": "/x.py", "original_content": "hello", "action": "Edit"},
            {"file_path": "/y.py", "original_content": None, "action": "Create"},
        ]
        undo_file = tmp_path / "undo.json"
        undo_file.write_text(json.dumps(data), encoding="utf-8")
        monkeypatch.setattr(undo_mod, "UNDO_FILE", undo_file)
        monkeypatch.setattr(undo_mod, "_undo_stack", [])
        undo_mod._load()
        assert len(undo_mod._undo_stack) == 2
        assert undo_mod._undo_stack[0].file_path == "/x.py"
        assert undo_mod._undo_stack[1].original_content is None

    def test_load_exception_logs_warning(self, tmp_path, monkeypatch):
        """If _load() fails for any reason, it should log a warning."""
        # Make UNDO_FILE.exists() blow up
        bad_path = MagicMock()
        bad_path.exists.side_effect = OSError("disk error")
        monkeypatch.setattr(undo_mod, "UNDO_FILE", bad_path)
        monkeypatch.setattr(undo_mod, "_undo_stack", [])
        with patch.object(undo_mod._logger, "warning") as mock_warn:
            undo_mod._load()
        mock_warn.assert_called_once()
        assert undo_mod._undo_stack == []


# ---------------------------------------------------------------------------
# undo_last() — additional edge cases
# ---------------------------------------------------------------------------

class TestUndoLastEdgeCases:

    def setup_method(self):
        clear()

    def test_file_was_created_but_is_now_gone(self):
        """
        Entry has original_content=None (file was created by the agent)
        but the file has since been externally deleted.
        Should return the 'Cannot undo' message, not crash.
        """
        push("/ghost/file_that_never_existed.txt", None, "Create")
        result = undo_last()
        assert "Cannot undo" in result
        assert "no longer exists" in result

    def test_undo_failed_on_write_error(self, tmp_path):
        """
        If restoring content raises an exception (e.g. parent dir gone),
        undo_last() should return 'Undo failed: ...' rather than crashing.
        """
        # Point to a path whose parent doesn't exist so write_text will fail
        bad_path = tmp_path / "missing_parent" / "file.txt"
        push(str(bad_path), "original content here", "Edit")
        result = undo_last()
        assert "Undo failed" in result

    def test_undo_failed_on_unlink_error(self, tmp_path):
        """
        If deleting a created file raises an exception, undo_last() should
        return 'Undo failed: ...' rather than propagating the error.
        """
        file_path = tmp_path / "created.txt"
        file_path.write_text("new content")
        push(str(file_path), None, "Create")
        with patch("luckyd_code.undo.Path.unlink", side_effect=PermissionError("locked")):
            result = undo_last()
        assert "Undo failed" in result

    def test_undo_last_message_includes_file_path(self, tmp_path):
        """Success messages should mention the file being restored."""
        f = tmp_path / "target.txt"
        f.write_text("modified")
        push(str(f), "original", "Edit")
        result = undo_last()
        assert "target.txt" in result

    def test_undo_last_message_includes_action(self, tmp_path):
        """Success messages should mention the action being undone."""
        f = tmp_path / "actionfile.txt"
        f.write_text("modified")
        push(str(f), "original", "MyCustomAction")
        result = undo_last()
        assert "MyCustomAction" in result


# needed for load_exception test
from unittest.mock import MagicMock  # noqa: E402 (placed here to avoid polluting top-level)
