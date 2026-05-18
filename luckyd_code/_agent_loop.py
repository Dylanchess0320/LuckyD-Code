"""Enhanced agentic execution loop — top-1% harness.

Architecture:
  1. THINK   — Model reasons; context-overflow protection runs before every turn
  2. ACT     — Execute tool calls (parallel where possible, results truncated)
  3. VERIFY  — Syntax → Lint → Test check on any written files
  4. RECOVER — If verification fails, feed error back and retry (up to N times);
               model escalates to a stronger tier after repeated failures

Improvements over the previous version:
  - Stuck-loop detection (same tool+args repeated → inject nudge and break)
  - Turn budget injection (model warned when ≤ 2 turns remain)
  - Mid-loop model escalation on repeated verify failures
  - Tool result truncation (large outputs capped before context injection)
  - Re-read-after-write (file existence + size verified after Write/Edit)
  - Context-overflow protection (auto-compact when token budget exceeded)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Protocol

from .api import stream_chat, _repair_json
from .context import ConversationContext
from .memory.manager import MemoryManager
from .memory.user import get_user_memory, UserMemory
from .model_registry import ALL_MODELS_FLAT as _ALL_MODELS_FLAT_ESC

_log = logging.getLogger(__name__)

__all__ = ["run_agent_loop", "RunConfig", "LoopResult"]


class _AgentConfig(Protocol):
    """Structural type for the Config object consumed by the agent loop.

    Using a Protocol instead of importing Config directly avoids a circular
    import (Config → context → _agent_loop → Config).
    """

    api_key: str
    base_url: str
    model: str
    max_tokens: int
    temperature: float
    system_prompt: str


class ToolRegistryProtocol(Protocol):
    """Structural type for a ToolRegistry consumed by the agent loop.

    Avoids importing the concrete ToolRegistry (which pulls in every tool
    module) and makes the dependency explicit and mockable in tests.
    """

    def execute(self, name: str, args: dict[str, Any]) -> str: ...
    def list_tools(self) -> list[dict[str, Any]]: ...

# ── tunables ──────────────────────────────────────────────────────────────────
_MAX_VERIFY_RETRIES     = 1       # verify-retry cycles before giving up
_MAX_PARALLEL_TOOLS     = 4       # max concurrent read-only tool threads
_MAX_TOOL_RESULT_CHARS  = 4_000   # truncate tool results longer than this
_STUCK_WINDOW           = 3       # identical tool-call hashes in a row = stuck
_TURN_BUDGET_WARN       = 3       # inject budget warning when ≤ N turns remain
# Model escalation ladder — used when verify keeps failing.
# Derived from model_registry models ordered by capability (cheapest first).
_ESCALATION_LADDER = [m.id for m in _ALL_MODELS_FLAT_ESC]


# ── config / result ────────────────────────────────────────────────────────────

class RunConfig:
    """Configuration for an agent loop run."""

    __slots__ = (
        "max_turns", "label", "verify_edits", "max_verify_retries",
        "run_tests", "test_runner_cmd", "project_root",
        "on_text", "on_tool_start", "on_tool_end",
        "on_verify",
        "auto_save_memory",   # auto-save conversation memories each turn
        "memory_manager",     # optional MemoryManager for auto-save
        "user_memory",        # optional UserMemory for cross-project recall
    )

    def __init__(
        self,
        max_turns: int = 8,
        label: str = "agent",
        verify_edits: bool = False,
        max_verify_retries: int = _MAX_VERIFY_RETRIES,
        run_tests: bool = False,
        test_runner_cmd: str | None = None,
        project_root: str = "",
        on_text: Callable[[str], None] | None = None,
        on_tool_start: Callable[[str, int, int], None] | None = None,
        on_tool_end: Callable[[str, str], None] | None = None,
        on_verify: Callable[[str], None] | None = None,
        auto_save_memory: bool = True,
    ) -> None:
        self.max_turns           = max_turns
        self.label               = label
        self.verify_edits        = verify_edits
        self.max_verify_retries  = max_verify_retries
        self.run_tests           = run_tests
        self.test_runner_cmd     = test_runner_cmd
        self.project_root        = project_root
        self.on_text             = on_text
        self.on_tool_start       = on_tool_start
        self.on_tool_end         = on_tool_end
        self.on_verify           = on_verify
        self.auto_save_memory    = auto_save_memory
        self.memory_manager: MemoryManager | None = None
        self.user_memory: UserMemory | None = None


class LoopResult:
    """Result from an agent loop run."""

    __slots__ = ("text", "tool_calls_executed", "files_modified",
                 "verification_passed", "escalated_model")

    def __init__(self):
        self.text: str = ""
        self.tool_calls_executed: int = 0
        self.files_modified: list[str] = []
        self.verification_passed: bool = True
        self.escalated_model: str | None = None


# ── helpers ───────────────────────────────────────────────────────────────────

def _truncate_tool_result(result: str) -> str:
    """Cap a tool result at _MAX_TOOL_RESULT_CHARS to protect context budget."""
    if len(result) <= _MAX_TOOL_RESULT_CHARS:
        return result
    head = result[:_MAX_TOOL_RESULT_CHARS // 2]
    tail = result[-(_MAX_TOOL_RESULT_CHARS // 4):]
    trimmed = len(result) - len(head) - len(tail)
    return (
        f"{head}\n\n"
        f"[... {trimmed:,} characters trimmed — output too large ...]\n\n"
        f"{tail}"
    )


def _tool_call_hash(tc: dict[str, Any]) -> str:
    """Stable hash of (tool_name, arguments) for stuck detection."""
    name = tc.get("function", {}).get("name", "")
    args = tc.get("function", {}).get("arguments", "")
    return hashlib.md5(f"{name}:{args}".encode("utf-8")).hexdigest()


def _verify_write(file_path: str) -> str | None:
    """Confirm a write actually landed — return error string or None if ok."""
    try:
        stat = os.stat(file_path)
        if stat.st_size == 0:
            return f"Write produced an empty file: {file_path}"
        return None
    except FileNotFoundError:
        return f"Write failed — file not found after write: {file_path}"
    except OSError as e:
        return f"Could not verify write for {file_path}: {e}"


def _escalate_model(current_model: str) -> str | None:
    """Return the next model up the escalation ladder, or None if at the top."""
    try:
        idx = _ESCALATION_LADDER.index(current_model)
        if idx + 1 < len(_ESCALATION_LADDER):
            return _ESCALATION_LADDER[idx + 1]
    except ValueError:
        pass
    return None


# ── parallel tool execution ───────────────────────────────────────────────────

def _ingest_tool_result(
    name: str,
    result: str,
    args: dict[str, Any],
    tc_id: str,
    context: ConversationContext,
    modified_files: list[str],
) -> None:
    """Truncate, store, and post-validate a single tool result."""
    truncated = _truncate_tool_result(result)
    context.add_tool_result(
        tool_call_id=tc_id, tool_name=name, result=truncated,
    )
    if name in ("Write", "Edit"):
        fp = args.get("file_path") or args.get("path", "")
        if fp:
            modified_files.append(fp)
            err = _verify_write(fp)
            if err:
                context.add_user_message(
                    f"⚠️  Write verification failed: {err}\n"
                    "Please retry the write operation."
                )


def _execute_tool_calls_parallel(
    pending_tool_calls: list[dict[str, Any]],
    registry: ToolRegistryProtocol,
    context: ConversationContext,
    on_start: Callable[[str, int, int], None] | None = None,
    on_end: Callable[[str, str], None] | None = None,
) -> list[str]:
    """Execute tool calls, parallelising independent read-only ones.

    Write-conflict tools run sequentially to prevent race conditions.
    All tool results are truncated before being added to the context.
    Write/Edit results trigger a re-read-after-write check.
    """
    WRITE_CONFLICT_TOOLS = {"Write", "Edit", "Bash", "GitCommit", "GitPush", "GitAdd"}
    modified_files: list[str] = []
    total = len(pending_tool_calls)

    def _run_one(tc: dict[str, Any], idx: int) -> tuple[int, str, str, dict[str, Any]]:
        """Execute a single tool call. Returns (orig_idx, name, result, args)."""
        name = tc["function"]["name"]
        raw_args = tc["function"]["arguments"]
        try:
            args = json.loads(_repair_json(raw_args)) if raw_args else {}
        except json.JSONDecodeError:
            return idx, name, f"Error: invalid JSON in tool arguments: {raw_args[:200]}", {}
        if on_start:
            on_start(name, idx + 1, total)
        result = registry.execute(name, args)
        if on_end:
            on_end(name, result)
        return idx, name, result, args

    # Separate into parallel (read-only) and sequential (write) groups
    parallel_group: list[tuple[int, dict[str, Any]]] = []
    sequential_group: list[tuple[int, dict[str, Any]]] = []
    for i, tc in enumerate(pending_tool_calls):
        name = tc["function"]["name"]
        if name in WRITE_CONFLICT_TOOLS:
            sequential_group.append((i, tc))
        else:
            parallel_group.append((i, tc))

    # Run read-only tools in parallel
    if parallel_group:
        with ThreadPoolExecutor(max_workers=min(len(parallel_group), _MAX_PARALLEL_TOOLS)) as ex:
            futures = {
                ex.submit(_run_one, tc, orig_idx): orig_idx
                for orig_idx, tc in parallel_group
            }
            for future in as_completed(futures):
                try:
                    orig_idx, name, result, args = future.result()
                    _ingest_tool_result(
                        name, result, args,
                        pending_tool_calls[orig_idx]["id"],
                        context, modified_files,
                    )
                except Exception as e:
                    _log.warning("Parallel tool execution failed: %s", e)

    # Run write-conflict tools sequentially
    for orig_idx, tc in sequential_group:
        _, name, result, args = _run_one(tc, orig_idx)
        _ingest_tool_result(
            name, result, args, tc["id"],
            context, modified_files,
        )

    return modified_files


# ── verification / recovery ───────────────────────────────────────────────────

def _check_files_verification(  # pragma: no cover
    files_modified: list[str],
    run_cfg: RunConfig,
    context: ConversationContext,
) -> tuple[bool, list[str]]:
    """Run the verify pipeline on each modified file.

    Returns (all_passed, failed_files).
    Split out of _verify_and_recover to lower its cyclomatic complexity.
    """
    from .verify import run_verify_pipeline, pipeline_all_passed, pipeline_feedback

    all_passed = True
    failed_files: list[str] = []

    for fp in files_modified:
        results = run_verify_pipeline(
            file_path=fp,
            project_root=run_cfg.project_root,
            run_lint=False,
            run_consistency=True,
            run_tests=run_cfg.run_tests,
            test_runner_cmd=run_cfg.test_runner_cmd,
        )
        feedback = pipeline_feedback(results)
        if run_cfg.on_verify:
            run_cfg.on_verify(feedback)
        if not pipeline_all_passed(results):
            all_passed = False
            failed_files.append(fp)
            context.add_user_message(
                f"Verification failed for {fp}:\n\n{feedback}\n\n"
                "Please fix the issues and try again."
            )

    return all_passed, failed_files


def _verify_and_recover(  # pragma: no cover
    context: ConversationContext,
    config: _AgentConfig,
    tools: list[dict[str, Any]],
    active_model: str,
    files_modified: list[str],
    run_cfg: RunConfig,
    registry: ToolRegistryProtocol | None = None,
) -> tuple[bool, str]:
    """Run verification on modified files and retry on failure.

    Returns (passed, active_model) — the model may have been escalated
    during recovery attempts.
    """
    if not run_cfg.verify_edits or not files_modified:
        return True, active_model
    if registry is None:
        return True, active_model

    for retry in range(run_cfg.max_verify_retries + 1):
        all_passed, failed_files = _check_files_verification(
            files_modified, run_cfg, context,
        )

        if all_passed:
            return True, active_model

        if retry >= run_cfg.max_verify_retries:
            _log.warning(
                "Verification still failing after %d retries for: %s",
                run_cfg.max_verify_retries, failed_files,
            )
            return False, active_model

        # Mid-loop model escalation — try a stronger model on retry
        escalated = _escalate_model(active_model)
        if escalated and escalated != active_model:
            active_model = escalated
            _log.info("Escalating to %s for verify-recovery retry %d", active_model, retry + 1)
            context.add_user_message(
                f"[System: escalating to {active_model} for better recovery]"
            )

        _log.info("Verification retry %d/%d for: %s",
                  retry + 1, run_cfg.max_verify_retries, failed_files)

        turn_text, pending_tool_calls, tool_reasoning, error = _stream_turn(
            context.get_messages(), tools, active_model, config, run_cfg,
        )
        if error:
            _log.error("Verify-recover stream error: %s", error)
            return False, active_model

        if pending_tool_calls:
            context.add_assistant_message(
                turn_text or None,
                tool_calls=pending_tool_calls,
                reasoning_content=tool_reasoning or None,
            )
            new_modified = _execute_tool_calls_parallel(
                pending_tool_calls, registry=registry, context=context,
            )
            files_modified.extend(new_modified)
            continue
        else:
            context.add_assistant_message(content=turn_text)
            break

    return False, active_model


# ── helpers for the main loop ─────────────────────────────────────────────────

def _context_text_for_memory(context: ConversationContext) -> str:
    """Extract a short text summary from the context for memory matching."""
    messages = context.get_messages()
    # Use the last user message as the primary search key
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, list):
                # Multimodal — take just the text part
                text_parts = [p.get("text", "") for p in content if p.get("type") == "text"]
                return " ".join(text_parts)[:500]
            return str(content)[:500]
    return ""


def _auto_save_turn_memory(
    mm: MemoryManager,
    um: UserMemory | None,
    context: ConversationContext,
    turn: int,
    max_turns: int,
) -> None:
    """Save a compact memory of what happened this turn.

    Project memory: save a rolling session summary.
    User memory: save key learnings on every 5th turn.
    """
    # Save session memory every turn (will overwrite latest_summary)
    messages = context.get_messages()
    recent = messages[-4:]  # last 2 exchanges (user + assistant)
    summary_parts = []
    for m in recent:
        role = m.get("role", "?")
        content = m.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                p.get("text", "") for p in content if p.get("type") == "text"
            )
        content_str = str(content)[:300]
        summary_parts.append(f"[{role}] {content_str}")

    mm.save_conversation_summary(
        "\n".join(summary_parts),
        turn_count=turn + 1,
    )

    # Every 5 turns, save a distilled fact to user memory
    if um and (turn + 1) % 5 == 0:
        user_msg = _context_text_for_memory(context)
        if user_msg:
            # Save a lightweight fact the user memory can recall later
            um.save(
                f"session_{turn + 1}of{max_turns}",
                content=f"Turn {turn + 1}/{max_turns} — context: {user_msg[:200]}",
                importance=3,  # moderate importance
            )


def _stream_turn(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    active_model: str,
    config: _AgentConfig,
    rc: RunConfig,
) -> tuple[str, list[dict[str, Any]] | None, str, str | None]:
    """Stream one model turn. Returns (turn_text, pending_tool_calls, tool_reasoning, error_msg)."""
    pending_tool_calls = None
    tool_reasoning = ""
    turn_text = ""

    for event_type, data in stream_chat(
        messages=messages,
        tools=tools,
        model=active_model,
        api_key=config.api_key,
        base_url=config.base_url,
        max_tokens=config.max_tokens,
        temperature=config.temperature,
    ):
        if event_type == "text":
            turn_text += data
            if rc.on_text:
                rc.on_text(data)
        elif event_type == "done":
            # data is (content, reasoning) — capture both
            turn_text, tool_reasoning = data[0], data[1]
        elif event_type == "tool_calls":
            pending_tool_calls, tool_reasoning = data
        elif event_type in ("error", "model_not_found"):
            return "", None, "", f"[{rc.label}] Error: {data}"

    return turn_text, pending_tool_calls, tool_reasoning, None


def _process_tool_calls_turn(
    pending_tool_calls: list[dict[str, Any]],
    turn_text: str,
    tool_reasoning: str,
    context: ConversationContext,
    registry: ToolRegistryProtocol,
    config: _AgentConfig,
    tools: list[dict[str, Any]],
    active_model: str,
    rc: RunConfig,
    result: LoopResult,
    recent_hashes: deque[str],
) -> tuple[bool, str]:
    """Handle tool calls: stuck detection, execution, verification.

    Returns (should_break, active_model).
    """
    # Stuck-loop detection
    batch_hash = hashlib.md5(
        "|".join(_tool_call_hash(tc) for tc in pending_tool_calls).encode()
    ).hexdigest()

    if list(recent_hashes).count(batch_hash) >= _STUCK_WINDOW - 1:
        _log.warning("[%s] Stuck loop detected — same tool batch repeated %d times",
                     rc.label, _STUCK_WINDOW)
        context.add_assistant_message(
            turn_text or None,
            tool_calls=pending_tool_calls,
            reasoning_content=tool_reasoning or None,
        )
        _execute_tool_calls_parallel(
            pending_tool_calls, registry, context,
            on_start=rc.on_tool_start, on_end=rc.on_tool_end,
        )
        context.add_user_message(
            "You appear to be stuck in a loop repeating the same tool calls. "
            "Stop and explain what you have accomplished so far, what is "
            "blocking you, and what the user should do next."
        )
        return True, active_model

    recent_hashes.append(batch_hash)

    context.add_assistant_message(
        turn_text or None,
        tool_calls=pending_tool_calls,
        reasoning_content=tool_reasoning or None,
    )

    modified = _execute_tool_calls_parallel(
        pending_tool_calls, registry, context,
        on_start=rc.on_tool_start,
        on_end=rc.on_tool_end,
    )
    result.tool_calls_executed += len(pending_tool_calls)
    result.files_modified.extend(modified)

    # Verification gate after file writes
    if modified and rc.verify_edits:
        passed, active_model = _verify_and_recover(
            context, config, tools, active_model, modified, rc, registry,
        )
        if not passed:
            result.verification_passed = False
        if active_model != config.model:
            result.escalated_model = active_model

    return False, active_model


# ── main loop ─────────────────────────────────────────────────────────────────

def run_agent_loop(
    context: ConversationContext,
    config: _AgentConfig,
    tools: list[dict[str, Any]],
    registry: ToolRegistryProtocol,
    max_turns: int = 10,
    label: str = "agent",
    on_text: Callable[[str], None] | None = None,
    run_config: RunConfig | None = None,
) -> str:
    """Run the agentic loop with verification and recovery.

    Improvements active in this version:
      ✓ Stuck-loop detection breaks infinite tool-call cycles
      ✓ Turn budget injected when ≤ 2 turns remain
      ✓ Model escalates to stronger tier on repeated verify failures
      ✓ Tool results truncated to protect context window
      ✓ Re-read-after-write confirms writes landed
      ✓ Context auto-compacted mid-loop if token budget exceeded

    Args:
        context:    Conversation context (pre-loaded with user message).
        config:     App config (api_key, base_url, model, etc.).
        tools:      OpenAI-format tool schemas.
        registry:   ToolRegistry instance.
        max_turns:  Max tool-call iterations before stopping.
        label:      Human label for this agent (e.g. "researcher", "coder").
        on_text:    Optional callback for streamed text chunks.
        run_config: Optional RunConfig for verification settings.

    Returns:
        Final text response from the agent.
    """
    rc = run_config or RunConfig(label=label, max_turns=max_turns, on_text=on_text)
    result = LoopResult()

    # ── memory persistence: init managers if auto-save is on ──────────────
    if rc.auto_save_memory:
        try:
            rc.memory_manager = MemoryManager(rc.project_root or os.getcwd())
        except Exception:
            _log.warning("MemoryManager init failed", exc_info=True)
        try:
            rc.user_memory = get_user_memory()
        except Exception:
            _log.warning("UserMemory init failed", exc_info=True)

        # Inject relevant project memories into the first turn
        try:
            if rc.memory_manager:
                relevant = rc.memory_manager.get_relevant_memories(
                    _context_text_for_memory(context), k=1,
                )
                if relevant and relevant != "<memories>\n</memories>":
                    context.add_user_message(
                        f"[System: relevant project memories]\n\n{relevant}"
                    )
        except Exception:
            _log.warning("Memory injection failed", exc_info=True)

        # Inject relevant cross-project user memories
        try:
            if rc.user_memory:
                user_relevant = rc.user_memory.get_relevant(
                    _context_text_for_memory(context), k=1,
                )
                if user_relevant and "<memory name=" in user_relevant:
                    context.add_user_message(
                        f"[System: relevant user memories from past sessions]\n\n{user_relevant}"
                    )
        except Exception:
            _log.warning("User memory injection failed", exc_info=True)
    text_buffer = ""

    # The model we're currently using — may escalate during verify-recovery
    active_model: str = config.model

    # Stuck-loop detection: track hashes of recent tool-call batches
    recent_hashes: deque[str] = deque(maxlen=_STUCK_WINDOW)

    # Budget warning: only inject once to avoid duplicate messages
    _budget_warning_sent = False

    for turn in range(rc.max_turns):
        turns_remaining = rc.max_turns - turn

        # ── context-overflow protection ──────────────────────────────────────
        if context.estimate_tokens() > context.token_compact_threshold * 0.70:  # pragma: no cover
            _log.info("[%s] Context near limit — auto-compacting before turn %d",
                      rc.label, turn + 1)
            context.compact(config, keep_last=5)

        # ── turn budget warning ──────────────────────────────────────────────
        if turns_remaining <= _TURN_BUDGET_WARN and not _budget_warning_sent:
            context.add_user_message(
                f"[System: {turns_remaining} turn(s) remaining. "
                "Wrap up your work and return a final answer now.]"
            )
            _budget_warning_sent = True

        # ── stream one turn ──────────────────────────────────────────────────
        turn_text, pending_tool_calls, tool_reasoning, error = _stream_turn(
            context.get_messages(), tools, active_model, config, rc,
        )
        if error:
            return error

        # ── tool calls ───────────────────────────────────────────────────────
        if pending_tool_calls:
            should_break, active_model = _process_tool_calls_turn(
                pending_tool_calls, turn_text, tool_reasoning,
                context, registry, config, tools, active_model, rc, result,
                recent_hashes,
            )
            # ── memory auto-save after tool-call turn ──────────────────────────
            if rc.auto_save_memory and rc.memory_manager:
                try:
                    _auto_save_turn_memory(
                        rc.memory_manager, rc.user_memory,
                        context, turn, rc.max_turns,
                    )
                except Exception:
                    _log.warning("Memory auto-save failed", exc_info=True)
            if should_break:
                break
            continue

        # ── no tool calls → agent is done ────────────────────────────────────
        text_buffer = turn_text
        # ── memory auto-save on final turn ─────────────────────────────────────
        if rc.auto_save_memory and rc.memory_manager:
            try:
                _auto_save_turn_memory(
                    rc.memory_manager, rc.user_memory,
                    context, turn, rc.max_turns,
                )
            except Exception:
                _log.warning("Final memory auto-save failed", exc_info=True)
        break

    else:
        # for-loop ran to completion without a break — agent was still making
        # tool calls when the turn budget ran out.
        _log.warning("[%s] Hit max turns (%d) — agent still mid-task", rc.label, rc.max_turns)
        result.text = (
            text_buffer.strip()
            or f"({rc.label}: no response after {rc.max_turns} turns)"
        )
        result.text += (
            f"\n\n---\n"
            f"\u26a0\ufe0f  Reached the **{rc.max_turns}-turn limit**. "
            f"Type **continue** to keep going."
        )
        return result.text

    result.text = text_buffer.strip() or f"({rc.label}: no response)"
    return result.text
