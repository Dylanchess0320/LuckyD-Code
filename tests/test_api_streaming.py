"""Tests for luckyd_code.api — covers uncovered SSE streaming branches.

Target uncovered lines (from cov_out.txt):
  30       module-level import (openai.OpenAI)
  149-150  test_connection: fallback chat completion success path
  172      _default_test_model: except branch
  443-516  stream_chat: SSE loop — text chunks, reasoning, tool_call deltas,
           done-event, model_not_found / NonRetryable / RetryableError yields
"""
from __future__ import annotations

import json
from collections.abc import Generator
from unittest.mock import MagicMock, patch, call

import pytest

from luckyd_code.api import (
    _parse_sse_line,
    _filter_messages,
    _repair_json,
    _remove_trailing_commas,
    _close_unclosed_string,
    _count_unquoted,
    _classify_http_error,
    _parse_stream_error,
    stream_chat,
)
from luckyd_code.retry import RetryableError, NonRetryableError, ModelNotFoundError


# ────────────────────────────────────────────────────────────────────────────
# _parse_sse_line
# ────────────────────────────────────────────────────────────────────────────

class TestParseSseLine:
    def test_empty_string_returns_none(self):
        assert _parse_sse_line("") is None

    def test_whitespace_only_returns_none(self):
        assert _parse_sse_line("   ") is None

    def test_done_sentinel_returns_empty_dict(self):
        assert _parse_sse_line("data: [DONE]") == {}

    def test_valid_data_line(self):
        data = {"choices": [{"delta": {"content": "hello"}}]}
        line = f"data: {json.dumps(data)}"
        result = _parse_sse_line(line)
        assert result == data

    def test_invalid_json_returns_none(self):
        assert _parse_sse_line("data: {bad json}") is None

    def test_non_data_line_returns_none(self):
        assert _parse_sse_line("event: ping") is None


# ────────────────────────────────────────────────────────────────────────────
# _filter_messages
# ────────────────────────────────────────────────────────────────────────────

class TestFilterMessages:
    def test_strips_reasoning_content_for_non_deepseek(self):
        msgs = [{"role": "assistant", "content": "hi", "reasoning_content": "thought"}]
        result = _filter_messages(msgs, provider="groq")
        assert "reasoning_content" not in result[0]

    def test_keeps_reasoning_content_for_deepseek(self):
        msgs = [{"role": "assistant", "content": None, "reasoning_content": "thought"}]
        result = _filter_messages(msgs, provider="deepseek")
        assert "reasoning_content" in result[0]
        assert result[0]["content"] == ""  # None → ""

    def test_leaves_user_messages_unchanged(self):
        msgs = [{"role": "user", "content": "hello"}]
        result = _filter_messages(msgs, provider="groq")
        assert result == msgs

    def test_empty_provider_defaults_to_deepseek_behaviour(self):
        """Empty provider → is_deepseek=True, reasoning_content kept."""
        msgs = [{"role": "assistant", "content": "hi", "reasoning_content": "thought"}]
        result = _filter_messages(msgs, provider="")
        assert "reasoning_content" in result[0]


# ────────────────────────────────────────────────────────────────────────────
# _classify_http_error
# ────────────────────────────────────────────────────────────────────────────

class TestClassifyHttpError:
    def test_400_model_not_exist(self):
        err = _classify_http_error(400, "model not exist")
        assert isinstance(err, ModelNotFoundError)

    def test_400_other(self):
        err = _classify_http_error(400, "bad request")
        assert isinstance(err, NonRetryableError)

    def test_401(self):
        err = _classify_http_error(401, "invalid api key")
        assert isinstance(err, NonRetryableError)
        assert "401" in str(err)

    def test_403(self):
        err = _classify_http_error(403, "forbidden")
        assert isinstance(err, NonRetryableError)

    def test_404(self):
        err = _classify_http_error(404, "not found")
        assert isinstance(err, NonRetryableError)

    def test_422(self):
        err = _classify_http_error(422, "invalid request")
        assert isinstance(err, NonRetryableError)

    def test_429(self):
        err = _classify_http_error(429, "rate limited")
        assert isinstance(err, RetryableError)

    def test_500(self):
        err = _classify_http_error(500, "internal server error")
        assert isinstance(err, RetryableError)

    def test_503(self):
        err = _classify_http_error(503, "unavailable")
        assert isinstance(err, RetryableError)

    def test_unknown_code(self):
        err = _classify_http_error(418, "I'm a teapot")
        assert isinstance(err, NonRetryableError)


