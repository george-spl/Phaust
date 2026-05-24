"""Active task lifecycle: steps, checkpoints, resume."""

from __future__ import annotations

from dataclasses import dataclass, field

from phaust.tasks.models import Checkpoint, Task, TaskStatus, _utc_now
from phaust.tasks.store import TaskStore

_PREVIEW_LIMIT = 200


def _preview(text: str, limit: int = _PREVIEW_LIMIT) -> str:
    one_line = " ".join(text.split())
    if len(one_line) <= limit:
        return one_line
    return one_line[: limit - 1] + "…"


@dataclass
class TaskManager:
    store: TaskStore
    auto_checkpoint: bool = True
    active_task_id: str | None = field(default=None)

    def get_active(self) -> Task | None:
        if not self.active_task_id:
            return None
        task = self.store.load(self.active_task_id)
        if task is None:
            self.active_task_id = None
            return None
        if task.status not in (TaskStatus.ACTIVE, TaskStatus.PAUSED):
            self.active_task_id = None
            return None
        return task

    def start(self, title: str, steps: list[str] | None = None) -> Task:
        if self.get_active():
            raise ValueError("A task is already active. Pause or finish it first.")
        task = Task.create(title, steps)
        self.store.save(task)
        self.active_task_id = task.id
        return task

    def resume(self, task_id: str | None = None) -> Task:
        if task_id:
            task = self.store.load(task_id)
            if task is None:
                raise ValueError(f"No task found: {task_id}")
        else:
            paused = self.store.list_tasks(status=TaskStatus.PAUSED)
            if not paused:
                raise ValueError("No paused task to resume.")
            task = paused[0]
        if self.active_task_id and self.active_task_id != task.id:
            other = self.store.load(self.active_task_id)
            if other and other.status == TaskStatus.ACTIVE:
                raise ValueError("Another task is active. Pause it first.")
        task.status = TaskStatus.ACTIVE
        self.store.save(task)
        self.active_task_id = task.id
        return task

    def pause(self) -> Task:
        task = self._require_active()
        task.status = TaskStatus.PAUSED
        self.add_checkpoint("Task paused.")
        self.store.save(task)
        self.active_task_id = None
        return task

    def done(self) -> Task:
        task = self._require_active()
        task.status = TaskStatus.DONE
        self.add_checkpoint("Task marked done.")
        self.store.save(task)
        self.active_task_id = None
        return task

    def cancel(self) -> Task:
        task = self._require_active()
        task.status = TaskStatus.CANCELLED
        self.add_checkpoint("Task cancelled.")
        self.store.save(task)
        self.active_task_id = None
        return task

    def add_step(self, description: str) -> Task:
        task = self._require_active()
        text = description.strip()
        if not text:
            raise ValueError("Step description cannot be empty.")
        task.steps.append(text)
        self.store.save(task)
        return task

    def next_step(self, note: str = "") -> Task:
        task = self._require_active()
        msg = note.strip() or f"Completed step {task.current_step + 1}: {task.step_label}"
        self.add_checkpoint(msg)
        if task.current_step < len(task.steps) - 1:
            task.current_step += 1
        else:
            task.status = TaskStatus.DONE
            self.active_task_id = None
        self.store.save(task)
        return task

    def skip_step(self) -> Task:
        task = self._require_active()
        self.add_checkpoint(f"Skipped step {task.current_step + 1}: {task.step_label}")
        if task.current_step < len(task.steps) - 1:
            task.current_step += 1
        else:
            task.status = TaskStatus.DONE
            self.active_task_id = None
        self.store.save(task)
        return task

    def add_checkpoint(
        self,
        note: str,
        *,
        user_message: str = "",
        assistant_reply: str = "",
    ) -> Checkpoint:
        task = self._require_active()
        cp = Checkpoint(
            at=_utc_now(),
            step_index=task.current_step,
            note=note.strip() or "Checkpoint",
            user_preview=_preview(user_message),
            assistant_preview=_preview(assistant_reply),
        )
        task.checkpoints.append(cp)
        self.store.save(task)
        return cp

    def record_turn(self, user_message: str, assistant_reply: str) -> None:
        if not self.auto_checkpoint:
            return
        task = self.get_active()
        if task is None or task.status != TaskStatus.ACTIVE:
            return
        self.add_checkpoint(
            f"Turn on step {task.current_step + 1}",
            user_message=user_message,
            assistant_reply=assistant_reply,
        )

    def _require_active(self) -> Task:
        task = self.get_active()
        if task is None:
            raise ValueError("No active task.")
        return task
