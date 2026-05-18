"""settings.json and hooks support."""

import json
from pathlib import Path
from typing import Any, cast

from .log import get_logger
from ._data_dir import project_data_path


def get_settings_dir() -> Path:
    return project_data_path()


def get_settings_path() -> Path:
    return get_settings_dir() / "settings.json"


def get_local_settings_path() -> Path:
    return get_settings_dir() / "settings.local.json"


def load_settings() -> dict[str, Any]:
    settings = {}
    for p in [get_settings_path(), get_local_settings_path()]:
        if p.exists():
            try:
                data = json.loads(p.read_text())
                settings.update(data)
            except Exception:
                get_logger().warning("Could not load settings from %s", str(p), exc_info=True)
    return settings


def save_setting(key: str, value: Any) -> None:
    path = get_local_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    settings = {}
    if path.exists():
        try:
            settings = json.loads(path.read_text())
        except Exception:
            get_logger().warning("Could not load existing settings from %s", str(path), exc_info=True)
    settings[key] = value
    path.write_text(json.dumps(settings, indent=2))


def get_hooks() -> dict[str, Any]:
    settings = load_settings()
    return cast(dict[str, Any], settings.get("hooks", {}))


def run_pre_hook(tool_name: str) -> list[str]:
    hooks = get_hooks()
    hook_cfg = hooks.get("preToolUse", "")
    # Normalise: the hook may be a plain string or a dict with a 'script' key
    if isinstance(hook_cfg, dict):
        script = hook_cfg.get("script", "")
        # 'tools' is nested inside the hook config, not at the top level
        allowed_tools = hook_cfg.get("tools", ["all"])
    else:
        script = hook_cfg
        allowed_tools = ["all"]
    if script and ("all" in allowed_tools or tool_name in allowed_tools):
        import subprocess
        try:
            r = subprocess.run(script, shell=True, capture_output=True, text=True, timeout=30)
            if r.returncode != 0:
                return [r.stderr.strip()]
        except Exception as e:
            return [str(e)]
    return []
