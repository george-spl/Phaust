"""Deterministic nudge messages for the tool loop."""

from __future__ import annotations

LOGGING_REFUSAL_PHRASES = (
    "cannot append",
    "can't append",
    "no tests were executed",
    "no tests ran",
    "would be inaccurate",
    "invent g1",
)

LOGGING_NUDGE = (
    "Append to the log file now with read_file then edit_file. "
    "Self-assessment lines must describe stress-test IDs from THIS session "
    "(e.g. G1: memory disable, I2: .git/config block) — NOT the logging edit. "
    "Use one sentence per test ID. Do not refuse."
)

SHELL_STAGING_NUDGE = (
    "Call run_command with `git add .` now (native function call). "
    "If blocked, report the allowlist error — do not read phaust.toml or "
    "suggest manual terminal commands."
)

MEMORIZE_NUDGE = (
    "Call memorize or remember now (native function call — not text only). "
    "For a note/snippet use memorize(text=...). For one fact use remember(key=..., value=...)."
)

META_NARRATION_NUDGE = (
    "Respond to George directly in second person. "
    "Do not narrate what 'the user' is asking — give your "
    "actual answer or next step."
)


def is_logging_refusal(text: str) -> bool:
    lower = text.lower()
    return any(phrase in lower for phrase in LOGGING_REFUSAL_PHRASES)


def recall_nudge_message(user_message: str, *, fact_recall_key: str | None) -> str:
    if fact_recall_key:
        return (
            f"Call recall(key={fact_recall_key!r}) now (native function call). "
            "Do not answer from injected memory text alone."
        )
    return (
        "Call search_semantic or recall_episode before answering about "
        "past sessions or prior tests (native function call)."
    )


def memorize_nudge_message(user_message: str, *, suggested_text: str | None) -> str:
    if suggested_text:
        return f"{MEMORIZE_NUDGE}\nText to store:\n{suggested_text}"
    return f"{MEMORIZE_NUDGE}\nUse the user's message as the memorize text."


def write_nudge_message(
    read_paths: list[str], *, create_ok: bool = False
) -> str:
    if create_ok and not read_paths:
        return (
            "Call create_file for a new file (no read_file needed), "
            "or read_file then edit_file/write_file for an existing file."
        )
    if not read_paths:
        return (
            "Call read_file on the target path first. "
            "Then use write_file or edit_file with exact on-disk text — not old chat."
        )
    joined = ", ".join(read_paths)
    return (
        "Apply the file change now using create_file, write_file, edit_file, or delete_file "
        "(native function calling — not XML). "
        "For a NEW file use create_file (no read_file needed). "
        "For an EXISTING file use read_file first, then edit_file or write_file. "
        f"File(s) already read: {joined}."
    )
