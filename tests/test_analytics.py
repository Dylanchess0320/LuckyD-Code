"""Tests for the analytics module."""
import json
from pathlib import Path


from luckyd_code.analytics.scanner import (
    CodebaseScanner,
    scan_project,
    _detect_language,
    _count_lines,
    _generic_complexity,
    _extract_todos,
)
from luckyd_code.analytics.smells import (
    SmellDetector,
    detect_smells,
)
from luckyd_code.analytics.reporter import (
    generate_report,
)
from luckyd_code.analytics.trends import (
    TrendTracker,
    TrendPoint,
    snapshot_project,
    get_trends,
)


class TestScanner:
    """Tests for the codebase scanner."""

    def test_detect_language(self):
        assert _detect_language(Path("test.py")) == "python"
        assert _detect_language(Path("test.js")) == "javascript"
        assert _detect_language(Path("test.ts")) == "typescript"
        assert _detect_language(Path("test.go")) == "go"
        assert _detect_language(Path("test.rs")) == "rust"
        assert _detect_language(Path("test.rb")) == "ruby"
        assert _detect_language(Path("test.unknown")) == "unknown"

    def test_count_lines(self):
        content = "line1\nline2\n\nline4\n"
        total, code, blank = _count_lines(content)
        assert total == 4
        assert code == 3
        assert blank == 1

    def test_generic_complexity(self):
        content = """if (a) { if (b) { while (c) { for (;;) {} } } }"""
        complexity = _generic_complexity(content)
        assert complexity >= 4  # at least 4 branches

    def test_extract_todos(self):
        content = """# TODO: fix this
# FIXME: urgent bug
normal code
# HACK: terrible hack
"""
        todos = _extract_todos(content, "test.py")
        assert len(todos) == 3
        kinds = {t["kind"] for t in todos}
        assert "TODO" in kinds
        assert "FIXME" in kinds
        assert "HACK" in kinds

    def test_scan_file_python(self, tmp_path):
        """Test scanning a simple Python file."""
        file_path = tmp_path / "test.py"
        file_path.write_text("""\"\"\"A test module.\"\"\"
import os

def hello(name):
    \"\"\"Say hello.\"\"\"
    if name:
        return f"Hello, {name}"
    return "Hello, world"

class Greeter:
    def greet(self, name):
        return hello(name)
""", encoding="utf-8")

        scanner = CodebaseScanner(str(tmp_path))
        fm = scanner.scan_file(str(file_path))
        assert fm is not None
        assert fm.language == "python"
        assert fm.function_count == 2  # hello + greet
        assert fm.class_count == 1
        assert fm.lines_code > 0

    def test_scan_project(self, tmp_path):
        """Test scanning a project directory."""
        # Create some test files
        (tmp_path / "main.py").write_text("# Main file\ndef main():\n    pass\n", encoding="utf-8")
        (tmp_path / "utils.py").write_text("# Utils\ndef helper():\n    return True\n", encoding="utf-8")
        (tmp_path / "app.js").write_text("// App\nfunction init() {}\n", encoding="utf-8")
        (tmp_path / "README.md").write_text("# Project\n", encoding="utf-8")
        # Create a hidden dir that should be skipped
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("", encoding="utf-8")

        pm = scan_project(str(tmp_path))
        assert pm.source_files >= 3  # main.py, utils.py, app.js (not README.md)
        assert pm.total_functions >= 2  # main + helper + init
        assert pm.total_code_lines > 0
        assert "python" in pm.files_by_language
        assert "javascript" in pm.files_by_language

    def test_health_score(self, tmp_path):
        """Test health score calculation."""
        (tmp_path / "clean.py").write_text("""
def small():
    return 1

def also_small():
    return 2
""", encoding="utf-8")

        pm = scan_project(str(tmp_path))
        assert pm.health_score > 50  # Should be fairly healthy
        assert 0 <= pm.health_score <= 100

    def test_scan_empty_project(self, tmp_path):
        """Test scanning a directory with no source files."""
        pm = scan_project(str(tmp_path))
        assert pm.source_files == 0
        assert pm.health_score == 100  # No code = no problems

    def test_metrics_to_dict(self, tmp_path):
        """Test that ProjectMetrics can be serialized to dict."""
        (tmp_path / "test.py").write_text("x = 1", encoding="utf-8")
        pm = scan_project(str(tmp_path))
        d = pm.to_dict()
        assert isinstance(d, dict)
        assert "health_score" in d
        assert "avg_complexity" in d
        # Should be JSON-serializable
        json.dumps(d)


