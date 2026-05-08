"""Tests for luckyd_code.planner — plan data model and storage."""

from pathlib import Path

import pytest

from luckyd_code.planner import (
    Plan,
    PlanStep,
    save_plan,
    load_plan,
    list_plans,
    read_plan,
    delete_plan,
    update_step_status,
    create_plan_file,
    get_plans_dir,
)


class TestPlanStep:
    """Tests for the PlanStep dataclass."""

    def test_default_values(self):
        """PlanStep should have sensible defaults."""
        step = PlanStep(id=1, title="Test", description="Do a thing", agent="coder")
        assert step.id == 1
        assert step.title == "Test"
        assert step.description == "Do a thing"
        assert step.agent == "coder"
        assert step.depends_on == []
        assert step.estimated_minutes == 5
        assert step.status == "pending"

    def test_depends_on_defaults_to_empty_list(self):
        """Each step gets its own depends_on list."""
        s1 = PlanStep(id=1, title="A", description="", agent="coder")
        s2 = PlanStep(id=2, title="B", description="", agent="coder")
        s1.depends_on.append(1)
        assert s2.depends_on == []

    def test_status_transitions(self):
        """Status can be changed to valid values."""
        step = PlanStep(id=1, title="A", description="", agent="coder")
        assert step.status == "pending"
        step.status = "in_progress"
        assert step.status == "in_progress"
        step.status = "done"
        assert step.status == "done"
        step.status = "skipped"
        assert step.status == "skipped"


class TestPlan:
    """Tests for the Plan dataclass."""

    def test_empty_plan_has_sensible_defaults(self):
        """An empty Plan should have defaults."""
        plan = Plan(name="test", goal="Test goal")
        assert plan.name == "test"
        assert plan.goal == "Test goal"
        assert plan.steps == []
        assert plan.created_at == ""
        assert plan.updated_at == ""

    def test_plan_with_steps(self):
        """Plan should hold steps."""
        steps = [
            PlanStep(id=1, title="A", description="First", agent="researcher"),
            PlanStep(id=2, title="B", description="Second", agent="coder", depends_on=[1]),
        ]
        plan = Plan(name="multi", goal="Do things", steps=steps)
        assert len(plan.steps) == 2
        assert plan.steps[1].depends_on == [1]

    def test_summary_when_empty(self):
        """summary() should report zero progress for empty plan."""
        plan = Plan(name="empty", goal="Nothing")
        assert "0/0" in plan.summary()
        assert "0 min" in plan.summary()

    def test_summary_with_done_steps(self):
        """summary() should count done steps and estimate time."""
        steps = [
            PlanStep(id=1, title="A", description="", agent="coder", status="done", estimated_minutes=10),
            PlanStep(id=2, title="B", description="", agent="coder", status="pending", estimated_minutes=20),
        ]
        plan = Plan(name="half", goal="Half done", steps=steps)
        summary = plan.summary()
        assert "1/2" in summary
        assert "30 min" in summary

    def test_to_markdown(self):
        """to_markdown() should produce readable markdown."""
        steps = [PlanStep(id=1, title="Setup", description="Set up the environment", agent="researcher")]
        plan = Plan(name="markdown-test", goal="Test MD", steps=steps, created_at="2026-01-01T00:00:00")
        md = plan.to_markdown()
        assert "# Plan: markdown-test" in md
        assert "**Goal:** Test MD" in md
        assert "Step 1: Setup" in md
        assert "Set up the environment" in md
        assert "**Agent:** `researcher`" in md
        assert "2026-01-01" in md

    def test_to_markdown_shows_dependencies(self):
        """to_markdown() should show depends_on in the output."""
        step = PlanStep(id=2, title="Dep Step", description="", agent="coder", depends_on=[1])
        plan = Plan(name="dep", goal="Dependency test", steps=[step])
        md = plan.to_markdown()
        assert "after steps [1]" in md


