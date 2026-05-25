"""Orchestration layer tests (Phaust-2)."""

from phaust.orchestration import classify_turn


def test_append_sets_wants_write():
    intent = classify_turn("Read test_logging.txt. Append R6 only.")
    assert intent.logging_task
    assert intent.append
    assert intent.wants_write


def test_lone_digit_is_minimal():
    intent = classify_turn("2")
    assert intent.minimal
    assert not intent.wants_write


def test_git_staging_not_file_change():
    intent = classify_turn("Stage all changes with git")
    assert intent.git_staging
    assert not intent.file_change


def test_fact_recall_key():
    intent = classify_turn("Recall test_fact_key")
    assert intent.fact_recall
    assert intent.fact_recall_key == "test_fact_key"


def test_explicit_search_semantic_skips_recall_past():
    intent = classify_turn("search_semantic stress_c1.txt line one")
    assert intent.explicit_memory_tool
    assert not intent.recall_past


def test_pathfinder_narrative_not_recall_past():
    msg = (
        "We ended last session right when we were about to be attacked "
        "by an enemy ship squadron. The admiral of the fleet is a female half-ork "
        "that killed Flint. We gathered all our allies, and we have our own squadron."
    )
    intent = classify_turn(msg)
    assert not intent.recall_past
    assert not intent.memory_question
    assert intent.memorize


def test_pause_and_archive_memorize():
    intent = classify_turn("We will pause and archive, so we can resume later.")
    assert intent.memorize
    assert not intent.recall_past


def test_stress_a3_still_recalls():
    intent = classify_turn("You don't remember our last session?")
    assert intent.recall_past


def test_search_semantic_not_direct_recall_tool():
    from phaust.orchestration.constants import MEMORY_DIRECT_RECALL_TOOLS

    assert "search_semantic" not in MEMORY_DIRECT_RECALL_TOOLS


def test_format_write_applied():
    from phaust.orchestration.outcomes import format_write_outcome

    msg = format_write_outcome([{"applied": True, "path": "foo.txt"}])
    assert "Change applied to foo.txt" in msg


def test_paths_read_this_round():
    from phaust.orchestration.outcomes import paths_read_this_round

    paths = paths_read_this_round([{"path": "a.txt", "content": "hi"}])
    assert paths == ["a.txt"]
