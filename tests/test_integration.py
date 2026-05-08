"""Integration tests — exercise real code paths end-to-end without mocking.

These tests verify that the critical subsystems work together correctly:
  - Router tier classification → model selection pipeline
  - SSE streaming parser (api module internals)
  - Context trimming + orphan-filter + compact pipeline
  - Web app static/health endpoints (no API key required)
  - Tool registry initialisation and schema validity
"""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Python 3.15 + anyio 4.13.0 incompatibility: current_task() returns None
# in thread-based asyncio contexts (e.g., Starlette TestClient).
# Skip web-app-related tests until upstream anyio/starlette supports 3.15.
_py315_skip = pytest.mark.skipif(
    sys.version_info >= (3, 15),
    reason="Python 3.15 + anyio 4.13.0 incompatibility (current_task returns None)",
)

from luckyd_code.router import (  # noqa: E402
    classify_tier,
    select_model,
    resolve_initial_route,
    escalate_tier,
    get_tier_description,
)
from luckyd_code.api import (  # noqa: E402
    _parse_sse_line,
    _repair_json,
    _filter_messages,
    _classify_http_error,
)
from luckyd_code.retry import RetryableError, NonRetryableError, ModelNotFoundError  # noqa: E402
from luckyd_code.context import ConversationContext  # noqa: E402
from luckyd_code.web_app import create_app  # noqa: E402


# ---------------------------------------------------------------------------
# Router pipeline integration
# ---------------------------------------------------------------------------

class TestRouterPipeline:
    """Full router pipeline: classify → select → routing result."""

    def test_simple_chat_routes_to_chat_model(self):
        tier = classify_tier("hi")
        assert tier == 1
        model = select_model("hi")
        # Tier-1 model is deepseek-v4-flash (V4 naming)
        assert "flash" in model.lower() or "chat" in model.lower()

    def test_debug_prompt_routes_to_reasoner(self):
        tier = classify_tier("Please debug this crash in my app")
        assert tier >= 3
        model = select_model("Please debug this crash in my app")
        assert isinstance(model, str) and len(model) > 0

    def test_heavy_refactor_routes_to_tier_4(self):
        tier = classify_tier("I need a large refactor of the entire auth system")
        assert tier == 4

    def test_tool_call_escalation_applied_in_select_model(self):
        """select_model should escalate tier when tool_call_count is high."""
        base_model = select_model("hi", recent_tool_count=0)
        escalated_model = select_model("hi", recent_tool_count=9)
        assert isinstance(base_model, str) and base_model
        assert isinstance(escalated_model, str) and escalated_model

    def test_resolve_initial_route_auto_off(self):
        result = resolve_initial_route(
            user_text="debug this crash",
            tool_call_count=0,
            provider="deepseek",
            preferred_model="deepseek-chat",
            auto_route=False,
        )
        assert result.model == "deepseek-chat"
        assert result.tier == 2

    def test_resolve_initial_route_auto_on(self):
        result = resolve_initial_route(
            user_text="debug this crash",
            tool_call_count=0,
            provider="deepseek",
            preferred_model="deepseek-chat",
            auto_route=True,
        )
        assert result.tier >= 3

    def test_escalate_tier_heavy_tool_calls(self):
        result = escalate_tier(
            user_text="hi",
            tool_call_count=9,
            provider="deepseek",
            preferred_model="deepseek-chat",
            current_model="deepseek-chat",
            current_tier=1,
            auto_route=True,
        )
        assert result.tier == 4

    def test_escalate_tier_moderate_tool_calls(self):
        result = escalate_tier(
            user_text="check the file in src/main.py",
            tool_call_count=3,
            provider="deepseek",
            preferred_model="deepseek-chat",
            current_model="deepseek-chat",
            current_tier=2,
            auto_route=True,
        )
        assert result.tier >= 3

    def test_escalate_tier_auto_off(self):
        result = escalate_tier(
            user_text="large refactor",
            tool_call_count=10,
            provider="deepseek",
            preferred_model="deepseek-chat",
            current_model="deepseek-chat",
            current_tier=2,
            auto_route=False,
        )
        assert result.tier == 2
        assert result.model == "deepseek-chat"

    def test_tier_descriptions_cover_all_tiers(self):
        for tier in range(1, 5):
            desc = get_tier_description(tier)
            assert isinstance(desc, str) and len(desc) > 0

    def test_select_model_with_tier_override(self):
        for tier in range(1, 5):
            model = select_model("anything", tier_override=tier)
            assert isinstance(model, str) and model

    def test_unknown_tier_description_falls_back(self):
        desc = get_tier_description(99)
        assert "99" in desc


