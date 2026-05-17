"""Tests for dream.py _phase_consolidate and _llm_merge — covers lines 165-242."""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from luckyd_code.dream import DreamCycle, DreamReport, _GROUP_SIZE_TO_MERGE, _MAX_MERGE_CALLS


# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────

def _make_mm(load_content: str = "shared python code quality refactor testing improvement") -> MagicMock:
    mm = MagicMock()
    mm.load_memory.return_value = load_content
    mm.save_memory.return_value = "/tmp/merged.md"
    mm.delete_memory.return_value = True
    mm.decay.return_value = 0
    return mm


def _make_group(size: int = 3) -> list[dict]:
    return [{"name": f"mem_{i}", "type": "general"} for i in range(size)]


def _make_mock_config(api_key: str = "sk-test", model: str = "deepseek-v4-flash") -> MagicMock:
    cfg = MagicMock()
    cfg.api_key = api_key
    cfg.base_url = "https://api.deepseek.com/v1"
    cfg.model = model
    return cfg


# ────────────────────────────────────────────────────────────────────────────
# _phase_consolidate — missing branch coverage (lines 165-195)
# ────────────────────────────────────────────────────────────────────────────

class TestPhaseConsolidate:
    def test_config_none_skips_entirely(self):
        mm = _make_mm()
        cycle = DreamCycle(mm, config=None)
        report = DreamReport()
        group = _make_group(size=_GROUP_SIZE_TO_MERGE)
        cycle._phase_consolidate([group], report)
        assert report.phase_3_memories_merged == 0
        assert report.errors == []

    def test_empty_groups_list_does_nothing(self):
        mm = _make_mm()
        cfg = _make_mock_config()
        cycle = DreamCycle(mm, config=cfg)
        report = DreamReport()
        cycle._phase_consolidate([], report)
        assert report.phase_3_memories_merged == 0

    def test_group_below_threshold_skipped(self):
        mm = _make_mm()
        cfg = _make_mock_config()
        cycle = DreamCycle(mm, config=cfg)
        report = DreamReport()
        small_group = _make_group(size=_GROUP_SIZE_TO_MERGE - 1)
        cycle._phase_consolidate([small_group], report)
        assert report.phase_3_memories_merged == 0

    def test_merge_cap_prevents_excess_calls(self):
        """Once merge_calls reaches _MAX_MERGE_CALLS, the loop breaks."""
        mm = _make_mm()
        cfg = _make_mock_config()
        cycle = DreamCycle(mm, config=cfg)
        report = DreamReport()

        # Create more groups than the cap allows
        groups = [_make_group(size=_GROUP_SIZE_TO_MERGE) for _ in range(_MAX_MERGE_CALLS + 3)]

        with patch.object(cycle, "_llm_merge", return_value=("merged", "consolidated content")):
            cycle._phase_consolidate(groups, report)

        # Should not exceed _MAX_MERGE_CALLS merges
        assert report.phase_3_memories_merged <= _MAX_MERGE_CALLS * _GROUP_SIZE_TO_MERGE

    def test_successful_merge_updates_report(self):
        mm = _make_mm()
        cfg = _make_mock_config()
        cycle = DreamCycle(mm, config=cfg)
        report = DreamReport()
        group = _make_group(size=_GROUP_SIZE_TO_MERGE)

        with patch.object(cycle, "_llm_merge", return_value=("merged_name", "merged content here")):
            cycle._phase_consolidate([group], report)

        assert report.phase_3_memories_merged == _GROUP_SIZE_TO_MERGE
        mm.save_memory.assert_called_once()

    def test_empty_merged_content_skips_save(self):
        """If _llm_merge returns empty content, the group is not saved."""
        mm = _make_mm()
        cfg = _make_mock_config()
        cycle = DreamCycle(mm, config=cfg)
        report = DreamReport()
        group = _make_group(size=_GROUP_SIZE_TO_MERGE)

        with patch.object(cycle, "_llm_merge", return_value=("name", "")):
            cycle._phase_consolidate([group], report)

        assert report.phase_3_memories_merged == 0
        mm.save_memory.assert_not_called()

    def test_merge_exception_captured_in_errors(self):
        """If _llm_merge raises, the error is logged and processing continues."""
        mm = _make_mm()
        cfg = _make_mock_config()
        cycle = DreamCycle(mm, config=cfg)
        report = DreamReport()
        group = _make_group(size=_GROUP_SIZE_TO_MERGE)

        with patch.object(cycle, "_llm_merge", side_effect=RuntimeError("api timeout")):
            cycle._phase_consolidate([group], report)

        assert len(report.errors) == 1
        assert "api timeout" in report.errors[0]
        assert report.phase_3_memories_merged == 0

    def test_delete_originals_before_save(self):
        """Original memories are deleted before the merged memory is saved."""
        mm = _make_mm()
        cfg = _make_mock_config()
        cycle = DreamCycle(mm, config=cfg)
        report = DreamReport()
        group = _make_group(size=_GROUP_SIZE_TO_MERGE)

        delete_calls = []
        mm.delete_memory.side_effect = lambda name, typ: delete_calls.append((name, typ))

        with patch.object(cycle, "_llm_merge", return_value=("m", "content")):
            cycle._phase_consolidate([group], report)

        assert len(delete_calls) == _GROUP_SIZE_TO_MERGE

    def test_dominant_memory_type_used_for_merged(self):
        """Merged memory uses the most common type from the group."""
        mm = _make_mm()
        cfg = _make_mock_config()
        cycle = DreamCycle(mm, config=cfg)
        report = DreamReport()
        # 2 "task" + 1 "general" → "task" wins
        group = [
            {"name": "a", "type": "task"},
            {"name": "b", "type": "task"},
            {"name": "c", "type": "general"},
        ]

        captured = {}

        def fake_save(name, content, memory_type=None, importance=None):
            captured["memory_type"] = memory_type
            return "/tmp/merged.md"

        mm.save_memory.side_effect = fake_save

        with patch.object(cycle, "_llm_merge", return_value=("merged", "some content")):
            cycle._phase_consolidate([group], report)

        assert captured.get("memory_type") == "task"


