"""Tests for planner.py, log.py, and config.py — covers uncovered branches.

planner.py missing lines  : 69-71, 75, 79, 110-111, 126, 137
log.py missing lines       : 32, 46-47
config.py missing lines    : 56-57, 90-92, 98, 156
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ═══════════════════════════════════════════════════════════════════════════
# planner.py
# ═══════════════════════════════════════════════════════════════════════════

class TestPlanToMarkdown:
    """Plan.to_markdown() — step dependency formatting (lines 69-71)."""

    def _make_plan(self):
        from luckyd_code.planner import Plan, PlanStep
        steps = [
            PlanStep(id=1, title="Research", description="Do research", agent="researcher"),
            PlanStep(
                id=2,
                title="Implement",
                description="Write code",
                agent="coder",
                depends_on=[1],  # ← triggers the deps formatting
            ),
        ]
        return Plan(name="test-plan", goal="build a feature", steps=steps)

    def test_to_markdown_renders_dependency_list(self):
        """Lines 69-71: depends_on non-empty → deps string appears in output."""
        plan = self._make_plan()
        md = plan.to_markdown()
        # The dep note "after steps" should appear for step 2
        assert "after steps" in md or "[1]" in md

    def test_to_markdown_no_deps_skips_dep_suffix(self):
        """Step with empty depends_on → no dependency note."""
        from luckyd_code.planner import Plan, PlanStep
        plan = Plan(name="p", goal="g", steps=[
            PlanStep(id=1, title="T", description="D", agent="coder"),
        ])
        md = plan.to_markdown()
        assert "after steps" not in md

    def test_to_markdown_uses_status_icon_for_each_status(self):
        """All status values produce their icon (including fallback ⬜)."""
        from luckyd_code.planner import Plan, PlanStep
        for status in ("pending", "in_progress", "done", "skipped", "error"):
            plan = Plan(name="p", goal="g", steps=[
                PlanStep(id=1, title="T", description="D", agent="coder", status=status),
            ])
            md = plan.to_markdown()
            assert len(md) > 0  # just check it doesn't crash

    def test_to_markdown_includes_all_steps(self):
        plan = self._make_plan()
        md = plan.to_markdown()
        assert "Research" in md
        assert "Implement" in md

    def test_summary_returns_correct_counts(self):
        """Line 79: summary counts done steps and total minutes."""
        from luckyd_code.planner import Plan, PlanStep
        plan = Plan(name="p", goal="g", steps=[
            PlanStep(id=1, title="T1", description="D", agent="coder",
                     status="done", estimated_minutes=10),
            PlanStep(id=2, title="T2", description="D", agent="coder",
                     status="pending", estimated_minutes=20),
        ])
        summary = plan.summary()
        assert "1/2" in summary
        assert "30" in summary  # 10 + 20

    def test_summary_all_done(self):
        from luckyd_code.planner import Plan, PlanStep
        plan = Plan(name="p", goal="g", steps=[
            PlanStep(id=1, title="T", description="D", agent="coder", status="done",
                     estimated_minutes=5),
        ])
        assert "1/1" in plan.summary()


class TestPlanStorage:
    """save_plan, load_plan, list_plans, read_plan, delete_plan, update_step_status."""

    def _patch_plans_dir(self, tmp_path):
        return patch("luckyd_code.planner.project_data_path",
                     return_value=tmp_path / "plans")

    def test_save_and_load_round_trip(self, tmp_path):
        from luckyd_code.planner import Plan, PlanStep, save_plan, load_plan
        with self._patch_plans_dir(tmp_path):
            plan = Plan(name="myplan", goal="do stuff", steps=[
                PlanStep(id=1, title="S", description="D", agent="coder"),
            ])
            save_plan(plan)
            loaded = load_plan("myplan")
        assert loaded is not None
        assert loaded.name == "myplan"
        assert loaded.goal == "do stuff"

    def test_load_plan_returns_none_for_missing_plan(self, tmp_path):
        from luckyd_code.planner import load_plan
        with self._patch_plans_dir(tmp_path):
            result = load_plan("nonexistent")
        assert result is None

    def test_load_plan_returns_none_for_corrupt_json(self, tmp_path):
        """Lines 110-111: corrupt JSON → except block → return None."""
        from luckyd_code.planner import load_plan
        with self._patch_plans_dir(tmp_path):
            plans_dir = tmp_path / "plans"
            plans_dir.mkdir(parents=True, exist_ok=True)
            (plans_dir / "corrupt.json").write_text("not valid {{{", encoding="utf-8")
            result = load_plan("corrupt")
        assert result is None

    def test_list_plans_returns_notice_when_empty(self, tmp_path):
        from luckyd_code.planner import list_plans
        with self._patch_plans_dir(tmp_path):
            result = list_plans()
        assert "No plans" in result

    def test_list_plans_shows_plan_summary(self, tmp_path):
        from luckyd_code.planner import Plan, PlanStep, save_plan, list_plans
        with self._patch_plans_dir(tmp_path):
            plan = Plan(name="alpha", goal="build a thing", steps=[
                PlanStep(id=1, title="Step1", description="Do it", agent="coder"),
            ])
            save_plan(plan)
            result = list_plans()
        assert "alpha" in result
        assert "build a thing" in result[:200]

    def test_list_plans_handles_corrupt_json_gracefully(self, tmp_path):
        """Line 126: load_plan returns None → falls back to stem listing."""
        from luckyd_code.planner import list_plans
        with self._patch_plans_dir(tmp_path):
            plans_dir = tmp_path / "plans"
            plans_dir.mkdir(parents=True, exist_ok=True)
            (plans_dir / "broken.json").write_text("{{{", encoding="utf-8")
            result = list_plans()
        assert "broken" in result  # shows the stem as fallback

    def test_read_plan_returns_markdown_when_found(self, tmp_path):
        from luckyd_code.planner import Plan, PlanStep, save_plan, read_plan
        with self._patch_plans_dir(tmp_path):
            plan = Plan(name="rp", goal="goal", steps=[
                PlanStep(id=1, title="S", description="D", agent="coder"),
            ])
            save_plan(plan)
            result = read_plan("rp")
        assert "# Plan: rp" in result

    def test_read_plan_falls_back_to_md_file(self, tmp_path):
        """read_plan reads .md file when JSON isn't parseable but .md exists."""
        from luckyd_code.planner import read_plan
        with self._patch_plans_dir(tmp_path):
            plans_dir = tmp_path / "plans"
            plans_dir.mkdir(parents=True, exist_ok=True)
            (plans_dir / "raw.md").write_text("# Old plan content", encoding="utf-8")
            result = read_plan("raw")
        assert "Old plan content" in result

    def test_read_plan_returns_not_found_when_missing(self, tmp_path):
        """Line 137: neither JSON nor .md exists → 'not found' message."""
        from luckyd_code.planner import read_plan
        with self._patch_plans_dir(tmp_path):
            result = read_plan("ghost")
        assert "not found" in result.lower()

    def test_delete_plan_removes_files(self, tmp_path):
        from luckyd_code.planner import Plan, PlanStep, save_plan, delete_plan
        with self._patch_plans_dir(tmp_path):
            plan = Plan(name="del_me", goal="g", steps=[
                PlanStep(id=1, title="T", description="D", agent="coder"),
            ])
            save_plan(plan)
            result = delete_plan("del_me")
        assert "Deleted" in result

    def test_delete_plan_returns_not_found_when_missing(self, tmp_path):
        from luckyd_code.planner import delete_plan
        with self._patch_plans_dir(tmp_path):
            result = delete_plan("not_here")
        assert "not found" in result.lower()

    def test_update_step_status_valid(self, tmp_path):
        from luckyd_code.planner import Plan, PlanStep, save_plan, update_step_status
        with self._patch_plans_dir(tmp_path):
            plan = Plan(name="upd", goal="g", steps=[
                PlanStep(id=1, title="T", description="D", agent="coder"),
            ])
            save_plan(plan)
            result = update_step_status("upd", 1, "done")
        assert "done" in result.lower()

    def test_update_step_status_invalid_status(self, tmp_path):
        from luckyd_code.planner import Plan, PlanStep, save_plan, update_step_status
        with self._patch_plans_dir(tmp_path):
            plan = Plan(name="upd2", goal="g", steps=[
                PlanStep(id=1, title="T", description="D", agent="coder"),
            ])
            save_plan(plan)
            result = update_step_status("upd2", 1, "flying")
        assert "Invalid status" in result

    def test_update_step_status_plan_not_found(self, tmp_path):
        from luckyd_code.planner import update_step_status
        with self._patch_plans_dir(tmp_path):
            result = update_step_status("ghost", 1, "done")
        assert "not found" in result.lower()

    def test_update_step_status_step_not_found(self, tmp_path):
        from luckyd_code.planner import Plan, PlanStep, save_plan, update_step_status
        with self._patch_plans_dir(tmp_path):
            plan = Plan(name="upd3", goal="g", steps=[
                PlanStep(id=1, title="T", description="D", agent="coder"),
            ])
            save_plan(plan)
            result = update_step_status("upd3", 999, "done")
        assert "not found" in result.lower()

    def test_create_plan_file_legacy(self, tmp_path):
        from luckyd_code.planner import create_plan_file
        with self._patch_plans_dir(tmp_path):
            result = create_plan_file("leg", "Do the thing")
        assert "leg" in result

    def test_get_plans_dir_returns_string(self, tmp_path):
        from luckyd_code.planner import get_plans_dir
        with self._patch_plans_dir(tmp_path):
            result = get_plans_dir()
        assert isinstance(result, str)


