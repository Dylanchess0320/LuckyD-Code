"""Tests for readme_gen.py and project_gen.py — covers uncovered branches.

Target uncovered lines:
  readme_gen.py:
    67         _collect_files: truncation suffix when text > _MAX_FILE_CHARS
    70-71      _collect_files: priority file snippet + append
    78         _collect_files: except Exception pass in priority loop
    90-91      _collect_files: PermissionError in _walk
    101-102    _collect_files: Exception while reading a file in _walk
    158        run(): README exists and overwrite=False path
    161-182    run(): model call, markdown fence stripping, write, error paths

  project_gen.py:
    113-134    run(): file-writing loop with per-file OSError errors list
    140-141    run(): errors section + notes section in output
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

import pytest


# ═══════════════════════════════════════════════════════════════════════════
# readme_gen helpers
# ═══════════════════════════════════════════════════════════════════════════

class TestCollectFiles:
    """Unit tests for _collect_files — the internal file scanner."""

    def test_collects_priority_file_with_truncation(self, tmp_path):
        """Line 67: text > _MAX_FILE_CHARS triggers the truncation suffix."""
        from luckyd_code.tools.readme_gen import _collect_files, _MAX_FILE_CHARS
        big_file = tmp_path / "main.py"
        big_file.write_text("x" * (_MAX_FILE_CHARS + 500), encoding="utf-8")
        result = _collect_files(tmp_path)
        snippets = dict(result)
        key = [k for k in snippets if "main.py" in k][0]
        assert "truncated" in snippets[key]

    def test_collects_priority_file_short_content(self, tmp_path):
        """Lines 70-71: priority file shorter than limit — no truncation."""
        from luckyd_code.tools.readme_gen import _collect_files
        f = tmp_path / "main.py"
        f.write_text("print('hello')", encoding="utf-8")
        result = _collect_files(tmp_path)
        snippets = dict(result)
        assert any("main.py" in k for k in snippets)
        key = [k for k in snippets if "main.py" in k][0]
        assert "truncated" not in snippets[key]

    def test_skips_priority_file_on_read_exception(self, tmp_path):
        """Line 78: except Exception pass in priority files loop."""
        from luckyd_code.tools.readme_gen import _collect_files, _PRIORITY_FILES
        f = tmp_path / "main.py"
        f.write_text("ok")
        # Patch read_text to raise on the priority file
        original_read = Path.read_text
        def _raise_read(self, *args, **kwargs):
            if self.name in _PRIORITY_FILES:
                raise UnicodeDecodeError("utf-8", b"", 0, 1, "bad")
            return original_read(self, *args, **kwargs)
        with patch.object(Path, "read_text", _raise_read):
            result = _collect_files(tmp_path)
        # Should not crash; priority file may or may not appear
        assert isinstance(result, list)

    def test_permission_error_in_walk_is_silently_skipped(self, tmp_path):
        """Lines 90-91: PermissionError during os.walk iteration."""
        from luckyd_code.tools.readme_gen import _collect_files
        # Create a normal file so _walk is entered
        f = tmp_path / "app.py"
        f.write_text("import os")
        # Patch Path.iterdir to raise PermissionError for subdirs only
        original_iterdir = Path.iterdir
        call_count = [0]
        def _restricted_iterdir(self):
            call_count[0] += 1
            if call_count[0] > 1:
                raise PermissionError("no access")
            return original_iterdir(self)
        with patch.object(Path, "iterdir", _restricted_iterdir):
            result = _collect_files(tmp_path)
        assert isinstance(result, list)

    def test_exception_reading_file_in_walk_is_silently_skipped(self, tmp_path):
        """Lines 101-102: Exception while reading a file body in _walk."""
        from luckyd_code.tools.readme_gen import _collect_files, _PRIORITY_FILES
        f = tmp_path / "utils.py"
        f.write_text("def helper(): pass")
        original_read = Path.read_text
        def _selective_raise(self, *args, **kwargs):
            if self.name not in _PRIORITY_FILES and self.name.endswith(".py"):
                raise OSError("read failed")
            return original_read(self, *args, **kwargs)
        with patch.object(Path, "read_text", _selective_raise):
            result = _collect_files(tmp_path)
        assert isinstance(result, list)

    def test_skipped_dirs_not_descended(self, tmp_path):
        """Directories in _SKIP_DIRS are not traversed."""
        from luckyd_code.tools.readme_gen import _collect_files
        venv_dir = tmp_path / ".venv"
        venv_dir.mkdir()
        (venv_dir / "site.py").write_text("# venv")
        result = _collect_files(tmp_path)
        assert not any(".venv" in k for k, _ in result)

    def test_skipped_extensions_not_collected(self, tmp_path):
        """Files with _SKIP_EXTS extensions are ignored."""
        from luckyd_code.tools.readme_gen import _collect_files
        (tmp_path / "image.png").write_bytes(b"\x89PNG")
        result = _collect_files(tmp_path)
        assert not any(".png" in k for k, _ in result)

    def test_multiple_source_files_collected(self, tmp_path):
        """General walk collects non-priority .py files."""
        from luckyd_code.tools.readme_gen import _collect_files
        for name in ("alpha.py", "beta.py", "gamma.py"):
            (tmp_path / name).write_text(f"# {name}")
        result = _collect_files(tmp_path)
        collected_names = [Path(k).name for k, _ in result]
        assert any("alpha.py" in n or "beta.py" in n or "gamma.py" in n
                   for n in collected_names)


class TestFormatContext:
    def test_separates_files_with_blank_lines(self):
        from luckyd_code.tools.readme_gen import _format_context
        files = [("a.py", "content a"), ("b.py", "content b")]
        result = _format_context(files)
        assert "=== a.py ===" in result
        assert "=== b.py ===" in result
        assert "content a" in result

    def test_empty_list_returns_empty_string(self):
        from luckyd_code.tools.readme_gen import _format_context
        assert _format_context([]) == ""


class TestReadmeGenToolRun:
    """Tests for ReadmeGenTool.run()."""

    def _make_tool(self):
        from luckyd_code.tools.readme_gen import ReadmeGenTool
        return ReadmeGenTool()

    def test_returns_error_when_dir_not_found(self, tmp_path):
        tool = self._make_tool()
        result = tool.run(project_dir=str(tmp_path / "nonexistent"))
        assert "Error" in result

    def test_returns_readme_exists_message_when_no_overwrite(self, tmp_path):
        """Line 158: README exists and overwrite=False → returns early."""
        readme = tmp_path / "README.md"
        readme.write_text("# Existing")
        (tmp_path / "main.py").write_text("# code")
        tool = self._make_tool()
        result = tool.run(project_dir=str(tmp_path), overwrite=False)
        assert "already exists" in result.lower() or "README" in result

    def test_returns_error_when_no_files_found(self, tmp_path):
        """run() with no readable source files."""
        tool = self._make_tool()
        with patch("luckyd_code.tools.readme_gen._collect_files", return_value=[]):
            result = tool.run(project_dir=str(tmp_path), overwrite=True)
        assert "Error" in result and "no readable" in result.lower()

    def test_run_calls_model_and_writes_readme(self, tmp_path):
        """Lines 161-182: happy path — model called, readme written."""
        (tmp_path / "main.py").write_text("print('hello')")
        tool = self._make_tool()
        fake_readme = "# My Project\n\nA cool project."
        with patch.object(tool, "_call_model", return_value=fake_readme) as mock_model:
            result = tool.run(project_dir=str(tmp_path), overwrite=True)
        mock_model.assert_called_once()
        assert (tmp_path / "README.md").exists()
        assert "generated" in result.lower() or "Written" in result

    def test_strips_markdown_fence_from_model_output(self, tmp_path):
        """run() strips ```markdown...``` fences from model output."""
        (tmp_path / "main.py").write_text("x = 1")
        tool = self._make_tool()
        fenced = "```markdown\n# Title\n\nContent\n```"
        with patch.object(tool, "_call_model", return_value=fenced):
            tool.run(project_dir=str(tmp_path), overwrite=True)
        content = (tmp_path / "README.md").read_text()
        assert "```markdown" not in content
        assert "# Title" in content

    def test_strips_trailing_fence_only(self, tmp_path):
        """run() strips trailing ``` even without opening markdown fence."""
        (tmp_path / "main.py").write_text("x = 1")
        tool = self._make_tool()
        fenced = "# Title\n\nContent\n```"
        with patch.object(tool, "_call_model", return_value=fenced):
            tool.run(project_dir=str(tmp_path), overwrite=True)
        content = (tmp_path / "README.md").read_text()
        assert not content.rstrip().endswith("```")

    def test_returns_error_on_model_failure(self, tmp_path):
        """run() catches model exceptions and returns error string."""
        (tmp_path / "main.py").write_text("x = 1")
        tool = self._make_tool()
        with patch.object(tool, "_call_model", side_effect=Exception("API down")):
            result = tool.run(project_dir=str(tmp_path), overwrite=True)
        assert "Error" in result
        assert "API down" in result

    def test_returns_error_on_write_failure(self, tmp_path):
        """run() catches OSError when writing README.md."""
        (tmp_path / "main.py").write_text("x = 1")
        tool = self._make_tool()
        with patch.object(tool, "_call_model", return_value="# Readme"):
            with patch.object(Path, "write_text", side_effect=OSError("disk full")):
                result = tool.run(project_dir=str(tmp_path), overwrite=True)
        assert "Error" in result

    def test_custom_output_path_is_respected(self, tmp_path):
        """output_path parameter directs where README is written."""
        (tmp_path / "main.py").write_text("x = 1")
        out = tmp_path / "docs" / "README.md"
        tool = self._make_tool()
        with patch.object(tool, "_call_model", return_value="# Docs"):
            result = tool.run(
                project_dir=str(tmp_path),
                output_path=str(out),
                overwrite=True,
            )
        assert out.exists()

    def test_overwrite_true_replaces_existing_readme(self, tmp_path):
        """When overwrite=True, existing README.md is replaced."""
        readme = tmp_path / "README.md"
        readme.write_text("# Old")
        (tmp_path / "main.py").write_text("x = 1")
        tool = self._make_tool()
        with patch.object(tool, "_call_model", return_value="# New"):
            tool.run(project_dir=str(tmp_path), overwrite=True)
        assert "# New" in readme.read_text()


