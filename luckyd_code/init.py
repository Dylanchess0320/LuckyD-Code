"""Project initialization tool."""

import os
from pathlib import Path


MEMORY_FILENAMES = ["MEMORY.md", "CLAUDE.md"]  # check both for backward compat

DEFAULT_MEMORY_MD = """# MEMORY.md

## Project Overview
<!-- Describe what this project does -->

## Tech Stack
<!-- List the key technologies used -->

## Development Setup
<!-- How to get started -->

## Commands
<!-- Common commands for dev, test, build, lint -->

## Guidelines
<!-- Project-specific coding conventions -->
"""


def init_project():
    """Initialize the project memory file (MEMORY.md).

    Creates MEMORY.md if neither MEMORY.md nor CLAUDE.md exists.
    """
    cwd = Path(os.getcwd())
    for name in MEMORY_FILENAMES:
        if (cwd / name).exists():
            return f"{name} already exists."
    path = cwd / "MEMORY.md"
    path.write_text(DEFAULT_MEMORY_MD, encoding="utf-8")
    return "Created MEMORY.md. Edit it with project-specific instructions."
