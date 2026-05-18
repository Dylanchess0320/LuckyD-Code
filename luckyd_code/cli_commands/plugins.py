"""Plugin management CLI command — /plugins."""

from typing import Any

from pathlib import Path
from rich.table import Table
from rich.panel import Panel
from ..cli_utils import console
from ..plugins import PLUGIN_DIR, discover_plugins, load_plugin


def handle_plugins_command(repl: Any, args: list[str]) -> None:
    """Handle /plugins [list|reload|dir|enable <name>]."""
    sub = args[0].lower() if args else "list"

    if sub == "list":
        _list_plugins(repl)

    elif sub == "dir":
        console.print(f"[cyan]Plugin directory:[/cyan] {PLUGIN_DIR}")
        if not PLUGIN_DIR.exists():
            console.print("[yellow]Directory does not exist yet — it will be created when you add your first plugin.[/yellow]")
            console.print(f"[dim]mkdir \"{PLUGIN_DIR}\"[/dim]")
        else:
            files = list(PLUGIN_DIR.glob("*.py"))
            console.print(f"[dim]{len(files)} plugin file(s) found[/dim]")

    elif sub == "reload":
        console.print("[yellow]Reloading plugins...[/yellow]")
        from ..plugins import load_all_plugins
        count = load_all_plugins(repl.registry)
        console.print(f"[green]Reloaded {count} plugin(s)[/green]")

    elif sub == "new":
        _scaffold_plugin(args[1] if len(args) > 1 else None)

    else:
        console.print("[yellow]Usage: /plugins [list|reload|dir|new <name>][/yellow]")
        console.print("[dim]  list    — show loaded plugins[/dim]")
        console.print("[dim]  reload  — hot-reload all plugins without restarting[/dim]")
        console.print("[dim]  dir     — show plugin directory path[/dim]")
        console.print("[dim]  new     — scaffold a new plugin file[/dim]")


def _list_plugins(repl: Any) -> None:
    """Display all discovered plugins and their registration status."""
    paths = discover_plugins()

    if not paths:
        console.print(Panel(
            f"No plugins found.\n\n"
            f"Plugin directory: [cyan]{PLUGIN_DIR}[/cyan]\n\n"
            f"Drop a [bold].py[/bold] file there with a [bold]register(registry)[/bold] function.\n"
            f"See [cyan]docs/PLUGINS.md[/cyan] or run [bold]/plugins new <name>[/bold] to scaffold one.",
            title="Plugins",
            border_style="yellow",
        ))
        return

    table = Table(title=f"Plugins ({len(paths)} found)", title_style="bold cyan")
    table.add_column("File", style="cyan", no_wrap=True)
    table.add_column("Status", style="white")
    table.add_column("Note", style="dim")

    for path in paths:
        reg = load_plugin(path)
        if reg is None:
            table.add_row(path.name, "[red]✗ failed[/red]", "No register() function or syntax error")
        else:
            table.add_row(path.name, "[green]✓ loaded[/green]", "")

    console.print(table)
    console.print(f"[dim]Plugin dir: {PLUGIN_DIR}[/dim]")
    console.print("[dim]Use /plugins reload to hot-reload after editing a plugin.[/dim]")


def _scaffold_plugin(name: str | None) -> None:
    """Write a starter plugin file to the plugin directory."""
    if not name:
        console.print("[yellow]Usage: /plugins new <plugin_name>[/yellow]")
        return

    slug = name.lower().replace(" ", "_").replace("-", "_")
    PLUGIN_DIR.mkdir(parents=True, exist_ok=True)
    dest = PLUGIN_DIR / f"{slug}.py"

    if dest.exists():
        console.print(f"[yellow]{dest} already exists — not overwriting.[/yellow]")
        return

    template = f'''"""LuckyD Code plugin: {name}

Drop this file in {PLUGIN_DIR} and run /plugins reload.
"""

from luckyd_code.tools.registry import Tool


class {slug.title().replace("_", "")}Tool(Tool):
    name = "{slug.title().replace("_", "")}"
    description = "Describe what your tool does in one sentence."
    parameters = {{
        "type": "object",
        "properties": {{
            "input": {{"type": "string", "description": "The input to process"}},
        }},
        "required": ["input"],
    }}

    def run(self, input: str = "") -> str:  # noqa: A002
        # Replace this with your actual logic
        return f"[{{{{self.name}}}}] You said: {{{{input}}}}"


def register(registry) -> None:
    """Called by LuckyD Code on startup — register your tools here."""
    registry.register({slug.title().replace("_", "")}Tool())
'''

    dest.write_text(template, encoding="utf-8")
    console.print(f"[green]Plugin scaffolded:[/green] {dest}")
    console.print("[dim]Edit the file, then run /plugins reload to activate it.[/dim]")
