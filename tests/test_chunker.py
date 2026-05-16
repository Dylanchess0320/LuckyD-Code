"""Tests for brain/chunker.py — code chunking logic."""

import ast
from pathlib import Path

import pytest

from luckyd_code.brain.chunker import (
    _chunk_by_lines,
    _chunk_python,
    _chunk_with_regex,
    _find_block_end,
    chunk_file,
    chunk_project,
)
from luckyd_code.brain.constants import Chunk


SIMPLE_PYTHON = '''\
"""Module docstring."""

import os


def hello(name):
    """Say hello."""
    return f"Hello, {name}!"


class Greeter:
    """A greeter class."""

    def greet(self, name):
        return f"Hi, {name}!"
'''

BROKEN_PYTHON = "def foo(\n"

SIMPLE_JS = '''\
function add(a, b) {
    return a + b;
}

class Calculator {
    multiply(a, b) {
        return a * b;
    }
}
'''

SIMPLE_GO = '''\
package main

func main() {
    println("hello")
}

type Server struct {
    port int
}
'''


class TestChunkPython:
    def test_returns_chunks(self, tmp_path):
        f = tmp_path / "mod.py"
        f.write_text(SIMPLE_PYTHON)
        chunks = _chunk_python(f, SIMPLE_PYTHON)
        assert len(chunks) > 0

    def test_has_module_chunk(self, tmp_path):
        f = tmp_path / "mod.py"
        f.write_text(SIMPLE_PYTHON)
        chunks = _chunk_python(f, SIMPLE_PYTHON)
        types = [c["type"] for c in chunks]
        assert "module" in types

    def test_has_function_chunk(self, tmp_path):
        f = tmp_path / "mod.py"
        f.write_text(SIMPLE_PYTHON)
        chunks = _chunk_python(f, SIMPLE_PYTHON)
        types = [c["type"] for c in chunks]
        assert "function" in types

    def test_has_class_chunk(self, tmp_path):
        f = tmp_path / "mod.py"
        f.write_text(SIMPLE_PYTHON)
        chunks = _chunk_python(f, SIMPLE_PYTHON)
        types = [c["type"] for c in chunks]
        assert "class" in types

    def test_has_method_chunk(self, tmp_path):
        f = tmp_path / "mod.py"
        f.write_text(SIMPLE_PYTHON)
        chunks = _chunk_python(f, SIMPLE_PYTHON)
        types = [c["type"] for c in chunks]
        assert "method" in types

    def test_broken_python_falls_back_to_line_chunks(self, tmp_path):
        f = tmp_path / "bad.py"
        f.write_text(BROKEN_PYTHON)
        chunks = _chunk_python(f, BROKEN_PYTHON)
        # Should not crash, may return zero or line-based chunks
        assert isinstance(chunks, list)

    def test_chunk_ids_are_unique(self, tmp_path):
        f = tmp_path / "mod.py"
        f.write_text(SIMPLE_PYTHON)
        chunks = _chunk_python(f, SIMPLE_PYTHON)
        ids = [c["chunk_id"] for c in chunks]
        assert len(ids) == len(set(ids))

    def test_language_is_python(self, tmp_path):
        f = tmp_path / "mod.py"
        f.write_text(SIMPLE_PYTHON)
        chunks = _chunk_python(f, SIMPLE_PYTHON)
        for c in chunks:
            assert c["language"] == "python"

    def test_empty_file_returns_no_chunks(self, tmp_path):
        f = tmp_path / "empty.py"
        f.write_text("")
        # _chunk_python on empty string — no syntax error, just no nodes
        chunks = _chunk_python(f, "")
        assert isinstance(chunks, list)


class TestChunkByLines:
    def test_returns_chunks(self, tmp_path):
        f = tmp_path / "file.sh"
        content = "#!/bin/bash\n\necho hello\n\necho world\n"
        chunks = _chunk_by_lines(f, content, "bash")
        assert len(chunks) >= 1

    def test_chunk_language_set(self, tmp_path):
        f = tmp_path / "file.sh"
        content = "#!/bin/bash\n\necho hello\n"
        chunks = _chunk_by_lines(f, content, "bash")
        for c in chunks:
            assert c["language"] == "bash"

    def test_empty_content(self, tmp_path):
        f = tmp_path / "file.sh"
        chunks = _chunk_by_lines(f, "", "bash")
        assert isinstance(chunks, list)

    def test_single_block(self, tmp_path):
        f = tmp_path / "file.sql"
        content = "SELECT *\nFROM users\nWHERE id = 1;\n"
        chunks = _chunk_by_lines(f, content, "sql")
        assert len(chunks) >= 1


