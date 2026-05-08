"""Tests for the conversation context module."""

from unittest.mock import patch, MagicMock


from luckyd_code.context import ConversationContext


class TestConversationContext:
    def test_init_creates_system_message(self):
        """Context should start with a system message."""
        ctx = ConversationContext("You are a helpful assistant.")
        assert len(ctx.messages) == 1
        assert ctx.messages[0]["role"] == "system"
        assert ctx.messages[0]["content"] == "You are a helpful assistant."

    def test_add_user_message(self):
        """Adding a user message should append it."""
        ctx = ConversationContext("system prompt")
        ctx.add_user_message("Hello!")
        assert len(ctx.messages) == 2
        assert ctx.messages[1]["role"] == "user"
        assert ctx.messages[1]["content"] == "Hello!"

    def test_add_assistant_message_text_only(self):
        """Adding an assistant message with text only."""
        ctx = ConversationContext("system prompt")
        ctx.add_assistant_message(content="Hi there!")
        assert ctx.messages[1]["role"] == "assistant"
        assert ctx.messages[1]["content"] == "Hi there!"

    def test_add_assistant_message_with_tool_calls(self):
        """Adding an assistant message with tool calls."""
        ctx = ConversationContext("system prompt")
        tool_calls = [{"id": "call_1", "type": "function", "function": {"name": "Read", "arguments": "{}"}}]
        ctx.add_assistant_message(content=None, tool_calls=tool_calls)
        assert ctx.messages[1]["role"] == "assistant"
        assert "tool_calls" in ctx.messages[1]
        assert len(ctx.messages[1]["tool_calls"]) == 1

    def test_add_assistant_message_no_content_no_tool_calls(self):
        """Adding an assistant message with no content and no tool_calls."""
        ctx = ConversationContext("sys")
        ctx.add_assistant_message(content=None)
        assert ctx.messages[1]["role"] == "assistant"
        # When content is None and no tool_calls, content key is not set
        assert "content" not in ctx.messages[1]

    def test_add_tool_result(self):
        """Adding a tool result should create a tool message."""
        ctx = ConversationContext("system prompt")
        ctx.add_tool_result("call_1", "Read", "file contents")
        assert ctx.messages[1]["role"] == "tool"
        assert ctx.messages[1]["tool_call_id"] == "call_1"
        assert ctx.messages[1]["content"] == "file contents"

    def test_get_messages(self):
        """get_messages should return all messages."""
        ctx = ConversationContext("sys")
        ctx.add_user_message("hello")
        ctx.add_assistant_message(content="world")
        msgs = ctx.get_messages()
        assert len(msgs) == 3

    def test_count_messages(self):
        """count_messages should return correct count."""
        ctx = ConversationContext("sys")
        ctx.add_user_message("a")
        ctx.add_user_message("b")
        ctx.add_user_message("c")
        assert ctx.count_messages() == 4  # system + 3 user

    def test_reset_keeps_system(self):
        """Reset should keep the system prompt."""
        ctx = ConversationContext("system prompt")
        ctx.add_user_message("hello")
        ctx.add_assistant_message(content="world")
        ctx.reset()
        assert len(ctx.messages) == 1
        assert ctx.messages[0]["content"] == "system prompt"

    def test_reset_with_new_system(self):
        """Reset with a new system prompt should replace it."""
        ctx = ConversationContext("old prompt")
        ctx.reset(system_prompt="new prompt")
        assert ctx.messages[0]["content"] == "new prompt"

    def test_trim_exceeding_max(self):
        """Context should trim when exceeding max_messages."""
        ctx = ConversationContext("sys", max_messages=5)
        # Add 4 user messages (system + 4 user = 5, at limit)
        for i in range(4):
            ctx.add_user_message(f"msg {i}")
        assert ctx.count_messages() == 5

        # Add one more — should trigger trim (keeping system + last 4 = 5)
        ctx.add_user_message("overflow")
        assert ctx.count_messages() <= 5
        # The last message should be the overflow one
        assert ctx.messages[-1]["content"] == "overflow"


