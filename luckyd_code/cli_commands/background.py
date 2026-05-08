"""Handle /background commands."""


def handle_background_command(repl, args):
    """Handle /background start|status|result|list commands."""
    from ..cli_utils import console

    if not args:
        console.print("[yellow]Usage: /background start|status|result|list[/yellow]")
        return

    sub = args[0].lower()

    if sub == "start":
        task = " ".join(args[1:])
        if not task:
            console.print("[yellow]Usage: /background start <task description>[/yellow]")
            return
        task_id = repl.background.start_task(task)
        console.print(f"[green]Background task started:[/green] {task_id}")
        console.print(f"[dim]Check status: /background status {task_id}[/dim]")
        console.print(f"[dim]View result: /background result {task_id}[/dim]")

    elif sub == "status":
        if len(args) > 1:
            statuses = repl.background.get_status(args[1])
        else:
            statuses = repl.background.get_status()

        if not statuses:
            console.print("[yellow]No background tasks[/yellow]")
            return

        for s in statuses:
            status_color = {
                "pending": "yellow",
                "running": "cyan",
                "done": "green",
                "error": "red",
            }.get(s["status"], "dim")

            console.print(f"  [{status_color}]{s['id']}[/{status_color}] {s['status']}")
            console.print(f"    Task: {s['description']}")
            if s["result_preview"]:
                console.print(f"    Preview: {s['result_preview']}")

    elif sub == "result":
        if len(args) < 2:
            console.print("[yellow]Usage: /background result <task_id>[/yellow]")
            return
        result = repl.background.get_result(args[1])
        if result:
            console.print(result)
        else:
            statuses = repl.background.get_status(args[1])
            if statuses and statuses[0]:
                s = statuses[0]
                if s["status"] == "running":
                    console.print("[yellow]Task still running...[/yellow]")
                elif s["status"] == "error":
                    console.print(f"[red]Task failed: {s['error']}[/red]")
                else:
                    console.print("[yellow]No result yet[/yellow]")
            else:
                console.print("[red]Task not found[/red]")

    elif sub == "list":
        statuses = repl.background.get_status()
        if not statuses:
            console.print("[yellow]No background tasks[/yellow]")
            return
        console.print("[bold]Background Tasks:[/bold]")
        for s in statuses:
            status_color = {
                "pending": "yellow",
                "running": "cyan",
                "done": "green",
                "error": "red",
            }.get(s["status"], "dim")
            console.print(f"  [{status_color}]{s['id']}[/{status_color}] ({s['status']}) {s['description']}")

    else:
        console.print(f"[red]Unknown: /background {sub}[/red]")
