"""Tests for indexer.py — project scanning and context formatting."""

import json
from pathlib import Path

import pytest

from luckyd_code.indexer import (
    _detect_language,
    _detect_frameworks,
    _extract_deps,
    _is_ignored,
    _load_gitignore,
    format_project_context,
    index_project,
    scan_project,
    IGNORED_DIRS,
    IGNORED_EXTS,
)


class TestLoadGitignore:
    def test_returns_empty_when_no_gitignore(self, tmp_path):
        result = _load_gitignore(tmp_path)
        assert result == []

    def test_parses_patterns(self, tmp_path):
        (tmp_path / ".gitignore").write_text("*.pyc\n__pycache__/\n# comment\n\n.venv\n")
        result = _load_gitignore(tmp_path)
        assert "*.pyc" in result
        assert "__pycache__/" in result
        assert ".venv" in result
        assert "# comment" not in result
        assert "" not in result

    def test_handles_read_error_gracefully(self, tmp_path, monkeypatch):
        gi = tmp_path / ".gitignore"
        gi.write_text("*.pyc")
        monkeypatch.setattr(Path, "read_text", lambda *a, **k: (_ for _ in ()).throw(OSError("fail")))
        result = _load_gitignore(tmp_path)
        assert result == []


class TestIsIgnored:
    def test_exact_match(self):
        assert _is_ignored("node_modules", ["node_modules"])

    def test_directory_pattern(self):
        assert _is_ignored("__pycache__", ["__pycache__/"])

    def test_glob_extension(self):
        assert _is_ignored("file.pyc", ["*.pyc"])

    def test_no_match(self):
        assert not _is_ignored("main.py", ["*.pyc", "node_modules"])

    def test_partial_glob_no_match(self):
        assert not _is_ignored("main.py", ["*.js"])


class TestDetectLanguage:
    def test_python(self):
        assert _detect_language(".py") == "Python"

    def test_javascript(self):
        assert _detect_language(".js") == "JavaScript"

    def test_typescript(self):
        assert _detect_language(".ts") == "TypeScript"

    def test_rust(self):
        assert _detect_language(".rs") == "Rust"

    def test_go(self):
        assert _detect_language(".go") == "Go"

    def test_markdown(self):
        assert _detect_language(".md") == "Markdown"

    def test_unknown(self):
        assert _detect_language(".xyz") is None

    def test_toml(self):
        assert _detect_language(".toml") == "TOML"

    def test_shell(self):
        assert _detect_language(".sh") == "Shell"


class TestDetectFrameworks:
    def test_detects_fastapi(self):
        result = _detect_frameworks({"pyproject.toml": ["fastapi", "uvicorn"]}, ["pyproject.toml"])
        assert "FastAPI" in result

    def test_detects_django(self):
        result = _detect_frameworks({"requirements.txt": ["django"]}, ["requirements.txt"])
        assert "Django" in result

    def test_detects_flask(self):
        result = _detect_frameworks({"requirements.txt": ["flask"]}, ["requirements.txt"])
        assert "Flask" in result

    def test_detects_react(self):
        result = _detect_frameworks({"package.json": ["react", "react-dom"]}, ["package.json"])
        assert "React/Next.js" in result

    def test_detects_vue(self):
        result = _detect_frameworks({"package.json": ["vue"]}, ["package.json"])
        assert "Vue" in result

    def test_detects_tailwind(self):
        result = _detect_frameworks({"package.json": ["tailwindcss"]}, ["package.json"])
        assert "Tailwind CSS" in result

    def test_detects_actix(self):
        result = _detect_frameworks({"Cargo.toml": ["actix-web"]}, ["Cargo.toml"])
        assert "Actix/Axum" in result

    def test_empty_config(self):
        result = _detect_frameworks({}, [])
        assert result == []

    def test_deduplication(self):
        result = _detect_frameworks(
            {"a.txt": ["react"], "b.txt": ["react"]}, ["a.txt", "b.txt"]
        )
        assert result.count("React/Next.js") == 1


