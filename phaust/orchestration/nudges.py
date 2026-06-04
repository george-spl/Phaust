"""Deterministic nudge messages for the tool loop."""

from __future__ import annotations

from phaust.orchestration.stress_log import FORBIDDEN_GENERIC_LOG

LOGGING_REFUSAL_PHRASES = (
    "cannot append",
    "can't append",
    "no tests were executed",
    "no tests ran",
    "would be inaccurate",
    "invent g1",
)

LOGGING_NUDGE = (
    "Update test_logging.txt from this session. Read the file, then append only new lines. "
    "Per-test format: `A1: PASS — what George asked and what you did.` "
    "No generic CPU/memory/latency fiction. Do not refuse."
)

LOGGING_EDIT_NUDGE = (
    "Apply the file change now — append only the new section to test_logging.txt, "
    "not the whole file again. Use the session transcript for real test results."
)

SHELL_STAGING_NUDGE = (
    "Try to stage the git changes with the allowed command. "
    "If policy blocks it, tell George plainly — do not send him to an external terminal."
)

MEMORIZE_NUDGE = (
    "Save what George asked you to remember (fact or note). "
    "Do not only say you saved it — actually store it."
)

META_NARRATION_NUDGE = (
    "Answer George directly in second person. "
    "Do not narrate what 'the user' is asking — give your actual answer."
)

NATIVE_TOOL_NUDGE = (
    "Perform the action using the system's tools, not simulated code in chat. "
    "Do not say you lack access — read, save, or run what is needed."
)


def is_logging_refusal(text: str) -> bool:
    lower = text.lower()
    return any(phrase in lower for phrase in LOGGING_REFUSAL_PHRASES)


def is_logging_hallucination(text: str) -> bool:
    """Chat reply invented generic infra metrics instead of Phaust test IDs."""
    return bool(FORBIDDEN_GENERIC_LOG.search(text))


def recall_nudge_message(
    user_message: str,
    *,
    fact_recall_key: str | None,
    session_state: dict | None = None,
) -> str:
    if fact_recall_key:
        return (
            f"Look up the stored fact {fact_recall_key!r} and answer from the result. "
            "Do not guess."
        )
    if session_state and (
        session_state.get("last_topic") or session_state.get("last_episode_id")
    ):
        topic = session_state.get("last_topic", "unknown")
        return (
            "Use <continue_from> first. "
            f"Last topic was {topic!r}. "
            "Summarize in 2–5 sentences — no raw id lists."
        )
    return (
        "Search or recall past sessions as needed, then answer George in prose."
    )


def memorize_nudge_message(user_message: str, *, suggested_text: str | None) -> str:
    if suggested_text:
        return f"{MEMORIZE_NUDGE}\nText to store:\n{suggested_text}"
    return f"{MEMORIZE_NUDGE}\nUse his message as the note text."


def write_nudge_message(
    read_paths: list[str], *, create_ok: bool = False
) -> str:
    if create_ok and not read_paths:
        return (
            "Create the new file he asked for, or read an existing file first then edit it."
        )
    if not read_paths:
        return "Read the file on disk first, then propose the change he asked for."
    joined = ", ".join(read_paths)
    return (
        f"Apply the file change now. Already read: {joined}. "
        "Use exact on-disk text for edits."
    )
