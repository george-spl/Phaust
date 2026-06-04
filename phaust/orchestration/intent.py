"""Turn intent classification — single entry point per user message."""

from __future__ import annotations

import re
from dataclasses import dataclass

from phaust.orchestration import patterns as p


@dataclass(frozen=True)
class TurnIntent:
    """Structured flags derived from one user message."""

    message: str
    file_change: bool = False
    append: bool = False
    create: bool = False
    logging_task: bool = False
    shell: bool = False
    git_staging: bool = False
    memorize: bool = False
    recall_past: bool = False
    fact_recall: bool = False
    fact_recall_key: str | None = None
    explicit_memory_tool: bool = False
    profile_question: bool = False
    store_fact: bool = False
    store_fact_key: str | None = None
    store_fact_value: str | None = None
    read_request: bool = False
    code_search: bool = False
    list_request: bool = False
    minimal: bool = False

    @property
    def wants_write(self) -> bool:
        return self.file_change or self.append or self.logging_task

    @property
    def memory_question(self) -> bool:
        return self.recall_past or bool(p.EPISODE_UUID.search(self.message))

    @property
    def skip_synthesis_default(self) -> bool:
        return self.wants_write or self.logging_task


def _file_change(message: str) -> bool:
    if p.SHELL_INTENT.search(message) or p.GIT_STAGING.search(message):
        return False
    return bool(p.WRITE_INTENT.search(message))


def _memorize(message: str) -> bool:
    if p.MEMORIZE_INTENT.search(message) or p.MEMORIZE_ARCHIVE.search(message):
        return True
    if p.MEMORY_RECALL.search(message) and not re.search(r"\bmemorize\b", message, re.I):
        return False
    # Rich new context (e.g. campaign pause state) — store, do not recall-search
    if is_supplying_new_context(message) and len(message.strip()) > 120:
        return True
    return False


def is_supplying_new_context(message: str) -> bool:
    """User is telling a story to save — not asking what Phaust remembers."""
    if p.MEMORY_RECALL.search(message):
        return False
    return bool(p.NARRATIVE_NEW_CONTEXT.search(message) or p.MEMORIZE_ARCHIVE.search(message))


def is_feedback_not_memory(message: str) -> bool:
    """Praise or meta commentary — not asking what was remembered."""
    return bool(p.FEEDBACK_NOT_MEMORY.search(message))


def _recall_past(message: str) -> bool:
    if p.EXPLICIT_MEMORY_TOOL.search(message):
        return False
    if is_supplying_new_context(message):
        return False
    if is_feedback_not_memory(message):
        return False
    return bool(
        p.MEMORY_RECALL.search(message)
        or p.RECALL_LOOKUP.search(message)
        or p.EPISODE_UUID.search(message)
        or p.CROSS_SESSION.search(message)
    )


def _store_fact(message: str) -> tuple[str, str] | None:
    match = p.REMEMBER_KV.match(message.strip())
    if not match:
        return None
    return match.group(1), match.group(2).strip()


def _fact_recall_key(message: str) -> str | None:
    match = p.FACT_RECALL.match(message.strip())
    if not match:
        return None
    key = match.group(1)
    if p.EPISODE_UUID.fullmatch(key):
        return None
    return key


def _minimal(message: str) -> bool:
    text = message.strip()
    if not text:
        return False
    if p.EXPLICIT_MEMORY_TOOL.search(text) or p.FACT_RECALL.match(text):
        return False
    if len(text) <= 12 and p.LONE_DIGIT.fullmatch(text):
        return True
    if len(text) <= 20 and not re.search(r"\s{2,}", text):
        words = text.split()
        if len(words) <= 2 and not p.WRITE_INTENT.search(text):
            return True
    return False


def classify_turn(message: str) -> TurnIntent:
    key = _fact_recall_key(message)
    stored = _store_fact(message)
    return TurnIntent(
        message=message,
        file_change=_file_change(message),
        append=bool(p.APPEND_INTENT.search(message)),
        create=bool(p.CREATE_FILE.search(message)),
        logging_task=bool(p.LOGGING_TASK.search(message)),
        shell=bool(p.SHELL_INTENT.search(message)),
        git_staging=bool(p.GIT_STAGING.search(message)),
        memorize=_memorize(message),
        recall_past=_recall_past(message),
        fact_recall=key is not None,
        fact_recall_key=key,
        explicit_memory_tool=bool(p.EXPLICIT_MEMORY_TOOL.search(message)),
        profile_question=bool(p.PROFILE_QUESTION.search(message)),
        store_fact=stored is not None,
        store_fact_key=stored[0] if stored else None,
        store_fact_value=stored[1] if stored else None,
        read_request=bool(p.READ_REQUEST.search(message)),
        code_search=bool(p.CODE_SEARCH.search(message)),
        list_request=bool(p.LIST_REQUEST.search(message)),
        minimal=_minimal(message),
    )


def is_conversational_turn(intent: TurnIntent) -> bool:
    """Pure chat — not file/shell/memory-tool work."""
    if intent.minimal:
        return True
    return not (
        intent.wants_write
        or intent.shell
        or intent.logging_task
        or intent.memorize
        or intent.store_fact
        or intent.fact_recall
        or intent.recall_past
        or intent.explicit_memory_tool
        or intent.profile_question
        or intent.read_request
        or intent.code_search
        or intent.list_request
    )


def memorize_text_from_message(message: str) -> str | None:
    for pattern in p.MEMORIZE_TEXT:
        match = pattern.search(message)
        if match:
            text = match.group(1).strip()
            if text:
                return text
    return None
