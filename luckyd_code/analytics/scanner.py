"""Codebase scanner — collects metrics across an entire project tree."""

import ast
import os
import re
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from ..log import get_logger

logger = get_logger()

# ── Constants ────────────────────────────────────────────────────────────────

SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv", "env",
    ".tox", ".eggs", "dist", "build", ".next", ".nuxt", "target",
    "vendor", ".bundle", ".claude", ".deepseek-code", ".luckyd-code", ".vscode", ".idea",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".svn", ".hg",
    "egg-info", ".pixi",
}

PYTHON_EXTENSIONS = {".py", ".pyw", ".pyi"}
JS_EXTENSIONS = {".js", ".jsx", ".mjs", ".cjs"}
TS_EXTENSIONS = {".ts", ".tsx", ".mts", ".cts"}
GO_EXTENSIONS = {".go"}
RUST_EXTENSIONS = {".rs"}
KNOWN_EXTENSIONS = PYTHON_EXTENSIONS | JS_EXTENSIONS | TS_EXTENSIONS | GO_EXTENSIONS | RUST_EXTENSIONS

TODO_RE = re.compile(r"(?:TODO|FIXME|HACK|XXX|BUG|OPTIMIZE|NOTE)[\s:]*(.*?)(?:\n|$)", re.IGNORECASE)
COMMENT_RE = re.compile(r"(#|//|/\*|<!--)\s*")
FUNC_RE = re.compile(
    r"^\s*(?:def |async def |fn |func |function |pub fn |pub async fn )",
    re.MULTILINE,
)
CLASS_RE = re.compile(
    r"^\s*(?:class |struct |impl |enum |interface |type )",
    re.MULTILINE,
)
RETURN_RE = re.compile(r"\breturn\b")


# ── Data classes ─────────────────────────────────────────────────────────────


@dataclass
class FileMetrics:
    """Metrics for a single source file."""

    path: str
    language: str = ""
    size_bytes: int = 0
    lines_total: int = 0
    lines_code: int = 0
    lines_blank: int = 0
    lines_comment: int = 0
    todo_count: int = 0
    fixme_count: int = 0
    function_count: int = 0
    class_count: int = 0
    complexity: int = 0  # rough cyclomatic
    max_indent: int = 0
    imports_count: int = 0
    # Additional fields expected by tests
    max_function_length: int = 0
    has_tests: bool = False
    import_count: int = 0  # alias for imports_count


@dataclass
class ProjectMetrics:
    """Aggregate metrics for an entire project."""

    root: str
    scanned_at: float = field(default_factory=time.time)
    total_files: int = 0
    source_files: int = 0
    total_lines: int = 0
    total_code_lines: int = 0
    total_comments: int = 0
    total_blank: int = 0
    total_todos: int = 0
    total_fixmes: int = 0
    total_functions: int = 0
    total_classes: int = 0
    total_complexity: int = 0
    total_size_bytes: int = 0
    max_complexity: int = 0
    file_metrics: list[FileMetrics] = field(default_factory=list)
    todos: list[dict[str, Any]] = field(default_factory=list)
    files_by_language: dict[str, int] = field(default_factory=dict)
    complexity_breakdown: dict[str, int] = field(default_factory=dict)
    smells: list[dict[str, Any]] = field(default_factory=list)

    avg_complexity: float = 0.0
    health_score: float = 0.0

    @property
    def todo_rate(self) -> float:
        if self.total_code_lines == 0:
            return 0.0
        return self.total_todos / (self.total_code_lines / 1000)

    def _compute_derived(self) -> None:
        """Recompute avg_complexity and health_score from current totals."""
        self.avg_complexity = (
            self.total_complexity / self.total_functions
            if self.total_functions > 0 else 0.0
        )
        score = 100.0
        score -= min(15, self.todo_rate * 5)
        score -= min(15, max(0, self.avg_complexity - 5) * 2)
        if self.source_files > 0:
            avg_lines = self.total_lines / self.source_files
            score -= min(10, max(0, (avg_lines - 300) / 50))
        if self.source_files > 100 and len(self.files_by_language) < 2:
            score -= 5
        self.health_score = max(0.0, round(score, 1))

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["avg_complexity"] = self.avg_complexity
        d["todo_rate"] = self.todo_rate
        d["health_score"] = self.health_score
        return d


# ── Scanner helpers ──────────────────────────────────────────────────────────