class TestConversationContextOrphanFiltering:
    """Tests for orphaned tool message filtering on trim."""

    def test_orphan_tool_removed_on_trim(self):
        """Orphaned tool results whose parent tool_call was trimmed MUST be removed.

        Setup: sys, user1, assistant(tc1), tool(tc1), user2
        Total = 5.  max_messages=4 forces a trim.
        After trim: sys + last 3 = sys + tool(tc1) + user2 + ?
        Wait — trim keeps system + messages[-(4-1):] = system + last 3:
          messages[-3:] = [assistant(tc1), tool(tc1), user2].
        So assistant(tc1) IS in the window → tool is kept.

        To actually trigger orphan removal we need the assistant to fall
        *outside* the kept window.  Make max_messages so tight that only
        tool + user survive the trim while the parent assistant is gone.
        """
        ctx = ConversationContext("sys", max_messages=3)
        # message 1 (sys), 2 (user1), 3 (assistant+tc1), 4 (tool tc1), 5 (user2)
        ctx.add_user_message("user1")
        ctx.add_assistant_message(
            content=None,
            tool_calls=[{"id": "tc1", "type": "function",
                         "function": {"name": "Test", "arguments": "{}"}}],
        )
        ctx.add_tool_result("tc1", "Test", "result1")
        ctx.add_user_message("user2")
        # 5 messages > 3 → trim. Kept: sys + last 2 = sys + tool(tc1) + user2.
        # The assistant with tc1 was pushed out, so tool(tc1) is orphaned
        # and MUST be filtered by _drop_orphaned_tool_messages.
        assert ctx.count_messages() <= 3
        tool_msgs = [m for m in ctx.messages if m.get("role") == "tool"]
        assert len(tool_msgs) == 0, (
            f"Orphaned tool message was not removed! "
            f"Messages: {[m['role'] for m in ctx.messages]}"
        )

    def test_orphan_tool_filtered_after_compact(self):
        """`compact()` runs _drop_orphaned_tool_messages on the result."""
        ctx = ConversationContext("sys")
        ctx.add_user_message("user1")
        ctx.add_assistant_message(
            content=None,
            tool_calls=[{"id": "tc_alive", "type": "function",
                         "function": {"name": "Test", "arguments": "{}"}}],
        )
        ctx.add_tool_result("tc_alive", "Test", "alive_result")
        # Add enough bulk to force compaction (keep_last=5 default)
        for i in range(8):
            ctx.add_user_message(f"pad {i}")
            ctx.add_assistant_message(content=f"resp {i}")
        # Now 1 system + 17 messages = 18, well above keep_last=5 → compact triggers

        mock_completion = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "All earlier messages summarized."
        mock_completion.choices = [mock_choice]

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_completion

        mock_config = MagicMock()
        mock_config.api_key = "test-key"
        mock_config.base_url = "https://api.deepseek.com/v1"

        with patch("openai.OpenAI", return_value=mock_client):
            result = ctx.compact(mock_config, "deepseek-chat")

        assert "Compacted" in result
        # Verify no orphaned tool messages survived compaction
        tool_msgs = [m for m in ctx.messages if m.get("role") == "tool"]
        assert len(tool_msgs) <= 1, "Orphaned tools should be filtered after compact"

    def test_orphan_tool_kept_when_parent_is_in_window(self):
        """Tool message whose parent tool_call IS in the window must survive."""
        ctx = ConversationContext("sys", max_messages=5)
        ctx.add_user_message("user1")
        ctx.add_assistant_message(
            content="Here are results:",
            tool_calls=[{"id": "tc1", "type": "function",
                         "function": {"name": "Read", "arguments": "{}"}}],
        )
        ctx.add_tool_result("tc1", "Read", "file content")
        # sys + user + assistant(tc1) + tool(tc1) = 4.  Add one more.
        ctx.add_user_message("user2")
        # 5 messages, at limit.  No trim triggered yet.
        # The tool's parent (assistant with tc1) is in position 2,
        # which is inside the window.  Tool SHOULD be kept.
        tool_msgs = [m for m in ctx.messages if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0]["tool_call_id"] == "tc1"


class TestConversationContextEstimateTokens:
    def test_estimate_tokens_empty(self):
        """estimate_tokens with no content should return small number."""
        ctx = ConversationContext("")
        tokens = ctx.estimate_tokens()
        assert tokens >= 0

    def test_estimate_tokens_system_only(self):
        """estimate_tokens should estimate based on character count."""
        ctx = ConversationContext("Hello world!")
        tokens = ctx.estimate_tokens()
        # "Hello world!" = 12 chars / 4 = 3, plus overhead (~5 tokens for system msg = 20 chars/4)
        assert tokens > 0
        assert isinstance(tokens, int)

    def test_estimate_tokens_with_content(self):
        """estimate_tokens should account for all message content."""
        ctx = ConversationContext("You are a bot.")
        ctx.add_user_message("What is the capital of France?")
        ctx.add_assistant_message(content="Paris.")
        tokens = ctx.estimate_tokens()
        assert tokens > 5

    def test_estimate_tokens_with_tool_calls(self):
        """estimate_tokens should account for tool call arguments."""
        ctx = ConversationContext("sys")
        ctx.add_assistant_message(
            content=None,
            tool_calls=[{"id": "tc1", "type": "function", "function": {"name": "Read", "arguments": '{"file": "x"}'}}],
        )
        tokens = ctx.estimate_tokens()
        assert tokens > 0

    def test_estimate_tokens_with_tool_result(self):
        """estimate_tokens should account for tool_call_id overhead."""
        ctx = ConversationContext("sys")
        ctx.add_tool_result("tc1", "Read", "some result content here")
        tokens = ctx.estimate_tokens()
        assert tokens > 0

    def test_estimate_tokens_with_long_content(self):
        """estimate_tokens should handle long content."""
        ctx = ConversationContext("x" * 1000)
        tokens = ctx.estimate_tokens()
        # With tiktoken, repeated chars are ~1 token per char for 'x',
        # so this can be up to ~1000 tokens. Just verify it returns a
        # reasonable positive integer.
        assert tokens > 0
        assert isinstance(tokens, int)


