"""Example plugin: Word Counter

Counts words, lines, and characters in any text or file.
Shows how to do light file I/O inside a plugin tool.

Install:
    cp word_counter.py ~/.luckyd-code/plugins/
    # then inside ldc: /plugins reload
"""

from pathlib import Path
from luckyd_code.tools.registry import Tool


class WordCounterTool(Tool):
    name = "WordCounter"
    description = (
        "Count words, lines, and characters in a block of text or a file path. "
        "Pass text directly or a file path prefixed with 'file:'."
    )
    parameters = {
        "type": "object",
        "properties": {
            "input": {
                "type": "string",
                "description": (
                    "Text to count, or a file path prefixed with 'file:' "
                    "(e.g. 'file:src/main.py')"
                ),
            },
        },
        "required": ["input"],
    }

    def run(self, input: str = "") -> str:  # noqa: A002
        if input.startswith("file:"):
            path = Path(input[5:].strip())
            if not path.exists():
                return f"Error: file not found: {path}"
            text = path.read_text(encoding="utf-8", errors="replace")
            source = str(path)
        else:
            text = input
            source = "input text"

        lines = text.splitlines()
        words = text.split()
        chars = len(text)
        chars_no_space = len(text.replace(" ", "").replace("\n", "").replace("\t", ""))

        return (
            f"Word count for {source}:\n"
            f"  Lines:              {len(lines):>8,}\n"
            f"  Words:              {len(words):>8,}\n"
            f"  Characters:         {chars:>8,}\n"
            f"  Characters (no ws): {chars_no_space:>8,}"
        )


def register(registry) -> None:
    registry.register(WordCounterTool())