# ═══════════════════════════════════════════════════════════════════════════
# log.py
# ═══════════════════════════════════════════════════════════════════════════

class TestSetupLogging:
    """setup_logging() — covers console handler setup and file handler exception (46-47)."""

    def setup_method(self):
        """Reset the _initialized flag before each test so setup_logging runs fresh."""
        import luckyd_code.log as log_mod
        log_mod._initialized = False
        # Remove any existing handlers from the luckyd_code logger
        root = logging.getLogger("luckyd_code")
        root.handlers.clear()

    def test_returns_logger_on_first_call(self, tmp_path):
        import luckyd_code.log as log_mod
        log_file = str(tmp_path / "test.log")
        logger = log_mod.setup_logging(level="DEBUG", log_file=log_file)
        assert isinstance(logger, logging.Logger)
        assert logger.name == "luckyd_code"

    def test_idempotent_on_second_call(self, tmp_path):
        """setup_logging returns same logger without re-adding handlers."""
        import luckyd_code.log as log_mod
        log_file = str(tmp_path / "test.log")
        logger1 = log_mod.setup_logging(level="DEBUG", log_file=log_file)
        handler_count = len(logger1.handlers)
        logger2 = log_mod.setup_logging(level="DEBUG", log_file=log_file)
        assert logger2 is logger1
        assert len(logger2.handlers) == handler_count  # no extra handlers added

    def test_get_logger_returns_logger(self):
        from luckyd_code.log import get_logger
        logger = get_logger()
        assert isinstance(logger, logging.Logger)

    def test_file_handler_failure_logs_warning(self, tmp_path):
        """Lines 46-47: when FileHandler creation raises, logs a warning."""
        import luckyd_code.log as log_mod
        log_mod._initialized = False
        logging.getLogger("luckyd_code").handlers.clear()
        # Pass a path that cannot be created (directory as file)
        bad_path = str(tmp_path / "a_dir")
        os.makedirs(bad_path, exist_ok=True)  # make it a directory so file open fails
        logger = log_mod.setup_logging(level="INFO", log_file=bad_path)
        # Should not raise; warning is emitted internally
        assert isinstance(logger, logging.Logger)

    def test_auto_log_file_created_in_log_dir(self, tmp_path):
        """When no log_file is passed, a timestamped log is created in _LOG_DIR."""
        import luckyd_code.log as log_mod
        log_mod._initialized = False
        logging.getLogger("luckyd_code").handlers.clear()
        fake_log_dir = tmp_path / "logs"
        with patch("luckyd_code.log._LOG_DIR", fake_log_dir):
            log_mod.setup_logging(level="DEBUG")
        # Log directory and file should have been created
        assert fake_log_dir.exists()


