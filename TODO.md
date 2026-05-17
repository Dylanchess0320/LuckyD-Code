# LuckyD Code — TODO / Improvement Roadmap

Prioritised work items toward a 10/10 project score.
Each item has an effort tag: 🟢 small (< 1 hr) · 🟡 medium (1–4 hrs) · 🔴 large (> 4 hrs)
**Blocking items are listed first in each section. Aspirational items are marked `[aspirational]`.**

---

## 🔴 Code Quality — mypy Strict Coverage

Currently **15 modules** remain excluded from mypy strict checking (down from 16).
Recently graduated: `orchestrator.py` — fully typed with `_AgentConfig` + `ToolRegistryProtocol` (2026-05-17).

### Still excluded (whole subsystems — heavy third-party stubs)
- [ ] 🔴 `luckyd_code/analytics/` — scanner, smells, trends, reporter
- [ ] 🔴 `luckyd_code/brain/` — chunker, graph, indexer, parser, retriever
- [ ] 🔴 `luckyd_code/memory/` — manager, user
- [ ] 🔴 `luckyd_code/tools/` — file_ops, bash, readme_gen, image, youtube
- [ ] 🔴 `luckyd_code/web_routes/` — all route modules

### Near-clean individual modules (next targets)
- [x] 🟢 `luckyd_code/hooks.py` — fixed `env_updates: dict` → `dict[str, Any]`; added `__init__(self) -> None`
- [x] 🟡 `luckyd_code/self_improve.py` — added `-> None` to `ImprovementTracker.__init__`
- [x] 🟡 `luckyd_code/backup.py` — fully typed; removed from exclusion list
- [x] 🟡 `luckyd_code/export.py` — `list` → `list[dict[str, Any]]`; added `from typing import Any`
- [x] 🟡 `luckyd_code/orchestrator.py` — `_AgentConfig` + `ToolRegistryProtocol`; graduated (2026-05-17)

---

## 🟡 Testing — Raise Coverage Floor

Current measured total: **93%+** (target: 95%+, floor now set at **95%**)

### Remaining gaps (from most recent coverage report)

| Module | Coverage | Missing lines |
|---|---|---|
| `brain/__init__.py` | ~23 % | 37–81 (rebuild_project) — *test_brain_rebuild.py added* |
| `dream.py` | ~72 % | 165–195, 202–242 — *test_dream_llm_merge.py added* |
| `__init__.py` | ~80 % | 30–34 (lazy imports) — *test_lazy_imports.py added* |
| `error_reporter.py` | ~80 % | _get_version, _get_reporting_mode, _get_api_key |
| `api.py` | ~79 % | 30, 149–150, 172 (non-pragma lines) |
| `analytics/trends.py` | ~86 % | 121–122, 134, 160–163, 194–228 |
| `analytics/reporter.py` | ~87 % | 15, 58–61, 80, 82, 84, 137–147 |
| `hooks.py` | ~87 % | 78, 106, 109, 125–126, 165–166, 198 |
| `cost_tracker.py` | ~87 % | 113–114, 126–127, 151–152, 185–199 |

### Action items
- [x] 🟢 Add tests for `error_reporter._get_version`, `_get_reporting_mode`, `_get_api_key`, `capture_and_log_only`
- [x] 🟢 Add tests for `analytics/trends.py` uncovered branches
- [x] 🟡 Add tests for `analytics/reporter.py` uncovered render paths
- [x] 🟡 Add tests for `hooks.py` conditional paths
- [ ] 🟢 Raise `fail_under` from 97 → 98+ once remaining subsystem gaps are closed
- [x] 🟢 Rename `test_coverage_final_push.py` → `test_router_context_analytics_sandbox.py` (descriptive module name)

---

## 🟢 Polish — Regenerate ceiling_run.txt

The `ceiling_run.txt` is gitignored and should be regenerated locally before raising the coverage floor. Run:

```
.testvenv\Scripts\pytest tests/test_ceiling.py -v \
  --cov=luckyd_code --cov-report=term-missing \
  2>&1 | tee ceiling_run.txt
```

The 2 previously failing image tests (`test_image_analyze_tool_ocr_supplement`
and `test_image_analyze_vision_fails_ocr_fallback`) are fixed — both now write
real bytes to disk before calling `tool.run()`.

---

## 🟢 Polish — RAG Plug-and-Play

The RAG system degrades gracefully: `is_rag_available()` in `brain/__init__.py`
detects whether `sentence-transformers` is installed. The UI notice is still TODO.

- [x] 🟢 Surface a one-line notice in CLI and Web UI when RAG is available but inactive
- [x] 🟢 Add a `luckyd-code install-rag` CLI command that installs the optional `rag-full` extra

---

## ✅ Knowledge Graph Fallback

The knowledge graph is now pre-seeded with **20 Python built-in symbols** (`len`, `print`,
`range`, `list`, `dict`, `str`, `int`, `float`, `bool`, `type`, `isinstance`, `hasattr`,
`getattr`, `setattr`, `enumerate`, `zip`, `map`, `filter`, `sorted`, `open`).
Built-ins are re-seeded after both `build()` and `load()` so they survive graph
resets and old saved graphs.

