# Contributing to LuckyD Code

This document supplements [CONTRIBUTING.md](../CONTRIBUTING.md) with technical how-tos for common contributor tasks.

---

## How to add a new tool

Tools are the primary extension point. A tool is a class with a `run()` method that the agent loop can call.

### 1. Create the tool file

Create `luckyd_code/tools/my_tool.py`:

```python
"""My tool — one-line summary."""

from typing import Any
from .decorators import tool


@tool(
    name="MyTool",
    description="Clear description of what the tool does and when the agent should use it.",
)
class MyTool:
    """Full docstring explaining args, return value, and side effects."""

    def run(self, *, param_one: str, param_two: int = 0) -> str:
        """Execute the tool.

        Args:
            param_one: Description of param_one.
            param_two: Description of param_two (optional).

        Returns:
            A string result the agent will see in its next context window.
        """
        # Implementation here
        return f"Result: {param_one}"
```

Guidelines:
- Return a `str` — the agent reads tool output as plain text.
- Keep the description specific. The agent uses it for tool selection.
- Raise `ValueError` for invalid inputs; the registry catches and formats errors.
- For read-only tools (no side effects), the registry will cache results for 5 minutes automatically.

### 2. Register the tool

Open `luckyd_code/tools/registry.py` and add two lines:

```python
# At the top with other imports
from .my_tool import MyTool

# Inside _TOOL_CLASSES list
_TOOL_CLASSES = [
    ...,
    MyTool,   # ← add here
]
```

### 3. Write tests

Create `tests/test_my_tool.py`:

```python
"""Tests for MyTool."""

import pytest
from luckyd_code.tools.my_tool import MyTool


def test_my_tool_basic():
    tool = MyTool()
    result = tool.run(param_one="hello")
    assert "hello" in result


def test_my_tool_invalid_input():
    tool = MyTool()
    with pytest.raises(ValueError):
        tool.run(param_one="")
```

Coverage requirement: new tools must hit **95%+ branch coverage** to pass CI.

### 4. Update README

Add your tool to the appropriate category in the **Tools Gallery** section of `README.md`.

---

## How to run the ceiling suite

The "ceiling suite" is a full test run that proves the project's coverage stays at or above the configured floor (`fail_under` in `pyproject.toml`).

### Quick run (uses the test venv)

```bat
REM Windows — run from the project root
.testvenv\Scripts\pytest tests/ -v --tb=short ^
  --cov=luckyd_code --cov-report=term-missing ^
  2>&1 | tee ceiling_run.txt
```

```bash
# macOS / Linux
.testvenv/bin/pytest tests/ -v --tb=short \
  --cov=luckyd_code --cov-report=term-missing \
  2>&1 | tee ceiling_run.txt
```

The output is saved to `ceiling_run.txt` so you can compare runs across commits.

### Running a single test file

```bash
pytest tests/test_my_tool.py -v --tb=short
```

### Running with the HTML coverage report

```bash
pytest --cov=luckyd_code --cov-report=html
# Open htmlcov/index.html in your browser
```

### Checking a single module's coverage

```bash
pytest --cov=luckyd_code --cov-report=term-missing \
       --cov-config=pyproject.toml \
  | grep "luckyd_code/my_module"
```

### CI equivalent (what GitHub Actions runs)

```bash
pytest -v --tb=short --cov=luckyd_code --cov-report=xml
```

---

## Type checking

All modules outside the exclusion list in `pyproject.toml` must pass mypy strict:

```bash
mypy luckyd_code --ignore-missing-imports
```

To check a single module:

```bash
mypy luckyd_code/tools/my_tool.py --ignore-missing-imports
```

When adding a new module, add it to the mypy exclusion list **only** if it has unavoidable third-party stubs issues (e.g. Playwright, FAISS). Otherwise, type it fully and leave it out of the exclusion list.

---

## Pre-commit hooks

Install the hooks once after cloning:

```bash
pip install pre-commit
pre-commit install
```

The hooks run automatically on `git commit`:
- `gitleaks` — scans staged files for secrets before they hit git history
- Standard formatting and lint checks

To run manually on all files:

```bash
pre-commit run --all-files
```

---

## Commit message format

```
<type>: <short summary>

<optional body — explain *why*, not *what*>
```

Types: `fix`, `feat`, `test`, `docs`, `refactor`, `chore`, `ci`

Examples:
```
fix: guard against empty brain graph on first run
feat: add install-rag CLI subcommand
test: cover ImprovementTracker.report() commit path
docs: add contributing.md tool and ceiling suite guides
```

---

## Release checklist

Before tagging a release:

1. Run the full ceiling suite and confirm `fail_under` passes
2. Run `mypy luckyd_code --ignore-missing-imports` — zero errors
3. Run `pre-commit run --all-files` — all hooks pass
4. Update `CHANGELOG.md` with the new version entry
5. Bump the version in `pyproject.toml` and `luckyd_code/__init__.py`
6. Tag: `git tag v1.x.y && git push --tags`
