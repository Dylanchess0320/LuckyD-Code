"""Tests for luckyd_code.model_registry — model definitions and routing."""


from luckyd_code.model_registry import (
    ModelDef,
    ALL_MODELS_FLAT,
    TIER_MODEL_MAP,
    get_model_by_id,
    get_models_by_tier,
    format_model_list,
    _MODEL_TIERS,
)


class TestModelDef:
    """Tests for the ModelDef dataclass."""

    def test_default_values(self):
        """Default context_window should be 1M, costs 0."""
        m = ModelDef(id="test-model", name="Test", tier=1)
        assert m.id == "test-model"
        assert m.name == "Test"
        assert m.tier == 1
        assert m.context_window == 1_000_000
        assert m.cost_per_1k_input == 0.0
        assert m.cost_per_1k_output == 0.0
        assert m.strengths == []

    def test_strengths_defaults_to_empty_list(self):
        """Each instance gets its own strengths list (no shared mutable default)."""
        m1 = ModelDef(id="a", name="A", tier=1)
        m2 = ModelDef(id="b", name="B", tier=2)
        m1.strengths.append("fast")
        assert m2.strengths == []  # not affected

    def test_all_fields_set(self):
        """All fields can be set at construction."""
        m = ModelDef(
            id="deepseek-v4-flash",
            name="Flash",
            tier=1,
            strengths=["fast"],
            context_window=128000,
            cost_per_1k_input=0.0001,
            cost_per_1k_output=0.0002,
        )
        assert m.id == "deepseek-v4-flash"
        assert m.tier == 1
        assert m.context_window == 128000
        assert "fast" in m.strengths


class TestModelRegistry:
    """Tests for model registry functions."""

    def test_all_models_flat_not_empty(self):
        """ALL_MODELS_FLAT should contain at least one model."""
        assert len(ALL_MODELS_FLAT) > 0

    def test_all_models_flat_are_modeldef(self):
        """All entries in ALL_MODELS_FLAT should be ModelDef instances."""
        for m in ALL_MODELS_FLAT:
            assert isinstance(m, ModelDef)

    def test_get_model_by_id_returns_model(self):
        """get_model_by_id should return the correct model."""
        for m in ALL_MODELS_FLAT:
            found = get_model_by_id(m.id)
            assert found is not None
            assert found.id == m.id

    def test_get_model_by_id_unknown_returns_none(self):
        """get_model_by_id should return None for unknown models."""
        assert get_model_by_id("nonexistent-model") is None

    def test_tier_model_map_has_4_tiers(self):
        """TIER_MODEL_MAP should map tiers 1-4."""
        assert TIER_MODEL_MAP[1] is not None
        assert TIER_MODEL_MAP[2] is not None
        assert TIER_MODEL_MAP[3] is not None
        assert TIER_MODEL_MAP[4] is not None

    def test_tier_models_are_valid_ids(self):
        """Every tier model id should resolve via get_model_by_id."""
        for tier, model_id in TIER_MODEL_MAP.items():
            assert get_model_by_id(model_id) is not None, f"tier {tier} model '{model_id}' not found"

    def test_get_models_by_tier_returns_list(self):
        """get_models_by_tier should return list of models for each tier."""
        import luckyd_code.model_registry as _mr  # fresh ref avoids stale class after any reload
        for tier in range(1, 5):
            result = get_models_by_tier(tier)
            assert isinstance(result, list)
            assert len(result) > 0
            for m in result:
                assert isinstance(m, _mr.ModelDef)

    def test_model_tiers_reverse_map(self):
        """_MODEL_TIERS should be the reverse of TIER_MODEL_MAP."""
        assert isinstance(_MODEL_TIERS, dict)
        # Every key in _MODEL_TIERS should be a valid model id
        for mid in _MODEL_TIERS:
            assert get_model_by_id(mid) is not None

    def test_format_model_list(self):
        """format_model_list should return a non-empty string."""
        result = format_model_list()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_model_properties(self):
        """Verify known model properties."""
        flash = get_model_by_id("deepseek-v4-flash")
        assert flash is not None
        assert flash.tier == 1
        assert flash.cost_per_1k_input == 0.000140
        assert flash.cost_per_1k_output == 0.000280
        assert flash.context_window == 1_000_000

    def test_pro_model_properties(self):
        """Verify Pro model properties."""
        pro = get_model_by_id("deepseek-v4-pro")
        assert pro is not None
        assert pro.tier == 3
        assert pro.cost_per_1k_input == 0.001740
        assert pro.cost_per_1k_output == 0.003480