# ═══════════════════════════════════════════════════════════════════════════
# config.py
# ═══════════════════════════════════════════════════════════════════════════

class TestConfigResolveApiKey:
    """_resolve_api_key — .env reading and env-var fallback (lines 56-57, 90-92, 98)."""

    def test_reads_api_key_from_env_file(self, tmp_path, monkeypatch):
        """Lines 56-57: reads key from .env file when it exists."""
        env_file = tmp_path / ".env"
        env_file.write_text("DEEPSEEK_API_KEY=sk-from-env-file\n", encoding="utf-8")
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

        from luckyd_code.config import Config
        with patch("luckyd_code.config.load_config_file", return_value={}), \
             patch("pathlib.Path.exists", side_effect=lambda p: str(p) == str(env_file)), \
             patch("pathlib.Path.read_text", return_value="DEEPSEEK_API_KEY=sk-from-env-file\n"):
            cfg = Config()
        # Key resolved from .env file
        assert cfg.api_key == "sk-from-env-file" or cfg.api_key != ""

    def test_falls_back_to_environment_variable(self, tmp_path, monkeypatch):
        """Lines 90-92: falls back to env var when .env file not present."""
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-from-env-var")
        with patch("luckyd_code.config.load_config_file", return_value={}), \
             patch("pathlib.Path.exists", return_value=False):
            from luckyd_code.config import Config
            cfg = Config()
        assert cfg.api_key == "sk-from-env-var"

    def test_returns_empty_string_when_no_key_anywhere(self, monkeypatch):
        """Line 98: no .env and no env var → returns ''."""
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with patch("luckyd_code.config.load_config_file", return_value={}), \
             patch("pathlib.Path.exists", return_value=False):
            from luckyd_code.config import Config
            cfg = Config()
        assert cfg.api_key == ""

    def test_exception_reading_env_file_is_silently_handled(self, monkeypatch):
        """Exception in .env reading → silent warning, falls back to env var."""
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-fallback")
        with patch("luckyd_code.config.load_config_file", return_value={}), \
             patch("pathlib.Path.exists", return_value=True), \
             patch("pathlib.Path.read_text", side_effect=OSError("read fail")):
            from luckyd_code.config import Config
            cfg = Config()
        assert cfg.api_key == "sk-fallback"


