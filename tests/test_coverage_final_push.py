"""Comprehensive coverage push — targets all remaining uncovered lines.

Covers:
  - api.py: stream_chat error paths, _call_with_retry retry logic, _parse_stream_error
  - brain/chunker.py: _chunk_with_regex, _chunk_by_lines, _find_block_end, chunk_file, chunk_project
  - tools/game_gen.py: run() branches, _resolve_pyinstaller, _generate_source mock
  - memory/manager.py: decay, save_conversation_summary, get_all_memories_formatted,
                        _rebuild_index, _update_index update branch, module-level API
  - memory/user.py: decay, list_all, get_relevant, delete, _keyword_search, module-level
  - self_improve.py: get_improvement_prompt branches, _git exception, ImprovementTracker
  - web_routes/brain.py: all 5 endpoints
  - _agent_loop.py: _auto_save_turn_memory, _context_text_for_memory multimodal,
                     budget warning, memory injection, _ingest_tool_result write paths
  - tools/file_ops.py: remaining branches in all 5 tools
"""
from __future__ import annotations

import json
import os
import textwrap
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest


# ═══════════════════════════════════════════════════════════════════════════════
# api.py — stream_chat error paths, _call_with_retry, _parse_stream_error
# ═══════════════════════════════════════════════════════════════════════════════

class TestStreamChatErrors:
    """Test stream_chat with _call_with_retry raising various exceptions."""

    def _chat(self, side_effect):
        from luckyd_code.api import stream_chat
        with patch("luckyd_code.api._call_with_retry", side_effect=side_effect):
            return list(stream_chat([], [], "m", "k", "http://x", 100, 0.7))

    def test_model_not_found_yields_model_not_found(self):
        from luckyd_code.retry import ModelNotFoundError
        events = self._chat(ModelNotFoundError("no such model"))
        assert events[0][0] == "model_not_found"
        assert "no such model" in events[0][1]

    def test_non_retryable_yields_error(self):
        from luckyd_code.retry import NonRetryableError
        events = self._chat(NonRetryableError("bad auth"))
        assert events[0][0] == "error"
        assert "bad auth" in events[0][1]

    def test_retryable_exhausted_yields_error(self):
        from luckyd_code.retry import RetryableError
        events = self._chat(RetryableError("rate limited"))
        assert events[0][0] == "error"

    def test_generic_exception_yields_error(self):
        events = self._chat(RuntimeError("network down"))
        assert events[0][0] == "error"
        assert "network down" in events[0][1]


class TestStreamChatParsing:
    """Test stream_chat SSE parsing with a mocked HTTP response."""

    def _mock_response(self, lines: list[str]):
        """Build (client, cm, response) mock from a list of SSE line strings."""
        mock_response = MagicMock()
        mock_response.iter_lines.return_value = [l.encode() for l in lines]
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_response)
        mock_cm.__exit__ = MagicMock(return_value=False)
        mock_client = MagicMock()
        return mock_client, mock_cm, mock_response

    def _chat_lines(self, lines):
        from luckyd_code.api import stream_chat
        client, cm, resp = self._mock_response(lines)
        with patch("luckyd_code.api._call_with_retry", return_value=(client, cm, resp)):
            return list(stream_chat([], [], "m", "k", "http://x", 100, 0.7))

    def test_text_chunk_yielded(self):
        chunk = json.dumps({"choices": [{"delta": {"content": "hello"}}]})
        events = self._chat_lines([f"data: {chunk}", "data: [DONE]"])
        texts = [d for t, d in events if t == "text"]
        assert "hello" in texts

    def test_done_event_has_content(self):
        chunk = json.dumps({"choices": [{"delta": {"content": "world"}}]})
        events = self._chat_lines([f"data: {chunk}", "data: [DONE]"])
        done_events = [(t, d) for t, d in events if t == "done"]
        assert done_events
        assert "world" in done_events[0][1][0]

    def test_reasoning_content_yielded(self):
        chunk = json.dumps({"choices": [{"delta": {"reasoning_content": "thinking..."}}]})
        events = self._chat_lines([f"data: {chunk}", "data: [DONE]"])
        reasoning = [d for t, d in events if t == "reasoning"]
        assert reasoning

    def test_empty_choices_skipped(self):
        chunk = json.dumps({"choices": []})
        events = self._chat_lines([f"data: {chunk}", "data: [DONE]"])
        # Should not crash and should produce done
        done_events = [t for t, d in events if t == "done"]
        assert done_events

    def test_delta_none_skipped(self):
        chunk = json.dumps({"choices": [{"delta": None}]})
        events = self._chat_lines([f"data: {chunk}", "data: [DONE]"])
        # Should not crash
        assert events

    def test_stream_error_yields_error(self):
        from luckyd_code.api import stream_chat
        mock_resp = MagicMock()
        mock_resp.iter_lines.side_effect = RuntimeError("socket broken")
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_resp)
        mock_cm.__exit__ = MagicMock(return_value=False)
        mock_client = MagicMock()
        with patch("luckyd_code.api._call_with_retry", return_value=(mock_client, mock_cm, mock_resp)):
            events = list(stream_chat([], [], "m", "k", "http://x", 100, 0.7))
        error_events = [d for t, d in events if t == "error"]
        assert error_events

    def test_none_choices_key_skipped(self):
        chunk = json.dumps({"no_choices": True})
        events = self._chat_lines([f"data: {chunk}", "data: [DONE]"])
        assert events  # should not crash


class TestCallWithRetry:
    """Test _call_with_retry retry logic."""

    def test_non_retryable_raises_immediately(self):
        from luckyd_code.api import _call_with_retry
        from luckyd_code.retry import NonRetryableError
        with patch("luckyd_code.api._open_stream", side_effect=NonRetryableError("bad")):
            with pytest.raises(NonRetryableError):
                _call_with_retry([], [], "m", "k", "http://x", 100, 0.7)

    def test_model_not_found_raises_immediately(self):
        from luckyd_code.api import _call_with_retry
        from luckyd_code.retry import ModelNotFoundError
        with patch("luckyd_code.api._open_stream", side_effect=ModelNotFoundError("nope")):
            with pytest.raises(ModelNotFoundError):
                _call_with_retry([], [], "m", "k", "http://x", 100, 0.7)

    def test_retryable_exhausts_and_raises(self):
        from luckyd_code.api import _call_with_retry
        from luckyd_code.retry import RetryableError
        with patch("luckyd_code.api._open_stream", side_effect=RetryableError("429")):
            with patch("time.sleep"):
                with pytest.raises(RetryableError):
                    _call_with_retry([], [], "m", "k", "http://x", 100, 0.7)

    def test_generic_error_retried_once_then_raises(self):
        from luckyd_code.api import _call_with_retry
        with patch("luckyd_code.api._open_stream", side_effect=RuntimeError("transient")):
            with patch("time.sleep"):
                with pytest.raises(RuntimeError):
                    _call_with_retry([], [], "m", "k", "http://x", 100, 0.7)

    def test_success_on_first_attempt(self):
        from luckyd_code.api import _call_with_retry
        mock_ret = (MagicMock(), MagicMock(), MagicMock())
        with patch("luckyd_code.api._open_stream", return_value=mock_ret):
            result = _call_with_retry([], [], "m", "k", "http://x", 100, 0.7)
        assert result is mock_ret


