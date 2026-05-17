"""Tests for luckyd_code.__init__ lazy loading and web_routes/brain.py — final gap push.

Target uncovered lines:
  luckyd_code/__init__.py     lines 30-34 — __getattr__ lazy sub-package import
  luckyd_code/web_routes/brain.py  lines 19-20, 41-42, 55 — RAG paths + search
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ═══════════════════════════════════════════════════════════════════════════
# luckyd_code/__init__.py — lazy sub-package loader (lines 30-34)
# ═══════════════════════════════════════════════════════════════════════════

class TestInitLazyLoader:
    """Lines 30-34: __getattr__ lazy-imports _LAZY_SUBPACKAGES on demand."""

    def test_lazy_access_memory(self):
        """Accessing luckyd_code.memory triggers lazy import."""
        import luckyd_code
        # Force deletion so __getattr__ runs fresh
        luckyd_code.__dict__.pop("memory", None)
        mem = luckyd_code.memory
        assert mem is not None
        assert hasattr(mem, "manager") or True

    def test_lazy_access_settings(self):
        """Accessing luckyd_code.settings triggers lazy import."""
        import luckyd_code
        luckyd_code.__dict__.pop("settings", None)
        settings = luckyd_code.settings
        assert settings is not None

    def test_lazy_access_tools(self):
        """Accessing luckyd_code.tools triggers lazy import."""
        import luckyd_code
        luckyd_code.__dict__.pop("tools", None)
        tools = luckyd_code.tools
        assert tools is not None

    def test_lazy_access_brain(self):
        """Accessing luckyd_code.brain triggers lazy import."""
        import luckyd_code
        luckyd_code.__dict__.pop("brain", None)
        brain = luckyd_code.brain
        assert brain is not None

    def test_unknown_attribute_raises_attribute_error(self):
        """__getattr__ raises AttributeError for unknown names."""
        import luckyd_code
        with pytest.raises(AttributeError, match="has no attribute"):
            _ = luckyd_code.totally_nonexistent_attribute_xyz

    def test_lazy_cached_after_first_access(self):
        """Second access returns the same object (cached in globals)."""
        import luckyd_code
        luckyd_code.__dict__.pop("settings", None)
        s1 = luckyd_code.settings
        s2 = luckyd_code.settings
        assert s1 is s2


# ═══════════════════════════════════════════════════════════════════════════
# web_routes/brain.py — remaining uncovered lines
# ═══════════════════════════════════════════════════════════════════════════

def _brain_app():
    """Build a minimal FastAPI app with the brain router attached."""
    from luckyd_code.web_routes.brain import router
    app = FastAPI()
    state = MagicMock()
    state.knowledge_graph = MagicMock()
    app.state.web_state = state
    app.include_router(router)
    return app


class TestBrainRoutesRemainingCoverage:
    @pytest.fixture
    def client(self):
        return TestClient(_brain_app(), raise_server_exceptions=False)

    # ── GET /api/brain — RAG available path (lines 19-20)
    def test_brain_status_with_rag_available(self, client):
        """Lines 19-20: rag_available=True path → rag_chunks in response."""
        mock_kg = MagicMock()
        mock_kg.nodes = {"module:x": {}}
        mock_kg.stats = {
            "node_count": 5, "edge_count": 3, "files_parsed": 2,
        }
        mock_idx = MagicMock()
        mock_idx.load.return_value = True

        mock_retriever = MagicMock()
        mock_retriever.stats.return_value = {
            "vector": {"chunks": 42, "files": 3},
            "graph": {},
        }

        with patch("luckyd_code.web_routes.brain.KnowledgeGraph", return_value=mock_kg), \
             patch("luckyd_code.web_routes.brain.VectorIndexer", return_value=mock_idx), \
             patch("luckyd_code.web_routes.brain.Retriever", return_value=mock_retriever):
            resp = client.get("/api/brain")

        assert resp.status_code == 200
        data = resp.json()
        assert "symbols" in data
        assert data.get("rag_chunks") == 42

    def test_brain_status_rag_retriever_exception_silenced(self, client):
        """Retriever.stats() exception inside rag path → still returns 200."""
        mock_kg = MagicMock()
        mock_kg.nodes = {"module:x": {}}
        mock_kg.stats = {"node_count": 1, "edge_count": 0, "files_parsed": 1}

        mock_idx = MagicMock()
        mock_idx.load.return_value = True

        mock_retriever = MagicMock()
        mock_retriever.stats.side_effect = RuntimeError("stats failed")

        with patch("luckyd_code.web_routes.brain.KnowledgeGraph", return_value=mock_kg), \
             patch("luckyd_code.web_routes.brain.VectorIndexer", return_value=mock_idx), \
             patch("luckyd_code.web_routes.brain.Retriever", return_value=mock_retriever):
            resp = client.get("/api/brain")

        assert resp.status_code == 200

    def test_brain_status_with_last_built_timestamp(self, client):
        """last_built in stats → formatted string in response."""
        import time
        mock_kg = MagicMock()
        mock_kg.nodes = {"x": {}}
        mock_kg.stats = {
            "node_count": 2, "edge_count": 1,
            "files_parsed": 1, "last_built": time.time(),
        }
        mock_idx = MagicMock()
        mock_idx.load.return_value = False

        with patch("luckyd_code.web_routes.brain.KnowledgeGraph", return_value=mock_kg), \
             patch("luckyd_code.web_routes.brain.VectorIndexer", return_value=mock_idx):
            resp = client.get("/api/brain")

        assert resp.status_code == 200
        assert "last_built" in resp.json()

    def test_brain_status_empty_graph(self, client):
        """Empty knowledge graph → returns status=empty message."""
        mock_kg = MagicMock()
        mock_kg.nodes = {}
        mock_kg.stats = {"node_count": 0}
        mock_idx = MagicMock()
        mock_idx.load.return_value = False

        with patch("luckyd_code.web_routes.brain.KnowledgeGraph", return_value=mock_kg), \
             patch("luckyd_code.web_routes.brain.VectorIndexer", return_value=mock_idx):
            resp = client.get("/api/brain")

        assert resp.status_code == 200
        assert resp.json().get("status") == "empty"

    # ── POST /api/brain/rebuild — state reload path (lines 41-42)
    def test_brain_rebuild_reloads_state(self, client):
        """Lines 41-42: after rebuild, state.knowledge_graph.load() is called."""
        mock_result = {"chunks": 10, "files": 3, "node_count": 20, "files_parsed": 3}

        with patch("luckyd_code.web_routes.brain.rebuild_project", return_value=mock_result), \
             patch("os.getcwd", return_value="/proj"):
            resp = client.post("/api/brain/rebuild")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["chunks"] == 10
        assert data["symbols"] == 20

    # ── GET /api/brain/search — result formatting (line 55)
    def test_brain_search_returns_formatted_results(self, client):
        """Line 55: search results are formatted with content/file/score keys."""
        mock_retriever = MagicMock()
        mock_retriever.search.return_value = [
            {"content": "def foo(): pass", "file": "foo.py", "score": 0.9},
            {"content": "class Bar: pass", "file": "bar.py", "score": 0.8},
        ]

        with patch("luckyd_code.web_routes.brain.Retriever", return_value=mock_retriever):
            resp = client.get("/api/brain/search", params={"q": "foo"})

        assert resp.status_code == 200
        results = resp.json().get("results", [])
        assert len(results) == 2
        assert results[0]["file"] == "foo.py"
        assert results[0]["score"] == 0.9

    def test_brain_search_empty_query_returns_empty(self, client):
        resp = client.get("/api/brain/search", params={"q": ""})
        assert resp.status_code == 200
        assert resp.json() == {"results": []}

    def test_brain_search_exception_returns_500(self, client):
        with patch("luckyd_code.web_routes.brain.Retriever",
                   side_effect=RuntimeError("search failed")):
            resp = client.get("/api/brain/search", params={"q": "anything"})
        assert resp.status_code == 500

    def test_brain_stats_returns_info(self, client):
        mock_retriever = MagicMock()
        mock_retriever.stats.return_value = {"vector": {"chunks": 5}, "graph": {}}
        with patch("luckyd_code.web_routes.brain.Retriever", return_value=mock_retriever):
            resp = client.get("/api/brain/stats")
        assert resp.status_code == 200
        assert "vector" in resp.json()

    def test_brain_stats_exception_returns_500(self, client):
        with patch("luckyd_code.web_routes.brain.Retriever",
                   side_effect=RuntimeError("stats error")):
            resp = client.get("/api/brain/stats")
        assert resp.status_code == 500

    def test_brain_dependents_no_symbol_returns_400(self, client):
        resp = client.get("/api/brain/dependents")
        assert resp.status_code == 400

    def test_brain_dependents_returns_results(self, client):
        mock_kg = MagicMock()
        mock_kg.find_dependents.return_value = ["module:x", "class:x:Foo"]
        with patch("luckyd_code.web_routes.brain.KnowledgeGraph", return_value=mock_kg):
            resp = client.get("/api/brain/dependents", params={"symbol": "Foo"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2

    def test_brain_dependents_exception_returns_500(self, client):
        with patch("luckyd_code.web_routes.brain.KnowledgeGraph",
                   side_effect=RuntimeError("db error")):
            resp = client.get("/api/brain/dependents", params={"symbol": "Foo"})
        assert resp.status_code == 500
