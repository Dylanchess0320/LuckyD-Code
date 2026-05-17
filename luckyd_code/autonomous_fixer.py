"""Autonomous Fixer - generates patches, validates them, and creates PRs.

Takes a Diagnosis from feedback_analyzer.py, generates a code fix via LLM,
applies it in a git worktree for isolation, runs the test suite, and
optionally creates a draft PR on GitHub.

All work is done locally. The user's API key is used for LLM calls.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import urllib.parse
import uuid
from dataclasses import dataclass
from pathlib import Path


from .feedback_analyzer import Diagnosis, _call_llm

FIX_SYSTEM_PROMPT = """You are a senior software engineer fixing a bug in the **LuckyD Code** project.

You will receive a diagnosis of a bug and the current source code of the affected files.
Generate the EXACT code change needed to fix the bug.

RULES:
- Only change LuckyD Code's own source code (luckyd_code/ or tests/)
- Make MINIMAL changes - fix the bug, nothing else
- Preserve all existing behavior
- Do NOT change imports unless absolutely necessary
- Output ONLY a unified diff (diff -u format)
- If multiple files need changes, include all diffs separated by "--- FILE ---"

Output format:
```diff
--- a/path/to/file.py
+++ b/path/to/file.py
@@ -line,count +line,count @@ context
-old line
+new line
```"""


@dataclass
class FixResult:
    """Result of an autonomous fix attempt."""
    diagnosis: Diagnosis
    success: bool
    branch_name: str = ""
    pr_url: str = ""
    diff: str = ""
    test_output: str = ""
    error: str = ""


def _git(*args: str, cwd: str | None = None) -> tuple[int, str, str]:
    """Run a git command, return (exit_code, stdout, stderr)."""
    try:
        r = subprocess.run(
            ["git"] + list(args),
            capture_output=True, text=True, timeout=30,
            cwd=cwd,
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except Exception as e:
        return -1, "", str(e)


def _read_file_safe(path: str, project_root: str) -> str:
    """Read a file, returning its contents or an error string.

    Enforces that the resolved path stays within *project_root* so a
    manipulated LLM response cannot read arbitrary files (e.g. ../../.env).
    """
    try:
        root = Path(project_root).resolve()
        full = (root / path).resolve()
        if not str(full).startswith(str(root) + os.sep) and full != root:
            return f"[BLOCKED: path '{path}' escapes project root]"
        if not full.exists():
            return f"[FILE NOT FOUND: {path}]"
        content = full.read_text(encoding="utf-8")
        lines = content.split("\n")
        if len(lines) > 300:
            content = "\n".join(lines[:300]) + f"\n... (truncated, {len(lines)} total lines)"
        return content
    except Exception as e:
        return f"[ERROR reading {path}: {e}]"


def generate_fix(
    diagnosis: Diagnosis,
    api_key: str,
    project_root: str = "",
    base_url: str = "https://api.deepseek.com/v1",
    model: str = "deepseek-v4-flash",
) -> str:
    """Generate a code fix for a diagnosed bug using LLM.

    Args:
        diagnosis: The Diagnosis from feedback_analyzer.
        api_key: API key for the configured provider.
        project_root: Project root directory.
        base_url: API base URL.
        model: Model to use.

    Returns:
        A unified diff string, or empty string on failure.
    """
    if not project_root:
        project_root = str(Path(__file__).resolve().parent.parent)

    # Read the affected files
    file_contents = ""
    for fpath in diagnosis.affected_files:
        content = _read_file_safe(fpath, project_root)
        file_contents += f"\n### {fpath}\n```python\n{content}\n```\n"

    if not file_contents:
        file_contents = "(No affected files could be read.)"

    user_message = f"""## Bug Diagnosis

**Error:** {diagnosis.error_type}: {diagnosis.error_message}
**Root Cause:** {diagnosis.root_cause}
**Suggested Fix:** {diagnosis.fix_suggestion}
**Confidence:** {diagnosis.confidence}

## Current Code{file_contents}

