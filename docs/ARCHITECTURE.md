# LuckyD Code — Architecture

This document describes the request lifecycle and module relationships for contributors and power users.

---

## High-level overview

```
User input (CLI or Browser)
       │
       ▼
  ┌─────────────────────────────────────────────────┐
  │              Entry points                        │
  │  cli.py / cli_entry.py  │  web_app.py (FastAPI)  │
  └───────────────┬─────────────────────────────────┘
                  │
       ┌──────────▼──────────┐
       │   router.py          │  ← classifies prompt → picks model tier
       │   (heuristic + LLM)  │
       └──────────┬──────────┘
                  │  model selected (T1-T4)
       ┌──────────▼──────────┐
       │   _agent_loop.py     │  ← shared Think → Act → Verify loop
       │   (CLI + Web + Subs) │
       └──────────┬──────────┘
          ┌───────┴──────────┐
          │                  │
   ┌──────▼──────┐   ┌───────▼──────┐
   │  api.py      │   │  tools/      │
   │  (stream_    │   │  registry.py │  ← 40 built-in tools
   │   chat SSE)  │   └─────────────┘
   └─────────────┘
```

---

## Request lifecycle (step by step)

### 1. User sends a message

**CLI path:** `cli.py` captures input via `prompt_toolkit`, attaches the active session and context, then calls `run_agent_loop()`.

**Web path:** `web_app.py` (FastAPI) receives a WebSocket message, decodes it, attaches the same session and context, then calls `run_agent_loop()`.

Both paths share a single `ConversationContext` object (`context.py`) that tracks messages and estimates token usage.

### 2. Model routing

`router.py` classifies the prompt into one of four tiers before the first API call:

| Tier | Model | When |
|------|-------|------|
| T1 | deepseek-v4-flash | Simple chat, one-liners |
| T2 | deepseek-v4-flash | General coding, explanations |
| T3 | deepseek-v4-pro | Debugging, architecture, complex analysis |
| T4 | deepseek-v4-pro | Large refactors, security audits |

The heuristic classifier returns in under 1 ms. An LLM classifier runs in a background thread (`ThreadPoolExecutor`) and caches results; if it doesn't respond within 400 ms the heuristic result is used instead.

### 3. Agent loop (`_agent_loop.py`)

The loop runs up to `max_turns` iterations:

```
for turn in range(max_turns):
    1. Context-overflow protection  (auto-compact if >70% of budget used)
    2. Turn-budget warning          (inject system message if ≤ 3 turns remain)
    3. stream_chat()                (Think — model reasons and optionally emits tool calls)
    4. If tool calls:
         a. Stuck-loop detection    (same batch repeated ≥ 3 times → break + explain)
         b. Parallel execution      (read-only tools in ThreadPoolExecutor, writes sequential)
         c. Re-read-after-write     (verify file exists + non-empty after Write/Edit)
         d. Verification gate       (syntax → consistency → test, if verify_edits=True)
         e. Model escalation        (promote to stronger tier on repeated verify failures)
    5. If no tool calls:            (Act complete — return final text)
         Memory auto-save
         break
```

### 4. Tool execution (`tools/`)

Tools are registered in `tools/registry.py` with a 5-minute TTL cache for read-only calls. The registry holds 40 tools across these categories:

- **File ops** — `Read`, `Write`, `Edit`, `Glob`, `Grep` (Write/Edit support `dry_run=True`)
- **Shell** — `Bash` (Docker-sandboxed), `DateTime`, `ShellDetect`
- **Web** — `WebFetch`, `WebSearch`, `BrowserNavigate`, …
- **Git** — `GitStatus`, `GitDiff`, `GitCommit`, `GitPush`, `GitPR`, `GitWorktree`, …
- **Brain** — `BrainSearch`, `BrainStatus`
- **Agent** — `SubAgent`, `AgentHandoff`
- **Generators** — `GameGen`, `ProjectGen`, `ReadmeGen`, `DockerfileGen`

### 5. Verification pipeline (`verify.py`)

After any `Write` or `Edit`, the pipeline runs:

1. **Syntax** — `py_compile.compile()` (always, mandatory)
2. **Lint** — `ruff` or `flake8` (optional, best-effort)
3. **Consistency** — AST checks: bare excepts, mutable defaults, circular imports
4. **Tests** — project test suite (optional, only if `run_tests=True`)

Failed stages feed an error message back into the agent context. If the same file keeps failing, the loop escalates to a stronger model tier.

