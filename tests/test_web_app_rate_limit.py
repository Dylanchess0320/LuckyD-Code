"""Additional tests for web_app.py.

Covers the two main gaps left after test_web_app.py:
  - Rate-limit middleware → 429 when the per-IP token bucket is exhausted
  - get_app() singleton   → second call returns the same FastAPI instance
"""

import sys
import time as time_module

import pytest

pytestmark = pytest.mark.skipif(
    sys.version_info >= (3, 15),
    reason="Python 3.15 + anyio 4.13.0 incompatibility (current_task returns None)",
)

from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

import luckyd_code.web_app as web_app_mod
from luckyd_code.web_app import create_app


# ---------------------------------------------------------------------------
# Shared helpers (mirrors test_web_app.py to keep fixtures consistent)
# ---------------------------------------------------------------------------

def _make_mock_config():
    cfg = MagicMock()
    cfg.api_key = "test-key"
    cfg.base_url = "https://api.deepseek.com/v1"
    cfg.provider = "deepseek"
    cfg.model = "deepseek-chat"
    cfg.max_tokens = 4096
    cfg.temperature = 0.7
    cfg.system_prompt = "You are a helpful assistant."
    cfg.max_context_messages = 100
    return cfg


def _app_patches():
    """Return a context-manager stack that patches out all heavy dependencies."""
    return [
        patch("luckyd_code.web_app.Config", return_value=_make_mock_config()),
        patch("luckyd_code.web_app.memory_module.load_claude_md", return_value=""),
        patch("luckyd_code.indexer.index_project", return_value=""),
    ]


def _create_patched_app():
    """Create a fully-patched FastAPI app for testing."""
    with patch("luckyd_code.web_app.Config", return_value=_make_mock_config()), \
         patch("luckyd_code.web_app.memory_module.load_claude_md", return_value=""), \
         patch("luckyd_code.indexer.index_project", return_value=""):
        return create_app()


# ---------------------------------------------------------------------------
# Rate-limit middleware
# ---------------------------------------------------------------------------

class TestRateLimitMiddleware:

    def test_rate_limit_returns_429_when_bucket_exhausted(self):
        """Exhausting the token bucket for an IP should produce HTTP 429."""
        app = _create_patched_app()
        client = TestClient(app)

        # The bucket key depends on what host TestClient advertises.
        # Make one real request to ensure the bucket entry is created,
        # then drain it to 0 tokens before the assertion request.
        client.post("/api/clear")

        # Find the bucket that was just created and drain it
        state = app.state.web_state
        # TestClient host is either "testclient" or None → "unknown"
        for key in list(state.rate_limit_buckets.keys()):
            state.rate_limit_buckets[key]["tokens"] = 0
            state.rate_limit_buckets[key]["last"] = time_module.time()

        resp = client.post("/api/clear")
        assert resp.status_code == 429
        assert "rate limit" in resp.json()["error"].lower()

    def test_rate_limit_error_body_is_json(self):
        """The 429 response must include a JSON error field."""
        app = _create_patched_app()
        client = TestClient(app)
        client.post("/api/clear")
        state = app.state.web_state
        for key in list(state.rate_limit_buckets.keys()):
            state.rate_limit_buckets[key]["tokens"] = 0
            state.rate_limit_buckets[key]["last"] = time_module.time()
        resp = client.post("/api/clear")
        data = resp.json()
        assert "error" in data

    def test_normal_requests_not_rate_limited(self):
        """A fresh client with a full bucket should always get through."""
        app = _create_patched_app()
        client = TestClient(app)
        resp = client.post("/api/clear")
        # Should not be 429 on the first request
        assert resp.status_code != 429

    def test_static_paths_bypass_rate_limit(self):
        """GET / is excluded from the rate limit (see allowlist in middleware)."""
        app = _create_patched_app()
        client = TestClient(app)

        # Drain ALL known buckets (and prefill any future "unknown" bucket too)
        state = app.state.web_state
        for key in ["testclient", "unknown", "127.0.0.1"]:
            state.rate_limit_buckets[key] = {"tokens": 0, "last": time_module.time()}

        # / is in the exclusion list so it must not return 429
        resp = client.get("/")
        assert resp.status_code != 429

    def test_token_bucket_refills_over_time(self):
        """
        Setting last_request to the past should add tokens on the next request,
        allowing a previously-exhausted IP to be served again.
        """
        app = _create_patched_app()
        client = TestClient(app)
        client.post("/api/clear")  # prime the bucket

        state = app.state.web_state
        for key in list(state.rate_limit_buckets.keys()):
            # Set last_request to 60 seconds ago → bucket should refill to 60
            state.rate_limit_buckets[key]["tokens"] = 0
            state.rate_limit_buckets[key]["last"] = time_module.time() - 60.0

        # After 60 s of inactivity the bucket should be full again
        resp = client.post("/api/clear")
        assert resp.status_code != 429


