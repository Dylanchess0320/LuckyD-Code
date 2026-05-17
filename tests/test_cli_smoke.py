"""CLI smoke tests — verify the entry point works without a live API key.

These tests exercise the argument-parsing and early-exit paths (--version,
--help) that run entirely without a DeepSeek key or network access.  They
catch broken imports, bad refactors of cli_entry.py, and packaging issues
that would make `ldc` fail to start.
"""

import subprocess
import sys


def _run(*args: str) -> subprocess.CompletedProcess:
    """Run the CLI via `python -m luckyd_code` and capture output."""
    return subprocess.run(
        [sys.executable, "-m", "luckyd_code", *args],
        capture_output=True,
        text=True,
        timeout=15,
    )


class TestCLISmoke:
    def test_version_flag_exits_zero(self):
        result = _run("--version")
        assert result.returncode == 0, result.stderr

    def test_version_output_contains_version_string(self):
        result = _run("--version")
        assert "LuckyD Code v" in result.stdout

    def test_version_output_matches_package_version(self):
        from luckyd_code import __version__
        result = _run("--version")
        assert __version__ in result.stdout

    def test_help_flag_exits_zero(self):
        result = _run("--help")
        assert result.returncode == 0, result.stderr

    def test_help_output_mentions_model_flag(self):
        result = _run("--help")
        assert "--model" in result.stdout

    def test_help_output_mentions_web_flag(self):
        result = _run("--help")
        assert "--web" in result.stdout

    def test_unknown_flag_exits_nonzero(self):
        result = _run("--this-flag-does-not-exist")
        assert result.returncode != 0
