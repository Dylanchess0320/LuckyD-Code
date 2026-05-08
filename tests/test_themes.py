"""Tests for the theme system (themes.py)."""

from rich.theme import Theme

from luckyd_code.themes import (
    DARK_THEME,
    LIGHT_THEME,
    THEMES,
    get_theme,
)

_REQUIRED_KEYS = {
    "info", "warning", "error", "success", "dim", "code", "title",
    "subtitle", "tool", "tool_result", "prompt", "hl", "path",
    "number", "keyword",
}


class TestThemeObjects:
    def test_dark_theme_is_rich_theme(self):
        assert isinstance(DARK_THEME, Theme)

    def test_light_theme_is_rich_theme(self):
        assert isinstance(LIGHT_THEME, Theme)

    def test_dark_theme_has_required_keys(self):
        missing = _REQUIRED_KEYS - set(DARK_THEME.styles.keys())
        assert not missing, f"DARK_THEME missing keys: {missing}"

    def test_light_theme_has_required_keys(self):
        missing = _REQUIRED_KEYS - set(LIGHT_THEME.styles.keys())
        assert not missing, f"LIGHT_THEME missing keys: {missing}"

    def test_dark_and_light_are_distinct(self):
        assert DARK_THEME is not LIGHT_THEME


class TestThemesDict:
    def test_themes_contains_dark(self):
        assert "dark" in THEMES

    def test_themes_contains_light(self):
        assert "light" in THEMES

    def test_themes_values_are_theme_instances(self):
        for key, value in THEMES.items():
            assert isinstance(value, Theme), f"THEMES[{key!r}] is not a Theme"

    def test_themes_maps_to_correct_objects(self):
        assert THEMES["dark"] is DARK_THEME
        assert THEMES["light"] is LIGHT_THEME


class TestGetTheme:
    def test_returns_dark_by_default(self):
        assert get_theme() is DARK_THEME

    def test_dark_name_returns_dark(self):
        assert get_theme("dark") is DARK_THEME

    def test_light_name_returns_light(self):
        assert get_theme("light") is LIGHT_THEME

    def test_unknown_name_falls_back_to_dark(self):
        result = get_theme("neon_rainbow")
        assert result is DARK_THEME

    def test_empty_string_falls_back_to_dark(self):
        assert get_theme("") is DARK_THEME

    def test_case_sensitive_unknown_falls_back(self):
        assert get_theme("Dark") is DARK_THEME
