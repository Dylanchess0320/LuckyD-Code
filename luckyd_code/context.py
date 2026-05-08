import logging
from typing import List, Dict, Any, Optional

_log = logging.getLogger(__name__)


def _get_accurate_token_count(text: str) -> int:
    """Count tokens using tiktoken if available, fall back to heuristic.

    Note: tiktoken uses OpenAI's cl100k_base encoding, not DeepSeek's native
    tokenizer. DeepSeek's vocabulary is similar but not identical, so counts
    may be slightly off. We apply a 15% safety multiplier to avoid hitting
    the context window before compaction triggers.
    """
    _DEEPSEEK_SAFETY_FACTOR = 1.15
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return int(len(enc.encode(text)) * _DEEPSEEK_SAFETY_FACTOR)
    except Exception:
        # Code is 2-3x more token-dense than prose due to symbols/indentation
        if any(c in text for c in '{}(\n') or text.count('    ') > 2:
            return max(len(text) // 3, 1)
        return max(len(text) // 4, 1)


class ConversationContext:
    """Manages conversation history and message structure."""

    def __init__(self, system_prompt: str, max_messages: int = 100,
                 config=None, model: str = "deepseek-v4-flash"):
        self.messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt}
        ]
        self.max_messages = max_messages
        self._config = config
        self._model = model
        # Auto-compact when estimated tokens exceed this threshold.
        # DeepSeek V4 Flash and V4 Pro both support 1M context windows.
        # We compact at 800K to leave ~200K headroom for the response and
        # any injected tool results. Users on older models with smaller
        # context windows can lower this via config.
        self._token_compact_threshold = 800_000

    def add_user_message(self, content: str):
        self.messages.append({"role": "user", "content": content})
        self._maybe_trim()
        # Token-aware auto-compaction: prevent silent context window overflow
        if self._config is not None and self.estimate_tokens() > self._token_compact_threshold:
            self.compact(self._config, self._model, keep_last=8)

    def add_assistant_message(self, content: Optional[str] = None, tool_calls: Optional[List[Dict[str, Any]]] = None, reasoning_content: Optional[str] = None):
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
            msg["reasoning_content"] = reasoning_content
        self.messages.append(msg)
        self._maybe_trim()

    def add_tool_result(self, tool_call_id: str, tool_name: str, result: str):
        self.messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": result,
        })
        self._maybe_trim()

    def get_messages(self) -> List[Dict[str, Any]]:
        return self.messages

    @staticmethod
    def _drop_orphaned_tool_messages(
        messages: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Remove tool-result messages whose parent assistant tool_call is absent.

        This keeps the message list valid for the DeepSeek API, which requires
        every ``role=tool`` message to be preceded by an assistant message that
        contains a matching ``tool_call_id`` in its ``tool_calls`` list.
        """
        valid_parent_ids: set = set()
        filtered: List[Dict[str, Any]] = []
        for msg in messages:
            role = msg.get("role")
            if role == "assistant":
                for tc in msg.get("tool_calls") or []:
                    valid_parent_ids.add(tc.get("id", ""))
                filtered.append(msg)
            elif role == "tool":
                if msg.get("tool_call_id") in valid_parent_ids:
                    filtered.append(msg)
                # orphaned tool result — silently dropped
            else:
                # user / system messages reset parent-id tracking
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
        """Estimate total tokens using tiktoken (accurate) with fallback to chars/4.

        Accounts for all message fields the API consumes: content, tool_calls,
        reasoning_content, and tool_call_ids.
        """
        total = 0
        for msg in self.messages:
            content = str(msg.get("content", ""))
            total += _get_accurate_token_count(content)
            # Account for tool_calls in assistant messages
            for tc in msg.get("tool_calls", []):
                fn = tc.get("function", {})
                total += _get_accurate_token_count(str(fn.get("name", "")))
                total += _get_accurate_token_count(str(fn.get("arguments", "")))
            # Account for tool_call_id in tool messages
            if msg.get("tool_call_id"):
                total += 5
            # DeepSeek reasoning_content (thinking blocks) — preserved across
            # multi-turn conversations and required by the API.  These can be
            # surprisingly large (hundreds of tokens per assistant turn) and
            # were previously invisible to the compaction threshold.
            reasoning = msg.get("reasoning_content", "")
            if reasoning:
                total += _get_accurate_token_count(str(reasoning))
            # Role overhead (~5 tokens per message)
            total += 5
        return total

    def reset(self, system_prompt: Optional[str] = None):
        if system_prompt:
            self.messages = [{"role": "system", "content": system_prompt}]
        else:
            system = self.messages[0]
            self.messages = [system]

    def compact(self, config, model: str, keep_last: int = 5,
                on_compact=None) -> str:
        """Compact conversation by summarizing older messages using the model.

        If *on_compact* is a callable, it is invoked with
        ``(summary_text, compacted_count)`` after a successful compaction.
        """
        if len(self.messages) <= keep_last + 1:
            return "Nothing to compact"

        system = self.messages[0]
        keep = self.messages[-keep_last:]
        compact_targets = self.messages[1:-keep_last]

        summary_text = "\n".join(
            f"{m['role']}: {str(m.get('content', ''))[:800]}"
            + (
                f"\n[key reasoning]: {str(m['reasoning_content'])[:200]}"
                if m.get("reasoning_content") else ""
            )
            for m in compact_targets
        )

        summary_prompt = (
            "Summarize the following conversation history concisely. "
            "Capture key decisions, code changes, file paths, and the user's goals:"
            f"\n\n{summary_text}"
        )

        try:
            from openai import OpenAI
            import httpx
            # Use the configured model for compaction, falling back to Flash.
            # Always prefer Flash if available — it's fast and cheap for summarisation.
            flash_id = "deepseek-v4-flash"
            compact_model = flash_id if getattr(config, "model", flash_id) != flash_id else flash_id
            compact_model = getattr(config, "model", flash_id) or flash_id
            # Override with Flash when the configured model is a reasoner —
            # summarisation doesn't benefit from chain-of-thought.
            if "reason" in compact_model.lower():
                compact_model = flash_id
            client = OpenAI(
                api_key=config.api_key,
                base_url=config.base_url,
                http_client=httpx.Client(timeout=30),
            )
            response = client.chat.completions.create(
                model=compact_model,
                messages=[{"role": "user", "content": summary_prompt}],
                max_tokens=1500,
            )
            summary = response.choices[0].message.content or ""
        except Exception as e:
            return f"Compaction failed: {e}"

        raw = [system, {
            "role": "system",
            "content": f"[Compacted conversation summary]: {summary}",
        }] + keep
        self.messages = self._drop_orphaned_tool_messages(raw)

        count = len(compact_targets)
        if callable(on_compact):
            try:
                on_compact(summary, count)
            except Exception:
                _log.warning("Compaction callback failed", exc_info=True)

        return f"Compacted {count} messages into a summary"
