"""Tests for luckyd_code.brain.rebuild_project — covers brain/__init__.py lines 37-81."""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest


# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────

def _make_mock_indexer(stats: dict | None = None) -> MagicMock:
    m = MagicMock()
    m.build.return_value = stats if stats is not None else {"chunks": 5, "files": 2, "languages": {"py": 2}}
    m.file_mtimes = {}
    return m


def _make_mock_graph(node_count: int = 10, files_parsed: int = 3) -> MagicMock:
    m = MagicMock()
    m.stats = {"node_count": node_count, "files_parsed": files_parsed}
    return m


# ────────────────────────────────────────────────────────────────────────────
# rebuild_project: entry-point and defaults
# ────────────────────────────────────────────────────────────────────────────

class TestRebuildProjectDefaults:
    def test_returns_dict_with_expected_keys(self, tmp_path):
        with patch("luckyd_code.brain.chunk_project", return_value=[]), \
             patch("luckyd_code.brain.parse_project", return_value=([], {})):
            from luckyd_code.brain import rebuild_project
            result = rebuild_project(str(tmp_path))

        assert isinstance(result, dict)
        for key in ("chunks", "files", "node_count", "files_parsed", "languages"):
            assert key in result

    def test_defaults_to_cwd_when_root_is_none(self):
        expected_cwd = os.getcwd()
        with patch("luckyd_code.brain.chunk_project", return_value=[]) as mock_cp, \
             patch("luckyd_code.brain.parse_project", return_value=([], {})):
            from luckyd_code.brain import rebuild_project
            rebuild_project(None)

        mock_cp.assert_called_once_with(expected_cwd)

    def test_empty_chunks_and_empty_parsed_returns_zeros(self, tmp_path):
        with patch("luckyd_code.brain.chunk_project", return_value=[]), \
             patch("luckyd_code.brain.parse_project", return_value=([], {})):
            from luckyd_code.brain import rebuild_project
            result = rebuild_project(str(tmp_path))

        assert result["chunks"] == 0
        assert result["files"] == 0
        assert result["node_count"] == 0
        assert result["files_parsed"] == 0
        assert result["languages"] == {}


# ────────────────────────────────────────────────────────────────────────────
# rebuild_project: vector index path (chunks present)
# ────────────────────────────────────────────────────────────────────────────

class TestRebuildProjectVectorIndex:
    def test_builds_index_when_chunks_present(self, tmp_path):
        fake_chunks = [MagicMock(), MagicMock()]
        mock_indexer = _make_mock_indexer({"chunks": 2, "files": 1, "languages": {"py": 1}})

        with patch("luckyd_code.brain.chunk_project", return_value=fake_chunks), \
             patch("luckyd_code.brain.VectorIndexer", return_value=mock_indexer), \
             patch("luckyd_code.brain.parse_project", return_value=([], {})), \
             patch("os.walk", return_value=[]):
            from luckyd_code.brain import rebuild_project
            result = rebuild_project(str(tmp_path))

        mock_indexer.build.assert_called_once_with(fake_chunks)
        mock_indexer.save.assert_called_once()
        assert result["chunks"] == 2
        assert result["files"] == 1
        assert result["languages"] == {"py": 1}

    def test_skips_index_when_no_chunks(self, tmp_path):
        mock_indexer = _make_mock_indexer()

        with patch("luckyd_code.brain.chunk_project", return_value=[]), \
             patch("luckyd_code.brain.VectorIndexer", return_value=mock_indexer), \
             patch("luckyd_code.brain.parse_project", return_value=([], {})):
            from luckyd_code.brain import rebuild_project
            rebuild_project(str(tmp_path))

        mock_indexer.build.assert_not_called()
        mock_indexer.save.assert_not_called()

    def test_mtime_tracking_with_matching_files(self, tmp_path):
        """os.walk finds a .py file → mtime is recorded."""
        py_file = tmp_path / "example.py"
        py_file.write_text("x = 1\n")

        fake_chunks = [MagicMock()]
        mock_indexer = _make_mock_indexer()

        with patch("luckyd_code.brain.chunk_project", return_value=fake_chunks), \
             patch("luckyd_code.brain.VectorIndexer", return_value=mock_indexer), \
             patch("luckyd_code.brain.parse_project", return_value=([], {})):
            from luckyd_code.brain import rebuild_project
            rebuild_project(str(tmp_path))

        # After the call, file_mtimes should have at least one entry
        assert isinstance(mock_indexer.file_mtimes, dict)

    def test_mtime_tracking_skips_non_source_files(self, tmp_path):
        """Files with extensions not in LANGUAGE_MAP are ignored."""
        txt_file = tmp_path / "notes.txt"
        txt_file.write_text("some notes")

        fake_chunks = [MagicMock()]
        mock_indexer = _make_mock_indexer()

        with patch("luckyd_code.brain.chunk_project", return_value=fake_chunks), \
             patch("luckyd_code.brain.VectorIndexer", return_value=mock_indexer), \
             patch("luckyd_code.brain.parse_project", return_value=([], {})):
            from luckyd_code.brain import rebuild_project
            rebuild_project(str(tmp_path))

        # .txt should not be tracked
        tracked = mock_indexer.file_mtimes
        assert not any(k.endswith(".txt") for k in tracked)

    def test_index_stats_missing_keys_default_to_zero(self, tmp_path):
        """If indexer.build() returns a partial stats dict, defaults apply."""
        fake_chunks = [MagicMock()]
        mock_indexer = _make_mock_indexer({})  # empty stats

        with patch("luckyd_code.brain.chunk_project", return_value=fake_chunks), \
             patch("luckyd_code.brain.VectorIndexer", return_value=mock_indexer), \
             patch("luckyd_code.brain.parse_project", return_value=([], {})), \
             patch("os.walk", return_value=[]):
            from luckyd_code.brain import rebuild_project
            result = rebuild_project(str(tmp_path))

        assert result["chunks"] == 0
        assert result["files"] == 0
        assert result["languages"] == {}


