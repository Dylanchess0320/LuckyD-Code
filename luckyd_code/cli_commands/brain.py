"""Handle /brain commands."""

import os
import time as _time

from ..brain import Retriever, VectorIndexer, rebuild_project


def handle_brain_command(repl, args):
    """Handle /brain rebuild|stats|status commands."""
    from ..cli_utils import console

    sub = args[0].lower() if args else "status"

    if sub == "rebuild":
        with console.status("Rebuilding codebase index...", spinner="dots"):
            result = rebuild_project(os.getcwd())
            repl.brain.load()
            repl._rag_retriever = None

        rag_info = f"{result.get('chunks', 0)} chunks, {result.get('files', 0)} files" if result.get('chunks') else "no supported files found"
        console.print(
            f"[green]Brain rebuilt:[/green] {rag_info} | "
            f"{result.get('node_count', 0)} symbols, "
            f"{result.get('files_parsed', 0)} files"
        )

        brain_summary = repl.brain.summarize()
        for i, m in enumerate(repl.context.messages):
            if isinstance(m.get("content"), str) and m["content"].startswith("<knowledge-graph>"):
                repl.context.messages[i]["content"] = brain_summary
                break
            elif isinstance(m.get("content"), str) and m["content"].startswith("<rag-context>"):
                repl.context.messages.pop(i)
                break
        else:
            repl.context.messages.insert(1, {
                "role": "user",
                "content": brain_summary,
            })

    elif sub == "stats":
        has_rag = True
        try:
            r = Retriever()
            info = r.stats()
        except Exception:
            has_rag = False

        if not repl.brain.nodes and not has_rag:
            console.print("[yellow]Brain is empty. Run `/brain rebuild` to index your codebase.[/yellow]")
            return

        from ..tools.brain_tools import BrainStatusTool
        status = BrainStatusTool()
        console.print(status.run())

    else:  # "status" or no args
        rag_available = False
        try:
            idx = VectorIndexer()
            rag_available = idx.load()
        except Exception:
            pass

        if not repl.brain.nodes and not rag_available:
            console.print("[yellow]Brain is empty. Run `/brain rebuild` to index your codebase.[/yellow]")
            return

        if rag_available:
            r = Retriever()
            info = r.stats()
            vec = info.get("vector", {})
            console.print(
                f"[cyan]Brain:[/cyan] {vec.get('chunks', 0)} chunks, "
                f"{vec.get('files', 0)} files | "
                f"{repl.brain.stats.get('node_count', 0)} symbols"
            )
        else:
            console.print(f"[cyan]Brain:[/cyan] {repl.brain.stats.get('node_count', 0)} symbols, "
                         f"{repl.brain.stats.get('edge_count', 0)} relations, "
                         f"{repl.brain.stats.get('files_parsed', 0)} files")
        if repl.brain.stats.get("last_built"):
            last = _time.strftime("%Y-%m-%d %H:%M:%S",
                                 _time.localtime(repl.brain.stats["last_built"]))
            console.print(f"[cyan]Last built:[/cyan] {last}")
        console.print("[dim]Full stats: /brain stats | Rebuild: /brain rebuild[/dim]")
