"""Tools Bridge — exposes all tools as CLI commands.

This makes every tool in the registry callable via:
    python -m luckyd_code.tools_bridge <tool> [args...]

Examples:
    python -m luckyd_code.tools_bridge browser navigate --url https://example.com
    python -m luckyd_code.tools_bridge bash --command "dir /b"
    python -m luckyd_code.tools_bridge brain search --query "authentication"
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.console import Console

if TYPE_CHECKING:
    from luckyd_code.tools.registry import Tool

# Ensure the project root is on sys.path
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

_console = Console()


def _parse_args(raw_args: list[str]) -> dict[str, Any]:
    """Parse KEY=VALUE or --flag VALUE pairs into a dict."""
    result = {}
    key = None
    for item in raw_args:
        if item.startswith("--"):
            if key is not None:
                result[key] = True  # flag
            key = item.removeprefix("--")
        elif key is not None:
            try:
                result[key] = json.loads(item)
            except (json.JSONDecodeError, TypeError):
                result[key] = item
            key = None
        elif "=" in item:
            k, v = item.split("=", 1)
            try:
                result[k] = json.loads(v)
            except (json.JSONDecodeError, TypeError):
                result[k] = v
    if key is not None:
        result[key] = True
    return result


def _import_tool(tool_name: str) -> Tool:
    """Import and return a tool instance by name."""
    from luckyd_code.tools import get_default_registry
    registry = get_default_registry()
    tool = registry.get(tool_name)
    if tool is None:
        _console.print(f"Unknown tool: {tool_name}", style="red")
        _console.print("\nAvailable tools:")
        for t in sorted(registry._tools.keys()):
            _console.print(f"  - {t}")
        sys.exit(1)
    return tool


def cmd_info(tool_name: str) -> None:
    """Show info about a tool."""
    tool = _import_tool(tool_name)
    _console.print(f"Tool: {tool.name}")
    _console.print(f"Risk:  {tool.permission_risk}")
    _console.print(f"Desc:  {tool.description}")
    _console.print("Params:")
    props = tool.parameters.get("properties", {})
    required = tool.parameters.get("required", [])
    for name, schema in props.items():
        req = " (required)" if name in required else ""
        desc = schema.get("description", "")
        _console.print(f"  --{name}: {desc}{req}")


def cmd_run(tool_name: str, *args: str) -> None:
    """Run a tool with given arguments."""
    tool = _import_tool(tool_name)
    kwargs = _parse_args(list(args))
    result = tool.run(**kwargs)
    _console.print(result)


def cmd_list() -> None:
    """List all registered tools."""
    from luckyd_code.tools import get_default_registry
    registry = get_default_registry()
    _console.print("=" * 60)
    _console.print("Available Tools (via luckyd_code.tools_bridge)")
    _console.print("=" * 60)
    for name, tool in sorted(registry._tools.items()):
        risk_icon = {"safe": "[SAFE]", "medium": "[MED]", "high": "[HIGH]"}.get(tool.permission_risk, "[?]")
        _console.print(f"\n{risk_icon} {name}")
        _console.print(f"   {tool.description[:120]}")
    _console.print(f"\n{'=' * 60}")
    _console.print("Usage: python -m luckyd_code.tools_bridge run <ToolName> [--key value ...]")
    _console.print("         python -m luckyd_code.tools_bridge info <ToolName>")


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        _console.print("LuckyD Code Tools Bridge — expose internal tools as CLI")
        _console.print()
        _console.print("Usage:")
        _console.print("  python -m luckyd_code.tools_bridge list")
        _console.print("  python -m luckyd_code.tools_bridge info <ToolName>")
        _console.print("  python -m luckyd_code.tools_bridge run <ToolName> [--key value ...]")
        _console.print()
        _console.print("Examples:")
        _console.print('  python -m luckyd_code.tools_bridge run Bash --command "dir /b"')
        _console.print('  python -m luckyd_code.tools_bridge run WebFetch --url https://example.com')
        _console.print('  python -m luckyd_code.tools_bridge run BrowserNavigate --url https://github.com')
        _console.print('  python -m luckyd_code.tools_bridge run BrainSearch --query "auth"')
        _console.print('  python -m luckyd_code.tools_bridge run GitStatus')
        return

    command = sys.argv[1]
    rest = sys.argv[2:]

    if command == "list":
        cmd_list()
    elif command == "info":
        if not rest:
            _console.print("Usage: tools_bridge info <ToolName>", style="yellow")
            sys.exit(1)
        cmd_info(rest[0])
    elif command == "run":
        if not rest:
            _console.print("Usage: tools_bridge run <ToolName> [--key value ...]", style="yellow")
            sys.exit(1)
        tool_name = rest[0]
        cmd_run(tool_name, *rest[1:])
    else:
        _console.print(f"Unknown command: {command}", style="red")
        _console.print("Available: list, info, run")
        sys.exit(1)


if __name__ == "__main__":
    main()
