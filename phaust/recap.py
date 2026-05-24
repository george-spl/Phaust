"""Session recap without starting the chat loop."""

from __future__ import annotations

from pathlib import Path

from phaust.config import load_config
from phaust.memory import LongTermMemory, MemoryStore, SemanticMemory
from phaust.tasks.models import TaskStatus
from phaust.tasks.store import TaskStore


def memory_db_path(workspace: Path) -> Path:
    return (workspace / "Memory" / "phaust.db").resolve()


def build_recap(
    workspace: Path,
    *,
    episode_limit: int = 5,
    facts_max: int = 12,
) -> str:
    """Summarize tasks, facts, episodes, and live context for this workspace."""
    workspace = workspace.resolve()
    config, config_path = load_config(project_root=workspace)
    ws = (config.workspace_root or workspace).resolve()

    lines: list[str] = [
        f"Phaust recap — {config.name}",
        f"Workspace: {ws}",
    ]
    if config_path:
        lines.append(f"Config: {config_path}")

    db_path = memory_db_path(ws)
    if not db_path.is_file():
        lines.append("\n## Memory")
        lines.append("No Memory/phaust.db yet — run a chat session and exit to archive.")
        return "\n".join(lines)

    db = MemoryStore(db_path=db_path)
    lt = LongTermMemory(db=db)
    sem = SemanticMemory(db=db, max_episodes=config.max_episodes)

    if config.tasks.enabled:
        task_root = (ws / config.tasks.storage_dir).resolve()
        store = TaskStore(task_root)
        active = store.list_tasks(status=TaskStatus.ACTIVE)
        paused = store.list_tasks(status=TaskStatus.PAUSED)
        lines.append("\n## Tasks")
        if active:
            for task in active:
                lines.append(
                    f"- ACTIVE: {task.title} ({task.progress}) "
                    f"step {task.current_step + 1}: {task.step_label} [id={task.id}]"
                )
        else:
            lines.append("- No active task.")
        if paused:
            for task in paused[:5]:
                lines.append(
                    f"- PAUSED: {task.title} ({task.progress}) [id={task.id}] "
                    f"— resume: task resume {task.id}"
                )
        recent_done = [
            t for t in store.list_tasks(status=TaskStatus.DONE)
        ][:3]
        if recent_done:
            lines.append("- Recently done:")
            for task in recent_done:
                lines.append(f"  - {task.title} [id={task.id}]")

    facts = lt.list_facts()
    keys = facts.get("keys") or []
    lines.append("\n## Long-term facts")
    if keys:
        fact_rows = db.list_facts()
        for key in keys[:facts_max]:
            val = str(fact_rows[key]["value"])
            if len(val) > 80:
                val = val[:79] + "…"
            lines.append(f"- {key} = {val}")
        if len(keys) > facts_max:
            lines.append(f"- … and {len(keys) - facts_max} more")
    else:
        lines.append("- (none)")

    episodes = sem.list_episode_summaries(limit=episode_limit)
    lines.append("\n## Recent episodes (archived sessions)")
    if episodes:
        for ep in episodes:
            lines.append(f"- {ep['id']}: {ep.get('preview', '')}")
    else:
        lines.append("- (none)")

    msg_count = db.message_count()
    lines.append("\n## Live context")
    if msg_count:
        lines.append(
            f"- {msg_count} message(s) in current session DB "
            "(not yet archived — exit chat to compact)."
        )
    else:
        lines.append("- Empty — no in-progress session messages.")

    lines.append("\nCommands: `phaust` (chat), `task help`, `task resume <id>`.")
    return "\n".join(lines)
