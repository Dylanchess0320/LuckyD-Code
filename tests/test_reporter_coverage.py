"""Tests for luckyd_code.analytics.reporter — covers uncovered branches.

Target uncovered lines (from cov_out.txt):
  15       _format_size: TB branch
  58-61    terminal(): Top Complexity section (when complexity_breakdown is populated)
  80       terminal(): if pm.todos section
  82,84    terminal(): if self.smells section
  137-142  markdown(): if self.smells section
  145-147  markdown(): smells per-item rendering
  175-176  generate_report(): html + output_path branches
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from luckyd_code.analytics.reporter import ReportGenerator, _format_size, generate_report


# ────────────────────────────────────────────────────────────────────────────
# _format_size — TB branch (line 15)
# ────────────────────────────────────────────────────────────────────────────

class TestFormatSize:
    def test_bytes(self):
        assert "B" in _format_size(512)

    def test_kilobytes(self):
        assert "KB" in _format_size(2048)

    def test_megabytes(self):
        assert "MB" in _format_size(2 * 1024 * 1024)

    def test_gigabytes(self):
        assert "GB" in _format_size(3 * 1024 ** 3)

    def test_terabytes(self):
        """Line 15: the TB branch — > 1 GB triggers the return."""
        result = _format_size(2 * 1024 ** 4)
        assert "TB" in result


# ────────────────────────────────────────────────────────────────────────────
# Helpers — build mock ProjectMetrics-like objects
# ────────────────────────────────────────────────────────────────────────────

def _make_pm(
    *,
    root="/proj",
    health_score=80,
    source_files=10,
    total_lines=1000,
    total_code_lines=800,
    total_size_bytes=50000,
    total_functions=30,
    total_classes=5,
    total_todos=3,
    total_fixmes=1,
    avg_complexity=2.5,
    files_by_language=None,
    complexity_breakdown=None,
    todos=None,
    file_metrics=None,
):
    pm = MagicMock()
    pm.root = root
    pm.health_score = health_score
    pm.source_files = source_files
    pm.total_lines = total_lines
    pm.total_code_lines = total_code_lines
    pm.total_size_bytes = total_size_bytes
    pm.total_functions = total_functions
    pm.total_classes = total_classes
    pm.total_todos = total_todos
    pm.total_fixmes = total_fixmes
    pm.avg_complexity = avg_complexity
    pm.files_by_language = files_by_language or {"py": 10}
    pm.complexity_breakdown = complexity_breakdown or {}
    pm.todos = todos or []
    pm.file_metrics = file_metrics or []
    pm.to_dict.return_value = {"root": root}
    return pm


def _make_smell(
    severity="warning",
    kind="LongFunction",
    file="main.py",
    line=42,
    message="Function is too long",
    suggestion="Refactor into smaller functions",
):
    s = MagicMock()
    s.severity = severity
    s.kind = kind
    s.file = file
    s.line = line
    s.message = message
    s.suggestion = suggestion
    return s


# ────────────────────────────────────────────────────────────────────────────
# terminal() — Top Complexity section (lines 58-61)
# ────────────────────────────────────────────────────────────────────────────

class TestTerminalReport:
    def test_top_complexity_section_rendered(self):
        """Lines 58-61: complexity_breakdown populated → Top Complexity block."""
        pm = _make_pm(complexity_breakdown={"main.py": 25, "utils.py": 15})
        gen = ReportGenerator(pm)
        result = gen.terminal()
        assert "Top Complexity" in result
        assert "main.py" in result

    def test_no_complexity_section_when_empty(self):
        pm = _make_pm(complexity_breakdown={})
        gen = ReportGenerator(pm)
        result = gen.terminal()
        assert "Top Complexity" not in result

    def test_todos_section_rendered(self):
        """Line 80: if pm.todos → TODOs section rendered."""
        todos = [
            {"kind": "TODO", "file": "app.py", "line": 10, "text": "fix this later"},
            {"kind": "FIXME", "file": "api.py", "line": 20, "text": "broken edge case"},
        ]
        pm = _make_pm(todos=todos, total_todos=2)
        gen = ReportGenerator(pm)
        result = gen.terminal()
        assert "TODOs" in result
        assert "fix this later" in result

    def test_no_todos_section_when_empty(self):
        pm = _make_pm(todos=[], total_todos=0)
        gen = ReportGenerator(pm)
        result = gen.terminal()
        assert "TODOs & FIXMEs" not in result

    def test_smells_section_rendered(self):
        """Lines 82, 84: if self.smells → Code Smells block."""
        smell = _make_smell()
        pm = _make_pm()
        gen = ReportGenerator(pm, smells=[smell])
        result = gen.terminal()
        assert "Code Smells" in result
        assert "LongFunction" in result
        assert "Refactor" in result

    def test_smells_with_no_message_no_suggestion(self):
        """Smell with empty message and suggestion — lines still rendered without crash."""
        smell = _make_smell(message="", suggestion="")
        pm = _make_pm()
        gen = ReportGenerator(pm, smells=[smell])
        result = gen.terminal()
        assert "Code Smells" in result

    def test_files_needing_attention_section(self):
        """Files with high complexity / todos appear in attention section."""
        fm = MagicMock()
        fm.path = "complex_module.py"
        fm.lines_code = 400   # > 300
        fm.complexity = 25    # > 20
        fm.todo_count = 6     # > 5
        fm.fixme_count = 3    # > 2
        pm = _make_pm(file_metrics=[fm])
        gen = ReportGenerator(pm)
        result = gen.terminal()
        assert "Files Needing Attention" in result
        assert "complex_module.py" in result

    def test_no_attention_section_when_all_clean(self):
        fm = MagicMock()
        fm.path = "clean.py"
        fm.lines_code = 50
        fm.complexity = 3
        fm.todo_count = 0
        fm.fixme_count = 0
        pm = _make_pm(file_metrics=[fm])
        gen = ReportGenerator(pm)
        result = gen.terminal()
        assert "Files Needing Attention" not in result

    def test_languages_section_rendered(self):
        pm = _make_pm(files_by_language={"py": 8, "js": 3})
        gen = ReportGenerator(pm)
        result = gen.terminal()
        assert "Languages" in result
        assert "py" in result


# ────────────────────────────────────────────────────────────────────────────
# markdown() — smells section (lines 137-147)
# ────────────────────────────────────────────────────────────────────────────

class TestMarkdownReport:
    def test_basic_markdown_output(self):
        pm = _make_pm()
        gen = ReportGenerator(pm)
        result = gen.markdown()
        assert "# Codebase Health Report" in result
        assert "Health Score" in result

    def test_smells_section_in_markdown(self):
        """Lines 137-147: Code Smells rendered in markdown."""
        smell = _make_smell(
            severity="error",
            kind="GodClass",
            file="monster.py",
            line=1,
            message="Too many responsibilities",
            suggestion="Split into smaller classes",
        )
        pm = _make_pm()
        gen = ReportGenerator(pm, smells=[smell])
        result = gen.markdown()
        assert "Code Smells" in result
        assert "GodClass" in result
        assert "monster.py" in result

    def test_todos_table_in_markdown(self):
        todos = [{"kind": "TODO", "file": "svc.py", "line": 5, "text": "handle errors"}]
        pm = _make_pm(todos=todos, total_todos=1)
        gen = ReportGenerator(pm)
        result = gen.markdown()
        assert "TODOs & FIXMEs" in result
        assert "svc.py" in result

    def test_top_complexity_in_markdown(self):
        pm = _make_pm(complexity_breakdown={"heavy.py": 30})
        gen = ReportGenerator(pm)
        result = gen.markdown()
        assert "Top Complexity" in result
        assert "heavy.py" in result

    def test_languages_in_markdown(self):
        pm = _make_pm(files_by_language={"py": 7, "ts": 2})
        gen = ReportGenerator(pm)
        result = gen.markdown()
        assert "Languages" in result
        assert "ts" in result


# ────────────────────────────────────────────────────────────────────────────
# json_report()
# ────────────────────────────────────────────────────────────────────────────

class TestJsonReport:
    def test_returns_valid_json(self):
        pm = _make_pm()
        gen = ReportGenerator(pm)
        result = gen.json_report()
        data = json.loads(result)
        assert "project" in data
        assert "smells" in data
        assert "generated_at" in data

    def test_smells_serialized(self):
        from dataclasses import dataclass

        @dataclass
        class FakeSmell:
            severity: str = "warning"
            kind: str = "LongMethod"
            file: str = "foo.py"
            line: int = 1
            message: str = "too long"
            suggestion: str = "refactor"

        pm = _make_pm()
        gen = ReportGenerator(pm, smells=[FakeSmell()])
        result = gen.json_report()
        data = json.loads(result)
        assert len(data["smells"]) == 1
        assert data["smells"][0]["kind"] == "LongMethod"


# ────────────────────────────────────────────────────────────────────────────
# html()
# ────────────────────────────────────────────────────────────────────────────

class TestHtmlReport:
    def test_returns_html_with_doctype(self):
        pm = _make_pm()
        gen = ReportGenerator(pm)
        result = gen.html()
        assert "<!DOCTYPE html>" in result
        assert "<html>" in result

    def test_html_contains_markdown_content(self):
        pm = _make_pm()
        gen = ReportGenerator(pm)
        result = gen.html()
        assert "Health Report" in result


# ────────────────────────────────────────────────────────────────────────────
# generate_report() — fmt variants and output_path (lines 175-176)
# ────────────────────────────────────────────────────────────────────────────

class TestGenerateReport:
    def test_default_terminal_format(self):
        pm = _make_pm()
        result = generate_report(pm=pm, fmt="terminal")
        assert "CODEBASE HEALTH REPORT" in result

    def test_markdown_format(self):
        pm = _make_pm()
        result = generate_report(pm=pm, fmt="markdown")
        assert "# Codebase Health Report" in result

    def test_json_format(self):
        pm = _make_pm()
        result = generate_report(pm=pm, fmt="json")
        data = json.loads(result)
        assert "project" in data

    def test_html_format(self):
        pm = _make_pm()
        result = generate_report(pm=pm, fmt="html")
        assert "<!DOCTYPE html>" in result

    def test_output_path_writes_file(self, tmp_path):
        """Lines 175-176: output_path → writes file and returns confirmation string."""
        pm = _make_pm()
        out = tmp_path / "report.txt"
        result = generate_report(pm=pm, fmt="terminal", output_path=str(out))
        assert out.exists()
        assert "report" in result.lower() or str(out) in result

    def test_pm_none_triggers_scan(self):
        """When pm=None, generate_report calls scan_project."""
        pm = _make_pm()
        with patch("luckyd_code.analytics.reporter.scan_project", return_value=pm) as mock_scan:
            result = generate_report(pm=None, fmt="terminal")
        mock_scan.assert_called_once()
        assert isinstance(result, str)
