"""Configuration management with validation and file persistence."""

import os
import json
from pathlib import Path
from typing import Any

from .log import get_logger
from ._data_dir import data_path, legacy_path

DEFAULT_SYSTEM_PROMPT = """You are LuckyD Code, an AI coding assistant in a terminal.

You can answer ANY question — coding, general knowledge, everyday questions, or anything else the user asks. You are a helpful general-purpose assistant who happens to specialise in code.

## Core Rules
- For coding tasks: use Bash/Read/Write/Edit/Glob/Grep tools as needed, working directory is the project root
- For general questions: answer directly and concisely from your knowledge
- Think step by step, but only show the final answer
- No unnecessary padding, greetings, or filler — just useful output

## Multi-Agent Usage
Use specialist agents automatically when a task has distinct phases or needs depth you can't provide in a single pass:

**Use AgentHandoff when:**
- The task needs research before coding → handoff to `researcher` first, then `coder`
- You've written code and it needs a thorough review → handoff to `reviewer`
- A module needs tests written or existing tests need running → handoff to `tester`
- A task has a clear specialist role (research, implement, review, test) — don't try to do it all yourself

**Use SubAgent when:**
- A subtask is self-contained and can run independently (e.g. generate a large file, deep-dive a codebase section)
- You want to explore without polluting the main conversation context

**Chain agents for complex tasks:**
researcher → coder → reviewer (research first, implement, then review the result)

**Don't use agents for:**
- Simple Q&A, quick edits, single-file changes, or anything you can do in 1-2 tool calls

## Pre-Edit Checklist (MANDATORY before any Write/Edit)
1. **Read the file first** — Never edit a file you haven't read this turn
2. **Understand the context** — Check how the code is used elsewhere (Grep for callers/imports)
3. **Match existing patterns** — Follow the project's conventions, naming, style
4. **Plan the minimal change** — Only touch what's necessary; no refactoring sprees
5. **Preview mentally** — What will break? What edge cases exist?

## Post-Edit Verification
After every Write or Edit:
- Your changes will be automatically verified (syntax, consistency, tests)
- If verification fails, you MUST fix the issues — don't ignore them
- Tests failing after your change? Fix them immediately

## Self-Critique
Before presenting your final answer, review it:
- Did I actually solve the user's problem?
- Could this be done more simply?
- Are there edge cases I missed?
- Is the code safe (no injection, no leaked secrets)?

## Quality Standards
- **Correctness over cleverness** — Working code beats elegant code
- **Minimal diffs** — Small, focused changes are easier to review and revert
- **Error handling** — Don't let errors pass silently
- **No dead code** — Remove unused imports, variables, functions
- **Type safety** — Use type hints where the project uses them"""

CONFIG_FILE = data_path("config.json")
_LEGACY_CONFIG_FILE = legacy_path("config.json")


def load_config_file() -> dict[str, Any]:
    """Load persistent config from the data directory.

    Checks the primary location first, then falls back to the legacy
    location for backward compatibility.
    """
    for path in (CONFIG_FILE, _LEGACY_CONFIG_FILE):
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                get_logger().warning(f"Could not load config file: {e}")
    return {}


def save_config_file(config: dict):
    """Save config to the data directory."""
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        CONFIG_FILE.write_text(json.dumps(config, indent=2), encoding="utf-8")
    except OSError as e:
        get_logger().warning(f"Could not save config file: {e}")


