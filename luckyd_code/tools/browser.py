"""Playwright browser automation tools.

Provides a persistent browser session that the AI agent can use to
navigate, click, type, screenshot, and extract content from web pages.

Supports headless (default) and headed modes. Set via settings:
  /config set browser_headless false

Features:
  - Cookie/session persistence across tool calls (storage_state)
  - Network interception for mocking/spying on requests
  - Mobile device emulation (viewport, touch, user-agent)
  - Browser tracing for session recording
  - Runtime headless toggle
  - Visual content extraction via screenshot
"""

import os
import uuid

from .registry import Tool
from ..settings import load_settings


class BrowserManager:
    """Singleton browser session manager.

    Supports cookie/session persistence via Playwright's storage_state.
    Call save_state() to persist cookies and localStorage to disk,
    and it will auto-restore on the next page creation.
    """

    _instance = None
    _playwright = None
    _browser = None
    _context = None
    _page = None
    _headless = None
    _state_dir = None
    _tracing_started = False
    _intercept_handler = None

    @classmethod
    def _state_path(cls) -> str:
        """Path for persistent browser state (cookies, localStorage)."""
        if cls._state_dir is None:
            cls._state_dir = os.path.join(
                os.environ.get(
                    "LUCKYD_DATA_DIR",
                    os.path.join(os.path.expanduser("~"), ".luckyd_code"),
                ),
                "browser",
            )
        os.makedirs(cls._state_dir, exist_ok=True)
        return os.path.join(cls._state_dir, "state.json")

    def _ensure(self, headless: bool | None = None, emulate_device: str | None = None):
        if self._page is None:
            try:
                from playwright.sync_api import sync_playwright
            except ImportError as exc:
                raise RuntimeError(
                    "Playwright is not installed. "
                    "Install it with: pip install luckyd-code[browser]"
                ) from exc
            if headless is None:
                settings = load_settings()
                headless = settings.get("browser_headless", True)
            BrowserManager._headless = headless
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(
                headless=headless,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                ],
            )

            # Build context options
            context_opts: dict = {
                "viewport": {"width": 1280, "height": 720},
                "user_agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            }

            # Mobile device emulation
            if emulate_device:
                try:
                    devices = self._playwright.devices
                    if emulate_device in devices:
                        device = devices[emulate_device]
                        context_opts.update({k: v for k, v in device.items()
                                             if k not in ("defaultBrowserType",)})
                except Exception:
                    pass

            # Restore saved state (cookies, localStorage)
            state_path = self._state_path()
            if os.path.exists(state_path):
                try:
                    context_opts["storage_state"] = state_path
                except Exception:
                    pass

            self._context = self._browser.new_context(**context_opts)

            # Enable network interception if requested
            if self._intercept_handler:
                self._context.route("**/*", self._intercept_handler)

            self._page = self._context.new_page()
        return self._page

    def page(self):
        return self._ensure()

    def restart(self, headless: bool | None = None):
        """Close and reopen browser — useful for toggling headless mode."""
        self.close()
        BrowserManager._headless = headless
        self._ensure(headless=headless)

    def save_state(self) -> str:
        """Persist cookies and localStorage to disk."""
        if self._context:
            state_path = self._state_path()
            self._context.storage_state(path=state_path)
            return f"Browser state saved to {state_path}"
        return "No active browser context to save."

    def clear_state(self) -> str:
        """Delete persisted browser state (cookies, localStorage)."""
        state_path = self._state_path()
        if os.path.exists(state_path):
            os.remove(state_path)
            return "Browser state cleared."
        return "No saved state to clear."

    def start_tracing(self) -> str:
        """Start recording a browser trace (for debugging)."""
        if self._context and not self._tracing_started:
            self._context.tracing.start(screenshots=True, snapshots=True)
            BrowserManager._tracing_started = True
            return "Tracing started."
        return "Tracing already active or no context."

    def stop_tracing(self) -> str:
        """Stop tracing and save the trace file."""
        if self._context and self._tracing_started:
            trace_dir = self._state_dir or os.getcwd()
            trace_path = os.path.join(
                trace_dir, f"trace_{uuid.uuid4().hex[:8]}.zip"
            )
            self._context.tracing.stop(path=trace_path)
            BrowserManager._tracing_started = False
            return f"Tracing saved to {trace_path}"
        return "No active tracing to stop."

    def set_intercept_handler(self, handler=None):
        """Set a network route handler for the current context.

        handler should be a callable(route) or None to clear.
        """
        BrowserManager._intercept_handler = handler
        if self._context:
            if handler:
                self._context.route("**/*", handler)
            else:
                self._context.unroute("**/*")

    def close(self):
        if self._tracing_started:
            try:
                self.stop_tracing()
            except Exception:
                pass
        if self._context:
            self._context.close()
            self._context = None
        if self._browser:
            self._browser.close()
            self._browser = None
        if self._playwright:
            self._playwright.stop()
            self._playwright = None
        self._page = None
        BrowserManager._tracing_started = False

    @classmethod
    def get(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance


_manager = None


def _get_manager():
    global _manager
    if _manager is None:
        _manager = BrowserManager()
    return _manager


def make_safe_snapshot(page, max_length=8000) -> str:
    """Extract an accessibility-style snapshot from the page."""
    try:
        title = page.title()
        url = page.url

        parts: list[str] = [f"URL: {url}", f"Title: {title}", ""]

        # Get all interactive elements via JavaScript
        snapshot_js = """
        () => {
            const results = [];
            const selectors = [
                'a[href]', 'button', 'input:not([type="hidden"])',
                'select', 'textarea', '[role="button"]',
                '[role="link"]', '[role="option"]', '[role="tab"]',
                '[role="menuitem"]', '[role="checkbox"]',
                '[role="radio"]', '[role="switch"]',
                'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
                'p', 'li', 'label', 'img[alt]',
                '[tabindex]:not([tabindex="-1"])',
            ];
            const seen = new Set();
            selectors.forEach(sel => {
                document.querySelectorAll(sel).forEach(el => {
                    const rect = el.getBoundingClientRect();
                    if (rect.width === 0 || rect.height === 0) return;
                    const tag = el.tagName.toLowerCase();
                    const text = (el.textContent || '').trim().slice(0, 120);
                    const aria = el.getAttribute('aria-label') || '';
                    const placeholder = el.getAttribute('placeholder') || '';
                    const value = el.getAttribute('value') || '';
                    const href = el.getAttribute('href') || '';
                    const name = el.getAttribute('name') || '';
                    const alt = el.getAttribute('alt') || '';
                    const type = el.getAttribute('type') || '';
                    const role = el.getAttribute('role') || '';

                    const key = tag + '|' + text + '|' + (href || '');
                    if (seen.has(key)) return;
                    seen.add(key);

                    const info = [`<${tag}`];
                    if (role) info.push(` role="${role}"`);
                    if (aria) info.push(` aria="${aria}"`);
                    if (name) info.push(` name="${name}"`);
                    if (type) info.push(` type="${type}"`);
                    if (placeholder) info.push(` placeholder="${placeholder}"`);
                    if (href) info.push(` href="${href}"`);
                    if (alt) info.push(` alt="${alt}"`);
                    if (value) info.push(` value="${value}"`);
                    info.push(`>[${text.slice(0, 80)}]`);
                    info.push(` [box=${Math.round(rect.x)},${Math.round(rect.y)},${Math.round(rect.width)},${Math.round(rect.height)}]`);
                    results.push(info.join(''));
                });
            });
            return results.join('\\n');
        }
        """
        elements = page.evaluate(snapshot_js)

        if elements:
            parts.append("--- Page Elements ---")
            parts.append(elements)
        else:
            # Fallback: get body text
            body_text = page.inner_text("body") or ""
            parts.append(body_text[:5000])

        result = "\n".join(parts)
        if len(result) > max_length:
            result = result[:max_length] + "\n... (truncated)"
        return result
    except Exception as e:
        return f"Error taking snapshot: {e}"


class BrowserNavigateTool(Tool):
    name = "BrowserNavigate"
    description = "Navigate the browser to a URL. Returns page title and summary of elements."
    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to navigate to",
            },
        },
        "required": ["url"],
    }

    def run(self, url: str) -> str:  # type: ignore[override]
        manager = _get_manager()
        page = manager.page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(1000)
            snapshot = make_safe_snapshot(page)
            return f"Navigated to {url}\n\n{snapshot}"
        except Exception as e:
            return f"Error navigating to {url}: {e}"


