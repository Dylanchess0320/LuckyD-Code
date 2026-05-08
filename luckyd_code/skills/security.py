"""Security review skill."""

import subprocess


def security_review() -> str:
    """Analyze pending changes for security issues."""
    try:
        diff = subprocess.run(
            ["git", "diff", "HEAD"],
            capture_output=True, text=True, timeout=30,
        ).stdout
        if not diff:
            return "No changes to review."
        return f"Security review of changes:\n\n```diff\n{diff[:8000]}\n```"
    except Exception as e:
        return f"Error: {e}"
