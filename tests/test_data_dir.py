"""Tests for luckyd_code._data_dir — data directory resolution."""

import os
import shutil
from pathlib import Path


from luckyd_code import _data_dir


class TestDataDir:
    """Tests for user-global data directory functions."""

    def test_default_data_dir_is_home_luckyd_code(self):
        """DATA_DIR should be ~/.luckyd-code/."""
        expected = Path.home() / ".luckyd-code"
        assert _data_dir.DATA_DIR == expected

    def test_legacy_dir_is_home_claude(self):
        """LEGACY_DIR should be ~/.deepseek-code/."""
        expected = Path.home() / ".deepseek-code"
        assert _data_dir._LEGACY_DIR == expected

    def test_ensure_data_dir_creates_directory(self, temp_data_dir, monkeypatch):
        """ensure_data_dir() should create the directory if missing."""
        # Remove it first
        if temp_data_dir.exists():
            shutil.rmtree(temp_data_dir, ignore_errors=True)

        result = _data_dir.ensure_data_dir()
        assert result == temp_data_dir
        assert temp_data_dir.exists()
        assert temp_data_dir.is_dir()

    def test_data_path_returns_subpath(self, temp_data_dir):
        """data_path() should return a path under the data dir."""
        result = _data_dir.data_path("sessions", "test.json")
        expected = temp_data_dir / "sessions" / "test.json"
        assert result == expected

    def test_data_path_multiple_parts(self, temp_data_dir):
        """data_path() with multiple parts joins them properly."""
        result = _data_dir.data_path("a", "b", "c.txt")
        assert result == temp_data_dir / "a" / "b" / "c.txt"

    def test_legacy_path_returns_correct_location(self):
        """legacy_path() should return path under ~/.claude/."""
        result = _data_dir.legacy_path("old_config.json")
        assert result == _data_dir._LEGACY_DIR / "old_config.json"

    def test_migration_from_legacy(self, temp_data_dir, monkeypatch, caplog):
        """Migration should copy legacy -> new when old exists and new doesn't."""
        legacy = _data_dir._LEGACY_DIR
        target = temp_data_dir

        # Clean slate
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        if legacy.exists():
            shutil.rmtree(legacy, ignore_errors=True)

        # Create legacy with content
        legacy.mkdir(parents=True)
        (legacy / "test.txt").write_text("legacy data", encoding="utf-8")

        # Trigger migration via ensure
        import logging
        with caplog.at_level(logging.INFO):
            _data_dir.ensure_data_dir()

        assert target.exists()
        assert (target / "test.txt").exists()
        assert (target / "test.txt").read_text() == "legacy data"


class TestProjectDataDir:
    """Tests for project-local data directory functions."""

    def test_ensure_project_data_dir_creates(self, temp_dir):
        """_ensure_project_data_dir should create .luckyd-code/ in project."""
        proj = temp_dir / "myproject"
        proj.mkdir()
        result = _data_dir._ensure_project_data_dir(proj)
        assert result == proj / ".luckyd-code"
        assert result.exists()

    def test_project_data_path_returns_subpath(self, temp_dir):
        """project_data_path() should join relative to project dir."""
        proj = temp_dir / "myproject"
        proj.mkdir()
        result = _data_dir.project_data_path("plans", "test.json", root=proj)
        expected = proj / ".luckyd-code" / "plans" / "test.json"
        assert result == expected

    def test_project_data_path_defaults_to_cwd(self, temp_dir, monkeypatch):
        """project_data_path() uses cwd when root is None."""
        proj = temp_dir / "myproject"
        proj.mkdir()
        original_cwd = os.getcwd()
        monkeypatch.chdir(proj)
        try:
            result = _data_dir.project_data_path("cache", root=None)
            # Use resolve() — on macOS /var is a symlink to /private/var
            assert result.resolve() == (proj / ".luckyd-code" / "cache").resolve()
        finally:
            os.chdir(original_cwd)

    def test_project_legacy_path(self, temp_dir):
        """project_legacy_path returns the legacy (.deepseek-code) variant."""
        proj = temp_dir / "myproject"
        proj.mkdir()
        result = _data_dir.project_legacy_path("old", root=proj)
        expected = proj / ".deepseek-code" / "old"
        assert result == expected

    def test_project_migration_from_legacy(self, temp_dir):
        """Project migration copies .deepseek-code/ -> .luckyd-code/."""
        proj = temp_dir / "myproject"
        proj.mkdir()
        legacy = proj / ".deepseek-code"
        legacy.mkdir()
        (legacy / "data.txt").write_text("project legacy", encoding="utf-8")

        result = _data_dir._ensure_project_data_dir(proj)
        assert result.exists()
        assert (proj / ".luckyd-code" / "data.txt").read_text() == "project legacy"
