"""File operation tools with path traversal protection."""

import difflib
import logging
import os
import re

from .registry import Tool
from .path_validate import validate_file_path
from ..undo import push as undo_push

_logger = logging.getLogger("luckyd_code.tools.file_ops")


def _unified_diff(original: str, updated: str, filename: str) -> str:
    """Return a unified diff string between two texts, or empty if identical."""
    a = original.splitlines(keepends=True)
    b = updated.splitlines(keepends=True)
    diff = list(difflib.unified_diff(a, b, fromfile=f"a/{filename}", tofile=f"b/{filename}"))
    return "".join(diff)


class ReadTool(Tool):
    name = "Read"
    description = "Read the contents of a file. Supports line offsets and limits."
    parameters = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Absolute path to the file to read",
            },
            "offset": {
                "type": "integer",
                "description": "Line number to start reading from (0-indexed)",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of lines to read",
            },
        },
        "required": ["file_path"],
    }

    def run(self, file_path: str, offset: int = 0, limit: int | None = None) -> str:  # type: ignore[override]
        try:
            path = validate_file_path(file_path, must_exist=True)
        except (ValueError, FileNotFoundError) as e:
            return f"Error: {e}"

        if not path.is_file():
            return f"Error: not a file: {file_path}"

        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        except Exception as e:
            return f"Error reading file: {e}"

        if offset >= len(lines):
            return f"Error: offset {offset} is beyond file length {len(lines)}"

        selected = lines[offset:]
        if limit is not None:
            selected = selected[:limit]

        result = "".join(selected)
        total = len(lines)
        start = offset
        end = offset + len(selected) - 1

        header = f"{path.name} ({total} lines, showing {start}-{end})"
        sep = "-" * len(header)
        return f"{header}\n{sep}\n{result}"


class WriteTool(Tool):
    name = "Write"
    description = (
        "Create a new file or overwrite an existing file with new content. "
        "Pass dry_run=true to preview a unified diff of the changes without writing."
    )
    permission_risk = "medium"
    parameters = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Absolute path to the file to write",
            },
            "content": {
                "type": "string",
                "description": "Content to write to the file",
            },
            "dry_run": {
                "type": "boolean",
                "description": (
                    "If true, return a unified diff of the proposed change "
                    "without modifying the file. Defaults to false."
                ),
            },
        },
        "required": ["file_path", "content"],
    }

    def run(self, file_path: str, content: str, dry_run: bool = False) -> str:  # type: ignore[override]
        try:
            path = validate_file_path(file_path)
        except ValueError as e:
            return f"Error: {e}"

        # Prevent writing files larger than 10MB
        if len(content) > 10 * 1024 * 1024:
            return "Error: content exceeds maximum file size (10MB)"

        original = path.read_text(encoding="utf-8") if path.exists() else None

        # Dry-run: show diff without touching the file
        if dry_run:
            if original is None:
                line_count = content.count("\n") + 1
                return f"[dry-run] Would create new file: {file_path} ({line_count} lines)"
            diff = _unified_diff(original, content, path.name)
            if not diff:
                return f"[dry-run] No changes — content is identical to {file_path}"
            return f"[dry-run] Proposed changes to {file_path}:\n\n{diff}"

        # Save undo info before writing
        undo_push(file_path, original or "", "Write")

        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.write_text(content, encoding="utf-8")
        except Exception as e:
            return f"Error writing file: {e}"

        # Show a concise summary of what changed
        if original is not None:
            diff = _unified_diff(original, content, path.name)
            changed_lines = sum(
                1 for line in diff.splitlines()
                if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
            )
            return (
                f"Successfully wrote {len(content)} bytes to {file_path} "
                f"({changed_lines} lines changed)"
            )
        return f"Successfully wrote {len(content)} bytes to {file_path} (new file)"


class EditTool(Tool):
    name = "Edit"
    description = "Edit an existing file by replacing text. Performs an exact string replacement."
    permission_risk = "medium"
    parameters = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Absolute path to the file to edit",
            },
            "old_string": {
                "type": "string",
                "description": "Text to replace (must be unique in the file)",
            },
            "new_string": {
                "type": "string",
                "description": "Text to replace it with",
            },
            "replace_all": {
                "type": "boolean",
                "description": "Replace all occurrences instead of just the first",
            },
            "dry_run": {
                "type": "boolean",
                "description": (
                    "If true, return a unified diff of the proposed change "
                    "without modifying the file. Defaults to false."
                ),
            },
        },
        "required": ["file_path", "old_string", "new_string"],
    }

    def run(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
        dry_run: bool = False,
    ) -> str:  # type: ignore[override]
        try:
            path = validate_file_path(file_path, must_exist=True)
        except (ValueError, FileNotFoundError) as e:
            return f"Error: {e}"

        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            return f"Error reading file: {e}"

        if not replace_all:
            count = content.count(old_string)
            if count == 0:
                return f"Error: old_string not found in {file_path}"
            if count > 1:
                return (
                    f"Error: old_string appears {count} times in {file_path}. "
                    "Use replace_all=True to replace all occurrences, "
                    "or provide more context to make it unique."
                )
            new_content = content.replace(old_string, new_string, 1)
        else:
            new_content = content.replace(old_string, new_string)

        # Dry-run: show diff without touching the file
        if dry_run:
            diff = _unified_diff(content, new_content, path.name)
            if not diff:
                return "[dry-run] No changes — old_string and new_string are identical"
            return f"[dry-run] Proposed changes to {file_path}:\n\n{diff}"

        # Save undo info before editing
        undo_push(file_path, content, "Edit")

        try:
            path.write_text(new_content, encoding="utf-8")
        except Exception as e:
            return f"Error writing file: {e}"

        replacements = content.count(old_string) if replace_all else 1
        return f"Applied {replacements} replacement(s) to {file_path}"


