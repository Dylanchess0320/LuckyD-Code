"""Verification pipeline — multi-pass validation of code changes.

Runs after every file write/edit to ensure correctness before the agent
declares completion. The pipeline is:

  1. Syntax check (fast, always runs)
  2. Lint check (optional, configurable)
  3. Test suite (if applicable)
  4. Consistency check (project patterns)
  5. Task completeness gate

All verifications return a ``VerificationResult`` so the agent loop can
decide whether to fix-and-retry or proceed.
"""

from __future__ import annotations

import ast
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


# ------------------------------------------------------------------ #
#  Data model
# ------------------------------------------------------------------ #

@dataclass
class VerificationResult:
    """Outcome of running the verification pipeline."""

    passed: bool
    stage: str                   # "syntax" | "lint" | "test" | "consistency" | "task"
    message: str                 # human-readable result
    fix_hint: str | None = None  # what the model should do to fix it
    raw_output: str = ""         # full tool output for context
    duration_ms: float = 0.0

    def to_agent_feedback(self) -> str:
        """Format this result as a user message the agent can act on."""
        if self.passed:
            return f"[verify ✓] {self.stage} passed ({self.duration_ms:.0f}ms)"
        lines = [
            f"[verify ✗] {self.stage} FAILED:",
            f"  {self.message}",
        ]
        if self.fix_hint:
            lines.append(f"  Fix: {self.fix_hint}")
        if self.raw_output:
            lines.append(f"  ```\n{self.raw_output[:1500]}\n  ```")
        return "\n".join(lines)


# ------------------------------------------------------------------ #
#  Verification stages
# ------------------------------------------------------------------ #

def verify_syntax(file_path: str) -> VerificationResult:
    """Check Python syntax with py_compile."""
    import time
    t0 = time.time()
    try:
        import py_compile
        py_compile.compile(file_path, doraise=True)
        elapsed = (time.time() - t0) * 1000
        return VerificationResult(
            passed=True, stage="syntax", message="Syntax OK",
            duration_ms=elapsed,
        )
    except py_compile.PyCompileError as e:
        elapsed = (time.time() - t0) * 1000
        return VerificationResult(
            passed=False, stage="syntax",
            message=f"Syntax error in {file_path}",
            fix_hint=f"Fix the Python syntax error at {e}",
            raw_output=str(e),
            duration_ms=elapsed,
        )


def verify_lint(file_path: str, cwd: str | None = None, project_root: str | None = None) -> VerificationResult | None:
    """Run ruff/flake8 on the changed file. Returns None if no linter is available.

    Linters are invoked from *project_root* (when provided) so they pick up
    the project-level ``pyproject.toml`` / ``.flake8`` config instead of
    falling back to built-in defaults.
    """
    import time
    t0 = time.time()

    # Prefer project_root so linters find pyproject.toml / .flake8 config.
    # Fall back to the explicit cwd arg, then the file's parent directory.
    run_cwd = project_root or cwd or str(Path(file_path).parent)

    linters = [
        ("ruff", ["ruff", "check", file_path, "--output-format=concise"]),
        ("flake8", ["flake8", file_path, "--max-line-length=120"]),
    ]

    for name, cmd in linters:
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=run_cwd,
            )
            elapsed = (time.time() - t0) * 1000
            combined = (result.stdout + result.stderr).strip()
            if result.returncode == 0 and not combined:
                return VerificationResult(
                    passed=True, stage="lint",
                    message=f"{name}: no issues",
                    duration_ms=elapsed,
                )
            else:
                return VerificationResult(
                    passed=False, stage="lint",
                    message=f"{name} found issues in {file_path}",
                    fix_hint="Fix the lint issues listed above",
                    raw_output=combined[:2000],
                    duration_ms=elapsed,
                )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue

    return None  # no linter available — not a failure


