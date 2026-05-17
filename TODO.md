# LuckyD Code — TODO / Improvement Roadmap

Prioritised work items toward a 10/10 project score.
Each item has an effort tag: 🟢 small (< 1 hr) · 🟡 medium (1–4 hrs) · 🔴 large (> 4 hrs)

---

## 🔴 Code Quality — mypy Strict Coverage

Currently 27 modules remain excluded from mypy strict checking.
Remove them incrementally once annotations are complete.

### High-value, low-effort removals (already partially typed)
- [ ] 🟢 `luckyd_code/keybindings.py` — add missing return types
- [ ] 🟢 `luckyd_code/undo.py` — add missing param annotations
- [ ] 🟢 `luckyd_code/settings.py` — add return types to public functions
- [ ] 🟢 `luckyd_code/plan_gate.py` — already structured; add `-> None` / `-> bool`
- [ ] 🟢 `luckyd_code/planner.py` — add annotations to `Planner` methods
- [ ] 🟡 `luckyd_code/verify.py` — complex; add annotations, remove from exclusion list
- [ ] 🟡 `luckyd_code/hooks.py` — add param + return types throughout

### Whole subsystems (deferred — heavy third-party stubs)
- [ ] 🔴 `luckyd_code/analytics/` — scanner, smells, trends, reporter
- [ ] 🔴 `luckyd_code/brain/` — chunker, graph, indexer, parser, retriever
- [ ] 🔴 `luckyd_code/memory/` — manager, user
- [ ] 🔴 `luckyd_code/tools/` — file_ops, bash, readme_gen, image, youtube
- [ ] 🔴 `luckyd_code/web_routes/` — all route modules

---

## 🟡 Testing — Raise Coverage Floor

Current measured total: **93 %** (target: 95 %+, floor set at 92 %)

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
- [ ] 🟢 Add tests for `error_reporter._get_version`, `_get_reporting_mode`, `_get_api_key`, `capture_and_log_only`
- [ ] 🟢 Add tests for `analytics/trends.py` uncovered branches
- [ ] 🟡 Add tests for `analytics/reporter.py` uncovered render paths
- [ ] 🟡 Add tests for `hooks.py` conditional paths
- [ ] 🟡 Raise `fail_under` from 92 → 95 once new tests land

---

## 🟢 Polish — Regenerate ceiling_run.txt

The `ceiling_run.txt` is stale (from an old test session).  Regenerate it:

```
.testvenv\Scripts\pytest tests/test_ceiling.py -v \
  --cov=luckyd_code --cov-report=term-missing \
  2>&1 | tee ceiling_run.txt
```

The 2 previously failing image tests (`test_image_analyze_tool_ocr_supplement`
and `test_image_analyze_vision_fails_ocr_fallback`) are fixed — both now write
real bytes to disk before calling `tool.run()`.

---

## 🟡 Polish — RAG Plug-and-Play

The RAG (Retrieval-Augmented Generation) system currently requires manual
steps to activate. Make it automatic:

- [ ] 🟡 Auto-detect whether `sentence-transformers` is installed and silently
       degrade to keyword search if not
- [ ] 🟢 Add a `luckyd-code install-rag` CLI command that installs the optional
       `rag-full` extra
- [ ] 🟢 Surface a one-line notice in the UI when RAG is available but inactive

---

## 🟡 Polish — Knowledge Graph Fallback

The knowledge graph's fallback path currently contains only 2 stub symbols.
Add at least 10 real built-in fallback symbols so first-run is useful without
a full parse step:

- [ ] 🟡 Expand `brain/graph.py` fallback with common Python builtins
- [ ] 🟢 Add a unit test asserting fallback has ≥ 10 symbols

---

## 🟢 Documentation

- [ ] 🟢 Write `docs/architecture.md` — one-page description of the request
       lifecycle (CLI → agent loop → tools → verify pipeline)
- [ ] 🟢 Write `docs/contributing.md` additions — how to add a new tool,
       how to run the ceiling suite
- [ ] 🟢 Add badges to README (coverage, PyPI version, Python ≥ 3.10)
- [ ] 🟢 Ensure all public API functions have docstrings (scan with `pydocstyle`)

---

## 🔴 Bus Factor — Contributor Onboarding

Currently a single-developer project (bus factor = 1).

- [ ] 🟡 Add `ARCHITECTURE.md` with a module-dependency diagram
- [ ] 🟡 Label GitHub issues with `good first issue` / `help wanted`
- [ ] 🔴 Set up GitHub Actions CI (lint → mypy → pytest) so contributors get
       instant feedback without needing the local dev setup

---

## Completed ✅

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
