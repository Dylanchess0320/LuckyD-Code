"""Auto-router — classify prompt complexity and pick the right model tier.

Uses a 4-tier classification system:
  Tier 1 — Ultra Fast / Cheap: simple chat, quick Q&A
  Tier 2 — Balanced: general purpose coding and chat
  Tier 3 — Reasoner: debugging, architecture, complex analysis
  Tier 4 — Code-Specialized: large refactors, code generation, reviews

The router escalates up tiers as task complexity increases.
"""

import hashlib
import os as _os_router
import re
import atexit
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from typing import Optional

from .model_registry import (
    get_models_by_tier,
    ALL_MODELS_FLAT,
    format_model_list,
    TIER_MODEL_MAP,
)

# Provider model tier → model mapping (single source of truth lives in model_registry)
TIER_MODELS: dict[int, str] = TIER_MODEL_MAP

# Model fallback order when a model is not found
FALLBACK_MODELS: list[str] = [m.id for m in ALL_MODELS_FLAT]

# Fallback models specifically for DeepSeek-backed providers when the primary model fails.
DEEPSEEK_FALLBACK_MODELS: list[str] = [
    "deepseek-v4-flash",   # fast, cheaper primary
    "deepseek-v4-pro",     # stronger general model
    "deepseek-reasoner",   # reasoning-optimized
    "deepseek-chat",       # general chat
    "deepseek-coder",      # code-focused
]
# Prompts that trigger reasoner (ordered by strength)
_REASONER_KEYWORDS = [
    "debug this", "fix this bug", "why is this broken", "what's wrong with",
    "optimize", "refactor", "redesign", "migrate",
    "security vulnerability", "race condition", "memory leak",
    "architecture decision", "design pattern", "trade-off",
    "complex", "complicated", "difficult", "hard problem",
    "review this code", "code review",
]

# Regex patterns catch paraphrased queries that keyword matches miss
_REASONER_PATTERNS = [
    r'\b(debug|broke|broken|crash|crashed|crashing)\b',
    r'\bfix\s+(this|the|bug|issue|problem)\b',
    r'\bwhy\s+(is|does|did|can\'t|won\'t|would)\b',
    r'\b(not\s+working|doesn\'t\s+work|won\'t\s+run|fails?\s+to)\b',
    r'\b(can\'t\s+figure|can\'t\s+understand)\b',
]

# Keywords that indicate heavy reasoning needed (tier 4)
_HEAVY_KEYWORDS = [
    "large refactor", "major redesign", "complex architecture",
    "security audit", "performance optimization",
    "migration plan", "full rewrite",
]

# Tool names that indicate the prompt is part of a complex workflow
_COMPLEX_TOOLS = {"Write", "Edit", "GitCommit", "GitPush", "GitPR", "Bash"}

# Thresholds
LONG_PROMPT_CHARS = 300
VERY_LONG_PROMPT_CHARS = 800
TOOL_CALL_THRESHOLD = 3        # After N tool calls, escalate to tier 3
HEAVY_TOOL_CALL_THRESHOLD = 8  # After N tool calls, escalate to tier 4

# LLM classifier timeout — set to zero to skip the background API call entirely.
# The heuristic classifier is free and fast; the LLM classifier was a marginal
# accuracy improvement at the cost of a full API round-trip per unique prompt.
_LLM_CLASSIFY_TIMEOUT = 0.0

# Shared thread pool for background LLM classification calls (daemon so it
# doesn't block process exit).
_classify_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="router-llm")
# Ensure the pool is cleanly shut down at process exit (non-blocking so the
# main thread is never held waiting for in-flight classification calls).
atexit.register(_classify_executor.shutdown, wait=False)


def _file_size_tier(text: str) -> int:
    """Check if the prompt references a local file; escalate tier based on line count.

    Only files that resolve to a path *within the current working directory*
    are opened — this prevents an adversarial user from tricking the router
    into reading arbitrary paths (e.g. ``../../.env``) embedded in their prompt.
    """
    cwd = _os_router.path.realpath(_os_router.getcwd())
    paths = re.findall(r'[\w./\\-]+\.\w{1,5}', text)
    max_tier = 1
    for p in paths:
        try:
            # Resolve the candidate path and confirm it stays inside cwd
            resolved = _os_router.path.realpath(p)
            if not resolved.startswith(cwd + _os_router.sep) and resolved != cwd:
                continue  # path escapes the project root — skip
            if _os_router.path.isfile(resolved):
                with open(resolved, errors='ignore') as fh:
                    lines = sum(1 for _ in fh)
                if lines > 500:
                    max_tier = max(max_tier, 4)
                elif lines > 200:
                    max_tier = max(max_tier, 3)
                elif lines > 80:
                    max_tier = max(max_tier, 2)
        except OSError:
            pass
    return max_tier


