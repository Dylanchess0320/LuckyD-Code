"""Multi-agent orchestration — coordinate specialized agents for complex tasks."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from rich.console import Console

from .context import ConversationContext
from .tools import get_default_registry
from ._agent_loop import run_agent_loop

_console = Console()

__all__ = ["AgentHandoff", "Coordinator"]

_MAX_PARALLEL_WORKERS = 4  # cap on simultaneous API calls in parallel_orchestrate


def _truncate_to_tokens(text: str, max_tokens: int = 600) -> str:
    """Truncate *text* to at most *max_tokens* tokens.

    Uses tiktoken (cl100k_base) when available for a precise token count;
    falls back to a 4-chars-per-token heuristic so the function always works
    even in environments without the optional tiktoken dependency.

    1500 tokens (≈6 000 chars) is the default — enough to convey full research
    findings without blowing the coder’s context budget.
    """
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        tokens = enc.encode(text)
        if len(tokens) <= max_tokens:
            return text
        truncated = enc.decode(tokens[:max_tokens])
        return truncated + "\n[...truncated to fit context window]"
    except Exception:
        char_limit = max_tokens * 4
        if len(text) <= char_limit:
            return text
        return text[:char_limit] + "\n[...truncated to fit context window]"

# Role definitions with specialized system prompts
ROLE_PROMPTS = {
    "researcher": """You are a Research Agent. Your job is to investigate and gather information.
Use WebSearch, WebFetch, Grep, Glob, and Read tools to find information.
Return comprehensive findings with sources and details.
Be thorough - leave no stone unturned.

CRITICAL: If the user asks a question that is NOT about the project or codebase
(e.g., general knowledge, trivia, opinions, factual questions), answer it directly
and immediately. Do NOT try to relate it back to the project. Answer the question
the user actually asked.""",

    "coder": """You are a Coding Agent. Your job is to implement changes.
Use Read, Write, Edit, Glob, Grep, and Bash tools.
Write clean, correct, well-tested code.
Follow existing patterns in the codebase.
Verify your changes work before reporting done.

CRITICAL: If the user asks a question that is NOT about the project or codebase
(e.g., general knowledge, trivia, opinions, factual questions), answer it directly
and immediately. Do NOT try to relate it back to the project. Answer the question
the user actually asked.""",

    "reviewer": """You are a Review Agent. Your job is to review code and provide feedback.
Use Read, Glob, and Grep tools to examine code.
Check for: bugs, edge cases, security issues, performance problems,
code style consistency, error handling, and documentation.
Provide specific, actionable feedback with line references.

CRITICAL: If the user asks a question that is NOT about the project or codebase
(e.g., general knowledge, trivia, opinions, factual questions), answer it directly
and immediately. Do NOT try to relate it back to the project. Answer the question
the user actually asked.""",

    "tester": """You are a Testing Agent. Your job is to write and run tests.
Use Read, Write, Edit, Bash, and Glob tools.
Write tests that cover edge cases and main paths.
Run existing tests first, then add new ones.
Report test results clearly (pass/fail).

