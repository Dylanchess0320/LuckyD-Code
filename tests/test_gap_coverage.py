"""Coverage gap closer — targets the 0.69% shortfall.

Covers:
  • luckyd_code/skills/review.py         (18% → ~100%)
  • luckyd_code/skills/security.py       (22% → ~100%)
  • luckyd_code/tasks/manager.py         (23% → ~85%)
  • luckyd_code/permissions/manager.py   (24% → ~85%)
  • luckyd_code/mcp/client.py            (24% → ~60%)
  • luckyd_code/brain/indexer.py         (35% → ~55%)
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest


# ===========================================================================
# skills/review.py
# ===========================================================================

class TestReviewSkill:
    def test_review_changes_with_diff(self):
        from luckyd_code.skills.review import review_changes
        with patch("subprocess.run", return_value=MagicMock(stdout="diff --git a/foo.py b/foo.py\n+line")):
            result = review_changes()
        assert "Changes to review" in result

    def test_review_changes_fallback_to_cached(self):
        from luckyd_code.skills.review import review_changes
        responses = [MagicMock(stdout=""), MagicMock(stdout="diff --git a/x.py b/x.py")]
        with patch("subprocess.run", side_effect=responses):
            result = review_changes()
        assert "Changes to review" in result

    def test_review_changes_no_changes(self):
        from luckyd_code.skills.review import review_changes
        with patch("subprocess.run", return_value=MagicMock(stdout="")):
            result = review_changes()
        assert result == "No changes to review."

    def test_review_changes_exception(self):
        from luckyd_code.skills.review import review_changes
        with patch("subprocess.run", side_effect=OSError("git not found")):
            result = review_changes()
        assert "Error" in result and "git not found" in result


# ===========================================================================
# skills/security.py
# ===========================================================================

class TestSecuritySkill:
    def test_security_review_with_diff(self):
        from luckyd_code.skills.security import security_review
        with patch("subprocess.run", return_value=MagicMock(stdout="diff --git a/auth.py\n-secret")):
            result = security_review()
        assert "Security review" in result

    def test_security_review_no_changes(self):
        from luckyd_code.skills.security import security_review
        with patch("subprocess.run", return_value=MagicMock(stdout="")):
            assert security_review() == "No changes to review."

    def test_security_review_exception(self):
        from luckyd_code.skills.security import security_review
        with patch("subprocess.run", side_effect=FileNotFoundError("git missing")):
            assert "Error" in security_review()


# ===========================================================================
# tasks/manager.py
# ===========================================================================

class TestTaskClass:
    def test_task_defaults(self):
        from luckyd_code.tasks.manager import Task
        t = Task("write tests")
        assert t.subject == "write tests"
        assert t.description == ""
        assert t.status == "pending"
        assert t.blocked_by == []
        assert t.blocks == []
        assert len(t.id) == 8

    def test_task_with_explicit_id(self):
        from luckyd_code.tasks.manager import Task
        t = Task("ship it", description="deploy", task_id="abc12345")
        assert t.id == "abc12345"
        assert t.description == "deploy"

    def test_task_to_dict(self):
        from luckyd_code.tasks.manager import Task
        t = Task("review PR", task_id="deadbeef")
        t.status = "in_progress"
        t.blocked_by = ["aa111111"]
        d = t.to_dict()
        assert d["id"] == "deadbeef"
        assert d["subject"] == "review PR"
        assert d["status"] == "in_progress"
        assert d["blocked_by"] == ["aa111111"]
        assert d["blocks"] == []


class TestTaskManagerFunctions:
    @pytest.fixture(autouse=True)
    def patch_db_path(self, tmp_path):
        tasks_file = tmp_path / "tasks.json"
        with patch("luckyd_code.tasks.manager.project_data_path", return_value=tasks_file):
            yield tasks_file

    def test_create_task_basic(self):
        from luckyd_code.tasks.manager import create_task, _load_tasks
        task = create_task("write unit tests")
        assert task.subject == "write unit tests"
        assert task.status == "pending"
        assert task.id in _load_tasks()

    def test_create_task_blocked_by(self):
        from luckyd_code.tasks.manager import create_task
        t1 = create_task("first")
        t2 = create_task("second", description="depends on first", blocked_by=[t1.id])
        assert t1.id in t2.blocked_by
        assert t2.description == "depends on first"

    def test_update_task_status(self):
        from luckyd_code.tasks.manager import create_task, update_task, _load_tasks
        task = create_task("do something")
        result = update_task(task.id, status="completed")
        assert "updated" in result
        assert _load_tasks()[task.id]["status"] == "completed"

    def test_update_task_subject_description(self):
        from luckyd_code.tasks.manager import create_task, update_task, _load_tasks
        task = create_task("old name")
        update_task(task.id, subject="new name", description="new desc")
        saved = _load_tasks()[task.id]
        assert saved["subject"] == "new name"
        assert saved["description"] == "new desc"

    def test_update_task_not_found(self):
        from luckyd_code.tasks.manager import update_task
        result = update_task("nonexistent", status="completed")
        assert "Error" in result and "not found" in result

    def test_list_tasks_empty(self):
        from luckyd_code.tasks.manager import list_tasks
        assert list_tasks() == "No tasks."

    def test_list_tasks_all(self):
        from luckyd_code.tasks.manager import create_task, list_tasks
        create_task("alpha")
        create_task("beta")
        result = list_tasks()
        assert "alpha" in result and "beta" in result

    def test_list_tasks_filtered(self):
        from luckyd_code.tasks.manager import create_task, update_task, list_tasks
        t1 = create_task("pending task")
        t2 = create_task("done task")
        update_task(t2.id, status="completed")
        assert "pending task" in list_tasks(status="pending")
        assert "done task" not in list_tasks(status="pending")
        assert "done task" in list_tasks(status="completed")

    def test_list_tasks_no_matching(self):
        from luckyd_code.tasks.manager import create_task, list_tasks
        create_task("something")
        assert list_tasks(status="deleted") == "No matching tasks."

    def test_list_tasks_shows_blocked_by(self):
        from luckyd_code.tasks.manager import create_task, list_tasks
        t1 = create_task("blocker")
        create_task("blocked", blocked_by=[t1.id])
        assert "blocked by" in list_tasks()

    def test_get_task_found(self):
        from luckyd_code.tasks.manager import create_task, get_task
        orig = create_task("find me", description="here")
        found = get_task(orig.id)
        assert found is not None
        assert found.subject == "find me"
        assert found.id == orig.id

    def test_get_task_not_found(self):
        from luckyd_code.tasks.manager import get_task
        assert get_task("does-not-exist") is None

    def test_load_tasks_corrupted_json(self, patch_db_path):
        patch_db_path.write_text("NOT VALID JSON {{{", encoding="utf-8")
        from luckyd_code.tasks.manager import _load_tasks
        assert _load_tasks() == {}

    def test_load_tasks_non_dict_json(self, patch_db_path):
        patch_db_path.write_text("[1, 2, 3]", encoding="utf-8")
        from luckyd_code.tasks.manager import _load_tasks
        assert _load_tasks() == {}


# ===========================================================================
# permissions/manager.py
# ===========================================================================

class TestPermissionsManager:
    @pytest.fixture(autouse=True)
    def patch_settings_path(self, tmp_path):
        settings_file = tmp_path / "settings.local.json"
        with patch("luckyd_code.permissions.manager.project_data_path", return_value=settings_file):
            yield settings_file

    def test_load_allowlist_no_file(self):
        from luckyd_code.permissions.manager import _load_allowlist
        assert _load_allowlist() == set()

    def test_load_allowlist_reads_existing(self, patch_settings_path):
        patch_settings_path.write_text(json.dumps({"allowed_tools": ["Read", "Glob"]}))
        from luckyd_code.permissions.manager import _load_allowlist
        result = _load_allowlist()
        assert "Read" in result and "Glob" in result

    def test_load_allowlist_corrupted(self, patch_settings_path):
        patch_settings_path.write_text("GARBAGE")
        from luckyd_code.permissions.manager import _load_allowlist
        assert _load_allowlist() == set()

    def test_save_to_allowlist(self, patch_settings_path):
        from luckyd_code.permissions.manager import _save_to_allowlist, _load_allowlist
        _save_to_allowlist("Bash")
        assert "Bash" in _load_allowlist()

    def test_save_to_allowlist_accumulates(self, patch_settings_path):
        from luckyd_code.permissions.manager import _save_to_allowlist, _load_allowlist
        _save_to_allowlist("Write")
        _save_to_allowlist("Edit")
        result = _load_allowlist()
        assert "Write" in result and "Edit" in result

    def test_safe_tools_always_allowed(self):
        from luckyd_code.permissions.manager import check_permission
        assert check_permission("Read") is True
        assert check_permission("Glob") is True
        assert check_permission("WebSearch") is True
        assert check_permission("BrainSearch") is True

    def test_allowlisted_high_risk_allowed(self, patch_settings_path):
        patch_settings_path.write_text(json.dumps({"allowed_tools": ["Bash"]}))
        from luckyd_code.permissions.manager import check_permission
        assert check_permission("Bash") is True

    def test_prompt_allow_once(self):
        from luckyd_code.permissions.manager import check_permission, _load_allowlist
        with patch("builtins.input", return_value="a"), patch("builtins.print"):
            assert check_permission("Write") is True
        assert "Write" not in _load_allowlist()

    def test_prompt_always_allow(self, patch_settings_path):
        from luckyd_code.permissions.manager import check_permission, _load_allowlist
        with patch("builtins.input", return_value="y"), patch("builtins.print"):
            assert check_permission("Write") is True
        assert "Write" in _load_allowlist()

    def test_prompt_deny(self):
        from luckyd_code.permissions.manager import check_permission
        with patch("builtins.input", return_value="n"), patch("builtins.print"):
            assert check_permission("Bash") is False

    def test_prompt_skip(self):
        from luckyd_code.permissions.manager import check_permission
        with patch("builtins.input", return_value="s"), patch("builtins.print"):
            assert check_permission("GitCommit") is False

    def test_prompt_empty_string_allow_once(self):
        from luckyd_code.permissions.manager import check_permission
        with patch("builtins.input", return_value=""), patch("builtins.print"):
            assert check_permission("Edit") is True

    def test_prompt_eof_denies(self):
        from luckyd_code.permissions.manager import check_permission
        with patch("builtins.input", side_effect=EOFError), patch("builtins.print"):
            assert check_permission("Bash") is False

    def test_prompt_keyboard_interrupt_denies(self):
        from luckyd_code.permissions.manager import check_permission
        with patch("builtins.input", side_effect=KeyboardInterrupt), patch("builtins.print"):
            assert check_permission("GitPush") is False

    def test_prompt_too_many_bad_inputs(self):
        from luckyd_code.permissions.manager import check_permission
        with patch("builtins.input", return_value="???"), patch("builtins.print"):
            assert check_permission("Bash") is False

    def test_unknown_tool_defaults_high_risk(self):
        from luckyd_code.permissions.manager import check_permission
        with patch("builtins.input", return_value="n"), patch("builtins.print"):
            assert check_permission("SomeFutureTool") is False


# ===========================================================================
# mcp/client.py
# ===========================================================================

def _make_mock_process():
    """Mock Popen process whose stderr thread exits immediately."""
    proc = MagicMock()
    proc.poll.return_value = None
    proc.stdin = MagicMock()
    proc.stdout = MagicMock()
    # readline() returns "" → the daemon thread exits cleanly
    proc.stderr.readline.return_value = ""
    return proc


class TestMCPServer:
    def _make(self):
        from luckyd_code.mcp.client import MCPServer
        return MCPServer(name="test", command="echo", args=["hello"])

    def test_init(self):
        s = self._make()
        assert s.name == "test"
        assert s.command == "echo"
        assert s.args == ["hello"]
        assert s.process is None
        assert s.tools == []

    def test_connect_success(self):
        s = self._make()
        proc = _make_mock_process()
        with patch("subprocess.Popen", return_value=proc):
            err = s.connect()
        assert err is None
        assert s.process is proc

    def test_connect_failure(self):
        s = self._make()
        with patch("subprocess.Popen", side_effect=OSError("no binary")):
            err = s.connect()
        assert err is not None and "Failed to start" in err

    def test_send_request_not_running(self):
        s = self._make()
        with patch.object(s, "_ensure_running", return_value=False):
            assert "error" in s._send_request("tools/list")

    def test_send_request_no_process(self):
        s = self._make()
        s.process = None
        with patch.object(s, "_ensure_running", return_value=True):
            assert "error" in s._send_request("tools/list")

    def test_send_request_success(self):
        s = self._make()
        proc = _make_mock_process()
        proc.stdout.readline.return_value = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}
        )
        s.process = proc
        with patch.object(s, "_ensure_running", return_value=True):
            assert "result" in s._send_request("tools/list")

    def test_send_request_empty_response(self):
        s = self._make()
        proc = _make_mock_process()
        proc.stdout.readline.return_value = ""
        s.process = proc
        with patch.object(s, "_ensure_running", return_value=True):
            assert s._send_request("tools/list").get("error") == "Empty response from server"

    def test_send_request_bad_json(self):
        s = self._make()
        proc = _make_mock_process()
        proc.stdout.readline.return_value = "NOT JSON"
        s.process = proc
        with patch.object(s, "_ensure_running", return_value=True):
            assert "error" in s._send_request("tools/list")

    def test_list_tools_success(self):
        s = self._make()
        resp = {"result": {"tools": [{"name": "run", "description": "Run"}]}}
        with patch.object(s, "_send_request", return_value=resp):
            tools = s.list_tools()
        assert len(tools) == 1 and tools[0]["name"] == "run"

    def test_list_tools_error(self):
        s = self._make()
        with patch.object(s, "_send_request", return_value={"error": "oops"}):
            assert s.list_tools() == []

    def test_call_tool_success(self):
        s = self._make()
        resp = {"result": {"content": [{"type": "text", "text": "hello world"}]}}
        with patch.object(s, "_send_request", return_value=resp):
            assert s.call_tool("run", {}) == "hello world"

    def test_call_tool_error(self):
        s = self._make()
        with patch.object(s, "_send_request", return_value={"error": "bad tool"}):
            assert "MCP error" in s.call_tool("run", {})

    def test_call_tool_empty_content(self):
        s = self._make()
        with patch.object(s, "_send_request", return_value={"result": {"content": []}}):
            assert s.call_tool("run", {}) == "[]"

    def test_close_terminates(self):
        s = self._make()
        proc = MagicMock()
        s.process = proc
        s.close()
        proc.terminate.assert_called_once()
        assert s.process is None

    def test_close_no_process(self):
        self._make().close()  # must not raise


class TestMCPManager:
    def test_init(self):
        from luckyd_code.mcp.client import MCPManager
        assert MCPManager().servers == []

    def test_get_all_tools_empty(self):
        from luckyd_code.mcp.client import MCPManager
        assert MCPManager().get_all_tools() == []

    def test_get_all_tools_populated(self):
        from luckyd_code.mcp.client import MCPManager, MCPServer
        mgr = MCPManager()
        srv = MagicMock(spec=MCPServer)
        srv.tools = [{"name": "search", "description": "Search", "inputSchema": {}}]
        mgr.servers.append(srv)
        tools = mgr.get_all_tools()
        assert tools[0]["function"]["name"] == "mcp_search"

    def test_execute_found(self):
        from luckyd_code.mcp.client import MCPManager, MCPServer
        mgr = MCPManager()
        srv = MagicMock(spec=MCPServer)
        srv.tools = [{"name": "run"}]
        srv.call_tool.return_value = "done"
        mgr.servers.append(srv)
        assert mgr.execute("mcp_run", {}) == "done"
        srv.call_tool.assert_called_with("run", {})

    def test_execute_not_found(self):
        from luckyd_code.mcp.client import MCPManager
        assert "not found" in MCPManager().execute("mcp_ghost", {})

    def test_close_all(self):
        from luckyd_code.mcp.client import MCPManager, MCPServer
        mgr = MCPManager()
        srv = MagicMock(spec=MCPServer)
        mgr.servers.append(srv)
        mgr.close_all()
        srv.close.assert_called_once()

    def test_load_from_config_empty(self):
        from luckyd_code.mcp.client import MCPManager
        mgr = MCPManager()
        mgr.load_from_config({})
        assert mgr.servers == []

    def test_load_from_config_failed_connect(self):
        from luckyd_code.mcp.client import MCPManager
        mgr = MCPManager()
        cfg = {"mcpServers": {"bad": {"command": "nope", "args": []}}}
        with patch("luckyd_code.mcp.client.MCPServer.connect", return_value="error"):
            mgr.load_from_config(cfg)
        assert mgr.servers == []


# ===========================================================================
# brain/indexer.py
# NOTE: get_embedder is imported inside build()/search() function bodies,
#       so we patch the SOURCE module: luckyd_code.brain.embedder.get_embedder
# ===========================================================================

class TestVectorIndexer:
    def test_init(self):
        from luckyd_code.brain.indexer import VectorIndexer
        v = VectorIndexer()
        assert v.index is None
        assert v.chunks == []
        assert v.file_mtimes == {}
        assert not v._faiss_available

    def test_check_deps_returns_bool(self):
        from luckyd_code.brain.indexer import VectorIndexer
        assert isinstance(VectorIndexer()._check_deps(), bool)

    def test_build_no_deps(self):
        from luckyd_code.brain.indexer import VectorIndexer
        v = VectorIndexer()
        chunks = [
            {"file_path": "a.py", "content": "def foo(): pass", "language": "python"},
            {"file_path": "b.py", "content": "def bar(): pass", "language": "python"},
        ]
        with patch.object(v, "_check_deps", return_value=False):
            stats = v.build(chunks)
        assert stats["chunks"] == 2
        assert stats["files"] == 2
        assert stats["last_indexed"] > 0

    def test_build_no_deps_empty(self):
        from luckyd_code.brain.indexer import VectorIndexer
        v = VectorIndexer()
        with patch.object(v, "_check_deps", return_value=False):
            assert v.build([])["chunks"] == 0

    def test_build_embedder_unavailable(self):
        from luckyd_code.brain.indexer import VectorIndexer
        v = VectorIndexer()
        mock_embedder = MagicMock()
        mock_embedder.available = False
        # Patch the SOURCE module because get_embedder is imported inside build()
        with patch.object(v, "_check_deps", return_value=True), \
             patch("luckyd_code.brain.embedder.get_embedder", return_value=mock_embedder):
            stats = v.build([{"file_path": "x.py", "content": "pass", "language": "python"}])
        assert stats["chunks"] == 1

    def test_build_empty_with_deps_available(self):
        from luckyd_code.brain.indexer import VectorIndexer
        v = VectorIndexer()
        mock_embedder = MagicMock()
        mock_embedder.available = True
        with patch.object(v, "_check_deps", return_value=True), \
             patch("luckyd_code.brain.embedder.get_embedder", return_value=mock_embedder):
            stats = v.build([])
        assert stats["chunks"] == 0
        assert v.index is None

    def test_search_no_index(self):
        from luckyd_code.brain.indexer import VectorIndexer
        assert VectorIndexer().search("find me") == []

    def test_search_deps_unavailable(self):
        from luckyd_code.brain.indexer import VectorIndexer
        v = VectorIndexer()
        with patch.object(v, "_check_deps", return_value=False):
            assert v.search("find me") == []

    def test_stats_text_empty(self):
        from luckyd_code.brain.indexer import VectorIndexer
        text = VectorIndexer().stats_text()
        assert "Chunks indexed: 0" in text and "Files: 0" in text

    def test_stats_text_full(self):
        from luckyd_code.brain.indexer import VectorIndexer
        v = VectorIndexer()
        v.stats = {
            "chunks": 42, "files": 5,
            "languages": {"python": 30, "js": 12},
            "dimension": 384,
            "index_size_bytes": 2048,
            "last_indexed": time.time(),
        }
        text = v.stats_text()
        assert "42" in text
        assert "python=30" in text
        assert "384" in text
        assert "2.0 KB" in text

    def test_stats_text_no_faiss_warning(self):
        from luckyd_code.brain.indexer import VectorIndexer
        v = VectorIndexer()
        v._faiss_available = False
        assert "faiss" in v.stats_text().lower()

    def test_stats_text_mb_size(self):
        from luckyd_code.brain.indexer import VectorIndexer
        v = VectorIndexer()
        v.stats["index_size_bytes"] = 2 * 1024 * 1024
        assert "MB" in v.stats_text()

    def test_stats_text_byte_size(self):
        from luckyd_code.brain.indexer import VectorIndexer
        v = VectorIndexer()
        v.stats["index_size_bytes"] = 512
        assert "512 B" in v.stats_text()

    def test_save_no_faiss(self, tmp_path):
        from luckyd_code.brain.indexer import VectorIndexer
        v = VectorIndexer()
        v.chunks = [{"file_path": "foo.py", "content": "x=1"}]
        with patch("luckyd_code.brain.indexer.BRAIN_DIR", tmp_path), \
             patch("luckyd_code.brain.indexer.CHUNKS_FILE", tmp_path / "chunks.json"), \
             patch("luckyd_code.brain.indexer.MTIMES_FILE", tmp_path / "mtimes.json"), \
             patch("luckyd_code.brain.indexer.STATS_FILE", tmp_path / "stats.json"):
            assert v.save() is True
        assert (tmp_path / "chunks.json").exists()

    def test_load_missing_files(self):
        from luckyd_code.brain.indexer import VectorIndexer
        v = VectorIndexer()
        with patch("luckyd_code.brain.indexer.INDEX_FILE", Path("/nonexistent/index.faiss")), \
             patch("luckyd_code.brain.indexer.CHUNKS_FILE", Path("/nonexistent/chunks.json")):
            assert v.load() is False

    def test_load_empty_chunks(self, tmp_path):
        from luckyd_code.brain.indexer import VectorIndexer
        chunks_file = tmp_path / "chunks.json"
        index_file = tmp_path / "index.faiss"
        chunks_file.write_text("[]", encoding="utf-8")
        index_file.write_bytes(b"placeholder")
        v = VectorIndexer()
        with patch("luckyd_code.brain.indexer.INDEX_FILE", index_file), \
             patch("luckyd_code.brain.indexer.CHUNKS_FILE", chunks_file):
            assert v.load() is False

    def test_is_available_false(self):
        from luckyd_code.brain.indexer import VectorIndexer
        assert VectorIndexer().is_available is False

    def test_get_changed_files_new_file(self, tmp_path):
        from luckyd_code.brain.indexer import VectorIndexer
        py_file = tmp_path / "main.py"
        py_file.write_text("print('hello')", encoding="utf-8")
        v = VectorIndexer()
        assert str(py_file) in v.get_changed_files(str(tmp_path))

    def test_get_changed_files_unchanged(self, tmp_path):
        from luckyd_code.brain.indexer import VectorIndexer
        py_file = tmp_path / "stable.py"
        py_file.write_text("x = 1", encoding="utf-8")
        st = py_file.stat()
        v = VectorIndexer()
        v.file_mtimes[str(py_file)] = (st.st_mtime, st.st_size)
        assert str(py_file) not in v.get_changed_files(str(tmp_path))
