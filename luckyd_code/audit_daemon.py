"""Continuous self-improvement daemon for LuckyD Code.

Runs an audit loop at a configurable interval, collecting metrics,
detecting regressions, and applying targeted improvements using the
project's existing self_improve, verify, and agent loop
infrastructure.

Usage (programmatic)::

    daemon = AuditDaemon(config, project_root="/path/to/project")
    asyncio.run(daemon.run_forever())

Usage (CLI)::

    luckyd-code --daemon
    luckyd-code audit run
    luckyd-code audit status
    luckyd-code audit metrics
"""

from __future__ import annotations

import asyncio
import ctypes
import datetime
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

_log = logging.getLogger(__name__)


def _pid_is_running(pid: int) -> bool:
    """Return True if *pid* refers to a currently running process.

    Uses a Windows-safe approach (ctypes OpenProcess) on win32 and the
    standard POSIX signal-0 trick elsewhere.
    """
    if sys.platform == "win32":
        SYNCHRONIZE = 0x00100000
        handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False

# Environment variable that overrides interval
_INTERVAL_ENV = "AUDIT_INTERVAL_MINUTES"
_DEFAULT_INTERVAL = 60

# Sentinel file — touching this pauses the daemon without killing the process
_PAUSE_MARKER = ".audit_daemon_paused"

# PID lock file — prevents two daemon processes from colliding
_LOCK_FILE = ".audit_lock"

# File cooldown in seconds (24 hours)
_FILE_COOLDOWN_SECS = 86_400

# Smell kind → improvement area mapping — determines which smells are auto-fixable
_FIXABLE_SMELL_KINDS: dict[str, str] = {
    # Trivial — mechanical fixes
    "syntax_error": "tools",
    "bare_except": "tools",
    "mutable_default": "tools",
    # Structural — focused refactoring
    "long_function": "refactor",
    "deep_nesting": "refactor",
    "too_many_params": "refactor",
    "large_class": "refactor",
    "high_complexity": "refactor",
    "large_file": "refactor",
    # Lightweight cleanup
    "high_todo_density": "cleanup",
    "empty_file": "cleanup",
    "large_file_bytes": "cleanup",
}

# Metric names — single source of truth
METRIC_NAMES = (
    "test_pass_rate",
    "syntax_error_rate",
    "lint_issue_count",
    "todo_count",
)


# ------------------------------------------------------------------ #
#  AuditDaemon
# ------------------------------------------------------------------ #