CRITICAL: If the user asks a question that is NOT about the project or codebase
(e.g., general knowledge, trivia, opinions, factual questions), answer it directly
and immediately. Do NOT try to relate it back to the project. Answer the question
the user actually asked.""",
}


class AgentHandoff:
    """Hand off a subtask to a specialized agent and get results back."""

    def __init__(self, config):
        self.config = config

    def handoff(self, role: str, task: str,
                tools: Optional[List[Dict[str, Any]]] = None) -> str:
        """Hand off a task to a specialized agent."""
        role = role.lower()
        if role not in ROLE_PROMPTS:
            return f"Error: unknown role '{role}'. Available: {', '.join(ROLE_PROMPTS.keys())}"

        # Build a context that combines the base system prompt with the
        # role-specific prompt. Using a single system message avoids
        # sending two consecutive system turns, which the DeepSeek API
        # does not support.
        combined_system = f"{self.config.system_prompt}\n\n{ROLE_PROMPTS[role]}"
        agent_ctx = ConversationContext(combined_system, max_messages=12)
        registry = get_default_registry()
        agent_ctx.add_user_message(task)

        return run_agent_loop(
            context=agent_ctx,
            config=self.config,
            tools=tools or registry.list_tools(),
            registry=registry,
            label=role,
        )


class Coordinator:
    """Break down tasks and distribute across specialized agents."""

    def __init__(self, config):
        self.config = config
        self.handoff = AgentHandoff(config)

    def orchestrate(self, task: str, roles: Optional[List[str]] = None) -> str:
        """Coordinate multiple agents for a complex task.

        Research and testing phases run in parallel when both are present,
        cutting total wall-clock time significantly on complex tasks.
        """
        if roles is None:
            roles = ["researcher", "coder", "reviewer"]

        results = {}
        report_parts = ["# Orchestration Report\n", f"**Task:** {task}\n"]

        # Phase 1: Run researcher + tester in parallel (they don't depend on each other)
        parallel_roles = [r for r in ["researcher", "tester"] if r in roles]
        if len(parallel_roles) > 1:
            _console.print(f"  [orchestrator] Running {' + '.join(parallel_roles)} in parallel...")
            sub_tasks = [
                ("researcher", f"Research this task and gather information: {task}"),
                ("tester", f"Review existing tests and identify what new tests will be needed for: {task}"),
            ]
            parallel_results = {}
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = {
                    executor.submit(self.handoff.handoff, role, sub_task): role
                    for role, sub_task in sub_tasks
                }
                for future in as_completed(futures):
                    role = futures[future]
                    try:
                        parallel_results[role] = future.result()
                    except Exception as e:
                        parallel_results[role] = f"Error: {e}"
            results.update(parallel_results)
            if "researcher" in results:
                report_parts.append(f"\n## Research Findings\n{results['researcher']}\n")
            if "tester" in results:
                report_parts.append(f"\n## Test Plan\n{results['tester']}\n")
        elif "researcher" in roles:
            _console.print("  [orchestrator] Research phase...")
            results["researcher"] = self.handoff.handoff(
                "researcher", f"Research this task and gather information: {task}"
            )
            report_parts.append(f"\n## Research Findings\n{results['researcher']}\n")
        elif "tester" in roles:
            _console.print("  [orchestrator] Test planning phase...")
            results["tester"] = self.handoff.handoff(
                "tester",
                f"Review existing tests and identify what new tests will be needed for: {task}",
            )
            report_parts.append(f"\n## Test Plan\n{results['tester']}\n")

        # Phase 2: Implementation (depends on research output)
        if "coder" in roles:
            context = results.get("researcher", "")
            coder_task = task
            if context:
                coder_task = f"{task}\n\nResearch context:\n{_truncate_to_tokens(context)}"

            _console.print("  [orchestrator] Implementation phase...")
            results["implementation"] = self.handoff.handoff("coder", coder_task)
            report_parts.append(f"\n## Implementation\n{results['implementation']}\n")

        # Phase 3: Review (depends on implementation)
        if "reviewer" in roles and "implementation" in results:
            _console.print("  [orchestrator] Review phase...")
            results["review"] = self.handoff.handoff(
                "reviewer",
                f"Review this implementation:\n{_truncate_to_tokens(results['implementation'])}"
            )
            report_parts.append(f"\n## Review Feedback\n{results['review']}\n")

        return "\n".join(report_parts)

    def parallel_orchestrate(self, task: str, sub_tasks: list[tuple[str, str]]) -> str:
        """Run multiple agents in parallel on different subtasks."""
        results = {}
        report_parts = ["# Parallel Orchestration\n", f"**Task:** {task}\n"]

        with ThreadPoolExecutor(max_workers=min(len(sub_tasks), _MAX_PARALLEL_WORKERS)) as executor:
            futures = {}
            for role, subtask in sub_tasks:
                _console.print(f"  [orchestrator] Launching {role}...")
                futures[executor.submit(self.handoff.handoff, role, subtask)] = role

            for future in as_completed(futures):
                role = futures[future]
                try:
                    results[role] = future.result()
                except Exception as e:
                    results[role] = f"Error: {e}"

        for role, result in results.items():
            report_parts.append(f"\n## {role.capitalize()} Results\n{result}\n")

        return "\n".join(report_parts)
