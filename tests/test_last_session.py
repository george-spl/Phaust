"""Last-session recall bias tests."""

import tempfile
from pathlib import Path

from phaust.memory.last_session import is_generic_last_session_query
from phaust.memory.semantic import SemanticMemory
from phaust.memory.store import MemoryStore
from phaust.session_state import save_session_state


def test_generic_last_session_prefers_starfinder_over_stress():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        mem = root / "Memory"
        mem.mkdir()
        save_session_state(
            root,
            {
                "last_topic": "starfinder",
                "last_user_preview": "Starfinder Android Operative Sniper character",
                "last_episode_id": "ep-recent",
            },
        )
        db = MemoryStore(db_path=mem / "phaust.db")
        sem = SemanticMemory(db=db, hybrid_retrieval=True)
        sem.store(
            "Block H round 2 stress test logging phaust-1 regression scores",
            tags=["phaust"],
        )
        sem.store(
            "Starfinder 1e Android Operative Sniper dry humor character sheet",
            tags=["starfinder", "character"],
        )
        hits = sem.search(
            "Hello Phaust. What were we discussing last time?",
            top_k=2,
            workspace_root=root,
        )
        assert hits
        top = hits[0]["text"].lower()
        assert "starfinder" in top or "sniper" in top or "operative" in top


def test_generic_query_detected():
    assert is_generic_last_session_query("What were we discussing last time?")
