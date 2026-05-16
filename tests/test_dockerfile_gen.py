"""Tests for tools/dockerfile_gen.py — context collection and tool logic."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from luckyd_code.tools.dockerfile_gen import (
    DockerfileGenTool,
    _collect_context,
)


class TestCollectContext:
    def test_collects_requirements_txt(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("fastapi\nuvicorn\n")
        ctx = _collect_context(tmp_path)
        assert "requirements.txt" in ctx
        assert "fastapi" in ctx

    def test_collects_package_json(self, tmp_path):
        (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"express": "^4.0"}}))
        ctx = _collect_context(tmp_path)
        assert "package.json" in ctx

    def test_collects_main_py(self, tmp_path):
        (tmp_path / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()")
        ctx = _collect_context(tmp_path)
        assert "main.py" in ctx

    def test_skips_skip_dirs(self, tmp_path):
        venv = tmp_path / ".venv"
        venv.mkdir()
        (venv / "lib.py").write_text("x=1")
        ctx = _collect_context(tmp_path)
        assert ".venv" not in ctx

    def test_truncates_large_files(self, tmp_path):
        large = "x" * 5000
        (tmp_path / "main.py").write_text(large)
        ctx = _collect_context(tmp_path)
        # Should be in context but truncated
        assert "main.py" in ctx
        assert len(ctx) < len(large) + 500

    def test_skips_binary_extensions(self, tmp_path):
        (tmp_path / "image.png").write_bytes(b"\x89PNG")
        ctx = _collect_context(tmp_path)
        assert "image.png" not in ctx

    def test_empty_project_returns_empty(self, tmp_path):
        ctx = _collect_context(tmp_path)
        assert ctx == ""

    def test_env_example_collected(self, tmp_path):
        (tmp_path / ".env.example").write_text("DATABASE_URL=postgres://\n")
        ctx = _collect_context(tmp_path)
        assert ".env.example" in ctx

    def test_pyproject_toml_collected(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[tool.poetry]\nname = 'myapp'\n")
        ctx = _collect_context(tmp_path)
        assert "pyproject.toml" in ctx


class TestDockerfileGenToolMeta:
    def test_name(self):
        assert DockerfileGenTool.name == "DockerfileGen"

    def test_permission_risk(self):
        assert DockerfileGenTool.permission_risk == "medium"

    def test_has_project_dir_param(self):
        assert "project_dir" in DockerfileGenTool.parameters["properties"]

    def test_has_overwrite_param(self):
        assert "overwrite" in DockerfileGenTool.parameters["properties"]


class TestDockerfileGenToolRun:
    def test_nonexistent_directory(self, tmp_path):
        tool = DockerfileGenTool()
        result = tool.run(project_dir=str(tmp_path / "nonexistent"))
        assert "Error" in result
        assert "not a directory" in result

    def test_dockerfile_exists_no_overwrite(self, tmp_path):
        (tmp_path / "Dockerfile").write_text("FROM python:3.12\n")
        tool = DockerfileGenTool()
        result = tool.run(project_dir=str(tmp_path), overwrite=False)
        assert "already exists" in result

    def test_dockerfile_exists_with_overwrite(self, tmp_path):
        (tmp_path / "Dockerfile").write_text("FROM python:3.12\n")
        (tmp_path / "main.py").write_text("print('hi')")
        tool = DockerfileGenTool()
        mock_result = {
            "dockerfile": "FROM python:3.12-slim\nRUN pip install fastapi\n",
            "compose": "",
            "notes": "Run with: docker run -p 8000:8000 myapp",
        }
        with patch.object(tool, "_call_model", return_value=mock_result):
            result = tool.run(project_dir=str(tmp_path), overwrite=True)
        assert "Generated" in result
        assert (tmp_path / "Dockerfile").read_text() == mock_result["dockerfile"].strip()

    def test_empty_project_returns_error(self, tmp_path):
        tool = DockerfileGenTool()
        result = tool.run(project_dir=str(tmp_path))
        assert "Error" in result

    def test_generates_dockerfile(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("fastapi\n")
        (tmp_path / "main.py").write_text("from fastapi import FastAPI\napp=FastAPI()")
        tool = DockerfileGenTool()
        mock_result = {
            "dockerfile": "FROM python:3.12-slim\nCOPY . .\nRUN pip install -r requirements.txt\n",
            "compose": "",
            "notes": "",
        }
        with patch.object(tool, "_call_model", return_value=mock_result):
            result = tool.run(project_dir=str(tmp_path))
        assert "Generated" in result
        assert (tmp_path / "Dockerfile").exists()

    def test_generates_compose_when_present(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("django\n")
        tool = DockerfileGenTool()
        mock_result = {
            "dockerfile": "FROM python:3.12-slim\n",
            "compose": "version: '3'\nservices:\n  web:\n    build: .\n",
            "notes": "Port 8000",
        }
        with patch.object(tool, "_call_model", return_value=mock_result):
            result = tool.run(project_dir=str(tmp_path))
        assert (tmp_path / "docker-compose.yml").exists()
        assert "Notes:" in result

    def test_invalid_json_from_model(self, tmp_path):
        (tmp_path / "main.py").write_text("x=1")
        tool = DockerfileGenTool()
        with patch.object(tool, "_call_model", side_effect=json.JSONDecodeError("bad", "", 0)):
            result = tool.run(project_dir=str(tmp_path))
        assert "Error" in result
        assert "JSON" in result

    def test_model_exception(self, tmp_path):
        (tmp_path / "main.py").write_text("x=1")
        tool = DockerfileGenTool()
        with patch.object(tool, "_call_model", side_effect=Exception("network error")):
            result = tool.run(project_dir=str(tmp_path))
        assert "Error" in result

    def test_call_model_strips_markdown_fences(self, tmp_path):
        (tmp_path / "main.py").write_text("x=1")
        tool = DockerfileGenTool()
        raw_with_fences = '```json\n{"dockerfile": "FROM scratch", "compose": "", "notes": ""}\n```'

        with patch.object(tool, "_call_model_direct", return_value=raw_with_fences):
            result = tool._call_model("context here")
        assert result["dockerfile"] == "FROM scratch"
