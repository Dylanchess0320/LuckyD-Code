"""Tests for the web UI module using FastAPI TestClient."""

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

# Python 3.15 + anyio 4.13.0 incompatibility: current_task() returns None
# in thread-based asyncio contexts (e.g., Starlette TestClient).
# Skip these tests until upstream anyio/starlette supports 3.15.
pytestmark = pytest.mark.skipif(
    sys.version_info >= (3, 15),
    reason="Python 3.15 + anyio 4.13.0 incompatibility (current_task returns None)",
)

from luckyd_code.web_app import create_app  # noqa: E402


def _identity_resolve(path, *args, **kwargs):
    """Bypasses CWD-relative check for file API tests."""
    return str(Path(path).resolve())


def _make_mock_config():
    """Create a mock Config with all required attributes."""
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


def _dummy_generator(*args, **kwargs):
    """A generator that yields a simple text response, then done."""
    yield ("text", "Hello from DeepSeek!")
    yield ("done", ("Hello from DeepSeek!", ""))


def _tool_call_generator(*args, **kwargs):
    """A generator that yields text then a tool call."""
    yield ("text", "Let me read that file...")
    tool_calls = [{
        "id": "call_abc123",
        "type": "function",
        "function": {"name": "Read", "arguments": '{"file_path": "test.txt"}'},
    }]
    yield ("tool_calls", (tool_calls, "thinking about reading the file"))


