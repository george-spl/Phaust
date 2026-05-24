"""Context memory — working/session layer (live providers + recent conversation)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, TYPE_CHECKING

MEMORY_WRITES_DISABLED = "memory_writes_disabled"

_NO_MEMORY_RE = re.compile(
    r"\bremember\s+nothing(?:\s+(?:this|for)\s+session)?\b"
    r"|\b(?:don'?t|do\s+not)\s+(?:remember|store|save)\s+"
    r"(?:anything|this|it|stuff|that|what\s+we\s+(?:said|discussed))"
    r"(?:\s+(?:this|for)\s+session|\s+session)?\b"
    r"|\b(?:don'?t|do\s+not)\s+(?:remember|store|save)\s+(?:anything\s+)?(?:this\s+)?session\b"
    r"|\bno\s+(?:new\s+)?(?:memory|facts?)\s+(?:this\s+)?session\b"
    r"|\bwithout\s+(?:saving|storing)\s+memory\b"
    r"|\bprivate\s+session\b",
    re.IGNORECASE,
)

# Describing/logging a test (e.g. "scores for remember nothing, enable") — not an opt-out.
_NO_MEMORY_LOGGING_MENTION_RE = re.compile(
    r"\b(?:scores?|self-assessment|block\s+[a-z0-9]+|R5\w*|append\b.*\b(?:scores?|regression))"
    r".{0,80}\bremember\s+nothing\b"
    r"|\bremember\s+nothing\b.{0,40}\b(?:,\s*enable|enable\s+remembering)\b",
    re.IGNORECASE | re.DOTALL,
)

_ENABLE_MEMORY_RE = re.compile(
    r"\b(?:remember|save|store)\s+(?:things|stuff|memories|this\s+session|normally|everything)\s+again\b"
    r"|\b(?:enable|turn\s+on)\s+(?:memory|remembering)(?:\s+writes?)?(?:\s+again)?\b"
    r"|\bturn\s+(?:on|back)\s+remembering\b"
    r"|\bsave\s+(?:this\s+)?session(?:\s+(?:to\s+memory|normally))?\b",
    re.IGNORECASE,
)

_RHETORICAL_MEMORY_RE = re.compile(
    r"\b(?:you|phaust)\s+don'?t\s+remember\b|\bdo\s+you\s+remember\b",
    re.IGNORECASE,
)

from phaust.memory.store import MemoryStore

if TYPE_CHECKING:
    from phaust.memory.compaction import Compactor
    from phaust.memory.long_term import LongTermMemory
    from phaust.memory.semantic import SemanticMemory


@dataclass
class ContextMemory:
    """Session-scoped working memory injected every turn."""

    db: MemoryStore = field(default_factory=MemoryStore)
    max_messages: int = 50
    compact_batch: int = 10
    providers: dict[str, Callable[[], str]] = field(default_factory=dict)
    _session_start_message_id: int | None = None

    @property
    def messages(self) -> list[dict[str, Any]]:
        msgs = self.db.get_messages()
        return [{k: v for k, v in m.items() if k != "_id"} for m in msgs]

    @property
    def session(self) -> dict[str, Any]:
        return self.db.all_session()

    def register_provider(self, name: str, fn: Callable[[], str]) -> Callable[[], str]:
        self.providers[name] = fn
        return fn

    def set_session(self, key: str, value: Any) -> None:
        self.db.set_session(key, value)

    def get_session(self, key: str, default: Any = None) -> Any:
        return self.db.get_session(key, default)

    def append_message(self, message: dict[str, Any]) -> None:
        if message.get("role") == "user" and not str(message.get("content") or "").strip():
            return
        self.db.append_message(message)

    @staticmethod
    def user_requests_no_memory(message: str) -> bool:
        if _RHETORICAL_MEMORY_RE.search(message):
            return False
        if _NO_MEMORY_LOGGING_MENTION_RE.search(message):
            return False
        return bool(_NO_MEMORY_RE.search(message))

    @staticmethod
    def user_requests_memory_again(message: str) -> bool:
        return bool(_ENABLE_MEMORY_RE.search(message))

    def memory_writes_enabled(self) -> bool:
        return not bool(self.get_session(MEMORY_WRITES_DISABLED, False))

    def set_memory_writes_disabled(self, disabled: bool = True) -> None:
        self.set_session(MEMORY_WRITES_DISABLED, disabled)

    def begin_session(self) -> None:
        """Mark where this REPL session started (for end-of-session compaction)."""
        self.db.clear_session_keys(MEMORY_WRITES_DISABLED)
        last = self.db.last_message_id()
        self._session_start_message_id = (last or 0) + 1
        self.db.set_session("_session_start_id", self._session_start_message_id)

    def load(self) -> None:
        removed = self.db.delete_empty_user_messages()
        if removed:
            print(f"Memory: removed {removed} empty user message(s) from context")
        repaired = self.db.repair_message_history()
        extra = repaired["orphan_users"] + repaired["dangling_tail"]
        if extra:
            print(
                f"Memory: repaired context ({repaired['orphan_users']} orphan user, "
                f"{repaired['dangling_tail']} dangling tool tail)"
            )
        start = self.db.get_session("_session_start_id")
        if isinstance(start, int):
            self._session_start_message_id = start

    def maybe_compact(
        self,
        long_term: LongTermMemory,
        semantic: SemanticMemory,
        compactor: Compactor,
    ) -> dict[str, Any] | None:
        """When over max_messages, summarize and remove oldest batch."""
        if not self.memory_writes_enabled():
            return None
        total = self.db.message_count()
        if total <= self.max_messages:
            return None

        overflow = total - self.max_messages
        batch = min(self.compact_batch, overflow)
        to_compact = self.db.pop_oldest_messages(batch)
        if not to_compact:
            return None
        return compactor.compact(to_compact, long_term, semantic, source="compaction")

    def finalize_session(
        self,
        long_term: LongTermMemory,
        semantic: SemanticMemory,
        compactor: Compactor,
    ) -> dict[str, Any] | None:
        """On exit: compact messages from this REPL session into episodic memory."""
        start_id = self._session_start_message_id
        if start_id is None:
            start_id = self.db.get_session("_session_start_id")
        if not isinstance(start_id, int):
            return None

        last_id = self.db.last_message_id()
        if last_id is None or last_id < start_id:
            return None

        to_compact = self.db.get_messages_slice(start_id, last_id)
        if not to_compact:
            return None

        if not self.memory_writes_enabled():
            count = len(to_compact)
            self.db.delete_messages_up_to(last_id)
            self.db.clear_session_keys("_session_start_id", MEMORY_WRITES_DISABLED)
            self._session_start_message_id = None
            return {
                "compacted": count,
                "episode_saved": False,
                "facts_saved": 0,
                "memory_skipped": True,
            }

        result = compactor.compact(
            to_compact, long_term, semantic, source="session_end"
        )
        self.db.delete_messages_up_to(last_id)
        self.db.clear_session_keys("_session_start_id")
        self._session_start_message_id = None
        return result

    def build_prompt_block(self) -> str:
        parts: list[str] = []
        sess = self.session
        display = {k: v for k, v in sess.items() if not str(k).startswith("_")}

        if display:
            lines = [f"  {k}: {v}" for k, v in display.items()]
            parts.append("<session>\n" + "\n".join(lines) + "\n</session>")

        for name, fn in self.providers.items():
            try:
                value = fn()
            except Exception as e:
                value = f"(provider error: {e})"
            parts.append(f"<context>\n<{name}>{value}</{name}>\n</context>")

        return "\n\n".join(parts)
