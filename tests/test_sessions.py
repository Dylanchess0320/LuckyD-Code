"""Tests for the sessions module."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from luckyd_code.context import ConversationContext
from luckyd_code.sessions import (
    save_session,
    load_session,
    list_sessions,
    delete_session,
)


class TestSessions:
    def setup_method(self):
        self.ctx = ConversationContext("system prompt")
        self.ctx.add_user_message("Hello")
        self.ctx.add_assistant_message(content="Hi there!")

    def test_save_and_load_roundtrip(self):
        """Save then load should restore messages."""
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path(tmp) / "sessions"
            with patch("luckyd_code.sessions.SESSIONS_DIR", sessions_dir):
                result = save_session("test_session", self.ctx)
                assert "saved" in result

                # Load into a new context
                new_ctx = ConversationContext("system prompt")
                result = load_session("test_session", new_ctx)
                assert "loaded" in result
                assert new_ctx.count_messages() == 3  # system + user + assistant

    def test_save_session_preserves_content(self):
        """Saved session should preserve message content (system prompt excluded)."""
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path(tmp) / "sessions"
            with patch("luckyd_code.sessions.SESSIONS_DIR", sessions_dir):
                save_session("content_test", self.ctx)

                # Read the file directly
                path = sessions_dir / "content_test.json"
                assert path.exists()
                data = json.loads(path.read_text())
                # System prompt is now excluded on save, so count is user + assistant = 2
                assert data["message_count"] == 2
                assert data["messages"][0]["content"] == "Hello"

    def test_load_nonexistent_session(self):
        """Loading a nonexistent session should return error."""
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path(tmp) / "sessions"
            with patch("luckyd_code.sessions.SESSIONS_DIR", sessions_dir):
                result = load_session("nonexistent", self.ctx)
                assert "not found" in result

    def test_list_sessions(self):
        """list_sessions should show saved sessions."""
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path(tmp) / "sessions"
            with patch("luckyd_code.sessions.SESSIONS_DIR", sessions_dir):
                save_session("session_a", self.ctx)
                save_session("session_b", self.ctx)
                result = list_sessions()
                assert "session_a" in result
                assert "session_b" in result

    def test_list_sessions_empty(self):
        """list_sessions with no sessions should return message."""
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path(tmp) / "sessions"
            with patch("luckyd_code.sessions.SESSIONS_DIR", sessions_dir):
                result = list_sessions()
                assert "No saved sessions" in result

    def test_delete_session(self):
        """Deleting a session should remove the file."""
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path(tmp) / "sessions"
            with patch("luckyd_code.sessions.SESSIONS_DIR", sessions_dir):
                save_session("to_delete", self.ctx)
                result = delete_session("to_delete")
                assert "deleted" in result
                assert not (sessions_dir / "to_delete.json").exists()

    def test_delete_nonexistent_session(self):
        """Deleting a nonexistent session should return error."""
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path(tmp) / "sessions"
            with patch("luckyd_code.sessions.SESSIONS_DIR", sessions_dir):
                result = delete_session("nonexistent")
                assert "not found" in result

    def test_list_sessions_corrupted_file_logs_warning(self, caplog):
        """Corrupted session files should log a WARNING, not fail silently."""
        import logging
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path(tmp) / "sessions"
            sessions_dir.mkdir(parents=True)
            # Write a malformed JSON file
            (sessions_dir / "bad_session.json").write_text("NOT VALID JSON", encoding="utf-8")
            with patch("luckyd_code.sessions.SESSIONS_DIR", sessions_dir), \
                 caplog.at_level(logging.WARNING, logger="luckyd_code.sessions"):
                result = list_sessions()
            # The stub entry should still appear in the listing
            assert "bad_session" in result
            # A warning must have been emitted
            assert any("bad_session.json" in r.message for r in caplog.records), (
                "Expected a warning about the corrupted session file"
            )
