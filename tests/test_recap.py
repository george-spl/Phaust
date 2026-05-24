"""Recap command tests."""

import tempfile
from pathlib import Path

from phaust.memory.store import MemoryStore
from phaust.recap import build_recap
from phaust.tasks.models import Task
from phaust.tasks.store import TaskStore


def test_build_recap_empty_workspace():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "phaust.toml").write_text(
            '[phaust]\nname = "Phaust-2"\niteration = 2\n',
            encoding="utf-8",
        )
        text = build_recap(root)
        assert "Phaust recap" in text
        assert "No Memory/phaust.db" in text or "No Memory" in text


def test_build_recap_shows_task_and_episode():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "phaust.toml").write_text(
            "[phaust]\nname = \"Phaust-2\"\niteration = 2\n",
            encoding="utf-8",
        )
        mem = root / "Memory"
        mem.mkdir()
        db = MemoryStore(db_path=mem / "phaust.db")
        db.insert_episode(
            entry_id="ep-1",
            text="[2026-05-24] stress_c1.txt contained line one",
            source="compaction",
            tags=["episode"],
        )
        db.upsert_fact("user_name", "George")

        tasks = TaskStore(mem / "tasks")
        tasks.save(Task.create("R4 fix", ["search stress_c1"]))

        text = build_recap(root)
        assert "user_name" in text
        assert "stress_c1" in text or "ep-1" in text
        assert "R4 fix" in text
