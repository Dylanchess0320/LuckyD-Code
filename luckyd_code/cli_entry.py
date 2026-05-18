"""CLI entry point — argument parsing, first-run wizard, and main dispatch."""

import argparse
import os
import sys
from pathlib import Path
from typing import Any

# Patch asyncio to allow nested event loops. This is needed because
# BackgroundAgent / KnowledgeGraph initialisation may start a loop before
# prompt_toolkit's synchronous session.prompt() runs, which would otherwise
# raise: RuntimeError: asyncio.run() cannot be called from a running event loop
try:
    import nest_asyncio
    nest_asyncio.apply()
except ImportError:
    pass  # Installed below; safe to ignore on first import before pip install

from .config import Config


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="LuckyD Code — AI coding assistant in your terminal",
    )
    parser.add_argument("--model", default=None, help="Model to use (default: deepseek-v4-flash)")
    parser.add_argument(
        "--provider", default=None, choices=["deepseek"],
        help="API provider (default: deepseek)",
    )
    parser.add_argument("--dir", default=None, help="Working directory (default: current)")
    parser.add_argument("--temperature", type=float, default=None, help="Model temperature (default: 0.7)")
    parser.add_argument("--system-prompt", default=None, help="Path to custom system prompt file")
    parser.add_argument("--version", action="store_true", help="Show version and exit")
    parser.add_argument("--update", action="store_true", help="Update to latest version and exit")
    parser.add_argument("--web", action="store_true", help="Launch web UI server")
    parser.add_argument("--port", type=int, default=8000, help="Web UI port (default: 8000)")
    parser.add_argument("--host", default="127.0.0.1", help="Web UI host (default: 127.0.0.1)")
    parser.add_argument(
        "--daemon", action="store_true",
        help="Start the background audit daemon alongside the REPL",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    # Lazy imports — only load the heavy CLI/web modules when actually running
    from .update import get_version, do_update

    if args.version:
        print(f"LuckyD Code v{get_version()}")
        return 0

    if args.update:
        print("Updating LuckyD Code...")
        print(do_update())
        return 0

    if args.web:
        from .web_app import run_web
        try:
            run_web(host=args.host, port=args.port)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        return 0

    # Resize terminal to a comfortable size before launching the REPL
    from .cli_utils import resize_terminal
    resize_terminal()

    if args.dir:
        os.chdir(args.dir)

    config = Config.from_args(args)

    if args.system_prompt:
        try:
            with open(args.system_prompt, encoding="utf-8") as f:
                custom = f.read().strip()
            if custom:
                config.system_prompt = custom
        except Exception as e:
            print(f"Warning: could not load system prompt from {args.system_prompt}: {e}", file=sys.stderr)

    # First-run wizard: interactive API key setup
    if not config.api_key:
        print()
        print("=" * 50)
        print("  Welcome to LuckyD Code!")
        print("=" * 50)
        print()
        print("No API key found. Let's get you set up.")
        print()
        print("You'll need a DeepSeek API key.")
        print("  Get one at: https://platform.deepseek.com")
        print()
        print("Paste your API key below (it will be saved to .env):")
        try:
            key = input("  DEEPSEEK_API_KEY = ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nSetup cancelled. Run again when you have an API key.")
            return 1
        if key:
            env_path = Path(__file__).resolve().parent.parent / ".env"
            if "DEEPSEEK_API_KEY=" in (env_path.read_text() if env_path.exists() else ""):
                lines = env_path.read_text().splitlines()
                new_lines = []
                for line in lines:
                    if line.startswith("DEEPSEEK_API_KEY="):
                        new_lines.append(f"DEEPSEEK_API_KEY={key}")
                    else:
                        new_lines.append(line)
                env_path.write_text("\n".join(new_lines) + "\n")
            else:
                with env_path.open("a") as f:
                    f.write(f"\nDEEPSEEK_API_KEY={key}\n")
            config.api_key = key
            print("✓ API key saved to .env")
        else:
            print("No key entered. Set DEEPSEEK_API_KEY in .env and try again.")
            return 1
        print()

    try:
        config.validate()
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    from .cli import Repl
    daemon_enabled = getattr(args, "daemon", False)
    repl = Repl(config, daemon=daemon_enabled)
    try:
        repl.run()
    except KeyboardInterrupt:
        print("\nGoodbye!")
        return 0
    except Exception as exc:
        # ── Error Reporter: safe, opt-in issue creation ──────────
        # This only fires for *unexpected* exceptions (not KeyboardInterrupt).
        # The user is prompted before anything is sent.  See error_reporter.py.
        from .error_reporter import capture_unhandled
        capture_unhandled(exc)
        raise  # re-raise so the process exits with a non-zero code
    return 0


if __name__ == "__main__":
    sys.exit(main())