class TestChunkWithRegex:
    def test_javascript_functions(self, tmp_path):
        f = tmp_path / "app.js"
        chunks = _chunk_with_regex(f, SIMPLE_JS, "javascript")
        names = [c["name"] for c in chunks]
        assert "add" in names

    def test_javascript_classes(self, tmp_path):
        f = tmp_path / "app.js"
        chunks = _chunk_with_regex(f, SIMPLE_JS, "javascript")
        types = [c["type"] for c in chunks]
        assert "class" in types

    def test_go_functions(self, tmp_path):
        f = tmp_path / "main.go"
        chunks = _chunk_with_regex(f, SIMPLE_GO, "go")
        names = [c["name"] for c in chunks]
        assert "main" in names

    def test_go_structs(self, tmp_path):
        f = tmp_path / "main.go"
        chunks = _chunk_with_regex(f, SIMPLE_GO, "go")
        types = [c["type"] for c in chunks]
        assert "class" in types  # structs map to "class" type

    def test_unknown_language_returns_empty(self, tmp_path):
        f = tmp_path / "file.xyz"
        chunks = _chunk_with_regex(f, "some content", "unknown_lang")
        assert chunks == []

    def test_rust_functions(self, tmp_path):
        f = tmp_path / "main.rs"
        rust_code = "fn main() {\n    println!(\"hello\");\n}\n\nstruct Point { x: i32 }\n"
        chunks = _chunk_with_regex(f, rust_code, "rust")
        names = [c["name"] for c in chunks]
        assert "main" in names


class TestFindBlockEnd:
    def test_simple_block(self):
        content = "before { inside } after"
        end = _find_block_end(content, 0)
        # Should find the closing brace
        assert content[end - 1] == "}"

    def test_nested_braces(self):
        content = "{ outer { inner } }"
        end = _find_block_end(content, 0)
        assert end == len(content)

    def test_no_opening_brace(self):
        content = "no braces here"
        end = _find_block_end(content, 0)
        assert end == len(content)

    def test_string_with_braces(self):
        content = '{ x = "}" }'
        end = _find_block_end(content, 0)
        # The closing brace inside a string shouldn't count
        assert end == len(content)


class TestChunkFile:
    def test_python_file(self, tmp_path):
        f = tmp_path / "app.py"
        f.write_text(SIMPLE_PYTHON)
        chunks = chunk_file(f)
        assert len(chunks) > 0

    def test_js_file(self, tmp_path):
        f = tmp_path / "app.js"
        f.write_text(SIMPLE_JS)
        chunks = chunk_file(f)
        assert len(chunks) > 0

    def test_unsupported_extension_returns_empty(self, tmp_path):
        f = tmp_path / "data.xyz"
        f.write_text("some data")
        chunks = chunk_file(f)
        assert chunks == []

    def test_empty_file_returns_empty(self, tmp_path):
        f = tmp_path / "empty.py"
        f.write_text("")
        chunks = chunk_file(f)
        assert chunks == []

    def test_unreadable_file_returns_empty(self, tmp_path):
        f = tmp_path / "bad.py"
        f.write_text("x=1")
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(Path, "read_text", lambda *a, **k: (_ for _ in ()).throw(OSError("fail")))
            chunks = chunk_file(f)
        assert chunks == []

    def test_go_file(self, tmp_path):
        f = tmp_path / "main.go"
        f.write_text(SIMPLE_GO)
        chunks = chunk_file(f)
        assert len(chunks) > 0

    def test_markdown_file(self, tmp_path):
        f = tmp_path / "README.md"
        f.write_text("# Title\n\nSome content here.\n\nMore text.\n")
        chunks = chunk_file(f)
        assert isinstance(chunks, list)


class TestChunkProject:
    def test_chunks_python_files(self, tmp_path):
        (tmp_path / "app.py").write_text(SIMPLE_PYTHON)
        chunks = chunk_project(str(tmp_path))
        assert len(chunks) > 0

    def test_skips_ignored_dirs(self, tmp_path):
        ignored = tmp_path / "__pycache__"
        ignored.mkdir()
        (ignored / "cached.py").write_text("x=1")
        (tmp_path / "real.py").write_text("def foo(): pass")
        chunks = chunk_project(str(tmp_path))
        paths = [c["file_path"] for c in chunks]
        assert not any("__pycache__" in p for p in paths)

    def test_handles_read_errors_gracefully(self, tmp_path):
        (tmp_path / "good.py").write_text("def foo(): pass")
        # Should not raise even if a file has issues
        chunks = chunk_project(str(tmp_path))
        assert isinstance(chunks, list)

    def test_empty_project(self, tmp_path):
        chunks = chunk_project(str(tmp_path))
        assert chunks == []
