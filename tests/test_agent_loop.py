"""Tests for luckyd_code._agent_loop — helpers, RunConfig, LoopResult, run_agent_loop."""

from __future__ import annotations

import hashlib
from collections import deque
from unittest.mock import MagicMock, patch, call

import pytest

from luckyd_code._agent_loop import (
    RunConfig,
    LoopResult,
    _truncate_tool_result,
    _tool_call_hash,
    _verify_write,
    _escalate_model,
    run_agent_loop,
    _MAX_TOOL_RESULT_CHARS,
    _STUCK_WINDOW,
)
from luckyd_code.context import ConversationContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(model="deepseek-v4-flash"):
    cfg = MagicMock()
    cfg.model = model
    cfg.api_key = "sk-test"
    cfg.base_url = "https://api.deepseek.com/v1"
    cfg.max_tokens = 1024
    cfg.temperature = 0.7
    cfg.system_prompt = "You are a test assistant."
    return cfg


def _make_registry(result="tool result"):
    reg = MagicMock()
    reg.list_tools.return_value = []
    reg.execute.return_value = result
    return reg


def _done_stream(text="done"):
    """Single-turn done event — no tools."""
    yield ("done", (text, ""))


def _tool_then_done(tool_result_text="answer"):
    """First call emits tool_calls, second emits done."""
    call_count = [0]

    def _gen(*args, **kwargs):
        if call_count[0] == 0:
            call_count[0] += 1
            yield ("tool_calls", (
                [{"id": "tc1", "type": "function",
                  "function": {"name": "Read", "arguments": '{"path": "a.py"}'}}],
                "",
            ))
        else:
            yield ("done", (tool_result_text, ""))

    return _gen


# ===========================================================================
# _truncate_tool_result
# ===========================================================================

class TestTruncateToolResult:
    def test_short_result_unchanged(self):
        text = "short result"
        assert _truncate_tool_result(text) == text

    def test_long_result_is_truncated(self):
        text = "x" * (_MAX_TOOL_RESULT_CHARS + 1000)
        result = _truncate_tool_result(text)
        assert len(result) < len(text)

    def test_truncation_marker_present(self):
        text = "x" * (_MAX_TOOL_RESULT_CHARS + 1000)
        result = _truncate_tool_result(text)
        assert "trimmed" in result

    def test_exact_limit_unchanged(self):
        text = "y" * _MAX_TOOL_RESULT_CHARS
        assert _truncate_tool_result(text) == text

    def test_head_and_tail_preserved(self):
        head = "HEADER"
        tail = "FOOTER"
        padding = "x" * (_MAX_TOOL_RESULT_CHARS + 5000)
        text = head + padding + tail
        result = _truncate_tool_result(text)
        assert head in result
        assert tail in result


# ===========================================================================
# _tool_call_hash
# ===========================================================================

class TestToolCallHash:
    def _make_tc(self, name, args):
        return {"function": {"name": name, "arguments": args}}

    def test_same_call_same_hash(self):
        tc = self._make_tc("Read", '{"path": "a.py"}')
        assert _tool_call_hash(tc) == _tool_call_hash(tc)

    def test_different_name_different_hash(self):
        tc1 = self._make_tc("Read", '{"path": "a.py"}')
        tc2 = self._make_tc("Write", '{"path": "a.py"}')
        assert _tool_call_hash(tc1) != _tool_call_hash(tc2)

    def test_different_args_different_hash(self):
        tc1 = self._make_tc("Read", '{"path": "a.py"}')
        tc2 = self._make_tc("Read", '{"path": "b.py"}')
        assert _tool_call_hash(tc1) != _tool_call_hash(tc2)

    def test_returns_string(self):
        tc = self._make_tc("Glob", '{"pattern": "*.py"}')
        assert isinstance(_tool_call_hash(tc), str)

    def test_empty_function_block(self):
        tc = {"function": {}}
        result = _tool_call_hash(tc)
        assert isinstance(result, str)


# ===========================================================================
# _verify_write
# ===========================================================================

