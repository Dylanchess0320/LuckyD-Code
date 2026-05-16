"""Token budget CLI command — /budget."""

from ..cli_utils import console


def handle_budget_command(repl, args: list[str]) -> None:
    """/budget [tokens] — get or set the per-turn output token cap."""

    if not args:
        _show_budget(repl)
        return

    raw = args[0].replace(",", "").replace("k", "000").replace("K", "000")
    try:
        tokens = int(raw)
    except ValueError:
        console.print(f"[red]Invalid value '{args[0]}'. Use a number e.g. /budget 2000[/red]")
        return

    if tokens < 256:
        console.print("[red]Minimum budget is 256 tokens.[/red]")
        return
    if tokens > 32000:
        console.print("[red]Maximum budget is 32000 tokens.[/red]")
        return

    repl.config.max_tokens = tokens
    repl.config.save()

    # Pick a label for context
    if tokens <= 1024:
        label = "minimal — very short responses"
    elif tokens <= 2048:
        label = "concise — good for quick edits"
    elif tokens <= 4096:
        label = "normal — balanced"
    elif tokens <= 8192:
        label = "extended — complex tasks"
    else:
        label = "max — long-form responses"

    console.print(f"[green]Budget set to {tokens:,} tokens[/green] [dim]({label})[/dim]")
    console.print("[dim]Takes effect on your next message.[/dim]")


def _show_budget(repl) -> None:
    current = repl.config.max_tokens
    console.print(f"[cyan]Current token budget:[/cyan] {current:,} tokens per turn")
    console.print()
    console.print("[dim]Presets:[/dim]")
    presets = [
        (512,   "minimal  — very short, fastest"),
        (1024,  "lean     — short answers"),
        (2048,  "concise  — quick edits and Q&A"),
        (4096,  "normal   — default balanced"),
        (8192,  "extended — debugging and analysis"),
        (16384, "max      — large refactors"),
    ]
    for tokens, label in presets:
        marker = " ←" if tokens == current else ""
        console.print(f"  [cyan]/budget {tokens:<6}[/cyan]  {label}{marker}")
    console.print()
    console.print("[dim]Use /budget <number> to change. Changes persist across sessions.[/dim]")
