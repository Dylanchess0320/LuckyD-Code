# Skills

The `luckyd_code/skills/` package provides lightweight, reusable analysis
functions that the agent can invoke on demand via slash commands or the
autonomous fixer pipeline.

## Purpose

Skills are **read-only analysis helpers** — they inspect the current project
state (git diff, file contents, metrics) and return a formatted string that
the agent can include in its response or act on. They do not write files or
call the LLM directly.

## Available Skills

### `review` — Code Review

**Module:** `luckyd_code/skills/review.py`
**Entry point:** `review_changes() -> str`

Runs `git diff HEAD` (falling back to `git diff --cached` for staged-only
changes) and returns the diff formatted as a Markdown fenced code block, ready
to paste into a review prompt or display directly.

**Used by:** `/review` slash command, `autonomous_fixer.py` post-patch check.

---

### `security` — Security Review

**Module:** `luckyd_code/skills/security.py`
**Entry points:** `security_review() -> str`, `SecurityFinding` dataclass

Scans added lines in the current git diff for common security anti-patterns
using regex-based static analysis. No network calls, no LLM — runs instantly.

**Detects:**
| Severity | Patterns |
|----------|----------|
| 🔴 HIGH | Hardcoded API keys/tokens, `eval()`/`exec()`, `os.system()`, `shell=True`, SQL string interpolation |
| 🟡 MEDIUM | `pickle.loads()`, path traversal (`../`) |
| 🔵 LOW | Insecure HTTP URLs, `random.randint` for security, MD5, hardcoded absolute paths |

Returns a severity-sorted report with file + line context for each finding.

**Used by:** `/review --security` variant (planned), `audit_daemon.py`.

---

## Adding a New Skill

1. Create a new file in `luckyd_code/skills/`, e.g. `complexity.py`.
2. Write one or more public functions that return `str`.
3. Add `__all__` listing your public functions.
4. Import and re-export from `luckyd_code/skills/__init__.py`.
5. Wire it up to a slash command in `luckyd_code/cli_commands/` or call it
   from `autonomous_fixer.py` / `audit_daemon.py` as appropriate.
6. Add a section to this file describing what the skill does.

### Conventions

- Skills must be **pure functions** with no side effects other than reading
  the filesystem or running read-only subprocess commands.
- Return a **formatted string** (Markdown preferred) so the result can be
  displayed directly in the terminal or web UI.
- Keep dependencies minimal — skills are imported at startup, so heavy imports
  should be deferred inside the function body.
- Timeout subprocess calls (use `timeout=30` or similar) so a slow git repo
  doesn't hang the agent.