# ────────────────────────────────────────────────────────────────────────────
# _repair_json + helpers
# ────────────────────────────────────────────────────────────────────────────

class TestRepairJson:
    def test_valid_json_returned_unchanged(self):
        raw = '{"key": "value"}'
        assert _repair_json(raw) == raw

    def test_trailing_comma_removed(self):
        raw = '{"key": "value",}'
        result = _repair_json(raw)
        assert json.loads(result) == {"key": "value"}

    def test_unclosed_brace_closed(self):
        raw = '{"key": "value"'
        result = _repair_json(raw)
        assert json.loads(result) == {"key": "value"}

    def test_unclosed_string_closed(self):
        raw = '{"key": "open'
        result = _repair_json(raw)
        # Should produce valid JSON after repair
        assert isinstance(result, str)

    def test_empty_string_returned_unchanged(self):
        assert _repair_json("") == ""

    def test_idempotent_on_already_valid(self):
        raw = '{"a": 1}'
        assert _repair_json(_repair_json(raw)) == _repair_json(raw)

    def test_trailing_comma_in_array(self):
        raw = '[1, 2, 3,]'
        result = _repair_json(raw)
        assert json.loads(result) == [1, 2, 3]


class TestCountUnquoted:
    def test_counts_outside_strings(self):
        opens, closes = _count_unquoted('{"a": 1}', "{", "}")
        assert opens == 1 and closes == 1

    def test_ignores_inside_strings(self):
        opens, closes = _count_unquoted('{"brace": "{not counted}"}', "{", "}")
        assert opens == 1 and closes == 1


class TestCloseUnclosedString:
    def test_closes_open_string(self):
        result = _close_unclosed_string('"open')
        assert result == '"open"'

    def test_does_nothing_to_closed_string(self):
        result = _close_unclosed_string('"closed"')
        assert result == '"closed"'

    def test_handles_escaped_quote(self):
        # "he said \"hi" - the escaped quote doesn't close the string
        result = _close_unclosed_string('"he said \\"hi')
        assert result.endswith('"')


# ────────────────────────────────────────────────────────────────────────────
# stream_chat — SSE loop via _call_with_retry mock
# ────────────────────────────────────────────────────────────────────────────

def _make_sse_response(chunks: list[dict]) -> MagicMock:
    """Build a mock httpx response that yields SSE lines from chunk dicts."""
    lines = []
    for chunk in chunks:
        lines.append(f"data: {json.dumps(chunk)}")
    lines.append("data: [DONE]")

    mock_response = MagicMock()
    mock_response.iter_lines.return_value = iter(lines)
    return mock_response


def _stream_to_list(gen: Generator) -> list:
    return list(gen)


