"""AI-powered planning module — decompose tasks into structured, executable steps.

The planner uses the configured AI API to break down complex tasks into ordered steps
with agent assignments, dependency tracking, and time estimates. Plans are saved
as structured Markdown files in the project data directory for persistence across sessions.
"""

import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import TYPE_CHECKING
from ._data_dir import project_data_path

_log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ._agent_loop import _AgentConfig as _PlanConfig


# ------------------------------------------------------------------ #
#  Plan data model
# ------------------------------------------------------------------ #

@dataclass
class PlanStep:
    id: int
    title: str
    description: str
    agent: str          # researcher | coder | reviewer | tester | user
    depends_on: list[int] = field(default_factory=list)
    estimated_minutes: int = 5
    status: str = "pending"  # pending | in_progress | done | skipped


@dataclass
class Plan:
    name: str
    goal: str
    steps: list[PlanStep] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    def to_markdown(self) -> str:
        from datetime import datetime
        lines = [
            f"# Plan: {self.name}",
            f"\n**Goal:** {self.goal}",
            f"\n**Created:** {self.created_at or datetime.now().isoformat()}",
            "\n## Steps\n",
        ]
        status_icon = {"pending": "⬜", "in_progress": "🔄", "done": "✅", "skipped": "⏭️", "error": "❌"}
        for step in self.steps:
            icon = status_icon.get(step.status, "⬜")
            deps = f" _(after steps {step.depends_on})_" if step.depends_on else ""
            lines.append(f"### {icon} Step {step.id}: {step.title}{deps}")
            lines.append(f"**Agent:** `{step.agent}` · **Est.:** {step.estimated_minutes} min")
            lines.append(f"\n{step.description}\n")
        return "\n".join(lines)

    def summary(self) -> str:
        done = sum(1 for s in self.steps if s.status == "done")
        total = len(self.steps)
        total_min = sum(s.estimated_minutes for s in self.steps)
        return f"{done}/{total} steps done · ~{total_min} min total"


# ------------------------------------------------------------------ #
#  Storage helpers
# ------------------------------------------------------------------ #


def _plans_dir() -> Path:
    p = project_data_path("plans")
    p.mkdir(parents=True, exist_ok=True)
    return p


def _plan_path(name: str) -> Path:
    return _plans_dir() / f"{name}.md"


def _plan_json_path(name: str) -> Path:
    return _plans_dir() / f"{name}.json"


def save_plan(plan: Plan) -> str:
    """Persist a plan as both Markdown (human-readable) and JSON (machine-readable)."""
    from datetime import datetime
    if not plan.created_at:
        plan.created_at = datetime.now().isoformat()
    plan.updated_at = datetime.now().isoformat()

    _plan_path(plan.name).write_text(plan.to_markdown(), encoding="utf-8")
    _plan_json_path(plan.name).write_text(
        json.dumps(asdict(plan), indent=2), encoding="utf-8"
    )
    return str(_plan_path(plan.name))


def load_plan(name: str) -> "Plan | None":
    """Load a plan from JSON (preferred) or fall back to Markdown."""
    json_path = _plan_json_path(name)
    if json_path.exists():
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            steps = [PlanStep(**s) for s in data.get("steps", [])]
            return Plan(
                name=data["name"],
                goal=data["goal"],
                steps=steps,
                created_at=data.get("created_at", ""),
                updated_at=data.get("updated_at", ""),
            )
        except Exception as exc:
            _log.warning(
                "load_plan: failed to deserialise plan '%s' from JSON: %s",
                name, exc, exc_info=True,
            )
    return None


def list_plans() -> str:
    """List all saved plans with a one-line summary each."""
    files = sorted(_plans_dir().glob("*.json"))
    if not files:
        return "No plans yet. Use /plan create <name> <goal> to create one."
    lines = []
    for f in files:
        plan = load_plan(f.stem)
        if plan:
            lines.append(f"  • {plan.name}: {plan.goal[:60]} — {plan.summary()}")
        else:
            lines.append(f"  • {f.stem}")
    return "\n".join(lines)


def read_plan(name: str) -> str:
    """Return the Markdown representation of a plan."""
    plan = load_plan(name)
    if plan:
        return plan.to_markdown()
    md_path = _plan_path(name)
    if md_path.exists():
        return md_path.read_text(encoding="utf-8")
    return f"Plan '{name}' not found."


def delete_plan(name: str) -> str:
    """Delete a plan (both Markdown and JSON files)."""
    removed = []
    for p in [_plan_path(name), _plan_json_path(name)]:
        if p.exists():
            p.unlink()
            removed.append(p.name)
    return f"Deleted: {', '.join(removed)}" if removed else f"Plan '{name}' not found."


def update_step_status(name: str, step_id: int, status: str) -> str:
    """Mark a step as done/in_progress/skipped and re-save the plan."""
    valid = {"pending", "in_progress", "done", "skipped", "error"}
    if status not in valid:
        return f"Invalid status '{status}'. Must be one of: {', '.join(sorted(valid))}"
    plan = load_plan(name)
    if not plan:
        return f"Plan '{name}' not found."
    for step in plan.steps:
        if step.id == step_id:
            step.status = status
            save_plan(plan)
            return f"Step {step_id} marked as '{status}'. {plan.summary()}"
    return f"Step {step_id} not found in plan '{name}'."


# ------------------------------------------------------------------ #
#  AI-powered plan generation
# ------------------------------------------------------------------ #

