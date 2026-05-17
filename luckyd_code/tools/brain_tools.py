"""Brain tools — query the codebase knowledge graph and RAG index."""

from ..brain import KnowledgeGraph, Retriever, ContextAssembler
from .registry import Tool


# Global instances that persist across tool calls
_graph: KnowledgeGraph | None = None
_retriever: Retriever | None = None
_assembler: ContextAssembler | None = None


def _get_graph() -> KnowledgeGraph:  # pragma: no cover
    """Get the shared graph instance, loading from disk if needed."""
    global _graph
    if _graph is None:
        _graph = KnowledgeGraph()
        _graph.load()
    return _graph


def _get_retriever() -> Retriever:  # pragma: no cover
    """Get the shared retriever instance."""
    global _retriever
    if _retriever is None:
        _retriever = Retriever()
    return _retriever


def _get_assembler() -> ContextAssembler:  # pragma: no cover
    """Get the shared context assembler instance."""
    global _assembler
    if _assembler is None:
        _assembler = ContextAssembler()
    return _assembler


class BrainSearchTool(Tool):
    name = "BrainSearch"
    description = "Search the codebase for functions, classes, and code patterns using semantic understanding. Use this INSTEAD of Grep when you need to find code by concept or behavior (e.g., 'authentication flow', 'database retry logic') rather than exact name matches."
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search term — natural language description of what you're looking for (e.g., 'user authentication', 'database connection', 'error handling')",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum results to return (default 10)",
                "default": 10,
            },
            "file_filter": {
                "type": "string",
                "description": "Optional file path filter (e.g., 'auth.py', 'src/api/')",
            },
        },
        "required": ["query"],
    }
    permission_risk = "safe"

    def run(self, query: str, max_results: int = 10, file_filter: str = "") -> str:
        retriever = _get_retriever()

        results = retriever.search(
            query,
            k=max_results,
            file_filter=file_filter or None,
        )
        if not results:
            # Check if old graph has anything
            graph = _get_graph()
            if not graph.nodes:
                return "Codebase index is empty. Run `/brain rebuild` first to index your codebase."
            return f"No results found for '{query}'."

        lines = [f"Brain search results for '{query}':", ""]
        for r in results:
            file_path = r.get("file_path", "?")
            start = r.get("start_line", 0)
            end = r.get("end_line", 0)
            score = r.get("score", 0)
            name = r.get("name", "")
            chunk_type = r.get("type", "?")
            lang = r.get("language", "")

            loc = f"{file_path}:{start}-{end}" if start else file_path
            label = f"[{chunk_type}] {name} ({lang})" if name else f"[{chunk_type}] ({lang})"
            lines.append(f"  {label} — {loc}  (score: {score:.2f})")

        return "\n".join(lines)


class BrainStatusTool(Tool):
    name = "BrainStatus"
    description = "Show the current state of the codebase index — vector index stats, knowledge graph stats, languages found, and last indexed time."
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }
    permission_risk = "safe"

    def run(self) -> str:
        retriever = _get_retriever()
        info = retriever.stats()

        lines = ["=== Vector Index ==="]
        vec = info.get("vector", {})
        if vec.get("available"):
            lines.append(f"  Chunks: {vec.get('chunks', 0)}")
            lines.append(f"  Files: {vec.get('files', 0)}")
            languages = vec.get("languages", {})
            if languages:
                lang_str = ", ".join(f"{k}={v}" for k, v in sorted(languages.items()))
                lines.append(f"  Languages: {lang_str}")
            last = vec.get("last_indexed", 0)
            if last:
                import time
                last_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last))
                lines.append(f"  Last indexed: {last_str}")
            stale = info.get("stale_files", 0)
            if stale:
                lines.append(f"  [yellow]Stale files: {stale} (run /brain rebuild)[/yellow]")
        else:
            lines.append("  Not available (install faiss-cpu + sentence-transformers for vector search)")

        lines.append("\n=== Knowledge Graph (Fallback) ===")
        graph_data = info.get("graph", {})
        if graph_data.get("nodes"):
            lines.append(f"  Symbols: {graph_data.get('nodes', 0)}")
            lines.append(f"  Relations: {graph_data.get('edges', 0)}")
            lines.append(f"  Files: {graph_data.get('files_parsed', 0)}")
        else:
            lines.append("  Empty")

        return "\n".join(lines)