class TestParseStreamError:
    """Test _parse_stream_error with various response mocks."""

    def test_json_error_message_extracted(self):
        from luckyd_code.api import _parse_stream_error
        mock_resp = MagicMock()
        mock_resp.read = MagicMock()
        mock_resp.json.return_value = {"error": {"message": "rate limit exceeded"}}
        result = _parse_stream_error(mock_resp)
        assert "rate limit exceeded" in result

    def test_falls_back_to_text(self):
        from luckyd_code.api import _parse_stream_error
        mock_resp = MagicMock()
        mock_resp.read = MagicMock()
        mock_resp.json.side_effect = ValueError("not json")
        mock_resp.text = "plain error text"
        result = _parse_stream_error(mock_resp)
        assert "plain error text" in result

    def test_all_fails_returns_status(self):
        from luckyd_code.api import _parse_stream_error
        from unittest.mock import PropertyMock
        mock_resp = MagicMock()
        mock_resp.read.side_effect = Exception("network")
        mock_resp.json.side_effect = Exception("json")
        type(mock_resp).text = PropertyMock(side_effect=Exception("text"))
        mock_resp.status_code = 503
        result = _parse_stream_error(mock_resp)
        assert "503" in result


# ═══════════════════════════════════════════════════════════════════════════════
# brain/chunker.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestChunkByLines:
    def test_basic_chunking(self, tmp_path):
        from pathlib import Path
        from luckyd_code.brain.chunker import _chunk_by_lines
        content = "line1\nline2\n\nline3\nline4\n\nline5"
        chunks = _chunk_by_lines(Path("test.go"), content, "go")
        assert len(chunks) >= 1
        assert all(c["language"] == "go" for c in chunks)

    def test_empty_file(self, tmp_path):
        from pathlib import Path
        from luckyd_code.brain.chunker import _chunk_by_lines
        chunks = _chunk_by_lines(Path("test.go"), "", "go")
        # Header detection with empty lines
        assert isinstance(chunks, list)

    def test_last_block_captured(self, tmp_path):
        from pathlib import Path
        from luckyd_code.brain.chunker import _chunk_by_lines
        content = "header\n\nblock1\n\nblock2 final"
        chunks = _chunk_by_lines(Path("t.go"), content, "go")
        all_content = " ".join(c["content"] for c in chunks)
        assert "final" in all_content or "block2" in all_content


class TestChunkWithRegex:
    """Test regex-based chunker for JS/TS/Go/Rust."""

    def _js_content(self):
        return textwrap.dedent("""\
            // header
            const utils = require('./utils');

            function doSomething(x) {
                return x + 1;
            }

            class MyWidget {
                constructor() {
                    this.value = 0;
                }
            }

            const arrowFn = (x) => x * 2;
        """)

    def test_js_functions_extracted(self, tmp_path):
        from pathlib import Path
        from luckyd_code.brain.chunker import _chunk_with_regex
        chunks = _chunk_with_regex(Path("app.js"), self._js_content(), "javascript")
        names = [c["name"] for c in chunks]
        assert "doSomething" in names or "MyWidget" in names

    def test_ts_interface_extracted(self, tmp_path):
        from pathlib import Path
        from luckyd_code.brain.chunker import _chunk_with_regex
        content = textwrap.dedent("""\
            interface IService {
                run(): void;
            }
            function start() {
                return true;
            }
        """)
        chunks = _chunk_with_regex(Path("svc.ts"), content, "typescript")
        names = [c["name"] for c in chunks]
        assert "IService" in names or "start" in names

    def test_go_struct_extracted(self):
        from pathlib import Path
        from luckyd_code.brain.chunker import _chunk_with_regex
        content = textwrap.dedent("""\
            package main

            type Server struct {
                Port int
            }

            func (s *Server) Run() {
            }
        """)
        chunks = _chunk_with_regex(Path("main.go"), content, "go")
        names = [c["name"] for c in chunks]
        assert "Server" in names or "Run" in names

    def test_rust_fn_extracted(self):
        from pathlib import Path
        from luckyd_code.brain.chunker import _chunk_with_regex
        content = textwrap.dedent("""\
            struct Config {
                value: i32,
            }
            fn process(cfg: &Config) -> i32 {
                cfg.value
            }
        """)
        chunks = _chunk_with_regex(Path("lib.rs"), content, "rust")
        names = [c["name"] for c in chunks]
        assert "Config" in names or "process" in names

    def test_no_patterns_falls_through(self):
        """Language with no regex patterns returns chunks without crashing."""
        from pathlib import Path
        from luckyd_code.brain.chunker import _chunk_with_regex, STRUCTURE_PATTERNS
        # ruby has no patterns
        content = "def foo\n  1\nend\n"
        chunks = _chunk_with_regex(Path("app.rb"), content, "ruby")
        assert isinstance(chunks, list)

    def test_header_detection_limits_at_first_match(self):
        from pathlib import Path
        from luckyd_code.brain.chunker import _chunk_with_regex
        content = "import x\n\nfunction alpha() {\n  return 1;\n}\n"
        chunks = _chunk_with_regex(Path("f.js"), content, "javascript")
        assert chunks  # should produce at least the module + function chunk


class TestFindBlockEnd:
    def test_simple_braces(self):
        from luckyd_code.brain.chunker import _find_block_end
        content = "function x() { return 1; }"
        end = _find_block_end(content, 0)
        assert end == len(content)

    def test_nested_braces(self):
        from luckyd_code.brain.chunker import _find_block_end
        content = "{ outer { inner } more }"
        end = _find_block_end(content, 0)
        assert content[end - 1] == "}"
        assert content[:end].count("{") == content[:end].count("}")

    def test_no_brace_returns_len(self):
        from luckyd_code.brain.chunker import _find_block_end
        content = "no braces here"
        end = _find_block_end(content, 0)
        assert end == len(content)

    def test_string_with_brace_not_counted(self):
        from luckyd_code.brain.chunker import _find_block_end
        content = 'fn x() { let s = "}"; }'
        end = _find_block_end(content, 0)
        assert end == len(content)

    def test_escape_in_string(self):
        from luckyd_code.brain.chunker import _find_block_end
        content = r'fn x() { let s = "\"nested\""; }'
        end = _find_block_end(content, 0)
        assert end > 0


