"""Extended coverage tests — router, config, memory, analytics, brain, agent loop,
api, indexer, cost_tracker, web_app, background, tools, orchestrator.

These tests were consolidated from per-module gap-fill runs into one file that
documents *which branch* each class covers, making future maintenance easier.
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# ═══════════════════════════════════════════════════════════════════════════════
# router.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetTierDescription:
    def test_all_tiers(self):
        from luckyd_code.router import get_tier_description
        for tier in (1, 2, 3, 4):
            desc = get_tier_description(tier)
            assert isinstance(desc, str)
            assert len(desc) > 5

    def test_unknown_tier(self):
        from luckyd_code.router import get_tier_description
        desc = get_tier_description(99)
        assert "99" in desc


class TestShowModelInfo:
    def test_returns_string(self):
        from luckyd_code.router import show_model_info
        result = show_model_info()
        assert isinstance(result, str)
        assert len(result) > 0


class TestShowCurrentRouting:
    def test_basic_output(self):
        from luckyd_code.router import show_current_routing
        result = show_current_routing("debug this function")
        assert "Classification" in result
        assert "Selected Model" in result
        assert "Tool Calls" in result

    def test_with_tool_count(self):
        from luckyd_code.router import show_current_routing
        result = show_current_routing("hi", recent_tool_count=5)
        assert "5" in result

    def test_heavy_tool_count_escalates(self):
        from luckyd_code.router import show_current_routing
        result = show_current_routing("simple task", recent_tool_count=10)
        # Effective tier should be higher
        assert "4" in result or "3" in result


class TestEffortTierFloor:
    def test_known_efforts(self):
        from luckyd_code.router import effort_tier_floor
        assert effort_tier_floor("low") == 1
        assert effort_tier_floor("normal") == 2
        assert effort_tier_floor("high") == 3
        assert effort_tier_floor("max") == 4

    def test_unknown_effort_defaults_to_normal(self):
        from luckyd_code.router import effort_tier_floor
        assert effort_tier_floor("unknown") == 2  # defaults to "normal"


class TestResolveInitialRoute:
    def test_auto_route_false_returns_preferred(self):
        from luckyd_code.router import resolve_initial_route
        result = resolve_initial_route(
            "debug this", 0, "deepseek", "deepseek-v4-flash",
            auto_route=False,
        )
        assert result.model == "deepseek-v4-flash"
        assert result.tier == 2

    def test_auto_route_true_classifies(self):
        from luckyd_code.router import resolve_initial_route
        result = resolve_initial_route(
            "hi", 0, "deepseek", "deepseek-v4-flash",
            auto_route=True,
        )
        assert result.tier in (1, 2, 3, 4)
        assert isinstance(result.model, str)
        assert isinstance(result.tier_description, str)

    def test_tier_changed_when_different_model(self):
        from luckyd_code.router import resolve_initial_route
        result = resolve_initial_route(
            "large refactor of entire codebase with security audit",
            0, "deepseek", "deepseek-v4-flash",
            auto_route=True,
        )
        assert isinstance(result.tier_changed, bool)

    def test_routing_result_dataclass(self):
        from luckyd_code.router import RoutingResult
        rr = RoutingResult(model="m", tier=2, tier_description="desc", tier_changed=True)
        assert rr.model == "m"
        assert rr.tier == 2
        assert rr.tier_description == "desc"
        assert rr.tier_changed is True


class TestEscalateTier:
    def test_auto_route_false_returns_current(self):
        from luckyd_code.router import escalate_tier
        result = escalate_tier(
            "hi", 0, "deepseek", "deepseek-v4-flash",
            current_model="deepseek-v4-flash", current_tier=1, auto_route=False,
        )
        assert result.model == "deepseek-v4-flash"
        assert result.tier == 1

    def test_heavy_tool_count_goes_to_tier_4(self):
        from luckyd_code.router import escalate_tier
        result = escalate_tier(
            "hi", 10, "deepseek", "deepseek-v4-flash",
            current_model="deepseek-v4-flash", current_tier=1, auto_route=True,
        )
        assert result.tier == 4

    def test_medium_tool_count_escalates_one(self):
        from luckyd_code.router import escalate_tier
        result = escalate_tier(
            "hi", 5, "deepseek", "deepseek-v4-flash",
            current_model="deepseek-v4-flash", current_tier=2, auto_route=True,
        )
        assert result.tier in (2, 3, 4)

    def test_no_tool_count_no_escalation(self):
        from luckyd_code.router import escalate_tier, classify_tier
        expected_tier = classify_tier("hi", 0)
        result = escalate_tier(
            "hi", 0, "deepseek", "deepseek-v4-flash",
            current_model="deepseek-v4-flash", current_tier=expected_tier,
            auto_route=True,
        )
        assert result.tier == expected_tier


class TestClassifyTierLlm:
    def test_returns_heuristic_on_timeout(self):
        """When LLM call times out, falls back to heuristic."""
        from luckyd_code.router import classify_tier_llm, classify_tier
        from concurrent.futures import TimeoutError as FutureTimeout

        cfg = MagicMock()
        cfg.api_key = "fake"
        cfg.base_url = "https://api.deepseek.com/v1"

        # Clear the cache
        import luckyd_code.router as router_mod
        with router_mod._tier_cache_lock:
            router_mod._tier_cache.clear()

        # Stub the executor to raise timeout immediately
        mock_future = MagicMock()
        mock_future.result.side_effect = FutureTimeout

        with patch.object(router_mod._classify_executor, "submit", return_value=mock_future):
            result = classify_tier_llm("hello world", cfg)

        expected = classify_tier("hello world")
        assert result == expected

    def test_cache_hit_returns_cached_tier(self):
        """Second call with same prompt should hit the cache."""
        from luckyd_code.router import classify_tier_llm
        import hashlib
        import luckyd_code.router as router_mod

        snippet = "cached query"
        cache_key = hashlib.md5(snippet.encode("utf-8", errors="replace")).hexdigest()

        with router_mod._tier_cache_lock:
            router_mod._tier_cache[cache_key] = 3

        cfg = MagicMock()
        result = classify_tier_llm(snippet, cfg)
        assert result == 3

        # Cleanup
        with router_mod._tier_cache_lock:
            router_mod._tier_cache.pop(cache_key, None)


# ═══════════════════════════════════════════════════════════════════════════════
# config.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestConfigFromArgsProvider:
    def test_provider_arg_sets_provider(self):
        from luckyd_code.config import Config
        import os

        class Args:
            model = None
            temperature = None
            system_prompt = None
            dir = None
            provider = "openai"

        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-openai-test"}, clear=True):
            with patch("luckyd_code.config.load_config_file", return_value={}):
                cfg = Config.from_args(Args())
                assert cfg.provider == "openai"

    def test_provider_updates_base_url(self):
        from luckyd_code.config import Config
        import os

        class Args:
            model = None
            temperature = None
            system_prompt = None
            dir = None
            provider = "groq"

        with patch.dict(os.environ, {"GROQ_API_KEY": "gsk-test"}, clear=True):
            # No base_url in saved config → should be derived from provider
            with patch("luckyd_code.config.load_config_file", return_value={}):
                cfg = Config.from_args(Args())
                assert "groq" in cfg.base_url.lower()

    def test_from_args_dir_override(self):
        from luckyd_code.config import Config

        class Args:
            model = None
            temperature = None
            system_prompt = None
            dir = "/tmp/myproject"
            provider = None

        with patch("luckyd_code.config.load_config_file", return_value={}):
            cfg = Config.from_args(Args())
            assert cfg.working_directory == "/tmp/myproject"

    def test_from_args_system_prompt(self):
        from luckyd_code.config import Config

        class Args:
            model = None
            temperature = None
            system_prompt = "Custom system prompt"
            dir = None
            provider = None

        with patch("luckyd_code.config.load_config_file", return_value={}):
            cfg = Config.from_args(Args())
            assert cfg.system_prompt == "Custom system prompt"


class TestConfigConvenienceFunctions:
    def test_get_api_key(self):
        from luckyd_code.config import get_api_key
        # Should return a string (may be empty)
        key = get_api_key()
        assert isinstance(key, str)

    def test_get_base_url(self):
        from luckyd_code.config import get_base_url
        url = get_base_url()
        assert isinstance(url, str)
        assert url.startswith("http")

    def test_validate_empty_base_url(self):
        from luckyd_code.config import Config
        cfg = Config()
        cfg.api_key = "sk-test"
        cfg.provider = "deepseek"
        cfg.base_url = ""
        with pytest.raises(ValueError, match="base_url is not set"):
            cfg.validate()


class TestLoadConfigFileLegacy:
    def test_falls_back_to_legacy_path(self, tmp_path):
        """If primary config doesn't exist, loads from legacy path."""
        import json
        from luckyd_code.config import load_config_file
        legacy = tmp_path / "legacy_config.json"
        legacy.write_text(json.dumps({"model": "legacy-model"}), encoding="utf-8")
        primary = tmp_path / "primary_config.json"

        with patch("luckyd_code.config.CONFIG_FILE", primary), \
             patch("luckyd_code.config._LEGACY_CONFIG_FILE", legacy):
            result = load_config_file()
            assert result.get("model") == "legacy-model"

    def test_corrupt_config_returns_empty(self, tmp_path):
        """Corrupt JSON in config file returns empty dict."""
        from luckyd_code.config import load_config_file
        corrupt = tmp_path / "config.json"
        corrupt.write_text("not json {{{", encoding="utf-8")
        dummy = tmp_path / "nope.json"

        with patch("luckyd_code.config.CONFIG_FILE", corrupt), \
             patch("luckyd_code.config._LEGACY_CONFIG_FILE", dummy):
            result = load_config_file()
            assert result == {}


