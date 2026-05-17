"""Final coverage gap-fillers — fixed for path-traversal guard and httpx mock.

Covers:
  - tools/file_ops.py  (19 missed): ReadTool, WriteTool, EditTool, Grep/Glob
  - tools/readme_gen.py (14 missed): _collect_files helpers, run() edge paths
  - tools/project_gen.py (7 missed): run() error paths
  - feedback_analyzer.py (14 missed): misc branches
  - orchestrator.py (6 missed): _truncate_to_tokens, tester-only path

FIX STRATEGY
-----------
* file_ops — use ``monkeypatch.chdir(tmp_path)`` so that
  validate_file_path() considers tmp_path the allowed root and every file
  written inside it passes the security check without any mocking of the
  guard itself.
* feedback_analyzer HTTP error — use a plain _Resp class (not MagicMock)
  for the httpx.HTTPStatusError response, avoiding the None-text bug.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest


# ═══════════════════════════════════════════════════════════════════════════════
# ReadTool
# ═══════════════════════════════════════════════════════════════════════════════

class TestReadToolExceptions:
    def test_read_raises_on_binary_read_error(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from luckyd_code.tools.file_ops import ReadTool
        f = tmp_path / "locked.py"
        f.write_text("x = 1")
        tool = ReadTool()
        with patch.object(Path, "read_text", side_effect=OSError("permission denied")):
            result = tool.run(str(f))
        assert "Error" in result

    def test_read_offset_beyond_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from luckyd_code.tools.file_ops import ReadTool
        f = tmp_path / "short.py"
        f.write_text("line1\nline2\n")
        tool = ReadTool()
        result = tool.run(str(f), offset=999)
        assert "Error" in result and "offset" in result.lower()

    def test_read_with_limit(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from luckyd_code.tools.file_ops import ReadTool
        f = tmp_path / "many.py"
        f.write_text("\n".join(f"line{i}" for i in range(20)))
        tool = ReadTool()
        result = tool.run(str(f), limit=5)
        assert "line0" in result
        assert "line19" not in result

    def test_read_not_a_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from luckyd_code.tools.file_ops import ReadTool
        tool = ReadTool()
        # Pass a subdirectory — validate_file_path passes but is_file() is False
        subdir = tmp_path / "adir"
        subdir.mkdir()
        result = tool.run(str(subdir))
        assert "Error" in result

    def test_read_nonexistent_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from luckyd_code.tools.file_ops import ReadTool
        tool = ReadTool()
        result = tool.run(str(tmp_path / "ghost.py"))
        assert "Error" in result

    def test_read_success(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from luckyd_code.tools.file_ops import ReadTool
        f = tmp_path / "ok.py"
        f.write_text("hello = 1\n")
        tool = ReadTool()
        result = tool.run(str(f))
        assert "hello = 1" in result


# ═══════════════════════════════════════════════════════════════════════════════
# WriteTool
# ═══════════════════════════════════════════════════════════════════════════════

class TestWriteToolErrorPaths:
    def test_write_validate_raises_value_error(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from luckyd_code.tools.file_ops import WriteTool
        tool = WriteTool()
        # Path that escapes tmp_path triggers the ValueError
        with patch("luckyd_code.tools.file_ops.validate_file_path",
                   side_effect=ValueError("bad path")):
            result = tool.run("/some/outside/path.py", "content")
        assert "Error" in result

    def test_write_oversized_content(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from luckyd_code.tools.file_ops import WriteTool
        f = tmp_path / "big.py"
        tool = WriteTool()
        big = "x" * (10 * 1024 * 1024 + 1)
        result = tool.run(str(f), big)
        assert "10MB" in result or "maximum" in result.lower()

    def test_write_disk_error(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from luckyd_code.tools.file_ops import WriteTool
        f = tmp_path / "out.py"
        tool = WriteTool()
        with patch.object(Path, "write_text", side_effect=OSError("disk full")):
            result = tool.run(str(f), "x = 1")
        assert "Error" in result

    def test_write_new_file_message(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from luckyd_code.tools.file_ops import WriteTool
        f = tmp_path / "new.py"
        tool = WriteTool()
        result = tool.run(str(f), "x = 1\n")
        assert "new file" in result.lower()

    def test_write_existing_file_shows_diff_stats(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from luckyd_code.tools.file_ops import WriteTool
        f = tmp_path / "existing.py"
        f.write_text("x = 1\n")
        tool = WriteTool()
        result = tool.run(str(f), "x = 2\n")
        assert "changed" in result.lower() or "bytes" in result.lower()

    def test_write_dry_run_new_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from luckyd_code.tools.file_ops import WriteTool
        f = tmp_path / "dry.py"
        tool = WriteTool()
        result = tool.run(str(f), "a = 1\nb = 2\n", dry_run=True)
        assert "[dry-run]" in result
        assert not f.exists()

    def test_write_dry_run_identical_content(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from luckyd_code.tools.file_ops import WriteTool
        f = tmp_path / "same.py"
        f.write_text("x = 1\n")
        tool = WriteTool()
        result = tool.run(str(f), "x = 1\n", dry_run=True)
        assert "identical" in result.lower() or "no changes" in result.lower()

    def test_write_dry_run_shows_diff(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from luckyd_code.tools.file_ops import WriteTool
        f = tmp_path / "change.py"
        f.write_text("x = 1\n")
        tool = WriteTool()
        result = tool.run(str(f), "x = 99\n", dry_run=True)
        assert "[dry-run]" in result
        assert "---" in result or "+++" in result


# ═══════════════════════════════════════════════════════════════════════════════
# EditTool
# ═══════════════════════════════════════════════════════════════════════════════

class TestEditToolErrorPaths:
    def test_edit_read_error(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from luckyd_code.tools.file_ops import EditTool
        f = tmp_path / "err.py"
        f.write_text("x = 1")
        tool = EditTool()
        with patch.object(Path, "read_text", side_effect=OSError("locked")):
            result = tool.run(str(f), "x", "y")
        assert "Error" in result

    def test_edit_old_string_not_found(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from luckyd_code.tools.file_ops import EditTool
        f = tmp_path / "code.py"
        f.write_text("x = 1\n")
        tool = EditTool()
        result = tool.run(str(f), "NOTFOUND", "replaced")
        assert "not found" in result.lower()

    def test_edit_ambiguous_string(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from luckyd_code.tools.file_ops import EditTool
        f = tmp_path / "dup.py"
        f.write_text("x = 1\nx = 1\n")
        tool = EditTool()
        result = tool.run(str(f), "x = 1", "y = 2")
        assert "times" in result.lower() or "replace_all" in result.lower()

    def test_edit_replace_all(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from luckyd_code.tools.file_ops import EditTool
        f = tmp_path / "multi.py"
        f.write_text("x = 1\nx = 1\nx = 1\n")
        tool = EditTool()
        result = tool.run(str(f), "x = 1", "y = 2", replace_all=True)
        assert "3" in result or "replacement" in result.lower()
        assert f.read_text() == "y = 2\ny = 2\ny = 2\n"

    def test_edit_dry_run_identical(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from luckyd_code.tools.file_ops import EditTool
        f = tmp_path / "nochange.py"
        f.write_text("x = 1\n")
        tool = EditTool()
        result = tool.run(str(f), "x = 1", "x = 1", dry_run=True)
        assert "identical" in result.lower() or "no changes" in result.lower()

    def test_edit_dry_run_shows_diff(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from luckyd_code.tools.file_ops import EditTool
        f = tmp_path / "edit.py"
        f.write_text("foo = 1\n")
        tool = EditTool()
        result = tool.run(str(f), "foo", "bar", dry_run=True)
        assert "[dry-run]" in result
        assert "bar" not in f.read_text()

    def test_edit_write_error(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from luckyd_code.tools.file_ops import EditTool
        f = tmp_path / "write_err.py"
        f.write_text("x = 1\n")
        tool = EditTool()
        with patch.object(Path, "write_text", side_effect=OSError("no space")):
            result = tool.run(str(f), "x = 1", "x = 2")
        assert "Error" in result


# ═══════════════════════════════════════════════════════════════════════════════
# GrepTool / GlobTool
# ═══════════════════════════════════════════════════════════════════════════════

class TestGrepToolOutputModes:
    def test_grep_count_mode(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from luckyd_code.tools.file_ops import GrepTool
        f = tmp_path / "code.py"
        f.write_text("hello world\nhello again\ngoodbye\n")
        tool = GrepTool()
        result = tool.run("hello", path=str(tmp_path), output_mode="count")
        assert "2" in result
        assert "match" in result.lower()

    def test_grep_files_with_matches_mode(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from luckyd_code.tools.file_ops import GrepTool
        (tmp_path / "a.py").write_text("hello\n")
        (tmp_path / "b.py").write_text("world\n")
        tool = GrepTool()
        result = tool.run("hello", path=str(tmp_path), output_mode="files_with_matches")
        assert "a.py" in result
        assert "b.py" not in result

    def test_grep_invalid_regex(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from luckyd_code.tools.file_ops import GrepTool
        tool = GrepTool()
        result = tool.run("[invalid(", path=str(tmp_path))
        assert "Invalid regex" in result or "Error" in result

    def test_grep_on_single_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from luckyd_code.tools.file_ops import GrepTool
        f = tmp_path / "single.py"
        f.write_text("needle_here\nno match\n")
        tool = GrepTool()
        result = tool.run("needle_here", path=str(f))
        assert "needle_here" in result

    def test_grep_glob_filter(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from luckyd_code.tools.file_ops import GrepTool
        (tmp_path / "a.py").write_text("pattern_here\n")
        (tmp_path / "b.txt").write_text("pattern_here\n")
        tool = GrepTool()
        result = tool.run("pattern_here", path=str(tmp_path), glob="*.py")
        assert "a.py" in result
        assert "b.txt" not in result

    def test_grep_no_matches(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from luckyd_code.tools.file_ops import GrepTool
        (tmp_path / "f.py").write_text("nothing relevant\n")
        tool = GrepTool()
        result = tool.run("ZZZNOMATCH", path=str(tmp_path))
        assert "No matches" in result

    def test_glob_tool_no_matches(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from luckyd_code.tools.file_ops import GlobTool
        (tmp_path / "placeholder.py").write_text("# keeps dir non-empty")
        tool = GlobTool()
        result = tool.run("**/*.nonexistent_ext", path=str(tmp_path))
        assert "No files" in result

    def test_glob_tool_not_a_dir(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from luckyd_code.tools.file_ops import GlobTool
        f = tmp_path / "file.py"
        f.write_text("x = 1")
        tool = GlobTool()
        result = tool.run("*.py", path=str(f))
        assert "Error" in result

    def test_glob_tool_success(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from luckyd_code.tools.file_ops import GlobTool
        (tmp_path / "foo.py").write_text("x = 1")
        (tmp_path / "bar.py").write_text("y = 2")
        tool = GlobTool()
        result = tool.run("*.py", path=str(tmp_path))
        assert "foo.py" in result
        assert "bar.py" in result


# ═══════════════════════════════════════════════════════════════════════════════
# tools/readme_gen.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestCollectFiles:
    def test_collect_skips_dot_dirs(self, tmp_path):
        from luckyd_code.tools.readme_gen import _collect_files
        (tmp_path / ".hidden").mkdir()
        (tmp_path / ".hidden" / "secret.py").write_text("x = 1")
        (tmp_path / "visible.py").write_text("y = 2")
        collected = _collect_files(tmp_path)
        paths = [rel for rel, _ in collected]
        assert any("visible.py" in p for p in paths)
        assert not any(".hidden" in p for p in paths)

    def test_collect_skips_node_modules(self, tmp_path):
        from luckyd_code.tools.readme_gen import _collect_files
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "dep.js").write_text("module.exports = {}")
        (tmp_path / "index.js").write_text("require('./dep')")
        collected = _collect_files(tmp_path)
        paths = [rel for rel, _ in collected]
        assert not any("node_modules" in p for p in paths)

    def test_collect_skips_pyc_extension(self, tmp_path):
        from luckyd_code.tools.readme_gen import _collect_files
        (tmp_path / "code.pyc").write_bytes(b"compiled")
        (tmp_path / "code.py").write_text("x = 1")
        collected = _collect_files(tmp_path)
        paths = [rel for rel, _ in collected]
        assert any(".py" in p and ".pyc" not in p for p in paths)
        assert not any(".pyc" in p for p in paths)

    def test_collect_truncates_large_files(self, tmp_path):
        from luckyd_code.tools.readme_gen import _collect_files, _MAX_FILE_CHARS
        big = tmp_path / "big.py"
        big.write_text("x\n" * (_MAX_FILE_CHARS + 500))
        collected = _collect_files(tmp_path)
        snippets = {rel: content for rel, content in collected}
        assert "big.py" in snippets
        assert "truncated" in snippets["big.py"]

    def test_collect_prioritises_known_files(self, tmp_path):
        from luckyd_code.tools.readme_gen import _collect_files
        (tmp_path / "requirements.txt").write_text("flask\n")
        (tmp_path / "zzz_last.py").write_text("# last")
        collected = _collect_files(tmp_path)
        paths = [rel for rel, _ in collected]
        req_idx = next((i for i, p in enumerate(paths) if "requirements.txt" in p), None)
        last_idx = next((i for i, p in enumerate(paths) if "zzz_last.py" in p), None)
        if req_idx is not None and last_idx is not None:
            assert req_idx < last_idx

    def test_format_context(self):
        from luckyd_code.tools.readme_gen import _format_context
        files = [("README.md", "# My Project"), ("setup.py", "from setuptools import setup")]
        ctx = _format_context(files)
        assert "=== README.md ===" in ctx
        assert "# My Project" in ctx
        assert "=== setup.py ===" in ctx


class TestReadmeGenToolRun:
    def test_run_nonexistent_dir(self, tmp_path):
        from luckyd_code.tools.readme_gen import ReadmeGenTool
        tool = ReadmeGenTool()
        result = tool.run(project_dir=str(tmp_path / "nosuchdir"))
        assert "Error" in result or "not a directory" in result.lower()

    def test_run_no_files_found(self, tmp_path):
        from luckyd_code.tools.readme_gen import ReadmeGenTool
        tool = ReadmeGenTool()
        result = tool.run(project_dir=str(tmp_path))
        assert "Error" in result or "no readable" in result.lower()

    def test_run_readme_already_exists_no_overwrite(self, tmp_path):
        from luckyd_code.tools.readme_gen import ReadmeGenTool
        (tmp_path / "README.md").write_text("# Existing")
        (tmp_path / "main.py").write_text("# source")
        tool = ReadmeGenTool()
        result = tool.run(project_dir=str(tmp_path), overwrite=False)
        assert "already exists" in result.lower() or "overwrite" in result.lower()

    def test_run_model_call_fails(self, tmp_path):
        from luckyd_code.tools.readme_gen import ReadmeGenTool
        (tmp_path / "main.py").write_text("def main(): pass\n")
        tool = ReadmeGenTool()
        with patch.object(tool, "_call_model", side_effect=Exception("timeout")):
            result = tool.run(project_dir=str(tmp_path))
        assert "Error" in result and "model" in result.lower()

    def test_run_write_fails(self, tmp_path):
        from luckyd_code.tools.readme_gen import ReadmeGenTool
        (tmp_path / "main.py").write_text("def main(): pass\n")
        tool = ReadmeGenTool()
        with patch.object(tool, "_call_model", return_value="# Generated README"):
            with patch.object(Path, "write_text", side_effect=OSError("disk full")):
                result = tool.run(project_dir=str(tmp_path))
        assert "Error" in result

    def test_run_success_strips_markdown_fences(self, tmp_path):
        from luckyd_code.tools.readme_gen import ReadmeGenTool
        (tmp_path / "main.py").write_text("def main(): pass\n")
        tool = ReadmeGenTool()
        fenced = "```markdown\n# My Project\nsome content\n```"
        with patch.object(tool, "_call_model", return_value=fenced):
            result = tool.run(project_dir=str(tmp_path))
        assert "Error" not in result
        content = (tmp_path / "README.md").read_text()
        assert "```markdown" not in content
        assert "# My Project" in content

    def test_run_with_custom_output_path(self, tmp_path):
        from luckyd_code.tools.readme_gen import ReadmeGenTool
        (tmp_path / "main.py").write_text("def main(): pass\n")
        out = tmp_path / "CUSTOM_README.md"
        tool = ReadmeGenTool()
        with patch.object(tool, "_call_model", return_value="# Custom"):
            tool.run(project_dir=str(tmp_path), output_path=str(out))
        assert out.exists()
        assert "# Custom" in out.read_text()

    def test_run_overwrite_existing(self, tmp_path):
        from luckyd_code.tools.readme_gen import ReadmeGenTool
        (tmp_path / "README.md").write_text("# Old")
        (tmp_path / "main.py").write_text("# source")
        tool = ReadmeGenTool()
        with patch.object(tool, "_call_model", return_value="# New README"):
            result = tool.run(project_dir=str(tmp_path), overwrite=True)
        assert "Error" not in result
        assert "# New README" in (tmp_path / "README.md").read_text()


# ═══════════════════════════════════════════════════════════════════════════════
# tools/project_gen.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestProjectGenToolRun:
    def _good_scaffold(self, name="my-project"):
        return {
            "project_name": name,
            "description": "A test project",
            "stack": "Python",
            "files": [
                {"path": "main.py", "content": "print('hello')\n"},
                {"path": "README.md", "content": "# Test\n"},
            ],
            "install": "pip install -r requirements.txt",
            "run": "python main.py",
            "notes": "Test project",
        }

    def test_run_model_invalid_json(self, tmp_path):
        from luckyd_code.tools.project_gen import ProjectGenTool
        tool = ProjectGenTool()
        with patch.object(tool, "_call_model", side_effect=json.JSONDecodeError("err", "", 0)):
            result = tool.run("a flask app", output_dir=str(tmp_path))
        assert "Error" in result and "JSON" in result

    def test_run_model_call_exception(self, tmp_path):
        from luckyd_code.tools.project_gen import ProjectGenTool
        tool = ProjectGenTool()
        with patch.object(tool, "_call_model", side_effect=ConnectionError("no network")):
            result = tool.run("a flask app", output_dir=str(tmp_path))
        assert "Error" in result and "model" in result.lower()

    def test_run_no_files_in_scaffold(self, tmp_path):
        from luckyd_code.tools.project_gen import ProjectGenTool
        tool = ProjectGenTool()
        scaffold = self._good_scaffold()
        scaffold["files"] = []
        with patch.object(tool, "_call_model", return_value=scaffold):
            result = tool.run("a project", output_dir=str(tmp_path))
        assert "Error" in result and "no files" in result.lower()

    def test_run_file_write_error(self, tmp_path):
        from luckyd_code.tools.project_gen import ProjectGenTool
        tool = ProjectGenTool()
        scaffold = self._good_scaffold()
        with patch.object(tool, "_call_model", return_value=scaffold):
            with patch.object(Path, "write_text", side_effect=OSError("disk full")):
                result = tool.run("a project", output_dir=str(tmp_path))
        assert "Errors" in result or "Error" in result

    def test_run_success_creates_files(self, tmp_path):
        from luckyd_code.tools.project_gen import ProjectGenTool
        tool = ProjectGenTool()
        scaffold = self._good_scaffold("test-app")
        with patch.object(tool, "_call_model", return_value=scaffold):
            result = tool.run("a test app", output_dir=str(tmp_path))
        assert "test-app" in result
        assert (tmp_path / "test-app" / "main.py").exists()
        assert (tmp_path / "test-app" / "README.md").exists()

    def test_run_includes_install_and_run_commands(self, tmp_path):
        from luckyd_code.tools.project_gen import ProjectGenTool
        tool = ProjectGenTool()
        scaffold = self._good_scaffold()
        with patch.object(tool, "_call_model", return_value=scaffold):
            result = tool.run("app", output_dir=str(tmp_path))
        assert "pip install" in result
        assert "python main.py" in result

    def test_run_with_notes(self, tmp_path):
        from luckyd_code.tools.project_gen import ProjectGenTool
        tool = ProjectGenTool()
        scaffold = self._good_scaffold()
        scaffold["notes"] = "Remember to set .env vars"
        with patch.object(tool, "_call_model", return_value=scaffold):
            result = tool.run("app", output_dir=str(tmp_path))
        assert "Remember to set .env vars" in result

    def test_call_model_strips_markdown_fences(self):
        from luckyd_code.tools.project_gen import ProjectGenTool
        tool = ProjectGenTool()
        scaffold = self._good_scaffold()
        fenced_json = f"```json\n{json.dumps(scaffold)}\n```"
        with patch.object(tool, "_call_model_direct", return_value=fenced_json):
            result = tool._call_model("description")
        assert result["project_name"] == "my-project"


# ═══════════════════════════════════════════════════════════════════════════════
# feedback_analyzer.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetRelevantFilesEdgeCases:
    def test_empty_traceback_and_message(self, tmp_path):
        from luckyd_code.feedback_analyzer import _get_relevant_files
        error_data = {"error_type": "Error", "error_message": "", "traceback": ""}
        result = _get_relevant_files(error_data, str(tmp_path))
        assert result == {}

    def test_file_read_error_silently_skipped(self, tmp_path):
        from luckyd_code.feedback_analyzer import _get_relevant_files
        (tmp_path / "luckyd_code").mkdir(parents=True)
        f = tmp_path / "luckyd_code" / "broken.py"
        f.write_text("# exists")
        error_data = {
            "error_type": "Error",
            "error_message": "",
            "traceback": f'File "luckyd_code/broken.py", line 1\n',
        }
        with patch.object(Path, "read_text", side_effect=OSError("no read")):
            result = _get_relevant_files(error_data, str(tmp_path))
        assert isinstance(result, dict)


class TestParseDiagnosisJsonEdgeCases:
    def test_bare_json_object_without_fences(self):
        from luckyd_code.feedback_analyzer import _parse_diagnosis_json
        raw = 'Some preamble\n{"root_cause": "bare", "affected_files": [], "fix_suggestion": "fix", "confidence": "low"}\nsome postamble'
        result = _parse_diagnosis_json(raw)
        assert result is not None
        assert result["root_cause"] == "bare"

    def test_fenced_with_no_json_label(self):
        from luckyd_code.feedback_analyzer import _parse_diagnosis_json
        raw = '```\n{"root_cause": "test", "affected_files": [], "fix_suggestion": "fix", "confidence": "high"}\n```'
        result = _parse_diagnosis_json(raw)
        assert result is not None

    def test_returns_none_on_error_prefix(self):
        from luckyd_code.feedback_analyzer import _parse_diagnosis_json
        assert _parse_diagnosis_json("ERROR: something bad") is None

    def test_returns_none_on_empty_string(self):
        from luckyd_code.feedback_analyzer import _parse_diagnosis_json
        assert _parse_diagnosis_json("") is None


class TestCallLlmEdgeCases:
    def test_generic_exception_returns_error_string(self):
        import luckyd_code.feedback_analyzer as fa

        fake_client = MagicMock()
        fake_client.__enter__ = MagicMock(return_value=fake_client)
        fake_client.__exit__ = MagicMock(return_value=False)
        fake_client.post.side_effect = RuntimeError("unexpected crash")

        with patch.object(fa.httpx, "Client", return_value=fake_client):
            with patch.object(fa.httpx, "Timeout", MagicMock()):
                result = fa._call_llm("sys", "user", "key")
        assert result.startswith("ERROR:")

    def test_http_error_returns_error_string(self):
        """HTTPStatusError with a valid response body returns ERROR: string."""
        import luckyd_code.feedback_analyzer as fa

        # Use a plain Python object — MagicMock's .text can be unpredictable
        class _FakeResp:
            status_code = 500
            text = "Internal Server Error"

        http_err = fa.httpx.HTTPStatusError(
            "Server error",
            request=MagicMock(),
            response=_FakeResp(),
        )

        fake_client = MagicMock()
        fake_client.__enter__ = MagicMock(return_value=fake_client)
        fake_client.__exit__ = MagicMock(return_value=False)
        # raise the HTTPStatusError when post() is called
        fake_client.post.side_effect = http_err

        with patch.object(fa.httpx, "Client", return_value=fake_client):
            with patch.object(fa.httpx, "Timeout", MagicMock()):
                result = fa._call_llm("sys", "user", "key")

        assert result.startswith("ERROR:")
        assert "500" in result or "Internal Server Error" in result

    def test_timeout_exception_returns_error_string(self):
        import luckyd_code.feedback_analyzer as fa

        fake_client = MagicMock()
        fake_client.__enter__ = MagicMock(return_value=fake_client)
        fake_client.__exit__ = MagicMock(return_value=False)
        fake_client.post.side_effect = fa.httpx.TimeoutException("timed out", request=MagicMock())

        with patch.object(fa.httpx, "Client", return_value=fake_client):
            with patch.object(fa.httpx, "Timeout", MagicMock()):
                result = fa._call_llm("sys", "user", "key")

        assert result.startswith("ERROR:")
        assert "timed out" in result.lower() or "timeout" in result.lower()


class TestAnalyzeErrorEdgeCases:
    def test_auto_detects_project_root_when_empty(self):
        from luckyd_code.feedback_analyzer import analyze_error
        with patch("luckyd_code.feedback_analyzer._call_llm",
                   return_value=json.dumps({
                       "root_cause": "auto-detected",
                       "affected_files": [],
                       "fix_suggestion": "fix",
                       "confidence": "low",
                   })):
            result = analyze_error(ValueError("test"), api_key="k", project_root="")
        assert result is not None

    def test_with_os_and_python_version_in_dict(self):
        from luckyd_code.feedback_analyzer import analyze_error
        error_data = {
            "error_type": "TypeError",
            "error_message": "bad type",
            "traceback": "",
            "python_version": "3.12",
            "os": "Windows",
        }
        with patch("luckyd_code.feedback_analyzer._call_llm",
                   return_value=json.dumps({
                       "root_cause": "type issue",
                       "affected_files": [],
                       "fix_suggestion": "add type check",
                       "confidence": "medium",
                   })):
            result = analyze_error(error_data, api_key="k")
        assert result is not None
        assert result.error_type == "TypeError"

    def test_returns_none_when_llm_errors(self):
        from luckyd_code.feedback_analyzer import analyze_error
        with patch("luckyd_code.feedback_analyzer._call_llm", return_value="ERROR: boom"):
            result = analyze_error(ValueError("test"), api_key="k")
        assert result is None

    def test_returns_none_when_json_invalid(self):
        from luckyd_code.feedback_analyzer import analyze_error
        with patch("luckyd_code.feedback_analyzer._call_llm", return_value="not json at all"):
            result = analyze_error(ValueError("test"), api_key="k")
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════════
# orchestrator.py — _truncate_to_tokens + tester-only path
# ═══════════════════════════════════════════════════════════════════════════════

class TestTruncateToTokens:
    def test_short_text_returned_unchanged(self):
        from luckyd_code.orchestrator import _truncate_to_tokens
        text = "hello world"
        assert _truncate_to_tokens(text, max_tokens=600) == text

    def test_long_text_truncated(self):
        from luckyd_code.orchestrator import _truncate_to_tokens
        long_text = "word " * 2000
        result = _truncate_to_tokens(long_text, max_tokens=100)
        assert len(result) < len(long_text)
        assert "truncated" in result

    def test_heuristic_fallback_when_tiktoken_unavailable(self):
        """Falls back to char-based heuristic when tiktoken is absent."""
        from luckyd_code.orchestrator import _truncate_to_tokens
        long_text = "a" * 10000
        with patch.dict("sys.modules", {"tiktoken": None}):
            result = _truncate_to_tokens(long_text, max_tokens=100)
        assert isinstance(result, str)
        assert len(result) < len(long_text)


class TestCoordinatorTesterOnly:
    def _make_config(self):
        cfg = MagicMock()
        cfg.model = "deepseek-v4-flash"
        cfg.api_key = "sk-test"
        cfg.base_url = "https://api.deepseek.com/v1"
        cfg.max_tokens = 1024
        cfg.temperature = 0.7
        cfg.system_prompt = "You are helpful."
        return cfg

    def test_orchestrate_tester_only_role(self):
        from luckyd_code.orchestrator import Coordinator
        cfg = self._make_config()
        coord = Coordinator(cfg)
        with patch.object(coord.handoff, "handoff", return_value="tests planned"):
            report = coord.orchestrate("write tests", roles=["tester"])
        assert "Test Plan" in report
        assert "tests planned" in report

    def test_orchestrate_researcher_and_tester_parallel(self):
        from luckyd_code.orchestrator import Coordinator
        cfg = self._make_config()
        coord = Coordinator(cfg)
        called_roles = []

        def _handoff(role, task, tools=None):
            called_roles.append(role)
            return f"{role} done"

        with patch.object(coord.handoff, "handoff", side_effect=_handoff):
            report = coord.orchestrate("task", roles=["researcher", "tester"])

        assert "researcher" in called_roles
        assert "tester" in called_roles
        assert "Research Findings" in report
        assert "Test Plan" in report

    def test_parallel_orchestrate_with_notes(self):
        from luckyd_code.orchestrator import Coordinator
        cfg = self._make_config()
        coord = Coordinator(cfg)
        subtasks = [("researcher", "find APIs"), ("coder", "implement feature")]
        with patch.object(coord.handoff, "handoff", return_value="done"):
            report = coord.parallel_orchestrate("big feature", subtasks)
        assert "Parallel Orchestration" in report
        assert "big feature" in report
