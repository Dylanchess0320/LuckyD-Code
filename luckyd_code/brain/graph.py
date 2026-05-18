"""Knowledge graph — stores and queries codebase structure across sessions."""

import json
import time
from pathlib import Path
from typing import Any

from ..log import get_logger
from .constants import BRAIN_DIR


GRAPH_FILE = BRAIN_DIR / "graph.json"

Node = dict[str, Any]
Edge = dict[str, str]


class KnowledgeGraph:
    """Persistent knowledge graph of codebase structure.

    Nodes: modules, classes, functions
    Edges: imports, contains, calls, inherits
    """

    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        self.edges: list[Edge] = []
        self.stats: dict[str, Any] = {
            "node_count": 0,
            "edge_count": 0,
            "last_built": 0,
            "files_parsed": 0,
            "errors": 0,
        }
        self._seed_builtins()

    def _seed_builtins(self) -> None:
        """Pre-populate the graph with common Python built-in symbols.

        These entries are always present so that first-run searches
        (before any project has been indexed) return useful results
        rather than an empty list.
        """
        _BUILTINS: list[tuple[str, str, str]] = [
            # (name, type, doc)
            ("len",        "function", "Return the number of items in a container."),
            ("print",      "function", "Print objects to the text stream file."),
            ("range",      "class",    "Return an object that produces a sequence of integers."),
            ("list",       "class",    "Built-in mutable sequence type."),
            ("dict",       "class",    "Built-in mapping type."),
            ("str",        "class",    "Built-in immutable string type."),
            ("int",        "class",    "Built-in integer type."),
            ("float",      "class",    "Built-in floating-point number type."),
            ("bool",       "class",    "Built-in boolean type (subclass of int)."),
            ("type",       "class",    "Return the type of an object, or create a new type."),
            ("isinstance", "function", "Return True if object is an instance of classinfo."),
            ("hasattr",    "function", "Return whether the object has a named attribute."),
            ("getattr",    "function", "Get a named attribute from an object."),
            ("setattr",    "function", "Set a named attribute on an object."),
            ("enumerate",  "function", "Return an enumerate object over an iterable."),
            ("zip",        "function", "Iterate over several iterables in parallel."),
            ("map",        "function", "Return an iterator that applies function to every item."),
            ("filter",     "function", "Construct an iterator from elements that are truthy."),
            ("sorted",     "function", "Return a new sorted list from an iterable."),
            ("open",       "function", "Open file and return a stream."),
        ]
        for name, sym_type, doc in _BUILTINS:
            nid = f"builtin:{name}"
            self.nodes[nid] = {
                "type": sym_type,
                "name": name,
                "file": "<builtins>",
                "line": 0,
                "doc": doc,
                "builtin": True,
            }

    def build(self, project_root: str, parsed_files: list[dict[str, Any]]) -> None:
        self.nodes = {}
        self.edges = []
        self.stats["last_built"] = time.time()
        self.stats["files_parsed"] = len(parsed_files)
        self.stats["errors"] = 0
        self._seed_builtins()
        _builtin_count = len(self.nodes)

        for pf in parsed_files:
            if pf["errors"]:
                self.stats["errors"] += len(pf["errors"])
                continue

            rel_path = pf["module"]
            module_id = f"module:{rel_path}"

            self.nodes[module_id] = {
                "type": "module",
                "name": Path(rel_path).name,
                "file": rel_path,
                "line": 1,
                "doc": "",
                "size": pf["size"],
            }

            for imp in pf["imports"]:
                import_id = f"import:{imp['module']}:{imp['name']}"
                if import_id not in self.nodes:
                    self.nodes[import_id] = {
                        "type": "import",
                        "name": imp["name"],
                        "module": imp["module"],
                        "alias": imp.get("alias"),
                        "file": rel_path,
                        "line": 0,
                        "doc": "",
                    }
                self.edges.append({"from": module_id, "to": import_id, "type": "imports"})

            for cls in pf["classes"]:
                cls_id = f"class:{rel_path}:{cls['name']}"
                self.nodes[cls_id] = {
                    "type": "class",
                    "name": cls["name"],
                    "file": rel_path,
                    "line": cls["line"],
                    "end_line": cls["end_line"],
                    "bases": cls["base_names"],
                    "decorators": cls["decorators"],
                    "doc": cls["docstring"][:200],
                }
                self.edges.append({"from": module_id, "to": cls_id, "type": "contains"})

                for base in cls["base_names"]:
                    if base and base != "object":
                        self.edges.append({
                            "from": cls_id, "to": f"class:??:{base}", "type": "inherits"
                        })

                for method in cls["methods"]:
                    method_id = f"method:{rel_path}:{cls['name']}.{method['name']}"
                    self.nodes[method_id] = {
                        "type": "method",
                        "name": method["name"],
                        "class": cls["name"],
                        "file": rel_path,
                        "line": method["line"],
                        "end_line": method["end_line"],
                        "decorators": method["decorators"],
                        "doc": method["docstring"][:200],
                    }
                    self.edges.append({"from": cls_id, "to": method_id, "type": "contains"})
                    for call in method["calls"]:
                        self.edges.append({"from": method_id, "to": f"func:??:{call}", "type": "calls"})

            for func in pf["functions"]:
                func_id = f"func:{rel_path}:{func['name']}"
                self.nodes[func_id] = {
                    "type": "function",
                    "name": func["name"],
                    "file": rel_path,
                    "line": func["line"],
                    "end_line": func["end_line"],
                    "decorators": func["decorators"],
                    "doc": func["docstring"][:200],
                }
                self.edges.append({"from": module_id, "to": func_id, "type": "contains"})
                for call in func["calls"]:
                    self.edges.append({"from": func_id, "to": f"func:??:{call}", "type": "calls"})

        self.stats["node_count"] = len(self.nodes) - _builtin_count
        self.stats["edge_count"] = len(self.edges)

    # --- Persistence ---

    def save(self) -> None:
        BRAIN_DIR.mkdir(parents=True, exist_ok=True)
        data = {"nodes": self.nodes, "edges": self.edges, "stats": self.stats}
        GRAPH_FILE.write_text(json.dumps(data), encoding="utf-8")

    def load(self) -> bool:
        if GRAPH_FILE.exists():
            try:
                data: Any = json.loads(GRAPH_FILE.read_text(encoding="utf-8"))
                self.nodes = data.get("nodes", {})
                self.edges = data.get("edges", {}) if isinstance(data.get("edges"), dict) else data.get("edges", [])
                self.stats = data.get("stats", {})
                # Ensure built-ins are always present even in old saved graphs
                self._seed_builtins()
                return True
            except (json.JSONDecodeError, OSError):
                get_logger().warning("Could not load knowledge graph from %s", GRAPH_FILE, exc_info=True)
        return False

    def search(self, query: str, max_results: int = 15) -> list[Node]:
        q = query.lower()
        scored: list[tuple[int, str, Node]] = []

        for nid, node in self.nodes.items():
            score = 0
            if q in node.get("name", "").lower():
                score += 10
            if q in node.get("file", "").lower():
                score += 5
            if q in node.get("doc", "").lower():
                score += 3
            if q in node.get("module", "").lower():
                score += 2
            if q in node.get("class", "").lower():
                score += 2
            if score > 0:
                scored.append((score, nid, node))

        scored.sort(key=lambda x: -x[0])
        seen: set[str] = set()
        top: list[Node] = []
        for _score, nid, node in scored[:max_results]:
            if nid not in seen:
                top.append(node)
                seen.add(nid)
        return top

    def get_related(self, node_id: str, max_depth: int = 1) -> list[Node]:
        related: set[str] = set()
        current = {node_id}

        for _ in range(max_depth):
            next_set: set[str] = set()
            for edge in self.edges:
                if isinstance(edge, dict):
                    if edge["from"] in current:
                        next_set.add(edge["to"])
                    if edge["to"] in current:
                        next_set.add(edge["from"])
            current = next_set
            related.update(current)

        return [
            self.nodes.get(nid, {"name": nid, "type": "unknown", "file": ""})
            for nid in related if nid != node_id
        ]

    def get_by_file(self, filepath: str) -> list[Node]:
        return [
            node for node in self.nodes.values()
            if node.get("file", "").endswith(filepath)
        ]

    def get_by_type(self, node_type: str) -> list[Node]:
        return [
            node for node in self.nodes.values()
            if node.get("type") == node_type and not node.get("builtin")
        ]

    def find_dependents(self, symbol_name: str, max_results: int = 15) -> list[dict[str, Any]]:
        """Find all nodes that depend on a symbol by traversing incoming edges."""
        matches = self.search(symbol_name, max_results=5)
        if not matches:
            return []

        # Build a lookup of known node IDs so we can match even with incomplete IDs
        node_ids = set(self.nodes.keys())
        dependents: list[dict[str, Any]] = []
        seen: set[str] = set()

        for match in matches:
            # Generate the most likely node ID for this match
            candidate_ids = [
                f"{match['type']}:{match.get('file', '')}:{match['name']}",
                f"func:??:{match['name']}",
                f"method:??:{match['name']}",
                f"class:??:{match['name']}",
            ]
            matched_id = None
            for cid in candidate_ids:
                if cid in node_ids:
                    matched_id = cid
                    break

            if not matched_id:
                continue

            for edge in self.edges:
                if isinstance(edge, dict) and edge.get("to") == matched_id:
                    src = self.nodes.get(edge["from"])
                    if src and edge["from"] not in seen:
                        seen.add(edge["from"])
                        dependents.append({
                            "name": f"{src.get('type', '?')}:{src.get('name', '?')}",
                            "file": src.get("file", ""),
                            "relation": edge.get("type", ""),
                            "line": src.get("line", 0),
                        })

        dependents.sort(key=lambda x: (x["file"], x["line"]))
        return dependents[:max_results]

    def summarize(self, max_modules: int = 20) -> str:
        lines = ["<knowledge-graph>"]
        lines.append(f"Graph: {self.stats.get('node_count', 0)} symbols, "
                     f"{self.stats.get('edge_count', 0)} relationships, "
                     f"{self.stats.get('files_parsed', 0)} files")

        by_file: dict[str, list[Node]] = {}
        for node in self.nodes.values():
            f = node.get("file", "")
            if f:
                by_file.setdefault(f, []).append(node)

        count = 0
        for filepath, nodes in sorted(by_file.items()):
            if count >= max_modules:
                break
            count += 1
            classes = [n for n in nodes if n["type"] == "class"]
            functions = [n for n in nodes if n["type"] == "function"]

            short_path = Path(filepath).name
            parts = [short_path]
            if classes:
                parts.append(f"classes={{{','.join(c['name'] for c in classes)}}}")
            if functions:
                parts.append(f"functions={{{','.join(f['name'] for f in functions)}}}")
            lines.append(f"  {' | '.join(parts)}")

        lines.append("</knowledge-graph>")
        return "\n".join(lines)

    def stats_text(self) -> str:
        by_type: dict[str, int] = {}
        for node in self.nodes.values():
            t = node.get("type", "unknown")
            by_type[t] = by_type.get(t, 0) + 1

        by_file: dict[str, int] = {}
        for node in self.nodes.values():
            f = node.get("file", "")
            if f:
                by_file[f] = by_file.get(f, 0) + 1

        lines = [
            f"Nodes: {self.stats.get('node_count', 0)}",
            f"Edges: {self.stats.get('edge_count', 0)}",
            f"Files parsed: {self.stats.get('files_parsed', 0)}",
            f"Parse errors: {self.stats.get('errors', 0)}",
        ]
        if by_type:
            lines.append("\nBy type:")
            for t, c in sorted(by_type.items(), key=lambda x: -x[1]):
                lines.append(f"  {t}: {c}")
        if by_file:
            lines.append("\nBy file:")
            for f, c in sorted(by_file.items(), key=lambda x: -x[1])[:20]:
                lines.append(f"  {f}: {c} symbols")
        if self.stats.get("last_built"):
            last = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.stats["last_built"]))
            lines.append(f"\nLast built: {last}")

        return "\n".join(lines)
