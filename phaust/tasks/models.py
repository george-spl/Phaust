"""Task mode data models (Phaust-2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class TaskStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    DONE = "done"
    CANCELLED = "cancelled"


@dataclass
class Checkpoint:
    """One saved point during a task (manual or auto after each turn)."""

    at: str
    step_index: int
    note: str
    user_preview: str = ""
    assistant_preview: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "at": self.at,
            "step_index": self.step_index,
            "note": self.note,
            "user_preview": self.user_preview,
            "assistant_preview": self.assistant_preview,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Checkpoint:
        return cls(
            at=str(raw.get("at") or _utc_now()),
            step_index=int(raw.get("step_index", 0)),
            note=str(raw.get("note") or ""),
            user_preview=str(raw.get("user_preview") or ""),
            assistant_preview=str(raw.get("assistant_preview") or ""),
        )


@dataclass
class Task:
    id: str
    title: str
    steps: list[str]
    status: TaskStatus = TaskStatus.ACTIVE
    current_step: int = 0
    checkpoints: list[Checkpoint] = field(default_factory=list)
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)

    @classmethod
    def create(cls, title: str, steps: list[str] | None = None) -> Task:
        clean_steps = [s.strip() for s in (steps or []) if s.strip()]
        if not clean_steps:
            clean_steps = [title.strip()]
        return cls(
            id=str(uuid4()),
            title=title.strip(),
            steps=clean_steps,
        )

    @property
    def step_label(self) -> str:
        if not self.steps:
            return "(no steps)"
        idx = min(max(self.current_step, 0), len(self.steps) - 1)
        return self.steps[idx]

    @property
    def progress(self) -> str:
        total = len(self.steps)
        done = min(self.current_step, total)
        return f"{done}/{total}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "steps": self.steps,
            "status": self.status.value,
            "current_step": self.current_step,
            "checkpoints": [cp.to_dict() for cp in self.checkpoints],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Task:
        status_raw = str(raw.get("status") or TaskStatus.ACTIVE.value)
        try:
            status = TaskStatus(status_raw)
        except ValueError:
            status = TaskStatus.ACTIVE
        cps = [Checkpoint.from_dict(cp) for cp in raw.get("checkpoints") or []]
        return cls(
            id=str(raw.get("id") or uuid4()),
            title=str(raw.get("title") or "Untitled task"),
            steps=[str(s) for s in raw.get("steps") or []],
            status=status,
            current_step=int(raw.get("current_step", 0)),
            checkpoints=cps,
            created_at=str(raw.get("created_at") or _utc_now()),
            updated_at=str(raw.get("updated_at") or _utc_now()),
        )

    def touch(self) -> None:
        self.updated_at = _utc_now()