# ────────────────────────────────────────────────────────────────────────────
# _llm_merge — missing coverage (lines 202-242)
# ────────────────────────────────────────────────────────────────────────────

class TestLlmMerge:
    def _make_llm_response(self, name: str, content: str) -> MagicMock:
        choice = MagicMock()
        choice.message.content = f"NAME: {name}\nCONTENT: {content}"
        resp = MagicMock()
        resp.choices = [choice]
        return resp

    def test_successful_merge_parses_name_and_content(self):
        mm = _make_mm()
        cfg = _make_mock_config()
        cycle = DreamCycle(mm, config=cfg)
        group = _make_group(size=3)

        mock_resp = self._make_llm_response("python_quality", "Python code quality guidelines.")
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_resp

        with patch("luckyd_code.dream.OpenAI", return_value=mock_client):
            name, content = cycle._llm_merge(group)

        assert name == "python_quality"
        assert content == "Python code quality guidelines."

    def test_merge_uses_config_model(self):
        mm = _make_mm()
        cfg = _make_mock_config(model="my-custom-model")
        cycle = DreamCycle(mm, config=cfg)
        group = _make_group(size=3)

        mock_resp = self._make_llm_response("n", "c")
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_resp

        with patch("luckyd_code.dream.OpenAI", return_value=mock_client) as mock_oai:
            cycle._llm_merge(group)

        create_call = mock_client.chat.completions.create.call_args
        assert create_call.kwargs["model"] == "my-custom-model"

    def test_merge_defaults_consolidation_model_when_config_has_no_model(self):
        from luckyd_code.dream import _CONSOLIDATION_MODEL
        mm = _make_mm()
        cfg = MagicMock(spec=[])  # no 'model' attribute
        cfg.api_key = "sk-test"
        cfg.base_url = "https://api.deepseek.com/v1"
        cycle = DreamCycle(mm, config=cfg)
        group = _make_group(size=3)

        mock_resp = self._make_llm_response("n", "c")
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_resp

        with patch("luckyd_code.dream.OpenAI", return_value=mock_client):
            name, content = cycle._llm_merge(group)

        create_call = mock_client.chat.completions.create.call_args
        assert create_call.kwargs["model"] == _CONSOLIDATION_MODEL

    def test_merge_with_malformed_response_defaults(self):
        """If LLM response doesn't have NAME:/CONTENT: lines, defaults apply."""
        mm = _make_mm()
        cfg = _make_mock_config()
        cycle = DreamCycle(mm, config=cfg)
        group = _make_group(size=3)

        choice = MagicMock()
        choice.message.content = "Just some random text without proper format."
        resp = MagicMock()
        resp.choices = [choice]
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = resp

        with patch("luckyd_code.dream.OpenAI", return_value=mock_client):
            name, content = cycle._llm_merge(group)

        assert name == "consolidated"  # default
        assert content == ""  # no CONTENT: line found

    def test_merge_truncates_long_names(self):
        """Names over 40 characters should be truncated."""
        mm = _make_mm()
        cfg = _make_mock_config()
        cycle = DreamCycle(mm, config=cfg)
        group = _make_group(size=3)

        long_name = "a" * 60
        mock_resp = self._make_llm_response(long_name, "short content")
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_resp

        with patch("luckyd_code.dream.OpenAI", return_value=mock_client):
            name, _ = cycle._llm_merge(group)

        assert len(name) <= 40

    def test_merge_loads_memory_content_for_prompt(self):
        """_llm_merge calls load_memory for each group member."""
        mm = _make_mm("memory about python testing")
        cfg = _make_mock_config()
        cycle = DreamCycle(mm, config=cfg)
        group = _make_group(size=3)

        mock_resp = self._make_llm_response("n", "c")
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_resp

        with patch("luckyd_code.dream.OpenAI", return_value=mock_client):
            cycle._llm_merge(group)

        assert mm.load_memory.call_count == 3

    def test_merge_handles_none_response_content(self):
        """If LLM returns None content, defaults to empty string gracefully."""
        mm = _make_mm()
        cfg = _make_mock_config()
        cycle = DreamCycle(mm, config=cfg)
        group = _make_group(size=3)

        choice = MagicMock()
        choice.message.content = None
        resp = MagicMock()
        resp.choices = [choice]
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = resp

        with patch("luckyd_code.dream.OpenAI", return_value=mock_client):
            name, content = cycle._llm_merge(group)

        assert isinstance(name, str)
        assert isinstance(content, str)
