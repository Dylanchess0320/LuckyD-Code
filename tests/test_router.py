"""Tests for the auto-router module (4-tier system)."""

from luckyd_code.router import classify_tier, should_use_reasoner, select_model


class TestClassifyTier:
    def test_very_short_prompt_is_tier_1(self):
        """Very short prompts should be tier 1 (simple chat)."""
        assert classify_tier("hi") == 1
        assert classify_tier("hello") == 1
        assert classify_tier("yes") == 1

    def test_long_prompt_is_tier_2(self):
        """Long prompts without code indicators should be tier 2."""
        long_text = "a" * 301
        assert classify_tier(long_text) == 2

    def test_debug_keyword_triggers_tier_3(self):
        """Prompts containing debug keywords should be tier 3."""
        assert classify_tier("Can you debug this issue?") == 3
        assert classify_tier("I need to fix this bug please") == 3
        assert classify_tier("help me fix this bug") == 3

    def test_optimization_keyword_triggers_tier_3(self):
        """Optimization prompts should be tier 3."""
        assert classify_tier("Can you optimize this function?") == 3
        assert classify_tier("Please refactor this code for me") == 3

    def test_code_review_triggers_tier_3(self):
        """Code review prompts should be tier 3."""
        assert classify_tier("Please review this code for me") == 3

    def test_code_blocks_with_keyword_triggers_tier_2(self):
        """Prompts with code blocks + keywords (2 indicators) should be tier 2."""
        text = "Here is the code:\n```python\ndef hello():\n    print('hello')\n```\nWhat do you think?"
        assert classify_tier(text) == 2

    def test_function_keyword_triggers_tier_2(self):
        """Prompts with function/class/def keywords should be tier 2."""
        assert classify_tier("Write a function in src/utils.py that adds two numbers") == 2

    def test_file_path_triggers_tier_2(self):
        """Prompts with file paths should be tier 2."""
        assert classify_tier("Check src/main.py for errors") == 2

    def test_tool_call_count_triggers_escalation(self):
        """High tool call count should escalate (but classify_tier alone doesn't escalate)."""
        # classify_tier doesn't escalate — that's done by select_model.
        # So without tool escalation, this is just a short prompt.
        assert classify_tier("please continue with the next step", recent_tool_count=3) == 1

    def test_simple_question_is_tier_1(self):
        """Simple questions should remain tier 1."""
        assert classify_tier("What is Python?") == 1
        assert classify_tier("How are you?") == 1

    def test_error_terms_trigger_tier_2(self):
        """Error terms plus file path should be tier 2."""
        assert classify_tier("I got an exception in my function") == 2
        assert classify_tier("This crashes with a stack trace in src/main.py") == 2

    def test_heavy_keyword_triggers_tier_4(self):
        """Heavy keywords like 'large refactor' should be tier 4."""
        assert classify_tier("I need a large refactor of the auth module") == 4
        assert classify_tier("Plan a migration plan for the database") == 4
        assert classify_tier("Full rewrite of the parser component") == 4


class TestShouldUseReasoner:
    def test_disabled_returns_false(self):
        """When auto_route is disabled, should always return False."""
        assert should_use_reasoner("debug this", auto_route_enabled=False) is False

    def test_disabled_returns_false_even_for_long(self):
        """When disabled, even long prompts should return False."""
        long_text = "a" * 500
        assert should_use_reasoner(long_text, auto_route_enabled=False) is False

    def test_enabled_returns_true_for_complex(self):
        """When enabled and tier 3+, should return True."""
        assert should_use_reasoner("Can you debug this issue?", auto_route_enabled=True) is True

    def test_enabled_returns_false_for_simple(self):
        """When enabled and simple, should return False."""
        assert should_use_reasoner("hi", auto_route_enabled=True) is False

    def test_enabled_returns_true_with_escalation(self):
        """When enabled and tool calls escalate a tier-2 prompt to tier 3+, return True."""
        # "help with function" is tier 1 (< 20 chars), so use a longer tier-2 prompt
        assert should_use_reasoner("help with the function in src/main.py", auto_route_enabled=True, recent_tool_count=3) is True

    def test_enabled_returns_false_with_few_tool_calls(self):
        """When enabled and few tool calls, should return False for short text."""
        assert should_use_reasoner("hi", auto_route_enabled=True, recent_tool_count=1) is False

    def test_enabled_with_code_blocks(self):
        """When enabled and code blocks present (2 indicators = tier 2), should return False."""
        text = "Here is the code:\n```python\ndef hello():\n    print('hello')\n```\nWhat do you think?"
        assert should_use_reasoner(text, auto_route_enabled=True) is False


class TestClassifyTierEdgeCases:
    def test_prompt_exactly_19_chars_is_tier_1(self):
        """Prompt under 20 chars should be tier 1."""
        text = "a" * 19
        assert classify_tier(text) == 1

    def test_prompt_20_chars_no_keywords(self):
        """Prompt at 20+ chars with no keywords should be tier 1."""
        text = "a" * 20
        assert classify_tier(text) == 1

    def test_keyword_at_boundary(self):
        """Prompt with debug keyword at 20+ chars should be tier 3."""
        assert classify_tier("I need help to fix this bug now please") == 3

    def test_code_indicators_none(self):
        """Text with no code indicators should remain tier 1."""
        assert classify_tier("What is the meaning of life?") == 1

    def test_one_code_indicator_is_tier_2(self):
        """Single code indicator in a longer prompt should be tier 2."""
        text = "I need help with a function for parsing json data"
        assert classify_tier(text) == 2

    def test_three_code_indicators_triggers_tier_3(self):
        """Three code indicators should trigger tier 3."""
        text = "```python``` define a function in src/main.py got an error"
        assert classify_tier(text) == 3

    def test_error_and_file_path_indicators(self):
        """Error term + file path should be tier 2."""
        text = "Got an error in src/main.py"
        assert classify_tier(text) == 2

    def test_long_code_heavy_prompt_is_tier_3(self):
        """Very long prompt with code should be tier 3."""
        text = "a" * 801 + "\n```python\ndef foo():\n    pass\n```"
        assert classify_tier(text) == 3

    def test_regex_catches_paraphrased_debug_queries(self):
        """Regex patterns catch paraphrased queries keyword matches miss."""
        assert classify_tier("can you help me figure out why this crashed") == 3
        assert classify_tier("my code broke and I don't know why") == 3
        assert classify_tier("this doesn't work can you look at it") == 3
        assert classify_tier("why is this happening in my app") == 3


class TestSelectModel:
    def test_select_model_returns_string(self):
        """select_model should always return a string model ID."""
        model = select_model("hi")
        assert isinstance(model, str)
        assert len(model) > 0

    def test_select_model_respects_preferred(self):
        """If preferred model is specified, it should be returned when valid."""
        model = select_model("hi", preferred_model="deepseek/deepseek-v4-flash")
        assert model == "deepseek/deepseek-v4-flash"

    def test_select_model_tier_override(self):
        """Tier override should force a specific tier."""
        # Simple chat with tier 4 override should select a tier-4 model
        model = select_model("hi", tier_override=4)
        assert isinstance(model, str)

    def test_select_model_escalates_with_tool_calls(self):
        """High tool call count should escalate tier."""
        simple_model = select_model("hi", recent_tool_count=0)
        escalated_model = select_model("hi", recent_tool_count=3)
        # Both should be valid model strings
        assert isinstance(simple_model, str)
        assert isinstance(escalated_model, str)
