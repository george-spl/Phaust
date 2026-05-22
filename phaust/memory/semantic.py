"""Semantic memory — similarity-based recall over stored episodes."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from phaust.memory.embeddings import (
    cosine,
    embed_pair,
    pack_embedding,
)
from phaust.memory.store import MemoryStore


@dataclass
class SemanticMemory:
    """Embedding-backed (or local fallback) retrieval over notes and snippets."""

    db: MemoryStore = field(default_factory=MemoryStore)
    base_url: str = "http://127.0.0.1:1234/v1"
    api_key: str = "NO_API_KEY"
    model: str = "qwen/qwen3.5-9b"
    embedding_model: str | None = None
    max_episodes: int = 500

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")

    def store(
        self,
        text: str,
        *,
        source: str = "user",
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        text = text.strip()
        if not text:
            return {"error": "text cannot be empty"}

        entry_id = str(uuid.uuid4())
        corpus = [text] + [e["text"] for e in self.db.list_episodes()]
        vec, backend = embed_pair(
            text,
            base_url=self.base_url,
            api_key=self.api_key,
            model=self.embedding_model or self.model,
            corpus=corpus,
        )
        self.db.insert_episode(
            entry_id=entry_id,
            text=text,
            source=source,
            tags=tags,
            embedding=pack_embedding(vec),
            embedding_backend=backend,
        )
        pruned = self.db.prune_oldest_episodes(self.max_episodes)
        return {
            "stored": True,
            "id": entry_id,
            "chars": len(text),
            "pruned": pruned,
        }

    def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        query = query.strip()
        entries = self.db.list_episodes()
        if not query or not entries:
            return []

        corpus = [query] + [e["text"] for e in entries]
        query_vec, backend = embed_pair(
            query,
            base_url=self.base_url,
            api_key=self.api_key,
            model=self.embedding_model or self.model,
            corpus=corpus,
            backend=None,
        )

        scored: list[tuple[float, dict[str, Any]]] = []
        for entry in entries:
            stored = entry.get("embedding")
            if stored and entry.get("embedding_backend") == backend:
                entry_vec = stored
            else:
                entry_vec, _ = embed_pair(
                    entry["text"],
                    base_url=self.base_url,
                    api_key=self.api_key,
                    model=self.embedding_model or self.model,
                    corpus=corpus,
                    backend=backend,
                )
            score = cosine(query_vec, entry_vec)
            scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for score, entry in scored[:top_k]:
            if score <= 0:
                continue
            results.append(
                {
                    "id": entry["id"],
                    "text": entry["text"],
                    "score": round(score, 4),
                    "source": entry.get("source"),
                    "tags": entry.get("tags", []),
                    "created_at": entry.get("created_at"),
                }
            )
        return results

    def forget(self, entry_id: str) -> dict[str, Any]:
        if not self.db.delete_episode(entry_id):
            return {"error": f"entry '{entry_id}' not found"}
        return {"deleted": entry_id}

    def build_prompt_block(self, query: str, top_k: int = 5) -> str:
        hits = self.search(query, top_k=top_k)
        if not hits:
            return ""
        lines = [
            f"- ({h['score']}) {h['text']}"
            + (f" [{', '.join(h['tags'])}]" if h.get("tags") else "")
            for h in hits
        ]
        return "<semantic_memory>\n" + "\n".join(lines) + "\n</semantic_memory>"
