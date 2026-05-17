"""Extra branch coverage for luckyd_code/config.py.

Target lines from cov_out.txt:
  56-57   load_config_file: JSONDecodeError / OSError exception handler
  90-92   _resolve_api_key: DEEPSEEK_API_KEY fallback line in .env reader
  98      _resolve_api_key: return key (env var path)
  156     from_args: cfg.api_key = cfg._resolve_api_key() after provider override
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, mock_open

import pytest

from luckyd_code.config import Config, load_config_file, save_config_file, get_api_key, get_base_url


# ────────────────────────────────────────────────────────────────────────────
# load_config_file — exception branches (lines 56-57)
# ────────────────────────────────────────────────────────────────────────────

class TestLoadConfigFileExceptions:
    def test_json_decode_error_returns_empty_dict(self, tmp_path):
        """JSONDecodeError on read → warning logged, fallback to {}."""
        bad = tmp_path / "config.json"
        bad.write_text("NOT VALID JSON {{{", encoding="utf-8")
        with patch("luckyd_code.config.CONFIG_FILE", bad), \
             patch("luckyd_code.config._LEGACY_CONFIG_FILE", tmp_path / "missing.json"):
            result = load_config_file()
        assert result == {}

    def test_os_error_on_read_returns_empty_dict(self, tmp_path):
        """OSError on path.read_text → warning logged, fallback to {}."""
        fake = tmp_path / "config.json"
        fake.touch()  # exists so the if-branch is entered
        with patch("luckyd_code.config.CONFIG_FILE", fake), \
             patch("luckyd_code.config._LEGACY_CONFIG_FILE", tmp_path / "missing.json"), \
             patch.object(Path, "read_text", side_effect=OSError("permission denied")):
            result = load_config_file()
        assert result == {}

    def test_legacy_path_used_when_primary_missing(self, tmp_path):
        """Falls through to legacy path when primary does not exist."""
        primary = tmp_path / "primary.json"
        legacy = tmp_path / "legacy.json"
        legacy.write_text(json.dumps({"model": "legacy-model"}), encoding="utf-8")
        with patch("luckyd_code.config.CONFIG_FILE", primary), \
             patch("luckyd_code.config._LEGACY_CONFIG_FILE", legacy):
            result = load_config_file()
        assert result["model"] == "legacy-model"


# ────────────────────────────────────────────────────────────────────────────
# _resolve_api_key — DEEPSEEK_API_KEY fallback path (lines 90-92)
# ────────────────────────────────────────────────────────────────────────────

class TestResolveApiKeyDotEnvFallback:
    def test_deepseek_key_from_dot_env_using_legacy_name(self, tmp_path):
        """Lines 90-91: DEEPSEEK_API_KEY= in .env file → returned for deepseek provider."""
        env_content = "DEEPSEEK_API_KEY=sk-from-dotenv-fallback\n"

        cfg = Config.__new__(Config)
        cfg.provider = "deepseek"

        # Patch both .env paths to point at our temp file
        env_file = tmp_path / ".env"
        env_file.write_text(env_content, encoding="utf-8")

        with patch.object(
            Path,
            "__truediv__",
            side_effect=lambda self, other: env_file if str(other) == ".env" else Path(str(self)) / other,
        ):
            # Simpler: patch read_text on the specific instance
            pass

        # Use a simpler direct approach — patch open at the builtins level
        with patch("builtins.open", mock_open(read_data=env_content)):
            with patch.object(Path, "read_text", return_value=env_content):
                key = cfg._resolve_api_key()

        assert key == "sk-from-dotenv-fallback"

    def test_exception_reading_env_file_falls_to_env_var(self):
        """Line 92: Exception reading .env → falls through to os.environ."""
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "env-var-key"}, clear=True):
            with patch.object(Path, "read_text", side_effect=PermissionError("no read")):
                cfg = Config.__new__(Config)
                cfg.provider = "deepseek"
                key = cfg._resolve_api_key()
        assert key == "env-var-key"


# ────────────────────────────────────────────────────────────────────────────
# _resolve_api_key — env var return path (line 98)
# ────────────────────────────────────────────────────────────────────────────

class TestResolveApiKeyEnvVarPath:
    def test_provider_specific_env_var_is_returned(self):
        """Line 98: os.environ.get(provider_env) → returned."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "openai-test-key"}, clear=True):
            with patch.object(Path, "read_text", side_effect=FileNotFoundError):
                with patch("luckyd_code.config.load_config_file", return_value={"provider": "openai"}):
                    cfg = Config()
        assert cfg.api_key == "openai-test-key"

    def test_legacy_deepseek_env_var_fallback(self):
        """Line 98: os.environ.get('DEEPSEEK_API_KEY') fallback for deepseek."""
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "ds-fallback-key"}, clear=True):
            with patch.object(Path, "read_text", side_effect=FileNotFoundError):
                cfg = Config()
        assert cfg.api_key == "ds-fallback-key"

    def test_no_key_returns_empty_string(self):
        """No .env and no env var → empty string."""
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(Path, "read_text", side_effect=FileNotFoundError):
                cfg = Config.__new__(Config)
                cfg.provider = "deepseek"
                key = cfg._resolve_api_key()
        assert key == ""


