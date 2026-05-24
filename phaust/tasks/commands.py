"""REPL commands for task mode."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from phaust.tasks.manager import TaskManager
from phaust.tasks.models import Task, TaskStatus


class TaskCommandKind(str, Enum):
    LIST = "list"
    SHOW = "show"
    START = "start"
    RESUME = "resume"
    PAUSE = "pause"
    DONE = "done"
    CANCEL = "cancel"
    NEXT = "next"
    SKIP = "skip"
    STEP = "step"
    CHECKPOINT = "checkpoint"
    HELP = "help"


@dataclass(frozen=True)
class TaskCommand:
    kind: TaskCommandKind
    arg: str = ""


_STEP_SEP = " :: "


def parse_task_command(line: str) -> TaskCommand | None:
    text = line.strip()
    if not text.lower().startswith("task"):
        return None
    rest = text[4:].strip()
    if not rest:
        return TaskCommand(TaskCommandKind.LIST)
    lower = rest.lower()
    if lower in {"help", "?"}:
        return TaskCommand(TaskCommandKind.HELP)
    if lower == "show":
        return TaskCommand(TaskCommandKind.SHOW)
    if lower == "pause":
        return TaskCommand(TaskCommandKind.PAUSE)
    if lower == "done":
        return TaskCommand(TaskCommandKind.DONE)
    if lower == "cancel":
        return TaskCommand(TaskCommandKind.CANCEL)
    if lower == "skip":
        return TaskCommand(TaskCommandKind.SKIP)
    if lower == "next" or lower.startswith("next "):
        arg = rest[4:].strip() if lower.startswith("next ") else ""
        return TaskCommand(TaskCommandKind.NEXT, arg)
    if lower.startswith("start "):
        payload = rest[6:].strip()
        return TaskCommand(TaskCommandKind.START, payload)
    if lower.startswith("resume"):
        arg = rest[6:].strip()
        return TaskCommand(TaskCommandKind.RESUME, arg)
    if lower.startswith("step "):
        return TaskCommand(TaskCommandKind.STEP, rest[5:].strip())
    if lower.startswith("checkpoint "):
        return TaskCommand(TaskCommandKind.CHECKPOINT, rest[11:].strip())
    if lower.startswith("checkpoint"):
        return TaskCommand(TaskCommandKind.CHECKPOINT, "")
    return TaskCommand(TaskCommandKind.HELP)


def _parse_start_arg(arg: str) -> tuple[str, list[str]]:
    if _STEP_SEP in arg:
        title, *steps = [p.strip() for p in arg.split(_STEP_SEP) if p.strip()]
        return title, steps
    return arg.strip(), []


def _format_task(task: Task, *, detailed: bool = False) -> str:
    lines = [
        f"{task.title} [{task.status.value}]",
        f"  id: {task.id}",
        f"  progress: {task.progress} — step {task.current_step + 1}: {task.step_label}",
    ]
    if detailed and task.steps:
        lines.append("  steps:")
        for i, step in enumerate(task.steps):
            mark = "→" if i == task.current_step else ("done" if i < task.current_step else "pending")
            lines.append(f"    {i + 1}. ({mark}) {step}")
    if detailed and task.checkpoints:
        lines.append(f"  checkpoints: {len(task.checkpoints)}")
        for cp in task.checkpoints[-3:]:
            lines.append(f"    - [{cp.step_index + 1}] {cp.note}")
    return "\n".join(lines)


def _list_summary(manager: TaskManager) -> str:
    active = manager.get_active()
    lines: list[str] = []
    if active:
        lines.append("Active:")
        lines.append(_format_task(active))
    else:
        lines.append("No active task.")
    paused = manager.store.list_tasks(status=TaskStatus.PAUSED)
    if paused:
        lines.append("\nPaused:")
        for task in paused[:5]:
            lines.append(_format_task(task))
    recent = [
        t
        for t in manager.store.list_tasks()
        if t.status in (TaskStatus.DONE, TaskStatus.CANCELLED)
    ][:3]
    if recent:
        lines.append("\nRecent:")
        for task in recent:
            lines.append(_format_task(task))
    return "\n".join(lines)


TASK_HELP = """Task mode commands:
  task                          list active / paused / recent tasks
  task start Title :: step1 :: step2   start multi-step task
  task show                     show active task detail
  task step <description>       add a step to active task
  task next [note]              complete current step and advance
  task skip                     skip current step
  task checkpoint [note]        save manual checkpoint
  task pause                    pause (saved to Memory/tasks/)
  task resume [task-id]         resume paused task
  task done                     mark task complete
  task cancel                   abandon task
During an active task, each chat turn auto-checkpoints."""


def handle_task_command(manager: TaskManager, line: str) -> str | None:
    cmd = parse_task_command(line)
    if cmd is None:
        return None
    try:
        if cmd.kind == TaskCommandKind.HELP:
            return TASK_HELP
        if cmd.kind == TaskCommandKind.LIST:
            return _list_summary(manager)
        if cmd.kind == TaskCommandKind.SHOW:
            task = manager.get_active()
            if task is None:
                return "No active task. Use `task start …` or `task resume`."
            return _format_task(task, detailed=True)
        if cmd.kind == TaskCommandKind.START:
            if not cmd.arg:
                return "Usage: task start Title :: optional step1 :: step2"
            title, steps = _parse_start_arg(cmd.arg)
            if not title:
                return "Task title cannot be empty."
            task = manager.start(title, steps or None)
            return "Started task:\n" + _format_task(task, detailed=True)
        if cmd.kind == TaskCommandKind.RESUME:
            task = manager.resume(cmd.arg or None)
            return "Resumed task:\n" + _format_task(task, detailed=True)
        if cmd.kind == TaskCommandKind.PAUSE:
            task = manager.pause()
            return f"Paused task `{task.title}` (id={task.id})."
        if cmd.kind == TaskCommandKind.DONE:
            task = manager.done()
            return f"Task done: `{task.title}`."
        if cmd.kind == TaskCommandKind.CANCEL:
            task = manager.cancel()
            return f"Task cancelled: `{task.title}`."
        if cmd.kind == TaskCommandKind.NEXT:
            task = manager.next_step(cmd.arg)
            if task.status == TaskStatus.DONE:
                return f"Final step complete. Task done: `{task.title}`."
            return "Advanced to next step:\n" + _format_task(task, detailed=True)
        if cmd.kind == TaskCommandKind.SKIP:
            task = manager.skip_step()
            if task.status == TaskStatus.DONE:
                return f"Skipped last step — task done: `{task.title}`."
            return "Skipped step:\n" + _format_task(task, detailed=True)
        if cmd.kind == TaskCommandKind.STEP:
            if not cmd.arg:
                return "Usage: task step <description>"
            task = manager.add_step(cmd.arg)
            return f"Added step {len(task.steps)}:\n" + _format_task(task, detailed=True)
        if cmd.kind == TaskCommandKind.CHECKPOINT:
            task = manager.get_active()
            if task is None:
                return "No active task."
            manager.add_checkpoint(cmd.arg or "Manual checkpoint.")
            return "Checkpoint saved."
    except ValueError as exc:
        return str(exc)
    return TASK_HELP