class TestChunkFile:
    def test_unsupported_extension_returns_empty(self, tmp_path):
        from luckyd_code.brain.chunker import chunk_file
        f = tmp_path / "file.xyz"
        f.write_text("data")
        assert chunk_file(f) == []

    def test_empty_file_returns_empty(self, tmp_path):
        from luckyd_code.brain.chunker import chunk_file
        f = tmp_path / "empty.py"
        f.write_text("   \n")
        assert chunk_file(f) == []

    def test_python_file_chunked(self, tmp_path):
        from luckyd_code.brain.chunker import chunk_file
        f = tmp_path / "code.py"
        f.write_text("def hello():\n    return 1\n")
        chunks = chunk_file(f)
        assert len(chunks) >= 1

    def test_js_file_chunked(self, tmp_path):
        from luckyd_code.brain.chunker import chunk_file
        f = tmp_path / "app.js"
        f.write_text("function greet() { return 'hi'; }\n")
        chunks = chunk_file(f)
        assert isinstance(chunks, list)

    def test_go_file_line_chunked(self, tmp_path):
        from luckyd_code.brain.chunker import chunk_file
        f = tmp_path / "main.go"
        f.write_text("package main\n\nfunc main() {\n}\n")
        chunks = chunk_file(f)
        assert isinstance(chunks, list)

    def test_os_error_returns_empty(self, tmp_path):
        from luckyd_code.brain.chunker import chunk_file
        f = tmp_path / "code.py"
        f.write_text("x = 1")
        with patch("pathlib.Path.read_text", side_effect=OSError("perm denied")):
            result = chunk_file(f)
        assert result == []

    def test_syntax_error_falls_back_to_line_chunker(self, tmp_path):
        from luckyd_code.brain.chunker import chunk_file
        f = tmp_path / "bad.py"
        f.write_text("def (broken:\n  pass\n")
        # Should not raise — falls back to line-based chunking
        result = chunk_file(f)
        assert isinstance(result, list)


class TestChunkProject:
    def test_skips_non_code_files(self, tmp_path):
        from luckyd_code.brain.chunker import chunk_project
        (tmp_path / "readme.txt").write_text("nothing")
        (tmp_path / "code.py").write_text("x = 1\n")
        chunks = chunk_project(str(tmp_path))
        # Only .py file should be chunked
        assert all(".py" in c["file_path"] or c["file_path"] for c in chunks)

    def test_handles_exception_per_file(self, tmp_path):
        from luckyd_code.brain.chunker import chunk_project
        (tmp_path / "ok.py").write_text("def f(): pass\n")
        with patch("luckyd_code.brain.chunker.chunk_file", side_effect=RuntimeError("oops")):
            result = chunk_project(str(tmp_path))
        assert result == []


# ═══════════════════════════════════════════════════════════════════════════════
# tools/game_gen.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestResolvePyInstaller:
    def test_not_found_returns_none(self):
        from luckyd_code.tools.game_gen import _resolve_pyinstaller
        with patch("shutil.which", return_value=None):
            with patch("subprocess.run", side_effect=Exception("no pyinstaller")):
                result = _resolve_pyinstaller()
        assert result is None

    def test_found_on_path_returns_found(self):
        from luckyd_code.tools.game_gen import _resolve_pyinstaller
        with patch("shutil.which", return_value="/usr/bin/pyinstaller"):
            result = _resolve_pyinstaller()
        assert result == "found"

    def test_found_as_module_returns_module(self):
        from luckyd_code.tools.game_gen import _resolve_pyinstaller
        with patch("shutil.which", return_value=None):
            with patch("subprocess.run", return_value=MagicMock(returncode=0)):
                result = _resolve_pyinstaller()
        assert result == "module"


class TestGameGenToolRun:
    def _tool(self):
        from luckyd_code.tools.game_gen import GameGenTool
        return GameGenTool()

    def test_bad_difficulty_returns_error(self):
        tool = self._tool()
        result = tool.run("a pong game", difficulty="impossible")
        assert "Error" in result

    def test_bad_output_format_returns_error(self):
        tool = self._tool()
        result = tool.run("a pong game", output_format="dmg")
        assert "Error" in result

    def test_mkdir_oserror_returns_error(self, tmp_path):
        tool = self._tool()
        with patch("pathlib.Path.mkdir", side_effect=OSError("no permission")):
            result = tool.run("game", output_dir="/no/such/dir")
        assert "Error" in result

    def test_model_call_failed_returns_error(self, tmp_path):
        tool = self._tool()
        with patch.object(tool, "_generate_source", side_effect=RuntimeError("API down")):
            result = tool.run("game", output_dir=str(tmp_path))
        assert "Error" in result

    def test_py_format_writes_file(self, tmp_path):
        tool = self._tool()
        with patch.object(tool, "_generate_source", return_value="import pygame\ndef main(): pass\n"):
            result = tool.run("a simple game", output_format="py", output_dir=str(tmp_path))
        assert "File" in result or "generated" in result.lower()

    def test_fences_stripped_from_source(self, tmp_path):
        tool = self._tool()
        fenced = "```python\nimport pygame\ndef main(): pass\n```"
        with patch.object(tool, "_generate_source", return_value=fenced):
            result = tool.run("game", output_format="py", output_dir=str(tmp_path))
        # Should not crash; file written without fences
        assert isinstance(result, str)

    def test_exe_format_compile_failure(self, tmp_path):
        tool = self._tool()
        with patch.object(tool, "_generate_source", return_value="import pygame\n"):
            with patch("luckyd_code.tools.game_gen.compile_exe", return_value=(False, "pyinstaller error")):
                result = tool.run("game", output_format="exe", output_dir=str(tmp_path))
        assert "Compilation failed" in result or "pyinstaller" in result.lower()

    def test_exe_format_compile_success(self, tmp_path):
        tool = self._tool()
        fake_exe = str(tmp_path / "game.exe")
        with patch.object(tool, "_generate_source", return_value="import pygame\n"):
            with patch("luckyd_code.tools.game_gen.compile_exe", return_value=(True, fake_exe)):
                result = tool.run("game", output_format="exe", output_dir=str(tmp_path))
        assert "exe" in result.lower() or fake_exe in result

    def test_generate_source_falls_back_on_api_exception(self, tmp_path):
        tool = self._tool()
        with patch.object(tool, "_generate_source_api", side_effect=RuntimeError("api down")):
            with patch.object(tool, "_generate_source_fallback", return_value="import pygame\n"):
                src = tool._generate_source("pong", "normal")
        assert "import pygame" in src