class Config:
    """Application configuration with validation."""

    def __init__(self):
        saved = load_config_file()

        self.provider: str = saved.get("provider", "deepseek")
        self.base_url: str = saved.get("base_url", "https://api.deepseek.com/v1")
        self.api_key: str = self._resolve_api_key()
        self.model: str = saved.get("model", "deepseek-v4-flash")
        self.max_tokens: int = saved.get("max_tokens", 8192)
        self.temperature: float = saved.get("temperature", 0.7)
        self.system_prompt: str = saved.get("system_prompt", DEFAULT_SYSTEM_PROMPT)
        self.working_directory: str = saved.get("working_directory", os.getcwd())
        self.max_context_messages: int = saved.get("max_context_messages", 100)
        self.log_level: str = saved.get("log_level", "INFO")

    def _resolve_api_key(self) -> str:
        provider_env = f"{self.provider.upper()}_API_KEY"
        for path in (Path(__file__).parent.parent / ".env", Path(".env")):
            if path.exists():
                try:
                    lines = path.read_text().splitlines()
                    for line in lines:
                        line = line.strip()
                        # Match both DEEPSEEK_API_KEY and <PROVIDER>_API_KEY
                        if line.startswith(f"{provider_env}="):
                            return line.split("=", 1)[1].strip("\"'")
                        if line.startswith("DEEPSEEK_API_KEY=") and self.provider == "deepseek":
                            return line.split("=", 1)[1].strip("\"'")
                except Exception:
                    get_logger().warning("Could not read .env file: %s", path, exc_info=True)

        # Fallback: environment variables (provider-specific first, then legacy)
        key = os.environ.get(provider_env) or os.environ.get("DEEPSEEK_API_KEY")
        if key:
            return key
        return ""

    def validate(self):
        """Validate config and raise ValueError with clear message on failure."""
        errors = []

        # Supported providers and their default base URLs
        _provider_urls = {
            "deepseek": "https://api.deepseek.com/v1",
            "openai": "https://api.openai.com/v1",
            "groq": "https://api.groq.com/openai/v1",
            "together": "https://api.together.xyz/v1",
            "ollama": "http://localhost:11434/v1",
        }
        if self.provider not in _provider_urls:
            errors.append(
                f"provider must be one of {sorted(_provider_urls.keys())} (got: {self.provider})"
            )

        if not self.api_key:
            key_env = f"{self.provider.upper()}_API_KEY"
            errors.append(
                f"{key_env} is not set. "
                "Set it as an environment variable or in a .env file."
            )

        if not self.base_url:
            errors.append("base_url is not set")
        elif not self.base_url.startswith(("http://", "https://")):
            errors.append(f"base_url must start with http:// or https:// (got: {self.base_url})")

        if self.max_tokens < 1 or self.max_tokens > 32000:
            errors.append(f"max_tokens must be between 1 and 32000 (got: {self.max_tokens})")

        if self.temperature < 0 or self.temperature > 2:
            errors.append(f"temperature must be between 0 and 2 (got: {self.temperature})")

        if self.max_context_messages < 2:
            errors.append(f"max_context_messages must be at least 2 (got: {self.max_context_messages})")

        if errors:
            raise ValueError("\n".join(errors))

    def to_dict(self) -> dict:
        """Export config as dict (excluding API key)."""
        return {
            "provider": self.provider,
            "base_url": self.base_url,
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "max_context_messages": self.max_context_messages,
            "log_level": self.log_level,
        }

    def save(self):
        """Persist current config (excluding API key) to config file."""
        save_config_file(self.to_dict())

    @classmethod
    def from_args(cls, args=None):
        cfg = cls()
        if args:
            if hasattr(args, "model") and args.model:
                cfg.model = args.model
            if hasattr(args, "temperature") and args.temperature is not None:
                cfg.temperature = args.temperature
            if hasattr(args, "system_prompt") and args.system_prompt:
                cfg.system_prompt = args.system_prompt
            if hasattr(args, "dir") and args.dir:
                cfg.working_directory = args.dir
            if hasattr(args, "provider") and args.provider:
                cfg.provider = args.provider
                # Only override base_url if none was persisted — derive it
                # from the provider name rather than hardcoding DeepSeek.
                if "base_url" not in load_config_file():
                    _provider_urls = {
                        "deepseek": "https://api.deepseek.com/v1",
                        "openai": "https://api.openai.com/v1",
                        "groq": "https://api.groq.com/openai/v1",
                        "together": "https://api.together.xyz/v1",
                        "ollama": "http://localhost:11434/v1",
                    }
                    cfg.base_url = _provider_urls.get(
                        cfg.provider, cfg.base_url
                    )
                # Re-resolve key now that provider is set from args
                cfg.api_key = cfg._resolve_api_key()
        return cfg


# ---------------------------------------------------------------------------
# Module-level convenience helpers (used by generator tools)
# ---------------------------------------------------------------------------

def get_api_key() -> str:
    """Return the resolved DeepSeek API key."""
    return Config()._resolve_api_key()


def get_base_url() -> str:
    """Return the configured API base URL."""
    return Config().base_url
