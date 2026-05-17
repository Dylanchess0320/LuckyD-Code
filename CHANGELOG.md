# Changelog

All notable changes to LuckyD Code will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [1.3.3] — 2026-05-17

### Fixed
- **`pyproject.toml`** — classifiers still listed `MIT License`; corrected to
  `GNU Affero General Public License v3` to match the AGPL v3 license set in
  v1.3.1.  This was a metadata-only bug with no code impact.

### Added
- **CLI startup RAG notice** — `cli.py` now prints a one-line dim notice at
  startup when the RAG backend is installed but the project has not yet been
  indexed (`/brain rebuild` prompt), or when it is not installed at all
  (`pip install luckyd-code[rag-full]` prompt). Resolves the long-standing
  TODO item "Surface a one-line notice in CLI when RAG is available but inactive".
- **`/install-rag` command** — new CLI command that checks whether
  `sentence-transformers` is installed and, if not, invokes
  `pip install luckyd-code[rag-full]` in a subprocess. The command is listed
  in `/help` under Skills & Tools and in `docs/contributing.md`.
- **`config.py` docstrings** — `Config.__init__`, `Config._resolve_api_key`,
  and `Config.from_args` now have full NumPy-style docstrings describing
  their search order, args, and return values.
- **`tests/test_config_coverage.py`** — 18 new cases targeting the remaining
  uncovered branches in `config.py`: `load_config_file` exception handler
  (lines 56–57), `_resolve_api_key` DEEPSEEK fallback (lines 90–92) and env
  var return path (line 98), `from_args` provider override key re-resolution
  (line 156), and `save_config_file` directory creation.

### Changed
- **`pyproject.toml`** — `fail_under` raised from 95 → 97 in both
  `[tool.pytest.ini_options]` and `[tool.coverage.report]`.

## [1.3.2] — 2026-05-17

### Changed
- **`pyproject.toml`** — mypy exclusion list reduced from 20 → 16 modules:
  `backup.py`, `export.py`, `hooks.py`, and `self_improve.py` are now fully
  annotated and pass strict checks.

### Fixed
- **`hooks.py`** — `HookResult.env_updates` narrowed from bare `dict` to
  `dict[str, Any]`; `HookRunner.__init__` now declares `-> None` return type.
- **`export.py`** — `messages` parameter typed from bare `list` to
  `list[dict[str, Any]]` in both `export_markdown` and `export_html`;
  `from typing import Any` import added.
- **`self_improve.py`** — `ImprovementTracker.__init__` now declares `-> None`.
- **`backup.py`** — confirmed fully typed; removed from mypy exclusion list
  (no source changes required).

### Added
- **`docs/contributing.md`** — contributor guide covering: how to add a new
  tool (file, registration, tests, README update), how to run the ceiling
  suite (Windows and Unix commands, single-file, HTML report, CI-equivalent),
  type-checking workflow, pre-commit setup, commit message format, and
  release checklist.
- **`TODO.md`** — marked all previously completed items as done (test
  coverage files, architecture docs, README badges, CI, ARCHITECTURE.md,
  and all near-clean type annotation items).

## [1.3.1] — 2026-05-24

### Changed
- **License** — MIT → GNU AGPL v3 (proprietary/internal use now requires commercial license)
- **`luckyd_code/__init__.py`** — `__license__` updated from `"MIT"` to `"AGPL-3.0-only"`
- **`pyproject.toml`** — `license` field updated to `"AGPL-3.0-only"`
- **`README.md`** — Badge and license section updated to reflect AGPL v3 + dual-license option
- **`CONTRIBUTING.md`** — CLA now references AGPL v3 instead of MIT

## [1.2.4] — 2026-05-17

### Added
- **Tests** — `tests/test_brain_rebuild.py` (11 cases fully covering `brain/__init__.py`
  `rebuild_project()`: defaults to cwd, vector-index path, mtime tracking, knowledge-graph
  path, both paths together, and partial stats handling).
- **Tests** — `tests/test_dream_llm_merge.py` (15 cases covering `dream.py`
  `_phase_consolidate` and `_llm_merge`: config=None skip, empty groups, merge cap,
  successful merge, empty-content skip, exception capture, delete-before-save order,
  dominant-type selection, LLM response parsing, default model fallback, malformed
  response, name truncation, and load-memory calls).
