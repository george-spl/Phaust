"""Helpers for “what did we discuss last time?” — recency and session pointer."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

_GENERIC_LAST_SESSION = re.compile(
    r"\b(?:what were we (?:discussing|talking about)|what did we (?:discuss|talk about)"
    r"|(?:last|previous)\s+time(?:\s+we)?\b|literally\s+last\s+time"
    r"|discussing\s+last\s+time|last\s+conversation)\b",
    re.I,
)

_DEV_EPISODE_MARKERS = re.compile(
    r"\b(?:stress[_ ]?test|test_logging|block\s+[a-z]\d|round\s+2\s+regression|phaust-1)\b",
    re.I,
)

_ADDRESSING_PHAUST = re.compile(r"^\s*(?:hello|hi|hey|good\s+morning)\s*,?\s*phaust\b", re.I)


def is_generic_last_session_query(query: str) -> bool:
    return bool(_GENERIC_LAST_SESSION.search(query))


def is_addressing_phaust_only(query: str) -> bool:
    """Greeting the agent by name — not a request about Phaust development."""
    return bool(_ADDRESSING_PHAUST.match(query.strip()))


def is_dev_episode_text(text: str) -> bool:
    return bool(_DEV_EPISODE_MARKERS.search(text))


def recency_score(created_at: str | None, *, newest: str | None, oldest: str | None) -> float:
    """0–1 boost for newer episodes when sorting by date."""
    if not created_at or not newest or not oldest or newest == oldest:
        return 0.5 if created_at else 0.0
    try:
        t = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
        n = datetime.fromisoformat(str(newest).replace("Z", "+00:00"))
        o = datetime.fromisoformat(str(oldest).replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    span = (n - o).total_seconds()
    if span <= 0:
        return 1.0
    return max(0.0, min(1.0, (t - o).total_seconds() / span))


def build_continue_from_block(state: dict[str, Any]) -> str:
    if not state:
        return ""
    lines = [
        "<continue_from>",
        'User asked what you discussed "last time". Prefer this pointer over older '
        "stress-test or Phaust-dev archives unless they asked about tests.",
    ]
    if state.get("last_topic"):
        lines.append(f"- Last topic: {state['last_topic']}")
    if state.get("last_user_preview"):
        lines.append(f"- Last user message: {state['last_user_preview']}")
    if state.get("last_assistant_preview"):
        lines.append(f"- Last assistant reply: {state['last_assistant_preview']}")
    if state.get("last_episode_id"):
        lines.append(
            f"- Most recent episode id: {state['last_episode_id']} "
            "(use recall_episode if you need detail, then summarize in prose)"
        )
    if state.get("last_files"):
        lines.append(f"- Recent files: {', '.join(state['last_files'][-4:])}")
    if state.get("updated_at"):
        lines.append(f"- Pointer saved: {state['updated_at']}")
    lines.append("</continue_from>")
    return "\n".join(lines)


def session_search_queries(
    query: str,
    state: dict[str, Any],
    *,
    topic_hints: list[str],
) -> list[str]:
    """Extra semantic searches for generic ‘last time’ questions."""
    out: list[str] = []
    seen: set[str] = set()

    def add(q: str) -> None:
        key = q.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(q.strip())

    if state.get("last_topic"):
        add(str(state["last_topic"]))
    for topic in state.get("last_topics") or []:
        add(str(topic))
    for hint in topic_hints:
        add(hint)
    preview = f"{state.get('last_user_preview', '')} {state.get('last_assistant_preview', '')}"
    for tag in topic_hints:
        if tag in preview.lower():
            add(tag)
    if not is_generic_last_session_query(query):
        add(query)
    return out[:6]
