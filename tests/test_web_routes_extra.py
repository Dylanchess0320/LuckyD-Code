"""Extra route tests to push coverage past 95%.

Covers: cost, project, review, settings, update, files web routes,
        and the testable helpers in tools/web.py.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ── shared client helpers ─────────────────────────────────────────────────────

def _make_app(*routers):
    app = FastAPI()
    state = MagicMock()
    state.registry = MagicMock()
    state.registry.list_tools.return_value = []
    state.context = MagicMock()
    state.context.messages = []
    app.state.web_state = state
    for r in routers:
        app.include_router(r)
    return app


def _client(*routers):
    return TestClient(_make_app(*routers))


# ══════════════════════════════════════════════════════════════════════════════
# web_routes/cost.py
# ══════════════════════════════════════════════════════════════════════════════

class TestCostRoutes:
    @pytest.fixture
    def c(self):
        from luckyd_code.web_routes.cost import router
        return _client(router)

    def test_get_cost(self, c):
        mock_tracker = MagicMock()
        mock_tracker.get_stats.return_value = {"total_cost": 0.05, "requests": 10}
        with patch("luckyd_code.cost_tracker.CostTracker", return_value=mock_tracker):
            resp = c.get("/api/cost")
        assert resp.status_code == 200
        assert resp.json()["total_cost"] == 0.05

    def test_get_cost_empty(self, c):
        mock_tracker = MagicMock()
        mock_tracker.get_stats.return_value = {}
        with patch("luckyd_code.cost_tracker.CostTracker", return_value=mock_tracker):
            resp = c.get("/api/cost")
        assert resp.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# web_routes/review.py
# ══════════════════════════════════════════════════════════════════════════════

class TestReviewRoutes:
    @pytest.fixture
    def c(self):
        from luckyd_code.web_routes.review import router
        return _client(router)

    def test_review_code(self, c):
        with patch("luckyd_code.web_routes.review.review_skill.review_changes",
                   return_value="diff --git a/foo.py"):
            resp = c.get("/api/review")
        assert resp.status_code == 200
        assert "diff" in resp.json()

    def test_security_review(self, c):
        with patch("luckyd_code.web_routes.review.security_skill.security_review",
                   return_value="No issues found."):
            resp = c.get("/api/security-review")
        assert resp.status_code == 200
        assert resp.json()["analysis"] == "No issues found."


# ══════════════════════════════════════════════════════════════════════════════
# web_routes/update.py
# ══════════════════════════════════════════════════════════════════════════════

class TestUpdateRoutes:
    @pytest.fixture
    def c(self):
        from luckyd_code.web_routes.update import router
        return _client(router)

    def test_check_updates(self, c):
        with patch("luckyd_code.web_routes.update.updater.get_version", return_value="1.2.3"):
            resp = c.get("/api/update/check")
        assert resp.status_code == 200
        assert resp.json()["version"] == "1.2.3"

    def test_do_update(self, c):
        with patch("luckyd_code.web_routes.update.updater.do_update",
                   return_value="Already up to date."):
            resp = c.post("/api/update")
        assert resp.status_code == 200
        assert resp.json()["message"] == "Already up to date."


# ══════════════════════════════════════════════════════════════════════════════
# web_routes/settings.py
# ══════════════════════════════════════════════════════════════════════════════

class TestSettingsRoutes:
    @pytest.fixture
    def c(self):
        from luckyd_code.web_routes.settings import router
        return _client(router)

    def test_get_settings(self, c):
        with patch("luckyd_code.web_routes.settings.cfg.load_settings",
                   return_value={"model": "deepseek-v4", "theme": "dark"}):
            resp = c.get("/api/settings")
        assert resp.status_code == 200
        assert resp.json()["model"] == "deepseek-v4"

    def test_set_settings(self, c):
        with patch("luckyd_code.web_routes.settings.cfg.save_setting") as mock_save:
            resp = c.post("/api/settings", json={"key": "theme", "value": "light"})
        assert resp.status_code == 200
        assert resp.json()["key"] == "theme"
        mock_save.assert_called_once_with("theme", "light")

    def test_list_models(self, c):
        with patch("luckyd_code.model_registry.format_model_list",
                   return_value=[{"id": "deepseek-v4", "name": "DeepSeek V4"}]):
            with patch("luckyd_code.model_registry.get_unique_model_count", return_value=1):
                resp = c.get("/api/models")
        assert resp.status_code == 200
        assert resp.json()["count"] == 1

    def test_set_model(self, c):
        mock_config = MagicMock()
        with patch("luckyd_code.config.Config", return_value=mock_config):
            resp = c.post("/api/models/set", json={"model": "deepseek-v3"})
        assert resp.status_code == 200
        assert resp.json()["model"] == "deepseek-v3"
        assert mock_config.save.called


# ══════════════════════════════════════════════════════════════════════════════
# web_routes/project.py
# ══════════════════════════════════════════════════════════════════════════════

class TestProjectRoutes:
    @pytest.fixture
    def c(self):
        from luckyd_code.web_routes.project import router
        return _client(router)

    def test_init_project(self, c):
        with patch("luckyd_code.web_routes.project.project_init.init_project",
                   return_value="Project initialized"):
            resp = c.post("/api/init")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_list_tasks_empty(self, c):
        with patch("luckyd_code.web_routes.project.tasks.list_tasks",
                   return_value="No tasks."):
            resp = c.get("/api/tasks")
        assert resp.status_code == 200
        assert resp.json()["tasks"] == "No tasks."

    def test_list_tasks_with_status(self, c):
        with patch("luckyd_code.web_routes.project.tasks.list_tasks",
                   return_value="Task A") as mock_lt:
            resp = c.get("/api/tasks?status=pending")
        assert resp.status_code == 200
        mock_lt.assert_called_once_with("pending")

    def test_list_plans(self, c):
        with patch("luckyd_code.web_routes.project.planner.list_plans",
                   return_value=["plan_a", "plan_b"]):
            resp = c.get("/api/plans")
        assert resp.status_code == 200
        assert resp.json()["plans"] == ["plan_a", "plan_b"]

    def test_reindex_no_context(self, c):
        with patch("luckyd_code.indexer.index_project", return_value=None):
            resp = c.post("/api/index")
        assert resp.status_code == 200
        assert resp.json()["items"] == 0

    def test_reindex_replaces_existing(self):
        from luckyd_code.web_routes.project import router
        app = FastAPI()
        app.include_router(router)
        state = MagicMock()
        state.context = MagicMock()
        state.context.messages = [
            {"role": "user", "content": "<project-context>\nold\n</project-context>"}
        ]
        app.state.web_state = state
        c = TestClient(app)
        with patch("luckyd_code.indexer.index_project",
                   return_value="file1.py\nfile2.py"):
            resp = c.post("/api/index")
        assert resp.status_code == 200
        assert resp.json()["items"] > 0
        # Existing project-context message should be replaced
        assert state.context.messages[0]["content"].startswith("<project-context>")

    def test_reindex_inserts_new(self):
        from luckyd_code.web_routes.project import router
        app = FastAPI()
        app.include_router(router)
        state = MagicMock()
        state.context = MagicMock()
        state.context.messages = [
            {"role": "system", "content": "You are helpful."}
        ]
        app.state.web_state = state
        c = TestClient(app)
        with patch("luckyd_code.indexer.index_project",
                   return_value="file1.py\nfile2.py"):
            resp = c.post("/api/index")
        assert resp.status_code == 200
        assert len(state.context.messages) == 2  # system + new project-context


# ══════════════════════════════════════════════════════════════════════════════
# web_routes/files.py
# ══════════════════════════════════════════════════════════════════════════════

class TestFilesRoutes:
    @pytest.fixture
    def c(self):
        from luckyd_code.web_routes.files import router
        return _client(router)

    # ── _safe_resolve ─────────────────────────────────────────────────────────

    def test_safe_resolve_value_error_returns_none(self):
        from luckyd_code.web_routes.files import _safe_resolve
        with patch("luckyd_code.web_routes.files.path_validate.safe_resolve",
                   side_effect=ValueError("traversal")):
            assert _safe_resolve("../../etc/passwd") is None

    def test_safe_resolve_ok(self, tmp_path):
        from luckyd_code.web_routes.files import _safe_resolve
        with patch("luckyd_code.web_routes.files.path_validate.safe_resolve",
                   return_value=str(tmp_path)):
            assert _safe_resolve(str(tmp_path)) == str(tmp_path)

    # ── list_tools ────────────────────────────────────────────────────────────

    def test_list_tools(self, c):
        resp = c.get("/api/tools")
        assert resp.status_code == 200
        assert "tools" in resp.json()

    # ── list_files ────────────────────────────────────────────────────────────

    def test_list_files_traversal_denied(self, c):
        with patch("luckyd_code.web_routes.files._safe_resolve", return_value=None):
            resp = c.get("/api/files?dir=../../etc")
        assert resp.status_code == 403

    def test_list_files_not_found(self, c, tmp_path):
        missing = str(tmp_path / "nonexistent")
        with patch("luckyd_code.web_routes.files._safe_resolve", return_value=missing):
            resp = c.get(f"/api/files?dir={missing}")
        assert resp.status_code == 404

    def test_list_files_not_a_dir(self, c, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("hello")
        with patch("luckyd_code.web_routes.files._safe_resolve", return_value=str(f)):
            resp = c.get(f"/api/files?dir={f}")
        assert resp.status_code == 400

    def test_list_files_permission_denied(self, c, tmp_path):
        with patch("luckyd_code.web_routes.files._safe_resolve", return_value=str(tmp_path)):
            with patch("pathlib.Path.iterdir", side_effect=PermissionError("denied")):
                resp = c.get(f"/api/files?dir={tmp_path}")
        assert resp.status_code == 403

    def test_list_files_ok(self, c, tmp_path):
        (tmp_path / "a.py").write_text("x=1")
        (tmp_path / "subdir").mkdir()
        with patch("luckyd_code.web_routes.files._safe_resolve", return_value=str(tmp_path)):
            resp = c.get(f"/api/files?dir={tmp_path}")
        assert resp.status_code == 200
        names = [f["name"] for f in resp.json()["files"]]
        assert "a.py" in names

    # ── read_file ─────────────────────────────────────────────────────────────

    def test_read_file_no_path(self, c):
        resp = c.get("/api/read-file")
        assert resp.status_code == 400

    def test_read_file_traversal_denied(self, c):
        with patch("luckyd_code.web_routes.files._safe_resolve", return_value=None):
            resp = c.get("/api/read-file?path=../../etc/passwd")
        assert resp.status_code == 403

    def test_read_file_not_found(self, c, tmp_path):
        missing = str(tmp_path / "ghost.py")
        with patch("luckyd_code.web_routes.files._safe_resolve", return_value=missing):
            resp = c.get(f"/api/read-file?path={missing}")
        assert resp.status_code == 404

    def test_read_file_is_dir(self, c, tmp_path):
        with patch("luckyd_code.web_routes.files._safe_resolve", return_value=str(tmp_path)):
            resp = c.get(f"/api/read-file?path={tmp_path}")
        assert resp.status_code == 400

    def test_read_file_too_large(self, c, tmp_path):
        import stat as stat_module
        f = tmp_path / "big.txt"
        f.write_text("x")
        mock_stat_result = MagicMock()
        mock_stat_result.st_size = 2_000_000
        mock_stat_result.st_mode = stat_module.S_IFREG | 0o644  # regular file flag
        with patch("luckyd_code.web_routes.files._safe_resolve", return_value=str(f)):
            with patch("pathlib.Path.stat", return_value=mock_stat_result):
                resp = c.get(f"/api/read-file?path={f}")
        assert resp.status_code == 413

    def test_read_file_exception(self, c, tmp_path):
        f = tmp_path / "err.txt"
        f.write_text("hello")
        with patch("luckyd_code.web_routes.files._safe_resolve", return_value=str(f)):
            with patch("pathlib.Path.read_text", side_effect=OSError("disk error")):
                resp = c.get(f"/api/read-file?path={f}")
        assert resp.status_code == 500

    def test_read_file_ok(self, c, tmp_path):
        f = tmp_path / "code.py"
        f.write_text("print('hello')")
        with patch("luckyd_code.web_routes.files._safe_resolve", return_value=str(f)):
            resp = c.get(f"/api/read-file?path={f}")
        assert resp.status_code == 200
        assert resp.json()["content"] == "print('hello')"

    # ── write_file ────────────────────────────────────────────────────────────

    def test_write_file_no_path(self, c):
        resp = c.post("/api/write-file", json={"path": "", "content": "x=1"})
        assert resp.status_code == 400

    def test_write_file_content_too_large(self, c):
        big = "x" * (10_485_760 + 1)
        with patch("luckyd_code.web_routes.files._safe_resolve", return_value="/tmp/f.py"):
            resp = c.post("/api/write-file", json={"path": "/tmp/f.py", "content": big})
        assert resp.status_code == 413

    def test_write_file_traversal_denied(self, c):
        with patch("luckyd_code.web_routes.files._safe_resolve", return_value=None):
            resp = c.post("/api/write-file", json={"path": "../../x", "content": "x"})
        assert resp.status_code == 403

    def test_write_file_ok(self, c, tmp_path):
        f = tmp_path / "out.py"
        with patch("luckyd_code.web_routes.files._safe_resolve", return_value=str(f)):
            resp = c.post("/api/write-file", json={"path": str(f), "content": "x=1"})
        assert resp.status_code == 200
        assert f.read_text() == "x=1"

    def test_write_file_exception(self, c, tmp_path):
        f = tmp_path / "out.py"
        with patch("luckyd_code.web_routes.files._safe_resolve", return_value=str(f)):
            with patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
                resp = c.post("/api/write-file", json={"path": str(f), "content": "x=1"})
        assert resp.status_code == 500

    # ── edit_file ─────────────────────────────────────────────────────────────

    def test_edit_file_missing_params(self, c):
        resp = c.post("/api/edit-file", json={"path": "", "old_string": "", "new_string": ""})
        assert resp.status_code == 400

    def test_edit_file_traversal_denied(self, c):
        with patch("luckyd_code.web_routes.files._safe_resolve", return_value=None):
            resp = c.post("/api/edit-file",
                          json={"path": "../../x", "old_string": "a", "new_string": "b"})
        assert resp.status_code == 403

    def test_edit_file_not_found(self, c, tmp_path):
        missing = str(tmp_path / "ghost.py")
        with patch("luckyd_code.web_routes.files._safe_resolve", return_value=missing):
            resp = c.post("/api/edit-file",
                          json={"path": missing, "old_string": "a", "new_string": "b"})
        assert resp.status_code == 404

    def test_edit_file_old_string_not_found(self, c, tmp_path):
        f = tmp_path / "code.py"
        f.write_text("x = 1")
        with patch("luckyd_code.web_routes.files._safe_resolve", return_value=str(f)):
            resp = c.post("/api/edit-file",
                          json={"path": str(f), "old_string": "NOTHERE", "new_string": "y"})
        assert resp.status_code == 400

    def test_edit_file_ok(self, c, tmp_path):
        f = tmp_path / "code.py"
        f.write_text("x = 1\ny = 2")
        with patch("luckyd_code.web_routes.files._safe_resolve", return_value=str(f)):
            resp = c.post("/api/edit-file",
                          json={"path": str(f), "old_string": "x = 1", "new_string": "x = 99"})
        assert resp.status_code == 200
        assert f.read_text() == "x = 99\ny = 2"

    def test_edit_file_exception(self, c, tmp_path):
        f = tmp_path / "code.py"
        f.write_text("x = 1")
        with patch("luckyd_code.web_routes.files._safe_resolve", return_value=str(f)):
            with patch("pathlib.Path.read_text", side_effect=OSError("io error")):
                resp = c.post("/api/edit-file",
                              json={"path": str(f), "old_string": "x", "new_string": "y"})
        assert resp.status_code == 500


# ══════════════════════════════════════════════════════════════════════════════
# tools/web.py — testable helpers (not pragma: no cover)
# ══════════════════════════════════════════════════════════════════════════════

class TestWebHelpers:
    def test_extract_text_strips_script(self):
        from luckyd_code.tools.web import _extract_text
        html = "<html><body><script>var x=1;</script><p>Hello world</p></body></html>"
        text = _extract_text(html)
        assert "Hello world" in text
        assert "var x=1" not in text

    def test_extract_text_strips_nav(self):
        from luckyd_code.tools.web import _extract_text
        html = "<html><body><nav>Skip to main</nav><main>Content here</main></body></html>"
        text = _extract_text(html)
        assert "Content here" in text
        assert "Skip to main" not in text

    def test_extract_text_empty(self):
        from luckyd_code.tools.web import _extract_text
        assert _extract_text("<html><body></body></html>") == ""

    def test_try_meta_extraction_with_description(self):
        from luckyd_code.tools.web import _try_meta_extraction
        html = '''<html><head>
            <title>My Site</title>
            <meta name="description" content="Best site ever">
        </head><body></body></html>'''
        result = _try_meta_extraction(html)
        assert result is not None
        assert "Best site ever" in result

    def test_try_meta_extraction_og_title(self):
        from luckyd_code.tools.web import _try_meta_extraction
        html = '''<html><head>
            <meta property="og:title" content="OG Title Here">
            <meta property="og:description" content="OG desc">
        </head><body></body></html>'''
        result = _try_meta_extraction(html)
        assert result is not None
        assert "OG Title Here" in result

    def test_try_meta_extraction_no_meta(self):
        from luckyd_code.tools.web import _try_meta_extraction
        assert _try_meta_extraction("<html><body>Nothing</body></html>") is None

    def test_try_meta_extraction_site_name(self):
        from luckyd_code.tools.web import _try_meta_extraction
        html = '''<html><head>
            <meta property="og:site_name" content="GitHub">
            <meta name="description" content="Code hosting">
        </head></html>'''
        result = _try_meta_extraction(html)
        assert "GitHub" in result

    def test_try_oembed_non_youtube_url(self):
        from luckyd_code.tools.web import _try_oembed
        # Non-YouTube URL — oEmbed endpoint will 404/fail
        import httpx
        with patch("httpx.get", side_effect=Exception("network error")):
            assert _try_oembed("https://example.com/video") is None

    def test_try_oembed_success(self):
        from luckyd_code.tools.web import _try_oembed
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "title": "Cool Video",
            "author_name": "Cool Channel",
        }
        with patch("httpx.get", return_value=mock_resp):
            result = _try_oembed("https://www.youtube.com/watch?v=abc123")
        assert result is not None
        assert "Cool Video" in result
        assert "Cool Channel" in result

    def test_try_oembed_non_200(self):
        from luckyd_code.tools.web import _try_oembed
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        with patch("httpx.get", return_value=mock_resp):
            assert _try_oembed("https://www.youtube.com/watch?v=xyz") is None
