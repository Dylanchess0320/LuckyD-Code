"""Tests for settings.py — settings load/save and hooks."""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from luckyd_code import settings as cfg


class TestGetSettingsPaths:
    def test_settings_path_is_path(self, tmp_path, monkeypatch):
        monkeypatch.setattr("luckyd_code.settings.get_settings_dir", lambda: tmp_path)
        result = cfg.get_settings_path()
        assert isinstance(result, Path)
        assert result.name == "settings.json"

    def test_local_settings_path(self, tmp_path, monkeypatch):
        monkeypatch.setattr("luckyd_code.settings.get_settings_dir", lambda: tmp_path)
        result = cfg.get_local_settings_path()
        assert result.name == "settings.local.json"


class TestLoadSettings:
    def test_returns_empty_when_no_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr("luckyd_code.settings.get_settings_path", lambda: tmp_path / "s.json")
        monkeypatch.setattr("luckyd_code.settings.get_local_settings_path", lambda: tmp_path / "sl.json")
        result = cfg.load_settings()
        assert result == {}

    def test_loads_from_settings_json(self, tmp_path, monkeypatch):
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({"key": "value"}))
        monkeypatch.setattr("luckyd_code.settings.get_settings_path", lambda: settings_file)
        monkeypatch.setattr("luckyd_code.settings.get_local_settings_path", lambda: tmp_path / "sl.json")
        result = cfg.load_settings()
        assert result["key"] == "value"

    def test_local_overrides_base(self, tmp_path, monkeypatch):
        base = tmp_path / "settings.json"
        local = tmp_path / "settings.local.json"
        base.write_text(json.dumps({"key": "base", "other": "keep"}))
        local.write_text(json.dumps({"key": "local"}))
        monkeypatch.setattr("luckyd_code.settings.get_settings_path", lambda: base)
        monkeypatch.setattr("luckyd_code.settings.get_local_settings_path", lambda: local)
        result = cfg.load_settings()
        assert result["key"] == "local"
        assert result["other"] == "keep"

    def test_corrupted_file_is_skipped(self, tmp_path, monkeypatch):
        settings_file = tmp_path / "settings.json"
        settings_file.write_text("not valid json {{{{")
        monkeypatch.setattr("luckyd_code.settings.get_settings_path", lambda: settings_file)
        monkeypatch.setattr("luckyd_code.settings.get_local_settings_path", lambda: tmp_path / "sl.json")
        result = cfg.load_settings()
        assert result == {}


class TestSaveSetting:
    def test_creates_local_settings_file(self, tmp_path, monkeypatch):
        local = tmp_path / "settings.local.json"
        monkeypatch.setattr("luckyd_code.settings.get_local_settings_path", lambda: local)
        cfg.save_setting("my_key", "my_value")
        assert local.exists()
        data = json.loads(local.read_text())
        assert data["my_key"] == "my_value"

    def test_merges_with_existing(self, tmp_path, monkeypatch):
        local = tmp_path / "settings.local.json"
        local.write_text(json.dumps({"existing": "yes"}))
        monkeypatch.setattr("luckyd_code.settings.get_local_settings_path", lambda: local)
        cfg.save_setting("new_key", "new_val")
        data = json.loads(local.read_text())
        assert data["existing"] == "yes"
        assert data["new_key"] == "new_val"

    def test_overwrites_existing_key(self, tmp_path, monkeypatch):
        local = tmp_path / "settings.local.json"
        local.write_text(json.dumps({"key": "old"}))
        monkeypatch.setattr("luckyd_code.settings.get_local_settings_path", lambda: local)
        cfg.save_setting("key", "new")
        data = json.loads(local.read_text())
        assert data["key"] == "new"

    def test_handles_corrupted_existing_file(self, tmp_path, monkeypatch):
        local = tmp_path / "settings.local.json"
        local.write_text("CORRUPTED")
        monkeypatch.setattr("luckyd_code.settings.get_local_settings_path", lambda: local)
        cfg.save_setting("k", "v")
        data = json.loads(local.read_text())
        assert data["k"] == "v"


class TestGetHooks:
    def test_returns_empty_when_no_hooks(self, tmp_path, monkeypatch):
        monkeypatch.setattr("luckyd_code.settings.load_settings", lambda: {})
        result = cfg.get_hooks()
        assert result == {}

    def test_returns_hooks_from_settings(self, tmp_path, monkeypatch):
        monkeypatch.setattr("luckyd_code.settings.load_settings",
                            lambda: {"hooks": {"preToolUse": "echo hi"}})
        result = cfg.get_hooks()
        assert result["preToolUse"] == "echo hi"


class TestRunPreHook:
    def test_no_hooks_returns_empty(self, monkeypatch):
        monkeypatch.setattr("luckyd_code.settings.get_hooks", lambda: {})
        result = cfg.run_pre_hook("Read")
        assert result == []

    def test_string_hook_runs_for_all_tools(self, monkeypatch):
        monkeypatch.setattr("luckyd_code.settings.get_hooks",
                            lambda: {"preToolUse": "echo hello"})
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("subprocess.run", return_value=mock_result):
            result = cfg.run_pre_hook("Read")
        assert result == []

    def test_hook_failure_returns_stderr(self, monkeypatch):
        monkeypatch.setattr("luckyd_code.settings.get_hooks",
                            lambda: {"preToolUse": "exit 1"})
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "hook failed"
        with patch("subprocess.run", return_value=mock_result):
            result = cfg.run_pre_hook("Read")
        assert "hook failed" in result

    def test_dict_hook_with_tool_filter(self, monkeypatch):
        monkeypatch.setattr("luckyd_code.settings.get_hooks",
                            lambda: {"preToolUse": {"script": "echo hi", "tools": ["Write"]}})
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            cfg.run_pre_hook("Read")  # Read not in allowed tools
            assert not mock_run.called

    def test_dict_hook_runs_for_matching_tool(self, monkeypatch):
        monkeypatch.setattr("luckyd_code.settings.get_hooks",
                            lambda: {"preToolUse": {"script": "echo hi", "tools": ["Write"]}})
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            cfg.run_pre_hook("Write")
            assert mock_run.called

    def test_hook_exception_returns_error(self, monkeypatch):
        monkeypatch.setattr("luckyd_code.settings.get_hooks",
                            lambda: {"preToolUse": "some_script"})
        with patch("subprocess.run", side_effect=Exception("boom")):
            result = cfg.run_pre_hook("Read")
        assert len(result) == 1
        assert "boom" in result[0]
