"""System prompt block for active tasks."""

from __future__ import annotations

from phaust.tasks.models import Task


def build_task_directive(task: Task) -> str:
    lines = [
        "<task_mode>",
        f"Active task: {task.title} (id={task.id}, progress {task.progress}).",
        f"Current step ({task.current_step + 1}/{len(task.steps)}): {task.step_label}",
    ]
    if task.steps:
        lines.append("All steps:")
        for i, step in enumerate(task.steps):
            mark = "→" if i == task.current_step else ("✓" if i < task.current_step else " ")
            lines.append(f"  {mark} {i + 1}. {step}")
    if task.checkpoints:
        last = task.checkpoints[-1]
        lines.append(f"Last checkpoint: {last.note}")
    lines.append(
        "Focus replies on the current step. Say 'task next' when a step is complete, "
        "or 'task checkpoint <note>' to save progress."
    )
    lines.append("</task_mode>")
    return "\n".join(lines)
