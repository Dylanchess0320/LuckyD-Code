"""Tests for the path validation module."""

import os
import tempfile
from pathlib import Path

import pytest

from luckyd_code.tools.path_validate import safe_resolve, validate_file_path, sanitize_filename


class TestSafeResolve:
    def test_valid_path_resolves(self):
        """A valid path should resolve correctly."""
        with tempfile.TemporaryDirectory() as tmp:
            result = safe_resolve(tmp, working_dir=tmp)
            assert str(result) == str(Path(tmp).resolve())

    def test_path_traversal_raises(self):
        """Path traversal outside working dir should raise ValueError."""
        with tempfile.TemporaryDirectory() as tmp:
            with pytest.raises(ValueError, match="Path traversal blocked"):
                safe_resolve("../outside", working_dir=tmp)

    def test_path_traversal_absolute_raises(self):
        """Absolute path outside working dir should raise ValueError."""
        with tempfile.TemporaryDirectory() as tmp:
            # Use a path that's definitely outside
            with pytest.raises(ValueError, match="Path traversal blocked"):
                safe_resolve("C:\\Windows\\System32", working_dir=tmp)

    def test_nested_path_within_dir(self):
        """Nested paths within the working dir should work."""
        with tempfile.TemporaryDirectory() as tmp:
            sub = Path(tmp) / "subdir" / "nested"
            sub.mkdir(parents=True)
            result = safe_resolve(str(sub), working_dir=tmp)
            assert str(result) == str(sub.resolve())

    def test_default_working_dir_is_cwd(self):
        """Default working dir should be current directory."""
        cwd = os.getcwd()
        result = safe_resolve(cwd)
        assert str(result) == str(Path(cwd).resolve())


class TestValidateFilePath:
    def test_existing_file_validates(self):
        """An existing file should validate successfully."""
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "test.txt"
            file_path.write_text("hello")
            result = validate_file_path(str(file_path), must_exist=True, working_dir=tmp)
            assert str(result) == str(file_path.resolve())

    def test_nonexistent_file_raises(self):
        """A nonexistent file with must_exist=True should raise."""
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "nonexistent.txt"
            with pytest.raises(FileNotFoundError, match="Path does not exist"):
                validate_file_path(str(file_path), must_exist=True, working_dir=tmp)

    def test_nonexistent_file_without_flag(self):
        """A nonexistent file without must_exist should not raise."""
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "nonexistent.txt"
            result = validate_file_path(str(file_path), must_exist=False, working_dir=tmp)
            assert str(result) == str(file_path.resolve())

    def test_traversal_raises(self):
        """Path traversal should raise ValueError."""
        with pytest.raises(ValueError, match="Path traversal blocked"):
            validate_file_path("../etc/passwd")


class TestSanitizeFilename:
    def test_simple_name(self):
        """Simple filenames should pass through."""
        assert sanitize_filename("hello.py") == "hello.py"

    def test_removes_path_separators(self):
        """Path separators should be replaced."""
        result = sanitize_filename("a/b/c.txt")
        assert "/" not in result
        assert "\\" not in result

    def test_removes_dangerous_chars(self):
        """Dangerous characters should be replaced."""
        result = sanitize_filename('file<>:"|?*.txt')
        assert "<" not in result
        assert ">" not in result
        assert '"' not in result
        assert "|" not in result
        assert "?" not in result

    def test_removes_null_bytes(self):
        """Null bytes should be removed."""
        result = sanitize_filename("file\x00.txt")
        assert "\x00" not in result

    def test_truncates_long_names(self):
        """Very long names should be truncated."""
        long_name = "a" * 300 + ".py"
        result = sanitize_filename(long_name)
        assert len(result) <= 200
