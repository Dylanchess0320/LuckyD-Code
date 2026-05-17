"""Model registry — defines available models with capabilities, costs, and tiers.

Each model has:
- id: DeepSeek model identifier
- name: Human-readable name
- tier: Lowest tier this model serves (1-4)
- strengths: list of task categories it excels at
- context_window: max context in tokens
- cost_per_1k_input: approximate cost per 1K input tokens (USD)
- cost_per_1k_output: approximate cost per 1K output tokens (USD)

Tier system:
  Tier 1 — Ultra Fast / Cheap: simple chat, quick Q&A, simple edits
  Tier 2 — Balanced: general purpose coding and chat
  Tier 3 — Reasoner: debugging, architecture, complex analysis
  Tier 4 — Code/Heavy: large refactors, code generation, heavy reasoning

Each physical model appears exactly once. The router maps tier → model id;
multiple tiers can map to the same model id without duplicating ModelDef objects.
"""

from dataclasses import dataclass, field

__all__ = [
    "ModelDef",
    "FLASH",
    "PRO",
    "ALL_MODELS_FLAT",
    "TIER_MODEL_MAP",
    "get_model_by_id",
    "get_models_by_tier",
    "get_unique_model_count",
    "get_models_by_strength",
    "format_model_list",
]


@dataclass
class ModelDef:
    id: str
    name: str
    tier: int  # primary/lowest tier this model is used for
    strengths: list[str] = field(default_factory=list)
    context_window: int = 1_000_000
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0


# ─── Canonical model definitions (each model appears exactly ONCE) ───

FLASH = ModelDef(
    id="deepseek-v4-flash",
    name="DeepSeek V4 Flash",
    tier=1,
    strengths=["chat", "quick_qa", "fast_coding", "simple_edits", "coding", "analysis", "general"],
    context_window=1_000_000,
    cost_per_1k_input=0.000140,
    cost_per_1k_output=0.000280,
)

PRO = ModelDef(
    id="deepseek-v4-pro",
    name="DeepSeek V4 Pro",
    tier=3,
    strengths=[
        "reasoning", "debugging", "math", "logic", "complex_analysis",
        "architecture", "code_generation", "refactoring", "complex_code",
    ],
    context_window=1_000_000,
    cost_per_1k_input=0.001740,
    cost_per_1k_output=0.003480,
)

# All unique models, ordered by capability (cheapest first)
ALL_MODELS_FLAT: list[ModelDef] = [FLASH, PRO]

# Tier → model id mapping.  Tiers 1-2 use Flash; tiers 3-4 use Pro.
# This is the single source of truth for routing decisions.
TIER_MODEL_MAP: dict[int, str] = {
    1: FLASH.id,
    2: FLASH.id,
    3: PRO.id,
    4: PRO.id,
}

# Reverse map: model id → list of tiers it serves
_MODEL_TIERS: dict[str, list[int]] = {}
for _tier, _mid in TIER_MODEL_MAP.items():
    _MODEL_TIERS.setdefault(_mid, []).append(_tier)


def get_model_by_id(model_id: str) -> ModelDef | None:
    """Find a model definition by its ID."""
    for m in ALL_MODELS_FLAT:
        if m.id == model_id:
            return m
    return None


def get_models_by_tier(tier: int) -> list[ModelDef]:
    """Return the single model that serves a given tier (wrapped in a list for API compat)."""
    mid = TIER_MODEL_MAP.get(tier)
    if not mid:
        return []
    m = get_model_by_id(mid)
    return [m] if m else []


def get_unique_model_count() -> int:
    """Count physically distinct models (not tier slots)."""
    return len(ALL_MODELS_FLAT)


def get_models_by_strength(strength: str, min_tier: int = 1, max_tier: int = 4) -> list[ModelDef]:
    """Get models that have a specific strength and serve at least one tier in range."""
    results = []
    seen: set[str] = set()
    for tier in range(min_tier, max_tier + 1):
        mid = TIER_MODEL_MAP.get(tier)
        if not mid or mid in seen:
            continue
        m = get_model_by_id(mid)
        if m and strength in m.strengths:
            results.append(m)
            seen.add(mid)
    return results


def format_model_list() -> str:
    """Return a human-readable list of all registered models and their tier assignments."""
    lines = [f"🌐 Model Registry: {get_unique_model_count()} models\n"]
    tier_names = {1: "Fast/Cheap", 2: "Balanced", 3: "Reasoner", 4: "Code-Specialist"}
    for m in ALL_MODELS_FLAT:
        tiers = _MODEL_TIERS.get(m.id, [])
        tier_labels = ", ".join(f"Tier {t} ({tier_names[t]})" for t in sorted(tiers))
        cost_in = f"${m.cost_per_1k_input * 1000:.4f}"
        cost_out = f"${m.cost_per_1k_output * 1000:.4f}"
        lines.append(f"  • {m.name} ({m.id})")
        lines.append(f"    Serves: {tier_labels}")
        lines.append(f"    Cost:   {cost_in}/1K input · {cost_out}/1K output")
        lines.append(f"    Context: {m.context_window:,} tokens")
        lines.append("")
    return "\n".join(lines)