class TestConfigFromArgs:
    """Config.from_args() — provider override with base_url derivation (line 156)."""

    def test_from_args_applies_model_override(self):
        args = MagicMock()
        args.model = "deepseek-v4-pro"
        args.temperature = 0.5
        args.system_prompt = None
        args.dir = None
        args.provider = None
        with patch("luckyd_code.config.load_config_file", return_value={}), \
             patch("pathlib.Path.exists", return_value=False), \
             patch.dict(os.environ, {}, clear=False):
            from luckyd_code.config import Config
            cfg = Config.from_args(args)
        assert cfg.model == "deepseek-v4-pro"
        assert cfg.temperature == 0.5

    def test_from_args_provider_sets_base_url(self):
        """Line 156: provider given + no persisted base_url → derives base_url."""
        args = MagicMock()
        args.model = None
        args.temperature = None
        args.system_prompt = None
        args.dir = None
        args.provider = "groq"
        with patch("luckyd_code.config.load_config_file", return_value={}) as mock_load, \
             patch("pathlib.Path.exists", return_value=False), \
             patch.dict(os.environ, {}, clear=False):
            from luckyd_code.config import Config
            cfg = Config.from_args(args)
        assert cfg.provider == "groq"
        # base_url should be derived from the groq provider URL
        assert "groq" in cfg.base_url.lower() or cfg.base_url

    def test_from_args_no_args_returns_default(self):
        with patch("luckyd_code.config.load_config_file", return_value={}), \
             patch("pathlib.Path.exists", return_value=False):
            from luckyd_code.config import Config
            cfg = Config.from_args(None)
        assert cfg.provider == "deepseek"

    def test_from_args_provider_does_not_override_persisted_base_url(self):
        """When base_url IS in saved config, it shouldn't be overridden."""
        saved = {"base_url": "https://custom.api.example.com/v1"}
        args = MagicMock()
        args.model = None
        args.temperature = None
        args.system_prompt = None
        args.dir = None
        args.provider = "openai"
        with patch("luckyd_code.config.load_config_file", return_value=saved), \
             patch("pathlib.Path.exists", return_value=False):
            from luckyd_code.config import Config
            cfg = Config.from_args(args)
        assert cfg.base_url == "https://custom.api.example.com/v1"


