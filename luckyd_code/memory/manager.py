"""Persistent memory system — file-based, survives across sessions.

Stores memories in the project data directory under projects/<project-name>/memory/.
Auto-saves conversation summaries, enables search and injection.

Memories carry metadata (importance, timestamps, access count) for decay management.
Low-importance, long-untouched memories are auto-archived after 30 days.

Search strategy:
  - When ``sentence-transformers`` is installed (the ``rag`` extra), memories
    are searched semantically using cosine similarity of sentence embeddings.
  - Otherwise, a simple keyword-frequency fallback is used automatically.

Cross-project search indexes all known project memory directories for
a global recall capability.
"""

import os
import re
import threading
import time
from pathlib import Path
from typing import Any

from .._data_dir import data_path

# ---------------------------------------------------------------------------
# SentenceTransformer singleton — loading the model takes 1-3 seconds and
# pulls ~90 MB into memory.  Caching it here means the cost is paid once per
# process instead of on every search call.
# ---------------------------------------------------------------------------
_ST_MODEL = None
_ST_MODEL_LOCK = threading.Lock()


def _get_st_model():  # pragma: no cover
    """Return the cached SentenceTransformer, loading it on first call."""
    global _ST_MODEL
    if _ST_MODEL is None:
        with _ST_MODEL_LOCK:
            if _ST_MODEL is None:  # double-checked locking
                from sentence_transformers import SentenceTransformer
                _ST_MODEL = SentenceTransformer("all-MiniLM-L6-v2")
    return _ST_MODEL


