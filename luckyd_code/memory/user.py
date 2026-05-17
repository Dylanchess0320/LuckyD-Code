"""User-level persistent memory — survives across projects and sessions.

Stores amnesia-proof memories in a user-scoped directory under
~/.luckyd_code/users/<user_hash>/ so the assistant can remember
preferences, facts about the user, and past interactions regardless
of which project/repo the user is currently in.

Search: semantic (sentence-transformers) with keyword fallback.
Decay: low-importance memories are archived after 30 days of inactivity.
"""

from __future__ import annotations

import hashlib
import re
import threading
import time
from pathlib import Path
from typing import Any

from .._data_dir import data_path

# ── user identity ────────────────────────────────────────────────────────────

def _user_hash() -> str:
    """Derive a stable hash for the current user.

    Uses a combination of home directory path and hostname, so the
    identity survives across projects but is unique per machine + user.
    """
    seed = ""
    try:
        seed += str(Path.home())
    except Exception:
        pass
    try:
        import socket
        seed += socket.gethostname()
    except Exception:
        pass
    if not seed:
        seed = "unknown_user"
    return hashlib.sha256(seed.encode()).hexdigest()[:16]


_USER_DIR = data_path("users", _user_hash())


def _get_user_mem_dir() -> Path:
    """Return (and create) the user-level memory directory."""
    d = _USER_DIR / "memories"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── embedding singleton ──────────────────────────────────────────────────────

_ST_MODEL = None
_ST_MODEL_LOCK = threading.Lock()


def _get_st_model():  # pragma: no cover
    """Return cached SentenceTransformer, loading it on first call."""
    global _ST_MODEL
    if _ST_MODEL is None:
        with _ST_MODEL_LOCK:
            if _ST_MODEL is None:
                from sentence_transformers import SentenceTransformer
                _ST_MODEL = SentenceTransformer("all-MiniLM-L6-v2")
    return _ST_MODEL


# ── UserMemory ──────────────────────────────────────────────────────────────────────────────

