"""DateTime tool — returns the current local date/time without touching the shell.

Using 'date' or 'time' in a Bash tool on Windows cmd.exe launches an
interactive prompt that hangs forever. This tool avoids the shell entirely.
"""

from datetime import datetime
from .registry import Tool


class DateTimeTool(Tool):
    name = "DateTime"
    description = (
        "Get the current local date and time. "
        "Always use this instead of running 'date' or 'time' in a shell."
    )
    permission_risk = "safe"
    parameters = {
        "type": "object",
        "properties": {
            "format": {
                "type": "string",
                "description": (
                    "Optional strftime format string "
                    "(e.g. '%Y-%m-%d %H:%M:%S'). "
                    "Defaults to a human-readable format."
                ),
            }
        },
        "required": [],
    }

    def run(self, format: str = "%A, %B %d %Y  %I:%M:%S %p") -> str:  # type: ignore[override]
        return datetime.now().strftime(format)
