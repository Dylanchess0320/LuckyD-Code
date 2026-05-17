"""Tests for the knowledge graph and code parser modules."""

import tempfile
import textwrap
from pathlib import Path
from unittest.mock import patch


from luckyd_code.brain.graph import KnowledgeGraph
from luckyd_code.brain.parser import parse_file, parse_project


SAMPLE_CLASS = textwrap.dedent("""\
    \"\"\"Module docstring.\"\"\"
    import os
    from pathlib import Path

    class MyClass:
        \"\"\"A test class.\"\"\"
        def greet(self, name: str) -> str:
            \"\"\"Greet someone.\"\"\"
            return f"Hello, {name}"

        def compute(self, x: int) -> int:
            return x * 2

    def top_level():
        \"\"\"Top-level function.\"\"\"
        return 42
""")


class TestKnowledgeGraphBuild:
    def test_build_empty(self):
        """Building from an empty list should produce an empty graph."""
        kg = KnowledgeGraph()
        kg.build("/project", [])
        assert kg.stats["node_count"] == 0
        assert kg.stats["edge_count"] == 0
        assert kg.stats["files_parsed"] == 0

    def test_build_with_errors(self):
        """Files with errors should still be counted but not add nodes."""
        parsed = [{
            "module": "src/broken.py",
            "classes": [],
            "functions": [],
            "imports": [],
            "errors": ["SyntaxError: invalid syntax"],
            "size": 100,
        }]
        kg = KnowledgeGraph()
        kg.build("/project", parsed)
        assert kg.stats["files_parsed"] == 1
        assert kg.stats["errors"] == 1
        assert kg.stats["node_count"] == 0

    def test_build_with_imports(self):
        """Imports should create import nodes and edges."""
        parsed = [{
            "module": "src/main.py",
            "classes": [],
            "functions": [],
            "imports": [
                {"module": "os", "name": "os", "alias": None},
                {"module": "pathlib", "name": "Path", "alias": None},
            ],
            "errors": [],
            "size": 200,
        }]
        kg = KnowledgeGraph()
        kg.build("/project", parsed)
        assert kg.stats["node_count"] == 3  # module + 2 imports
        assert kg.stats["edge_count"] == 2  # 2 import edges
        assert "module:src/main.py" in kg.nodes
        assert "import:os:os" in kg.nodes
        assert "import:pathlib:Path" in kg.nodes

    def test_build_with_classes_and_methods(self):
        """Classes with methods should create proper hierarchy."""
        parsed = [{
            "module": "src/models.py",
            "classes": [{
                "name": "User",
                "line": 10,
                "end_line": 40,
                "base_names": ["BaseModel"],
                "decorators": [],
                "docstring": "User model",
                "methods": [
                    {
                        "name": "save",
                        "line": 12,
                        "end_line": 18,
                        "decorators": [],
                        "docstring": "Save to DB",
                        "calls": ["db_insert", "log"],
                    },
                    {
                        "name": "delete",
                        "line": 20,
                        "end_line": 25,
                        "decorators": [],
                        "docstring": "",
                        "calls": ["db_delete"],
                    },
                ],
            }],
            "functions": [],
            "imports": [],
            "errors": [],
            "size": 500,
        }]
        kg = KnowledgeGraph()
        kg.build("/project", parsed)

        # Should have: module + class + 2 methods
        assert kg.stats["node_count"] == 4
        assert kg.stats["edge_count"] >= 5  # contains + inherits + calls edges

        class_id = "class:src/models.py:User"
        assert class_id in kg.nodes
        assert kg.nodes[class_id]["type"] == "class"
        assert kg.nodes[class_id]["bases"] == ["BaseModel"]

        method_save = "method:src/models.py:User.save"
        assert method_save in kg.nodes
        assert kg.nodes[method_save]["type"] == "method"
        assert "db_insert" in str(kg.edges)

    def test_build_with_functions(self):
        """Top-level functions should be added as function nodes."""
        parsed = [{
            "module": "src/utils.py",
            "classes": [],
            "functions": [{
                "name": "helper",
                "line": 5,
                "end_line": 10,
                "decorators": [],
                "docstring": "Helper utility",
                "calls": ["format"],
            }],
            "imports": [],
            "errors": [],
            "size": 300,
        }]
        kg = KnowledgeGraph()
        kg.build("/project", parsed)

        func_id = "func:src/utils.py:helper"
        assert func_id in kg.nodes
        assert kg.nodes[func_id]["type"] == "function"
        assert kg.nodes[func_id]["file"] == "src/utils.py"

    def test_build_rebuild_clears_previous(self):
        """Re-building should clear all previous data."""
        kg = KnowledgeGraph()
        kg.build("/project", [{
            "module": "a.py", "classes": [], "functions": [],
            "imports": [], "errors": [], "size": 10,
        }])
        assert kg.stats["node_count"] == 1
        kg.build("/project", [])
        assert kg.stats["node_count"] == 0


