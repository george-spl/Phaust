"""Map TurnIntent → system prompt directive blocks."""

from __future__ import annotations

from phaust.orchestration.intent import TurnIntent, memorize_text_from_message


def build_turn_directives(
    intent: TurnIntent,
    *,
    session_has_prior_reply: bool,
    memory_writes_enabled: bool,
    empty_write_paths: set[str] | None = None,
    file_snapshots: dict[str, str] | None = None,
) -> list[str]:
    blocks: list[str] = []
    empty_write_paths = empty_write_paths or set()
    file_snapshots = file_snapshots or {}

    if intent.memory_question:
        blocks.append(
            "<memory_rules>\n"
            "User is asking about past conversations. Check <memory_recall> and use "
            "recall_episode, list_episodes, or search_semantic before saying you have "
            "no record. Episodes are summaries — if a detail is missing, say the "
            "episode mentions X but not Y; do not invent.\n"
            "Answer in clear prose (2–5 sentences). Do NOT paste raw tool output, "
            "episode id lists, or full archived transcripts as your reply unless the "
            "user explicitly asked for ids or raw text.\n"
            "</memory_rules>"
        )

    if intent.memorize:
        text = memorize_text_from_message(intent.message)
        blocks.append(
            "<memory_store_request>\n"
            "User asked to store something now. Call memorize (for notes/snippets) or "
            "remember (for key-value facts) — native function call, not text only.\n"
            + (f"Suggested text for memorize: {text}\n" if text else "")
            + "</memory_store_request>"
        )

    if intent.file_change:
        blocks.append(
            "<write_rules>\n"
            "For file edits, trust read_file on disk — not old chat or episodic memory. "
            "To create a NEW file: create_file (no read_file needed). "
            "To change an EXISTING file: read_file first, then edit_file or write_file. "
            "To delete a file: delete_file (after read_file). "
            "To clear contents only: write_file with empty content or edit_file.\n"
            "If the file is empty, write only what the user asked now (plain lines, "
            "no N| prefixes, do not continue numbering from earlier turns).\n"
            "</write_rules>"
        )

    if empty_write_paths:
        paths = ", ".join(sorted(empty_write_paths))
        empty_msg = (
            f"Confirmed empty on disk: {paths}. "
            f"write_file must contain only the new lines the user requested."
        )
        if intent.append:
            empty_msg = (
                f"Confirmed empty on disk: {paths}. "
                f"User asked for MORE lines but the file has 0 lines — use write_file "
                f"with fresh lines starting at 1 (or plain unnumbered lines). "
                f"Ignore any prior chat claiming earlier lines exist."
            )
        blocks.append(f"<write_context>\n{empty_msg}\n</write_context>")

    if file_snapshots:
        parts = [f"### {path}\n{file_snapshots[path]}" for path in sorted(file_snapshots)]
        blocks.append(
            "<file_on_disk>\n"
            + "\n\n".join(parts)
            + "\n\nCopy this text exactly for edit_file old_string (no added prefixes).\n"
            "</file_on_disk>"
        )

    if not memory_writes_enabled:
        blocks.append(
            "<session_memory_policy>\n"
            "Memory writes are OFF for this session. Do not call remember or memorize. "
            "On exit, nothing from this chat will be archived. "
            "If the user asks to re-enable memory, they can say 'enable remembering' or "
            "'save this session'.\n"
            "</session_memory_policy>"
        )

    if session_has_prior_reply:
        blocks.append(
            "<conversation_rules>\n"
            "You already greeted the user this session. Do NOT open with hello, "
            "good morning, good to see you, or re-introduce yourself. "
            "Respond directly to what they asked.\n"
            "Speak to the user in second person ('you'). Never narrate in third person "
            "('The user is asking…', 'they want…'). Give your actual answer.\n"
            "</conversation_rules>"
        )

    if intent.minimal:
        blocks.append(
            "<brevity>\n"
            "The user's message is very short (a number, yes/no, or single word). "
            "Reply in one brief sentence unless they asked for detail. "
            "If the message is only a digit (1, 2, 3), reply with just that digit or "
            "one word (e.g. '1' or 'Two.'). Do not say 'ready for task #N', "
            "'first/second/third task', or ask what they want next.\n"
            "</brevity>"
        )

    if intent.git_staging:
        blocks.append(
            "<git_staging_request>\n"
            "User wants to stage git changes. Call run_command with `git add .` "
            "(native function call). If blocked, report the allowlist error and stop — "
            "do not read phaust.toml, do not suggest running git in an external terminal.\n"
            "</git_staging_request>"
        )
    elif intent.shell:
        blocks.append(
            "<shell_rules>\n"
            "Use run_command only for allowlisted prefixes (see phaust.toml). "
            "If a command is blocked, explain the limitation and stop — do not run "
            "a different shell command unless the user asks for one.\n"
            "</shell_rules>"
        )

    if intent.logging_task:
        blocks.append(
            "<logging_task>\n"
            "Append stress-test results to the log file using read_file then edit_file.\n"
            "The user's earlier messages in THIS session are the tests (G1=memory disable, "
            "I2=.git/config block, etc.) — do not refuse or claim 'no tests ran'.\n"
            "Self-assessment must use the test IDs from the prompt (A1, K7, …) and describe "
            "what happened in each test — NOT the read_file/edit_file logging operation.\n"
            "Example line: G1: PASS — memory writes disabled; memorize blocked.\n"
            "Write concrete prose; no [placeholders], TBD, or shuffled labels.\n"
            "</logging_task>"
        )

    return blocks
