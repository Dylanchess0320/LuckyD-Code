"""Git worktree tools."""

import subprocess

from .registry import Tool


class GitWorktreeTool(Tool):
    name = "GitWorktree"
    description = "Manage git worktrees (create, list, remove)."
    permission_risk = "high"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "create", "remove"],
                "description": "Action to perform",
            },
            "path": {
                "type": "string",
                "description": "Path for the new worktree (required for create)",
            },
            "branch": {
                "type": "string",
                "description": "Branch for the new worktree (optional for create)",
            },
        },
        "required": ["action"],
    }

    def run(self, action: str, path: str | None = None, branch: str | None = None) -> str:
        try:
            if action == "list":
                r = subprocess.run(
                    ["git", "worktree", "list"],
                    capture_output=True, text=True, timeout=30,
                )
                return r.stdout.strip() or r.stderr.strip()

            elif action == "create":
                if not path:
                    return "Error: path is required for create"
                cmd = ["git", "worktree", "add", path]
                if branch:
                    cmd.extend(["-b", branch])
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                return r.stdout.strip() or r.stderr.strip()

            elif action == "remove":
                if not path:
                    return "Error: path is required for remove"
                r = subprocess.run(
                    ["git", "worktree", "remove", path],
                    capture_output=True, text=True, timeout=30,
                )
                return r.stdout.strip() or r.stderr.strip()

            return f"Unknown action: {action}"
        except subprocess.TimeoutExpired:
            return "Error: command timed out"
        except Exception as e:
            return f"Error: {e}"
