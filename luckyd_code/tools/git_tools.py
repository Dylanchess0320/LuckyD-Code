from typing import Any
from .registry import Tool
from ..git import git_status, git_diff, git_log, git_commit, git_add, git_branch, git_create_pr, git_push


class GitStatusTool(Tool):
    name = "GitStatus"
    description = "Show git working tree status."
    permission_risk = "safe"
    parameters = {
        "type": "object",
        "properties": {},
    }

    def run(self, **kwargs: Any) -> str:
        return git_status()


class GitDiffTool(Tool):
    name = "GitDiff"
    description = "Show git diff of changes."
    permission_risk = "safe"
    parameters = {
        "type": "object",
        "properties": {
            "staged": {
                "type": "boolean",
                "description": "Show staged changes only",
            },
        },
    }

    def run(self, staged: bool = False) -> str:
        return git_diff(staged)


class GitLogTool(Tool):
    name = "GitLog"
    description = "Show recent commit history."
    permission_risk = "safe"
    parameters = {
        "type": "object",
        "properties": {
            "count": {"type": "integer", "description": "Number of commits to show"},
        },
    }

    def run(self, count: int = 10) -> str:
        return git_log(count)


class GitCommitTool(Tool):
    name = "GitCommit"
    description = "Create a git commit with a message."
    permission_risk = "high"
    parameters = {
        "type": "object",
        "properties": {
            "message": {"type": "string", "description": "Commit message"},
        },
        "required": ["message"],
    }

    def run(self, message: str) -> str:
        return git_commit(message)


class GitAddTool(Tool):
    name = "GitAdd"
    description = "Stage files for commit."
    permission_risk = "medium"
    parameters = {
        "type": "object",
        "properties": {
            "files": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Files to stage (default: all)",
            },
        },
    }

    def run(self, files: list[str] | None = None) -> str:
        return git_add(files)


class GitBranchTool(Tool):
    name = "GitBranch"
    description = "List and manage git branches."
    permission_risk = "safe"
    parameters = {
        "type": "object",
        "properties": {},
    }

    def run(self, **kwargs: Any) -> str:
        return git_branch()


class GitPRTool(Tool):
    name = "GitPR"
    description = "Push current branch and create a DRAFT pull request on GitHub."
    permission_risk = "high"
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "PR title"},
            "body": {"type": "string", "description": "PR body/description"},
        },
        "required": ["title"],
    }

    def run(self, title: str, body: str = "") -> str:
        push_result = git_push()
        pr_result = git_create_pr(title, body, draft=True)
        return f"Push: {push_result}\nDraft PR: {pr_result}"


class GitPushTool(Tool):
    name = "GitPush"
    description = "Push commits to remote."
    permission_risk = "high"
    parameters = {
        "type": "object",
        "properties": {
            "branch": {"type": "string", "description": "Branch to push"},
        },
    }

    def run(self, branch: str | None = None) -> str:
        return git_push(branch)
