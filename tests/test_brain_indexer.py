"""Tests for brain/indexer.py — VectorIndexer save/load/stats/get_changed_files."""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from luckyd_code.brain.indexer import VectorIndexer


SAMPLE_CHUNKS = [
    {
        "file_path": "app.py",
        "chunk_id": "app.py:function:foo",
        "start_line": 1,
        "end_line": 5,
        "type": "function",
        "name": "foo",
        "language": "python",
        "content": "def foo():\n    return 42\n",
    },
    {
        "file_path": "app.py",
        "chunk_id": "app.py:module",
        "start_line": 0,
        "end_line": 0,
        "type": "module",
        "name": "app.py",
        "language": "python",
        "content": '"""Module."""\n',
    },
]


class TestVectorIndexerSave:
    def test_save_creates_chunks_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("luckyd_code.brain.indexer.BRAIN_DIR", tmp_path)
        monkeypatch.setattr("luckyd_code.brain.indexer.CHUNKS_FILE", tmp_path / "chunks.json")
        monkeypatch.setattr("luckyd_code.brain.indexer.MTIMES_FILE", tmp_path / "mtimes.json")
        monkeypatch.setattr("luckyd_code.brain.indexer.STATS_FILE", tmp_path / "stats.json")
        monkeypatch.setattr("luckyd_code.brain.indexer.INDEX_FILE", tmp_path / "index.faiss")

        vi = VectorIndexer()
        vi.chunks = SAMPLE_CHUNKS
        result = vi.save()

        assert result is True
        assert (tmp_path / "chunks.json").exists()
        saved = json.loads((tmp_path / "chunks.json").read_text())
        assert len(saved) == 2

    def test_save_writes_mtimes(self, tmp_path, monkeypatch):
        monkeypatch.setattr("luckyd_code.brain.indexer.BRAIN_DIR", tmp_path)
        monkeypatch.setattr("luckyd_code.brain.indexer.CHUNKS_FILE", tmp_path / "chunks.json")
        monkeypatch.setattr("luckyd_code.brain.indexer.MTIMES_FILE", tmp_path / "mtimes.json")
        monkeypatch.setattr("luckyd_code.brain.indexer.STATS_FILE", tmp_path / "stats.json")
        monkeypatch.setattr("luckyd_code.brain.indexer.INDEX_FILE", tmp_path / "index.faiss")

        vi = VectorIndexer()
        vi.file_mtimes = {"app.py": (1234567890.0, 500)}
        vi.save()

        saved = json.loads((tmp_path / "mtimes.json").read_text())
        assert "app.py" in saved

    def test_save_writes_stats(self, tmp_path, monkeypatch):
        monkeypatch.setattr("luckyd_code.brain.indexer.BRAIN_DIR", tmp_path)
        monkeypatch.setattr("luckyd_code.brain.indexer.CHUNKS_FILE", tmp_path / "chunks.json")
        monkeypatch.setattr("luckyd_code.brain.indexer.MTIMES_FILE", tmp_path / "mtimes.json")
        monkeypatch.setattr("luckyd_code.brain.indexer.STATS_FILE", tmp_path / "stats.json")
        monkeypatch.setattr("luckyd_code.brain.indexer.INDEX_FILE", tmp_path / "index.faiss")

        vi = VectorIndexer()
        vi.stats["chunks"] = 42
        vi.save()

        saved = json.loads((tmp_path / "stats.json").read_text())
        assert saved["chunks"] == 42

    def test_save_returns_false_on_write_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr("luckyd_code.brain.indexer.BRAIN_DIR", tmp_path)
        monkeypatch.setattr("luckyd_code.brain.indexer.CHUNKS_FILE", tmp_path / "chunks.json")
        monkeypatch.setattr("luckyd_code.brain.indexer.MTIMES_FILE", tmp_path / "mtimes.json")
        monkeypatch.setattr("luckyd_code.brain.indexer.STATS_FILE", tmp_path / "stats.json")
        monkeypatch.setattr("luckyd_code.brain.indexer.INDEX_FILE", tmp_path / "index.faiss")

        vi = VectorIndexer()
        with patch.object(Path, "write_text", side_effect=OSError("disk full")):
            result = vi.save()
        assert result is False


