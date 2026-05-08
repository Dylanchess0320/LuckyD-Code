"""Tests for orchestrator.py and agent.py — all API calls mocked."""

from unittest.mock import MagicMock, patch


from luckyd_code.agent import SubAgent
from luckyd_code.orchestrator import (
    AgentHandoff,
    Coordinator,
    ROLE_PROMPTS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(model="deepseek-v4-flash"):
    cfg = MagicMock()
    cfg.model = model
    cfg.api_key = "sk-test"
    cfg.base_url = "https://api.deepseek.com/v1"
    cfg.max_tokens = 1024
    cfg.temperature = 0.7
    cfg.system_prompt = "You are a helpful assistant."
    return cfg


def _done_stream(text="done"):
    """Yields a single 'done' event — no tool calls."""
    yield ("done", (text, ""))


def _text_then_done_stream(text="hello"):
    """Yields a text chunk then done."""
    yield ("text", text)
    yield ("done", (text, ""))


# ---------------------------------------------------------------------------
# ROLE_PROMPTS
# ---------------------------------------------------------------------------

class TestRolePrompts:
    def test_all_four_roles_defined(self):
        assert set(ROLE_PROMPTS.keys()) == {"researcher", "coder", "reviewer", "tester"}

    def test_prompts_are_non_empty_strings(self):
        for role, prompt in ROLE_PROMPTS.items():
            assert isinstance(prompt, str) and len(prompt) > 20, f"{role} prompt too short"


# ---------------------------------------------------------------------------
# SubAgent
# ---------------------------------------------------------------------------

class TestSubAgent:
    def test_init_sets_task(self):
        cfg = _make_config()
        agent = SubAgent(cfg, "write a sort function")
        assert agent.task == "write a sort function"

    def test_run_returns_text_on_done(self):
        cfg = _make_config()
        agent = SubAgent(cfg, "explain recursion")

        with patch("luckyd_code._agent_loop.stream_chat") as mock_stream:
            mock_stream.return_value = _done_stream("Recursion is self-reference.")
            result = agent.run()

        assert result == "Recursion is self-reference."

    def test_run_returns_no_response_when_empty(self):
        cfg = _make_config()
        agent = SubAgent(cfg, "do nothing")

        with patch("luckyd_code._agent_loop.stream_chat") as mock_stream:
            mock_stream.return_value = _done_stream("")
            result = agent.run()

        assert result == "(sub-agent: no response)"

    def test_run_handles_api_error(self):
        cfg = _make_config()
        agent = SubAgent(cfg, "task")

        def _error_stream(*args, **kwargs):
            yield ("error", "API unavailable")

        with patch("luckyd_code._agent_loop.stream_chat") as mock_stream:
            mock_stream.return_value = _error_stream()
            result = agent.run()

        assert "[sub-agent] Error" in result
        assert "API unavailable" in result

    def test_run_executes_tool_call_then_continues(self):
        cfg = _make_config()
        agent = SubAgent(cfg, "read a file")
        call_count = [0]

        def _stream(*args, **kwargs):
            if call_count[0] == 0:
                call_count[0] += 1
                yield ("tool_calls", (
                    [{"id": "tc1", "type": "function",
                      "function": {"name": "Read", "arguments": '{"path": "main.py"}'}}],
                    "",
                ))
            else:
                yield ("done", ("File contents processed.", ""))

        with patch("luckyd_code._agent_loop.stream_chat") as mock_stream:
            mock_stream.side_effect = _stream
            with patch.object(agent.registry, "execute", return_value="# main.py content"):
                result = agent.run()

        assert result == "File contents processed."

    def test_run_handles_invalid_json_tool_args(self):
        cfg = _make_config()
        agent = SubAgent(cfg, "task")
        call_count = [0]

        def _stream(*args, **kwargs):
            if call_count[0] == 0:
                call_count[0] += 1
                yield ("tool_calls", (
                    [{"id": "tc1", "type": "function",
                      "function": {"name": "Read", "arguments": "NOT JSON {"}}],
                    "",
                ))
            else:
                yield ("done", ("recovered", ""))

        with patch("luckyd_code._agent_loop.stream_chat") as mock_stream:
            mock_stream.side_effect = _stream
            result = agent.run()

        assert isinstance(result, str)

    def test_run_respects_max_turns(self):
        """Agent should stop after max_turns even if tool calls keep coming."""
        cfg = _make_config()
        agent = SubAgent(cfg, "infinite tools")

        def _always_tool(*args, **kwargs):
            yield ("tool_calls", (
                [{"id": "tc1", "type": "function",
                  "function": {"name": "Read", "arguments": '{"path": "x.py"}'}}],
                "",
            ))

        with patch("luckyd_code._agent_loop.stream_chat") as mock_stream:
            mock_stream.side_effect = _always_tool
            with patch.object(agent.registry, "execute", return_value="content"):
                result = agent.run()

        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# AgentHandoff
# ---------------------------------------------------------------------------

class TestAgentHandoff:
    def test_unknown_role_returns_error(self):
        cfg = _make_config()
        handoff = AgentHandoff(cfg)
        result = handoff.handoff("wizard", "cast a spell")
        assert "unknown role" in result.lower()
        assert "wizard" in result

    def test_known_roles_accepted(self):
        cfg = _make_config()
        handoff = AgentHandoff(cfg)

        for role in ("researcher", "coder", "reviewer", "tester"):
            with patch("luckyd_code._agent_loop.stream_chat") as mock_stream:
                mock_stream.return_value = _done_stream(f"{role} done")
                result = handoff.handoff(role, "some task")
            assert isinstance(result, str) and len(result) > 0

    def test_role_case_insensitive(self):
        cfg = _make_config()
        handoff = AgentHandoff(cfg)

        with patch("luckyd_code._agent_loop.stream_chat") as mock_stream:
            mock_stream.return_value = _done_stream("ok")
            result = handoff.handoff("RESEARCHER", "task")

        assert "unknown role" not in result.lower()

    def test_handoff_returns_text_response(self):
        cfg = _make_config()
        handoff = AgentHandoff(cfg)

        with patch("luckyd_code._agent_loop.stream_chat") as mock_stream:
            mock_stream.return_value = _done_stream("Research complete: found 3 files.")
            result = handoff.handoff("researcher", "find config files")

        assert result == "Research complete: found 3 files."

    def test_handoff_handles_api_error(self):
        cfg = _make_config()
        handoff = AgentHandoff(cfg)

        def _err(*args, **kwargs):
            yield ("error", "timeout")

        with patch("luckyd_code._agent_loop.stream_chat") as mock_stream:
            mock_stream.return_value = _err()
            result = handoff.handoff("coder", "write something")

        assert "Error" in result

    def test_handoff_executes_tool_and_continues(self):
        cfg = _make_config()
        handoff = AgentHandoff(cfg)
        call_count = [0]

        def _stream(*args, **kwargs):
            if call_count[0] == 0:
                call_count[0] += 1
                yield ("tool_calls", (
                    [{"id": "tc1", "type": "function",
                      "function": {"name": "Glob", "arguments": '{"pattern": "*.py"}'}}],
                    "",
                ))
            else:
                yield ("done", ("Found files.", ""))

        with patch("luckyd_code._agent_loop.stream_chat") as mock_stream:
            mock_stream.side_effect = _stream
            with patch("luckyd_code.orchestrator.get_default_registry") as mock_reg:
                mock_registry = MagicMock()
                mock_registry.list_tools.return_value = []
                mock_registry.execute.return_value = "['a.py', 'b.py']"
                mock_reg.return_value = mock_registry
                result = handoff.handoff("researcher", "find python files")

        assert result == "Found files."

    def test_handoff_no_response_fallback(self):
        cfg = _make_config()
        handoff = AgentHandoff(cfg)

        with patch("luckyd_code._agent_loop.stream_chat") as mock_stream:
            mock_stream.return_value = _done_stream("")
            result = handoff.handoff("reviewer", "review code")

        assert "no response" in result.lower()


# ---------------------------------------------------------------------------
# Coordinator
# ---------------------------------------------------------------------------

class TestCoordinator:
    def _patched_handoff(self, responses: dict):
        def _handoff(role, task, tools=None):
            return responses.get(role, f"({role} done)")
        return _handoff

    def test_orchestrate_default_roles(self):
        cfg = _make_config()
        coord = Coordinator(cfg)

        responses = {
            "researcher": "Found relevant files.",
            "coder": "Implemented the feature.",
            "reviewer": "LGTM.",
        }
        with patch.object(coord.handoff, "handoff", side_effect=self._patched_handoff(responses)):
            report = coord.orchestrate("add logging to the app")

        assert "Research Findings" in report
        assert "Implementation" in report
        assert "Review Feedback" in report

    def test_orchestrate_custom_roles(self):
        cfg = _make_config()
        coord = Coordinator(cfg)

        with patch.object(coord.handoff, "handoff", return_value="done") as mock_h:
            coord.orchestrate("task", roles=["coder"])

        called_roles = [c.args[0] for c in mock_h.call_args_list]
        assert "coder" in called_roles
        assert "researcher" not in called_roles

    def test_orchestrate_researcher_only(self):
        cfg = _make_config()
        coord = Coordinator(cfg)

        with patch.object(coord.handoff, "handoff", return_value="findings"):
            report = coord.orchestrate("research task", roles=["researcher"])

        assert "Research Findings" in report
        assert "findings" in report

    def test_orchestrate_parallel_researcher_tester(self):
        cfg = _make_config()
        coord = Coordinator(cfg)

        responses = {
            "researcher": "Research done.",
            "tester": "Tests planned.",
            "coder": "Code written.",
            "reviewer": "Reviewed.",
        }
        with patch.object(coord.handoff, "handoff", side_effect=self._patched_handoff(responses)):
            report = coord.orchestrate("big task", roles=["researcher", "tester", "coder", "reviewer"])

        assert "Research Findings" in report
        assert "Test Plan" in report
        assert "Implementation" in report
        assert "Review Feedback" in report

    def test_orchestrate_coder_receives_research_context(self):
        cfg = _make_config()
        coord = Coordinator(cfg)
        captured = {}

        def _handoff(role, task, tools=None):
            captured[role] = task
            return f"{role} done"

        with patch.object(coord.handoff, "handoff", side_effect=_handoff):
            coord.orchestrate("implement search", roles=["researcher", "coder"])

        assert "researcher done" in captured["coder"]

    def test_orchestrate_review_skipped_without_implementation(self):
        cfg = _make_config()
        coord = Coordinator(cfg)

        with patch.object(coord.handoff, "handoff", return_value="done") as mock_h:
            coord.orchestrate("task", roles=["researcher", "reviewer"])

        called_roles = [c.args[0] for c in mock_h.call_args_list]
        assert "reviewer" not in called_roles

    def test_orchestrate_returns_string(self):
        cfg = _make_config()
        coord = Coordinator(cfg)

        with patch.object(coord.handoff, "handoff", return_value="ok"):
            result = coord.orchestrate("do something")

        assert isinstance(result, str) and len(result) > 0

    def test_parallel_orchestrate_runs_all_subtasks(self):
        cfg = _make_config()
        coord = Coordinator(cfg)

        subtasks = [("researcher", "find files"), ("tester", "check tests")]

        with patch.object(coord.handoff, "handoff", return_value="done") as mock_h:
            report = coord.parallel_orchestrate("big task", subtasks)

        assert mock_h.call_count == 2
        assert "Parallel Orchestration" in report

    def test_parallel_orchestrate_handles_agent_error(self):
        cfg = _make_config()
        coord = Coordinator(cfg)

        def _handoff(role, task, tools=None):
            if role == "researcher":
                raise RuntimeError("network failure")
            return "done"

        subtasks = [("researcher", "find stuff"), ("coder", "write code")]

        with patch.object(coord.handoff, "handoff", side_effect=_handoff):
            report = coord.parallel_orchestrate("task", subtasks)

        assert isinstance(report, str)
        assert "Error" in report or "Researcher" in report


# ---------------------------------------------------------------------------
# Import guard — stream_chat must be importable from orchestrator
# ---------------------------------------------------------------------------

class TestOrchestratorImports:
    def test_stream_chat_importable(self):
        """Regression test for the v1.1.0 NameError crash."""
        from luckyd_code._agent_loop import stream_chat  # noqa: F401
        assert callable(stream_chat)

    def test_repair_json_importable(self):
        from luckyd_code._agent_loop import _repair_json  # noqa: F401
        assert callable(_repair_json)