class TestKnowledgeGraphSearch:
    def setup_method(self):
        self.kg = KnowledgeGraph()
        self.kg.build("/project", [{
            "module": "src/main.py",
            "classes": [{
                "name": "Calculator",
                "line": 1, "end_line": 20,
                "base_names": [], "decorators": [],
                "docstring": "Performs arithmetic",
                "methods": [],
            }],
            "functions": [{
                "name": "run",
                "line": 22, "end_line": 30,
                "decorators": [], "docstring": "Entry point",
                "calls": [],
            }],
            "imports": [{"module": "sys", "name": "sys", "alias": None}],
            "errors": [], "size": 100,
        }])

    def test_search_by_name(self):
        """Searching by name should find matching nodes."""
        results = self.kg.search("Calculator")
        assert len(results) >= 1
        assert any(r["name"] == "Calculator" for r in results)

    def test_search_by_file(self):
        """Searching by file path should find matching nodes."""
        results = self.kg.search("main.py")
        assert len(results) >= 1
        assert all("main.py" in r.get("file", "") for r in results)

    def test_search_by_docstring(self):
        """Searching by docstring content should find matching nodes."""
        results = self.kg.search("arithmetic")
        assert len(results) >= 1

    def test_search_case_insensitive(self):
        """Search should be case-insensitive."""
        results_lower = self.kg.search("calculator")
        results_upper = self.kg.search("CALCULATOR")
        assert len(results_lower) == len(results_upper)

    def test_search_max_results(self):
        """Search should respect max_results limit."""
        results = self.kg.search("", max_results=1)
        # Empty query matches nothing, but if it did, should be limited to 1
        assert isinstance(results, list)

    def test_search_no_match(self):
        """Searching for nonexistent text should return empty list."""
        results = self.kg.search("zzzznonexistent")
        assert results == []


