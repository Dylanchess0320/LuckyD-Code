"""Simple permissions system for tool execution."""

import json
import logging
from pathlib import Path

from .._data_dir import project_data_path

_logger = logging.getLogger("luckyd_code.permissions")


# Risk levels
RISK_SAFE = "safe"      # Always allowed
RISK_MEDIUM = "medium"  # Prompt user
RISK_HIGH = "high"      # Always prompt

TOOL_RISKS = {
    "Read": RISK_SAFE,
    "Glob": RISK_SAFE,
    "Grep": RISK_SAFE,
    "WebFetch": RISK_SAFE,
    "WebSearch": RISK_SAFE,
    "Write": RISK_MEDIUM,
    "Edit": RISK_MEDIUM,
    "Bash": RISK_HIGH,
    "GitStatus": RISK_MEDIUM,
    "GitDiff": RISK_MEDIUM,
    "GitLog": RISK_SAFE,
    "GitBranch": RISK_SAFE,
    "GitAdd": RISK_MEDIUM,
    "GitCommit": RISK_HIGH,
    "GitPush": RISK_HIGH,
    "GitPR": RISK_HIGH,
    "GitWorktree": RISK_HIGH,
    "SubAgent": RISK_MEDIUM,
    "AgentHandoff": RISK_MEDIUM,
    "BrainSearch": RISK_SAFE,
    "BrainStatus": RISK_SAFE,
}


def _get_settings_path() -> Path:
    return project_data_path("settings.local.json")


def _load_allowlist() -> set[str]:
    path = _get_settings_path()
    if path.exists():
        try:
            data = json.loads(path.read_text())
            return set(data.get("allowed_tools", []))
        except Exception:
            _logger.warning("Failed to load allowlist from %s", path, exc_info=True)
            return set()
    return set()


def _save_to_allowlist(tool_name: str):
    path = _get_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    allowlist = _load_allowlist()
    allowlist.add(tool_name)
    data = {"allowed_tools": list(allowlist)}
    path.write_text(json.dumps(data, indent=2))


def check_permission(tool_name: str) -> bool:
    """Check if a tool is allowed. Returns True if allowed, False if blocked."""
    if tool_name in _load_allowlist():
        return True

    risk = TOOL_RISKS.get(tool_name, RISK_HIGH)
    if risk == RISK_SAFE:
        return True
    if risk == RISK_MEDIUM:
        return _prompt_user(tool_name, risk)
    return _prompt_user(tool_name, risk)


def _prompt_user(tool_name: str, risk: str) -> bool:
    """Prompt user for permission. Returns True if approved."""
    risk_label = {"medium": "moderate risk", "high": "HIGH risk"}.get(risk, risk)
    print(f"\n[Permission] Allow {tool_name}? ({risk_label})")
    print("  a = allow once | y = always allow | n = deny | s = skip")
    attempts = 0
    while attempts < 3:
        try:
            choice = input("  [a/y/n/s]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return False

        if choice == "y":
            _save_to_allowlist(tool_name)
            return True
        if choice in ("a", ""):
            return True
        if choice in ("n", "s"):
            return False
        attempts += 1
        print(f"  Invalid input '{choice}' — enter a (allow once), y (always allow), n (deny), or s (skip)")
    print("  Too many invalid attempts. Denying permission.")
    return False
