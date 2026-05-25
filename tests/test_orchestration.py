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


def test_conversational_recall_not_auto_returned():
    from phaust.orchestration.policy import should_auto_return_recall_outcome

    intent = classify_turn("Let's review my current responsibilities")
    tool_calls = [{"function": {"name": "recall", "arguments": '{"key":"user_job"}'}}]
    reply = "user_job = Warehouse Lead at Hyve Solutions"
    assert not should_auto_return_recall_outcome(tool_calls, reply, intent)


def test_explicit_fact_recall_auto_returned():
    from phaust.orchestration.policy import should_auto_return_recall_outcome

    intent = classify_turn("recall user_job")
    tool_calls = [{"function": {"name": "recall", "arguments": '{"key":"user_job"}'}}]
    assert should_auto_return_recall_outcome(
        tool_calls, "user_job = Warehouse Lead", intent
    )


def test_list_episodes_not_auto_returned_for_conversation():
    from phaust.orchestration.policy import should_auto_return_recall_outcome

    intent = classify_turn("What were we discussing last time?")
    tool_calls = [{"function": {"name": "list_episodes", "arguments": '{"limit":5}'}}]
    assert intent.memory_question
    assert not should_auto_return_recall_outcome(
        tool_calls, "- ep-1: preview", intent
    )


def test_make_smarter_not_write_intent():
    intent = classify_turn("I am trying to make you smarter each day, bit by bit.")
    assert not intent.wants_write
    assert not intent.file_change


def test_hello_phaust_last_time_is_memory_question():
    from phaust.memory.last_session import is_addressing_phaust_only, is_generic_last_session_query

    msg = "Hello Phaust. What were we discussing last time?"
    intent = classify_turn(msg)
    assert intent.memory_question
    assert is_generic_last_session_query(msg)
    assert is_addressing_phaust_only(msg)


def test_feedback_with_recall_word_not_memory_question():
    from phaust.orchestration.intent import is_feedback_not_memory

    msg = "Good! Now you can actually recall latest session rather than older ones."
    assert is_feedback_not_memory(msg)
    intent = classify_turn(msg)
    assert not intent.recall_past
    assert not intent.memory_question


def test_no_recall_nudge_when_continue_from_available():
    from phaust.orchestration.policy import should_nudge_recall
    from phaust.orchestration.policy import NudgeBudget

    intent = classify_turn("What were we discussing last time?")
    state = {
        "last_topic": "starfinder",
        "last_episode_id": "ep-1",
        "last_user_preview": "Starfinder character",
    }
    assert not should_nudge_recall(
        intent, memory_recall_this_turn=False, budget=NudgeBudget(), session_state=state
    )


def test_format_write_applied():
    from phaust.orchestration.outcomes import format_write_outcome

    msg = format_write_outcome([{"applied": True, "path": "foo.txt"}])
    assert "Change applied to foo.txt" in msg


def test_paths_read_this_round():
    from phaust.orchestration.outcomes import paths_read_this_round

    paths = paths_read_this_round([{"path": "a.txt", "content": "hi"}])
    assert paths == ["a.txt"]