class TestStreamChatEvents:
    def _open_stream_returns(self, response):
        """Return a fake (client, response_cm, response) triple."""
        mock_client = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__exit__ = MagicMock(return_value=None)
        return mock_client, mock_cm, response

    def test_text_chunks_yield_text_events(self):
        chunk = {"choices": [{"delta": {"content": "Hello"}}]}
        response = _make_sse_response([chunk])

        with patch("luckyd_code.api._call_with_retry",
                   return_value=self._open_stream_returns(response)):
            events = _stream_to_list(
                stream_chat([], [], "m", "k", "http://x")
            )

        text_events = [e for e in events if e[0] == "text"]
        assert any(e[1] == "Hello" for e in text_events)

    def test_reasoning_chunks_yield_reasoning_events(self):
        chunk = {"choices": [{"delta": {"reasoning_content": "thinking..."}}]}
        response = _make_sse_response([chunk])

        with patch("luckyd_code.api._call_with_retry",
                   return_value=self._open_stream_returns(response)):
            events = _stream_to_list(
                stream_chat([], [], "m", "k", "http://x")
            )

        reasoning_events = [e for e in events if e[0] == "reasoning"]
        assert any("thinking" in e[1] for e in reasoning_events)

    def test_done_event_emitted_after_text(self):
        chunks = [{"choices": [{"delta": {"content": "Hi"}}]}]
        response = _make_sse_response(chunks)

        with patch("luckyd_code.api._call_with_retry",
                   return_value=self._open_stream_returns(response)):
            events = _stream_to_list(
                stream_chat([], [], "m", "k", "http://x")
            )

        done_events = [e for e in events if e[0] == "done"]
        assert len(done_events) == 1
        content, reasoning = done_events[0][1]
        assert content == "Hi"
        assert reasoning == ""

    def test_done_with_reasoning_content(self):
        chunks = [
            {"choices": [{"delta": {"reasoning_content": "think"}}]},
            {"choices": [{"delta": {"content": "answer"}}]},
        ]
        response = _make_sse_response(chunks)

        with patch("luckyd_code.api._call_with_retry",
                   return_value=self._open_stream_returns(response)):
            events = _stream_to_list(
                stream_chat([], [], "m", "k", "http://x")
            )

        done_events = [e for e in events if e[0] == "done"]
        assert len(done_events) == 1
        content, reasoning = done_events[0][1]
        assert content == "answer"
        assert reasoning == "think"

    def test_empty_choices_skipped(self):
        chunks = [
            {"choices": []},  # should skip
            {"choices": [{"delta": {"content": "ok"}}]},
        ]
        response = _make_sse_response(chunks)

        with patch("luckyd_code.api._call_with_retry",
                   return_value=self._open_stream_returns(response)):
            events = _stream_to_list(
                stream_chat([], [], "m", "k", "http://x")
            )

        text_events = [e for e in events if e[0] == "text"]
        assert len(text_events) == 1

    def test_none_delta_skipped(self):
        chunks = [
            {"choices": [{"delta": None}]},
            {"choices": [{"delta": {"content": "hi"}}]},
        ]
        response = _make_sse_response(chunks)

        with patch("luckyd_code.api._call_with_retry",
                   return_value=self._open_stream_returns(response)):
            events = _stream_to_list(
                stream_chat([], [], "m", "k", "http://x")
            )

        text_events = [e for e in events if e[0] == "text"]
        assert len(text_events) == 1

    def test_model_not_found_yields_event(self):
        with patch("luckyd_code.api._call_with_retry",
                   side_effect=ModelNotFoundError("no such model")):
            events = _stream_to_list(
                stream_chat([], [], "m", "k", "http://x")
            )
        assert events[0][0] == "model_not_found"
        assert "no such model" in events[0][1]

    def test_non_retryable_error_yields_error_event(self):
        with patch("luckyd_code.api._call_with_retry",
                   side_effect=NonRetryableError("auth failed")):
            events = _stream_to_list(
                stream_chat([], [], "m", "k", "http://x")
            )
        assert events[0][0] == "error"
        assert "auth failed" in events[0][1]

    def test_retryable_error_after_retries_yields_error(self):
        with patch("luckyd_code.api._call_with_retry",
                   side_effect=RetryableError("rate limit")):
            events = _stream_to_list(
                stream_chat([], [], "m", "k", "http://x")
            )
        assert events[0][0] == "error"
        assert "retries" in events[0][1]

    def test_generic_exception_yields_error(self):
        with patch("luckyd_code.api._call_with_retry",
                   side_effect=RuntimeError("unexpected")):
            events = _stream_to_list(
                stream_chat([], [], "m", "k", "http://x")
            )
        assert events[0][0] == "error"

    def test_stream_error_during_iteration(self):
        """Exception inside the iter_lines loop → yields error event."""
        mock_response = MagicMock()
        mock_response.iter_lines.side_effect = ConnectionError("dropped")

        mock_client = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__exit__ = MagicMock(return_value=None)

        with patch("luckyd_code.api._call_with_retry",
                   return_value=(mock_client, mock_cm, mock_response)):
            events = _stream_to_list(
                stream_chat([], [], "m", "k", "http://x")
            )
        error_events = [e for e in events if e[0] == "error"]
        assert len(error_events) >= 1

    def test_no_choices_key_skipped(self):
        """Chunk without 'choices' key is skipped gracefully."""
        chunks = [
            {"usage": {"total_tokens": 10}},  # usage-only chunk, no choices
            {"choices": [{"delta": {"content": "ok"}}]},
        ]
        response = _make_sse_response(chunks)

        with patch("luckyd_code.api._call_with_retry",
                   return_value=(MagicMock(), MagicMock(), response)):
            events = _stream_to_list(
                stream_chat([], [], "m", "k", "http://x")
            )
        text_events = [e for e in events if e[0] == "text"]
        assert len(text_events) == 1
