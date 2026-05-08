"""Tests for the undo module."""

import tempfile
from pathlib import Path

from luckyd_code.undo import push, pop, peek, clear, undo_last


class TestUndo:
    def setup_method(self):
        clear()

    def test_push_and_pop(self):
        """Push an entry and pop it back."""
        push("/path/to/file.py", "original content", "Edit")
        entry = pop()
        assert entry is not None
        assert entry.file_path == "/path/to/file.py"
        assert entry.original_content == "original content"
        assert entry.action == "Edit"

    def test_pop_empty_stack(self):
        """Pop from empty stack should return None."""
        clear()
        assert pop() is None

    def test_peek_returns_last_without_popping(self):
        """Peek should return the last entry without removing it."""
        push("/a.py", "content", "Write")
        push("/b.py", "content2", "Edit")
        entry = peek()
        assert entry.file_path == "/b.py"
        # Stack should still have both
        assert len(pop_all()) == 2

    def test_clear_empties_stack(self):
        """Clear should remove all entries."""
        push("/a.py", "content", "Write")
        push("/b.py", "content2", "Edit")
        clear()
        assert pop() is None

    def test_undo_last_with_empty_stack(self):
        """undo_last on empty stack should return message."""
        clear()
        result = undo_last()
        assert "Nothing to undo" in result

    def test_undo_last_restores_file(self):
        """undo_last should restore a file's original content."""
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "test.txt"
            file_path.write_text("modified content")
            push(str(file_path), "original content", "Edit")
            result = undo_last()
            assert "Undone" in result
            assert file_path.read_text() == "original content"

    def test_undo_last_deletes_created_file(self):
        """undo_last should delete a file that was created."""
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "new_file.txt"
            file_path.write_text("new content")
            push(str(file_path), None, "Write")  # None original = file was created
            result = undo_last()
            assert "Undone" in result
            assert not file_path.exists()


def pop_all():
    """Helper to pop all entries."""
    entries = []
    while True:
        e = pop()
        if e is None:
            break
        entries.append(e)
    return entries