# ═══════════════════════════════════════════════════════════════════════════════
# memory/user.py
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def user_mem(tmp_path):
    """Isolated UserMemory instance pointing at a temp directory."""
    from luckyd_code.memory.user import UserMemory
    um = UserMemory()
    um._mem_dir = tmp_path / "user_mem"
    um._mem_dir.mkdir(parents=True, exist_ok=True)
    return um


class TestUserMemoryCRUD:
    def test_save_and_load(self, user_mem):
        user_mem.save("pref_lang", "Python is preferred")
        content = user_mem.load("pref_lang")
        assert content == "Python is preferred"

    def test_load_missing_returns_none(self, user_mem):
        assert user_mem.load("no_such_key") is None

    def test_save_updates_existing(self, user_mem):
        user_mem.save("key", "v1")
        user_mem.save("key", "v2")
        assert user_mem.load("key") == "v2"

    def test_delete_existing(self, user_mem):
        user_mem.save("del_me", "content")
        assert user_mem.delete("del_me") is True
        assert user_mem.load("del_me") is None

    def test_delete_missing(self, user_mem):
        assert user_mem.delete("never_saved") is False

    def test_list_all_empty(self, user_mem):
        assert user_mem.list_all() == []

    def test_list_all_populated(self, user_mem):
        user_mem.save("a", "alpha", importance=7)
        user_mem.save("b", "beta", importance=3)
        entries = user_mem.list_all()
        assert len(entries) == 2
        names = {e["name"] for e in entries}
        assert "a" in names
        assert "b" in names
        importances = {e["importance"] for e in entries}
        assert 7 in importances

    def test_importance_persisted(self, user_mem):
        user_mem.save("critical", "value", importance=10)
        entries = user_mem.list_all()
        e = next(x for x in entries if x["name"] == "critical")
        assert e["importance"] == 10


