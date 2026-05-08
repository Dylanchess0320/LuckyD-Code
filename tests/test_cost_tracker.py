"""Tests for luckyd_code.cost_tracker — usage cost tracking."""

import json

import pytest

from luckyd_code.cost_tracker import (
    CostTracker,
    UsageRecord,
)


class TestUsageRecord:
    """Tests for the UsageRecord dataclass."""

    def test_default_values(self):
        """UsageRecord should auto-set timestamp and calculate cost."""
        rec = UsageRecord(model="deepseek-v4-flash", input_tokens=1000, output_tokens=500)
        assert rec.model == "deepseek-v4-flash"
        assert rec.input_tokens == 1000
        assert rec.output_tokens == 500
        assert rec.timestamp != ""
        assert rec.estimated_cost > 0.0

    def test_zero_tokens_zero_cost(self):
        """Zero tokens should give zero cost."""
        rec = UsageRecord(model="deepseek-v4-flash", input_tokens=0, output_tokens=0)
        assert rec.estimated_cost == 0.0

    def test_explicit_cost_overrides_calculation(self):
        """Explicit cost parameter should override calculation."""
        rec = UsageRecord(
            model="deepseek-v4-flash",
            input_tokens=100000,
            output_tokens=50000,
            estimated_cost=0.005,
            _cost_provided=True,
        )
        assert rec.estimated_cost == 0.005

    def test_cost_calculation(self):
        """Verify cost calculation for known models."""
        # Flash: $0.000140/1K in, $0.000280/1K out
        rec = UsageRecord(model="deepseek-v4-flash", input_tokens=1000, output_tokens=0)
        assert rec.estimated_cost == pytest.approx(0.000140, rel=0.01)

        # Both input and output
        rec = UsageRecord(model="deepseek-v4-flash", input_tokens=1000, output_tokens=1000)
        assert rec.estimated_cost == pytest.approx(0.000420, rel=0.01)

    def test_pro_model_cost(self):
        """Verify Pro model costs."""
        rec = UsageRecord(model="deepseek-v4-pro", input_tokens=1000, output_tokens=0)
        assert rec.estimated_cost == pytest.approx(0.001740, rel=0.01)

    def test_unknown_model_defaults_to_flash_price(self):
        """Unknown model should default to flash pricing."""
        rec = UsageRecord(model="unknown-model-xyz", input_tokens=1000, output_tokens=0)
        assert rec.estimated_cost == pytest.approx(0.000140, rel=0.01)

    def test_legacy_model_names_work(self):
        """Legacy model names should resolve to flash pricing."""
        for model in ["deepseek-chat", "deepseek-reasoner"]:
            rec = UsageRecord(model=model, input_tokens=1000, output_tokens=0)
            assert rec.estimated_cost == pytest.approx(0.000140, rel=0.01)

    def test_timestamp_is_formatted(self):
        """Timestamp should be ISO format."""
        rec = UsageRecord(model="deepseek-v4-flash", input_tokens=1, output_tokens=1)
        assert "T" in rec.timestamp  # ISO 8601


class TestCostTracker:
    """Tests for CostTracker."""

    @pytest.fixture(autouse=True)
    def isolate_cost_file(self, monkeypatch, temp_dir):
        """Redirect cost files to temp directory."""
        cost_file = temp_dir / "costs.jsonl"
        legacy_file = temp_dir / "costs.json"
        totals_file = temp_dir / "costs_total.json"
        monkeypatch.setattr(
            "luckyd_code.cost_tracker.COST_FILE", cost_file
        )
        monkeypatch.setattr(
            "luckyd_code.cost_tracker._LEGACY_COST_FILE", legacy_file
        )
        monkeypatch.setattr(
            "luckyd_code.cost_tracker._TOTALS_FILE", totals_file
        )
        yield cost_file

    def test_record_usage_adds_record(self, isolate_cost_file):
        """record_usage should add a record and return it."""
        tracker = CostTracker()
        rec = tracker.record_usage("deepseek-v4-flash", 100, 50)
        assert rec.model == "deepseek-v4-flash"
        assert len(tracker.records) == 1

    def test_get_session_cost(self, isolate_cost_file):
        """get_session_cost should sum all records' costs."""
        tracker = CostTracker()
        tracker.record_usage("deepseek-v4-flash", 1000, 500)
        tracker.record_usage("deepseek-v4-flash", 500, 1000)
        cost = tracker.get_session_cost()
        # (1000/1000*0.000140 + 500/1000*0.000280) + (500/1000*0.000140 + 1000/1000*0.000280)
        # = (0.000140 + 0.000140) + (0.000070 + 0.000280) = 0.000280 + 0.000350 = 0.000630
        assert cost == pytest.approx(0.000630, rel=0.01)

    def test_get_session_tokens(self, isolate_cost_file):
        """get_session_tokens should return (input, output) totals."""
        tracker = CostTracker()
        tracker.record_usage("deepseek-v4-flash", 100, 50)
        tracker.record_usage("deepseek-v4-flash", 200, 75)
        inp, out = tracker.get_session_tokens()
        assert inp == 300
        assert out == 125

    def test_get_cumulative_cost_no_history(self, isolate_cost_file):
        """get_cumulative_cost should be 0 with no history."""
        tracker = CostTracker()
        assert tracker.get_cumulative_cost() == 0.0

    def test_persistence(self, isolate_cost_file):
        """Records should be persisted to JSONL."""
        tracker = CostTracker()
        tracker.record_usage("deepseek-v4-flash", 1000, 500)

        # Read the JSONL file directly
        lines = isolate_cost_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["model"] == "deepseek-v4-flash"
        assert data["input_tokens"] == 1000
        assert data["output_tokens"] == 500

    def test_multiple_records(self, isolate_cost_file):
        """Multiple records should be appended."""
        tracker = CostTracker()
        tracker.record_usage("deepseek-v4-flash", 100, 50)
        tracker.record_usage("deepseek-v4-pro", 200, 100)

        assert len(tracker.records) == 2
        lines = isolate_cost_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2

    def test_get_stats_returns_string(self, isolate_cost_file):
        """get_stats should return a non-empty string."""
        tracker = CostTracker()
        tracker.record_usage("deepseek-v4-flash", 1000, 500)
        stats = tracker.get_stats()
        assert isinstance(stats, str)
        assert "Cost Tracking" in stats

    def test_reset_cumulative(self, isolate_cost_file):
        """reset_cumulative should clear records."""
        tracker = CostTracker()
        tracker.record_usage("deepseek-v4-flash", 1000, 500)
        assert len(tracker.records) == 1

        result = tracker.reset_cumulative()
        assert "cleared" in result.lower()
        assert len(tracker.records) == 0