# ---------------------------------------------------------------------------
# SSE parser / API internals
# ---------------------------------------------------------------------------

class TestSSEParsing:
    """Verify SSE parsing without any network calls."""

    def test_empty_line_returns_none(self):
        assert _parse_sse_line("") is None
        assert _parse_sse_line("   ") is None

    def test_done_signal_returns_empty_dict(self):
        assert _parse_sse_line("data: [DONE]") == {}

    def test_valid_json_chunk_parsed(self):
        payload = json.dumps({
            "choices": [{"delta": {"content": "hello"}, "finish_reason": None}]
        })
        result = _parse_sse_line(f"data: {payload}")
        assert isinstance(result, dict)
        assert result["choices"][0]["delta"]["content"] == "hello"

    def test_invalid_json_returns_none(self):
        assert _parse_sse_line("data: {bad json}") is None

    def test_non_data_line_returns_none(self):
        assert _parse_sse_line("event: ping") is None
        assert _parse_sse_line(": keep-alive") is None


class TestRepairJson:
    """Verify JSON repair handles common model output issues."""

    def test_empty_string_unchanged(self):
        assert _repair_json("") == ""

    def test_trailing_comma_removed(self):
        result = _repair_json('{"key": "value",}')
        assert result == '{"key": "value"}'

    def test_unclosed_brace_completed(self):
        result = _repair_json('{"key": "value"')
        assert result.endswith("}")

    def test_unclosed_bracket_completed(self):
        result = _repair_json('["a", "b"')
        assert result.endswith("]")

    def test_valid_json_passes_through(self):
        valid = '{"a": 1, "b": [1, 2]}'
        assert _repair_json(valid) == valid


class TestFilterMessages:
    """Verify DeepSeek reasoning_content message filtering."""

    def test_empty_content_guaranteed_when_reasoning_present(self):
        """When reasoning_content is present and content is empty/missing,
        _filter_messages must ensure content is '' so the DeepSeek API
        always sees both fields (sending None/missing causes
        'content or tool_calls must be set')."""
        messages = [
            {"role": "assistant", "content": "", "reasoning_content": "thinking..."}
        ]
        result = _filter_messages(messages)
        assert result[0]["content"] == ""

    def test_missing_content_filled_when_reasoning_present(self):
        """When content key is absent but reasoning_content is present,
        content should be set to '' not left missing."""
        messages = [
            {"role": "assistant", "reasoning_content": "thinking..."}
        ]
        result = _filter_messages(messages)
        assert result[0]["content"] == ""

    def test_non_empty_content_preserved(self):
        messages = [
            {"role": "assistant", "content": "answer", "reasoning_content": "thinking"}
        ]
        result = _filter_messages(messages)
        assert result[0]["content"] == "answer"

    def test_messages_without_reasoning_unchanged(self):
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ]
        result = _filter_messages(messages)
        assert result == messages

    def test_original_messages_not_mutated(self):
        """_filter_messages must not mutate the input list."""
        original = [{"role": "assistant", "content": "", "reasoning_content": "x"}]
        _filter_messages(original)
        assert original[0]["content"] == ""