class TestVerifyWrite:
    def test_existing_file_returns_none(self, tmp_path):
        f = tmp_path / "ok.py"
        f.write_text("x = 1")
        assert _verify_write(str(f)) is None

    def test_missing_file_returns_error(self, tmp_path):
        result = _verify_write(str(tmp_path / "nonexistent.py"))
        assert result is not None
        assert "not found" in result

    def test_empty_file_returns_error(self, tmp_path):
        f = tmp_path / "empty.py"
        f.write_text("")
        result = _verify_write(str(f))
        assert result is not None
        assert "empty" in result.lower()


# ===========================================================================
# _escalate_model
# ===========================================================================

class TestEscalateModel:
    def test_known_model_escalates(self):
        from luckyd_code._agent_loop import _ESCALATION_LADDER
        if len(_ESCALATION_LADDER) < 2:
            pytest.skip("Escalation ladder has fewer than 2 models")
        first = _ESCALATION_LADDER[0]
        result = _escalate_model(first)
        assert result == _ESCALATION_LADDER[1]

    def test_top_model_returns_none(self):
        from luckyd_code._agent_loop import _ESCALATION_LADDER
        if not _ESCALATION_LADDER:
            pytest.skip("Escalation ladder is empty")
        top = _ESCALATION_LADDER[-1]
        assert _escalate_model(top) is None

    def test_unknown_model_returns_none(self):
        assert _escalate_model("not-a-real-model-xyz") is None


# ===========================================================================
# RunConfig
# ===========================================================================

class TestRunConfig:
    def test_defaults(self):
        rc = RunConfig()
        assert rc.max_turns == 8
        assert rc.label == "agent"
        assert rc.verify_edits is False
        assert rc.run_tests is False
        assert rc.auto_save_memory is True
        assert rc.on_text is None
        assert rc.on_tool_start is None
        assert rc.on_tool_end is None
        assert rc.on_verify is None
        assert rc.memory_manager is None
        assert rc.user_memory is None

    def test_custom_values(self):
        cb = lambda x: x
        rc = RunConfig(
            max_turns=20,
            label="coder",
            verify_edits=True,
            run_tests=True,
            on_text=cb,
        )
        assert rc.max_turns == 20
        assert rc.label == "coder"
        assert rc.verify_edits is True
        assert rc.run_tests is True
        assert rc.on_text is cb

    def test_project_root_default_empty(self):
        rc = RunConfig()
        assert rc.project_root == ""

    def test_test_runner_cmd_default_none(self):
        rc = RunConfig()
        assert rc.test_runner_cmd is None


# ===========================================================================
# LoopResult
# ===========================================================================

class TestLoopResult:
    def test_defaults(self):
        r = LoopResult()
        assert r.text == ""
        assert r.tool_calls_executed == 0
        assert r.files_modified == []
        assert r.verification_passed is True
        assert r.escalated_model is None

    def test_mutable_list_per_instance(self):
        r1 = LoopResult()
        r2 = LoopResult()
        r1.files_modified.append("a.py")
        assert r2.files_modified == []


# ===========================================================================
# run_agent_loop — core behaviour
# ===========================================================================

