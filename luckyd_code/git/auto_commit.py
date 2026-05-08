"""Auto-commit — stage and commit agent-modified files after each completed turn.

Behaviour
---------
* Only runs when inside a git repository.
* Only commits files that the agent actually wrote or edited this turn.
* Skips the commit if there are no staged changes (e.g. the write was a no-op).
* Commit message is derived from the user's prompt (first 72 chars) so the
  git log stays readable — same approach as Aider.
* Can be disabled globally with:  /config set auto_commit false
"""

import subprocess

from ..log import get_logger

# Tool names whose arguments contain the path of a file that was changed.
# The argument key that holds the path is listed alongside.
_WRITE_TOOLS: dict[str, str] = {
    "Write":     "file_path",
    "Edit":      "file_path",
    "MultiEdit": "file_path",
}

_logger = get_logger()


def _in_git_repo(cwd: str | None = None) -> bool:
    """Return True if cwd (or the process cwd) is inside a git repository."""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, timeout=5,
            cwd=cwd,
        )
        return r.returncode == 0
    except Exception:
        return False


def _stage_files(paths: list[str], cwd: str | None = None) -> bool:
    """Stage specific files. Returns True if at least one file was staged."""
    if not paths:
        return False
    try:
        r = subprocess.run(
            ["git", "add", "--"] + paths,
            capture_output=True, text=True, timeout=10,
            cwd=cwd,
        )
        if r.returncode != 0:
            _logger.warning("git add failed: %s", r.stderr.strip())
            return False
        return True
    except Exception as e:
        _logger.warning("git add error: %s", e)
        return False


def _has_staged_changes(cwd: str | None = None) -> bool:
    """Return True if there is anything in the index to commit."""
    try:
        r = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            capture_output=True, timeout=5,
            cwd=cwd,
        )
        # exit 1 means differences exist
        return r.returncode == 1
    except Exception:
        return False


def _make_commit_message(user_prompt: str) -> str:
    """Build a short, readable commit message from the user's prompt."""
    first_line = user_prompt.strip().splitlines()[0] if user_prompt.strip() else "agent changes"
    # Truncate to 72 chars (git convention)
    subject = first_line[:72].rstrip()
    return f"agent: {subject}"


def _commit(message: str, cwd: str | None = None) -> str | None:
    """Create a commit. Returns the short SHA on success, None on failure."""
    try:
        r = subprocess.run(
            ["git", "commit", "-m", message],
            capture_output=True, text=True, timeout=15,
            cwd=cwd,
        )
        if r.returncode != 0:
            _logger.warning("git commit failed: %s", r.stderr.strip())
            return None
        # Parse the short SHA from the output line like "[main abc1234] ..."
        for line in r.stdout.splitlines():
            if line.startswith("["):
                parts = line.split()
                if len(parts) >= 2:
                    return parts[1].rstrip("]")
        return "ok"
    except Exception as e:
        _logger.warning("git commit error: %s", e)
        return None


def collect_modified_paths(tool_calls: list[dict], tool_args_map: dict[str, dict]) -> list[str]:
    """Extract file paths that were written or edited this turn.

    Args:
        tool_calls:    List of tool-call dicts (id, function.name, function.arguments).
        tool_args_map: Mapping of tool_call_id → parsed args dict (populated during execution).

    Returns:
        Deduplicated list of absolute/relative file path strings.
    """
    seen: set[str] = set()
    paths: list[str] = []
    for tc in tool_calls:
        name = tc.get("function", {}).get("name", "")
        arg_key = _WRITE_TOOLS.get(name)
        if not arg_key:
            continue
        args = tool_args_map.get(tc.get("id", ""), {})
        fp = args.get(arg_key, "")
        if fp and fp not in seen:
            seen.add(fp)
            paths.append(fp)
    return paths


def auto_commit(
    user_prompt: str,
    modified_paths: list[str],
    cwd: str | None = None,
    enabled: bool = True,
) -> str | None:
    """Stage modified_paths and commit if inside a git repo and enabled.

    Returns the short commit SHA on success, None if skipped or failed.
    """
    if not enabled or not modified_paths:
        return None

    if not _in_git_repo(cwd):
        return None

    # Only stage the files the agent actually touched
    if not _stage_files(modified_paths, cwd):
        return None

    if not _has_staged_changes(cwd):
        return None

    message = _make_commit_message(user_prompt)
    sha = _commit(message, cwd)
    if sha:
        _logger.info("Auto-committed %d file(s): %s [%s]", len(modified_paths), message, sha)
    return sha