class TestHTTPErrorClassification:
    """Verify error classification maps HTTP status codes correctly."""

    def test_401_is_non_retryable(self):
        err = _classify_http_error(401, "Unauthorized")
        assert isinstance(err, NonRetryableError)

    def test_403_is_non_retryable(self):
        err = _classify_http_error(403, "Forbidden")
        assert isinstance(err, NonRetryableError)

    def test_429_is_retryable(self):
        err = _classify_http_error(429, "Rate limited")
        assert isinstance(err, RetryableError)

    def test_500_is_retryable(self):
        err = _classify_http_error(500, "Internal server error")
        assert isinstance(err, RetryableError)

    def test_503_is_retryable(self):
        err = _classify_http_error(503, "Service unavailable")
        assert isinstance(err, RetryableError)

    def test_400_model_not_found(self):
        err = _classify_http_error(400, "model not exist in the platform")
        assert isinstance(err, ModelNotFoundError)

    def test_400_other_is_non_retryable(self):
        err = _classify_http_error(400, "bad request")
        assert isinstance(err, NonRetryableError)

    def test_404_is_non_retryable(self):
        err = _classify_http_error(404, "not found")
        assert isinstance(err, NonRetryableError)

    def test_422_is_non_retryable(self):
        err = _classify_http_error(422, "unprocessable")
        assert isinstance(err, NonRetryableError)


# ---------------------------------------------------------------------------
# Context trim + orphan filter + compact pipeline
# ---------------------------------------------------------------------------

class TestContextPipeline:
    """Integration tests for ConversationContext without external API calls."""

    def test_orphan_filter_standalone(self):
        """_drop_orphaned_tool_messages removes orphans correctly."""
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
            # tool result with no preceding assistant tool_calls — orphaned
            {"role": "tool", "tool_call_id": "tc_orphan", "content": "result"},
            {"role": "assistant", "content": "done"},
        ]
        filtered = ConversationContext._drop_orphaned_tool_messages(messages)
        roles = [m["role"] for m in filtered]
        assert "tool" not in roles

    def test_orphan_filter_keeps_paired_tool(self):
        """_drop_orphaned_tool_messages keeps tool results whose parent is present."""
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "assistant", "tool_calls": [
                {"id": "tc1", "type": "function", "function": {"name": "Read", "arguments": "{}"}}
            ]},
            {"role": "tool", "tool_call_id": "tc1", "content": "file content"},
        ]
        filtered = ConversationContext._drop_orphaned_tool_messages(messages)
        assert len(filtered) == 3
        assert filtered[2]["role"] == "tool"

    def test_trim_drops_orphaned_tool_after_window_cut(self):
        """When trimming cuts the parent assistant message, the tool result is dropped."""
        ctx = ConversationContext("sys", max_messages=3)
        ctx.messages.append({
            "role": "assistant",
            "tool_calls": [{"id": "tc1", "type": "function",
                            "function": {"name": "Read", "arguments": "{}"}}],
        })
        ctx.messages.append({"role": "tool", "tool_call_id": "tc1", "content": "data"})
        # add_user_message pushes to 4, triggering trim to 3
        ctx.add_user_message("overflow")
        tool_msgs = [m for m in ctx.messages if m.get("role") == "tool"]
        assert len(tool_msgs) == 0

    def test_full_conversation_trim_cycle(self):
        """A realistic multi-turn conversation trims cleanly without corrupting history."""
        ctx = ConversationContext("You are a coding assistant.", max_messages=10)
        for i in range(6):
            ctx.add_user_message(f"question {i}")
            ctx.add_assistant_message(content=f"answer {i}")
        assert ctx.count_messages() <= 10
        assert ctx.messages[0]["role"] == "system"
        assert ctx.messages[-1]["role"] == "assistant"

    def test_estimate_tokens_increases_with_content(self):
        """More content → more estimated tokens."""
        ctx_small = ConversationContext("short")
        ctx_large = ConversationContext("x" * 500)
        ctx_large.add_user_message("y" * 500)
        assert ctx_large.estimate_tokens() > ctx_small.estimate_tokens()

    def test_compact_no_op_small_context(self):
        """compact returns early when there's nothing to summarise."""
        ctx = ConversationContext("sys")
        ctx.add_user_message("hello")
        result = ctx.compact(None, "deepseek-chat", keep_last=5)
        assert "Nothing to compact" in result

    def test_compact_on_compact_callback_called(self):
        """on_compact callback is invoked with (summary, count)."""
        ctx = ConversationContext("sys")
        for i in range(8):
            ctx.add_user_message(f"msg {i}")
            ctx.add_assistant_message(content=f"resp {i}")

        mock_completion = MagicMock()
        mock_completion.choices[0].message.content = "Summary"
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_completion
        cfg = MagicMock()
        cfg.api_key = "k"
        cfg.base_url = "https://api.deepseek.com/v1"

        callback_args = []

        def _callback(summary, count):
            callback_args.append((summary, count))

        with patch("openai.OpenAI", return_value=mock_client):
            ctx.compact(cfg, "deepseek-chat", keep_last=5, on_compact=_callback)

        assert len(callback_args) == 1
        summary, count = callback_args[0]
        assert summary == "Summary"
        assert count > 0