Generate the exact diff to fix this bug."""

    raw = _call_llm(
        system_prompt=FIX_SYSTEM_PROMPT,
        user_message=user_message,
        api_key=api_key,
        base_url=base_url,
        model=model,
    )

    if raw.startswith("ERROR:"):
        return ""

    return _extract_diff(raw)


def _extract_diff(llm_response: str) -> str:
    """Extract unified diff from an LLM response that may have markdown fences."""
    if not llm_response:
        return ""

    m = re.search(r'```diff\s*\n(.*?)```', llm_response, re.DOTALL)
    if m:
        return m.group(1).strip()

    m = re.search(r'```\s*\n(.*?)```', llm_response, re.DOTALL)
    if m and ('--- a/' in m.group(1) or '+++ b/' in m.group(1)):
        return m.group(1).strip()

    if '--- a/' in llm_response:
        return llm_response.strip()

    return ""


def apply_fix_in_worktree(  # pragma: no cover
    diff: str,
    project_root: str = "",
) -> tuple[str, str]:
    """Apply a diff in a real isolated git worktree (temp directory).

    Uses ``git worktree add`` so the user's working copy is NEVER touched.
    The fix is applied inside a throw-away directory in the system temp folder.

    Returns (worktree_path, branch_name) on success.
    Returns ("", error_message) on failure.
    """
    if not project_root:
        project_root = str(Path(__file__).resolve().parent.parent)

    if not diff:
        return "", "Empty diff - nothing to apply"

    # Check we're in a git repo
    exit_code, _, stderr = _git("rev-parse", "--is-inside-work-tree", cwd=project_root)
    if exit_code != 0:
        return "", f"Not in a git repository: {stderr}"

    worktree_id = uuid.uuid4().hex[:8]
    worktree_path = str(Path(tempfile.gettempdir()) / f"luckyd-autofix-{worktree_id}")
    branch_name = f"autofix/error-{worktree_id}"

    # Create a real isolated worktree in a temp directory on a new branch.
    # This leaves the user's working copy completely untouched.
    exit_code, _, stderr = _git(
        "worktree", "add", worktree_path, "-b", branch_name,
        cwd=project_root,
    )
    if exit_code != 0:
        return "", f"Failed to create git worktree: {stderr}"

    # Write the diff to a temp file and apply it inside the worktree
    diff_file = Path(tempfile.gettempdir()) / f"luckyd-fix-{worktree_id}.diff"
    diff_file.write_text(diff, encoding="utf-8")

    try:
        result = subprocess.run(
            ["git", "apply", str(diff_file)],
            capture_output=True, text=True, timeout=30,
            cwd=worktree_path,
        )
        if result.returncode != 0:
            # Try with --reject for partial application
            result2 = subprocess.run(
                ["git", "apply", "--reject", str(diff_file)],
                capture_output=True, text=True, timeout=30,
                cwd=worktree_path,
            )
            if result2.returncode != 0:
                # Clean up — nothing in the main repo was ever changed
                _git("worktree", "remove", "--force", worktree_path, cwd=project_root)
                _git("branch", "-D", branch_name, cwd=project_root)
                return "", f"Failed to apply diff: {result.stderr.strip()}"
    finally:
        diff_file.unlink(missing_ok=True)

    return worktree_path, branch_name


def validate_fix(  # pragma: no cover
    worktree_path: str,
    branch_name: str = "",
) -> tuple[bool, str]:
    """Run the verification pipeline on the fix.

    Args:
        worktree_path: Path to the git worktree where the diff was applied.
        branch_name: Kept for API compatibility, not used internally.

    Returns (passed, output_text).
    """
    results: list[str] = []

    # 1. Syntax-check changed files.
    # The diff is applied but NOT yet committed, so compare unstaged working
    # tree changes — not HEAD~1 which would compare two committed snapshots.
    exit_code, stdout, _ = _git("diff", "--name-only", cwd=worktree_path)
    changed_files = [f for f in stdout.split("\n") if f.endswith(".py") and f.strip()]

    if not changed_files:
        # Also check staged (pre-committed) changes
        exit_code, stdout, _ = _git("diff", "--name-only", "--cached", cwd=worktree_path)
        changed_files = [f for f in stdout.split("\n") if f.endswith(".py") and f.strip()]

    for fpath in changed_files:
        full = Path(worktree_path) / fpath
        if not full.exists():
            continue
        try:
            import py_compile
            py_compile.compile(str(full), doraise=True)
            results.append(f"  [OK] Syntax: {fpath}")
        except py_compile.PyCompileError as e:
            results.append(f"  [FAIL] Syntax: {fpath} - {e}")
            return False, "\n".join(results)

    # 2. Run test suite inside the worktree so the patched code is exercised
    results.append("  Running tests...")
    try:
        proc = subprocess.run(
            ["python", "-m", "pytest", "tests/", "-x", "--timeout=60", "-q"],
            capture_output=True, text=True, timeout=120,
            cwd=worktree_path,
        )
        combined = (proc.stdout + proc.stderr).strip()
        results.append(combined[-2000:] if len(combined) > 2000 else combined)
        if proc.returncode == 0:
            results.append("  [OK] All tests passed")
            return True, "\n".join(results)
        else:
            results.append(f"  [FAIL] Tests failed (exit {proc.returncode})")
            return False, "\n".join(results)
    except subprocess.TimeoutExpired:
        results.append("  [FAIL] Tests timed out (120s)")
        return False, "\n".join(results)
    except Exception as e:
        results.append(f"  [FAIL] Could not run tests: {e}")
        return False, "\n".join(results)


def create_pr(  # pragma: no cover
    branch_name: str,
    diagnosis: Diagnosis,
    diff: str,
    test_passed: bool,
    test_output: str,
    project_root: str = "",
) -> str:
    """Create a pull request via GitHub CLI or a pre-filled browser URL.

    Returns PR URL on success, or a pre-filled new-PR URL as fallback.
    """
    if not project_root:
        project_root = str(Path(__file__).resolve().parent.parent)

    test_badge = "[OK] tests passed" if test_passed else "[FAIL] tests failing"
    title = f"autofix: {diagnosis.error_type}: {diagnosis.error_message[:60]}"

    body = f"""## Autonomous Fix