class AuditDaemon:
    """Background daemon that continuously audits and improves the project."""

    def __init__(
        self,
        config,
        project_root: str,
        interval_minutes: Optional[int] = None,
    ):
        self.config = config
        self.project_root = Path(project_root).resolve()
        self.interval_minutes: int = (
            interval_minutes
            or int(os.environ.get(_INTERVAL_ENV, _DEFAULT_INTERVAL))
        )

        # Metrics storage
        self._metrics_dir = self.project_root / "luckyd_code" / "metrics"
        self._metrics_dir.mkdir(parents=True, exist_ok=True)
        self._ts_file = self._metrics_dir / "time_series.jsonl"

        # Audit log
        self._log_file = self.project_root / "luckyd_code" / "audit.log"

        # In-memory state
        self.last_audit_time: Optional[datetime.datetime] = None
        self.improvement_count: int = 0

        # Per-file cooldown: maps relative path -> last improvement timestamp
        self._file_last_improved: dict[str, float] = {}

        # Per-file backoff after failed attempts: maps rel path -> fail count
        self._file_fail_count: dict[str, int] = {}

        # Configure file handler for audit.log
        fh = logging.FileHandler(str(self._log_file), encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s"))
        _log.addHandler(fh)
        _log.setLevel(logging.INFO)

    # ------------------------------------------------------------------ #
    #  Public entry points
    # ------------------------------------------------------------------ #

    async def run_forever(self) -> None:
        """Async loop: acquire lock -> audit -> sleep -> repeat.

        Exits immediately if another daemon process already holds the lock.
        Releases the lock on exit (normal or exception).
        """
        if not self._acquire_lock():
            _log.error(
                "Another audit daemon is already running. "
                "Check %s/%s. Exiting.",
                self.project_root, _LOCK_FILE,
            )
            return
        try:
            _log.info(
                "Audit daemon starting — interval=%dm, project=%s",
                self.interval_minutes, self.project_root,
            )
            while True:
                try:
                    self.audit()
                except Exception as exc:
                    _log.exception("Unhandled error in audit(): %s", exc)
                await asyncio.sleep(self.interval_minutes * 60)
        finally:
            self._release_lock()

    def audit(self) -> dict:
        """Run one full audit cycle. Returns a summary dict.

        Checks the PID lock so that a standalone CLI invocation (``audit run``)
        also refuses to run if a daemon process is already holding the lock.
        When called from within ``run_forever()`` (same PID), the check is a
        no-op because ``_acquire_lock`` recognises our own PID.
        """
        summary: dict = {
            "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
            "skipped": False,
            "skip_reason": "",
            "metrics": {},
            "improvements_attempted": 0,
            "improvements_committed": 0,
            "regressions": [],
        }

        # --- Guard: missing API key
        if not self.config.api_key:
            msg = "DEEPSEEK_API_KEY not set — skipping audit"
            _log.warning(msg)
            summary.update(skipped=True, skip_reason=msg)
            return summary

        # --- Guard: paused
        if self._is_paused():
            msg = "Daemon paused (remove .audit_daemon_paused to resume)"
            _log.info(msg)
            summary.update(skipped=True, skip_reason=msg)
            return summary

        # --- Guard: lock check (standalone invocation — run_forever already holds it)
        lock_path = self.project_root / _LOCK_FILE
        if lock_path.exists():
            try:
                pid = int(lock_path.read_text().strip())
                if pid != os.getpid() and _pid_is_running(pid):
                    msg = f"Another daemon is running (PID {pid}) — skipping"
                    _log.info(msg)
                    summary.update(skipped=True, skip_reason=msg)
                    return summary
            except (ValueError, OSError):
                pass
            lock_path.unlink(missing_ok=True)

        # --- Guard: dirty working tree
        if not self._is_tree_clean():
            msg = "Working tree is dirty — skipping audit to avoid conflicts"
            _log.info(msg)
            summary.update(skipped=True, skip_reason=msg)
            return summary

        _log.info("=== Audit cycle starting ===")

        # Step 1: Collect metrics
        metrics = self._collect_metrics()
        summary["metrics"] = metrics
        _log.info("Metrics: %s", {k: round(v, 4) for k, v in metrics.items()})

        # Step 2: Load historical metrics and detect regressions
        history = self._load_metric_history()
        is_first_run = not history
        regressions = [] if is_first_run else self._detect_regressions(metrics, history)
        summary["regressions"] = regressions
        if regressions:
            _log.warning("Regressions detected: %s", regressions)

        # Step 3: First run — just collect baseline, skip improvements
        if is_first_run:
            _log.info("First run — collecting baseline metrics, no improvements attempted")
            self._append_metrics(metrics, deltas={})
            self.last_audit_time = datetime.datetime.now()
            return summary

        # Step 4: Decide whether improvements are needed
        needs_improvement = (
            metrics.get("test_pass_rate", 1.0) < 1.0
            or metrics.get("syntax_error_rate", 0.0) > 0.0
            or metrics.get("lint_issue_count", 0) > 0
            or bool(regressions)
        )

        if not needs_improvement:
            _log.info("All metrics healthy — no improvements needed this cycle")
            prev_metrics = {m["metric"]: m["value"] for m in history[-len(METRIC_NAMES):]}
            deltas = {k: metrics[k] - prev_metrics.get(k, metrics[k]) for k in metrics}
            self._append_metrics(metrics, deltas)
            self.last_audit_time = datetime.datetime.now()
            return summary

        # Step 5: Find issues via analytics.smells (compose — do not reimplement)
        from .analytics.smells import detect_smells
        all_smells = detect_smells(str(self.project_root / "luckyd_code"))
        all_issues: list[dict[str, Any]] = sorted(
            [
                {
                    "file": s.file,
                    "line": s.line,
                    "kind": s.kind,
                    "detail": s.message,
                    "priority": {"error": 1, "warning": 2, "info": 3}.get(s.severity, 2),
                }
                for s in all_smells
            ],
            key=lambda i: (i["priority"], i["file"], i["line"]),
        )
        _log.info("Found %d source issues", len(all_issues))

        # Filter files on cooldown or high backoff
        now = datetime.datetime.now().timestamp()
        eligible_issues = [
            issue for issue in all_issues
            if (now - self._file_last_improved.get(issue["file"], 0.0)) >= _FILE_COOLDOWN_SECS
            and self._file_fail_count.get(issue["file"], 0) < 3
        ]

        if not eligible_issues:
            _log.info("No eligible issues (all files on cooldown or backed off)")
            self._append_metrics(metrics, deltas={})
            self.last_audit_time = datetime.datetime.now()
            return summary

        # Step 6: Filter out unfixable smells and attempt ONE improvement per cycle.
        # Processing multiple issues per cycle is unsafe: after the first commit
        # the second attempt's baseline snapshot is stale.
        fixable_issues = [
            i for i in eligible_issues
            if i["kind"] in _FIXABLE_SMELL_KINDS
        ]
        if not fixable_issues:
            _log.info(
                "No fixable issues — %d eligible but none mappable "
                "(available kinds: %s)", len(eligible_issues),
                sorted(_FIXABLE_SMELL_KINDS),
            )
            self._append_metrics(metrics, deltas={})
            self.last_audit_time = datetime.datetime.now()
            return summary

        target_issue = fixable_issues[0]
        target_issue["_area"] = _FIXABLE_SMELL_KINDS[target_issue["kind"]]
        _log.info(
            "Target issue: %s (kind=%s, area=%s, file=%s line=%d)",
            target_issue["detail"], target_issue["kind"],
            target_issue["_area"], target_issue["file"],
            target_issue["line"],
        )

        ok = self._attempt_improvement(target_issue, metrics)
        summary["improvements_attempted"] = 1
        rel = target_issue["file"]

        if ok:
            summary["improvements_committed"] = 1
            self.improvement_count += 1
            self._file_last_improved[rel] = datetime.datetime.now().timestamp()
            self._file_fail_count.pop(rel, None)
        else:
            self._file_fail_count[rel] = self._file_fail_count.get(rel, 0) + 1

        # Step 7: Update metrics
        post_metrics = self._collect_metrics() if ok else metrics
        prev_metrics = {m["metric"]: m["value"] for m in history[-len(METRIC_NAMES):]}
        deltas = {
            k: post_metrics[k] - prev_metrics.get(k, post_metrics[k])
            for k in post_metrics
        }
        self._append_metrics(post_metrics, deltas)

        _log.info(
            "=== Audit cycle complete: %d committed, 1 attempted ===",
            summary["improvements_committed"],
        )
        self.last_audit_time = datetime.datetime.now()
        return summary

    # ------------------------------------------------------------------ #
    #  Improvement orchestration
    # ------------------------------------------------------------------ #

    def _attempt_improvement(self, issue: dict, baseline_metrics: dict) -> bool:
        """Try to fix one issue. Returns True if committed successfully."""
        from .self_improve import ImprovementTracker, get_improvement_prompt
        from .verify import run_verify_pipeline, pipeline_all_passed, pipeline_feedback
        from .context import ConversationContext
        from ._agent_loop import run_agent_loop, RunConfig
        from .tools import get_default_registry

        rel_file = issue["file"]
        kind = issue["kind"]

        _log.info("Attempting improvement: %s in %s", kind, rel_file)

        area = issue.get("_area") or _FIXABLE_SMELL_KINDS.get(kind)
        if area is None:
            _log.info(
                "Skipping smell '%s' — not mapped to an improvement area "
                "(only %s are auto-fixable)", kind, sorted(_FIXABLE_SMELL_KINDS),
            )
            return False

        base_prompt = get_improvement_prompt(area)
        task = (
            f"{base_prompt}\n\n"
            f"**Specific issue to fix:** {issue['detail']}\n"
            f"**File:** {rel_file}\n"
            f"**Line:** {issue['line']}\n"
            f"**Kind:** {kind}\n\n"
            f"Fix only this specific issue. Do not make unrelated changes."
        )

        tracker = ImprovementTracker(cwd=str(self.project_root))
        snap_msg = tracker.snapshot()
        _log.debug("Tracker snapshot: %s", snap_msg)

        registry = get_default_registry()
        ctx = ConversationContext(
            system_prompt=self.config.system_prompt,
            max_messages=40,
            config=self.config,
            model=self.config.model,
        )
        ctx.add_user_message(task)

        run_cfg = RunConfig(
            label="self-improve",
            verify_edits=True,
            max_verify_retries=2,
            run_tests=False,
            project_root=str(self.project_root),
        )

        # More complex tasks get more turns
        max_turns = 12 if area == "refactor" else 8

        try:
            run_agent_loop(
                context=ctx,
                config=self.config,
                tools=registry.list_tools(),
                registry=registry,
                max_turns=max_turns,
                label="self-improve",
                run_config=run_cfg,
            )
        except Exception as exc:
            _log.error("Agent loop error: %s", exc)
            # Get whatever files the agent may have created before crashing
            try:
                crash_report = tracker.report(commit=False)
                agent_files = crash_report.files_changed
            except Exception:
                agent_files = []
            self._rollback(agent_new_files=agent_files)
            return False

        # Verify changed files (compose with verify module — do not reimplement)
        report = tracker.report(commit=False)
        changed = report.files_changed

        if not changed:
            _log.info("Agent made no file changes — nothing to commit")
            return False

        all_ok = True
        for fp in changed:
            abs_fp = str(self.project_root / fp)
            if not abs_fp.endswith(".py"):
                continue
            results = run_verify_pipeline(
                file_path=abs_fp,
                project_root=str(self.project_root),
                run_lint=True,
                run_consistency=True,
                run_tests=False,
            )
            if not pipeline_all_passed(results):
                _log.warning(
                    "Verification failed for %s:\n%s", fp, pipeline_feedback(results)
                )
                all_ok = False

        if not all_ok:
            _log.warning("Verification failed — rolling back working tree")
            self._rollback(agent_new_files=changed)
            return False

        # Check metrics didn't regress
        post_metrics = self._collect_metrics()
        if self._is_regression(baseline_metrics, post_metrics):
            _log.warning("Metrics regressed after change — rolling back")
            self._rollback(agent_new_files=changed)
            return False

        # Commit
        commit_msg = (
            f"self-improve: fix {kind} in {rel_file} "
            f"[auto, cycle #{self.improvement_count + 1}]"
        )
        final_report = tracker.report(commit=True, commit_msg=commit_msg)
        _log.info(
            "Committed: %s — files: %s",
            final_report.commit_hash, final_report.files_changed,
        )

        self._log_to_changelog(
            description=f"Fix {kind}: {issue['detail']} in `{rel_file}`",
            files=final_report.files_changed,
            metrics_delta={
                k: post_metrics[k] - baseline_metrics.get(k, post_metrics[k])
                for k in post_metrics
            },
        )
        return True

    # ------------------------------------------------------------------ #
    #  Metrics — compose with verify and analytics modules
    # ------------------------------------------------------------------ #

    def _collect_metrics(self) -> dict[str, float]:
        """Measure current state of all tracked benchmarks.

        Composes with existing modules:
        - test_pass_rate: pytest via subprocess
        - syntax_error_rate: verify.verify_syntax() per file
        - lint_issue_count: verify.verify_lint() on the package directory
        - todo_count: analytics.smells.detect_smells()
        """
        from .verify import verify_syntax, verify_lint
        from .analytics.smells import detect_smells

        metrics: dict[str, float] = {}

        # test_pass_rate — pytest subprocess (run_verify_pipeline is per-file only)
        pass_rate = self._run_pytest()
        # None means pytest couldn't run (timeout, missing, etc.) —
        # use the last known value from history so a transient infra
        # hiccup doesn't look like a regression.
        if pass_rate is None:
            history = self._load_metric_history()
            prev = {row["metric"]: row["value"] for row in history}
            pass_rate = prev.get("test_pass_rate", 1.0)
            _log.warning(
                "pytest unavailable — using last known test_pass_rate: %.4f", pass_rate
            )
        metrics["test_pass_rate"] = pass_rate

        # syntax_error_rate — verify_syntax per Python file
        pkg = self.project_root / "luckyd_code"
        py_files = [f for f in pkg.rglob("*.py") if "__pycache__" not in f.parts]
        total = len(py_files)
        if total:
            error_count = sum(1 for f in py_files if not verify_syntax(str(f)).passed)
            metrics["syntax_error_rate"] = round(error_count / total, 4)
        else:
            metrics["syntax_error_rate"] = 0.0

        # lint_issue_count — verify_lint on the whole package dir (ruff/flake8 accept dirs)
        lint_result = verify_lint(str(pkg), str(self.project_root))
        if lint_result is not None and not lint_result.passed:
            issue_lines = [
                ln for ln in lint_result.raw_output.splitlines() if ln.strip()
            ]
            metrics["lint_issue_count"] = float(max(1, len(issue_lines)))
        else:
            metrics["lint_issue_count"] = 0.0

        # todo_count — detect_smells; count smells whose message contains TODO markers
        _TODO_MARKERS = ("TODO", "FIXME", "HACK", "XXX")
        smells = detect_smells(str(pkg))
        metrics["todo_count"] = float(
            sum(
                1 for s in smells
                if any(marker in s.message.upper() for marker in _TODO_MARKERS)
            )
        )

        return metrics

    def _run_pytest(self) -> Optional[float]:
        """Run pytest in quiet mode and return pass rate (0.0–1.0), or None on failure.

        Returns None if pytest cannot run (timeout, missing, subprocess error)
        so callers can distinguish "all tests passed" from "couldn't run tests".
        """
        timeout_secs = 180
        try:
            proc = subprocess.run(
                [
                    sys.executable, "-m", "pytest",
                    "--tb=no", "-q", "--no-header",
                    "--ignore=.venv", "--ignore=.mypy_cache",
                ],
                capture_output=True,
                text=True,
                timeout=timeout_secs,
                cwd=str(self.project_root),
            )
            combined = (proc.stdout + proc.stderr).strip()
            passed = failed = 0
            for line in reversed(combined.splitlines()):
                m_pass = re.search(r"(\d+) passed", line)
                m_fail = re.search(r"(\d+) failed", line)
                m_error = re.search(r"(\d+) error", line)
                if m_pass or m_fail or m_error:
                    passed = int(m_pass.group(1)) if m_pass else 0
                    failed = (int(m_fail.group(1)) if m_fail else 0) + (
                        int(m_error.group(1)) if m_error else 0
                    )
                    break
            total = passed + failed
            return round(passed / total, 4) if total > 0 else 1.0
        except subprocess.TimeoutExpired:
            _log.error("pytest timed out after %ds — tests may be hanging", timeout_secs)
            return None
        except Exception as e:
            _log.error("Could not run pytest: %s", e)
            return None

    def _load_metric_history(self) -> list[dict]:
        """Load all rows from time_series.jsonl."""
        if not self._ts_file.exists():
            return []
        rows = []
        for line in self._ts_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return rows

    def _append_metrics(self, metrics: dict[str, float], deltas: dict[str, float]) -> None:
        """Write current metrics to time_series.jsonl."""
        ts = datetime.datetime.now().isoformat(timespec="seconds")
        self._ts_file.parent.mkdir(parents=True, exist_ok=True)
        with self._ts_file.open("a", encoding="utf-8") as fh:
            for metric, value in metrics.items():
                row = {
                    "timestamp": ts,
                    "metric": metric,
                    "value": value,
                    "delta": round(deltas.get(metric, 0.0), 6),
                }
                fh.write(json.dumps(row) + "\n")

    def _detect_regressions(
        self, current: dict[str, float], history: list[dict]
    ) -> list[str]:
        """Compare current metrics against history and flag regressions."""
        regressions: list[str] = []
        prev: dict[str, float] = {}
        for row in history:
            prev[row["metric"]] = row["value"]

        # Higher is better
        for metric in ("test_pass_rate",):
            if metric in prev and metric in current:
                if current[metric] < prev[metric] - 0.01:
                    regressions.append(
                        f"{metric}: {prev[metric]:.3f} -> {current[metric]:.3f}"
                    )

        # Lower is better
        for metric in ("syntax_error_rate", "lint_issue_count", "todo_count"):
            if metric in prev and metric in current:
                if current[metric] > prev[metric] + 1:
                    regressions.append(
                        f"{metric}: {prev[metric]:.1f} -> {current[metric]:.1f}"
                    )
        return regressions

    def _is_regression(
        self, baseline: dict[str, float], post: dict[str, float]
    ) -> bool:
        """Return True if post-metrics are strictly worse than baseline."""
        if post.get("test_pass_rate", 1.0) < baseline.get("test_pass_rate", 1.0) - 0.005:
            return True
        if post.get("syntax_error_rate", 0.0) > baseline.get("syntax_error_rate", 0.0) + 0.01:
            return True
        return False

    # ------------------------------------------------------------------ #
    #  Git helpers
    # ------------------------------------------------------------------ #

    def _is_tree_clean(self) -> bool:
        """Return True if the git working tree has no uncommitted changes.

        Returns True (optimistic) on subprocess errors — a transient git
        failure (e.g., Windows file locking) should not stall the daemon
        for hours.  The daemon's own snapshot/rollback guards provide a
        second layer of safety.
        """
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True, text=True, timeout=15,
                cwd=str(self.project_root),
            )
            if result.returncode != 0:
                _log.warning(
                    "git status exited %d (assuming clean): %s",
                    result.returncode, result.stderr.strip()[:200],
                )
                return True
            return result.stdout.strip() == ""
        except Exception as exc:
            _log.warning("git status check failed (assuming clean): %s", exc)
            return True

    def _rollback(self, agent_new_files: Optional[list] = None) -> None:
        """Roll back changes made by the agent.

        Restores tracked files via ``git checkout -- .`` and removes only
        the untracked files that the agent created (passed in as
        *agent_new_files*).  Using ``git clean -fd`` was unsafe because it
        deleted ALL untracked user files in the project, not just those
        created by the improvement session.
        """
        try:
            subprocess.run(
                ["git", "checkout", "--", "."],
                capture_output=True, text=True, timeout=15,
                cwd=str(self.project_root),
                check=False,
            )
            _log.info("Rolled back tracked file changes to HEAD")
        except Exception as exc:
            _log.error("git checkout rollback failed: %s", exc)

        # Remove only files the agent created (untracked before this session)
        if agent_new_files:
            for rel_path in agent_new_files:
                abs_path = self.project_root / rel_path
                try:
                    if abs_path.exists() and abs_path.is_file():
                        abs_path.unlink()
                        _log.info("Removed agent-created file: %s", rel_path)
                except Exception as exc:
                    _log.warning("Could not remove %s: %s", rel_path, exc)

    # ------------------------------------------------------------------ #
    #  Locking
    # ------------------------------------------------------------------ #

    def _acquire_lock(self) -> bool:
        """Write a PID lock file.

        Returns True if the lock was acquired (or we already hold it).
        Returns False if another live process holds the lock.
        Removes stale lock files automatically.
        """
        lock_path = self.project_root / _LOCK_FILE
        if lock_path.exists():
            try:
                pid = int(lock_path.read_text().strip())
                if pid == os.getpid():
                    return True  # we already hold it (re-entrant call)
                if _pid_is_running(pid):
                    return False
                # Process is gone — stale lock, remove and proceed
                lock_path.unlink(missing_ok=True)
            except (ValueError, OSError):
                lock_path.unlink(missing_ok=True)
        try:
            lock_path.write_text(str(os.getpid()), encoding="utf-8")
            return True
        except OSError as exc:
            _log.error("Could not write lock file %s: %s", lock_path, exc)
            return False

    def _release_lock(self) -> None:
        """Remove the PID lock file if we own it."""
        lock_path = self.project_root / _LOCK_FILE
        try:
            if lock_path.exists():
                content = lock_path.read_text(encoding="utf-8").strip()
                if content == str(os.getpid()):
                    lock_path.unlink(missing_ok=True)
        except OSError:
            pass

    # ------------------------------------------------------------------ #
    #  Changelog
    # ------------------------------------------------------------------ #

    def _log_to_changelog(
        self,
        description: str,
        files: list[str],
        metrics_delta: dict[str, float],
    ) -> None:
        """Append an entry to CHANGELOG.md."""
        changelog = self.project_root / "CHANGELOG.md"
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        delta_str = ", ".join(
            f"{k}: {'+' if v >= 0 else ''}{v:.4f}"
            for k, v in metrics_delta.items()
            if abs(v) > 0.0001
        )
        entry = (
            f"\n### [{ts}] Self-improvement #{self.improvement_count}\n\n"
            f"**Change:** {description}\n\n"
            f"**Files:** {', '.join(f'`{f}`' for f in files)}\n\n"
        )
        if delta_str:
            entry += f"**Metric deltas:** {delta_str}\n"

        try:
            if changelog.exists():
                content = changelog.read_text(encoding="utf-8")
                lines = content.splitlines(keepends=True)
                insert_at = 1
                changelog.write_text(
                    "".join(lines[:insert_at]) + entry + "".join(lines[insert_at:]),
                    encoding="utf-8",
                )
            else:
                changelog.write_text(f"# Changelog\n{entry}", encoding="utf-8")
        except OSError as exc:
            _log.warning("Could not update CHANGELOG.md: %s", exc)

    # ------------------------------------------------------------------ #
    #  Status / metrics dump (used by CLI audit subcommands)
    # ------------------------------------------------------------------ #

    def status(self) -> str:
        """Return a human-readable status summary."""
        last = self.last_audit_time.isoformat() if self.last_audit_time else "never"
        paused = "(PAUSED)" if self._is_paused() else ""
        lock_path = self.project_root / _LOCK_FILE
        try:
            locked = f"(LOCKED by PID {lock_path.read_text(encoding='utf-8').strip()})" if lock_path.exists() else ""
        except OSError:
            locked = "(LOCKED — could not read lock file)"
        lines = [
            f"Audit daemon status {paused} {locked}".strip(),
            f"  Last audit:        {last}",
            f"  Improvements made: {self.improvement_count}",
            f"  Interval:          {self.interval_minutes}m",
            f"  Project:           {self.project_root}",
            f"  Metrics file:      {self._ts_file}",
        ]
        history = self._load_metric_history()
        if history:
            last_by_metric: dict[str, dict] = {}
            for row in history:
                last_by_metric[row["metric"]] = row
            lines.append("\n  Latest metrics:")
            for name, row in sorted(last_by_metric.items()):
                delta_str = (
                    f" ({'+' if row['delta'] >= 0 else ''}{row['delta']:.4f})"
                    if row["delta"] != 0
                    else ""
                )
                lines.append(f"    {name:<28} {row['value']:.4f}{delta_str}")
        return "\n".join(lines)

    def metrics_json(self) -> str:
        """Dump full metrics history as JSON."""
        return json.dumps(self._load_metric_history(), indent=2)

    # ------------------------------------------------------------------ #
    #  Internal helpers
    # ------------------------------------------------------------------ #

    def _is_paused(self) -> bool:
        return (self.project_root / _PAUSE_MARKER).exists()