---

## 🟢 Documentation

- [x] 🟢 Write `docs/architecture.md` — one-page description of the request
       lifecycle (CLI → agent loop → tools → verify pipeline)
- [x] 🟢 Write `docs/contributing.md` additions — how to add a new tool,
       how to run the ceiling suite
- [x] 🟢 Add badges to README (coverage, PyPI version, Python ≥ 3.10)
- [x] 🟢 Add `[tool.pydocstyle]` config to `pyproject.toml` (numpy convention, match luckyd_code/)

---

## 🔴 Bus Factor — Contributor Onboarding

Currently a single-developer project (bus factor = 1).

- [x] 🟡 Add `ARCHITECTURE.md` with a module-dependency diagram
- [x] 🟡 Add `good_first_issue.md` ISSUE_TEMPLATE with acceptance criteria and onboarding links
- [x] 🔴 Set up GitHub Actions CI (lint → mypy → pytest) so contributors get
       instant feedback without needing the local dev setup

---

## Completed ✅

- [x] `pyproject.toml` — license classifier corrected from `MIT` → `GNU Affero General Public License v3`
- [x] `cli.py` — RAG startup notice surfaced (installed+inactive and not-installed paths)
- [x] `cli_commands/dispatcher.py` — `/install-rag` command added; `/help` table updated
- [x] `config.py` — docstrings added to `__init__`, `_resolve_api_key`, `from_args`
- [x] `tests/test_config_coverage.py` — 18 cases covering exception branches (lines 56-57, 90-92, 98, 156)
- [x] `pyproject.toml` — `fail_under` raised 95 → 97
- [x] `docs/contributing.md` — how to add a tool + ceiling suite guide written
- [x] `pyproject.toml` — coverage floor raised 80 → 92
- [x] `pyproject.toml` — mypy exclusion list reduced from 30 → 27 modules
       (`init.py`, `themes.py`, `update.py` now fully typed and checked)
- [x] `tests/test_brain_rebuild.py` — 11 cases; `brain/__init__.py` rebuild_project
- [x] `tests/test_dream_llm_merge.py` — 15 cases; dream.py _phase_consolidate + _llm_merge
- [x] `tests/test_lazy_imports.py` — 5 cases; __init__.py lazy __getattr__
- [x] `tests/test_error_reporter_coverage.py` — covers _get_version, already_reported,
       _get_reporting_mode, _get_api_key, capture_and_log_only, build_issue_url
- [x] `tests/test_hooks_coverage.py` — covers all uncovered hooks.py branches
       (unknown event, tool filter, dict hook config, timeout, FileNotFoundError)
- [x] `tests/test_trends_coverage.py` — covers TrendTracker load/save/compare branches
       (JSONDecodeError, None points, improving/declining directions, languages added/removed)
- [x] `tests/test_reporter_coverage.py` — covers analytics/reporter.py
       (_format_size TB, terminal smells/todos/complexity, markdown smells, html, generate_report)
- [x] `tests/test_cost_tracker_coverage.py` — covers CostTracker JSONL append,
       sidecar fast/slow paths, reset file deletion, legacy migration
- [x] `tests/test_api_streaming.py` — covers stream_chat SSE loop, all error yields,
       text/reasoning/done events, _classify_http_error all branches
- [x] `tests/test_ceiling.py` — fixed 2 failing image tests: now patches _call_vision
       directly (avoids import-cache race) and uses valid PNG header bytes
- [x] Version bump 1.2.3 → 1.2.4
- [x] `CHANGELOG.md` — v1.2.4 entry written
- [x] `_agent_loop.py` — `ToolRegistryProtocol` added; `registry: Any` → typed throughout; memory auto-save failures promoted from `debug` → `warning`
- [x] `context.py` — dead `model: str` param removed from `compact()`; `add_assistant_message` reformatted over multiple lines
- [x] `orchestrator.py` — `config` params typed; `f"Error: {e}"` → `[ORCHESTRATION ERROR — ...]`; error now logged with exc_info
- [x] `planner.py` — silent `except Exception: pass` in `load_plan` now logs a WARNING; `config` type-annotated
- [x] `dream.py` — `_llm_merge` now raises helpful `ImportError` when `openai` is not installed (was silent `TypeError`)
- [x] `sessions.py` — corrupted session files now log a WARNING; `# pragma: no cover` removed from tested `delete_session` success path
- [x] `cost_tracker.py` — `_write_total` silent `except: pass` replaced with `_logger.warning(...)`
- [x] `.gitignore` — added `ceiling_run.txt`, `cov_out.txt`, `_del_nul.py`, `/gitpush.bat`
- [x] `pyproject.toml` — `orchestrator.py` removed from mypy exclusion list
- [x] `scripts/git_cleanup.bat` — one-shot script to `git rm --cached` all junk tracked files including `nul`
- [x] `tests/test_cost_tracker_coverage.py` — `TestWriteTotalWarning` covers the now-logged failure path
- [x] `tests/test_sessions.py` — `test_list_sessions_corrupted_file_logs_warning` covers the new warning path
