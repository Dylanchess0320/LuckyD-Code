"""Tests for web_routes/memories.py, misc.py, and sessions.py."""

import sys
import pytest

# Skip on Python 3.15 — anyio compatibility
if sys.version_info >= (3, 15):
    pytest.skip("anyio not compatible with Python 3.15", allow_module_level=True)

from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from luckyd_code.web_routes.memories import router as memories_router
from luckyd_code.web_routes.misc import router as misc_router
from luckyd_code.web_routes.sessions import router as sessions_router


# ---------------------------------------------------------------------------
# Shared app factory
# ---------------------------------------------------------------------------

def _make_app(*routers):
    app = FastAPI()
    for r in routers:
        app.include_router(r)
    return app


def _make_state():
    state = MagicMock()
    state.context.count_messages.return_value = 5
    state.context.messages = []
    state.context.max_messages = 100
    state.context.estimate_tokens.return_value = 1000
    state.memory_module.load_claude_md.return_value = ""
    state.web_memory_mgr.list_memories.return_value = []
    state.web_memory_mgr.search_memories.return_value = []
    state.web_memory_mgr.load_memory.return_value = None
    state.web_memory_mgr.delete_memory.return_value = True
    return state


# ---------------------------------------------------------------------------
# Memories routes
# ---------------------------------------------------------------------------

class TestMemoriesRoutes:
    @pytest.fixture
    def client(self):
        app = _make_app(memories_router)
        state = _make_state()
        with patch("luckyd_code.web_routes.memories.memory_module") as mock_mm:
            mock_mm.load_claude_md.return_value = "# Memory"
            app.state.web_state = state

            with TestClient(app) as c:
                c.app = app
                yield c, mock_mm, state

    def test_get_memory(self, client):
        c, mock_mm, state = client
        resp = c.get("/api/memory")
        assert resp.status_code == 200
        data = resp.json()
        assert "claude_md" in data
        assert "message_count" in data

    def test_save_memory(self, client):
        c, mock_mm, state = client
        resp = c.post("/api/memory/save", json={"content": "new memory"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "saved"
        mock_mm.save_claude_md.assert_called_once_with("new memory")

    def test_save_memory_updates_existing_message(self, client):
        c, mock_mm, state = client
        state.context.messages = [
            {"role": "user", "content": "<claude-md>old</claude-md>"}
        ]
        resp = c.post("/api/memory/save", json={"content": "new"})
        assert resp.status_code == 200

    def test_list_memories(self, client):
        c, mock_mm, state = client
        state.web_memory_mgr.list_memories.return_value = [{"name": "note", "content": "hi"}]
        resp = c.get("/api/memories")
        assert resp.status_code == 200
        assert "memories" in resp.json()

    def test_list_memories_with_query(self, client):
        c, mock_mm, state = client
        state.web_memory_mgr.search_memories.return_value = [{"name": "note"}]
        resp = c.get("/api/memories?q=note")
        assert resp.status_code == 200
        state.web_memory_mgr.search_memories.assert_called_once_with("note")

    def test_save_named_memory(self, client):
        c, mock_mm, state = client
        resp = c.post("/api/memories/save", json={"name": "note1", "content": "hello"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_delete_memory_found(self, client):
        c, mock_mm, state = client
        state.web_memory_mgr.delete_memory.return_value = True
        resp = c.delete("/api/memories/note1")
        assert resp.status_code == 200

    def test_delete_memory_not_found(self, client):
        c, mock_mm, state = client
        state.web_memory_mgr.delete_memory.return_value = False
        resp = c.delete("/api/memories/nope")
        assert resp.status_code == 404

    def test_get_named_memory_found(self, client):
        c, mock_mm, state = client
        state.web_memory_mgr.load_memory.return_value = "memory content"
        resp = c.get("/api/memories/note1")
        assert resp.status_code == 200
        assert resp.json()["content"] == "memory content"

    def test_get_named_memory_not_found(self, client):
        c, mock_mm, state = client
        state.web_memory_mgr.load_memory.return_value = None
        resp = c.get("/api/memories/missing")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Misc routes
# ---------------------------------------------------------------------------

class TestMiscRoutes:
    @pytest.fixture
    def client(self):
        app = _make_app(misc_router)
        state = _make_state()
        app.state.web_state = state

        with TestClient(app) as c:
            yield c, state

    def test_clear(self, client):
        c, state = client
        with patch("luckyd_code.web_routes.misc.MemoryManager") as MockMgr:
            mgr = MockMgr.return_value
            mgr.get_all_memories_formatted.return_value = ""
            resp = c.post("/api/clear")
        assert resp.status_code == 200
        assert resp.json()["status"] == "cleared"

    def test_clear_with_merged_memory(self, client):
        c, state = client
        state.memory_module.load_claude_md.return_value = "# Project"
        with patch("luckyd_code.web_routes.misc.MemoryManager") as MockMgr:
            mgr = MockMgr.return_value
            mgr.get_all_memories_formatted.return_value = "- note"
            resp = c.post("/api/clear")
        assert resp.status_code == 200

    def test_clear_exception_returns_500(self, client):
        c, state = client
        state.context.reset.side_effect = RuntimeError("boom")
        resp = c.post("/api/clear")
        assert resp.status_code == 500

    def test_undo(self, client):
        c, state = client
        with patch("luckyd_code.web_routes.misc.undo_last", return_value="undone"):
            resp = c.post("/api/undo")
        assert resp.status_code == 200
        assert resp.json()["status"] == "undone"

    def test_undo_exception(self, client):
        c, state = client
        with patch("luckyd_code.web_routes.misc.undo_last", side_effect=Exception("fail")):
            resp = c.post("/api/undo")
        assert resp.status_code == 500

    def test_compact(self, client):
        c, state = client
        state.context.compact.return_value = "compacted"
        resp = c.post("/api/compact")
        assert resp.status_code == 200
        assert resp.json()["status"] == "compacted"

    def test_compact_exception(self, client):
        c, state = client
        state.context.compact.side_effect = Exception("fail")
        resp = c.post("/api/compact")
        assert resp.status_code == 500

    def test_context_info(self, client):
        c, state = client
        resp = c.get("/api/context")
        assert resp.status_code == 200
        data = resp.json()
        assert "message_count" in data
        assert "max_messages" in data
        assert "estimated_tokens" in data

    def test_context_info_exception(self, client):
        c, state = client
        state.context.count_messages.side_effect = Exception("fail")
        resp = c.get("/api/context")
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# Sessions routes
# ---------------------------------------------------------------------------

class TestSessionsRoutes:
    @pytest.fixture
    def client(self):
        app = _make_app(sessions_router)
        state = _make_state()
        app.state.web_state = state

        with TestClient(app) as c:
            yield c, state

    def test_list_sessions(self, client):
        c, state = client
        with patch("luckyd_code.web_routes.sessions.list_sessions", return_value=["s1", "s2"]):
            resp = c.get("/api/sessions")
        assert resp.status_code == 200
        assert resp.json()["sessions"] == ["s1", "s2"]

    def test_save_session(self, client):
        c, state = client
        with patch("luckyd_code.web_routes.sessions.save_session", return_value="Saved session 'work'"):
            resp = c.post("/api/sessions/save", json={"name": "work"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_load_session(self, client):
        c, state = client
        with patch("luckyd_code.web_routes.sessions.load_session", return_value="Loaded session 'work'"):
            resp = c.post("/api/sessions/load", json={"name": "work"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_delete_session(self, client):
        c, state = client
        with patch("luckyd_code.web_routes.sessions.delete_session", return_value="Deleted"):
            resp = c.delete("/api/sessions/work")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