### 6. Memory system (`memory/`)

Two layers of persistence:

- **Project memory** (`memory/manager.py`) — CLAUDE.md-style key-value store, scoped to the current project. Relevant memories are injected at the start of each agent run.
- **User memory** (`memory/user.py`) — cross-project long-term facts (e.g. preferred code style, working environment). Injected every 5 turns.

---

## Supporting subsystems

### Knowledge graph (`brain/`)

```
brain/
├── parser.py       AST-based file parser (classes, functions, imports, calls)
├── chunker.py      Splits files into semantic chunks for embedding
├── embedder.py     sentence-transformers or OpenAI embeddings (optional)
├── indexer.py      FAISS vector index with mtime-based staleness detection
├── retriever.py    RRF merge of vector + BM25 results, with graph fallback
├── graph.py        JSON knowledge graph (nodes: modules/classes/functions, edges: imports/calls)
├── assembler.py    Formats retrieved context for prompt injection
└── __init__.py     Exposes rebuild_project() and is_rag_available()
```

The graph is pre-seeded with 20 Python built-in symbols so `/brain search` returns useful results before the project has been indexed.

### Analytics (`analytics/`)

```
analytics/
├── scanner.py      Walks the project; scores health 0-100; detects 12 code smells
├── smells.py       Smell definitions (deep nesting, god functions, magic numbers, …)
├── trends.py       Snapshots health over time; compare any two points
└── reporter.py     Outputs terminal, Markdown, JSON, or HTML reports
```

### Orchestrator (`orchestrator.py`)

Runs a three-agent pipeline for complex tasks:
`Researcher → Coder → Reviewer`

Each agent is a `SubAgent` instance that shares the same `run_agent_loop()` harness. Parallel sub-tasks run in a capped `ThreadPoolExecutor` (max 4 workers).

### Autonomous fixer (`autonomous_fixer.py`)

Five-step self-repair pipeline triggered by unhandled exceptions:

1. **Diagnose** — `feedback_analyzer.py` produces a `Diagnosis` with root cause and affected files
2. **Generate** — LLM produces a unified diff
3. **Apply** — `git worktree add` creates an isolated branch; the diff is applied with `git apply`
4. **Validate** — syntax check + full test suite inside the worktree
5. **PR** — `gh pr create` (or a pre-filled GitHub URL as fallback)

The user's working copy is never touched.

### Hooks (`hooks.py`)

Shell and Python scripts that fire on lifecycle events:

| Event | When |
|-------|------|
| `preToolUse` | Before every tool call (can return `{"allow": false}` to block) |
| `postToolUse` | After every tool call |
| `preChat` | Before sending the prompt to the API |
| `postChat` | After receiving the response |
| `onSessionStart` / `onSessionEnd` | Session lifecycle |

### Plan gate (`plan_gate.py` + `planner.py`)

In daemon mode (`auto_plan`), the AI generates a structured `Plan` before execution so the agent has a concrete checklist instead of an open-ended task. In interactive mode, `plan_and_approve()` shows the plan in rich Markdown and waits for confirmation.

---

## Configuration and data layout

```
~/.luckyd-code/                 ← user-global data (cross-project)
    memories/                   ← long-term user memories
    settings.json               ← global settings

<project-root>/.luckyd-code/    ← project-scoped data
    settings.local.json         ← per-project overrides + hooks config
    memories/                   ← project memories (CLAUDE.md-style)
    plans/                      ← AI-generated plans (Markdown + JSON)
    undo.json                   ← undo history
    keybindings.json            ← custom keybindings
    brain/
        graph.json              ← knowledge graph
        index/                  ← FAISS vector index + chunk metadata
    analytics/
        snapshots/              ← health trend snapshots
    costs.jsonl                 ← append-only cost log
    sessions/                   ← saved conversation sessions
```

---

## Adding a new tool

1. Create `luckyd_code/tools/my_tool.py` with a class that implements `run(self, **kwargs) -> str`.
2. Decorate it with `@tool(name="MyTool", description="…")` from `tools/decorators.py`.
3. Register it in `tools/registry.py` — add an import and append to `_TOOL_CLASSES`.
4. Write tests in `tests/test_my_tool.py`.
5. Update `README.md` → Tools Gallery section.

For a plugin (user-contributed, hot-reloaded), drop a `.py` file into `~/.luckyd-code/plugins/`. See `docs/PLUGINS.md` for the plugin API.