# In-process cache: prompt_hash → tier int.  Avoids a blocking API call on
# repeated or similar prompts.  Capped at 512 entries to bound memory use.
# Protected by _tier_cache_lock — the cache is written from a background
# thread (the LLM classifier) and read from the main thread concurrently.
_tier_cache: dict[str, int] = {}
_tier_cache_lock = threading.Lock()
_TIER_CACHE_MAX = 512


def _llm_classify_worker(prompt_snippet: str, config) -> int:  # pragma: no cover
    """Blocking worker that calls the LLM to classify a prompt (runs in thread pool)."""
    _CLASSIFY_PROMPT = (
        "Rate this coding task 1-4:\n"
        "1 = simple Q&A or single-line change\n"
        "2 = general coding, explanation, or small feature\n"
        "3 = debugging, architecture, complex analysis, or multi-file reasoning\n"
        "4 = large refactor, full rewrite, security audit, or migration\n"
        "Reply with ONLY the single digit, nothing else.\n"
        f"Task: {prompt_snippet}"
    )
    from openai import OpenAI
    import httpx
    client = OpenAI(
        api_key=config.api_key,
        base_url=config.base_url,
        http_client=httpx.Client(timeout=8),
    )
    resp = client.chat.completions.create(
        model="deepseek-v4-flash",
        messages=[{"role": "user", "content": _CLASSIFY_PROMPT}],
        max_tokens=2,
        temperature=0.0,
    )
    digit = (resp.choices[0].message.content or "").strip()
    return max(1, min(4, int(digit)))


def classify_tier_llm(user_text: str, config) -> int:
    """Classify a prompt using the LLM, without blocking the caller.

    Strategy:
    1. Compute heuristic tier immediately (< 1ms).
    2. Check the cache — if we've seen this prompt before, return cached result.
    3. Submit the LLM call to a background thread pool.
    4. Wait up to ``_LLM_CLASSIFY_TIMEOUT`` seconds for the result.
    5. If it arrives in time, cache it and return it.
    6. If it times out, return the heuristic result and let the thread keep
       running — the result will be written to the cache for future identical
       queries (zero extra cost on repeated prompts).
    """
    prompt_snippet = user_text[:600]
    cache_key = hashlib.md5(prompt_snippet.encode("utf-8", errors="replace")).hexdigest()

    # Cache hit — no API call needed (lock guards compound check+get)
    with _tier_cache_lock:
        if cache_key in _tier_cache:
            return _tier_cache[cache_key]

    # Compute heuristic immediately as the fallback
    heuristic = classify_tier(user_text)

    def _background_classify() -> int:  # pragma: no cover
        try:
            result = _llm_classify_worker(prompt_snippet, config)
        except Exception:
            result = heuristic
        # Always write to cache (even if we timed out below, future calls benefit)
        with _tier_cache_lock:
            if len(_tier_cache) >= _TIER_CACHE_MAX:
                oldest = list(_tier_cache.keys())[:64]
                for k in oldest:
                    del _tier_cache[k]
            _tier_cache[cache_key] = result
        return result

    future = _classify_executor.submit(_background_classify)
    try:
        return future.result(timeout=_LLM_CLASSIFY_TIMEOUT)
    except (FutureTimeoutError, Exception):
        # Timed out or errored — return heuristic, background thread caches result
        return heuristic