class BrowserClickTool(Tool):
    name = "BrowserClick"
    description = "Click an element on the page by CSS selector."
    parameters = {
        "type": "object",
        "properties": {
            "selector": {
                "type": "string",
                "description": "CSS selector of the element to click",
            },
        },
        "required": ["selector"],
    }

    def run(self, selector: str) -> str:  # type: ignore[override]
        manager = _get_manager()
        page = manager.page()
        try:
            page.wait_for_selector(selector, timeout=5000)
            page.click(selector)
            page.wait_for_timeout(500)
            snapshot = make_safe_snapshot(page)
            return f"Clicked {selector}\n\n{snapshot}"
        except Exception as e:
            return f"Error clicking {selector}: {e}"


class BrowserTypeTool(Tool):
    name = "BrowserType"
    description = "Type text into an input field."
    parameters = {
        "type": "object",
        "properties": {
            "selector": {
                "type": "string",
                "description": "CSS selector of the input element",
            },
            "text": {
                "type": "string",
                "description": "Text to type",
            },
            "submit": {
                "type": "boolean",
                "description": "Press Enter after typing (default: false)",
            },
        },
        "required": ["selector", "text"],
    }

    def run(self, selector: str, text: str, submit: bool = False) -> str:  # type: ignore[override]
        manager = _get_manager()
        page = manager.page()
        try:
            page.wait_for_selector(selector, timeout=5000)
            page.fill(selector, "")
            page.type(selector, text, delay=20)
            if submit:
                page.press(selector, "Enter")
                page.wait_for_timeout(1000)
            snapshot = make_safe_snapshot(page)
            return f"Typed into {selector}\n\n{snapshot}"
        except Exception as e:
            return f"Error typing into {selector}: {e}"