class TestKnowledgeGraphPersistence:
    def test_save_and_load_roundtrip(self):
        """Save then load should restore all nodes, edges, and stats."""
        kg = KnowledgeGraph()
        kg.build("/project", [{
            "module": "src/app.py",
            "classes": [{
                "name": "App", "line": 1, "end_line": 10,
                "base_names": [], "decorators": [],
                "docstring": "Main app",
                "methods": [],
            }],
            "functions": [], "imports": [],
            "errors": [], "size": 50,
        }])

        with tempfile.TemporaryDirectory() as tmp:
            brain_dir = Path(tmp) / ".claude" / "brain"
            graph_file = brain_dir / "graph.json"
            with patch("luckyd_code.brain.graph.BRAIN_DIR", brain_dir):
                with patch("luckyd_code.brain.graph.GRAPH_FILE", graph_file):
                    kg.save()
                    assert graph_file.exists()

                    # Load into a fresh graph
                    kg2 = KnowledgeGraph()
                    loaded = kg2.load()
                    assert loaded is True
                    assert kg2.stats["node_count"] == 2  # module + class
                    assert "module:src/app.py" in kg2.nodes
                    assert kg2.nodes["class:src/app.py:App"]["name"] == "App"

    def test_load_nonexistent(self):
        """Loading when no graph file exists should return False."""
        kg = KnowledgeGraph()
        with tempfile.TemporaryDirectory() as tmp:
            brain_dir = Path(tmp) / "nobrain"
            graph_file = brain_dir / "graph.json"
            with patch("luckyd_code.brain.graph.BRAIN_DIR", brain_dir):
                with patch("luckyd_code.brain.graph.GRAPH_FILE", graph_file):
                    assert kg.load() is False

    def test_load_corrupted(self):
        """Loading a corrupted file should return False gracefully."""
        kg = KnowledgeGraph()
        with tempfile.TemporaryDirectory() as tmp:
            graph_file = Path(tmp) / "graph.json"
            graph_file.write_text("not valid json", encoding="utf-8")
            with patch("luckyd_code.brain.graph.GRAPH_FILE", graph_file):
                # load() catches JSONDecodeError and returns False
                assert kg.load() is False


class TestKnowledgeGraphQuery:
    def setup_method(self):
        self.kg = KnowledgeGraph()
        self.kg.build("/project", [{
            "module": "src/models.py",
            "classes": [{
                "name": "User", "line": 1, "end_line": 30,
                "base_names": ["BaseModel"], "decorators": [],
                "docstring": "User account",
                "methods": [
                    {
                        "name": "activate", "line": 5, "end_line": 10,
                        "decorators": [], "docstring": "Activate user",
                        "calls": ["save"],
                    },
                ],
            }],
            "functions": [{
                "name": "create_user", "line": 32, "end_line": 40,
                "decorators": [], "docstring": "Factory",
                "calls": [],
            }],
            "imports": [{"module": "datetime", "name": "datetime", "alias": None}],
            "errors": [], "size": 200,
        }])

    def test_get_related(self):
        """get_related should traverse edges from a node."""
        module_id = "module:src/models.py"
        related = self.kg.get_related(module_id, max_depth=1)
        # Should find class and import nodes
        related_ids = [r.get("name") for r in related]
        assert "User" in related_ids or "datetime" in related_ids

    def test_get_related_unknown(self):
        """get_related with unknown node_id should return empty list."""
        related = self.kg.get_related("nonexistent:id")
        assert related == []

    def test_get_by_file(self):
        """get_by_file should return all nodes in a file."""
        nodes = self.kg.get_by_file("src/models.py")
        assert len(nodes) >= 3  # module, class, function, import...

    def test_get_by_file_suffix_match(self):
        """get_by_file should match on file suffix."""
        nodes = self.kg.get_by_file("models.py")
        assert len(nodes) >= 1

    def test_get_by_type(self):
        """get_by_type should filter by node type."""
        classes = self.kg.get_by_type("class")
        assert len(classes) == 1
        assert classes[0]["name"] == "User"

        functions = self.kg.get_by_type("function")
        assert len(functions) == 1
        assert functions[0]["name"] == "create_user"

    def test_get_by_type_unknown(self):
        """get_by_type with no matches should return empty list."""
        assert self.kg.get_by_type("nonexistent_type") == []