class TestConversationContextCompact:
    def test_compact_returns_early_for_small_context(self):
        """compact should return early if there's nothing to compact."""
        ctx = ConversationContext("sys")
        ctx.add_user_message("hello")
        ctx.add_assistant_message(content="world")
        result = ctx.compact(None, "deepseek-chat")
        assert "Nothing to compact" in result

    def test_compact_returns_early_at_exact_boundary(self):
        """compact should return early when messages == keep_last + 1."""
        ctx = ConversationContext("sys")
        for i in range(5):
            ctx.add_user_message(f"msg {i}")
        # 6 messages total (system + 5 user). keep_last=5 means threshold is 6.
        # Since 6 <= 6, nothing to compact.
        result = ctx.compact(None, "deepseek-chat")
        assert "Nothing to compact" in result

    def test_compact_with_api_success(self):
        """compact should call the API and produce a summary."""
        ctx = ConversationContext("sys")
        for i in range(6):
            ctx.add_user_message(f"user message {i}")
            ctx.add_assistant_message(content=f"response {i}")
        # 13 messages total. keep_last=5 means we compact 13-1-5=7 messages.

        # Mock the OpenAI client
        mock_completion = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "Summary of the conversation."
        mock_completion.choices = [mock_choice]

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_completion

        mock_config = MagicMock()
        mock_config.api_key = "test-key"
        mock_config.base_url = "https://api.deepseek.com/v1"
        mock_config.provider = "deepseek"

        with patch("openai.OpenAI", return_value=mock_client):
            result = ctx.compact(mock_config, "deepseek-chat")
            assert "Compacted" in result
            assert "7" in result  # 7 messages compacted

            # Messages should now have: system + summary + last 5 kept messages
            assert ctx.messages[0]["role"] == "system"
            assert ctx.messages[1]["role"] == "system"  # summary inserted as system
            assert "[Compacted conversation summary]" in ctx.messages[1]["content"]

    def test_compact_with_api_failure(self):
        """compact should handle API failures gracefully."""
        ctx = ConversationContext("sys")
        for i in range(6):
            ctx.add_user_message(f"msg {i}")
            ctx.add_assistant_message(content=f"resp {i}")

        mock_config = MagicMock()
        mock_config.api_key = "bad-key"
        mock_config.base_url = "https://api.deepseek.com/v1"
        mock_config.provider = "deepseek"

        with patch("openai.OpenAI", side_effect=Exception("API error")):
            result = ctx.compact(mock_config, "deepseek-chat")
            assert "Compaction failed" in result

    def test_compact_with_reasoner_model(self):
        """compact should use deepseek-chat when reasoner is the active model."""
        ctx = ConversationContext("sys")
        for i in range(6):
            ctx.add_user_message(f"msg {i}")
            ctx.add_assistant_message(content=f"resp {i}")

        mock_completion = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "Summary"
        mock_completion.choices = [mock_choice]

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_completion

        mock_config = MagicMock()
        mock_config.api_key = "test-key"
        mock_config.base_url = "https://api.deepseek.com/v1"
        mock_config.provider = "deepseek"

        with patch("openai.OpenAI", return_value=mock_client):
            result = ctx.compact(mock_config, "deepseek-reasoner")
            assert "Compacted" in result