class TestPlanStorage:
    """Tests for plan persistence functions."""

    @pytest.fixture(autouse=True)
    def patch_plans_dir(self, monkeypatch, temp_dir):
        """Redirect plans dir to a temp location."""
        plans_dir = temp_dir / ".deepseek-code" / "plans"
        plans_dir.mkdir(parents=True)

        monkeypatch.setattr("luckyd_code.planner._plans_dir", lambda: plans_dir)
        monkeypatch.setattr("luckyd_code.planner._plan_path", lambda name: plans_dir / f"{name}.md")
        monkeypatch.setattr(
            "luckyd_code.planner._plan_json_path",
            lambda name: plans_dir / f"{name}.json",
        )
        yield plans_dir

    def test_save_and_load_plan(self, patch_plans_dir):
        """save_plan() and load_plan() should round-trip."""
        steps = [
            PlanStep(id=1, title="Research", description="Investigate", agent="researcher"),
        ]
        plan = Plan(name="test-plan", goal="Do research", steps=steps)

        path = save_plan(plan)
        assert Path(path).exists()

        loaded = load_plan("test-plan")
        assert loaded is not None
        assert loaded.name == "test-plan"
        assert loaded.goal == "Do research"
        assert len(loaded.steps) == 1
        assert loaded.steps[0].id == 1
        assert loaded.steps[0].title == "Research"
        assert loaded.steps[0].agent == "researcher"

    def test_save_plan_sets_timestamps(self, patch_plans_dir):
        """save_plan should set created_at and updated_at if empty."""
        plan = Plan(name="time-test", goal="Test timestamps")
        _ = save_plan(plan)
        assert plan.created_at != ""
        assert plan.updated_at != ""

    def test_load_nonexistent_plan_returns_none(self, patch_plans_dir):
        """load_plan on a nonexistent plan returns None."""
        assert load_plan("nonexistent") is None

    def test_writes_both_md_and_json(self, patch_plans_dir):
        """save_plan should write both .md and .json files."""
        plan = Plan(name="dual", goal="Test dual files")
        save_plan(plan)

        assert (patch_plans_dir / "dual.md").exists()
        assert (patch_plans_dir / "dual.json").exists()

    def test_read_plan_returns_markdown(self, patch_plans_dir):
        """read_plan should return markdown string."""
        plan = Plan(name="read-test", goal="Readable")
        save_plan(plan)
        md = read_plan("read-test")
        assert "# Plan: read-test" in md

    def test_read_missing_plan(self, patch_plans_dir):
        """read_plan on missing plan returns error message."""
        result = read_plan("missing")
        assert "not found" in result.lower()

    def test_list_plans_with_no_plans(self, patch_plans_dir):
        """list_plans() when empty should return appropriate message."""
        result = list_plans()
        assert "No plans" in result or "no plans" in result.lower()

    def test_list_plans_with_plans(self, patch_plans_dir):
        """list_plans() should list saved plans."""
        save_plan(Plan(name="alpha", goal="First"))
        save_plan(Plan(name="beta", goal="Second"))
        result = list_plans()
        assert "alpha" in result
        assert "beta" in result

    def test_delete_plan(self, patch_plans_dir):
        """delete_plan() should remove both .md and .json files."""
        plan = Plan(name="deleteme", goal="To delete")
        save_plan(plan)
        assert (patch_plans_dir / "deleteme.md").exists()
        assert (patch_plans_dir / "deleteme.json").exists()

        result = delete_plan("deleteme")
        assert "Deleted" in result
        assert not (patch_plans_dir / "deleteme.md").exists()
        assert not (patch_plans_dir / "deleteme.json").exists()

    def test_delete_nonexistent_plan(self, patch_plans_dir):
        """delete_plan on nonexistent returns not-found message."""
        result = delete_plan("ghost")
        assert "not found" in result.lower()

    def test_update_step_status(self, patch_plans_dir):
        """update_step_status should change status and re-save."""
        steps = [PlanStep(id=1, title="S1", description="", agent="coder")]
        plan = Plan(name="status-test", goal="Test", steps=steps)
        save_plan(plan)

        result = update_step_status("status-test", 1, "done")
        assert "marked as 'done'" in result

        reloaded = load_plan("status-test")
        assert reloaded.steps[0].status == "done"

    def test_update_step_invalid_status(self, patch_plans_dir):
        """update_step_status with invalid status should return error."""
        plan = Plan(name="invalid-status", goal="Test",
                     steps=[PlanStep(id=1, title="S1", description="", agent="coder")])
        save_plan(plan)
        result = update_step_status("invalid-status", 1, "unknown")
        assert "Invalid status" in result

    def test_update_step_missing_plan(self, patch_plans_dir):
        """update_step_status on missing plan returns error."""
        result = update_step_status("ghost-plan", 1, "done")
        assert "not found" in result.lower()

    def test_update_step_missing_step_id(self, patch_plans_dir):
        """update_step_status with wrong step id returns error."""
        plan = Plan(name="missing-step", goal="Test",
                     steps=[PlanStep(id=1, title="S1", description="", agent="coder")])
        save_plan(plan)
        result = update_step_status("missing-step", 999, "done")
        assert "not found" in result.lower()

    def test_create_plan_file_legacy(self, patch_plans_dir):
        """create_plan_file (legacy) should write raw content."""
        _ = create_plan_file("legacy-plan", "Some content")
        assert (patch_plans_dir / "legacy-plan.md").exists()
        content = (patch_plans_dir / "legacy-plan.md").read_text()
        assert "# Plan: legacy-plan" in content
        assert "Some content" in content

    def test_get_plans_dir_returns_string(self, patch_plans_dir):
        """get_plans_dir() returns a string path."""
        result = get_plans_dir()
        assert isinstance(result, str)
        assert "plans" in result
