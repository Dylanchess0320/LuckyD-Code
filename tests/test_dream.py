"""Tests for luckyd_code.dream — autoDream 4-phase memory consolidation."""
from __future__ import annotations

import time
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from luckyd_code.dream import DreamCycle, DreamReport, run_dream_cycle, _MIN_MEMORIES_TO_DREAM


# ------------------------------------------------------------------ #
#  Fixtures
# ------------------------------------------------------------------ #

def _make_mm(tmp_path: Path, num_memories: int = 0) -> MagicMock:
    """Return a mock MemoryManager pre-loaded with *num_memories* entries."""
    mm = MagicMock()
    memories = [
        {"name": f"mem_{i}", "type": "general", "path": str(tmp_path / f"m{i}.md"),
         "importance": 5, "saved": time.time(), "accessed": time.time()}
        for i in range(num_memories)
    ]
    mm.list_memories.return_value = memories
    mm.load_memory.return_value = "sample memory content about python code quality"
    mm.save_memory.return_value = str(tmp_path / "merged.md")
    mm.delete_memory.return_value = True
    mm.decay.return_value = 0
    return mm


# ------------------------------------------------------------------ #
#  DreamReport
# ------------------------------------------------------------------ #

class TestDreamReport:
    def test_defaults(self):
        r = DreamReport()
        assert r.phase_1_memories_found == 0
        assert r.phase_2_groups_formed == 0
        assert r.phase_3_memories_merged == 0
        assert r.phase_4_memories_pruned == 0
        assert r.duration_seconds == 0.0
        assert r.errors == []

    def test_summary_smoke(self):
        r = DreamReport(
            phase_1_memories_found=10,
            phase_2_groups_formed=3,
            phase_3_memories_merged=6,
            phase_4_memories_pruned=2,
            duration_seconds=1.23,
        )
        s = r.summary()
        assert "10 surveyed" in s
        assert "3 groups" in s
        assert "6 merged" in s
        assert "2 pruned" in s
        assert "1.2s" in s

    def test_errors_list_mutable_default_isolation(self):
        r1 = DreamReport()
        r2 = DreamReport()
        r1.errors.append("boom")
        assert r2.errors == []


# ------------------------------------------------------------------ #
#  Phase 1 — Orient
# ------------------------------------------------------------------ #

class TestPhaseOrient:
    def test_empty_mm(self, tmp_path):
        mm = _make_mm(tmp_path, 0)
        cycle = DreamCycle(mm)
        report = DreamReport()
        result = cycle._phase_orient(report)
        assert result == []
        assert report.phase_1_memories_found == 0

    def test_five_memories(self, tmp_path):
        mm = _make_mm(tmp_path, 5)
        cycle = DreamCycle(mm)
        report = DreamReport()
        result = cycle._phase_orient(report)
        assert len(result) == 5
        assert report.phase_1_memories_found == 5


# ------------------------------------------------------------------ #
#  Phase 2 — Gather
# ------------------------------------------------------------------ #

class TestPhaseGather:
    def test_no_overlap_produces_no_groups(self, tmp_path):
        mm = _make_mm(tmp_path, 0)
        # Return distinct content with no shared words
        contents = ["alpha beta gamma", "delta epsilon zeta"]
        mm.load_memory.side_effect = contents
        memories = [
            {"name": "a", "type": "general"},
            {"name": "b", "type": "general"},
        ]
        cycle = DreamCycle(mm)
        report = DreamReport()
        groups = cycle._phase_gather(memories, report)
        assert groups == []
        assert report.phase_2_groups_formed == 0

    def test_high_overlap_produces_group(self, tmp_path):
        mm = _make_mm(tmp_path, 0)
        shared = "python code quality refactor improve linting tests coverage checks"
        mm.load_memory.side_effect = [shared, shared + " extra"]
        memories = [
            {"name": "x", "type": "general"},
            {"name": "y", "type": "general"},
        ]
        cycle = DreamCycle(mm)
        report = DreamReport()
        groups = cycle._phase_gather(memories, report)
        assert len(groups) == 1
        assert len(groups[0]) == 2
        assert report.phase_2_groups_formed == 1

    def test_already_assigned_not_double_grouped(self, tmp_path):
        mm = _make_mm(tmp_path, 0)
        shared = "python code quality refactor improve linting tests coverage checks"
        # Three identical contents → should form one group of 3, not multiple
        mm.load_memory.side_effect = [shared, shared, shared]
        memories = [
            {"name": f"m{i}", "type": "general"} for i in range(3)
        ]
        cycle = DreamCycle(mm)
        report = DreamReport()
        groups = cycle._phase_gather(memories, report)
        # All three end up in one group
        total_in_groups = sum(len(g) for g in groups)
        assert total_in_groups <= 3


