"""Session save/load — persist and restore conversations."""

import json
import os
from datetime import datetime

from .context import ConversationContext

from ._data_dir import data_path

SESSIONS_DIR = data_path("sessions")


def _ensure_dir():
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def _sanitize_name(name: str) -> str:
    """Sanitize a session name for use as a filename."""
    safe = "".join(c if c.isalnum() or c in " _-" else "_" for c in name)
    return safe.strip() or "unnamed"


def save_session(name: str, context: ConversationContext) -> str:
    """Save current conversation to a session file."""
    _ensure_dir()
    safe = _sanitize_name(name)
    path = SESSIONS_DIR / f"{safe}.json"

    # Filter out the system prompt — it's re-applied from the live config on load,
    # so storing it would restore a potentially stale prompt on future loads.
    messages = [m for m in context.messages if m.get("role") != "system"]

    data = {
        "name": name,
        "saved_at": datetime.now().isoformat(),
        "message_count": len(messages),
        "messages": messages,
    }

    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return f"Session '{name}' saved ({len(messages)} messages)"


def load_session(name: str, context: ConversationContext) -> str:
    """Load a session into the current context."""
    _ensure_dir()
    safe = _sanitize_name(name)
    path = SESSIONS_DIR / f"{safe}.json"

    if not path.exists():
        # Try partial match
        matches = list(SESSIONS_DIR.glob(f"{safe}*.json"))
        if not matches:
            return f"Session '{name}' not found"
        path = matches[0]

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return f"Error loading session: {e}"

    messages = data.get("messages", [])
    if not messages:
        return "Session is empty"

    # Preserve system prompt, replace everything else
    system = context.messages[0] if context.messages else None
    if messages[0].get("role") == "system":
        context.messages = messages
    else:
        context.messages = [system] + messages if system else messages

    # Re-apply max_messages
    while len(context.messages) > context.max_messages:
        context.messages.pop(1)

    return f"Session '{data.get('name', name)}' loaded ({len(messages)} messages)"


def list_sessions() -> str:
    """List all saved sessions."""
    _ensure_dir()
    sessions = []
    for path in sorted(SESSIONS_DIR.glob("*.json"), key=os.path.getmtime, reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            sessions.append({
                "name": data.get("name", path.stem),
                "saved_at": data.get("saved_at", "unknown"),
                "count": data.get("message_count", 0),
            })
        except Exception:
            sessions.append({"name": path.stem, "saved_at": "unknown", "count": 0})

    if not sessions:
        return "No saved sessions."

    lines = []
    for s in sessions:
        time = s["saved_at"][:19] if s["saved_at"] != "unknown" else "unknown"
        lines.append(f"  {s['name']:20s} ({s['count']} msgs, saved {time})")
    return "\n".join(lines)


def delete_session(name: str) -> str:
    """Delete a saved session."""
    _ensure_dir()
    safe = _sanitize_name(name)
    path = SESSIONS_DIR / f"{safe}.json"
    if path.exists():
        path.unlink()
        return f"Session '{name}' deleted"
    return f"Session '{name}' not found"
