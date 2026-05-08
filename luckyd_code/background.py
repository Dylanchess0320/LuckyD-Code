"""Background autonomous agent - persistent background tasks with progress reporting."""

import json
import threading
import time
from datetime import datetime

from .agent import SubAgent
from .log import get_logger

from ._data_dir import data_path

BACKGROUND_DIR = data_path("background")


class BackgroundTask:
    """Represents a background task with status tracking."""

    def __init__(self, task_id: str, description: str):
        self.task_id: str = task_id
        self.description: str = description
        self.status: str = "pending"  # pending, running, done, error
        self.result: str = ""
        self.error: str = ""
        self.started_at: str | None = None
        self.finished_at: str | None = None


class BackgroundAgent:
    """Manages autonomous background agents that work independently."""

    def __init__(self, config):
        self.config = config
        self.tasks: dict[str, BackgroundTask] = {}
        self.threads: dict[str, threading.Thread] = {}
        self._lock = threading.Lock()
        BACKGROUND_DIR.mkdir(parents=True, exist_ok=True)

    def start_task(self, description: str) -> str:
        """Start a new background task and return its ID."""
        task_id = f"bg_{int(time.time())}_{len(self.tasks)}"
        task = BackgroundTask(task_id, description)
        task.status = "pending"
        task.started_at = datetime.now().isoformat()

        with self._lock:
            self.tasks[task_id] = task

        thread = threading.Thread(
            target=self._run_task,
            args=(task_id, description),
            daemon=True,
        )
        self.threads[task_id] = thread
        thread.start()

        return task_id

    def _run_task(self, task_id: str, description: str):
        """Run a task in the background thread."""
        with self._lock:
            self.tasks[task_id].status = "running"

        try:
            agent = SubAgent(self.config, description)
            result = agent.run()

            with self._lock:
                self.tasks[task_id].status = "done"
                self.tasks[task_id].result = result
                self.tasks[task_id].finished_at = datetime.now().isoformat()

            # Save to disk
            self._save_task(task_id)

        except Exception as e:
            with self._lock:
                self.tasks[task_id].status = "error"
                self.tasks[task_id].error = str(e)
                self.tasks[task_id].finished_at = datetime.now().isoformat()
            self._save_task(task_id)

    def get_status(self, task_id: str | None = None) -> list[dict[str, object]]:
        """Get status of tasks. If task_id is None, return all."""
        with self._lock:
            if task_id:
                tasks = [self.tasks.get(task_id)]
            else:
                tasks = list(self.tasks.values())

        result = []
        for t in tasks:
            if t is None:
                continue
            result.append({
                "id": t.task_id,
                "description": t.description[:100],
                "status": t.status,
                "started_at": t.started_at or "",
                "finished_at": t.finished_at or "",
                "result_preview": t.result[:200] if t.result else "",
                "error": t.error,
            })
        return result

    def get_result(self, task_id: str) -> str | None:
        """Get the full result of a completed task."""
        with self._lock:
            task = self.tasks.get(task_id)
            if task and task.status == "done":
                return task.result
            return None

    def _save_task(self, task_id: str):
        """Persist task result to disk."""
        with self._lock:
            task = self.tasks.get(task_id)
            if not task:
                return

        data = {
            "id": task.task_id,
            "description": task.description,
            "status": task.status,
            "result": task.result,
            "error": task.error,
            "started_at": task.started_at,
            "finished_at": task.finished_at,
        }

        path = BACKGROUND_DIR / f"{task_id}.json"
        try:
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            get_logger().warning("Failed to save background task %s", task_id, exc_info=True)

    def load_history(self):
        """Load past background tasks from disk."""
        if not BACKGROUND_DIR.exists():
            return
        for f in sorted(BACKGROUND_DIR.glob("bg_*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                task = BackgroundTask(data["id"], data["description"])
                task.status = data["status"]
                task.result = data.get("result", "")
                task.error = data.get("error", "")
                task.started_at = data.get("started_at")
                task.finished_at = data.get("finished_at")
                with self._lock:
                    self.tasks[data["id"]] = task
            except (json.JSONDecodeError, KeyError):
                get_logger().warning("Corrupt background task file %s — deleting", f.name)
                try:
                    f.unlink()
                except OSError:
                    pass
            except Exception:
                get_logger().warning("Failed to load background task %s", f.name, exc_info=True)