def _detect_language(file_path: Path) -> str:
    suffix = file_path.suffix.lower()
    if suffix in PYTHON_EXTENSIONS:
        return "python"
    if suffix in JS_EXTENSIONS:
        return "javascript"
    if suffix in TS_EXTENSIONS:
        return "typescript"
    if suffix in GO_EXTENSIONS:
        return "go"
    if suffix in RUST_EXTENSIONS:
        return "rust"
    if suffix in {".c", ".h"}:
        return "c"
    if suffix in {".cpp", ".cc", ".cxx", ".hpp", ".hxx"}:
        return "c++"
    if suffix in {".java"}:
        return "java"
    if suffix in {".rb"}:
        return "ruby"
    if suffix in {".php"}:
        return "php"
    if suffix in {".swift"}:
        return "swift"
    if suffix in {".kt", ".kts"}:
        return "kotlin"
    if suffix in {".sh", ".bash", ".zsh"}:
        return "shell"
    if suffix in {".md", ".mdx"}:
        return "markdown"
    if suffix in {".json"}:
        return "json"
    if suffix in {".yaml", ".yml"}:
        return "yaml"
    if suffix in {".toml"}:
        return "toml"
    if suffix in {".cfg", ".ini"}:
        return "config"
    return "unknown"


def _count_lines(content: str) -> tuple[int, int, int]:
    """Count total, code, and blank lines."""
    total = 0
    blank = 0
    for line in content.splitlines():
        total += 1
        stripped = line.strip()
        if not stripped:
            blank += 1
    code = total - blank
    return total, code, blank


def _count_comment_lines(content: str, language: str) -> int:
    """Rough count of comment lines."""
    count = 0
    in_block = False
    for line in content.splitlines():
        stripped = line.strip()
        if language in ("python", "ruby", "shell", "yaml", "toml", "config"):
            if stripped.startswith("#"):
                count += 1
        elif language in ("javascript", "typescript", "go", "rust", "c", "c++",
                          "java", "kotlin", "swift", "php"):
            if in_block:
                count += 1
                if "*/" in stripped:
                    in_block = False
                continue
            if stripped.startswith("//"):
                count += 1
            elif stripped.startswith("/*"):
                count += 1
                if "*/" not in stripped:
                    in_block = True
    return count


def _python_complexity(tree: ast.AST) -> int:
    """Cyclomatic complexity for Python via AST."""
    complexity = 1  # base path
    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.While, ast.For, ast.AsyncFor,
                              ast.ExceptHandler, ast.With, ast.AsyncWith,
                              ast.Assert)):
            complexity += 1
        elif isinstance(node, ast.BoolOp):
            complexity += len(node.values) - 1
        elif isinstance(node, ast.Match):
            complexity += 1  # each case adds at walk level
        elif isinstance(node, ast.match_case):
            complexity += 1
    return complexity


def _generic_complexity(content: str) -> int:
    """Regex-based complexity approximation for non-Python languages."""
    complexity = 1
    for pattern in [
        r"\bif\b", r"\belse if\b", r"\bwhile\b", r"\bfor\b",
        r"\bcatch\b", r"\bexcept\b", r"\bmatch\b", r"\bswitch\b",
        r"\bcase\b", r"\b&&\b", r"\b\|\|\b", r"\?\s*[^?:]",
    ]:
        complexity += len(re.findall(pattern, content, re.IGNORECASE))
    return complexity


def _max_indent(content: str) -> int:
    """Find the maximum indentation level."""
    max_indent = 0
    for line in content.splitlines():
        if line.strip():
            indent = len(line) - len(line.lstrip())
            max_indent = max(max_indent, indent)
    return max_indent


def _scan_python(path: Path, content: str) -> FileMetrics:
    """Deep scan of a Python file."""
    fm = FileMetrics(path=str(path), language="python")

    # AST analysis
    try:
        tree = ast.parse(content, filename=str(path))
    except SyntaxError:
        tree = None

    # Line counts
    total, code, blank = _count_lines(content)
    fm.lines_total = total
    fm.lines_code = code
    fm.lines_blank = blank
    fm.lines_comment = _count_comment_lines(content, "python")

    # Max indent
    fm.max_indent = _max_indent(content)

    # Functions and classes
    if tree is not None:
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fm.function_count += 1
            elif isinstance(node, ast.ClassDef):
                fm.class_count += 1
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                fm.imports_count += 1

        fm.complexity = _python_complexity(tree)
    else:
        # Fallback regex counts
        fm.function_count = len(FUNC_RE.findall(content))
        fm.class_count = len(CLASS_RE.findall(content))
        fm.complexity = _generic_complexity(content)

    return fm


