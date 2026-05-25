"""Topic hints for tagged episodic memory (Layer 2)."""

from __future__ import annotations

import re
from typing import Any

_TOPIC_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("starfinder", re.compile(r"\bstarfinder\b", re.I)),
    ("pathfinder", re.compile(r"\bpathfinder\b", re.I)),
    ("tabletop", re.compile(r"\b(?:campaign|rpg|tabletop|dnd|d&d)\b", re.I)),
    ("career", re.compile(r"\b(?:career|job|resume|hyve|automation engineer|promotion)\b", re.I)),
    ("phaust", re.compile(r"\b(?:phaust|stress[_ ]?test|test_logging)\b", re.I)),
    ("character", re.compile(r"\b(?:character sheet|pc build|ancestry|class)\b", re.I)),
]

_FOLDER_TOPIC_HINTS = (
    ("characters/", "character"),
    ("campaigns/", "tabletop"),
    ("notes/", "notes"),
)


def infer_topic_tags(text: str, *, extra_tags: list[str] | None = None) -> list[str]:
    """Derive topic tags from message or file path text."""
    tags: list[str] = []
    seen: set[str] = set()

    def add(tag: str) -> None:
        t = tag.strip().lower()
        if t and t not in seen:
            seen.add(t)
            tags.append(t)

    for name, pattern in _TOPIC_PATTERNS:
        if pattern.search(text):
            add(name)

    lower = text.lower().replace("\\", "/")
    for prefix, topic in _FOLDER_TOPIC_HINTS:
        if prefix in lower:
            add(topic)

    for tag in extra_tags or []:
        add(tag)

    return tags


def extract_topic_hints(query: str) -> list[str]:
    """Topics implied by the user query for retrieval boosting."""
    return infer_topic_tags(query)


def tag_match_score(entry: dict[str, Any], topic_hints: list[str]) -> float:
    if not topic_hints:
        return 0.0
    raw = entry.get("tags") or []
    if isinstance(raw, str):
        tags = [raw.lower()]
    else:
        tags = [str(t).lower() for t in raw]
    if not tags:
        text_tags = infer_topic_tags(str(entry.get("text") or ""))
        tags = text_tags
    hits = sum(1 for hint in topic_hints if hint in tags)
    return min(1.0, hits / max(len(topic_hints), 1))