# ═══════════════════════════════════════════════════════════════════════════
# project_gen.py
# ═══════════════════════════════════════════════════════════════════════════

def _make_scaffold(
    project_name: str = "my-proj",
    files: list | None = None,
    errors: bool = False,
    notes: str = "",
) -> dict:
    if files is None:
        files = [
            {"path": "main.py", "content": "print('hello')"},
            {"path": "README.md", "content": "# My Proj"},
        ]
    return {
        "project_name": project_name,
        "description": "A test project",
        "stack": "Python",
        "files": files,
        "install": "pip install -r requirements.txt",
        "run": "python main.py",
        "notes": notes,
    }


class TestProjectGenToolRun:
    """Tests for ProjectGenTool.run() covering uncovered branches."""

    def _make_tool(self):
        from luckyd_code.tools.project_gen import ProjectGenTool
        return ProjectGenTool()

    def test_happy_path_creates_files(self, tmp_path):
        """Basic scaffold creation writes all files."""
        tool = self._make_tool()
        scaffold = _make_scaffold()
        with patch.object(tool, "_call_model", return_value=scaffold):
            result = tool.run(description="a python hello-world", output_dir=str(tmp_path))
        assert "my-proj" in result
        assert (tmp_path / "my-proj" / "main.py").exists()
        assert (tmp_path / "my-proj" / "README.md").exists()

    def test_returns_error_when_model_returns_invalid_json(self, tmp_path):
        """json.JSONDecodeError from _call_model → error string."""
        tool = self._make_tool()
        with patch.object(tool, "_call_model", side_effect=json.JSONDecodeError("bad", "", 0)):
            result = tool.run(description="anything", output_dir=str(tmp_path))
        assert "Error" in result and "JSON" in result

    def test_returns_error_when_model_raises_generic_exception(self, tmp_path):
        """Generic exception from _call_model → error string."""
        tool = self._make_tool()
        with patch.object(tool, "_call_model", side_effect=RuntimeError("API timeout")):
            result = tool.run(description="anything", output_dir=str(tmp_path))
        assert "Error" in result

    def test_returns_error_when_scaffold_has_no_files(self, tmp_path):
        """Scaffold with empty files list → error."""
        tool = self._make_tool()
        empty_scaffold = _make_scaffold(files=[])
        with patch.object(tool, "_call_model", return_value=empty_scaffold):
            result = tool.run(description="anything", output_dir=str(tmp_path))
        assert "Error" in result and "no files" in result.lower()

    def test_file_with_empty_path_is_skipped(self, tmp_path):
        """Files with no path field are silently skipped."""
        tool = self._make_tool()
        scaffold = _make_scaffold(files=[
            {"path": "", "content": "should be skipped"},
            {"path": "main.py", "content": "# good"},
        ])
        with patch.object(tool, "_call_model", return_value=scaffold):
            result = tool.run(description="test", output_dir=str(tmp_path))
        assert (tmp_path / "my-proj" / "main.py").exists()

    def test_per_file_oserror_added_to_errors_list(self, tmp_path):
        """Lines 113-134: OSError writing a file → added to errors list."""
        tool = self._make_tool()
        scaffold = _make_scaffold(files=[
            {"path": "main.py", "content": "# good"},
            {"path": "bad.py", "content": "# will fail"},
        ])
        original_write = Path.write_text
        def _selective_fail(self, content, *args, **kwargs):
            if self.name == "bad.py":
                raise OSError("permission denied")
            return original_write(self, content, *args, **kwargs)
        with patch.object(tool, "_call_model", return_value=scaffold):
            with patch.object(Path, "write_text", _selective_fail):
                result = tool.run(description="test", output_dir=str(tmp_path))
        # Errors count should appear in output
        assert "Errors" in result or "error" in result.lower()

    def test_errors_section_in_output_when_files_fail(self, tmp_path):
        """Lines 140-141: when errors list is non-empty, Errors line appears."""
        tool = self._make_tool()
        scaffold = _make_scaffold(files=[
            {"path": "fail.py", "content": "x"}
        ])
        original_write = Path.write_text
        def _always_fail(self, content, *args, **kwargs):
            raise OSError("disk full")
        with patch.object(tool, "_call_model", return_value=scaffold):
            with patch.object(Path, "write_text", _always_fail):
                result = tool.run(description="test", output_dir=str(tmp_path))
        assert "Errors" in result

    def test_notes_section_in_output_when_provided(self, tmp_path):
        """Lines 140-141: scaffold.notes → Notes line in output."""
        tool = self._make_tool()
        scaffold = _make_scaffold(notes="Remember to add .env file!")
        with patch.object(tool, "_call_model", return_value=scaffold):
            result = tool.run(description="test", output_dir=str(tmp_path))
        assert "Notes" in result
        assert "Remember to add .env file!" in result

    def test_no_notes_section_when_empty(self, tmp_path):
        """When notes is empty/falsy, Notes section is absent."""
        tool = self._make_tool()
        scaffold = _make_scaffold(notes="")
        with patch.object(tool, "_call_model", return_value=scaffold):
            result = tool.run(description="test", output_dir=str(tmp_path))
        assert "Notes" not in result

    def test_output_contains_install_and_run(self, tmp_path):
        """Output always includes Install and Run lines."""
        tool = self._make_tool()
        scaffold = _make_scaffold()
        with patch.object(tool, "_call_model", return_value=scaffold):
            result = tool.run(description="test", output_dir=str(tmp_path))
        assert "Install" in result
        assert "Run" in result

    def test_output_dir_created_if_missing(self, tmp_path):
        """parent.mkdir(parents=True, exist_ok=True) creates nested dirs."""
        tool = self._make_tool()
        nested = tmp_path / "a" / "b" / "c"
        scaffold = _make_scaffold()
        with patch.object(tool, "_call_model", return_value=scaffold):
            result = tool.run(description="test", output_dir=str(nested))
        assert nested.exists()

    def test_returns_error_when_output_dir_mkdir_fails(self, tmp_path):
        """OSError from parent.mkdir → error string returned."""
        tool = self._make_tool()
        with patch.object(Path, "mkdir", side_effect=OSError("no space")):
            result = tool.run(description="test", output_dir="/bad/path")
        assert "Error" in result

    def test_strip_markdown_fence_from_model_json(self, tmp_path):
        """_call_model strips ```...``` fences before json.loads."""
        from luckyd_code.tools.project_gen import ProjectGenTool
        tool = ProjectGenTool()
        scaffold_json = json.dumps(_make_scaffold())
        fenced = f"```json\n{scaffold_json}\n```"
        with patch.object(tool, "_call_model_direct", return_value=fenced):
            result = tool._call_model("build something")
        assert result["project_name"] == "my-proj"

    def test_nested_file_paths_create_parent_dirs(self, tmp_path):
        """Files with nested paths create parent directories."""
        tool = self._make_tool()
        scaffold = _make_scaffold(files=[
            {"path": "src/utils/helper.py", "content": "def help(): pass"},
        ])
        with patch.object(tool, "_call_model", return_value=scaffold):
            tool.run(description="test", output_dir=str(tmp_path))
        assert (tmp_path / "my-proj" / "src" / "utils" / "helper.py").exists()
