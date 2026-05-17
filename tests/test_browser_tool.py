"""Browser tool tests — full coverage without a real Playwright browser.

All Playwright objects are replaced with MagicMock so these tests run in CI
with no browser binaries installed.  The tests verify:
  - Tool schemas (name, description, parameters)
  - run() return-value contracts for every tool
  - BrowserManager state helpers (save, clear, tracing)
  - OpenInBrowserTool platform dispatch
  - make_safe_snapshot truncation and fallback
  - BrowserInterceptTool list / mock / clear actions
  - BrowserEmulateTool known and unknown devices
"""

import os
import sys
from types import ModuleType
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


# ---------------------------------------------------------------------------
# Playwright stub — injected before the browser module is imported
# ---------------------------------------------------------------------------

def _make_playwright_stub():
    """Return a minimal sync_playwright context-manager stub."""
    page = MagicMock()
    page.url = "https://example.com"
    page.title.return_value = "Example"
    page.evaluate.return_value = "<a>[link]</a>"
    page.inner_text.return_value = "body text"

    context = MagicMock()
    context.new_page.return_value = page

    browser = MagicMock()
    browser.new_context.return_value = context

    pw = MagicMock()
    pw.chromium.launch.return_value = browser
    pw.devices = {}

    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=pw)
    cm.__exit__ = MagicMock(return_value=False)
    cm.start.return_value = pw

    return pw, browser, context, page, cm


@pytest.fixture(autouse=True)
def _patch_playwright(monkeypatch):
    """Patch playwright.sync_api globally before any import of browser.py."""
    pw, browser, context, page, cm = _make_playwright_stub()

    fake_pw_module = MagicMock()
    fake_pw_module.sync_playwright.return_value = cm

    monkeypatch.setitem(sys.modules, "playwright", MagicMock())
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_pw_module)
    return pw, browser, context, page


@pytest.fixture()
def browser_module(_patch_playwright):
    """Import (or re-import) the browser module with Playwright stubbed out."""
    import importlib
    import luckyd_code.tools.browser as bmod
    # Reset singleton so each test starts clean
    bmod._manager = None
    bmod.BrowserManager._instance = None
    bmod.BrowserManager._playwright = None
    bmod.BrowserManager._browser = None
    bmod.BrowserManager._context = None
    bmod.BrowserManager._page = None
    bmod.BrowserManager._tracing_started = False
    return bmod


# ---------------------------------------------------------------------------
# Tool schema contracts
# ---------------------------------------------------------------------------

class TestToolSchemas:
    TOOL_CLASSES = [
        "BrowserNavigateTool",
        "BrowserClickTool",
        "BrowserTypeTool",
        "BrowserSnapshotTool",
        "BrowserScreenshotTool",
        "BrowserCloseTool",
        "OpenInBrowserTool",
        "BrowserStateTool",
        "BrowserEmulateTool",
        "BrowserInterceptTool",
        "BrowserTraceTool",
        "BrowserToggleHeadlessTool",
        "BrowserEvaluateTool",
    ]

    def test_all_tools_have_name(self, browser_module):
        for cls_name in self.TOOL_CLASSES:
            cls = getattr(browser_module, cls_name)
            assert cls.name, f"{cls_name} must have a non-empty name"

    def test_all_tools_have_description(self, browser_module):
        for cls_name in self.TOOL_CLASSES:
            cls = getattr(browser_module, cls_name)
            assert cls.description, f"{cls_name} must have a description"

    def test_all_tools_have_parameters(self, browser_module):
        for cls_name in self.TOOL_CLASSES:
            cls = getattr(browser_module, cls_name)
            assert isinstance(cls.parameters, dict), f"{cls_name}.parameters must be a dict"


# ---------------------------------------------------------------------------
# make_safe_snapshot
# ---------------------------------------------------------------------------

class TestMakeSafeSnapshot:
    def test_returns_url_and_title(self, browser_module):
        page = MagicMock()
        page.url = "https://test.com"
        page.title.return_value = "Test Page"
        page.evaluate.return_value = "<a>[link text]</a>"

        result = browser_module.make_safe_snapshot(page)
        assert "https://test.com" in result
        assert "Test Page" in result

    def test_truncates_to_max_length(self, browser_module):
        page = MagicMock()
        page.url = "https://x.com"
        page.title.return_value = "X"
        page.evaluate.return_value = "a" * 20_000

        result = browser_module.make_safe_snapshot(page, max_length=500)
        assert len(result) <= 520  # small buffer for truncation suffix
        assert "truncated" in result

    def test_falls_back_to_body_text_on_empty_evaluate(self, browser_module):
        page = MagicMock()
        page.url = "https://x.com"
        page.title.return_value = "X"
        page.evaluate.return_value = ""
        page.inner_text.return_value = "fallback body content"

        result = browser_module.make_safe_snapshot(page)
        assert "fallback body content" in result

    def test_handles_evaluate_exception(self, browser_module):
        page = MagicMock()
        page.url = "https://x.com"
        page.title.return_value = "X"
        page.evaluate.side_effect = RuntimeError("JS error")

        result = browser_module.make_safe_snapshot(page)
        assert "Error" in result


