# Contributing to LuckyD Code

Thanks for your interest! This guide covers everything from setting up a dev environment to submitting your first PR.

---

## Quick links

| Task | Where to look |
|---|---|
| First-time setup | [Development setup](#development-setup) |
| Add a new tool | [Adding a tool](#adding-a-tool) |
| Run the full test suite | [Testing](#testing) |
| Type checking | [Type checking](#type-checking) |
| Run the ceiling suite | [Ceiling suite](#ceiling-suite) |
| Release process | [Release checklist](#release-checklist) |

---

## Good first issues

New here? Look for issues labelled **`good first issue`** on GitHub — they're scoped to be doable without knowing the full codebase. Each one has a suggested approach and clear acceptance criteria.

If you want to work on something that isn't labelled yet, open a Discussion first so we can scope it before you invest time.

---

## Development setup

```bash
# Clone the repo
git clone https://github.com/Dylanchess0320/LuckyD-Code
cd LuckyD-Code

# Create a virtual environment (Python 3.10+)
python -m venv .venv

# Activate it
# Windows:  .venv\Scripts\activate
# Linux/Mac: source .venv/bin/activate

# Install in editable mode with all dev dependencies
pip install -e ".[dev]"

# Optional: RAG support (code search & knowledge graph)
pip install -e ".[rag-full]"

# Install pre-commit hooks (gitleaks + ruff + mypy)
pre-commit install
```

Copy `.env.example` to `.env` and fill in your API key.

---

## Project structure

```
luckyd_code/
├── _agent_loop.py       # Think → Act → Verify harness (shared by all agentic paths)
├── router.py            # Prompt → model tier classification
├── api.py               # DeepSeek SSE streaming client
├── context.py           # Conversation context + auto-compaction
├── config.py            # Config resolution (env → file → defaults)
├── cost_tracker.py      # Per-session and cumulative cost (JSONL)
├── verify.py            # Post-write: syntax → lint → AST → test gate
├── hooks.py             # Pre/post tool, pre/post chat lifecycle hooks
├── model_registry.py    # Model definitions and tier map
├── memory/              # Persistent project + cross-project memory
├── brain/               # Knowledge graph, FAISS index, BM25 retriever
├── tools/               # 40 built-in tools + registry (5-min TTL cache)
├── analytics/           # Code health, smell detection, trend tracking
├── autonomous_fixer.py  # Diagnose → patch → validate → open PR
├── cli.py               # Terminal UI (Rich + prompt_toolkit)
├── web_app.py           # FastAPI WebSocket server
└── templates/           # Web UI assets
```

The key insight: `cli.py`, `web_app.py`, `SubAgent`, and `AgentHandoff` all call the **same** `run_agent_loop()`. Fix a bug there and it propagates everywhere.

---

## Adding a tool

1. **Create the tool file** (or add to an existing file in `tools/`):

```python
# luckyd_code/tools/my_tool.py
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class MyToolResult:
    """Result returned by MyTool."""

    output: str
    success: bool


class MyTool:
    """One-line description of what this tool does."""

    name = "MyTool"
    description = "Does the thing."

    def run(self, *, param: str) -> MyToolResult:
        """Run the tool.

        Parameters
        ----------
        param:
            Description of param.

        Returns
        -------
        MyToolResult
            The result.
        """
        return MyToolResult(output=f"did {param}", success=True)
```

2. **Register it** in `tools/registry.py`:

```python
from .my_tool import MyTool

# Inside ToolRegistry.__init__ or _register_defaults():
self.register(MyTool())
```

3. **Write tests** in `tests/test_my_tool.py` — aim for behaviour coverage, not just line coverage.

4. **Update README.md** — add the tool to the "40+ built-in tools" list or the relevant feature section.

5. **Add a CHANGELOG entry** under `[Unreleased]`.

---

## Testing

```bash
# Run all tests (enforces ≥ 97% coverage)
pytest

# With a full HTML report
pytest --cov=luckyd_code --cov-report=html
open htmlcov/index.html

# Single file
pytest tests/test_router.py -v

# Property-based tests only
pytest tests/test_property_based.py -v

# Type checking
mypy luckyd_code
```

Coverage floor is enforced in CI at **97%**. New code must be tested — unexercised branches block merge.

---

## Ceiling suite

The ceiling suite measures the highest achievable coverage given the omit list in `pyproject.toml`. Run it before raising the `fail_under` threshold:

```bash
# Windows
.testvenv\Scripts\pytest tests/test_ceiling.py -v ^
  --cov=luckyd_code --cov-report=term-missing ^
  2>&1 | tee ceiling_run.txt

# Linux / Mac
.testvenv/bin/pytest tests/test_ceiling.py -v \
  --cov=luckyd_code --cov-report=term-missing \
  2>&1 | tee ceiling_run.txt
```

The file `ceiling_run.txt` is gitignored — don't commit it.

---

## Type checking

Mypy runs in incremental strict mode. Modules are graduated one at a time as they reach full annotation. The current exclusion list is in `pyproject.toml` under `[tool.mypy] exclude`.

To check whether a module is ready to graduate:
```bash
# Temporarily remove it from the exclude list, then:
mypy luckyd_code/the_module.py
```

Fix all errors, then remove it from the exclude list in a dedicated PR. See `TODO.md` for the queue.

---

## Code style

- Python 3.10+ syntax: `X | None` not `Optional[X]`, `list[str]` not `List[str]`
- `%`-style lazy formatting in `logger.*()` calls (not f-strings)
- NumPy-style docstrings on public functions
- Max line length: 100 (configured in `pyproject.toml`)
- Pre-commit runs ruff + gitleaks on every commit

---

## Commit message format

```
type(scope): short description

Longer explanation if needed. References: closes #123.
```

Types: `feat`, `fix`, `chore`, `docs`, `test`, `refactor`, `perf`, `ci`

---

## Pull request process

1. Branch from `main` (`git checkout -b feat/my-feature`)
2. Write tests first if possible (TDD makes the coverage floor easier to hit)
3. Run `pytest` and `mypy luckyd_code` — both must pass
4. Run `pre-commit run --all-files` — must pass (includes gitleaks)
5. Update `CHANGELOG.md` under `[Unreleased]`
6. Open the PR — the template will guide you through the checklist
7. CI runs automatically; address any failures before requesting review

---

## Release checklist

1. Update version in `luckyd_code/__init__.py` and `pyproject.toml`
2. Move `[Unreleased]` entries to a new versioned section in `CHANGELOG.md`
3. Tag: `git tag -a v1.x.y -m "Release v1.x.y"`
4. Push tags: `git push --tags`
5. GitHub Actions publishes to PyPI automatically on tag push

---

## License

By contributing, you agree that your contributions will be licensed under the **GNU Affero General Public License v3**. For alternative licensing (commercial use), contact the maintainer.
