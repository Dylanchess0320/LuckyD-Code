"""Sub-agent support — spawn child agents for parallel work."""

from __future__ import annotations

from typing import Any

from .config import Config
from .context import ConversationContext
from .tools import get_default_registry
from ._agent_loop import run_agent_loop, RunConfig

__all__ = ["SubAgent"]


class SubAgent:
    """A lightweight agent that runs independently with its own context.

    Parameters:
        config: Global configuration.
        task: The task description to run.
        tools: Optional tool list override.
        max_turns: Max tool-call iterations before the agent is cut off.
            Default 25 (up from RunConfig's default of 8) so complex
            multi-step tasks don't hit the limit prematurely.
    """

    def __init__(self, config: Config, task: str,
                 tools: list[dict[str, Any]] | None = None,
                 max_turns: int = 25):
        self.config = config
        self.task = task
        self.tools = tools
        self.max_turns = max_turns
        self.context = ConversationContext(
            config.system_prompt,
            max_messages=10,
        )
        self.registry = get_default_registry()

    def run(self) -> str:
        """Run the sub-agent synchronously and return its final response."""
        self.context.add_user_message(self.task)
        # Sub-agents are ephemeral workers — disable memory persistence so
        # stream_chat is called exactly once per turn (avoids exhausting a
        # shared generator in tests and prevents noisy memory writes).
        # max_turns is raised to 25 by default so sub-agents can complete
        # complex workflows without hitting the old 8-turn cap.
        rc = RunConfig(
            label="sub-agent",
            max_turns=self.max_turns,
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