# ---------------------------------------------------------------------------
# get_app() singleton
# ---------------------------------------------------------------------------

class TestGetAppSingleton:

    def setup_method(self):
        # Reset singleton before each test
        web_app_mod._app_instance = None

    def teardown_method(self):
        # Clean up after test so other tests aren't affected
        web_app_mod._app_instance = None

    def test_first_call_creates_instance(self):
        with patch("luckyd_code.web_app.Config", return_value=_make_mock_config()), \
             patch("luckyd_code.web_app.memory_module.load_claude_md", return_value=""), \
             patch("luckyd_code.indexer.index_project", return_value=""):
            app = web_app_mod.get_app()
        assert app is not None

    def test_second_call_returns_same_instance(self):
        with patch("luckyd_code.web_app.Config", return_value=_make_mock_config()), \
             patch("luckyd_code.web_app.memory_module.load_claude_md", return_value=""), \
             patch("luckyd_code.indexer.index_project", return_value=""):
            app1 = web_app_mod.get_app()
            app2 = web_app_mod.get_app()
        assert app1 is app2

    def test_singleton_create_app_called_only_once(self):
        call_count = {"n": 0}
        real_create = web_app_mod.create_app

        def counting_create(*args, **kwargs):
            call_count["n"] += 1
            return real_create(*args, **kwargs)

        with patch("luckyd_code.web_app.create_app", side_effect=counting_create), \
             patch("luckyd_code.web_app.Config", return_value=_make_mock_config()), \
             patch("luckyd_code.web_app.memory_module.load_claude_md", return_value=""), \
             patch("luckyd_code.indexer.index_project", return_value=""):
            web_app_mod.get_app()
            web_app_mod.get_app()
            web_app_mod.get_app()

        assert call_count["n"] == 1


# ---------------------------------------------------------------------------
# create_app — Config.validate() exception path
# ---------------------------------------------------------------------------

class TestCreateAppConfigValidation:

    def test_config_validation_warning_does_not_crash(self):
        """
        If Config.validate() raises ValueError, create_app() should log a warning
        and continue — not crash.
        """
        bad_config = _make_mock_config()
        bad_config.validate.side_effect = ValueError("missing API key")

        with patch("luckyd_code.web_app.Config", return_value=bad_config), \
             patch("luckyd_code.web_app.memory_module.load_claude_md", return_value=""), \
             patch("luckyd_code.indexer.index_project", return_value=""):
            # Should not raise
            app = create_app()

        assert app is not None

    def test_mcp_load_failure_does_not_crash(self):
        """
        If loading MCP servers fails, create_app() should log a warning
        and return a valid app.
        """
        with patch("luckyd_code.web_app.Config", return_value=_make_mock_config()), \
             patch("luckyd_code.web_app.memory_module.load_claude_md", return_value=""), \
             patch("luckyd_code.indexer.index_project", return_value=""), \
             patch("luckyd_code.mcp.client.MCPManager.load_from_config",
                   side_effect=Exception("MCP failed")):
            app = create_app()

        assert app is not None