class TestRunAgentLoop:
    """All API calls mocked via stream_chat patch."""

    def _ctx(self, msg="do something"):
        ctx = ConversationContext("system prompt")
        ctx.add_user_message(msg)
        return ctx

    def test_simple_done_returns_text(self):
        ctx = self._ctx()
        cfg = _make_config()
        reg = _make_registry()

        with patch("luckyd_code._agent_loop.stream_chat", return_value=_done_stream("hello")):
            with patch("luckyd_code._agent_loop.MemoryManager"):
                with patch("luckyd_code._agent_loop.get_user_memory"):
                    result = run_agent_loop(ctx, cfg, [], reg)

        assert result == "hello"

    def test_no_response_fallback(self):
        ctx = self._ctx()
        cfg = _make_config()
        reg = _make_registry()

        with patch("luckyd_code._agent_loop.stream_chat", return_value=_done_stream("")):
            with patch("luckyd_code._agent_loop.MemoryManager"):
                with patch("luckyd_code._agent_loop.get_user_memory"):
                    result = run_agent_loop(ctx, cfg, [], reg)

        assert "no response" in result

    def test_api_error_returns_error_string(self):
        def _err(*args, **kwargs):
            yield ("error", "network timeout")

        ctx = self._ctx()
        cfg = _make_config()
        reg = _make_registry()

        with patch("luckyd_code._agent_loop.stream_chat", return_value=_err()):
            with patch("luckyd_code._agent_loop.MemoryManager"):
                with patch("luckyd_code._agent_loop.get_user_memory"):
                    result = run_agent_loop(ctx, cfg, [], reg)

        assert "Error" in result

    def test_single_tool_call_then_done(self):
        gen = _tool_then_done("final answer")
        call_count = [0]

        def _stream(*args, **kwargs):
            if call_count[0] == 0:
                call_count[0] += 1
                yield ("tool_calls", (
                    [{"id": "tc1", "type": "function",
                      "function": {"name": "Read", "arguments": '{"path": "a.py"}'}}],
                    "",
                ))
            else:
                yield ("done", ("final answer", ""))

        ctx = self._ctx()
        cfg = _make_config()
        reg = _make_registry("file contents")

        with patch("luckyd_code._agent_loop.stream_chat", side_effect=_stream):
            with patch("luckyd_code._agent_loop.MemoryManager"):
                with patch("luckyd_code._agent_loop.get_user_memory"):
                    result = run_agent_loop(ctx, cfg, [], reg)

        assert result == "final answer"
        assert reg.execute.called

    def test_tool_executed_with_correct_args(self):
        call_count = [0]

        def _stream(*args, **kwargs):
            if call_count[0] == 0:
                call_count[0] += 1
                yield ("tool_calls", (
                    [{"id": "tc1", "type": "function",
                      "function": {"name": "Grep", "arguments": '{"pattern": "TODO"}'}}],
                    "",
                ))
            else:
                yield ("done", ("done", ""))

        ctx = self._ctx()
        cfg = _make_config()
        reg = _make_registry("grep results")

        with patch("luckyd_code._agent_loop.stream_chat", side_effect=_stream):
            with patch("luckyd_code._agent_loop.MemoryManager"):
                with patch("luckyd_code._agent_loop.get_user_memory"):
                    run_agent_loop(ctx, cfg, [], reg)

        reg.execute.assert_called_once_with("Grep", {"pattern": "TODO"})

    def test_max_turns_respected(self):
        """If tool calls keep coming, loop stops at max_turns."""
        call_count = [0]

        def _always_tool(*args, **kwargs):
            call_count[0] += 1
            yield ("tool_calls", (
                [{"id": f"tc{call_count[0]}", "type": "function",
                  "function": {"name": "Read", "arguments": '{"path": "x.py"}'}}],
                "",
            ))

        ctx = self._ctx()
        cfg = _make_config()
        reg = _make_registry("content")

        with patch("luckyd_code._agent_loop.stream_chat", side_effect=_always_tool):
            with patch("luckyd_code._agent_loop.MemoryManager"):
                with patch("luckyd_code._agent_loop.get_user_memory"):
                    result = run_agent_loop(ctx, cfg, [], reg, max_turns=3)

        # Should have stopped — result should be the fallback "no response"
        assert isinstance(result, str)
        assert call_count[0] <= 3 + 1  # max_turns + stuck detection

    def test_on_text_callback_called(self):
        received = []

        def _stream(*args, **kwargs):
            yield ("text", "chunk1")
            yield ("text", "chunk2")
            yield ("done", ("chunk1chunk2", ""))

        ctx = self._ctx()
        cfg = _make_config()
        reg = _make_registry()

        rc = RunConfig(on_text=received.append, auto_save_memory=False)

        with patch("luckyd_code._agent_loop.stream_chat", return_value=_stream()):
            with patch("luckyd_code._agent_loop.MemoryManager"):
                with patch("luckyd_code._agent_loop.get_user_memory"):
                    run_agent_loop(ctx, cfg, [], reg, run_config=rc)

        assert "chunk1" in received
        assert "chunk2" in received

    def test_on_tool_start_callback(self):
        started = []
        call_count = [0]

        def _stream(*args, **kwargs):
            if call_count[0] == 0:
                call_count[0] += 1
                yield ("tool_calls", (
                    [{"id": "tc1", "type": "function",
                      "function": {"name": "Read", "arguments": '{"path": "f.py"}'}}],
                    "",
                ))
            else:
                yield ("done", ("done", ""))

        def _on_start(name, idx, total):
            started.append(name)

        ctx = self._ctx()
        cfg = _make_config()
        reg = _make_registry()
        rc = RunConfig(on_tool_start=_on_start, auto_save_memory=False)

        with patch("luckyd_code._agent_loop.stream_chat", side_effect=_stream):
            with patch("luckyd_code._agent_loop.MemoryManager"):
                with patch("luckyd_code._agent_loop.get_user_memory"):
                    run_agent_loop(ctx, cfg, [], reg, run_config=rc)

        assert "Read" in started

    def test_invalid_json_tool_args_handled(self):
        call_count = [0]

        def _stream(*args, **kwargs):
            if call_count[0] == 0:
                call_count[0] += 1
                yield ("tool_calls", (
                    [{"id": "tc1", "type": "function",
                      "function": {"name": "Read", "arguments": "NOT JSON {"}}],
                    "",
                ))
            else:
                yield ("done", ("recovered", ""))

        ctx = self._ctx()
        cfg = _make_config()
        reg = _make_registry("fallback")

        with patch("luckyd_code._agent_loop.stream_chat", side_effect=_stream):
            with patch("luckyd_code._agent_loop.MemoryManager"):
                with patch("luckyd_code._agent_loop.get_user_memory"):
                    result = run_agent_loop(ctx, cfg, [], reg)

        assert isinstance(result, str)

    def test_auto_save_memory_disabled(self):
        ctx = self._ctx()
        cfg = _make_config()
        reg = _make_registry()
        rc = RunConfig(auto_save_memory=False)

        with patch("luckyd_code._agent_loop.stream_chat", return_value=_done_stream("ok")):
            with patch("luckyd_code._agent_loop.MemoryManager") as mock_mm:
                result = run_agent_loop(ctx, cfg, [], reg, run_config=rc)

        # MemoryManager should NOT have been instantiated
        mock_mm.assert_not_called()
        assert result == "ok"


