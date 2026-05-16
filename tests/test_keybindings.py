"""Tests for keybindings.py."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from luckyd_code.keybindings import (
    DEFAULT_BINDINGS,
    _parse_key_sequence,
    apply_keybindings,
    get_keybindings_path,
    load_keybindings,
)


class TestParseKeySequence:
    def test_regular_key(self):
        assert _parse_key_sequence("enter") == ("enter",)

    def test_ctrl_key(self):
        assert _parse_key_sequence("ctrl-c") == ("ctrl-c",)

    def test_alt_enter(self):
        assert _parse_key_sequence("alt-enter") == ("escape", "enter")

    def test_alt_a(self):
        assert _parse_key_sequence("alt-a") == ("escape", "a")

    def test_non_alt_prefix(self):
        assert _parse_key_sequence("ctrl-p") == ("ctrl-p",)


class TestGetKeybindingsPath:
    def test_returns_path(self):
        p = get_keybindings_path()
        assert isinstance(p, Path)
        assert p.name == "keybindings.json"


class TestLoadKeybindings:
    def test_returns_empty_when_file_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "luckyd_code.keybindings.get_keybindings_path",
            lambda: tmp_path / "nonexistent.json",
        )
        result = load_keybindings()
        assert result == {}

    def test_returns_dict_from_valid_file(self, tmp_path, monkeypatch):
        p = tmp_path / "keybindings.json"
        p.write_text(json.dumps({"submit": "ctrl-s"}), encoding="utf-8")
        monkeypatch.setattr(
            "luckyd_code.keybindings.get_keybindings_path", lambda: p
        )
        result = load_keybindings()
        assert result == {"submit": "ctrl-s"}

    def test_returns_empty_on_invalid_json(self, tmp_path, monkeypatch):
        p = tmp_path / "keybindings.json"
        p.write_text("{not valid json", encoding="utf-8")
        monkeypatch.setattr(
            "luckyd_code.keybindings.get_keybindings_path", lambda: p
        )
        result = load_keybindings()
        assert result == {}

    def test_returns_empty_when_json_is_not_dict(self, tmp_path, monkeypatch):
        p = tmp_path / "keybindings.json"
        p.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        monkeypatch.setattr(
            "luckyd_code.keybindings.get_keybindings_path", lambda: p
        )
        result = load_keybindings()
        assert result == {}


class TestApplyKeybindings:
    def test_returns_keybindings_object(self, monkeypatch):
        monkeypatch.setattr("luckyd_code.keybindings.load_keybindings", lambda: {})
        kb = apply_keybindings()
        assert kb is not None

    def test_custom_submit_key(self, monkeypatch):
        monkeypatch.setattr(
            "luckyd_code.keybindings.load_keybindings",
            lambda: {"submit": "ctrl-s"},
        )
        kb = apply_keybindings()
        assert kb is not None

    def test_custom_newline_key(self, monkeypatch):
        monkeypatch.setattr(
            "luckyd_code.keybindings.load_keybindings",
            lambda: {"newline": "ctrl-j"},
        )
        kb = apply_keybindings()
        assert kb is not None

    def test_invalid_submit_key_falls_back(self, monkeypatch):
        """Bad key string should not crash — just logs a warning."""
        monkeypatch.setattr(
            "luckyd_code.keybindings.load_keybindings",
            lambda: {"submit": "___invalid___key___"},
        )
        # Should not raise
        kb = apply_keybindings()
        assert kb is not None

    def test_default_bindings_exist(self):
        assert "submit" in DEFAULT_BINDINGS
        assert "newline" in DEFAULT_BINDINGS
        assert "cancel" in DEFAULT_BINDINGS