def classify_tier(user_text: str, recent_tool_count: int = 0) -> int:
    """Classify a prompt into a model tier (1-4) using pure heuristics (no API call).

    Returns:
        1 = fast/cheap (simple chat)
        2 = balanced (general purpose)
        3 = reasoner (debugging, architecture)
        4 = code-specialist (heavy refactoring)
    """
    text_lower = user_text.lower()

    # File-size signal: referenced local files are a strong complexity indicator
    file_tier = _file_size_tier(user_text)

    # Heavy keywords → tier 4 (always checked, even for short prompts)
    for kw in _HEAVY_KEYWORDS:
        if kw in text_lower:
            return 4

    # Check for heavy reasoner keywords → tier 3 (always checked)
    for kw in _REASONER_KEYWORDS:
        if kw in text_lower:
            return 3

    # Regex fallback catches paraphrased queries keyword match misses
    for pattern in _REASONER_PATTERNS:
        if re.search(pattern, text_lower):
            return 3

    # Very short prompts: return file_tier unless keyword matched above
    if len(user_text) < 20:
        return file_tier

    # Very long + code-heavy → tier 3
    if len(user_text) > VERY_LONG_PROMPT_CHARS:
        if "```" in user_text or re.search(r'\b(def|function|class|import|const)\b', text_lower):
            return 3
        return 2

    # Code-heavy prompts (contains code blocks or file paths) → tier 2
    code_indicators = 0
    if "```" in user_text:
        code_indicators += 1
    if re.search(r'[\\/][\w.]+\.\w{1,4}', user_text):
        code_indicators += 1
    if re.search(r'\b(function|class|def|import|const|let|var)\b', text_lower):
        code_indicators += 1
    if re.search(r'error|exception|fail|crash|stack.trace', text_lower):
        code_indicators += 1

    if code_indicators >= 3:
        return 3
    if code_indicators >= 1:
        return 2

    # Long prompts with details → tier 2
    if len(user_text) > LONG_PROMPT_CHARS:
        return max(2, file_tier)

    # Default: tier 1 for simple chat, but respect file-size floor
    return max(1, file_tier)


def select_model(user_text: str, recent_tool_count: int = 0,
                 preferred_model: Optional[str] = None,
                 tier_override: Optional[int] = None) -> str:
    """Select the best model based on task complexity and tool usage."""
    if tier_override is not None:
        tier = tier_override
    else:
        base_tier = classify_tier(user_text, recent_tool_count)
        if recent_tool_count >= HEAVY_TOOL_CALL_THRESHOLD:
            tier = min(base_tier + 2, 4)
        elif recent_tool_count >= TOOL_CALL_THRESHOLD:
            tier = min(base_tier + 1, 4)
        else:
            tier = base_tier

    tier_models = get_models_by_tier(tier)

    if not tier_models:  # pragma: no cover
        return preferred_model or ALL_MODELS_FLAT[0].id

    if preferred_model:  # pragma: no cover
        for m in tier_models:
            if m.id == preferred_model:
                return m.id
        return preferred_model

    return tier_models[0].id


def should_use_reasoner(user_text: str, recent_tool_count: int = 0,
                        auto_route_enabled: bool = True) -> bool:
    """Returns True if tier 3+ model should be used."""
    if not auto_route_enabled:
        return False
    tier = classify_tier(user_text, recent_tool_count)
    effective_tier = tier
    if recent_tool_count >= HEAVY_TOOL_CALL_THRESHOLD:
        effective_tier = min(tier + 2, 4)
    elif recent_tool_count >= TOOL_CALL_THRESHOLD:
        effective_tier = min(tier + 1, 4)
    return effective_tier >= 3


def get_tier_description(tier: int) -> str:
    """Get a human-readable description of a tier."""
    descriptions = {
        1: "Fast/Cheap (simple chat, quick queries)",
        2: "Balanced (general purpose coding & chat)",
        3: "Reasoner (debugging, architecture, complex analysis)",
        4: "Code-Specialist (large refactors, code generation)",
    }
    return descriptions.get(tier, f"Tier {tier}")


# ---------------------------------------------------------------------------
# Effort-level helpers
# ---------------------------------------------------------------------------

# Effort level → (tier_floor, max_tokens, temperature)
EFFORT_SETTINGS: dict[str, tuple[int, int, float]] = {
    "low":    (1, 2048,  0.5),
    "normal": (2, 4096,  0.3),
    "high":   (3, 8192,  0.2),
    "max":    (4, 16384, 0.1),
}

EFFORT_LABELS: dict[str, str] = {
    "low":    "low    — fast & cheap, tier 1 floor",
    "normal": "normal — balanced, tier 2 floor (default)",
    "high":   "high   — reasoner, tier 3 floor, 8K tokens",
    "max":    "max    — pro model always, tier 4, 16K tokens",
}


