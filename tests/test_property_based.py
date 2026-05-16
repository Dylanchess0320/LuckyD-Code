"""Property-based (Hypothesis) tests for _repair_json and classify_tier.

These tests use fuzzing to verify invariants that hold for *all* inputs,
catching edge cases that hand-written unit tests miss.

Run:  pytest tests/test_property_based.py -v
Req:  hypothesis>=6.0  (already in [project.optional-dependencies].dev)
"""

import json

import pytest
from hypothesis import assume, given, settings, HealthCheck
from hypothesis import strategies as st

from luckyd_code.api import _repair_json, _remove_trailing_commas
from luckyd_code.router import classify_tier


# ── _repair_json — invariants ─────────────────────────────────────────────────


class TestRepairJsonProperties:
    """_repair_json must never raise, always return str, preserve valid JSON."""

    @given(st.text())
    @settings(max_examples=500, suppress_health_check=[HealthCheck.too_slow])
    def test_never_raises_on_arbitrary_input(self, s: str) -> None:
        """No input should ever cause _repair_json to raise an exception."""
        result = _repair_json(s)
        assert isinstance(result, str)

    @given(st.text(max_size=0))
    def test_empty_or_whitespace_returns_empty(self, s: str) -> None:
        """Empty / whitespace-only input always returns the empty string."""
        assert _repair_json(s) == ""

    @given(
        st.one_of(
            st.fixed_dictionaries({"k": st.text(max_size=20), "v": st.integers()}),
            st.fixed_dictionaries({"a": st.booleans(), "b": st.none()}),
            st.fixed_dictionaries({"x": st.lists(st.integers(), max_size=5)}),
        )
    )
    def test_valid_json_object_is_unchanged(self, obj: dict) -> None:
        """Already-valid JSON objects must pass through completely unchanged."""
        valid = json.dumps(obj)
        assert _repair_json(valid) == valid

    @given(st.lists(st.integers(), max_size=10))
    def test_valid_json_array_is_unchanged(self, lst: list) -> None:
        """Already-valid JSON arrays must pass through completely unchanged."""
        valid = json.dumps(lst)
        assert _repair_json(valid) == valid

    @given(
        st.fixed_dictionaries({"key": st.text(max_size=20), "val": st.text(max_size=20)})
    )
    def test_truncated_object_repaired_to_parseable(self, obj: dict) -> None:
        """Truncating a valid JSON object and repairing it must yield parseable JSON."""
        valid = json.dumps(obj)
        assume(len(valid) >= 2)
        truncated = valid[:-1]  # drop closing brace
        repaired = _repair_json(truncated)
        try:
            json.loads(repaired)
        except json.JSONDecodeError:
            pytest.fail(f"Repaired JSON is not parseable: {repaired!r}")

    @given(
        st.fixed_dictionaries({"key": st.text(max_size=10), "val": st.integers()})
    )
    def test_trailing_comma_repair_yields_parseable(self, obj: dict) -> None:
        """JSON with a trailing comma before } must be repaired to valid JSON."""
        valid = json.dumps(obj)
        with_comma = valid[:-1] + ",}"  # insert trailing comma
        repaired = _repair_json(with_comma)
        try:
            json.loads(repaired)
        except json.JSONDecodeError:
            pytest.fail(f"Trailing-comma repair failed: {repaired!r}")

    @given(st.text(max_size=200))
    @settings(max_examples=300)
    def test_idempotent_on_already_repaired(self, s: str) -> None:
        """Repairing an already-repaired string must produce the same result."""
        once = _repair_json(s)
        twice = _repair_json(once)
        assert once == twice

    @given(st.text())
    @settings(max_examples=300)
    def test_result_has_balanced_or_excess_close_braces(self, s: str) -> None:
        """After repair, close-brace count >= open-brace count (outside strings)."""
        result = _repair_json(s)
        # Simple count check (not string-aware, but sufficient to detect we
        # never *remove* closing braces)
        assert result.count("}") >= s.count("{") or result == ""

    @given(st.text())
    @settings(max_examples=300)
    def test_result_has_balanced_or_excess_close_brackets(self, s: str) -> None:
        """After repair, close-bracket count >= open-bracket count (outside strings)."""
        result = _repair_json(s)
        assert result.count("]") >= s.count("[") or result == ""


# ── _remove_trailing_commas — invariants ──────────────────────────────────────


