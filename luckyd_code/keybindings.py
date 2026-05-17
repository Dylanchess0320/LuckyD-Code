"""Custom keybinding support."""

import json
from pathlib import Path

from .log import get_logger

from prompt_toolkit.key_binding import KeyBindings


DEFAULT_BINDINGS = {
    "submit": "enter",
    "newline": "alt-enter",
    "cancel": "ctrl-c",
    "history-up": "ctrl-p",
    "history-down": "ctrl-n",
}


from ._data_dir import data_path  # noqa: E402


def get_keybindings_path() -> Path:
    return data_path("keybindings.json")


def load_keybindings() -> dict[str, str]:
    path = get_keybindings_path()
    if path.exists():
        try:
            data = json.loads(path.read_text())
            if isinstance(data, dict):
                return data
        except Exception:
            get_logger().warning("Could not load keybindings from %s", path, exc_info=True)
    return {}


def _parse_key_sequence(key: str) -> tuple:
    """Convert a key string into a tuple of prompt_toolkit key names.

    prompt_toolkit does not understand 'alt-X' — alt combos must be passed
    as the two-key sequence ('escape', 'X').
    """
    if key.startswith("alt-"):
        remainder = key[4:]  # e.g. 'enter', 'a', etc.
        return ("escape", remainder)
    return (key,)


def apply_keybindings() -> KeyBindings:
    """Create KeyBindings from config file, falling back to defaults."""
    user = load_keybindings()
    bindings = {**DEFAULT_BINDINGS, **user}

    kb = KeyBindings()

    submit_key = bindings.get("submit", "enter")
    newline_key = bindings.get("newline", "alt-enter")

    # Enter submits the prompt (works even in multiline mode)
    try:
        @kb.add(*_parse_key_sequence(submit_key))
        def _submit(event):
            event.current_buffer.validate_and_handle()
    except Exception:
        get_logger().warning("Failed to register submit keybinding '%s'", submit_key, exc_info=True)

    # Alt+Enter inserts a newline
    try:
        @kb.add(*_parse_key_sequence(newline_key))
        def _newline(event):
            event.current_buffer.insert_text("\n")
    except Exception:
        get_logger().warning("Failed to register newline keybinding '%s'", newline_key, exc_info=True)

    return kb
