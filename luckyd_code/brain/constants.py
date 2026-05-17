"""Shared constants, types, and helpers for the brain module."""

from typing import TypedDict

from .._data_dir import data_path

# Directories to skip during project scanning
SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv", "env",
    ".tox", ".eggs", "dist", "build", ".next", ".nuxt",
    "target", "vendor", ".bundle", ".claude", ".vscode", ".idea",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".ruff",
    ".svn", ".hg", "egg-info",
}

# Supported file extensions and their languages
LANGUAGE_MAP = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".c": "c",
    ".h": "c",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".lua": "lua",
    ".r": "r",
    ".R": "r",
    ".scala": "scala",
    ".ex": "elixir",
    ".exs": "elixir",
    ".md": "markdown",
    ".toml": "toml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".sql": "sql",
}

# Storage directory for index and cache files
BRAIN_DIR = data_path("brain")


class Chunk(TypedDict):
    """A chunk of source code ready for embedding and search."""
    file_path: str
    chunk_id: str
    start_line: int
    end_line: int
    type: str      # module, class, function, method, block
    name: str
    language: str
    content: str
    # score is added by the retriever at search time


def should_skip(name: str) -> bool:
    return name in SKIP_DIRS or name.startswith(".")