def _scan_generic(path: Path, content: str) -> FileMetrics:
    """Scan a non-Python source file with regex-based metrics."""
    language = _detect_language(path)
    fm = FileMetrics(path=str(path), language=language)

    total, code, blank = _count_lines(content)
    fm.lines_total = total
    fm.lines_code = code
    fm.lines_blank = blank
    fm.lines_comment = _count_comment_lines(content, language)

    fm.max_indent = _max_indent(content)
    fm.function_count = len(FUNC_RE.findall(content))
    fm.class_count = len(CLASS_RE.findall(content))
    fm.complexity = _generic_complexity(content)
    fm.imports_count = len(re.findall(r"^\s*(?:import|from|require|use|#include)\b",
                                       content, re.MULTILINE))

    return fm


def _extract_todos(content: str, file_path: str) -> list[dict[str, Any]]:
    """Extract TODO/FIXME items with context."""
    items = []
    lines = content.splitlines()
    for i, line in enumerate(lines):
        m = TODO_RE.search(line)
        if m:
            kind = m.group(0).split(":")[0].split()[0].upper().strip(":")
            if kind in ("NOTE", "OPTIMIZE"):
                continue  # less critical
            items.append({
                "file": file_path,
                "line": i + 1,
                "kind": kind,
                "text": m.group(1).strip() if m.group(1) else "",
                "context": line.strip()[:120],
            })
    return items


def _should_skip_dir(dirname: str) -> bool:
    return dirname in SKIP_DIRS or dirname.startswith(".")


def _should_scan_file(file_path: Path) -> bool:
    """Check if this file should be scanned."""
    if file_path.suffix.lower() not in KNOWN_EXTENSIONS:
        return False
    # Skip very large files (>2MB)
    try:
        if file_path.stat().st_size > 2 * 1024 * 1024:
            return False
    except OSError:
        return False
    return True


# ── Main scanner ─────────────────────────────────────────────────────────────


class CodebaseScanner:
    """Scan a directory tree and produce comprehensive metrics."""

    def __init__(self, root: str | None = None):
        self.root = Path(root) if root else Path.cwd()

    def scan(self) -> ProjectMetrics:
        """Run a full scan and return aggregated metrics."""
        pm = ProjectMetrics(root=str(self.root))

        for dirpath, dirnames, filenames in os.walk(self.root):
            # Skip hidden / known dirs
            dirnames[:] = [
                d for d in dirnames
                if not _should_skip_dir(d)
            ]

            for fname in sorted(filenames):
                file_path = Path(dirpath) / fname
                if not _should_scan_file(file_path):
                    continue

                try:
                    content = file_path.read_text(encoding="utf-8", errors="replace")
                except (OSError, UnicodeDecodeError):
                    continue

                language = _detect_language(file_path)

                # Choose scan strategy
                if language == "python":
                    fm = _scan_python(file_path, content)
                else:
                    fm = _scan_generic(file_path, content)

                fm.size_bytes = file_path.stat().st_size
                fm.todo_count = len(re.findall(r"\bTODO\b", content, re.IGNORECASE))
                fm.fixme_count = len(re.findall(r"\bFIXME\b", content, re.IGNORECASE))

                pm.file_metrics.append(fm)
                pm.source_files += 1
                pm.total_lines += fm.lines_total
                pm.total_code_lines += fm.lines_code
                pm.total_todos += fm.todo_count
                pm.total_fixmes += fm.fixme_count
                pm.total_functions += fm.function_count
                pm.total_classes += fm.class_count
                pm.total_complexity += fm.complexity
                pm.total_size_bytes += fm.size_bytes

                # Language breakdown
                lang = fm.language
                pm.files_by_language[lang] = pm.files_by_language.get(lang, 0) + 1

                # Complexity breakdown
                if fm.complexity > 0:
                    pm.complexity_breakdown[str(file_path)] = fm.complexity

                # Extract TODOs
                todos = _extract_todos(content, str(file_path))
                pm.todos.extend(todos)

            pm.total_files += len(filenames)

        pm._compute_derived()
        return pm

    def scan_file(self, file_path: str) -> FileMetrics | None:
        """Scan a single file and return its metrics."""
        fp = Path(file_path)
        if not fp.exists() or not fp.is_file():
            return None
        try:
            content = fp.read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeDecodeError):
            return None

        language = _detect_language(fp)
        if language == "python":
            fm = _scan_python(fp, content)
        else:
            fm = _scan_generic(fp, content)

        fm.size_bytes = fp.stat().st_size
        fm.todo_count = len(re.findall(r"\bTODO\b", content, re.IGNORECASE))
        fm.fixme_count = len(re.findall(r"\bFIXME\b", content, re.IGNORECASE))
        return fm


# ── Convenience ──────────────────────────────────────────────────────────────


def scan_project(root: str | None = None) -> ProjectMetrics:
    """Convenience: scan a project directory and return metrics."""
    scanner = CodebaseScanner(root)
    return scanner.scan()
