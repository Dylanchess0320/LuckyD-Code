"""Tests for file_watcher.py — watchdog-based background file watcher."""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from luckyd_code.file_watcher import FileWatcher


# ---------------------------------------------------------------------------
# Construction / defaults
# ---------------------------------------------------------------------------

class TestFileWatcherInit:
    def test_default_root_is_cwd(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        fw = FileWatcher()
        assert fw.root == tmp_path.resolve()

    def test_explicit_root(self, tmp_path):
        fw = FileWatcher(root=str(tmp_path))
        assert fw.root == tmp_path.resolve()

    def test_default_debounce(self):
        fw = FileWatcher()
        assert fw.debounce_seconds == 3.0

    def test_custom_debounce(self):
        fw = FileWatcher(debounce_seconds=1.5)
        assert fw.debounce_seconds == 1.5

    def test_on_change_callback_stored(self):
        cb = MagicMock()
        fw = FileWatcher(on_change=cb)
        assert fw.on_change is cb

    def test_not_running_initially(self):
        fw = FileWatcher()
        assert fw.is_running is False

    def test_watched_exts_includes_python(self):
        fw = FileWatcher()
        assert ".py" in fw._watched_exts

    def test_watched_exts_includes_common_types(self):
        fw = FileWatcher()
        for ext in (".ts", ".json", ".yaml", ".md", ".rs"):
            assert ext in fw._watched_exts


# ---------------------------------------------------------------------------
# start / stop
# ---------------------------------------------------------------------------

class TestStartStop:
    def test_start_sets_running(self):
        fw = FileWatcher()
        with patch.object(fw, "_try_watchdog", return_value=False), \
             patch.object(fw, "_poll_loop"):
            fw.start()
            assert fw.is_running is True
            fw.stop()

    def test_start_twice_is_idempotent(self):
        fw = FileWatcher()
        with patch.object(fw, "_try_watchdog", return_value=False), \
             patch.object(fw, "_poll_loop"):
            fw.start()
            fw.start()  # second call should be a no-op
            assert fw.is_running is True
            fw.stop()

    def test_stop_clears_running(self):
        fw = FileWatcher()
        with patch.object(fw, "_try_watchdog", return_value=False), \
             patch.object(fw, "_poll_loop"):
            fw.start()
            fw.stop()
        assert fw.is_running is False

    def test_stop_without_start_is_safe(self):
        fw = FileWatcher()
        fw.stop()  # must not raise

    def test_stop_joins_poll_thread(self):
        """Thread should be cleaned up after stop()."""
        fw = FileWatcher()
        with patch.object(fw, "_try_watchdog", return_value=False):
            # Use a real thread that immediately exits
            def _quick_loop():
                fw._stop_event.wait()

            with patch.object(fw, "_poll_loop", side_effect=_quick_loop):
                fw.start()
                thread = fw._thread
                fw.stop()
        assert thread is not None
        assert not thread.is_alive()


# ---------------------------------------------------------------------------
# pause / resume
# ---------------------------------------------------------------------------

class TestPauseResume:
    def test_pause_sets_flag(self):
        fw = FileWatcher()
        assert fw._paused is False
        fw.pause()
        assert fw._paused is True

    def test_resume_clears_flag(self):
        fw = FileWatcher()
        fw.pause()
        fw.resume()
        assert fw._paused is False


# ---------------------------------------------------------------------------
# status property
# ---------------------------------------------------------------------------

class TestStatus:
    def test_stopped_status(self):
        fw = FileWatcher()
        assert fw.status == "stopped"

    def test_running_polling_status(self):
        fw = FileWatcher()
        fw._running = True
        fw._use_watchdog = False
        assert "running" in fw.status
        assert "polling" in fw.status

    def test_running_watchdog_status(self):
        fw = FileWatcher()
        fw._running = True
        fw._use_watchdog = True
        assert "watchdog" in fw.status

    def test_paused_shown_in_status(self):
        fw = FileWatcher()
        fw._running = True
        fw._use_watchdog = False
        fw._paused = True
        assert "paused" in fw.status

    def test_pending_count_shown_in_status(self):
        fw = FileWatcher()
        fw._running = True
        fw._use_watchdog = False
        fw._pending = {"a.py", "b.py"}
        assert "2 pending" in fw.status


# ---------------------------------------------------------------------------
# _try_watchdog fallback
# ---------------------------------------------------------------------------

class TestTryWatchdog:
    def test_returns_false_when_watchdog_not_installed(self):
        fw = FileWatcher()
        with patch("builtins.__import__", side_effect=ImportError("no watchdog")):
            # _try_watchdog is pragma no cover; test indirectly via start()
            with patch.object(fw, "_poll_loop"):
                fw.start()
        assert fw._use_watchdog is False
        fw.stop()

    def test_fallback_polling_thread_is_daemon(self):
        fw = FileWatcher()
        with patch.object(fw, "_try_watchdog", return_value=False), \
             patch.object(fw, "_poll_loop"):
            fw.start()
            thread = fw._thread
            fw.stop()
        assert thread.daemon is True

    def test_fallback_thread_named(self):
        fw = FileWatcher()
        with patch.object(fw, "_try_watchdog", return_value=False), \
             patch.object(fw, "_poll_loop"):
            fw.start()
            thread = fw._thread
            fw.stop()
        assert "file-watcher" in thread.name


# ---------------------------------------------------------------------------
# pending set thread-safety (basic)
# ---------------------------------------------------------------------------

class TestPendingSet:
    def test_pending_starts_empty(self):
        fw = FileWatcher()
        assert len(fw._pending) == 0

    def test_start_clears_pending(self):
        fw = FileWatcher()
        fw._pending = {"stale.py"}
        with patch.object(fw, "_try_watchdog", return_value=False), \
             patch.object(fw, "_poll_loop"):
            fw.start()
            fw.stop()
        assert len(fw._pending) == 0


# ---------------------------------------------------------------------------
# watched extensions filter
# ---------------------------------------------------------------------------

class TestWatchedExtensions:
    def test_py_is_watched(self):
        fw = FileWatcher()
        assert ".py" in fw._watched_exts

    def test_png_is_not_watched(self):
        fw = FileWatcher()
        assert ".png" not in fw._watched_exts

    def test_exe_is_not_watched(self):
        fw = FileWatcher()
        assert ".exe" not in fw._watched_exts

    def test_all_exts_start_with_dot(self):
        fw = FileWatcher()
        for ext in fw._watched_exts:
            assert ext.startswith("."), f"Extension {ext!r} should start with '.'"
