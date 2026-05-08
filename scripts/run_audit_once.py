"""Standalone runner for one audit cycle.

Designed to be called by Windows Task Scheduler every hour.
Loads the project config, runs audit(), and logs the result.

Usage:
    .venv\Scripts\python.exe scripts\run_audit_once.py
"""

import sys
import os
from pathlib import Path

# Ensure the project root is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from luckyd_code.config import Config
from luckyd_code.audit_daemon import AuditDaemon


def main():
    """Run one audit cycle and exit."""
    # Change to project root so Config resolves .env correctly
    os.chdir(str(PROJECT_ROOT))
    config = Config()
    config.working_directory = str(PROJECT_ROOT)

    if not config.api_key:
        print("ERROR: DEEPSEEK_API_KEY not set — aborting audit", file=sys.stderr)
        sys.exit(1)

    daemon = AuditDaemon(config, project_root=str(PROJECT_ROOT))

    try:
        summary = daemon.audit()
    except Exception as exc:
        print(f"Audit failed: {exc}", file=sys.stderr)
        sys.exit(1)

    if summary.get("skipped"):
        print(f"SKIPPED: {summary['skip_reason']}")
        return

    metrics = summary.get("metrics", {})
    attempted = summary.get("improvements_attempted", 0)
    committed = summary.get("improvements_committed", 0)

    print(f"OK — {committed} committed, {attempted} attempted")
    for name, value in sorted(metrics.items()):
        print(f"  {name}: {value:.4f}")


if __name__ == "__main__":
    main()
