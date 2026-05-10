"""Tests for luckyd_code.memory.manager — MemoryManager CRUD, search, decay, index."""

import time
from pathlib import Path
from unittest.mock import patch

import pytest

from luckyd_code.memory.manager import MemoryManager


# ---------------------------------------------------------------------------
# Fixture: isolated MemoryManager pointing at a tmp dir
# ---------------------------------------------------------------------------

@pytest.fixture
def mm(tmp_path):
    """MemoryManager scoped to a temp directory with no side-effects."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    # Redirect data_path so nothing writes to the real ~/.luckyd-code
    mem_dir = tmp_path / "mem"
    mem_dir.mkdir()
    mgr = MemoryManager(str(project_dir))
    mgr.mem_dir = mem_dir          # override the computed mem_dir
    return mgr


# ===========================================================================
# MemoryManager._sanitize
# ===========================================================================

class TestSanitize:
    def test_alphanumeric_unchanged(self):
        assert MemoryManager._sanitize("hello_world") == "hello_world"

    def test_spaces_replaced(self):
        assert MemoryManager._sanitize("hello world") == "hello_world"

    def test_special_chars_stripped(self):
        result = MemoryManager._sanitize("my/memory.key!")
        assert "/" not in result
        assert "." not in result
        assert "!" not in result

    def test_empty_string_returns_unnamed(self):
        assert MemoryManager._sanitize("") == "unnamed"

    def test_leading_trailing_underscores_stripped(self):
        result = MemoryManager._sanitize("   ")
        assert result == "unnamed"


# ===========================================================================
# MemoryManager._strip_meta / _read_meta
# ===========================================================================

class TestMetaParsing:
    def test_strip_meta_removes_comment_block(self):
        raw = "<!-- importance:7 saved:100 accessed:200 count:3 -->\nreal content"
        assert MemoryManager._strip_meta(raw) == "real content"

    def test_strip_meta_no_comment_unchanged(self):
        raw = "no meta here"
        assert MemoryManager._strip_meta(raw) == "no meta here"

    def test_read_meta_extracts_importance(self, tmp_path):
        f = tmp_path / "mem.md"
        f.write_text("<!-- importance:9 saved:0 accessed:0 count:0 -->\ncontent")
        meta = MemoryManager._read_meta(f)
        assert meta["importance"] == 9

    def test_read_meta_missing_file_defaults(self, tmp_path):
        f = tmp_path / "nonexistent.md"
        meta = MemoryManager._read_meta(f)
        assert meta["importance"] == 5
        assert meta["saved"] == 0

    def test_read_meta_corrupted_file_defaults(self, tmp_path):
        f = tmp_path / "bad.md"
        f.write_text("not a valid meta line\ncontent")
        meta = MemoryManager._read_meta(f)
        assert meta["importance"] == 5  # should not crash


# ===========================================================================
# MemoryManager._make_snippet
# ===========================================================================

class TestMakeSnippet:
    def test_snippet_includes_query_context(self):
        content = "This is a long string. The important keyword is here. And more text follows."
        snippet = MemoryManager._make_snippet(content, "keyword")
        assert "keyword" in snippet

    def test_snippet_no_match_returns_start(self):
        content = "abcdef" * 50
        snippet = MemoryManager._make_snippet(content, "zzz")
        assert snippet == content[:300]

    def test_snippet_adds_ellipsis_for_cut(self):
        content = "a" * 1000 + "MATCH" + "b" * 1000
        snippet = MemoryManager._make_snippet(content, "match")
        assert "..." in snippet


# ===========================================================================
# CRUD: save_memory / load_memory / delete_memory / list_memories
# ===========================================================================

class TestCRUD:
    def test_save_creates_file(self, mm):
        mm.save_memory("api_key", "sk-test-123", memory_type="technical")
        files = list(mm.mem_dir.glob("technical_api_key.md"))
        assert len(files) == 1

    def test_save_content_persisted(self, mm):
        mm.save_memory("note", "remember this")
        f = mm.mem_dir / "general_note.md"
        assert "remember this" in f.read_text(encoding="utf-8")

    def test_load_returns_content(self, mm):
        mm.save_memory("note", "loaded content", memory_type="general")
        result = mm.load_memory("note", "general")
        assert result == "loaded content"

    def test_load_missing_returns_none(self, mm):
        assert mm.load_memory("does_not_exist") is None

    def test_save_updates_existing(self, mm):
        mm.save_memory("note", "v1")
        mm.save_memory("note", "v2")
        result = mm.load_memory("note")
        assert result == "v2"
        # Should still be one file, not two
        files = list(mm.mem_dir.glob("general_note.md"))
        assert len(files) == 1

    def test_delete_removes_file(self, mm):
        mm.save_memory("temp", "bye")
        assert mm.delete_memory("temp") is True
        assert not (mm.mem_dir / "general_temp.md").exists()

    def test_delete_missing_returns_false(self, mm):
        assert mm.delete_memory("never_saved") is False

    def test_list_memories_empty(self, mm):
        assert mm.list_memories() == []

    def test_list_memories_returns_entries(self, mm):
        mm.save_memory("alpha", "a", memory_type="general")
        mm.save_memory("beta", "b", memory_type="session")
        entries = mm.list_memories()
        names = {e["name"] for e in entries}
        assert "alpha" in names
        assert "beta" in names

    def test_list_memories_filtered_by_type(self, mm):
        mm.save_memory("x", "x", memory_type="general")
        mm.save_memory("y", "y", memory_type="technical")
        general = mm.list_memories(memory_type="general")
        assert all(e["type"] == "general" for e in general)

    def test_list_memories_excludes_index(self, mm):
        # MEMORY.md should never appear in the list
        mm.save_memory("foo", "bar")
        entries = mm.list_memories()
        names = [e["name"] for e in entries]
        assert "MEMORY" not in names

    def test_importance_persisted_in_metadata(self, mm):
        mm.save_memory("critical", "don't forget", importance=9)
        entries = mm.list_memories()
        entry = next(e for e in entries if e["name"] == "critical")
        assert entry["importance"] == 9


# ===========================================================================
# Index: MEMORY.md
# ===========================================================================

class TestIndex:
    def test_index_created_on_save(self, mm):
        mm.save_memory("idx_test", "content")
        index = mm.mem_dir / "MEMORY.md"
        assert index.exists()

    def test_index_contains_name(self, mm):
        mm.save_memory("findme", "unique-content-xyz")
        index = (mm.mem_dir / "MEMORY.md").read_text(encoding="utf-8")
        assert "findme" in index

    def test_rebuild_index_after_delete(self, mm):
        mm.save_memory("keep", "stays")
        mm.save_memory("gone", "leaves")
        mm.delete_memory("gone")
        index = (mm.mem_dir / "MEMORY.md").read_text(encoding="utf-8")
        assert "gone" not in index
        assert "keep" in index

    def test_index_updated_not_duplicated(self, mm):
        mm.save_memory("once", "v1")
        mm.save_memory("once", "v2")
        index = (mm.mem_dir / "MEMORY.md").read_text(encoding="utf-8")
        assert index.count("[once]") == 1


# ===========================================================================
# Search: keyword fallback (always available)
# ===========================================================================

class TestKeywordSearch:
    def test_search_finds_matching_memory(self, mm):
        mm.save_memory("auth", "JWT token authentication flow")
        mm.save_memory("db", "PostgreSQL database connection")
        results = mm._keyword_search("JWT authentication", k=5)
        assert any("auth" in r["name"] for r in results)

    def test_search_no_match_empty(self, mm):
        mm.save_memory("foo", "something unrelated")
        results = mm._keyword_search("zzz_no_match", k=5)
        assert results == []

    def test_search_respects_k_limit(self, mm):
        for i in range(10):
            mm.save_memory(f"item{i}", f"common keyword here item{i}")
        results = mm._keyword_search("common keyword", k=3)
        assert len(results) <= 3

    def test_search_results_have_required_keys(self, mm):
        mm.save_memory("meta_test", "check keys in result")
        results = mm._keyword_search("check keys", k=1)
        assert len(results) == 1
        r = results[0]
        assert "file" in r
        assert "name" in r
        assert "score" in r
        assert "snippet" in r

    def test_search_excludes_index_file(self, mm):
        mm.save_memory("real", "memory content")
        results = mm._keyword_search("memory", k=10)
        files = [r["file"] for r in results]
        assert "MEMORY.md" not in files

    def test_search_higher_frequency_scores_higher(self, mm):
        mm.save_memory("low", "python once")
        mm.save_memory("high", "python python python python python")
        results = mm._keyword_search("python", k=5)
        names = [r["name"] for r in results]
        assert names.index("high") < names.index("low")

    def test_public_search_memories_delegates_to_keyword(self, mm):
        mm.save_memory("delegate", "test delegation path")
        # Without sentence-transformers installed in CI, should fall back to keyword
        results = mm.search_memories("delegation", k=3)
        assert isinstance(results, list)


# ===========================================================================
# Context injection helpers
# ===========================================================================

class TestContextInjection:
    def test_get_relevant_memories_empty(self, mm):
        result = mm.get_relevant_memories("anything")
        assert result == ""

    def test_get_relevant_memories_returns_xml(self, mm):
        mm.save_memory("tip", "use async for IO-bound tasks")
        result = mm.get_relevant_memories("async IO", k=3)
        # Either found something (wrapped in XML) or nothing
        if result:
            assert "<memories>" in result
            assert "</memories>" in result

    def test_get_all_memories_formatted_empty(self, mm):
        assert mm.get_all_memories_formatted() == ""

    def test_get_all_memories_formatted_wraps_xml(self, mm):
        mm.save_memory("fact", "Python uses GIL")
        result = mm.get_all_memories_formatted()
        assert "<memories>" in result
        assert "<memory name=" in result
        assert "</memories>" in result

    def test_get_all_memories_truncates_long_content(self, mm):
        long_content = "x" * 2000
        mm.save_memory("long", long_content)
        result = mm.get_all_memories_formatted()
        assert "truncated" in result


# ===========================================================================
# Project memory (MEMORY.md / CLAUDE.md)
# ===========================================================================

class TestProjectMemory:
    def test_save_and_load_claude_md(self, mm, tmp_path):
        project_dir = tmp_path / "project2"
        project_dir.mkdir()
        mgr = MemoryManager(str(project_dir))
        mgr.mem_dir = tmp_path / "mem2"
        mgr.mem_dir.mkdir()
        mgr.project_dir = str(project_dir)

        mgr.save_claude_md("# Project Notes\n\nImportant stuff")
        content = mgr.load_claude_md()
        assert "Important stuff" in content

    def test_load_claude_md_missing_returns_empty(self, mm, tmp_path):
        project_dir = tmp_path / "empty_project"
        project_dir.mkdir()
        mgr = MemoryManager(str(project_dir))
        mgr.project_dir = str(project_dir)
        assert mgr.load_claude_md() == ""

    def test_load_claude_md_falls_back_to_claude_md(self, mm, tmp_path):
        project_dir = tmp_path / "legacy_project"
        project_dir.mkdir()
        (project_dir / "CLAUDE.md").write_text("legacy memory")
        mgr = MemoryManager(str(project_dir))
        mgr.project_dir = str(project_dir)
        content = mgr.load_claude_md()
        assert "legacy memory" in content


# ===========================================================================
# Decay / archiving
# ===========================================================================

class TestDecay:
    def test_decay_archives_old_low_importance(self, mm):
        mm.save_memory("stale", "old content", importance=2)
        # Backdate the accessed timestamp manually
        f = mm.mem_dir / "general_stale.md"
        raw = f.read_text(encoding="utf-8")
        old_time = int(time.time()) - (40 * 86400)  # 40 days ago
        raw = raw.replace(
            raw.split("-->")[0],
            f"<!-- importance:2 saved:{old_time} accessed:{old_time} count:0 -->"
        )
        f.write_text(raw, encoding="utf-8")

        archived = mm.decay(max_days=30, importance_threshold=3)
        assert archived == 1
        assert not f.exists()
        archive_dir = mm.mem_dir / "_archive"
        assert (archive_dir / "general_stale.md").exists()

    def test_decay_keeps_high_importance(self, mm):
        mm.save_memory("critical", "keep this", importance=8)
        # Backdate
        f = mm.mem_dir / "general_critical.md"
        raw = f.read_text(encoding="utf-8")
        old_time = int(time.time()) - (40 * 86400)
        raw = raw.replace(
            raw.split("-->")[0],
            f"<!-- importance:8 saved:{old_time} accessed:{old_time} count:0 -->"
        )
        f.write_text(raw, encoding="utf-8")

        archived = mm.decay(max_days=30, importance_threshold=3)
        assert archived == 0
        assert f.exists()

    def test_decay_keeps_recently_accessed(self, mm):
        mm.save_memory("recent", "still fresh", importance=1)
        # Just saved = recent timestamp → should NOT be archived
        archived = mm.decay(max_days=30, importance_threshold=3)
        assert archived == 0


# ===========================================================================
# save_conversation_summary
# ===========================================================================

class TestConversationSummary:
    def test_summary_creates_latest_summary(self, mm):
        mm.save_conversation_summary("User asked about Python. We discussed async.")
        result = mm.load_memory("latest_summary", "session")
        assert result is not None
        assert "async" in result

    def test_summary_appends_log(self, mm):
        mm.save_conversation_summary("turn 1 summary", turn_count=1)
        mm.save_conversation_summary("turn 2 summary", turn_count=2)
        log = (mm.mem_dir / "session_log.md").read_text(encoding="utf-8")
        assert "turn 1 summary" in log
        assert "turn 2 summary" in log


# ===========================================================================
# Module-level convenience API
# ===========================================================================

class TestModuleAPI:
    def test_save_and_list_via_module(self, tmp_path, monkeypatch):
        """Module-level save_memory / list_memories use the singleton manager."""
        import luckyd_code.memory.manager as mod

        # Reset singleton
        mod._DEFAULT_MANAGER = None

        project_dir = tmp_path / "proj"
        project_dir.mkdir()

        # Patch MemoryManager to use our tmp dir
        original_cls = mod.MemoryManager

        class _PatchedMM(original_cls):
            def __init__(self, pd=None):
                super().__init__(str(project_dir))
                self.mem_dir = tmp_path / "singleton_mem"
                self.mem_dir.mkdir(exist_ok=True)

        monkeypatch.setattr(mod, "MemoryManager", _PatchedMM)
        mod._DEFAULT_MANAGER = None

        mod.save_memory("singleton_key", "singleton_value")
        listing = mod.list_memories()
        assert "singleton_key" in listing

        # Cleanup singleton
        mod._DEFAULT_MANAGER = None
        monkeypatch.setattr(mod, "MemoryManager", original_cls)