_PLANNER_SYSTEM = """You are an expert software engineering planner.
Break down the user's goal into a concrete, ordered list of steps.
Each step must be assigned to one of these agents: researcher, coder, reviewer, tester.
Use 'user' for steps that require human input or decisions.

Respond with ONLY a valid JSON object — no preamble, no markdown fences — in this exact schema:
{
  "steps": [
    {
      "id": 1,
      "title": "Short title",
      "description": "Detailed description of what to do and how",
      "agent": "researcher|coder|reviewer|tester|user",
      "depends_on": [],
      "estimated_minutes": 10
    }
  ]
}

Guidelines:
- Keep steps atomic and independently executable.
- Use depends_on to express ordering (step 3 depends on step 1 means [1]).
- Parallel steps that can run simultaneously should have the same depends_on list.
- estimated_minutes should be realistic (5-120).
- Minimum 3 steps, maximum 15 steps.
"""


def ai_create_plan(name: str, goal: str, config: "_PlanConfig") -> Plan:  # pragma: no cover
    """Use the DeepSeek API to decompose a goal into a structured Plan.

    Falls back to a minimal placeholder plan if the API call fails.

    Args:
        name:   Short identifier for the plan (used as filename).
        goal:   Natural-language description of what needs to be accomplished.
        config: App config object with api_key, base_url, model attributes.

    Returns:
        A populated ``Plan`` instance (already saved to disk).
    """
    from openai import OpenAI
    import httpx

    steps: list[PlanStep] = []

    try:
        client = OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            http_client=httpx.Client(timeout=30),
        )
        resp = client.chat.completions.create(
            model="deepseek-v4-flash",   # Flash is fast and cheap for planning
            messages=[
                {"role": "system", "content": _PLANNER_SYSTEM},
                {"role": "user", "content": f"Goal: {goal}"},
            ],
            max_tokens=2000,
            temperature=0.3,
        )
        raw = (resp.choices[0].message.content or "").strip()

        # Strip any accidental markdown code fences
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        data = json.loads(raw)
        for s in data.get("steps", []):
            steps.append(PlanStep(
                id=int(s.get("id", len(steps) + 1)),
                title=str(s.get("title", "Untitled")),
                description=str(s.get("description", "")),
                agent=str(s.get("agent", "coder")),
                depends_on=[int(d) for d in s.get("depends_on", [])],
                estimated_minutes=int(s.get("estimated_minutes", 10)),
            ))
    except Exception as exc:
        # Fallback: single placeholder step so the plan is never empty
        steps = [
            PlanStep(
                id=1,
                title="Investigate and implement",
                description=f"Complete the goal: {goal}\n\n(Plan generation failed: {exc})",
                agent="coder",
                depends_on=[],
                estimated_minutes=30,
            )
        ]

    plan = Plan(name=name, goal=goal, steps=steps)
    save_plan(plan)
    return plan


# ------------------------------------------------------------------ #
#  Interactive plan approval and execution
# ------------------------------------------------------------------ #

def plan_and_approve(goal: str, config, session=None) -> "Plan | None":  # pragma: no cover
    """Generate a plan with AI, show it, and ask the user to approve it.

    Returns the approved ``Plan`` if the user confirms, or ``None`` if
    the user rejects it or presses Ctrl-C.
    """
    import re
    from datetime import datetime
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.prompt import Confirm

    _console = Console()

    # Build a safe plan name from the goal
    slug = re.sub(r"[^a-z0-9]+", "_", goal[:30].lower()).strip("_") or "plan"
    name = f"{slug}_{datetime.now().strftime('%H%M%S')}"

    _console.print(f"\n[bold cyan]Creating plan for:[/bold cyan] {goal}")
    _console.print("[dim]Generating steps with AI...[/dim]")

    plan = ai_create_plan(name, goal, config)

    _console.print(f"\n[bold]Generated Plan: {plan.name}[/bold]")
    _console.print(Markdown(plan.to_markdown()))
    _console.print(f"\n[dim]{plan.summary()}[/dim]")

    try:
        approved = Confirm.ask("\nProceed with this plan?", default=True)
    except (KeyboardInterrupt, EOFError):
        approved = False

    if not approved:
        _console.print("[yellow]Plan rejected. Refine the task description and try again.[/yellow]")
        return None

    return plan


def execute_plan(plan: "Plan", task: str, config) -> str:  # pragma: no cover
    """Execute an approved plan step-by-step, running each step through a SubAgent.

    Returns a summary string of all step outcomes.
    """
    from .agent import SubAgent

    results: list[str] = []
    for step in plan.steps:
        if step.status == "skipped":
            results.append(f"⏭\u202f Step {step.id} skipped: {step.title}")
            continue

        step.status = "in_progress"
        save_plan(plan)

        agent_prompt = (
            f"You are the {step.agent} agent working on a multi-step plan.\n"
            f"Overall goal: {task}\n"
            f"Your step ({step.id}/{len(plan.steps)}): {step.title}\n\n"
            f"{step.description}"
        )

        try:
            agent = SubAgent(config, agent_prompt)
            result = agent.run()
            step.status = "done"
            results.append(f"✅ Step {step.id}: {step.title}\n   {result[:300]}")
        except Exception as exc:
            step.status = "error"
            results.append(f"❌ Step {step.id}: {step.title}\n   Error: {exc}")

        save_plan(plan)

    return "\n\n".join(results) + f"\n\n**{plan.summary()}**"


# ------------------------------------------------------------------ #
#  Legacy shim — keep old callers working
# ------------------------------------------------------------------ #

def create_plan_file(name: str, content: str) -> str:
    """Write raw content to a plan file (legacy, no AI decomposition)."""
    path = _plan_path(name)
    path.write_text(f"# Plan: {name}\n\n{content}", encoding="utf-8")
    return str(path)


def get_plans_dir() -> str:
    return str(_plans_dir())
