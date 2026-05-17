"""Error reporter — safe, opt-in error telemetry via GitHub Issues.

Captures unhandled exceptions, sanitizes them thoroughly, and opens a
pre-filled GitHub Issue URL in the user's browser so they can review and
submit.  Nothing is sent without explicit user consent.

Settings key:  ``error_reporting``
  - ``"ask"``  (default) — prompt the user before opening the issue
  - ``"off"``  — never prompt; silently log locally only
  - ``"log"``  — write sanitized details to a local log file (no browser)
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import os
import platform
import re
import sys
import urllib.parse
import webbrowser
from datetime import datetime, timezone

# --- Globals ----------------------------------------------------------------

GITHUB_ISSUES_URL = (
    "https://github.com/Dylanchess0320/LuckyD-Code/issues/new"
)

SANITIZE_PATTERNS: list[str] = [
    "DEEPSEEK_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "HUGGINGFACE_TOKEN",
    "TOGETHER_API_KEY",
    "COHERE_API_KEY",
    "MISTRAL_API_KEY",
]

_seen_hashes: set[str] = set()

# Regex for common API key *value* formats (not just the key name).
# These catch key values that leak into error messages, logs, etc.
_API_KEY_VALUE_RE = re.compile(
    r"(?:sk-(?:ant-)?|gh[poru]_|hf_)[a-zA-Z0-9_-]{16,}",
)


def _sanitize_line(line: str) -> str:
    """Redact common secret patterns from a single string."""
    # 1. Redact known API key value patterns (regardless of context)
    line = _API_KEY_VALUE_RE.sub("[REDACTED]", line)

    # 2. Redact key names (env var names that appear in messages)
    for pattern in SANITIZE_PATTERNS:
        if pattern not in line:
            continue
        # key=value style
        needle = f"{pattern}="
        if needle in line:
            idx = line.index(needle)
            rest = line[idx + len(needle) :]
            end = len(rest)
            for c in " \t\n\r\"';":
                pos = rest.find(c)
                if pos != -1 and pos < end:
                    end = pos
            line = line[: idx + len(needle)] + "[REDACTED]" + rest[end:]
        # bare key present (env var name leaked in message)
        elif pattern in line:
            line = line.replace(pattern, "[REDACTED]")
    return line


def _clean_path(filepath: str) -> str:
    """Replace absolute paths with safe, generic labels."""
    cwd = os.getcwd()
    home = str(os.path.expanduser("~"))

    if filepath.startswith(cwd):
        rel = filepath[len(cwd) :].lstrip(os.sep)
        return f"<cwd>/{rel}"
    if filepath.startswith(home):
        return f"~/.../{os.path.basename(filepath)}"
    if "site-packages" in filepath:
        idx = filepath.find("site-packages")
        return f"<venv>/{filepath[idx:]}"
    # Just keep the filename
    return os.path.basename(filepath)


def sanitize_traceback(exc: BaseException) -> dict[str, str]:
    """Build a fully-sanitised dict from a live exception.

    Strips: API keys, absolute file paths, environment-variable values,
    and anything else that could leak user data.
    """
    tb_text = "".join(
        _sanitize_line(line)
        for line in __import__("traceback").format_exception(
            type(exc), exc, exc.__traceback__
        )
    )

    # Second pass: clean paths in the traceback
    cleaned_lines: list[str] = []
    for line in tb_text.split("\n"):
        # File "C:\Users\...\foo.py", line 42, in bar
        cleaned = line
        if 'File "' in line:
            start = line.index('File "') + 6
            end = line.index('"', start)
            path = line[start:end]
            cleaned_path = _clean_path(path)
            cleaned = line[:start] + cleaned_path + line[end:]
        cleaned_lines.append(cleaned)

    return {
        "error_type": type(exc).__name__,
        "error_message": _sanitize_line(str(exc)),
        "traceback": "\n".join(cleaned_lines),
        "python_version": sys.version.split()[0],
        "os": platform.platform(),
        "app_version": _get_version(),
    }


def _get_version() -> str:
    try:
        from .update import get_version  # noqa: PLC0415

        return get_version()
    except Exception:
        return "unknown"


# --- Deduplication ----------------------------------------------------------


def _error_fingerprint(exc: BaseException) -> str:
    """Stable hash for deduplicating identical errors within a session."""
    raw = f"{type(exc).__name__}:{exc}"
    return hashlib.md5(raw.encode(), usedforsecurity=False).hexdigest()[:12]


def already_reported(exc: BaseException) -> bool:
    """Return True if this error was already reported this session."""
    fp = _error_fingerprint(exc)
    if fp in _seen_hashes:
        return True
    _seen_hashes.add(fp)
    return False


# --- GitHub URL Builder -----------------------------------------------------


def build_issue_url(
    error_data: dict[str, str],
    diagnosis: str = "",
    diff: str = "",
    pr_url: str = "",
) -> str:
    """Build a pre-filled GitHub new-issue URL from sanitised error data.

    The user still has to click *Submit new issue* on GitHub — we never post
    anything automatically.

    Args:
        error_data: Sanitised traceback dict from ``sanitize_traceback``.
        diagnosis: Optional LLM diagnosis Markdown (from autonomous mode).
        diff: Optional unified diff (from autonomous fix mode).
        pr_url: Optional PR URL (from autonomous full mode).
    """
    # Truncate traceback for URL length limits (browsers handle 2 MB, but
    # GitHub's title+body limit is ~64 KB; we keep it well under that).
    tb_preview = error_data["traceback"]
    if len(tb_preview) > 3000:
        tb_preview = tb_preview[:3000] + "\n... (truncated)"

    title = urllib.parse.quote(
        f"[auto-report] {error_data['error_type']}: "
        f"{error_data['error_message'][:60]}",
        safe="",
    )

    # Build extra sections for autonomous improvement
    extra_sections = ""

    if diagnosis:
        extra_sections += f"""