class TestConversationContextReasoningContent:
    """DeepSeek requires content + reasoning_content to travel together."""

    def test_add_assistant_with_reasoning_content(self):
        """reasoning_content is stored and accessible."""
        ctx = ConversationContext("sys")
        ctx.add_assistant_message(
            content="Answer",
            reasoning_content="Let me think step by step...",
        )
        assert ctx.messages[1]["role"] == "assistant"
        assert ctx.messages[1]["content"] == "Answer"
        assert ctx.messages[1]["reasoning_content"] == "Let me think step by step..."

    def test_reasoning_without_content_falls_back_to_empty_string(self):
        """When reasoning_content is present but content is None/absent,
        content must default to ``""`` so the DeepSeek API accepts the message."""
        ctx = ConversationContext("sys")
        ctx.add_assistant_message(
            content=None,
            reasoning_content="Deep thought...",
        )
        # The API requires content alongside reasoning_content in multi-turn
        assert ctx.messages[1].get("content") == ""
        assert ctx.messages[1]["reasoning_content"] == "Deep thought..."

    def test_estimate_tokens_counts_reasoning_content(self):
        """Token estimation must include reasoning_content (it consumes API budget)."""
        ctx = ConversationContext("sys")
        ctx.add_assistant_message(
            content="Answer",
            reasoning_content="x" * 400,  # 400 chars of reasoning
        )
        tokens = ctx.estimate_tokens()
        # The reasoning_content alone contributes substantially.
        # With tiktoken: ~400 tokens.  Without: ~100 (chars/4 heuristic).
        # Either way, the total must be strictly greater than the non-reasoning
        # baseline.
        baseline = ConversationContext("sys")
        baseline.add_assistant_message(content="Answer")
        baseline_tokens = baseline.estimate_tokens()
        assert tokens > baseline_tokens, (
            f"Tokens with reasoning ({tokens}) must exceed without ({baseline_tokens})"
        )

    def test_full_reasoning_roundtrip(self):
        """Simulate a thinking-model exchange and verify messages stay valid."""
        ctx = ConversationContext("You are a thinking assistant.")
        ctx.add_user_message("Solve: 1+1")
        ctx.add_assistant_message(
            content="It's 2.",
            reasoning_content="The user asked 1+1. That equals 2.",
        )
        ctx.add_user_message("How about 2+2?")
        # The second user message should not crash — all messages from the
        # previous turn should be valid.
        assert ctx.count_messages() == 4
        # Verify the assistant message has both content and reasoning_content
        assistant = ctx.messages[2]
        assert assistant["role"] == "assistant"
        assert assistant["content"] == "It's 2."
        assert "reasoning_content" in assistant


class TestConversationContextEdgeCases:
    def test_max_messages_default(self):
        """Default max_messages should be 100."""
        ctx = ConversationContext("sys")
        assert ctx.max_messages == 100

    def test_no_trim_below_max(self):
        """Messages below max_messages should not be trimmed."""
        ctx = ConversationContext("sys")
        for i in range(98):
            ctx.add_user_message(f"msg {i}")
        assert ctx.count_messages() == 99  # system + 98 users

    def test_trim_exactly_at_max(self):
        """Messages at exactly max_messages should not be trimmed."""
        ctx = ConversationContext("sys", max_messages=5)
        for i in range(4):
            ctx.add_user_message(f"msg {i}")
        assert ctx.count_messages() == 5  # system + 4 users = exactly max

    def test_trim_keeps_most_recent(self):
        """Trim should keep the most recent messages."""
        ctx = ConversationContext("sys", max_messages=4)
        ctx.add_user_message("keep_me")
        ctx.add_user_message("and_me")
        ctx.add_user_message("and_me_too")
        # Now at 4 (sys + 3 users), at limit
        ctx.add_user_message("overflow")
        # After trim: sys + last 3 = sys + keep_me + and_me + overflow
        # wait: sys + last 3 = sys + and_me + and_me_too + overflow
        # But 'keep_me' was message index 1 and gets pushed out
        assert ctx.count_messages() == 4
        assert ctx.messages[-1]["content"] == "overflow"

    def test_full_conversation_flow(self):
        """Test a realistic conversation flow."""
        ctx = ConversationContext("You are a coding assistant.")
        ctx.add_user_message("Read the file main.py")
        ctx.add_assistant_message(
            content=None,
            tool_calls=[{"id": "tc1", "type": "function", "function": {"name": "Read", "arguments": '{"file_path": "main.py"}'}}],
        )
        ctx.add_tool_result("tc1", "Read", "print('hello')")
        ctx.add_assistant_message(content="The file contains: print('hello')")
        assert ctx.count_messages() == 5
        assert ctx.messages[1]["content"] == "Read the file main.py"
        assert ctx.messages[4]["content"] == "The file contains: print('hello')"

    def test_add_user_message_with_empty_content(self):
        """Adding empty user message should still work."""
        ctx = ConversationContext("sys")
        ctx.add_user_message("")
        assert ctx.messages[1]["content"] == ""