# ────────────────────────────────────────────────────────────────────────────
# from_args — provider override re-resolves api_key (line 156)
# ────────────────────────────────────────────────────────────────────────────

class TestFromArgsProviderOverride:
    def test_provider_arg_triggers_api_key_resolution(self):
        """Line 156: cfg.api_key = cfg._resolve_api_key() after provider override."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "openai-resolved"}, clear=True):
            with patch.object(Path, "read_text", side_effect=FileNotFoundError):
                with patch("luckyd_code.config.load_config_file", return_value={}):
                    class Args:
                        model = None
                        temperature = None
                        system_prompt = None
                        dir = None
                        provider = "openai"

                    cfg = Config.from_args(Args())

        assert cfg.provider == "openai"
        assert cfg.api_key == "openai-resolved"

    def test_provider_arg_sets_base_url_from_registry(self):
        """from_args with provider → base_url derived from _PROVIDER_URLS."""
        with patch.dict(os.environ, {"GROQ_API_KEY": "groq-key"}, clear=True):
            with patch.object(Path, "read_text", side_effect=FileNotFoundError):
                with patch("luckyd_code.config.load_config_file", return_value={}):
                    class Args:
                        model = None
                        temperature = None
                        system_prompt = None
                        dir = None
                        provider = "groq"

                    cfg = Config.from_args(Args())

        assert "groq" in cfg.base_url

    def test_from_args_system_prompt_override(self):
        """from_args applies system_prompt override."""
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "key"}, clear=True):
            with patch.object(Path, "read_text", side_effect=FileNotFoundError):
                class Args:
                    model = None
                    temperature = None
                    system_prompt = "Custom system prompt"
                    dir = None
                    provider = None

                cfg = Config.from_args(Args())

        assert cfg.system_prompt == "Custom system prompt"

    def test_from_args_dir_override(self):
        """from_args applies working_directory override."""
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "key"}, clear=True):
            with patch.object(Path, "read_text", side_effect=FileNotFoundError):
                class Args:
                    model = None
                    temperature = None
                    system_prompt = None
                    dir = "/tmp/myproject"
                    provider = None

                cfg = Config.from_args(Args())

        assert cfg.working_directory == "/tmp/myproject"


# ────────────────────────────────────────────────────────────────────────────
# Module-level helpers
# ────────────────────────────────────────────────────────────────────────────

class TestModuleHelpers:
    def test_get_api_key_returns_string(self):
        """get_api_key() returns a string (may be empty in test env)."""
        with patch.object(Path, "read_text", side_effect=FileNotFoundError):
            with patch.dict(os.environ, {}, clear=True):
                result = get_api_key()
        assert isinstance(result, str)

    def test_get_base_url_returns_string(self):
        """get_base_url() returns a non-empty URL string."""
        result = get_base_url()
        assert isinstance(result, str)
        assert result.startswith("http")

    def test_save_config_creates_directories(self, tmp_path):
        """save_config_file creates parent dirs and writes JSON."""
        nested = tmp_path / "a" / "b" / "config.json"
        with patch("luckyd_code.config.CONFIG_FILE", nested):
            save_config_file({"key": "value"})
        assert nested.exists()
        data = json.loads(nested.read_text())
        assert data["key"] == "value"

    def test_config_to_dict_has_expected_keys(self):
        """to_dict() includes provider, model, temperature, etc."""
        cfg = Config.__new__(Config)
        cfg.provider = "deepseek"
        cfg.base_url = "https://api.deepseek.com/v1"
        cfg.model = "deepseek-v4-flash"
        cfg.max_tokens = 4096
        cfg.temperature = 0.3
        cfg.max_context_messages = 40
        cfg.log_level = "WARNING"
        cfg.effort = "normal"
        d = cfg.to_dict()
        assert "provider" in d
        assert "model" in d
        assert "api_key" not in d  # never exported

    def test_config_validate_empty_base_url(self):
        """Empty base_url should raise ValueError."""
        cfg = Config.__new__(Config)
        cfg.provider = "deepseek"
        cfg.api_key = "key"
        cfg.base_url = ""
        cfg.max_tokens = 4096
        cfg.temperature = 0.5
        cfg.max_context_messages = 10
        with pytest.raises(ValueError, match="base_url"):
            cfg.validate()
