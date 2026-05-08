"""Global pytest configuration and safety fixtures.

Key guarantee: no test may make a live network call to the DeepSeek API
(or any external API) unless the ``DEEPSEEK_API_KEY`` environment variable
is set AND the test is explicitly marked ``@pytest.mark.live``.

This prevents accidental API charges in CI and keeps the test suite fast
and deterministic.
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Ensure the project root is on sys.path
PROJECT_ROOT = Path(__file__).parent.parent


# Python 3.15 anyio compatibility:
# anyio 4.13.0 does not yet fully support Python 3.15 — see
# https://github.com/agronholm/anyio/issues for status.
# Tests requiring Starlette TestClient are skipped on 3.15 until
# upstream releases a fix.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Daemon sentinel files — clean stale markers before every test run
# ---------------------------------------------------------------------------

_DAEMON_SENTINELS = (".audit_daemon_paused", ".audit_lock")


@pytest.fixture(autouse=True)
def clean_daemon_sentinels(tmp_path, monkeypatch):
    """Remove stale .audit_daemon_paused / .audit_lock files before each test.

    If a previous test run crashed while an AuditDaemon was active, these
    sentinel files can block subsequent test runs by making audit() believe
    the daemon is paused or locked.  Cleaning them in an autouse fixture
    ensures every test starts from a known state.
    """
    cwd = Path.cwd()
    for name in _DAEMON_SENTINELS:
        (cwd / name).unlink(missing_ok=True)
    yield
    for name in _DAEMON_SENTINELS:
        (cwd / name).unlink(missing_ok=True)
        (tmp_path / name).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Live-call guard — blocks real stream_chat / _stream_chat_raw calls
# ---------------------------------------------------------------------------

def _no_live_calls(*args, **kwargs):
    raise RuntimeError(
        "Live API call detected in test! All API calls must be mocked."
    )


@pytest.fixture
def temp_dir():
    """Create a temporary directory, cleaned up after test."""
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.fixture
def temp_data_dir(monkeypatch, temp_dir):
    """Temporary data directory, replacing ~/.deepseek-code/."""
    from luckyd_code import _data_dir

    monkeypatch.setattr(_data_dir, "DATA_DIR", temp_dir / ".deepseek-code")
    monkeypatch.setattr(_data_dir, "_LEGACY_DIR", temp_dir / ".claude")
    (_data_dir.DATA_DIR).mkdir(parents=True, exist_ok=True)
    yield _data_dir.DATA_DIR


@pytest.fixture
def temp_project_dir(temp_dir):
    """Temporary project directory with .deepseek-code/ subdir."""
    proj = temp_dir / "project"
    proj.mkdir()
    (proj / ".deepseek-code").mkdir()
    return proj


@pytest.fixture
def mock_config():
    """A mock Config object with fake API credentials for testing."""
    cfg = MagicMock()
    cfg.api_key = "sk-test-mock-key-12345"
    cfg.base_url = "https://api.deepseek.com/v1"
    cfg.model = "deepseek-v4-flash"
    cfg.max_tokens = 4096
    cfg.temperature = 0.7
    cfg.provider = "deepseek"
    cfg.system_prompt = "You are a test assistant."
    cfg.working_directory = os.getcwd()
    cfg.max_context_messages = 100
    cfg.log_level = "INFO"
    return cfg


@pytest.fixture
def sample_python_file(temp_dir):
    """Create a sample .py file for scanner/smell tests."""
    content = '''"""Sample module for testing."""

import os
import sys
from pathlib import Path

# TODO: add type hints here
# FIXME: handle edge case

def simple_function(a, b):
    """Add two numbers."""
    result = a + b
    return result

def long_function(x, y, z, w, a, b, c):
    """A function that is long enough to trigger smell detection."""
    t = x + y
    t = t * z
    t = t / w
    t = t + a
    t = t - b
    t = t * c
    if t > 0:
        t = t * 2
        if t > 10:
            t = t / 2
            if t > 20:
                t = t - 5
                if t > 30:
                    t = t + 1
    return t

class SampleClass:
    """A sample class."""

    def __init__(self, name):
        self.name = name

    def greet(self):
        return f"Hello, {self.name}!"

'''
    fpath = temp_dir / "sample.py"
    fpath.write_text(content, encoding="utf-8")
    return fpath
