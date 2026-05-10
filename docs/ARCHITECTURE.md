# LuckyD Code — Architecture Deep Dive

> This document explains how LuckyD Code works internally. It's the reference for contributors, power users, and anyone who wants to extend the system.

---

## Table of Contents

1. [High-Level Overview](#high-level-overview)
2. [Entry Points](#entry-points)
3. [The Agent Loop](#the-agent-loop)
4. [Model Router](#model-router)
5. [Tool Registry](#tool-registry)
6. [Memory System](#memory-system)
7. [Context Management](#context-management)
8. [Orchestrator & Sub-Agents](#orchestrator--sub-agents)
9. [Retry & Error Handling](#retry--error-handling)
10. [Web UI Architecture](#web-ui-architecture)
11. [Plugin System](#plugin-system)
12. [Data Directory Layout](#data-directory-layout)
13. [Adding a New Tool](#adding-a-new-tool)
14. [Adding a New CLI Command](#adding-a-new-cli-command)

---

## High-Level Overview

```
User Input (CLI or Web UI)
        │
        ▼
  ┌─────────────┐
  │   Router    │  ← classify_tier() picks model tier 1–4
  └──────┬──────┘
         │ model selected
         ▼
  ┌─────────────────────────────────────────┐
  │            Agent Loop                   │
  │  THINK → ACT → VERIFY → RECOVER        │
  │                                         │
  │  • Stuck-loop detection                 │
  │  • Parallel tool execution              │
  │  • Mid-loop model escalation            │
  │  • Context overflow protection          │
  │  • Memory auto-save every turn          │
  └────────────┬────────────────────────────┘
               │ tool calls
               ▼
  ┌─────────────────────┐
  │    Tool Registry    │  ← 40+ tools: Read, Write, Bash, Git, Browser, Web…
  └─────────────────────┘
               │
               ▼
  ┌─────────────────────┐
  │   Memory System     │  ← project + cross-project persistent memories
  └─────────────────────┘
```

LuckyD Code is a **single-binary, multi-interface AI coding assistant** powered by DeepSeek. Both the CLI and Web UI share the same agent loop, tool registry, and memory system — no divergence between interfaces.

---

## Entry Points

| Entry Point | File | Description |
|---|---|---|
| `luckyd-code` / `ldc` | `cli_entry.py` | pip-installed CLI shim |
| `python main.py` | `main.py` | Direct source run |
| `python main.py --web` | `web_app.py` | FastAPI web server |
| `LuckyD Code.bat` | Desktop `.bat` | Windows launcher |

`cli_entry.py` calls `cli.py`, which sets up the REPL, loads config, and feeds messages into the agent loop. The Web UI (`web_app.py`) exposes WebSocket endpoints that drive the same loop from the browser.

---

## The Agent Loop

**File:** `luckyd_code/_agent_loop.py`

The agent loop is the core execution harness. Every request — CLI or Web — runs through it.

### Architecture

```
run_agent_loop()
    │
    ├── [pre-turn] context overflow check → auto-compact if >85% of budget
    ├── [pre-turn] turn budget injection  → warn model when ≤2 turns remain
    │
    └── for turn in range(max_turns):
            │
            ├── _stream_turn()          ← one model API call (streaming)
            │       ├── event: "text"       → streamed to on_text callback
            │       ├── event: "tool_calls" → pass to tool execution
            │       ├── event: "done"       → final text, loop ends
            │       └── event: "error"      → return error string
            │
            ├── if tool_calls:
            │       ├── stuck-loop detection (hash of tool batch × _STUCK_WINDOW)
            │       ├── _execute_tool_calls_parallel()
            │       │       ├── read-only tools → ThreadPoolExecutor (max 4)
            │       │       └── write tools     → sequential (race prevention)
            │       ├── re-read-after-write verification
            │       └── _verify_and_recover()  ← syntax/lint/test check
            │               └── on failure: escalate model + retry
            │
            └── if no tool_calls: agent is done → break
```

### Key Tunables (top of `_agent_loop.py`)

| Constant | Default | Purpose |
|---|---|---|
| `_MAX_VERIFY_RETRIES` | 3 | Max verify-retry cycles before giving up |
| `_MAX_PARALLEL_TOOLS` | 4 | Max concurrent read-only tool threads |
| `_MAX_TOOL_RESULT_CHARS` | 8,000 | Truncation cap for tool results |
| `_STUCK_WINDOW` | 3 | Identical tool-call hashes in a row = stuck |
| `_TURN_BUDGET_WARN` | 2 | Inject budget warning when ≤ N turns remain |

### Stuck-Loop Detection

Before each tool batch executes, a MD5 hash of `(tool_name, arguments)` for every call in the batch is computed. If the same hash appears `_STUCK_WINDOW` times consecutively, the loop breaks and injects a message asking the model to explain what's blocking it rather than burning all remaining turns.

### Model Escalation

When `verify_edits=True` and verification keeps failing, the loop automatically promotes to the next model in `_ESCALATION_LADDER` (defined from `model_registry.ALL_MODELS_FLAT`). The escalation is recorded in `LoopResult.escalated_model` for observability.

### RunConfig

All loop behaviour is controlled via `RunConfig`:

```python
from luckyd_code._agent_loop import RunConfig

rc = RunConfig(
    max_turns=15,
    verify_edits=True,       # run verify pipeline after file writes
    run_tests=True,          # include pytest in verify pipeline
    on_text=print,           # stream text chunks to stdout
    on_tool_start=...,       # called before each tool runs
    on_tool_end=...,         # called after each tool runs
    auto_save_memory=True,   # persist conversation summaries each turn
)
```

---

## Model Router

**File:** `luckyd_code/router.py`

The router classifies every prompt into one of 4 tiers and selects the appropriate DeepSeek model.

### Tiers

| Tier | Model | Use Case |
|---|---|---|
| 1 | `deepseek-v4-flash` | Simple chat, quick Q&A |
| 2 | `deepseek-v4-flash` | General coding, explanations |
| 3 | `deepseek-v4-pro` | Debugging, architecture, complex analysis |
| 4 | `deepseek-v4-pro` | Large refactors, security audits, migrations |

### Classification Pipeline

```
classify_tier(user_text)
    │
    ├── 1. Check _HEAVY_KEYWORDS    → tier 4 if matched
    ├── 2. Check _REASONER_KEYWORDS → tier 3 if matched
    ├── 3. Check _REASONER_PATTERNS → tier 3 if matched (regex)
    ├── 4. Check referenced files   → tier by line count (>500 = tier 4)
    ├── 5. Prompt length + code density heuristics
    └── 6. Default: tier 1
```

There's also `classify_tier_llm()` which submits an LLM classification call in a background thread. The main thread always returns the heuristic result immediately (`_LLM_CLASSIFY_TIMEOUT = 0.01s`) — the LLM result is written to an in-process cache (`_tier_cache`) for future identical prompts. This means zero latency on the hot path with improved accuracy on repeats.

### Mid-Conversation Escalation

As tool calls accumulate during a session, `escalate_tier()` is called:
- `≥ 2` tool calls → tier escalates by +1
- `≥ 8` tool calls → tier escalates by +2

This ensures complex multi-step tasks automatically get stronger models as they grow.

---

## Tool Registry

**File:** `luckyd_code/tools/registry.py` and `luckyd_code/tools/__init__.py`

The `ToolRegistry` is a dict-like container of `Tool` objects. It handles registration, dispatch, and result caching.

### Caching

Read-only tools (`Read`, `Glob`, `Grep`, `WebFetch`, `WebSearch`, `DateTime`) cache their results for 5 minutes by default. The cache key is `tool_name + sorted(arguments)`. Write/Bash/Git tools are excluded. Invalidate with `registry.invalidate()`.

### Built-in Tool Categories

| Category | Tools |
|---|---|
| File I/O | Read, Write, Edit, Glob, Grep |
| Shell | Bash |
| Web | WebFetch, WebSearch |
| Browser | Navigate, Click, Type, Snapshot, Screenshot, Evaluate, Close, OpenInBrowser, State, Emulate, Intercept, Trace, ToggleHeadless |
| Git | Status, Diff, Log, Commit, Add, Branch, PR, Push, Worktree |
| Agents | SubAgent, AgentHandoff |
| Brain | BrainSearch, BrainStatus |
| Generators | GameGen, ProjectGen, ReadmeGen, DockerfileGen |
| Media | YouTubePlaylist |
| Utility | DateTime |

### Dry-Run Mode

`WriteTool` and `EditTool` accept `dry_run=true`. When set, they return a unified diff of the proposed change without touching the file. Useful for previewing edits before committing.

---

## Memory System

**File:** `luckyd_code/memory/manager.py`

The memory system provides two scopes: **project memory** (scoped to one repo) and **user memory** (cross-project, lives in `~/.luckyd_code/`).

### Project Memory (`MemoryManager`)

```
~/.luckyd_code_data/
└── projects/
    └── <project-name>/
        └── memory/
            ├── MEMORY.md           ← index of all memories
            ├── general_<name>.md   ← general memories
            ├── session_<name>.md   ← auto-saved session summaries
            ├── technical_<name>.md ← technical facts
            └── session_log.md      ← rolling append log
```

Each memory file has a metadata header:
```
<!-- importance:7 saved:1746000000 accessed:1746001000 count:3 -->
```

### Search Strategy

1. **Semantic search** (when `sentence-transformers` is installed via `pip install luckyd-code[rag]`): uses `all-MiniLM-L6-v2` embeddings with cosine similarity. The model is a lazy-loaded singleton — 1–3s on first use, then cached in memory.
2. **Keyword fallback** (always available): frequency-based scoring across memory files.

### Memory Injection

At the start of every agent loop turn, `get_relevant_memories()` searches for memories relevant to the current user message and injects them as a `<memories>` block before the model sees the request. This gives the agent continuity across sessions without any user action.

### Decay

`MemoryManager.decay(max_days=30, importance_threshold=3)` archives memories that haven't been accessed in 30 days and have importance ≤ 3. Call it periodically to keep the memory directory from growing unbounded.

---

## Context Management

**File:** `luckyd_code/context.py`

`ConversationContext` manages the message list sent to the DeepSeek API.

### Token Counting

Uses `tiktoken` (cl100k_base) with a **15% safety multiplier** to account for the difference between OpenAI's tokenizer and DeepSeek's vocabulary. Falls back to a character-based heuristic if tiktoken is unavailable.

### Auto-Compaction

When estimated tokens exceed `_token_compact_threshold` (800K by default — leaving 200K headroom in DeepSeek's 1M context window), `compact()` is triggered automatically. It:

1. Summarizes all messages except the last `keep_last=8` using `deepseek-v4-flash`
2. Replaces compacted messages with a `[Compacted conversation summary]` system message
3. Drops orphaned `role=tool` messages whose parent `tool_call_id` is no longer present (required for API correctness)

### Orphaned Tool Message Cleanup

DeepSeek's API requires every `role=tool` message to have a preceding assistant message containing a matching `tool_call_id`. After compaction, this invariant can break. `_drop_orphaned_tool_messages()` enforces it automatically.

---

## Orchestrator & Sub-Agents

**File:** `luckyd_code/orchestrator.py`, `luckyd_code/agent.py`

### Sub-Agents

`SubAgent` is a lightweight, ephemeral agent with its own `ConversationContext`. It shares the tool registry but has no memory persistence (`auto_save_memory=False`) to avoid contaminating the parent session's memory.

```python
from luckyd_code.agent import SubAgent

agent = SubAgent(config, task="Summarize all TODOs in the codebase")
result = agent.run()
```

### Orchestrator

`Coordinator.orchestrate()` runs a Researcher → Coder → Reviewer pipeline. Research and testing phases run **in parallel** via `ThreadPoolExecutor`:

```
Phase 1 (parallel): researcher + tester
Phase 2 (sequential): coder (receives research context, truncated to 1500 tokens)
Phase 3 (sequential): reviewer (receives implementation output)
```

Each agent gets a role-specific system prompt from `ROLE_PROMPTS`. The parallel thread pool is capped at `_MAX_PARALLEL_WORKERS = 4` to prevent unbounded concurrent API calls.

`Coordinator.parallel_orchestrate()` lets you define arbitrary `(role, subtask)` pairs and runs them all concurrently — useful for tasks like "write tests for module A, B, and C simultaneously."

---

## Retry & Error Handling

**File:** `luckyd_code/retry.py`, `luckyd_code/exceptions.py`

The `@with_retry` decorator provides exponential backoff with jitter:

```python
@with_retry(max_retries=3, base_delay=1.0, max_delay=30.0, jitter=True)
def my_api_call():
    ...
```

Error classification:
- `RetryableError` → retried up to `max_retries` times (rate limits, 5xx)
- `NonRetryableError` → raised immediately (auth errors, 4xx client errors)
- `ModelNotFoundError` → raised immediately (triggers model fallback in the router)
- Unclassified exceptions → retried once, then re-raised

In `api.py`, `stream_chat` wraps `_stream_chat_raw` with `_call_with_retry()` (3 attempts, 1s base, 30s cap). Rate-limit (429) and server errors (5xx) are retried; auth errors and bad requests are not.

---

## Web UI Architecture

**File:** `luckyd_code/web_app.py`, `luckyd_code/web_routes/`

The Web UI is a FastAPI application that serves:
- Static HTML/JS/CSS from `luckyd_code/templates/`
- A WebSocket endpoint at `/ws` that streams agent responses in real-time
- REST endpoints for memory management, cost tracking, session management, and settings

The WebSocket protocol mirrors the CLI streaming model — the same `run_agent_loop()` is called with `on_text` set to a WebSocket send callback.

Rate limiting is per-IP (configurable). Bearer token auth is supported for production deployments.

---

## Plugin System

**File:** `luckyd_code/plugins.py`

Drop a Python file into `~/.claude/plugins/` (or the configured plugins directory). The file must define a `register(registry: ToolRegistry)` function. LuckyD Code loads all plugins at startup via `load_all_plugins(registry)`.

Example plugin:
```python
# ~/.claude/plugins/my_tool.py
from luckyd_code.tools.registry import Tool, ToolRegistry

class MyTool(Tool):
    name = "MyTool"
    description = "Does something custom"

    def execute(self, **kwargs) -> str:
        return "hello from my plugin!"

def register(registry: ToolRegistry):
    registry.register(MyTool())
```

---

## Data Directory Layout

```
~/.luckyd_code_data/          ← all persistent data lives here
├── projects/
│   └── <project-name>/
│       ├── memory/           ← project-scoped memories
│       │   ├── MEMORY.md
│       │   ├── general_*.md
│       │   └── session_log.md
│       └── costs.jsonl       ← append-only cost log
├── user_memory/              ← cross-project user memory
└── sessions/                 ← saved conversation sessions
```

The data directory is resolved by `luckyd_code/_data_dir.py` using `platformdirs` (respects XDG on Linux, `AppData` on Windows, `~/Library` on macOS).

---

## Adding a New Tool

1. Create a file in `luckyd_code/tools/` (e.g. `my_tool.py`):

```python
from .registry import Tool

class MyTool(Tool):
    name = "MyTool"
    description = "One sentence describing what this tool does."
    parameters = {
        "type": "object",
        "properties": {
            "input": {"type": "string", "description": "The input text."}
        },
        "required": ["input"],
    }

    def execute(self, input: str) -> str:
        return f"processed: {input}"
```

2. Import and register it in `luckyd_code/tools/__init__.py`:

```python
from .my_tool import MyTool

# In get_default_registry():
registry.register(MyTool())
```

3. Add it to `__all__` in `__init__.py`.

4. Write tests in `tests/test_my_tool.py`.

> **Caching:** If your tool is read-only, add its name to the `_READ_ONLY_TOOLS` set in `registry.py` to enable automatic 5-minute result caching.

---

## Adding a New CLI Command

CLI commands live in `luckyd_code/cli_commands/`. Each command is a function that takes `(args: list[str], context: ConversationContext, config: Config) -> str`.

1. Add your function to the appropriate file (or create a new one).
2. Register it in `luckyd_code/cli.py` in the command dispatch table.
3. Add a help entry to `/help` output in `luckyd_code/cli_utils.py`.

---

*Last updated: May 2026 — LuckyD Code v1.2.2*