def apply_effort(config, effort: str) -> str:  # pragma: no cover
    """Apply an effort level to a Config object in-place.

    Updates ``config.effort``, ``config.max_tokens``, and
    ``config.temperature``, then saves the config.

    Returns a human-readable confirmation string.
    """
    effort = effort.lower().strip()
    if effort not in EFFORT_SETTINGS:
        valid = ", ".join(EFFORT_SETTINGS)
        return f"Unknown effort level '{effort}'. Valid: {valid}"

    _, max_tokens, temperature = EFFORT_SETTINGS[effort]
    config.effort = effort
    config.max_tokens = max_tokens
    config.temperature = temperature
    config.save()
    return EFFORT_LABELS[effort]


def effort_tier_floor(effort: str) -> int:
    """Return the minimum tier enforced by the current effort level."""
    return EFFORT_SETTINGS.get(effort, EFFORT_SETTINGS["normal"])[0]


def show_model_info() -> str:
    """Return a formatted string of all available models and tiers."""
    return format_model_list()


def show_current_routing(user_text: str, recent_tool_count: int = 0,
                         preferred_model: Optional[str] = None) -> str:
    """Show the routing decision for a given input."""
    tier = classify_tier(user_text, recent_tool_count)

    if recent_tool_count >= HEAVY_TOOL_CALL_THRESHOLD:
        effective_tier = min(tier + 2, 4)
    elif recent_tool_count >= TOOL_CALL_THRESHOLD:
        effective_tier = min(tier + 1, 4)
    else:
        effective_tier = tier

    model_id = select_model(user_text, recent_tool_count, preferred_model)

    return (
        f"Classification: Tier {tier} → Effective Tier {effective_tier}\n"
        f"Selected Model: {model_id}\n"
        f"Description: {get_tier_description(effective_tier)}\n"
        f"Tool Calls: {recent_tool_count}"
    )


# ------------------------------------------------------------------ #
#  Shared routing helpers (used by both CLI and Web UI)
# ------------------------------------------------------------------ #

@dataclass
class RoutingResult:
    """Result of a model routing decision."""
    model: str
    tier: int
    tier_description: str
    tier_changed: bool = False


def resolve_initial_route(
    user_text: str,
    tool_call_count: int,
    provider: str,
    preferred_model: str,
    auto_route: bool = True,
    config=None,
) -> RoutingResult:
    """Determine the initial model tier for a user message."""
    if not auto_route:
        return RoutingResult(model=preferred_model, tier=2,
                             tier_description=get_tier_description(2))

    if config is not None:  # pragma: no cover
        base_tier = classify_tier_llm(user_text, config)
    else:
        base_tier = classify_tier(user_text, tool_call_count)

    # Enforce effort floor — never route below the effort-level minimum
    if config is not None:
        floor = effort_tier_floor(getattr(config, "effort", "normal"))
        base_tier = max(base_tier, floor)

    new_model = TIER_MODELS.get(base_tier, ALL_MODELS_FLAT[0].id)

    tier_changed = new_model != preferred_model
    return RoutingResult(
        model=new_model,
        tier=base_tier,
        tier_description=get_tier_description(base_tier),
        tier_changed=tier_changed,
    )


def escalate_tier(
    user_text: str,
    tool_call_count: int,
    provider: str,
    preferred_model: str,
    current_model: str,
    current_tier: int,
    auto_route: bool = True,
) -> RoutingResult:
    """Re-evaluate and possibly escalate the model tier mid-conversation."""
    if not auto_route:
        return RoutingResult(model=current_model, tier=current_tier,
                             tier_description=get_tier_description(current_tier))

    base_tier = classify_tier(user_text, tool_call_count)

    if tool_call_count >= HEAVY_TOOL_CALL_THRESHOLD:
        effective_tier = 4
    elif tool_call_count >= TOOL_CALL_THRESHOLD:
        effective_tier = min(base_tier + 1, 4)
    else:
        effective_tier = base_tier

    new_model = TIER_MODELS.get(effective_tier, ALL_MODELS_FLAT[0].id)

    tier_changed = new_model != current_model
    return RoutingResult(
        model=new_model,
        tier=effective_tier,
        tier_description=get_tier_description(effective_tier),
        tier_changed=tier_changed,
    )
