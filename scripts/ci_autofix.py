"""CI Autofix — runs after a pytest failure in GitHub Actions.

Reads pytest output from a file (written by the CI step), feeds it into
the autonomous fixer pipeline, and if the fix passes validation it commits
it and opens a PR.

Environment variables expected:
    AUTOFIX_API_KEY     - API key for the LLM provider
    AUTOFIX_BASE_URL    - Base URL (default: https://api.anthropic.com/v1)
    AUTOFIX_MODEL       - Model name (default: claude-sonnet-4-20250514)
    PYTEST_OUTPUT_FILE  - Path to file containing the captured pytest output
    GITHUB_TOKEN        - Injected automatically by Actions (used by gh CLI)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# ── configuration ──────────────────────────────────────────────────────────

API_KEY      = os.environ.get("AUTOFIX_API_KEY", "")
BASE_URL     = os.environ.get("AUTOFIX_BASE_URL", "https://api.anthropic.com/v1")
MODEL        = os.environ.get("AUTOFIX_MODEL", "claude-sonnet-4-20250514")
OUTPUT_FILE  = os.environ.get("PYTEST_OUTPUT_FILE", "pytest_output.txt")
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)

# ── helpers ────────────────────────────────────────────────────────────────

def _bail(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


def _read_pytest_output() -> str:
    path = Path(OUTPUT_FILE)
    if not path.exists():
        _bail(f"[autofix] pytest output file not found: {OUTPUT_FILE}")
    return path.read_text(encoding="utf-8")


def _build_error_data(pytest_output: str) -> dict[str, str]:
    """Convert raw pytest output into the dict format analyze_error expects."""
    import re, platform

    # Extract the short failure summary (everything from FAILURES onwards)
    failures_block = ""
    m = re.search(r"={3,} FAILURES ={3,}(.*)", pytest_output, re.DOTALL)
    if m:
        failures_block = m.group(1).strip()

    # Pull out the first test name + assertion as a terse error message
    first_fail = ""
    m2 = re.search(r"FAILED (.+?) - (.+)", pytest_output)
    if m2:
        first_fail = f"{m2.group(1)}: {m2.group(2)}"

    # Also grab coverage failure if present
    coverage_fail = ""
    m3 = re.search(r"(FAIL Required test coverage.+)", pytest_output)
    if m3:
        coverage_fail = m3.group(1)

    error_message = first_fail or coverage_fail or "pytest reported failures"
    traceback     = failures_block or pytest_output[-8000:]   # cap at 8 k chars

    return {
        "error_type":     "PytestFailure",
        "error_message":  error_message,
        "traceback":      traceback,
        "python_version": platform.python_version(),
        "os":             platform.system(),
    }


# ── main ───────────────────────────────────────────────────────────────────

def main() -> None:
    if not API_KEY:
        _bail("[autofix] AUTOFIX_API_KEY is not set — skipping autonomous fix.")

    print("[autofix] Reading pytest output …")
    pytest_output = _read_pytest_output()
    error_data    = _build_error_data(pytest_output)

    print(f"[autofix] Diagnosing: {error_data['error_message']}")

    # Add project root to sys.path so luckyd_code is importable without install
    sys.path.insert(0, PROJECT_ROOT)

    from luckyd_code.feedback_analyzer import analyze_error
    from luckyd_code.autonomous_fixer  import (
        generate_fix,
        apply_fix_in_worktree,
        validate_fix,
        create_pr,
        _git,
    )

    # ── Step 1: diagnose ──────────────────────────────────────────────────
    diagnosis = analyze_error(
        error_data,
        api_key=API_KEY,
        base_url=BASE_URL,
        model=MODEL,
        project_root=PROJECT_ROOT,
    )
    if not diagnosis:
        _bail("[autofix] LLM diagnosis failed — cannot continue.")

    print(f"[autofix] Root cause: {diagnosis.root_cause}")
    print(f"[autofix] Affected files: {diagnosis.affected_files}")
    print(f"[autofix] Confidence: {diagnosis.confidence}")

    if diagnosis.confidence == "low":
        print("[autofix] Confidence too low — skipping patch attempt.")
        sys.exit(0)

    # ── Step 2: generate patch ────────────────────────────────────────────
    print("[autofix] Generating patch …")
    diff = generate_fix(
        diagnosis,
        api_key=API_KEY,
        project_root=PROJECT_ROOT,
        base_url=BASE_URL,
        model=MODEL,
    )
    if not diff:
        _bail("[autofix] LLM returned no usable diff — skipping.")

    print("[autofix] Patch generated:")
    print(diff[:2000])

    # ── Step 3: apply in isolated worktree ────────────────────────────────
    print("[autofix] Applying patch in isolated git worktree …")
    worktree_path, branch_or_err = apply_fix_in_worktree(diff, PROJECT_ROOT)
    if not worktree_path:
        _bail(f"[autofix] Could not apply patch: {branch_or_err}")

    branch_name = branch_or_err
    print(f"[autofix] Worktree: {worktree_path}  branch: {branch_name}")

    # ── Step 4: validate ──────────────────────────────────────────────────
    print("[autofix] Running tests inside worktree …")
    passed, test_output = validate_fix(worktree_path, branch_name)
    print(test_output[-3000:])

    # Always clean up the temp worktree directory
    _git("worktree", "remove", "--force", worktree_path, cwd=PROJECT_ROOT)

    if not passed:
        # Delete the branch too — nothing worth keeping
        _git("branch", "-D", branch_name, cwd=PROJECT_ROOT)
        _bail("[autofix] Fixed patch did not pass tests — no PR created.")

    # ── Step 5: commit + open PR ─────────────────────────────────────────
    print("[autofix] Tests passed — creating pull request …")

    # Configure git identity for the Actions bot
    _git("config", "user.email", "github-actions[bot]@users.noreply.github.com", cwd=PROJECT_ROOT)
    _git("config", "user.name",  "github-actions[bot]", cwd=PROJECT_ROOT)

    pr_url = create_pr(
        branch_name=branch_name,
        diagnosis=diagnosis,
        diff=diff,
        test_passed=passed,
        test_output=test_output,
        project_root=PROJECT_ROOT,
    )

    if pr_url:
        print(f"[autofix] PR created: {pr_url}")
    else:
        print("[autofix] Could not push/create PR (no push access or gh CLI missing).")
        print(f"[autofix] Branch '{branch_name}' is ready locally — push it manually.")

    sys.exit(0)


if __name__ == "__main__":
    main()