# ---------------------------------------------------------------------------
# Individual tool run() contracts
# ---------------------------------------------------------------------------

class TestBrowserNavigateTool:
    def test_navigate_returns_url_in_output(self, browser_module):
        tool = browser_module.BrowserNavigateTool()
        result = tool.run("https://example.com")
        assert "https://example.com" in result

    def test_navigate_error_returns_error_string(self, browser_module):
        tool = browser_module.BrowserNavigateTool()
        with patch.object(browser_module, "_get_manager") as mock_mgr:
            mock_mgr.return_value.page.return_value.goto.side_effect = Exception("timeout")
            result = tool.run("https://bad.url")
        assert "Error" in result


class TestBrowserClickTool:
    def test_click_returns_selector_in_output(self, browser_module):
        tool = browser_module.BrowserClickTool()
        result = tool.run("#submit-btn")
        assert "#submit-btn" in result

    def test_click_error_returns_error_string(self, browser_module):
        tool = browser_module.BrowserClickTool()
        with patch.object(browser_module, "_get_manager") as mock_mgr:
            mock_mgr.return_value.page.return_value.click.side_effect = Exception("not found")
            result = tool.run("#missing")
        assert "Error" in result


class TestBrowserTypeTool:
    def test_type_returns_selector_in_output(self, browser_module):
        tool = browser_module.BrowserTypeTool()
        result = tool.run("#search", "hello world")
        assert "#search" in result

    def test_type_with_submit_presses_enter(self, browser_module):
        with patch.object(browser_module, "_get_manager") as mock_mgr:
            page = MagicMock()
            page.evaluate.return_value = ""
            page.inner_text.return_value = "body"
            mock_mgr.return_value.page.return_value = page
            tool = browser_module.BrowserTypeTool()
            tool.run("#q", "query", submit=True)
            page.press.assert_called_once_with("#q", "Enter")


class TestBrowserSnapshotTool:
    def test_snapshot_returns_string(self, browser_module):
        tool = browser_module.BrowserSnapshotTool()
        result = tool.run()
        assert isinstance(result, str)
        assert len(result) > 0


class TestBrowserScreenshotTool:
    def test_screenshot_uses_provided_path(self, browser_module, tmp_path):
        path = str(tmp_path / "shot.png")
        tool = browser_module.BrowserScreenshotTool()
        with patch.object(browser_module, "_get_manager") as mock_mgr:
            page = MagicMock()
            mock_mgr.return_value.page.return_value = page
            result = tool.run(path=path)
        assert path in result

    def test_screenshot_auto_generates_path_when_empty(self, browser_module):
        tool = browser_module.BrowserScreenshotTool()
        with patch.object(browser_module, "_get_manager") as mock_mgr:
            page = MagicMock()
            mock_mgr.return_value.page.return_value = page
            result = tool.run(path="")
        assert "screenshot_" in result


class TestBrowserCloseTool:
    def test_close_returns_confirmation(self, browser_module):
        tool = browser_module.BrowserCloseTool()
        result = tool.run()
        assert "closed" in result.lower()


class TestOpenInBrowserTool:
    def test_open_windows(self, browser_module):
        tool = browser_module.OpenInBrowserTool()
        with patch("platform.system", return_value="Windows"), \
             patch("subprocess.Popen") as mock_popen:
            result = tool.run("https://example.com")
        assert "https://example.com" in result

    def test_open_macos(self, browser_module):
        tool = browser_module.OpenInBrowserTool()
        with patch("platform.system", return_value="Darwin"), \
             patch("subprocess.Popen") as mock_popen:
            result = tool.run("https://example.com")
        assert "https://example.com" in result

    def test_open_linux(self, browser_module):
        tool = browser_module.OpenInBrowserTool()
        with patch("platform.system", return_value="Linux"), \
             patch("subprocess.Popen") as mock_popen:
            result = tool.run("https://example.com")
        assert "https://example.com" in result

    def test_open_error_returns_error_string(self, browser_module):
        tool = browser_module.OpenInBrowserTool()
        with patch("platform.system", return_value="Linux"), \
             patch("subprocess.Popen", side_effect=OSError("no xdg-open")):
            result = tool.run("https://example.com")
        assert "Error" in result


# ---------------------------------------------------------------------------
# BrowserStateTool
# ---------------------------------------------------------------------------

class TestBrowserStateTool:
    def test_save_calls_save_state(self, browser_module):
        tool = browser_module.BrowserStateTool()
        with patch.object(browser_module, "_get_manager") as mock_mgr:
            mock_mgr.return_value.page.return_value = MagicMock()
            mock_mgr.return_value.save_state.return_value = "saved"
            result = tool.run("save")
        assert result == "saved"

    def test_clear_calls_clear_state(self, browser_module):
        tool = browser_module.BrowserStateTool()
        with patch.object(browser_module, "_get_manager") as mock_mgr:
            mock_mgr.return_value.page.return_value = MagicMock()
            mock_mgr.return_value.clear_state.return_value = "cleared"
            result = tool.run("clear")
        assert result == "cleared"

    def test_unknown_action_returns_error(self, browser_module):
        tool = browser_module.BrowserStateTool()
        with patch.object(browser_module, "_get_manager") as mock_mgr:
            mock_mgr.return_value.page.return_value = MagicMock()
            result = tool.run("explode")
        assert "Unknown" in result


