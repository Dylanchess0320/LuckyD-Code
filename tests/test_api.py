"""Tests for api.py — JSON repair, SSE parsing, message filtering."""

import json
from luckyd_code.api import (
    _remove_trailing_commas,
    _repair_json,
    _parse_sse_line,
    _filter_messages,
    _classify_http_error,
)
from luckyd_code.retry import RetryableError, NonRetryableError, ModelNotFoundError


# ── _remove_trailing_commas ────────────────────────────────────────

class TestRemoveTrailingCommas:
    """Character-level comma stripping with string-literal awareness."""

    # ── basic functionality ──

    def test_simple_object(self):
        assert _remove_trailing_commas('{"a": 1,}') == '{"a": 1}'

    def test_simple_array(self):
        assert _remove_trailing_commas('[1, 2,]') == '[1, 2]'

    def test_nested_mixed(self):
        result = _remove_trailing_commas('{"x": [1, 2,], "y": 3,}')
        assert result == '{"x": [1, 2], "y": 3}'

    def test_no_trailing_commas(self):
        assert _remove_trailing_commas('{"a": 1}') == '{"a": 1}'
        assert _remove_trailing_commas('[1, 2]') == '[1, 2]'

    def test_multiple_trailing_commas_consecutive(self):
        # ",," before ] — only the last comma (before ]) is removed
        result = _remove_trailing_commas('[1,,]')
        assert result == '[1,]'

    # ── string awareness ──

    def test_comma_inside_string_preserved(self):
        # The }, inside a string looks like a closing brace but must stay
        text = '{"pattern": "],",}'
        result = _remove_trailing_commas(text)
        assert result == '{"pattern": "],"}'  # trailing comma after string removed
        assert '],"' in result  # the literal inside the string is untouched

    def test_brace_inside_string_not_confused(self):
        # A string containing }]] should not confuse the parser
        text = '{"a": "[1, 2,]", "b": 3}'
        result = _remove_trailing_commas(text)
        # No trailing comma to strip here — string commas must stay
        assert result == text

    def test_escaped_quote_inside_string(self):
        """Backslash-escaped quotes do not terminate the string."""
        # The comma after the string (before }) should be removed
        text = '{"val": "te\\"xt",}'
        result = _remove_trailing_commas(text)
        assert result == '{"val": "te\\"xt"}'
        assert 'te\\"xt' in result  # escape sequence preserved

    def test_double_backslash_before_quote(self):
        """`\\\\"` is an escaped backslash then a real quote — string ends."""
        text = '{"val": "foo\\\\", "next": 2}'
        result = _remove_trailing_commas(text)
        assert result == text  # nothing to strip

    # ── whitespace handling ──

    def test_whitespace_before_closing_brace(self):
        assert _remove_trailing_commas('{"a": 1,\n  }') == '{"a": 1\n  }'

    def test_whitespace_before_closing_bracket(self):
        assert _remove_trailing_commas('[1, 2, \t ]') == '[1, 2 \t ]'

    # ── edge cases ──

    def test_empty_string(self):
        assert _remove_trailing_commas('') == ''

    def test_only_comma(self):
        assert _remove_trailing_commas(',') == ','

    def test_comma_then_brace(self):
        assert _remove_trailing_commas(',}') == '}'

    def test_single_value_object(self):
        assert _remove_trailing_commas('{"key": "value"}') == '{"key": "value"}'


# ── _repair_json ───────────────────────────────────────────────────

class TestRepairJson:
    """Full JSON repair pipeline (strips commas + closes unclosed brackets)."""

    def test_strip_trailing_comma_delegates(self):
        result = _repair_json('{"a": 1,}')
        assert result == '{"a": 1}'

    def test_close_unmatched_brace(self):
        result = _repair_json('{"a": {"b": 2}')
        assert result.count('{') == result.count('}')

    def test_close_unmatched_bracket(self):
        result = _repair_json('["a", ["b"')
        assert result.count('[') == result.count(']')

    def test_multiple_unmatched(self):
        result = _repair_json('{"a": {"b": [1, 2')
        expected_brace = 2  # original two {
        expected_bracket = 1  # original one [
        assert result.count('}') == expected_brace
        assert result.count(']') == expected_bracket

    def test_strip_empty_input(self):
        assert _repair_json('  ') == ''


# ── _parse_sse_line ────────────────────────────────────────────────

