"""Semantic memory — similarity-based recall over stored episodes."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from phaust.memory.embeddings import (
    cosine,
    embed_pair,
    pack_embedding,
)
from phaust.memory.retrieval import (
    expanded_queries,
    extract_file_hints,
    merge_search_results,
    rank_episodes,
)
from phaust.memory.last_session import (
    build_continue_from_block,
    is_addressing_phaust_only,
    is_generic_last_session_query,
    session_search_queries,
)
from phaust.memory.topics import extract_topic_hints, infer_topic_tags
from phaust.session_state import load_session_state
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
    hybrid_retrieval: bool = True
    filename_boost: float = 0.4
    lexical_weight: float = 0.25
    query_expansion: bool = True

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

        merged_tags = infer_topic_tags(text, extra_tags=tags)
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
            tags=merged_tags or None,
            embedding=pack_embedding(vec),
            embedding_backend=backend,
        )
        pruned = self.db.prune_oldest_episodes(self.max_episodes)
        return {
            "stored": True,
            "id": entry_id,
            "chars": len(text),
            "pruned": pruned,
            "tags": merged_tags,
        }

    def _embed_score(
        self,
        query: str,
        entry: dict[str, Any],
        *,
        corpus: list[str],
        query_vec: list[float],
        backend: str,
    ) -> float:
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
        return cosine(query_vec, entry_vec)

    def _search_single(
        self,
        query: str,
        entries: list[dict[str, Any]],
        *,
        top_k: int,
        hints: list[str] | None = None,
        topic_hints: list[str] | None = None,
        recency_weight: float = 0.0,
        demote_dev_episodes: bool = False,
    ) -> list[dict[str, Any]]:
        query = query.strip()
        if not query or not entries:
            return []

        hints = hints if hints is not None else extract_file_hints(query)
        topic_hints = topic_hints if topic_hints is not None else extract_topic_hints(query)
        corpus = [query] + [e["text"] for e in entries]
        query_vec, backend = embed_pair(
            query,
            base_url=self.base_url,
            api_key=self.api_key,
            model=self.embedding_model or self.model,
            corpus=corpus,
            backend=None,
        )

        if self.hybrid_retrieval:
            return rank_episodes(
                query,
                entries,
                embed_score_fn=lambda q, entry: self._embed_score(
                    q, entry, corpus=corpus, query_vec=query_vec, backend=backend
                ),
                top_k=top_k,
                filename_boost=self.filename_boost,
                lexical_weight=self.lexical_weight,
                topic_hints=topic_hints,
                recency_weight=recency_weight,
                demote_dev_episodes=demote_dev_episodes,
            )

        scored: list[tuple[float, dict[str, Any]]] = []
        for entry in entries:
            score = self._embed_score(
                query, entry, corpus=corpus, query_vec=query_vec, backend=backend
            )
            scored.append((score, entry))
        scored.sort(key=lambda x: x[0], reverse=True)

        results: list[dict[str, Any]] = []
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

    def search(
        self,
        query: str,
        top_k: int = 5,
        *,
        workspace_root: Path | None = None,
    ) -> list[dict[str, Any]]:
        try:
            top_k = int(top_k)
        except (TypeError, ValueError):
            top_k = 5
        entries = self.db.list_episodes()
        query = query.strip()
        if not query or not entries:
            return []

        generic = is_generic_last_session_query(query)
        state = (
            load_session_state(workspace_root.resolve())
            if workspace_root and generic
            else {}
        )
        hints = extract_file_hints(query)
        topic_hints = extract_topic_hints(query)
        if state.get("last_topic"):
            topic_hints = list(
                dict.fromkeys([str(state["last_topic"]), *topic_hints])
            )
        recency_weight = 0.4 if generic else 0.0
        demote_dev = bool(
            generic
            and state.get("last_topic")
            and str(state["last_topic"]).lower() not in ("phaust",)
        )

        if generic and state:
            queries = session_search_queries(query, state, topic_hints=topic_hints)
            lists = [
                self._search_single(
                    q,
                    entries,
                    top_k=top_k + 2,
                    hints=hints,
                    topic_hints=topic_hints,
                    recency_weight=recency_weight,
                    demote_dev_episodes=demote_dev,
                )
                for q in queries
            ]
            return merge_search_results(lists, top_k=top_k)

        if self.query_expansion and (hints or len(query) > 40):
            queries = expanded_queries(query, hints)
            lists = [
                self._search_single(
                    q,
                    entries,
                    top_k=top_k + 2,
                    hints=hints,
                    topic_hints=topic_hints,
                    recency_weight=recency_weight,
                    demote_dev_episodes=demote_dev,
                )
                for q in queries[:6]
            ]
            return merge_search_results(lists, top_k=top_k)

        return self._search_single(
            query,
            entries,
            top_k=top_k,
            hints=hints,
            topic_hints=topic_hints,
            recency_weight=recency_weight,
            demote_dev_episodes=demote_dev,
        )

    def forget(self, entry_id: str) -> dict[str, Any]:
        if not self.db.delete_episode(entry_id):
            return {"error": f"entry '{entry_id}' not found"}
        return {"deleted": entry_id}

    def recall_episode(self, entry_id: str) -> dict[str, Any]:
        """Fetch one episodic memory by UUID."""
        entry = self.db.get_episode(entry_id.strip())
        if not entry:
            return {
                "error": f"episode '{entry_id}' not found",
                "hint": "Use search_semantic for topic search or list_episodes for ids.",
            }
        return {
            "id": entry["id"],
            "text": entry["text"],
            "source": entry.get("source"),
            "tags": entry.get("tags", []),
            "created_at": entry.get("created_at"),
        }

    def list_episode_summaries(self, limit: int = 20) -> list[dict[str, Any]]:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 20
        limit = max(1, min(limit, 100))
        entries = self.db.list_episodes()
        out: list[dict[str, Any]] = []
        for entry in entries[-limit:]:
            text = str(entry.get("text") or "")
            preview = text[:160] + ("…" if len(text) > 160 else "")
            out.append(
                {
                    "id": entry["id"],
                    "preview": preview,
                    "created_at": entry.get("created_at"),
                    "source": entry.get("source"),
                }
            )
        return out

    def build_prompt_block(self, query: str, top_k: int = 5) -> str:
        hits = self.search(query, top_k=top_k)
        if not hits:
            return ""
        lines = []
        for h in hits:
            line = f"- ({h['score']}) {h['text']}"
            if h.get("matched_hints"):
                line += f" [matched: {', '.join(h['matched_hints'])}]"
            if h.get("matched_topics"):
                line += f" [topics: {', '.join(h['matched_topics'])}]"
            if h.get("tags"):
                line += f" [{', '.join(h['tags'])}]"
            lines.append(line)
        return "<semantic_memory>\n" + "\n".join(lines) + "\n</semantic_memory>"

    def build_recall_block(
        self,
        query: str,
        top_k: int = 8,
        *,
        workspace_root: Path | None = None,
    ) -> str:
        """Broader episodic search when the user asks about past conversations."""
        query = query.strip()
        if not query:
            return ""

        generic = is_generic_last_session_query(query)
        state = (
            load_session_state(workspace_root.resolve())
            if workspace_root and generic
            else {}
        )
        hints = extract_file_hints(query)
        topic_hints = extract_topic_hints(query)
        if state.get("last_topic"):
            topic_hints = list(
                dict.fromkeys([str(state["last_topic"]), *topic_hints])
            )

        lists: list[list[dict[str, Any]]] = []
        if generic and state:
            for q in session_search_queries(query, state, topic_hints=topic_hints):
                lists.append(
                    self.search(q, top_k=top_k, workspace_root=workspace_root)
                )
        else:
            extra_terms: list[str] = list(hints)
            lower = query.lower()
            for term in (
                "cursor",
                "message",
                "design",
                "episode",
                "remember",
                "archived",
            ):
                if term in lower and term not in extra_terms:
                    extra_terms.append(term)
            if "phaust" in lower and not is_addressing_phaust_only(query):
                extra_terms.append("phaust")
            if "stress test" in lower or "stress_" in lower:
                extra_terms.append("stress test")

            for q in expanded_queries(query, hints):
                lists.append(self.search(q, top_k=top_k, workspace_root=workspace_root))
            for term in extra_terms:
                if term.lower() not in query.lower():
                    lists.append(
                        self.search(term, top_k=top_k, workspace_root=workspace_root)
                    )

        hits = merge_search_results(lists, top_k=top_k)

        parts: list[str] = []
        if state:
            block = build_continue_from_block(state)
            if block:
                parts.append(block)
        if hits:
            parts.append("<episodes_matching_query>")
            for hit in hits:
                hint_note = ""
                if hit.get("matched_hints"):
                    hint_note = f" matched={hit['matched_hints']}"
                parts.append(
                    f"### id={hit['id']} (score={hit.get('score')}{hint_note})\n"
                    f"{hit.get('text', '')}"
                )
            parts.append("</episodes_matching_query>")

        recent = self.list_episode_summaries(limit=10)
        if recent:
            lines = [
                f"- {e['id']}: {e['preview']}" for e in reversed(recent)
            ]
            parts.append(
                "<recent_episodes>\n"
                + "\n".join(lines)
                + "\n</recent_episodes>"
            )

        if not parts:
            return ""

        file_note = ""
        if hints:
            file_note = (
                f"Query mentions file/artifact: {', '.join(hints)}. "
                "Prefer episodes that reference those names.\n\n"
            )

        lead = (
            "The user is asking about past conversations. Prefer <continue_from> for "
            '"last time" questions, then summarize in prose — do not paste raw lists.'
            if generic and state
            else
            "The user is asking about past conversations. Use this archive — do not "
            "claim you have no record until you have checked these episodes. "
            "For a specific id use recall_episode."
        )
        return (
            "<memory_recall>\n"
            + lead
            + "\n\n"
            + file_note
            + "\n\n".join(parts)
            + "\n</memory_recall>"
        )
