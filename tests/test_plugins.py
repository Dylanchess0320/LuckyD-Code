"""Tests for the plugin discovery and loading system (plugins.py)."""

import textwrap
from unittest.mock import MagicMock, patch


from luckyd_code.plugins import discover_plugins, load_plugin, load_all_plugins
from luckyd_code.tools.registry import ToolRegistry


# ---------------------------------------------------------------------------
# discover_plugins
# ---------------------------------------------------------------------------

class TestDiscoverPlugins:
    def test_returns_empty_when_dir_missing(self, tmp_path):
        missing = tmp_path / "plugins"
        with patch("luckyd_code.plugins.PLUGIN_DIR", missing):
            result = discover_plugins()
        assert result == []

    def test_returns_py_files(self, tmp_path):
        plugin_dir = tmp_path / "plugins"
        plugin_dir.mkdir()
        (plugin_dir / "alpha.py").touch()
        (plugin_dir / "beta.py").touch()
        (plugin_dir / "README.md").touch()

        with patch("luckyd_code.plugins.PLUGIN_DIR", plugin_dir):
            result = discover_plugins()

        names = [p.name for p in result]
        assert "alpha.py" in names
        assert "beta.py" in names
        assert "README.md" not in names

    def test_returns_sorted_list(self, tmp_path):
        plugin_dir = tmp_path / "plugins"
        plugin_dir.mkdir()
        for name in ("z_last.py", "a_first.py", "m_mid.py"):
            (plugin_dir / name).write_text("", encoding="utf-8")

        with patch("luckyd_code.plugins.PLUGIN_DIR", plugin_dir):
            result = discover_plugins()

        names = [p.name for p in result]
        assert names == sorted(names)


# ---------------------------------------------------------------------------
# load_plugin
# ---------------------------------------------------------------------------

class TestLoadPlugin:
    def test_valid_plugin_returns_register_fn(self, tmp_path):
        plugin = tmp_path / "good.py"
        plugin.write_text(
            textwrap.dedent("""\
                def register(registry):
                    pass
            """),
            encoding="utf-8",
        )
        fn = load_plugin(plugin)
        assert callable(fn)

    def test_plugin_without_register_returns_none(self, tmp_path):
        plugin = tmp_path / "noregister.py"
        plugin.write_text("X = 1\n", encoding="utf-8")
        fn = load_plugin(plugin)
        assert fn is None

    def test_syntax_error_returns_none(self, tmp_path):
        plugin = tmp_path / "broken.py"
        plugin.write_text("def register(: \n    pass\n", encoding="utf-8")
        fn = load_plugin(plugin)
        assert fn is None

    def test_import_error_returns_none(self, tmp_path):
        plugin = tmp_path / "badimport.py"
        plugin.write_text(
            "import nonexistent_package_xyz\ndef register(r): pass\n",
            encoding="utf-8",
        )
        fn = load_plugin(plugin)
        assert fn is None

    def test_nonexistent_path_returns_none(self, tmp_path):
        result = load_plugin(tmp_path / "does_not_exist.py")
        assert result is None


# ---------------------------------------------------------------------------
# load_all_plugins
# ---------------------------------------------------------------------------

class TestLoadAllPlugins:
    def test_empty_dir_loads_zero_plugins(self, tmp_path):
        plugin_dir = tmp_path / "plugins"
        plugin_dir.mkdir()
        registry = MagicMock(spec=ToolRegistry)

        with patch("luckyd_code.plugins.PLUGIN_DIR", plugin_dir):
            count = load_all_plugins(registry)

        assert count == 0
        registry.register.assert_not_called()

    def test_valid_plugin_is_registered(self, tmp_path):
        plugin_dir = tmp_path / "plugins"
        plugin_dir.mkdir()
        plugin = plugin_dir / "hello.py"
        plugin.write_text(
            textwrap.dedent("""\
                def register(registry):
                    registry.register("hello_tool")
            """),
            encoding="utf-8",
        )
        registry = MagicMock()

        with patch("luckyd_code.plugins.PLUGIN_DIR", plugin_dir):
            count = load_all_plugins(registry)

        assert count == 1
        registry.register.assert_called_once_with("hello_tool")

    def test_failing_register_does_not_raise(self, tmp_path):
        plugin_dir = tmp_path / "plugins"
        plugin_dir.mkdir()
        plugin = plugin_dir / "crasher.py"
        plugin.write_text(
            textwrap.dedent("""\
                def register(registry):
                    raise RuntimeError("register exploded")
            """),
            encoding="utf-8",
        )
        registry = MagicMock()

        with patch("luckyd_code.plugins.PLUGIN_DIR", plugin_dir):
            count = load_all_plugins(registry)

        assert count == 0

    def test_mixed_valid_and_invalid_plugins(self, tmp_path):
        plugin_dir = tmp_path / "plugins"
        plugin_dir.mkdir()

        (plugin_dir / "good.py").write_text(
            "def register(r): r.register('good')\n", encoding="utf-8"
        )
        (plugin_dir / "bad.py").write_text(
            "def register(r): raise ValueError('boom')\n", encoding="utf-8"
        )
        (plugin_dir / "noregister.py").write_text("X = 1\n", encoding="utf-8")

        registry = MagicMock()
        with patch("luckyd_code.plugins.PLUGIN_DIR", plugin_dir):
            count = load_all_plugins(registry)

        assert count == 1
        registry.register.assert_called_once_with("good")

    def test_missing_dir_loads_zero_plugins(self, tmp_path):
        missing = tmp_path / "plugins"
        registry = MagicMock()

        with patch("luckyd_code.plugins.PLUGIN_DIR", missing):
            count = load_all_plugins(registry)

        assert count == 0