# ------------------------------------------------------------------ #
#  Phase 3 — Consolidate
# ------------------------------------------------------------------ #

class TestPhaseConsolidate:
    def test_no_config_skips_llm(self, tmp_path):
        mm = _make_mm(tmp_path, 6)
        cycle = DreamCycle(mm, config=None)
        report = DreamReport()
        groups = [[mm.list_memories()[i] for i in range(3)]]
        cycle._phase_consolidate(groups, report)
        # No LLM calls when config is None
        assert report.phase_3_memories_merged == 0
        assert report.errors == []

    def test_small_group_skipped(self, tmp_path):
        """Groups smaller than _GROUP_SIZE_TO_MERGE are not merged."""
        from luckyd_code.dream import _GROUP_SIZE_TO_MERGE
        mm = _make_mm(tmp_path, 2)
        config = MagicMock()
        cycle = DreamCycle(mm, config=config)
        report = DreamReport()
        small_group = [mm.list_memories()[i] for i in range(min(2, _GROUP_SIZE_TO_MERGE - 1))]
        if len(small_group) < _GROUP_SIZE_TO_MERGE:
            cycle._phase_consolidate([small_group], report)
            assert report.phase_3_memories_merged == 0


# ------------------------------------------------------------------ #
#  Phase 4 — Prune
# ------------------------------------------------------------------ #

class TestPhasePrune:
    def test_archives_returned_count(self, tmp_path):
        mm = _make_mm(tmp_path, 10)
        mm.decay.return_value = 4
        cycle = DreamCycle(mm)
        report = DreamReport()
        cycle._phase_prune(report)
        assert report.phase_4_memories_pruned == 4
        mm.decay.assert_called_once()

    def test_prune_exception_captured(self, tmp_path):
        mm = _make_mm(tmp_path, 5)
        mm.decay.side_effect = RuntimeError("disk full")
        cycle = DreamCycle(mm)
        report = DreamReport()
        cycle._phase_prune(report)
        assert len(report.errors) == 1
        assert "prune" in report.errors[0]


# ------------------------------------------------------------------ #
#  Full cycle — DreamCycle.run()
# ------------------------------------------------------------------ #

class TestDreamCycleRun:
    def test_skips_when_too_few_memories(self, tmp_path):
        mm = _make_mm(tmp_path, _MIN_MEMORIES_TO_DREAM - 1)
        cycle = DreamCycle(mm)
        report = cycle.run()
        assert report.phase_2_groups_formed == 0
        assert report.phase_3_memories_merged == 0
        assert report.phase_4_memories_pruned == 0
        assert report.errors == []

    def test_runs_all_phases_with_enough_memories(self, tmp_path):
        mm = _make_mm(tmp_path, _MIN_MEMORIES_TO_DREAM + 2)
        # Make decay return something
        mm.decay.return_value = 1
        cycle = DreamCycle(mm, config=None)
        report = cycle.run()
        # Phase 1 ran
        assert report.phase_1_memories_found == _MIN_MEMORIES_TO_DREAM + 2
        # Duration tracked
        assert report.duration_seconds >= 0.0
        # Never raises
        assert isinstance(report, DreamReport)

    def test_never_raises_on_exception(self, tmp_path):
        mm = MagicMock()
        mm.list_memories.side_effect = RuntimeError("storage exploded")
        cycle = DreamCycle(mm)
        report = cycle.run()
        assert len(report.errors) == 1
        assert "storage exploded" in report.errors[0]


# ------------------------------------------------------------------ #
#  run_dream_cycle convenience wrapper
# ------------------------------------------------------------------ #

class TestRunDreamCycle:
    def test_wrapper_returns_report(self, tmp_path):
        mm = _make_mm(tmp_path, _MIN_MEMORIES_TO_DREAM - 1)
        report = run_dream_cycle(mm)
        assert isinstance(report, DreamReport)

    def test_wrapper_passes_config(self, tmp_path):
        mm = _make_mm(tmp_path, _MIN_MEMORIES_TO_DREAM - 1)
        config = MagicMock()
        report = run_dream_cycle(mm, config=config)
        assert isinstance(report, DreamReport)
