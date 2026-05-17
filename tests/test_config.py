"""Tests for the config module."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from luckyd_code.config import Config, load_config_file, save_config_file


class TestConfig:
    def test_default_provider(self):
        """Default provider should be deepseek."""
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}, clear=True):
            cfg = Config()
            assert cfg.provider == "deepseek"

    def test_validate_valid_config(self):
        """Valid config should not raise."""
        cfg = Config()
        cfg.api_key = "test-key"
        cfg.base_url = "https://api.deepseek.com/v1"
        cfg.provider = "deepseek"
        cfg.max_tokens = 4096
        cfg.temperature = 0.7
        cfg.max_context_messages = 100
        cfg.validate()  # Should not raise

    def test_validate_missing_api_key(self):
        """Missing API key should raise ValueError."""
        cfg = Config()
        cfg.api_key = ""
        cfg.provider = "deepseek"
        cfg.base_url = "https://api.deepseek.com/v1"
        with pytest.raises(ValueError, match="DEEPSEEK_API_KEY is not set"):
            cfg.validate()

    def test_validate_invalid_provider(self):
        """Invalid provider should raise ValueError."""
        cfg = Config()
        cfg.provider = "invalid"
        cfg.api_key = "test-key"
        cfg.base_url = "https://api.deepseek.com/v1"
        with pytest.raises(ValueError, match="provider must be"):
            cfg.validate()

    def test_validate_invalid_base_url(self):
        """Invalid base URL should raise ValueError."""
        cfg = Config()
        cfg.api_key = "test-key"
        cfg.provider = "deepseek"
        cfg.base_url = "not-a-url"
        with pytest.raises(ValueError, match="base_url must start with"):
            cfg.validate()

    def test_validate_max_tokens_out_of_range(self):
        """max_tokens out of range should raise ValueError."""
        cfg = Config()
        cfg.api_key = "test-key"
        cfg.provider = "deepseek"
        cfg.base_url = "https://api.deepseek.com/v1"
        cfg.max_tokens = 999999
        with pytest.raises(ValueError, match="max_tokens must be between"):
            cfg.validate()

    def test_validate_temperature_out_of_range(self):
        """Temperature out of range should raise ValueError."""
        cfg = Config()
        cfg.api_key = "test-key"
        cfg.provider = "deepseek"
        cfg.base_url = "https://api.deepseek.com/v1"
        cfg.temperature = 5.0
        with pytest.raises(ValueError, match="temperature must be between"):
            cfg.validate()

    def test_validate_max_context_messages_too_low(self):
        """max_context_messages below 2 should raise ValueError."""
        cfg = Config()
        cfg.api_key = "test-key"
        cfg.provider = "deepseek"
        cfg.base_url = "https://api.deepseek.com/v1"
        cfg.max_context_messages = 1
        with pytest.raises(ValueError, match="max_context_messages must be at least"):
            cfg.validate()

    def test_to_dict_excludes_api_key(self):
        """to_dict should not include the API key."""
        cfg = Config()
        cfg.api_key = "secret-key"
        d = cfg.to_dict()
        assert "api_key" not in d

    def test_from_args_overrides_model(self):
        """from_args should apply CLI overrides."""
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}, clear=True):
            class Args:
                model = "deepseek-reasoner"
                temperature = None
                system_prompt = None
                dir = None
                provider = None
            cfg = Config.from_args(Args())
            assert cfg.model == "deepseek-reasoner"

    def test_from_args_overrides_temperature(self):
        """from_args should apply temperature override."""
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}, clear=True):
            class Args:
                model = None
                temperature = 0.3
                system_prompt = None
                dir = None
                provider = None
            cfg = Config.from_args(Args())
            assert cfg.temperature == 0.3

    def test_load_config_file_not_found(self):
        """load_config_file should return empty dict if file doesn't exist."""
        nonexistent = Path(tempfile.gettempdir()) / "_nonexistent_config.json"
        with patch("luckyd_code.config.CONFIG_FILE", nonexistent), \
             patch("luckyd_code.config._LEGACY_CONFIG_FILE", nonexistent):
            result = load_config_file()
            assert result == {}

    def test_save_and_load_config_file(self):
        """save_config_file then load_config_file should round-trip."""
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "config.json"
            with patch("luckyd_code.config.CONFIG_FILE", cfg_path):
                test_config = {"provider": "deepseek", "model": "test-model"}
                save_config_file(test_config)
                loaded = load_config_file()
                assert loaded["provider"] == "deepseek"
                assert loaded["model"] == "test-model"

    def test_api_key_from_env(self):
        """API key should be read from environment variable."""
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "env-test-key"}, clear=True):
            # Simulate missing .env files so _resolve_api_key falls through to env vars
            with patch.object(Path, "read_text", side_effect=FileNotFoundError):
                cfg = Config()
                assert cfg.api_key == "env-test-key"