# ---------------------------------------------------------------------------
# Web app static / health endpoints (no API key needed)
# ---------------------------------------------------------------------------

def _make_config():
    cfg = MagicMock()
    cfg.api_key = "test-key"
    cfg.base_url = "https://api.deepseek.com/v1"
    cfg.provider = "deepseek"
    cfg.model = "deepseek-chat"
    cfg.max_tokens = 4096
    cfg.temperature = 0.7
    cfg.system_prompt = "You are a coding assistant."
    cfg.max_context_messages = 100
    return cfg


@_py315_skip
class TestWebAppEndpoints:
    """Integration tests for the FastAPI web app endpoints (real routing, no API calls)."""

    @pytest.fixture
    def client(self):
        with patch("luckyd_code.web_app.Config", return_value=_make_config()):
            with patch("luckyd_code.web_app.memory_module.load_claude_md", return_value=""):
                with patch("luckyd_code.indexer.index_project", return_value=""):
                    app = create_app()
                    yield TestClient(app)

    def test_index_returns_200_html(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_tools_endpoint_returns_valid_schema(self, client):
        resp = client.get("/api/tools")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["tools"], list)
        assert data["count"] == len(data["tools"])
        for tool in data["tools"]:
            assert "name" in tool

    def test_memory_endpoint_returns_fields(self, client):
        resp = client.get("/api/memory")
        assert resp.status_code == 200
        data = resp.json()
        assert "claude_md" in data
        assert "message_count" in data

    def test_clear_resets_context(self, client):
        resp = client.post("/api/clear")
        assert resp.status_code == 200
        assert resp.json()["status"] == "cleared"

    def test_write_and_read_file_roundtrip(self, client):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "roundtrip.txt")
            with patch("luckyd_code.tools.path_validate.safe_resolve",
                       side_effect=lambda p, **kw: Path(p).resolve()):
                write_resp = client.post("/api/write-file",
                                         json={"path": path, "content": "roundtrip"})
                assert write_resp.status_code == 200

                read_resp = client.get("/api/read-file", params={"path": path})
                assert read_resp.status_code == 200
                assert read_resp.json()["content"] == "roundtrip"

    def test_unknown_endpoint_returns_404(self, client):
        resp = client.get("/api/does-not-exist")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tool registry integration
# ---------------------------------------------------------------------------

class TestToolRegistryIntegration:
    """Verify the tool registry initialises and produces valid OpenAI-style schemas."""

    def test_registry_has_tools(self):
        from luckyd_code.tools import get_default_registry
        registry = get_default_registry()
        schemas = registry.list_tools()
        assert len(schemas) > 0

    def test_all_tools_have_name_and_description(self):
        from luckyd_code.tools import get_default_registry
        registry = get_default_registry()
        for schema in registry.list_tools():
            fn = schema["function"]
            assert fn.get("name"), "Tool must have a non-empty name"
            assert fn.get("description"), f"Tool '{fn['name']}' must have a description"

    def test_tool_schemas_are_serialisable(self):
        from luckyd_code.tools import get_default_registry
        schemas = get_default_registry().list_tools()
        serialised = json.dumps(schemas)
        parsed = json.loads(serialised)
        assert len(parsed) == len(schemas)
        for schema in parsed:
            assert schema.get("type") == "function"
            assert "function" in schema
            assert "name" in schema["function"]
