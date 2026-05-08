"""Handle /sessions commands."""


def handle_sessions_command(repl, args):
    """Handle /sessions list|save|load|delete commands."""
    from ..cli_utils import console
    from ..sessions import save_session, load_session, list_sessions, delete_session

    if not args:
        console.print("[yellow]Usage: /sessions list|save <name>|load <name>|delete <name>[/yellow]")
        return

    sub = args[0].lower()

    if sub == "list":
        result = list_sessions()
        console.print(result)

    elif sub == "save":
        name = " ".join(args[1:]) if len(args) > 1 else "unnamed"
        result = save_session(name, repl.context)
        console.print(f"[green]{result}[/green]")

    elif sub == "load":
        if len(args) < 2:
            console.print("[yellow]Usage: /sessions load <name>[/yellow]")
            return
        name = " ".join(args[1:])
        result = load_session(name, repl.context)
        console.print(f"[cyan]{result}[/cyan]")

    elif sub == "delete":
        if len(args) < 2:
            console.print("[yellow]Usage: /sessions delete <name>[/yellow]")
            return
        name = " ".join(args[1:])
        result = delete_session(name)
        console.print(f"[yellow]{result}[/yellow]")

    else:
        console.print(f"[red]Unknown: /sessions {sub}[/red]")