class TestExtractDeps:
    def test_package_json(self, tmp_path):
        p = tmp_path / "package.json"
        p.write_text(json.dumps({
            "dependencies": {"react": "^18.0.0", "axios": "^1.0.0"},
            "devDependencies": {"jest": "^29.0.0"},
        }))
        result = _extract_deps(p, "package.json")
        assert "react" in result
        assert "axios" in result
        assert "jest" in result

    def test_requirements_txt(self, tmp_path):
        p = tmp_path / "requirements.txt"
        p.write_text("fastapi>=0.100.0\nuvicorn==0.23.0\n# comment\n-r other.txt\n")
        result = _extract_deps(p, "requirements.txt")
        assert "fastapi" in result
        assert "uvicorn" in result
        assert "# comment" not in result

    def test_pyproject_toml(self, tmp_path):
        p = tmp_path / "pyproject.toml"
        p.write_text('[tool.poetry.dependencies]\npython = "^3.11"\nfastapi = "*"\n')
        result = _extract_deps(p, "pyproject.toml")
        assert isinstance(result, list)

    def test_cargo_toml(self, tmp_path):
        p = tmp_path / "Cargo.toml"
        p.write_text("[dependencies]\nserde = \"1.0\"\ntokio = \"1.0\"\n")
        result = _extract_deps(p, "Cargo.toml")
        assert "serde" in result
        assert "tokio" in result

    def test_cargo_toml_stops_at_next_section(self, tmp_path):
        p = tmp_path / "Cargo.toml"
        p.write_text("[dependencies]\nserde = \"1.0\"\n[dev-dependencies]\nmockall = \"0.11\"\n")
        result = _extract_deps(p, "Cargo.toml")
        assert "serde" in result
        assert "mockall" not in result

    def test_unknown_file_returns_empty(self, tmp_path):
        p = tmp_path / "Gemfile"
        p.write_text("gem 'rails'")
        result = _extract_deps(p, "Gemfile")
        assert result == []

    def test_invalid_json_returns_empty(self, tmp_path):
        p = tmp_path / "package.json"
        p.write_text("{bad json")
        result = _extract_deps(p, "package.json")
        assert result == []


class TestScanProject:
    def test_basic_python_project(self, tmp_path):
        (tmp_path / "main.py").write_text("print('hello')")
        (tmp_path / "requirements.txt").write_text("requests\n")
        result = scan_project(tmp_path)
        assert result["name"] == tmp_path.name
        assert "Python" in result["languages"]
        assert "main.py" in result["entry_points"][0]
        assert "requirements.txt" in result["dependency_files"]

    def test_ignores_pycache(self, tmp_path):
        cache = tmp_path / "__pycache__"
        cache.mkdir()
        (cache / "main.cpython-311.pyc").write_bytes(b"")
        (tmp_path / "main.py").write_text("x=1")
        result = scan_project(tmp_path)
        tree_str = "\n".join(result["file_tree"])
        assert "__pycache__" not in tree_str

    def test_ignores_ignored_extensions(self, tmp_path):
        (tmp_path / "image.png").write_bytes(b"")
        (tmp_path / "main.py").write_text("x=1")
        result = scan_project(tmp_path)
        tree_str = "\n".join(result["file_tree"])
        assert "image.png" not in tree_str

    def test_respects_max_depth(self, tmp_path):
        deep = tmp_path / "a" / "b" / "c" / "d"
        deep.mkdir(parents=True)
        (deep / "deep.py").write_text("x=1")
        result = scan_project(tmp_path, max_depth=1)
        tree_str = "\n".join(result["file_tree"])
        assert "deep.py" not in tree_str

    def test_respects_max_items(self, tmp_path):
        for i in range(20):
            (tmp_path / f"file{i}.py").write_text("x=1")
        result = scan_project(tmp_path, max_items=5)
        assert result["total_files"] <= 5

    def test_empty_directory(self, tmp_path):
        result = scan_project(tmp_path)
        assert result["total_files"] == 0
        assert result["languages"] == []

    def test_gitignore_respected(self, tmp_path):
        (tmp_path / ".gitignore").write_text("ignored_dir/\n")
        ignored = tmp_path / "ignored_dir"
        ignored.mkdir()
        (ignored / "secret.py").write_text("x=1")
        result = scan_project(tmp_path)
        tree_str = "\n".join(result["file_tree"])
        assert "ignored_dir" not in tree_str

    def test_multiple_languages(self, tmp_path):
        (tmp_path / "app.py").write_text("x=1")
        (tmp_path / "index.js").write_text("const x=1")
        result = scan_project(tmp_path)
        assert "Python" in result["languages"]
        assert "JavaScript" in result["languages"]


class TestFormatProjectContext:
    def test_basic_output(self, tmp_path):
        (tmp_path / "main.py").write_text("x=1")
        info = scan_project(tmp_path)
        text = format_project_context(info)
        assert "# Project:" in text
        assert tmp_path.name in text

    def test_includes_languages(self, tmp_path):
        (tmp_path / "app.py").write_text("x=1")
        info = scan_project(tmp_path)
        text = format_project_context(info)
        assert "Python" in text

    def test_includes_file_tree(self, tmp_path):
        (tmp_path / "app.py").write_text("x=1")
        info = scan_project(tmp_path)
        text = format_project_context(info)
        assert "app.py" in text

    def test_includes_total_files(self, tmp_path):
        (tmp_path / "a.py").write_text("x=1")
        (tmp_path / "b.py").write_text("x=1")
        info = scan_project(tmp_path)
        text = format_project_context(info)
        assert "2" in text


class TestIndexProject:
    def test_returns_string(self, tmp_path):
        (tmp_path / "main.py").write_text("x=1")
        result = index_project(str(tmp_path))
        assert isinstance(result, str)

    def test_nonexistent_dir_returns_empty(self, tmp_path):
        result = index_project(str(tmp_path / "nope"))
        assert result == ""

    def test_uses_cwd_when_no_arg(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "run.py").write_text("x=1")
        result = index_project()
        assert isinstance(result, str)
        assert len(result) > 0
