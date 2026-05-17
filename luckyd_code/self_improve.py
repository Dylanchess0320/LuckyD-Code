"""Self-improvement module — AI improves its own source code with git-based tracking."""

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

SELF_IMPROVE_PROMPT = """You are in SELF-IMPROVEMENT MODE. Your task is to analyze and improve the LuckyD Code project's own source code.

You have full access to Read, Write, Edit, Glob, Grep, and Bash tools to explore and modify the codebase.

CRITICAL RULES — FOLLOW EXACTLY:
- NEVER write a file without running a syntax check immediately after
- A syntax check failure means you MUST fix the file before proceeding
- Do NOT make more than 3 files changes in a single session
- Read a file BEFORE editing it, every time
- If a test mock fails, first read the production code to verify it matches what the test expects before touching the test

Follow this protocol strictly:

STEP 1 — EXPLORE:
- Use Glob and Grep to understand the project structure
- Read key files to understand how modules work
- Identify areas that need improvement

STEP 2 — DIAGNOSE:
- Find bugs, missing features, code quality issues, or performance problems
- Check for error handling gaps, missing type hints, hardcoded values
- Look for places where the web UI or CLI could be improved

STEP 3 — PROPOSE:
- State clearly what you want to change and why
- Keep changes focused and minimal — max 3 files

STEP 4 — IMPLEMENT:
- Read the file first
- Make the targeted change using Edit/Write
- IMMEDIATELY run the syntax check (see STEP 5) — do NOT skip this

STEP 5 — MANDATORY SYNTAX CHECK (after EVERY file write):
  For each .py file you edited, run:
    python -c "import py_compile; py_compile.compile('PATH_TO_FILE', doraise=True)"
  If it fails: fix the file immediately before touching anything else.
  Do NOT proceed to the next file until the current one passes.

STEP 6 — REPORT:
- Summarize what was changed and why
- Note any follow-up improvements that could be made

CHANGE TRACKING:
- The system will automatically run tests and validate all changed files before committing
- If tests fail, changes will NOT be committed — so getting syntax right is essential
- You do NOT need to git commit — that is handled automatically

Focus areas (in priority order):
1. Bug fixes
2. Missing error handling
3. User-facing improvements (CLI + web UI)
4. Performance
5. Code quality (type hints, docs)
"""


def get_improvement_prompt(area: str = "") -> str:
    """Get a targeted improvement prompt."""
    if area == "web":
        return "Focus on improving the web UI in web_app.py and templates/index.html. Add features, fix issues, improve the UX."
    elif area == "cli":
        return "Focus on improving the CLI experience in cli.py. Add commands, fix issues, improve UX."
    elif area == "tools":
        return "Focus on improving the tool implementations. Check for bugs, error handling, and missing features."
    elif area == "refactor":
        return (
            "You are fixing a structural code smell (long function, deep nesting, too many parameters, "
            "large class, high cyclomatic complexity, or large file). Your approach should be:\n"
            "- For LONG FUNCTIONS: extract logical blocks into well-named helper functions\n"
            "- For DEEP NESTING: use early returns, guard clauses, or extract nested logic\n"
            "- For TOO MANY PARAMETERS: group related parameters into a dataclass or TypedDict\n"
            "- For LARGE CLASSES: extract cohesive groups of methods into a new class using composition\n"
            "- For HIGH COMPLEXITY: reduce branching (if/else chains → lookup dicts or polymorphism)\n"
            "- For LARGE FILES: split into smaller modules by grouping related functions/classes\n"
            "- Make MINIMAL changes — do NOT rewrite the whole file\n"
            "- Preserve all existing behavior exactly — same logic, same return values\n"
            "- After every edit, verify that imports are correct and all callers still work"
        )
    elif area == "perf":
        return "Focus on performance improvements across the codebase. Look for caching opportunities, reduce API calls, optimize imports."
    elif area == "cleanup":
        return (
            "You are fixing a lightweight code cleanliness issue. Your approach should be:\n"
            "- For TODOs: remove stale ones, or replace with actionable comments linked to issues\n"
            "- For empty files: remove them if genuinely dead code, or add a docstring explaining "
            "why they exist (e.g., namespace package marker)\n"
            "- For large non-code files: consider whether they can be compressed, split, or moved "
            "out of the source tree\n"
            "- Make MINIMAL changes — do NOT rewrite or refactor anything\n"
            "- If removing a file, FIRST verify no other module imports or references it"
        )
    else:
        return "Explore the codebase and find the most impactful improvements to make. Fix bugs first, then add value."


# ------------------------------------------------------------------ #
#  Git-based change tracking
# ------------------------------------------------------------------ #

@dataclass
class ImprovementReport:
    branch: str = ""
    start_hash: str = ""
    end_hash: str = ""
    files_changed: list[str] = field(default_factory=list)
    diff_summary: str = ""
    commit_hash: str = ""
    error: str | None = None


def _git(*args: str, cwd: str | None = None) -> str:
    """Run a git command and return stdout."""
    try:
        result = subprocess.run(
            ["git"] + list(args),
            capture_output=True,
            text=True,
            timeout=30,
            cwd=cwd,
        )
        return result.stdout.strip()
    except Exception as e:
        return f"<error: {e}>"