- **Tests** — `tests/test_lazy_imports.py` (5 cases covering `luckyd_code/__init__.py`
  lazy `__getattr__` subpackage loader: memory, tools, settings, brain, unknown-attr
  error, and caching behaviour).
- **TODO.md** — Comprehensive prioritised improvement roadmap covering code quality,
  testing, polish, and documentation work items with effort estimates.

### Changed
- **`pyproject.toml`** — coverage `fail_under` threshold raised from 80 → 92
  (actual measured coverage is 93%+; the floor now reflects a meaningful standard).
- **`pyproject.toml`** — pytest `--cov-fail-under` flag updated from 80 → 92 to match.
- **`pyproject.toml`** — `init.py`, `themes.py`, and `update.py` removed from the mypy
  exclusion list — all three modules are fully annotated and pass strict checks.
  Mypy exclusion list reduced from 30 modules to 27.
- **Version bump** — `1.2.3` → `1.2.4`.

## [Unreleased] — 2026-05-17

### Fixed
- **`api.py`** — replaced `Dict[str, Any]` (old-style capital-D) with `dict[str,
  Any]` in two local variable annotations inside `_open_stream` and
  `_parse_sse_line`. While Python does not evaluate local annotations at runtime,
  the usage was inconsistent with the rest of the codebase and would confuse
  static analysis tools.
- **`analytics/reporter.py`** — footer text changed from
  "Report generated by DeepSeek Code Analytics" → "LuckyD Code Analytics".
- **`analytics/scanner.py`** — `.luckyd-code` added to `SKIP_DIRS` so the
  project's own data directory is excluded from codebase scans (`.deepseek-code`
  retained for backward compatibility during migration).
- **`cli_commands/config.py`** — `/config set provider` now accepts any provider
  registered in `_PROVIDER_URLS` (deepseek, openai, groq, together, ollama)
  instead of hard-rejecting everything except "deepseek". The base URL is now
  looked up from `_PROVIDER_URLS` and the env-var key is derived from the
  provider name (`{PROVIDER}_API_KEY`) instead of hardcoding `DEEPSEEK_API_KEY`.
- **`tasks/manager.py`** — `from typing import Optional` removed; `get_task()`
  return type changed from `Optional[Task]` → `Task | None`.
- **`tests/conftest.py`** — `temp_project_dir` fixture docstring corrected from
  `.deepseek-code/` to `.luckyd-code/` to match what the fixture actually creates.
- **`autonomous_fixer.py`** — docstring references to "DeepSeek API key" made
  provider-agnostic (now "API key for the configured provider").
- **`error_reporter.py`** — `_get_api_key()` no longer falls back to
  `os.environ.get("DEEPSEEK_API_KEY", "")` as a last resort; `Config().api_key`
  already handles provider-specific env-var resolution correctly.
- **`brain/retriever.py`** — `from typing import Optional` removed; all three
  `Optional[str]` parameter annotations (`search`, `_bm25_search`,
  `_fallback_search`) migrated to `str | None`.
- **`tools/image.py`** — `from typing import Optional` removed; `_ocr_text()`
  return type changed from `Optional[str]` → `str | None`.

