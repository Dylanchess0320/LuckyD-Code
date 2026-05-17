"""Tests for luckyd_code.__init__ lazy subpackage imports (lines 30-34)."""
from __future__ import annotations

import importlib
import sys
import types
from unittest.mock import MagicMock, patch

import pytest


class TestLazySubpackageImports:
    def test_getattr_returns_memory_module(self):
        """Accessing luckyd_code.memory via getattr triggers lazy import."""
        import luckyd_code
        # After import, memory should be accessible (may already be cached)
        mem = luckyd_code.memory
        assert mem is not None
        # Subsequent access uses the cache (no re-import)
        mem2 = luckyd_code.memory
        assert mem is mem2

    def test_getattr_returns_tools_module(self):
        """Accessing luckyd_code.tools via getattr triggers lazy import."""
        import luckyd_code
        tools = luckyd_code.tools
        assert tools is not None

    def test_getattr_raises_for_unknown_attribute(self):
        """Unknown attributes raise AttributeError."""
        import luckyd_code
        with pytest.raises(AttributeError, match="no attribute"):
            _ = luckyd_code.nonexistent_attribute_xyz

    def test_getattr_caches_module_after_first_access(self):
        """Once loaded, the module is stored in globals() for instant re-access."""
        import luckyd_code
        # Access to prime the cache
        _ = luckyd_code.settings
        # The module should now be in luckyd_code's namespace directly
        assert "settings" in vars(luckyd_code)

    def test_all_lazy_subpackages_importable(self):
        """All subpackages listed in _LAZY_SUBPACKAGES can be imported."""
        import luckyd_code
        for name in luckyd_code._LAZY_SUBPACKAGES:
            mod = getattr(luckyd_code, name)
            assert mod is not None, f"Lazy subpackage {name!r} failed to import"
