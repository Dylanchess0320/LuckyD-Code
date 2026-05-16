"""API client for DeepSeek Chat with streaming and retry logic."""

import json
import time
import random
from typing import Any, Dict, Generator, List, Optional, Tuple

import httpx
from openai import OpenAI

from .retry import RetryableError, NonRetryableError, ModelNotFoundError
from .log import get_logger

_RETRY_MAX = 3
_RETRY_BASE_DELAY = 1.0
_RETRY_MAX_DELAY = 30.0

Event = Tuple[str, Any]
# Event types:
#   ("text", str)              - streamed text chunk
#   ("tool_calls", (list, str))  - (tool_calls, reasoning_content)
#   ("done", (str, str))       - (content, reasoning_content), no tool calls
#   ("error", str)             - error message

API_TIMEOUT = 60.0  # seconds


def _make_client(api_key: str, base_url: str) -> OpenAI:
    """Create an OpenAI client with timeout."""
    return OpenAI(
        api_key=api_key,
        base_url=base_url,
        http_client=httpx.Client(timeout=httpx.Timeout(API_TIMEOUT, connect=10.0)),
    )



def test_connection(api_key: str, base_url: str = "https://api.deepseek.com/v1",
                    model: str = "") -> tuple[bool, str]:  # pragma: no cover
    """Test the API connection. Returns (success, message)."""
    client = _make_client(api_key, base_url)
    # Use the provided model name, or fall back to the cheapest registered model
    test_model = model or _default_test_model()
    try:
        client.models.list()
        return True, "API connection OK"
    except Exception as e:
        err = str(e)
        if "401" in err or "authentication" in err.lower() or "invalid" in err.lower():
            return False, f"API key rejected: {err[:200]}"
        if "connect" in err.lower() or "timeout" in err.lower() or "dns" in err.lower():
            return False, f"Network error (cannot reach {base_url}): {err[:200]}"
        # models.list() might not work with all providers — fall back to a
        # minimal chat completion using the same client.
        try:
            response = client.chat.completions.create(
                model=test_model,
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=5,
                stream=False,
            )
            if response.choices:
                return True, "API connection OK"
            return False, "API returned empty response"
        except Exception as e2:
            return False, f"API error: {str(e2)[:200]}"


def _default_test_model() -> str:  # pragma: no cover
    """Return the cheapest model ID for connection testing, or a sensible default."""
    try:
        from .model_registry import ALL_MODELS_FLAT
        return ALL_MODELS_FLAT[0].id if ALL_MODELS_FLAT else "deepseek-v4-flash"
    except Exception:
        return "deepseek-v4-flash"