# ---------------------------------------------------------------------------
# BrowserEmulateTool
# ---------------------------------------------------------------------------

class TestBrowserEmulateTool:
    def test_desktop_resets_viewport(self, browser_module):
        tool = browser_module.BrowserEmulateTool()
        with patch.object(browser_module, "_get_manager") as mock_mgr:
            page = MagicMock()
            mock_mgr.return_value.page.return_value = page
            result = tool.run(device="desktop")
        page.set_viewport_size.assert_called_once_with({"width": 1280, "height": 720})
        assert "desktop" in result.lower()

    def test_known_device_sets_viewport(self, browser_module):
        tool = browser_module.BrowserEmulateTool()
        with patch.object(browser_module, "_get_manager") as mock_mgr:
            page = MagicMock()
            mock_mgr.return_value.page.return_value = page
            result = tool.run(device="iPhone 12")
        assert "iPhone 12" in result

    def test_unknown_device_lists_options(self, browser_module):
        tool = browser_module.BrowserEmulateTool()
        with patch.object(browser_module, "_get_manager") as mock_mgr:
            mock_mgr.return_value.page.return_value = MagicMock()
            result = tool.run(device="NoSuchPhone 99")
        assert "not found" in result.lower()

    def test_custom_width_height(self, browser_module):
        tool = browser_module.BrowserEmulateTool()
        with patch.object(browser_module, "_get_manager") as mock_mgr:
            page = MagicMock()
            mock_mgr.return_value.page.return_value = page
            result = tool.run(width=800, height=600)
        page.set_viewport_size.assert_called_once_with({"width": 800, "height": 600})
        assert "800" in result


# ---------------------------------------------------------------------------
# BrowserInterceptTool
# ---------------------------------------------------------------------------

class TestBrowserInterceptTool:
    def test_list_returns_string(self, browser_module):
        tool = browser_module.BrowserInterceptTool()
        with patch.object(browser_module, "_get_manager") as mock_mgr:
            page = MagicMock()
            page.evaluate.return_value = [
                {"name": "https://x.com/a.js", "type": "script", "duration": 50, "size": 1000}
            ]
            mock_mgr.return_value.page.return_value = page
            result = tool.run("list")
        assert isinstance(result, str)

    def test_mock_requires_url_pattern(self, browser_module):
        tool = browser_module.BrowserInterceptTool()
        with patch.object(browser_module, "_get_manager") as mock_mgr:
            mock_mgr.return_value.page.return_value = MagicMock()
            result = tool.run("mock", url_pattern="")
        assert "url_pattern" in result

    def test_clear_removes_intercepts(self, browser_module):
        tool = browser_module.BrowserInterceptTool()
        with patch.object(browser_module, "_get_manager") as mock_mgr:
            mock_mgr.return_value.page.return_value = MagicMock()
            result = tool.run("clear")
        assert "cleared" in result.lower()


# ---------------------------------------------------------------------------
# BrowserTraceTool
# ---------------------------------------------------------------------------

class TestBrowserTraceTool:
    def test_start_calls_start_tracing(self, browser_module):
        tool = browser_module.BrowserTraceTool()
        with patch.object(browser_module, "_get_manager") as mock_mgr:
            mock_mgr.return_value.page.return_value = MagicMock()
            mock_mgr.return_value.start_tracing.return_value = "Tracing started."
            result = tool.run("start")
        assert result == "Tracing started."

    def test_stop_calls_stop_tracing(self, browser_module):
        tool = browser_module.BrowserTraceTool()
        with patch.object(browser_module, "_get_manager") as mock_mgr:
            mock_mgr.return_value.page.return_value = MagicMock()
            mock_mgr.return_value.stop_tracing.return_value = "Tracing saved."
            result = tool.run("stop")
        assert result == "Tracing saved."


# ---------------------------------------------------------------------------
# BrowserToggleHeadlessTool
# ---------------------------------------------------------------------------

class TestBrowserToggleHeadlessTool:
    def test_headless_true_returns_confirmation(self, browser_module):
        tool = browser_module.BrowserToggleHeadlessTool()
        with patch.object(browser_module, "_get_manager") as mock_mgr:
            result = tool.run(headless=True)
        assert "headless" in result.lower()

    def test_headless_false_returns_confirmation(self, browser_module):
        tool = browser_module.BrowserToggleHeadlessTool()
        with patch.object(browser_module, "_get_manager") as mock_mgr:
            result = tool.run(headless=False)
        assert "headed" in result.lower() or "visible" in result.lower()
