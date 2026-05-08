"""Lifecycle hooks system — pre/post tool use, pre/post chat, session events.

Hooks are shell scripts defined in .luckyd-code/settings.local.json:

    {
      "hooks": {
        "preToolUse": {
          "script": "echo 'About to run $DSC_TOOL_NAME'",
          "tools": ["all"]
        },
        "postToolUse": "npm run lint-changed",
        "preChat": "echo 'Sending request to $DSC_MODEL'",
        "postChat": "echo 'Response received'",
        "onSessionStart": "echo 'Session started at $DSC_TIME'",
        "onSessionEnd": "echo 'Session ended'"
      }
    }

Hooks can return JSON on their first line to control execution:
  {"allow": false}     — block the tool call (preToolUse only)
  {"env": {"K": "v"}} — update environment variables
"""

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

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
    error: Optional[str] = None
    allow: bool = True           # preToolUse: block or allow the tool call
    env_updates: dict = field(default_factory=dict)


class HookRunner:
    """Execute shell-based hooks for lifecycle events."""

    def __init__(self):
        self.settings = load_settings()

    def run_hook(self, event: str, context: Optional[dict] = None) -> list[HookResult]:
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

    def _get_hook_scripts(self, event: str) -> list[dict]:
        """Get all hook scripts for an event from settings.

        Returns empty for unknown (not in HOOK_EVENTS) event types
        even if hooks are configured — prevents misconfiguration.
        """
        if event not in HOOK_EVENTS:
            return []
        hooks = self.settings.get("hooks", {})
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

    def _execute_script(self, script: str, event: str,
                        context: Optional[dict] = None) -> HookResult:
        """Execute a single hook script and return the result.

        Supports both shell commands and ``.py`` scripts.  Python scripts
        are launched via ``sys.executable`` with the same environment
        variables, so they work portably across platforms.
        """
        env = {
            "DSC_HOOK_EVENT": event,
            "DSC_PROJECT_DIR": str(get_settings_dir().parent),
            "DSC_TIME": __import__("datetime").datetime.now().isoformat(),
        }
        if context:
            for k, v in context.items():
                env[f"DSC_{k.upper()}"] = str(v)

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
            output = proc.stdout.strip()
            if proc.returncode != 0 and proc.stderr.strip():
                return HookResult(
                    success=False,
                    error=proc.stderr.strip(),
                    output=output,
                )

            # Parse optional JSON directive from first line
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

        except subprocess.TimeoutExpired:
            return HookResult(success=False, error=f"Hook '{event}' timed out after 30s")
        except FileNotFoundError:
            return HookResult(success=False, error=f"Hook '{event}' command not found: {script[:100]}")
        except Exception as e:
            return HookResult(success=False, error=f"Hook '{event}' error: {e}")

    def _run_python_script(self, script_path: Path, event: str,
                           full_env: dict) -> HookResult:
        """Execute a ``.py`` hook script with the current Python interpreter.

        The script receives all ``DSC_*`` environment variables and can
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
            output = proc.stdout.strip()
            if proc.returncode != 0 and proc.stderr.strip():
                return HookResult(
                    success=False,
                    error=proc.stderr.strip(),
                    output=output,
                )

            # Parse optional JSON directive from first line
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

        except subprocess.TimeoutExpired:
            return HookResult(success=False, error=f"Python hook '{script_path.name}' timed out after 30s")
        except Exception as e:
            return HookResult(success=False, error=f"Python hook '{script_path.name}' error: {e}")


# Global singleton access
_hook_runner: Optional[HookRunner] = None


def get_hook_runner() -> HookRunner:
    global _hook_runner
    if _hook_runner is None:
        _hook_runner = HookRunner()
    return _hook_runner