class TestSmells:
    """Tests for the smell detector."""

    def test_detect_long_function(self, tmp_path):
        """Detect functions that are too long."""
        lines = ["def long_func():"] + ["    x = i" for i in range(60)] + [""]
        content = "\n".join(lines)
        file_path = tmp_path / "long.py"
        file_path.write_text(content, encoding="utf-8")

        detector = SmellDetector()
        smells = detector.detect_file(str(file_path))
        long_funcs = [s for s in smells if s.kind == "long_function"]
        assert len(long_funcs) >= 1

    def test_detect_large_file(self, tmp_path):
        """Detect files that exceed size thresholds."""
        content = "\n".join(["x = 1"] * 600)  # 600 lines
        file_path = tmp_path / "big.py"
        file_path.write_text(content, encoding="utf-8")

        detector = SmellDetector()
        smells = detector.detect_file(str(file_path))
        large_files = [s for s in smells if s.kind == "large_file"]
        assert len(large_files) >= 1

    def test_detect_deep_nesting(self, tmp_path):
        """Detect deeply nested code."""
        content = """def deep():
    if a:
        if b:
            if c:
                if d:
                    if e:
                        if f:
                            pass
"""
        file_path = tmp_path / "deep.py"
        file_path.write_text(content, encoding="utf-8")

        detector = SmellDetector()
        smells = detector.detect_file(str(file_path))
        nesting = [s for s in smells if s.kind == "deep_nesting"]
        assert len(nesting) >= 1

    def test_detect_bare_except(self, tmp_path):
        """Detect bare except clauses."""
        content = """
try:
    risky()
except:
    pass
"""
        file_path = tmp_path / "bare.py"
        file_path.write_text(content, encoding="utf-8")

        detector = SmellDetector()
        smells = detector.detect_file(str(file_path))
        bare = [s for s in smells if s.kind == "bare_except"]
        assert len(bare) >= 1

    def test_detect_too_many_params(self, tmp_path):
        """Detect functions with too many parameters."""
        content = """def many(a, b, c, d, e, f, g, h):
    pass
"""
        file_path = tmp_path / "params.py"
        file_path.write_text(content, encoding="utf-8")

        detector = SmellDetector()
        smells = detector.detect_file(str(file_path))
        params = [s for s in smells if s.kind == "too_many_params"]
        assert len(params) >= 1

    def test_detect_high_complexity_on_project(self, tmp_path):
        """Project-level smell detection for high complexity files."""
        # Create a function with high cyclomatic complexity (>15 branches)
        # 16+ if/elif/for/while branches
        content = """def complex_func(x):
    if x == 1:
        pass
    elif x == 2:
        pass
    elif x == 3:
        pass
    elif x == 4:
        pass
    elif x == 5:
        pass
    elif x == 6:
        if x > 3:
            pass
    elif x == 7:
        pass
    elif x == 8:
        pass
    elif x == 9:
        pass
    elif x == 10:
        while x > 0:
            x -= 1
    elif x == 11:
        pass
    elif x == 12:
        pass
    elif x == 13:
        pass
    elif x == 14:
        pass
    elif x == 15:
        for i in range(10):
            if i % 2:
                pass
    else:
        pass
    return x
"""
        (tmp_path / "complex.py").write_text(content, encoding="utf-8")

        from luckyd_code.analytics.scanner import scan_project
        pm = scan_project(str(tmp_path))
        # Verify complexity is high enough
        assert pm.total_complexity >= 15, f"Complexity is {pm.total_complexity}, expected >= 15"
        detector = SmellDetector()
        smells = detector.detect_project(pm)
        # Should detect high complexity
        complex_smells = [s for s in smells if s.kind == "high_complexity"]
        assert len(complex_smells) >= 1, f"Smells found: {[s.kind for s in smells]}"

    def test_convenience_detect_smells(self, tmp_path):
        """Test the convenience detect_smells function."""
        (tmp_path / "test.py").write_text("x = 1\ny = 2\n", encoding="utf-8")
        smells = detect_smells(str(tmp_path))
        assert isinstance(smells, list)

    def test_severity_levels(self, tmp_path):
        """Test that smells have correct severity levels."""
        # Error: syntax error
        (tmp_path / "broken.py").write_text("def broken(\n", encoding="utf-8")
        detector = SmellDetector()
        smells = detector.detect_file(str(tmp_path / "broken.py"))
        errors = [s for s in smells if s.severity == "error"]
        assert len(errors) >= 1


