"""Sub-agent tool for spawning child agents."""

from .registry import Tool


# Reference to the Repl instance for config access
_repl = None


def set_repl(repl):
    global _repl
    _repl = repl


class SubAgentTool(Tool):
    name = "SubAgent"
    description = (
        "Spawn a child agent to work independently on a focused subtask. "
        "Use when a task can be cleanly isolated: deep research, exploring an unfamiliar codebase, "
        "generating a large standalone file, or any work that shouldn't pollute the main context. "
        "The sub-agent runs its own tool loop and returns a summary. "
        "Prefer AgentHandoff when you need a named specialist role."
    )
    permission_risk = "medium"
    parameters = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "The task for the sub-agent to complete",
            },
        },
        "required": ["task"],
    }

    def run(self, task: str) -> str:  # type: ignore[override]
        global _repl
        if _repl is None:
            return "Error: sub-agent not available (not initialized)"
        from ..agent import SubAgent
        agent = SubAgent(_repl.config, task, _repl.registry.list_tools())
        return agent.run()


class AgentHandoffTool(Tool):
    name = "AgentHandoff"
    description = (
        "Hand off a subtask to a specialist agent. Use this instead of doing everything yourself "
        "when a task has a clear specialist role:\n"
        "  - researcher: web search, reading docs, gathering facts before coding\n"
        "  - coder: implementing a feature or fix after research is done\n"
        "  - reviewer: auditing code for bugs, security issues, or style problems\n"
        "  - tester: writing or running tests for a specific module\n"
        "Chain multiple handoffs for complex tasks: researcher → coder → reviewer."
    )
    permission_risk = "medium"
    parameters = {
        "type": "object",
        "properties": {
            "role": {
                "type": "string",
                "enum": ["researcher", "coder", "reviewer", "tester"],
                "description": "The specialist role to hand off to",
            },
            "task": {
                "type": "string",
                "description": "The specific task for the specialist agent",
            },
        },
        "required": ["role", "task"],
    }

    def run(self, role: str, task: str) -> str:  # type: ignore[override]
        global _repl
        if _repl is None:
            return "Error: handoff not available (not initialized)"
        from ..orchestrator import AgentHandoff
        handoff = AgentHandoff(_repl.config)
        return handoff.handoff(role, task, _repl.registry.list_tools())