class GlobTool(Tool):
    name = "Glob"
    description = "Find files matching a glob pattern. Supports ** and * wildcards."
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob pattern (e.g., '**/*.py', 'src/**/*.ts')",
            },
            "path": {
                "type": "string",
                "description": "Directory to search in (defaults to current directory)",
            },
        },
        "required": ["pattern"],
    }

    def run(self, pattern: str, path: str | None = None) -> str:  # type: ignore[override]
        search_dir = path or os.getcwd()
        try:
            root = validate_file_path(search_dir, must_exist=True)
        except (ValueError, FileNotFoundError) as e:
            return f"Error: {e}"

        if not root.is_dir():
            return f"Error: not a directory: {search_dir}"

        try:
            matches = sorted([p.relative_to(root) for p in root.rglob(pattern) if p.is_file()])
        except Exception as e:
            return f"Error during glob: {e}"

        if not matches:
            return f"No files matching '{pattern}' found in {search_dir}"

        max_results = 200
        if len(matches) > max_results:
            lines = "\n".join(str(m) for m in matches[:max_results])
            return f"{lines}\n... and {len(matches) - max_results} more"
        return "\n".join(str(m) for m in matches)


class GrepTool(Tool):
    name = "Grep"
    description = "Search for a pattern in file contents. Supports regex."
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Regular expression pattern to search for",
            },
            "path": {
                "type": "string",
                "description": "Directory or file to search in",
            },
            "glob": {
                "type": "string",
                "description": "File glob pattern to filter (e.g., '*.py')",
            },
            "output_mode": {
                "type": "string",
                "enum": ["content", "files_with_matches", "count"],
                "description": "Output format",
            },
        },
        "required": ["pattern"],
    }

    def run(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
        output_mode: str = "content",
    ) -> str:  # type: ignore[override]
        search_path = path or os.getcwd()
        try:
            search_path_validated = validate_file_path(search_path, must_exist=True)
        except (ValueError, FileNotFoundError) as e:
            return f"Error: {e}"

        try:
            regex = re.compile(pattern)
        except re.error as e:
            return f"Invalid regex: {e}"

        results: list[str] = []
        file_count = 0
        total_matches = 0
        limit = 200

        files = []
        if search_path_validated.is_file():
            files = [str(search_path_validated)]
        else:
            for root, _dirs, fnames in os.walk(str(search_path_validated)):
                for fname in fnames:
                    if glob and not self._matches_glob(fname, glob):
                        continue
                    files.append(os.path.join(root, fname))

        for fpath in files:
            try:
                file_has_match = False
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    for i, line in enumerate(f, 1):
                        if regex.search(line.rstrip("\n")):
                            if not file_has_match:
                                file_has_match = True
                                file_count += 1
                            total_matches += 1
                            if output_mode == "content" and len(results) < limit:
                                rel = (
                                    os.path.relpath(fpath, str(search_path_validated))
                                    if search_path_validated.is_dir()
                                    else os.path.basename(fpath)
                                )
                                results.append(f"{rel}:{i}:{line.rstrip()}")
                            elif output_mode == "files_with_matches" and (
                                len(results) == 0
                                or results[-1] != os.path.relpath(fpath, str(search_path_validated))
                            ):
                                if len(results) < limit:
                                    results.append(os.path.relpath(fpath, str(search_path_validated)))
            except Exception:
                _logger.debug("Error reading file %s during grep", fpath, exc_info=True)

            if len(results) >= limit:
                break

        if output_mode == "count":
            return f"{total_matches} matches in {file_count} files"

        if not results:
            return "No matches found"

        text = "\n".join(results)
        if total_matches > limit:
            text += f"\n... and {total_matches - limit} more results"
        return text

    @staticmethod
    def _matches_glob(filename: str, pattern: str) -> bool:
        import fnmatch
        return fnmatch.fnmatch(filename, pattern)
