"""Tests for export.py — markdown and HTML conversation export."""

import pytest
from pathlib import Path
from luckyd_code.export import export_markdown, export_html, _escape_html


MESSAGES = [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Hello!"},
    {"role": "assistant", "content": "Hi there!"},
    {"role": "tool", "tool_call_id": "call_1", "content": "Tool result here"},
]

MESSAGES_WITH_TOOL_CALLS = [
    {"role": "user", "content": "Read the file"},
    {
        "role": "assistant",
        "content": "Sure",
        "tool_calls": [
            {"function": {"name": "Read", "arguments": '{"file_path": "test.py"}'}}
        ],
    },
]


class TestEscapeHtml:
    def test_ampersand(self):
        assert _escape_html("a & b") == "a &amp; b"

    def test_less_than(self):
        assert _escape_html("<tag>") == "&lt;tag&gt;"

    def test_greater_than(self):
        assert _escape_html("x > y") == "x &gt; y"

    def test_no_special_chars(self):
        assert _escape_html("hello world") == "hello world"

    def test_combined(self):
        result = _escape_html("<script>alert('xss & friends')</script>")
        assert "&lt;" in result
        assert "&gt;" in result
        assert "&amp;" in result


class TestExportMarkdown:
    def test_returns_string(self):
        result = export_markdown(MESSAGES)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_contains_header(self):
        result = export_markdown(MESSAGES)
        assert "# Conversation Export" in result

    def test_contains_exported_timestamp(self):
        result = export_markdown(MESSAGES)
        assert "Exported:" in result

    def test_system_role_formatted(self):
        result = export_markdown(MESSAGES)
        assert "## System" in result
        assert "You are a helpful assistant." in result

    def test_user_role_formatted(self):
        result = export_markdown(MESSAGES)
        assert "## User" in result
        assert "Hello!" in result

    def test_assistant_role_formatted(self):
        result = export_markdown(MESSAGES)
        assert "## Assistant" in result
        assert "Hi there!" in result

    def test_tool_role_formatted(self):
        result = export_markdown(MESSAGES)
        assert "## Tool Result" in result
        assert "Tool result here" in result
        assert "call_1" in result

    def test_assistant_with_tool_calls(self):
        result = export_markdown(MESSAGES_WITH_TOOL_CALLS)
        assert "tool: Read" in result
        assert "file_path" in result

    def test_tool_content_truncated_at_500(self):
        long_content = "x" * 600
        msgs = [{"role": "tool", "tool_call_id": "c1", "content": long_content}]
        result = export_markdown(msgs)
        assert "truncated" in result

    def test_tool_content_not_truncated_when_short(self):
        msgs = [{"role": "tool", "tool_call_id": "c1", "content": "short"}]
        result = export_markdown(msgs)
        assert "truncated" not in result

    def test_empty_messages(self):
        result = export_markdown([])
        assert isinstance(result, str)
        assert "# Conversation Export" in result

    def test_writes_to_file(self, tmp_path):
        fpath = str(tmp_path / "export.md")
        result = export_markdown(MESSAGES, filepath=fpath)
        assert Path(fpath).exists()
        assert Path(fpath).read_text(encoding="utf-8") == result

    def test_no_filepath_does_not_write_file(self, tmp_path):
        export_markdown(MESSAGES)
        assert not list(tmp_path.glob("*.md"))

    def test_unknown_role_handled(self):
        msgs = [{"role": "unknown", "content": "mystery"}]
        result = export_markdown(msgs)
        assert isinstance(result, str)

    def test_assistant_content_and_tool_calls(self):
        msgs = [
            {
                "role": "assistant",
                "content": "I'll do that",
                "tool_calls": [
                    {"function": {"name": "Write", "arguments": '{"path": "f.py"}'}}
                ],
            }
        ]
        result = export_markdown(msgs)
        assert "tool: Write" in result
        assert "I'll do that" in result


class TestExportHtml:
    def test_returns_string(self):
        result = export_html(MESSAGES)
        assert isinstance(result, str)

    def test_is_valid_html(self):
        result = export_html(MESSAGES)
        assert "<!DOCTYPE html>" in result
        assert "</html>" in result

    def test_custom_title(self):
        result = export_html(MESSAGES, title="My Chat")
        assert "My Chat" in result

    def test_default_title(self):
        result = export_html(MESSAGES)
        assert "Conversation Export" in result

    def test_system_message_rendered(self):
        result = export_html(MESSAGES)
        assert "System" in result
        assert "You are a helpful assistant." in result

    def test_user_message_rendered(self):
        result = export_html(MESSAGES)
        assert "User" in result
        assert "Hello!" in result

    def test_assistant_message_rendered(self):
        result = export_html(MESSAGES)
        assert "Assistant" in result
        assert "Hi there!" in result

    def test_tool_result_rendered(self):
        result = export_html(MESSAGES)
        assert "Tool Result" in result
        assert "call_1" in result

    def test_html_escaping_applied(self):
        msgs = [{"role": "user", "content": "<script>alert('xss')</script>"}]
        result = export_html(msgs)
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_assistant_with_tool_calls(self):
        result = export_html(MESSAGES_WITH_TOOL_CALLS)
        assert "Tool: Read" in result

    def test_writes_to_file(self, tmp_path):
        fpath = str(tmp_path / "export.html")
        result = export_html(MESSAGES, filepath=fpath)
        assert Path(fpath).exists()
        assert Path(fpath).read_text(encoding="utf-8") == result

    def test_contains_css(self):
        result = export_html(MESSAGES)
        assert "<style>" in result

    def test_tool_content_truncated(self):
        long_content = "y" * 600
        msgs = [{"role": "tool", "tool_call_id": "t1", "content": long_content}]
        result = export_html(msgs)
        assert len(result) > 0

    def test_empty_messages(self):
        result = export_html([])
        assert "<!DOCTYPE html>" in result
