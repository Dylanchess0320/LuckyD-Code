"""Handle /config commands."""

import os

from .. import settings as cfg
from ..api import test_connection


def handle_config_command(repl, args):
    """Handle /config list|get|set commands."""
    from ..cli_utils import console

    if not args:
        console.print("[yellow]Usage: /config list|get|set[/yellow]")
        return

    sub = args[0].lower()

    if sub == "list":
        console.print("[bold]Provider:[/bold]")
        console.print(f"  [cyan]provider[/cyan] = {repl.config.provider}")
        console.print(f"  [cyan]model[/cyan] = {repl.config.model}")
        console.print(f"  [cyan]base_url[/cyan] = {repl.config.base_url}")
        console.print("[bold]Settings:[/bold]")
        settings = cfg.load_settings()
        for k, v in settings.items():
            console.print(f"  [cyan]{k}[/cyan] = {v}")

    elif sub == "get":
        if len(args) < 2:
            console.print("[yellow]Usage: /config get <key>[/yellow]")
            return
        settings = cfg.load_settings()
        val = settings.get(args[1], "[dim]not set[/dim]")
        console.print(f"[cyan]{args[1]}[/cyan] = {val}")

    elif sub == "set":
        if len(args) < 3:
            console.print("[yellow]Usage: /config set <key> <value>[/yellow]")
            return

        if args[1] == "provider":
            from ..config import _PROVIDER_URLS
            if args[2] not in _PROVIDER_URLS:
                valid = ", ".join(sorted(_PROVIDER_URLS.keys()))
                console.print(f"[red]Unknown provider '{args[2]}'. Valid: {valid}[/red]")
                return
            repl.config.provider = args[2]
            repl.config.base_url = _PROVIDER_URLS[args[2]]
            env_key = os.environ.get(f"{args[2].upper()}_API_KEY")
            if env_key:
                repl.config.api_key = env_key
            repl.config.save()
            console.print(f"[green]Switched provider to {args[2]}[/green]")
            console.print(f"[green]  base_url: {repl.config.base_url}[/green]")
            with console.status("Testing new API connection...", spinner="dots"):
                ok, msg = test_connection(repl.config.api_key, repl.config.base_url)
            if ok:
                console.print("[green]New connection OK[/green]")
            else:
                console.print(f"[red]New connection failed: {msg}[/red]")
            return

        if args[1] == "shell":
            valid = ("auto", "git_bash", "wsl", "cmd")
            if args[2] not in valid:
                console.print(f"[red]Shell must be one of: {', '.join(valid)}[/red]")
                return
            from ..tools.bash import reset_shell_cache
            reset_shell_cache()
            console.print(f"[green]Shell set to {args[2]}. Will take effect on next Bash command.[/green]")

        cfg.save_setting(args[1], args[2])
        console.print(f"[green]Set {args[1]} = {args[2]}[/green]")

    else:
        console.print(f"[red]Unknown: /config {sub}[/red]")
