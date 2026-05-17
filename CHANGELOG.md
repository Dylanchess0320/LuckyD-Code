# Changelog

## [Unreleased] — 2026-05-17

### Fixed
- **`router.py`** — `_LLM_CLASSIFY_TIMEOUT` raised from `0.0` to `0.4` s.
  At zero the background LLM classifier always timed out on the first call,
  making smart routing heuristic-only until a cached result existed. 0.4 s
  gives the fast flash model enough time to respond on a normal connection
  while remaining imperceptible to the user.

### Changed
- **`tests/test_coverage_gaps_*.py`** — module docstrings updated to describe
  *what* each test class covers rather than labelling the files as
  "batch 1/2/3/final gap-fillers". Coverage tests that were written to chase
  a number now self-document their intent.
- **`pyproject.toml` [tool.mypy]** — tightened type-checking: added
  `warn_unused_ignores`, `no_implicit_reexport`, `disallow_any_generics`,
  `disallow_subclassing_any`, `disallow_untyped_decorators`, and
  `check_untyped_defs`. CLI entry-points and optional-dep modules explicitly
  excluded so the stricter checks apply only to the core library.
- **`Makefile`** — `lint` target no longer passes `--ignore-missing-imports`
  (now set in `pyproject.toml`); added `typecheck` alias and `secrets-scan`
  target (`gitleaks detect --source .`) for one-time history audit.

### Security
- **`SECURITY.md`** — added a prominent ⚠️ banner at the top reminding cloners
  from before v1.2.1 to rotate their `DEEPSEEK_API_KEY`.
- **`.pre-commit-config.yaml`** — added `gitleaks` pre-commit hook (v8.18.2)
  that scans staged files on every commit, preventing a recurrence of the
  v1.2.1 key-commit incident.

## [1.2.2] — 2026-05-06

### Changed
- **.gitignore** — added `.luckyd_history` and `.luckyd-code/` for project rename parity
- **Docstring fix** (`_agent_loop.py`) — removed stale `/critique` reference in `run_config`

## [1.2.3] — 2026-05-16

### Fixed
- **`backup.py`** — renamed `BACKUP_TAG_PREFIX` from `"dsc-backup/"` to `"luckyd-backup/"` to match the project rename. Existing tags with the old prefix remain in your repo history and are unaffected.

### Removed
- **`self_critique.py`** — deleted the empty tombstone file (contained only a comment noting it had already been removed).

### Added
- **Tests** — `tests/test_backup.py` (52 cases covering all public functions in `backup.py`) and `tests/test_file_watcher.py` (28 cases covering `FileWatcher` public API, start/stop lifecycle, pause/resume, status, and extension filtering).
- **Coverage badge** — Codecov integration added to CI (`ci.yml`) and badge added to `README.md`. Coverage uploads only on Python 3.12 to avoid duplicate reports.

All notable changes to LuckyD Code will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [1.2.1] — 2026-05-02

### Changed
- **Agent loop** (`_agent_loop.py`) — complete harness overhaul targeting top-1% quality:
  - **Stuck-loop detection** — tracks hashes of recent tool-call batches; if the same batch repeats `_STUCK_WINDOW` times the loop breaks and asks the model to explain what's blocking it instead of burning all turns.
  - **Turn budget injection** — when ≤ 2 turns remain, a system message is injected so the model can wrap up gracefully instead of being cut off mid-task.
  - **Mid-loop model escalation** — on repeated verify failures the loop automatically promotes to the next tier in `_ESCALATION_LADDER` (`deepseek-v4-flash` → `deepseek-v4-pro`) for recovery turns.
  - **Tool result truncation** — all tool results are capped at 8,000 characters before context injection, protecting the token budget on large file reads.
  - **Re-read-after-write** — after every `Write` or `Edit` tool call, the file's existence and size are checked; if the write silently failed a warning is injected immediately.
  - **Context-overflow protection** — `estimate_tokens()` is checked before every turn; if usage exceeds 85% of the compact threshold, `compact()` runs automatically.
  - `LoopResult` gains `escalated_model` field to report any mid-loop model promotion.
  - ~~`RunConfig` gains `enable_self_critique` flag~~ *(removed before release — the verify pipeline + pre-edit checklist in the system prompt replaced this)*.

