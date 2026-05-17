"""AST-based code parser — extracts functions, classes, imports, and relationships."""

import ast
import os
from pathlib import Path
from typing import Any

from .constants import should_skip

ParsedFile = dict[str, Any]
ParseResult = tuple[list[ParsedFile], dict[str, tuple[float, int]]]


def _extract_calls(node: ast.FunctionDef) -> list[str]:
    calls: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
            calls.append(child.func.id)
        elif isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
            calls.append(child.func.attr)
    return list(set(calls))


def parse_file(filepath: Path) -> ParsedFile:
    result: ParsedFile = {
        "module": str(filepath),
        "classes": [],
        "functions": [],
        "imports": [],
        "errors": [],
        "size": 0,
    }

    try:
        source = filepath.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        result["errors"].append(str(e))
        return result

    result["size"] = len(source)

    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError as e:
        result["errors"].append(f"SyntaxError: {e}")
        return result

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                result["imports"].append({
                    "module": alias.name,
                    "name": alias.asname or alias.name,
                    "alias": alias.asname,
                })
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                result["imports"].append({
                    "module": module,
                    "name": alias.name,
                    "alias": alias.asname,
                })

        elif isinstance(node, ast.ClassDef):
            cls_info: ParsedFile = {
                "name": node.name,
                "bases": [ast.dump(b) if isinstance(b, ast.Name) else "" for b in node.bases],
                "base_names": [
                    b.id if isinstance(b, ast.Name) else
                    f"{b.value.id}.{b.attr}" if isinstance(b, ast.Attribute) and hasattr(b, 'value') and isinstance(b.value, ast.Name) else
                    str(ast.dump(b))
                    for b in node.bases
                ],
                "methods": [],
                "decorators": [ast.dump(d) for d in node.decorator_list],
                "docstring": ast.get_docstring(node) or "",
                "line": node.lineno,
                "end_line": node.end_lineno or node.lineno,
            }

            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.FunctionDef):
                    method_info: ParsedFile = {
                        "name": child.name,
                        "decorators": [ast.dump(d) for d in child.decorator_list],
                        "docstring": ast.get_docstring(child) or "",
                        "line": child.lineno,
                        "end_line": child.end_lineno or child.lineno,
                        "calls": _extract_calls(child),
                    }
                    cls_info["methods"].append(method_info)

            result["classes"].append(cls_info)

        elif isinstance(node, ast.FunctionDef):
            func_info: ParsedFile = {
                "name": node.name,
                "decorators": [ast.dump(d) for d in node.decorator_list],
                "docstring": ast.get_docstring(node) or "",
                "line": node.lineno,
                "end_line": node.end_lineno or node.lineno,
                "calls": _extract_calls(node),
            }
            result["functions"].append(func_info)

    return result


def parse_project(project_root: str, file_mtimes: dict[str, tuple[float, int]] | None = None) -> ParseResult:
    root = Path(project_root).resolve()
    results: list[ParsedFile] = []
    new_mtimes: dict[str, tuple[float, int]] = {}

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not should_skip(d)]

        for fname in filenames:
            if not fname.endswith(".py"):
                continue

            fpath = Path(dirpath) / fname
            try:
                st = fpath.stat()
                mtime = st.st_mtime
                size = st.st_size
            except OSError:
                continue

            new_mtimes[str(fpath)] = (mtime, size)

            if file_mtimes and str(fpath) in file_mtimes:
                old_mtime, old_size = file_mtimes[str(fpath)]
                if old_mtime == mtime and old_size == size:
                    continue

            parsed = parse_file(fpath)
            results.append(parsed)

    return results, new_mtimes
