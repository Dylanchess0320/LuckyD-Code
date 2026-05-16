"""Coverage push #3 — targets gaps remaining after 90.88%.

Covers:
  - indexer.py: gitignore error, deep-scan edge cases, framework detection,
                Cargo.toml deps, entry-point detection, missing root
  - config.py: legacy config load, save OSError, validate errors, from_args branches
  - git/tools.py: exception branches in all git helpers
  - web_routes/misc.py: exception paths in all 4 routes
  - web_routes/sessions.py: save / load / delete routes
  - web_routes/settings.py: set_model endpoint
  - tools/project_gen.py: run() success + error paths
  - tools/dockerfile_gen.py: _collect_context + run() branches
  - tools/readme_gen.py: _collect_files + run() branches
  - sessions.py: load_session edge cases (partial match, JSON error, system prompt)
  - backup.py: _git errors, create_backup edge cases, list_backups fallback, restore_backup
  - web_routes/files.py: exception paths in list_files / read_file / write_file / edit_file
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

import pytest


# ═══════════════════════════════════════════════════════════════════════════════
# indexer.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestIndexerGitignore:
    def test_load_gitignore_read_error(self, tmp_path):
        from luckyd_code.indexer import _load_gitignore
        gi = tmp_path / ".gitignore"
        gi.write_text("*.pyc\n")
        with patch("pathlib.Path.read_text", side_effect=OSError("disk error")):
            patterns = _load_gitignore(tmp_path)
        # Should return empty list on error
        assert isinstance(patterns, list)

    def test_load_gitignore_normal(self, tmp_path):
        from luckyd_code.indexer import _load_gitignore
        gi = tmp_path / ".gitignore"
        gi.write_text("*.pyc\n# comment\n.env\n")
        patterns = _load_gitignore(tmp_path)
        assert "*.pyc" in patterns
        assert ".env" in patterns
        assert "# comment" not in patterns

    def test_is_ignored_wildcard(self):
        from luckyd_code.indexer import _is_ignored
        assert _is_ignored("foo.pyc", ["*.pyc"]) is True
        assert _is_ignored("foo.py", ["*.pyc"]) is False

    def test_is_ignored_dir(self):
        from luckyd_code.indexer import _is_ignored
        assert _is_ignored("dist", ["dist/"]) is True

    def test_is_ignored_exact(self):
        from luckyd_code.indexer import _is_ignored
        assert _is_ignored(".env", [".env"]) is True


class TestIndexerScanProject:
    def test_scan_respects_max_items(self, tmp_path):
        from luckyd_code.indexer import scan_project
        for i in range(20):
            (tmp_path / f"file{i}.py").write_text("x = 1\n")
        info = scan_project(tmp_path, max_items=5)
        assert info["total_files"] <= 5

    def test_scan_skips_ignored_dirs(self, tmp_path):
        from luckyd_code.indexer import scan_project
        node_mods = tmp_path / "node_modules"
        node_mods.mkdir()
        (node_mods / "lib.js").write_text("x = 1\n")
        (tmp_path / "app.py").write_text("x = 1\n")
        info = scan_project(tmp_path)
        tree_str = "\n".join(info["file_tree"])
        assert "node_modules" not in tree_str

    def test_scan_skips_hidden_dirs(self, tmp_path):
        from luckyd_code.indexer import scan_project
        hidden = tmp_path / ".hidden"
        hidden.mkdir()
        (hidden / "secret.py").write_text("x = 1\n")
        (tmp_path / "visible.py").write_text("x = 1\n")
        info = scan_project(tmp_path)
        tree_str = "\n".join(info["file_tree"])
        assert ".hidden" not in tree_str

    def test_scan_skips_egg_info_dirs(self, tmp_path):
        from luckyd_code.indexer import scan_project
        egg = tmp_path / "mypackage.egg-info"
        egg.mkdir()
        (egg / "PKG-INFO").write_text("Name: mypackage\n")
        (tmp_path / "app.py").write_text("x = 1\n")
        info = scan_project(tmp_path)
        tree_str = "\n".join(info["file_tree"])
        assert "egg-info" not in tree_str

    def test_scan_skips_ignored_extensions(self, tmp_path):
        from luckyd_code.indexer import scan_project
        (tmp_path / "image.png").write_bytes(b"\x89PNG")
        (tmp_path / "code.py").write_text("x = 1\n")
        info = scan_project(tmp_path)
        tree_str = "\n".join(info["file_tree"])
        assert "image.png" not in tree_str
        assert "code.py" in tree_str

    def test_scan_detects_python_language(self, tmp_path):
        from luckyd_code.indexer import scan_project
        (tmp_path / "app.py").write_text("x = 1\n")
        info = scan_project(tmp_path)
        assert "Python" in info["languages"]

    def test_scan_detects_entry_points(self, tmp_path):
        from luckyd_code.indexer import scan_project
        (tmp_path / "main.py").write_text("if __name__ == '__main__': pass\n")
        info = scan_project(tmp_path)
        assert any("main.py" in ep for ep in info["entry_points"])

    def test_scan_detects_requirements_txt_deps(self, tmp_path):
        from luckyd_code.indexer import scan_project
        (tmp_path / "requirements.txt").write_text("fastapi>=0.95\nuvicorn\n")
        (tmp_path / "app.py").write_text("from fastapi import FastAPI\n")
        info = scan_project(tmp_path)
        assert "fastapi" in info["config_files"].get("requirements.txt", []) or \
               "requirements.txt" in info["dependency_files"]

    def test_scan_detects_fastapi_framework(self, tmp_path):
        from luckyd_code.indexer import scan_project
        (tmp_path / "requirements.txt").write_text("fastapi\nuvicorn\n")
        (tmp_path / "app.py").write_text("from fastapi import FastAPI\n")
        info = scan_project(tmp_path)
        assert "FastAPI" in info["frameworks"]


class TestIndexerExtractDeps:
    def test_extract_package_json(self, tmp_path):
        from luckyd_code.indexer import _extract_deps
        f = tmp_path / "package.json"
        f.write_text(json.dumps({
            "dependencies": {"react": "^18.0.0", "axios": "^1.0.0"},
            "devDependencies": {"jest": "^29.0.0"}
        }))
        deps = _extract_deps(f, "package.json")
        assert "react" in deps
        assert "axios" in deps
        assert "jest" in deps

    def test_extract_cargo_toml(self, tmp_path):
        from luckyd_code.indexer import _extract_deps
        f = tmp_path / "Cargo.toml"
        f.write_text("[dependencies]\nserde = \"1.0\"\ntokio = \"1.0\"\n")
        deps = _extract_deps(f, "Cargo.toml")
        assert "serde" in deps
        assert "tokio" in deps

    def test_extract_requirements_txt(self, tmp_path):
        from luckyd_code.indexer import _extract_deps
        f = tmp_path / "requirements.txt"
        f.write_text("django>=4.0\n# comment\npsycopg2==2.9\n")
        deps = _extract_deps(f, "requirements.txt")
        assert "django" in deps
        assert "psycopg2" in deps

    def test_extract_returns_empty_on_error(self, tmp_path):
        from luckyd_code.indexer import _extract_deps
        f = tmp_path / "package.json"
        f.write_text("not json")
        deps = _extract_deps(f, "package.json")
        assert deps == []

    def test_extract_unknown_file_returns_empty(self, tmp_path):
        from luckyd_code.indexer import _extract_deps
        f = tmp_path / "unknown.txt"
        f.write_text("x = 1")
        deps = _extract_deps(f, "unknown.txt")
        assert deps == []


class TestIndexerDetectFrameworks:
    def test_detects_react(self):
        from luckyd_code.indexer import _detect_frameworks
        result = _detect_frameworks({"package.json": ["react"]}, ["package.json"])
        assert "React/Next.js" in result

    def test_detects_vue(self):
        from luckyd_code.indexer import _detect_frameworks
        result = _detect_frameworks({"package.json": ["vue"]}, ["package.json"])
        assert "Vue" in result

    def test_detects_tailwind(self):
        from luckyd_code.indexer import _detect_frameworks
        result = _detect_frameworks({"package.json": ["tailwindcss"]}, ["package.json"])
        assert "Tailwind CSS" in result

    def test_detects_django(self):
        from luckyd_code.indexer import _detect_frameworks
        result = _detect_frameworks({"requirements.txt": ["django"]}, ["requirements.txt"])
        assert "Django" in result

    def test_detects_flask(self):
        from luckyd_code.indexer import _detect_frameworks
        result = _detect_frameworks({"requirements.txt": ["flask"]}, ["requirements.txt"])
        assert "Flask" in result

    def test_detects_express(self):
        from luckyd_code.indexer import _detect_frameworks
        result = _detect_frameworks({"package.json": ["express"]}, ["package.json"])
        assert "Express/NestJS" in result


class TestIndexProject:
    def test_index_project_missing_root(self, tmp_path):
        from luckyd_code.indexer import index_project
        result = index_project(str(tmp_path / "nonexistent"))
        assert result == ""

    def test_index_project_with_dir(self, tmp_path):
        from luckyd_code.indexer import index_project
        (tmp_path / "app.py").write_text("x = 1\n")
        result = index_project(str(tmp_path))
        assert isinstance(result, str)
        assert "Project" in result or "app.py" in result

    def test_index_project_default_cwd(self, tmp_path, monkeypatch):
        from luckyd_code.indexer import index_project
        monkeypatch.chdir(tmp_path)
        (tmp_path / "main.py").write_text("x = 1\n")
        result = index_project()
        assert isinstance(result, str)


# ═══════════════════════════════════════════════════════════════════════════════
# config.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestConfigLoad:
    def test_load_legacy_config_fallback(self, tmp_path, monkeypatch):
        from luckyd_code import config as cfg_module
        # Primary doesn't exist but legacy does
        legacy = tmp_path / "legacy_config.json"
        legacy.write_text(json.dumps({"model": "deepseek-v4-pro"}))
        monkeypatch.setattr(cfg_module, "CONFIG_FILE", tmp_path / "nonexistent.json")
        monkeypatch.setattr(cfg_module, "_LEGACY_CONFIG_FILE", legacy)
        result = cfg_module.load_config_file()
        assert result.get("model") == "deepseek-v4-pro"

    def test_load_config_json_decode_error(self, tmp_path, monkeypatch):
        from luckyd_code import config as cfg_module
        bad = tmp_path / "bad.json"
        bad.write_text("not json")
        monkeypatch.setattr(cfg_module, "CONFIG_FILE", bad)
        monkeypatch.setattr(cfg_module, "_LEGACY_CONFIG_FILE", tmp_path / "nonexistent.json")
        result = cfg_module.load_config_file()
        assert result == {}

    def test_save_config_oserror(self, tmp_path, monkeypatch):
        from luckyd_code import config as cfg_module
        monkeypatch.setattr(cfg_module, "CONFIG_FILE", tmp_path / "cfg.json")
        with patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
            # Should not raise
            cfg_module.save_config_file({"model": "test"})


class TestConfigValidate:
    def test_invalid_provider_raises(self, monkeypatch):
        from luckyd_code.config import Config
        with patch("luckyd_code.config.load_config_file", return_value={}):
            with patch.object(Config, "_resolve_api_key", return_value="sk-test"):
                cfg = Config.__new__(Config)
                cfg.provider = "badprovider"
                cfg.api_key = "sk-test"
                cfg.base_url = "https://api.test.com/v1"
                cfg.max_tokens = 4096
                cfg.temperature = 0.3
                cfg.max_context_messages = 40
                with pytest.raises(ValueError, match="provider"):
                    cfg.validate()

    def test_missing_api_key_raises(self):
        from luckyd_code.config import Config
        with patch("luckyd_code.config.load_config_file", return_value={}):
            with patch.object(Config, "_resolve_api_key", return_value=""):
                cfg = Config.__new__(Config)
                cfg.provider = "deepseek"
                cfg.api_key = ""
                cfg.base_url = "https://api.deepseek.com/v1"
                cfg.max_tokens = 4096
                cfg.temperature = 0.3
                cfg.max_context_messages = 40
                with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
                    cfg.validate()

    def test_bad_base_url_raises(self):
        from luckyd_code.config import Config
        cfg = Config.__new__(Config)
        cfg.provider = "deepseek"
        cfg.api_key = "sk-test"
        cfg.base_url = "ftp://bad"
        cfg.max_tokens = 4096
        cfg.temperature = 0.3
        cfg.max_context_messages = 40
        with pytest.raises(ValueError, match="base_url"):
            cfg.validate()

    def test_bad_max_tokens_raises(self):
        from luckyd_code.config import Config
        cfg = Config.__new__(Config)
        cfg.provider = "deepseek"
        cfg.api_key = "sk-test"
        cfg.base_url = "https://api.deepseek.com/v1"
        cfg.max_tokens = 0
        cfg.temperature = 0.3
        cfg.max_context_messages = 40
        with pytest.raises(ValueError, match="max_tokens"):
            cfg.validate()

    def test_bad_temperature_raises(self):
        from luckyd_code.config import Config
        cfg = Config.__new__(Config)
        cfg.provider = "deepseek"
        cfg.api_key = "sk-test"
        cfg.base_url = "https://api.deepseek.com/v1"
        cfg.max_tokens = 4096
        cfg.temperature = 5.0
        cfg.max_context_messages = 40
        with pytest.raises(ValueError, match="temperature"):
            cfg.validate()


class TestConfigFromArgs:
    def test_from_args_sets_model(self):
        from luckyd_code.config import Config
        args = MagicMock()
        args.model = "deepseek-v4-pro"
        args.temperature = None
        args.system_prompt = None
        args.dir = None
        args.provider = None
        with patch("luckyd_code.config.load_config_file", return_value={}):
            with patch.object(Config, "_resolve_api_key", return_value="sk-test"):
                cfg = Config.from_args(args)
        assert cfg.model == "deepseek-v4-pro"

    def test_from_args_sets_provider_and_base_url(self):
        from luckyd_code.config import Config
        args = MagicMock()
        args.model = None
        args.temperature = None
        args.system_prompt = None
        args.dir = None
        args.provider = "groq"
        with patch("luckyd_code.config.load_config_file", return_value={}):
            with patch.object(Config, "_resolve_api_key", return_value="sk-test"):
                cfg = Config.from_args(args)
        assert cfg.provider == "groq"
        assert "groq" in cfg.base_url

    def test_from_args_no_args(self):
        from luckyd_code.config import Config
        with patch("luckyd_code.config.load_config_file", return_value={}):
            with patch.object(Config, "_resolve_api_key", return_value="sk-test"):
                cfg = Config.from_args(None)
        assert cfg.provider == "deepseek"


# ═══════════════════════════════════════════════════════════════════════════════
# git/tools.py — exception branches
# ═══════════════════════════════════════════════════════════════════════════════

class TestGitTools:
    def test_git_status_exception(self):
        from luckyd_code.git.tools import git_status
        with patch("subprocess.run", side_effect=Exception("no git")):
            result = git_status()
        assert "Error" in result

    def test_git_diff_exception(self):
        from luckyd_code.git.tools import git_diff
        with patch("subprocess.run", side_effect=Exception("no git")):
            result = git_diff()
        assert "Error" in result

    def test_git_diff_staged_no_changes(self):
        from luckyd_code.git.tools import git_diff
        mock = MagicMock(returncode=0, stdout="", stderr="")
        with patch("subprocess.run", return_value=mock):
            result = git_diff(staged=True)
        assert result == "No changes"

    def test_git_log_exception(self):
        from luckyd_code.git.tools import git_log
        with patch("subprocess.run", side_effect=Exception("no git")):
            result = git_log()
        assert "Error" in result

    def test_git_commit_exception(self):
        from luckyd_code.git.tools import git_commit
        with patch("subprocess.run", side_effect=Exception("no git")):
            result = git_commit("test commit")
        assert "Error" in result

    def test_git_add_exception(self):
        from luckyd_code.git.tools import git_add
        with patch("subprocess.run", side_effect=Exception("no git")):
            result = git_add(["/tmp/f.py"])
        assert "Error" in result

    def test_git_add_all_success(self):
        from luckyd_code.git.tools import git_add
        mock = MagicMock(returncode=0, stdout="", stderr="")
        with patch("subprocess.run", return_value=mock):
            result = git_add()
        assert result == "Staged"

    def test_git_branch_exception(self):
        from luckyd_code.git.tools import git_branch
        with patch("subprocess.run", side_effect=Exception("no git")):
            result = git_branch()
        assert "Error" in result

    def test_git_create_pr_exception(self):
        from luckyd_code.git.tools import git_create_pr
        with patch("subprocess.run", side_effect=Exception("no gh cli")):
            result = git_create_pr("fix: something")
        assert "Error" in result

    def test_git_push_exception(self):
        from luckyd_code.git.tools import git_push
        with patch("subprocess.run", side_effect=Exception("no git")):
            result = git_push("main")
        assert "Error" in result


# ═══════════════════════════════════════════════════════════════════════════════
# web_routes/misc.py — exception paths
# ═══════════════════════════════════════════════════════════════════════════════

class TestWebRoutesMisc:
    def _make_request(self, **state_attrs):
        req = MagicMock()
        for k, v in state_attrs.items():
            setattr(req.app.state.web_state, k, v)
        return req

    @pytest.mark.asyncio
    async def test_clear_context_success(self):
        from luckyd_code.web_routes.misc import clear_context
        ctx = MagicMock()
        ctx.messages = []
        ctx.reset = MagicMock()
        mem = MagicMock()
        mem.load_claude_md.return_value = ""
        req = MagicMock()
        req.app.state.web_state.context = ctx
        req.app.state.web_state.memory_module = mem
        with patch("luckyd_code.memory.MemoryManager") as MockMgr:
            MockMgr.return_value.get_all_memories_formatted.return_value = ""
            result = await clear_context(req)
        assert result == {"status": "cleared"}

    @pytest.mark.asyncio
    async def test_clear_context_with_memories(self):
        from luckyd_code.web_routes.misc import clear_context
        ctx = MagicMock()
        ctx.messages = []
        ctx.reset = MagicMock()
        mem = MagicMock()
        mem.load_claude_md.return_value = "some md"
        req = MagicMock()
        req.app.state.web_state.context = ctx
        req.app.state.web_state.memory_module = mem
        with patch("luckyd_code.memory.MemoryManager") as MockMgr:
            MockMgr.return_value.get_all_memories_formatted.return_value = "session memories"
            result = await clear_context(req)
        assert result == {"status": "cleared"}

    @pytest.mark.asyncio
    async def test_clear_context_exception(self):
        from luckyd_code.web_routes.misc import clear_context
        req = MagicMock()
        req.app.state.web_state.context.reset.side_effect = Exception("boom")
        result = await clear_context(req)
        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_undo_success(self):
        from luckyd_code.web_routes.misc import undo
        with patch("luckyd_code.undo.undo_last", return_value="Undone"):
            result = await undo()
        assert result == {"status": "Undone"}

    @pytest.mark.asyncio
    async def test_undo_exception(self):
        from luckyd_code.web_routes.misc import undo
        with patch("luckyd_code.undo.undo_last", side_effect=Exception("fail")):
            result = await undo()
        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_compact_success(self):
        from luckyd_code.web_routes.misc import compact
        req = MagicMock()
        req.app.state.web_state.context.compact.return_value = "Compacted"
        result = await compact(req)
        assert result == {"status": "Compacted"}

    @pytest.mark.asyncio
    async def test_compact_exception(self):
        from luckyd_code.web_routes.misc import compact
        req = MagicMock()
        req.app.state.web_state.context.compact.side_effect = Exception("fail")
        result = await compact(req)
        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_context_info_success(self):
        from luckyd_code.web_routes.misc import context_info
        req = MagicMock()
        req.app.state.web_state.context.count_messages.return_value = 5
        req.app.state.web_state.context.max_messages = 40
        req.app.state.web_state.context.estimate_tokens.return_value = 1000
        result = await context_info(req)
        assert result["message_count"] == 5
        assert result["max_messages"] == 40
        assert result["estimated_tokens"] == 1000

    @pytest.mark.asyncio
    async def test_context_info_exception(self):
        from luckyd_code.web_routes.misc import context_info
        req = MagicMock()
        req.app.state.web_state.context.count_messages.side_effect = Exception("fail")
        result = await context_info(req)
        assert result.status_code == 500


# ═══════════════════════════════════════════════════════════════════════════════
# web_routes/sessions.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestWebRoutesSessions:
    @pytest.mark.asyncio
    async def test_sessions_list(self):
        from luckyd_code.web_routes.sessions import sessions_list
        with patch("luckyd_code.sessions.list_sessions", return_value="session1\nsession2"):
            result = await sessions_list()
        assert "sessions" in result

    @pytest.mark.asyncio
    async def test_sessions_save(self):
        from luckyd_code.web_routes.sessions import sessions_save, SessionSave
        req = MagicMock()
        req.app.state.web_state.context = MagicMock()
        with patch("luckyd_code.sessions.save_session", return_value="Saved ok"):
            result = await sessions_save(req, SessionSave(name="my-session"))
        assert result["status"] == "ok"
        assert "Saved" in result["message"]

    @pytest.mark.asyncio
    async def test_sessions_load(self):
        from luckyd_code.web_routes.sessions import sessions_load, SessionLoad
        req = MagicMock()
        req.app.state.web_state.context = MagicMock()
        with patch("luckyd_code.sessions.load_session", return_value="Loaded ok"):
            result = await sessions_load(req, SessionLoad(name="my-session"))
        assert result["status"] == "ok"
        assert "Loaded" in result["message"]

    @pytest.mark.asyncio
    async def test_sessions_delete(self):
        from luckyd_code.web_routes.sessions import sessions_delete
        with patch("luckyd_code.sessions.delete_session", return_value="Deleted"):
            result = await sessions_delete("my-session")
        assert result["status"] == "ok"
        assert "Deleted" in result["message"]


# ═══════════════════════════════════════════════════════════════════════════════
# web_routes/settings.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestWebRoutesSettings:
    @pytest.mark.asyncio
    async def test_get_settings(self):
        from luckyd_code.web_routes.settings import get_settings
        req = MagicMock()
        with patch("luckyd_code.web_routes.settings.cfg.load_settings", return_value={"theme": "dark"}):
            result = await get_settings(req)
        assert result == {"theme": "dark"}

    @pytest.mark.asyncio
    async def test_set_settings(self):
        from luckyd_code.web_routes.settings import set_settings, SettingUpdate
        with patch("luckyd_code.web_routes.settings.cfg.save_setting"):
            result = await set_settings(SettingUpdate(key="theme", value="dark"))
        assert result["status"] == "ok"
        assert result["key"] == "theme"

    @pytest.mark.asyncio
    async def test_list_models(self):
        from luckyd_code.web_routes.settings import list_models
        with patch("luckyd_code.model_registry.format_model_list", return_value="Flash | Pro"):
            with patch("luckyd_code.model_registry.get_unique_model_count", return_value=2):
                result = await list_models()
        assert "models" in result
        assert result["count"] == 2

    @pytest.mark.asyncio
    async def test_set_model(self):
        from luckyd_code.web_routes.settings import set_model, ModelSet
        mock_cfg = MagicMock()
        with patch("luckyd_code.config.Config", return_value=mock_cfg):
            result = await set_model(ModelSet(model="deepseek-v4-pro"))
        assert result["status"] == "ok"
        assert result["model"] == "deepseek-v4-pro"
        mock_cfg.save.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════════
# tools/project_gen.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestProjectGenRun:
    def _tool(self):
        from luckyd_code.tools.project_gen import ProjectGenTool
        return ProjectGenTool()

    def test_bad_output_dir_returns_error(self, tmp_path):
        tool = self._tool()
        # Use a file as output_dir so mkdir fails
        f = tmp_path / "afile.txt"
        f.write_text("x")
        with patch("pathlib.Path.mkdir", side_effect=OSError("is a file")):
            result = tool.run("a test app", output_dir=str(f))
        assert "Error" in result

    def test_model_invalid_json_returns_error(self, tmp_path):
        tool = self._tool()
        with patch.object(tool, "_call_model_direct", return_value="NOT JSON"):
            result = tool.run("a test app", output_dir=str(tmp_path))
        assert "Error" in result and "JSON" in result

    def test_model_exception_returns_error(self, tmp_path):
        tool = self._tool()
        with patch.object(tool, "_call_model_direct", side_effect=Exception("api down")):
            result = tool.run("a test app", output_dir=str(tmp_path))
        assert "Error" in result

    def test_no_files_in_scaffold_returns_error(self, tmp_path):
        tool = self._tool()
        scaffold = {"project_name": "test", "files": [], "stack": "Python"}
        with patch.object(tool, "_call_model_direct", return_value=json.dumps(scaffold)):
            result = tool.run("a test app", output_dir=str(tmp_path))
        assert "Error" in result and "files" in result.lower()

    def test_successful_scaffold_creates_files(self, tmp_path):
        tool = self._tool()
        scaffold = {
            "project_name": "myapp",
            "description": "A test app",
            "stack": "Python/FastAPI",
            "files": [
                {"path": "main.py", "content": "# main\n"},
                {"path": "README.md", "content": "# MyApp\n"},
            ],
            "install": "pip install -r requirements.txt",
            "run": "python main.py",
            "notes": "Great app!",
        }
        with patch.object(tool, "_call_model_direct", return_value=json.dumps(scaffold)):
            result = tool.run("a test app", output_dir=str(tmp_path))
        assert "myapp" in result
        assert "2 written" in result
        assert (tmp_path / "myapp" / "main.py").exists()

    def test_file_write_error_reported(self, tmp_path):
        tool = self._tool()
        scaffold = {
            "project_name": "myapp",
            "files": [{"path": "main.py", "content": "x = 1"}],
            "stack": "Python",
            "install": "",
            "run": "",
        }
        with patch.object(tool, "_call_model_direct", return_value=json.dumps(scaffold)):
            with patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
                result = tool.run("a test app", output_dir=str(tmp_path))
        assert "Error" in result or "Errors" in result

    def test_scaffold_with_fences_stripped(self, tmp_path):
        tool = self._tool()
        scaffold = {
            "project_name": "myapp",
            "files": [{"path": "app.py", "content": "x = 1"}],
            "stack": "Python",
            "install": "pip install fastapi",
            "run": "python app.py",
        }
        raw = f"```json\n{json.dumps(scaffold)}\n```"
        with patch.object(tool, "_call_model_direct", return_value=raw):
            result = tool.run("a test app", output_dir=str(tmp_path))
        assert "myapp" in result


# ═══════════════════════════════════════════════════════════════════════════════
# tools/dockerfile_gen.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestDockerfileGenCollectContext:
    def test_collects_priority_files(self, tmp_path):
        from luckyd_code.tools.dockerfile_gen import _collect_context
        (tmp_path / "requirements.txt").write_text("fastapi\n")
        (tmp_path / "main.py").write_text("from fastapi import FastAPI\n")
        ctx = _collect_context(tmp_path)
        assert "requirements.txt" in ctx
        assert "main.py" in ctx

    def test_skips_skip_dirs(self, tmp_path):
        from luckyd_code.tools.dockerfile_gen import _collect_context
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "pkg.js").write_text("x = 1")
        (tmp_path / "app.py").write_text("x = 1")
        ctx = _collect_context(tmp_path)
        assert "node_modules" not in ctx

    def test_returns_empty_for_empty_dir(self, tmp_path):
        from luckyd_code.tools.dockerfile_gen import _collect_context
        ctx = _collect_context(tmp_path)
        assert ctx == ""


class TestDockerfileGenRun:
    def _tool(self):
        from luckyd_code.tools.dockerfile_gen import DockerfileGenTool
        return DockerfileGenTool()

    def test_not_a_dir_returns_error(self, tmp_path):
        tool = self._tool()
        f = tmp_path / "file.txt"
        f.write_text("x")
        result = tool.run(project_dir=str(f))
        assert "Error" in result and "directory" in result.lower()

    def test_no_source_files_returns_error(self, tmp_path):
        tool = self._tool()
        result = tool.run(project_dir=str(tmp_path))
        assert "Error" in result

    def test_existing_dockerfile_no_overwrite(self, tmp_path):
        tool = self._tool()
        (tmp_path / "Dockerfile").write_text("FROM python:3.12-slim\n")
        (tmp_path / "requirements.txt").write_text("fastapi\n")
        result = tool.run(project_dir=str(tmp_path), overwrite=False)
        assert "already exists" in result

    def test_model_invalid_json(self, tmp_path):
        tool = self._tool()
        (tmp_path / "requirements.txt").write_text("fastapi\n")
        with patch.object(tool, "_call_model_direct", return_value="NOT JSON"):
            result = tool.run(project_dir=str(tmp_path))
        assert "Error" in result and "JSON" in result

    def test_model_exception(self, tmp_path):
        tool = self._tool()
        (tmp_path / "requirements.txt").write_text("fastapi\n")
        with patch.object(tool, "_call_model_direct", side_effect=Exception("api down")):
            result = tool.run(project_dir=str(tmp_path))
        assert "Error" in result

    def test_successful_generation(self, tmp_path):
        tool = self._tool()
        (tmp_path / "requirements.txt").write_text("fastapi\n")
        response = json.dumps({
            "dockerfile": "FROM python:3.12-slim\nRUN pip install fastapi\n",
            "compose": "",
            "notes": "Exposes port 8000",
        })
        with patch.object(tool, "_call_model_direct", return_value=response):
            result = tool.run(project_dir=str(tmp_path), overwrite=True)
        assert "Generated" in result
        assert (tmp_path / "Dockerfile").exists()

    def test_generates_compose_file(self, tmp_path):
        tool = self._tool()
        (tmp_path / "requirements.txt").write_text("fastapi\n")
        response = json.dumps({
            "dockerfile": "FROM python:3.12-slim\n",
            "compose": "version: '3'\nservices:\n  app:\n    build: .\n",
            "notes": "",
        })
        with patch.object(tool, "_call_model_direct", return_value=response):
            result = tool.run(project_dir=str(tmp_path), overwrite=True)
        assert (tmp_path / "docker-compose.yml").exists()

    def test_dockerfile_write_error(self, tmp_path):
        tool = self._tool()
        (tmp_path / "requirements.txt").write_text("fastapi\n")
        response = json.dumps({
            "dockerfile": "FROM python:3.12-slim\n",
            "compose": "",
            "notes": "",
        })
        with patch.object(tool, "_call_model_direct", return_value=response):
            with patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
                result = tool.run(project_dir=str(tmp_path), overwrite=True)
        assert "Error" in result


# ═══════════════════════════════════════════════════════════════════════════════
# tools/readme_gen.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestReadmeGenCollectFiles:
    def test_collects_priority_files_first(self, tmp_path):
        from luckyd_code.tools.readme_gen import _collect_files
        (tmp_path / "main.py").write_text("x = 1\n")
        (tmp_path / "requirements.txt").write_text("fastapi\n")
        files = _collect_files(tmp_path)
        names = [f[0] for f in files]
        assert any("main.py" in n for n in names)

    def test_skips_hidden_files(self, tmp_path):
        from luckyd_code.tools.readme_gen import _collect_files
        (tmp_path / ".hidden").write_text("secret")
        (tmp_path / "app.py").write_text("x = 1")
        files = _collect_files(tmp_path)
        names = [f[0] for f in files]
        assert not any(".hidden" in n for n in names)

    def test_env_example_included(self, tmp_path):
        from luckyd_code.tools.readme_gen import _collect_files
        (tmp_path / ".env.example").write_text("API_KEY=\n")
        files = _collect_files(tmp_path)
        names = [f[0] for f in files]
        assert any(".env.example" in n for n in names)

    def test_long_file_truncated(self, tmp_path):
        from luckyd_code.tools.readme_gen import _collect_files
        # Use a non-priority filename so it goes through _walk (which adds the truncation marker)
        (tmp_path / "bigmodule.py").write_text("x = 1\n" * 1000)
        files = _collect_files(tmp_path)
        content = next((c for n, c in files if "bigmodule.py" in n), "")
        assert "truncated" in content


class TestReadmeGenRun:
    def _tool(self):
        from luckyd_code.tools.readme_gen import ReadmeGenTool
        return ReadmeGenTool()

    def test_not_a_dir_returns_error(self, tmp_path):
        tool = self._tool()
        f = tmp_path / "file.txt"
        f.write_text("x")
        result = tool.run(project_dir=str(f))
        assert "Error" in result

    def test_no_files_returns_error(self, tmp_path):
        tool = self._tool()
        result = tool.run(project_dir=str(tmp_path))
        assert "Error" in result

    def test_existing_readme_no_overwrite(self, tmp_path):
        tool = self._tool()
        (tmp_path / "README.md").write_text("# Existing\n")
        (tmp_path / "main.py").write_text("x = 1")
        result = tool.run(project_dir=str(tmp_path), overwrite=False)
        assert "already exists" in result

    def test_model_exception_returns_error(self, tmp_path):
        tool = self._tool()
        (tmp_path / "main.py").write_text("x = 1")
        with patch.object(tool, "_call_model_direct", side_effect=Exception("api down")):
            result = tool.run(project_dir=str(tmp_path), overwrite=True)
        assert "Error" in result

    def test_successful_generation(self, tmp_path):
        tool = self._tool()
        (tmp_path / "main.py").write_text("x = 1")
        readme_content = "# My App\n\nA great app.\n"
        with patch.object(tool, "_call_model_direct", return_value=readme_content):
            result = tool.run(project_dir=str(tmp_path), overwrite=True)
        assert "Written to" in result
        assert (tmp_path / "README.md").exists()

    def test_readme_fence_stripped(self, tmp_path):
        tool = self._tool()
        (tmp_path / "main.py").write_text("x = 1")
        fenced = "```markdown\n# My App\n\nContent here.\n```"
        with patch.object(tool, "_call_model_direct", return_value=fenced):
            result = tool.run(project_dir=str(tmp_path), overwrite=True)
        content = (tmp_path / "README.md").read_text()
        assert "```" not in content

    def test_custom_output_path(self, tmp_path):
        tool = self._tool()
        (tmp_path / "main.py").write_text("x = 1")
        out = tmp_path / "docs" / "README.md"
        out.parent.mkdir(parents=True, exist_ok=True)  # source doesn't create parents
        with patch.object(tool, "_call_model_direct", return_value="# Docs\n"):
            result = tool.run(
                project_dir=str(tmp_path),
                output_path=str(out),
                overwrite=True,
            )
        assert out.exists()

    def test_write_error_returns_error(self, tmp_path):
        tool = self._tool()
        (tmp_path / "main.py").write_text("x = 1")
        with patch.object(tool, "_call_model_direct", return_value="# README\n"):
            with patch("pathlib.Path.write_text", side_effect=OSError("no space")):
                result = tool.run(project_dir=str(tmp_path), overwrite=True)
        assert "Error" in result


# ═══════════════════════════════════════════════════════════════════════════════
# sessions.py — load_session edge cases
# ═══════════════════════════════════════════════════════════════════════════════

class TestSessionsLoadEdgeCases:
    def test_load_session_partial_match(self, tmp_path, monkeypatch):
        from luckyd_code import sessions
        monkeypatch.setattr(sessions, "SESSIONS_DIR", tmp_path)
        # Save under "my-session" but load with "my" (partial)
        data = {
            "name": "my-session",
            "saved_at": "2024-01-01T00:00:00",
            "message_count": 1,
            "messages": [{"role": "user", "content": "hello"}],
        }
        (tmp_path / "my-session.json").write_text(json.dumps(data))
        ctx = MagicMock()
        ctx.messages = [{"role": "system", "content": "sys"}]
        ctx.max_messages = 40
        result = sessions.load_session("my", ctx)
        assert "loaded" in result.lower() or "my-session" in result

    def test_load_session_json_decode_error(self, tmp_path, monkeypatch):
        from luckyd_code import sessions
        monkeypatch.setattr(sessions, "SESSIONS_DIR", tmp_path)
        (tmp_path / "bad-session.json").write_text("NOT JSON")
        ctx = MagicMock()
        result = sessions.load_session("bad-session", ctx)
        assert "Error" in result

    def test_load_session_empty_messages(self, tmp_path, monkeypatch):
        from luckyd_code import sessions
        monkeypatch.setattr(sessions, "SESSIONS_DIR", tmp_path)
        data = {
            "name": "empty",
            "saved_at": "2024-01-01",
            "message_count": 0,
            "messages": [],
        }
        (tmp_path / "empty.json").write_text(json.dumps(data))
        ctx = MagicMock()
        result = sessions.load_session("empty", ctx)
        assert "empty" in result.lower()

    def test_load_session_preserves_system_prompt(self, tmp_path, monkeypatch):
        from luckyd_code import sessions
        monkeypatch.setattr(sessions, "SESSIONS_DIR", tmp_path)
        data = {
            "name": "test",
            "messages": [{"role": "user", "content": "hello"}],
        }
        (tmp_path / "test.json").write_text(json.dumps(data))
        ctx = MagicMock()
        ctx.messages = [{"role": "system", "content": "You are helpful"}]
        ctx.max_messages = 40
        sessions.load_session("test", ctx)
        # Should prepend system message since it's not in session
        assert ctx.messages[0] == {"role": "system", "content": "You are helpful"}

    def test_load_session_with_system_in_messages(self, tmp_path, monkeypatch):
        from luckyd_code import sessions
        monkeypatch.setattr(sessions, "SESSIONS_DIR", tmp_path)
        data = {
            "name": "test2",
            "messages": [
                {"role": "system", "content": "Saved system"},
                {"role": "user", "content": "hi"},
            ],
        }
        (tmp_path / "test2.json").write_text(json.dumps(data))
        ctx = MagicMock()
        ctx.messages = [{"role": "system", "content": "Live system"}]
        ctx.max_messages = 40
        result = sessions.load_session("test2", ctx)
        assert "loaded" in result.lower() or "test2" in result

    def test_load_session_trims_over_max(self, tmp_path, monkeypatch):
        from luckyd_code import sessions
        monkeypatch.setattr(sessions, "SESSIONS_DIR", tmp_path)
        messages = [{"role": "user", "content": f"msg{i}"} for i in range(50)]
        data = {"name": "big", "messages": messages}
        (tmp_path / "big.json").write_text(json.dumps(data))
        ctx = MagicMock()
        ctx.messages = []
        ctx.max_messages = 10
        sessions.load_session("big", ctx)
        # After load, context.messages is a real list trimmed to max_messages
        assert len(ctx.messages) <= 10


# ═══════════════════════════════════════════════════════════════════════════════
# backup.py — error paths
# ═══════════════════════════════════════════════════════════════════════════════

class TestBackupGit:
    def test_git_file_not_found(self):
        from luckyd_code.backup import _git
        with patch("subprocess.run", side_effect=FileNotFoundError):
            code, out, err = _git("status")
        assert code == 1
        assert "not found" in err.lower() or "git" in err.lower()

    def test_git_generic_exception(self):
        from luckyd_code.backup import _git
        with patch("subprocess.run", side_effect=Exception("oops")):
            code, out, err = _git("status")
        assert code == 1
        assert "oops" in err


class TestBackupIsGitRepo:
    def test_is_git_repo_true(self):
        from luckyd_code.backup import _is_git_repo
        with patch("luckyd_code.backup._git", return_value=(0, "", "")):
            assert _is_git_repo() is True

    def test_is_git_repo_false(self):
        from luckyd_code.backup import _is_git_repo
        with patch("luckyd_code.backup._git", return_value=(1, "", "not a git repo")):
            assert _is_git_repo() is False


class TestBackupHasChanges:
    def test_has_changes_true(self):
        from luckyd_code.backup import _has_changes
        with patch("luckyd_code.backup._git", return_value=(0, "M file.py", "")):
            assert _has_changes() is True

    def test_has_changes_false(self):
        from luckyd_code.backup import _has_changes
        with patch("luckyd_code.backup._git", return_value=(0, "", "")):
            assert _has_changes() is False


class TestCreateBackup:
    def test_not_git_repo_returns_error(self):
        from luckyd_code.backup import create_backup
        with patch("luckyd_code.backup._is_git_repo", return_value=False):
            result = create_backup()
        assert not result["ok"]
        assert "git" in result["error"].lower()

    def test_no_changes_returns_ok_with_head(self):
        from luckyd_code.backup import create_backup
        with patch("luckyd_code.backup._is_git_repo", return_value=True):
            with patch("luckyd_code.backup._has_changes", return_value=False):
                with patch("luckyd_code.backup._short_hash", return_value="abc1234"):
                    result = create_backup()
        assert result["ok"] is True
        assert "abc1234" in result["hash"]

    def test_git_add_fails_returns_error(self):
        from luckyd_code.backup import create_backup
        with patch("luckyd_code.backup._is_git_repo", return_value=True):
            with patch("luckyd_code.backup._has_changes", return_value=True):
                with patch("luckyd_code.backup._git", return_value=(1, "", "add failed")):
                    result = create_backup()
        assert not result["ok"]
        assert "add" in result["error"].lower()

    def test_git_commit_fails_returns_error(self):
        from luckyd_code.backup import create_backup
        call_count = [0]
        def mock_git(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:  # git add
                return (0, "", "")
            return (1, "", "commit failed")  # git commit
        with patch("luckyd_code.backup._is_git_repo", return_value=True):
            with patch("luckyd_code.backup._has_changes", return_value=True):
                with patch("luckyd_code.backup._git", side_effect=mock_git):
                    result = create_backup("my backup")
        assert not result["ok"]
        assert "commit" in result["error"].lower()

    def test_successful_backup(self):
        from luckyd_code.backup import create_backup
        call_count = [0]
        def mock_git(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] <= 2:
                return (0, "ok", "")
            return (0, "", "")  # tag
        with patch("luckyd_code.backup._is_git_repo", return_value=True):
            with patch("luckyd_code.backup._has_changes", return_value=True):
                with patch("luckyd_code.backup._git", side_effect=mock_git):
                    with patch("luckyd_code.backup._short_hash", return_value="abc1234"):
                        result = create_backup("snapshot")
        assert result["ok"] is True
        assert "abc1234" in result["hash"]


class TestListBackups:
    def test_list_uses_fallback_when_no_tags(self):
        from luckyd_code.backup import list_backups
        def mock_git(*args, **kwargs):
            args_list = list(args)
            if "tag" in args_list:
                return (0, "", "")  # no tags
            if "log" in args_list:
                return (0, "abc1234|2024-01-01|[dsc-backup] snapshot (2024-01-01)", "")
            return (0, "", "")
        with patch("luckyd_code.backup._git", side_effect=mock_git):
            result = list_backups()
        assert len(result) == 1
        assert result[0]["hash"] == "abc1234"

    def test_list_with_tags(self):
        from luckyd_code.backup import list_backups
        tag_line = "dsc-backup/20240101_120000|abc1234|2024-01-01"
        with patch("luckyd_code.backup._git", return_value=(0, tag_line, "")):
            result = list_backups()
        assert len(result) == 1
        assert result[0]["hash"] == "abc1234"

    def test_format_backup_list_empty(self):
        from luckyd_code.backup import format_backup_list
        result = format_backup_list([])
        assert "No backups" in result

    def test_format_backup_list_with_entries(self):
        from luckyd_code.backup import format_backup_list
        backups = [{"n": 1, "hash": "abc1234", "tag": "dsc-backup/20240101", "date": "2024-01-01", "subject": "snapshot"}]
        result = format_backup_list(backups)
        assert "abc1234" in result
        assert "#1" in result


class TestRestoreBackup:
    def test_not_git_repo_returns_error(self):
        from luckyd_code.backup import restore_backup
        with patch("luckyd_code.backup._is_git_repo", return_value=False):
            result = restore_backup("abc1234")
        assert not result["ok"]

    def test_numeric_ref_not_found(self):
        from luckyd_code.backup import restore_backup
        with patch("luckyd_code.backup._is_git_repo", return_value=True):
            with patch("luckyd_code.backup.list_backups", return_value=[]):
                result = restore_backup("5")
        assert not result["ok"]
        assert "No backup" in result["error"]

    def test_checkout_fails_returns_error(self):
        from luckyd_code.backup import restore_backup
        def mock_git(*args, **kwargs):
            args_list = list(args)
            if "status" in args_list:
                return (0, "", "")
            if "checkout" in args_list:
                return (1, "", "checkout failed")
            return (0, "", "")
        with patch("luckyd_code.backup._is_git_repo", return_value=True):
            with patch("luckyd_code.backup._has_changes", return_value=False):
                with patch("luckyd_code.backup._git", side_effect=mock_git):
                    result = restore_backup("abc1234")
        assert not result["ok"]

    def test_successful_restore(self):
        from luckyd_code.backup import restore_backup
        with patch("luckyd_code.backup._is_git_repo", return_value=True):
            with patch("luckyd_code.backup._has_changes", return_value=False):
                with patch("luckyd_code.backup._git", return_value=(0, "ok", "")):
                    result = restore_backup("abc1234")
        assert result["ok"] is True
        assert "abc1234" in result["message"]

    def test_restore_stashes_dirty_changes(self):
        from luckyd_code.backup import restore_backup
        git_calls = []
        def mock_git(*args, **kwargs):
            git_calls.append(args)
            return (0, "ok", "")
        with patch("luckyd_code.backup._is_git_repo", return_value=True):
            with patch("luckyd_code.backup._has_changes", return_value=True):
                with patch("luckyd_code.backup._git", side_effect=mock_git):
                    result = restore_backup("abc1234")
        # Should have called stash push before checkout
        stash_calls = [c for c in git_calls if "stash" in c]
        assert len(stash_calls) >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# web_routes/files.py — exception paths
# ═══════════════════════════════════════════════════════════════════════════════

class TestWebRoutesFiles:
    @pytest.mark.asyncio
    async def test_list_files_access_denied(self):
        from luckyd_code.web_routes.files import list_files
        req = MagicMock()
        with patch("luckyd_code.web_routes.files._safe_resolve", return_value=None):
            result = await list_files(req, dir="/etc/shadow")
        assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_list_files_not_found(self, tmp_path):
        from luckyd_code.web_routes.files import list_files
        req = MagicMock()
        nonexistent = str(tmp_path / "ghost")
        with patch("luckyd_code.web_routes.files._safe_resolve", return_value=nonexistent):
            result = await list_files(req, dir=nonexistent)
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_list_files_not_a_dir(self, tmp_path):
        from luckyd_code.web_routes.files import list_files
        req = MagicMock()
        f = tmp_path / "file.txt"
        f.write_text("x")
        with patch("luckyd_code.web_routes.files._safe_resolve", return_value=str(f)):
            result = await list_files(req, dir=str(f))
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_list_files_permission_denied(self, tmp_path):
        from luckyd_code.web_routes.files import list_files
        req = MagicMock()
        with patch("luckyd_code.web_routes.files._safe_resolve", return_value=str(tmp_path)):
            with patch("pathlib.Path.iterdir", side_effect=PermissionError("denied")):
                result = await list_files(req, dir=str(tmp_path))
        assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_read_file_no_path(self):
        from luckyd_code.web_routes.files import read_file
        req = MagicMock()
        result = await read_file(req, path="")
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_read_file_access_denied(self):
        from luckyd_code.web_routes.files import read_file
        req = MagicMock()
        with patch("luckyd_code.web_routes.files._safe_resolve", return_value=None):
            result = await read_file(req, path="/etc/shadow")
        assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_read_file_not_found(self, tmp_path):
        from luckyd_code.web_routes.files import read_file
        req = MagicMock()
        ghost = str(tmp_path / "ghost.txt")
        with patch("luckyd_code.web_routes.files._safe_resolve", return_value=ghost):
            result = await read_file(req, path=ghost)
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_read_file_is_dir(self, tmp_path):
        from luckyd_code.web_routes.files import read_file
        req = MagicMock()
        with patch("luckyd_code.web_routes.files._safe_resolve", return_value=str(tmp_path)):
            result = await read_file(req, path=str(tmp_path))
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_write_file_access_denied(self):
        from luckyd_code.web_routes.files import write_file, WriteData
        req = MagicMock()
        with patch("luckyd_code.web_routes.files._safe_resolve", return_value=None):
            result = await write_file(req, WriteData(path="/etc/shadow", content="x"))
        assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_write_file_no_path(self):
        from luckyd_code.web_routes.files import write_file, WriteData
        req = MagicMock()
        result = await write_file(req, WriteData(path="", content="x"))
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_write_file_too_large(self):
        from luckyd_code.web_routes.files import write_file, WriteData, MAX_WRITE_BYTES
        req = MagicMock()
        big_content = "x" * (MAX_WRITE_BYTES + 1)
        result = await write_file(req, WriteData(path="f.py", content=big_content))
        assert result.status_code == 413

    @pytest.mark.asyncio
    async def test_edit_file_no_path_or_old(self):
        from luckyd_code.web_routes.files import edit_file, EditData
        req = MagicMock()
        result = await edit_file(req, EditData(path="", old_string="", new_string="y"))
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_edit_file_access_denied(self):
        from luckyd_code.web_routes.files import edit_file, EditData
        req = MagicMock()
        with patch("luckyd_code.web_routes.files._safe_resolve", return_value=None):
            result = await edit_file(req, EditData(path="/etc/shadow", old_string="x", new_string="y"))
        assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_edit_file_not_found(self, tmp_path):
        from luckyd_code.web_routes.files import edit_file, EditData
        req = MagicMock()
        ghost = str(tmp_path / "ghost.py")
        with patch("luckyd_code.web_routes.files._safe_resolve", return_value=ghost):
            result = await edit_file(req, EditData(path=ghost, old_string="x", new_string="y"))
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_edit_file_old_string_not_found(self, tmp_path):
        from luckyd_code.web_routes.files import edit_file, EditData
        req = MagicMock()
        f = tmp_path / "code.py"
        f.write_text("x = 1\n")
        with patch("luckyd_code.web_routes.files._safe_resolve", return_value=str(f)):
            result = await edit_file(req, EditData(path=str(f), old_string="NOTHERE", new_string="y"))
        assert result.status_code == 400
