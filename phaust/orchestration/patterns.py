"""Compiled patterns for turn intent classification (Phaust-2)."""

from __future__ import annotations

import re

WRITE_INTENT = re.compile(
    r"\b(write|add|insert|append|edit|replace|overwrite|create|make|put|delete|remove|clear|empty|"
    r"comment\s+in|update\s+the\s+file|new\s+file)\b",
    re.I,
)
APPEND_INTENT = re.compile(
    r"\b(?:more|another|additional|\d+\s+more)\s+lines?\b|\bappend\b",
    re.I,
)
MEMORY_RECALL = re.compile(
    r"\b(?:do you remember|don'?t you remember|you don'?t remember"
    r"|recall\s+episode|what did we (?:say|discuss|talk about)"
    r"|what (?:did )?I (?:just )?memorize|what I memorized"
    r"|something we discussed|discussed earlier|previous(?:ly)?\s+(?:session|conversation)"
    r"|sent .* message|message to cursor|earlier today|\brecall\b)\b",
    re.I,
)
MEMORIZE_INTENT = re.compile(
    r"^\s*memorize\b|\bmemorize\s*:|\bremember\s+that\b"
    r"|\b(?:please|make sure to)\s+remember\s+(?:this|that)\b",
    re.I,
)
EPISODE_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)
SHELL_INTENT = re.compile(
    r"\b(?:run_command|run\s+(?:git|python|curl)|git\s+\w+|stage\s+(?:all\s+)?changes?"
    r"|curl\s+http)\b",
    re.I,
)
GIT_STAGING = re.compile(
    r"\b(?:stage\s+(?:all\s+)?changes?(?:\s+with\s+git)?|git\s+add\b)\b",
    re.I,
)
FACT_RECALL = re.compile(r"^\s*recall\s+([a-z_][\w]*)\s*$", re.I)
CROSS_SESSION = re.compile(
    r"\b(?:what did we do|in testing|last session|prior session|stress_c1|earlier today)\b",
    re.I,
)
LOGGING_TASK = re.compile(
    r"\btest_logging(?:_\d+)?(?:_\d+-\d+-\d+)?\.txt\b|"
    r"\b(?:George scores|self-assessment|Phaust overall opinion)\b",
    re.I,
)
CREATE_FILE = re.compile(
    r"\b(create|make|new)\b.*\b(file|\.txt|\.md|\.py)\b|\bcreate\s+a\s+file\b",
    re.I,
)
MEMORIZE_TEXT = (
    re.compile(r"^\s*memorize\s*:\s*(.+)", re.I | re.S),
    re.compile(r"^\s*memorize\s+(.+)", re.I | re.S),
    re.compile(r"\bremember\s+that\s+(.+)", re.I | re.S),
)
LONE_DIGIT = re.compile(r"\d{1,3}")
EXPLICIT_MEMORY_TOOL = re.compile(
    r"^\s*(?:search_semantic|recall_episode|list_episodes|list_memories|forget_semantic)\b",
    re.I,
)
