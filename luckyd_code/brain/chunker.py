"""Code chunker — splits source files into overlapping chunks for embedding."""

import ast
import os
import re
from pathlib import Path

from ..log import get_logger
from .constants import LANGUAGE_MAP, Chunk, should_skip

# Regex patterns for non-Python language structure detection
STRUCTURE_PATTERNS: dict[str, list[tuple[str, str, str]]] = {
    "javascript": [
        (r"(?:^|\n)\s*function\s+\*?\s*(\w+)\s*\(", "function", "function"),
        (r"(?:^|\n)\s*(?:async\s+)?function\s+\*?\s*(\w+)\s*\(", "function", "function"),
        (r"(?:^|\n)\s*class\s+(\w+)", "class", "class"),
        (r"(?:^|\n)\s*(?:export\s+)?(?:default\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\(?.*\)?\s*=>", "function", "arrow_function"),
        (r"(?:^|\n)\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*function", "function", "function_expression"),
    ],
    "typescript": [
        (r"(?:^|\n)\s*function\s+\*?\s*(\w+)\s*\(", "function", "function"),
        (r"(?:^|\n)\s*(?:async\s+)?function\s+\*?\s*(\w+)\s*\(", "function", "function"),
        (r"(?:^|\n)\s*class\s+(\w+)", "class", "class"),
        (r"(?:^|\n)\s*interface\s+(\w+)", "class", "interface"),
        (r"(?:^|\n)\s*type\s+(\w+)\s*=", "class", "type_alias"),
        (r"(?:^|\n)\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\(?.*\)?\s*=>", "function", "arrow_function"),
        (r"(?:^|\n)\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*function", "function", "function_expression"),
    ],
    "go": [
        (r"(?:^|\n)\s*func\s+(\w+)", "function", "function"),
        (r"(?:^|\n)\s*type\s+(\w+)\s+struct", "class", "struct"),
        (r"(?:^|\n)\s*type\s+(\w+)\s+interface", "class", "interface"),
    ],
    "rust": [
        (r"(?:^|\n)\s*fn\s+(\w+)", "function", "function"),
        (r"(?:^|\n)\s*struct\s+(\w+)", "class", "struct"),
        (r"(?:^|\n)\s*enum\s+(\w+)", "class", "enum"),
        (r"(?:^|\n)\s*trait\s+(\w+)", "class", "trait"),
        (r"(?:^|\n)\s*impl\s+(\w+)", "class", "impl"),
    ],
}


def _chunk_python(filepath: Path, content: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    lines = content.split("\n")
    rel_path = str(filepath)

    try:
        tree = ast.parse(content, filename=str(filepath))
    except SyntaxError:
        return _chunk_by_lines(filepath, content, "python")

    header_end = 1
    module_doc = ast.get_docstring(tree) or ""
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            header_end = node.end_lineno or node.lineno
        elif isinstance(node, ast.Expr) and module_doc:
            header_end = node.end_lineno or node.lineno
        else:
            break

    header_content = "\n".join(lines[:header_end])
    if header_content.strip():
        chunks.append(Chunk(
            file_path=rel_path,
            chunk_id=f"{rel_path}:module",
            start_line=1,
            end_line=header_end,
            type="module",
            name=Path(rel_path).name,
            language="python",
            content=header_content,
        ))

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            end = node.end_lineno or node.lineno
            cls_lines = lines[node.lineno - 1:end]
            if end < len(lines):
                cls_lines.append(lines[end])

            content = "\n".join(cls_lines)
            chunks.append(Chunk(
                file_path=rel_path,
                chunk_id=f"{rel_path}:class:{node.name}",
                start_line=node.lineno,
                end_line=end,
                type="class",
                name=node.name,
                language="python",
                content=content,
            ))

            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.FunctionDef):
                    m_end = child.end_lineno or child.lineno
                    method_lines = lines[child.lineno - 1:m_end]
                    if m_end < len(lines):
                        method_lines.append(lines[m_end])
                    chunks.append(Chunk(
                        file_path=rel_path,
                        chunk_id=f"{rel_path}:method:{child.name}",
                        start_line=child.lineno,
                        end_line=m_end,
                        type="method",
                        name=child.name,
                        language="python",
                        content="\n".join(method_lines),
                    ))

        elif isinstance(node, ast.FunctionDef):
            end = node.end_lineno or node.lineno
            func_lines = lines[node.lineno - 1:end]
            if end < len(lines):
                func_lines.append(lines[end])

            chunks.append(Chunk(
                file_path=rel_path,
                chunk_id=f"{rel_path}:function:{node.name}",
                start_line=node.lineno,
                end_line=end,
                type="function",
                name=node.name,
                language="python",
                content="\n".join(func_lines),
            ))

    return chunks