def _open_stream(  # pragma: no cover
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    model: str,
    api_key: str,
    base_url: str,
    max_tokens: int,
    temperature: float,
    provider: str = "",
):
    """Open the streaming HTTP connection and validate the status code.

    This is a **regular function** (not a generator) so that
    ``_call_with_retry`` can actually catch and retry HTTP errors.  The
    previous implementation (``_stream_chat_raw``) was a generator function:
    calling it returned a lazy iterator without executing any code, which
    made every ``try/except`` in ``_call_with_retry`` permanently unreachable.

    Returns ``(client, response_cm, response)``.  The caller is responsible
    for cleanup once iteration is complete::

        response_cm.__exit__(None, None, None)
        client.close()

    Raises ``RetryableError``, ``NonRetryableError``, or
    ``ModelNotFoundError`` so ``_call_with_retry`` can route correctly.
    """
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    body: Dict[str, Any] = {
        "model": model,
        "messages": _filter_messages(messages, provider),
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if tools:
        body["tools"] = tools

    client = httpx.Client(timeout=httpx.Timeout(API_TIMEOUT, connect=10.0))
    try:
        response_cm = client.stream("POST", url, json=body, headers=headers)
        response = response_cm.__enter__()
        if response.status_code != 200:
            err_detail = _parse_stream_error(response)
            response_cm.__exit__(None, None, None)
            client.close()
            raise _classify_http_error(response.status_code, err_detail)
        return client, response_cm, response
    except (RetryableError, NonRetryableError, ModelNotFoundError):
        # Re-raise classified errors — _call_with_retry decides whether to retry
        raise
    except Exception:
        client.close()
        raise


def _parse_stream_error(response: httpx.Response) -> str:
    """Extract error detail from a non-200 streaming response."""
    try:
        response.read()
        data: dict[str, Any] = response.json()
        return str(data.get("error", {}).get("message", str(response.text[:500])))
    except Exception:
        try:
            return str(response.text[:500])
        except Exception:
            return f"HTTP {response.status_code}"


def _classify_http_error(status_code: int, detail: str) -> Exception:
    """Classify an HTTP error into the appropriate exception type."""
    err_lower = detail.lower()
    if status_code == 400:
        if "model not exist" in err_lower or "model_not_exist" in err_lower:
            return ModelNotFoundError(detail)
        return NonRetryableError(detail)
    if status_code == 401:
        return NonRetryableError(f"Authentication failed (401). Check your API key: {detail[:200]}")
    if status_code == 403:
        return NonRetryableError(f"Access denied (403): {detail[:200]}")
    if status_code == 404:
        return NonRetryableError(f"Resource not found (404): {detail[:200]}")
    if status_code == 422:
        return NonRetryableError(f"Invalid request (422): {detail[:200]}")
    if status_code == 429:
        return RetryableError(f"Rate limited (429): {detail[:200]}")
    if status_code >= 500:
        return RetryableError(f"Server error ({status_code}): {detail[:200]}")
    return NonRetryableError(detail)


def _parse_sse_line(line: str) -> Optional[Dict[str, Any]]:
    """Parse a single SSE line from a streaming response."""
    line = line.strip()
    if not line:
        return None
    if line == "data: [DONE]":
        return {}
    if line.startswith("data: "):
        try:
            result: Dict[str, Any] = json.loads(line[6:])
            return result
        except json.JSONDecodeError:
            return None
    return None


def _filter_messages(messages: List[Dict[str, Any]], provider: str = "") -> List[Dict[str, Any]]:
    """Normalise messages for the target provider.

    DeepSeek: keep reasoning_content, ensure content is always set alongside it.
    Non-DeepSeek (Groq, Ollama, …): strip reasoning_content entirely — those
    APIs don't understand it and will error or silently corrupt the request.
    """
    is_deepseek = "deepseek" in provider.lower() if provider else True
    filtered = []
    for msg in messages:
        m = dict(msg)
        if m.get("role") == "assistant" and "reasoning_content" in m:
            if is_deepseek:
                if m.get("content") is None or "content" not in m:
                    m["content"] = ""
            else:
                del m["reasoning_content"]
        filtered.append(m)
    return filtered


def _count_unquoted(text: str, open_ch: str, close_ch: str) -> tuple[int, int]:
    """Count open_ch and close_ch occurrences that are outside string literals.

    Handles ``\\"`` escape sequences so braces/brackets embedded inside JSON
    string values are never counted.  Returns ``(open_count, close_count)``.
    """
    opens = closes = 0
    in_string = False
    escape = False
    for ch in text:
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if not in_string:
            if ch == open_ch:
                opens += 1
            elif ch == close_ch:
                closes += 1
    return opens, closes


def _close_unclosed_string(text: str) -> str:
    """If the text ends inside an unterminated string literal, close it.

    This must run before bracket-counting so that closing brackets/braces
    appended to fix an unclosed string are not themselves counted as
    structural characters on a subsequent repair pass.
    """
    in_string = False
    escape = False
    for ch in text:
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
    return text + '"' if in_string else text


def _repair_json(raw: str) -> str:
    """Attempt to repair common JSON issues in model-generated tool arguments.

    Reasoning models sometimes produce multiline string values or trailing
    commas that break JSON parsing. This tries to recover the intended JSON.

    All replacements are done *outside* string literals to avoid corrupting
    valid JSON that legitimately contains e.g. "}" inside a string value.

    The function is idempotent: if the input already parses as valid JSON it
    is returned unchanged, so calling it twice produces the same result.
    """
    raw = raw.strip()
    if not raw:
        return raw

    # Fast path — already valid JSON, nothing to repair.
    # This is also what makes the function idempotent: after one repair pass
    # the output is valid JSON, so a second pass returns it immediately.
    try:
        json.loads(raw)
        return raw
    except json.JSONDecodeError:
        pass

    # Remove trailing comma before closing brace/bracket (outside strings only)
    raw = _remove_trailing_commas(raw)

    # Close any unterminated string literal before counting brackets.
    # Without this, a bracket appended to close an open string would itself
    # be invisible to _count_unquoted (it lands inside the string), causing
    # the next repair pass to add yet another bracket.
    raw = _close_unclosed_string(raw)

    # Close unmatched braces/brackets — count only characters outside strings
    # so that values like {"key": "template {var}"} are never corrupted.
    open_braces, close_braces = _count_unquoted(raw, "{", "}")
    if open_braces > close_braces:
        raw += "}" * (open_braces - close_braces)

    open_brackets, close_brackets = _count_unquoted(raw, "[", "]")
    if open_brackets > close_brackets:
        raw += "]" * (open_brackets - close_brackets)

    return raw


def _remove_trailing_commas(text: str) -> str:
    """Remove trailing commas before ``}`` or ``]``, but only outside strings.

    Walks the text character-by-character tracking whether we're inside a
    double-quoted string (handling ``\"`` escapes), and only strips a
    comma when the immediately-following non-whitespace char is ``}`` or
    ``]`` and we are NOT inside a string.
    """
    result: list[str] = []
    in_string = False
    escape = False
    i = 0
    n = len(text)

    while i < n:
        ch = text[i]

        if escape:
            escape = False
            result.append(ch)
            i += 1
            continue

        if ch == "\\" and in_string:
            escape = True
            result.append(ch)
            i += 1
            continue

        if ch == '"':
            in_string = not in_string
            result.append(ch)
            i += 1
            continue

        if ch == "," and not in_string:
            # Look ahead past whitespace to see if next char is } or ]
            j = i + 1
            while j < n and text[j] in (" ", "\t", "\n", "\r"):
                j += 1
            if j < n and text[j] in ("}", "]"):
                # Trailing comma — skip it
                i += 1
                continue

        result.append(ch)
        i += 1

    return "".join(result)


def _call_with_retry(
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    model: str,
    api_key: str,
    base_url: str,
    max_tokens: int,
    temperature: float,
    provider: str = "",
):
    """Open the streaming connection with exponential-backoff retry on retryable errors.

    Delegates to ``_open_stream`` (a regular function) so that HTTP-level
    errors — rate limits (429), server errors (5xx), network timeouts — are
    raised during the call and can actually be caught and retried here.
    """
    logger = get_logger()
    delay = _RETRY_BASE_DELAY
    last_err: Exception = RuntimeError("Unknown error")

    for attempt in range(_RETRY_MAX + 1):
        try:
            return _open_stream(
                messages, tools, model, api_key, base_url, max_tokens, temperature, provider
            )
        except ModelNotFoundError:
            raise  # never retry — model doesn't exist
        except NonRetryableError:
            raise  # never retry — auth/bad-request etc.
        except RetryableError as e:
            last_err = e
            if attempt < _RETRY_MAX:
                jittered = delay * (0.5 + random.random() * 0.5)
                logger.warning(
                    "Retryable API error (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1, _RETRY_MAX, jittered, e,
                )
                time.sleep(jittered)  # pragma: no cover
                delay = min(delay * 2, _RETRY_MAX_DELAY)
        except Exception as e:
            last_err = e
            if attempt == 0:  # one grace retry for unclassified errors
                jittered = delay * (0.5 + random.random() * 0.5)
                logger.warning("Transient error, retrying once in %.1fs: %s", jittered, e)
                time.sleep(jittered)  # pragma: no cover
            else:
                raise

    raise last_err


def stream_chat(
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    model: str,
    api_key: str,
    base_url: str = "https://api.deepseek.com/v1",
    max_tokens: int = 4096,
    temperature: float = 0.7,
    provider: str = "",
) -> Generator[Event, None, None]:
    """Stream a chat completion, yielding text chunks and tool calls.

    Uses raw httpx (not the OpenAI SDK) so that vendor-specific fields like
    DeepSeek ``reasoning_content`` are preserved in the JSON payload.
    Retries automatically on rate-limits and transient server errors.
    """
    try:
        client, response_cm, response = _call_with_retry(
            messages, tools, model, api_key, base_url,
            max_tokens, temperature, provider,
        )
    except ModelNotFoundError as e:
        yield ("model_not_found", str(e))
        return
    except NonRetryableError as e:
        yield ("error", str(e))
        return
    except RetryableError as e:
        yield ("error", f"API request failed after {_RETRY_MAX} retries: {e}")
        return
    except Exception as e:
        yield ("error", f"API request failed: {e}")
        return

    content_parts: List[str] = []
    reasoning_parts: List[str] = []
    tool_call_deltas: Dict[int, Dict[str, str]] = {}

    try:
        for raw_line in response.iter_lines():
            line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
            chunk = _parse_sse_line(line)
            if chunk is None:
                continue
            if not chunk:
                # [DONE] signal
                break

            choices = chunk.get("choices")
            if not choices:
                continue

            choice = choices[0]
            delta = choice.get("delta", {})

            if delta is None:
                continue

            # Capture reasoning_content (DeepSeek thinking mode) so it can be
            # passed back in subsequent requests — the API requires it.
            reasoning = delta.get("reasoning_content")
            if reasoning:
                reasoning_parts.append(reasoning)
                yield ("reasoning", reasoning)

            content = delta.get("content")
            if content:
                content_parts.append(content)
                yield ("text", content)

            tool_calls_delta = delta.get("tool_calls")
            if tool_calls_delta:
                for tc in tool_calls_delta:
                    idx = tc.get("index", 0)
                    if idx not in tool_call_deltas:
                        tool_call_deltas[idx] = {"id": "", "name": "", "arguments": ""}
                    tc_id = tc.get("id")
                    if tc_id:
                        tool_call_deltas[idx]["id"] = tc_id
                    fn = tc.get("function", {})
                    fn_name = fn.get("name", "")
                    if fn_name:
                        tool_call_deltas[idx]["name"] += fn_name
                    fn_args = fn.get("arguments", "")
                    if fn_args:
                        tool_call_deltas[idx]["arguments"] += fn_args

        if tool_call_deltas:  # pragma: no cover
            tool_calls = []
            for idx in sorted(tool_call_deltas.keys()):
                d = tool_call_deltas[idx]
                tool_calls.append({
                    "id": d["id"],
                    "type": "function",
                    "function": {
                        "name": d["name"],
                        "arguments": d["arguments"],
                    },
                })
            reasoning_str = "".join(reasoning_parts) if reasoning_parts else ""
            yield ("tool_calls", (tool_calls, reasoning_str))
        else:
            content = "".join(content_parts)
            reasoning = "".join(reasoning_parts) if reasoning_parts else ""
            yield ("done", (content, reasoning))

    except Exception as e:
        yield ("error", f"Stream error: {e}")
    finally:  # pragma: no cover
        # Always release the HTTP connection, even if streaming was interrupted
        try:
            response_cm.__exit__(None, None, None)
        except Exception:
            pass
        try:
            client.close()
        except Exception:
            pass
