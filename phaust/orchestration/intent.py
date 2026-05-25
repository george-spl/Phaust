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


def _recall_past(message: str) -> bool:
    if p.EXPLICIT_MEMORY_TOOL.search(message):
        return False
    if is_supplying_new_context(message):
        return False
    return bool(
        p.MEMORY_RECALL.search(message)
        or p.EPISODE_UUID.search(message)
        or re.search(r"\brecall\b", message, re.I)
        or p.CROSS_SESSION.search(message)
    )


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
    if len(text) <= 12 and p.LONE_DIGIT.fullmatch(text):
        return True
    if len(text) <= 20 and not re.search(r"\s{2,}", text):
        words = text.split()
        if len(words) <= 2 and not p.WRITE_INTENT.search(text):
            return True
    return False


def classify_turn(message: str) -> TurnIntent:
    key = _fact_recall_key(message)
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
        minimal=_minimal(message),
    )


def memorize_text_from_message(message: str) -> str | None:
    for pattern in p.MEMORIZE_TEXT:
        match = pattern.search(message)
        if match:
            text = match.group(1).strip()
            if text:
                return text
    return None
