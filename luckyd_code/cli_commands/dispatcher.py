"""Command dispatcher for the CLI REPL.

All ``/command`` handlers live here so the Repl class stays focused on
chat-loop orchestration rather than CLI argument parsing.
"""

import sys
from pathlib import Path

from rich.markdown import Markdown
from rich.panel import Panel

from ..cli_utils import console
from .. import memory as memory_module
from .. import tasks, planner, init as project_init
from .. import update as updater
from ..skills import review as review_skill
from ..skills import security as security_skill

from .background import handle_background_command
from .sessions import handle_sessions_command
from .brain import handle_brain_command
from .config import handle_config_command
from .audit import handle_audit_command
from ..backup import create_backup, list_backups, restore_backup, format_backup_list


def handle_command(repl, cmd: str):
    """Dispatch a /command to the appropriate handler."""
    parts = cmd.split()
    command = parts[0].lower()
    args = parts[1:]

    if command in ("/exit", "/quit"):
        console.print("Goodbye!")
        sys.exit(0)

    elif command == "/stop":
        stopped_bg = 0
        if repl.background:
            for task in repl.background.tasks.values():
                if task.status in ("running", "pending"):
                    task.status = "stopped"
                    if not task.finished_at:
                        from datetime import datetime
                        task.finished_at = datetime.now().isoformat()
                    stopped_bg += 1
        if stopped_bg:
            console.print(f"[yellow]⏹ Stopped {stopped_bg} background task(s)[/yellow]")
        else:
            console.print("[dim]No background tasks running. Use Ctrl+C to stop a live response.[/dim]")

    elif command == "/clear":
        repl.context.reset()
        repl._load_memory()
        console.print("[cyan]Conversation reset.[/cyan]")

    elif command == "/backup":
        if args and args[0].lower() == "list":
            backups = list_backups(cwd=repl.config.working_directory)
            console.print(format_backup_list(backups))
        elif args and args[0].lower() == "restore":
            ref = args[1] if len(args) > 1 else "1"
            console.print(f"[yellow]Restoring backup {ref}...[/yellow]")
            result = restore_backup(ref, cwd=repl.config.working_directory)
            if result["ok"]:
                console.print(f"[green]{result['message']}[/green]")
            else:
                console.print(f"[red]Restore failed: {result['error']}[/red]")
        else:
            message = " ".join(args) if args else "manual backup"
            console.print("[yellow]Creating backup...[/yellow]")
            result = create_backup(message, cwd=repl.config.working_directory)
            if result["ok"]:
                console.print(f"[green]{result['message']}[/green]")
            else:
                console.print(f"[red]Backup failed: {result['error']}[/red]")

    elif command == "/deps":
        symbol = " ".join(args)
        if not symbol:
            console.print("[yellow]Usage: /deps <symbol_name>[/yellow]")
        else:
            from rich.table import Table
            deps = repl.brain.find_dependents(symbol)
            if deps:
                table = Table(title=f"Nodes that depend on '{symbol}'")
                table.add_column("Dependent", style="cyan")
                table.add_column("File", style="green")
                table.add_column("Relation", style="yellow")
                for d in deps:
                    table.add_row(d["name"], d["file"], d["relation"])
                console.print(table)
            else:
                console.print(f"[dim]No dependents found for '{symbol}' in the knowledge graph.[/dim]")

    elif command == "/help":
        from rich.table import Table

        def _cmd_table(title: str, cmds: list[tuple[str, str]], style: str = "cyan") -> Table:
            t = Table(title=title, title_style=f"bold {style}", box=None,
                      show_header=False, padding=(0, 2, 0, 0))
            t.add_column("Cmd", style=style, no_wrap=True)
            t.add_column("Desc", style="white")
            for cmd, desc in cmds:
                t.add_row(cmd, desc)
            return t

        # ── Commands ──────────────────────────────────────────────
        console.print()
        console.print("[bold]╭─ Commands[/bold]")
        console.print("[bold]│[/bold]")

        sections = [
            ("Chat", [
                ("/help", "Show this help"),
                ("/clear", "Reset conversation"),
                ("/stop", "Stop background tasks (Ctrl+C to stop live response)"),
                ("/compact", "Compact conversation history"),
                ("/undo", "Undo last file write/edit"),
                ("/model", "Show current model settings"),
                ("/tokens", "Show message count"),
                ("/stats", "Show message stats (counts, chars)"),
                ("/cost", "Show session & cumulative cost"),
                ("/cost reset", "Clear cumulative cost history"),
                ("/version", "Show version"),
                ("/exit", "Exit (or Ctrl+D)"),
            ]),
            ("Export & Backup", [
                ("/export md [file]", "Export conversation as Markdown"),
                ("/export html [file]", "Export conversation as HTML"),
                ("/backup", "Git snapshot (auto before /debug, /self-improve)"),
                ("/backup list", "List recent backups"),
                ("/backup restore [#]", "Restore project to a backup"),
            ]),
            ("Config", [
                ("/config list", "Show all settings"),
                ("/config get <key>", "Get a setting value"),
                ("/config set <key> <value>", "Set a setting value"),
            ]),
            ("Memory & Sessions", [
                ("/memory", "Show project memory (MEMORY.md)"),
                ("/memory save <name>", "Save conversation to memory"),
                ("/memory search <query>", "Search persistent memories"),
                ("/memory list", "List all memories"),
                ("/memory delete <name>", "Delete a memory"),
                ("/init", "Create MEMORY.md"),
                ("/sessions list", "List saved conversations"),
                ("/sessions save <name>", "Save conversation"),
                ("/sessions load <name>", "Load conversation"),
                ("/sessions delete <name>", "Delete session"),
            ]),
            ("Models & Routing", [
                ("/models", "List available models by tier"),
                ("/models set <id>", "Switch to a specific model"),
                ("/route <text>", "Show routing decision for input"),
            ]),
            ("Agents & Automation", [
                ("/debug", "Auto debug loop (test → fix → re-run)"),
                ("/orchestrate <task>", "Researcher → coder → reviewer pipeline"),
                ("/background start <task>", "Run task in background"),
                ("/background status [id]", "Check background task status"),
                ("/background result <id>", "View background task result"),
                ("/background list", "List all background tasks"),
            ]),
            ("Knowledge Graph", [
                ("/brain", "Show knowledge graph status"),
                ("/brain rebuild", "Re-index Python files into graph"),
                ("/brain stats", "Detailed graph statistics"),
                ("/index", "Re-index project structure"),
                ("/deps <symbol>", "Find dependents of a symbol"),
                ("/watch start", "Auto-reindex on file changes"),
                ("/watch stop", "Stop file watcher"),
                ("/watch status", "Show file watcher state"),
            ]),
            ("Tasks & Git", [
                ("/tasks", "List tasks"),
                ("/plan", "List saved plans"),
                ("/plan <task>", "Draft → approve → execute (interactive)"),
                ("/parallel <task>", "Decompose & run subtasks concurrently"),
                ("/branch <task>", "Create & checkout a task branch"),
                ("/finish [--pr]", "Commit all changes + optional PR"),
            ]),
            ("Skills & Tools", [
                ("/review", "Review git changes"),
                ("/security-review", "Run security analysis"),
                ("/sandbox status", "Check Docker sandbox availability"),
                ("/allow <tool>", "Allow a tool without confirmation"),
                ("/update", "Update LuckyD Code"),
            ]),
        ]

        for title, cmds in sections:
            console.print(_cmd_table(title, cmds))
            console.print()

        # ── Tools ────────────────────────────────────────────────
        console.print("[bold]╭─ Tools[/bold]")
        console.print("[bold]│[/bold]")

        builtin_tools = repl.registry.list_tools()
        mcp_tools = repl.mcp.get_all_tools()
        total_count = len(builtin_tools) + len(mcp_tools)

        # Build name→description lookup
        name_to_desc = {}
        for t in builtin_tools:
            name_to_desc[t["function"]["name"]] = t["function"]["description"]

        tool_categories = {
            "📁 Files": ["Read", "Write", "Edit", "Glob", "Grep"],
            "💻 Shell": ["Bash"],
            "🕐 Date/Time": ["DateTime"],
            "🌐 Web": ["WebFetch", "WebSearch"],
            "🔧 Git": ["GitStatus", "GitDiff", "GitLog", "GitCommit", "GitAdd",
                       "GitBranch", "GitPR", "GitPush", "GitWorktree"],
            "🤖 Agents": ["SubAgent", "AgentHandoff"],
            "🧠 Codebase": ["BrainSearch", "BrainStatus"],
            "🌍 Browser": ["BrowserNavigate", "BrowserClick", "BrowserType",
                          "BrowserSnapshot", "BrowserScreenshot", "BrowserEvaluate",
                          "BrowserClose", "OpenInBrowser"],
        }

        for cat_name, tool_names in tool_categories.items():
            visible = [n for n in tool_names if n in name_to_desc]
            if not visible:
                continue
            rows = []
            for name in visible:
                desc = name_to_desc.get(name, "")
                if len(desc) > 100:
                    desc = desc[:100] + "…"
                rows.append((f"`{name}`", desc))
            cat_table = _cmd_table(cat_name, rows, style="green")
            console.print(cat_table)
            console.print()

        if mcp_tools:
            mcp_rows = []
            for t in mcp_tools:
                name = t["function"]["name"]
                desc = t["function"].get("description", "")[:80]
                mcp_rows.append((f"`{name}`", desc))
            console.print(_cmd_table(f"🔌 MCP Tools ({len(mcp_tools)})", mcp_rows, style="magenta"))
            console.print()

        console.print(f"[dim]Total: {total_count} tools[/dim]")
        console.print("[dim]Enter to submit · Alt+Enter for newline[/dim]")
        console.print()

    elif command == "/model":
        if args and args[0] == "list":
            repl._handle_model_list()
            return
        provider_str = f" ({repl.config.provider})" if repl.config.provider != "deepseek" else ""
        console.print(f"[cyan]Model:[/cyan] {repl.config.model}{provider_str}")
        console.print(f"[cyan]Provider:[/cyan] {repl.config.provider}")
        console.print(f"[cyan]Temperature:[/cyan] {repl.config.temperature}")
        console.print(f"[cyan]Max tokens:[/cyan] {repl.config.max_tokens}")
        console.print(f"[cyan]API Base:[/cyan] {repl.config.base_url}")
        console.print(f"[cyan]Context messages:[/cyan] {repl.context.count_messages()}")

    elif command == "/models":
        from ..model_registry import format_model_list
        if args and args[0] == "set":
            new_model = " ".join(args[1:])
            if new_model:
                repl.config.model = new_model
                repl.config.save()
                console.print(f"[green]Model set to: {new_model}[/green]")
            else:
                console.print("[yellow]Usage: /models set <model_id>[/yellow]")
        else:
            console.print(format_model_list())
            console.print(f"\n[cyan]Current model:[/cyan] {repl.config.model}")
            console.print("[dim]Use /models set <model_id> to switch[/dim]")

    elif command == "/route":
        from ..router import show_current_routing
        if args:
            sample = " ".join(args)
            info = show_current_routing(sample, 0, repl.config.model)
            console.print(Panel(info, title=f"Routing for: {sample[:50]}", border_style="cyan"))
        else:
            console.print("[yellow]Usage: /route <text>[/yellow]")
            console.print("[dim]Example: /route fix this bug in auth.py[/dim]")

    elif command == "/tokens":
        console.print(f"Messages in context: {repl.context.count_messages()}")

    elif command == "/version":
        console.print(f"LuckyD Code v{updater.get_version()}")

    elif command == "/compact":
        console.print("[yellow]Compacting conversation...[/yellow]")
        result = repl.context.compact(
            repl.config, repl.config.model,
            on_compact=lambda s, c: repl.memory_mgr.save_conversation_summary(s, c),
        )
        console.print(f"[green]{result}[/green]")

    elif command == "/cost":
        if args and args[0].lower() == "reset":
            result = repl.cost_tracker.reset_cumulative()
            console.print(f"[green]{result}[/green]")
        else:
            console.print(repl.cost_tracker.get_stats())
            console.print("[dim]Use /cost reset to clear cumulative history[/dim]")

    elif command == "/stats":
        total = repl.context.count_messages()
        user_msgs = sum(1 for m in repl.context.messages if m["role"] == "user")
        asst_msgs = sum(1 for m in repl.context.messages if m["role"] == "assistant")
        tool_msgs = sum(1 for m in repl.context.messages if m["role"] == "tool")
        total_chars = sum(len(str(m.get("content", ""))) for m in repl.context.messages)
        console.print(f"[cyan]Messages:[/cyan] {total} ({user_msgs} user, {asst_msgs} assistant, {tool_msgs} tool)")
        console.print(f"[cyan]Total chars:[/cyan] {total_chars:,}")
        console.print(f"[cyan]Model:[/cyan] {repl.config.model}")
        console.print(f"[cyan]Temperature:[/cyan] {repl.config.temperature}")

    elif command == "/config":
        handle_config_command(repl, args)

    elif command == "/export":
        if not args:
            console.print("[yellow]Usage: /export md|html [filepath][/yellow]")
            return
        fmt = args[0].lower()
        filepath = None
        if len(args) > 1:
            filepath = " ".join(args[1:])
        else:
            from datetime import datetime
            desktop = Path.home() / "OneDrive" / "Desktop"
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            ext = "md" if fmt == "md" else "html"
            filepath = str(desktop / f"deepseek_export_{ts}.{ext}")
        if fmt == "md":
            from ..export import export_markdown
            result = export_markdown(repl.context.messages, filepath)
            if filepath:
                console.print(f"[green]Exported to {filepath}[/green]")
            else:
                console.print(result)
        elif fmt == "html":
            from ..export import export_html
            result = export_html(repl.context.messages, filepath)
            if filepath:
                console.print(f"[green]Exported to {filepath}[/green]")
            else:
                console.print(result[:2000])
        else:
            console.print(f"[red]Unknown format: {fmt}. Use md or html.[/red]")

    elif command == "/update":
        console.print("[yellow]Checking for updates...[/yellow]")
        result = updater.do_update()
        console.print(f"[green]{result}[/green]")

    elif command == "/memory":
        if not args:
            md = memory_module.load_claude_md()
            if md:
                console.print(Panel(md, title="Project Memory (MEMORY.md)", border_style="cyan"))
            else:
                console.print("[yellow]No MEMORY.md found[/yellow]")
            return

        sub = args[0].lower()
        if sub == "save":
            name = " ".join(args[1:]) if args[1:] else "unnamed"
            recent_msgs = repl.context.messages[-4:]
            summary_parts = []
            for m in recent_msgs:
                role = m.get("role", "?")
                content = str(m.get("content", ""))[:300]
                if content:
                    summary_parts.append(f"{role}: {content}")
            summary = "\n\n".join(summary_parts) or "(empty conversation)"
            repl.memory_mgr.save_memory(name, summary)
            console.print(f"[green]Saved memory '{name}'[/green]")

        elif sub == "search":
            query = " ".join(args[1:]) if args[1:] else ""
            if not query:
                console.print("[yellow]Usage: /memory search <query>[/yellow]")
                return
            results = repl.memory_mgr.search_memories(query)
            if results:
                lines = ["[bold]Memory search results:[/bold]\n"]
                for r in results:
                    lines.append(f"[cyan]{r['name']}[/cyan] (score: {r['score']})")
                    lines.append(f"  {r['snippet'][:200]}")
                console.print("\n".join(lines))
            else:
                console.print("[yellow]No memories found[/yellow]")

        elif sub == "list":
            memories = repl.memory_mgr.list_memories()
            if memories:
                lines = ["[bold]Memories:[/bold]\n"]
                for m in memories:
                    lines.append(f"  [cyan]{m['name']}[/cyan] ({m['type']})")
                console.print("\n".join(lines))
            else:
                console.print("[yellow]No memories yet[/yellow]")

        elif sub == "delete":
            name = " ".join(args[1:]) if args[1:] else ""
            if not name:
                console.print("[yellow]Usage: /memory delete <name>[/yellow]")
                return
            ok = repl.memory_mgr.delete_memory(name)
            if ok:
                console.print(f"[green]Deleted memory '{name}'[/green]")
            else:
                console.print(f"[yellow]Memory '{name}' not found[/yellow]")

        else:
            console.print("[yellow]Usage: /memory [save|search|list|delete] [args][/yellow]")

    elif command == "/index":
        from ..indexer import index_project
        with console.status("Indexing project...", spinner="dots"):
            project_context = index_project()
        if project_context:
            new_content = f"<project-context>\n{project_context}\n</project-context>"
            replaced = False
            for i, m in enumerate(repl.context.messages):
                content = str(m.get("content", ""))
                if content.startswith("<project-context>") and content.endswith("</project-context>"):
                    repl.context.messages[i]["content"] = new_content
                    console.print(f"[green]Re-indexed project ({project_context.count(chr(10)) + 1} items)[/green]")
                    replaced = True
                    break
            if not replaced:
                repl.context.messages.insert(1, {
                    "role": "user",
                    "content": new_content,
                })
                console.print(f"[green]Indexed project ({project_context.count(chr(10)) + 1} items)[/green]")
        else:
            console.print("[yellow]No project files found to index[/yellow]")

    elif command == "/init":
        result = project_init.init_project()
        console.print(f"[green]{result}[/green]")

    elif command == "/tasks":
        status = args[0] if args else None
        result = tasks.list_tasks(status)
        console.print(result)

    elif command == "/plan":
        if not args:
            plans = planner.list_plans()
            console.print(Markdown(f"**Saved plans:**\n\n{plans}"))
            console.print("[dim]Usage: /plan <task description>  — to create and execute a plan[/dim]")
            return

        task = " ".join(args)
        approved_plan = planner.plan_and_approve(task, repl.config, repl.session)
        if approved_plan is None:
            return

        console.print("\n[bold cyan]Executing approved plan...[/bold cyan]")
        result = planner.execute_plan(approved_plan, task, repl.config)
        console.print(result)

    elif command == "/parallel":
        if not args:
            console.print("[yellow]Usage: /parallel <task description>[/yellow]")
            console.print("[dim]Decomposes the task into parallel subtasks and runs them concurrently.[/dim]")
            return

        task = " ".join(args)
        console.print(f"\n[bold cyan]Parallel execution:[/bold cyan] {task}")

        from ..parallel_executor import ParallelExecutor

        def _on_progress(role: str, status: str):
            icons = {"queued": "○", "running": "◉", "done": "✓", "error": "✗", "timeout": "⏱"}
            icon = icons.get(status, "·")
            colors = {"queued": "dim", "running": "cyan", "done": "green", "error": "red", "timeout": "yellow"}
            color = colors.get(status, "white")
            console.print(f"  [{color}]{icon} {role}[/{color}]")

        executor = ParallelExecutor(repl.config, max_workers=4)
        result = executor.run(task, on_progress=_on_progress)
        console.print("\n" + result)

    elif command == "/branch":
        from ..git.workflow import start_task_branch, in_git_repo

        if not args:
            console.print("[yellow]Usage: /branch <task description>[/yellow]")
            console.print("[dim]Creates and checks out a git branch named task/<slug>[/dim]")
            return

        if not in_git_repo(repl.config.working_directory):
            console.print("[red]Not in a git repository.[/red]")
            return

        task = " ".join(args)
        ok, result = start_task_branch(task, cwd=repl.config.working_directory)
        if ok:
            console.print(f"[green]Switched to branch:[/green] {result}")
            console.print("[dim]Use /finish when done to commit and optionally open a PR.[/dim]")
        else:
            console.print(f"[red]Branch failed:[/red] {result}")

    elif command == "/finish":
        from ..git.workflow import finish_task, in_git_repo, current_branch

        if not in_git_repo(repl.config.working_directory):
            console.print("[red]Not in a git repository.[/red]")
            return

        branch = current_branch(repl.config.working_directory)
        if not branch.startswith("task/"):
            console.print(f"[yellow]Current branch '{branch}' is not a task branch — committing anyway.[/yellow]")

        make_pr = "--pr" in args
        task_args = [a for a in args if a != "--pr"]
        task = " ".join(task_args) if task_args else branch.replace("task/", "").replace("-", " ")

        console.print(f"[bold cyan]Finishing task:[/bold cyan] {task}")
        result = finish_task(task, repl.config, make_pr=make_pr, cwd=repl.config.working_directory)
        console.print(result)
        if not make_pr:
            console.print("[dim]Tip: /finish --pr to also open a GitHub PR.[/dim]")

    elif command == "/review":
        diff = review_skill.review_changes()
        console.print(Markdown(f"**Code Review**\n\n{diff}"))

    elif command == "/security-review":
        analysis = security_skill.security_review()
        console.print(Markdown(f"**Security Review**\n\n{analysis}"))

    elif command == "/allow":
        if args:
            from ..permissions.manager import _save_to_allowlist
            _save_to_allowlist(args[0])
            console.print(f"[green]Allowed {args[0]}[/green]")
        else:
            console.print("[yellow]Usage: /allow <tool_name>[/yellow]")

    elif command == "/debug":
        DEBUG_PROMPT = (
            "You are now in DEBUG MODE. Your single purpose is to make ALL tests pass.\n\n"
            "FOLLOW THIS PROTOCOL STEP BY STEP. Do NOT skip steps.\n\n"
            "STEP 1 — DISCOVER: Find how to run tests. Use Glob to find test files.\n"
            "STEP 2 — RUN: Execute the test command via Bash. Show the full output.\n"
            "STEP 3 — EVALUATE: If ALL tests pass, report success.\n"
            "STEP 4 — ANALYZE: Read failing test output. Identify which tests fail.\n"
            "STEP 5 — DIAGNOSE: Explain the root cause of each failure.\n"
            "STEP 6 — FIX: Edit source files to fix issues.\n"
            "STEP 7 — RE-RUN: Run the tests again.\n"
            "STEP 8 — REPEAT: If any tests still fail, go back to STEP 4. Maximum 5 iterations.\n\n"
            "CRITICAL RULES:\n"
            "- Read files before editing them\n"
            "- Make minimal, targeted fixes\n"
            "- Show test output clearly at each iteration"
        )
        console.print("\n[bold cyan]Entering DEBUG MODE[/bold cyan]")
        console.print("[dim]I will run tests, find failures, fix them, and repeat until all pass.[/dim]\n")
        # Auto-backup before debug modifies any files
        console.print("[yellow]Creating safety backup before debug...[/yellow]")
        bk = create_backup("pre-debug", cwd=repl.config.working_directory)
        if bk["ok"]:
            console.print(f"[green]Backup ready: {bk['message']}[/green]")
            console.print("[dim]Run /backup restore to undo any changes if something breaks.[/dim]\n")
        else:
            console.print(f"[yellow]Backup skipped: {bk['error']}[/yellow]\n")
        repl.context.messages.insert(1, {
            "role": "system",
            "content": DEBUG_PROMPT,
        })
        repl.context.add_user_message(
            "Run the debug protocol. Find how to run tests, execute them, "
            "fix any failures iteratively, and make ALL tests pass. "
            "Show each step clearly."
        )
        repl._chat_loop()

    elif command == "/self-improve":
        from ..self_improve import SELF_IMPROVE_PROMPT, get_improvement_prompt, ImprovementTracker
        console.print("\n[bold cyan]SELF-IMPROVEMENT MODE[/bold cyan]")
        console.print("[dim]The AI will analyze, propose, implement, and verify improvements to itself.[/dim]\n")
        # Auto-backup before any source files are modified
        console.print("[yellow]Creating safety backup before self-improve...[/yellow]")
        bk = create_backup("pre-self-improve", cwd=repl.config.working_directory)
        if bk["ok"]:
            console.print(f"[green]Backup ready: {bk['message']}[/green]")
            console.print("[dim]Run /backup restore to undo all changes if something breaks.[/dim]\n")
        else:
            console.print(f"[yellow]Backup skipped: {bk['error']}[/yellow]\n")

        tracker = ImprovementTracker()
        snap_msg = tracker.snapshot()
        console.print(f"[dim]{snap_msg}[/dim]")

        repl.context.messages.insert(1, {
            "role": "system",
            "content": SELF_IMPROVE_PROMPT,
        })
        area = args[0] if args else ""
        task = get_improvement_prompt(area)
        repl.context.add_user_message(task)
        repl._chat_loop()

        report = tracker.report(commit=False)
        if report.files_changed:
            console.print("\n[bold cyan]Changes Made:[/bold cyan]")
            console.print(report.diff_summary)
        else:
            console.print("[yellow]No file changes were detected by git.[/yellow]")

    elif command == "/orchestrate":
        from ..orchestrator import Coordinator
        if not args:
            console.print("[yellow]Usage: /orchestrate <task description>[/yellow]")
            console.print("[dim]Example: /orchestrate add error handling to web_app.py[/dim]")
            return
        task = " ".join(args)
        console.print(f"[bold cyan]Orchestrating:[/bold cyan] {task}")
        console.print("[dim]Running researcher -> coder -> reviewer pipeline...[/dim]")
        coord = Coordinator(repl.config)
        result = coord.orchestrate(task)
        console.print(result)

    elif command == "/background":
        handle_background_command(repl, args)

    elif command == "/watch":
        if not args:
            console.print("[yellow]Usage: /watch start|stop|status[/yellow]")
            return
        sub = args[0].lower()
        if sub == "start":
            if repl.file_watcher and repl.file_watcher.is_running:
                console.print("[yellow]File watcher already running[/yellow]")
            else:
                from ..file_watcher import FileWatcher
                repl.file_watcher = FileWatcher()
                repl.file_watcher.start()
                console.print("[green]File watcher started — auto-reindexing on changes[/green]")
        elif sub == "stop":
            if repl.file_watcher and repl.file_watcher.is_running:
                repl.file_watcher.stop()
                console.print("[yellow]File watcher stopped[/yellow]")
            else:
                console.print("[yellow]File watcher is not running[/yellow]")
        elif sub == "status":
            if repl.file_watcher:
                console.print(f"[cyan]File watcher:[/cyan] {repl.file_watcher.status}")
            else:
                console.print("[yellow]File watcher not initialized[/yellow]")
        else:
            console.print(f"[red]Unknown: /watch {sub}[/red]")

    elif command == "/sandbox":
        from ..sandbox import get_sandbox, check_docker
        sub = args[0].lower() if args else "status"
        if sub == "status":
            available, version = check_docker()
            if available:
                sb = get_sandbox()
                image_ready = sb.ensure_image()
                console.print(f"[green]Docker:[/green] {version}")
                console.print(f"[cyan]Image:[/cyan] {sb.image} ({'ready' if image_ready else 'not pulled'})")
                console.print("[green]Sandbox mode: ACTIVE[/green]")
            else:
                console.print("[yellow]Docker not found — commands run without sandboxing[/yellow]")
                console.print("[dim]Install Docker to enable isolated command execution[/dim]")
        else:
            console.print("[yellow]Usage: /sandbox status[/yellow]")

    elif command == "/undo":
        from ..undo import undo_last
        result = undo_last()
        console.print(f"[cyan]{result}[/cyan]")

    elif command == "/sessions":
        handle_sessions_command(repl, args)

    elif command == "/brain":
        handle_brain_command(repl, args)

    elif command == "/audit":
        handle_audit_command(repl, args)

    else:
        console.print(f"[red]Unknown command: {command}. Type /help[/red]")
