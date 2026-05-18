"""Lifecycle hooks system — pre/post tool use, pre/post chat, session events.

Hooks are shell scripts defined in .luckyd-code/settings.local.json:

    {
      "hooks": {
        "preToolUse": {
          "script": "echo 'About to run $LDC_TOOL_NAME'",
          "tools": ["all"]
        },
        "postToolUse": "npm run lint-changed",
        "preChat": "echo 'Sending request to $LDC_MODEL'",
        "postChat": "echo 'Response received'",
        "onSessionStart": "echo 'Session started at $LDC_TIME'",
        "onSessionEnd": "echo 'Session ended'"
      }
    }

Hooks can return JSON on their first line to control execution:
  {"allow": false}     — block the tool call (preToolUse only)
  {"env": {"K": "v"}} — update environment variables

Environment variables injected into every hook script:
  LDC_HOOK_EVENT   — the hook event name (e.g. preToolUse)
  LDC_PROJECT_DIR  — absolute path to the project root
  LDC_TIME         — ISO-8601 timestamp when the hook fired
  LDC_TOOL_NAME    — (preToolUse / postToolUse only) name of the tool
  LDC_MODEL        — (preChat only) model being used
"""

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .settings import load_settings, get_settings_dir


HOOK_EVENTS = [
    "preToolUse",
    "postToolUse",
    "preChat",
    "postChat",
    "onSessionStart",
    "onSessionEnd",
]


@dataclass
class HookResult:
    success: bool = True
    output: str = ""
    error: str | None = None
    allow: bool = True           # preToolUse: block or allow the tool call
    env_updates: dict[str, Any] = field(default_factory=dict)


class HookRunner:
    """Execute shell-based hooks for lifecycle events."""

    def __init__(self) -> None:
        self.settings = load_settings()

    def run_hook(self, event: str, context: dict[str, Any] | None = None) -> list[HookResult]:
        """Run all hooks configured for an event.

        Args:
            event: One of HOOK_EVENTS.
            context: Dict of extra env vars to pass (e.g. tool_name, tool_args).

        Returns:
            List of HookResult, one per hook script.
        """
        if event not in HOOK_EVENTS:
            return [HookResult(success=False, error=f"Unknown hook event: {event}")]

        scripts = self._get_hook_scripts(event)
        results = []
        for hook_cfg in scripts:
            script = hook_cfg.get("script", "")
            if not script:
                continue
            # Check tool filter if present
            tool_filter = hook_cfg.get("tools", ["all"])
            if "all" not in tool_filter:
                tool_name = (context or {}).get("tool_name", "")
                if tool_name not in tool_filter:
                    continue
            result = self._execute_script(script, event, context)
            results.append(result)
        return results

    def _get_hook_scripts(self, event: str) -> list[dict[str, Any]]:
        """Get all hook scripts for an event from settings.

        Returns empty for unknown (not in HOOK_EVENTS) event types
        even if hooks are configured — prevents misconfiguration.
        """
        if event not in HOOK_EVENTS:
            return []
        hooks: dict[str, object] = self.settings.get("hooks", {})
        raw = hooks.get(event, "")
        if isinstance(raw, str):
            return [{"script": raw, "tools": ["all"]}] if raw else []
        elif isinstance(raw, dict):
            # Single hook config
            if "script" in raw:
                return [raw]
            # Multiple hook configs keyed by name
            return list(raw.values())
        elif isinstance(raw, list):
            return raw
        return []

    def _parse_script_output(
        self, output: str, returncode: int, stderr: str, hook_label: str
    ) -> HookResult:
        """Build a HookResult from subprocess output — shared by shell and Python hooks."""
        if returncode != 0 and stderr.strip():
            return HookResult(success=False, error=stderr.strip(), output=output.strip())

        output = output.strip()
        if output:
            first_line = output.split("\n")[0]
            if first_line.startswith("{"):
                try:
                    data = json.loads(first_line)
                    output = "\n".join(output.split("\n")[1:])
                    return HookResult(
                        success=True,
                        output=output,
                        allow=data.get("allow", True),
                        env_updates=data.get("env", {}),
                    )
                except json.JSONDecodeError:
                    pass

        return HookResult(success=True, output=output)

    def _execute_script(self, script: str, event: str,
                        context: dict[str, Any] | None = None) -> HookResult:
        """Execute a single hook script and return the result.

        Supports both shell commands and ``.py`` scripts.  Python scripts
        are launched via ``sys.executable`` with the same environment
        variables, so they work portably across platforms.
        """
        env = {
            "LDC_HOOK_EVENT": event,
            "LDC_PROJECT_DIR": str(get_settings_dir().parent),
            "LDC_TIME": __import__("datetime").datetime.now().isoformat(),
        }
        if context:
            for k, v in context.items():
                env[f"LDC_{k.upper()}"] = str(v)

        full_env = {**os.environ, **env}

        # Detect Python hook scripts
        script_path = Path(script)
        if script_path.suffix == ".py":
            return self._run_python_script(script_path, event, full_env)

        try:
            proc = subprocess.run(
                script,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
                env=full_env,
            )
            return self._parse_script_output(
                proc.stdout, proc.returncode, proc.stderr, event
            )
        except subprocess.TimeoutExpired:
            return HookResult(success=False, error=f"Hook '{event}' timed out after 30s")
        except FileNotFoundError:
            return HookResult(success=False, error=f"Hook '{event}' command not found: {script[:100]}")
        except Exception as e:
            return HookResult(success=False, error=f"Hook '{event}' error: {e}")

    def _run_python_script(self, script_path: Path, event: str,
                           full_env: dict[str, str]) -> HookResult:
        """Execute a ``.py`` hook script with the current Python interpreter.

        The script receives all ``LDC_*`` environment variables and can
        return JSON on its first stdout line for execution control
        (same protocol as shell hooks).
        """
        # Merge with os.environ so the child process inherits essential
        # system variables (PATH, SYSTEMROOT, etc.) – required on Windows.
        merged_env = {**os.environ, **full_env}
        try:
            proc = subprocess.run(
                [sys.executable, str(script_path)],
                capture_output=True,
                text=True,
                timeout=30,
                env=merged_env,
            )
            return self._parse_script_output(
                proc.stdout, proc.returncode, proc.stderr, script_path.name
            )
        except subprocess.TimeoutExpired:
            return HookResult(success=False, error=f"Python hook '{script_path.name}' timed out after 30s")
        except Exception as e:
            return HookResult(success=False, error=f"Python hook '{script_path.name}' error: {e}")


# Global singleton access
_hook_runner: HookRunner | None = None


def get_hook_runner() -> HookRunner:
    global _hook_runner
    if _hook_runner is None:
        _hook_runner = HookRunner()
    return _hook_runner
