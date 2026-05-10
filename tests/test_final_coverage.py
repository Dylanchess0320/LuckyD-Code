"""Final coverage push — fixed version.

All patches corrected to patch at the *source* module since imports are lazy
(inside functions). Removed tests for non-existent modules (git.workflow,
parallel_executor). Fixed static.py source bug (Response now imported at
module level), so all 4 "missing file" routes are now fully tested.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_request(state=None):
    req = MagicMock()
    req.app.state.web_state = state or MagicMock()
    return req


def _make_repl(**kwargs):
    repl = MagicMock()
    repl.config = MagicMock()
    repl.config.working_directory = "/tmp/project"
    repl.config.model = "deepseek-v4-flash"
    repl.config.provider = "deepseek"
    repl.config.temperature = 0.7
    repl.config.max_tokens = 4096
    repl.config.base_url = "https://api.deepseek.com/v1"
    repl.context = MagicMock()
    repl.context.count_messages.return_value = 3
    repl.context.messages = []
    repl.background = MagicMock()
    repl.brain = MagicMock()
    repl.brain.nodes = {}
    repl.brain.stats = {}
    repl.registry = MagicMock()
    repl.registry.list_tools.return_value = []
    repl.mcp = MagicMock()
    repl.mcp.get_all_tools.return_value = []
    repl.session = MagicMock()
    repl.memory_mgr = MagicMock()
    repl.cost_tracker = MagicMock()
    repl.file_watcher = None
    repl._audit_daemon = None
    for k, v in kwargs.items():
        setattr(repl, k, v)
    return repl


# ===========================================================================
# web_routes/brain.py  — patch at luckyd_code.brain.* (lazy imports)
# ===========================================================================

class TestWebRoutesBrain:
    @pytest.mark.asyncio
    async def test_brain_status_empty(self):
        from luckyd_code.web_routes.brain import brain_status
        req = _make_request()
        with patch("luckyd_code.brain.KnowledgeGraph") as MockKG, \
             patch("luckyd_code.brain.VectorIndexer") as MockVI:
            kg = MockKG.return_value
            kg.nodes = {}
            kg.stats = {}
            vi = MockVI.return_value
            vi.load.return_value = False
            result = await brain_status(req)
        assert result["status"] == "empty"

    @pytest.mark.asyncio
    async def test_brain_status_with_data(self):
        from luckyd_code.web_routes.brain import brain_status
        req = _make_request()
        with patch("luckyd_code.brain.KnowledgeGraph") as MockKG, \
             patch("luckyd_code.brain.VectorIndexer") as MockVI:
            kg = MockKG.return_value
            kg.nodes = {"sym1": {}}
            kg.stats = {"node_count": 1, "edge_count": 0, "files_parsed": 1}
            vi = MockVI.return_value
            vi.load.return_value = False
            result = await brain_status(req)
        assert "symbols" in result

    @pytest.mark.asyncio
    async def test_brain_status_rag_available(self):
        from luckyd_code.web_routes.brain import brain_status
        req = _make_request()
        with patch("luckyd_code.brain.KnowledgeGraph") as MockKG, \
             patch("luckyd_code.brain.VectorIndexer") as MockVI, \
             patch("luckyd_code.brain.Retriever") as MockR:
            kg = MockKG.return_value
            kg.nodes = {"s": {}}
            kg.stats = {"node_count": 5, "edge_count": 2, "files_parsed": 3,
                        "last_built": 1700000000}
            vi = MockVI.return_value
            vi.load.return_value = True
            MockR.return_value.stats.return_value = {
                "vector": {"chunks": 100, "files": 10}
            }
            result = await brain_status(req)
        assert "rag_chunks" in result or "symbols" in result

    @pytest.mark.asyncio
    async def test_brain_rebuild(self):
        from luckyd_code.web_routes.brain import brain_rebuild
        state = MagicMock()
        state.knowledge_graph = MagicMock()
        req = _make_request(state)
        with patch("luckyd_code.brain.rebuild_project",
                   return_value={"chunks": 50, "files": 5, "node_count": 10, "files_parsed": 5}):
            result = await brain_rebuild(req)
        assert result["status"] == "ok"
        assert result["chunks"] == 50

    @pytest.mark.asyncio
    async def test_brain_rebuild_no_graph_state(self):
        from luckyd_code.web_routes.brain import brain_rebuild
        state = MagicMock()
        state.knowledge_graph = None
        req = _make_request(state)
        with patch("luckyd_code.brain.rebuild_project",
                   return_value={"chunks": 0, "files": 0, "node_count": 0, "files_parsed": 0}):
            result = await brain_rebuild(req)
        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_brain_search_empty_query(self):
        from luckyd_code.web_routes.brain import brain_search
        req = _make_request()
        result = await brain_search(req, q="", max_results=5)
        assert result["results"] == []

    @pytest.mark.asyncio
    async def test_brain_search_with_query(self):
        from luckyd_code.web_routes.brain import brain_search
        req = _make_request()
        with patch("luckyd_code.brain.Retriever") as MockR:
            MockR.return_value.search.return_value = [
                {"content": "def foo(): pass", "file": "main.py", "score": 0.9}
            ]
            result = await brain_search(req, q="foo", max_results=5)
        assert len(result["results"]) == 1

    @pytest.mark.asyncio
    async def test_brain_search_exception(self):
        from luckyd_code.web_routes.brain import brain_search
        from fastapi.responses import JSONResponse
        req = _make_request()
        with patch("luckyd_code.brain.Retriever", side_effect=Exception("no rag")):
            result = await brain_search(req, q="foo")
        assert isinstance(result, JSONResponse)

    @pytest.mark.asyncio
    async def test_brain_stats_ok(self):
        from luckyd_code.web_routes.brain import brain_stats
        req = _make_request()
        with patch("luckyd_code.brain.Retriever") as MockR:
            MockR.return_value.stats.return_value = {"vector": {"chunks": 100}}
            result = await brain_stats(req)
        assert "vector" in result

    @pytest.mark.asyncio
    async def test_brain_stats_exception(self):
        from luckyd_code.web_routes.brain import brain_stats
        from fastapi.responses import JSONResponse
        req = _make_request()
        with patch("luckyd_code.brain.Retriever", side_effect=Exception("no rag")):
            result = await brain_stats(req)
        assert isinstance(result, JSONResponse)

    @pytest.mark.asyncio
    async def test_brain_dependents_no_symbol(self):
        from luckyd_code.web_routes.brain import brain_dependents
        from fastapi.responses import JSONResponse
        req = _make_request()
        result = await brain_dependents(req, symbol="")
        assert isinstance(result, JSONResponse)
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_brain_dependents_ok(self):
        from luckyd_code.web_routes.brain import brain_dependents
        req = _make_request()
        with patch("luckyd_code.brain.KnowledgeGraph") as MockKG:
            MockKG.return_value.find_dependents.return_value = [
                {"name": "Foo", "file": "a.py", "relation": "uses"}
            ]
            result = await brain_dependents(req, symbol="Bar")
        assert result["symbol"] == "Bar"
        assert result["count"] == 1

    @pytest.mark.asyncio
    async def test_brain_dependents_exception(self):
        from luckyd_code.web_routes.brain import brain_dependents
        from fastapi.responses import JSONResponse
        req = _make_request()
        with patch("luckyd_code.brain.KnowledgeGraph", side_effect=Exception("no brain")):
            result = await brain_dependents(req, symbol="Foo")
        assert isinstance(result, JSONResponse)


# ===========================================================================
# web_routes/static.py — all paths tested (source bug fixed: Response at top level)
# ===========================================================================

class TestWebRoutesStatic:
    @pytest.mark.asyncio
    async def test_index_template_found(self, tmp_path):
        from luckyd_code.web_routes import static as static_mod
        (tmp_path / "index.html").write_text("<html>hello</html>", encoding="utf-8")
        with patch.object(static_mod, "TEMPLATES", tmp_path):
            result = await static_mod.index()
        from fastapi.responses import HTMLResponse
        assert isinstance(result, HTMLResponse)
        assert "hello" in result.body.decode()

    @pytest.mark.asyncio
    async def test_index_template_missing(self, tmp_path):
        from luckyd_code.web_routes import static as static_mod
        with patch.object(static_mod, "TEMPLATES", tmp_path):
            result = await static_mod.index()
        from fastapi.responses import HTMLResponse
        assert isinstance(result, HTMLResponse)
        assert "Template not found" in result.body.decode()

    @pytest.mark.asyncio
    async def test_manifest_found(self, tmp_path):
        from luckyd_code.web_routes import static as static_mod
        (tmp_path / "manifest.json").write_text('{"name":"App"}', encoding="utf-8")
        with patch.object(static_mod, "TEMPLATES", tmp_path):
            result = await static_mod.manifest()
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_manifest_missing(self, tmp_path):
        from luckyd_code.web_routes import static as static_mod
        with patch.object(static_mod, "TEMPLATES", tmp_path):
            result = await static_mod.manifest()
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_service_worker_found(self, tmp_path):
        from luckyd_code.web_routes import static as static_mod
        (tmp_path / "sw.js").write_bytes(b"self.addEventListener('install',()={})")
        with patch.object(static_mod, "TEMPLATES", tmp_path):
            result = await static_mod.service_worker()
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_service_worker_missing(self, tmp_path):
        from luckyd_code.web_routes import static as static_mod
        with patch.object(static_mod, "TEMPLATES", tmp_path):
            result = await static_mod.service_worker()
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_icon_192_found(self, tmp_path):
        from luckyd_code.web_routes import static as static_mod
        (tmp_path / "icon-192.png").write_bytes(b"\x89PNG\r\n")
        with patch.object(static_mod, "TEMPLATES", tmp_path):
            result = await static_mod.icon_192()
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_icon_192_missing(self, tmp_path):
        from luckyd_code.web_routes import static as static_mod
        with patch.object(static_mod, "TEMPLATES", tmp_path):
            result = await static_mod.icon_192()
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_icon_512_found(self, tmp_path):
        from luckyd_code.web_routes import static as static_mod
        (tmp_path / "icon-512.png").write_bytes(b"\x89PNG\r\n")
        with patch.object(static_mod, "TEMPLATES", tmp_path):
            result = await static_mod.icon_512()
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_icon_512_missing(self, tmp_path):
        from luckyd_code.web_routes import static as static_mod
        with patch.object(static_mod, "TEMPLATES", tmp_path):
            result = await static_mod.icon_512()
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_favicon_found(self, tmp_path):
        from luckyd_code.web_routes import static as static_mod
        (tmp_path / "icon-192.png").write_bytes(b"\x89PNG\r\n")
        with patch.object(static_mod, "TEMPLATES", tmp_path):
            result = await static_mod.favicon()
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_favicon_missing(self, tmp_path):
        from luckyd_code.web_routes import static as static_mod
        with patch.object(static_mod, "TEMPLATES", tmp_path):
            result = await static_mod.favicon()
        assert result.status_code == 404


# ===========================================================================
# cli_commands/audit.py — AuditDaemon imported lazily inside functions
# ===========================================================================

class TestCliAuditCommand:
    def test_audit_help_no_args(self):
        from luckyd_code.cli_commands.audit import handle_audit_command
        repl = _make_repl()
        with patch("luckyd_code.cli_commands.audit.console"):
            handle_audit_command(repl, [])

    def test_audit_help_unknown(self):
        from luckyd_code.cli_commands.audit import handle_audit_command
        repl = _make_repl()
        with patch("luckyd_code.cli_commands.audit.console"):
            handle_audit_command(repl, ["unknown"])

    def test_audit_run_skipped(self):
        from luckyd_code.cli_commands.audit import handle_audit_command
        repl = _make_repl()
        mock_daemon = MagicMock()
        mock_daemon.audit.return_value = {"skipped": True, "skip_reason": "locked"}
        with patch("luckyd_code.cli_commands.audit.console"), \
             patch("luckyd_code.audit_daemon.AuditDaemon", return_value=mock_daemon):
            handle_audit_command(repl, ["run"])

    def test_audit_run_with_metrics(self):
        from luckyd_code.cli_commands.audit import handle_audit_command
        repl = _make_repl()
        mock_daemon = MagicMock()
        mock_daemon.audit.return_value = {
            "skipped": False,
            "metrics": {"coverage": 0.85},
            "improvements_attempted": 1,
            "improvements_committed": 1,
            "regressions": [],
        }
        with patch("luckyd_code.cli_commands.audit.console"), \
             patch("luckyd_code.audit_daemon.AuditDaemon", return_value=mock_daemon):
            handle_audit_command(repl, ["run"])

    def test_audit_run_with_regressions(self):
        from luckyd_code.cli_commands.audit import handle_audit_command
        repl = _make_repl()
        mock_daemon = MagicMock()
        mock_daemon.audit.return_value = {
            "skipped": False,
            "metrics": {},
            "improvements_attempted": 0,
            "improvements_committed": 0,
            "regressions": ["coverage dropped"],
        }
        with patch("luckyd_code.cli_commands.audit.console"), \
             patch("luckyd_code.audit_daemon.AuditDaemon", return_value=mock_daemon):
            handle_audit_command(repl, ["run"])

    def test_audit_run_exception(self):
        from luckyd_code.cli_commands.audit import handle_audit_command
        repl = _make_repl()
        mock_daemon = MagicMock()
        mock_daemon.audit.side_effect = RuntimeError("failed")
        with patch("luckyd_code.cli_commands.audit.console"), \
             patch("luckyd_code.audit_daemon.AuditDaemon", return_value=mock_daemon):
            handle_audit_command(repl, ["run"])

    def test_audit_run_uses_existing_daemon(self):
        from luckyd_code.cli_commands.audit import handle_audit_command
        repl = _make_repl()
        existing = MagicMock()
        existing.audit.return_value = {"skipped": True, "skip_reason": "running"}
        repl._audit_daemon = existing
        with patch("luckyd_code.cli_commands.audit.console"):
            handle_audit_command(repl, ["run"])
        existing.audit.assert_called_once()

    def test_audit_status(self):
        from luckyd_code.cli_commands.audit import handle_audit_command
        repl = _make_repl()
        mock_daemon = MagicMock()
        mock_daemon.status.return_value = "Daemon idle"
        with patch("luckyd_code.cli_commands.audit.console") as mock_con, \
             patch("luckyd_code.audit_daemon.AuditDaemon", return_value=mock_daemon):
            handle_audit_command(repl, ["status"])
        mock_con.print.assert_called_with("Daemon idle")

    def test_audit_metrics_empty(self):
        from luckyd_code.cli_commands.audit import handle_audit_command
        repl = _make_repl()
        mock_daemon = MagicMock()
        mock_daemon.metrics_json.return_value = "[]"
        with patch("luckyd_code.cli_commands.audit.console"), \
             patch("luckyd_code.audit_daemon.AuditDaemon", return_value=mock_daemon):
            handle_audit_command(repl, ["metrics"])

    def test_audit_metrics_with_data(self):
        from luckyd_code.cli_commands.audit import handle_audit_command
        repl = _make_repl()
        mock_daemon = MagicMock()
        mock_daemon.metrics_json.return_value = json.dumps([{"coverage": 0.9}])
        with patch("luckyd_code.cli_commands.audit.console"), \
             patch("luckyd_code.audit_daemon.AuditDaemon", return_value=mock_daemon):
            handle_audit_command(repl, ["metrics"])


# ===========================================================================
# cli_commands/background.py — console imported lazily inside function
# ===========================================================================

class TestCliBackgroundCommand:
    def test_no_args(self):
        from luckyd_code.cli_commands.background import handle_background_command
        with patch("luckyd_code.cli_utils.console"):
            handle_background_command(_make_repl(), [])

    def test_start_no_task(self):
        from luckyd_code.cli_commands.background import handle_background_command
        with patch("luckyd_code.cli_utils.console"):
            handle_background_command(_make_repl(), ["start"])

    def test_start_with_task(self):
        from luckyd_code.cli_commands.background import handle_background_command
        repl = _make_repl()
        repl.background.start_task.return_value = "task-123"
        with patch("luckyd_code.cli_utils.console"):
            handle_background_command(repl, ["start", "analyze", "code"])
        repl.background.start_task.assert_called_once_with("analyze code")

    def test_status_empty(self):
        from luckyd_code.cli_commands.background import handle_background_command
        repl = _make_repl()
        repl.background.get_status.return_value = []
        with patch("luckyd_code.cli_utils.console"):
            handle_background_command(repl, ["status"])

    def test_status_with_results(self):
        from luckyd_code.cli_commands.background import handle_background_command
        repl = _make_repl()
        repl.background.get_status.return_value = [
            {"id": "t1", "status": "done",    "description": "a", "result_preview": "ok"},
            {"id": "t2", "status": "running", "description": "b", "result_preview": None},
            {"id": "t3", "status": "error",   "description": "c", "result_preview": None},
            {"id": "t4", "status": "pending", "description": "d", "result_preview": None},
        ]
        with patch("luckyd_code.cli_utils.console"):
            handle_background_command(repl, ["status"])

    def test_status_with_id(self):
        from luckyd_code.cli_commands.background import handle_background_command
        repl = _make_repl()
        repl.background.get_status.return_value = [
            {"id": "t1", "status": "done", "description": "x", "result_preview": "y"}
        ]
        with patch("luckyd_code.cli_utils.console"):
            handle_background_command(repl, ["status", "t1"])
        repl.background.get_status.assert_called_with("t1")

    def test_result_no_id(self):
        from luckyd_code.cli_commands.background import handle_background_command
        with patch("luckyd_code.cli_utils.console"):
            handle_background_command(_make_repl(), ["result"])

    def test_result_found(self):
        from luckyd_code.cli_commands.background import handle_background_command
        repl = _make_repl()
        repl.background.get_result.return_value = "Analysis complete."
        with patch("luckyd_code.cli_utils.console") as mock_con:
            handle_background_command(repl, ["result", "t1"])
        mock_con.print.assert_any_call("Analysis complete.")

    def test_result_still_running(self):
        from luckyd_code.cli_commands.background import handle_background_command
        repl = _make_repl()
        repl.background.get_result.return_value = None
        repl.background.get_status.return_value = [
            {"id": "t1", "status": "running", "description": "x",
             "result_preview": None, "error": None}
        ]
        with patch("luckyd_code.cli_utils.console"):
            handle_background_command(repl, ["result", "t1"])

    def test_result_error_status(self):
        from luckyd_code.cli_commands.background import handle_background_command
        repl = _make_repl()
        repl.background.get_result.return_value = None
        repl.background.get_status.return_value = [
            {"id": "t1", "status": "error", "description": "x",
             "result_preview": None, "error": "oops"}
        ]
        with patch("luckyd_code.cli_utils.console"):
            handle_background_command(repl, ["result", "t1"])

    def test_result_pending_no_result(self):
        from luckyd_code.cli_commands.background import handle_background_command
        repl = _make_repl()
        repl.background.get_result.return_value = None
        repl.background.get_status.return_value = [
            {"id": "t1", "status": "pending", "description": "x",
             "result_preview": None, "error": None}
        ]
        with patch("luckyd_code.cli_utils.console"):
            handle_background_command(repl, ["result", "t1"])

    def test_result_task_not_found(self):
        from luckyd_code.cli_commands.background import handle_background_command
        repl = _make_repl()
        repl.background.get_result.return_value = None
        repl.background.get_status.return_value = []
        with patch("luckyd_code.cli_utils.console"):
            handle_background_command(repl, ["result", "ghost"])

    def test_list_empty(self):
        from luckyd_code.cli_commands.background import handle_background_command
        repl = _make_repl()
        repl.background.get_status.return_value = []
        with patch("luckyd_code.cli_utils.console"):
            handle_background_command(repl, ["list"])

    def test_list_with_tasks(self):
        from luckyd_code.cli_commands.background import handle_background_command
        repl = _make_repl()
        repl.background.get_status.return_value = [
            {"id": "t1", "status": "done", "description": "analyze code"},
        ]
        with patch("luckyd_code.cli_utils.console"):
            handle_background_command(repl, ["list"])

    def test_unknown_subcommand(self):
        from luckyd_code.cli_commands.background import handle_background_command
        with patch("luckyd_code.cli_utils.console"):
            handle_background_command(_make_repl(), ["reboot"])


# ===========================================================================
# cli_commands/brain.py — console + BrainStatusTool imported lazily
# ===========================================================================

class TestCliBrainCommand:
    def test_status_empty(self):
        from luckyd_code.cli_commands.brain import handle_brain_command
        repl = _make_repl()
        repl.brain.nodes = {}
        with patch("luckyd_code.brain.VectorIndexer") as MockVI, \
             patch("luckyd_code.cli_utils.console"):
            MockVI.return_value.load.return_value = False
            handle_brain_command(repl, [])

    def test_status_with_rag(self):
        from luckyd_code.cli_commands.brain import handle_brain_command
        repl = _make_repl()
        repl.brain.nodes = {"sym": {}}
        repl.brain.stats = {"node_count": 5, "edge_count": 3, "files_parsed": 2}
        with patch("luckyd_code.brain.VectorIndexer") as MockVI, \
             patch("luckyd_code.brain.Retriever") as MockR, \
             patch("luckyd_code.cli_utils.console"):
            MockVI.return_value.load.return_value = True
            MockR.return_value.stats.return_value = {"vector": {"chunks": 50, "files": 5}}
            handle_brain_command(repl, ["status"])

    def test_status_with_last_built(self):
        from luckyd_code.cli_commands.brain import handle_brain_command
        repl = _make_repl()
        repl.brain.nodes = {"sym": {}}
        repl.brain.stats = {"node_count": 1, "edge_count": 0,
                            "files_parsed": 1, "last_built": 1700000000}
        with patch("luckyd_code.brain.VectorIndexer") as MockVI, \
             patch("luckyd_code.cli_utils.console"):
            MockVI.return_value.load.return_value = False
            handle_brain_command(repl, [])

    def test_rebuild_inserts_new(self):
        from luckyd_code.cli_commands.brain import handle_brain_command
        repl = _make_repl()
        repl.brain.summarize.return_value = "<knowledge-graph>summary</knowledge-graph>"
        repl.context.messages = []
        with patch("luckyd_code.brain.rebuild_project",
                   return_value={"chunks": 10, "files": 2, "node_count": 5, "files_parsed": 2}), \
             patch("luckyd_code.cli_utils.console"):
            handle_brain_command(repl, ["rebuild"])

    def test_rebuild_replaces_existing(self):
        from luckyd_code.cli_commands.brain import handle_brain_command
        repl = _make_repl()
        repl.brain.summarize.return_value = "<knowledge-graph>new</knowledge-graph>"
        repl.context.messages = [
            {"role": "user", "content": "<knowledge-graph>old</knowledge-graph>"}
        ]
        with patch("luckyd_code.brain.rebuild_project",
                   return_value={"chunks": 0, "files": 0, "node_count": 0, "files_parsed": 0}), \
             patch("luckyd_code.cli_utils.console"):
            handle_brain_command(repl, ["rebuild"])
        assert "new" in repl.context.messages[0]["content"]

    def test_rebuild_removes_rag_context(self):
        from luckyd_code.cli_commands.brain import handle_brain_command
        repl = _make_repl()
        repl.brain.summarize.return_value = "<knowledge-graph>x</knowledge-graph>"
        repl.context.messages = [
            {"role": "user", "content": "<rag-context>old</rag-context>"}
        ]
        with patch("luckyd_code.brain.rebuild_project",
                   return_value={"chunks": 0, "files": 0, "node_count": 0, "files_parsed": 0}), \
             patch("luckyd_code.cli_utils.console"):
            handle_brain_command(repl, ["rebuild"])

    def test_stats_has_rag(self):
        from luckyd_code.cli_commands.brain import handle_brain_command
        repl = _make_repl()
        repl.brain.nodes = {"sym": {}}
        with patch("luckyd_code.brain.Retriever") as MockR, \
             patch("luckyd_code.tools.brain_tools.BrainStatusTool") as MockBS, \
             patch("luckyd_code.cli_utils.console"):
            MockR.return_value.stats.return_value = {}
            MockBS.return_value.run.return_value = "Brain status info"
            handle_brain_command(repl, ["stats"])

    def test_stats_empty(self):
        from luckyd_code.cli_commands.brain import handle_brain_command
        repl = _make_repl()
        repl.brain.nodes = {}
        with patch("luckyd_code.brain.Retriever", side_effect=Exception("no rag")), \
             patch("luckyd_code.cli_utils.console"):
            handle_brain_command(repl, ["stats"])


# ===========================================================================
# cli_commands/config.py — console imported lazily inside function
# ===========================================================================

class TestCliConfigCommand:
    def test_no_args(self):
        from luckyd_code.cli_commands.config import handle_config_command
        with patch("luckyd_code.cli_utils.console"):
            handle_config_command(_make_repl(), [])

    def test_list(self):
        from luckyd_code.cli_commands.config import handle_config_command
        with patch("luckyd_code.cli_utils.console"), \
             patch("luckyd_code.settings.load_settings",
                   return_value={"theme": "dark"}):
            handle_config_command(_make_repl(), ["list"])

    def test_get_existing_key(self):
        from luckyd_code.cli_commands.config import handle_config_command
        with patch("luckyd_code.cli_utils.console"), \
             patch("luckyd_code.settings.load_settings", return_value={"theme": "dark"}):
            handle_config_command(_make_repl(), ["get", "theme"])

    def test_get_missing_key(self):
        from luckyd_code.cli_commands.config import handle_config_command
        with patch("luckyd_code.cli_utils.console"), \
             patch("luckyd_code.settings.load_settings", return_value={}):
            handle_config_command(_make_repl(), ["get", "nonexistent"])

    def test_get_no_key(self):
        from luckyd_code.cli_commands.config import handle_config_command
        with patch("luckyd_code.cli_utils.console"):
            handle_config_command(_make_repl(), ["get"])

    def test_set_generic_key(self):
        from luckyd_code.cli_commands.config import handle_config_command
        with patch("luckyd_code.cli_utils.console"), \
             patch("luckyd_code.settings.save_setting") as mock_save:
            handle_config_command(_make_repl(), ["set", "theme", "dark"])
        mock_save.assert_called_once_with("theme", "dark")

    def test_set_no_args(self):
        from luckyd_code.cli_commands.config import handle_config_command
        with patch("luckyd_code.cli_utils.console"):
            handle_config_command(_make_repl(), ["set"])

    def test_set_provider_deepseek_ok(self):
        from luckyd_code.cli_commands.config import handle_config_command
        import os
        repl = _make_repl()
        with patch("luckyd_code.cli_utils.console"), \
             patch("luckyd_code.cli_commands.config.test_connection", return_value=(True, "ok")), \
             patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-key"}):
            handle_config_command(repl, ["set", "provider", "deepseek"])
        repl.config.save.assert_called()

    def test_set_provider_deepseek_connection_fails(self):
        from luckyd_code.cli_commands.config import handle_config_command
        import os
        repl = _make_repl()
        with patch("luckyd_code.cli_utils.console"), \
             patch("luckyd_code.cli_commands.config.test_connection", return_value=(False, "unauthorized")), \
             patch.dict(os.environ, {}, clear=True):
            handle_config_command(repl, ["set", "provider", "deepseek"])

    def test_set_provider_invalid(self):
        from luckyd_code.cli_commands.config import handle_config_command
        repl = _make_repl()
        with patch("luckyd_code.cli_utils.console"):
            handle_config_command(repl, ["set", "provider", "openai"])
        repl.config.save.assert_not_called()

    def test_set_shell_valid(self):
        from luckyd_code.cli_commands.config import handle_config_command
        with patch("luckyd_code.cli_utils.console"), \
             patch("luckyd_code.settings.save_setting"), \
             patch("luckyd_code.tools.bash.reset_shell_cache"):
            handle_config_command(_make_repl(), ["set", "shell", "git_bash"])

    def test_set_shell_invalid(self):
        from luckyd_code.cli_commands.config import handle_config_command
        with patch("luckyd_code.cli_utils.console"):
            handle_config_command(_make_repl(), ["set", "shell", "powershell"])

    def test_unknown_subcommand(self):
        from luckyd_code.cli_commands.config import handle_config_command
        with patch("luckyd_code.cli_utils.console"):
            handle_config_command(_make_repl(), ["purge"])


# ===========================================================================
# cli_commands/dispatcher.py — handle_command branches
# ===========================================================================

class TestDispatcherHandleCommand:
    def _con(self):
        return patch("luckyd_code.cli_utils.console")

    def test_exit(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        with self._con(), pytest.raises(SystemExit):
            handle_command(_make_repl(), "/exit")

    def test_quit(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        with self._con(), pytest.raises(SystemExit):
            handle_command(_make_repl(), "/quit")

    def test_stop_no_tasks(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        repl = _make_repl()
        repl.background.tasks = {}
        with self._con():
            handle_command(repl, "/stop")

    def test_stop_with_running_task(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        repl = _make_repl()
        task = MagicMock()
        task.status = "running"
        task.finished_at = None
        repl.background.tasks = {"t1": task}
        with self._con():
            handle_command(repl, "/stop")
        assert task.status == "stopped"

    def test_clear(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        repl = _make_repl()
        with self._con():
            handle_command(repl, "/clear")
        repl.context.reset.assert_called_once()

    def test_help(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        with self._con():
            handle_command(_make_repl(), "/help")

    def test_model_no_args(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        with self._con():
            handle_command(_make_repl(), "/model")

    def test_model_list(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        with self._con():
            handle_command(_make_repl(), "/model list")

    def test_models_set(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        repl = _make_repl()
        with self._con():
            handle_command(repl, "/models set deepseek-v4-pro")
        assert repl.config.model == "deepseek-v4-pro"

    def test_models_set_empty(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        with self._con():
            handle_command(_make_repl(), "/models set")

    def test_models_no_args(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        with self._con(), \
             patch("luckyd_code.model_registry.format_model_list", return_value="Tier 1: Flash"):
            handle_command(_make_repl(), "/models")

    def test_route_with_text(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        with self._con(), \
             patch("luckyd_code.router.show_current_routing", return_value="Tier 1"):
            handle_command(_make_repl(), "/route debug this bug")

    def test_route_no_args(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        with self._con():
            handle_command(_make_repl(), "/route")

    def test_tokens(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        with self._con():
            handle_command(_make_repl(), "/tokens")

    def test_version(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        with self._con(), \
             patch("luckyd_code.update.get_version", return_value="1.2.3"):
            handle_command(_make_repl(), "/version")

    def test_compact(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        repl = _make_repl()
        repl.context.compact.return_value = "Compacted 5 messages."
        with self._con():
            handle_command(repl, "/compact")
        repl.context.compact.assert_called_once()

    def test_cost_show(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        repl = _make_repl()
        repl.cost_tracker.get_stats.return_value = "Cost: $0.01"
        with self._con():
            handle_command(repl, "/cost")

    def test_cost_reset(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        repl = _make_repl()
        repl.cost_tracker.reset_cumulative.return_value = "Cleared."
        with self._con():
            handle_command(repl, "/cost reset")
        repl.cost_tracker.reset_cumulative.assert_called_once()

    def test_stats(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        repl = _make_repl()
        repl.context.messages = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
            {"role": "tool", "content": "result"},
        ]
        with self._con():
            handle_command(repl, "/stats")

    def test_config_delegates(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        with self._con(), \
             patch("luckyd_code.cli_commands.dispatcher.handle_config_command") as m:
            handle_command(_make_repl(), "/config list")
        m.assert_called_once()

    def test_export_no_args(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        with self._con():
            handle_command(_make_repl(), "/export")

    def test_export_md(self, tmp_path):
        from luckyd_code.cli_commands.dispatcher import handle_command
        repl = _make_repl()
        repl.context.messages = [{"role": "user", "content": "hello"}]
        with self._con(), patch("luckyd_code.export.export_markdown", return_value="# Export"):
            handle_command(repl, f"/export md {tmp_path / 'out.md'}")

    def test_export_html(self, tmp_path):
        from luckyd_code.cli_commands.dispatcher import handle_command
        repl = _make_repl()
        repl.context.messages = []
        with self._con(), patch("luckyd_code.export.export_html", return_value="<html>"):
            handle_command(repl, f"/export html {tmp_path / 'out.html'}")

    def test_export_unknown_format(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        with self._con():
            handle_command(_make_repl(), "/export pdf file.pdf")

    def test_update(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        with self._con(), \
             patch("luckyd_code.update.do_update", return_value="Up to date."):
            handle_command(_make_repl(), "/update")

    def test_memory_no_args_with_md(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        with self._con(), \
             patch("luckyd_code.memory.load_claude_md", return_value="# Memory"):
            handle_command(_make_repl(), "/memory")

    def test_memory_no_args_no_md(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        with self._con(), \
             patch("luckyd_code.memory.load_claude_md", return_value=None):
            handle_command(_make_repl(), "/memory")

    def test_memory_save(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        repl = _make_repl()
        repl.context.messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        with self._con():
            handle_command(repl, "/memory save myconv")
        repl.memory_mgr.save_memory.assert_called_once()

    def test_memory_save_unnamed(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        repl = _make_repl()
        repl.context.messages = []
        with self._con():
            handle_command(repl, "/memory save")

    def test_memory_search_no_query(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        with self._con():
            handle_command(_make_repl(), "/memory search")

    def test_memory_search_with_results(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        repl = _make_repl()
        repl.memory_mgr.search_memories.return_value = [
            {"name": "c1", "score": 0.9, "snippet": "hello world"}
        ]
        with self._con():
            handle_command(repl, "/memory search hello")

    def test_memory_search_no_results(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        repl = _make_repl()
        repl.memory_mgr.search_memories.return_value = []
        with self._con():
            handle_command(repl, "/memory search hello")

    def test_memory_list_items(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        repl = _make_repl()
        repl.memory_mgr.list_memories.return_value = [{"name": "m1", "type": "conversation"}]
        with self._con():
            handle_command(repl, "/memory list")

    def test_memory_list_empty(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        repl = _make_repl()
        repl.memory_mgr.list_memories.return_value = []
        with self._con():
            handle_command(repl, "/memory list")

    def test_memory_delete_found(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        repl = _make_repl()
        repl.memory_mgr.delete_memory.return_value = True
        with self._con():
            handle_command(repl, "/memory delete conv1")

    def test_memory_delete_not_found(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        repl = _make_repl()
        repl.memory_mgr.delete_memory.return_value = False
        with self._con():
            handle_command(repl, "/memory delete ghost")

    def test_memory_delete_no_name(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        with self._con():
            handle_command(_make_repl(), "/memory delete")

    def test_memory_unknown_sub(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        with self._con():
            handle_command(_make_repl(), "/memory purge")

    def test_index_empty_result(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        repl = _make_repl()
        repl.context.messages = []
        with self._con(), patch("luckyd_code.indexer.index_project", return_value=""):
            handle_command(repl, "/index")

    def test_index_inserts_new(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        repl = _make_repl()
        repl.context.messages = []
        with self._con(), patch("luckyd_code.indexer.index_project", return_value="app.py"):
            handle_command(repl, "/index")

    def test_index_replaces_existing(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        repl = _make_repl()
        repl.context.messages = [
            {"role": "user", "content": "<project-context>\nold\n</project-context>"}
        ]
        with self._con(), patch("luckyd_code.indexer.index_project", return_value="app.py"):
            handle_command(repl, "/index")

    def test_init(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        with self._con(), \
             patch("luckyd_code.init.init_project", return_value="Created MEMORY.md"):
            handle_command(_make_repl(), "/init")

    def test_tasks_no_args(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        with self._con(), patch("luckyd_code.tasks.list_tasks", return_value="No tasks"):
            handle_command(_make_repl(), "/tasks")

    def test_tasks_with_status(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        with self._con(), patch("luckyd_code.tasks.list_tasks", return_value="pending"):
            handle_command(_make_repl(), "/tasks pending")

    def test_plan_no_args(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        with self._con(), patch("luckyd_code.planner.list_plans", return_value="No plans"):
            handle_command(_make_repl(), "/plan")

    def test_plan_approved(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        with self._con(), \
             patch("luckyd_code.planner.plan_and_approve", return_value=MagicMock()), \
             patch("luckyd_code.planner.execute_plan", return_value="Done!"):
            handle_command(_make_repl(), "/plan add error handling")

    def test_plan_cancelled(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        with self._con(), patch("luckyd_code.planner.plan_and_approve", return_value=None):
            handle_command(_make_repl(), "/plan add error handling")

    def test_review(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        with self._con(), \
             patch("luckyd_code.skills.review.review_changes", return_value="diff"):
            handle_command(_make_repl(), "/review")

    def test_security_review(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        with self._con(), \
             patch("luckyd_code.skills.security.security_review", return_value="ok"):
            handle_command(_make_repl(), "/security-review")

    def test_allow_with_tool(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        with self._con(), \
             patch("luckyd_code.permissions.manager._save_to_allowlist"):
            handle_command(_make_repl(), "/allow Read")

    def test_allow_no_args(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        with self._con():
            handle_command(_make_repl(), "/allow")

    def test_undo(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        with self._con(), patch("luckyd_code.undo.undo_last", return_value="Undone: main.py"):
            handle_command(_make_repl(), "/undo")

    def test_sessions_delegates(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        with self._con(), \
             patch("luckyd_code.cli_commands.dispatcher.handle_sessions_command") as m:
            handle_command(_make_repl(), "/sessions list")
        m.assert_called_once()

    def test_brain_delegates(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        with self._con(), \
             patch("luckyd_code.cli_commands.dispatcher.handle_brain_command") as m:
            handle_command(_make_repl(), "/brain status")
        m.assert_called_once()

    def test_audit_delegates(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        with self._con(), \
             patch("luckyd_code.cli_commands.dispatcher.handle_audit_command") as m:
            handle_command(_make_repl(), "/audit run")
        m.assert_called_once()

    def test_background_delegates(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        with self._con(), \
             patch("luckyd_code.cli_commands.dispatcher.handle_background_command") as m:
            handle_command(_make_repl(), "/background list")
        m.assert_called_once()

    def test_watch_no_args(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        with self._con():
            handle_command(_make_repl(), "/watch")

    def test_watch_start(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        repl = _make_repl()
        repl.file_watcher = None
        with self._con(), patch("luckyd_code.file_watcher.FileWatcher") as MockFW:
            MockFW.return_value.is_running = False
            handle_command(repl, "/watch start")

    def test_watch_start_already_running(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        repl = _make_repl()
        repl.file_watcher = MagicMock()
        repl.file_watcher.is_running = True
        with self._con():
            handle_command(repl, "/watch start")

    def test_watch_stop_running(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        repl = _make_repl()
        repl.file_watcher = MagicMock()
        repl.file_watcher.is_running = True
        with self._con():
            handle_command(repl, "/watch stop")
        repl.file_watcher.stop.assert_called_once()

    def test_watch_stop_not_running(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        repl = _make_repl()
        repl.file_watcher = MagicMock()
        repl.file_watcher.is_running = False
        with self._con():
            handle_command(repl, "/watch stop")

    def test_watch_status_with_watcher(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        repl = _make_repl()
        repl.file_watcher = MagicMock()
        repl.file_watcher.status = "running (polling)"
        with self._con():
            handle_command(repl, "/watch status")

    def test_watch_status_no_watcher(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        repl = _make_repl()
        repl.file_watcher = None
        with self._con():
            handle_command(repl, "/watch status")

    def test_watch_unknown_sub(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        with self._con():
            handle_command(_make_repl(), "/watch pause")

    def test_sandbox_docker_available(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        with self._con(), \
             patch("luckyd_code.sandbox.check_docker", return_value=(True, "Docker 24")), \
             patch("luckyd_code.sandbox.get_sandbox") as mock_sb:
            mock_sb.return_value.image = "python:3.12-slim"
            mock_sb.return_value.ensure_image.return_value = True
            handle_command(_make_repl(), "/sandbox status")

    def test_sandbox_no_docker(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        with self._con(), patch("luckyd_code.sandbox.check_docker", return_value=(False, "")):
            handle_command(_make_repl(), "/sandbox status")

    def test_sandbox_unknown_sub(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        with self._con(), patch("luckyd_code.sandbox.check_docker", return_value=(False, "")):
            handle_command(_make_repl(), "/sandbox run")

    def test_backup_create_ok(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        with self._con(), \
             patch("luckyd_code.backup.create_backup",
                   return_value={"ok": True, "message": "Backup ok"}):
            handle_command(_make_repl(), "/backup")

    def test_backup_create_fails(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        with self._con(), \
             patch("luckyd_code.backup.create_backup",
                   return_value={"ok": False, "error": "not a git repo"}):
            handle_command(_make_repl(), "/backup")

    def test_backup_list(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        with self._con(), \
             patch("luckyd_code.backup.list_backups", return_value=[]), \
             patch("luckyd_code.backup.format_backup_list", return_value="No backups"):
            handle_command(_make_repl(), "/backup list")

    def test_backup_restore_ok(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        with self._con(), \
             patch("luckyd_code.backup.restore_backup",
                   return_value={"ok": True, "message": "Restored"}):
            handle_command(_make_repl(), "/backup restore 1")

    def test_backup_restore_fails(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        with self._con(), \
             patch("luckyd_code.backup.restore_backup",
                   return_value={"ok": False, "error": "No backup #1"}):
            handle_command(_make_repl(), "/backup restore 1")

    def test_deps_no_symbol(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        with self._con():
            handle_command(_make_repl(), "/deps")

    def test_deps_with_results(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        repl = _make_repl()
        repl.brain.find_dependents.return_value = [
            {"name": "Foo", "file": "a.py", "relation": "imports"}
        ]
        with self._con():
            handle_command(repl, "/deps Bar")

    def test_deps_no_results(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        repl = _make_repl()
        repl.brain.find_dependents.return_value = []
        with self._con():
            handle_command(repl, "/deps Baz")

    def test_unknown_command(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        with self._con():
            handle_command(_make_repl(), "/foobar")

    def test_orchestrate_no_args(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        with self._con():
            handle_command(_make_repl(), "/orchestrate")

    def test_orchestrate_with_task(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        with self._con(), \
             patch("luckyd_code.orchestrator.Coordinator") as MockCoord:
            MockCoord.return_value.orchestrate.return_value = "Done"
            handle_command(_make_repl(), "/orchestrate add tests")

    def test_debug_backup_ok(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        repl = _make_repl()
        repl.context.messages = []
        with self._con(), \
             patch("luckyd_code.backup.create_backup",
                   return_value={"ok": True, "message": "Backup ready"}):
            handle_command(repl, "/debug")
        repl._chat_loop.assert_called_once()

    def test_debug_backup_fails(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        repl = _make_repl()
        repl.context.messages = []
        with self._con(), \
             patch("luckyd_code.backup.create_backup",
                   return_value={"ok": False, "error": "no git"}):
            handle_command(repl, "/debug")

    def test_self_improve_no_changes(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        repl = _make_repl()
        repl.context.messages = []
        with self._con(), \
             patch("luckyd_code.backup.create_backup",
                   return_value={"ok": True, "message": "ok"}), \
             patch("luckyd_code.self_improve.ImprovementTracker") as MockIT:
            MockIT.return_value.snapshot.return_value = "snap"
            MockIT.return_value.report.return_value = MagicMock(
                files_changed=[], diff_summary=""
            )
            handle_command(repl, "/self-improve")

    def test_self_improve_with_changes(self):
        from luckyd_code.cli_commands.dispatcher import handle_command
        repl = _make_repl()
        repl.context.messages = []
        with self._con(), \
             patch("luckyd_code.backup.create_backup",
                   return_value={"ok": False, "error": "no git"}), \
             patch("luckyd_code.self_improve.ImprovementTracker") as MockIT:
            MockIT.return_value.snapshot.return_value = "snap"
            MockIT.return_value.report.return_value = MagicMock(
                files_changed=["app.py"], diff_summary="+ def foo(): pass"
            )
            handle_command(repl, "/self-improve web")
