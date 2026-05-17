"""Tests for luckyd_code.cost_tracker — covers uncovered branches.

Target uncovered lines (from cov_out.txt):
  113-114  get_cumulative_cost(): fast path (sidecar file exists, reads total)
  126-127  get_cumulative_cost(): slow path (JSONL sum + write total)
  151-152  get_stats(): format string with cumulative cost
  158      _write_total(): internal write call
  171-172  reset_cumulative(): file deletion loop
  185-186  _append_new_records(): JSONL append path
  197-199  _append_new_records(): cost increment + sidecar update
  207-208  _migrate_legacy_json_once(): migration path
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from luckyd_code.cost_tracker import CostTracker, UsageRecord


# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────

def _patched_tracker(tmp_path: Path):
    """Return a CostTracker with all file paths redirected to tmp_path."""
    cost_file = tmp_path / "costs.jsonl"
    legacy_file = tmp_path / "costs.json"
    totals_file = tmp_path / "costs_total.json"

    tracker = CostTracker.__new__(CostTracker)
    tracker.records = []
    tracker._written_count = 0
    from datetime import datetime
    tracker.session_start = datetime.now()

    return tracker, cost_file, legacy_file, totals_file


# ────────────────────────────────────────────────────────────────────────────
# UsageRecord
# ────────────────────────────────────────────────────────────────────────────

class TestUsageRecord:
    def test_cost_calculated_from_tokens(self):
        rec = UsageRecord("deepseek-v4-flash", input_tokens=1000, output_tokens=500)
        assert rec.estimated_cost > 0

    def test_explicit_cost_not_recalculated(self):
        rec = UsageRecord("deepseek-v4-flash", input_tokens=1000, output_tokens=500,
                          estimated_cost=0.0, _cost_provided=True)
        assert rec.estimated_cost == 0.0

    def test_to_dict_excludes_private_fields(self):
        rec = UsageRecord("deepseek-v4-flash", 100, 200)
        d = rec.to_dict()
        assert "_cost_provided" not in d
        assert "model" in d
        assert "estimated_cost" in d

    def test_unknown_model_uses_flash_rates(self):
        rec = UsageRecord("some-unknown-model", input_tokens=1000, output_tokens=1000)
        flash = UsageRecord("deepseek-v4-flash", input_tokens=1000, output_tokens=1000)
        assert rec.estimated_cost == flash.estimated_cost

    def test_pro_model_is_more_expensive_than_flash(self):
        flash = UsageRecord("deepseek-v4-flash", input_tokens=10000, output_tokens=10000)
        pro = UsageRecord("deepseek-v4-pro", input_tokens=10000, output_tokens=10000)
        assert pro.estimated_cost > flash.estimated_cost

    def test_timestamp_auto_set(self):
        rec = UsageRecord("deepseek-v4-flash", 1, 1)
        assert rec.timestamp != ""


# ────────────────────────────────────────────────────────────────────────────
# CostTracker.record_usage + session helpers
# ────────────────────────────────────────────────────────────────────────────

class TestCostTrackerBasic:
    def test_record_usage_returns_record(self):
        tracker = CostTracker()
        with patch.object(tracker, "_append_new_records"):
            rec = tracker.record_usage("deepseek-v4-flash", 100, 200)
        assert isinstance(rec, UsageRecord)
        assert rec.model == "deepseek-v4-flash"

    def test_get_session_cost_sums_records(self):
        tracker = CostTracker()
        with patch.object(tracker, "_append_new_records"):
            tracker.record_usage("deepseek-v4-flash", 1000, 1000)
            tracker.record_usage("deepseek-v4-flash", 500, 500)
        cost = tracker.get_session_cost()
        assert cost > 0

    def test_get_session_tokens(self):
        tracker = CostTracker()
        with patch.object(tracker, "_append_new_records"):
            tracker.record_usage("deepseek-v4-flash", 300, 200)
        inp, out = tracker.get_session_tokens()
        assert inp == 300
        assert out == 200


# ────────────────────────────────────────────────────────────────────────────
# get_cumulative_cost() — fast path and slow path
# ────────────────────────────────────────────────────────────────────────────

class TestGetCumulativeCost:
    def test_fast_path_reads_sidecar(self, tmp_path):
        """Lines 113-114: sidecar file exists → reads total directly."""
        totals_file = tmp_path / "costs_total.json"
        totals_file.write_text(json.dumps({"total": 1.2345}))

        tracker = CostTracker()
        with patch("luckyd_code.cost_tracker._TOTALS_FILE", totals_file):
            result = tracker.get_cumulative_cost()
        assert abs(result - 1.2345) < 1e-9

    def test_fast_path_returns_zero_on_bad_json(self, tmp_path):
        """Sidecar exists but malformed → exception caught, falls to slow path."""
        totals_file = tmp_path / "costs_total.json"
        totals_file.write_text("not valid json")
        cost_file = tmp_path / "costs.jsonl"

        tracker = CostTracker()
        with patch("luckyd_code.cost_tracker._TOTALS_FILE", totals_file), \
             patch("luckyd_code.cost_tracker.COST_FILE", cost_file), \
             patch("luckyd_code.cost_tracker._LEGACY_COST_FILE", tmp_path / "legacy.json"):
            result = tracker.get_cumulative_cost()
        assert result == 0.0

    def test_slow_path_sums_jsonl(self, tmp_path):
        """Lines 126-127: no sidecar → reads JSONL, sums, writes sidecar."""
        cost_file = tmp_path / "costs.jsonl"
        cost_file.write_text(
            json.dumps({"estimated_cost": 0.5}) + "\n" +
            json.dumps({"estimated_cost": 0.3}) + "\n"
        )
        totals_file = tmp_path / "costs_total.json"
        legacy_file = tmp_path / "costs_legacy.json"

        tracker = CostTracker()
        with patch("luckyd_code.cost_tracker._TOTALS_FILE", totals_file), \
             patch("luckyd_code.cost_tracker.COST_FILE", cost_file), \
             patch("luckyd_code.cost_tracker._LEGACY_COST_FILE", legacy_file):
            result = tracker.get_cumulative_cost()

        assert abs(result - 0.8) < 1e-9
        # Sidecar should now be written
        assert totals_file.exists()


# ────────────────────────────────────────────────────────────────────────────
# _write_total (line 158)
# ────────────────────────────────────────────────────────────────────────────

class TestWriteTotal:
    def test_writes_total_to_file(self, tmp_path):
        totals_file = tmp_path / "costs_total.json"
        with patch("luckyd_code.cost_tracker._TOTALS_FILE", totals_file):
            CostTracker._write_total(3.14159)
        data = json.loads(totals_file.read_text())
        assert abs(data["total"] - 3.14159) < 1e-9

    def test_write_total_survives_permission_error(self, tmp_path):
        """Exception in write_total is silently suppressed."""
        with patch("luckyd_code.cost_tracker._TOTALS_FILE") as mock_path:
            mock_path.parent.mkdir.side_effect = OSError("no permission")
            # Should not raise
            CostTracker._write_total(1.0)


# ────────────────────────────────────────────────────────────────────────────
# get_stats() — cumulative line (lines 151-152, 171-172)
# ────────────────────────────────────────────────────────────────────────────

class TestGetStats:
    def test_get_stats_includes_cumulative(self):
        """Lines 151-152: cumulative cost line is present in output."""
        tracker = CostTracker()
        tracker.records = []
        with patch.object(tracker, "get_cumulative_cost", return_value=42.5):
            result = tracker.get_stats()
        assert "42.5" in result
        assert "Cumulative" in result

    def test_get_stats_format(self):
        tracker = CostTracker()
        tracker.records = []
        with patch.object(tracker, "get_cumulative_cost", return_value=0.0):
            result = tracker.get_stats()
        assert "Session tokens" in result
        assert "Session cost" in result
        assert "API calls" in result


# ────────────────────────────────────────────────────────────────────────────
# reset_cumulative() — file deletion (lines 171-172)
# ────────────────────────────────────────────────────────────────────────────

class TestResetCumulative:
    def test_reset_deletes_cost_files(self, tmp_path):
        """Lines 171-172: existing files are deleted."""
        cost_file = tmp_path / "costs.jsonl"
        legacy_file = tmp_path / "costs.json"
        totals_file = tmp_path / "costs_total.json"
        cost_file.write_text('{"estimated_cost": 1.0}\n')
        totals_file.write_text('{"total": 1.0}')

        tracker = CostTracker()
        with patch("luckyd_code.cost_tracker.COST_FILE", cost_file), \
             patch("luckyd_code.cost_tracker._LEGACY_COST_FILE", legacy_file), \
             patch("luckyd_code.cost_tracker._TOTALS_FILE", totals_file):
            result = tracker.reset_cumulative()

        assert not cost_file.exists()
        assert not totals_file.exists()
        assert "cleared" in result.lower()

    def test_reset_clears_records(self, tmp_path):
        tracker = CostTracker()
        tracker.records = [MagicMock(), MagicMock()]
        tracker._written_count = 2
        with patch("luckyd_code.cost_tracker.COST_FILE", tmp_path / "c.jsonl"), \
             patch("luckyd_code.cost_tracker._LEGACY_COST_FILE", tmp_path / "l.json"), \
             patch("luckyd_code.cost_tracker._TOTALS_FILE", tmp_path / "t.json"):
            tracker.reset_cumulative()
        assert tracker.records == []
        assert tracker._written_count == 0

    def test_reset_handles_delete_exception(self, tmp_path):
        """If file deletion fails, returns error string."""
        tracker = CostTracker()
        tracker.records = []
        with patch("luckyd_code.cost_tracker.COST_FILE") as mock_cf, \
             patch("luckyd_code.cost_tracker._LEGACY_COST_FILE") as mock_lf, \
             patch("luckyd_code.cost_tracker._TOTALS_FILE") as mock_tf:
            mock_cf.exists.return_value = True
            mock_cf.unlink.side_effect = PermissionError("locked")
            mock_lf.exists.return_value = False
            mock_tf.exists.return_value = False
            result = tracker.reset_cumulative()
        assert "Failed" in result


# ────────────────────────────────────────────────────────────────────────────
# _append_new_records() — JSONL append + sidecar update (lines 185-199)
# ────────────────────────────────────────────────────────────────────────────

class TestAppendNewRecords:
    def test_appends_to_jsonl_file(self, tmp_path):
        """Lines 185-186: new records are written to JSONL."""
        cost_file = tmp_path / "costs.jsonl"
        totals_file = tmp_path / "costs_total.json"
        totals_file.write_text(json.dumps({"total": 0.0}))

        tracker = CostTracker()
        tracker.records = [UsageRecord("deepseek-v4-flash", 1000, 500)]
        tracker._written_count = 0

        with patch("luckyd_code.cost_tracker.COST_FILE", cost_file), \
             patch("luckyd_code.cost_tracker._TOTALS_FILE", totals_file), \
             patch("luckyd_code.cost_tracker._LEGACY_COST_FILE", tmp_path / "legacy.json"), \
             patch.object(CostTracker, "_migrate_legacy_json_once"):
            tracker._append_new_records()

        assert cost_file.exists()
        lines = cost_file.read_text().strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["model"] == "deepseek-v4-flash"

    def test_sidecar_updated_after_append(self, tmp_path):
        """Lines 197-199: sidecar total incremented by new cost."""
        cost_file = tmp_path / "costs.jsonl"
        totals_file = tmp_path / "costs_total.json"
        totals_file.write_text(json.dumps({"total": 1.0}))

        tracker = CostTracker()
        rec = UsageRecord("deepseek-v4-flash", input_tokens=10000, output_tokens=5000)
        tracker.records = [rec]
        tracker._written_count = 0

        with patch("luckyd_code.cost_tracker.COST_FILE", cost_file), \
             patch("luckyd_code.cost_tracker._TOTALS_FILE", totals_file), \
             patch("luckyd_code.cost_tracker._LEGACY_COST_FILE", tmp_path / "legacy.json"), \
             patch.object(CostTracker, "_migrate_legacy_json_once"):
            tracker._append_new_records()

        new_total_data = json.loads(totals_file.read_text())
        assert new_total_data["total"] > 1.0  # increased by the record's cost

    def test_no_op_when_nothing_new(self, tmp_path):
        """_append_new_records does nothing when all records already flushed."""
        tracker = CostTracker()
        tracker.records = [UsageRecord("deepseek-v4-flash", 1, 1)]
        tracker._written_count = 1  # already written

        with patch("luckyd_code.cost_tracker.COST_FILE") as mock_cf:
            tracker._append_new_records()
        # File should not be opened at all
        mock_cf.open.assert_not_called()

    def test_survives_write_exception(self, tmp_path):
        """Exception during write is caught and logged, not raised."""
        cost_file = tmp_path / "costs.jsonl"

        tracker = CostTracker()
        tracker.records = [UsageRecord("deepseek-v4-flash", 100, 100)]
        tracker._written_count = 0

        with patch("luckyd_code.cost_tracker.COST_FILE", cost_file), \
             patch("luckyd_code.cost_tracker._LEGACY_COST_FILE", tmp_path / "legacy.json"), \
             patch.object(CostTracker, "_migrate_legacy_json_once",
                          side_effect=OSError("disk full")):
            # Should not raise
            tracker._append_new_records()


# ────────────────────────────────────────────────────────────────────────────
# _migrate_legacy_json_once() (lines 207-208)
# ────────────────────────────────────────────────────────────────────────────

class TestMigrateLegacy:
    def test_migrates_legacy_json_to_jsonl(self, tmp_path):
        """Lines 207-208: legacy JSON → JSONL migration."""
        legacy_file = tmp_path / "costs.json"
        cost_file = tmp_path / "costs.jsonl"

        legacy_data = [
            {"model": "deepseek-v4-flash", "estimated_cost": 0.1},
            {"model": "deepseek-v4-flash", "estimated_cost": 0.2},
        ]
        legacy_file.write_text(json.dumps(legacy_data))

        with patch("luckyd_code.cost_tracker._LEGACY_COST_FILE", legacy_file), \
             patch("luckyd_code.cost_tracker.COST_FILE", cost_file):
            CostTracker._migrate_legacy_json_once()

        assert cost_file.exists()
        assert not legacy_file.exists()  # deleted after migration
        lines = cost_file.read_text().strip().split("\n")
        assert len(lines) == 2

    def test_skips_migration_when_cost_file_exists(self, tmp_path):
        """Migration skipped if costs.jsonl already exists."""
        legacy_file = tmp_path / "costs.json"
        cost_file = tmp_path / "costs.jsonl"
        cost_file.write_text("")  # already exists
        legacy_file.write_text("[]")

        with patch("luckyd_code.cost_tracker._LEGACY_COST_FILE", legacy_file), \
             patch("luckyd_code.cost_tracker.COST_FILE", cost_file):
            CostTracker._migrate_legacy_json_once()

        # Legacy file should NOT have been touched
        assert legacy_file.exists()

    def test_migration_handles_bad_json(self, tmp_path):
        """Malformed legacy JSON is caught and logged, not raised."""
        legacy_file = tmp_path / "costs.json"
        cost_file = tmp_path / "costs.jsonl"
        legacy_file.write_text("not json")

        with patch("luckyd_code.cost_tracker._LEGACY_COST_FILE", legacy_file), \
             patch("luckyd_code.cost_tracker.COST_FILE", cost_file):
            CostTracker._migrate_legacy_json_once()

        # Should not raise; cost_file should not exist
        assert not cost_file.exists()


# ────────────────────────────────────────────────────────────────────────────
# _load_all()
# ────────────────────────────────────────────────────────────────────────────

class TestLoadAll:
    def test_loads_jsonl_records(self, tmp_path):
        cost_file = tmp_path / "costs.jsonl"
        cost_file.write_text(
            '{"model": "deepseek-v4-flash", "estimated_cost": 0.1}\n'
            '{"model": "deepseek-v4-flash", "estimated_cost": 0.2}\n'
        )
        with patch("luckyd_code.cost_tracker.COST_FILE", cost_file), \
             patch("luckyd_code.cost_tracker._LEGACY_COST_FILE", tmp_path / "no.json"):
            records = CostTracker._load_all()
        assert len(records) == 2

    def test_loads_legacy_json_when_no_jsonl(self, tmp_path):
        legacy_file = tmp_path / "costs.json"
        cost_file = tmp_path / "costs.jsonl"
        legacy_file.write_text(json.dumps([{"estimated_cost": 0.5}]))

        with patch("luckyd_code.cost_tracker._LEGACY_COST_FILE", legacy_file), \
             patch("luckyd_code.cost_tracker.COST_FILE", cost_file):
            records = CostTracker._load_all()
        assert len(records) == 1

    def test_returns_empty_when_no_files(self, tmp_path):
        cost_file = tmp_path / "costs.jsonl"
        legacy_file = tmp_path / "costs.json"
        with patch("luckyd_code.cost_tracker.COST_FILE", cost_file), \
             patch("luckyd_code.cost_tracker._LEGACY_COST_FILE", legacy_file):
            records = CostTracker._load_all()
        assert records == []


class TestWriteTotalWarning:
    """_write_total should log a WARNING (not swallow silently) on failure."""

    def test_write_total_logs_warning_on_ioerror(self, tmp_path, caplog):
        import logging
        # Point _TOTALS_FILE at a path whose parent does NOT exist and cannot
        # be created (simulate by making the parent a file, not a directory).
        fake_parent = tmp_path / "is_a_file.txt"
        fake_parent.write_text("blocker")
        bad_totals = fake_parent / "costs_total.json"  # parent is a file → mkdir will fail

        with patch("luckyd_code.cost_tracker._TOTALS_FILE", bad_totals), \
             caplog.at_level(logging.WARNING, logger="luckyd_code.cost_tracker"):
            CostTracker._write_total(1.23)

        assert any("persist cost total" in r.message for r in caplog.records), (
            "Expected a WARNING about failing to persist the cost total, but none was emitted"
        )
