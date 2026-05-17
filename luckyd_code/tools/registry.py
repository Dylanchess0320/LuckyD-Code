import time
from typing import Any, Dict, Optional

# Tools in this set are read-only and safe to cache.
# Write/Bash/Git tools are explicitly excluded — their results must never be stale.
_CACHEABLE_TOOLS: frozenset[str] = frozenset({
    "Read", "Glob", "Grep", "WebFetch", "WebSearch", "DateTime",
    "YouTubePlaylist",  # pure URL construction — no I/O, deterministic output
})

# Default TTL for cached tool results (seconds).
_DEFAULT_CACHE_TTL: float = 300.0  # 5 minutes


class _CacheEntry:
    __slots__ = ("value", "expires_at")

    def __init__(self, value: str, ttl: float) -> None:
        self.value = value
        self.expires_at = time.monotonic() + ttl


class Tool:
    """Base class for all tools."""

    name: str = ""
    description: str = ""
    parameters: Dict[str, Any] = {}
    permission_risk: str = "safe"  # safe | medium | high

    def run(self, **kwargs) -> str:
        raise NotImplementedError

    def to_openai_tool(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """Registry of all available tools with optional result caching.

    Caching is applied only to read-only tools (``_CACHEABLE_TOOLS``).
    Cache keys are derived from the tool name and its sorted arguments, so
    calling ``Read`` on the same file twice within the TTL window costs only
    one real I/O operation.

    Set ``cache_ttl=0`` to disable caching entirely.
    """

    def __init__(self, cache_ttl: float = _DEFAULT_CACHE_TTL):
        self._tools: Dict[str, Tool] = {}
        self._cache: Dict[str, _CacheEntry] = {}
        self._cache_ttl = cache_ttl

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def list_tools(self) -> list[Dict[str, Any]]:
        return [t.to_openai_tool() for t in self._tools.values()]

    # ------------------------------------------------------------------ #
    #  Cache helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _cache_key(name: str, arguments: Dict[str, Any]) -> str:
        """Stable cache key: tool name + sorted argument pairs."""
        arg_repr = ",".join(f"{k}={v!r}" for k, v in sorted(arguments.items()))
        return f"{name}|{arg_repr}"

    def _get_cached(self, key: str) -> Optional[str]:
        entry = self._cache.get(key)
        if entry is None:
            return None
        if time.monotonic() > entry.expires_at:
            del self._cache[key]
            return None
        return entry.value

    def _set_cached(self, key: str, value: str) -> None:
        if self._cache_ttl <= 0:
            return
        # Evict expired entries when the cache grows large, OR unconditionally
        # every 60 seconds so short-lived sessions don't accumulate stale
        # entries indefinitely.
        now = time.monotonic()
        should_evict = (
            (len(self._cache) + 1) % 100 == 0    # every 100th insert (large cache)
            or getattr(self, "_last_evict", 0) + 60 < now  # time-based fallback
        )
        if should_evict:
            expired = [k for k, e in self._cache.items() if now > e.expires_at]
            for k in expired:
                del self._cache[k]
            self._last_evict = now
        self._cache[key] = _CacheEntry(value, self._cache_ttl)

    def invalidate(self, tool_name: Optional[str] = None) -> int:
        """Invalidate cache entries.

        Args:
            tool_name: If given, only entries for this tool are removed.
                       If None, the entire cache is cleared.

        Returns:
            Number of entries removed.
        """
        if tool_name is None:
            count = len(self._cache)
            self._cache.clear()
            return count
        prefix = f"{tool_name}|"
        keys = [k for k in self._cache if k.startswith(prefix)]
        for k in keys:
            del self._cache[k]
        return len(keys)

    # ------------------------------------------------------------------ #
    #  Execution
    # ------------------------------------------------------------------ #

    def execute(self, name: str, arguments: Dict[str, Any], check_perm=None) -> str:
        tool = self.get(name)
        if not tool:
            return f"Error: unknown tool '{name}'"

        if check_perm:
            allowed = check_perm(name)
            if not allowed:
                return f"Permission denied for tool '{name}'"

        # Check cache for eligible read-only tools
        use_cache = name in _CACHEABLE_TOOLS and self._cache_ttl > 0
        if use_cache:
            key = self._cache_key(name, arguments)
            cached = self._get_cached(key)
            if cached is not None:
                return cached

        try:
            result = tool.run(**arguments)
        except Exception as e:
            return f"Error executing {name}: {e}"

        if use_cache:
            self._set_cached(key, result)

        return result
