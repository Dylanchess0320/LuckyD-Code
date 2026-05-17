"""Configuration management with validation and file persistence."""

import os
import json
from pathlib import Path
from typing import Any

from .log import get_logger
from ._data_dir import data_path, legacy_path

__all__ = ["Config", "load_config_file", "save_config_file", "get_api_key", "get_base_url"]

DEFAULT_SYSTEM_PROMPT = """You are LuckyD Code, an AI coding assistant in a terminal.

Answer concisely. For code: use Bash/Read/Write/Edit/Glob/Grep tools. For questions: answer directly.

CRITICAL: If the user asks a question that is NOT about this project or codebase
(e.g., general knowledge, trivia, opinions, factual questions), answer it directly
and immediately. Do NOT search the codebase first. Do NOT redirect to project
concerns. Answer the question the user actually asked.

## Agents
- Use AgentHandoff for specialist roles: researcher → coder → reviewer
- Use SubAgent for self-contained subtasks
- Skip agents for simple Q&A or 1-2 tool edits

## Code Rules
1. Read file before editing
2. Match existing patterns
3. Minimal diffs only
4. Verify changes work
5. No dead code, no silent errors

## When stuck
- If you attempt the same approach 2+ times and it fails, STOP and ask the user for guidance instead of trying again
- If a task is beyond your current context or capability, say so clearly and suggest what the user should do next
- Never repeat a failing tool call more than twice — explain what blocked you instead"""

CONFIG_FILE = data_path("config.json")
_LEGACY_CONFIG_FILE = legacy_path("config.json")

# Single source of truth for supported providers and their default base URLs.
_PROVIDER_URLS: dict[str, str] = {
    "deepseek": "https://api.deepseek.com/v1",
    "openai": "https://api.openai.com/v1",
    "groq": "https://api.groq.com/openai/v1",
    "together": "https://api.together.xyz/v1",
    "ollama": "http://localhost:11434/v1",
}


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
                get_logger().warning("Could not load config file: %s", e)
    return {}


def save_config_file(config: dict):
    """Save config to the data directory."""
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        CONFIG_FILE.write_text(json.dumps(config, indent=2), encoding="utf-8")
    except OSError as e:
        get_logger().warning("Could not save config file: %s", e)


class Config:
    """Application configuration with validation."""

    def __init__(self):
        saved = load_config_file()

        self.provider: str = saved.get("provider", "deepseek")
        self.base_url: str = saved.get("base_url", "https://api.deepseek.com/v1")
        self.api_key: str = self._resolve_api_key()
        self.model: str = saved.get("model", "deepseek-v4-flash")
        self.max_tokens: int = saved.get("max_tokens", 4096)
        self.temperature: float = saved.get("temperature", 0.3)
        self.system_prompt: str = saved.get("system_prompt", DEFAULT_SYSTEM_PROMPT)
        self.working_directory: str = saved.get("working_directory", os.getcwd())
        self.max_context_messages: int = saved.get("max_context_messages", 40)
        self.log_level: str = saved.get("log_level", "WARNING")
        self.effort: str = saved.get("effort", "normal")  # low | normal | high | max

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

        if self.provider not in _PROVIDER_URLS:
            errors.append(
                f"provider must be one of {sorted(_PROVIDER_URLS.keys())} (got: {self.provider})"
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
            "effort": self.effort,
        }

    def save(self):
        """Persist current config (excluding API key) to config file."""
        save_config_file(self.to_dict())

    @classmethod
    def from_args(cls, args: Any = None) -> "Config":
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
                    cfg.base_url = _PROVIDER_URLS.get(
                        cfg.provider, cfg.base_url
                    )
                # Re-resolve key now that provider is set from args
                cfg.api_key = cfg._resolve_api_key()
        return cfg


# ---------------------------------------------------------------------------
# Module-level convenience helpers (used by generator tools)
# ---------------------------------------------------------------------------

def get_api_key() -> str:
    """Return the resolved API key for the configured provider."""
    return Config()._resolve_api_key()


def get_base_url() -> str:
    """Return the configured API base URL."""
    return Config().base_url