def verify_consistency(file_path: str, project_root: str) -> VerificationResult | None:
    """Check that the file follows project conventions.

    Currently checks:
    - Imports follow project structure (no circular imports)
    - File uses same encoding/style as the project
    - Type hints are present (if project uses them)

    Returns None if no checks apply (not a failure).
    """
    import time
    t0 = time.time()

    p = Path(file_path)
    if not p.exists() or p.suffix != ".py":
        return None

    issues: list[str] = []

    try:
        tree = ast.parse(p.read_text(encoding="utf-8"))
    except SyntaxError:
        return None  # syntax check will catch this

    # Check for __init__.py imports that might actually cause circular imports
    # Only flag when a submodule import could form a true cycle:
    # e.g. __init__.py does "from .foo import Bar" and foo.py does "from . import Bar"
    # Simple imports in __init__.py are standard Python practice — not an issue.
    if p.name == "__init__.py":
        package_dir = p.parent
        module_name = p.parent.name
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module is not None:
                # Flag only if the imported submodule also imports from this package
                target = node.module
                if target.startswith("."):
                    # Should not happen (dots tracked by level), but handle gracefully
                    target = target.lstrip(".")
                # Resolve the actual module name.
                # level=0 → absolute import, level=1 → same package, level=2 → parent, etc.
                if node.level == 0:
                    # Absolute import — target is already a fully-qualified module name
                    target_module = target
                else:
                    parts = module_name.split(".")
                    base_parts = parts[:len(parts) - (node.level - 1)]
                    target_module = ".".join(base_parts + [target]) if base_parts else target
                # Check if the target module might import back from this package
                target_file = package_dir / (target_module.replace(".", os.sep) + ".py")
                if target_file.exists():
                    try:
                        target_tree = ast.parse(target_file.read_text(encoding="utf-8"))
                        for target_node in ast.walk(target_tree):
                            if isinstance(target_node, ast.ImportFrom):
                                if target_node.module and module_name in target_node.module:
                                    issues.append(
                                        f"Circular import detected: {p.name} imports from "
                                        f"'{target_module}' which also imports from '{module_name}'. "
                                        f"Consider lazy imports."
                                    )
                                    break
                    except (SyntaxError, OSError):
                        pass
                # do NOT break here — continue scanning remaining imports in __init__.py

    # Check for bare except clauses
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            if node.type is None:
                issues.append("Bare except: clause — replace with 'except Exception'")
            elif isinstance(node.type, ast.Tuple) or (
                isinstance(node.type, ast.Name) and node.type.id == "Exception"
            ):
                pass  # ok
            elif isinstance(node.type, ast.Name) and node.type.id == "BaseException":
                issues.append("Catching BaseException — use Exception instead")

    # Check for mutable default arguments
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for default in node.args.defaults + node.args.kw_defaults:
                if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                    issues.append(
                        f"Mutable default argument in {node.name}() — "
                        f"use None and set default in function body"
                    )

    elapsed = (time.time() - t0) * 1000

    if issues:
        return VerificationResult(
            passed=False, stage="consistency",
            message=f"Found {len(issues)} consistency issue(s)",
            fix_hint="\n".join(f"  • {i}" for i in issues),
            raw_output="\n".join(issues),
            duration_ms=elapsed,
        )
    return VerificationResult(
        passed=True, stage="consistency",
        message="No consistency issues found",
        duration_ms=elapsed,
    )


# ------------------------------------------------------------------ #
#  Full pipeline
# ------------------------------------------------------------------ #


def run_verify_pipeline(
    file_path: str,
    project_root: str,
    run_lint: bool = True,
    run_consistency: bool = True,
    run_tests: bool = False,
    test_runner_cmd: str | None = None,
) -> list[VerificationResult]:
    """Run all applicable verification stages on a file.

    Args:
        file_path: Absolute path to the file to verify.
        project_root: Project root for context.
        run_lint: If True, attempt lint check.
        run_consistency: If True, run AST-based consistency checks.
        run_tests: If True, run the project test suite.
        test_runner_cmd: Shell command to run tests.

    Returns:
        List of VerificationResult, one per stage that ran.
    """
    results: list[VerificationResult] = []
    import time

    # Stage 1: Syntax (always, mandatory)
    results.append(verify_syntax(file_path))

    # If syntax failed, skip remaining stages (file is broken)
    if not results[-1].passed:
        return results

    # Stage 2: Lint (optional, best-effort)
    if run_lint:
        lint_result = verify_lint(file_path, project_root=project_root)
        if lint_result is not None:
            results.append(lint_result)

    # Stage 3: Consistency (optional)
    if run_consistency:
        consistency_result = verify_consistency(file_path, project_root)
        if consistency_result is not None:
            results.append(consistency_result)

    # Stage 4: Tests (optional, run if requested)
    if run_tests and test_runner_cmd:
        # Allowlist check: only permit simple pytest / unittest invocations
        # to prevent shell injection if the command comes from settings or LLM.
        _allowed_runners = ("pytest", "python -m pytest", "python -m unittest", "tox", "uv run pytest")
        _cmd_stripped = test_runner_cmd.strip()
        if not any(_cmd_stripped.startswith(r) for r in _allowed_runners):
            results.append(VerificationResult(
                passed=False, stage="test",
                message=f"Blocked: test_runner_cmd '{_cmd_stripped[:80]}' is not an allowed test runner",
                fix_hint="Use pytest, python -m pytest, python -m unittest, tox, or uv run pytest",
            ))
            return results
        t0 = time.time()
        try:
            proc = subprocess.run(
                test_runner_cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=project_root,
            )
            elapsed = (time.time() - t0) * 1000
            combined = (proc.stdout + proc.stderr).strip()
            if proc.returncode == 0:
                results.append(VerificationResult(
                    passed=True, stage="test",
                    message="All tests passed",
                    raw_output=combined[:1000],
                    duration_ms=elapsed,
                ))
            else:
                results.append(VerificationResult(
                    passed=False, stage="test",
                    message=f"Tests failed (exit code {proc.returncode})",
                    fix_hint="Fix the failing tests before proceeding",
                    raw_output=combined[:3000],
                    duration_ms=elapsed,
                ))
        except subprocess.TimeoutExpired:
            results.append(VerificationResult(
                passed=False, stage="test",
                message="Test run timed out (120s)",
                fix_hint="Check for infinite loops or hanging tests",
                duration_ms=120000,
            ))
        except Exception as e:
            results.append(VerificationResult(
                passed=False, stage="test",
                message=f"Could not run tests: {e}",
                duration_ms=(time.time() - t0) * 1000,
            ))

    return results


def pipeline_all_passed(results: list[VerificationResult]) -> bool:
    """True if all mandatory stages passed."""
    for r in results:
        if not r.passed and r.stage in ("syntax", "test", "consistency"):
            return False
    return True


def pipeline_feedback(results: list[VerificationResult]) -> str:
    """Build a single feedback message from all verification results."""
    if not results:
        return ""
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    lines = [f"## Verification: {passed}/{total} passed\n"]
    for r in results:
        lines.append(r.to_agent_feedback())
    return "\n".join(lines)