class TestVectorIndexerStatsText:
    def test_basic_stats(self):
        vi = VectorIndexer()
        vi.stats = {
            "chunks": 100,
            "files": 10,
            "languages": {"python": 80, "javascript": 20},
            "last_indexed": time.time(),
            "dimension": 384,
            "index_size_bytes": 1024 * 512,
        }
        text = vi.stats_text()
        assert "100" in text
        assert "10" in text
        assert "python" in text
        assert "384" in text

    def test_shows_kb_for_small_index(self):
        vi = VectorIndexer()
        vi.stats["index_size_bytes"] = 500 * 1024  # 500 KB
        text = vi.stats_text()
        assert "KB" in text

    def test_shows_mb_for_large_index(self):
        vi = VectorIndexer()
        vi.stats["index_size_bytes"] = 2 * 1024 * 1024  # 2 MB
        text = vi.stats_text()
        assert "MB" in text

    def test_shows_bytes_for_tiny_index(self):
        vi = VectorIndexer()
        vi.stats["index_size_bytes"] = 512
        text = vi.stats_text()
        assert "B" in text

    def test_shows_faiss_unavailable_message(self):
        vi = VectorIndexer()
        vi._faiss_available = False
        text = vi.stats_text()
        assert "faiss" in text.lower() or "FAISS" in text

    def test_shows_last_indexed(self):
        vi = VectorIndexer()
        vi.stats["last_indexed"] = time.time()
        text = vi.stats_text()
        assert "Last indexed" in text

    def test_no_last_indexed_omitted(self):
        vi = VectorIndexer()
        vi.stats["last_indexed"] = 0
        text = vi.stats_text()
        assert "Last indexed" not in text

    def test_no_dimension_omitted(self):
        vi = VectorIndexer()
        vi.stats["dimension"] = 0
        text = vi.stats_text()
        assert "dimension" not in text.lower()


class TestVectorIndexerGetChangedFiles:
    def test_new_file_is_reported(self, tmp_path):
        (tmp_path / "new.py").write_text("def foo(): pass")
        vi = VectorIndexer()
        changed = vi.get_changed_files(str(tmp_path))
        assert any("new.py" in p for p in changed)

    def test_unchanged_file_not_reported(self, tmp_path):
        f = tmp_path / "stable.py"
        f.write_text("def foo(): pass")
        st = f.stat()
        vi = VectorIndexer()
        vi.file_mtimes[str(f)] = (st.st_mtime, st.st_size)
        changed = vi.get_changed_files(str(tmp_path))
        assert not any("stable.py" in p for p in changed)

    def test_modified_file_is_reported(self, tmp_path):
        f = tmp_path / "mod.py"
        f.write_text("def foo(): pass")
        vi = VectorIndexer()
        # Store wrong mtime to simulate modification
        vi.file_mtimes[str(f)] = (0.0, 0)
        changed = vi.get_changed_files(str(tmp_path))
        assert any("mod.py" in p for p in changed)

    def test_skips_non_source_files(self, tmp_path):
        (tmp_path / "image.png").write_bytes(b"\x89PNG")
        vi = VectorIndexer()
        changed = vi.get_changed_files(str(tmp_path))
        assert all(".png" not in p for p in changed)

    def test_skips_ignored_dirs(self, tmp_path):
        cache = tmp_path / "__pycache__"
        cache.mkdir()
        (cache / "cached.py").write_text("x=1")
        vi = VectorIndexer()
        changed = vi.get_changed_files(str(tmp_path))
        assert not any("__pycache__" in p for p in changed)


class TestVectorIndexerIsAvailable:
    def test_not_available_by_default(self):
        vi = VectorIndexer()
        assert vi.is_available is False

    def test_not_available_when_no_index(self):
        vi = VectorIndexer()
        vi._faiss_available = True
        vi.index = None
        assert vi.is_available is False

    def test_available_when_index_has_entries(self):
        vi = VectorIndexer()
        vi._faiss_available = True
        mock_index = MagicMock()
        mock_index.ntotal = 10
        vi.index = mock_index
        assert vi.is_available is True

    def test_not_available_when_empty_index(self):
        vi = VectorIndexer()
        vi._faiss_available = True
        mock_index = MagicMock()
        mock_index.ntotal = 0
        vi.index = mock_index
        assert vi.is_available is False
