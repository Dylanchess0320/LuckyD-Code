"""Codebase Health & Analytics - scan, measure, report, and track code quality."""

from .scanner import CodebaseScanner, scan_project
from .reporter import ReportGenerator, generate_report
from .trends import TrendTracker, snapshot_project, get_trends
from .smells import SmellDetector, detect_smells

__all__ = [
    "CodebaseScanner",
    "scan_project",
    "ReportGenerator",
    "generate_report",
    "TrendTracker",
    "snapshot_project",
    "get_trends",
    "SmellDetector",
    "detect_smells",
]