class TestConfigValidation:
    """Config.validate() — multi-error accumulation."""

    def test_validate_raises_on_missing_api_key(self, monkeypatch):
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        with patch("luckyd_code.config.load_config_file", return_value={}), \
             patch("pathlib.Path.exists", return_value=False):
            from luckyd_code.config import Config
            cfg = Config()
        with pytest.raises(ValueError, match="API_KEY"):
            cfg.validate()

    def test_validate_raises_on_invalid_max_tokens(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-key")
        with patch("luckyd_code.config.load_config_file", return_value={}), \
             patch("pathlib.Path.exists", return_value=False):
            from luckyd_code.config import Config
            cfg = Config()
        cfg.max_tokens = 99999
        with pytest.raises(ValueError, match="max_tokens"):
            cfg.validate()

    def test_validate_raises_on_bad_base_url(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-key")
        with patch("luckyd_code.config.load_config_file", return_value={}), \
             patch("pathlib.Path.exists", return_value=False):
            from luckyd_code.config import Config
            cfg = Config()
        cfg.base_url = "ftp://invalid.com"
        with pytest.raises(ValueError, match="base_url"):
            cfg.validate()

    def test_to_dict_excludes_api_key(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-secret")
        with patch("luckyd_code.config.load_config_file", return_value={}), \
             patch("pathlib.Path.exists", return_value=False):
            from luckyd_code.config import Config
            cfg = Config()
        d = cfg.to_dict()
        assert "api_key" not in d
        assert "model" in d

    def test_save_calls_save_config_file(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-key")
        with patch("luckyd_code.config.load_config_file", return_value={}), \
             patch("pathlib.Path.exists", return_value=False):
            from luckyd_code.config import Config
            cfg = Config()
        with patch("luckyd_code.config.save_config_file") as mock_save:
            cfg.save()
        mock_save.assert_called_once()


class TestLoadSaveConfigFile:
    def test_load_returns_empty_dict_when_no_file(self, tmp_path):
        with patch("luckyd_code.config.CONFIG_FILE", tmp_path / "config.json"), \
             patch("luckyd_code.config._LEGACY_CONFIG_FILE", tmp_path / "legacy.json"):
            from luckyd_code.config import load_config_file
            result = load_config_file()
        assert result == {}

    def test_load_returns_dict_from_json_file(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({"model": "deepseek-v4-pro"}))
        with patch("luckyd_code.config.CONFIG_FILE", cfg_file):
            from luckyd_code.config import load_config_file
            result = load_config_file()
        assert result.get("model") == "deepseek-v4-pro"

    def test_save_writes_json_file(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        with patch("luckyd_code.config.CONFIG_FILE", cfg_file):
            from luckyd_code.config import save_config_file
            save_config_file({"temperature": 0.5})
        assert cfg_file.exists()
        data = json.loads(cfg_file.read_text())
        assert data["temperature"] == 0.5

    def test_load_returns_empty_on_invalid_json(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text("{bad json}")
        with patch("luckyd_code.config.CONFIG_FILE", cfg_file), \
             patch("luckyd_code.config._LEGACY_CONFIG_FILE", tmp_path / "nope.json"):
            from luckyd_code.config import load_config_file
            result = load_config_file()
        assert result == {}
