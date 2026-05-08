"""Sub-agent support — spawn child agents for parallel work."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .config import Config
from .context import ConversationContext
from .tools import get_default_registry
from ._agent_loop import run_agent_loop, RunConfig

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
        # Sub-agents are ephemeral workers — disable memory persistence so
        # stream_chat is called exactly once per turn (avoids exhausting a
        # shared generator in tests and prevents noisy memory writes).
        rc = RunConfig(
            label="sub-agent",
            auto_save_memory=False,
        )
        return run_agent_loop(
            context=self.context,
            config=self.config,
            tools=self.tools or self.registry.list_tools(),
            registry=self.registry,
            label="sub-agent",
            run_config=rc,
        )