# ────────────────────────────────────────────────────────────────────────────
# rebuild_project: knowledge graph path (parsed present)
# ────────────────────────────────────────────────────────────────────────────

class TestRebuildProjectKnowledgeGraph:
    def test_builds_graph_when_parsed_present(self, tmp_path):
        fake_parsed = [MagicMock()]
        mock_graph = _make_mock_graph(node_count=7, files_parsed=4)

        with patch("luckyd_code.brain.chunk_project", return_value=[]), \
             patch("luckyd_code.brain.parse_project", return_value=(fake_parsed, {})), \
             patch("luckyd_code.brain.KnowledgeGraph", return_value=mock_graph):
            from luckyd_code.brain import rebuild_project
            result = rebuild_project(str(tmp_path))

        mock_graph.build.assert_called_once()
        mock_graph.save.assert_called_once()
        assert result["node_count"] == 7
        assert result["files_parsed"] == 4

    def test_skips_graph_when_no_parsed(self, tmp_path):
        mock_graph = _make_mock_graph()

        with patch("luckyd_code.brain.chunk_project", return_value=[]), \
             patch("luckyd_code.brain.parse_project", return_value=([], {})), \
             patch("luckyd_code.brain.KnowledgeGraph", return_value=mock_graph):
            from luckyd_code.brain import rebuild_project
            rebuild_project(str(tmp_path))

        mock_graph.build.assert_not_called()
        mock_graph.save.assert_not_called()

    def test_both_index_and_graph_built(self, tmp_path):
        """Verifies both indexer and graph are called when both have data."""
        fake_chunks = [MagicMock()]
        fake_parsed = [MagicMock()]
        mock_indexer = _make_mock_indexer()
        mock_graph = _make_mock_graph()

        with patch("luckyd_code.brain.chunk_project", return_value=fake_chunks), \
             patch("luckyd_code.brain.VectorIndexer", return_value=mock_indexer), \
             patch("luckyd_code.brain.parse_project", return_value=(fake_parsed, {})), \
             patch("luckyd_code.brain.KnowledgeGraph", return_value=mock_graph), \
             patch("os.walk", return_value=[]):
            from luckyd_code.brain import rebuild_project
            result = rebuild_project(str(tmp_path))

        mock_indexer.save.assert_called_once()
        mock_graph.save.assert_called_once()
        assert isinstance(result, dict)
