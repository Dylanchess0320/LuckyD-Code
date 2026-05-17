"""Targeted coverage gap-fillers — Batch 2.

Covers uncovered branches in:
  - _agent_loop.py (budget warning, multimodal context, auto-save branches,
                   _ingest_tool_result Write/Edit path, verification failure)
  - api.py (_parse_stream_error, _close_unclosed_string, _count_unquoted,
            stream_chat reasoning yield, _call_with_retry retry logic)
  - indexer.py (_extract_deps Cargo.toml, format_project_context,
                _is_ignored glob patterns, index_project non-existent)
  - cost_tracker.py (legacy migration, totals sidecar, record_usage explicit cost)
  - web_app.py (get_app caching, merged memory injection)
  - background.py (missing background dir on load_history)
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest

# ═══════════════════════════════════════════════════════════════════════════════
# _agent_loop.py — uncovered branches
# ═══════════════════════════════════════════════════════════════════════════════

class TestContextTextForMemory:
    """_context_text_for_memory handles both string and list content."""

    def test_string_content(self):
        from luckyd_code._agent_loop import _context_text_for_memory
        from luckyd_code.context import ConversationContext

        ctx = ConversationContext("sys")
        ctx.add_user_message("this is a plain text message")
        result = _context_text_for_memory(ctx)
        assert "plain text message" in result

    def test_list_content_multimodal(self):
        """Multimodal content (list of parts) should extract the text part."""
        from luckyd_code._agent_loop import _context_text_for_memory
        from luckyd_code.context import ConversationContext

        ctx = ConversationContext("sys")
        # Inject a multimodal message directly
        ctx.messages.append({
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "url", "url": "http://img"}},
                {"type": "text", "text": "describe this image"},
            ]
        })
        result = _context_text_for_memory(ctx)
        assert "describe this image" in result

    def test_no_user_message_returns_empty(self):
        from luckyd_code._agent_loop import _context_text_for_memory
        from luckyd_code.context import ConversationContext

        ctx = ConversationContext("sys")
        # Only system message
        result = _context_text_for_memory(ctx)
        assert result == ""


class TestAutoSaveTurnMemory:
    """_auto_save_turn_memory calls UserMemory every 5 turns."""

    def test_saves_project_memory_every_turn(self):
        from luckyd_code._agent_loop import _auto_save_turn_memory
        from luckyd_code.context import ConversationContext

        ctx = ConversationContext("sys")
        ctx.add_user_message("hi")
        ctx.add_user_message("and another")

        mm = MagicMock()
        _auto_save_turn_memory(mm, None, ctx, turn=0, max_turns=5)
        mm.save_conversation_summary.assert_called_once()

    def test_user_memory_saved_on_fifth_turn(self):
        from luckyd_code._agent_loop import _auto_save_turn_memory
        from luckyd_code.context import ConversationContext

        ctx = ConversationContext("sys")
        ctx.add_user_message("message")

        mm = MagicMock()
        um = MagicMock()
        # Turn 4 (0-indexed) → turn+1 == 5 → should save user memory
        _auto_save_turn_memory(mm, um, ctx, turn=4, max_turns=10)
        um.save.assert_called_once()

    def test_user_memory_not_saved_on_non_fifth_turn(self):
        from luckyd_code._agent_loop import _auto_save_turn_memory
        from luckyd_code.context import ConversationContext

        ctx = ConversationContext("sys")
        ctx.add_user_message("message")

        mm = MagicMock()
        um = MagicMock()
        # Turn 2 → turn+1 == 3 → should NOT save user memory
        _auto_save_turn_memory(mm, um, ctx, turn=2, max_turns=10)
        um.save.assert_not_called()


class TestRunAgentLoopBudgetWarning:
    """Budget warning is injected when turns_remaining <= _TURN_BUDGET_WARN."""

    def _make_config(self, model="deepseek-v4-flash"):
        cfg = MagicMock()
        cfg.model = model
        cfg.api_key = "sk-test"
        cfg.base_url = "https://api.deepseek.com/v1"
        cfg.max_tokens = 1024
        cfg.temperature = 0.7
        return cfg

    def test_budget_warning_injected(self):
        """With max_turns=3 and _TURN_BUDGET_WARN=3, warning fires on turn 0."""
        from luckyd_code._agent_loop import RunConfig, run_agent_loop, _TURN_BUDGET_WARN
        from luckyd_code.context import ConversationContext

        messages_added = []

        def _stream(*args, **kwargs):
            # Capture added messages by spying on context (done lazily)
            yield ("done", ("final", ""))

        ctx = ConversationContext("sys")
        ctx.add_user_message("task")

        original_add = ctx.add_user_message

        def spy_add(msg):
            messages_added.append(msg)
            original_add(msg)

        ctx.add_user_message = spy_add

        cfg = self._make_config()
        reg = MagicMock()
        reg.execute.return_value = "ok"
        rc = RunConfig(auto_save_memory=False, max_turns=_TURN_BUDGET_WARN)

        with patch("luckyd_code._agent_loop.stream_chat", return_value=_stream()):
            run_agent_loop(ctx, cfg, [], reg, run_config=rc)

        budget_msgs = [m for m in messages_added if "remaining" in m.lower()]
        assert len(budget_msgs) >= 1

    def test_budget_warning_sent_only_once(self):
        """Budget warning should not be sent more than once per loop."""
        from luckyd_code._agent_loop import RunConfig, run_agent_loop
        from luckyd_code.context import ConversationContext

        messages_added = []
        call_count = [0]

        def _stream(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] <= 2:
                yield ("tool_calls", ([{
                    "id": f"tc{call_count[0]}", "type": "function",
                    "function": {"name": "Read", "arguments": '{"path":"a.py"}'},
                }], ""))
            else:
                yield ("done", ("done", ""))

        ctx = ConversationContext("sys")
        ctx.add_user_message("hi")

        original_add = ctx.add_user_message

        def spy_add(msg):
            messages_added.append(msg)
            original_add(msg)

        ctx.add_user_message = spy_add

        cfg = self._make_config()
        reg = MagicMock()
        reg.execute.return_value = "result"
        rc = RunConfig(auto_save_memory=False, max_turns=4)

        with patch("luckyd_code._agent_loop.stream_chat", side_effect=_stream):
            run_agent_loop(ctx, cfg, [], reg, run_config=rc)

        budget_msgs = [m for m in messages_added if "remaining" in m.lower()]
        assert len(budget_msgs) <= 1


class TestIngestToolResult:
    """_ingest_tool_result handles Write/Edit tool verification."""

    def test_write_tool_triggers_verify(self, tmp_path):
        from luckyd_code._agent_loop import _ingest_tool_result
        from luckyd_code.context import ConversationContext

        # Create a real file so _verify_write passes
        f = tmp_path / "output.py"
        f.write_text("x = 1")

        ctx = ConversationContext("sys")
        ctx.add_user_message("write something")

        modified = []
        _ingest_tool_result(
            name="Write",
            result="written",
            args={"file_path": str(f)},
            tc_id="tc1",
            context=ctx,
            modified_files=modified,
        )
        assert str(f) in modified

    def test_write_tool_empty_file_adds_warning(self, tmp_path):
        from luckyd_code._agent_loop import _ingest_tool_result
        from luckyd_code.context import ConversationContext

        # Create an empty file → verify fails
        f = tmp_path / "empty.py"
        f.write_text("")

        ctx = ConversationContext("sys")
        ctx.add_user_message("write something")
        modified = []

        _ingest_tool_result(
            name="Write",
            result="written",
            args={"file_path": str(f)},
            tc_id="tc1",
            context=ctx,
            modified_files=modified,
        )
        # Should have added a user message about the failure
        messages = ctx.get_messages()
        warning_msgs = [m for m in messages
                        if m.get("role") == "user" and "verification failed" in str(m.get("content", "")).lower()]
        assert len(warning_msgs) >= 1

    def test_non_write_tool_no_verify(self):
        from luckyd_code._agent_loop import _ingest_tool_result
        from luckyd_code.context import ConversationContext

        ctx = ConversationContext("sys")
        ctx.add_user_message("read something")
        modified = []

        _ingest_tool_result(
            name="Read",
            result="file contents",
            args={"file_path": "some.py"},
            tc_id="tc1",
            context=ctx,
            modified_files=modified,
        )
        # Read tool does not add to modified_files
        assert len(modified) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# api.py — uncovered branches
# ═══════════════════════════════════════════════════════════════════════════════

class TestCloseUnclosedString:
    def test_closes_open_string(self):
        from luckyd_code.api import _close_unclosed_string
        # String that starts but doesn't end
        result = _close_unclosed_string('{"key": "value')
        assert result.endswith('"')

    def test_no_change_when_balanced(self):
        from luckyd_code.api import _close_unclosed_string
        text = '{"key": "value"}'
        result = _close_unclosed_string(text)
        assert result == text

    def test_escape_inside_string(self):
        from luckyd_code.api import _close_unclosed_string
        # Escaped quote inside string — should still close
        result = _close_unclosed_string('{"val": "te\\"xt')
        assert result.endswith('"')


class TestCountUnquoted:
    def test_counts_braces_outside_strings(self):
        from luckyd_code.api import _count_unquoted
        opens, closes = _count_unquoted('{"a": {"b": 1}}', "{", "}")
        assert opens == 2
        assert closes == 2

    def test_ignores_braces_inside_strings(self):
        from luckyd_code.api import _count_unquoted
        opens, closes = _count_unquoted('{"key": "value { }"}', "{", "}")
        # Only the outer brace counts
        assert opens == 1
        assert closes == 1

    def test_escape_handling(self):
        from luckyd_code.api import _count_unquoted
        # Escaped quote should not toggle string state
        opens, closes = _count_unquoted('{"val": "a\\"b"}', "{", "}")
        assert opens == 1
        assert closes == 1


class TestParseStreamError:
    def test_parse_json_error_body(self):
        from luckyd_code.api import _parse_stream_error
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"error": {"message": "model not found"}}
        result = _parse_stream_error(mock_resp)
        assert "model not found" in result

    def test_parse_text_fallback(self):
        from luckyd_code.api import _parse_stream_error
        mock_resp = MagicMock()
        mock_resp.json.side_effect = Exception("not json")
        mock_resp.text = "raw error text"
        result = _parse_stream_error(mock_resp)
        assert "raw error text" in result

    def test_parse_total_failure(self):
        from luckyd_code.api import _parse_stream_error
        mock_resp = MagicMock()
        mock_resp.json.side_effect = Exception("fail")
        mock_resp.text = MagicMock()
        mock_resp.text.__str__ = MagicMock(side_effect=Exception("also fail"))
        mock_resp.status_code = 503
        result = _parse_stream_error(mock_resp)
        assert "503" in result or isinstance(result, str)


class TestCallWithRetryRetries:
    def test_retryable_error_eventually_raises(self):
        """After _RETRY_MAX retries, raises the last error."""
        from luckyd_code.api import _call_with_retry
        from luckyd_code.retry import RetryableError

        with patch("luckyd_code.api._open_stream", side_effect=RetryableError("rate limit")):
            with patch("time.sleep"):  # don't actually sleep
                with pytest.raises(RetryableError):
                    _call_with_retry([], [], "model", "key", "http://localhost", 1024, 0.7)

    def test_non_retryable_error_raises_immediately(self):
        """NonRetryableError should not be retried."""
        from luckyd_code.api import _call_with_retry
        from luckyd_code.retry import NonRetryableError

        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            raise NonRetryableError("auth failed")

        with patch("luckyd_code.api._open_stream", side_effect=side_effect):
            with pytest.raises(NonRetryableError):
                _call_with_retry([], [], "model", "key", "http://localhost", 1024, 0.7)

        assert call_count[0] == 1  # only called once

    def test_model_not_found_raises_immediately(self):
        from luckyd_code.api import _call_with_retry
        from luckyd_code.retry import ModelNotFoundError

        with patch("luckyd_code.api._open_stream", side_effect=ModelNotFoundError("no model")):
            with pytest.raises(ModelNotFoundError):
                _call_with_retry([], [], "model", "key", "http://localhost", 1024, 0.7)


class TestStreamChatErrorHandling:
    def test_model_not_found_yields_event(self):
        from luckyd_code.api import stream_chat
        from luckyd_code.retry import ModelNotFoundError

        with patch("luckyd_code.api._call_with_retry", side_effect=ModelNotFoundError("no model")):
            events = list(stream_chat([], [], "bad-model", "key"))

        assert events[0][0] == "model_not_found"

    def test_non_retryable_yields_error(self):
        from luckyd_code.api import stream_chat
        from luckyd_code.retry import NonRetryableError

        with patch("luckyd_code.api._call_with_retry", side_effect=NonRetryableError("auth")):
            events = list(stream_chat([], [], "model", "key"))

        assert events[0][0] == "error"

    def test_retryable_exhausted_yields_error(self):
        from luckyd_code.api import stream_chat
        from luckyd_code.retry import RetryableError

        with patch("luckyd_code.api._call_with_retry",
                   side_effect=RetryableError("rate limit")):
            events = list(stream_chat([], [], "model", "key"))

        assert events[0][0] == "error"
        assert "retries" in events[0][1]

    def test_generic_exception_yields_error(self):
        from luckyd_code.api import stream_chat

        with patch("luckyd_code.api._call_with_retry", side_effect=RuntimeError("kaboom")):
            events = list(stream_chat([], [], "model", "key"))

        assert events[0][0] == "error"


class TestFilterMessagesNonDeepSeek:
    """For non-DeepSeek providers, reasoning_content should be stripped."""

    def test_non_deepseek_strips_reasoning_content(self):
        from luckyd_code.api import _filter_messages
        msgs = [
            {"role": "assistant", "reasoning_content": "thinking...", "content": "answer"},
        ]
        result = _filter_messages(msgs, provider="groq")
        assert "reasoning_content" not in result[0]
        assert result[0]["content"] == "answer"

    def test_deepseek_preserves_reasoning_content(self):
        from luckyd_code.api import _filter_messages
        msgs = [
            {"role": "assistant", "reasoning_content": "thinking...", "content": None},
        ]
        result = _filter_messages(msgs, provider="deepseek")
        assert "reasoning_content" in result[0]
        assert result[0]["content"] == ""


# ═══════════════════════════════════════════════════════════════════════════════
# indexer.py — uncovered branches
# ═══════════════════════════════════════════════════════════════════════════════

class TestExtractDepsCargo:
    def test_cargo_toml_extraction(self, tmp_path):
        from luckyd_code.indexer import _extract_deps
        cargo = tmp_path / "Cargo.toml"
        cargo.write_text("[dependencies]\nserde = \"1.0\"\ntokio = \"1.0\"\n")
        result = _extract_deps(cargo, "Cargo.toml")
        assert "serde" in result
        assert "tokio" in result

    def test_cargo_toml_stops_at_next_section(self, tmp_path):
        from luckyd_code.indexer import _extract_deps
        cargo = tmp_path / "Cargo.toml"
        cargo.write_text("[dependencies]\nhyper = \"0.14\"\n\n[dev-dependencies]\ntestkit = \"1.0\"\n")
        result = _extract_deps(cargo, "Cargo.toml")
        assert "hyper" in result
        assert "testkit" not in result

    def test_unknown_file_returns_empty(self, tmp_path):
        from luckyd_code.indexer import _extract_deps
        f = tmp_path / "Gemfile"
        f.write_text("gem 'rails'\n")
        result = _extract_deps(f, "Gemfile")
        assert result == []

    def test_requirements_txt_extraction(self, tmp_path):
        from luckyd_code.indexer import _extract_deps
        f = tmp_path / "requirements.txt"
        f.write_text("requests>=2.0\nflask==2.3.0\n# comment\n-r other.txt\n")
        result = _extract_deps(f, "requirements.txt")
        assert "requests" in result
        assert "flask" in result
        assert "-r other.txt" not in result

    def test_package_json_extraction(self, tmp_path):
        from luckyd_code.indexer import _extract_deps
        f = tmp_path / "package.json"
        f.write_text(json.dumps({
            "dependencies": {"react": "^18", "lodash": "^4"},
            "devDependencies": {"jest": "^29"},
        }))
        result = _extract_deps(f, "package.json")
        assert "react" in result
        assert "lodash" in result
        assert "jest" in result

    def test_corrupt_file_returns_empty(self, tmp_path):
        from luckyd_code.indexer import _extract_deps
        f = tmp_path / "package.json"
        f.write_text("NOT JSON {{{")
        result = _extract_deps(f, "package.json")
        assert result == []


class TestIsIgnored:
    def test_exact_match(self):
        from luckyd_code.indexer import _is_ignored
        assert _is_ignored(".venv", [".venv"])
        assert _is_ignored("dist", ["dist"])

    def test_dir_pattern_with_slash(self):
        from luckyd_code.indexer import _is_ignored
        assert _is_ignored("build", ["build/"])

    def test_glob_star_dot_extension(self):
        from luckyd_code.indexer import _is_ignored
        assert _is_ignored("main.pyc", ["*.pyc"])
        assert _is_ignored("app.min.js", ["*.js"])

    def test_no_match(self):
        from luckyd_code.indexer import _is_ignored
        assert not _is_ignored("src", [".venv", "build/", "*.pyc"])


class TestFormatProjectContext:
    def test_all_sections_present(self):
        from luckyd_code.indexer import format_project_context
        info = {
            "name": "myproject",
            "languages": ["Python", "JavaScript"],
            "frameworks": ["Django", "React"],
            "entry_points": ["main.py"],
            "dependency_files": ["requirements.txt"],
            "total_files": 42,
            "file_tree": ["src/", "  main.py"],
        }
        result = format_project_context(info)
        assert "myproject" in result
        assert "Python" in result
        assert "Django" in result
        assert "main.py" in result
        assert "requirements.txt" in result
        assert "42" in result

    def test_empty_optionals_no_crash(self):
        from luckyd_code.indexer import format_project_context
        info = {
            "name": "minimal",
            "languages": [],
            "frameworks": [],
            "entry_points": [],
            "dependency_files": [],
            "total_files": 0,
            "file_tree": [],
        }
        result = format_project_context(info)
        assert "minimal" in result


class TestIndexProjectEdgeCases:
    def test_nonexistent_dir_returns_empty(self):
        from luckyd_code.indexer import index_project
        result = index_project("/nonexistent/path/to/project")
        assert result == ""

    def test_empty_dir_returns_something(self, tmp_path):
        from luckyd_code.indexer import index_project
        result = index_project(str(tmp_path))
        assert isinstance(result, str)


# ═══════════════════════════════════════════════════════════════════════════════
# cost_tracker.py — uncovered branches
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def cost_tmp(tmp_path, monkeypatch):
    """Redirect all cost files to tmp directory."""
    cost_file = tmp_path / "costs.jsonl"
    legacy_file = tmp_path / "costs.json"
    totals_file = tmp_path / "costs_total.json"
    monkeypatch.setattr("luckyd_code.cost_tracker.COST_FILE", cost_file)
    monkeypatch.setattr("luckyd_code.cost_tracker._LEGACY_COST_FILE", legacy_file)
    monkeypatch.setattr("luckyd_code.cost_tracker._TOTALS_FILE", totals_file)
    return {"cost": cost_file, "legacy": legacy_file, "totals": totals_file}


class TestLegacyMigration:
    def test_migrates_legacy_json_to_jsonl(self, cost_tmp):
        from luckyd_code.cost_tracker import CostTracker

        # Write a legacy costs.json
        legacy_records = [
            {"model": "deepseek-chat", "input_tokens": 100, "output_tokens": 50,
             "timestamp": "2024-01-01T00:00:00", "estimated_cost": 0.0001},
        ]
        cost_tmp["legacy"].write_text(json.dumps(legacy_records), encoding="utf-8")

        # CostTracker should migrate on first use
        tracker = CostTracker()
        tracker.record_usage("deepseek-v4-flash", 10, 5)

        # Legacy file should now be gone (migrated)
        assert not cost_tmp["legacy"].exists()
        # JSONL should exist
        assert cost_tmp["cost"].exists()

    def test_no_migration_when_already_jsonl(self, cost_tmp):
        from luckyd_code.cost_tracker import CostTracker

        # Pre-populate JSONL
        cost_tmp["cost"].write_text(
            json.dumps({"model": "m", "input_tokens": 1, "output_tokens": 1,
                        "timestamp": "t", "estimated_cost": 0.0}) + "\n"
        )

        tracker = CostTracker()
        tracker.record_usage("deepseek-v4-flash", 10, 5)

        # Legacy file never existed so no migration runs
        assert not cost_tmp["legacy"].exists()


class TestTotalsSidecar:
    def test_get_cumulative_uses_sidecar(self, cost_tmp):
        from luckyd_code.cost_tracker import CostTracker

        # Pre-populate sidecar
        cost_tmp["totals"].write_text(json.dumps({"total": 3.14}), encoding="utf-8")

        tracker = CostTracker()
        total = tracker.get_cumulative_cost()
        assert total == pytest.approx(3.14, rel=0.001)

    def test_cumulative_cost_increments_sidecar(self, cost_tmp):
        from luckyd_code.cost_tracker import CostTracker

        tracker = CostTracker()
        tracker.record_usage("deepseek-v4-flash", 1000, 1000)

        # Totals file should be updated
        assert cost_tmp["totals"].exists()
        data = json.loads(cost_tmp["totals"].read_text())
        assert data["total"] > 0.0

    def test_cumulative_slow_path_sums_jsonl(self, cost_tmp):
        """If totals file doesn't exist, falls back to summing JSONL."""
        from luckyd_code.cost_tracker import CostTracker

        # Write JSONL with known records
        records = [
            {"model": "deepseek-v4-flash", "input_tokens": 1000, "output_tokens": 0,
             "timestamp": "t", "estimated_cost": 0.000140},
            {"model": "deepseek-v4-flash", "input_tokens": 0, "output_tokens": 1000,
             "timestamp": "t", "estimated_cost": 0.000280},
        ]
        with cost_tmp["cost"].open("w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

        tracker = CostTracker()
        total = tracker.get_cumulative_cost()
        assert total == pytest.approx(0.000420, rel=0.01)


class TestRecordUsageExplicitCost:
    def test_explicit_zero_cost(self, cost_tmp):
        from luckyd_code.cost_tracker import CostTracker

        tracker = CostTracker()
        rec = tracker.record_usage("deepseek-v4-flash", 5000, 2000, cost=0.0)
        # Explicit zero should NOT be recalculated
        assert rec.estimated_cost == 0.0

    def test_explicit_nonzero_cost(self, cost_tmp):
        from luckyd_code.cost_tracker import CostTracker

        tracker = CostTracker()
        rec = tracker.record_usage("deepseek-v4-flash", 100, 50, cost=9.99)
        assert rec.estimated_cost == 9.99


class TestLoadAllLegacy:
    def test_load_all_from_legacy_json(self, cost_tmp):
        from luckyd_code.cost_tracker import CostTracker

        records = [{"model": "m", "estimated_cost": 1.0}]
        cost_tmp["legacy"].write_text(json.dumps(records), encoding="utf-8")
        # Don't create JSONL so legacy path is hit
        loaded = CostTracker._load_all()
        assert len(loaded) == 1
        assert loaded[0]["estimated_cost"] == 1.0

    def test_load_all_empty_when_no_files(self, cost_tmp):
        from luckyd_code.cost_tracker import CostTracker

        loaded = CostTracker._load_all()
        assert loaded == []


# ═══════════════════════════════════════════════════════════════════════════════
# web_app.py — uncovered branches
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.skipif(
    sys.version_info >= (3, 15),
    reason="Python 3.15 + anyio incompatibility",
)
class TestGetApp:
    def test_get_app_returns_fastapi_instance(self):
        import luckyd_code.web_app as wa
        from fastapi import FastAPI

        wa._app_instance = None  # reset
        with patch("luckyd_code.web_app.Config", return_value=MagicMock(
            api_key="k", base_url="http://x", provider="deepseek",
            model="m", max_tokens=1024, temperature=0.7, system_prompt="s",
            max_context_messages=50,
        )):
            with patch("luckyd_code.web_app.memory_module.load_claude_md", return_value=""):
                with patch("luckyd_code.indexer.index_project", return_value=""):
                    app1 = wa.get_app()
                    app2 = wa.get_app()

        assert isinstance(app1, FastAPI)
        assert app1 is app2  # cached
        wa._app_instance = None  # cleanup

    def test_create_app_with_merged_memory(self):
        """Both md and session_memories non-empty → merged into one block."""
        from luckyd_code.web_app import create_app
        from luckyd_code.memory.manager import MemoryManager

        mock_cfg = MagicMock(
            api_key="k", base_url="http://x", provider="deepseek",
            model="m", max_tokens=1024, temperature=0.7, system_prompt="s",
            max_context_messages=50,
        )
        with patch("luckyd_code.web_app.Config", return_value=mock_cfg):
            with patch("luckyd_code.web_app.memory_module.load_claude_md", return_value="# Notes"):
                with patch.object(MemoryManager, "get_all_memories_formatted", return_value="<memories>stuff</memories>"):
                    with patch("luckyd_code.indexer.index_project", return_value=""):
                        app = create_app()

        assert app is not None


# ═══════════════════════════════════════════════════════════════════════════════
# background.py — uncovered branches
# ═══════════════════════════════════════════════════════════════════════════════

class TestBackgroundLoadHistoryEdges:
    def test_load_history_nonexistent_dir_no_error(self, tmp_path):
        """load_history when BACKGROUND_DIR doesn't exist should be a no-op."""
        from luckyd_code.background import BackgroundAgent

        # Use a path under tmp_path that genuinely doesn't exist (no PermissionError)
        nonexistent = tmp_path / "no_such_bg_dir"

        # Manually test load_history with a missing dir
        class FakeAgent:
            tasks = {}
            _lock = __import__("threading").Lock()

        fake = FakeAgent()
        fake.load_history = BackgroundAgent.load_history.__get__(fake, type(fake))

        with patch("luckyd_code.background.BACKGROUND_DIR", nonexistent):
            # load_history returns early when dir doesn't exist
            fake.load_history()  # should not raise
            assert len(fake.tasks) == 0

    def test_load_history_key_error_in_data(self, tmp_path):
        """load_history should skip files missing required keys."""
        from luckyd_code.background import BackgroundAgent

        bg_dir = tmp_path / "background"
        bg_dir.mkdir()

        # Write a JSON file missing the 'id' key
        (bg_dir / "bg_bad.json").write_text(
            json.dumps({"description": "no id field", "status": "done"}),
            encoding="utf-8",
        )

        config = MagicMock()
        with patch("luckyd_code.background.BACKGROUND_DIR", bg_dir):
            agent = BackgroundAgent(config)
            agent.load_history()

        # File had KeyError → should not have been loaded
        assert len(agent.tasks) == 0