class MemoryManager:
    """Project-scoped persistent memory with CRUD, search, and auto-summary."""

    def __init__(self, project_dir: str | None = None):
        self.project_dir = project_dir or os.getcwd()
        self.project_name = Path(self.project_dir).name
        self.mem_dir = data_path("projects", self.project_name, "memory")
        self.mem_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    #  CRUD
    # ------------------------------------------------------------------ #

    def save_memory(
        self, name: str, content: str, memory_type: str = "general",
        importance: int = 5,
    ) -> str:
        """Save a memory file and update MEMORY.md index.

        Args:
            name:         Short label (used as filename).
            content:      Full markdown or plain text content.
            memory_type:  Category tag (session, general, technical, etc.).
            importance:   1-10, where 10 is "never forget". Default 5.

        Returns the file path.
        """
        safe_name = self._sanitize(name)
        filename = f"{memory_type}_{safe_name}.md"
        filepath = self.mem_dir / filename

        # Read existing metadata if updating
        existing_meta = self._read_meta(filepath)
        access_count = existing_meta.get("access_count", 0)

        now = time.time()
        meta = (
            f"<!-- importance:{importance} saved:{now:.0f} "
            f"accessed:{now:.0f} count:{access_count} -->\n"
        )
        filepath.write_text(meta + content, encoding="utf-8")

        self._update_index(name, filename, content)
        return str(filepath)

    def load_memory(self, name: str, memory_type: str = "general") -> str | None:
        """Load a specific memory by name and type.

        Updates the accessed timestamp and access count on read.
        """
        safe_name = self._sanitize(name)
        filepath = self.mem_dir / f"{memory_type}_{safe_name}.md"
        if filepath.exists():
            raw = filepath.read_text(encoding="utf-8")
            content = self._strip_meta(raw)
            # Bump access metadata and re-save
            meta = self._read_meta(filepath)
            self.save_memory(
                name, content, memory_type,
                importance=meta.get("importance", 5),
            )
            return content
        return None

    def delete_memory(self, name: str, memory_type: str = "general") -> bool:
        """Delete a memory file. Returns True if deleted."""
        safe_name = self._sanitize(name)
        filepath = self.mem_dir / f"{memory_type}_{safe_name}.md"
        if filepath.exists():
            filepath.unlink()
            self._rebuild_index()
            return True
        return False

    def list_memories(self, memory_type: str | None = None) -> list[dict]:
        """List all memories, optionally filtered by type. Returns list of {name, type, path, importance}."""
        results = []
        pattern = f"{memory_type}_*.md" if memory_type else "*.md"
        for f in sorted(self.mem_dir.glob(pattern)):
            if f.name == "MEMORY.md":
                continue
            parts = f.stem.split("_", 1)
            typ = parts[0] if len(parts) > 1 else "general"
            name = parts[1] if len(parts) > 1 else parts[0]
            meta = self._read_meta(f)
            results.append({
                "name": name, "type": typ, "path": str(f),
                "importance": meta.get("importance", 5),
                "saved": meta.get("saved", 0),
                "accessed": meta.get("accessed", 0),
            })
        return results

    # ------------------------------------------------------------------ #
    #  Search
    # ------------------------------------------------------------------ #

    def search_memories(self, query: str, k: int = 5) -> list[dict]:
        """Search memories by relevance.

        Uses semantic cosine-similarity search when ``sentence-transformers``
        is available; falls back to keyword-frequency scoring otherwise.

        Returns up to ``k`` results sorted by relevance, each with
        ``file``, ``name``, ``score``, and ``snippet`` keys.
        """
        try:
            return self._semantic_search(query, k)
        except Exception:
            return self._keyword_search(query, k)

    def _semantic_search(self, query: str, k: int) -> list[dict]:  # pragma: no cover
        """Cosine-similarity search using sentence-transformers."""
        from sentence_transformers import util

        files = [f for f in self.mem_dir.glob("*.md") if f.name != "MEMORY.md"]
        if not files:
            return []

        model = _get_st_model()
        contents = [f.read_text(encoding="utf-8") for f in files]
        corpus_emb = model.encode(contents, convert_to_tensor=True)
        query_emb = model.encode(query, convert_to_tensor=True)
        scores = util.cos_sim(query_emb, corpus_emb)[0].tolist()

        results: list[dict[str, Any]] = []
        for f, content, score in zip(files, contents, scores):
            if score > 0.1:  # ignore near-zero similarity
                results.append({
                    "file": f.name,
                    "name": f.stem.split("_", 1)[-1] if "_" in f.stem else f.stem,
                    "score": float(score),
                    "snippet": self._make_snippet(content, query.lower()),
                })
        results.sort(key=lambda r: float(r["score"]), reverse=True)
        return results[:k]

    def _keyword_search(self, query: str, k: int) -> list[dict]:
        """Simple keyword-frequency search (always available)."""
        query_lower = query.lower()
        words = query_lower.split()
        results: list[dict[str, Any]] = []

        for f in self.mem_dir.glob("*.md"):
            if f.name == "MEMORY.md":
                continue
            content = f.read_text(encoding="utf-8")
            content_lower = content.lower()
            score = sum(content_lower.count(w) for w in words) if words else 0
            if score > 0:
                results.append({
                    "file": f.name,
                    "name": f.stem.split("_", 1)[-1] if "_" in f.stem else f.stem,
                    "score": score,
                    "snippet": self._make_snippet(content, query_lower),
                })

        results.sort(key=lambda r: int(r["score"]), reverse=True)
        return results[:k]

    # ------------------------------------------------------------------ #
    #  Cross-project search
    # ------------------------------------------------------------------ #

    def cross_project_search(self, query: str, k: int = 3) -> list[dict]:  # pragma: no cover
        """Search memories across all known projects.

        Scans the projects/ directory for any project with a memory/
        subdirectory and searches each one. Useful for finding information
        that may live in a different project than the current one.

        Returns results with an extra ``project`` key.
        """
        projects_dir = data_path("projects")
        all_results: list[dict] = []

        for proj_path in projects_dir.iterdir():
            if not proj_path.is_dir():
                continue
            mem_dir = proj_path / "memory"
            if not mem_dir.is_dir():
                continue

            # Create a temporary manager scoped to this project
            tmp = MemoryManager(str(proj_path))
            local_results = tmp.search_memories(query, k=k)
            for r in local_results:
                r["project"] = proj_path.name
            all_results.extend(local_results)

        # Sort by score descending, break ties with importance
        all_results.sort(
            key=lambda r: (float(r.get("score", 0)), int(r.get("importance", 5))),
            reverse=True,
        )
        return all_results[:k]

    # ------------------------------------------------------------------ #
    #  Decay / maintenance
    # ------------------------------------------------------------------ #

    def decay(self, max_days: int = 30, importance_threshold: int = 3) -> int:
        """Archive low-importance, long-untouched memories.

        Moves files to an _archive/ subdirectory. Returns count archived.
        """
        archived = 0
        archive_dir = self.mem_dir / "_archive"
        cutoff = time.time() - (max_days * 86400)

        for f in self.mem_dir.glob("*_*.md"):
            if f.name == "MEMORY.md":
                continue
            meta = self._read_meta(f)
            importance = meta.get("importance", 5)
            last_accessed = meta.get("accessed", 0)

            if importance <= importance_threshold and last_accessed < cutoff:
                archive_dir.mkdir(exist_ok=True)
                f.rename(archive_dir / f.name)
                archived += 1

        if archived:
            self._rebuild_index()
        return archived

    def save_conversation_summary(self, summary: str, turn_count: int = 0):
        """Auto-save a conversation summary to a rotating slot.

        Keeps the last N summaries (default 10) by using a numbered
        filename.
        """
        self.save_memory("latest_summary", summary, memory_type="session")
        # Also append to running log
        log_path = self.mem_dir / "session_log.md"
        from datetime import datetime
        entry = (
            f"## Session — {datetime.now().isoformat()}\n"
            f"**Turns:** {turn_count}\n\n{summary}\n\n"
        )
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(entry)

    # ------------------------------------------------------------------ #
    #  Context injection helpers
    # ------------------------------------------------------------------ #

    def get_relevant_memories(self, context: str, k: int = 3) -> str:
        """Search memories relevant to the given context and return formatted text."""
        results = self.search_memories(context, k=k)
        if not results:
            return ""
        parts = ["<memories>"]
        for r in results:
            parts.append(f"### {r['name']}\n{r['snippet']}")
        parts.append("</memories>")
        return "\n\n".join(parts)

    def get_all_memories_formatted(self) -> str:
        """Return all memories as a formatted XML block for prompt injection."""
        memories = self.list_memories()
        if not memories:
            return ""

        parts = ["<memories>"]
        for m in memories:
            content = self.load_memory(m["name"], m["type"]) or ""
            # Truncate very long memories
            if len(content) > 500:
                content = content[:500] + f"\n... (truncated, {len(content)} total chars)"
            parts.append(f"<memory name='{m['name']}' type='{m['type']}'>\n{content}\n</memory>")
        parts.append("</memories>")
        return "\n\n".join(parts)

    # ------------------------------------------------------------------ #
    #  Project memory helpers (MEMORY.md / CLAUDE.md)
    # ------------------------------------------------------------------ #

    def load_claude_md(self) -> str:
        """Load the project memory file.

        Checks MEMORY.md first, then CLAUDE.md for backward compatibility.
        """
        for name in ("MEMORY.md", "CLAUDE.md"):
            path = Path(self.project_dir) / name
            if path.exists():
                return path.read_text(encoding="utf-8")
        return ""

    def save_claude_md(self, content: str):
        """Save the project memory file as MEMORY.md."""
        path = Path(self.project_dir) / "MEMORY.md"
        path.write_text(content, encoding="utf-8")

    # ------------------------------------------------------------------ #
    #  Internal helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _sanitize(name: str) -> str:
        """Make a name safe for use as a filename."""
        return re.sub(r'[^\w\-]', '_', name).strip('_') or "unnamed"

    @staticmethod
    def _strip_meta(raw: str) -> str:
        """Remove metadata comment block from file content."""
        if raw.startswith("<!--"):
            end = raw.find("-->")
            if end != -1:
                return raw[end + 3:].lstrip("\n")
        return raw

    @staticmethod
    def _read_meta(filepath: Path) -> dict:
        """Parse metadata from a memory file header."""
        meta: dict = {"importance": 5, "saved": 0, "accessed": 0, "access_count": 0}
        if not filepath.exists():
            return meta
        try:
            first_line = filepath.read_text(encoding="utf-8").split("\n", 1)[0]
            if first_line.startswith("<!--") and first_line.endswith("-->"):
                inner = first_line[5:-3].strip()
                for part in inner.split():
                    if ":" in part:
                        k, v = part.split(":", 1)
                        try:
                            meta[k] = int(v) if k in ("importance", "saved", "accessed", "access_count") else v
                        except ValueError:
                            meta[k] = v
        except Exception:
            pass
        return meta

    @staticmethod
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

    def _update_index(self, name: str, filename: str, content: str):
        """Add or update an entry in MEMORY.md."""
        index_path = self.mem_dir / "MEMORY.md"
        entry = f"- [{name}]({filename}) — {content[:80].strip()}"
        if index_path.exists():
            existing = index_path.read_text(encoding="utf-8")
            # Replace existing entry if it exists
            if f"[{name}]" in existing:
                lines = existing.split("\n")
                new_lines = [
                    entry if f"[{name}]" in line else line
                    for line in lines
                ]
                index_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            else:
                with open(index_path, "a", encoding="utf-8") as f:
                    f.write(entry + "\n")
        else:
            index_path.write_text(f"# Memory Index\n\n{entry}\n", encoding="utf-8")

    def _rebuild_index(self):
        """Rebuild MEMORY.md from all memory files."""
        index_path = self.mem_dir / "MEMORY.md"
        files = sorted(self.mem_dir.glob("*.md"))
        entries = []
        for f in files:
            if f.name == "MEMORY.md":
                continue
            name = f.stem.split("_", 1)[-1] if "_" in f.stem else f.stem
            content = f.read_text(encoding="utf-8")
            entries.append(f"- [{name}]({f.name}) — {content[:80].strip()}")
        if entries:
            index_path.write_text("# Memory Index\n\n" + "\n".join(entries) + "\n", encoding="utf-8")
        elif index_path.exists():
            index_path.unlink()


# ------------------------------------------------------------------ #
#  Module-level convenience API (backwards-compatible)
# ------------------------------------------------------------------ #

_DEFAULT_MANAGER: MemoryManager | None = None
_MANAGER_LOCK = threading.Lock()


def _get_manager() -> MemoryManager:
    global _DEFAULT_MANAGER
    if _DEFAULT_MANAGER is None:
        with _MANAGER_LOCK:
            if _DEFAULT_MANAGER is None:  # double-checked locking
                _DEFAULT_MANAGER = MemoryManager()
    return _DEFAULT_MANAGER


def get_project_memory_dir() -> str:
    return str(_get_manager().mem_dir)


def load_claude_md() -> str:
    return _get_manager().load_claude_md()


def save_claude_md(content: str):
    _get_manager().save_claude_md(content)


def load_memory_index() -> str:
    return _get_manager().get_all_memories_formatted()


def save_memory(name: str, content: str, memory_type: str = "general"):
    _get_manager().save_memory(name, content, memory_type)


def list_memories() -> str:
    memories = _get_manager().list_memories()
    if not memories:
        return "No memories yet."
    return "\n".join(f"- {m['name']} ({m['type']})" for m in memories)
