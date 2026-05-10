# Examples

Three working scripts that show LuckyD Code used as a Python library — no CLI required.

---

## `web_scraper.py` — AI-powered web scraping

Fetches a URL, extracts structured data using the model, and saves results as JSON.

```bash
# Scrape Hacker News (default)
python examples/web_scraper.py

# Scrape any URL
python examples/web_scraper.py https://example.com output.json
```

What it demonstrates:
- Embedding LuckyD Code as a library in your own script
- `RunConfig` with `on_text` and `on_tool_start` callbacks for real-time output
- The WebFetch and Write tools working together in one agent turn

---

## `git_automation.py` — Intelligent commit message generation

Reads your git diff, reasons about the changes, and commits with a proper conventional commit message.

```bash
# Preview what the agent would commit (no changes made)
python examples/git_automation.py --dry-run

# Stage, commit
python examples/git_automation.py

# Stage, commit, and push
python examples/git_automation.py --push
```

What it demonstrates:
- Git tools (GitStatus, GitDiff, GitAdd, GitCommit, GitPush) in a real workflow
- Low temperature (`0.2`) for consistent, deterministic output
- `--dry-run` mode using task instructions to control agent behaviour

---

## `parallel_code_review.py` — Multi-agent parallel code review

Runs three specialized agents simultaneously (researcher, tester, reviewer) on a Python file and merges results into a single markdown report.

```bash
python examples/parallel_code_review.py luckyd_code/router.py
# → saves review_router.py_20260510_143201.md
```

What it demonstrates:
- `Coordinator.parallel_orchestrate()` for concurrent multi-agent workflows
- Role-specialized agents (each gets a different system prompt)
- Merging parallel outputs into a structured report

---

## Setup (all examples)

```bash
# 1. Install LuckyD Code
pip install luckyd-code

# 2. Set your API key
echo "DEEPSEEK_API_KEY=your-key-here" > .env

# 3. Run any example from the repo root
python examples/web_scraper.py
```

Get your API key at [platform.deepseek.com/api_keys](https://platform.deepseek.com/api_keys).
