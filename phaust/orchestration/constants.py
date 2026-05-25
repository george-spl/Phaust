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
# Tools that may bypass the model for the final reply (see should_auto_return_recall_outcome)
MEMORY_LOOKUP_TOOLS = frozenset({
    "recall_episode",
    "list_episodes",
    "list_memories",
})