class BrowserSnapshotTool(Tool):
    name = "BrowserSnapshot"
    description = "Get a text snapshot of the current page (interactive elements, headings, links, etc.)."
    parameters = {
        "type": "object",
        "properties": {},
    }

    def run(self) -> str:  # type: ignore[override]
        manager = _get_manager()
        page = manager.page()
        try:
            return make_safe_snapshot(page)
        except Exception as e:
            return f"Error taking snapshot: {e}"


class BrowserScreenshotTool(Tool):
    name = "BrowserScreenshot"
    description = "Take a screenshot of the current page and save it to a file."
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path to save the screenshot (default: auto-generated in working dir)",
            },
            "full_page": {
                "type": "boolean",
                "description": "Capture full scrollable page (default: false)",
            },
        },
    }

    def run(self, path: str = "", full_page: bool = False) -> str:  # type: ignore[override]
        manager = _get_manager()
        page = manager.page()
        try:
            if not path:
                path = os.path.join(os.getcwd(), f"screenshot_{uuid.uuid4().hex[:8]}.png")
            page.screenshot(path=path, full_page=full_page)
            return f"Screenshot saved to {path}"
        except Exception as e:
            return f"Error taking screenshot: {e}"


class BrowserEvaluateTool(Tool):
    name = "BrowserEvaluate"
    description = "Run JavaScript on the current page and return the result."
    parameters = {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "JavaScript expression to evaluate",
            },
        },
        "required": ["expression"],
    }

    def run(self, expression: str) -> str:  # type: ignore[override]
        manager = _get_manager()
        page = manager.page()
        try:
            result = page.evaluate(expression)
            return str(result)[:5000]
        except Exception as e:
            return f"Error evaluating JS: {e}"