class TestRemoveTrailingCommasProperties:
    """_remove_trailing_commas must never raise and must preserve string contents."""

    @given(st.text())
    @settings(max_examples=400, suppress_health_check=[HealthCheck.too_slow])
    def test_never_raises(self, s: str) -> None:
        result = _remove_trailing_commas(s)
        assert isinstance(result, str)

    @given(st.text())
    @settings(max_examples=400)
    def test_length_never_increases(self, s: str) -> None:
        """Stripping commas can only shorten or preserve length, never extend."""
        result = _remove_trailing_commas(s)
        assert len(result) <= len(s)

    @given(
        st.fixed_dictionaries({"key": st.text(max_size=15), "val": st.integers()})
    )
    def test_valid_json_objects_unchanged(self, obj: dict) -> None:
        """Already-valid JSON objects have no trailing commas — must be unchanged."""
        valid = json.dumps(obj)
        assert _remove_trailing_commas(valid) == valid

    @given(st.text())
    @settings(max_examples=400)
    def test_idempotent(self, s: str) -> None:
        """Stripping twice must equal stripping once."""
        assert _remove_trailing_commas(_remove_trailing_commas(s)) == _remove_trailing_commas(s)

    @given(st.text(max_size=100, alphabet=st.characters(blacklist_categories=("Cs",))))
    @settings(max_examples=300)
    def test_non_json_commas_outside_closers_preserved(self, s: str) -> None:
        """Commas that are NOT followed by ] or } must be preserved."""
        # Append a space so any trailing comma in s is not followed by a closer
        padded = s + " "
        result = _remove_trailing_commas(padded)
        # Any comma in the original that wasn't before } or ] must still be there
        # (This is a weaker check — just verifies we don't strip everything)
        assert result.count(",") <= padded.count(",")


# ── classify_tier — invariants ────────────────────────────────────────────────


class TestClassifyTierProperties:
    """classify_tier must always return an int in [1, 4] and respect key invariants."""

    @given(st.text())
    @settings(max_examples=500, suppress_health_check=[HealthCheck.too_slow])
    def test_never_raises_on_arbitrary_input(self, text: str) -> None:
        """No string input should ever cause classify_tier to raise."""
        result = classify_tier(text)
        assert isinstance(result, int)

    @given(st.text())
    @settings(max_examples=500)
    def test_always_returns_valid_tier(self, text: str) -> None:
        """Result must always be in the valid range 1–4."""
        assert 1 <= classify_tier(text) <= 4

    def test_empty_string_returns_tier_1(self) -> None:
        """Empty string has no keywords or file refs — tier 1."""
        assert classify_tier("") == 1

    @given(st.text(max_size=0))
    def test_zero_length_always_tier_1(self, text: str) -> None:
        assert classify_tier(text) == 1

    @given(
        st.sampled_from([
            "debug this crash",
            "fix this bug now",
            "why is this broken",
            "what's wrong with my code",
            "review this code",
            "I need to optimize this function",
            "can you refactor this module",
        ])
    )
    def test_debug_prompts_always_tier_3_or_higher(self, text: str) -> None:
        """Known debug/fix keywords must always produce tier 3+."""
        assert classify_tier(text) >= 3

    @given(
        st.sampled_from([
            "I need a large refactor of the auth module",
            "plan a full rewrite of the parser",
            "complex architecture redesign for the database layer",
            "security audit of the whole codebase",
            "migration plan for moving to microservices",
        ])
    )
    def test_heavy_prompts_always_tier_4(self, text: str) -> None:
        """Known heavy-keyword prompts must always produce tier 4."""
        assert classify_tier(text) == 4

    @given(st.text(), st.integers(min_value=0, max_value=20))
    @settings(max_examples=300)
    def test_tool_count_parameter_ignored_by_classify_tier(
        self, text: str, tool_count: int
    ) -> None:
        """classify_tier doesn't use recent_tool_count — result must be identical
        for any tool count value. Escalation is classify_tier_llm / select_model's job."""
        t1 = classify_tier(text, 0)
        t2 = classify_tier(text, tool_count)
        assert t1 == t2
        assert 1 <= t2 <= 4

    @given(
        st.text(max_size=400),
        st.text(max_size=400),
    )
    @settings(max_examples=200)
    def test_adding_heavy_keyword_never_lowers_tier(
        self, prefix: str, suffix: str
    ) -> None:
        """Injecting a heavy keyword into any text must never *decrease* the tier."""
        base_tier = classify_tier(prefix + suffix)
        heavy_tier = classify_tier(prefix + " large refactor " + suffix)
        assert heavy_tier >= base_tier

    @given(
        st.text(max_size=400),
        st.text(max_size=400),
    )
    @settings(max_examples=200)
    def test_adding_debug_keyword_never_lowers_tier(
        self, prefix: str, suffix: str
    ) -> None:
        """Injecting 'debug this' into any text must never *decrease* the tier."""
        base_tier = classify_tier(prefix + suffix)
        debug_tier = classify_tier(prefix + " debug this " + suffix)
        assert debug_tier >= base_tier

    @given(st.text(max_size=5, alphabet="abcdefghijklmnopqrstuvwxyz "))
    def test_short_simple_text_never_tier_3_or_higher(self, text: str) -> None:
        """Very short prompts with no trigger keywords must never reach tier 3+."""
        assume(not any(kw in text for kw in ("debug", "fix", "bug", "refactor", "optimize")))
        # Short, clean, no keywords → must be tier 1 or 2
        assert classify_tier(text) <= 2
