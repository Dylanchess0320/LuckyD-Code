"""Tests for AuditDaemon.

Six cases that verify daemon behaviour without making any live API calls or
touching the real filesystem outside of tmp_path.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch


from luckyd_code.audit_daemon import AuditDaemon, _LOCK_FILE, _PAUSE_MARKER


# ------------------------------------------------------------------ #
#  Shared helpers
# ------------------------------------------------------------------ #

def _make_daemon(tmp_path: Path, api_key: str = "sk-test") -> AuditDaemon:
    """Return an AuditDaemon wired to tmp_path with a mock config."""
    config = MagicMock()
    config.api_key = api_key
    config.system_prompt = "You are a helpful assistant."
    config.model = "deepseek-v4-flash"
    return AuditDaemon(config, project_root=str(tmp_path), interval_minutes=1)


def _write_fake_history(daemon: AuditDaemon, value: float = 0.95) -> None:
    """Seed time_series.jsonl so audit() sees a non-empty history."""
    daemon._ts_file.parent.mkdir(parents=True, exist_ok=True)
    with daemon._ts_file.open("w", encoding="utf-8") as fh:
        import datetime
        ts = datetime.datetime.now().isoformat(timespec="seconds")
        for metric in ("test_pass_rate", "syntax_error_rate", "lint_issue_count", "todo_count"):
            fh.write(json.dumps({"timestamp": ts, "metric": metric, "value": value, "delta": 0.0}) + "\n")


# ------------------------------------------------------------------ #
#  Test 1 — first run collects baseline; no improvements attempted
# ------------------------------------------------------------------ #

def test_first_run_collects_baseline(tmp_path):
    """On first run (empty history) the daemon records metrics and returns
    skipped=False but improvements_attempted=0."""
    daemon = _make_daemon(tmp_path)

    mock_metrics = {
        "test_pass_rate": 1.0,
        "syntax_error_rate": 0.0,
        "lint_issue_count": 0.0,
        "todo_count": 2.0,
    }

    with patch.object(daemon, "_collect_metrics", return_value=mock_metrics), \
         patch.object(daemon, "_is_tree_clean", return_value=True):
        summary = daemon.audit()

    assert not summary["skipped"], f"Expected not skipped; got: {summary}"
    assert summary["improvements_attempted"] == 0
    assert summary["metrics"] == mock_metrics
    # Baseline must be persisted
    assert daemon._ts_file.exists()
    rows = [json.loads(line) for line in daemon._ts_file.read_text().splitlines() if line.strip()]
    assert len(rows) == len(mock_metrics)


# ------------------------------------------------------------------ #
#  Test 2 — audit skips when daemon is paused
# ------------------------------------------------------------------ #

def test_audit_skips_when_paused(tmp_path):
    """Touching the pause marker file causes audit() to skip immediately."""
    daemon = _make_daemon(tmp_path)
    (tmp_path / _PAUSE_MARKER).touch()

    summary = daemon.audit()

    assert summary["skipped"] is True
    assert "paused" in summary["skip_reason"].lower()


# ------------------------------------------------------------------ #
#  Test 3 — audit skips when API key is missing
# ------------------------------------------------------------------ #

def test_audit_skips_when_api_key_missing(tmp_path):
    """audit() must short-circuit with a clear skip reason when api_key is falsy."""
    daemon = _make_daemon(tmp_path, api_key="")

    summary = daemon.audit()

    assert summary["skipped"] is True
    assert "api" in summary["skip_reason"].lower() or "key" in summary["skip_reason"].lower()


# ------------------------------------------------------------------ #
#  Test 4 — audit skips when working tree is dirty
# ------------------------------------------------------------------ #

def test_audit_skips_when_dirty_tree(tmp_path):
    """A dirty git working tree must prevent the audit from running."""
    daemon = _make_daemon(tmp_path)

    with patch.object(daemon, "_is_tree_clean", return_value=False):
        summary = daemon.audit()

    assert summary["skipped"] is True
    assert "dirty" in summary["skip_reason"].lower()


# ------------------------------------------------------------------ #
#  Test 5 — lock file prevents a second concurrent daemon
# ------------------------------------------------------------------ #

def test_lock_prevents_concurrent_daemon(tmp_path):
    """If the lock file is held by a live process other than us, audit() skips.

    We write an arbitrary alien PID into the lock file, then mock os.kill so
    that signalling that PID succeeds (simulating a running process) on every
    platform — avoiding the Windows PermissionError that PID 1 would raise.
    """
    daemon = _make_daemon(tmp_path)
    lock_path = tmp_path / _LOCK_FILE

    alien_pid = os.getpid() + 9999
    lock_path.write_text(str(alien_pid), encoding="utf-8")

    with patch("luckyd_code.audit_daemon._pid_is_running", return_value=True), \
         patch.object(daemon, "_is_tree_clean", return_value=True), \
         patch.object(daemon, "_is_paused", return_value=False):
        summary = daemon.audit()

    assert summary["skipped"] is True
    assert "running" in summary["skip_reason"].lower() or "pid" in summary["skip_reason"].lower()


# ------------------------------------------------------------------ #
#  Test 6 — status() output contains all expected fields
# ------------------------------------------------------------------ #

def test_status_output_contains_expected_fields(tmp_path):
    """status() must mention interval, project path, and latest metrics."""
    daemon = _make_daemon(tmp_path)
    _write_fake_history(daemon)

    output = daemon.status()

    assert "interval" in output.lower()
    assert str(tmp_path) in output
    assert "test_pass_rate" in output
    assert "syntax_error_rate" in output
