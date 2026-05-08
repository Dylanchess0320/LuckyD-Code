"""Code smell detector — identifies common anti-patterns and quality issues."""

import re
from dataclasses import dataclass
from pathlib import Path

from .scanner import ProjectMetrics, PYTHON_EXTENSIONS


# ── Smell type definitions ───────────────────────────────────────────────────


@dataclass
class Smell:
    """A detected code smell."""

    file: str
    line: int
    kind: str  # e.g. "long_function", "deep_nesting", "large_file"
    severity: str  # "info", "warning", "error"
    message: str
    suggestion: str = ""


# ── Individual detectors ─────────────────────────────────────────────────────


class SmellDetector:
    """Detect code smells in files and projects."""

    # Thresholds
    LONG_FUNCTION_LINES = 50
    LONG_FILE_LINES = 500
    DEEP_NESTING = 4
    HIGH_COMPLEXITY = 15
    MANY_PARAMS = 6
    FILE_SIZE_MB_WARNING = 0.5
    DUPLICATION_MIN_LINES = 5
    BIG_CLASS_LINES = 300

    def __init__(self):
        self.smells: list[Smell] = []

    def detect_file(self, file_path: str, content: str | None = None) -> list[Smell]:
        """Detect smells in a single file."""
        self.smells = []
        fp = Path(file_path)

        if content is None:
            try:
                content = fp.read_text(encoding="utf-8", errors="replace")
            except (OSError, UnicodeDecodeError):
                return []

        lines = content.splitlines()

        # Large file
        if len(lines) > self.LONG_FILE_LINES:
            self.smells.append(Smell(
                file=str(fp), line=len(lines),
                kind="large_file", severity="warning",
                message=f"File is {len(lines)} lines (threshold: {self.LONG_FILE_LINES})",
                suggestion="Consider splitting into smaller modules.",
            ))

        # Very large file
        if len(lines) > self.LONG_FILE_LINES * 2:
            self.smells.append(Smell(
                file=str(fp), line=len(lines),
                kind="large_file", severity="error",
                message=f"File is {len(lines)} lines — extremely large",
                suggestion="Split into multiple files immediately.",
            ))

        # Detect long functions (Python-specific)
        if fp.suffix.lower() in PYTHON_EXTENSIONS:
            self._detect_python_smells(content, fp, lines)
        else:
            self._detect_generic_smells(content, fp, lines)

        # Detect deep nesting
        self._detect_deep_nesting(content, fp, lines)

        # Check file size
        try:
            size_mb = fp.stat().st_size / (1024 * 1024)
            if size_mb > self.FILE_SIZE_MB_WARNING:
                self.smells.append(Smell(
                    file=str(fp), line=1,
                    kind="large_file_bytes", severity="warning",
                    message=f"File size is {size_mb:.1f}MB",
                    suggestion="Consider splitting or compressing assets.",
                ))
        except OSError:
            pass

        return self.smells

    def _detect_python_smells(self, content: str, fp: Path, lines: list[str]):
        """Python-specific smell detection."""
        import ast

        try:
            tree = ast.parse(content, filename=str(fp))
        except SyntaxError:
            self.smells.append(Smell(
                file=str(fp), line=1,
                kind="syntax_error", severity="error",
                message="File has a syntax error and cannot be parsed.",
                suggestion="Fix the syntax error.",
            ))
            return

        for node in ast.walk(tree):
            # Long functions
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_lines = node.end_lineno - node.lineno if node.end_lineno else 0
                if func_lines > self.LONG_FUNCTION_LINES:
                    self.smells.append(Smell(
                        file=str(fp), line=node.lineno,
                        kind="long_function", severity="warning",
                        message=f"'{node.name}' is {func_lines} lines long",
                        suggestion=f"Break into smaller functions (<={self.LONG_FUNCTION_LINES} lines).",
                    ))

                # Many parameters
                params = len(node.args.args)
                if params > self.MANY_PARAMS:
                    self.smells.append(Smell(
                        file=str(fp), line=node.lineno,
                        kind="too_many_params", severity="warning",
                        message=f"'{node.name}' has {params} parameters",
                        suggestion="Use a config object/dataclass or split the function.",
                    ))

            # Large classes
            if isinstance(node, ast.ClassDef):
                class_lines = node.end_lineno - node.lineno if node.end_lineno else 0
                if class_lines > self.BIG_CLASS_LINES:
                    self.smells.append(Smell(
                        file=str(fp), line=node.lineno,
                        kind="large_class", severity="warning",
                        message=f"'{node.name}' is {class_lines} lines",
                        suggestion="Split into smaller classes or use composition.",
                    ))

            # Bare except
            if isinstance(node, ast.ExceptHandler):
                if node.type is None:
                    self.smells.append(Smell(
                        file=str(fp), line=node.lineno,
                        kind="bare_except", severity="warning",
                        message="Bare 'except:' clause catches everything including SystemExit",
                        suggestion="Specify exception types: 'except ValueError:'",
                    ))

            # Mutable default arguments
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for default in node.args.defaults + node.args.kw_defaults:
                    if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                        self.smells.append(Smell(
                            file=str(fp), line=node.lineno,
                            kind="mutable_default", severity="warning",
                            message=(
                                f"Mutable default argument in '{node.name}()' "
                                f"({default.__class__.__name__.lower()})"
                            ),
                            suggestion="Use None as default and set the mutable value in the function body.",
                        ))

    def _detect_generic_smells(self, content: str, fp: Path, lines: list[str]):
        """Generic smell detection for any language."""

        # Long function detection via indentation heuristics
        in_func = False
        func_start = 0

        # Function keyword regex
        func_start_re = re.compile(
            r"^\s*(?:def |async def |fn |func |function |pub fn )",
        )

        bare_except_re = re.compile(r"^\s*except\s*:", re.MULTILINE)
        catch_all_re = re.compile(r"catch\s*\(", re.MULTILINE)

        for i, line in enumerate(lines):
            m = func_start_re.match(line)
            if m:
                # End previous function
                if in_func and (i - func_start) > self.LONG_FUNCTION_LINES:
                    self.smells.append(Smell(
                        file=str(fp), line=func_start + 1,
                        kind="long_function", severity="warning",
                        message=f"Function is {i - func_start} lines long",
                        suggestion=f"Break into smaller functions (<={self.LONG_FUNCTION_LINES} lines).",
                    ))
                in_func = True
                func_start = i

        # Check last function
        if in_func and (len(lines) - func_start) > self.LONG_FUNCTION_LINES:
            self.smells.append(Smell(
                file=str(fp), line=func_start + 1,
                kind="long_function", severity="warning",
                message=f"Function is {len(lines) - func_start} lines long",
                suggestion=f"Break into smaller functions (<={self.LONG_FUNCTION_LINES} lines).",
            ))

        # Bare except / catch-all
        if bare_except_re.search(content):
            self.smells.append(Smell(
                file=str(fp), line=1,
                kind="bare_except", severity="warning",
                message="Bare 'except:' found (catches everything)",
                suggestion="Specify exception types.",
            ))
        elif catch_all_re.search(content):
            self.smells.append(Smell(
                file=str(fp), line=1,
                kind="bare_except", severity="warning",
                message="Catch-all 'catch(' found (catches every exception)",
                suggestion="Catch specific exception types.",
            ))

    def _detect_deep_nesting(self, content: str, fp: Path, lines: list[str]):
        """Detect lines with deep indentation."""
        for i, line in enumerate(lines):
            if not line.strip():
                continue
            indent = len(line) - len(line.lstrip())
            # Assume 4-space indentation
            nesting_level = indent // 4
            if nesting_level > self.DEEP_NESTING:
                self.smells.append(Smell(
                    file=str(fp), line=i + 1,
                    kind="deep_nesting", severity="info",
                    message=f"Nesting level {nesting_level} (>{self.DEEP_NESTING})",
                    suggestion="Consider extracting nested logic or using early returns.",
                ))
                # Only report first few occurrences per file
                if len([s for s in self.smells if s.kind == "deep_nesting" and s.file == str(fp)]) >= 3:
                    break

    def detect_project(self, pm: ProjectMetrics) -> list[Smell]:
        """Detect smells across an entire project's metrics."""
        smells = []

        # Files with high complexity
        for path, complexity in pm.complexity_breakdown.items():
            if complexity > self.HIGH_COMPLEXITY:
                smells.append(Smell(
                    file=path, line=1,
                    kind="high_complexity", severity="warning",
                    message=f"Cyclomatic complexity is {complexity}",
                    suggestion="Refactor to reduce branching and nesting.",
                ))

        # Files with high TODO density
        for fm in pm.file_metrics:
            if fm.lines_code > 0:
                todo_density = fm.todo_count / (fm.lines_code / 100)
                if todo_density > 10:
                    smells.append(Smell(
                        file=fm.path, line=1,
                        kind="high_todo_density", severity="info",
                        message=f"{fm.todo_count} TODOs in {fm.lines_code} lines",
                        suggestion="Address or triage outstanding TODOs.",
                    ))

        # Empty files
        for fm in pm.file_metrics:
            if fm.lines_code == 0 and fm.lines_total > 0:
                smells.append(Smell(
                    file=fm.path, line=1,
                    kind="empty_file", severity="info",
                    message="File has no code lines",
                    suggestion="Remove empty files or add content.",
                ))

        # Large files (project-level)
        for fm in pm.file_metrics:
            if fm.lines_total > self.LONG_FILE_LINES:
                smells.append(Smell(
                    file=fm.path, line=fm.lines_total,
                    kind="large_file", severity="warning",
                    message=f"File is {fm.lines_total} lines (threshold: {self.LONG_FILE_LINES})",
                    suggestion="Consider splitting into smaller modules.",
                ))

        return smells + self.smells


# ── Convenience ──────────────────────────────────────────────────────────────


def detect_smells(path: str | None = None) -> list[Smell]:
    """Convenience: detect smells in a file or project."""
    detector = SmellDetector()

    if path is None:
        # Scan whole project
        from .scanner import scan_project
        pm = scan_project()
        return detector.detect_project(pm)

    fp = Path(path)
    if fp.is_file():
        return detector.detect_file(str(fp))

    if fp.is_dir():
        from .scanner import CodebaseScanner
        scanner = CodebaseScanner(str(fp))
        pm = scanner.scan()
        return detector.detect_project(pm)

    return []
