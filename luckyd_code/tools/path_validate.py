"""Path traversal protection and file path utilities."""

import os
from pathlib import Path


def safe_resolve(path: str, working_dir: str | None = None) -> Path:
    """Resolve a path safely, preventing directory traversal outside allowed directories.

    Raises ValueError if the resolved path is outside the allowed directory.
    """
    resolved = Path(path).resolve()

    if working_dir:
        allowed = Path(working_dir).resolve()
    else:
        allowed = Path(os.getcwd()).resolve()

    # Check if resolved path is within the allowed directory
    try:
        resolved.relative_to(allowed)
    except ValueError:
        raise ValueError(
            f"Path traversal blocked: '{path}' resolves outside the working directory '{allowed}'"
        )

    return resolved


def validate_file_path(file_path: str, must_exist: bool = False, working_dir: str | None = None) -> Path:
    """Validate a file path and return the resolved Path.

    Args:
        file_path: The path to validate
        must_exist: If True, raises FileNotFoundError when path doesn't exist
        working_dir: Optional working directory to restrict to

    Returns:
        Resolved Path object

    Raises:
        ValueError: If path traversal is detected
        FileNotFoundError: If must_exist is True and path doesn't exist
    """
    resolved = safe_resolve(file_path, working_dir)

    if must_exist and not resolved.exists():
        raise FileNotFoundError(f"Path does not exist: {file_path}")

    return resolved


def sanitize_filename(name: str) -> str:
    """Sanitize a filename by removing dangerous characters."""
    import re
    # Remove path separators and null bytes
    name = name.replace("/", "_").replace("\\", "_").replace("\0", "")
    # Remove any remaining dangerous characters
    name = re.sub(r'[<>:"|?*]', "_", name)
    # Limit length
    if len(name) > 200:
        base, ext = os.path.splitext(name)
        name = base[:195] + ext
    return name.strip()
