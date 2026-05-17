import uuid
import json
import logging
from pathlib import Path
from typing import Any

_logger = logging.getLogger("luckyd_code.tasks")


class Task:
    def __init__(self, subject: str, description: str = "", task_id: str | None = None) -> None:
        self.id = task_id or uuid.uuid4().hex[:8]
        self.subject = subject
        self.description = description
        self.status = "pending"  # pending, in_progress, completed, deleted
        self.blocked_by: list[str] = []
        self.blocks: list[str] = []

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "subject": self.subject,
            "description": self.description,
            "status": self.status,
            "blocked_by": self.blocked_by,
            "blocks": self.blocks,
        }


from .._data_dir import project_data_path  # noqa: E402


def _get_db_path() -> Path:
    p = project_data_path("tasks.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load_tasks() -> dict[str, dict[str, Any]]:
    path = _get_db_path()
    if path.exists():
        try:
            data: object = json.loads(path.read_text())
            if isinstance(data, dict):
                return data  # type: ignore[return-value]
            return {}
        except Exception:
            _logger.warning("Failed to load tasks from %s", path, exc_info=True)
            return {}
    return {}


def _save_tasks(tasks: dict[str, dict[str, Any]]) -> None:
    path = _get_db_path()
    path.write_text(json.dumps(tasks, indent=2))


def create_task(subject: str, description: str = "", blocked_by: list[str] | None = None) -> Task:
    tasks = _load_tasks()
    task = Task(subject, description)
    if blocked_by:
        task.blocked_by = blocked_by
    tasks[task.id] = task.to_dict()
    _save_tasks(tasks)
    return task


def update_task(task_id: str, status: str | None = None, subject: str | None = None, description: str | None = None) -> str:
    tasks = _load_tasks()
    if task_id not in tasks:
        return f"Error: task {task_id} not found"
    if status:
        tasks[task_id]["status"] = status
    if subject:
        tasks[task_id]["subject"] = subject
    if description:
        tasks[task_id]["description"] = description
    _save_tasks(tasks)
    return f"Task {task_id} updated: {status or 'ok'}"


def list_tasks(status: str | None = None) -> str:
    tasks = _load_tasks()
    if not tasks:
        return "No tasks."

    items = []
    for tid, t in tasks.items():
        if status and t["status"] != status:
            continue
        blocked = f" [blocked by: {', '.join(t['blocked_by'])}]" if t.get("blocked_by") else ""
        items.append(f"[{t['status']}] {tid}: {t['subject']}{blocked}")

    return "\n".join(items) if items else "No matching tasks."


def get_task(task_id: str) -> Task | None:
    tasks = _load_tasks()
    if task_id not in tasks:
        return None
    d = tasks[task_id]
    return Task(d["subject"], d.get("description", ""), task_id)
