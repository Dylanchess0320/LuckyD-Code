"""Conversation context management with token-aware compaction."""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class _CompactConfig(Protocol):
    """Minimal interface the context needs from a Config for compaction calls."""

    api_key: str
    base_url: str
    model: str

try:
    import openai
except ImportError:  # pragma: no cover
    openai = None  # type: ignore[assignment]

_log = logging.getLogger(__name__)

# Safety multiplier applied to tiktoken counts to account for the difference
# between OpenAI's cl100k_base encoding and DeepSeek's native tokenizer.
# A 5% overhead prevents hitting the context window before compaction triggers.
_TOKEN_SAFETY_FACTOR = 1.05


def _get_accurate_token_count(text: str) -> int:
    """Count tokens using tiktoken if available, fall back to heuristic.

    Note: tiktoken uses OpenAI's cl100k_base encoding, not DeepSeek's native
    tokenizer. DeepSeek's vocabulary is similar but not identical, so counts
    may be slightly off. We apply a 15% safety multiplier to avoid hitting
    the context window before compaction triggers.
    """
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return int(len(enc.encode(text)) * _TOKEN_SAFETY_FACTOR)
    except Exception:
        # Code is 2-3x more token-dense than prose due to symbols/indentation
        if any(c in text for c in '{}(\n') or text.count('    ') > 2:
            return max(len(text) // 3, 1)
        return max(len(text) // 4, 1)


class ConversationContext:
    """Manages conversation history and message structure."""

    def __init__(
        self,
        system_prompt: str,
        max_messages: int = 100,
        config: _CompactConfig | None = None,
        model: str = "deepseek-v4-flash",
    ) -> None:
        self.messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt}
        ]
        self.max_messages = max_messages
        self._config = config
        self._model = model
        # Auto-compact when estimated tokens exceed this threshold.
        # DeepSeek V4 Flash and V4 Pro both support 1M context windows.
        # Compacting much earlier (150K) keeps the context lean, reducing
        # per-request token costs dramatically for long sessions.
        self._token_compact_threshold: int = 150_000

    # ------------------------------------------------------------------
    # Public property so other modules never reach into private state.
    # ------------------------------------------------------------------

    @property
    def token_compact_threshold(self) -> int:
        """Token count at which auto-compaction is triggered. Settable."""
        return self._token_compact_threshold

    @token_compact_threshold.setter
    def token_compact_threshold(self, value: int) -> None:
        if value < 1:
            raise ValueError(
                f"token_compact_threshold must be positive, got {value}"
            )
        self._token_compact_threshold = value

    def add_user_message(self, content: str) -> None:
        self.messages.append({"role": "user", "content": content})
        self._maybe_trim()
        # Token-aware auto-compaction: prevent silent context window overflow
        if self._config is not None and self.estimate_tokens() > self._token_compact_threshold:
            self.compact(self._config, keep_last=5)


    def add_assistant_message(
        self,
        content: str | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        reasoning_content: str | None = None,
    ) -> None:
        msg: dict[str, Any] = {"role": "assistant"}
        if content is not None:
            msg["content"] = content
        elif reasoning_content:
            # DeepSeek API requires 'content' to always be present alongside
            # 'reasoning_content' in multi-turn requests. Omitting it causes
            # "content or tool_calls must be set". Default to empty string.
            msg["content"] = ""
        if tool_calls:
            msg["tool_calls"] = tool_calls
        if reasoning_content:
            # Truncate reasoning to first 800 chars to keep context lean.
            # The API requires reasoning_content to be present, but it's
            # rarely useful beyond the first few hundred characters.
            msg["reasoning_content"] = str(reasoning_content)[:800]
        self.messages.append(msg)
        self._maybe_trim()

    def add_tool_result(self, tool_call_id: str, tool_name: str, result: str) -> None:
        self.messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": result,
        })
        self._maybe_trim()

    def get_messages(self) -> list[dict[str, Any]]:
        return self.messages

    @staticmethod
    def _drop_orphaned_tool_messages(
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Remove tool-result messages whose parent assistant tool_call is absent."""
        valid_parent_ids: set = set()
        filtered: list[dict[str, Any]] = []
        for msg in messages:
            role = msg.get("role")
            if role == "assistant":
                for tc in msg.get("tool_calls") or []:
                    valid_parent_ids.add(tc.get("id", ""))
                filtered.append(msg)
            elif role == "tool":
                if msg.get("tool_call_id") in valid_parent_ids:
                    filtered.append(msg)
            else:
                valid_parent_ids.clear()
                filtered.append(msg)
        return filtered

    def _maybe_trim(self):
        """Trim oldest messages if we exceed max_messages, keeping system prompt."""
        if len(self.messages) > self.max_messages:
            keep = [self.messages[0]] + self.messages[-(self.max_messages - 1):]
            self.messages = self._drop_orphaned_tool_messages(keep)

    def count_messages(self) -> int:
        return len(self.messages)

    def estimate_tokens(self) -> int:
        """Estimate total tokens using tiktoken (accurate) with fallback to chars/4."""
        total = 0
        for msg in self.messages:
            content = str(msg.get("content", ""))
            total += _get_accurate_token_count(content)
            for tc in msg.get("tool_calls", []):
                fn = tc.get("function", {})
                total += _get_accurate_token_count(str(fn.get("name", "")))
                total += _get_accurate_token_count(str(fn.get("arguments", "")))
            if msg.get("tool_call_id"):
                total += 5
            reasoning = msg.get("reasoning_content", "")
            if reasoning:
                total += _get_accurate_token_count(str(reasoning))
            total += 5
        return total

    def reset(self, system_prompt: str | None = None) -> None:
        if system_prompt:
            self.messages = [{"role": "system", "content": system_prompt}]
        else:
            system = self.messages[0]
            self.messages = [system]

    # ------------------------------------------------------------------
    # Compaction — network concern isolated in _fetch_summary()
    # ------------------------------------------------------------------

    def _fetch_summary(
        self,
        config: _CompactConfig,
        compact_targets: list[dict[str, Any]],
    ) -> str:
        """Call the LLM to produce a concise summary of *compact_targets*.

        Separated from :meth:`compact` so state-management logic and network
        I/O live in different methods (single-responsibility principle).
        """
        import httpx  # lazy — only pay the import cost when compacting

        summary_text = "\n".join(
            f"{m['role']}: {str(m.get('content', ''))[:400]}"
            + (
                f"\n[key reasoning]: {str(m['reasoning_content'])[:100]}"
                if m.get("reasoning_content") else ""
            )
            for m in compact_targets
        )
        summary_prompt = (
            "Summarize the following conversation history concisely. "
            "Capture key decisions, code changes, file paths, and the user's goals:"
            f"\n\n{summary_text}"
        )

        flash_id = "deepseek-v4-flash"
        compact_model = config.model or flash_id
        # Reasoner models don't summarise well — fall back to Flash.
        if "reason" in compact_model.lower():
            compact_model = flash_id

        client = openai.OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            http_client=httpx.Client(timeout=30),
        )
        response = client.chat.completions.create(
            model=compact_model,
            messages=[{"role": "user", "content": summary_prompt}],
            max_tokens=500,
        )
        return response.choices[0].message.content or ""

    def compact(
        self,
        config: _CompactConfig,
        keep_last: int = 5,
        on_compact: Callable[[str, int], None] | None = None,
    ) -> str:
        """Compact conversation by summarising older messages using the LLM.

        The model used for summarisation is taken from ``config.model``
        (falling back to Flash if the config model is a reasoner).
        Network I/O is delegated to :meth:`_fetch_summary` so this method
        only owns state transitions.
        """
        if len(self.messages) <= keep_last + 1:
            return "Nothing to compact"

        system = self.messages[0]
        keep = self.messages[-keep_last:]
        compact_targets = self.messages[1:-keep_last]

        try:
            summary = self._fetch_summary(config, compact_targets)
        except Exception as e:
            return f"Compaction failed: {e}"

        raw: list[dict[str, Any]] = [
            system,
            {
                "role": "system",
                "content": f"[Compacted conversation summary]: {summary}",
            },
        ] + keep
        self.messages = self._drop_orphaned_tool_messages(raw)

        count = len(compact_targets)
        if on_compact is not None:
            try:
                on_compact(summary, count)
            except Exception:
                _log.warning("Compaction callback failed", exc_info=True)

        return f"Compacted {count} messages into a summary"