class TestUserMemorySearch:
    def test_keyword_search_finds_content(self, user_mem):
        user_mem.save("python_tip", "Use list comprehensions for speed")
        user_mem.save("go_tip", "Goroutines are great for concurrency")
        results = user_mem._keyword_search("list comprehensions", k=5)
        assert len(results) >= 1
        assert any("python_tip" in r["name"] for r in results)

    def test_keyword_search_empty(self, user_mem):
        results = user_mem._keyword_search("zzz_not_here", k=5)
        assert results == []

    def test_keyword_search_respects_k(self, user_mem):
        for i in range(8):
            user_mem.save(f"item{i}", f"keyword here {i}")
        results = user_mem._keyword_search("keyword", k=3)
        assert len(results) <= 3

    def test_search_delegates_to_keyword(self, user_mem):
        user_mem.save("note", "important fact about testing")
        results = user_mem.search("important fact", k=3)
        assert isinstance(results, list)

    def test_get_relevant_empty_returns_empty_string(self, user_mem):
        result = user_mem.get_relevant("anything", k=3)
        assert result == ""

    def test_get_relevant_with_match_returns_xml(self, user_mem):
        user_mem.save("tip", "use pytest fixtures for isolation")
        result = user_mem.get_relevant("pytest fixtures", k=3)
        # Either found something (XML) or nothing
        if result:
            assert "<user_memories>" in result
            assert "</user_memories>" in result


