"""Trend tracking — snapshot project metrics over time and analyze changes."""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .scanner import ProjectMetrics, scan_project


from .._data_dir import project_data_path


def _get_db_path() -> Path:
    """Get path to the analytics database file."""
    p = project_data_path("analytics.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


@dataclass
class TrendPoint:
    """A single snapshot in the trend history."""

    timestamp: float
    source_files: int
    total_lines: int
    total_code_lines: int
    total_todos: int
    total_fixmes: int
    total_functions: int
    total_classes: int
    avg_complexity: float
    health_score: float
    total_size_bytes: int
    languages: dict[str, int]

    @classmethod
    def from_metrics(cls, pm: ProjectMetrics) -> "TrendPoint":
        return cls(
            timestamp=pm.scanned_at,
            source_files=pm.source_files,
            total_lines=pm.total_lines,
            total_code_lines=pm.total_code_lines,
            total_todos=pm.total_todos,
            total_fixmes=pm.total_fixmes,
            total_functions=pm.total_functions,
            total_classes=pm.total_classes,
            avg_complexity=pm.avg_complexity,
            health_score=pm.health_score,
            total_size_bytes=pm.total_size_bytes,
            languages=dict(pm.files_by_language),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "source_files": self.source_files,
            "total_lines": self.total_lines,
            "total_code_lines": self.total_code_lines,
            "total_todos": self.total_todos,
            "total_fixmes": self.total_fixmes,
            "total_functions": self.total_functions,
            "total_classes": self.total_classes,
            "avg_complexity": self.avg_complexity,
            "health_score": self.health_score,
            "total_size_bytes": self.total_size_bytes,
            "languages": self.languages,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TrendPoint":
        return cls(
            timestamp=d["timestamp"],
            source_files=d["source_files"],
            total_lines=d["total_lines"],
            total_code_lines=d["total_code_lines"],
            total_todos=d["total_todos"],
            total_fixmes=d["total_fixmes"],
            total_functions=d["total_functions"],
            total_classes=d["total_classes"],
            avg_complexity=d["avg_complexity"],
            health_score=d["health_score"],
            total_size_bytes=d["total_size_bytes"],
            languages=d.get("languages", {}),
        )


@dataclass
class TrendReport:
    """Analysis of changes between two snapshots."""

    points: list[TrendPoint] = field(default_factory=list)
    delta_files: int = 0
    delta_lines: int = 0
    delta_todos: int = 0
    delta_fixmes: int = 0
    delta_health: float = 0.0
    delta_complexity: float = 0.0
    direction: str = ""  # "improving", "declining", "stable"
    summary: str = ""


class TrendTracker:
    """Track project metrics over time with snapshots."""

    def __init__(self):
        self.db_path = _get_db_path()
        self._points: list[TrendPoint] | None = None

    def load(self) -> list[TrendPoint]:
        """Load all snapshots from disk."""
        if self._points is not None:
            return self._points

        if self.db_path.exists():
            try:
                data = json.loads(self.db_path.read_text())
                self._points = [TrendPoint.from_dict(p) for p in data.get("snapshots", [])]
            except (json.JSONDecodeError, KeyError):
                self._points = []
        else:
            self._points = []

        return self._points

    def save(self, points: list[TrendPoint] | None = None):
        """Save snapshots to disk."""
        if points is not None:
            self._points = points

        if self._points is None:
            self._points = []

        data = {
            "snapshots": [p.to_dict() for p in self._points],
            "updated_at": time.time(),
        }
        self.db_path.write_text(json.dumps(data, indent=2))

    def snapshot(self) -> TrendPoint:
        """Take a snapshot of the current project state."""
        pm = scan_project()
        point = TrendPoint.from_metrics(pm)

        # Load existing
        points = self.load()
        points.append(point)
        self.save(points)

        return point

    def get_all(self) -> list[TrendPoint]:
        """Get all snapshots sorted by time."""
        return sorted(self.load(), key=lambda p: p.timestamp)

    def get_latest(self) -> TrendPoint | None:
        """Get the most recent snapshot."""
        points = self.get_all()
        if points:
            return points[-1]
        return None

    def compare(self, index_a: int = -2, index_b: int = -1) -> TrendReport:
        """Compare two snapshots by index (default: last two)."""
        points = self.get_all()

        if len(points) < 2:
            return TrendReport(
                points=points,
                direction="stable",
                summary="Not enough data for comparison (need at least 2 snapshots).",
            )

        a = points[index_a]
        b = points[index_b]

        report = TrendReport(
            points=[a, b],
            delta_files=b.source_files - a.source_files,
            delta_lines=b.total_code_lines - a.total_code_lines,
            delta_todos=b.total_todos - a.total_todos,
            delta_fixmes=b.total_fixmes - a.total_fixmes,
            delta_health=b.health_score - a.health_score,
            delta_complexity=b.avg_complexity - a.avg_complexity,
        )

        # Determine direction
        improvements = []
        declines = []

        if report.delta_todos < 0:
            improvements.append(f"TODOs decreased by {abs(report.delta_todos)}")
        elif report.delta_todos > 0:
            declines.append(f"TODOs increased by {report.delta_todos}")

        if report.delta_fixmes < 0:
            improvements.append(f"FIXMEs decreased by {abs(report.delta_fixmes)}")
        elif report.delta_fixmes > 0:
            declines.append(f"FIXMEs increased by {report.delta_fixmes}")

        if report.delta_complexity < -0.5:
            improvements.append(f"Avg complexity decreased ({report.delta_complexity:.1f})")
        elif report.delta_complexity > 0.5:
            declines.append(f"Avg complexity increased (+{report.delta_complexity:.1f})")

        if report.delta_health > 1:
            improvements.append(f"Health score improved (+{report.delta_health:.1f})")
        elif report.delta_health < -1:
            declines.append(f"Health score declined ({report.delta_health:.1f})")

        if report.delta_lines > 0:
            improvements.append(f"Codebase grew by {report.delta_lines:} lines")

        if not improvements and not declines:
            report.direction = "stable"
            report.summary = "No significant changes detected."
        elif len(improvements) >= len(declines):
            report.direction = "improving"
            report.summary = "Improvements: " + "; ".join(improvements)
            if declines:
                report.summary += " | Concerns: " + "; ".join(declines)
        else:
            report.direction = "declining"
            report.summary = "Concerns: " + "; ".join(declines)
            if improvements:
                report.summary += " | Improvements: " + "; ".join(improvements)

        return report

    def trend_summary(self) -> str:
        """Generate a human-readable trend summary."""
        points = self.get_all()
        if len(points) < 2:
            return "Not enough data for trends (take at least 2 snapshots)."

        first = points[0]
        last = points[-1]

        days_span = (last.timestamp - first.timestamp) / 86400

        lines = []
        lines.append("=== Project Trends ===")
        lines.append(f"Snapshots: {len(points)} over {days_span:.1f} days")
        lines.append("")

        # File count
        delta_files = last.source_files - first.source_files
        lines.append(f"Source files: {first.source_files} -> {last.source_files} ({delta_files:+d})")

        # Lines
        delta_lines = last.total_code_lines - first.total_code_lines
        lines.append(f"Code lines:   {first.total_code_lines:} -> {last.total_code_lines:} ({delta_lines:+})")

        # TODOs
        delta_todos = last.total_todos - first.total_todos
        lines.append(f"TODOs:        {first.total_todos} -> {last.total_todos} ({delta_todos:+d})")

        # FIXMEs
        delta_fixmes = last.total_fixmes - first.total_fixmes
        lines.append(f"FIXMEs:       {first.total_fixmes} -> {last.total_fixmes} ({delta_fixmes:+d})")

        # Health
        delta_health = last.health_score - first.health_score
        direction = "improving" if delta_health > 0 else "declining"
        lines.append(f"Health:       {first.health_score:.1f} -> {last.health_score:.1f} ({delta_health:+.1f}, {direction})")

        # Complexity
        delta_comp = last.avg_complexity - first.avg_complexity
        lines.append(f"Avg complexity: {first.avg_complexity:.1f} -> {last.avg_complexity:.1f} ({delta_comp:+.1f})")

        # Languages
        all_langs = set(list(first.languages.keys()) + list(last.languages.keys()))
        added = [lang for lang in all_langs if lang not in first.languages]
        removed = [lang for lang in all_langs if lang not in last.languages]
        if added:
            lines.append(f"Languages added: {', '.join(added)}")
        if removed:
            lines.append(f"Languages removed: {', '.join(removed)}")

        return "\n".join(lines)

    def clear(self):
        """Delete all snapshots."""
        self._points = []
        if self.db_path.exists():
            self.db_path.unlink()


# ── Convenience functions ───────────────────────────────────────────────────


def snapshot_project() -> TrendPoint:
    """Take a snapshot of the current project."""
    tracker = TrendTracker()
    return tracker.snapshot()


def get_trends() -> str:
    """Get a trend summary of the current project."""
    tracker = TrendTracker()
    return tracker.trend_summary()
