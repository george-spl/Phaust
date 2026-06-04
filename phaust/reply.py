"""User-facing reply cleanup (no orchestration regex for intents)."""

from __future__ import annotations

import re
from typing import Any

_META_NARRATION_START = re.compile(
    r"^(?:The user (?:is asking|wants|has asked|requested)|"
    r"\w+ is asking me to|"
    r"I (?:need to|should|must) (?:analyze|understand|consider|help|respond)|"
    r"Let me (?:analyze|think|consider|break down)|"
    r"This is a (?:broad|complex|large|non-trivial|significant|important))[\s.,!]",
    re.IGNORECASE,
)


def strip_meta_preamble(text: str) -> str:
    paragraphs = [p.strip() for p in re.split(r"\n\n+", text) if p.strip()]
    while paragraphs and _META_NARRATION_START.match(paragraphs[0]):
        paragraphs.pop(0)
    return "\n\n".join(paragraphs) if paragraphs else text


def is_planning_monologue(text: str) -> bool:
    """Model narrates steps instead of acting (common on logging/edit turns)."""
    t = text.strip()
    if len(t) < 400:
        return False
    lower = t.lower()
    markers = (
        "let's see",
        "let me recheck",
        "first, i need",
        "wait,",
        "so first",
        "the user wants me to",
        "i need to check",
    )
    hits = sum(1 for m in markers if m in lower)
    return hits >= 2 or (hits >= 1 and len(t) > 1200)


def is_meta_narration(text: str) -> bool:
    t = text.strip()
    if not t:
        return False
    if _META_NARRATION_START.match(t):
        return True
    if len(t) < 500 and re.search(r"\bThe user\b", t, re.I):
        if not re.search(
            r"\b(I can|Let's|Here'?s|Would you|We can|Sure|Happy to|Understood)\b",
            t,
            re.I,
        ):
            return True
    return False


def clean_reply(text: str) -> str:
    """Strip Qwen chain-of-thought / thinking blocks from user-facing text."""
    text = text.strip()
    text = re.sub(
        r"<think(?:ing)?>[\s\S]*?</think(?:ing)?>",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()
    text = re.sub(
        r"<tool_call>[\s\S]*?</tool_call>",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()
    text = strip_meta_preamble(text)

    if "Thinking Process" not in text and not re.search(
        r"^\d+\.\s+\*\*Analyze", text, re.MULTILINE
    ):
        return text

    draft = re.search(
        r"\*Draft:\*\*\s*\n([\s\S]+?)(?:\n\d+\.\s+\*\*Review|\n\*\*Review against|$)",
        text,
    )
    if draft:
        body = draft.group(1).strip()
        body = re.sub(r"^\*?Draft:?\*?\s*", "", body)
        if len(body) > 80:
            return body

    paragraphs = [p.strip() for p in re.split(r"\n\n+", text) if len(p.strip()) > 100]
    for para in reversed(paragraphs):
        if re.match(r"^\d+\.", para):
            continue
        if any(
            skip in para[:60]
            for skip in ("Analyze the", "Constraint", "Drafting the", "**")
        ):
            continue
        return para
    return text


def message_text(msg: dict[str, Any]) -> str:
    """Prefer final content; avoid dumping raw reasoning traces to the user."""
    content = msg.get("content")
    if content and str(content).strip():
        return clean_reply(str(content))

    for key in ("reasoning_content", "reasoning"):
        val = msg.get(key)
        if val and str(val).strip():
            return clean_reply(str(val))
    return ""