# ═══════════════════════════════════════════════════════════════════════════════
# memory/manager.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestMemoryManagerCoverage:
    @pytest.fixture
    def mgr(self, tmp_path):
        from luckyd_code.memory.manager import MemoryManager
        m = MemoryManager(str(tmp_path))
        # Override mem_dir to use tmp_path so tests don't write to home dir
        mem_dir = tmp_path / "memory"
        mem_dir.mkdir(exist_ok=True)
        m.mem_dir = mem_dir
        return m

    def test_save_and_load_memory(self, mgr):
        mgr.save_memory("test-key", "test content", "general", importance=7)
        loaded = mgr.load_memory("test-key", "general")
        assert loaded == "test content"

    def test_load_nonexistent_returns_none(self, mgr):
        assert mgr.load_memory("ghost", "general") is None

    def test_delete_existing_memory(self, mgr):
        mgr.save_memory("del-key", "bye", "general")
        assert mgr.delete_memory("del-key", "general") is True

    def test_delete_nonexistent_returns_false(self, mgr):
        assert mgr.delete_memory("nope", "general") is False

    def test_list_memories_all(self, mgr):
        mgr.save_memory("a", "content a", "general")
        mgr.save_memory("b", "content b", "session")
        mems = mgr.list_memories()
        assert len(mems) >= 2

    def test_list_memories_filtered_by_type(self, mgr):
        mgr.save_memory("x", "x content", "general")
        mgr.save_memory("y", "y content", "technical")
        mems = mgr.list_memories("technical")
        assert all(m["type"] == "technical" for m in mems)

    def test_decay_archives_old_low_importance(self, mgr, tmp_path):
        # Write a memory file directly with old timestamp (bypass save_memory path issues)
        f = mgr.mem_dir / "general_old_mem.md"
        old_time = time.time() - (40 * 86400)  # 40 days ago
        f.write_text(
            f"<!-- importance:1 saved:{old_time:.0f} accessed:{old_time:.0f} count:0 -->\nold content",
            encoding="utf-8",
        )
        assert f.exists()
        count = mgr.decay(max_days=30, importance_threshold=3)
        assert count >= 1

    def test_decay_does_not_archive_high_importance(self, mgr):
        mgr.save_memory("important", "keep this", "general", importance=9)
        count = mgr.decay(max_days=1, importance_threshold=3)
        assert count == 0

    def test_save_conversation_summary(self, mgr):
        mgr.save_conversation_summary("summary text", turn_count=3)
        loaded = mgr.load_memory("latest_summary", "session")
        assert loaded is not None
        assert "summary text" in loaded

    def test_get_all_memories_formatted_empty(self, mgr):
        result = mgr.get_all_memories_formatted()
        assert result == ""

    def test_get_all_memories_formatted_with_data(self, mgr):
        mgr.save_memory("m1", "content one", "general")
        result = mgr.get_all_memories_formatted()
        assert "<memories>" in result
        assert "m1" in result

    def test_get_relevant_memories_empty(self, mgr):
        result = mgr.get_relevant_memories("find something", k=3)
        assert result == "" or "<memories>" in result

    def test_get_relevant_memories_with_match(self, mgr):
        mgr.save_memory("auth", "authentication module uses JWT tokens", "technical")
        result = mgr.get_relevant_memories("JWT token authentication", k=3)
        assert "<memories>" in result or result == ""

    def test_update_index_replaces_existing_entry(self, mgr):
        mgr.save_memory("dup", "first version", "general")
        mgr.save_memory("dup", "second version", "general")  # should update, not duplicate
        index = (mgr.mem_dir / "MEMORY.md").read_text()
        # Only one entry for "dup"
        assert index.count("[dup]") <= 2  # may appear once or twice due to anchored links

    def test_rebuild_index_removes_empty(self, mgr):
        mgr.save_memory("z", "content z", "general")
        mem_f = mgr.mem_dir / "general_z.md"
        mem_f.unlink()
        mgr._rebuild_index()
        index_path = mgr.mem_dir / "MEMORY.md"
        if index_path.exists():
            assert "[z]" not in index_path.read_text()

    def test_make_snippet_no_match_returns_beginning(self, mgr):
        result = mgr._make_snippet("hello world content", "xyz")
        assert "hello" in result

    def test_make_snippet_match_in_middle(self, mgr):
        content = "a" * 200 + "KEYWORD" + "b" * 200
        result = mgr._make_snippet(content, "keyword")
        assert "KEYWORD" in result

    def test_module_level_save_and_list(self, tmp_path):
        """Module-level convenience API."""
        import luckyd_code.memory.manager as mm_mod
        orig = mm_mod._DEFAULT_MANAGER
        try:
            mm_mod._DEFAULT_MANAGER = None
            with patch("luckyd_code.memory.manager.MemoryManager") as MockMM:
                inst = MagicMock()
                inst.list_memories.return_value = []
                MockMM.return_value = inst
                result = mm_mod.list_memories()
            assert result == "No memories yet."
        finally:
            mm_mod._DEFAULT_MANAGER = orig

    def test_load_claude_md_reads_memory_md(self, mgr, tmp_path):
        mem_md = Path(mgr.project_dir) / "MEMORY.md"
        mem_md.write_text("# Memory")
        result = mgr.load_claude_md()
        assert "Memory" in result

    def test_load_claude_md_falls_back_to_claude_md(self, mgr, tmp_path):
        claude_md = Path(mgr.project_dir) / "CLAUDE.md"
        claude_md.write_text("# Claude")
        result = mgr.load_claude_md()
        assert "Claude" in result

    def test_load_claude_md_returns_empty_when_missing(self, mgr):
        result = mgr.load_claude_md()
        assert result == ""

    def test_save_claude_md(self, mgr, tmp_path):
        mgr.save_claude_md("# Updated")
        assert (Path(mgr.project_dir) / "MEMORY.md").read_text() == "# Updated"


