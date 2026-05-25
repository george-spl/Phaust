"""Persist last-session pointers for phaust resume (Layer 2)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def session_state_path(workspace: Path) -> Path:
    return (workspace / "Memory" / "session_state.json").resolve()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_session_state(workspace: Path) -> dict[str, Any]:
    path = session_state_path(workspace)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_session_state(workspace: Path, state: dict[str, Any]) -> None:
    path = session_state_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    state = dict(state)
    state["updated_at"] = _utc_now()
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _preview(text: str, limit: int = 120) -> str:
    t = " ".join(str(text or "").split())
    if len(t) <= limit:
        return t
    return t[: limit - 1] + "…"


def update_session_state(
    workspace: Path,
    *,
    user_message: str = "",
    assistant_reply: str = "",
    topic: str | None = None,
    topics: list[str] | None = None,
    files: list[str] | None = None,
    task_id: str | None = None,
    task_title: str | None = None,
    last_episode_id: str | None = None,
) -> None:
    state = load_session_state(workspace)
    if user_message.strip():
        state["last_user_preview"] = _preview(user_message, 160)
    if assistant_reply.strip():
        state["last_assistant_preview"] = _preview(assistant_reply, 160)
    if topic:
        state["last_topic"] = topic
    if topics:
        merged = list(dict.fromkeys([*(state.get("last_topics") or []), *topics]))[-8:]
        state["last_topics"] = merged
    if files:
        merged = list(dict.fromkeys([*(state.get("last_files") or []), *files]))[-12:]
        state["last_files"] = merged
    if task_id is not None:
        state["active_task_id"] = task_id
    if task_title is not None:
        state["active_task_title"] = task_title
    if last_episode_id:
        state["last_episode_id"] = last_episode_id
    save_session_state(workspace, state)