# ===========================================================================
# Stuck-loop detection
# ===========================================================================

class TestStuckLoopDetection:
    def test_stuck_loop_breaks_out(self):
        """Same tool call repeated _STUCK_WINDOW times should break the loop."""
        call_count = [0]

        def _always_same_tool(*args, **kwargs):
            call_count[0] += 1
            yield ("tool_calls", (
                [{"id": "tc1", "type": "function",
                  "function": {"name": "Read", "arguments": '{"path": "same.py"}'}}],
                "",
            ))

        ctx = ConversationContext("sys")
        ctx.add_user_message("read the file")
        cfg = _make_config()
        reg = _make_registry("content")

        with patch("luckyd_code._agent_loop.stream_chat", side_effect=_always_same_tool):
            with patch("luckyd_code._agent_loop.MemoryManager"):
                with patch("luckyd_code._agent_loop.get_user_memory"):
                    result = run_agent_loop(ctx, cfg, [], reg, max_turns=20)

        # Should have broken out before hitting max_turns
        assert call_count[0] <= _STUCK_WINDOW + 2
        assert isinstance(result, str)


# ===========================================================================
# run_agent_loop with run_config label
# ===========================================================================

class TestRunConfigLabel:
    def test_error_message_includes_label(self):
        def _err(*args, **kwargs):
            yield ("error", "timeout")

        ctx = ConversationContext("sys")
        ctx.add_user_message("task")
        cfg = _make_config()
        reg = _make_registry()
        rc = RunConfig(label="researcher", auto_save_memory=False)

        with patch("luckyd_code._agent_loop.stream_chat", return_value=_err()):
            result = run_agent_loop(ctx, cfg, [], reg, run_config=rc)

        assert "researcher" in result