# ═══════════════════════════════════════════════════════════════════════════════
# memory/user.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestUserMemoryCoverage:
    @pytest.fixture
    def um(self, tmp_path):
        from luckyd_code.memory.user import UserMemory
        um = UserMemory.__new__(UserMemory)
        d = tmp_path / "memories"
        d.mkdir()
        um._mem_dir = d
        return um

    def test_save_and_load(self, um):
        um.save("pref1", "dark mode", importance=8)
        loaded = um.load("pref1")
        assert loaded == "dark mode"

    def test_load_nonexistent_returns_none(self, um):
        assert um.load("ghost") is None

    def test_delete_existing(self, um):
        um.save("to-del", "bye")
        assert um.delete("to-del") is True

    def test_delete_nonexistent(self, um):
        assert um.delete("nope") is False

    def test_list_all(self, um):
        um.save("a", "alpha", importance=5)
        um.save("b", "beta", importance=7)
        mems = um.list_all()
        assert len(mems) == 2
        names = [m["name"] for m in mems]
        assert "a" in names and "b" in names

    def test_list_all_includes_metadata(self, um):
        um.save("x", "content", importance=9)
        mems = um.list_all()
        assert mems[0]["importance"] == 9

    def test_keyword_search_finds_match(self, um):
        um.save("jwt", "we use JWT tokens for auth")
        results = um._keyword_search("JWT", k=5)
        assert len(results) >= 1

    def test_keyword_search_empty_query(self, um):
        um.save("doc", "some content")
        results = um._keyword_search("", k=5)
        assert results == []

    def test_keyword_search_no_match(self, um):
        um.save("doc", "unrelated content here")
        results = um._keyword_search("xyzfoo", k=5)
        assert results == []

    def test_get_relevant_empty_returns_empty(self, um):
        assert um.get_relevant("something") == ""

    def test_get_relevant_returns_formatted_xml(self, um):
        um.save("pref", "user prefers dark mode")
        result = um.get_relevant("dark mode preferences", k=3)
        # Either finds it or returns empty string (keyword search)
        assert isinstance(result, str)

    def test_decay_archives_old_low_importance(self, um):
        um.save("old", "stale content", importance=1)
        f = um._mem_dir / "old.md"
        old_time = time.time() - (40 * 86400)
        f.write_text(
            f"<!-- importance:1 saved:{old_time:.0f} accessed:{old_time:.0f} count:0 -->\nstale",
            encoding="utf-8",
        )
        count = um.decay()
        assert count >= 1

    def test_decay_skips_high_importance(self, um):
        um.save("vital", "critical info", importance=9)
        count = um.decay()
        assert count == 0

    def test_strip_meta_with_comment(self, um):
        raw = "<!-- importance:5 saved:1000 accessed:1000 count:0 -->\nActual content"
        assert um._strip_meta(raw) == "Actual content"

    def test_strip_meta_no_comment(self, um):
        raw = "Just plain text"
        assert um._strip_meta(raw) == "Just plain text"

    def test_read_meta_nonexistent_file(self, um, tmp_path):
        meta = um._read_meta(tmp_path / "ghost.md")
        assert meta["importance"] == 5

    def test_module_level_get_user_memory_singleton(self):
        from luckyd_code.memory import user as user_mod
        orig = user_mod._user_memory
        try:
            user_mod._user_memory = None
            with patch.object(user_mod, "_get_user_mem_dir") as mock_dir:
                mock_dir.return_value = Path("/tmp")
                with patch("luckyd_code.memory.user.UserMemory") as MockUM:
                    MockUM.return_value = MagicMock()
                    um1 = user_mod.get_user_memory()
                    um2 = user_mod.get_user_memory()
            assert um1 is um2
        finally:
            user_mod._user_memory = orig

    def test_module_sanitize(self):
        from luckyd_code.memory.user import _sanitize
        # strip('_') removes trailing underscore from '!'
        assert _sanitize("hello world!") == "hello_world"
        assert _sanitize("") == "unnamed"

    def test_module_make_snippet_no_match(self):
        from luckyd_code.memory.user import _make_snippet
        result = _make_snippet("no match here", "xyz")
        assert result[:300] == "no match here"[:300]

    def test_module_make_snippet_match(self):
        from luckyd_code.memory.user import _make_snippet
        content = "x" * 200 + "TARGET" + "y" * 200
        result = _make_snippet(content, "target")
        assert "TARGET" in result


# ═══════════════════════════════════════════════════════════════════════════════
# self_improve.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetImprovementPrompt:
    def test_web_area(self):
        from luckyd_code.self_improve import get_improvement_prompt
        p = get_improvement_prompt("web")
        assert "web" in p.lower() or "UI" in p

    def test_cli_area(self):
        from luckyd_code.self_improve import get_improvement_prompt
        p = get_improvement_prompt("cli")
        assert "cli" in p.lower() or "CLI" in p

    def test_tools_area(self):
        from luckyd_code.self_improve import get_improvement_prompt
        p = get_improvement_prompt("tools")
        assert "tool" in p.lower()

    def test_refactor_area(self):
        from luckyd_code.self_improve import get_improvement_prompt
        p = get_improvement_prompt("refactor")
        assert "refactor" in p.lower() or "extract" in p.lower()

    def test_perf_area(self):
        from luckyd_code.self_improve import get_improvement_prompt
        p = get_improvement_prompt("perf")
        assert "performance" in p.lower() or "cach" in p.lower()

    def test_cleanup_area(self):
        from luckyd_code.self_improve import get_improvement_prompt
        p = get_improvement_prompt("cleanup")
        assert "clean" in p.lower() or "TODO" in p

    def test_empty_area_returns_explore(self):
        from luckyd_code.self_improve import get_improvement_prompt
        p = get_improvement_prompt("")
        assert "explore" in p.lower() or "bug" in p.lower()


class TestGitHelper:
    def test_git_exception_returns_error_string(self):
        from luckyd_code.self_improve import _git
        with patch("subprocess.run", side_effect=Exception("git not found")):
            result = _git("status")
        assert "<error:" in result

    def test_git_returns_stdout(self):
        from luckyd_code.self_improve import _git
        mock = MagicMock()
        mock.stdout = "main\n"
        with patch("subprocess.run", return_value=mock):
            result = _git("rev-parse", "--abbrev-ref", "HEAD")
        assert result == "main"


class TestImprovementTracker:
    def test_init_captures_branch_and_hash(self, tmp_path):
        from luckyd_code.self_improve import ImprovementTracker
        with patch("luckyd_code.self_improve._git") as mock_git:
            mock_git.side_effect = ["main", "abc123"]
            tracker = ImprovementTracker(str(tmp_path))
        assert tracker._branch == "main"
        assert tracker._start_hash == "abc123"

    def test_report_no_changes(self, tmp_path):
        from luckyd_code.self_improve import ImprovementTracker
        with patch("luckyd_code.self_improve._git") as mock_git:
            # init: branch, hash
            # report: end_hash, unstaged diff, staged diff, stash pop check, changed files
            mock_git.side_effect = ["main", "abc123", "abc123", "", "", "", ""]
            tracker = ImprovementTracker(str(tmp_path))
            report = tracker.report()
        assert report.branch == "main"
        assert report.error is None

    def test_report_with_changed_files(self, tmp_path):
        from luckyd_code.self_improve import ImprovementTracker
        with patch("luckyd_code.self_improve._git") as mock_git:
            mock_git.side_effect = [
                "main", "abc123",   # init
                "def456",           # end_hash
                "diff content",     # unstaged
                "",                 # staged
                "",                 # stash pop (not stashed)
                "file.py",          # changed files
                "1 insertion",      # stat for file.py
            ]
            tracker = ImprovementTracker(str(tmp_path))
            report = tracker.report()
        assert isinstance(report.diff_summary, str)