def _chunk_by_lines(filepath: Path, content: str, language: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    lines = content.split("\n")
    rel_path = str(filepath)

    header_lines: list[str] = []
    i = 0
    while i < len(lines):
        if lines[i].strip() == "" and any(line.strip() for line in lines[i + 1:i + 3]):
            break
        header_lines.append(lines[i])
        i += 1
    if header_lines:
        chunks.append(Chunk(
            file_path=rel_path,
            chunk_id=f"{rel_path}:module",
            start_line=1,
            end_line=i,
            type="module",
            name=Path(rel_path).name,
            language=language,
            content="\n".join(header_lines).strip(),
        ))

    block_start = i + 1
    for match in re.finditer(r"\n\s*\n", content):
        block_end = match.start()
        if block_end > block_start:
            block_content = content[block_start:block_end].strip()
            if block_content:
                start_line = content[:block_start].count("\n") + 1
                end_line = content[:block_end].count("\n") + 1
                chunks.append(Chunk(
                    file_path=rel_path,
                    chunk_id=f"{rel_path}:block:{start_line}",
                    start_line=start_line,
                    end_line=end_line,
                    type="block",
                    name="",
                    language=language,
                    content=block_content,
                ))
        block_start = match.end()

    if block_start < len(content):
        last_block = content[block_start:].strip()
        if last_block:
            start_line = content[:block_start].count("\n") + 1
            end_line = content.count("\n") + 1
            chunks.append(Chunk(
                file_path=rel_path,
                chunk_id=f"{rel_path}:block:{start_line}",
                start_line=start_line,
                end_line=end_line,
                type="block",
                name="",
                language=language,
                content=last_block,
            ))

    return chunks


def _chunk_with_regex(filepath: Path, content: str, language: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    lines = content.split("\n")
    rel_path = str(filepath)
    patterns = STRUCTURE_PATTERNS.get(language, [])

    if not patterns:
        return []

    header_end = min(20, len(lines))
    for pattern, _type, _subtype in patterns:
        for m in re.finditer(pattern, content):
            line_num = content[:m.start()].count("\n") + 1
            header_end = min(header_end, line_num - 1)
            break

    header_content = "\n".join(lines[:header_end]).strip()
    if header_content:
        chunks.append(Chunk(
            file_path=rel_path,
            chunk_id=f"{rel_path}:module",
            start_line=1,
            end_line=header_end,
            type="module",
            name=Path(rel_path).name,
            language=language,
            content=header_content,
        ))

    finds: list[tuple[int, str, str, str]] = []
    for pattern, chunk_type, subtype in patterns:
        for m in re.finditer(pattern, content):
            line_num = content[:m.start()].count("\n") + 1
            name = m.group(1)
            finds.append((line_num, name, chunk_type, subtype))

    finds.sort(key=lambda x: x[0])

    for idx, (start_line, name, chunk_type, subtype) in enumerate(finds):
        byte_pos = 0
        for _ in range(start_line - 1):
            byte_pos = content.index("\n", byte_pos) + 1

        end_byte = _find_block_end(content, byte_pos)
        if end_byte <= byte_pos:
            end_byte = len(content)

        end_line = content[:end_byte].count("\n") + 1

        chunk_content = content[byte_pos:end_byte].rstrip()
        if not chunk_content:
            continue

        if idx + 1 < len(finds):
            next_start = finds[idx + 1][0]
            next_byte = 0
            for _ in range(next_start - 1):
                next_byte = content.index("\n", next_byte) + 1
            overlap_end = min(end_byte + 200, next_byte)
            overlap_content = content[end_byte:overlap_end]
            chunk_content += overlap_content

        chunks.append(Chunk(
            file_path=rel_path,
            chunk_id=f"{rel_path}:{chunk_type}:{name}",
            start_line=start_line,
            end_line=end_line,
            type=chunk_type,
            name=name,
            language=language,
            content=chunk_content,
        ))

    return chunks


def _find_block_end(content: str, start_byte: int) -> int:
    """Find the end of a brace-delimited block starting at start_byte."""
    # Find the first '{' after start_byte
    brace_start = content.find("{", start_byte)
    if brace_start == -1:
        return len(content)

    depth = 0
    in_string = False
    string_char = None
    i = brace_start

    while i < len(content):
        ch = content[i]
        if not in_string:
            if ch == '"' or ch == "'":
                in_string = True
                string_char = ch
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return i + 1
        else:
            if ch == "\\":
                i += 1  # skip escaped char
            elif ch == string_char:
                in_string = False
        i += 1

    return len(content)


def chunk_file(filepath: Path) -> list[Chunk]:
    suffix = filepath.suffix.lower()
    language = LANGUAGE_MAP.get(suffix)
    if not language:
        return []

    try:
        content = filepath.read_text(encoding="utf-8", errors="replace")
    except OSError:
        get_logger().warning("Could not read file %s", filepath, exc_info=True)
        return []

    if not content.strip():
        return []

    if language == "python":
        return _chunk_python(filepath, content)
    elif language in STRUCTURE_PATTERNS:
        return _chunk_with_regex(filepath, content, language)
    else:
        return _chunk_by_lines(filepath, content, language)


def chunk_project(project_root: str) -> list[Chunk]:
    root = Path(project_root).resolve()
    all_chunks: list[Chunk] = []

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not should_skip(d)]

        for fname in filenames:
            suffix = Path(fname).suffix.lower()
            if suffix not in LANGUAGE_MAP:
                continue

            fpath = Path(dirpath) / fname
            try:
                chunks = chunk_file(fpath)
                all_chunks.extend(chunks)
            except Exception:
                get_logger().warning("Error chunking %s", fpath, exc_info=True)

    return all_chunks
