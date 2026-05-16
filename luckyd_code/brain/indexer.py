"""Vector indexer — builds and queries FAISS vector index for code chunks."""

import json
import os
import time
from pathlib import Path
from typing import Any

from ..log import get_logger
from .constants import BRAIN_DIR, LANGUAGE_MAP, SKIP_DIRS

INDEX_FILE = BRAIN_DIR / "index.faiss"
CHUNKS_FILE = BRAIN_DIR / "chunks.json"
MTIMES_FILE = BRAIN_DIR / "mtimes.json"
STATS_FILE = BRAIN_DIR / "stats.json"

CHUNK_SIZE = 384  # all-MiniLM-L6-v2 dimension


class VectorIndexer:
    """Manages the FAISS vector index with mtime tracking."""

    def __init__(self):
        self.index: Any = None  # FAISS index object
        self.chunks: list[dict[str, Any]] = []
        self.file_mtimes: dict[str, tuple[float, int]] = {}
        self.stats: dict[str, Any] = {
            "chunks": 0,
            "files": 0,
            "languages": {},
            "last_indexed": 0,
            "dimension": 0,
            "index_size_bytes": 0,
        }
        self._faiss_available = False

    def _check_deps(self) -> bool:  # pragma: no cover
        """Check if FAISS and numpy are available."""
        if not self._faiss_available:
            try:
                import faiss
                import numpy as np

                self._faiss = faiss
                self._np = np
                self._faiss_available = True
                return True
            except ImportError:
                get_logger().info(
                    "faiss-cpu not available. Vector search disabled. "
                    "Install with: pip install faiss-cpu"
                )
                return False
        return True

    def build(self, chunks: list[dict[str, Any]]) -> dict[str, Any]:  # pragma: no cover
        """Build the FAISS index from chunks.

        Args:
            chunks: List of chunk dicts from chunker.

        Returns:
            Stats dict.
        """
        from .embedder import get_embedder

        if not self._check_deps():
            self.stats["chunks"] = len(chunks)
            self.stats["files"] = len(set(c["file_path"] for c in chunks))
            self.stats["last_indexed"] = time.time()
            return self.stats

        embedder = get_embedder()
        if not embedder.available:
            self.stats["chunks"] = len(chunks)
            self.stats["files"] = len(set(c["file_path"] for c in chunks))
            self.stats["last_indexed"] = time.time()
            return self.stats

        if not chunks:
            self.chunks = []
            self.index = None
            self.stats["chunks"] = 0
            self.stats["files"] = 0
            self.stats["languages"] = {}
            self.stats["last_indexed"] = time.time()
            return self.stats

        # Track languages
        languages: dict[str, int] = {}
        for c in chunks:
            lang = c.get("language", "unknown")
            languages[lang] = languages.get(lang, 0) + 1

        # Sort chunks by file_path then start_line for stable ordering
        chunks.sort(key=lambda c: (c["file_path"], c.get("start_line", 0)))
        self.chunks = chunks

        # Embed all chunk contents
        texts = [c.get("content", "") for c in chunks]
        embeddings = embedder.embed(texts)

        if embeddings is None:
            self.stats["chunks"] = len(chunks)
            self.stats["files"] = len(set(c["file_path"] for c in chunks))
            self.stats["last_indexed"] = time.time()
            return self.stats

        # Build FAISS index
        dim = len(embeddings[0])
        idx = self._faiss.IndexFlatIP(dim)  # Inner product = cosine sim for normalized vectors
        vectors = self._np.array(embeddings, dtype=self._np.float32)

        # Normalize vectors for cosine similarity
        self._faiss.normalize_L2(vectors)
        idx.add(vectors)

        self.index = idx
        self.stats = {
            "chunks": len(chunks),
            "files": len(set(c["file_path"] for c in chunks)),
            "languages": languages,
            "last_indexed": time.time(),
            "dimension": dim,
            "index_size_bytes": 0,
        }

        return self.stats

    def search(  # pragma: no cover
        self, query: str, k: int = 10
    ) -> list[dict[str, Any]]:
        """Search the index by embedding the query.

        Args:
            query: Natural language search query.
            k: Number of results to return.

        Returns:
            List of chunk dicts with a 'score' key added.
        """
        from .embedder import get_embedder

        if not self._check_deps() or self.index is None or self.index.ntotal == 0:
            return []

        embedder = get_embedder()
        if not embedder.available:
            return []

        query_vec = embedder.embed_query(query)
        if query_vec is None:
            return []

        # Normalize query vector
        q = self._np.array([query_vec], dtype=self._np.float32)
        self._faiss.normalize_L2(q)

        k_actual = min(k, self.index.ntotal)
        if k_actual == 0:
            return []

        scores, indices = self.index.search(q, k_actual)

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(self.chunks):
                continue
            chunk = dict(self.chunks[idx])
            chunk["score"] = float(score)
            results.append(chunk)

        return results

    def save(self) -> bool:
        """Save the index, chunks, and mtimes to disk."""
        BRAIN_DIR.mkdir(parents=True, exist_ok=True)

        try:
            # Save FAISS index
            if self._faiss_available and self.index is not None:
                self._faiss.write_index(self.index, str(INDEX_FILE))
                self.stats["index_size_bytes"] = INDEX_FILE.stat().st_size

            # Save chunks with content
            CHUNKS_FILE.write_text(
                json.dumps(self.chunks, indent=2), encoding="utf-8"
            )

            # Save mtimes
            MTIMES_FILE.write_text(
                json.dumps(self.file_mtimes), encoding="utf-8"
            )

            # Save stats
            STATS_FILE.write_text(
                json.dumps(self.stats), encoding="utf-8"
            )

            return True
        except Exception as exc:
            get_logger().warning("Failed to save vector index: %s", exc)
            return False

    def load(self) -> bool:  # pragma: no cover
        """Load the index and metadata from disk.

        Returns:
            True if index was loaded successfully.
        """
        if not INDEX_FILE.exists() or not CHUNKS_FILE.exists():
            return False

        try:
            self._check_deps()

            # Load chunks
            self.chunks = json.loads(CHUNKS_FILE.read_text(encoding="utf-8"))
            if not self.chunks:
                return False

            # Load FAISS index
            if self._faiss_available and INDEX_FILE.exists():
                self.index = self._faiss.read_index(str(INDEX_FILE))

            # Load mtimes
            if MTIMES_FILE.exists():
                self.file_mtimes = json.loads(MTIMES_FILE.read_text(encoding="utf-8")) or {}

            # Load stats
            if STATS_FILE.exists():
                self.stats = json.loads(STATS_FILE.read_text(encoding="utf-8")) or {}

            return True

        except Exception as exc:
            get_logger().warning("Failed to load vector index: %s", exc)
            return False

    def stats_text(self) -> str:
        """Return human-readable statistics."""
        lines = [
            f"Chunks indexed: {self.stats.get('chunks', 0)}",
            f"Files: {self.stats.get('files', 0)}",
        ]

        languages = self.stats.get("languages", {})
        if languages:
            lines.append(f"Languages: {', '.join(f'{k}={v}' for k, v in sorted(languages.items()))}")

        dim = self.stats.get("dimension", 0)
        if dim:
            lines.append(f"Vector dimension: {dim}")

        size = self.stats.get("index_size_bytes", 0)
        if size:
            if size < 1024:
                size_str = f"{size} B"
            elif size < 1024 * 1024:
                size_str = f"{size / 1024:.1f} KB"
            else:
                size_str = f"{size / 1024 / 1024:.1f} MB"
            lines.append(f"Index size: {size_str}")

        last = self.stats.get("last_indexed", 0)
        if last:
            last_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last))
            lines.append(f"Last indexed: {last_str}")

        if not self._faiss_available:
            lines.append("FAISS not available (install faiss-cpu for vector search)")

        return "\n".join(lines)

    def get_changed_files(self, project_root: str) -> list[str]:
        """Check which files have changed since last index.

        Args:
            project_root: Root directory to scan.

        Returns:
            List of file paths that have changed or are new.
        """
        changed: list[str] = []
        root = Path(project_root).resolve()

        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]

            for fname in filenames:
                suffix = Path(fname).suffix.lower()
                if suffix not in LANGUAGE_MAP:
                    continue

                fpath = Path(dirpath) / fname
                try:
                    st = fpath.stat()
                    mtime = st.st_mtime
                    size = st.st_size
                except OSError:
                    continue

                fpath_str = str(fpath)
                if fpath_str in self.file_mtimes:
                    old_mtime, old_size = self.file_mtimes[fpath_str]
                    if old_mtime == mtime and old_size == size:
                        continue

                changed.append(fpath_str)

        return changed

    @property
    def is_available(self) -> bool:
        """Whether the index is loaded and ready."""
        return self._faiss_available and self.index is not None and self.index.ntotal > 0