### Security
- **Removed `.env` from git tracking** — the `.env` file containing the
  `DEEPSEEK_API_KEY` was previously committed to the repository. It is now
  untracked (`git rm --cached .env`). The `.gitignore` rule for `.env` already
  existed but had no effect while the file was being tracked. **If you cloned
  this repo before this release, rotate your API key at
  [platform.deepseek.com/api_keys](https://platform.deepseek.com/api_keys).**

### Fixed
- **`SECURITY.md`** — updated supported versions table to reflect v1.2.x as the
  current supported release.

## [1.2.0] — 2026-05-02

### Changed
- **Shared agent loop** (`_agent_loop.py`) — extracted a single `run_agent_loop()`
  function used by both `SubAgent` and `AgentHandoff`. Bug fixes now propagate
  to all agentic paths automatically; `agent.py` and `orchestrator.py` are ~60%
  shorter as a result.
- **Retry in `stream_chat`** (`api.py`) — `_call_with_retry()` now wraps
  `_stream_chat_raw` with up to 3 attempts using exponential backoff and jitter
  (1 s base, 30 s cap). Rate-limit (429) and server errors (5xx) are retried;
  auth and bad-request errors are not.
- **Cost tracking** (`cost_tracker.py`) — switched from full-rewrite JSON to
  append-only JSONL (`costs.jsonl`). Each API call is now O(1) instead of
  O(session length). Existing `costs.json` files are migrated automatically on
  first write.
- **Memory search** (`memory/manager.py`) — `search_memories()` now uses
  semantic cosine-similarity via `sentence-transformers` (all-MiniLM-L6-v2)
  when the `rag` extra is installed, with keyword-frequency as an automatic
  fallback. Thread-safe singleton (`_DEFAULT_MANAGER`) fixed with
  double-checked locking.
- **Orchestrator** (`orchestrator.py`) — reviewer handoff now uses
  `_truncate_to_tokens()` instead of a hardcoded `[:3000]` char slice.
  `parallel_orchestrate` thread pool capped at `min(len(sub_tasks), 4)` to
  prevent unbounded concurrent API calls.
- **`__all__` exports** — added to `memory/__init__.py`, `tools/__init__.py`,
  `_agent_loop.py`, `agent.py`, and `orchestrator.py`.

## [1.1.0] — 2026-05-01

### Fixed
- **Critical bug**: `orchestrator.py` — `stream_chat` was called but never imported,
  causing a `NameError` crash on any `/orchestrate` command. Fixed by adding
  `from .api import stream_chat` to the import block.
- Removed unused `import time` from `orchestrator.py`.

### Changed
- **Model registry** (`model_registry.py`) — eliminated duplicate `ModelDef` entries.
  `deepseek-v4-flash` and `deepseek-v4-pro` now each appear exactly once.
  A `TIER_MODEL_MAP` dict handles the tier→model mapping; `get_unique_model_count()`
  now correctly returns 2 instead of 4. `format_model_list()` updated to show
  tier assignments alongside each model.
- **Router** (`router.py`) — `classify_tier_llm()` no longer blocks the main thread.
  The LLM API call now runs in a background `ThreadPoolExecutor`; the heuristic
  result is returned immediately if the call doesn't finish within 4 seconds.
  The LLM result is still cached once it arrives, so future identical prompts
  are instant. Router now imports `TIER_MODEL_MAP` directly from `model_registry`
  instead of maintaining a separate copy.
- **Planner** (`planner.py`) — completely rebuilt from a plain file-manager into
  a real AI-powered task decomposer. `ai_create_plan(name, goal, config)` calls
  `deepseek-v4-flash` to break a goal into structured `PlanStep` objects with
  agent assignments, dependency tracking, and time estimates. Plans are persisted
  as both human-readable Markdown and machine-readable JSON. Added `load_plan`,
  `save_plan`, `update_step_status`, and `delete_plan` helpers.

### Added
- **Tool result caching** (`tools/registry.py`) — `ToolRegistry` now caches results
  from read-only tools (`Read`, `Glob`, `Grep`, `WebFetch`, `WebSearch`, `DateTime`)
  for 5 minutes (configurable via `cache_ttl`). Identical calls within the TTL
  window skip the underlying I/O entirely. Cache keys are derived from tool name +
  sorted arguments. Write/Bash/Git tools are explicitly excluded. Added
  `ToolRegistry.invalidate()` to clear entries by tool name or globally.
- **Diff preview for Write and Edit tools** (`tools/file_ops.py`) — both `WriteTool`
  and `EditTool` now accept a `dry_run=true` parameter. When set, the tool returns
  a unified diff of the proposed change without modifying the file. `WriteTool`
  also reports how many lines changed after every successful write.

## [1.0.0] — 2025-04-28

### Added
- **AI Chat** — Conversational coding assistant with streaming responses and thinking/reasoning mode
- **Smart Model Routing** — Auto-classifies prompt complexity into 4 tiers
- **Knowledge Graph** — Automatic codebase indexing with vector search and dependency tracking
- **Memory System** — Persistent `CLAUDE.md` memory across sessions with relevance search
- **Cost Tracking** — Per-session and cumulative cost tracking across models
- **Web UI** — Browser-based interface with cost panel, memory management, and model routing
- **40 Built-in Tools** — Read, Write, Edit, Glob, Grep, Bash, WebFetch, WebSearch, Git, Browser automation
- **MCP Support** — Model Context Protocol for extending with custom tools
- **DeepSeek API** — Native integration with `deepseek-v4-flash` and `deepseek-v4-pro`
- **Context Management** — Auto-compaction with summarization to stay within context windows
- **Background Agents** — Run tasks asynchronously while continuing to chat
- **Orchestrator** — Researcher → Coder → Reviewer pipeline for complex tasks
- **Hooks System** — Pre/post tool use, pre/post chat, lifecycle hooks
- **Sandboxing** — Docker-based secure command execution
- **Session Management** — Save, load, and auto-recover conversations
- **Undo** — Revert file writes and edits
- **Export** — Conversations to Markdown or HTML
- **Shell Detection** — Auto-detects Git Bash → WSL → cmd.exe on Windows
- **Playwright Browser** — Full browser automation for testing and web interaction
- **Self-Improvement** — Automated audit and improvement system
- **File Watching** — Watch files and auto-reindex knowledge graph
- **Rate Limiting** — Per-IP rate limiting for Web UI
- **Auth Support** — Bearer token authentication for Web UI
- **First-run Wizard** — Interactive API key setup on first launch
- **CLI Commands** — `/help`, `/clear`, `/compact`, `/undo`, `/model`, `/cost`, `/memory`, `/brain`, `/export`, `/sessions`, `/review`, `/orchestrate`