class TestCreateApp:
    @pytest.fixture(autouse=True)
    def _patch_path_check(self):
        """Bypass path traversal check so temp dirs work in tests."""
        with patch("luckyd_code.tools.path_validate.safe_resolve", side_effect=lambda p, **kw: Path(p).resolve()):
            yield

    def test_index_returns_html(self):
        """GET / should return HTML."""
        with patch("luckyd_code.web_app.Config", return_value=_make_mock_config()):
            with patch("luckyd_code.web_app.memory_module.load_claude_md", return_value=""):
                with patch("luckyd_code.indexer.index_project", return_value=""):
                    app = create_app()
                    client = TestClient(app)
                    resp = client.get("/")
                    assert resp.status_code == 200
                    assert "text/html" in resp.headers["content-type"]

    def test_api_files_lists_directory(self):
        """GET /api/files should list files in a directory."""
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "test.txt").write_text("hello")
            (Path(tmp) / "subdir").mkdir()

            with patch("luckyd_code.tools.path_validate.safe_resolve", _identity_resolve):
                with patch("luckyd_code.web_app.Config", return_value=_make_mock_config()):
                    with patch("luckyd_code.web_app.memory_module.load_claude_md", return_value=""):
                        with patch("luckyd_code.indexer.index_project", return_value=""):
                            app = create_app()
                            client = TestClient(app)
                            resp = client.get("/api/files", params={"dir": tmp})
                            assert resp.status_code == 200
                            data = resp.json()
                            assert "files" in data
                            names = [f["name"] for f in data["files"]]
                            assert "test.txt" in names
                            assert "subdir" in names

    def test_api_files_invalid_path(self):
        """GET /api/files with invalid path should return 400."""
        with patch("luckyd_code.web_app.Config", return_value=_make_mock_config()):
            with patch("luckyd_code.web_app.memory_module.load_claude_md", return_value=""):
                with patch("luckyd_code.indexer.index_project", return_value=""):
                    app = create_app()
                    client = TestClient(app)
                    resp = client.get("/api/files", params={"dir": "../etc/passwd"})
                    assert resp.status_code in (400, 404)

    def test_api_list_tools(self):
        """GET /api/tools should return tool list."""
        with patch("luckyd_code.web_app.Config", return_value=_make_mock_config()):
            with patch("luckyd_code.web_app.memory_module.load_claude_md", return_value=""):
                with patch("luckyd_code.indexer.index_project", return_value=""):
                    app = create_app()
                    client = TestClient(app)
                    resp = client.get("/api/tools")
                    assert resp.status_code == 200
                    data = resp.json()
                    assert "tools" in data
                    assert "count" in data
                    assert data["count"] > 0

    def test_api_read_file(self):
        """GET /api/read-file should return file contents."""
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "readme.txt"
            file_path.write_text("Hello World", encoding="utf-8")

            with patch("luckyd_code.tools.path_validate.safe_resolve", _identity_resolve):
                with patch("luckyd_code.web_app.Config", return_value=_make_mock_config()):
                    with patch("luckyd_code.web_app.memory_module.load_claude_md", return_value=""):
                        with patch("luckyd_code.indexer.index_project", return_value=""):
                            app = create_app()
                            client = TestClient(app)
                            resp = client.get("/api/read-file", params={"path": str(file_path)})
                            assert resp.status_code == 200
                            data = resp.json()
                            assert data["content"] == "Hello World"
                            assert data["size"] == 11

    def test_api_read_file_not_found(self):
        """GET /api/read-file with nonexistent path should return 404."""
        with patch("luckyd_code.tools.path_validate.safe_resolve", _identity_resolve):
            with patch("luckyd_code.web_app.Config", return_value=_make_mock_config()):
                with patch("luckyd_code.web_app.memory_module.load_claude_md", return_value=""):
                    with patch("luckyd_code.indexer.index_project", return_value=""):
                        app = create_app()
                        client = TestClient(app)
                        resp = client.get("/api/read-file", params={"path": "/nonexistent/file.txt"})
                        assert resp.status_code == 404

    def test_api_read_file_no_path(self):
        """GET /api/read-file with no path should return 400."""
        with patch("luckyd_code.web_app.Config", return_value=_make_mock_config()):
            with patch("luckyd_code.web_app.memory_module.load_claude_md", return_value=""):
                with patch("luckyd_code.indexer.index_project", return_value=""):
                    app = create_app()
                    client = TestClient(app)
                    resp = client.get("/api/read-file")
                    assert resp.status_code == 400

    def test_api_write_file(self):
        """POST /api/write-file should create a file."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "new_file.txt"
            payload = {"path": str(target), "content": "written content"}

            with patch("luckyd_code.tools.path_validate.safe_resolve", _identity_resolve):
                with patch("luckyd_code.web_app.Config", return_value=_make_mock_config()):
                    with patch("luckyd_code.web_app.memory_module.load_claude_md", return_value=""):
                        with patch("luckyd_code.indexer.index_project", return_value=""):
                            app = create_app()
                            client = TestClient(app)
                            resp = client.post("/api/write-file", json=payload)
                            assert resp.status_code == 200
                            data = resp.json()
                            assert data["status"] == "written"
                            assert target.read_text() == "written content"

    def test_api_write_file_no_path(self):
        """POST /api/write-file with no path should return 400."""
        with patch("luckyd_code.web_app.Config", return_value=_make_mock_config()):
            with patch("luckyd_code.web_app.memory_module.load_claude_md", return_value=""):
                with patch("luckyd_code.indexer.index_project", return_value=""):
                    app = create_app()
                    client = TestClient(app)
                    resp = client.post("/api/write-file", json={"content": "test"})
                    assert resp.status_code == 400

    def test_api_edit_file(self):
        """POST /api/edit-file should replace old_string with new_string."""
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "editable.txt"
            file_path.write_text("Hello old world", encoding="utf-8")

            payload = {
                "path": str(file_path),
                "old_string": "old",
                "new_string": "new",
            }
            with patch("luckyd_code.tools.path_validate.safe_resolve", _identity_resolve):
                with patch("luckyd_code.web_app.Config", return_value=_make_mock_config()):
                    with patch("luckyd_code.web_app.memory_module.load_claude_md", return_value=""):
                        with patch("luckyd_code.indexer.index_project", return_value=""):
                            app = create_app()
                            client = TestClient(app)
                            resp = client.post("/api/edit-file", json=payload)
                            assert resp.status_code == 200
                            data = resp.json()
                            assert data["status"] == "edited"
                            assert data["replacements"] == 1
                            assert file_path.read_text() == "Hello new world"

    def test_api_edit_file_not_found(self):
        """POST /api/edit-file with nonexistent file should return 404."""
        payload = {
            "path": "/nonexistent/file.txt",
            "old_string": "old",
            "new_string": "new",
        }
        with patch("luckyd_code.tools.path_validate.safe_resolve", _identity_resolve):
            with patch("luckyd_code.web_app.Config", return_value=_make_mock_config()):
                with patch("luckyd_code.web_app.memory_module.load_claude_md", return_value=""):
                    with patch("luckyd_code.indexer.index_project", return_value=""):
                        app = create_app()
                        client = TestClient(app)
                        resp = client.post("/api/edit-file", json=payload)
                        assert resp.status_code == 404

    def test_api_edit_file_no_match(self):
        """POST /api/edit-file with non-matching old_string should return 400."""
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "editable.txt"
            file_path.write_text("content", encoding="utf-8")

            payload = {
                "path": str(file_path),
                "old_string": "nonexistent",
                "new_string": "replacement",
            }
            with patch("luckyd_code.tools.path_validate.safe_resolve", _identity_resolve):
                with patch("luckyd_code.web_app.Config", return_value=_make_mock_config()):
                    with patch("luckyd_code.web_app.memory_module.load_claude_md", return_value=""):
                        with patch("luckyd_code.indexer.index_project", return_value=""):
                            app = create_app()
                            client = TestClient(app)
                            resp = client.post("/api/edit-file", json=payload)
                            assert resp.status_code == 400
                            assert "old_string not found" in resp.json()["error"]

    def test_api_memory(self):
        """GET /api/memory should return claude.md content."""
        with patch("luckyd_code.web_app.Config", return_value=_make_mock_config()):
            with patch("luckyd_code.web_app.memory_module.load_claude_md",
                       return_value="# Project memory"):
                with patch("luckyd_code.indexer.index_project", return_value=""):
                    app = create_app()
                    client = TestClient(app)
                    resp = client.get("/api/memory")
                    assert resp.status_code == 200
                    data = resp.json()
                    assert data["claude_md"] == "# Project memory"
                    assert "message_count" in data

    def test_api_clear(self):
        """POST /api/clear should reset the context."""
        with patch("luckyd_code.web_app.Config", return_value=_make_mock_config()):
            with patch("luckyd_code.web_app.memory_module.load_claude_md", return_value=""):
                with patch("luckyd_code.indexer.index_project", return_value=""):
                    app = create_app()
                    client = TestClient(app)
                    resp = client.post("/api/clear")
                    assert resp.status_code == 200
                    data = resp.json()
                    assert data["status"] == "cleared"


class TestWebSocketEndpoint:
    def test_websocket_message_roundtrip(self):
        """WebSocket should accept a message and stream text back."""
        with patch("luckyd_code.web_app.Config", return_value=_make_mock_config()):
            with patch("luckyd_code.api.stream_chat", side_effect=_dummy_generator):
                with patch("luckyd_code.web_app.memory_module.load_claude_md", return_value=""):
                    with patch("luckyd_code.indexer.index_project", return_value=""):
                        with patch("luckyd_code.settings.load_settings", return_value={"auto_route": False}):
                            app = create_app()
                            client = TestClient(app)

                            with client.websocket_connect("/ws") as ws:
                                ws.send_json({"type": "message", "content": "Hello!"})
                                response = ws.receive_json()
                                assert response["type"] == "text"
                                assert len(response["content"]) > 0

                                done = ws.receive_json()
                                assert done["type"] == "done"

    def test_websocket_clear(self):
        """WebSocket clear message should reset context."""
        with patch("luckyd_code.web_app.Config", return_value=_make_mock_config()):
            with patch("luckyd_code.api.stream_chat", side_effect=_dummy_generator):
                with patch("luckyd_code.web_app.memory_module.load_claude_md", return_value=""):
                    with patch("luckyd_code.indexer.index_project", return_value=""):
                        with patch("luckyd_code.settings.load_settings", return_value={"auto_route": False}):
                            app = create_app()
                            client = TestClient(app)

                            with client.websocket_connect("/ws") as ws:
                                ws.send_json({"type": "clear"})
                                resp = ws.receive_json()
                                assert resp["type"] == "cleared"

    def test_websocket_tool_call_flow(self):
        """WebSocket should handle tool calls."""
        with patch("luckyd_code.web_app.Config", return_value=_make_mock_config()):
            with patch("luckyd_code.api.stream_chat", side_effect=_tool_call_generator):
                with patch("luckyd_code.web_app.memory_module.load_claude_md", return_value=""):
                    with patch("luckyd_code.indexer.index_project", return_value=""):
                        with patch("luckyd_code.settings.load_settings", return_value={"auto_route": False}):
                            app = create_app()
                            client = TestClient(app)

                            with client.websocket_connect("/ws") as ws:
                                ws.send_json({"type": "message", "content": "Read the file"})

                                text_resp = ws.receive_json()
                                assert text_resp["type"] == "text"

                                # Tool execution
                                tool_resp = ws.receive_json()
                                assert tool_resp["type"] == "tool"
                                assert "name" in tool_resp

                                tool_result = ws.receive_json()
                                assert tool_result["type"] == "tool_result"

    def test_websocket_empty_message_skipped(self):
        """WebSocket should skip empty messages."""
        with patch("luckyd_code.web_app.Config", return_value=_make_mock_config()):
            with patch("luckyd_code.api.stream_chat", side_effect=_dummy_generator):
                with patch("luckyd_code.web_app.memory_module.load_claude_md", return_value=""):
                    with patch("luckyd_code.indexer.index_project", return_value=""):
                        with patch("luckyd_code.settings.load_settings", return_value={"auto_route": False}):
                            app = create_app()
                            client = TestClient(app)

                            with client.websocket_connect("/ws") as ws:
                                ws.send_json({"type": "message", "content": "   "})
                                # Should not get any response (message is all whitespace)
                                # Send another message to trigger a response
                                ws.send_json({"type": "message", "content": "Hi"})
                                resp = ws.receive_json()
                                assert resp["type"] == "text"

    def test_websocket_message_too_long(self):
        """WebSocket should reject messages exceeding max length."""
        with patch("luckyd_code.web_app.Config", return_value=_make_mock_config()):
            with patch("luckyd_code.api.stream_chat", side_effect=_dummy_generator):
                with patch("luckyd_code.web_app.memory_module.load_claude_md", return_value=""):
                    with patch("luckyd_code.indexer.index_project", return_value=""):
                        with patch("luckyd_code.settings.load_settings", return_value={"auto_route": False}):
                            app = create_app()
                            client = TestClient(app)

                            with client.websocket_connect("/ws") as ws:
                                long_msg = "x" * 10001
                                ws.send_json({"type": "message", "content": long_msg})
                                resp = ws.receive_json()
                                assert resp["type"] == "error"
                                assert "too long" in resp["content"].lower()

    def test_websocket_invalid_json(self):
        """WebSocket should handle invalid JSON gracefully."""
        with patch("luckyd_code.web_app.Config", return_value=_make_mock_config()):
            with patch("luckyd_code.api.stream_chat", side_effect=_dummy_generator):
                with patch("luckyd_code.web_app.memory_module.load_claude_md", return_value=""):
                    with patch("luckyd_code.indexer.index_project", return_value=""):
                        with patch("luckyd_code.settings.load_settings", return_value={"auto_route": False}):
                            app = create_app()
                            client = TestClient(app)

                            with client.websocket_connect("/ws") as ws:
                                ws.send_text("not valid json")
                                resp = ws.receive_json()
                                assert resp["type"] == "error"
                                assert "Invalid JSON" in resp["content"]
