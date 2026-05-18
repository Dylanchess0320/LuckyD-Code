"""Feedback Analyzer — LLM-powered error diagnosis for autonomous self-improvement.

Takes a sanitized error, gathers code context from the project, and uses the
user's own DeepSeek API key to diagnose the root cause and suggest a fix.

All analysis runs locally on the user's machine.  Nothing is sent to any
central server.  The user's API key is used directly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from .error_reporter import sanitize_traceback

__all__ = ["Diagnosis", "analyze_error"]

# ------------------------------------------------------------------ #
#  Data model
# ------------------------------------------------------------------ #


@dataclass
class Diagnosis:
    """Structured result of LLM-powered error analysis."""

    error_type: str
    error_message: str
    root_cause: str            # Natural-language explanation of the root cause
    affected_files: list[str]  # Relative paths of files that need changing
    fix_suggestion: str        # Concrete fix description
    confidence: str            # "high" | "medium" | "low"
    raw_analysis: str = ""     # Full LLM response for debugging

    def to_markdown(self) -> str:
        """Format as a GitHub-issue-ready Markdown section."""
        files_list = "\n".join(f"   - `{f}`" for f in self.affected_files) or "   - (none)"
        return f"""\
### 🤖 Autonomous Diagnosis

**Root Cause:** {self.root_cause}

**Affected files:**
{files_list}

**Suggested Fix:** {self.fix_suggestion}

**Confidence:** `{self.confidence}`
"""


# ------------------------------------------------------------------ #
#  LLM call helpers
# ------------------------------------------------------------------ #

ANALYSIS_SYSTEM_PROMPT = """You are a senior software engineer analyzing a bug in the **LuckyD Code** project — an open-source AI coding assistant that runs in the terminal.

You will receive:
1. An error report (type, message, traceback)
2. Relevant source code snippets from the project

Your task: diagnose the ROOT CAUSE and propose a SPECIFIC, CONCRETE fix.

CRITICAL:
- Only suggest changes to LuckyD Code's OWN source code (luckyd_code/ and tests/)
- Do NOT suggest changes to the user's project or third-party libraries
- Be precise about which file(s) and what lines need to change
- Consider error handling gaps, edge cases, type issues, and import problems
- If you cannot determine the root cause from the provided context, say so honestly

