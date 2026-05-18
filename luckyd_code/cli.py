import json
import os
import signal
import subprocess
import sys
import io
import threading
import time
from pathlib import Path

# Force UTF-8 encoding for Windows console compatibility with Rich Unicode output
if sys.platform == "win32":
    # Set the console code page to UTF-8 so the terminal decodes bytes correctly.
    # Without this, box-drawing characters (╔═╗║╚╝) render as mojibake (ΓòöΓòÉ...).
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleCP(65001)
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    except Exception:
        pass
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from typing import Any

from rich.console import Console

from ._data_dir import data_path
from .api import stream_chat, test_connection, _repair_json
from .config import Config
from .context import ConversationContext
from .tools import get_default_registry
from .tools.agent_tools import set_repl
from .permissions.manager import check_permission
from . import memory, settings as cfg
from .memory import MemoryManager
from .hooks import get_hook_runner
from .cost_tracker import CostTracker
from . import update as updater
from .log import get_logger
from .themes import get_theme
from .mcp.client import MCPManager
from .background import BackgroundAgent
from .brain import KnowledgeGraph, Retriever, ContextAssembler
from .cli_utils import console, init_prompt_session, read_input, play_completion_sound
from .git.auto_commit import auto_commit, collect_modified_paths
from .verify import run_verify_pipeline, pipeline_all_passed, pipeline_feedback

