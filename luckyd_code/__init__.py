"""LuckyD Code — AI coding assistant in your terminal."""

__version__ = "1.2.3"
__author__ = "LuckyD Code"
__license__ = "MIT"

# ---------------------------------------------------------------------------
# Core symbols — imported eagerly because they are lightweight and always used.
# ---------------------------------------------------------------------------
from .cli_entry import main
from .config import Config
from .api import stream_chat, test_connection
from .context import ConversationContext
from .cost_tracker import CostTracker
from .hooks import HookRunner, get_hook_runner
from .router import resolve_initial_route, escalate_tier
from .model_registry import get_models_by_tier

# ---------------------------------------------------------------------------
# Heavy sub-packages (memory, tools, brain, settings) are imported lazily so
# that a bare `import luckyd_code` doesn't pull in sentence-transformers,
# FAISS, Playwright, or the full tool registry at cold-start.  They become
# available as normal attributes the first time they are accessed.
# ---------------------------------------------------------------------------
_LAZY_SUBPACKAGES = {"memory", "settings", "tools", "brain"}


def __getattr__(name: str):
    if name in _LAZY_SUBPACKAGES:
        import importlib
        module = importlib.import_module(f".{name}", package=__name__)
        # Cache on the package so subsequent accesses are instant.
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "main",
    "Config",
    "stream_chat",
    "test_connection",
    "ConversationContext",
    "CostTracker",
    "HookRunner",
    "get_hook_runner",
    "resolve_initial_route",
    "escalate_tier",
    "get_models_by_tier",
    "memory",
    "settings",
    "tools",
    "brain",
]