Respond in this EXACT JSON format (no other text):
```json
{
  "root_cause": "...",
  "affected_files": ["path/relative/to/project/root.py"],
  "fix_suggestion": "...",
  "confidence": "high|medium|low"
}
```"""


def _get_relevant_files(error_data: dict[str, str], project_root: str) -> dict[str, str]:
    """Collect source files mentioned in the traceback or likely relevant.

    Returns a dict of {relative_path: file_contents} — at most 5 files,
    truncated to 200 lines each.
    """
    tb = error_data.get("traceback", "")
    relevant: dict[str, str] = {}
    root = Path(project_root).resolve()

    # Extract file references from traceback
    for line in tb.split("\n"):
        if "luckyd_code" in line and ".py" in line:
            # Try to extract a relative path
            import re
            m = re.search(r'([\w/.-]*luckyd_code/[\w/.-]+\.py)', line)
            if m:
                rel = m.group(1)
                abs_path = root / rel
                if abs_path.exists() and rel not in relevant:
                    try:
                        content = abs_path.read_text(encoding="utf-8")
                        lines = content.split("\n")
                        if len(lines) > 200:
                            content = "\n".join(lines[:200]) + "\n... (file truncated)"
                        relevant[rel] = content
                    except Exception:
                        pass

    # If we found fewer than 3 files, try to read files referenced by error message
    if len(relevant) < 3:
        msg = error_data.get("error_message", "")
        for part in msg.replace("'", " ").replace('"', " ").split():
            if ".py" in part:
                candidate = root / part
                if candidate.exists() and str(candidate.relative_to(root)) not in relevant:
                    try:
                        content = candidate.read_text(encoding="utf-8")
                        lines = content.split("\n")
                        if len(lines) > 200:
                            content = "\n".join(lines[:200]) + "\n... (file truncated)"
                        relevant[str(candidate.relative_to(root))] = content
                    except Exception:
                        pass

    return dict(list(relevant.items())[:5])


def _call_llm(
    system_prompt: str,
    user_message: str,
    api_key: str,
    base_url: str = "https://api.deepseek.com/v1",
    model: str = "deepseek-v4-flash",
    timeout: float = 30.0,
) -> str:
    """Make a single synchronous (non-streaming) LLM call.

    Returns the response text, or an error string starting with "ERROR:".
    """
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "max_tokens": 2048,
        "temperature": 0.1,  # Low temperature for deterministic analysis
        "stream": False,
    }

    try:
        with httpx.Client(timeout=httpx.Timeout(timeout, connect=10.0)) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            return str(content).strip()
    except httpx.HTTPStatusError as e:
        body = e.response.text[:500] if e.response else ""
        return f"ERROR: HTTP {e.response.status_code if e.response else '?'}: {body}"
    except httpx.TimeoutException:
        return "ERROR: LLM request timed out"
    except Exception as e:
        return f"ERROR: {e}"


def _parse_diagnosis_json(raw: str) -> dict[str, Any] | None:
    """Extract JSON from an LLM response that may have markdown fences."""
    if not raw or raw.startswith("ERROR:"):
        return None
    # Try to extract JSON from ```json ... ``` fences
    import re
    m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', raw, re.DOTALL)
    if m:
        try:
            return dict(json.loads(m.group(1)))  # type: ignore[return-value]
        except json.JSONDecodeError:
            pass
    # Try parsing the whole response as JSON
    try:
        return dict(json.loads(raw))  # type: ignore[return-value]
    except json.JSONDecodeError:
        pass
    # Try finding a bare JSON object
    m = re.search(r'\{[^{}]*"root_cause"[^{}]*\}', raw, re.DOTALL)
    if m:
        try:
            return dict(json.loads(m.group(0)))  # type: ignore[return-value]
        except json.JSONDecodeError:
            pass
    return None


# ------------------------------------------------------------------ #
#  Main API
# ------------------------------------------------------------------ #


def analyze_error(
    exc_or_data: BaseException | dict[str, str],
    api_key: str,
    base_url: str = "https://api.deepseek.com/v1",
    model: str = "deepseek-v4-flash",
    project_root: str = "",
) -> Diagnosis | None:
    """Analyze an error with LLM-powered root cause diagnosis.

    Args:
        exc_or_data: Either a live exception or a sanitized traceback dict.
        api_key: DeepSeek API key (the user's own).
        base_url: API base URL.
        model: Model name to use.
        project_root: Root of the LuckyD Code project (auto-detected if empty).

    Returns:
        A Diagnosis on success, None if analysis failed or no root cause found.
    """
    # Resolve project root
    if not project_root:
        project_root = str(Path(__file__).resolve().parent.parent)

    # Sanitize if given a live exception
    if isinstance(exc_or_data, BaseException):
        error_data = sanitize_traceback(exc_or_data)
    else:
        error_data = exc_or_data

    # Gather code context
    file_context = _get_relevant_files(error_data, project_root)

    # Build user message
    context_section = ""
    if file_context:
        context_section = "## Relevant Source Code\n\n"
        for fpath, content in file_context.items():
            context_section += f"### {fpath}\n```python\n{content}\n```\n\n"
    else:
        context_section = "## Relevant Source Code\n(No relevant files could be extracted from the traceback.)\n"

    user_message = f"""## Error Report

**Error Type:** `{error_data['error_type']}`
**Message:** `{error_data['error_message']}`
**Python:** {error_data.get('python_version', 'unknown')}
**OS:** {error_data.get('os', 'unknown')}

## Traceback

```
{error_data['traceback']}
```

{context_section}"""

    # Call LLM
    raw = _call_llm(
        system_prompt=ANALYSIS_SYSTEM_PROMPT,
        user_message=user_message,
        api_key=api_key,
        base_url=base_url,
        model=model,
    )

    if raw.startswith("ERROR:"):
        return None

    parsed = _parse_diagnosis_json(raw)
    if not parsed:
        return None

    return Diagnosis(
        error_type=error_data["error_type"],
        error_message=error_data["error_message"],
        root_cause=parsed.get("root_cause", "Unknown"),
        affected_files=parsed.get("affected_files", []),
        fix_suggestion=parsed.get("fix_suggestion", ""),
        confidence=parsed.get("confidence", "low"),
        raw_analysis=raw,
    )