{diagnosis.to_markdown()}

### Changes
```diff
{diff[:4000]}
```

### Validation
**Tests:** {test_badge}
```
{test_output[:2000]}
```

---
*Generated by LuckyD Code's autonomous self-improvement system.
Please review carefully before merging.*
"""

    # Try GitHub CLI first — only works if the user has push access to the repo
    # (i.e. the repo owner themselves). For regular users the push will fail
    # and we return "" so the diff flows into the issue body instead.
    try:
        exit_code, stdout, stderr = _git("push", "-u", "origin", branch_name, cwd=project_root)
        if exit_code != 0:
            # User doesn't have push access — not an error, just skip the PR.
            # The diff will be included in the GitHub issue body by the caller.
            return ""

        proc = subprocess.run(
            ["gh", "pr", "create",
             "--title", title,
             "--body", body,
             "--base", "main",
             "--head", branch_name,
             ],
            capture_output=True, text=True, timeout=30,
            cwd=project_root,
        )
        if proc.returncode == 0:
            pr_url = proc.stdout.strip()
            if pr_url:
                return pr_url
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    except Exception:
        pass

    return ""


def _pr_fallback_url(title: str, body: str, branch_name: str = "") -> str:
    """Build a pre-filled GitHub new-PR URL (no API needed)."""
    repo_path = "Dylanchess0320/LuckyD-Code"
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=5,
        )
        remote = result.stdout.strip()
        if "github.com" in remote:
            m = re.search(r'github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$', remote)
            if m:
                repo_path = m.group(1)
    except Exception:
        pass

    if len(body) > 60000:
        body = body[:60000] + "\n... (truncated)"

    q_title = urllib.parse.quote(title, safe="")
    q_body = urllib.parse.quote(body, safe="")
    # Use the actual branch name in the compare URL, not the PR title
    q_branch = urllib.parse.quote(branch_name, safe="") if branch_name else urllib.parse.quote(title[:50], safe="")

    return f"https://github.com/{repo_path}/compare/main...{q_branch}?expand=1&title={q_title}&body={q_body}"


def full_autonomous_pipeline(  # pragma: no cover
    exc: BaseException,
    api_key: str,
    project_root: str = "",
    base_url: str = "https://api.deepseek.com/v1",
    model: str = "deepseek-v4-flash",
    create_pr_flag: bool = False,
) -> FixResult:
    """Run the complete autonomous fix pipeline.

    Args:
        exc: The unhandled exception.
        api_key: API key for the configured provider.
        project_root: Project root.
        base_url: API base URL.
        model: LLM model.
        create_pr_flag: If True, create a PR on success.

    Returns:
        FixResult with full details.
    """
    from .feedback_analyzer import analyze_error

    if not project_root:
        project_root = str(Path(__file__).resolve().parent.parent)

    # Step 1: Diagnose
    diagnosis = analyze_error(exc, api_key, base_url, model, project_root)
    if not diagnosis:
        return FixResult(
            diagnosis=Diagnosis(
                error_type=type(exc).__name__,
                error_message=str(exc),
                root_cause="",
                affected_files=[],
                fix_suggestion="",
                confidence="low",
            ),
            success=False,
            error="LLM diagnosis failed",
        )

    # Step 2: Generate fix
    diff = generate_fix(diagnosis, api_key, project_root, base_url, model)
    if not diff:
        return FixResult(
            diagnosis=diagnosis,
            success=False,
            error="LLM fix generation failed",
        )

    # Step 3: Apply in an isolated worktree — user's working copy stays clean
    worktree_path, branch = apply_fix_in_worktree(diff, project_root)
    if not worktree_path:
        return FixResult(
            diagnosis=diagnosis,
            success=False,
            diff=diff,
            error=f"Failed to apply fix: {branch}",
        )

    # Step 4: Validate inside the worktree so the patched code is what's tested
    passed, test_output = validate_fix(worktree_path, branch)

    result = FixResult(
        diagnosis=diagnosis,
        success=passed,
        branch_name=branch,
        diff=diff,
        test_output=test_output,
    )

    # Step 5: Create PR if requested and tests passed
    if create_pr_flag and passed:
        result.pr_url = create_pr(branch, diagnosis, diff, passed, test_output, project_root)

    # Always tear down the temp worktree directory.
    # If validation failed, also delete the branch — nothing worth keeping.
    # If validation passed, keep the branch so the user can merge/push it.
    _git("worktree", "remove", "--force", worktree_path, cwd=project_root)
    if not passed and branch:
        _git("branch", "-D", branch, cwd=project_root)

    return result