class UserMemory:
    """User-level persistent memory across all projects.

    Each memory is a markdown file with frontmatter-like metadata
    (importance, timestamps, access count).
    """

    MAX_SNIPPET = 500
    DECAY_DAYS = 30         # archive if untouched for this long
    ARCHIVE_THRESHOLD = 3   # only archive if importance <= this

    def __init__(self) -> None:
        self._mem_dir = _get_user_mem_dir()

    # ── CRUD ─────────────────────────────────────────────────────────────────

    def save(self, name: str, content: str, importance: int = 5) -> str:
        """Save a user-scoped memory.

        Args:
            name:       Short label (used as filename).
            content:    Full content — markdown, plain text, anything.
            importance: 1-10, where 10 is "never forget". Default 5.

        Returns the file path.
        """
        safe_name = _sanitize(name)
        filepath = self._mem_dir / f"{safe_name}.md"

        # Read existing metadata if updating
        existing_meta = self._read_meta(filepath)

        now = time.time()
        access_count = existing_meta.get("access_count", 0)

        meta = (
            f"<!-- importance:{importance} saved:{now:.0f} "
            f"accessed:{now:.0f} count:{access_count} -->\n"
        )
        filepath.write_text(meta + content, encoding="utf-8")
        return str(filepath)

    def load(self, name: str) -> str | None:
        """Load a user memory by name, updating last_accessed."""
        safe_name = _sanitize(name)
        filepath = self._mem_dir / f"{safe_name}.md"
        if not filepath.exists():
            return None

        raw = filepath.read_text(encoding="utf-8")
        content = self._strip_meta(raw)

        # Bump access count and timestamp
        meta = self._read_meta(filepath)
        self.save(name, content, meta.get("importance", 5))
        return content

    def delete(self, name: str) -> bool:
        """Delete a user memory. Returns True if it existed."""
        safe_name = _sanitize(name)
        filepath = self._mem_dir / f"{safe_name}.md"
        if filepath.exists():
            filepath.unlink()
            return True
        return False

    def list_all(self) -> list[dict[str, Any]]:
        """List all user memories with metadata."""
        results: list[dict[str, Any]] = []
        for f in sorted(self._mem_dir.glob("*.md")):
            meta = self._read_meta(f)
            results.append({
                "name": f.stem,
                "path": str(f),
                "importance": meta.get("importance", 5),
                "saved": meta.get("saved", 0),
                "accessed": meta.get("accessed", 0),
                "access_count": meta.get("access_count", 0),
            })
        return results

    # ── search ───────────────────────────────────────────────────────────────

    def search(self, query: str, k: int = 5) -> list[dict[str, Any]]:
        """Search user memories by relevance.

        Uses semantic search when sentence-transformers is available;
        falls back to keyword frequency.
        """
        try:
            return self._semantic_search(query, k)
        except Exception:
            return self._keyword_search(query, k)

    def get_relevant(self, context: str, k: int = 3) -> str:
        """Get formatted relevant memories for context injection.

        Returns empty string if nothing matches.
        """
        results = self.search(context, k=k)
        if not results:
            return ""
        parts = ["<user_memories>"]
        for r in results:
            parts.append(
                f"<memory name='{r['name']}' importance='{r['importance']}'>\n"
                f"{r['snippet']}\n"
                f"</memory>"
            )
        parts.append("</user_memories>")
        return "\n\n".join(parts)

    # ── decay / maintenance ──────────────────────────────────────────────────

    def decay(self) -> int:
        """Archive low-importance, long-untouched memories.

        Returns the number of memories archived.
        """
        archived = 0
        archive_dir = self._mem_dir / "_archive"
        cutoff = time.time() - (self.DECAY_DAYS * 86400)

        for f in self._mem_dir.glob("*.md"):
            meta = self._read_meta(f)
            importance = meta.get("importance", 5)
            last_accessed = meta.get("accessed", 0)

            if importance <= self.ARCHIVE_THRESHOLD and last_accessed < cutoff:
                archive_dir.mkdir(exist_ok=True)
                f.rename(archive_dir / f.name)
                archived += 1

        return archived

    # ── semantic search ──────────────────────────────────────────────────────

    def _semantic_search(self, query: str, k: int) -> list[dict[str, Any]]:  # pragma: no cover
        """Cosine-similarity search using sentence-transformers."""
        from sentence_transformers import util

        files = [f for f in self._mem_dir.glob("*.md")]
        if not files:
            return []

        model = _get_st_model()
        contents = [self._strip_meta(f.read_text(encoding="utf-8")) for f in files]
        corpus_emb = model.encode(contents, convert_to_tensor=True)
        query_emb = model.encode(query, convert_to_tensor=True)
        scores = util.cos_sim(query_emb, corpus_emb)[0].tolist()

        results: list[dict[str, Any]] = []
        for f, content, score in zip(files, contents, scores):
            if score > 0.1:
                meta = self._read_meta(f)
                results.append({
                    "name": f.stem,
                    "importance": meta.get("importance", 5),
                    "score": float(score),
                    "snippet": _make_snippet(content, query.lower()),
                })
        results.sort(key=lambda r: (int(r["importance"]), float(r["score"])), reverse=True)
        return results[:k]

    def _keyword_search(self, query: str, k: int) -> list[dict[str, Any]]:
        """Simple keyword-frequency fallback search."""
        query_lower = query.lower()
        words = query_lower.split()
        results: list[dict[str, Any]] = []

        for f in self._mem_dir.glob("*.md"):
            content = self._strip_meta(f.read_text(encoding="utf-8"))
            content_lower = content.lower()
            score = sum(content_lower.count(w) for w in words) if words else 0
            if score > 0:
                meta = self._read_meta(f)
                results.append({
                    "name": f.stem,
                    "importance": meta.get("importance", 5),
                    "score": score,
                    "snippet": _make_snippet(content, query_lower),
                })

        results.sort(key=lambda r: (int(r["importance"]), int(r["score"])), reverse=True)
        return results[:k]

    # ── metadata helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _strip_meta(raw: str) -> str:
        """Remove metadata comment block from file content."""
        if raw.startswith("<!--"):
            end = raw.find("-->")
            if end != -1:
                return raw[end + 3:].lstrip("\n")
        return raw

    @staticmethod
    def _read_meta(filepath: Path) -> dict[str, Any]:
        """Parse metadata from a memory file."""
        meta: dict[str, Any] = {"importance": 5, "saved": 0, "accessed": 0, "access_count": 0}
        if not filepath.exists():
            return meta
        first_line = filepath.read_text(encoding="utf-8").split("\n", 1)[0]
        if first_line.startswith("<!--") and first_line.endswith("-->"):
            inner = first_line[5:-3].strip()
            parts = inner.split()
            for p in parts:
                if ":" in p:
                    k, v = p.split(":", 1)
                    try:
                        meta[k] = int(v) if k in ("importance", "saved", "accessed", "access_count") else v
                    except ValueError:
                        meta[k] = v
        return meta


# ── helpers ──────────────────────────────────────────────────────────────────

def _sanitize(name: str) -> str:
    """Make a name safe for use as a filename."""
    return re.sub(r'[^\w\-]', '_', name).strip('_') or "unnamed"


def _make_snippet(content: str, query_lower: str, context_chars: int = 120) -> str:
    """Extract a snippet around the first match of query_lower."""
    idx = content.lower().find(query_lower)
    if idx == -1:
        return content[:300]
    start = max(0, idx - context_chars)
    end = min(len(content), idx + context_chars)
    snippet = content[start:end]
    if start > 0:
        snippet = "... " + snippet
    if end < len(content):
        snippet = snippet + " ..."
    return snippet


# ── module-level singleton ───────────────────────────────────────────────────

_user_memory: UserMemory | None = None
_user_memory_lock = threading.Lock()


def get_user_memory() -> UserMemory:
    """Get or create the shared UserMemory instance (thread-safe)."""
    global _user_memory
    if _user_memory is None:
        with _user_memory_lock:
            if _user_memory is None:
                _user_memory = UserMemory()
    return _user_memory