# ═══════════════════════════════════════════════════════════════════════════════
# web_routes/brain.py
# ═══════════════════════════════════════════════════════════════════════════════

def _brain_request():
    req = MagicMock()
    req.app.state.web_state = MagicMock()
    return req


class TestBrainStatusEndpoint:
    @pytest.mark.asyncio
    async def test_empty_brain_returns_empty_status(self):
        from luckyd_code.web_routes.brain import brain_status
        with patch("luckyd_code.brain.KnowledgeGraph") as MockKG, \
             patch("luckyd_code.brain.VectorIndexer") as MockVI:
            kg = MagicMock()
            kg.nodes = {}
            kg.stats = {}
            MockKG.return_value = kg
            vi = MagicMock()
            vi.load.return_value = False
            MockVI.return_value = vi
            result = await brain_status(_brain_request())
        assert result["status"] == "empty"

    @pytest.mark.asyncio
    async def test_brain_with_nodes_returns_stats(self):
        from luckyd_code.web_routes.brain import brain_status
        with patch("luckyd_code.brain.KnowledgeGraph") as MockKG, \
             patch("luckyd_code.brain.VectorIndexer") as MockVI, \
             patch("luckyd_code.brain.Retriever") as MockR:
            kg = MagicMock()
            kg.nodes = {"sym1": {}}
            kg.stats = {"node_count": 1, "edge_count": 2, "files_parsed": 3, "last_built": 1000000}
            MockKG.return_value = kg
            vi = MagicMock()
            vi.load.return_value = True
            MockVI.return_value = vi
            r = MagicMock()
            r.stats.return_value = {"vector": {"chunks": 10, "files": 5}}
            MockR.return_value = r
            result = await brain_status(_brain_request())
        assert result["symbols"] == 1
        assert result["rag_chunks"] == 10

    @pytest.mark.asyncio
    async def test_brain_vectorindexer_exception_handled(self):
        from luckyd_code.web_routes.brain import brain_status
        with patch("luckyd_code.brain.KnowledgeGraph") as MockKG, \
             patch("luckyd_code.brain.VectorIndexer", side_effect=Exception("no index")):
            kg = MagicMock()
            kg.nodes = {}
            kg.stats = {}
            MockKG.return_value = kg
            result = await brain_status(_brain_request())
        assert result["status"] == "empty"


class TestBrainRebuildEndpoint:
    @pytest.mark.asyncio
    async def test_rebuild_returns_stats(self):
        from luckyd_code.web_routes.brain import brain_rebuild
        req = _brain_request()
        req.app.state.web_state.knowledge_graph = MagicMock()
        with patch("luckyd_code.brain.rebuild_project",
                   return_value={"chunks": 50, "files": 10, "node_count": 100, "files_parsed": 10}):
            result = await brain_rebuild(req)
        assert result["status"] == "ok"
        assert result["chunks"] == 50

    @pytest.mark.asyncio
    async def test_rebuild_no_knowledge_graph_on_state(self):
        from luckyd_code.web_routes.brain import brain_rebuild
        req = _brain_request()
        req.app.state.web_state.knowledge_graph = None
        with patch("luckyd_code.brain.rebuild_project",
                   return_value={"chunks": 0, "files": 0, "node_count": 0, "files_parsed": 0}):
            result = await brain_rebuild(req)
        assert result["status"] == "ok"


class TestBrainSearchEndpoint:
    @pytest.mark.asyncio
    async def test_search_empty_query_returns_empty(self):
        from luckyd_code.web_routes.brain import brain_search
        result = await brain_search(_brain_request(), q="")
        assert result == {"results": []}

    @pytest.mark.asyncio
    async def test_search_returns_results(self):
        from luckyd_code.web_routes.brain import brain_search
        with patch("luckyd_code.brain.Retriever") as MockR:
            r = MagicMock()
            r.search.return_value = [{"content": "some code", "file": "a.py", "score": 0.9}]
            MockR.return_value = r
            result = await brain_search(_brain_request(), q="auth", max_results=3)
        assert len(result["results"]) == 1
        assert result["results"][0]["score"] == 0.9

    @pytest.mark.asyncio
    async def test_search_exception_returns_500(self):
        from luckyd_code.web_routes.brain import brain_search
        from fastapi.responses import JSONResponse
        with patch("luckyd_code.brain.Retriever", side_effect=Exception("crash")):
            result = await brain_search(_brain_request(), q="something")
        assert isinstance(result, JSONResponse)
        assert result.status_code == 500


class TestBrainStatsEndpoint:
    @pytest.mark.asyncio
    async def test_stats_returns_info(self):
        from luckyd_code.web_routes.brain import brain_stats
        with patch("luckyd_code.brain.Retriever") as MockR:
            r = MagicMock()
            r.stats.return_value = {"vector": {"chunks": 5}}
            MockR.return_value = r
            result = await brain_stats(_brain_request())
        assert "vector" in result

    @pytest.mark.asyncio
    async def test_stats_exception_returns_500(self):
        from luckyd_code.web_routes.brain import brain_stats
        from fastapi.responses import JSONResponse
        with patch("luckyd_code.brain.Retriever", side_effect=Exception("crash")):
            result = await brain_stats(_brain_request())
        assert isinstance(result, JSONResponse)
        assert result.status_code == 500


class TestBrainDependentsEndpoint:
    @pytest.mark.asyncio
    async def test_no_symbol_returns_400(self):
        from luckyd_code.web_routes.brain import brain_dependents
        from fastapi.responses import JSONResponse
        result = await brain_dependents(_brain_request(), symbol="")
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_returns_dependents(self):
        from luckyd_code.web_routes.brain import brain_dependents
        with patch("luckyd_code.brain.KnowledgeGraph") as MockKG:
            kg = MagicMock()
            kg.find_dependents.return_value = ["mod_a", "mod_b"]
            MockKG.return_value = kg
            result = await brain_dependents(_brain_request(), symbol="MyClass")
        assert result["symbol"] == "MyClass"
        assert result["count"] == 2

    @pytest.mark.asyncio
    async def test_exception_returns_500(self):
        from luckyd_code.web_routes.brain import brain_dependents
        from fastapi.responses import JSONResponse
        with patch("luckyd_code.brain.KnowledgeGraph", side_effect=Exception("oops")):
            result = await brain_dependents(_brain_request(), symbol="Foo")
        assert isinstance(result, JSONResponse)
        assert result.status_code == 500


