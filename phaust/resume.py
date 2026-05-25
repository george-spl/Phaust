"""Actionable resume snapshot (Layer 2)."""

from __future__ import annotations

from pathlib import Path

from phaust.config import load_config
from phaust.recap import build_recap, memory_db_path
from phaust.session_state import load_session_state
from phaust.tasks.models import TaskStatus
from phaust.tasks.store import TaskStore


def build_resume(workspace: Path) -> str:
    """Recap plus where you left off and suggested next commands."""
    workspace = workspace.resolve()
    config, _ = load_config(project_root=workspace)
    ws = (config.workspace_root or workspace).resolve()
    state = load_session_state(ws)

    lines = [build_recap(workspace), "", "## Resume — where you left off"]

    if not state:
        lines.append("- No saved session pointer yet — chat once and exit, or run a task.")
    else:
        updated = state.get("updated_at")
        if updated:
            lines.append(f"- Last activity: {updated}")
        if state.get("last_topic"):
            lines.append(f"- Last topic: `{state['last_topic']}`")
        if state.get("last_topics"):
            lines.append(f"- Recent topics: {', '.join(state['last_topics'])}")
        if state.get("last_user_preview"):
            lines.append(f"- Last you said: {state['last_user_preview']}")
        if state.get("last_assistant_preview"):
            lines.append(f"- Last reply: {state['last_assistant_preview']}")
        if state.get("last_files"):
            lines.append("- Recent files:")
            for path in state["last_files"][-6:]:
                lines.append(f"  - `{path}`")

    task_root = (ws / config.tasks.storage_dir).resolve()
    if config.tasks.enabled and task_root.is_dir():
        store = TaskStore(task_root)
        active = store.list_tasks(status=TaskStatus.ACTIVE)
        if active:
            task = active[0]
            lines.append(
                f"\n**Active task:** {task.title} — step {task.current_step + 1}: "
                f"{task.step_label} (`task show` / `task next`)"
            )
        elif state.get("active_task_id"):
            lines.append(
                f"\n**Paused task id:** {state['active_task_id']} "
                f"— try `task resume {state['active_task_id']}`"
            )

    if memory_db_path(ws).is_file() and state.get("last_topic"):
        lines.append(
            f'\n**Memory tip:** `search_semantic {state["last_topic"]}` or continue in chat.'
        )

    lines.append("\n**Start chat:** `phaust`")
    lines.append("**One-shot:** `phaust ask \"continue where we left off\"`")
    lines.append("**Slash in chat:** `/resume` `/recap`")
    return "\n".join(lines)
