"""Map TurnIntent → system prompt directive blocks."""

from __future__ import annotations

from phaust.orchestration.intent import (
    TurnIntent,
    memorize_text_from_message,
)


def build_turn_directives(
    intent: TurnIntent,
    *,
    session_has_prior_reply: bool,
    memory_writes_enabled: bool,
    conversational_first: bool = True,
    empty_write_paths: set[str] | None = None,
    file_snapshots: dict[str, str] | None = None,
) -> list[str]:
    blocks: list[str] = []
    empty_write_paths = empty_write_paths or set()
    file_snapshots = file_snapshots or {}

    if intent.profile_question:
        blocks.append(
            "<profile_memory>\n"
            "George asked what you know about him personally (facts, not past chat episodes). "
            "Use EVERY line in <long_term_memory> above — name, age, job, goals, etc. "
            "Answer in warm, direct prose covering all stored facts.\n"
            "</profile_memory>"
        )

    if intent.memory_question:
        blocks.append(
            "<memory_rules>\n"
            "George is asking about past conversations. Use <memory_recall> and search "
            "past sessions before saying you have no record. "
            "Answer in clear prose (2–5 sentences). Do not paste raw logs or id lists "
            "unless he asked for them.\n"
            "</memory_rules>"
        )

    if intent.memorize or intent.store_fact:
        text = memorize_text_from_message(intent.message)
        hint = ""
        if intent.store_fact and intent.store_fact_key:
            hint = (
                f"Store fact: {intent.store_fact_key} = {intent.store_fact_value!r}. "
                "Confirm only after it is saved.\n"
            )
        blocks.append(
            "<memory_store_request>\n"
            "George asked you to keep something. Save it now (do not only say you will). "
            + hint
            + (f"Suggested note text: {text}\n" if text else "")
            + "</memory_store_request>"
        )

    if intent.fact_recall and intent.fact_recall_key:
        blocks.append(
            "<fact_recall_request>\n"
            f"Look up the stored fact for {intent.fact_recall_key!r} and answer from the result. "
            "Do not claim you cannot access memory.\n"
            "</fact_recall_request>"
        )

    if intent.explicit_memory_tool:
        blocks.append(
            "<memory_lookup_request>\n"
            "George wants a memory lookup (episodes or semantic search). Do it, then summarize in prose.\n"
            "</memory_lookup_request>"
        )

    if intent.code_search or intent.read_request or intent.list_request:
        blocks.append(
            "<explore_request>\n"
            "George needs accurate information from the project. Read or search the repo on disk — "
            "do not rely on earlier chat snippets alone.\n"
            "</explore_request>"
        )

    if intent.file_change:
        blocks.append(
            "<write_rules>\n"
            "George wants a file change. Use on-disk text from a fresh read, not old chat. "
            "New files can be created outright. Existing files: read first, then propose the edit. "
            "He will approve at the terminal (y/N). "
            "For appending to a log or document, add only the new lines — never paste the whole file back.\n"
            "</write_rules>"
        )

    if empty_write_paths:
        paths = ", ".join(sorted(empty_write_paths))
        empty_msg = (
            f"Confirmed empty on disk: {paths}. "
            f"Write only what George asked for now."
        )
        if intent.append:
            empty_msg = (
                f"Confirmed empty on disk: {paths}. "
                f"He asked for more lines but the file is empty — write fresh lines from scratch."
            )
        blocks.append(f"<write_context>\n{empty_msg}\n</write_context>")

    if file_snapshots:
        parts = [f"### {path}\n{file_snapshots[path]}" for path in sorted(file_snapshots)]
        blocks.append(
            "<file_on_disk>\n"
            + "\n\n".join(parts)
            + "\n\nUse this exact text for edits (no invented line prefixes).\n"
            "</file_on_disk>"
        )

    if not memory_writes_enabled:
        blocks.append(
            "<session_memory_policy>\n"
            "Memory saves are OFF this session. Do not store new facts or notes. "
            "On exit, this chat will not be archived. "
            "If George wants saves again, he can say 'enable remembering' or 'save this session'.\n"
            "</session_memory_policy>"
        )

    if session_has_prior_reply:
        blocks.append(
            "<conversation_rules>\n"
            "You already greeted George this session. Do NOT open with hello or re-introduce yourself. "
            "Respond directly. Second person only — never narrate 'the user' in third person.\n"
            "</conversation_rules>"
        )

    if intent.minimal:
        blocks.append(
            "<brevity>\n"
            "Very short message — reply in one brief sentence unless he asked for detail.\n"
            "</brevity>"
        )

    if intent.git_staging:
        blocks.append(
            "<git_staging_request>\n"
            "George wants to stage git changes. Try the allowed git command; if blocked, "
            "explain the allowlist limitation — do not send him to an external terminal unless he asks.\n"
            "</git_staging_request>"
        )
    elif intent.shell:
        blocks.append(
            "<shell_rules>\n"
            "George asked to run a shell command. Use only allowlisted commands. "
            "If blocked, explain plainly and stop.\n"
            "</shell_rules>"
        )

    if intent.logging_task:
        blocks.append(
            "<logging_task>\n"
            "Update test_logging.txt from this session. Read the file, then append only NEW text.\n"
            "For per-test scores use: `A1: PASS — one sentence` (real behaviour, no CPU/latency fiction).\n"
            "For a **Phaust overall opinion** section, use normal markdown headings "
            "(strongest / weakest / nudges / fixes) — no A1: lines required there.\n"
            "</logging_task>"
        )

    return blocks
