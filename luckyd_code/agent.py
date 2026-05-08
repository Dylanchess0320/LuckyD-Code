"""Sub-agent support — spawn child agents for parallel work."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .config import Config
from .context import ConversationContext
from .tools import get_default_registry
from ._agent_loop import run_agent_loop

__all__ = ["SubAgent"]


class SubAgent:
    """A lightweight agent that runs independently with its own context."""

    def __init__(self, config: Config, task: str,
                 tools: Optional[List[Dict[str, Any]]] = None):
        self.config = config
        self.task = task
        self.tools = tools
        self.context = ConversationContext(
            config.system_prompt,
            max_messages=20,
        )
        self.registry = get_default_registry()

    def run(self) -> str:
        """Run the sub-agent synchronously and return its final response."""
        self.context.add_user_message(self.task)
        return run_agent_loop(
            context=self.context,
            config=self.config,
            tools=self.tools or self.registry.list_tools(),
            registry=self.registry,
            label="sub-agent",
        )
