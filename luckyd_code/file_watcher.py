"""Auto-reindex on file changes — watchdog-based background file watcher.

Usage::

    from luckyd_code.file_watcher import FileWatcher

    watcher = FileWatcher("/path/to/project")
    watcher.start()
    ...
    watcher.stop()
"""

import os
import threading
import time
from pathlib import Path
from collections.abc import Callable

from .log import get_logger


class FileWatcher:
    """Watch a project directory for source file changes and auto-reindex.

    Uses watchdog if available; falls back to a polling timer otherwise.
    Debounces rapid changes so reindex doesn't fire on every keystroke.
    """

    def __init__(self, root: str = "", debounce_seconds: float = 3.0,
                 on_change: Callable[[list[str]], None] | None = None):
        self.root = Path(root or os.getcwd()).resolve()
        self.debounce_seconds = debounce_seconds
        self.on_change = on_change
        self._watchdog = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._pending: set[str] = set()
        self._running = False
        self._poll_interval = 1.0  # seconds between polls in fallback mode
        self._use_watchdog = False
        self._paused = False
        self._debounce_timer: threading.Timer | None = None

        # Build the set of watched file extensions
        self._watched_exts = {
            ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx",
            ".rs", ".go", ".java", ".rb", ".php",
            ".c", ".h", ".cpp", ".hpp", ".cs",
            ".swift", ".kt", ".scala",
            ".json", ".yaml", ".yml", ".toml",
            ".md", ".sql", ".sh", ".bat",
            ".html", ".css",
        }

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self):
        """Start watching for file changes in a background thread."""
        if self._running:
            return

        self._stop_event.clear()
        self._pending.clear()

        # Try watchdog first
        watchdog_ok = self._try_watchdog()

        if watchdog_ok:  # pragma: no cover
            self._running = True
            get_logger().info("File watcher started (watchdog) on %s", self.root)
        else:
            # Fallback: poll for mtime changes
            self._thread = threading.Thread(
                target=self._poll_loop,
                daemon=True,
                name="file-watcher-poll",
            )
            self._thread.start()
            self._running = True
            get_logger().info("File watcher started (polling) on %s", self.root)

    def stop(self):
        """Stop watching."""
        self._running = False
        self._stop_event.set()

        if self._watchdog is not None:  # pragma: no cover
            try:
                self._watchdog.stop()
                self._watchdog.join(timeout=3)
            except Exception:
                pass
            self._watchdog = None

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
            self._thread = None

        get_logger().info("File watcher stopped")

    def pause(self):
        """Temporarily pause reindex on changes."""
        self._paused = True

    def resume(self):
        """Resume reindex after pause."""
        self._paused = False

    @property
    def status(self) -> str:
        if not self._running:
            return "stopped"
        mode = "watchdog" if self._use_watchdog else "polling"
        paused = " (paused)" if self._paused else ""
        pending = f" ({len(self._pending)} pending)" if self._pending else ""
        return f"running [{mode}]{paused}{pending}"

    # ------------------------------------------------------------------ #
    #  Watchdog-based watching
    # ------------------------------------------------------------------ #

    def _try_watchdog(self) -> bool:  # pragma: no cover
        """Try to use watchdog for file watching. Returns True on success."""
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler

            class _Handler(FileSystemEventHandler):
                def __init__(self, watcher):
                    self.watcher = watcher

                def on_modified(self, event):
                    if not event.is_directory:
                        self.watcher._on_file_changed(event.src_path)

                def on_created(self, event):
                    if not event.is_directory:
                        self.watcher._on_file_changed(event.src_path)

            handler = _Handler(self)
            observer = Observer()
            observer.schedule(handler, str(self.root), recursive=True)
            observer.daemon = True
            observer.start()
            self._watchdog = observer
            self._use_watchdog = True
            return True
        except Exception as e:
            get_logger().warning("watchdog init failed, falling back to polling: %s", e)
            return False

    # ------------------------------------------------------------------ #
    #  Fallback polling
    # ------------------------------------------------------------------ #

    def _poll_loop(self):  # pragma: no cover
        """Polling fallback when watchdog is unavailable.

        Tracks mtime/size of watched files and detects changes.
        """
        snapshot: dict[str, tuple[float, int]] = {}
        last_trigger = 0.0

        while not self._stop_event.is_set():
            time.sleep(self._poll_interval)

            if self._paused:
                continue

            now = time.time()
            changed: list[str] = []

            for dirpath, dirnames, filenames in os.walk(self.root):
                dirnames[:] = [d for d in dirnames
                               if not d.startswith(".") and d != "__pycache__"]
                for fname in filenames:
                    ext = Path(fname).suffix.lower()
                    if ext not in self._watched_exts:
                        continue
                    fpath = Path(dirpath) / fname
                    try:
                        st = fpath.stat()
                        key = str(fpath)
                        prev = snapshot.get(key)
                        cur = (st.st_mtime, st.st_size)
                        if prev is not None and prev != cur:
                            changed.append(key)
                        snapshot[key] = cur
                    except OSError:
                        continue

            if changed:
                with self._lock:
                    self._pending.update(changed)
                    last_trigger = now

            # Debounce: only trigger if no new changes for debounce_seconds
            if self._pending and (now - last_trigger) >= self.debounce_seconds:
                with self._lock:
                    batch = list(self._pending)
                    self._pending.clear()
                self._fire(batch)

    # ------------------------------------------------------------------ #
    #  Shared change handling
    # ------------------------------------------------------------------ #

    def _on_file_changed(self, path: str):  # pragma: no cover
        """Called by watchdog on each file change event."""
        if self._paused:
            return

        ext = Path(path).suffix.lower()
        if ext not in self._watched_exts:
            return

        with self._lock:
            self._pending.add(path)

        # Start a debounce timer if not already running
        if self._debounce_timer is None or not self._debounce_timer.is_alive():
            self._debounce_timer = threading.Timer(
                self.debounce_seconds,
                self._debounce_fire,
            )
            self._debounce_timer.daemon = True
            self._debounce_timer.start()

    def _debounce_fire(self):  # pragma: no cover
        """Called after debounce window elapses (watchdog mode)."""
        with self._lock:
            batch = list(self._pending)
            self._pending.clear()
        if batch:
            self._fire(batch)

    def _fire(self, changed_files: list[str]):  # pragma: no cover
        """Trigger reindex with the list of changed files."""
        if not changed_files:
            return
        try:
            # Rel import to avoid circular dependency
            from .brain import rebuild_project
            result = rebuild_project(str(self.root))
            stats = f"{result.get('chunks', 0)} chunks, {result.get('files', 0)} files"
            get_logger().info("Auto-reindexed (%d files changed): %s",
                              len(changed_files), stats)
            if self.on_change:
                self.on_change(changed_files)
        except Exception as e:
            get_logger().warning("Auto-reindex failed: %s", e)