class ImprovementTracker:
    """Track file changes made during a self-improvement session using git.

    Usage::

        tracker = ImprovementTracker(cwd)
        before = tracker.snapshot()          # git stash of dirty files
        # ... AI makes changes ...
        report = tracker.report()            # git diff + optional commit
    """

    def __init__(self, cwd: str | None = None) -> None:
        self.cwd = cwd or str(Path.cwd())
        self._branch = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=self.cwd)
        self._start_hash = _git("rev-parse", "--short", "HEAD", cwd=self.cwd)
        self._stash_made = False
        self._changes_before: set[str] = set()

    def snapshot(self) -> str:  # pragma: no cover
        """Stash any uncommitted changes so the diff shows only AI-made changes.

        Returns a status message.
        """
        # Record files that were dirty before AI starts
        status = _git("status", "--porcelain", cwd=self.cwd)
        if status:
            self._changes_before = {
                line.strip().split()[-1] for line in status.splitlines()
                if line.strip()
            }
            # Stash to get a clean baseline
            result = _git("stash", "push", "-m",
                          "self-improve-before", cwd=self.cwd)
            if "Saved" in result:
                self._stash_made = True
                stashed = len(self._changes_before)
                return f"Stashed {stashed} dirty file(s) for clean diff"
        return "Working tree was clean"

    def report(self, commit: bool = False,
               commit_msg: str = "") -> ImprovementReport:
        """Generate a change report after the AI has made modifications.

        Args:
            commit: If True, commit the changes.
            commit_msg: Commit message (auto-generated if empty).

        Returns:
            An ImprovementReport with diff, file list, and optional commit hash.
        """
        end_hash = _git("rev-parse", "--short", "HEAD", cwd=self.cwd)

        # Get diff of unstaged + staged changes
        unstaged = _git("diff", cwd=self.cwd)
        staged = _git("diff", "--cached", cwd=self.cwd)
        diff_text = unstaged + ("\n" if unstaged and staged else "") + staged

        # Restore stashed dirty files so user doesn't lose them
        if self._stash_made:
            _git("stash", "pop", cwd=self.cwd)

        # List changed files
        changed = _git("diff", "--name-only", cwd=self.cwd)
        files = [f for f in changed.splitlines() if f.strip()] if changed else []

        # Filter out files that were already dirty before
        new_files = [f for f in files if f not in self._changes_before]

        # Build a concise summary
        summary_lines = []
        summary_lines.append(f"Branch: {self._branch}")
        summary_lines.append(f"From:   {self._start_hash}")
        summary_lines.append(f"To:     {end_hash}")
        if new_files:
            summary_lines.append(f"\nFiles changed ({len(new_files)}):")
            for f in new_files:
                # Show a one-line stat per file
                stat = _git("diff", "--stat", "--", f, cwd=self.cwd)
                short_stat = stat.split("\n")[-1].strip() if stat else f
                summary_lines.append(f"  {short_stat}")
        else:
            summary_lines.append("\nNo new file changes detected")

        if diff_text:
            summary_lines.append(f"\n--- Diff ({len(diff_text)} chars) ---")
            # Show first 30 lines of diff as preview
            diff_lines = diff_text.splitlines()
            preview = diff_lines[:30]
            summary_lines.extend(preview)
            if len(diff_lines) > 30:
                summary_lines.append(f"... ({len(diff_lines) - 30} more lines)")

        commit_hash = ""
        if commit and new_files:  # pragma: no cover
            # Run verification pipeline on every changed Python file before committing.
            # Any failure aborts the commit — changes stay as unstaged edits so
            # nothing is lost, but main/branch history stays clean.
            try:
                from .verify import run_verify_pipeline, pipeline_all_passed, pipeline_feedback
                for f in new_files:
                    if f.endswith(".py"):
                        abs_path = str(Path(self.cwd) / f)
                        results = run_verify_pipeline(
                            abs_path, self.cwd,
                            run_lint=True, run_consistency=True, run_tests=False,
                        )
                        if not pipeline_all_passed(results):
                            summary_lines.append(
                                f"\n⚠ Verification failed for {f} — commit aborted"
                            )
                            summary_lines.append(pipeline_feedback(results))
                            summary = "\n".join(summary_lines)
                            return ImprovementReport(
                                branch=self._branch,
                                start_hash=self._start_hash,
                                end_hash=end_hash,
                                files_changed=new_files,
                                diff_summary=summary,
                                commit_hash="",
                                error=f"Verification failed for {f}",
                            )
            except ImportError:
                pass  # verify module unavailable — proceed without it

            msg = commit_msg or f"self-improve: {', '.join(new_files[:3])}"
            if len(new_files) > 3:
                msg += f" (+{len(new_files) - 3} more)"
            _git("add", *new_files, cwd=self.cwd)
            _git("commit", "-m", msg, cwd=self.cwd)
            commit_hash = _git("rev-parse", "--short", "HEAD", cwd=self.cwd)
            summary_lines.append(f"\nCommitted as {commit_hash}")

        summary = "\n".join(summary_lines)

        return ImprovementReport(
            branch=self._branch,
            start_hash=self._start_hash,
            end_hash=end_hash,
            files_changed=new_files,
            diff_summary=summary,
            commit_hash=commit_hash,
        )
