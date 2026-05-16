"""Persistent Codebase Brain — knowledge graph and RAG system for code understanding."""
import os
from .graph import KnowledgeGraph
from .parser import parse_project
from .chunker import chunk_file, chunk_project
from .embedder import Embedder, get_embedder
from .indexer import VectorIndexer
from .retriever import Retriever
from .assembler import ContextAssembler

__all__ = [
    "KnowledgeGraph",
    "parse_project",
    "chunk_file",
    "chunk_project",
    "Embedder",
    "get_embedder",
    "VectorIndexer",
    "Retriever",
    "ContextAssembler",
    "rebuild_project",
    "find_dependents",
]

find_dependents = KnowledgeGraph.find_dependents


def rebuild_project(project_root: str | None = None) -> dict:
    """Rebuild both the vector index and the knowledge graph for a project.

    Args:
        project_root: Root directory to index. Defaults to current working directory.

    Returns:
        Dict with keys: chunks, files, node_count, files_parsed, languages
    """
    if project_root is None:
        project_root = os.getcwd()

    result = {"chunks": 0, "files": 0, "node_count": 0, "files_parsed": 0, "languages": {}}

    # Build vector index
    chunks = chunk_project(project_root)
    if chunks:
        indexer = VectorIndexer()
        stats = indexer.build(chunks)  # type: ignore[arg-type]
        # Track mtimes
        from .chunker import LANGUAGE_MAP
        from .constants import should_skip
        from pathlib import Path

        mtimes: dict = {}
        for dirpath, dirnames, filenames in os.walk(Path(project_root).resolve()):
            dirnames[:] = [d for d in dirnames if not should_skip(d)]
            for fname in filenames:
                suffix = Path(fname).suffix.lower()
                if suffix not in LANGUAGE_MAP:
                    continue
                fpath = Path(dirpath) / fname
                try:
                    st = fpath.stat()
                    mtimes[str(fpath)] = (st.st_mtime, st.st_size)
                except OSError:
                    continue
        indexer.file_mtimes = mtimes
        indexer.save()

        result["chunks"] = stats.get("chunks", 0)
        result["files"] = stats.get("files", 0)
        result["languages"] = stats.get("languages", {})

    # Build old graph (backward compatible)
    parsed, _ = parse_project(project_root)
    if parsed:
        brain = KnowledgeGraph()
        brain.build(project_root, parsed)
        brain.save()
        result["node_count"] = brain.stats.get("node_count", 0)
        result["files_parsed"] = brain.stats.get("files_parsed", 0)

    return result
