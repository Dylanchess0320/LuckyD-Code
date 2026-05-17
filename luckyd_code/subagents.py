"""Named subagent registry — YAML-configured specialist agents.

Agent definitions live in  ``.luckyd-code/agents/<name>.yaml``.
Each YAML file may contain::

    name: code_reviewer
    description: Reviews diffs and gives structured feedback
    model: deepseek-v4-flash        # optional, overrides global model
    system_prompt: |
        You are an expert code reviewer ...
    max_turns: 8                    # optional, default 6
    tools: [read, write, grep]      # optional, defaults to all tools

Up to ``MAX_PARALLEL`` agents can run simultaneously (default 10).

Typical usage::

    registry = SubagentRegistry(project_root=".")
    runner   = SubagentRunner(registry, global_config)

    # Single agent
    result = runner.run_one("code_reviewer", "Review PR #42")

    # Parallel batch
    results = runner.run_parallel([
        ("researcher",    "Investigate the bug in agent.py"),
        ("code_reviewer", "Review the last commit"),
    ])
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from pathlib import Path

from .context import ConversationContext
from ._agent_loop import run_agent_loop
from .tools import get_default_registry

_log = logging.getLogger(__name__)

MAX_PARALLEL: int = 10
_CONFIG_ROOT: str = ".luckyd-code"
_AGENTS_DIR_NAME: str = "agents"


# ------------------------------------------------------------------ #
#  Data model
# ------------------------------------------------------------------ #

@dataclass
class SubagentConfig:
    """Configuration for one named subagent, loaded from a YAML file."""
    name: str
    description: str = ""
    model: str = ""           # empty → use global model
    system_prompt: str = ""
    max_turns: int = 6
    tools: list[str] = field(default_factory=list)  # empty → all tools

    @classmethod
    def from_dict(cls, data: dict) -> "SubagentConfig":
        """Build a SubagentConfig from a raw YAML-parsed dict."""
        return cls(
            name=str(data.get("name", "unnamed")),
            description=str(data.get("description", "")),
            model=str(data.get("model", "")),
            system_prompt=str(data.get("system_prompt", "")),
            max_turns=int(data.get("max_turns", 6)),
            tools=list(data.get("tools", [])),
        )

    def to_dict(self) -> dict:
        """Serialize to a plain dict (round-trips through YAML)."""
        return {
            "name": self.name,
            "description": self.description,
            "model": self.model,
            "system_prompt": self.system_prompt,
            "max_turns": self.max_turns,
            "tools": self.tools,
        }


@dataclass
class SubagentResult:
    """Output from running one subagent."""
    name: str
    output: str
    error: str | None = None
    success: bool = True


# ------------------------------------------------------------------ #
#  Registry
# ------------------------------------------------------------------ #

class SubagentRegistry:
    """Loads and stores SubagentConfig instances from YAML files.

    Scans ``<project_root>/.luckyd-code/agents/*.yaml`` on first access.
    Call :meth:`reload` to pick up new files at runtime.
    """

    def __init__(self, project_root: str | None = None):
        self._root = Path(project_root or ".").resolve()
        self._agents_dir: Path = self._root / _CONFIG_ROOT / _AGENTS_DIR_NAME
        self._registry: dict[str, SubagentConfig] = {}
        self._loaded: bool = False

    # ------------------------------------------------------------------ #
    #  Loading
    # ------------------------------------------------------------------ #

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.reload()

    def reload(self) -> int:
        """Scan the agents directory and re-load all YAML definitions.

        Silently skips malformed files.  Returns the number of agents loaded.
        """
        self._registry.clear()
        self._loaded = True

        if not self._agents_dir.exists():
            return 0

        count = 0
        for yaml_file in sorted(self._agents_dir.glob("*.yaml")):
            try:
                import yaml as _yaml
                data = _yaml.safe_load(yaml_file.read_text(encoding="utf-8")) or {}
                if "name" not in data:
                    data["name"] = yaml_file.stem
                cfg = SubagentConfig.from_dict(data)
                self._registry[cfg.name] = cfg
                count += 1
            except Exception as exc:
                _log.warning("Skipping bad agent YAML %s: %s", yaml_file.name, exc)

        _log.debug("SubagentRegistry: loaded %d agents from %s", count, self._agents_dir)
        return count

    # ------------------------------------------------------------------ #
    #  CRUD
    # ------------------------------------------------------------------ #

    def get(self, name: str) -> SubagentConfig | None:
        """Return a named agent or None if not registered."""
        self._ensure_loaded()
        return self._registry.get(name)

    def list_agents(self) -> list[SubagentConfig]:
        """All registered agents, sorted by name."""
        self._ensure_loaded()
        return sorted(self._registry.values(), key=lambda a: a.name)

    def register(self, config: SubagentConfig) -> None:
        """Register an agent in memory without writing YAML."""
        self._registry[config.name] = config
        self._loaded = True

    def save_agent(self, config: SubagentConfig) -> Path:
        """Persist a SubagentConfig as a YAML file and register it.

        Creates the agents directory if it does not exist.
        """
        import yaml as _yaml

        self._agents_dir.mkdir(parents=True, exist_ok=True)
        path = self._agents_dir / f"{config.name}.yaml"
        path.write_text(
            _yaml.dump(config.to_dict(), sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        self._registry[config.name] = config
        self._loaded = True
        return path

    def delete_agent(self, name: str) -> bool:
        """Delete an agent's YAML file and remove it from the registry.

        Returns True if a file was deleted, False if the agent was unknown.
        """
        path = self._agents_dir / f"{name}.yaml"
        removed = False
        if path.exists():
            path.unlink()
            removed = True
        self._registry.pop(name, None)
        return removed

    def __len__(self) -> int:
        self._ensure_loaded()
        return len(self._registry)

    def __contains__(self, name: object) -> bool:
        self._ensure_loaded()
        return name in self._registry


# ------------------------------------------------------------------ #
#  Runner
# ------------------------------------------------------------------ #

class SubagentRunner:
    """Runs one or more named subagents against tasks.

    Agents can run sequentially or in parallel (up to ``MAX_PARALLEL``
    threads — each thread makes its own API call so there is no GIL
    contention on the hot path).
    """

    def __init__(self, registry: SubagentRegistry, global_config):
        self.registry = registry
        self.global_config = global_config

    # ------------------------------------------------------------------ #
    #  Single agent
    # ------------------------------------------------------------------ #

    def run_one(self, agent_name: str, task: str) -> SubagentResult:
        """Run a single named subagent on *task*.

        Falls back to a default config if the agent is not in the registry
        rather than raising, so callers never get an unexpected exception.
        """
        cfg = self.registry.get(agent_name)
        if cfg is None:
            _log.warning("Subagent '%s' not registered — using defaults", agent_name)
            cfg = SubagentConfig(name=agent_name)

        model = cfg.model or getattr(self.global_config, "model", "")
        system = cfg.system_prompt or getattr(self.global_config, "system_prompt", "")

        try:
            ctx = ConversationContext(
                system_prompt=system,
                max_messages=cfg.max_turns * 2 + 4,
                config=self.global_config,
                model=model,
            )
            ctx.add_user_message(task)

            tool_registry = get_default_registry()
            output = run_agent_loop(
                context=ctx,
                config=self.global_config,
                tools=tool_registry.list_tools(),
                registry=tool_registry,
                max_turns=cfg.max_turns,
                label=agent_name,
            )
            return SubagentResult(name=agent_name, output=output or "", success=True)

        except Exception as exc:
            _log.error("Subagent '%s' failed: %s", agent_name, exc)
            return SubagentResult(
                name=agent_name, output="", error=str(exc), success=False
            )

    # ------------------------------------------------------------------ #
    #  Parallel batch
    # ------------------------------------------------------------------ #

    def run_parallel(
        self,
        tasks: list[tuple[str, str]],
        max_workers: int | None = None,
    ) -> list[SubagentResult]:
        """Run multiple agents concurrently.

        Args:
            tasks:       ``[(agent_name, task_text), ...]``
            max_workers: Thread pool size; capped at :data:`MAX_PARALLEL`.

        Returns results in the *same order* as *tasks* (not completion order).
        """
        if not tasks:
            return []

        workers = min(len(tasks), max_workers or MAX_PARALLEL, MAX_PARALLEL)
        results_map: dict[int, SubagentResult] = {}

        with ThreadPoolExecutor(max_workers=workers) as pool:
            future_to_idx = {
                pool.submit(self.run_one, name, task_text): idx
                for idx, (name, task_text) in enumerate(tasks)
            }
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    results_map[idx] = future.result()
                except Exception as exc:
                    name = tasks[idx][0]
                    results_map[idx] = SubagentResult(
                        name=name, output="", error=str(exc), success=False
                    )

        return [results_map[i] for i in range(len(tasks))]

    # ------------------------------------------------------------------ #
    #  Sequential batch (for dependent tasks)
    # ------------------------------------------------------------------ #

    def run_sequential(
        self, tasks: list[tuple[str, str]]
    ) -> list[SubagentResult]:
        """Run agents one at a time in order (safe for dependent steps)."""
        return [self.run_one(name, task_text) for name, task_text in tasks]

    # ------------------------------------------------------------------ #
    #  Convenience: run a named pipeline defined in the registry
    # ------------------------------------------------------------------ #

    def describe(self) -> str:
        """Return a human-readable summary of all registered agents."""
        agents = self.registry.list_agents()
        if not agents:
            return "No subagents registered. Add YAML files to .luckyd-code/agents/"
        lines = [f"Registered subagents ({len(agents)}):"]
        for a in agents:
            model_tag = f" [{a.model}]" if a.model else ""
            lines.append(f"  • {a.name}{model_tag}: {a.description or '(no description)'}")
        return "\n".join(lines)
