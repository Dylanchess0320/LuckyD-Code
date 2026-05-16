"""Tests for luckyd_code.plan_gate — plan-before-execute gate."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from luckyd_code.plan_gate import (
    GateResult,
    PlanGate,
    auto_plan,
    gate_summary,
    plan_to_prompt_context,
)
from luckyd_code.planner import Plan, PlanStep


# ------------------------------------------------------------------ #
#  Helpers
# ------------------------------------------------------------------ #

def _make_plan(n_steps: int = 3) -> Plan:
    steps = [
        PlanStep(
            id=i + 1,
            title=f"Step {i + 1}",
            description=f"Do thing {i + 1}",
            agent="coder",
            estimated_minutes=10,
        )
        for i in range(n_steps)
    ]
    return Plan(name="test_plan", goal="Fix the bug", steps=steps)


def _make_config() -> MagicMock:
    cfg = MagicMock()
    cfg.api_key = "sk-test"
    cfg.base_url = "https://api.example.com"
    cfg.model = "deepseek-v4-flash"
    return cfg


# ------------------------------------------------------------------ #
#  GateResult
# ------------------------------------------------------------------ #

class TestGateResult:
    def test_approved_fields(self):
        plan = _make_plan()
        r = GateResult(plan=plan, approved=True, reason="ok")
        assert r.approved is True
        assert r.plan is plan
        assert r.reason == "ok"

    def test_rejected_no_plan(self):
        r = GateResult(plan=None, approved=False, reason="user rejected")
        assert r.plan is None
        assert not r.approved


# ------------------------------------------------------------------ #
#  gate_summary
# ------------------------------------------------------------------ #

class TestGateSummary:
    def test_no_plan(self):
        r = GateResult(plan=None, approved=False, reason="failed")
        s = gate_summary(r)
        assert "No plan" in s
        assert "failed" in s

    def test_approved_plan(self):
        plan = _make_plan(4)
        r = GateResult(plan=plan, approved=True, reason="auto-approved (daemon mode)")
        s = gate_summary(r)
        assert "test_plan" in s
        assert "4 steps" in s
        assert "approved" in s
        assert "40 min" in s   # 4 steps * 10 min each

    def test_rejected_plan(self):
        plan = _make_plan(2)
        r = GateResult(plan=plan, approved=False, reason="user said no")
        s = gate_summary(r)
        assert "rejected" in s


# ------------------------------------------------------------------ #
#  plan_to_prompt_context
# ------------------------------------------------------------------ #

class TestPlanToPromptContext:
    def test_empty_when_not_approved(self):
        plan = _make_plan(2)
        r = GateResult(plan=plan, approved=False, reason="no")
        assert plan_to_prompt_context(r) == ""

    def test_empty_when_no_plan(self):
        r = GateResult(plan=None, approved=True, reason="ok")
        assert plan_to_prompt_context(r) == ""

    def test_contains_steps(self):
        plan = _make_plan(3)
        r = GateResult(plan=plan, approved=True, reason="ok")
        ctx = plan_to_prompt_context(r)
        assert "Execution Plan" in ctx
        assert "Fix the bug" in ctx
        for i in range(1, 4):
            assert f"Step {i}" in ctx

    def test_contains_agent_and_estimate(self):
        plan = _make_plan(2)
        r = GateResult(plan=plan, approved=True, reason="ok")
        ctx = plan_to_prompt_context(r)
        assert "coder" in ctx
        assert "10m" in ctx

    def test_empty_steps_list(self):
        plan = Plan(name="empty", goal="nothing", steps=[])
        r = GateResult(plan=plan, approved=True, reason="ok")
        assert plan_to_prompt_context(r) == ""


# ------------------------------------------------------------------ #
#  auto_plan
# ------------------------------------------------------------------ #

class TestAutoPlan:
    def test_success_path(self):
        plan = _make_plan(5)
        cfg = _make_config()
        with patch("luckyd_code.plan_gate.ai_create_plan", return_value=plan), \
             patch("luckyd_code.plan_gate.save_plan"):
            result = auto_plan("Fix bug in agent.py", cfg)
        assert result.approved is True
        assert result.plan is plan
        assert "daemon mode" in result.reason

    def test_caps_steps_at_max(self):
        plan = _make_plan(12)       # 12 steps > default max of 8
        cfg = _make_config()
        with patch("luckyd_code.plan_gate.ai_create_plan", return_value=plan), \
             patch("luckyd_code.plan_gate.save_plan") as mock_save:
            result = auto_plan("Big task", cfg, max_steps=8)
        assert len(result.plan.steps) == 8   # type: ignore[union-attr]
        mock_save.assert_called_once()

    def test_api_failure_returns_rejected(self):
        cfg = _make_config()
        with patch("luckyd_code.plan_gate.ai_create_plan", side_effect=RuntimeError("API down")):
            result = auto_plan("Do something", cfg)
        assert result.approved is False
        assert result.plan is None
        assert "API down" in result.reason

    def test_name_slugified_from_task(self):
        plan = _make_plan(2)
        cfg = _make_config()
        captured = {}
        def _mock_create(name, goal, config):
            captured["name"] = name
            return plan
        with patch("luckyd_code.plan_gate.ai_create_plan", side_effect=_mock_create), \
             patch("luckyd_code.plan_gate.save_plan"):
            auto_plan("Fix: the bug in agent.py!", cfg)
        assert "auto_" in captured["name"]
        # Name must not contain spaces
        assert " " not in captured["name"]


# ------------------------------------------------------------------ #
#  PlanGate
# ------------------------------------------------------------------ #

class TestPlanGate:
    def test_generate_daemon_mode(self):
        plan = _make_plan(3)
        cfg = _make_config()
        with patch("luckyd_code.plan_gate.auto_plan",
                   return_value=GateResult(plan=plan, approved=True, reason="ok")):
            gate = PlanGate("Fix lint issues", cfg, interactive=False)
            result = gate.generate()
        assert result.approved is True
        assert result.plan is plan

    def test_generate_caches_result(self):
        plan = _make_plan(2)
        cfg = _make_config()
        with patch("luckyd_code.plan_gate.auto_plan",
                   return_value=GateResult(plan=plan, approved=True, reason="ok")) as mock_auto:
            gate = PlanGate("task", cfg)
            gate.generate()
            gate.generate()   # second call should NOT re-generate
        assert mock_auto.call_count == 1

    def test_prompt_context_empty_before_generate(self):
        cfg = _make_config()
        gate = PlanGate("task", cfg)
        assert gate.prompt_context() == ""

    def test_prompt_context_after_generate(self):
        plan = _make_plan(3)
        cfg = _make_config()
        with patch("luckyd_code.plan_gate.auto_plan",
                   return_value=GateResult(plan=plan, approved=True, reason="ok")):
            gate = PlanGate("task", cfg)
            gate.generate()
        ctx = gate.prompt_context()
        assert "Execution Plan" in ctx

    def test_task_list_empty_before_generate(self):
        cfg = _make_config()
        gate = PlanGate("task", cfg)
        assert gate.task_list() == []

    def test_task_list_after_generate(self):
        plan = _make_plan(3)
        cfg = _make_config()
        with patch("luckyd_code.plan_gate.auto_plan",
                   return_value=GateResult(plan=plan, approved=True, reason="ok")):
            gate = PlanGate("task", cfg)
            gate.generate()
        items = gate.task_list()
        assert len(items) == 3
        for item in items:
            assert "coder" in item
            assert "Step" in item

    def test_plan_property_none_before_generate(self):
        cfg = _make_config()
        gate = PlanGate("task", cfg)
        assert gate.plan is None

    def test_plan_property_after_generate(self):
        plan = _make_plan(2)
        cfg = _make_config()
        with patch("luckyd_code.plan_gate.auto_plan",
                   return_value=GateResult(plan=plan, approved=True, reason="ok")):
            gate = PlanGate("task", cfg)
            gate.generate()
        assert gate.plan is plan

    def test_approved_property(self):
        plan = _make_plan(2)
        cfg = _make_config()
        with patch("luckyd_code.plan_gate.auto_plan",
                   return_value=GateResult(plan=plan, approved=True, reason="ok")):
            gate = PlanGate("task", cfg)
            assert gate.approved is False   # before generate
            gate.generate()
            assert gate.approved is True

    def test_rejected_gate(self):
        cfg = _make_config()
        with patch("luckyd_code.plan_gate.auto_plan",
                   return_value=GateResult(plan=None, approved=False, reason="fail")):
            gate = PlanGate("task", cfg)
            gate.generate()
        assert gate.approved is False
        assert gate.plan is None
        assert gate.task_list() == []
        assert gate.prompt_context() == ""
