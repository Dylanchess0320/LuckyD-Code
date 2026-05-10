"""
LuckyD Code Example — Git Automation Agent
============================================
Demonstrates using LuckyD Code as a library to automate a full Git workflow.

The agent:
  1. Checks git status to understand what's changed
  2. Reviews the diff for each modified file
  3. Writes a conventional commit message based on the actual changes
  4. Stages and commits with the generated message
  5. Optionally pushes to remote

Usage:
    python examples/git_automation.py [--push] [--dry-run]

    --push      Also push to remote after committing
    --dry-run   Show what the agent would do without committing

Requirements:
    pip install luckyd-code
    Set DEEPSEEK_API_KEY in your environment or .env file.
    Run from inside a git repository.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv()


def run_git_agent(push: bool = False, dry_run: bool = False) -> None:
    """Run an AI agent that inspects git changes and commits them intelligently."""
    from luckyd_code.config import Config
    from luckyd_code.context import ConversationContext
    from luckyd_code.tools import get_default_registry
    from luckyd_code._agent_loop import run_agent_loop, RunConfig

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("Error: DEEPSEEK_API_KEY not set. Add it to your .env file.")
        sys.exit(1)

    config = Config()
    config.api_key = api_key
    config.base_url = "https://api.deepseek.com/v1"
    config.model = "deepseek-v4-flash"
    config.max_tokens = 2048
    config.temperature = 0.2  # low temperature for consistent commit messages
    config.system_prompt = (
        "You are a Git automation agent. "
        "You write clear, conventional commit messages based on actual code diffs. "
        "Use the format: <type>(<scope>): <short description>\n\n<body if needed>\n\n"
        "Types: feat, fix, docs, style, refactor, test, chore. "
        "Be specific — reference file names and what actually changed. "
        "Never make up changes you haven't verified in the diff."
    )

    context = ConversationContext(config.system_prompt)
    registry = get_default_registry()

    if dry_run:
        task = """
Please do the following (DRY RUN — do NOT commit or push anything):
1. Run `git status` to see what's changed
2. Run `git diff --stat` for a summary of changes
3. Run `git diff` to read the full diff
4. Write the conventional commit message you WOULD use, and explain your reasoning
5. List the files you would stage
"""
    else:
        push_instruction = (
            "\n6. After committing, run `git push` to push to remote."
            if push else ""
        )
        task = f"""
Please do the following:
1. Run `git status` to see what's changed
2. Run `git diff --stat` for a summary
3. Run `git diff` to read the actual changes (check each modified file)
4. Stage all changes with `git add -A`
5. Write a conventional commit message based on what you read in the diff, then commit{push_instruction}

Important:
- The commit message must reflect the ACTUAL changes you read, not a generic message
- If there are no changes, say so and stop
- If changes span multiple concerns, write a multi-line commit body
"""

    context.add_user_message(task)

    mode = "DRY RUN" if dry_run else ("with push" if push else "commit only")
    print(f"🔧 Git Automation Agent ({mode})\n")

    def on_text(chunk: str) -> None:
        print(chunk, end="", flush=True)

    def on_tool_start(name: str, idx: int, total: int) -> None:
        print(f"\n⚙️  [{idx}/{total}] {name}")

    rc = RunConfig(
        max_turns=10,
        on_text=on_text,
        on_tool_start=on_tool_start,
        auto_save_memory=False,
    )

    run_agent_loop(
        context=context,
        config=config,
        tools=registry.list_tools(),
        registry=registry,
        run_config=rc,
    )

    print("\n\n✅ Done!")


if __name__ == "__main__":
    args = sys.argv[1:]
    push = "--push" in args
    dry_run = "--dry-run" in args

    if "--help" in args or "-h" in args:
        print(__doc__)
        sys.exit(0)

    # Must be run from inside a git repo
    if not os.path.exists(".git"):
        print("Error: not inside a git repository. cd into your project first.")
        sys.exit(1)

    run_git_agent(push=push, dry_run=dry_run)
