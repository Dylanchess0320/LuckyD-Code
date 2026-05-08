"""Tests for the tool registry."""

import pytest

from luckyd_code.tools.registry import Tool, ToolRegistry


class TestTool:
    def test_tool_base_has_required_attrs(self):
        """Tool base class should have all required attributes."""
        t = Tool()
        assert hasattr(t, "name")
        assert hasattr(t, "description")
        assert hasattr(t, "parameters")
        assert hasattr(t, "permission_risk")
        assert hasattr(t, "run")

    def test_run_raises_not_implemented(self):
        """Tool.run should raise NotImplementedError."""
        t = Tool()
        with pytest.raises(NotImplementedError):
            t.run()

    def test_to_openai_tool(self):
        """to_openai_tool should return proper OpenAI tool format."""
        t = Tool()
        t.name = "Read"
        t.description = "Read a file"
        t.parameters = {"type": "object", "properties": {}}
        result = t.to_openai_tool()
        assert result["type"] == "function"
        assert result["function"]["name"] == "Read"
        assert result["function"]["description"] == "Read a file"


class TestToolRegistry:
    def setup_method(self):
        self.registry = ToolRegistry()

    def test_register_and_get(self):
        """Register a tool and retrieve it."""
        t = Tool()
        t.name = "TestTool"
        self.registry.register(t)
        assert self.registry.get("TestTool") is t

    def test_get_unknown_tool(self):
        """Getting an unknown tool should return None."""
        assert self.registry.get("nonexistent") is None

    def test_list_tools(self):
        """list_tools should return OpenAI-formatted tool list."""
        t = Tool()
        t.name = "TestTool"
        t.description = "A test tool"
        t.parameters = {"type": "object", "properties": {}}
        self.registry.register(t)
        tools = self.registry.list_tools()
        assert len(tools) == 1
        assert tools[0]["function"]["name"] == "TestTool"

    def test_execute_unknown_tool(self):
        """Executing an unknown tool should return error message."""
        result = self.registry.execute("nonexistent", {})
        assert "unknown tool" in result

    def test_execute_tool(self):
        """Executing a registered tool should work."""
        class MyTool(Tool):
            name = "MyTool"
            description = "My tool"

            def run(self, **kwargs):
                return f"ran with {kwargs}"

        self.registry.register(MyTool())
        result = self.registry.execute("MyTool", {"key": "value"})
        assert "ran with" in result
        assert "key" in result

    def test_execute_tool_error(self):
        """Executing a tool that raises should return error message."""
        class BrokenTool(Tool):
            name = "Broken"
            description = "Broken tool"

            def run(self, **kwargs):
                raise RuntimeError("something broke")

        self.registry.register(BrokenTool())
        result = self.registry.execute("Broken", {})
        assert "Error executing" in result
        assert "something broke" in result

    def test_execute_with_permission_check(self):
        """Executing with permission check should work."""
        t = Tool()
        t.name = "SafeTool"
        self.registry.register(t)

        def check_perm(name):
            return name == "SafeTool"

        result = self.registry.execute("SafeTool", {}, check_perm=check_perm)
        # Should not get permission denied since check returns True
        assert "Permission denied" not in result