class BrowserCloseTool(Tool):
    name = "BrowserClose"
    description = "Close the browser session."
    parameters = {
        "type": "object",
        "properties": {},
    }

    def run(self) -> str:  # type: ignore[override]
        manager = _get_manager()
        manager.close()
        return "Browser session closed."


class OpenInBrowserTool(Tool):
    name = "OpenInBrowser"
    description = "Open a URL in the user's default system browser (Chrome, Edge, etc.). Use this when the user wants to see a web page, watch a video, or interact with a site in their real browser."
    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to open",
            },
        },
        "required": ["url"],
    }

    def run(self, url: str) -> str:  # type: ignore[override]
        import subprocess
        import platform
        try:
            if platform.system() == "Windows":
                subprocess.Popen(["start", url], shell=True)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", url])
            else:
                subprocess.Popen(["xdg-open", url])
            return f"Opened {url} in your default browser."
        except Exception as e:
            return f"Error opening browser: {e}"


# ── new tools: persistence, emulation, interception, tracing ──────────────────

class BrowserStateTool(Tool):
    """Save or load browser cookies/localStorage state."""

    name = "BrowserState"
    description = (
        "Save or load persistent browser state (cookies, localStorage). "
        "Use 'save' to persist the current session, 'load' to restore "
        "a previously saved session, or 'clear' to wipe saved state."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["save", "clear"],
                "description": "Action: 'save' persists current state, 'clear' wipes it.",
            },
        },
        "required": ["action"],
    }

    def run(self, action: str) -> str:  # type: ignore[override]
        manager = _get_manager()
        _ = manager.page()  # ensure browser is up
        if action == "save":
            return manager.save_state()
        elif action == "clear":
            return manager.clear_state()
        return f"Unknown action: {action}"


class BrowserEmulateTool(Tool):
    """Emulate a mobile device or set custom viewport."""

    name = "BrowserEmulate"
    description = (
        "Emulate a mobile device or set a custom viewport. "
        "Predefined devices include: 'iPhone 12', 'Pixel 5', 'iPad Pro', "
        "'Galaxy S9+', 'iPhone SE'. Pass 'desktop' to reset to default. "
        "Alternatively, pass custom width/height numbers."
    )
    parameters = {
        "type": "object",
        "properties": {
            "device": {
                "type": "string",
                "description": "Device name to emulate (e.g., 'iPhone 12', 'Pixel 5') or 'desktop' to reset.",
            },
            "width": {
                "type": "integer",
                "description": "Custom viewport width (optional, used if device is not set).",
            },
            "height": {
                "type": "integer",
                "description": "Custom viewport height (optional, used if device is not set).",
            },
        },
    }

    def run(self, device: str = "", width: int = 0, height: int = 0) -> str:  # type: ignore[override]
        manager = _get_manager()
        page = manager.page()

        try:
            if device.lower() == "desktop":
                page.set_viewport_size({"width": 1280, "height": 720})
                return "Viewport reset to desktop (1280x720)."
            elif device:
                _KNOWN_DEVICES = {
                    "iPhone 12": {"viewport": {"width": 390, "height": 844}, "has_touch": True, "is_mobile": True},
                    "iPhone SE": {"viewport": {"width": 375, "height": 667}, "has_touch": True, "is_mobile": True},
                    "Pixel 5": {"viewport": {"width": 393, "height": 851}, "has_touch": True, "is_mobile": True},
                    "Galaxy S9+": {"viewport": {"width": 320, "height": 658}, "has_touch": True, "is_mobile": True},
                    "iPad Pro": {"viewport": {"width": 1024, "height": 1366}, "has_touch": True, "is_mobile": True},
                }
                d = _KNOWN_DEVICES.get(device)
                if d:
                    page.set_viewport_size(d["viewport"])
                    return (
                        f"Emulating {device} — "
                        f"viewport {d['viewport']['width']}x{d['viewport']['height']}, "
                        f"touch: {d.get('has_touch', True)}, "
                        f"mobile: {d.get('is_mobile', True)}"
                    )
                return f"Device '{device}' not found. Try: {', '.join(_KNOWN_DEVICES)}."
            elif width and height:
                page.set_viewport_size({"width": width, "height": height})
                return f"Viewport set to {width}x{height}."
            else:
                return "Provide a device name or custom width/height."
        except Exception as e:
            return f"Error emulating device: {e}"