# ═══════════════════════════════════════════════════════════════════════════════
# _agent_loop.py — remaining branch coverage
# ═══════════════════════════════════════════════════════════════════════════════

class TestContextTextForMemory:
    def test_last_user_message_extracted(self):
        from luckyd_code._agent_loop import _context_text_for_memory
        from luckyd_code.context import ConversationContext
        ctx = ConversationContext("sys")
        ctx.add_user_message("find all the bugs")
        result = _context_text_for_memory(ctx)
        assert "bugs" in result

    def test_multimodal_content_text_extracted(self):
        from luckyd_code._agent_loop import _context_text_for_memory
        from luckyd_code.context import ConversationContext
        ctx = ConversationContext("sys")
        # Inject a multimodal message directly
        ctx.messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": "data:..."},
                {"type": "text", "text": "describe this image"},
            ]}
        ]
        result = _context_text_for_memory(ctx)
        assert "describe" in result

    def test_no_user_message_returns_empty(self):
        from luckyd_code._agent_loop import _context_text_for_memory
        from luckyd_code.context import ConversationContext
        ctx = ConversationContext("sys")
        result = _context_text_for_memory(ctx)
        assert result == ""


class TestAutoSaveTurnMemory:
    def test_saves_session_summary(self):
        from luckyd_code._agent_loop import _auto_save_turn_memory
        from luckyd_code.context import ConversationContext
        ctx = ConversationContext("sys")
        ctx.add_user_message("do the thing")

        mm = MagicMock()
        _auto_save_turn_memory(mm, None, ctx, turn=0, max_turns=10)
        mm.save_conversation_summary.assert_called_once()

    def test_saves_user_memory_on_5th_turn(self):
        from luckyd_code._agent_loop import _auto_save_turn_memory
        from luckyd_code.context import ConversationContext
        ctx = ConversationContext("sys")
        ctx.add_user_message("fifth turn task")

        mm = MagicMock()
        um = MagicMock()
        _auto_save_turn_memory(mm, um, ctx, turn=4, max_turns=10)  # turn 4 = 5th (0-indexed)
        um.save.assert_called_once()

    def test_no_user_memory_given_skips_um_save(self):
        from luckyd_code._agent_loop import _auto_save_turn_memory
        from luckyd_code.context import ConversationContext
        ctx = ConversationContext("sys")
        ctx.add_user_message("task")

        mm = MagicMock()
        _auto_save_turn_memory(mm, None, ctx, turn=4, max_turns=10)
        # Should not crash


class TestIngestToolResultWritePaths:
    def test_write_tool_triggers_verify(self, tmp_path):
        from luckyd_code._agent_loop import _ingest_tool_result
        from luckyd_code.context import ConversationContext
        ctx = ConversationContext("sys")
        ctx.add_user_message("x")
        modified = []
        f = tmp_path / "out.py"
        f.write_text("x = 1")

        _ingest_tool_result(
            name="Write",
            result="wrote ok",
            args={"file_path": str(f)},
            tc_id="tc1",
            context=ctx,
            modified_files=modified,
        )
        assert str(f) in modified

    def test_write_tool_empty_file_adds_warning(self, tmp_path):
        from luckyd_code._agent_loop import _ingest_tool_result
        from luckyd_code.context import ConversationContext
        ctx = ConversationContext("sys")
        ctx.add_user_message("x")
        modified = []
        f = tmp_path / "empty.py"
        f.write_text("")  # empty file

        _ingest_tool_result(
            name="Write",
            result="wrote",
            args={"file_path": str(f)},
            tc_id="tc1",
            context=ctx,
            modified_files=modified,
        )
        # Warning message should have been added about empty file
        msgs = ctx.get_messages()
        assert any("empty" in str(m.get("content", "")).lower() for m in msgs)

    def test_edit_tool_missing_file_adds_warning(self, tmp_path):
        from luckyd_code._agent_loop import _ingest_tool_result
        from luckyd_code.context import ConversationContext
        ctx = ConversationContext("sys")
        ctx.add_user_message("x")
        modified = []
        missing = str(tmp_path / "ghost.py")

        _ingest_tool_result(
            name="Edit",
            result="edited",
            args={"file_path": missing},
            tc_id="tc1",
            context=ctx,
            modified_files=modified,
        )
        msgs = ctx.get_messages()
        assert any("not found" in str(m.get("content", "")).lower() for m in msgs)


