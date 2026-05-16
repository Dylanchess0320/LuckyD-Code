"""Effort-level CLI command — /effort."""

from rich.table import Table
from ..cli_utils import console
from ..router import apply_effort, EFFORT_SETTINGS, EFFORT_LABELS


def handle_effort_command(repl, args: list[str]) -> None:
    """/effort [low|normal|high|max] — get or set the effort level."""

    if not args:
        _show_effort(repl)
        return

    level = args[0].lower()
    result = apply_effort(repl.config, level)
    if result.startswith("Unknown"):
        console.print(f"[red]{result}[/red]")
        return

    icons = {"low": "⚡", "normal": "◎", "high": "◉", "max": "🔥"}
    icon = icons.get(level, "◎")
    console.print(f"[green]{icon} Effort set to {result}[/green]")
    console.print(
        f"[dim]max_tokens={repl.config.max_tokens}  "
        f"temperature={repl.config.temperature}  "
        f"tier_floor={EFFORT_SETTINGS[level][0]}[/dim]"
    )


def _show_effort(repl) -> None:
    """Display current effort level and all options."""
    current = getattr(repl.config, "effort", "normal")
    icons = {"low": "⚡", "normal": "◎", "high": "◉", "max": "🔥"}

    table = Table(title="Effort levels", title_style="bold cyan", box=None,
                  show_header=True, padding=(0, 2, 0, 0))
    table.add_column("", width=2)
    table.add_column("Level", style="cyan", no_wrap=True)
    table.add_column("Tier floor", style="dim")
    table.add_column("Max tokens", style="dim")
    table.add_column("Temp", style="dim")
    table.add_column("Description", style="white")

    descriptions = {
        "low":    "Fast & cheap — ideal for quick edits and Q&A",
        "normal": "Balanced — default for everyday coding tasks",
        "high":   "Reasoner — debugging, architecture, analysis",
        "max":    "Pro model always — large refactors, deep reviews",
    }

    for level, (tier_floor, max_tokens, temp) in EFFORT_SETTINGS.items():
        active = "→" if level == current else " "
        style = "bold green" if level == current else "white"
        table.add_row(
            f"[{style}]{active}[/{style}]",
            f"[{style}]{icons[level]} {level}[/{style}]",
            str(tier_floor),
            f"{max_tokens:,}",
            str(temp),
            descriptions[level],
        )

    console.print(table)
    console.print(f"\n[dim]Current: [cyan]{current}[/cyan] — use /effort <level> to change[/dim]")
