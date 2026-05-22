"""Long-term memory — explicit durable facts (key → value)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from phaust.memory.store import MemoryStore


@dataclass
class LongTermMemory:
    """Structured facts the agent or user store on purpose."""

    db: MemoryStore = field(default_factory=MemoryStore)

    def remember(self, key: str, value: str) -> dict[str, Any]:
        self.db.upsert_fact(key, value)
        return {"saved": True, "key": key}

    def recall(self, key: str) -> dict[str, Any]:
        entry = self.db.get_fact(key)
        if not entry:
            return {"key": key, "value": None}
        return {
            "key": key,
            "value": entry["value"],
            "updated_at": entry.get("updated_at"),
        }

    def forget(self, key: str) -> dict[str, Any]:
        self.db.delete_fact(key)
        return {"deleted": key}

    def list_facts(self) -> dict[str, Any]:
        facts = self.db.list_facts()
        return {"count": len(facts), "keys": sorted(facts.keys())}

    def summary_for_prompt(self, max_items: int = 20) -> str:
        facts = self.db.list_facts()
        if not facts:
            return ""
        lines = []
        for key in sorted(facts.keys())[:max_items]:
            lines.append(f"- {key}: {facts[key]['value']}")
        return "<long_term_memory>\n" + "\n".join(lines) + "\n</long_term_memory>"
