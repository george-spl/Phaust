"""Hybrid retrieval tests."""

from phaust.memory.retrieval import (
    expanded_queries,
    extract_file_hints,
    filename_match_score,
    merge_search_results,
    rank_episodes,
)


def test_extract_stress_c1_hints():
    hints = extract_file_hints("What was in stress_c1.txt from round 1?")
    assert "stress_c1.txt" in hints
    assert "stress_c1" in hints


def test_expanded_queries_include_stem():
    hints = extract_file_hints("stress_c1.txt content")
    queries = expanded_queries("stress_c1.txt content", hints)
    assert "stress_c1.txt" in queries
    assert "stress_c1" in queries


def test_filename_match_prefers_relevant_episode():
    entries = [
        {"id": "a", "text": "memorize regression G note for session"},
        {
            "id": "b",
            "text": "C1 PASS create_file stress_c1.txt with exactly line one",
        },
    ]

    def embed_fn(_query: str, entry: dict) -> float:
        return 0.1

    hits = rank_episodes(
        "stress_c1.txt from round 1",
        entries,
        embed_score_fn=embed_fn,
        top_k=2,
        filename_boost=0.5,
        lexical_weight=0.25,
    )
    assert hits[0]["id"] == "b"
    assert "stress_c1" in hits[0]["matched_hints"]


def test_merge_keeps_best_score():
    merged = merge_search_results(
        [
            [{"id": "x", "text": "a", "score": 0.2}],
            [{"id": "x", "text": "a", "score": 0.9}, {"id": "y", "text": "b", "score": 0.3}],
        ],
        top_k=2,
    )
    assert merged[0]["id"] == "x"
    assert float(merged[0]["score"]) == 0.9


def test_unrelated_memorize_notes_rank_below_file_hit():
    entries = [
        {"id": "note1", "text": "Block K round 2 note"},
        {"id": "note2", "text": "regression G note"},
        {
            "id": "file",
            "text": "C1 PASS create_file stress_c1.txt with exactly line one",
        },
    ]

    def embed_fn(_query: str, entry: dict) -> float:
        return 1.0

    hits = rank_episodes(
        "stress_c1.txt line one",
        entries,
        embed_score_fn=embed_fn,
        top_k=3,
        filename_boost=0.4,
        lexical_weight=0.25,
    )
    assert hits[0]["id"] == "file"
    assert hits[0]["matched_hints"]
    assert all(h["id"] != "note1" or float(h["score"]) < float(hits[0]["score"]) for h in hits)
