"""Compiled patterns for turn intent classification (Phaust-2)."""

from __future__ import annotations

import re

WRITE_INTENT = re.compile(
    r"\b(write|add|insert|append|edit|replace|overwrite|create|put|delete|remove|clear|empty|"
    r"comment\s+in|update\s+the\s+file|new\s+file)\b"
    r"|\bmake\s+(?:a\s+)?(?:new\s+)?(?:file|changes?\s+to)\b",
    re.I,
)
APPEND_INTENT = re.compile(
    r"\b(?:more|another|additional|\d+\s+more)\s+lines?\b|\bappend\b",
    re.I,
)
PROFILE_QUESTION = re.compile(
    r"\b(?:what do you know about me|know anything about me|anything about me"
    r"|tell me about myself|who am i\b|about my (?:life|job|work)"
    r"|what(?:'s| is) my (?:name|job|age|goal))\b",
    re.I,
)
MEMORY_RECALL = re.compile(
    r"\b(?:do you remember|don'?t you remember|you don'?t remember"
    r"|recall\s+episode|what did we (?:say|discuss|talk about)"
    r"|\b(?:what|how|do you|did we|tell me about).{0,50}last session\b"
    r"|\bprevious session\b"
    r"|what were we (?:discussing|talking about)"
    r"|what (?:did )?I (?:just )?memorize|what I memorized"
    r"|something we discussed|discussed earlier|previous(?:ly)?\s+(?:session|conversation)"
    r"|(?:last|previous)\s+time\s+we\b|literally\s+last\s+time"
    r"|sent .* message|message to cursor|earlier today)\b",
    re.I,
)
# Bare "recall" only when requesting a lookup, not "you can recall now" feedback
RECALL_LOOKUP = re.compile(
    r"^\s*recall\s+\w|"
    r"\brecall\s+episode\b|"
    r"\bdo you recall\b|"
    r"\bwhat did (?:we|i) recall\b",
    re.I,
)
FEEDBACK_NOT_MEMORY = re.compile(
    r"^\s*(?:good|great|nice|perfect|excellent|yes|ok|okay)\b"
    r"|\bimprovements?\s+every\s+day\b"
    r"|\b(?:now\s+)?you\s+can\s+(?:actually\s+)?recall\b"
    r"|\b(?:that'?s|this is)\s+(?:better|correct|right)\b",
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
REMEMBER_KV = re.compile(
    r"^\s*remember\s+([a-z_][\w]*)\s*=\s*(.+?)\s*$",
    re.I,
)
READ_REQUEST = re.compile(
    r"\bread\b.*\.(?:py|md|txt|toml|json)\b|\bread\b.*\blines?\s+\d",
    re.I,
)
CODE_SEARCH = re.compile(
    r"\b(?:find|where is|locate|grep|search for)\b",
    re.I,
)
LIST_REQUEST = re.compile(
    r"\blist\b.*\b(?:files?|directory|folder)\b|\blist_directory\b|\blist_files\b",
    re.I,
)
# Question-oriented cross-session recall — not bare "last session" in user narratives
CROSS_SESSION = re.compile(
    r"\b(?:what did we do|in testing|prior session|stress_c1|earlier today"
    r"|(?:what|how|do you|did we).{0,50}last session)\b",
    re.I,
)
MEMORIZE_ARCHIVE = re.compile(
    r"\b(?:pause and archive|archive (?:this|everything|the campaign|for later)"
    r"|save (?:this |everything )?for later|memorize this campaign)\b",
    re.I,
)
NARRATIVE_NEW_CONTEXT = re.compile(
    r"\b(?:we ended last session|last session (?:right )?when|our (?:campaign|party|allies|squadron))\b",
    re.I,
)
LOGGING_TASK = re.compile(
    r"\btest_logging(?:_\d+)?(?:_\d+-\d+-\d+)?\.txt\b|"
    r"\b(?:operator scores|test scores|self-assessment|Phaust overall opinion)\b|"
    r"\b(?:tests?\s+[A-Z]\d|opinion on tests?\s+[A-Z]|append (?:your )?opinion)\b",
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
    r"(?:^\s*(?:search_semantic|recall_episode|list_episodes|list_memories|forget_semantic)\b|"
    r"\b(?:search_semantic|recall_episode|list_episodes)\b)",
    re.I,
)
