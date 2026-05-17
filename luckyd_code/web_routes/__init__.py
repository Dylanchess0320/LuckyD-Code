"""Shared state for web route handlers, attached to app.state.web_state."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class WebAppState:
    """Mutable shared state injected into every request via app.state.web_state."""
    config: Any = None
    context: Any = None
    registry: Any = None
    mcp: Any = None
    web_memory_mgr: Any = None
    settings: dict[str, Any] = field(default_factory=dict)
    rate_limit_buckets: dict[str, dict[str, float]] = field(default_factory=dict)
    memory_module: Any = None
    brain_module: Any = None

    # Imported lazily by routes
    knowledge_graph: Any = None
    retriever: Any = None
    context_assembler: Any = None
