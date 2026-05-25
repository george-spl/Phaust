"""Topic tagging and retrieval boost tests."""

import tempfile
from pathlib import Path

from phaust.memory.store import MemoryStore
from phaust.memory.topics import extract_topic_hints, infer_topic_tags
from phaust.memory.semantic import SemanticMemory


def test_infer_starfinder_tags():
    tags = infer_topic_tags("Starfinder 1e android character sheet")
    assert "starfinder" in tags
    assert "character" in tags


def test_infer_from_characters_path():
    tags = infer_topic_tags("Saved to characters/android_sniper.md")
    assert "character" in tags


def test_topic_boost_in_search():
    with tempfile.TemporaryDirectory() as tmp:
        db = MemoryStore(db_path=Path(tmp) / "phaust.db")
        sem = SemanticMemory(db=db, hybrid_retrieval=True)
        sem.store("stress test block G round 2 note", tags=["phaust"])
        sem.store(
            "Pathfinder fleet battle pause — half-orc admiral, Flint as squadron admiral",
            tags=["pathfinder", "tabletop"],
        )
        hits = sem.search("pathfinder campaign pause", top_k=3)
        assert hits
        top_text = hits[0]["text"].lower()
        assert "pathfinder" in top_text or "fleet" in top_text