class TestParseSSELine:
    """Server-Sent Events line parsing."""

    def test_empty_line(self):
        assert _parse_sse_line('') is None
        assert _parse_sse_line('   ') is None

    def test_done_signal(self):
        assert _parse_sse_line('data: [DONE]') == {}

    def test_valid_data_line(self):
        payload = json.dumps({"choices": [{"delta": {"content": "hello"}}]})
        result = _parse_sse_line(f'data: {payload}')
        assert result is not None
        assert result["choices"][0]["delta"]["content"] == "hello"

    def test_data_with_leading_whitespace(self):
        """The real API sometimes has a leading space after 'data:'."""
        payload = json.dumps({"foo": "bar"})
        result = _parse_sse_line(f'data: {payload}')
        assert result is not None
        assert result["foo"] == "bar"

    def test_invalid_json(self):
        assert _parse_sse_line('data: {not valid}') is None

    def test_not_data_prefix(self):
        assert _parse_sse_line('event: message') is None
        assert _parse_sse_line(':heartbeat') is None

    def test_data_only_prefix_no_payload(self):
        # 'data: ' with nothing after maps to '' which json.loads rejects
        assert _parse_sse_line('data: ') is None

    def test_usage_chunk(self):
        """Some providers send usage info via SSE."""
        payload = json.dumps({"choices": [], "usage": {"total_tokens": 42}})
        result = _parse_sse_line(f'data: {payload}')
        assert result is not None
        assert result["usage"]["total_tokens"] == 42


# ── _filter_messages ───────────────────────────────────────────────

class TestFilterMessages:
    """Ensures reasoning_content messages always have a content field."""

    def test_no_reasoning_messages_unchanged(self):
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]
        result = _filter_messages(msgs)
        assert result == msgs

    def test_reasoning_with_null_content(self):
        msgs = [
            {"role": "assistant", "reasoning_content": "Let me think...",
             "content": None},
        ]
        result = _filter_messages(msgs)
        assert result[0]["content"] == ""
        assert result[0]["reasoning_content"] == "Let me think..."

    def test_reasoning_without_content_key(self):
        msgs = [
            {"role": "assistant", "reasoning_content": "thinking..."},
        ]
        result = _filter_messages(msgs)
        assert result[0]["content"] == ""
        assert result[0]["reasoning_content"] == "thinking..."

    def test_reasoning_with_existing_content(self):
        msgs = [
            {"role": "assistant", "reasoning_content": "hmm",
             "content": "the answer"},
        ]
        result = _filter_messages(msgs)
        assert result[0]["content"] == "the answer"  # not overwritten

    def test_non_assistant_reasoning_ignored(self):
        """Only assistant role gets the fix; user messages are unchanged."""
        msgs = [
            {"role": "user", "reasoning_content": "user thought",
             "content": None},
        ]
        result = _filter_messages(msgs)
        # User messages are NOT patched
        assert result[0]["content"] is None

    def test_multiple_messages_mixed(self):
        msgs = [
            {"role": "user", "content": "q"},
            {"role": "assistant", "reasoning_content": "t1"},
            {"role": "assistant", "content": "a1"},
            {"role": "assistant", "reasoning_content": "t2", "content": None},
        ]
        result = _filter_messages(msgs)
        assert result[0]["content"] == "q"       # user untouched
        assert result[1]["content"] == ""          # missing → ''
        assert result[2]["content"] == "a1"        # existing stays
        assert result[3]["content"] == ""          # None → ''


# ── _classify_http_error ───────────────────────────────────────────

class TestClassifyHTTPError:
    """HTTP status → exception type mapping."""

    def test_400_model_not_found(self):
        exc = _classify_http_error(400, "model not exist: deepseek-v99")
        assert isinstance(exc, ModelNotFoundError)

    def test_400_other(self):
        exc = _classify_http_error(400, "bad request param")
        assert isinstance(exc, NonRetryableError)

    def test_401_auth(self):
        exc = _classify_http_error(401, "invalid token")
        assert isinstance(exc, NonRetryableError)

    def test_403_forbidden(self):
        exc = _classify_http_error(403, "no access")
        assert isinstance(exc, NonRetryableError)

    def test_404_not_found(self):
        exc = _classify_http_error(404, "endpoint gone")
        assert isinstance(exc, NonRetryableError)

    def test_422_unprocessable(self):
        exc = _classify_http_error(422, "validation")
        assert isinstance(exc, NonRetryableError)

    def test_429_rate_limit(self):
        exc = _classify_http_error(429, "too many requests")
        assert isinstance(exc, RetryableError)

    def test_500_server_error(self):
        exc = _classify_http_error(500, "internal error")
        assert isinstance(exc, RetryableError)

    def test_502_bad_gateway(self):
        exc = _classify_http_error(502, "bad gateway")
        assert isinstance(exc, RetryableError)

    def test_503_unavailable(self):
        exc = _classify_http_error(503, "service unavailable")
        assert isinstance(exc, RetryableError)
