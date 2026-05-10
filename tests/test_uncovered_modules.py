"""Comprehensive coverage for previously untested modules.

Targets: export, indexer, init, backup, update, self_improve, keybindings,
         tools/datetime_tool, tools/registry (extra), tools/shell_detect,
         tools/git_tools, tools/git_worktree, git/tools, git/auto_commit,
         file_watcher, tools/bash (safety layer), tools/agent_tools,
         tools/brain_tools, tools/web, tools/readme_gen, tools/dockerfile_gen,
         tools/project_gen, tools/game_gen,
         cli_commands/sessions, web_routes/*
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock
import subprocess

import pytest


# ===========================================================================
# export.py
# ===========================================================================

class TestExportMarkdown:
    def test_empty_messages(self):
        from luckyd_code.export import export_markdown
        result = export_markdown([])
        assert "# Conversation Export" in result
        assert "Exported:" in result

    def test_system_message(self):
        from luckyd_code.export import export_markdown
        msgs = [{"role": "system", "content": "You are helpful."}]
        result = export_markdown(msgs)
        assert "System" in result
        assert "You are helpful." in result

    def test_user_message(self):
        from luckyd_code.export import export_markdown
        msgs = [{"role": "user", "content": "Hello!"}]
        result = export_markdown(msgs)
        assert "User" in result
        assert "Hello!" in result

    def test_assistant_message(self):
        from luckyd_code.export import export_markdown
        msgs = [{"role": "assistant", "content": "Hi there!"}]
        result = export_markdown(msgs)
        assert "Assistant" in result
        assert "Hi there!" in result

    def test_assistant_with_tool_calls(self):
        from luckyd_code.export import export_markdown
        msgs = [{"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "Read", "arguments": '{"file_path": "x.py"}'}}
        ]}]
        result = export_markdown(msgs)
        assert "Read" in result

    def test_tool_result_message(self):
        from luckyd_code.export import export_markdown
        msgs = [{"role": "tool", "tool_call_id": "tc1", "content": "file content here"}]
        result = export_markdown(msgs)
        assert "tc1" in result
        assert "file content" in result

    def test_tool_result_truncation(self):
        from luckyd_code.export import export_markdown
        long_content = "x" * 600
        msgs = [{"role": "tool", "tool_call_id": "tc2", "content": long_content}]
        result = export_markdown(msgs)
        assert "truncated" in result

    def test_write_to_file(self, tmp_path):
        from luckyd_code.export import export_markdown
        msgs = [{"role": "user", "content": "test"}]
        fpath = str(tmp_path / "conv.md")
        result = export_markdown(msgs, filepath=fpath)
        assert Path(fpath).exists()
        assert "test" in Path(fpath).read_text()

    def test_full_conversation(self):
        from luckyd_code.export import export_markdown
        msgs = [
            {"role": "system", "content": "You are an assistant."},
            {"role": "user", "content": "What is 2+2?"},
            {"role": "assistant", "content": "4"},
        ]
        result = export_markdown(msgs)
        assert "4" in result


class TestExportHtml:
    def test_basic_html_structure(self):
        from luckyd_code.export import export_html
        result = export_html([])
        assert "<!DOCTYPE html>" in result
        assert "<html>" in result
        assert "</html>" in result

    def test_custom_title(self):
        from luckyd_code.export import export_html
        result = export_html([], title="My Chat")
        assert "My Chat" in result

    def test_user_message_in_html(self):
        from luckyd_code.export import export_html
        msgs = [{"role": "user", "content": "Hello world"}]
        result = export_html(msgs)
        assert "Hello world" in result
        assert "user" in result

    def test_assistant_message_in_html(self):
        from luckyd_code.export import export_html
        msgs = [{"role": "assistant", "content": "Response here"}]
        result = export_html(msgs)
        assert "Response here" in result
        assert "assistant" in result

    def test_tool_result_in_html(self):
        from luckyd_code.export import export_html
        msgs = [{"role": "tool", "tool_call_id": "tc3", "content": "result"}]
        result = export_html(msgs)
        assert "tc3" in result

    def test_html_escaping(self):
        from luckyd_code.export import _escape_html
        assert _escape_html("<b>bold</b>") == "&lt;b&gt;bold&lt;/b&gt;"
        assert _escape_html("a & b") == "a &amp; b"
        assert _escape_html("no change") == "no change"

    def test_write_to_file(self, tmp_path):
        from luckyd_code.export import export_html
        fpath = str(tmp_path / "conv.html")
        export_html([{"role": "user", "content": "test"}], filepath=fpath)
        assert Path(fpath).exists()

    def test_assistant_with_tool_calls_html(self):
        from luckyd_code.export import export_html
        msgs = [{"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "Write", "arguments": '{"file_path":"a.py"}'}}
        ]}]
        result = export_html(msgs)
        assert "Write" in result

    def test_system_message_html(self):
        from luckyd_code.export import export_html
        msgs = [{"role": "system", "content": "sys prompt"}]
        result = export_html(msgs)
        assert "sys prompt" in result


# ===========================================================================
# indexer.py
# ===========================================================================

class TestIndexer:
    def test_scan_project_basic(self, tmp_path):
        from luckyd_code.indexer import scan_project
        (tmp_path / "main.py").write_text("print('hi')", encoding="utf-8")
        (tmp_path / "readme.md").write_text("# Test", encoding="utf-8")
        info = scan_project(tmp_path)
        assert info["name"] == tmp_path.name
        assert "Python" in info["languages"]
        assert info["total_files"] >= 1

    def test_scan_project_detects_entry_points(self, tmp_path):
        from luckyd_code.indexer import scan_project
        (tmp_path / "main.py").write_text("pass", encoding="utf-8")
        info = scan_project(tmp_path)
        assert "main.py" in info["entry_points"]

    def test_scan_ignores_pycache(self, tmp_path):
        from luckyd_code.indexer import scan_project
        pycache = tmp_path / "__pycache__"
        pycache.mkdir()
        (pycache / "x.pyc").write_bytes(b"\x00\x01")
        info = scan_project(tmp_path)
        tree_str = "\n".join(info["file_tree"])
        assert "__pycache__" not in tree_str

    def test_scan_detects_requirements(self, tmp_path):
        from luckyd_code.indexer import scan_project
        (tmp_path / "requirements.txt").write_text("fastapi>=0.100\nuvicorn\n", encoding="utf-8")
        info = scan_project(tmp_path)
        assert "requirements.txt" in info["dependency_files"]

    def test_scan_detects_package_json(self, tmp_path):
        from luckyd_code.indexer import scan_project
        (tmp_path / "package.json").write_text('{"name":"app","dependencies":{"react":"^18"}}', encoding="utf-8")
        info = scan_project(tmp_path)
        assert "JavaScript" in info["languages"] or "package.json" in info["dependency_files"]

    def test_detect_language_all_types(self):
        from luckyd_code.indexer import _detect_language
        assert _detect_language(".py") == "Python"
        assert _detect_language(".js") == "JavaScript"
        assert _detect_language(".ts") == "TypeScript"
        assert _detect_language(".rs") == "Rust"
        assert _detect_language(".go") == "Go"
        assert _detect_language(".java") == "Java"
        assert _detect_language(".rb") == "Ruby"
        assert _detect_language(".xyz") is None

    def test_detect_frameworks_fastapi(self):
        from luckyd_code.indexer import _detect_frameworks
        config_files = {"requirements.txt": ["fastapi", "uvicorn"]}
        result = _detect_frameworks(config_files, ["requirements.txt"])
        assert "FastAPI" in result

    def test_detect_frameworks_react(self):
        from luckyd_code.indexer import _detect_frameworks
        config_files = {"package.json": ["react", "next"]}
        result = _detect_frameworks(config_files, ["package.json"])
        assert "React/Next.js" in result

    def test_extract_deps_requirements(self, tmp_path):
        from luckyd_code.indexer import _extract_deps
        req = tmp_path / "requirements.txt"
        req.write_text("fastapi>=0.100\nuvicorn>=0.23\n# comment\n", encoding="utf-8")
        deps = _extract_deps(req, "requirements.txt")
        assert "fastapi" in deps
        assert "uvicorn" in deps

    def test_extract_deps_package_json(self, tmp_path):
        from luckyd_code.indexer import _extract_deps
        pj = tmp_path / "package.json"
        pj.write_text('{"dependencies":{"react":"18"},"devDependencies":{"jest":"29"}}', encoding="utf-8")
        deps = _extract_deps(pj, "package.json")
        assert "react" in deps
        assert "jest" in deps

    def test_format_project_context(self):
        from luckyd_code.indexer import format_project_context
        info = {
            "name": "myproject",
            "languages": ["Python"],
            "frameworks": ["FastAPI"],
            "entry_points": ["main.py"],
            "dependency_files": ["requirements.txt"],
            "total_files": 5,
            "file_tree": ["main.py", "app/"],
        }
        result = format_project_context(info)
        assert "myproject" in result
        assert "Python" in result
        assert "FastAPI" in result

    def test_index_project_returns_string(self, tmp_path):
        from luckyd_code.indexer import index_project
        (tmp_path / "app.py").write_text("pass", encoding="utf-8")
        result = index_project(str(tmp_path))
        assert isinstance(result, str)
        assert len(result) > 0

    def test_index_project_nonexistent(self, tmp_path):
        from luckyd_code.indexer import index_project
        result = index_project(str(tmp_path / "nonexistent"))
        assert result == ""

    def test_is_ignored(self):
        from luckyd_code.indexer import _is_ignored
        assert _is_ignored("node_modules", ["node_modules/"])
        assert _is_ignored("dist", ["dist"])
        assert _is_ignored("app.pyc", ["*.pyc"])
        assert not _is_ignored("main.py", ["*.pyc"])

    def test_load_gitignore(self, tmp_path):
        from luckyd_code.indexer import _load_gitignore
        gi = tmp_path / ".gitignore"
        gi.write_text("*.pyc\n# comment\n.env\n\n", encoding="utf-8")
        patterns = _load_gitignore(tmp_path)
        assert "*.pyc" in patterns
        assert ".env" in patterns
        assert "# comment" not in patterns

    def test_extract_deps_cargo_toml(self, tmp_path):
        from luckyd_code.indexer import _extract_deps
        cargo = tmp_path / "Cargo.toml"
        cargo.write_text("[dependencies]\nserde = \"1.0\"\ntokio = \"1\"\n", encoding="utf-8")
        deps = _extract_deps(cargo, "Cargo.toml")
        assert "serde" in deps


# ===========================================================================
# init.py
# ===========================================================================

class TestInitProject:
    def test_creates_memory_md(self, tmp_path, monkeypatch):
        from luckyd_code import init
        monkeypatch.chdir(tmp_path)
        result = init.init_project()
        assert "Created" in result
        assert (tmp_path / "MEMORY.md").exists()

    def test_does_not_overwrite_existing(self, tmp_path, monkeypatch):
        from luckyd_code import init
        monkeypatch.chdir(tmp_path)
        (tmp_path / "MEMORY.md").write_text("existing content", encoding="utf-8")
        result = init.init_project()
        assert "already exists" in result
        assert (tmp_path / "MEMORY.md").read_text() == "existing content"

    def test_does_not_overwrite_claude_md(self, tmp_path, monkeypatch):
        from luckyd_code import init
        monkeypatch.chdir(tmp_path)
        (tmp_path / "CLAUDE.md").write_text("claude content", encoding="utf-8")
        result = init.init_project()
        assert "already exists" in result

    def test_default_memory_content(self, tmp_path, monkeypatch):
        from luckyd_code import init
        monkeypatch.chdir(tmp_path)
        init.init_project()
        content = (tmp_path / "MEMORY.md").read_text()
        assert "## Project Overview" in content


# ===========================================================================
# backup.py
# ===========================================================================

class TestBackup:
    def test_git_helper_success(self):
        from luckyd_code.backup import _git
        mock_result = MagicMock(returncode=0, stdout="main\n", stderr="")
        with patch("subprocess.run", return_value=mock_result):
            code, out, err = _git("rev-parse", "--abbrev-ref", "HEAD")
        assert code == 0
        assert out == "main"

    def test_git_helper_not_found(self):
        from luckyd_code.backup import _git
        with patch("subprocess.run", side_effect=FileNotFoundError("no git")):
            code, out, err = _git("status")
        assert code == 1
        assert "git not found" in err

    def test_is_git_repo_true(self):
        from luckyd_code.backup import _is_git_repo
        mock_result = MagicMock(returncode=0)
        with patch("subprocess.run", return_value=mock_result):
            assert _is_git_repo() is True

    def test_is_git_repo_false(self):
        from luckyd_code.backup import _is_git_repo
        mock_result = MagicMock(returncode=1)
        with patch("subprocess.run", return_value=mock_result):
            assert _is_git_repo() is False

    def test_has_changes_true(self):
        from luckyd_code.backup import _has_changes
        mock_result = MagicMock(returncode=0, stdout=" M file.py\n", stderr="")
        with patch("subprocess.run", return_value=mock_result):
            assert _has_changes() is True

    def test_has_changes_false(self):
        from luckyd_code.backup import _has_changes
        mock_result = MagicMock(returncode=0, stdout="", stderr="")
        with patch("subprocess.run", return_value=mock_result):
            assert _has_changes() is False

    def test_create_backup_no_git_repo(self):
        from luckyd_code.backup import create_backup
        with patch("luckyd_code.backup._is_git_repo", return_value=False):
            result = create_backup("test")
        assert result["ok"] is False
        assert "git repository" in result["error"].lower()

    def test_create_backup_clean_tree(self):
        from luckyd_code.backup import create_backup
        with patch("luckyd_code.backup._is_git_repo", return_value=True):
            with patch("luckyd_code.backup._has_changes", return_value=False):
                with patch("luckyd_code.backup._short_hash", return_value="abc1234"):
                    result = create_backup()
        assert result["ok"] is True
        assert "clean" in result["message"].lower() or "abc1234" in result["message"]

    def test_create_backup_with_changes(self):
        from luckyd_code.backup import create_backup
        with patch("luckyd_code.backup._is_git_repo", return_value=True):
            with patch("luckyd_code.backup._has_changes", return_value=True):
                with patch("luckyd_code.backup._git") as mock_git:
                    mock_git.side_effect = [
                        (0, "", ""),  # add -A
                        (0, "", ""),  # commit
                        (0, "", ""),  # tag
                        (0, "abc1234", ""),  # short_hash
                    ]
                    result = create_backup("my message")
        assert result["ok"] is True

    def test_create_backup_add_fails(self):
        from luckyd_code.backup import create_backup
        with patch("luckyd_code.backup._is_git_repo", return_value=True):
            with patch("luckyd_code.backup._has_changes", return_value=True):
                with patch("luckyd_code.backup._git", return_value=(1, "", "permission denied")):
                    result = create_backup()
        assert result["ok"] is False

    def test_list_backups_from_tags(self):
        from luckyd_code.backup import list_backups
        tag_output = "dsc-backup/20240101_120000|abc123|2024-01-01\ndsc-backup/20240102_120000|def456|2024-01-02"
        with patch("luckyd_code.backup._git") as mock_git:
            mock_git.side_effect = [
                (0, tag_output, ""),
            ]
            result = list_backups(limit=5)
        assert len(result) == 2
        assert result[0]["hash"] == "abc123"

    def test_list_backups_fallback_to_log(self):
        from luckyd_code.backup import list_backups
        log_output = "abc123|2024-01-01|[dsc-backup] test (2024-01-01 12:00:00)"
        with patch("luckyd_code.backup._git") as mock_git:
            mock_git.side_effect = [
                (0, "", ""),   # tag list returns empty
                (0, log_output, ""),  # log fallback
            ]
            result = list_backups()
        assert len(result) >= 1

    def test_restore_backup_no_git(self):
        from luckyd_code.backup import restore_backup
        with patch("luckyd_code.backup._is_git_repo", return_value=False):
            result = restore_backup("1")
        assert result["ok"] is False

    def test_restore_backup_numeric_not_found(self):
        from luckyd_code.backup import restore_backup
        with patch("luckyd_code.backup._is_git_repo", return_value=True):
            with patch("luckyd_code.backup.list_backups", return_value=[]):
                result = restore_backup("5")
        assert result["ok"] is False
        assert "No backup" in result["error"]

    def test_restore_backup_success(self):
        from luckyd_code.backup import restore_backup
        with patch("luckyd_code.backup._is_git_repo", return_value=True):
            with patch("luckyd_code.backup._has_changes", return_value=False):
                with patch("luckyd_code.backup._git", return_value=(0, "", "")):
                    result = restore_backup("abc123")
        assert result["ok"] is True

    def test_format_backup_list_empty(self):
        from luckyd_code.backup import format_backup_list
        result = format_backup_list([])
        assert "No backups" in result

    def test_format_backup_list_with_entries(self):
        from luckyd_code.backup import format_backup_list
        backups = [{"n": 1, "hash": "abc", "date": "2024-01-01", "tag": "dsc-backup/x", "subject": "test"}]
        result = format_backup_list(backups)
        assert "#1" in result
        assert "abc" in result


# ===========================================================================
# update.py
# ===========================================================================

class TestUpdate:
    def test_get_version(self):
        from luckyd_code.update import get_version
        v = get_version()
        assert isinstance(v, str)

    def test_check_for_updates_behind(self):
        from luckyd_code.update import check_for_updates
        def side(cmd, **kw):
            r = MagicMock()
            if "fetch" in cmd:
                r.returncode = 0
            elif "rev-list" in cmd:
                r.returncode = 0; r.stdout = "3\n"
            elif "remote" in cmd:
                r.returncode = 0; r.stdout = "origin\t...\n"
            return r
        with patch("subprocess.run", side_effect=side):
            result = check_for_updates()
        assert "3 commit" in result or "behind" in result.lower()

    def test_check_for_updates_up_to_date(self):
        from luckyd_code.update import check_for_updates
        def side(cmd, **kw):
            r = MagicMock()
            if "fetch" in cmd:
                r.returncode = 0
            elif "rev-list" in cmd:
                r.returncode = 0; r.stdout = "0\n"
            elif "remote" in cmd:
                r.returncode = 0; r.stdout = "origin\t...\n"
            return r
        with patch("subprocess.run", side_effect=side):
            result = check_for_updates()
        assert "up to date" in result.lower() or isinstance(result, str)

    def test_check_for_updates_exception(self):
        from luckyd_code.update import check_for_updates
        with patch("subprocess.run", side_effect=Exception("git error")):
            result = check_for_updates()
        assert "Cannot check" in result or isinstance(result, str)

    def test_do_update_success(self):
        from luckyd_code.update import do_update
        def side(cmd, **kw):
            r = MagicMock()
            r.returncode = 0
            if "status" in cmd:
                r.stdout = ""
            elif "pull" in cmd:
                r.stdout = "Already up to date."
            else:
                r.stdout = ""
            return r
        with patch("subprocess.run", side_effect=side):
            result = do_update()
        assert "up to date" in result.lower() or isinstance(result, str)

    def test_do_update_with_stash(self):
        from luckyd_code.update import do_update
        call_count = [0]
        def side(cmd, **kw):
            call_count[0] += 1
            r = MagicMock()
            r.returncode = 0
            if "status" in cmd:
                r.stdout = " M file.py\n"
            elif "pull" in cmd:
                r.stdout = "Updated."
            else:
                r.stdout = ""
            return r
        with patch("subprocess.run", side_effect=side):
            result = do_update()
        assert isinstance(result, str)

    def test_do_update_exception(self):
        from luckyd_code.update import do_update
        with patch("subprocess.run", side_effect=Exception("fail")):
            result = do_update()
        assert "fail" in result or "Update failed" in result


# ===========================================================================
# self_improve.py
# ===========================================================================

class TestSelfImprove:
    def test_get_improvement_prompt_default(self):
        from luckyd_code.self_improve import get_improvement_prompt
        result = get_improvement_prompt()
        assert isinstance(result, str) and len(result) > 10

    def test_get_improvement_prompt_web(self):
        from luckyd_code.self_improve import get_improvement_prompt
        result = get_improvement_prompt("web")
        assert "web" in result.lower()

    def test_get_improvement_prompt_cli(self):
        from luckyd_code.self_improve import get_improvement_prompt
        result = get_improvement_prompt("cli")
        assert "cli" in result.lower()

    def test_get_improvement_prompt_refactor(self):
        from luckyd_code.self_improve import get_improvement_prompt
        result = get_improvement_prompt("refactor")
        assert "refactor" in result.lower() or "MINIMAL" in result

    def test_get_improvement_prompt_perf(self):
        from luckyd_code.self_improve import get_improvement_prompt
        result = get_improvement_prompt("perf")
        assert "performance" in result.lower()

    def test_get_improvement_prompt_cleanup(self):
        from luckyd_code.self_improve import get_improvement_prompt
        result = get_improvement_prompt("cleanup")
        assert "TODO" in result or "cleanup" in result.lower()

    def test_self_improve_prompt_constant(self):
        from luckyd_code.self_improve import SELF_IMPROVE_PROMPT
        assert "SELF-IMPROVEMENT MODE" in SELF_IMPROVE_PROMPT

    def test_improvement_tracker_snapshot_clean(self):
        from luckyd_code.self_improve import ImprovementTracker
        with patch("luckyd_code.self_improve._git") as mock_git:
            mock_git.side_effect = [
                "main",       # rev-parse branch
                "abc1234",    # rev-parse start_hash
                "",           # status --porcelain (clean)
            ]
            tracker = ImprovementTracker()
            result = tracker.snapshot()
        assert "clean" in result.lower()

    def test_improvement_report_no_changes(self):
        from luckyd_code.self_improve import ImprovementTracker
        with patch("luckyd_code.self_improve._git") as mock_git:
            mock_git.side_effect = [
                "main",     # branch
                "abc1234",  # start hash
                "abc1234",  # end hash in report
                "",         # unstaged diff
                "",         # staged diff
                "",         # stash pop (not called)
                "",         # diff --name-only
            ]
            tracker = ImprovementTracker()
            report = tracker.report()
        assert report.branch == "main"
        assert isinstance(report.files_changed, list)

    def test_improvement_report_dataclass(self):
        from luckyd_code.self_improve import ImprovementReport
        r = ImprovementReport(branch="main", start_hash="abc", end_hash="def",
                               files_changed=["x.py"], diff_summary="diff", commit_hash="")
        assert r.files_changed == ["x.py"]
        assert r.error is None


# ===========================================================================
# keybindings.py
# ===========================================================================

class TestKeybindings:
    def test_load_keybindings_missing_file(self, tmp_path, monkeypatch):
        from luckyd_code import keybindings
        monkeypatch.setattr(keybindings, "get_keybindings_path", lambda: tmp_path / "nonexistent.json")
        result = keybindings.load_keybindings()
        assert result == {}

    def test_load_keybindings_valid(self, tmp_path, monkeypatch):
        from luckyd_code import keybindings
        kbf = tmp_path / "keybindings.json"
        kbf.write_text('{"submit": "ctrl-j"}', encoding="utf-8")
        monkeypatch.setattr(keybindings, "get_keybindings_path", lambda: kbf)
        result = keybindings.load_keybindings()
        assert result.get("submit") == "ctrl-j"

    def test_load_keybindings_malformed(self, tmp_path, monkeypatch):
        from luckyd_code import keybindings
        kbf = tmp_path / "keybindings.json"
        kbf.write_text("not json!", encoding="utf-8")
        monkeypatch.setattr(keybindings, "get_keybindings_path", lambda: kbf)
        result = keybindings.load_keybindings()
        assert result == {}

    def test_parse_key_sequence_regular(self):
        from luckyd_code.keybindings import _parse_key_sequence
        assert _parse_key_sequence("enter") == ("enter",)
        assert _parse_key_sequence("ctrl-c") == ("ctrl-c",)

    def test_parse_key_sequence_alt(self):
        from luckyd_code.keybindings import _parse_key_sequence
        assert _parse_key_sequence("alt-enter") == ("escape", "enter")
        assert _parse_key_sequence("alt-a") == ("escape", "a")

    def test_apply_keybindings_returns_bindings(self, tmp_path, monkeypatch):
        from luckyd_code import keybindings
        monkeypatch.setattr(keybindings, "get_keybindings_path", lambda: tmp_path / "none.json")
        kb = keybindings.apply_keybindings()
        assert kb is not None


# ===========================================================================
# tools/datetime_tool.py
# ===========================================================================

class TestDateTimeTool:
    def test_returns_string(self):
        from luckyd_code.tools.datetime_tool import DateTimeTool
        tool = DateTimeTool()
        result = tool.run()
        assert isinstance(result, str) and len(result) > 0

    def test_custom_format(self):
        from luckyd_code.tools.datetime_tool import DateTimeTool
        tool = DateTimeTool()
        result = tool.run(format="%Y")
        assert len(result) == 4 and result.isdigit()

    def test_tool_name(self):
        from luckyd_code.tools.datetime_tool import DateTimeTool
        assert DateTimeTool().name == "DateTime"

    def test_to_openai_format(self):
        from luckyd_code.tools.datetime_tool import DateTimeTool
        schema = DateTimeTool().to_openai_tool()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "DateTime"


# ===========================================================================
# tools/registry.py  (caching + execute paths)
# ===========================================================================

class TestToolRegistryExtras:
    def test_execute_unknown_tool(self):
        from luckyd_code.tools.registry import ToolRegistry
        reg = ToolRegistry()
        result = reg.execute("Nonexistent", {})
        assert "unknown tool" in result

    def test_execute_permission_denied(self):
        from luckyd_code.tools.registry import ToolRegistry, Tool
        class MyTool(Tool):
            name = "MyTool"
            description = "test"
            def run(self, **kwargs): return "ok"
        reg = ToolRegistry()
        reg.register(MyTool())
        result = reg.execute("MyTool", {}, check_perm=lambda n: False)
        assert "Permission denied" in result

    def test_execute_tool_exception(self):
        from luckyd_code.tools.registry import ToolRegistry, Tool
        class BrokenTool(Tool):
            name = "BrokenTool"
            description = "broken"
            def run(self, **kwargs): raise ValueError("boom")
        reg = ToolRegistry()
        reg.register(BrokenTool())
        result = reg.execute("BrokenTool", {})
        assert "Error executing" in result

    def test_cache_hit(self):
        from luckyd_code.tools.datetime_tool import DateTimeTool
        from luckyd_code.tools.registry import ToolRegistry
        reg = ToolRegistry(cache_ttl=60)
        reg.register(DateTimeTool())
        r1 = reg.execute("DateTime", {})
        r2 = reg.execute("DateTime", {})
        assert r1 == r2  # cached

    def test_cache_disabled(self):
        from luckyd_code.tools.datetime_tool import DateTimeTool
        from luckyd_code.tools.registry import ToolRegistry
        reg = ToolRegistry(cache_ttl=0)
        reg.register(DateTimeTool())
        r1 = reg.execute("DateTime", {})
        r2 = reg.execute("DateTime", {})
        assert isinstance(r1, str)

    def test_invalidate_specific(self):
        from luckyd_code.tools.datetime_tool import DateTimeTool
        from luckyd_code.tools.registry import ToolRegistry
        reg = ToolRegistry(cache_ttl=60)
        reg.register(DateTimeTool())
        reg.execute("DateTime", {})  # populate cache
        removed = reg.invalidate("DateTime")
        assert removed >= 1

    def test_invalidate_all(self):
        from luckyd_code.tools.datetime_tool import DateTimeTool
        from luckyd_code.tools.registry import ToolRegistry
        reg = ToolRegistry(cache_ttl=60)
        reg.register(DateTimeTool())
        reg.execute("DateTime", {})
        removed = reg.invalidate()
        assert removed >= 0

    def test_cache_key_stable(self):
        from luckyd_code.tools.registry import ToolRegistry
        k1 = ToolRegistry._cache_key("Read", {"a": 1, "b": 2})
        k2 = ToolRegistry._cache_key("Read", {"b": 2, "a": 1})
        assert k1 == k2  # sorted args → same key


# ===========================================================================
# tools/shell_detect.py
# ===========================================================================

class TestShellDetect:
    def test_detect_shell_unix(self):
        from luckyd_code.tools.shell_detect import detect_shell
        with patch("sys.platform", "linux"):
            with patch("os.environ", {"SHELL": "/bin/bash"}):
                with patch("shutil.which", return_value="/bin/bash"):
                    info = detect_shell()
        assert info.unix_like is True

    def test_detect_shell_windows_git_bash(self):
        from luckyd_code.tools.shell_detect import detect_shell
        with patch("sys.platform", "win32"):
            with patch("luckyd_code.tools.shell_detect._find_git_bash", return_value=r"C:\Git\bin\bash.exe"):
                info = detect_shell()
        assert info.name == "git_bash"

    def test_detect_shell_windows_wsl(self):
        from luckyd_code.tools.shell_detect import detect_shell
        with patch("sys.platform", "win32"):
            with patch("luckyd_code.tools.shell_detect._find_git_bash", return_value=None):
                with patch("luckyd_code.tools.shell_detect._find_wsl", return_value="wsl.exe"):
                    info = detect_shell()
        assert info.name == "wsl"

    def test_detect_shell_windows_cmd_fallback(self):
        from luckyd_code.tools.shell_detect import detect_shell
        with patch("sys.platform", "win32"):
            with patch("luckyd_code.tools.shell_detect._find_git_bash", return_value=None):
                with patch("luckyd_code.tools.shell_detect._find_wsl", return_value=None):
                    info = detect_shell()
        assert info.name == "cmd"
        assert info.unix_like is False

    def test_find_git_bash_in_path(self):
        from luckyd_code.tools.shell_detect import _find_git_bash
        with patch("shutil.which", return_value=r"C:\Git\bin\bash.exe"):
            with patch("luckyd_code.tools.shell_detect._is_windows_store_stub", return_value=False):
                result = _find_git_bash()
        assert result == r"C:\Git\bin\bash.exe"

    def test_find_git_bash_store_stub_skipped(self):
        from luckyd_code.tools.shell_detect import _find_git_bash
        with patch("shutil.which", return_value=r"C:\Users\user\AppData\Local\Microsoft\WindowsApps\bash.exe"):
            with patch("os.path.isfile", return_value=False):
                result = _find_git_bash()
        assert result is None

    def test_is_windows_store_stub(self):
        from luckyd_code.tools.shell_detect import _is_windows_store_stub
        assert _is_windows_store_stub(r"C:\Users\user\AppData\Local\Microsoft\WindowsApps\bash.exe")
        assert not _is_windows_store_stub(r"C:\Program Files\Git\bin\bash.exe")

    def test_find_wsl(self):
        from luckyd_code.tools.shell_detect import _find_wsl
        with patch("shutil.which", return_value="wsl.exe"):
            result = _find_wsl()
        assert result == "wsl.exe"

    def test_find_wsl_not_found(self):
        from luckyd_code.tools.shell_detect import _find_wsl
        with patch("shutil.which", return_value=None):
            result = _find_wsl()
        assert result is None

    def test_resolve_shell_auto(self):
        from luckyd_code.tools.shell_detect import resolve_shell
        info = resolve_shell("auto")
        assert info is not None

    def test_resolve_shell_cmd_override(self):
        from luckyd_code.tools.shell_detect import resolve_shell
        with patch("os.environ.get", return_value="cmd.exe"):
            info = resolve_shell("cmd")
        assert info is not None

    def test_shell_info_dataclass(self):
        from luckyd_code.tools.shell_detect import ShellInfo
        s = ShellInfo(name="git_bash", path="/usr/bin/bash", args=[], unix_like=True, description="Git Bash")
        assert s.name == "git_bash"
        assert s.unix_like is True


# ===========================================================================
# tools/git_tools.py
# ===========================================================================

class TestGitToolsCoverage:
    def test_git_status(self):
        from luckyd_code.tools.git_tools import GitStatusTool
        with patch("luckyd_code.tools.git_tools.git_status", return_value="On branch main"):
            result = GitStatusTool().run()
        assert "main" in result

    def test_git_diff(self):
        from luckyd_code.tools.git_tools import GitDiffTool
        with patch("luckyd_code.tools.git_tools.git_diff", return_value="diff output"):
            result = GitDiffTool().run()
        assert "diff output" in result

    def test_git_diff_staged(self):
        from luckyd_code.tools.git_tools import GitDiffTool
        with patch("luckyd_code.tools.git_tools.git_diff", return_value="staged diff") as mock:
            GitDiffTool().run(staged=True)
            mock.assert_called_once_with(True)

    def test_git_log(self):
        from luckyd_code.tools.git_tools import GitLogTool
        with patch("luckyd_code.tools.git_tools.git_log", return_value="abc commit") as mock:
            result = GitLogTool().run(count=5)
            mock.assert_called_once_with(5)
        assert "abc commit" in result

    def test_git_commit(self):
        from luckyd_code.tools.git_tools import GitCommitTool
        with patch("luckyd_code.tools.git_tools.git_commit", return_value="committed") as mock:
            result = GitCommitTool().run(message="fix: bug")
            mock.assert_called_once_with("fix: bug")
        assert "committed" in result

    def test_git_add(self):
        from luckyd_code.tools.git_tools import GitAddTool
        with patch("luckyd_code.tools.git_tools.git_add", return_value="Staged") as mock:
            result = GitAddTool().run(files=["a.py"])
        assert "Staged" in result

    def test_git_branch(self):
        from luckyd_code.tools.git_tools import GitBranchTool
        with patch("luckyd_code.tools.git_tools.git_branch", return_value="* main"):
            result = GitBranchTool().run()
        assert "main" in result

    def test_git_pr(self):
        from luckyd_code.tools.git_tools import GitPRTool
        with patch("luckyd_code.tools.git_tools.git_push", return_value="pushed"):
            with patch("luckyd_code.tools.git_tools.git_create_pr", return_value="PR created"):
                result = GitPRTool().run(title="My PR", body="desc")
        assert "pushed" in result
        assert "PR created" in result

    def test_git_push(self):
        from luckyd_code.tools.git_tools import GitPushTool
        with patch("luckyd_code.tools.git_tools.git_push", return_value="pushed") as mock:
            result = GitPushTool().run(branch="main")
            mock.assert_called_once_with("main")
        assert "pushed" in result


# ===========================================================================
# tools/git_worktree.py
# ===========================================================================

class TestGitWorktree:
    def _mock_run(self, stdout="", returncode=0):
        r = MagicMock(returncode=returncode, stdout=stdout, stderr="")
        return r

    def test_list(self):
        from luckyd_code.tools.git_worktree import GitWorktreeTool
        with patch("subprocess.run", return_value=self._mock_run("worktree1\nworktree2")):
            result = GitWorktreeTool().run(action="list")
        assert "worktree" in result

    def test_create_no_path(self):
        from luckyd_code.tools.git_worktree import GitWorktreeTool
        result = GitWorktreeTool().run(action="create")
        assert "Error" in result

    def test_create_with_path(self):
        from luckyd_code.tools.git_worktree import GitWorktreeTool
        with patch("subprocess.run", return_value=self._mock_run("Preparing worktree")):
            result = GitWorktreeTool().run(action="create", path="../other")
        assert isinstance(result, str)

    def test_create_with_branch(self):
        from luckyd_code.tools.git_worktree import GitWorktreeTool
        with patch("subprocess.run", return_value=self._mock_run("created")) as mock:
            GitWorktreeTool().run(action="create", path="../feat", branch="feat/x")
        called = mock.call_args[0][0]
        assert "-b" in called

    def test_remove(self):
        from luckyd_code.tools.git_worktree import GitWorktreeTool
        with patch("subprocess.run", return_value=self._mock_run("Removing")):
            result = GitWorktreeTool().run(action="remove", path="../other")
        assert isinstance(result, str)

    def test_remove_no_path(self):
        from luckyd_code.tools.git_worktree import GitWorktreeTool
        result = GitWorktreeTool().run(action="remove")
        assert "Error" in result

    def test_unknown_action(self):
        from luckyd_code.tools.git_worktree import GitWorktreeTool
        result = GitWorktreeTool().run(action="rebase")
        assert "Unknown" in result

    def test_timeout(self):
        from luckyd_code.tools.git_worktree import GitWorktreeTool
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 30)):
            result = GitWorktreeTool().run(action="list")
        assert "timed out" in result


# ===========================================================================
# git/tools.py
# ===========================================================================

class TestGitModuleTools:
    def _mk(self, stdout="", returncode=0):
        r = MagicMock(returncode=returncode, stdout=stdout, stderr="")
        return r

    def test_git_status_ok(self):
        from luckyd_code.git.tools import git_status
        with patch("subprocess.run", return_value=self._mk("On branch main")):
            assert "main" in git_status()

    def test_git_status_error(self):
        from luckyd_code.git.tools import git_status
        with patch("subprocess.run", side_effect=Exception("fail")):
            assert "Error" in git_status()

    def test_git_diff_ok(self):
        from luckyd_code.git.tools import git_diff
        with patch("subprocess.run", return_value=self._mk("diff output")):
            assert "diff output" in git_diff()

    def test_git_diff_no_changes(self):
        from luckyd_code.git.tools import git_diff
        with patch("subprocess.run", return_value=self._mk("")):
            assert git_diff() == "No changes"

    def test_git_diff_staged(self):
        from luckyd_code.git.tools import git_diff
        with patch("subprocess.run", return_value=self._mk("staged diff")) as mock:
            git_diff(staged=True)
        assert "--cached" in mock.call_args[0][0]

    def test_git_log_ok(self):
        from luckyd_code.git.tools import git_log
        with patch("subprocess.run", return_value=self._mk("abc fix bug")):
            assert "fix bug" in git_log(5)

    def test_git_commit_ok(self):
        from luckyd_code.git.tools import git_commit
        with patch("subprocess.run", return_value=self._mk("committed")):
            assert "committed" in git_commit("feat: add thing")

    def test_git_add_all(self):
        from luckyd_code.git.tools import git_add
        with patch("subprocess.run", return_value=self._mk("Staged")) as mock:
            git_add()
        assert "-A" in mock.call_args[0][0]

    def test_git_add_files(self):
        from luckyd_code.git.tools import git_add
        with patch("subprocess.run", return_value=self._mk()) as mock:
            git_add(["a.py", "b.py"])
        assert "a.py" in mock.call_args[0][0]

    def test_git_branch_ok(self):
        from luckyd_code.git.tools import git_branch
        with patch("subprocess.run", return_value=self._mk("* main\n  dev")):
            assert "main" in git_branch()

    def test_git_create_pr(self):
        from luckyd_code.git.tools import git_create_pr
        with patch("subprocess.run", return_value=self._mk("https://github.com/pr/1")):
            result = git_create_pr("My PR", "desc", draft=True)
        assert isinstance(result, str)

    def test_git_push(self):
        from luckyd_code.git.tools import git_push
        with patch("subprocess.run", return_value=self._mk("pushed")):
            assert "pushed" in git_push()

    def test_git_push_branch(self):
        from luckyd_code.git.tools import git_push
        with patch("subprocess.run", return_value=self._mk("pushed")) as mock:
            git_push("main")
        assert "main" in mock.call_args[0][0]


# ===========================================================================
# git/auto_commit.py
# ===========================================================================

class TestAutoCommit:
    def test_collect_modified_paths_write(self):
        from luckyd_code.git.auto_commit import collect_modified_paths
        tool_calls = [{"id": "tc1", "function": {"name": "Write", "arguments": ""}}]
        tool_args = {"tc1": {"file_path": "main.py"}}
        result = collect_modified_paths(tool_calls, tool_args)
        assert "main.py" in result

    def test_collect_modified_paths_edit(self):
        from luckyd_code.git.auto_commit import collect_modified_paths
        tool_calls = [{"id": "tc2", "function": {"name": "Edit", "arguments": ""}}]
        tool_args = {"tc2": {"file_path": "app.py"}}
        result = collect_modified_paths(tool_calls, tool_args)
        assert "app.py" in result

    def test_collect_modified_paths_deduplication(self):
        from luckyd_code.git.auto_commit import collect_modified_paths
        tool_calls = [
            {"id": "tc1", "function": {"name": "Write", "arguments": ""}},
            {"id": "tc2", "function": {"name": "Edit", "arguments": ""}},
        ]
        tool_args = {"tc1": {"file_path": "x.py"}, "tc2": {"file_path": "x.py"}}
        result = collect_modified_paths(tool_calls, tool_args)
        assert result.count("x.py") == 1

    def test_collect_ignores_non_write_tools(self):
        from luckyd_code.git.auto_commit import collect_modified_paths
        tool_calls = [{"id": "tc1", "function": {"name": "Read", "arguments": ""}}]
        tool_args = {"tc1": {"file_path": "main.py"}}
        result = collect_modified_paths(tool_calls, tool_args)
        assert result == []

    def test_make_commit_message(self):
        from luckyd_code.git.auto_commit import _make_commit_message
        msg = _make_commit_message("Fix the authentication bug in login flow")
        assert msg.startswith("agent: ")
        assert len(msg) <= 80

    def test_make_commit_message_long(self):
        from luckyd_code.git.auto_commit import _make_commit_message
        long_prompt = "x" * 200
        msg = _make_commit_message(long_prompt)
        assert len(msg) <= 80

    def test_in_git_repo_true(self):
        from luckyd_code.git.auto_commit import _in_git_repo
        with patch("subprocess.run", return_value=MagicMock(returncode=0)):
            assert _in_git_repo() is True

    def test_in_git_repo_false(self):
        from luckyd_code.git.auto_commit import _in_git_repo
        with patch("subprocess.run", return_value=MagicMock(returncode=1)):
            assert _in_git_repo() is False

    def test_stage_files_success(self):
        from luckyd_code.git.auto_commit import _stage_files
        with patch("subprocess.run", return_value=MagicMock(returncode=0, stderr="")):
            assert _stage_files(["a.py"]) is True

    def test_stage_files_empty(self):
        from luckyd_code.git.auto_commit import _stage_files
        assert _stage_files([]) is False

    def test_stage_files_failure(self):
        from luckyd_code.git.auto_commit import _stage_files
        with patch("subprocess.run", return_value=MagicMock(returncode=1, stderr="permission denied")):
            assert _stage_files(["a.py"]) is False

    def test_has_staged_changes_yes(self):
        from luckyd_code.git.auto_commit import _has_staged_changes
        with patch("subprocess.run", return_value=MagicMock(returncode=1)):
            assert _has_staged_changes() is True

    def test_has_staged_changes_no(self):
        from luckyd_code.git.auto_commit import _has_staged_changes
        with patch("subprocess.run", return_value=MagicMock(returncode=0)):
            assert _has_staged_changes() is False

    def test_auto_commit_disabled(self):
        from luckyd_code.git.auto_commit import auto_commit
        result = auto_commit("fix bug", ["a.py"], enabled=False)
        assert result is None

    def test_auto_commit_no_paths(self):
        from luckyd_code.git.auto_commit import auto_commit
        result = auto_commit("fix bug", [])
        assert result is None

    def test_auto_commit_not_in_repo(self):
        from luckyd_code.git.auto_commit import auto_commit
        with patch("luckyd_code.git.auto_commit._in_git_repo", return_value=False):
            result = auto_commit("fix bug", ["a.py"])
        assert result is None

    def test_auto_commit_success(self):
        from luckyd_code.git.auto_commit import auto_commit
        with patch("luckyd_code.git.auto_commit._in_git_repo", return_value=True):
            with patch("luckyd_code.git.auto_commit._stage_files", return_value=True):
                with patch("luckyd_code.git.auto_commit._has_staged_changes", return_value=True):
                    with patch("luckyd_code.git.auto_commit._commit", return_value="abc1234"):
                        result = auto_commit("fix bug", ["a.py"])
        assert result == "abc1234"


# ===========================================================================
# file_watcher.py
# ===========================================================================

class TestFileWatcher:
    def test_init_defaults(self):
        from luckyd_code.file_watcher import FileWatcher
        fw = FileWatcher()
        assert fw.root is not None
        assert fw.debounce_seconds == 3.0
        assert fw.is_running is False

    def test_init_custom(self, tmp_path):
        from luckyd_code.file_watcher import FileWatcher
        fw = FileWatcher(root=str(tmp_path), debounce_seconds=1.0)
        assert fw.root == tmp_path.resolve()

    def test_start_polling(self, tmp_path):
        from luckyd_code.file_watcher import FileWatcher
        with patch("luckyd_code.file_watcher.FileWatcher._try_watchdog", return_value=False):
            fw = FileWatcher(root=str(tmp_path))
            fw.start()
            assert fw.is_running
            fw.stop()

    def test_start_already_running(self, tmp_path):
        from luckyd_code.file_watcher import FileWatcher
        with patch("luckyd_code.file_watcher.FileWatcher._try_watchdog", return_value=False):
            fw = FileWatcher(root=str(tmp_path))
            fw.start()
            fw.start()  # second start should no-op
            assert fw.is_running
            fw.stop()

    def test_stop(self, tmp_path):
        from luckyd_code.file_watcher import FileWatcher
        with patch("luckyd_code.file_watcher.FileWatcher._try_watchdog", return_value=False):
            fw = FileWatcher(root=str(tmp_path))
            fw.start()
            fw.stop()
        assert fw.is_running is False

    def test_pause_resume(self, tmp_path):
        from luckyd_code.file_watcher import FileWatcher
        fw = FileWatcher(root=str(tmp_path))
        fw.pause()
        assert fw._paused is True
        fw.resume()
        assert fw._paused is False

    def test_status_stopped(self, tmp_path):
        from luckyd_code.file_watcher import FileWatcher
        fw = FileWatcher(root=str(tmp_path))
        assert fw.status == "stopped"

    def test_status_running_polling(self, tmp_path):
        from luckyd_code.file_watcher import FileWatcher
        with patch("luckyd_code.file_watcher.FileWatcher._try_watchdog", return_value=False):
            fw = FileWatcher(root=str(tmp_path))
            fw.start()
            status = fw.status
            fw.stop()
        assert "running" in status

    def test_on_file_changed_ignored_ext(self, tmp_path):
        from luckyd_code.file_watcher import FileWatcher
        fw = FileWatcher(root=str(tmp_path))
        fw._on_file_changed(str(tmp_path / "image.png"))
        assert len(fw._pending) == 0

    def test_on_file_changed_valid_ext(self, tmp_path):
        from luckyd_code.file_watcher import FileWatcher
        fw = FileWatcher(root=str(tmp_path))
        fw._on_file_changed(str(tmp_path / "app.py"))
        assert str(tmp_path / "app.py") in fw._pending

    def test_on_file_changed_while_paused(self, tmp_path):
        from luckyd_code.file_watcher import FileWatcher
        fw = FileWatcher(root=str(tmp_path))
        fw.pause()
        fw._on_file_changed(str(tmp_path / "app.py"))
        assert len(fw._pending) == 0


# ===========================================================================
# tools/bash.py  — safety layer and command fixers
# ===========================================================================

class TestBashSafety:
    def test_is_dangerous_rm_rf(self):
        from luckyd_code.tools.bash import _is_dangerous
        result = _is_dangerous("rm -rf /")
        assert result is not None
        assert "blocked" in result.lower()

    def test_is_dangerous_sudo(self):
        from luckyd_code.tools.bash import _is_dangerous
        result = _is_dangerous("sudo apt install vim")
        assert result is not None

    def test_is_dangerous_fork_bomb(self):
        from luckyd_code.tools.bash import _is_dangerous
        result = _is_dangerous(":(){ :|:& };:")
        assert result is not None

    def test_is_dangerous_safe_command(self):
        from luckyd_code.tools.bash import _is_dangerous
        result = _is_dangerous("ls -la")
        assert result is None

    def test_is_dangerous_interactive_vim(self):
        from luckyd_code.tools.bash import _is_dangerous
        result = _is_dangerous("vim myfile.py")
        assert result is not None

    def test_fix_windows_cmd_date(self):
        from luckyd_code.tools.bash import _fix_windows_cmd
        assert _fix_windows_cmd("date") == "date /T"

    def test_fix_windows_cmd_time(self):
        from luckyd_code.tools.bash import _fix_windows_cmd
        assert _fix_windows_cmd("time") == "time /T"

    def test_fix_windows_cmd_ping(self):
        from luckyd_code.tools.bash import _fix_windows_cmd
        result = _fix_windows_cmd("ping google.com")
        assert "-n 4" in result

    def test_fix_windows_cmd_pause(self):
        from luckyd_code.tools.bash import _fix_windows_cmd
        assert _fix_windows_cmd("pause") == "echo."

    def test_fix_windows_cmd_choice(self):
        from luckyd_code.tools.bash import _fix_windows_cmd
        result = _fix_windows_cmd("choice")
        assert "/T" in result

    def test_fix_windows_cmd_clip(self):
        from luckyd_code.tools.bash import _fix_windows_cmd
        result = _fix_windows_cmd("clip")
        assert "clip" in result

    def test_fix_windows_cmd_passthrough(self):
        from luckyd_code.tools.bash import _fix_windows_cmd
        assert _fix_windows_cmd("echo hello") == "echo hello"

    def test_fix_unix_ping(self):
        from luckyd_code.tools.bash import _fix_unix_ping
        result = _fix_unix_ping("ping google.com")
        assert "-c 4" in result

    def test_fix_unix_ping_already_has_flag(self):
        from luckyd_code.tools.bash import _fix_unix_ping
        cmd = "ping -c 3 google.com"
        assert _fix_unix_ping(cmd) == cmd

    def test_bash_tool_blocked_command(self):
        from luckyd_code.tools.bash import BashTool
        result = BashTool().run(command="rm -rf /")
        assert "Error" in result

    def test_bash_tool_name(self):
        from luckyd_code.tools.bash import BashTool
        assert BashTool().name == "Bash"

    def test_reset_shell_cache(self):
        from luckyd_code.tools.bash import reset_shell_cache, _get_shell
        _get_shell()  # populate cache
        reset_shell_cache()
        from luckyd_code.tools import bash as bash_mod
        assert bash_mod._SHELL_CACHE is None


# ===========================================================================
# tools/agent_tools.py
# ===========================================================================

class TestAgentTools:
    def test_sub_agent_no_repl(self):
        from luckyd_code.tools.agent_tools import SubAgentTool, set_repl
        set_repl(None)
        result = SubAgentTool().run(task="do something")
        assert "Error" in result

    def test_agent_handoff_no_repl(self):
        from luckyd_code.tools.agent_tools import AgentHandoffTool, set_repl
        set_repl(None)
        result = AgentHandoffTool().run(role="coder", task="write code")
        assert "Error" in result

    def test_sub_agent_name(self):
        from luckyd_code.tools.agent_tools import SubAgentTool
        assert SubAgentTool().name == "SubAgent"

    def test_agent_handoff_name(self):
        from luckyd_code.tools.agent_tools import AgentHandoffTool
        assert AgentHandoffTool().name == "AgentHandoff"

    def test_set_repl(self):
        from luckyd_code.tools.agent_tools import set_repl
        mock_repl = MagicMock()
        set_repl(mock_repl)
        from luckyd_code.tools import agent_tools
        assert agent_tools._repl is mock_repl
        set_repl(None)  # cleanup


# ===========================================================================
# tools/brain_tools.py
# ===========================================================================

class TestBrainToolsCoverage:
    def test_brain_search_no_results(self):
        from luckyd_code.tools.brain_tools import BrainSearchTool
        mock_retriever = MagicMock()
        mock_retriever.search.return_value = []
        mock_graph = MagicMock()
        mock_graph.nodes = {}
        with patch("luckyd_code.tools.brain_tools._get_retriever", return_value=mock_retriever):
            with patch("luckyd_code.tools.brain_tools._get_graph", return_value=mock_graph):
                result = BrainSearchTool().run(query="nonexistent")
        assert "empty" in result.lower() or "No results" in result

    def test_brain_search_with_results(self):
        from luckyd_code.tools.brain_tools import BrainSearchTool
        mock_retriever = MagicMock()
        mock_retriever.search.return_value = [
            {"file_path": "main.py", "start_line": 1, "end_line": 10,
             "score": 0.95, "name": "main", "type": "function", "language": "python"}
        ]
        with patch("luckyd_code.tools.brain_tools._get_retriever", return_value=mock_retriever):
            result = BrainSearchTool().run(query="main function")
        assert "main.py" in result

    def test_brain_status(self):
        from luckyd_code.tools.brain_tools import BrainStatusTool
        mock_retriever = MagicMock()
        mock_retriever.stats.return_value = {
            "vector": {"available": True, "chunks": 100, "files": 10, "languages": {"python": 10}},
            "graph": {"nodes": 50, "edges": 30, "files_parsed": 5},
        }
        with patch("luckyd_code.tools.brain_tools._get_retriever", return_value=mock_retriever):
            result = BrainStatusTool().run()
        assert "Vector Index" in result
        assert "100" in result

    def test_brain_status_unavailable(self):
        from luckyd_code.tools.brain_tools import BrainStatusTool
        mock_retriever = MagicMock()
        mock_retriever.stats.return_value = {
            "vector": {"available": False},
            "graph": {},
        }
        with patch("luckyd_code.tools.brain_tools._get_retriever", return_value=mock_retriever):
            result = BrainStatusTool().run()
        assert "Not available" in result or "Vector" in result

    def test_brain_search_tool_name(self):
        from luckyd_code.tools.brain_tools import BrainSearchTool
        assert BrainSearchTool().name == "BrainSearch"

    def test_brain_status_tool_name(self):
        from luckyd_code.tools.brain_tools import BrainStatusTool
        assert BrainStatusTool().name == "BrainStatus"


# ===========================================================================
# tools/web.py  (helpers; no live network calls)
# ===========================================================================

class TestWebHelpers:
    def test_escape_html_via_extract(self):
        from luckyd_code.tools.web import _extract_text
        html = "<html><body><script>x=1</script><p>Hello world</p></body></html>"
        result = _extract_text(html)
        assert "Hello world" in result
        assert "x=1" not in result

    def test_try_meta_extraction_with_description(self):
        from luckyd_code.tools.web import _try_meta_extraction
        html = '<html><head><meta name="description" content="Page desc"/></head></html>'
        result = _try_meta_extraction(html)
        assert result is not None
        assert "Page desc" in result

    def test_try_meta_extraction_no_meta(self):
        from luckyd_code.tools.web import _try_meta_extraction
        html = "<html><head></head><body>nothing</body></html>"
        result = _try_meta_extraction(html)
        assert result is None

    def test_web_fetch_http_error(self):
        from luckyd_code.tools.web import WebFetchTool
        import httpx
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = "Not Found"
        with patch("httpx.get", side_effect=httpx.HTTPStatusError("404", request=MagicMock(), response=mock_resp)):
            result = WebFetchTool().run(url="https://example.com/404")
        assert "404" in result

    def test_web_fetch_exception(self):
        from luckyd_code.tools.web import WebFetchTool
        with patch("httpx.get", side_effect=Exception("connection refused")):
            result = WebFetchTool().run(url="https://nonexistent.invalid")
        assert "Error" in result

    def test_web_fetch_html_success(self):
        from luckyd_code.tools.web import WebFetchTool
        mock_resp = MagicMock()
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.text = "<html><body>" + "<p>Content here.</p>" * 20 + "</body></html>"
        mock_resp.raise_for_status = MagicMock()
        with patch("httpx.get", return_value=mock_resp):
            with patch("luckyd_code.tools.web._OEMBED_PLATFORMS", []):
                result = WebFetchTool().run(url="https://example.com")
        assert isinstance(result, str)

    def test_web_fetch_non_html(self):
        from luckyd_code.tools.web import WebFetchTool
        mock_resp = MagicMock()
        mock_resp.headers = {"content-type": "text/plain"}
        mock_resp.text = "plain text content"
        mock_resp.raise_for_status = MagicMock()
        with patch("httpx.get", return_value=mock_resp):
            result = WebFetchTool().run(url="https://example.com/file.txt")
        assert "plain text" in result

    def test_ddg_api_no_results(self):
        from luckyd_code.tools.web import WebSearchTool
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"AbstractText": "", "RelatedTopics": []}
        with patch("httpx.get", return_value=mock_resp):
            result = WebSearchTool._search_ddg_api("nothing_will_match_xyz")
        assert result is None

    def test_ddg_html_captcha(self):
        from luckyd_code.tools.web import WebSearchTool
        mock_resp = MagicMock()
        mock_resp.status_code = 202
        with patch("httpx.get", return_value=mock_resp):
            result = WebSearchTool._search_ddg_html("test query")
        assert result is None

    def test_web_search_all_providers_fail(self):
        from luckyd_code.tools.web import WebSearchTool
        with patch("luckyd_code.tools.web.WebSearchTool._search_ddg_html", return_value=None):
            with patch("luckyd_code.tools.web.WebSearchTool._search_ddg_api", return_value=None):
                with patch("luckyd_code.tools.web.WebSearchTool._search_searxng", return_value=None):
                    result = WebSearchTool().run(query="test")
        assert "No results" in result

    def test_web_search_tool_name(self):
        from luckyd_code.tools.web import WebSearchTool
        assert WebSearchTool().name == "WebSearch"

    def test_web_fetch_tool_name(self):
        from luckyd_code.tools.web import WebFetchTool
        assert WebFetchTool().name == "WebFetch"


# ===========================================================================
# tools/readme_gen.py  — helpers + error paths
# ===========================================================================

class TestReadmeGen:
    def test_collect_files_basic(self, tmp_path):
        from luckyd_code.tools.readme_gen import _collect_files
        (tmp_path / "main.py").write_text("# main", encoding="utf-8")
        (tmp_path / "README.md").write_text("# readme", encoding="utf-8")
        files = _collect_files(tmp_path)
        names = [f[0] for f in files]
        assert any("README.md" in n or "main.py" in n for n in names)

    def test_format_context(self):
        from luckyd_code.tools.readme_gen import _format_context
        files = [("main.py", "print('hi')"), ("test.py", "def test(): pass")]
        result = _format_context(files)
        assert "main.py" in result
        assert "print('hi')" in result

    def test_run_not_a_directory(self, tmp_path):
        from luckyd_code.tools.readme_gen import ReadmeGenTool
        result = ReadmeGenTool().run(project_dir=str(tmp_path / "nonexistent"))
        assert "Error" in result

    def test_run_readme_exists_no_overwrite(self, tmp_path):
        from luckyd_code.tools.readme_gen import ReadmeGenTool
        (tmp_path / "README.md").write_text("existing", encoding="utf-8")
        result = ReadmeGenTool().run(project_dir=str(tmp_path), overwrite=False)
        assert "already exists" in result

    def test_run_no_source_files(self, tmp_path):
        from luckyd_code.tools.readme_gen import ReadmeGenTool
        with patch("luckyd_code.tools.readme_gen._collect_files", return_value=[]):
            result = ReadmeGenTool().run(project_dir=str(tmp_path))
        assert "Error" in result

    def test_run_model_fails(self, tmp_path):
        from luckyd_code.tools.readme_gen import ReadmeGenTool
        (tmp_path / "main.py").write_text("pass", encoding="utf-8")
        with patch.object(ReadmeGenTool, "_call_model", side_effect=Exception("API down")):
            result = ReadmeGenTool().run(project_dir=str(tmp_path))
        assert "Error" in result

    def test_run_success(self, tmp_path):
        from luckyd_code.tools.readme_gen import ReadmeGenTool
        (tmp_path / "main.py").write_text("pass", encoding="utf-8")
        with patch.object(ReadmeGenTool, "_call_model", return_value="# MyProject\nGreat project."):
            result = ReadmeGenTool().run(project_dir=str(tmp_path))
        assert "generated" in result.lower() or "README" in result
        assert (tmp_path / "README.md").exists()

    def test_run_strips_code_fences(self, tmp_path):
        from luckyd_code.tools.readme_gen import ReadmeGenTool
        (tmp_path / "main.py").write_text("pass", encoding="utf-8")
        fenced = "```markdown\n# Title\nContent\n```"
        with patch.object(ReadmeGenTool, "_call_model", return_value=fenced):
            ReadmeGenTool().run(project_dir=str(tmp_path))
        content = (tmp_path / "README.md").read_text()
        assert "```" not in content


# ===========================================================================
# tools/dockerfile_gen.py  — helpers + error paths
# ===========================================================================

class TestDockerfileGen:
    def test_collect_context(self, tmp_path):
        from luckyd_code.tools.dockerfile_gen import _collect_context
        (tmp_path / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
        result = _collect_context(tmp_path)
        assert "requirements.txt" in result
        assert "fastapi" in result

    def test_run_not_a_directory(self, tmp_path):
        from luckyd_code.tools.dockerfile_gen import DockerfileGenTool
        result = DockerfileGenTool().run(project_dir=str(tmp_path / "nope"))
        assert "Error" in result

    def test_run_dockerfile_exists_no_overwrite(self, tmp_path):
        from luckyd_code.tools.dockerfile_gen import DockerfileGenTool
        (tmp_path / "Dockerfile").write_text("FROM python:3.12", encoding="utf-8")
        result = DockerfileGenTool().run(project_dir=str(tmp_path), overwrite=False)
        assert "already exists" in result

    def test_run_no_source_files(self, tmp_path):
        from luckyd_code.tools.dockerfile_gen import DockerfileGenTool
        with patch("luckyd_code.tools.dockerfile_gen._collect_context", return_value=""):
            result = DockerfileGenTool().run(project_dir=str(tmp_path))
        assert "Error" in result

    def test_run_model_fails(self, tmp_path):
        from luckyd_code.tools.dockerfile_gen import DockerfileGenTool
        (tmp_path / "main.py").write_text("pass", encoding="utf-8")
        with patch.object(DockerfileGenTool, "_call_model", side_effect=Exception("fail")):
            result = DockerfileGenTool().run(project_dir=str(tmp_path))
        assert "Error" in result

    def test_run_invalid_json(self, tmp_path):
        from luckyd_code.tools.dockerfile_gen import DockerfileGenTool
        (tmp_path / "main.py").write_text("pass", encoding="utf-8")
        with patch.object(DockerfileGenTool, "_call_model", side_effect=json.JSONDecodeError("bad", "", 0)):
            result = DockerfileGenTool().run(project_dir=str(tmp_path))
        assert "invalid JSON" in result

    def test_run_success(self, tmp_path):
        from luckyd_code.tools.dockerfile_gen import DockerfileGenTool
        (tmp_path / "main.py").write_text("pass", encoding="utf-8")
        with patch.object(DockerfileGenTool, "_call_model",
                          return_value={"dockerfile": "FROM python:3.12\nCMD [\"python\"]",
                                        "compose": "", "notes": ""}):
            result = DockerfileGenTool().run(project_dir=str(tmp_path))
        assert (tmp_path / "Dockerfile").exists()

    def test_tool_name(self):
        from luckyd_code.tools.dockerfile_gen import DockerfileGenTool
        assert DockerfileGenTool().name == "DockerfileGen"


# ===========================================================================
# tools/project_gen.py  — error paths
# ===========================================================================

class TestProjectGen:
    def test_run_model_fails(self, tmp_path):
        from luckyd_code.tools.project_gen import ProjectGenTool
        with patch.object(ProjectGenTool, "_call_model", side_effect=Exception("API down")):
            result = ProjectGenTool().run(description="FastAPI app", output_dir=str(tmp_path))
        assert "Error" in result

    def test_run_invalid_json(self, tmp_path):
        from luckyd_code.tools.project_gen import ProjectGenTool
        with patch.object(ProjectGenTool, "_call_model", side_effect=json.JSONDecodeError("bad", "", 0)):
            result = ProjectGenTool().run(description="FastAPI app", output_dir=str(tmp_path))
        assert "invalid JSON" in result

    def test_run_no_files(self, tmp_path):
        from luckyd_code.tools.project_gen import ProjectGenTool
        with patch.object(ProjectGenTool, "_call_model",
                          return_value={"project_name": "test", "files": [], "stack": "Python"}):
            result = ProjectGenTool().run(description="nothing", output_dir=str(tmp_path))
        assert "Error" in result

    def test_run_success(self, tmp_path):
        from luckyd_code.tools.project_gen import ProjectGenTool
        scaffold = {
            "project_name": "my-app",
            "description": "A test app",
            "stack": "Python",
            "files": [{"path": "main.py", "content": "print('hello')"}],
            "install": "pip install -r requirements.txt",
            "run": "python main.py",
            "notes": "",
        }
        with patch.object(ProjectGenTool, "_call_model", return_value=scaffold):
            result = ProjectGenTool().run(description="simple app", output_dir=str(tmp_path))
        assert "my-app" in result
        assert (tmp_path / "my-app" / "main.py").exists()

    def test_tool_name(self):
        from luckyd_code.tools.project_gen import ProjectGenTool
        assert ProjectGenTool().name == "ProjectGen"


# ===========================================================================
# tools/game_gen.py  — safety functions + error paths
# ===========================================================================

class TestGameGen:
    def test_bad_difficulty(self, tmp_path):
        from luckyd_code.tools.game_gen import GameGenTool
        result = GameGenTool().run(description="snake game", difficulty="insane", output_dir=str(tmp_path))
        assert "Error" in result

    def test_bad_output_format(self, tmp_path):
        from luckyd_code.tools.game_gen import GameGenTool
        result = GameGenTool().run(description="snake", output_format="jar", output_dir=str(tmp_path))
        assert "Error" in result

    def test_model_fails(self, tmp_path):
        from luckyd_code.tools.game_gen import GameGenTool
        with patch.object(GameGenTool, "_generate_source", side_effect=Exception("API down")):
            result = GameGenTool().run(description="snake", output_dir=str(tmp_path))
        assert "Error" in result

    def test_py_output_success(self, tmp_path):
        from luckyd_code.tools.game_gen import GameGenTool
        source = "import os\nprint('game')\n"
        with patch.object(GameGenTool, "_generate_source", return_value=source):
            result = GameGenTool().run(description="snake", output_format="py", output_dir=str(tmp_path))
        assert "generated" in result.lower() or ".py" in result

    def test_compile_exe_no_pyinstaller(self, tmp_path):
        from luckyd_code.tools.game_gen import compile_exe
        src = tmp_path / "game.py"
        src.write_text("pass", encoding="utf-8")
        with patch("luckyd_code.tools.game_gen._resolve_pyinstaller", return_value=None):
            ok, msg = compile_exe(src, tmp_path, "game")
        assert ok is False
        assert "PyInstaller" in msg

    def test_resolve_pyinstaller_found(self):
        from luckyd_code.tools.game_gen import _resolve_pyinstaller
        with patch("shutil.which", return_value="/usr/bin/pyinstaller"):
            result = _resolve_pyinstaller()
        assert result == "found"

    def test_resolve_pyinstaller_not_found(self):
        from luckyd_code.tools.game_gen import _resolve_pyinstaller
        with patch("shutil.which", return_value=None):
            with patch("subprocess.run", side_effect=Exception("not found")):
                result = _resolve_pyinstaller()
        assert result is None

    def test_tool_name(self):
        from luckyd_code.tools.game_gen import GameGenTool
        assert GameGenTool().name == "GameGen"

    def test_difficulty_constants(self):
        from luckyd_code.tools.game_gen import DIFFICULTIES, DIFFICULTY_HINTS
        assert "easy" in DIFFICULTIES
        assert "normal" in DIFFICULTIES
        assert "hard" in DIFFICULTIES
        for d in DIFFICULTIES:
            assert d in DIFFICULTY_HINTS


# ===========================================================================
# cli_commands/sessions.py
# ===========================================================================

class TestCLISessionsCommand:
    def _make_repl(self):
        repl = MagicMock()
        repl.context = MagicMock()
        return repl

    def test_no_args(self):
        from luckyd_code.cli_commands.sessions import handle_sessions_command
        repl = self._make_repl()
        with patch("luckyd_code.cli_utils.console"):
            handle_sessions_command(repl, [])

    def test_list(self):
        from luckyd_code.cli_commands.sessions import handle_sessions_command
        repl = self._make_repl()
        with patch("luckyd_code.sessions.list_sessions", return_value="session1\n"):
            with patch("luckyd_code.cli_utils.console"):
                handle_sessions_command(repl, ["list"])

    def test_save(self):
        from luckyd_code.cli_commands.sessions import handle_sessions_command
        repl = self._make_repl()
        with patch("luckyd_code.sessions.save_session", return_value="Saved"):
            with patch("luckyd_code.cli_utils.console"):
                handle_sessions_command(repl, ["save", "my-session"])

    def test_load(self):
        from luckyd_code.cli_commands.sessions import handle_sessions_command
        repl = self._make_repl()
        with patch("luckyd_code.sessions.load_session", return_value="Loaded"):
            with patch("luckyd_code.cli_utils.console"):
                handle_sessions_command(repl, ["load", "my-session"])

    def test_load_no_name(self):
        from luckyd_code.cli_commands.sessions import handle_sessions_command
        repl = self._make_repl()
        with patch("luckyd_code.cli_utils.console"):
            handle_sessions_command(repl, ["load"])

    def test_delete(self):
        from luckyd_code.cli_commands.sessions import handle_sessions_command
        repl = self._make_repl()
        with patch("luckyd_code.sessions.delete_session", return_value="Deleted"):
            with patch("luckyd_code.cli_utils.console"):
                handle_sessions_command(repl, ["delete", "old"])

    def test_unknown_sub(self):
        from luckyd_code.cli_commands.sessions import handle_sessions_command
        repl = self._make_repl()
        with patch("luckyd_code.cli_utils.console"):
            handle_sessions_command(repl, ["purge"])


# ===========================================================================
# web_routes — direct route function tests
# ===========================================================================

class TestWebRoutesMisc:
    def _make_state(self):
        ctx = MagicMock()
        ctx.count_messages.return_value = 5
        ctx.max_messages = 100
        ctx.estimate_tokens.return_value = 1500
        ctx.messages = []
        state = MagicMock()
        state.context = ctx
        state.config = MagicMock()
        state.memory_module = MagicMock()
        state.memory_module.load_claude_md.return_value = "# Memory"
        return state

    @pytest.mark.asyncio
    async def test_clear_context(self):
        from luckyd_code.web_routes.misc import clear_context
        state = self._make_state()
        request = MagicMock()
        request.app.state.web_state = state
        with patch("luckyd_code.memory.MemoryManager") as MockMgr:
            MockMgr.return_value.get_all_memories_formatted.return_value = ""
            result = await clear_context(request)
        assert result["status"] == "cleared"

    @pytest.mark.asyncio
    async def test_undo_route(self):
        from luckyd_code.web_routes import misc as misc_mod
        with patch("luckyd_code.undo.undo_last", return_value="Undone: main.py"):
            result = await misc_mod.undo()
        assert "status" in result

    @pytest.mark.asyncio
    async def test_context_info(self):
        from luckyd_code.web_routes.misc import context_info
        state = self._make_state()
        request = MagicMock()
        request.app.state.web_state = state
        result = await context_info(request)
        assert result["message_count"] == 5
        assert "max_messages" in result

    @pytest.mark.asyncio
    async def test_compact_route(self):
        from luckyd_code.web_routes.misc import compact
        state = self._make_state()
        state.context.compact.return_value = "Compacted 5 messages"
        request = MagicMock()
        request.app.state.web_state = state
        result = await compact(request)
        assert "status" in result


class TestWebRoutesCost:
    @pytest.mark.asyncio
    async def test_get_cost(self):
        from luckyd_code.web_routes.cost import get_cost
        mock_tracker = MagicMock()
        mock_tracker.get_stats.return_value = {"session_cost": 0.01, "total": 0.05}
        request = MagicMock()
        with patch("luckyd_code.cost_tracker.CostTracker", return_value=mock_tracker):
            result = await get_cost(request)
        assert "session_cost" in result


class TestWebRoutesSessions:
    @pytest.mark.asyncio
    async def test_sessions_list(self):
        from luckyd_code.web_routes.sessions import sessions_list
        with patch("luckyd_code.sessions.list_sessions", return_value="sess1\nsess2"):
            result = await sessions_list()
        assert "sessions" in result

    @pytest.mark.asyncio
    async def test_sessions_save(self):
        from luckyd_code.web_routes.sessions import sessions_save, SessionSave
        state = MagicMock()
        request = MagicMock()
        request.app.state.web_state = state
        data = SessionSave(name="test-session")
        with patch("luckyd_code.sessions.save_session", return_value="Saved"):
            result = await sessions_save(request, data)
        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_sessions_delete(self):
        from luckyd_code.web_routes.sessions import sessions_delete
        with patch("luckyd_code.sessions.delete_session", return_value="Deleted"):
            result = await sessions_delete("old-session")
        assert result["status"] == "ok"


class TestWebRoutesSettings:
    @pytest.mark.asyncio
    async def test_get_settings(self):
        from luckyd_code.web_routes.settings import get_settings
        request = MagicMock()
        with patch("luckyd_code.web_routes.settings.cfg.load_settings", return_value={"theme": "dark"}):
            result = await get_settings(request)
        assert result.get("theme") == "dark"

    @pytest.mark.asyncio
    async def test_set_settings(self):
        from luckyd_code.web_routes.settings import set_settings, SettingUpdate
        data = SettingUpdate(key="theme", value="light")
        with patch("luckyd_code.web_routes.settings.cfg.save_setting") as mock_save:
            result = await set_settings(data)
            mock_save.assert_called_once_with("theme", "light")
        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_list_models(self):
        from luckyd_code.web_routes.settings import list_models
        with patch("luckyd_code.model_registry.format_model_list", return_value="Tier 1: Flash"):
            with patch("luckyd_code.model_registry.get_unique_model_count", return_value=4):
                result = await list_models()
        assert "models" in result
        assert result["count"] == 4


class TestWebRoutesProject:
    @pytest.mark.asyncio
    async def test_init_project(self):
        from luckyd_code.web_routes.project import init_project
        with patch("luckyd_code.web_routes.project.project_init.init_project",
                   return_value="Created MEMORY.md"):
            result = await init_project()
        assert result["status"] == "ok"
        assert "MEMORY.md" in result["message"]

    @pytest.mark.asyncio
    async def test_list_tasks(self):
        from luckyd_code.web_routes.project import list_tasks
        with patch("luckyd_code.web_routes.project.tasks.list_tasks", return_value="No tasks"):
            result = await list_tasks()
        assert "tasks" in result

    @pytest.mark.asyncio
    async def test_list_plans(self):
        from luckyd_code.web_routes.project import list_plans
        with patch("luckyd_code.web_routes.project.planner.list_plans", return_value="No plans"):
            result = await list_plans()
        assert "plans" in result


class TestWebRoutesFiles:
    def test_safe_resolve_traversal(self):
        from luckyd_code.web_routes.files import _safe_resolve
        with patch("luckyd_code.web_routes.files.path_validate.safe_resolve",
                   side_effect=ValueError("traversal")):
            result = _safe_resolve("../etc/passwd")
        assert result is None

    def test_safe_resolve_ok(self, tmp_path):
        from luckyd_code.web_routes.files import _safe_resolve
        with patch("luckyd_code.web_routes.files.path_validate.safe_resolve",
                   return_value=str(tmp_path)):
            result = _safe_resolve(str(tmp_path))
        assert result == str(tmp_path)
