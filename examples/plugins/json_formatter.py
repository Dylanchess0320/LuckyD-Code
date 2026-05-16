"""Example plugin: JSON Formatter

Pretty-prints and validates JSON. Shows how to handle errors gracefully.

Install:
    cp json_formatter.py ~/.luckyd-code/plugins/
    # then inside ldc: /plugins reload
"""

import json
from luckyd_code.tools.registry import Tool


class JsonFormatterTool(Tool):
    name = "JsonFormatter"
    description = (
        "Pretty-print and validate a JSON string. "
        "Returns formatted JSON or a clear error message if invalid."
    )
    parameters = {
        "type": "object",
        "properties": {
            "json_string": {
                "type": "string",
                "description": "The raw JSON string to format and validate.",
            },
            "indent": {
                "type": "integer",
                "description": "Number of spaces for indentation (default: 2).",
            },
        },
        "required": ["json_string"],
    }

    def run(self, json_string: str = "", indent: int = 2) -> str:
        try:
            parsed = json.loads(json_string)
            formatted = json.dumps(parsed, indent=indent, ensure_ascii=False)
            key_count = len(parsed) if isinstance(parsed, dict) else len(parsed) if isinstance(parsed, list) else 1
            type_name = type(parsed).__name__
            return f"Valid JSON ({type_name}, {key_count} top-level items):\n\n{formatted}"
        except json.JSONDecodeError as e:
            return f"Invalid JSON: {e}"


def register(registry) -> None:
    registry.register(JsonFormatterTool())