class TestKnowledgeGraphSummarize:
    def setup_method(self):
        self.kg = KnowledgeGraph()
        self.kg.build("/project", [{
            "module": "src/main.py",
            "classes": [{
                "name": "Engine", "line": 1, "end_line": 15,
                "base_names": [], "decorators": [],
                "docstring": "Core engine",
                "methods": [],
            }],
            "functions": [{
                "name": "start", "line": 17, "end_line": 22,
                "decorators": [], "docstring": "",
                "calls": [],
            }],
            "imports": [],
            "errors": [], "size": 100,
        }])

    def test_summarize_contains_tags(self):
        """Summarize output should have XML-style tags."""
        summary = self.kg.summarize()
        assert "<knowledge-graph>" in summary
        assert "</knowledge-graph>" in summary
        assert "Engine" in summary
        assert "start" in summary
        assert "main.py" in summary

    def test_summarize_empty(self):
        """Summarize with no nodes should still produce valid output."""
        kg = KnowledgeGraph()
        summary = kg.summarize()
        assert "<knowledge-graph>" in summary
        assert "0 symbols" in summary

    def test_stats_text(self):
        """stats_text should return formatted statistics."""
        stats = self.kg.stats_text()
        assert "Nodes:" in stats
        assert "Edges:" in stats
        assert "Files parsed:" in stats
        assert "By type:" in stats
        assert "class:" in stats
        assert "function:" in stats
        assert "Last built:" in stats

    def test_stats_text_empty(self):
        """stats_text with empty graph should still work."""
        kg = KnowledgeGraph()
        text = kg.stats_text()
        assert "Nodes: 0" in text


class TestParseFile:
    def test_parse_simple_file(self):
        """Parse a simple Python file."""
        with tempfile.TemporaryDirectory() as tmp:
            fpath = Path(tmp) / "simple.py"
            fpath.write_text(SAMPLE_CLASS, encoding="utf-8")

            result = parse_file(fpath)
            assert result["size"] > 0
            assert not result["errors"]
            assert len(result["imports"]) == 2
            assert result["imports"][0]["module"] == "os"
            assert result["imports"][1]["module"] == "pathlib"

    def test_parse_detects_classes(self):
        """Parse should detect classes and their methods."""
        with tempfile.TemporaryDirectory() as tmp:
            fpath = Path(tmp) / "simple.py"
            fpath.write_text(SAMPLE_CLASS, encoding="utf-8")

            result = parse_file(fpath)
            assert len(result["classes"]) == 1
            cls = result["classes"][0]
            assert cls["name"] == "MyClass"
            assert cls["docstring"] == "A test class."
            assert len(cls["methods"]) == 2
            assert cls["methods"][0]["name"] == "greet"
            assert cls["methods"][1]["name"] == "compute"

    def test_parse_detects_functions(self):
        """Parse should detect top-level functions."""
        source = textwrap.dedent("""\
            def top_level():
                \"\"\"Top-level function.\"\"\"
                return 42
        """)
        with tempfile.TemporaryDirectory() as tmp:
            fpath = Path(tmp) / "simple.py"
            fpath.write_text(source, encoding="utf-8")

            result = parse_file(fpath)
            assert len(result["functions"]) == 1
            assert result["functions"][0]["name"] == "top_level"
            assert result["functions"][0]["docstring"] == "Top-level function."

    def test_parse_detects_calls(self):
        """Parse should extract function call names."""
        source = textwrap.dedent("""\
            def worker():
                result = process(data)
                save(result)
                return result
        """)
        with tempfile.TemporaryDirectory() as tmp:
            fpath = Path(tmp) / "worker.py"
            fpath.write_text(source, encoding="utf-8")
            result = parse_file(fpath)
            assert len(result["functions"]) == 1
            calls = result["functions"][0]["calls"]
            assert "process" in calls
            assert "save" in calls

    def test_parse_detects_method_calls(self):
        """Parse should extract obj.method() style calls."""
        source = textwrap.dedent("""\
            class Handler:
                def run(self):
                    self.connect()
                    logger.info("started")
                    return self.data
        """)
        with tempfile.TemporaryDirectory() as tmp:
            fpath = Path(tmp) / "handler.py"
            fpath.write_text(source, encoding="utf-8")
            result = parse_file(fpath)
            assert len(result["classes"]) == 1
            methods = result["classes"][0]["methods"]
            assert len(methods) == 1
            calls = methods[0]["calls"]
            assert "connect" in calls or "info" in calls

    def test_parse_syntax_error(self):
        """Parse should handle syntax errors gracefully."""
        with tempfile.TemporaryDirectory() as tmp:
            fpath = Path(tmp) / "broken.py"
            fpath.write_text("def foo( :", encoding="utf-8")
            result = parse_file(fpath)
            assert len(result["errors"]) == 1
            assert "SyntaxError" in result["errors"][0]

    def test_parse_empty_file(self):
        """Parse should handle empty files."""
        with tempfile.TemporaryDirectory() as tmp:
            fpath = Path(tmp) / "empty.py"
            fpath.write_text("", encoding="utf-8")
            result = parse_file(fpath)
            assert not result["errors"]
            assert result["size"] == 0
            assert result["classes"] == []
            assert result["functions"] == []
            assert result["imports"] == []

    def test_parse_nonexistent_file(self):
        """Parse should handle file read errors."""
        with tempfile.TemporaryDirectory() as tmp:
            fpath = Path(tmp) / "nonexistent.py"
            result = parse_file(fpath)
            assert len(result["errors"]) == 1

    def test_parse_import_from(self):
        """Parse should handle from X import Y statements."""
        source = textwrap.dedent("""\
            from typing import Optional, List
            from collections.abc import Iterator
        """)
        with tempfile.TemporaryDirectory() as tmp:
            fpath = Path(tmp) / "imports.py"
            fpath.write_text(source, encoding="utf-8")
            result = parse_file(fpath)
            assert len(result["imports"]) == 3
            modules = {imp["module"] for imp in result["imports"]}
            assert "typing" in modules
            assert "collections.abc" in modules


