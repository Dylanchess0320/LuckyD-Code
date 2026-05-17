"""Conversation export — markdown and HTML."""

from datetime import datetime
from pathlib import Path


def export_markdown(messages: list, filepath: str | None = None) -> str:
    """Export conversation messages as markdown.

    Args:
        messages: List of message dicts from ConversationContext.
        filepath: Optional path to write the file. If omitted, returns the string.

    Returns:
        The markdown string.
    """
    lines = [
        "# Conversation Export\n",
        f"_Exported: {datetime.now().isoformat()}_\n",
    ]
    for msg in messages:
        role = msg.get("role", "unknown")
        content = str(msg.get("content", ""))
        tool_calls = msg.get("tool_calls")

        if role == "system":
            lines.append(f"## System\n```\n{content}\n```\n")
        elif role == "user":
            lines.append(f"## User\n{content}\n")
        elif role == "assistant":
            if tool_calls:
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    args_str = fn.get("arguments", "")[:500]
                    lines.append(
                        f"## Assistant (tool: {fn.get('name')})\n"
                        f"```json\n{args_str}\n```\n"
                    )
            if content:
                lines.append(f"## Assistant\n{content}\n")
        elif role == "tool":
            tool_id = msg.get("tool_call_id", "?")
            trunc = content[:500]
            if len(content) > 500:
                trunc += f"\n... (truncated, {len(content)} total chars)"
            lines.append(f"## Tool Result ({tool_id})\n```\n{trunc}\n```\n")

    output = "\n".join(lines)
    if filepath:
        Path(filepath).write_text(output, encoding="utf-8")
    return output


def export_html(messages: list, filepath: str | None = None,
                title: str = "Conversation Export") -> str:
    """Export conversation messages as a standalone HTML page.

    Args:
        messages: List of message dicts from ConversationContext.
        filepath: Optional path to write the file.
        title: Page title.

    Returns:
        The HTML string.
    """
    parts = [
        "<!DOCTYPE html>",
        f"<html><head><meta charset='utf-8'><title>{title}</title>",
        "<style>",
        "body { font-family: -apple-system, sans-serif; max-width: 800px; "
        "margin: 2em auto; padding: 0 1em; background: #fafafa; color: #333; }",
        ".msg { margin: 1em 0; padding: 1em; border-radius: 8px; }",
        ".system { background: #e8e8e8; }",
        ".user { background: #dbeafe; }",
        ".assistant { background: #dcfce7; }",
        ".tool { background: #fef3c7; font-family: monospace; font-size: 0.9em; }",
        "pre { background: #1e1e1e; color: #d4d4d4; padding: 1em; border-radius: 4px; "
        "overflow-x: auto; }",
        ".meta { font-size: 0.85em; color: #666; margin-bottom: 0.5em; }",
        "</style></head><body>",
        f"<h1>{title}</h1>",
        f"<p class='meta'>Exported: {datetime.now().isoformat()}</p>",
        "<hr>",
    ]

    for msg in messages:
        role = msg.get("role", "unknown")
        content = str(msg.get("content", ""))
        tool_calls = msg.get("tool_calls")

        if role == "system":
            parts.append(f"<div class='msg system'><div class='meta'>System</div>"
                         f"<pre>{_escape_html(content)}</pre></div>")
        elif role == "user":
            parts.append(f"<div class='msg user'><div class='meta'>User</div>"
                         f"<pre>{_escape_html(content)}</pre></div>")
        elif role == "assistant":
            if tool_calls:
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    parts.append(
                        f"<div class='msg tool'><div class='meta'>Tool: "
                        f"{_escape_html(fn.get('name', ''))}</div>"
                        f"<pre>{_escape_html(fn.get('arguments', '')[:500])}</pre></div>"
                    )
            if content:
                parts.append(f"<div class='msg assistant'><div class='meta'>Assistant</div>"
                             f"<pre>{_escape_html(content)}</pre></div>")
        elif role == "tool":
            tid = msg.get("tool_call_id", "?")
            trunc = content[:500]
            parts.append(
                f"<div class='msg tool'><div class='meta'>Tool Result ({tid})</div>"
                f"<pre>{_escape_html(trunc)}</pre></div>"
            )

    parts.append("</body></html>")
    output = "\n".join(parts)
    if filepath:
        Path(filepath).write_text(output, encoding="utf-8")
    return output


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