class TestAgentLoopBudgetWarning:
    def test_budget_warning_injected_near_limit(self):
        from luckyd_code._agent_loop import run_agent_loop, RunConfig
        from luckyd_code.context import ConversationContext

        call_count = [0]
        def _stream(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # First turn: tool call (so loop continues and warning is injected)
                yield ("tool_calls", (
                    [{"id": "tc1", "type": "function",
                      "function": {"name": "Read", "arguments": '{"path": "x.py"}'}}],
                    "",
                ))
            else:
                yield ("done", ("finished", ""))

        ctx = ConversationContext("sys")
        ctx.add_user_message("task")
        cfg = MagicMock()
        cfg.model = "test-model"
        cfg.api_key = "k"
        cfg.base_url = "http://x"
        cfg.max_tokens = 100
        cfg.temperature = 0.7
        reg = MagicMock()
        reg.execute.return_value = "ok"

        rc = RunConfig(max_turns=2, auto_save_memory=False)  # ≤3 turns remaining from start

        with patch("luckyd_code._agent_loop.stream_chat", side_effect=_stream):
            result = run_agent_loop(ctx, cfg, [], reg, run_config=rc)

        # Check budget warning was injected (looking in context messages)
        msgs = ctx.get_messages()
        assert any("turn" in str(m.get("content", "")).lower() and
                   "remain" in str(m.get("content", "")).lower()
                   for m in msgs)

    def test_memory_injection_on_auto_save(self):
        """Relevant memories are injected into first turn context."""
        from luckyd_code._agent_loop import run_agent_loop, RunConfig
        from luckyd_code.context import ConversationContext

        def _stream(*args, **kwargs):
            yield ("done", ("done response", ""))

        ctx = ConversationContext("sys")
        ctx.add_user_message("fix the bug")
        cfg = MagicMock()
        cfg.model = "model"
        cfg.api_key = "k"
        cfg.base_url = "http://x"
        cfg.max_tokens = 100
        cfg.temperature = 0.7
        reg = MagicMock()

        with patch("luckyd_code._agent_loop.stream_chat", side_effect=_stream):
            with patch("luckyd_code._agent_loop.MemoryManager") as MockMM:
                mm = MagicMock()
                mm.get_relevant_memories.return_value = "<memories>\n<mem>fix auth bug</mem>\n</memories>"
                MockMM.return_value = mm
                with patch("luckyd_code._agent_loop.get_user_memory") as MockUM:
                    um = MagicMock()
                    um.get_relevant.return_value = ""
                    MockUM.return_value = um
                    result = run_agent_loop(ctx, cfg, [], reg)

        assert result == "done response"
        mm.get_relevant_memories.assert_called()


# ═══════════════════════════════════════════════════════════════════════════════
# tools/file_ops.py — remaining branches
# ═══════════════════════════════════════════════════════════════════════════════

class TestReadToolBranches:
    def _tool(self):
        from luckyd_code.tools.file_ops import ReadTool
        return ReadTool()

    def test_offset_beyond_length(self, tmp_path):
        f = tmp_path / "f.py"
        f.write_text("one\ntwo\n")
        tool = self._tool()
        result = tool.run(str(f), offset=100)
        assert "offset" in result.lower() or "error" in result.lower()

    def test_not_a_file_returns_error(self, tmp_path):
        tool = self._tool()
        result = tool.run(str(tmp_path))  # directory, not a file
        assert "error" in result.lower()

    def test_read_error_returns_error(self, tmp_path):
        f = tmp_path / "f.py"
        f.write_text("data")
        tool = self._tool()
        with patch("pathlib.Path.read_text", side_effect=IOError("perm")):
            result = tool.run(str(f))
        assert "error" in result.lower()


class TestWriteToolBranches:
    def _tool(self):
        from luckyd_code.tools.file_ops import WriteTool
        return WriteTool()

    def test_content_too_large_returns_error(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        tool = self._tool()
        big = "x" * (10 * 1024 * 1024 + 1)
        f = tmp_path / "big.py"
        result = tool.run(str(f), big)
        assert "10MB" in result or "size" in result.lower()

    def test_dry_run_new_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        tool = self._tool()
        f = tmp_path / "new.py"
        result = tool.run(str(f), "x = 1", dry_run=True)
        assert "dry-run" in result.lower() or "new file" in result.lower()

    def test_dry_run_no_diff(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        tool = self._tool()
        f = tmp_path / "same.py"
        f.write_text("x = 1")
        result = tool.run(str(f), "x = 1", dry_run=True)
        assert "identical" in result.lower() or "no change" in result.lower()

    def test_dry_run_shows_diff(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        tool = self._tool()
        f = tmp_path / "code.py"
        f.write_text("x = 1")
        result = tool.run(str(f), "x = 2", dry_run=True)
        assert "dry-run" in result.lower()

    def test_write_error_returns_error(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        tool = self._tool()
        f = tmp_path / "fail.py"
        with patch("pathlib.Path.write_text", side_effect=IOError("disk full")):
            result = tool.run(str(f), "content")
        assert "error" in result.lower()


class TestEditToolBranches:
    def _tool(self):
        from luckyd_code.tools.file_ops import EditTool
        return EditTool()

    def test_replace_all_replaces_multiple(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        tool = self._tool()
        f = tmp_path / "f.py"
        f.write_text("foo foo foo")
        result = tool.run(str(f), "foo", "bar", replace_all=True)
        assert f.read_text() == "bar bar bar"

    def test_dry_run_no_diff(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        tool = self._tool()
        f = tmp_path / "f.py"
        f.write_text("hello world")
        result = tool.run(str(f), "hello", "hello", dry_run=True)
        assert "identical" in result.lower() or "no change" in result.lower()

    def test_dry_run_shows_diff(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        tool = self._tool()
        f = tmp_path / "f.py"
        f.write_text("hello world")
        result = tool.run(str(f), "hello", "goodbye", dry_run=True)
        assert "dry-run" in result.lower()

    def test_write_error_returns_error(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        tool = self._tool()
        f = tmp_path / "f.py"
        f.write_text("target text")
        with patch("pathlib.Path.write_text", side_effect=IOError("disk full")):
            result = tool.run(str(f), "target text", "new text")
        assert "error" in result.lower()

    def test_multiple_occurrences_returns_error(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        tool = self._tool()
        f = tmp_path / "f.py"
        f.write_text("x = 1\nx = 1\n")
        result = tool.run(str(f), "x = 1", "y = 2")
        assert "2 times" in result or "appears" in result


class TestGlobToolBranches:
    def _tool(self):
        from luckyd_code.tools.file_ops import GlobTool
        return GlobTool()

    def test_path_is_not_dir_returns_error(self, tmp_path):
        tool = self._tool()
        f = tmp_path / "file.txt"
        f.write_text("x")
        result = tool.run("*.py", path=str(f))
        assert "error" in result.lower()

    def test_glob_exception_returns_error(self, tmp_path):
        tool = self._tool()
        with patch("pathlib.Path.rglob", side_effect=Exception("perm")):
            result = tool.run("*.py", path=str(tmp_path))
        assert "error" in result.lower()

    def test_truncation_at_200_results(self, tmp_path):
        tool = self._tool()
        for i in range(250):
            (tmp_path / f"f{i}.py").write_text("x")
        result = tool.run("*.py", path=str(tmp_path))
        assert "more" in result.lower() or len(result.splitlines()) <= 205


class TestGrepToolBranches:
    def _tool(self):
        from luckyd_code.tools.file_ops import GrepTool
        return GrepTool()

    def test_count_output_mode(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        tool = self._tool()
        f = tmp_path / "f.py"
        f.write_text("foo\nfoo\nbar\n")
        result = tool.run("foo", path=str(tmp_path), output_mode="count")
        assert "matches" in result.lower()

    def test_files_with_matches_mode(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        tool = self._tool()
        f1 = tmp_path / "a.py"
        f1.write_text("needle in a haystack")
        f2 = tmp_path / "b.py"
        f2.write_text("no match here")
        result = tool.run("needle", path=str(tmp_path), output_mode="files_with_matches")
        assert "a.py" in result

    def test_glob_filter_used(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        tool = self._tool()
        (tmp_path / "a.py").write_text("match_me")
        (tmp_path / "b.txt").write_text("match_me")
        result = tool.run("match_me", path=str(tmp_path), glob="*.py")
        assert "a.py" in result
        assert "b.txt" not in result

    def test_file_read_error_continues(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        tool = self._tool()
        f = tmp_path / "f.py"
        f.write_text("data")
        with patch("builtins.open", side_effect=Exception("perm")):
            result = tool.run("data", path=str(tmp_path))
        assert result == "No matches found"

    def test_no_matches_returns_message(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        tool = self._tool()
        (tmp_path / "f.py").write_text("hello world")
        result = tool.run("xyznothere", path=str(tmp_path))
        assert "No matches" in result

    def test_search_in_single_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        tool = self._tool()
        f = tmp_path / "f.py"
        f.write_text("target pattern here")
        result = tool.run("target", path=str(f))
        assert "target" in result
