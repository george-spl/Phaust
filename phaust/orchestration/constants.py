"""Tool groupings used by turn policy."""

from __future__ import annotations

MEMORY_STORE_TOOLS = frozenset({"memorize", "remember"})
MEMORY_RECALL_TOOLS = frozenset({
    "recall_episode",
    "recall",
    "search_semantic",
    "list_episodes",
    "list_memories",
})
