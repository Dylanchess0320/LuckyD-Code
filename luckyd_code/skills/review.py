"""Code review skill."""

import subprocess

__all__ = ["review_changes"]


def review_changes() -> str:
    """Review pending git changes."""
    try:
        diff = subprocess.run(
            ["git", "diff", "HEAD"],
            capture_output=True, text=True, timeout=30,
        ).stdout
        if not diff:
            diff = subprocess.run(
                ["git", "diff", "--cached"],
                capture_output=True, text=True, timeout=30,
            ).stdout
        if not diff:
            return "No changes to review."
        return f"Changes to review:\n\n```diff\n{diff[:8000]}\n```"
    except Exception as e:
        return f"Error getting diff: {e}"