class TestReporter:
    """Tests for the report generator."""

    def test_generate_terminal_report(self, tmp_path):
        (tmp_path / "test.py").write_text("def hello():\n    return 'hi'\n", encoding="utf-8")
        pm = scan_project(str(tmp_path))
        report = generate_report(pm, fmt="terminal")
        assert "HEALTH REPORT" in report
        assert "test.py" in report

    def test_generate_markdown_report(self, tmp_path):
        (tmp_path / "test.py").write_text("x = 1\n", encoding="utf-8")
        pm = scan_project(str(tmp_path))
        report = generate_report(pm, fmt="markdown")
        assert "# Codebase Health Report" in report
        assert "|" in report

    def test_generate_json_report(self, tmp_path):
        (tmp_path / "test.py").write_text("x = 1\n", encoding="utf-8")
        pm = scan_project(str(tmp_path))
        report = generate_report(pm, fmt="json")
        data = json.loads(report)
        assert "project" in data
        assert "smells" in data

    def test_generate_html_report(self, tmp_path):
        (tmp_path / "test.py").write_text("x = 1\n", encoding="utf-8")
        pm = scan_project(str(tmp_path))
        report = generate_report(pm, fmt="html")
        assert "<!DOCTYPE html>" in report
        assert "</html>" in report

    def test_generate_report_with_smells(self, tmp_path):
        (tmp_path / "big.py").write_text("\n".join(["x = 1"] * 600), encoding="utf-8")
        pm = scan_project(str(tmp_path))
        from luckyd_code.analytics.smells import SmellDetector
        detector = SmellDetector()
        smells = detector.detect_project(pm)
        report = generate_report(pm, smells=smells, fmt="terminal")
        assert "Code Smells" in report

    def test_generate_report_to_file(self, tmp_path):
        (tmp_path / "test.py").write_text("x = 1\n", encoding="utf-8")
        pm = scan_project(str(tmp_path))
        output = tmp_path / "report.md"
        result = generate_report(pm, fmt="markdown", output_path=str(output))
        assert output.exists()
        assert "Report written" in result

    def test_format_size(self):
        from luckyd_code.analytics.reporter import _format_size
        assert "B" in _format_size(100)
        assert "KB" in _format_size(2000)
        assert "MB" in _format_size(2000000)
        assert "GB" in _format_size(2000000000)


class TestTrends:
    """Tests for trend tracking."""

    def test_take_snapshot(self, tmp_path, monkeypatch):
        """Test taking a snapshot."""
        # Create test files
        (tmp_path / "test.py").write_text("x = 1\n", encoding="utf-8")

        # Change working directory for the trend tracker
        monkeypatch.chdir(tmp_path)

        # Clear any existing analytics
        tracker = TrendTracker()
        tracker.clear()

        point = tracker.snapshot()
        assert point.source_files >= 1
        assert point.health_score >= 0

        # Clean up
        tracker.clear()

    def test_compare_snapshots(self, tmp_path, monkeypatch):
        """Test comparing two snapshots."""
        (tmp_path / "v1.py").write_text("x = 1\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        tracker = TrendTracker()
        tracker.clear()

        # First snapshot
        _ = tracker.snapshot()

        # Add more code
        (tmp_path / "v2.py").write_text("def foo():\n    return 42\n", encoding="utf-8")

        # Second snapshot
        _ = tracker.snapshot()

        report = tracker.compare()
        assert report.delta_files > 0  # Should have added a file
        assert report.direction in ("improving", "declining", "stable")

        # Clean up
        tracker.clear()

    def test_trend_summary(self, tmp_path, monkeypatch):
        """Test generating a trend summary."""
        (tmp_path / "test.py").write_text("x = 1\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        tracker = TrendTracker()
        tracker.clear()
        tracker.snapshot()
        summary = tracker.trend_summary()

        # With only one snapshot
        assert "Not enough data" in summary

        # Add another
        (tmp_path / "test2.py").write_text("y = 2\n", encoding="utf-8")
        tracker.snapshot()
        summary = tracker.trend_summary()
        assert "Snapshots:" in summary
        assert "Code lines" in summary

        tracker.clear()

    def test_clear(self, tmp_path, monkeypatch):
        """Test clearing all snapshots."""
        (tmp_path / "test.py").write_text("x = 1\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        tracker = TrendTracker()
        tracker.snapshot()
        assert len(tracker.get_all()) >= 1
        tracker.clear()
        assert len(tracker.get_all()) == 0

    def test_convenience_functions(self, tmp_path, monkeypatch):
        """Test the convenience functions."""
        (tmp_path / "test.py").write_text("x = 1\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        tracker = TrendTracker()
        tracker.clear()

        point = snapshot_project()
        assert isinstance(point, TrendPoint)

        summary = get_trends()
        assert isinstance(summary, str)

        tracker.clear()
