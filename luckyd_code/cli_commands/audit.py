"""Handler for /audit subcommands.

Subcommands
-----------
/audit run      — run one synchronous audit cycle immediately
/audit status   — print daemon status summary
/audit metrics  — dump full metrics history as JSONL
"""

from __future__ import annotations

import json
from typing import Any

from ..cli_utils import console


def handle_audit_command(repl: Any, args: list[str]) -> None:
    """Dispatch /audit <subcommand> [options]."""
    sub = args[0].lower() if args else "help"

    if sub == "run":
        _audit_run(repl)
    elif sub == "status":
        _audit_status(repl)
    elif sub == "metrics":
        _audit_metrics(repl)
    else:
        console.print(
            "[yellow]Usage:[/yellow] /audit run | status | metrics\n"
            "  [dim]run[/dim]     — trigger one audit cycle right now\n"
            "  [dim]status[/dim]  — show daemon state and latest metrics\n"
            "  [dim]metrics[/dim] — dump full JSONL metrics history"
        )


# ------------------------------------------------------------------ #
#  /audit run
# ------------------------------------------------------------------ #

def _audit_run(repl: Any) -> None:
    """Run one synchronous audit cycle in the foreground."""
    from pathlib import Path
    from ..audit_daemon import AuditDaemon

    project_root = str(repl.config.working_directory or Path.cwd())

    # Re-use a running daemon instance if available, otherwise create a
    # temporary one.  The temporary instance will respect the lock file and
    # bail out if the background daemon is already running.
    daemon: AuditDaemon = getattr(repl, "_audit_daemon", None) or AuditDaemon(
        repl.config, project_root=project_root
    )

    console.print("[dim]Running audit cycle...[/dim]")
    try:
        summary = daemon.audit()
    except Exception as exc:
        console.print(f"[red]Audit failed: {exc}[/red]")
        return

    if summary.get("skipped"):
        console.print(f"[yellow]Audit skipped:[/yellow] {summary['skip_reason']}")
        return

    metrics = summary.get("metrics", {})
    attempted = summary.get("improvements_attempted", 0)
    committed = summary.get("improvements_committed", 0)
    regressions = summary.get("regressions", [])

    console.print("[bold green]Audit complete[/bold green]")
    if metrics:
        for name, value in sorted(metrics.items()):
            console.print(f"  [cyan]{name:<28}[/cyan] {value:.4f}")
    if regressions:
        for r in regressions:
            console.print(f"  [red]⚠ regression:[/red] {r}")
    if attempted:
        status = "committed" if committed else "rolled back"
        console.print(f"  improvement: {status} ({attempted} attempted, {committed} committed)")


# ------------------------------------------------------------------ #
#  /audit status
# ------------------------------------------------------------------ #

def _audit_status(repl: Any) -> None:
    """Print human-readable daemon status."""
    from pathlib import Path
    from ..audit_daemon import AuditDaemon

    project_root = str(repl.config.working_directory or Path.cwd())
    daemon: AuditDaemon = getattr(repl, "_audit_daemon", None) or AuditDaemon(
        repl.config, project_root=project_root
    )

    console.print(daemon.status())


# ------------------------------------------------------------------ #
#  /audit metrics
# ------------------------------------------------------------------ #

def _audit_metrics(repl: Any) -> None:
    """Dump full metrics history as pretty-printed JSON."""
    from pathlib import Path
    from ..audit_daemon import AuditDaemon

    project_root = str(repl.config.working_directory or Path.cwd())
    daemon: AuditDaemon = getattr(repl, "_audit_daemon", None) or AuditDaemon(
        repl.config, project_root=project_root
    )

    raw = daemon.metrics_json()
    rows = json.loads(raw)
    if not rows:
        console.print("[yellow]No metrics recorded yet. Run /audit run to collect a baseline.[/yellow]")
        return

    console.print(f"[dim]{len(rows)} metric rows — most recent last[/dim]")
    console.print(raw)
