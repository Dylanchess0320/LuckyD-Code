"""Plan-before-execute gate — enforce a planning phase before agent execution.

In daemon (unattended) mode  → ``auto_plan``  generates a plan without blocking.
In interactive mode           → ``plan_and_approve`` (from planner) shows the
                                plan in rich Markdown and waits for confirmation.

The gate integrates cleanly with ``audit_daemon._attempt_improvement`` by
injecting a structured task breakdown into the agent prompt, giving the
agent a concrete checklist to work through rather than an open-ended task.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .planner import ai_create_plan, save_plan

_log = logging.getLogger(__name__)


@dataclass
class GateResult:
    """Outcome of a plan gate evaluation."""
    plan: object              # Optional[Plan] — typed as object to avoid circular import
    approved: bool
    reason: str               # human-readable explanation


# ------------------------------------------------------------------ #
#  Non-interactive (daemon) path
# ------------------------------------------------------------------ #

def auto_plan(task: str, config, max_steps: int = 8) -> GateResult:
    """Generate a plan without user interaction (always approves).

    Used by ``audit_daemon`` and other unattended callers.  Falls back
    to a minimal single-step plan if the API call fails.

    Args:
        task:      Natural-language description of what needs to be done.
        config:    App config with api_key / base_url / model attributes.
        max_steps: Cap the number of steps to prevent runaway plans.

    Returns a :class:`GateResult` with ``approved=True`` (or False on
    catastrophic failure).
    """
    slug = re.sub(r"[^a-z0-9]+", "_", task[:30].lower()).strip("_") or "plan"
    name = f"auto_{slug}_{datetime.now().strftime('%H%M%S')}"

    try:
        plan = ai_create_plan(name, task, config)
        if len(plan.steps) > max_steps:
            plan.steps = plan.steps[:max_steps]
            save_plan(plan)
        _log.debug("auto_plan: generated %d-step plan '%s'", len(plan.steps), name)
        return GateResult(plan=plan, approved=True, reason="auto-approved (daemon mode)")
    except Exception as exc:
        _log.warning("auto_plan: generation failed — %s", exc)
        return GateResult(plan=None, approved=False, reason=f"plan generation failed: {exc}")


# ------------------------------------------------------------------ #
#  Formatting helpers
# ------------------------------------------------------------------ #

def gate_summary(result: GateResult) -> str:
    """One-line summary of a GateResult suitable for log messages."""
    if result.plan is None:
        return f"No plan — {result.reason}"
    steps = getattr(result.plan, "steps", [])
    total_min = sum(getattr(s, "estimated_minutes", 0) for s in steps)
    status = "✓ approved" if result.approved else "✗ rejected"
    name = getattr(result.plan, "name", "?")
    return (
        f"Plan '{name}' — {len(steps)} steps, ~{total_min} min "
        f"— {status} ({result.reason})"
    )


def plan_to_prompt_context(result: GateResult) -> str:
    """Serialize an approved plan into a compact string for prompt injection.

    Returns an empty string if no plan is available (so callers can safely
    concatenate without an ``if`` guard).
    """
    if not result.approved or result.plan is None:
        return ""

    steps = getattr(result.plan, "steps", [])
    if not steps:
        return ""

    lines = [
        "## Execution Plan",
        f"Goal: {getattr(result.plan, 'goal', '')}",
        "",
    ]
    for s in steps:
        sid = getattr(s, "id", "?")
        title = getattr(s, "title", "")
        desc = getattr(s, "description", "")
        agent = getattr(s, "agent", "coder")
        est = getattr(s, "estimated_minutes", 5)
        lines.append(f"Step {sid} [{agent}, ~{est}m]: {title}")
        if desc:
            lines.append(f"  {desc}")
    lines.append("")
    lines.append("Work through the steps above in order.  Mark each done before starting the next.")
    return "\n".join(lines)


# ------------------------------------------------------------------ #
#  Stateful gate object
# ------------------------------------------------------------------ #

class PlanGate:
    """Stateful plan gate for a single task execution.

    Wraps plan generation and approval into one object so the caller does
    not need to manage the GateResult manually.

    Usage (daemon)::

        gate = PlanGate(task, config)
        result = gate.generate()
        if result.approved:
            prompt_ctx = gate.prompt_context()  # inject into agent prompt

    Usage (interactive)::

        gate = PlanGate(task, config, interactive=True)
        result = gate.generate()          # blocks for user confirmation
        if result.approved:
            ...
    """

    def __init__(self, task: str, config, interactive: bool = False):
        self.task = task
        self.config = config
        self.interactive = interactive
        self._result: Optional[GateResult] = None

    # ------------------------------------------------------------------ #
    #  Core API
    # ------------------------------------------------------------------ #

    def generate(self) -> GateResult:
        """Generate (and optionally display) a plan.  Caches the result."""
        if self._result is not None:
            return self._result

        if self.interactive:  # pragma: no cover
            from .planner import plan_and_approve
            plan = plan_and_approve(self.task, self.config)
            self._result = GateResult(
                plan=plan,
                approved=plan is not None,
                reason="user approved" if plan else "user rejected",
            )
        else:
            self._result = auto_plan(self.task, self.config)

        return self._result

    def prompt_context(self) -> str:
        """Return the plan formatted for injection into an agent prompt.

        Returns an empty string if no plan has been generated or approved.
        """
        if self._result is None:
            return ""
        return plan_to_prompt_context(self._result)

    def task_list(self) -> list[str]:
        """Return step descriptions as a flat list of strings.

        Useful for building progress-tracking UIs.
        """
        if self._result is None or self._result.plan is None:
            return []
        return [
            f"[{getattr(s, 'agent', 'coder')}] "
            f"Step {getattr(s, 'id', '?')}: {getattr(s, 'title', '')} — "
            f"{getattr(s, 'description', '')}"
            for s in getattr(self._result.plan, "steps", [])
        ]

    @property
    def plan(self) -> Optional[object]:
        """Shortcut to the Plan object (None if not generated or rejected)."""
        return self._result.plan if self._result else None

    @property
    def approved(self) -> bool:
        """True only after generate() has been called and approved the plan."""
        return bool(self._result and self._result.approved)