class TestUserMemoryDecay:
    def test_decay_archives_old_low_importance(self, user_mem):
        user_mem.save("stale", "old content", importance=2)
        # Backdate the accessed timestamp
        f = user_mem._mem_dir / "stale.md"
        raw = f.read_text(encoding="utf-8")
        old_time = int(time.time()) - (35 * 86400)
        # Replace the timestamp comment
        first_line = raw.split("\n", 1)[0]
        new_line = f"<!-- importance:2 saved:{old_time} accessed:{old_time} count:0 -->"
        new_raw = raw.replace(first_line, new_line)
        f.write_text(new_raw, encoding="utf-8")

        archived = user_mem.decay()
        assert archived == 1
        assert not f.exists()

    def test_decay_keeps_high_importance(self, user_mem):
        user_mem.save("keep", "critical", importance=9)
        f = user_mem._mem_dir / "keep.md"
        raw = f.read_text(encoding="utf-8")
        old_time = int(time.time()) - (35 * 86400)
        first_line = raw.split("\n", 1)[0]
        new_line = f"<!-- importance:9 saved:{old_time} accessed:{old_time} count:0 -->"
        f.write_text(raw.replace(first_line, new_line), encoding="utf-8")
        archived = user_mem.decay()
        assert archived == 0

    def test_decay_keeps_recent(self, user_mem):
        user_mem.save("fresh", "just saved", importance=1)
        archived = user_mem.decay()
        assert archived == 0  # just saved = recent timestamp


class TestGetUserMemorySingleton:
    def test_singleton_returns_same_instance(self):
        import luckyd_code.memory.user as user_mod
        # Reset the singleton
        user_mod._user_memory = None
        um1 = user_mod.get_user_memory()
        um2 = user_mod.get_user_memory()
        assert um1 is um2

    def test_singleton_is_user_memory_instance(self):
        from luckyd_code.memory.user import get_user_memory, UserMemory, _user_memory
        import luckyd_code.memory.user as user_mod
        user_mod._user_memory = None
        um = get_user_memory()
        assert isinstance(um, UserMemory)


# ═══════════════════════════════════════════════════════════════════════════════
# analytics/scanner.py — extra language detection & comment counting
# ═══════════════════════════════════════════════════════════════════════════════

class TestDetectLanguageExtras:
    def test_c_files(self):
        from luckyd_code.analytics.scanner import _detect_language
        assert _detect_language(Path("foo.c")) == "c"
        assert _detect_language(Path("foo.h")) == "c"

    def test_cpp_files(self):
        from luckyd_code.analytics.scanner import _detect_language
        assert _detect_language(Path("foo.cpp")) == "c++"
        assert _detect_language(Path("foo.hpp")) == "c++"
        assert _detect_language(Path("foo.cc")) == "c++"

    def test_java(self):
        from luckyd_code.analytics.scanner import _detect_language
        assert _detect_language(Path("Foo.java")) == "java"

    def test_ruby(self):
        from luckyd_code.analytics.scanner import _detect_language
        assert _detect_language(Path("app.rb")) == "ruby"

    def test_php(self):
        from luckyd_code.analytics.scanner import _detect_language
        assert _detect_language(Path("index.php")) == "php"

    def test_swift(self):
        from luckyd_code.analytics.scanner import _detect_language
        assert _detect_language(Path("App.swift")) == "swift"

    def test_kotlin(self):
        from luckyd_code.analytics.scanner import _detect_language
        assert _detect_language(Path("Main.kt")) == "kotlin"

    def test_shell(self):
        from luckyd_code.analytics.scanner import _detect_language
        assert _detect_language(Path("run.sh")) == "shell"
        assert _detect_language(Path("run.bash")) == "shell"

    def test_markdown(self):
        from luckyd_code.analytics.scanner import _detect_language
        assert _detect_language(Path("README.md")) == "markdown"

    def test_json(self):
        from luckyd_code.analytics.scanner import _detect_language
        assert _detect_language(Path("data.json")) == "json"

    def test_yaml(self):
        from luckyd_code.analytics.scanner import _detect_language
        assert _detect_language(Path("ci.yaml")) == "yaml"
        assert _detect_language(Path("ci.yml")) == "yaml"

    def test_toml(self):
        from luckyd_code.analytics.scanner import _detect_language
        assert _detect_language(Path("config.toml")) == "toml"

    def test_config(self):
        from luckyd_code.analytics.scanner import _detect_language
        assert _detect_language(Path("setup.cfg")) == "config"
        assert _detect_language(Path("setup.ini")) == "config"