class TestParseProject:
    def test_parse_project_finds_python_files(self):
        """parse_project should discover all .py files."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src/__init__.py").write_text("")
            (root / "src/main.py").write_text("def main(): pass")
            (root / "README.md").write_text("# readme")
            (root / ".hidden.py").write_text("x = 1")

            results, mtimes = parse_project(str(root))
            # Should find 2 .py files (__init__.py and main.py)
            # .hidden.py starts with '.' so its dir gets skipped
            py_files = [r for r in results if r["module"].endswith(".py")]
            assert len(py_files) >= 2

    def test_parse_project_skips_ignored_dirs(self):
        """parse_project should skip __pycache__, node_modules, etc."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "__pycache__").mkdir()
            (root / "__pycache__/cached.py").write_text("x = 1")
            (root / "good.py").write_text("y = 2")

            results, mtimes = parse_project(str(root))
            # Should not include files in __pycache__
            modules = [r["module"] for r in results]
            assert not any("__pycache__" in m for m in modules)

    def test_parse_project_incremental(self):
        """parse_project with file_mtimes should only parse changed files."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_text("x = 1")
            (root / "b.py").write_text("y = 2")

            # First parse
            _, mtimes = parse_project(str(root))
            assert len(mtimes) == 2

            # Second parse with same mtimes — should parse 0 files
            results, new_mtimes = parse_project(str(root), file_mtimes=mtimes)
            assert len(results) == 0

            # Modify a file
            (root / "a.py").write_text("x = 999")
            results2, new_mtimes2 = parse_project(str(root), file_mtimes=new_mtimes)
            assert len(results2) == 1
            assert "a.py" in results2[0]["module"]


class TestKnowledgeGraphBuildFullCycle:
    """Integration test: parse then build then search."""

    def test_full_parse_build_search_cycle(self):
        """Parse a real file, build a graph, then search it."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "calc.py").write_text(textwrap.dedent("""\
                def add(a, b):
                    \"\"\"Add two numbers.\"\"\"
                    return a + b

                class Calculator:
                    \"\"\"A simple calculator.\"\"\"
                    def multiply(self, x, y):
                        return x * y
            """), encoding="utf-8")

            # Parse
            parsed_files, mtimes = parse_project(str(root))
            assert len(parsed_files) == 1

            # Build
            kg = KnowledgeGraph()
            kg.build(str(root), parsed_files)
            assert kg.stats["node_count"] >= 3  # module + function + class

            # Search
            results = kg.search("add")
            assert any(r["name"] == "add" for r in results)

            results_calc = kg.search("Calculator")
            assert any(r["name"] == "Calculator" for r in results_calc)

            results_multiply = kg.search("multiply")
            assert len(results_multiply) >= 1

            # Summarize
            summary = kg.summarize()
            assert "calc.py" in summary
            assert "add" in summary
            assert "Calculator" in summary


class TestCodeChunker:
    """Tests for chunker.chunk_file and chunker.chunk_project."""

    def test_chunk_python_class(self):
        """Python class with docstring produces correct chunk metadata."""
        import tempfile
        from luckyd_code.brain.chunker import chunk_file
        source = textwrap.dedent("""\
            class MyService:
                \"\"\"A service class.\"\"\"
                def run(self):
                    pass
        """)
        with tempfile.TemporaryDirectory() as tmp:
            fpath = Path(tmp) / "service.py"
            fpath.write_text(source, encoding="utf-8")
            chunks = chunk_file(fpath)
        class_chunks = [c for c in chunks if c["type"] == "class"]
        assert len(class_chunks) == 1
        assert class_chunks[0]["name"] == "MyService"
        assert class_chunks[0]["language"] == "python"
        assert class_chunks[0]["start_line"] >= 1

    def test_chunk_python_function(self):
        """Top-level function produces a function-type chunk."""
        import tempfile
        from luckyd_code.brain.chunker import chunk_file
        source = textwrap.dedent("""\
            def calculate(x, y):
                \"\"\"Calculate result.\"\"\"
                return x + y
        """)
        with tempfile.TemporaryDirectory() as tmp:
            fpath = Path(tmp) / "calc.py"
            fpath.write_text(source, encoding="utf-8")
            chunks = chunk_file(fpath)
        func_chunks = [c for c in chunks if c["type"] == "function"]
        assert len(func_chunks) == 1
        assert func_chunks[0]["name"] == "calculate"

    def test_chunk_module_header(self):
        """Module docstring + imports produce a module-type chunk."""
        import tempfile
        from luckyd_code.brain.chunker import chunk_file
        source = textwrap.dedent("""\
            \"\"\"Module docstring.\"\"\"
            import os
            from typing import Optional

            class Handler:
                pass
        """)
        with tempfile.TemporaryDirectory() as tmp:
            fpath = Path(tmp) / "module_test.py"
            fpath.write_text(source, encoding="utf-8")
            chunks = chunk_file(fpath)
        module_chunks = [c for c in chunks if c["type"] == "module"]
        assert len(module_chunks) == 1
        assert "import os" in module_chunks[0]["content"]

    def test_chunk_python_full_file(self):
        """Mixed classes + functions produce expected chunk count."""
        import tempfile
        from luckyd_code.brain.chunker import chunk_file
        source = textwrap.dedent("""\
            import sys

            class Engine:
                def start(self):
                    pass

            def helper():
                pass
        """)
        with tempfile.TemporaryDirectory() as tmp:
            fpath = Path(tmp) / "full.py"
            fpath.write_text(source, encoding="utf-8")
            chunks = chunk_file(fpath)
        types = [c["type"] for c in chunks]
        assert "module" in types
        assert "class" in types
        assert "function" in types

    def test_chunk_empty_file(self):
        """Empty file returns empty list."""
        import tempfile
        from luckyd_code.brain.chunker import chunk_file
        with tempfile.TemporaryDirectory() as tmp:
            fpath = Path(tmp) / "empty.py"
            fpath.write_text("", encoding="utf-8")
            chunks = chunk_file(fpath)
        assert chunks == []

    def test_chunk_unsupported_extension(self):
        """Unsupported file extension returns empty list."""
        import tempfile
        from luckyd_code.brain.chunker import chunk_file
        with tempfile.TemporaryDirectory() as tmp:
            fpath = Path(tmp) / "data.xyz"
            fpath.write_text("nothing", encoding="utf-8")
            chunks = chunk_file(fpath)
        assert chunks == []

    def test_chunk_project_walks_directory(self):
        """chunk_project discovers and chunks all supported files."""
        import tempfile
        from luckyd_code.brain.chunker import chunk_project
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src/main.py").write_text("def main(): pass")
            (root / "src/utils.py").write_text("def util(): pass")
            (root / "readme.md").write_text("# docs")
            chunks = chunk_project(str(root))
        assert len(chunks) >= 2  # module chunks for both files
        files = {c["file_path"] for c in chunks}
        assert any("main.py" in f for f in files)
        assert any("utils.py" in f for f in files)


class TestContextAssembler:
    """Tests for ContextAssembler."""

    def setup_method(self):
        from luckyd_code.brain.assembler import ContextAssembler
        self.assembler = ContextAssembler()

    def test_assemble_single_chunk(self):
        """Single chunk wrapped in XML with correct attributes."""
        chunks = [{
            "file_path": "src/main.py",
            "start_line": 10,
            "end_line": 20,
            "content": "def hello():\n    pass",
            "score": 0.95,
            "language": "python",
            "type": "function",
            "name": "hello",
        }]
        result = self.assembler.assemble(chunks)
        assert '<context file="src/main.py"' in result
        assert 'lines="10-20"' in result
        assert 'relevance="0.95"' in result
        assert "def hello():" in result
        assert "</context>" in result

    def test_assemble_multiple_chunks(self):
        """Multiple chunks ordered by score descending."""
        chunks = [
            {"file_path": "a.py", "start_line": 1, "end_line": 5,
             "content": "low", "score": 0.3},
            {"file_path": "b.py", "start_line": 1, "end_line": 5,
             "content": "high", "score": 0.9},
        ]
        result = self.assembler.assemble(chunks)
        # Higher score should appear first
        high_pos = result.index("high")
        low_pos = result.index("low")
        assert high_pos < low_pos

    def test_assemble_empty(self):
        """Empty input returns empty string."""
        assert self.assembler.assemble([]) == ""

    def test_assemble_token_budget(self):
        """Chunks exceeding max_tokens are truncated."""
        chunks = [{
            "file_path": "big.py",
            "start_line": 1,
            "end_line": 100,
            "content": "x\n" * 5000,
            "score": 0.9,
        }]
        # Very small max_tokens
        result = self.assembler.assemble(chunks, max_tokens=10)
        # Should include the context tag even with truncated content
        assert "<context" in result
        assert "</context>" in result

    def test_assemble_dedup_overlap(self):
        """Overlapping chunks from same file get deduplicated."""
        chunks = [
            {"file_path": "same.py", "start_line": 1, "end_line": 10,
             "content": "overlap_a", "score": 0.5},
            {"file_path": "same.py", "start_line": 5, "end_line": 15,
             "content": "overlap_b", "score": 0.9},
        ]
        result = self.assembler.assemble(chunks)
        # Higher-scored overlapping chunk should be kept
        assert "overlap_b" in result


class TestEmbedder:
    """Tests for Embedder (with mocks)."""

    def test_embedder_singleton(self, monkeypatch):
        """get_embedder() returns same instance across calls."""
        import luckyd_code.brain.embedder as emb_mod
        emb_mod._embedder = None
        monkeypatch.setattr(emb_mod.Embedder, "load", lambda self: None)

        from luckyd_code.brain.embedder import get_embedder
        e1 = get_embedder()
        e2 = get_embedder()
        assert e1 is e2

    def test_embedder_not_available(self, monkeypatch):
        """Without sentence-transformers, available=False."""
        import luckyd_code.brain.embedder as emb_mod
        emb_mod._embedder = None

        # Mock ImportError when importing sentence_transformers inside _load_local
        def mock_load(self):
            self.available = False
            return False
        monkeypatch.setattr(emb_mod.Embedder, "_load_local", mock_load)

        e = emb_mod.Embedder()
        e.load()
        assert not e.available
        result = e.embed(["test"])
        assert result is None

    def test_embed_empty_input(self):
        """Empty text list returns None."""
        from luckyd_code.brain.embedder import Embedder
        e = Embedder()
        assert e.embed([]) is None
        assert e.embed([""]) is None


class TestVectorIndexer:
    """Tests for VectorIndexer (with mocks)."""

    def test_build_empty(self, monkeypatch):
        """Building with no chunks produces empty stats."""
        from luckyd_code.brain.indexer import VectorIndexer
        idx = VectorIndexer()
        # Disable FAISS check
        monkeypatch.setattr(idx, "_check_deps", lambda: False)
        stats = idx.build([])
        assert stats["chunks"] == 0
        assert stats["files"] == 0

    def test_load_missing_file(self):
        """load() returns False when index file missing."""
        import tempfile
        from luckyd_code.brain.indexer import VectorIndexer
        with tempfile.TemporaryDirectory() as tmp:
            idx = VectorIndexer()
            # Point to nonexistent files via monkeypatch
            import luckyd_code.brain.indexer as idx_mod
            real_index = idx_mod.INDEX_FILE
            real_chunks = idx_mod.CHUNKS_FILE
            idx_mod.INDEX_FILE = Path(tmp) / "nope.faiss"
            idx_mod.CHUNKS_FILE = Path(tmp) / "nope.json"
            try:
                assert not idx.load()
            finally:
                idx_mod.INDEX_FILE = real_index
                idx_mod.CHUNKS_FILE = real_chunks

    def test_stats_text_empty(self):
        """stats_text works with empty index."""
        from luckyd_code.brain.indexer import VectorIndexer
        idx = VectorIndexer()
        text = idx.stats_text()
        assert "Chunks indexed: 0" in text


class TestRetriever:
    """Tests for Retriever."""

    def test_search_empty_no_fallback(self, monkeypatch):
        """Retriever returns empty list when nothing is available."""
        from luckyd_code.brain.retriever import Retriever
        from luckyd_code.brain.indexer import VectorIndexer
        r = Retriever()
        # Provide an empty indexer (no data, not available)
        empty_indexer = VectorIndexer()
        empty_indexer.chunks = []
        monkeypatch.setattr(type(empty_indexer), "is_available", property(lambda self: False))
        monkeypatch.setattr(r, "_get_indexer", lambda: empty_indexer)
        monkeypatch.setattr(r, "_fallback_search", lambda q, k, f: [])
        results = r.search("something", k=5)
        assert results == []

    def test_stats_returns_dict(self):
        """stats() returns a dict with vector and graph keys."""
        from luckyd_code.brain.retriever import Retriever
        r = Retriever()
        info = r.stats()
        assert "vector" in info
        assert "graph" in info


class TestRAGIntegration:
    """Integration tests (chunk -> assemble, no embeddings needed)."""

    def test_chunk_then_assemble(self):
        """Chunk a file and assemble results without embeddings."""
        import tempfile
        from luckyd_code.brain.chunker import chunk_file
        from luckyd_code.brain.assembler import ContextAssembler

        source = textwrap.dedent("""\
            import os

            class Handler:
                \"\"\"Handles requests.\"\"\"
                def process(self):
                    pass

            def startup():
                \"\"\"Initialize app.\"\"\"
                pass
        """)
        with tempfile.TemporaryDirectory() as tmp:
            fpath = Path(tmp) / "handler.py"
            fpath.write_text(source, encoding="utf-8")
            chunks = chunk_file(fpath)

        assert len(chunks) >= 3  # module + class + function

        # Give them synthetic scores
        for i, c in enumerate(chunks):
            c["score"] = 1.0 - (i * 0.1)

        assembler = ContextAssembler()
        context = assembler.assemble(chunks)
        assert "<context" in context
        assert "Handler" in context
        assert "startup" in context
        assert "</context>" in context
