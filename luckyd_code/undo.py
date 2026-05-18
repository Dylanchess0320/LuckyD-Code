"""Undo support — track file changes and reverse them, with persistence."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ._data_dir import data_path

UNDO_FILE = data_path("undo.json")

_logger = logging.getLogger("luckyd_code.undo")


class UndoEntry:
    def __init__(self, file_path: str, original_content: str | None = None, action: str = ""):
        self.file_path = file_path
        self.original_content = original_content
        self.action = action

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "original_content": self.original_content,
            "action": self.action,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "UndoEntry":
        return cls(
            file_path=d.get("file_path", ""),
            original_content=d.get("original_content"),
            action=d.get("action", ""),
        )


_undo_stack: list[UndoEntry] = []


def _save() -> None:
    """Persist the undo stack to disk."""
    try:
        data = [e.to_dict() for e in _undo_stack]
        UNDO_FILE.parent.mkdir(parents=True, exist_ok=True)
        UNDO_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        _logger.warning("Failed to save undo history", exc_info=True)


def _load() -> None:
    """Load the undo stack from disk."""
    global _undo_stack
    try:
        if UNDO_FILE.exists():
            data = json.loads(UNDO_FILE.read_text(encoding="utf-8"))
            _undo_stack = [UndoEntry.from_dict(d) for d in data]
        else:
            _undo_stack = []
    except Exception:
        _logger.warning("Failed to load undo history", exc_info=True)
        _undo_stack = []


def push(file_path: str, original_content: str | None = None, action: str = "") -> None:
    """Push an undo entry and persist."""
    _undo_stack.append(UndoEntry(file_path, original_content, action))
    _save()


def pop() -> UndoEntry | None:
    """Pop and return the last undo entry."""
    if _undo_stack:
        entry = _undo_stack.pop()
        _save()
        return entry
    return None


def peek() -> UndoEntry | None:
    """Peek at the last undo entry without popping."""
    if _undo_stack:
        return _undo_stack[-1]
    return None


def clear() -> None:
    """Clear all undo history."""
    _undo_stack.clear()
    _save()


def undo_last() -> str:
    """Undo the last file operation. Returns status message."""
    entry = pop()
    if not entry:
        return "Nothing to undo."

    path = Path(entry.file_path)
    if not path.exists() and entry.original_content is None:
        return f"Cannot undo: {entry.file_path} no longer exists (was created)"

    try:
        if entry.original_content is None:
            path.unlink()
            return f"Undone: deleted {entry.file_path} (was created by {entry.action})"
        else:
            path.write_text(entry.original_content, encoding="utf-8")
            return f"Undone: restored {entry.file_path} to before {entry.action}"
    except Exception as e:
        return f"Undo failed: {e}"


def get_history() -> list[dict[str, Any]]:
    """Return readable history of undo entries."""
    return [
        {"file": e.file_path, "action": e.action}
        for e in reversed(_undo_stack[-20:])
    ]


def count() -> int:
    return len(_undo_stack)


# Load existing history on import
_load()
