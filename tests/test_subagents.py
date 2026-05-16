"""Tests for luckyd_code.subagents — named subagent registry and runner."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from luckyd_code.subagents import (
    MAX_PARALLEL,
    SubagentConfig,
    SubagentRegistry,
    SubagentResult,
    SubagentRunner,
)


# ------------------------------------------------------------------ #
#  Helpers
# ------------------------------------------------------------------ #

def _write_agent_yaml(agents_dir: Path, name: str, **kwargs) -> Path:
    """Write a minimal agent YAML to *agents_dir*."""
    data = {"name": name, "description": f"{name} description", **kwargs}
    path = agents_dir / f"{name}.yaml"
    path.write_text(yaml.dump(data), encoding="utf-8")
    return path


def _make_registry(tmp_path: Path, agents: list[dict] | None = None) -> SubagentRegistry:
    agents_dir = tmp_path / ".luckyd-code" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    for agent in (agents or []):
        _write_agent_yaml(agents_dir, **agent)
    return SubagentRegistry(project_root=str(tmp_path))


# ------------------------------------------------------------------ #
#  SubagentConfig
# ------------------------------------------------------------------ #

class TestSubagentConfig:
    def test_defaults(self):
        cfg = SubagentConfig(name="tester")
        assert cfg.description == ""
        assert cfg.model == ""
        assert cfg.system_prompt == ""
        assert cfg.max_turns == 6
        assert cfg.tools == []

    def test_from_dict_full(self):
        data = {
            "name": "reviewer",
            "description": "Reviews code",
            "model": "deepseek-v4-flash",
            "system_prompt": "You are a reviewer.",
            "max_turns": 10,
            "tools": ["read", "grep"],
        }
        cfg = SubagentConfig.from_dict(data)
        assert cfg.name == "reviewer"
        assert cfg.description == "Reviews code"
        assert cfg.model == "deepseek-v4-flash"
        assert cfg.max_turns == 10
        assert cfg.tools == ["read", "grep"]

    def test_from_dict_missing_fields_use_defaults(self):
        cfg = SubagentConfig.from_dict({"name": "minimal"})
        assert cfg.model == ""
        assert cfg.max_turns == 6
        assert cfg.tools == []

    def test_to_dict_round_trip(self):
        original = SubagentConfig(
            name="agent_x",
            description="desc",
            model="opus",
            system_prompt="do stuff",
            max_turns=8,
            tools=["bash"],
        )
        d = original.to_dict()
        restored = SubagentConfig.from_dict(d)
        assert restored.name == original.name
        assert restored.model == original.model
        assert restored.max_turns == original.max_turns
        assert restored.tools == original.tools

    def test_mutable_default_isolation(self):
        a = SubagentConfig(name="a")
        b = SubagentConfig(name="b")
        a.tools.append("read")
        assert b.tools == []


# ------------------------------------------------------------------ #
#  SubagentResult
# ------------------------------------------------------------------ #

class TestSubagentResult:
    def test_success_defaults(self):
        r = SubagentResult(name="coder", output="done")
        assert r.success is True
        assert r.error is None

    def test_failure(self):
        r = SubagentResult(name="coder", output="", error="timeout", success=False)
        assert r.success is False
        assert r.error == "timeout"


# ------------------------------------------------------------------ #
#  SubagentRegistry — loading
# ------------------------------------------------------------------ #

class TestSubagentRegistryLoad:
    def test_empty_dir_returns_zero(self, tmp_path):
        reg = _make_registry(tmp_path, agents=[])
        count = reg.reload()
        assert count == 0
        assert len(reg) == 0

    def test_loads_single_agent(self, tmp_path):
        reg = _make_registry(tmp_path, agents=[{"name": "helper"}])
        assert len(reg) == 1
        cfg = reg.get("helper")
        assert cfg is not None
        assert cfg.name == "helper"

    def test_loads_multiple_agents(self, tmp_path):
        agents = [{"name": f"agent_{i}"} for i in range(5)]
        reg = _make_registry(tmp_path, agents=agents)
        assert len(reg) == 5

    def test_name_falls_back_to_stem_when_missing(self, tmp_path):
        agents_dir = tmp_path / ".luckyd-code" / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)
        # YAML without a 'name' key
        (agents_dir / "my_agent.yaml").write_text(
            yaml.dump({"description": "no name in yaml"}), encoding="utf-8"
        )
        reg = SubagentRegistry(project_root=str(tmp_path))
        assert len(reg) == 1
        assert reg.get("my_agent") is not None

    def test_bad_yaml_skipped(self, tmp_path):
        agents_dir = tmp_path / ".luckyd-code" / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)
        (agents_dir / "broken.yaml").write_text("{ bad yaml: [unclosed", encoding="utf-8")
        (agents_dir / "good.yaml").write_text(yaml.dump({"name": "good"}), encoding="utf-8")
        reg = SubagentRegistry(project_root=str(tmp_path))
        # Only the good one loaded
        assert len(reg) == 1

    def test_no_agents_dir_returns_zero(self, tmp_path):
        # No .luckyd-code/agents directory at all
        reg = SubagentRegistry(project_root=str(tmp_path))
        assert len(reg) == 0

    def test_reload_refreshes_registry(self, tmp_path):
        agents_dir = tmp_path / ".luckyd-code" / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)
        reg = SubagentRegistry(project_root=str(tmp_path))
        assert len(reg) == 0
        # Add an agent and reload
        _write_agent_yaml(agents_dir, "new_agent")
        count = reg.reload()
        assert count == 1
        assert len(reg) == 1

    def test_list_agents_sorted_by_name(self, tmp_path):
        agents = [{"name": "zzz"}, {"name": "aaa"}, {"name": "mmm"}]
        reg = _make_registry(tmp_path, agents=agents)
        names = [a.name for a in reg.list_agents()]
        assert names == sorted(names)

    def test_contains_check(self, tmp_path):
        reg = _make_registry(tmp_path, agents=[{"name": "known"}])
        assert "known" in reg
        assert "unknown" not in reg


# ------------------------------------------------------------------ #
#  SubagentRegistry — CRUD
# ------------------------------------------------------------------ #

class TestSubagentRegistryCRUD:
    def test_register_in_memory(self, tmp_path):
        reg = SubagentRegistry(project_root=str(tmp_path))
        cfg = SubagentConfig(name="in_mem_agent", description="test")
        reg.register(cfg)
        assert reg.get("in_mem_agent") is cfg

    def test_save_agent_writes_yaml(self, tmp_path):
        reg = SubagentRegistry(project_root=str(tmp_path))
        cfg = SubagentConfig(name="writer", description="writes files", max_turns=4)
        path = reg.save_agent(cfg)
        assert path.exists()
        loaded_data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert loaded_data["name"] == "writer"
        assert loaded_data["max_turns"] == 4

    def test_save_and_get_round_trip(self, tmp_path):
        reg = SubagentRegistry(project_root=str(tmp_path))
        cfg = SubagentConfig(name="round_trip", system_prompt="hello world", max_turns=9)
        reg.save_agent(cfg)
        # Fresh registry from same dir
        reg2 = SubagentRegistry(project_root=str(tmp_path))
        loaded = reg2.get("round_trip")
        assert loaded is not None
        assert loaded.system_prompt == "hello world"
        assert loaded.max_turns == 9

    def test_delete_agent_removes_file_and_registry(self, tmp_path):
        reg = _make_registry(tmp_path, agents=[{"name": "to_delete"}])
        result = reg.delete_agent("to_delete")
        assert result is True
        assert reg.get("to_delete") is None
        yaml_path = tmp_path / ".luckyd-code" / "agents" / "to_delete.yaml"
        assert not yaml_path.exists()

    def test_delete_nonexistent_returns_false(self, tmp_path):
        reg = SubagentRegistry(project_root=str(tmp_path))
        assert reg.delete_agent("ghost") is False


# ------------------------------------------------------------------ #
#  SubagentRunner
# ------------------------------------------------------------------ #

def _make_runner(tmp_path: Path, agents: list[dict] | None = None):
    reg = _make_registry(tmp_path, agents)
    cfg = MagicMock()
    cfg.model = "deepseek-v4-flash"
    cfg.system_prompt = "You are a coding assistant."
    return SubagentRunner(reg, cfg), reg


class TestSubagentRunnerRunOne:
    def _mock_agent_loop(self, *args, **kwargs):
        return "Agent output text"

    def test_run_one_success(self, tmp_path):
        runner, _ = _make_runner(tmp_path, [{"name": "coder", "system_prompt": "Code!"}])
        with patch("luckyd_code.subagents.ConversationContext") as MockCtx, \
             patch("luckyd_code.subagents.run_agent_loop", return_value="done"), \
             patch("luckyd_code.subagents.get_default_registry"):
            MockCtx.return_value = MagicMock()
            result = runner.run_one("coder", "Fix the bug")
        assert result.success is True
        assert result.output == "done"
        assert result.name == "coder"

    def test_run_one_unknown_agent_uses_defaults(self, tmp_path):
        runner, _ = _make_runner(tmp_path)
        with patch("luckyd_code.subagents.ConversationContext") as MockCtx, \
             patch("luckyd_code.subagents.run_agent_loop", return_value="fallback"), \
             patch("luckyd_code.subagents.get_default_registry"):
            MockCtx.return_value = MagicMock()
            result = runner.run_one("nonexistent", "some task")
        assert result.success is True
        assert result.name == "nonexistent"

    def test_run_one_exception_returns_failure(self, tmp_path):
        runner, _ = _make_runner(tmp_path)
        with patch("luckyd_code.subagents.ConversationContext", side_effect=RuntimeError("no conn")):
            result = runner.run_one("any_agent", "task")
        assert result.success is False
        assert result.error is not None
        assert "no conn" in result.error

    def test_run_one_uses_agent_model(self, tmp_path):
        runner, _ = _make_runner(tmp_path, [{"name": "opus_agent", "model": "claude-opus"}])
        captured = {}
        def _capture_ctx(*args, **kwargs):
            captured.update(kwargs)
            return MagicMock()
        with patch("luckyd_code.subagents.ConversationContext", side_effect=_capture_ctx), \
             patch("luckyd_code.subagents.run_agent_loop", return_value=""), \
             patch("luckyd_code.subagents.get_default_registry"):
            runner.run_one("opus_agent", "task")
        assert captured.get("model") == "claude-opus"


class TestSubagentRunnerParallel:
    def test_parallel_returns_results_in_order(self, tmp_path):
        runner, _ = _make_runner(tmp_path)
        tasks = [("agent_a", "task A"), ("agent_b", "task B"), ("agent_c", "task C")]
        side_effects = ["output A", "output B", "output C"]

        with patch.object(runner, "run_one", side_effect=[
            SubagentResult(name=t[0], output=o, success=True)
            for t, o in zip(tasks, side_effects)
        ]):
            results = runner.run_parallel(tasks)

        assert len(results) == 3
        for i, (name, _) in enumerate(tasks):
            assert results[i].name == name

    def test_parallel_empty_tasks_returns_empty(self, tmp_path):
        runner, _ = _make_runner(tmp_path)
        results = runner.run_parallel([])
        assert results == []

    def test_parallel_handles_exception(self, tmp_path):
        runner, _ = _make_runner(tmp_path)
        tasks = [("ok_agent", "task")]

        def _run_one_raises(name, task):
            raise RuntimeError("catastrophic")

        with patch.object(runner, "run_one", side_effect=_run_one_raises):
            results = runner.run_parallel(tasks)

        assert len(results) == 1
        assert results[0].success is False

    def test_max_parallel_constant(self):
        assert MAX_PARALLEL == 10


class TestSubagentRunnerSequential:
    def test_sequential_order(self, tmp_path):
        runner, _ = _make_runner(tmp_path)
        call_order = []

        def _track(name, task):
            call_order.append(name)
            return SubagentResult(name=name, output="ok", success=True)

        with patch.object(runner, "run_one", side_effect=_track):
            runner.run_sequential([("first", "t1"), ("second", "t2"), ("third", "t3")])

        assert call_order == ["first", "second", "third"]

    def test_sequential_empty(self, tmp_path):
        runner, _ = _make_runner(tmp_path)
        assert runner.run_sequential([]) == []


class TestSubagentRunnerDescribe:
    def test_describe_no_agents(self, tmp_path):
        runner, _ = _make_runner(tmp_path)
        desc = runner.describe()
        assert "No subagents" in desc

    def test_describe_with_agents(self, tmp_path):
        runner, _ = _make_runner(tmp_path, [
            {"name": "coder", "description": "Writes code"},
            {"name": "reviewer", "description": "Reviews code", "model": "opus"},
        ])
        desc = runner.describe()
        assert "coder" in desc
        assert "reviewer" in desc
        assert "Writes code" in desc
        assert "opus" in desc
