"""Tests for init.py — project initialization."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from luckyd_code.init import init_project, MEMORY_FILENAMES, DEFAULT_MEMORY_MD


class TestInitProject:
    def test_creates_memory_md_when_neither_exists(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = init_project()
        assert "Created MEMORY.md" in result
        assert (tmp_path / "MEMORY.md").exists()

    def test_memory_md_has_correct_content(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        init_project()
        content = (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
        assert "# MEMORY.md" in content
        assert "Tech Stack" in content

    def test_skips_if_memory_md_exists(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "MEMORY.md").write_text("existing content")
        result = init_project()
        assert "already exists" in result
        assert (tmp_path / "MEMORY.md").read_text() == "existing content"

    def test_skips_if_claude_md_exists(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "CLAUDE.md").write_text("claude content")
        result = init_project()
        assert "already exists" in result
        assert not (tmp_path / "MEMORY.md").exists()

    def test_memory_filenames_constant(self):
        assert "MEMORY.md" in MEMORY_FILENAMES
        assert "CLAUDE.md" in MEMORY_FILENAMES

    def test_default_memory_md_constant(self):
        assert "# MEMORY.md" in DEFAULT_MEMORY_MD
        assert "Tech Stack" in DEFAULT_MEMORY_MD
        assert "Guidelines" in DEFAULT_MEMORY_MD

    def test_does_not_create_claude_md(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        init_project()
        assert not (tmp_path / "CLAUDE.md").exists()
        assert (tmp_path / "MEMORY.md").exists()