{diagnosis}
"""

    if diff:
        diff_preview = diff
        extra_sections += f"""
<details>
<summary><b>Proposed Fix (diff)</b></summary>

```diff
{diff_preview}
```

</details>
"""

    if pr_url:
        extra_sections += f"""

**PR created:** {pr_url}
"""

    body = urllib.parse.quote(
        f"""\
## Error Report (auto-generated by luckyd-code)

**Error Type:** `{error_data['error_type']}`
**Message:** `{error_data['error_message']}`
**Version:** {error_data['app_version']}
**Python:** {error_data['python_version']}
**OS:** {error_data['os']}

<details>
<summary><b>Traceback</b></summary>

```
{tb_preview}
```

</details>
{extra_sections}
---
*This issue was pre-filled by LuckyD Code's built-in error reporter.
The human user reviewed the content above before submitting.*
""",
        safe="",
    )

    return f"{GITHUB_ISSUES_URL}?title={title}&body={body}"


# --- Local Logging (offline / 'log' mode) -----------------------------------


def _log_to_file(exc: BaseException) -> Path:
    """Write a sanitised error report to a local file. Returns the path."""
    data = sanitize_traceback(exc)
    from ._data_dir import data_path  # noqa: PLC0415

    log_dir = data_path("error-reports")
    log_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    fname = log_dir / f"error-{timestamp}-{_error_fingerprint(exc)}.json"
    fname.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return fname


# --- Main API ---------------------------------------------------------------


def capture_unhandled(exc: BaseException) -> bool:
    """Entry point for unhandled-exception reporting.

    Behaviour is controlled by the ``error_reporting`` setting:

    ────────  ────────────────────────────────────────────────────
    ``"off"``  Do nothing (return False).
    ``"log"``  Write a sanitised report to a local file.
    ``"ask"``  Prompt the user, then open a GitHub Issue URL in
               their browser if they consent (the default).
    ────────  ────────────────────────────────────────────────────

    Returns True if the browser was opened (or the file was written).
    """
    mode = _get_reporting_mode()

    if mode == "off":
        return False

    if already_reported(exc):
        return False

    if mode == "log":  # pragma: no cover
        path = _log_to_file(exc)
        try:
            from .log import get_logger  # noqa: PLC0415

            get_logger().info("Error report saved to %s", path)
        except Exception:
            pass
        return True

    # mode == "ask" — interactive
    return _ask_and_open(exc)  # pragma: no cover


def _get_reporting_mode() -> str:
    """Read the ``error_reporting`` setting (case-insensitive)."""
    try:
        from . import settings  # noqa: PLC0415

        s = settings.load_settings()
        val = str(s.get("error_reporting", "ask")).strip().lower()
        if val in ("off", "log", "ask"):
            return val
    except Exception:
        pass
    return "ask"


def _get_api_key() -> str:
    """Get the configured API key from config or environment."""
    try:
        from .config import Config  # noqa: PLC0415
        cfg = Config()
        return cfg.api_key
    except Exception:
        pass
    return ""


def _get_autonomous_mode() -> str:
    """Read the ``autonomous_improvement`` setting (case-insensitive).

    ────────────  ───────────────────────────────────────────────────
    ``"off"``     Just open the GitHub Issue URL.
                  (use this if you want the old behaviour)
    ``"analyze"`` Report + LLM diagnosis appended to the issue.
    ``"fix"``     Report + diagnosis + generate patch, show diff.
    ``"full"``    Report + diagnosis + patch + validate + create PR.
    ────────────  ───────────────────────────────────────────────────
    """
    try:
        from . import settings  # noqa: PLC0415
        s = settings.load_settings()
        val = str(s.get("autonomous_improvement", "fix")).strip().lower()
        if val in ("off", "analyze", "fix", "full"):
            return val
    except Exception:
        pass
    return "fix"


def _ask_and_open(exc: BaseException) -> bool:  # pragma: no cover
    """Prompt the user and — if they consent — open a GitHub issue URL.

    If ``autonomous_improvement`` is enabled, also runs LLM diagnosis, fix
    generation, and/or PR creation depending on the setting level.
    """
    try:
        from rich.console import Console  # noqa: PLC0415

        console = Console()
    except Exception:
        console = None  # type: ignore[assignment]

    try:
        input_fn = __builtins__["input"]  # type: ignore[index]
    except (KeyError, TypeError):
        input_fn = input

    if console:
        console.print(
            "\n[bold yellow]:pensive: Oops! Something unexpected happened.[/bold yellow]"
        )
        console.print(
            "[dim]Help improve LuckyD Code by reporting this? "
            "A GitHub issue page will open in your browser for review — "
            "[bold]you[/bold] decide whether to submit.[/dim]"
        )
    else:
        print(
            "\n:pensive: Oops! Something unexpected happened.\n"
            "Help improve LuckyD Code by reporting this? "
            "A GitHub issue page will open in your browser for review — "
            "YOU decide whether to submit."
        )

    try:
        answer = input_fn("  Report issue? [Y/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False

    if answer not in ("", "y", "yes"):
        if console:
            console.print("[dim]Skipped. You can report later at:\n"
                          "  https://github.com/Dylanchess0320/LuckyD-Code/issues[/dim]")
        return False

    error_data = sanitize_traceback(exc)

    # ── Autonomous Improvement Pipeline ──────────────────────────
    auto_mode = _get_autonomous_mode()
    diagnosis_text = ""
    pr_url = ""
    diff_preview = ""

    if auto_mode != "off":
        api_key = _get_api_key()
        if not api_key:
            if console:
                console.print("[dim]Autonomous improvement skipped: no API key configured.[/dim]")
        else:
            if console:
                console.print(f"[dim]Running autonomous diagnosis (mode: {auto_mode})...[/dim]")

            try:
                from .feedback_analyzer import analyze_error  # noqa: PLC0415

                diagnosis = analyze_error(exc, api_key)
                if diagnosis:
                    diagnosis_text = diagnosis.to_markdown()
                    if console:
                        console.print(
                            f"\n[bold cyan]Diagnosis (confidence: {diagnosis.confidence}):[/bold cyan]"
                        )
                        console.print(f"  {diagnosis.root_cause}")
                        console.print(f"  Suggested: {diagnosis.fix_suggestion}")
                else:
                    if console:
                        console.print("[dim]Diagnosis failed — the LLM could not determine root cause.[/dim]")

            except Exception as diag_err:
                if console:
                    console.print(f"[dim]Diagnosis error: {diag_err}[/dim]")

        # "fix" and "full" mode: generate a fix
        if auto_mode in ("fix", "full") and api_key:
            try:
                from .autonomous_fixer import (  # noqa: PLC0415
                    full_autonomous_pipeline,
                )

                create_pr_flag = (auto_mode == "full")

                if console:
                    console.print("[dim]Generating and validating fix...[/dim]")

                fix_result = full_autonomous_pipeline(
                    exc, api_key, create_pr_flag=create_pr_flag,
                )

                if fix_result.diff:
                    diff_preview = fix_result.diff[:3000]
                    if len(fix_result.diff) > 3000:
                        diff_preview += "\n... (truncated)"

                if fix_result.success:
                    if console:
                        console.print("\n[bold green]Fix generated and validated! Patch attached to report.[/bold green]")
                        if fix_result.pr_url:
                            console.print(f"[bold green]PR created: {fix_result.pr_url}[/bold green]")
                            pr_url = fix_result.pr_url
                        else:
                            console.print("[dim]Patch will be included in the issue for the maintainer to review.[/dim]")
                else:
                    if fix_result.error:
                        if console:
                            console.print(f"[yellow]Fix could not be completed: {fix_result.error}[/yellow]")
                    elif not fix_result.diff:
                        if console:
                            console.print("[yellow]Fix generation failed — "
                                          "LLM could not produce a patch.[/yellow]")
                    else:
                        if console:
                            console.print(f"[yellow]Fix validation failed. "
                                          f"Diff available on branch {fix_result.branch_name}.[/yellow]")

            except Exception as fix_err:
                if console:
                    console.print(f"[dim]Fix pipeline error: {fix_err}[/dim]")

    # ── Build and open the issue URL ──────────────────────────────
    url = build_issue_url(error_data, diagnosis=diagnosis_text, diff=diff_preview, pr_url=pr_url)

    try:
        print("  Opening browser …")
        webbrowser.open_new_tab(url)
        return True
    except Exception:
        print(f"  Could not open your browser. Copy this URL:\n\n  {url}")
        return False


def capture_and_log_only(exc: BaseException) -> None:
    """Non-interactive: log the error locally without any user prompt.

    Useful for background threads / daemons where interaction is impossible.
    """
    from .log import get_logger

    data = sanitize_traceback(exc)
    get_logger().error(
        "Unhandled error: %s: %s",
        data["error_type"],
        data["error_message"],
    )
