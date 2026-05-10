"""
LuckyD Code Example — Parallel Orchestration
=============================================
Demonstrates the Coordinator's parallel_orchestrate() to split a task across
multiple specialized agents running concurrently.

This example takes a Python file and simultaneously:
  - Researcher: analyses the code for bugs, anti-patterns, and improvements
  - Tester:     writes pytest unit tests for the module
  - Reviewer:   produces a code review with line-specific feedback

All three agents run in parallel (ThreadPoolExecutor), then results are merged
into a single markdown report saved to disk.

Usage:
    python examples/parallel_code_review.py <path/to/your_module.py>

Requirements:
    pip install luckyd-code
    Set DEEPSEEK_API_KEY in your environment or .env file.
"""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv()


def run_parallel_review(target_file: str) -> None:
    """Run researcher, tester, and reviewer in parallel on a Python file."""
    from luckyd_code.config import Config
    from luckyd_code.orchestrator import Coordinator

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("Error: DEEPSEEK_API_KEY not set. Add it to your .env file.")
        sys.exit(1)

    if not os.path.exists(target_file):
        print(f"Error: file not found: {target_file}")
        sys.exit(1)

    config = Config()
    config.api_key = api_key
    config.base_url = "https://api.deepseek.com/v1"
    config.model = "deepseek-v4-flash"
    config.max_tokens = 4096
    config.temperature = 0.3
    config.system_prompt = "You are a senior software engineer."

    coordinator = Coordinator(config)

    abs_path = os.path.abspath(target_file)
    module_name = os.path.basename(target_file)

    print(f"🚀 Parallel code review: {module_name}")
    print("   Launching researcher + tester + reviewer simultaneously...\n")

    # Define the three parallel subtasks
    sub_tasks = [
        (
            "researcher",
            f"Analyse the Python file at {abs_path}. "
            "Read it fully, then identify: bugs, edge cases not handled, "
            "anti-patterns, performance issues, security concerns, and "
            "3–5 concrete improvement suggestions with examples.",
        ),
        (
            "tester",
            f"Read the Python file at {abs_path}. "
            "Write a complete pytest test suite covering the public API. "
            "Include: happy paths, edge cases, error conditions, and "
            "at least one parametrize decorator. "
            "Save tests to tests/test_{module_name}",
        ),
        (
            "reviewer",
            f"Do a thorough code review of {abs_path}. "
            "Structure your review as: Summary, Strengths, Issues (with line references), "
            "and Recommendations. Be specific and actionable.",
        ),
    ]

    # Run all three in parallel
    report = coordinator.parallel_orchestrate(
        task=f"Full code review of {module_name}",
        sub_tasks=sub_tasks,
    )

    # Save the combined report
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_file = f"review_{module_name}_{timestamp}.md"

    header = (
        f"# Code Review Report — {module_name}\n"
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"File: `{abs_path}`\n\n---\n\n"
    )

    with open(report_file, "w", encoding="utf-8") as f:
        f.write(header + report)

    print(f"\n\n✅ Report saved to: {report_file}")
    print(f"   Size: {os.path.getsize(report_file):,} bytes")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("--help", "-h"):
        print(__doc__)
        sys.exit(0 if "--help" in sys.argv or "-h" in sys.argv else 1)

    run_parallel_review(sys.argv[1])