class Repl:
    def __init__(self, config: Config, daemon: bool = False):
        self.config = config
        self.config.validate()
        self.registry = get_default_registry()
        self.context = ConversationContext(
            config.system_prompt,
            max_messages=config.max_context_messages,
        )
        self.session = init_prompt_session()
        self.mcp = MCPManager()
        self.background = BackgroundAgent(config)
        self.background.load_history()
        self.brain = KnowledgeGraph()
        self.brain.load()
        self._rag_retriever: Retriever | None = None
        self._rag_assembler = ContextAssembler()
        self.memory_mgr = MemoryManager()
        self.hooks = get_hook_runner()
        self.cost_tracker = CostTracker()
        self.file_watcher: Any = None
        self._stop_requested = False
        self._first_sigint_at = 0.0
        # Reasoning content captured from the last "done" stream event.
        # Passed to add_assistant_message so the context retains reasoning.
        self._pending_reasoning: str = ""
        # Whether to run the background audit daemon alongside the REPL
        self._daemon_enabled: bool = daemon
        self._audit_daemon_thread: threading.Thread | None = None
        self._audit_daemon: Any = None
        set_repl(self)

        # Load theme
        settings = cfg.load_settings()
        self.theme_name = settings.get("theme", "dark")
        # Update console in BOTH cli.py and cli_utils.py so that all
        # Rich output (including prompts and sounds) shares the theme.
        from . import cli_utils as _cli_utils_mod
        _new_console = Console(theme=get_theme(self.theme_name))
        _cli_utils_mod.console = _new_console
        global console
        console = _new_console

    def run(self) -> None:
        # Clear the terminal so output starts at the top
        console.clear()
        self._running = True
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

        # Run session-start hooks
        self.hooks.run_hook("onSessionStart", {
            "model": self.config.model,
            "provider": self.config.provider,
        })

        # Initialize everything under a single spinner
        ok = False
        msg = ""
        with console.status("Starting...", spinner="dots"):
            # Test API connection
            ok, msg = test_connection(self.config.api_key, self.config.base_url)
            # Load MCP tools
            self._init_mcp()
            # Load memory (project indexing, brain)
            self._load_memory()

        if not ok:
            console.print(f"[error]API connection failed: {msg}[/error]")
            self._prompt_for_api_key()
            # Retry after key entry
            with console.status("Reconnecting...", spinner="dots"):
                ok, msg = test_connection(self.config.api_key, self.config.base_url)
            if ok:
                console.print("[green]Connected![/green]")
            else:
                console.print(f"[error]Still failed: {msg}[/error]")

        tool_count = len(self.registry.list_tools()) + len(self.mcp.get_all_tools())
        symbol_summary = f"{self.brain.stats.get('node_count', 0)} symbols" if self.brain.nodes else ""
        effort = getattr(self.config, "effort", "normal")
        effort_icons = {"low": "⚡", "normal": "◎", "high": "◉", "max": "🔥"}
        effort_str = f"{effort_icons.get(effort, '◎')} {effort}"
        console.print(f"[dim]LuckyD Code v{updater.get_version()} — {tool_count} tools{', ' + symbol_summary if symbol_summary else ''} — effort: {effort_str} — /help for commands[/dim]")

        # RAG availability notice — shown once at startup
        from .brain import is_rag_available as _is_rag_available
        if _is_rag_available() and not self.brain.nodes:
            console.print("[dim]💡 RAG backend ready — run [bold]/brain rebuild[/bold] to enable semantic code search[/dim]")
        elif not _is_rag_available():
            console.print('[dim]⚡ Tip: [bold]pip install "luckyd-code[rag-full]"[/bold] for semantic codebase search[/dim]')

        # Start background audit daemon if requested via --daemon flag
        if self._daemon_enabled:
            self._start_audit_daemon()


        while True:
            # Reset stop flag for each new prompt cycle
            self._stop_requested = False
            self._first_sigint_at = 0.0

            user_input = read_input(self.session)
            if user_input == "__EOF__":
                print()
                break
            if user_input is None:
                print()
                continue

            user_input = user_input.strip()
            if not user_input:
                continue

            if user_input.startswith("/"):
                from .cli_commands.dispatcher import handle_command
                handle_command(self, user_input)
                continue

            self.context.add_user_message(user_input)
            try:
                self._chat_loop(user_input)
            except Exception as e:
                get_logger().error("Chat error: %s", e, exc_info=True)
                console.print(f"[red]Something went wrong: {e}[/red]")
                # Reset context to recover
                self.context = ConversationContext(
                    self.config.system_prompt,
                    max_messages=self.config.max_context_messages,
                )
            print()
        self.hooks.run_hook("onSessionEnd")
        self._cleanup()

    def _init_mcp(self) -> None:
        """Initialize MCP servers from settings."""
        settings = cfg.load_settings()
        self.mcp.load_from_config(settings)

    def _load_memory(self) -> None:
        md = memory.load_claude_md()

        # Merge session memories into the project memory block so the model
        # sees one coherent memory context instead of two overlapping blocks
        session_memories = self.memory_mgr.get_all_memories_formatted()
        if md and session_memories:
            merged = md + "\n\n" + session_memories
        elif session_memories:
            merged = session_memories
        else:
            merged = md or ""

        if merged:
            self.context.messages.insert(1, {
                "role": "user",
                "content": f"<claude-md>{merged}</claude-md>",
            })

        # Smart project indexing
        from .indexer import index_project
        project_context = index_project()
        if project_context:
            idx = 2 if merged else 1
            has_context = any(
                isinstance(m.get("content"), str) and m["content"].startswith("<project-context>")
                for m in self.context.messages
            )
            if not has_context:
                self.context.messages.insert(idx, {
                    "role": "user",
                    "content": f"<project-context>\n{project_context}\n</project-context>",
                })

        # Load knowledge graph
        if self.brain.nodes:
            brain_summary = self.brain.summarize()
            has_brain = any(
                isinstance(m.get("content"), str) and m["content"].startswith("<knowledge-graph>")
                for m in self.context.messages
            )
            if not has_brain:
                self.context.messages.insert(1, {
                    "role": "user",
                    "content": brain_summary,
                })

        # Silently restore auto-saved conversation from recovery file
        try:
            recovery_file = data_path("recovery.json")
            if recovery_file.exists():
                data = json.loads(recovery_file.read_text(encoding="utf-8"))
                if len(data) > 1:
                    self.context.messages = data
                    get_logger().info("Restored %d messages from recovery", len(data) - 1)
                    recovery_file.unlink(missing_ok=True)
        except Exception:
            get_logger().warning("Failed to check recovery file", exc_info=True)

    def _prompt_for_api_key(self) -> None:
        """Prompt user to enter a new API key and save it to .env."""
        from .cli_utils import read_input
        console.print("\n[bold]Enter your DEEPSEEK_API_KEY:[/bold] (or press Enter to skip)")
        new_key = read_input(self.session)
        if new_key and new_key.strip():
            new_key = new_key.strip()
            self.config.api_key = new_key
            env_path = Path(__file__).parent.parent / ".env"
            if env_path.exists():
                lines = env_path.read_text(encoding="utf-8").splitlines()
                found = False
                for i, line in enumerate(lines):
                    if line.strip().startswith("DEEPSEEK_API_KEY="):
                        lines[i] = f"DEEPSEEK_API_KEY={new_key}"
                        found = True
                        break
                if not found:
                    lines.append(f"DEEPSEEK_API_KEY={new_key}")
                env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            else:
                env_path.write_text(f"DEEPSEEK_API_KEY={new_key}\n", encoding="utf-8")
            console.print("[green]Key saved to .env[/green]")

    def _get_rag_retriever(self) -> Retriever:
        """Lazy init the RAG retriever."""
        if self._rag_retriever is None:
            self._rag_retriever = Retriever()
        return self._rag_retriever

    def _inject_rag_context(self, force: bool = False) -> None:
        """Silently search for context relevant to the user's latest message and inject it."""
        try:
            user_msg = None
            for m in reversed(self.context.messages):
                if m.get("role") == "user" and isinstance(m.get("content"), str):
                    user_msg = m["content"]
                    break

            if not user_msg or len(user_msg.strip()) < 15:
                return

            retriever = self._get_rag_retriever()
            results = retriever.search(user_msg, k=5)
            if not results:
                return

            if force:
                self.context.messages = [
                    m for m in self.context.messages
                    if not (isinstance(m.get("content"), str) and m["content"].startswith("<rag-context>"))
                ]

            if not force:
                has_rag = any(
                    isinstance(m.get("content"), str) and m["content"].startswith("<rag-context>")
                    for m in self.context.messages
                )
                if has_rag:
                    return

            context_block = self._rag_assembler.assemble(results, max_tokens=1500, max_chunks=5)
            if context_block:
                self.context.messages.insert(1, {
                    "role": "user",
                    "content": f"<rag-context>\n{context_block}\n</rag-context>",
                })
        except Exception:
            get_logger().warning("RAG context injection failed", exc_info=True)

    def _get_reasoner_model(self) -> str:
        """Return the model name to use for complex/reasoning tasks based on provider."""
        from .router import select_model
        return select_model("complex task", recent_tool_count=6,
                            preferred_model=self.config.model)

    def _chat_loop(self, user_prompt: str = "") -> None:
        max_iterations = 20        # hard cap (was 100)
        max_consecutive_errors = 3  # bail if tool calls keep failing
        iteration = 0
        tool_call_count = 0
        consecutive_errors = 0
        _budget_warning_sent = False

        # Per-turn state for auto-commit
        all_tool_calls: list[dict[str, Any]] = []
        tool_args_map: dict[str, dict[str, Any]] = {}  # tool_call_id → parsed args
        # Track all files modified this turn for verification
        modified_files_this_turn: list[str] = []

        settings = cfg.load_settings()
        auto_route = settings.get("auto_route", True)
        auto_commit_enabled = settings.get("auto_commit", True)
        verify_enabled = settings.get("verify_edits", True)
        verify_retries = settings.get("verify_retries", 3)
        project_root = str(self.config.working_directory or os.getcwd())

        from .router import resolve_initial_route, escalate_tier
        current_tier = 2
        active_model = self.config.model
        t0 = time.time()
        text_buffer = ""

        while iteration < max_iterations:
            if self._stop_requested:
                if text_buffer:
                    self.context.add_assistant_message(content=text_buffer)
                console.print("\n[dim]⏹ Stopped[/dim]")
                self._stop_requested = False
                return

            # ── token budget warning ─────────────────────────────────────────
            turns_remaining = max_iterations - iteration
            if turns_remaining <= 3 and not _budget_warning_sent:
                self.context.add_user_message(
                    f"[System: {turns_remaining} turn(s) remaining in this session. "
                    "Wrap up your work and give a final answer now.]"
                )
                _budget_warning_sent = True

            # ── 75% token budget protection ──────────────────────────────────
            est = self.context.estimate_tokens()
            budget = getattr(self.config, "max_tokens", 4096)
            if est > budget * 0.75 and not _budget_warning_sent:
                console.print("[dim yellow]⚠ Approaching token limit — wrapping up[/dim yellow]")
                self.context.add_user_message(
                    "[System: context window is nearly full. Finish your current task and return a final answer now. Do not start new tool calls.]"
                )
                _budget_warning_sent = True

            iteration += 1
            messages = self.context.get_messages()
            text_buffer = ""
            pending_tool_calls = None
            tool_reasoning = ""

            all_tools = self.registry.list_tools()
            all_tools.extend(self.mcp.get_all_tools())

            user_msgs = [m for m in messages if m.get("role") == "user"]
            user_text = user_msgs[-1].get("content", "") if user_msgs else ""
            if auto_route and user_text:
                if iteration == 1 and tool_call_count == 0:
                    result = resolve_initial_route(
                        user_text, tool_call_count, self.config.provider,
                        self.config.model, auto_route,
                        config=self.config,
                    )
                else:
                    result = escalate_tier(
                        user_text, tool_call_count, self.config.provider,
                        self.config.model, active_model, current_tier, auto_route,
                    )
                active_model = result.model
                current_tier = result.tier

            if iteration == 1:
                console.print(f"[dim]... {int(time.time() - t0)}s[/dim]")

            if iteration == 1:
                self._inject_rag_context()
                messages = self.context.get_messages()
            elif iteration % 3 == 0 and tool_call_count > 0:
                self._inject_rag_context(force=True)
                messages = self.context.get_messages()

            if iteration == 1 and tool_call_count == 0:
                try:
                    # Use 1/4 of the model's full context budget as the
                    # pre-turn compaction trigger.  The old value (28 000)
                    # was far too small for a 800 K-token context window
                    # and caused history to be wiped after just a few exchanges.
                    context_limit = self.context._token_compact_threshold // 4
                    est_tokens = self.context.estimate_tokens()
                    if est_tokens > context_limit:
                        self.context.compact(
                            self.config, active_model, keep_last=6,
                            on_compact=lambda s, c: self.memory_mgr.save_conversation_summary(s, c),
                        )
                        messages = self.context.get_messages()
                except Exception:
                    get_logger().warning("Auto-compaction failed", exc_info=True)

            print()
            text_buffer, pending_tool_calls, tool_reasoning, active_model = self._stream_with_fallback(
                messages, all_tools, active_model, current_tier,
            )

            if pending_tool_calls:
                tool_call_count = self._execute_tool_calls(
                    pending_tool_calls, tool_reasoning, text_buffer,
                    tool_call_count, t0, tool_args_map,
                )
                all_tool_calls.extend(pending_tool_calls)

                # Track consecutive errors for bail-out
                last_results = [
                    m.get("content", "") for m in self.context.messages[-len(pending_tool_calls):]
                    if m.get("role") == "tool"
                ]
                if all(str(r).startswith("Error") for r in last_results if r):
                    consecutive_errors += 1
                else:
                    consecutive_errors = 0

                if consecutive_errors >= max_consecutive_errors:
                    console.print(f"[yellow]⚠ {consecutive_errors} consecutive tool errors — stopping to avoid wasting tokens[/yellow]")
                    self.context.add_assistant_message(
                        content=f"I encountered {consecutive_errors} consecutive tool failures and stopped to avoid wasting tokens. "
                        "Here's what I tried and where I got stuck. Please review and let me know how to proceed."
                    )
                    break

                # Track files modified by Write/Edit tools
                for tc in pending_tool_calls:
                    if tc["function"]["name"] in ("Write", "Edit"):
                        tid = tc["id"]
                        args = tool_args_map.get(tid, {})
                        fp = args.get("file_path", "")
                        if fp and fp not in modified_files_this_turn:
                            modified_files_this_turn.append(fp)

                # ── VERIFICATION GATE ─────────────────────────────────
                # Run multi-pass verification on all modified files
                if verify_enabled and modified_files_this_turn:
                    self._run_verification_gate(
                        modified_files_this_turn, project_root, verify_retries,
                    )

                # Fix-until-green: auto-run tests after any file write/edit
                test_feedback = self._maybe_run_tests(pending_tool_calls)
                if test_feedback:
                    self.context.add_user_message(test_feedback)
                continue

            if text_buffer:
                self.context.add_assistant_message(
                    content=text_buffer,
                    reasoning_content=self._pending_reasoning or None,
                )
                self._pending_reasoning = ""

            break

        if iteration >= max_iterations:
            console.print(f"[yellow]⚠ Reached the {max_iterations}-turn limit. The task may be too complex for one session. Try breaking it into smaller steps or use /orchestrate.[/yellow]")
            play_completion_sound(success=False)
        else:
            play_completion_sound(success=True)

        # Auto-commit any files the agent wrote or edited this turn
        if auto_commit_enabled and all_tool_calls:
            modified = collect_modified_paths(all_tool_calls, tool_args_map)
            if modified:
                sha = auto_commit(
                    user_prompt=user_prompt,
                    modified_paths=modified,
                    cwd=self.config.working_directory,
                    enabled=True,
                )
                if sha:
                    console.print(f"[dim]git: auto-committed {len(modified)} file(s) [{sha}][/dim]")

    def _fallback_models(
        self, active_model: str, current_tier: int
    ) -> Any:  # Generator[tuple[str, str, str], None, None]
        """Generator yielding (model, api_key, base_url) for the fallback chain."""
        from .router import DEEPSEEK_FALLBACK_MODELS

        models_tried = set()

        models_tried.add(active_model)
        yield active_model, self.config.api_key, self.config.base_url

        for model in DEEPSEEK_FALLBACK_MODELS:
            if model not in models_tried:
                models_tried.add(model)
                yield model, self.config.api_key, self.config.base_url

    def _stream_with_fallback(
        self,
        messages: list[dict[str, Any]],
        all_tools: list[dict[str, Any]],
        active_model: str,
        current_tier: int,
    ) -> tuple[str, list[dict[str, Any]] | None, str, str]:
        """Stream response with model fallback chain."""
        self.hooks.run_hook("preChat", {
            "model": active_model,
            "message_count": str(self.context.count_messages()),
        })

        text_buffer: str = ""
        pending_tool_calls: list[dict[str, Any]] | None = None
        tool_reasoning: str = ""
        last_error: Any = None
        _reasoning_started: bool = False  # track first reasoning chunk for header

        attempt_model: str = active_model
        for attempt_model, api_key, base_url in self._fallback_models(active_model, current_tier):
            stream_failed = False
            auth_retried = False

            while True:
                stream_failed = False
                _reasoning_started = False
                for event_type, data in stream_chat(
                    messages=messages,
                    tools=all_tools,
                    model=attempt_model,
                    api_key=api_key,
                    base_url=base_url,
                    max_tokens=self.config.max_tokens,
                    temperature=self.config.temperature,
                ):
                    # Check for user-requested stop (Ctrl+C / /stop)
                    if self._stop_requested:
                        stream_failed = True
                        break

                    if event_type == "model_not_found":
                        stream_failed = True
                        break
                    elif event_type == "reasoning":
                        # Stream DeepSeek Reasoner chain-of-thought live in dim style
                        if not _reasoning_started:
                            _reasoning_started = True
                            sys.stdout.write("\n")
                            console.print("[dim]\u22ef thinking[/dim]")
                        console.print(data, style="dim", end="", highlight=False)
                        sys.stdout.flush()
                    elif event_type == "text":
                        if _reasoning_started:
                            # Separator between reasoning and answer
                            sys.stdout.write("\n")
                            console.print("[dim]\u2500\u2500\u2500[/dim]")
                            _reasoning_started = False
                        sys.stdout.write(data)
                        sys.stdout.flush()
                        text_buffer += data
                    elif event_type == "tool_calls":
                        pending_tool_calls, tool_reasoning = data
                    elif event_type == "error":
                        is_auth = (
                            "401" in str(data)
                            or "authentication" in str(data).lower()
                            or "unauthorized" in str(data).lower()
                            or "invalid api key" in str(data).lower()
                        )
                        if is_auth and not auth_retried:
                            text_buffer = ""
                            pending_tool_calls = None
                            console.print("\n[red]API key rejected.[/red]")
                            self._prompt_for_api_key()
                            api_key = self.config.api_key
                            auth_retried = True
                            stream_failed = True
                            break
                        console.print(f"[red]API Error: {data}[/red]")
                        stream_failed = True
                        last_error = data
                        break
                    elif event_type == "done":
                        content, reasoning = data
                        # Store reasoning so _chat_loop can include it when
                        # adding the message to context.  Do NOT clear
                        # text_buffer here — leave it non-empty so the
                        # loop finishes normally.
                        self._pending_reasoning = reasoning
                        pending_tool_calls = None
                        stream_failed = False
                        break

                if not stream_failed:
                    break
                if auth_retried and stream_failed:
                    auth_retried = False
                    break
                break

            if self._stop_requested:
                break
            if not stream_failed:
                break
            if last_error and "model" not in str(last_error).lower():
                break
        else:
            detail = f" Last error: {str(last_error)[:200]}" if last_error else ""
            get_logger().error("All models exhausted.%s", detail)

        total_chars = sum(len(str(m.get("content", ""))) for m in messages)
        self.cost_tracker.record_usage(
            model=attempt_model,
            input_tokens=max(total_chars // 4, 1),
            output_tokens=max(len(text_buffer) // 4, 1),
        )
        self.hooks.run_hook("postChat", {
            "model": attempt_model,
            "tool_calls": str(len(pending_tool_calls)) if pending_tool_calls else "0",
        })

        return text_buffer, pending_tool_calls, tool_reasoning, attempt_model

    def _execute_tool_calls(
        self,
        pending_tool_calls: list[dict[str, Any]],
        tool_reasoning: str,
        text_buffer: str,
        tool_call_count: int,
        t0: float = 0,
        tool_args_map: dict[str, Any] | None = None,
    ) -> int:
        """Execute tool calls with permissions, hooks, and result rendering."""
        self.context.add_assistant_message(
            text_buffer or None,
            tool_calls=pending_tool_calls,
            reasoning_content=tool_reasoning or None,
        )

        total = len(pending_tool_calls)
        # Streamed text doesn't end with a newline, so force one here to
        # prevent tool stamps from appearing glued to the last word of output.
        sys.stdout.write("\n")
        sys.stdout.flush()
        for i, tc in enumerate(pending_tool_calls, 1):
            name = tc["function"]["name"]
            raw_args = tc["function"]["arguments"]
            try:
                args = json.loads(_repair_json(raw_args)) if raw_args else {}
            except json.JSONDecodeError:
                self.context.add_tool_result(
                    tool_call_id=tc["id"], tool_name=name,
                    result=f"Error: invalid JSON in tool arguments: {raw_args[:200]}",
                )
                continue

            # Record parsed args for auto-commit path tracking
            if tool_args_map is not None:
                tool_args_map[tc["id"]] = args

            if not check_permission(name):
                self.context.add_tool_result(
                    tool_call_id=tc["id"], tool_name=name,
                    result="Permission denied",
                )
                continue

            hook_results = self.hooks.run_hook("preToolUse", {
                "tool_name": name,
                "tool_args": str(args)[:500],
            })
            if any(not r.allow for r in hook_results):
                self.context.add_tool_result(
                    tool_call_id=tc["id"], tool_name=name,
                    result="Tool blocked by preToolUse hook",
                )
                continue

            elapsed = int(time.time() - t0) if t0 else 0
            console.print(f"[dim]{name} ({i}/{total}) {elapsed}s[/dim]")

            if name.startswith("mcp_"):
                result = self.mcp.execute(name, args)
            else:
                result = self.registry.execute(name, args)

            self.hooks.run_hook("postToolUse", {
                "tool_name": name,
                "tool_result_length": str(len(result)),
            })

            self.context.add_tool_result(
                tool_call_id=tc["id"], tool_name=name, result=result,
            )
            tool_call_count += 1

        return tool_call_count

    def _maybe_run_tests(self, tool_calls: list[dict[str, Any]]) -> str | None:
        """After Write/Edit tool calls, auto-run the test suite.

        Disabled by default (auto_test=False). Enable per-project via
        /config set auto_test true. Returns a failure message for the model
        to fix, or None if tests passed or the feature is disabled.
        """
        write_tools = {"Write", "Edit"}
        did_write = any(tc["function"]["name"] in write_tools for tc in tool_calls)
        if not did_write:
            return None

        settings = cfg.load_settings()
        if not settings.get("auto_test", False):
            return None

        cwd = str(self.config.working_directory or os.getcwd())
        runner_cmd = self._detect_test_runner(cwd)
        if not runner_cmd:
            return None

        console.print(f"[dim]Running tests: {runner_cmd}[/dim]")
        try:
            result = subprocess.run(
                runner_cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=60,
                cwd=cwd,
            )
            if result.returncode == 0:
                output_preview = (result.stdout or "").strip()[:300]
                console.print("[dim green]Tests passed[/dim green]"
                               + (f" — {output_preview}" if output_preview else ""))
                return None
            # Tests failed — collect output and feed it back to the model
            full_output = ((result.stdout or "") + (result.stderr or "")).strip()
            truncated = full_output[:3000]
            if len(full_output) > 3000:
                truncated += f"\n... ({len(full_output) - 3000} chars truncated)"
            console.print("[dim red]Tests failed — asking model to fix...[/dim red]")
            return (
                f"Tests failed after your last change. Please fix all failures before continuing.\n"
                f"\n```\n{truncated}\n```"
            )
        except subprocess.TimeoutExpired:
            console.print("[dim]Test run timed out (60s) — skipping[/dim]")
            return None
        except Exception as e:
            get_logger().warning("Test runner error: %s", e)
            return None

    def _detect_test_runner(self, cwd: str) -> str | None:
        """Detect the appropriate test runner for the project.

        Checks in priority order: pytest, jest/vitest, cargo, go test.
        Prefers the virtualenv binary on Windows over the global one.
        """
        root = Path(cwd)

        # Python: pytest
        has_pytest_cfg = (
            (root / "pytest.ini").exists()
            or (root / "pyproject.toml").exists()
            or (root / "setup.cfg").exists()
            or (root / "tests").is_dir()
        )
        if has_pytest_cfg:
            if sys.platform == "win32":
                venv_pytest = root / ".venv" / "Scripts" / "pytest.exe"
                if venv_pytest.exists():
                    return f'"{venv_pytest}" -x -q --tb=short'
            else:
                venv_pytest = root / ".venv" / "bin" / "pytest"
                if venv_pytest.exists():
                    return f'"{venv_pytest}" -x -q --tb=short'
            return "pytest -x -q --tb=short"

        # JavaScript/TypeScript: vitest or jest
        pkg = root / "package.json"
        if pkg.exists():
            try:
                import json as _json
                data = _json.loads(pkg.read_text(encoding="utf-8"))
                scripts = data.get("scripts", {})
                if "test" in scripts:
                    return "npm test -- --passWithNoTests 2>&1"
            except Exception:
                pass

        # Rust: cargo test
        if (root / "Cargo.toml").exists():
            return "cargo test 2>&1"

        # Go: go test
        if (root / "go.mod").exists():
            return "go test ./... 2>&1"

        return None

    def _run_verification_gate(
        self,
        modified_files: list[str],
        project_root: str,
        max_retries: int = 3,
    ) -> None:
        """Run the multi-pass verification pipeline on modified files.

        If verification fails, injects feedback into the conversation context
        so the model can fix issues on the next iteration.
        """
        for file_path in modified_files:
            if not file_path.endswith(".py"):
                continue

            for attempt in range(max_retries + 1):
                results = run_verify_pipeline(
                    file_path=file_path,
                    project_root=project_root,
                    run_lint=False,
                    run_consistency=True,
                    run_tests=False,  # tests handled separately by _maybe_run_tests
                )

                if pipeline_all_passed(results):
                    if attempt == 0:
                        # Only show first-attempt success as dim
                        console.print(f"[dim]✓ verify: {Path(file_path).name}[/dim]")
                    else:
                        console.print(
                            f"[dim green]✓ verify: {Path(file_path).name} "
                            f"(fixed after {attempt} attempt(s))[/dim green]"
                        )
                    break

                # Build feedback for the model
                feedback = pipeline_feedback(results)
                console.print(
                    f"[dim yellow]⚠ verify: {Path(file_path).name} "
                    f"(attempt {attempt + 1}/{max_retries + 1})[/dim yellow]"
                )

                if attempt >= max_retries:
                    get_logger().warning(
                        "Verification still failing after %d retries for %s",
                        max_retries, file_path,
                    )
                    # Inject failure as user message so the model sees it next turn
                    self.context.add_user_message(
                        f"⚠ Verification failed for {file_path} after {max_retries + 1} "
                        f"attempts. Please fix these issues:\n\n{feedback}"
                    )
                    break

                # Inject feedback for the model to fix
                self.context.add_user_message(
                    f"Verification found issues in {file_path}. "
                    f"Fix them before proceeding:\n\n{feedback}"
                )
                # Don't break here — the model will fix on the next turn

    def _handle_command(self, cmd: str) -> None:
        from .cli_commands.dispatcher import handle_command
        handle_command(self, cmd)

    def _save_state(self) -> None:
        """Save current configuration and state."""
        try:
            self.config.save()
            from . import settings as cfg
            cfg.save_setting("model_name", self.config.model)
        except Exception:
            get_logger().warning("Failed to save state", exc_info=True)
            console.print("[dim]Failed to save state[/dim]")

    def _start_audit_daemon(self) -> None:
        """Start AuditDaemon.run_forever() in a background daemon thread."""
        import threading
        import asyncio
        from .audit_daemon import AuditDaemon
        from pathlib import Path as _Path

        project_root = str(self.config.working_directory or _Path.cwd())
        daemon_obj = AuditDaemon(self.config, project_root=project_root)
        self._audit_daemon = daemon_obj

        def _run_loop() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(daemon_obj.run_forever())
            finally:
                loop.close()

        t = threading.Thread(target=_run_loop, name="audit-daemon", daemon=True)
        t.start()
        self._audit_daemon_thread = t
        console.print("[dim]Audit daemon started in background[/dim]")

    def _stop_audit_daemon(self) -> None:
        """Release the daemon lock so the background thread can exit cleanly."""
        if self._audit_daemon is not None:
            self._audit_daemon._release_lock()
            self._audit_daemon = None

    def _cleanup(self) -> None:
        """Graceful cleanup on shutdown."""
        self._save_state()
        self._auto_save_conversation()
        self._stop_audit_daemon()
        if self.file_watcher and self.file_watcher.is_running:
            self.file_watcher.stop()
        self.mcp.close_all()

    def _auto_save_conversation(self) -> None:
        """Save the last N messages to a recovery file for SIGTERM protection."""
        try:
            recovery_dir = data_path()
            recovery_dir.mkdir(parents=True, exist_ok=True)
            recovery_file = recovery_dir / "recovery.json"

            msgs = self.context.get_messages()
            if len(msgs) <= 1:
                return

            keep = [msgs[0]] + msgs[-10:]
            recovery_file.write_text(
                json.dumps(keep, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception:
            get_logger().warning("Auto-save conversation failed", exc_info=True)

    def _handle_signal(self, signum: int, frame: Any) -> None:
        if signum == signal.SIGINT:
            now = time.time()
            # Double-tap SIGINT within 2 seconds → force exit
            if self._stop_requested and (now - self._first_sigint_at) < 2.0:
                console.print("\n[dim]Exiting...[/dim]")
                self._running = False
                self._cleanup()
                sys.exit(0)
            # First SIGINT → request stop of current operation
            self._stop_requested = True
            self._first_sigint_at = now
        elif signum == signal.SIGTERM:
            self._running = False
            self._cleanup()
            sys.exit(0)