class BrowserInterceptTool(Tool):
    """Intercept and mock network requests."""

    name = "BrowserIntercept"
    description = (
        "Intercept network requests on the current page. "
        "Use 'list' to see recent requests, 'mock' to block/fake URLs, "
        "'clear' to remove all intercepts. "
        "For 'mock', pass URL pattern (glob) and optional status code (default 200)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "mock", "clear"],
                "description": "Action: 'list' requests, 'mock' URLs, or 'clear' intercepts.",
            },
            "url_pattern": {
                "type": "string",
                "description": "Glob pattern for URLs to intercept (e.g., '**/*.png').",
            },
            "status": {
                "type": "integer",
                "description": "HTTP status code for mocked response (default: 200, or 204 for block).",
            },
        },
        "required": ["action"],
    }

    # Track requests for 'list' action
    _requests: list[dict] = []

    def run(self, action: str, url_pattern: str = "", status: int = 200) -> str:  # type: ignore[override]
        manager = _get_manager()
        page = manager.page()

        if action == "list":
            # Collect requests via JS
            try:
                requests = page.evaluate("""
                    () => {
                        const entries = performance.getEntriesByType('resource');
                        return entries.slice(-20).map(e => ({
                            name: e.name,
                            type: e.initiatorType,
                            duration: Math.round(e.duration),
                            size: e.transferSize || 0,
                        }));
                    }
                """)
                if requests:
                    lines = [f"  {r['type']:8s} {r['duration']:5d}ms  {r['size']:6d}B  {r['name'][:100]}" for r in requests]
                    return "Recent network requests:\n" + "\n".join(lines)
                return "No network requests captured yet."
            except Exception as e:
                return f"Error listing requests: {e}"

        elif action == "mock":
            if not url_pattern:
                return "Provide a url_pattern to mock (e.g., '**/*.png')."
            try:

                def _block_route(route):
                    route.fulfill(status=status, body="")
                manager.set_intercept_handler(_block_route)
                return (
                    f"Intercepting {url_pattern} → HTTP {status}. "
                    "Use BrowserIntercept action='clear' to remove."
                )
            except Exception as e:
                return f"Error setting up intercept: {e}"

        elif action == "clear":
            manager.set_intercept_handler(None)
            return "All network intercepts cleared."

        return f"Unknown action: {action}"


class BrowserTraceTool(Tool):
    """Start/stop browser tracing for debugging."""

    name = "BrowserTrace"
    description = (
        "Start or stop browser tracing (records screenshots, network, "
        "and DOM snapshots for debugging). Use 'start' to begin, 'stop' "
        "to save the trace to a .zip file."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["start", "stop"],
                "description": "Start or stop tracing.",
            },
        },
        "required": ["action"],
    }

    def run(self, action: str) -> str:  # type: ignore[override]
        manager = _get_manager()
        _ = manager.page()  # ensure browser is up
        if action == "start":
            return manager.start_tracing()
        elif action == "stop":
            return manager.stop_tracing()
        return f"Unknown action: {action}"


class BrowserToggleHeadlessTool(Tool):
    """Toggle between headless and headed browser mode at runtime."""

    name = "BrowserToggleHeadless"
    description = (
        "Toggle the browser between headless (invisible) and headed (visible) mode. "
        "Useful when you need to see the actual rendered page. "
        "Pass 'true' for headless, 'false' for headed."
    )
    parameters = {
        "type": "object",
        "properties": {
            "headless": {
                "type": "boolean",
                "description": "True for headless (default), False for visible browser window.",
            },
        },
        "required": ["headless"],
    }

    def run(self, headless: bool) -> str:  # type: ignore[override]
        manager = _get_manager()
        manager.restart(headless=headless)
        mode = "headless (invisible)" if headless else "headed (visible window)"
        return f"Browser restarted in {mode} mode."