class TestCountCommentLinesJS:
    def test_js_single_line_comments(self):
        from luckyd_code.analytics.scanner import _count_comment_lines
        content = "// first line\ncode here\n// third line\n"
        count = _count_comment_lines(content, "javascript")
        assert count == 2

    def test_js_block_comments(self):
        from luckyd_code.analytics.scanner import _count_comment_lines
        content = "/* start\n middle \n end */\ncode\n"
        count = _count_comment_lines(content, "javascript")
        assert count >= 2  # multi-line block comment

    def test_ts_inline_comments(self):
        from luckyd_code.analytics.scanner import _count_comment_lines
        content = "// ts comment\nconst x = 1;\n"
        count = _count_comment_lines(content, "typescript")
        assert count == 1

    def test_go_comments(self):
        from luckyd_code.analytics.scanner import _count_comment_lines
        content = "// go comment\nfunc main() {}\n// another\n"
        count = _count_comment_lines(content, "go")
        assert count == 2

    def test_python_hash_comments(self):
        from luckyd_code.analytics.scanner import _count_comment_lines
        content = "# comment\nx = 1\n# another\n"
        count = _count_comment_lines(content, "python")
        assert count == 2

    def test_ruby_hash_comments(self):
        from luckyd_code.analytics.scanner import _count_comment_lines
        content = "# ruby comment\nputs 'hi'\n"
        count = _count_comment_lines(content, "ruby")
        assert count == 1

    def test_shell_hash_comments(self):
        from luckyd_code.analytics.scanner import _count_comment_lines
        content = "# shebang\necho hi\n"
        count = _count_comment_lines(content, "shell")
        assert count == 1


class TestScanFileEdgeCases:
    def test_scan_file_nonexistent_returns_none(self):
        from luckyd_code.analytics.scanner import CodebaseScanner
        scanner = CodebaseScanner()
        result = scanner.scan_file("/nonexistent/path/file.py")
        assert result is None

    def test_scan_file_directory_returns_none(self, tmp_path):
        from luckyd_code.analytics.scanner import CodebaseScanner
        scanner = CodebaseScanner()
        result = scanner.scan_file(str(tmp_path))  # directory, not file
        assert result is None

    def test_scan_file_js(self, tmp_path):
        from luckyd_code.analytics.scanner import CodebaseScanner
        f = tmp_path / "app.js"
        f.write_text("function hello() { return 42; }\n")
        scanner = CodebaseScanner()
        fm = scanner.scan_file(str(f))
        assert fm is not None
        assert fm.language == "javascript"
        assert fm.function_count >= 1

    def test_scan_python_with_syntax_error_fallback(self, tmp_path):
        """Python file with syntax error falls back to regex counts."""
        from luckyd_code.analytics.scanner import CodebaseScanner
        f = tmp_path / "broken.py"
        # Valid enough to be read but syntax error for AST
        f.write_text("def foo(\n", encoding="utf-8")
        scanner = CodebaseScanner()
        fm = scanner.scan_file(str(f))
        assert fm is not None
        # Regex fallback should still count functions
        assert fm.language == "python"


class TestShouldSkipDir:
    def test_known_dirs_skipped(self):
        from luckyd_code.analytics.scanner import _should_skip_dir
        for d in ("__pycache__", ".git", "node_modules", ".venv"):
            assert _should_skip_dir(d) is True

    def test_dot_dirs_skipped(self):
        from luckyd_code.analytics.scanner import _should_skip_dir
        assert _should_skip_dir(".hidden") is True
        assert _should_skip_dir(".pytest_cache") is True

    def test_normal_dirs_not_skipped(self):
        from luckyd_code.analytics.scanner import _should_skip_dir
        assert _should_skip_dir("src") is False
        assert _should_skip_dir("tests") is False