- **`planner.py`** — Removed `from typing import Optional`; migrated `Optional[Plan]` return types to `Plan | None` in `load_plan()` and `plan_and_approve()`.
- **`_agent_loop.py`** — Removed `from typing import Callable, Optional`; added `from collections.abc import Callable`; migrated all `Optional[X]` and `Callable[...]` annotations to `X | None` and builtin `Callable` throughout. Changed `Deque[str]` annotation to `deque[str]`.
- **`hooks.py`** — Fixed stale `DSC_*` reference in `_run_python_script` docstring — now correctly says `LDC_*`.
- **`api.py`** — Removed `from typing import Dict, Generator, List, Optional, Tuple`; replaced all with `collections.abc.Generator` and builtin `list[...]`, `dict[...]`, `tuple[...]`, `X | None`.
- **`cost_tracker.py`** — Removed `Optional`; migrated `Optional[float]` to `float | None`.
- **`file_watcher.py`** — Removed `from typing import Callable, Optional`; added `from collections.abc import Callable`; migrated all `Optional[...]` annotations to `X | None`.
- **`orchestrator.py`** — Removed `Optional` from import.
- **`plan_gate.py`** — Removed `from typing import Optional`; migrated `Optional[GateResult]` and `Optional[object]` to `X | None`.
- **`router.py`** — Removed `from typing import Optional`; migrated all `Optional[str]` and `Optional[int]` annotations to `X | None`.
- **`cli_utils.py`** — Removed `from typing import Optional`; migrated `Optional[str]` to `str | None`.
- **`themes.py`** — Fixed module docstring: was "DeepSeek Code", now "LuckyD Code".
- **`memory/manager.py`** — Removed `Optional`; migrated `Optional[str]`, `Optional[MemoryManager]` to `X | None`.
- **`memory/user.py`** — Removed `Optional`; migrated `Optional[str]`, `Optional[UserMemory]` to `X | None`.
- **`tools/registry.py`** — Removed `from typing import Dict, Optional`; migrated all to builtin `dict[...]` and `X | None`.
- **`cli_commands/dispatcher.py`** — Fixed stale export filename: was `deepseek_export_*.{ext}`, now `luckyd_export_*.{ext}`.
- **`tests/conftest.py`** — Fixed stale `.deepseek-code/` directory in `temp_project_dir` fixture; now `.luckyd-code/`.
- **`mcp/client.py`** — Removed `Optional` from import; migrated `Optional[subprocess.Popen]` to `subprocess.Popen | None`.
- **`tools/bash.py`** — Removed `from typing import Optional`; migrated `Optional[ShellInfo]` to `ShellInfo | None`.
- **`web_routes/__init__.py`** — Removed `Dict` from import; migrated `Dict[str, Any]` and `Dict[str, Dict[str, float]]` to builtin `dict[...]`.

- **`log.py`** — replaced f-strings in `logger.info()` / `logger.warning()` calls
  with `%`-style lazy formatting (G004 lint rule; avoids string construction cost
  when the log level would suppress the message).
- **`router.py`** — `import os as _os_router` private alias replaced with plain
  `import os`; all `_os_router.*` call sites updated.
- **`cost_tracker.py`** — removed hardcoded `2026-05-31` expiry date from the
  `_calc_cost` docstring (the discount may be renewed); replaced with a pointer
  to the DeepSeek pricing page to verify current rates.

### Breaking Changes
- **`hooks.py`** — Hook environment variables renamed from `DSC_*` to `LDC_*`
  to match the project rename (e.g. `$DSC_TOOL_NAME` → `$LDC_TOOL_NAME`,
  `$DSC_HOOK_EVENT` → `$LDC_HOOK_EVENT`). **Update any existing hook scripts
  that reference `$DSC_*` variables.**

### Changed
- **`tests/test_coverage_*.py`** — renamed all 7 coverage-chase files to
  descriptive names reflecting the module groups they exercise:
  `test_supplemental_tools_and_web.py`, `test_routing_config_analytics.py`,
  `test_agent_loop_and_api.py`, `test_memory_analytics_brain.py`,
  `test_file_ops_and_orchestrator.py`, `test_git_sessions_smells_dream.py`,
  and `test_image_registry_sessions.py`.
- **`pyproject.toml`** — coverage `fail_under` threshold raised from 69 to 80
  (actual measured coverage is 93%; the floor now reflects a meaningful standard).
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

## [1.2.3] — 2026-05-16

### Fixed
- **`backup.py`** — renamed `BACKUP_TAG_PREFIX` from `"dsc-backup/"` to `"luckyd-backup/"` to match the project rename. Existing tags with the old prefix remain in your repo history and are unaffected.

### Removed
- **`self_critique.py`** — deleted the empty tombstone file (contained only a comment noting it had already been removed).

### Added
- **Tests** — `tests/test_backup.py` (52 cases covering all public functions in `backup.py`) and `tests/test_file_watcher.py` (28 cases covering `FileWatcher` public API, start/stop lifecycle, pause/resume, status, and extension filtering).
- **Coverage badge** — Codecov integration added to CI (`ci.yml`) and badge added to `README.md`. Coverage uploads only on Python 3.12 to avoid duplicate reports.

## [1.2.2] — 2026-05-06

### Changed
- **.gitignore** — added `.luckyd_history` and `.luckyd-code/` for project rename parity
- **Docstring fix** (`_agent_loop.py`) — removed stale `/critique` reference in `run_config`

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
