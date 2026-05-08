"""Retriever — semantic search over code chunks with fallback to substring search."""

import os
from typing import Any, Optional

from ..log import get_logger

_RRF_K = 60  # standard RRF constant — higher = smoother rank blending


class Retriever:
    """Searches indexed code chunks semantically, with fallback to substring search.

    Search strategy (in order of quality):
      1. RRF merge of vector + BM25 when both are available (best quality)
      2. Vector-only when BM25 unavailable
      3. BM25-only when vector unavailable
      4. Graph keyword fallback with token-overlap scoring
    """

    def __init__(self):
        self._indexer = None
        self._graph = None
        self._bm25 = None
        self._bm25_tokenized = None
        self._bm25_chunk_count = 0

    def _get_indexer(self):
        if self._indexer is None:
            from .indexer import VectorIndexer

            idx = VectorIndexer()
            idx.load()
            self._indexer = idx
        return self._indexer

    def _get_graph(self):
        if self._graph is None:
            from .graph import KnowledgeGraph

            g = KnowledgeGraph()
            g.load()
            self._graph = g
        return self._graph

    def search(
        self,
        query: str,
        k: int = 10,
        file_filter: Optional[str] = None,
        min_score: float = 0.0,
    ) -> list[dict[str, Any]]:
        indexer = self._get_indexer()
        vec_results: list[dict[str, Any]] = []
        bm25_results: list[dict[str, Any]] = []

        if indexer.is_available:
            vec_results = indexer.search(query, k=k)
            if file_filter:
                vec_results = [
                    r for r in vec_results
                    if file_filter in r.get("file_path", "")
                ]

        bm25_results = self._bm25_search(query, k, file_filter)

        # Best path: RRF merge when both sources have results
        if vec_results and bm25_results:
            merged = self._rrf_merge(vec_results, bm25_results, k=k)
            if min_score > 0:
                merged = [r for r in merged if r.get("score", 0) >= min_score]
            if merged:
                return merged

        # Single-source fallback
        for results in (vec_results, bm25_results):
            if results:
                if min_score > 0:
                    results = [r for r in results if r.get("score", 0) >= min_score]
                if results:
                    return results

        return self._fallback_search(query, k, file_filter)

    def _rrf_merge(
        self,
        vec_results: list[dict[str, Any]],
        bm25_results: list[dict[str, Any]],
        k: int = 10,
    ) -> list[dict[str, Any]]:
        """Reciprocal Rank Fusion — combines two ranked lists without score normalisation.

        Each chunk gets score = sum(1 / (_RRF_K + rank)) across lists it appears in.
        Chunks that rank highly in BOTH lists bubble to the top.
        """
        rrf_scores: dict[str, float] = {}
        chunk_by_id: dict[str, dict[str, Any]] = {}

        for rank, chunk in enumerate(vec_results):
            cid = chunk.get("chunk_id", chunk.get("file_path", str(rank)))
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + 1.0 / (_RRF_K + rank + 1)
            chunk_by_id[cid] = chunk

        for rank, chunk in enumerate(bm25_results):
            cid = chunk.get("chunk_id", chunk.get("file_path", str(rank)))
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + 1.0 / (_RRF_K + rank + 1)
            chunk_by_id.setdefault(cid, chunk)

        sorted_ids = sorted(rrf_scores, key=lambda c: -rrf_scores[c])
        results = []
        for cid in sorted_ids[:k]:
            chunk = dict(chunk_by_id[cid])
            chunk["score"] = round(rrf_scores[cid], 6)
            results.append(chunk)
        return results

    def _bm25_search(
        self,
        query: str,
        k: int,
        file_filter: Optional[str],
    ) -> list[dict[str, Any]]:
        try:
            import rank_bm25
        except ImportError:
            return []

        indexer = self._get_indexer()
        if not indexer.chunks:
            return []

        try:
            if self._bm25 is None or len(indexer.chunks) != self._bm25_chunk_count:
                self._bm25_tokenized = [
                    c.get("content", "").lower().split()
                    for c in indexer.chunks
                ]
                self._bm25 = rank_bm25.BM25Okapi(self._bm25_tokenized)
                self._bm25_chunk_count = len(indexer.chunks)

            tokenized_query = query.lower().split()
            bm25_scores = self._bm25.get_scores(tokenized_query)

            scored: list[tuple[int, float]] = []
            for i, (chunk, bm25_score) in enumerate(zip(indexer.chunks, bm25_scores)):
                combined = float(bm25_score)
                if combined > 0:
                    scored.append((i, combined))

            scored.sort(key=lambda x: -x[1])

            results = []
            for i, score in scored[:k]:
                chunk = dict(indexer.chunks[i])
                chunk["score"] = score
                if file_filter and file_filter not in chunk.get("file_path", ""):
                    continue
                results.append(chunk)

            return results
        except Exception as exc:
            get_logger().warning("BM25 search failed: %s", exc)
            return []

    def _fallback_search(
        self,
        query: str,
        k: int,
        file_filter: Optional[str],
    ) -> list[dict[str, Any]]:
        graph = self._get_graph()
        if not graph.nodes:
            return []

        nodes = graph.search(query, max_results=k)
        query_lower = query.lower()
        query_tokens = set(query_lower.split())
        results = []
        for node in nodes:
            if file_filter and file_filter not in node.get("file", ""):
                continue
            name = node.get("name", "").lower()
            # Score by name overlap: exact > partial token > type-only
            if name == query_lower:
                score = 1.0
            elif any(t in name or name in t for t in query_tokens if len(t) > 2):
                score = 0.7
            elif any(t in (node.get("type", "") or "").lower() for t in query_tokens):
                score = 0.4
            else:
                score = 0.2
            results.append({
                "file_path": node.get("file", ""),
                "chunk_id": f"{node.get('type', 'node')}:{node.get('name', '')}",
                "start_line": node.get("line", 0),
                "end_line": node.get("end_line", 0),
                "type": node.get("type", "symbol"),
                "name": node.get("name", ""),
                "language": "python",
                "content": f"{node.get('type', 'symbol')} {node.get('name', '')}",
                "score": score,
            })

        results.sort(key=lambda r: -r["score"])
        return results

    def stats(self) -> dict[str, Any]:
        indexer = self._get_indexer()
        graph = self._get_graph()

        info: dict[str, Any] = {
            "vector": {
                "available": indexer.is_available,
                "chunks": indexer.stats.get("chunks", 0),
                "files": indexer.stats.get("files", 0),
                "languages": indexer.stats.get("languages", {}),
                "last_indexed": indexer.stats.get("last_indexed", 0),
            },
            "graph": {
                "nodes": graph.stats.get("node_count", 0),
                "edges": graph.stats.get("edge_count", 0),
                "files_parsed": graph.stats.get("files_parsed", 0),
            },
        }

        if indexer.stats.get("last_indexed"):
            try:
                changed = len(indexer.get_changed_files(os.getcwd()))
                if changed:
                    info["stale_files"] = changed
            except Exception:
                get_logger().warning("Failed to check for changed files", exc_info=True)

        return info
