"""Track API usage costs per session with persistence."""

import json
import logging
from dataclasses import dataclass, field, fields
from datetime import datetime
from typing import Any, cast

from ._data_dir import data_path, legacy_path

__all__ = ["UsageRecord", "CostTracker"]

COST_FILE = data_path("costs.jsonl")  # append-only, one JSON record per line
_LEGACY_COST_FILE = legacy_path("costs.json")  # migrated on first write
_TOTALS_FILE = data_path("costs_total.json")  # single-float running total

_logger = logging.getLogger("luckyd_code.cost_tracker")


@dataclass
class UsageRecord:
    model: str
    input_tokens: int
    output_tokens: int
    timestamp: str = ""
    estimated_cost: float = 0.0
    # Internal flag — excluded from serialization so it never appears in
    # costs.jsonl.  repr=False keeps it out of str() output too.
    _cost_provided: bool = field(default=False, repr=False)

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()
        # Only recalculate when cost was NOT explicitly provided by the caller.
        # This preserves intentional zero-cost values (e.g. cached / free responses).
        if not self._cost_provided and (self.input_tokens > 0 or self.output_tokens > 0):
            self.estimated_cost = self._calc_cost()

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict, excluding internal/private fields."""
        return {
            f.name: getattr(self, f.name)
            for f in fields(self)
            if not f.name.startswith("_")
        }

    def _calc_cost(self) -> float:
        """Estimate cost using approximate per-token rates.

        Rates (per 1K tokens, USD):
          deepseek-v4-flash : $0.000140 in / $0.000280 out
          deepseek-v4-pro   : $0.001740 in / $0.003480 out
          deepseek-chat     : legacy alias for deepseek-v4-flash
          deepseek-reasoner : legacy alias for deepseek-v4-flash (thinking mode)
        Prices sourced from api-docs.deepseek.com/quick_start/pricing (2026-04-26)
        """
        rates = {
            # Current V4 models
            "deepseek-v4-flash": (0.000140, 0.000280),
            "deepseek-v4-pro":   (0.001740, 0.003480),
            # Legacy names — now route to deepseek-v4-flash
            "deepseek-chat":     (0.000140, 0.000280),
            "deepseek-reasoner": (0.000140, 0.000280),
            # Older models (kept for historical cost records)
            "deepseek-v3-0324":  (0.000270, 0.001100),
            "deepseek-v3":       (0.000270, 0.001100),
        }
        # Default to v4-flash pricing for unknown models
        input_rate, output_rate = rates.get(self.model, (0.000140, 0.000280))
        return (self.input_tokens / 1000 * input_rate) + (
            self.output_tokens / 1000 * output_rate
        )


class CostTracker:
    """Records API usage costs per session with cumulative tracking."""

    def __init__(self) -> None:
        self.session_start = datetime.now()
        self.records: list[UsageRecord] = []
        self._written_count: int = 0  # how many records already flushed to disk

    def record_usage(self, model: str, input_tokens: int, output_tokens: int,
                     cost: float | None = None) -> UsageRecord:
        rec = UsageRecord(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost=cost if cost is not None else 0.0,
            _cost_provided=cost is not None,
        )
        self.records.append(rec)
        self._append_new_records()
        return rec

    def get_session_cost(self) -> float:
        return sum(r.estimated_cost for r in self.records)

    def get_session_tokens(self) -> tuple[int, int]:
        inp = sum(r.input_tokens for r in self.records)
        out = sum(r.output_tokens for r in self.records)
        return inp, out

    def get_cumulative_cost(self) -> float:
        """Return the lifetime total cost in O(1) using the sidecar totals file.

        Falls back to summing the full JSONL on first run (migration) and
        writes the total to the sidecar file for all future calls.
        """
        # Fast path: read the single-value sidecar
        if _TOTALS_FILE.exists():
            try:
                data = json.loads(_TOTALS_FILE.read_text(encoding="utf-8"))
                return float(data.get("total", 0.0))
            except Exception:
                pass
        # Slow path (first run / migration): sum the full JSONL, then persist
        total = sum(r.get("estimated_cost", 0) for r in self._load_all())
        self._write_total(total)
        return total

    @staticmethod
    def _write_total(total: float) -> None:
        """Persist the running total to the sidecar file."""
        try:
            _TOTALS_FILE.parent.mkdir(parents=True, exist_ok=True)
            _TOTALS_FILE.write_text(json.dumps({"total": total}), encoding="utf-8")
        except Exception:
            _logger.warning("Failed to persist cost total to sidecar file", exc_info=True)

    def get_stats(self) -> str:
        inp, out = self.get_session_tokens()
        cost = self.get_session_cost()
        total_cost = self.get_cumulative_cost()
        lines = [
            "[bold]Cost Tracking[/bold]",
            f"  Session tokens: {inp:,} in / {out:,} out",
            f"  Session cost: ${cost:.4f}",
            f"  Cumulative cost: ${total_cost:.4f}",
            f"  API calls this session: {len(self.records)}",
        ]
        return "\n".join(lines)

    def reset_cumulative(self) -> str:
        """Wipe the persistent costs.jsonl and reset session records."""
        self.records.clear()
        self._written_count = 0
        try:
            for f in (COST_FILE, _LEGACY_COST_FILE, _TOTALS_FILE):
                if f.exists():
                    f.unlink()
            return "Cumulative cost history cleared."
        except Exception as e:
            return f"Failed to clear cost file: {e}"

    def _append_new_records(self) -> None:
        """Append only new records to the JSONL file — O(1) per call."""
        new_records = self.records[self._written_count:]
        if not new_records:
            return
        COST_FILE.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._migrate_legacy_json_once()
            with COST_FILE.open("a", encoding="utf-8") as fh:
                for r in new_records:
                    fh.write(json.dumps(r.to_dict()) + "\n")
            self._written_count = len(self.records)
            # Keep running total sidecar in sync — O(1) increment
            new_cost = sum(r.estimated_cost for r in new_records)
            if new_cost:
                current = self.get_cumulative_cost()
                self._write_total(current + new_cost)
        except Exception:
            _logger.warning("Failed to persist cost records", exc_info=True)

    @staticmethod
    def _migrate_legacy_json_once() -> None:
        """One-time migration: convert costs.json → costs.jsonl."""
        if not _LEGACY_COST_FILE.exists() or COST_FILE.exists():
            return
        try:
            records = json.loads(_LEGACY_COST_FILE.read_text(encoding="utf-8"))
            with COST_FILE.open("w", encoding="utf-8") as fh:
                for r in records:
                    fh.write(json.dumps(r) + "\n")
            _LEGACY_COST_FILE.unlink()
        except Exception:
            _logger.warning("Failed to migrate legacy costs.json", exc_info=True)

    @staticmethod
    def _load_all() -> list[dict[str, Any]]:
        """Load all records from JSONL (plus legacy JSON if present)."""
        records: list[dict[str, Any]] = []
        # Legacy fallback — only present before first migration
        if _LEGACY_COST_FILE.exists() and not COST_FILE.exists():
            try:
                records = cast(list[dict[str, Any]], json.loads(_LEGACY_COST_FILE.read_text(encoding="utf-8")))
                return records
            except Exception:
                _logger.warning("Failed to load legacy cost records", exc_info=True)
                return []
        if COST_FILE.exists():
            try:
                with COST_FILE.open(encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if line:
                            records.append(json.loads(line))
            except Exception:
                _logger.warning("Failed to load cost records", exc_info=True)
        return records
