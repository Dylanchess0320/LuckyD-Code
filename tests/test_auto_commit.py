"""Tests for git auto-commit logic."""

from unittest.mock import patch
from luckyd_code.git.auto_commit import (
    collect_modified_paths,
    auto_commit,
    _make_commit_message,
)


# ── collect_modified_paths ────────────────────────────────────────────────────

def _tc(id_, name, args_json):
    return {"id": id_, "function": {"name": name, "arguments": args_json}}


def test_collect_write_tool():
    tool_calls = [_tc("1", "Write", '{"file_path": "/tmp/foo.py"}')]
    args_map = {"1": {"file_path": "/tmp/foo.py"}}
    result = collect_modified_paths(tool_calls, args_map)
    assert result == ["/tmp/foo.py"]


def test_collect_edit_tool():
    tool_calls = [_tc("1", "Edit", '{"file_path": "/tmp/bar.py"}')]
    args_map = {"1": {"file_path": "/tmp/bar.py"}}
    result = collect_modified_paths(tool_calls, args_map)
    assert result == ["/tmp/bar.py"]


def test_collect_ignores_read_tool():
    tool_calls = [_tc("1", "Read", '{"file_path": "/tmp/foo.py"}')]
    args_map = {"1": {"file_path": "/tmp/foo.py"}}
    result = collect_modified_paths(tool_calls, args_map)
    assert result == []


def test_collect_deduplicates():
    tool_calls = [
        _tc("1", "Write", '{"file_path": "/tmp/foo.py"}'),
        _tc("2", "Edit",  '{"file_path": "/tmp/foo.py"}'),
    ]
    args_map = {
        "1": {"file_path": "/tmp/foo.py"},
        "2": {"file_path": "/tmp/foo.py"},
    }
    result = collect_modified_paths(tool_calls, args_map)
    assert result == ["/tmp/foo.py"]


def test_collect_multiple_files():
    tool_calls = [
        _tc("1", "Write", '{"file_path": "/tmp/a.py"}'),
        _tc("2", "Edit",  '{"file_path": "/tmp/b.py"}'),
    ]
    args_map = {
        "1": {"file_path": "/tmp/a.py"},
        "2": {"file_path": "/tmp/b.py"},
    }
    result = collect_modified_paths(tool_calls, args_map)
    assert result == ["/tmp/a.py", "/tmp/b.py"]


# ── _make_commit_message ─────────────────────────────────────────────────────

def test_commit_message_basic():
    msg = _make_commit_message("add login endpoint")
    assert msg == "agent: add login endpoint"


def test_commit_message_truncated():
    long_prompt = "a" * 100
    msg = _make_commit_message(long_prompt)
    assert len(msg) <= len("agent: ") + 72


def test_commit_message_multiline():
    msg = _make_commit_message("fix bug\nmore details here")
    assert "\n" not in msg
    assert "fix bug" in msg


def test_commit_message_empty():
    msg = _make_commit_message("")
    assert "agent:" in msg


# ── auto_commit (integration-style with mocks) ───────────────────────────────

@patch("luckyd_code.git.auto_commit._in_git_repo", return_value=False)
def test_auto_commit_skips_outside_git(mock_git):
    result = auto_commit("fix something", ["/tmp/foo.py"])
    assert result is None


@patch("luckyd_code.git.auto_commit._commit", return_value="abc1234")
@patch("luckyd_code.git.auto_commit._has_staged_changes", return_value=True)
@patch("luckyd_code.git.auto_commit._stage_files", return_value=True)
@patch("luckyd_code.git.auto_commit._in_git_repo", return_value=True)
def test_auto_commit_returns_sha(mock_repo, mock_stage, mock_staged, mock_commit):
    result = auto_commit("add feature", ["/tmp/foo.py"])
    assert result == "abc1234"
    mock_commit.assert_called_once()
    call_msg = mock_commit.call_args[0][0]
    assert call_msg.startswith("agent:")


@patch("luckyd_code.git.auto_commit._in_git_repo", return_value=True)
def test_auto_commit_skips_empty_paths(mock_repo):
    result = auto_commit("fix something", [])
    assert result is None


@patch("luckyd_code.git.auto_commit._in_git_repo", return_value=True)
def test_auto_commit_disabled(mock_repo):
    result = auto_commit("fix something", ["/tmp/foo.py"], enabled=False)
    assert result is None


@patch("luckyd_code.git.auto_commit._commit", return_value="abc1234")
@patch("luckyd_code.git.auto_commit._has_staged_changes", return_value=False)
@patch("luckyd_code.git.auto_commit._stage_files", return_value=True)
@patch("luckyd_code.git.auto_commit._in_git_repo", return_value=True)
def test_auto_commit_skips_no_staged_changes(mock_repo, mock_stage, mock_staged, mock_commit):
    result = auto_commit("no-op write", ["/tmp/foo.py"])
    assert result is None
    mock_commit.assert_not_called()
