"""Persist tasks under Memory/tasks/."""

from __future__ import annotations

import json
from pathlib import Path

from phaust.tasks.models import Task, TaskStatus


class TaskStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, task_id: str) -> Path:
        return self.root / f"{task_id}.json"

    def save(self, task: Task) -> None:
        task.touch()
        self._path(task.id).write_text(
            json.dumps(task.to_dict(), indent=2),
            encoding="utf-8",
        )

    def load(self, task_id: str) -> Task | None:
        path = self._path(task_id)
        if not path.is_file():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return None
        return Task.from_dict(raw)

    def delete(self, task_id: str) -> bool:
        path = self._path(task_id)
        if not path.is_file():
            return False
        path.unlink()
        return True

    def list_tasks(self, *, status: TaskStatus | None = None) -> list[Task]:
        tasks: list[Task] = []
        for path in sorted(
            self.root.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        ):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(raw, dict):
                    continue
                task = Task.from_dict(raw)
            except (OSError, json.JSONDecodeError):
                continue
            if status is not None and task.status != status:
                continue
            tasks.append(task)
        return tasks