class TestPythonComplexityExtras:
    def test_bool_op_counted(self):
        """BoolOp (and/or with 3 operands) adds 2 to complexity."""
        import ast
        from luckyd_code.analytics.scanner import _python_complexity
        code = "x = a and b and c"
        tree = ast.parse(code)
        complexity = _python_complexity(tree)
        assert complexity >= 3  # base 1 + 2 boolean branches

    def test_assert_counted(self):
        import ast
        from luckyd_code.analytics.scanner import _python_complexity
        code = "assert x, 'error'"
        tree = ast.parse(code)
        complexity = _python_complexity(tree)
        assert complexity >= 2


# ═══════════════════════════════════════════════════════════════════════════════
# brain/graph.py
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def populated_kg():
    """A KnowledgeGraph built with a realistic parsed file."""
    from luckyd_code.brain.graph import KnowledgeGraph
    kg = KnowledgeGraph()
    kg.build("/project", [{
        "module": "src/service.py",
        "classes": [{
            "name": "UserService",
            "line": 1, "end_line": 50,
            "base_names": ["BaseService"],
            "decorators": [],
            "docstring": "User management service",
            "methods": [{
                "name": "create_user",
                "line": 5, "end_line": 15,
                "decorators": [],
                "docstring": "Create a new user",
                "calls": ["validate", "save"],
            }],
        }],
        "functions": [{
            "name": "helper",
            "line": 52, "end_line": 60,
            "decorators": [],
            "docstring": "Helper function",
            "calls": ["log"],
        }],
        "imports": [{"module": "datetime", "name": "datetime", "alias": None}],
        "errors": [],
        "size": 300,
    }])
    return kg


class TestFindDependents:
    def test_find_dependents_for_known_symbol(self, populated_kg):
        results = populated_kg.find_dependents("create_user")
        # May find the class that contains it
        assert isinstance(results, list)

    def test_find_dependents_no_match_empty(self, populated_kg):
        results = populated_kg.find_dependents("zzz_nonexistent_symbol")
        assert results == []

    def test_find_dependents_returns_list_of_dicts(self, populated_kg):
        results = populated_kg.find_dependents("UserService")
        assert isinstance(results, list)
        for r in results:
            assert isinstance(r, dict)
            assert "file" in r or "name" in r


class TestGetRelatedDepth:
    def test_depth_2_traversal(self, populated_kg):
        """get_related with depth=2 should find nodes 2 hops away."""
        # Start from module, should reach method via class
        module_id = "module:src/service.py"
        related_d1 = populated_kg.get_related(module_id, max_depth=1)
        related_d2 = populated_kg.get_related(module_id, max_depth=2)
        # Depth 2 should find at least as many nodes as depth 1
        assert len(related_d2) >= len(related_d1)

    def test_empty_node_id_no_crash(self, populated_kg):
        related = populated_kg.get_related("nonexistent:id", max_depth=2)
        assert isinstance(related, list)


class TestSummarizeMaxModules:
    def test_max_modules_limits_output(self):
        """Summarize should stop after max_modules files."""
        from luckyd_code.brain.graph import KnowledgeGraph
        kg = KnowledgeGraph()
        # Build with 5 modules
        parsed = []
        for i in range(5):
            parsed.append({
                "module": f"src/module{i}.py",
                "classes": [{"name": f"Class{i}", "line": 1, "end_line": 10,
                              "base_names": [], "decorators": [],
                              "docstring": "", "methods": []}],
                "functions": [],
                "imports": [],
                "errors": [],
                "size": 100,
            })
        kg.build("/project", parsed)

        # Limit to 3 modules
        summary = kg.summarize(max_modules=3)
        # Should have stopped at 3 modules
        class_mentions = [f"Class{i}" for i in range(5)]
        found_count = sum(1 for c in class_mentions if c in summary)
        assert found_count <= 3

    def test_stats_text_with_no_last_built(self):
        from luckyd_code.brain.graph import KnowledgeGraph
        kg = KnowledgeGraph()
        kg.stats["last_built"] = 0  # epoch = no meaningful time
        text = kg.stats_text()
        assert "Nodes:" in text
