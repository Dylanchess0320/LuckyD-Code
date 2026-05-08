"""Plugin system — auto-discover and load user plugins from ~/.luckyd-code/plugins/.

Plugins are .py files placed in ~/.luckyd-code/plugins/. Each plugin exports a
``register(registry)`` function that receives the ToolRegistry to add tools.

Example plugin (~/.luckyd-code/plugins/hello.py)::

    from luckyd_code.tools.registry import Tool

    class HelloTool(Tool):
        name = "Hello"
        description = "Say hello to someone."
        parameters = {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name to greet"},
            },
            "required": ["name"],
        }

        def run(self, name: str = "world") -> str:
            return f"Hello, {name}! Plugin system works."

    def register(registry):
        registry.register(HelloTool())
"""


import importlib.util
import logging
from pathlib import Path
from typing import Any, Callable

from .tools.registry import ToolRegistry

logger = logging.getLogger("luckyd_code.plugins")

from ._data_dir import data_path  # noqa: E402

PLUGIN_DIR = data_path("plugins")


def discover_plugins() -> list[Path]:
    """Find all .py files in the plugins directory."""
    if not PLUGIN_DIR.exists():
        return []
    return sorted(PLUGIN_DIR.glob("*.py"))


def load_plugin(path: Path) -> Callable[..., Any] | None:
    """Load a single plugin file and return its ``register`` function.

    Returns None if the plugin is invalid or has no register function.
    """
    try:
        spec = importlib.util.spec_from_file_location(path.stem, path)
        if not spec or not spec.loader:
            logger.warning("Could not load plugin: %s", path.name)
            return None

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        if not hasattr(module, "register"):
            logger.warning("Plugin '%s' has no register() function, skipping", path.name)
            return None

        register: Callable[..., Any] = module.register
        return register

    except Exception as e:
        logger.error("Failed to load plugin '%s': %s", path.name, e)
        return None


def load_all_plugins(registry: ToolRegistry) -> int:
    """Discover and load all plugins into the registry.

    Returns the number of plugins successfully loaded.
    """
    count = 0
    for path in discover_plugins():
        register_fn = load_plugin(path)
        if register_fn:
            try:
                register_fn(registry)
                count += 1
                logger.info("Loaded plugin: %s", path.name)
            except Exception as e:
                logger.error("Plugin '%s' register() failed: %s", path.name, e)
    return count
