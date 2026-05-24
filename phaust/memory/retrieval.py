"""Hybrid episodic retrieval: embeddings + lexical / filename signals."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any, Callable

from phaust.memory.embeddings import tokenize

_FILE_PATH_RE = re.compile(
    r"\b[\w./\\-]+\.(?:txt|md|py|toml|json|yaml|yml)\b",
    re.I,
)
_STRESS_ARTIFACT_RE = re.compile(r"\bstress_[a-z0-9_]+\b", re.I)
_TEST_BLOCK_RE = re.compile(r"\b(?:block|test|round)\s+([a-z0-9]+)\b", re.I)


def extract_file_hints(query: str) -> list[str]:
    """Filenames, stems, and stress-test artifact ids mentioned in the query."""
    hints: set[str] = set()
    for match in _FILE_PATH_RE.finditer(query):
        raw = match.group(0).replace("\\", "/")
        hints.add(raw.lower())
        name = PurePosixPath(raw).name.lower()
        hints.add(name)
        stem = PurePosixPath(raw).stem.lower()
        if stem:
            hints.add(stem)
    for match in _STRESS_ARTIFACT_RE.finditer(query):
        hints.add(match.group(0).lower())
    return sorted(hints)


def expanded_queries(query: str, hints: list[str] | None = None) -> list[str]:
    """Search variants for cross-session file/topic recall."""
    hints = hints if hints is not None else extract_file_hints(query)
    out: list[str] = []
    seen: set[str] = set()

    def add(q: str) -> None:
        text = q.strip()
        if not text:
            return
        key = text.lower()
        if key in seen:
            return
        seen.add(key)
        out.append(text)

    add(query)
    for hint in hints:
        add(hint)
        if "." in hint:
            add(PurePosixPath(hint).stem)
    lower = query.lower()
    for term in ("round 1", "round 2", "prior session", "last session", "earlier today"):
        if term in lower:
            add(term)
    return out


def filename_match_score(text: str, hints: list[str]) -> float:
    if not hints:
        return 0.0
    lower = text.lower()
    hits = sum(1 for hint in hints if hint in lower)
    return min(1.0, hits / max(len(hints), 1))


def lexical_overlap_score(query: str, text: str) -> float:
    q_tokens = set(tokenize(query))
    if not q_tokens:
        return 0.0
    t_tokens = set(tokenize(text))
    return len(q_tokens & t_tokens) / len(q_tokens)


def hybrid_score(
    *,
    embed_score: float,
    query: str,
    text: str,
    hints: list[str],
    filename_boost: float,
    lexical_weight: float,
) -> float:
    fname = filename_match_score(text, hints)
    lexical = lexical_overlap_score(query, text)
    if hints and fname == 0:
        # Query names a file — generic token overlap must not outrank real file hits.
        lexical *= 0.15
    score = embed_score + (filename_boost * fname) + (lexical_weight * lexical)
    if hints and fname == 0:
        score = min(score, embed_score * 0.75)
    return min(1.0, score)


def _sort_key(
    combined: float,
    embed: float,
    fname: float,
    matched_count: int,
) -> tuple[float, float, float, int]:
    return (combined, fname, embed, matched_count)


def rank_episodes(
    query: str,
    entries: list[dict[str, Any]],
    *,
    embed_score_fn: Callable[[str, dict[str, Any]], float],
    top_k: int = 5,
    filename_boost: float = 0.4,
    lexical_weight: float = 0.25,
    min_score: float = 0.0,
) -> list[dict[str, Any]]:
    """Rank episodes with embedding score plus lexical / filename boosts."""
    hints = extract_file_hints(query)
    scored: list[tuple[tuple[float, float, float, int], float, dict[str, Any]]] = []

    for entry in entries:
        text = str(entry.get("text") or "")
        embed = embed_score_fn(query, entry)
        fname = filename_match_score(text, hints)
        combined = hybrid_score(
            embed_score=embed,
            query=query,
            text=text,
            hints=hints,
            filename_boost=filename_boost,
            lexical_weight=lexical_weight,
        )
        if combined <= min_score and embed <= min_score:
            continue
        matched = [h for h in hints if h in text.lower()]
        key = _sort_key(combined, embed, fname, len(matched))
        scored.append((key, combined, entry))

    scored.sort(key=lambda row: row[0], reverse=True)
    results: list[dict[str, Any]] = []
    for _key, score, entry in scored[:top_k]:
        results.append(
            {
                "id": entry["id"],
                "text": entry["text"],
                "score": round(score, 4),
                "source": entry.get("source"),
                "tags": entry.get("tags", []),
                "created_at": entry.get("created_at"),
                "matched_hints": [h for h in hints if h in str(entry.get("text") or "").lower()],
            }
        )
    return results


def merge_search_results(
    result_lists: list[list[dict[str, Any]]],
    *,
    top_k: int,
) -> list[dict[str, Any]]:
    """Merge multiple search result lists, keeping the best score per episode id."""
    best: dict[str, dict[str, Any]] = {}
    for hits in result_lists:
        for hit in hits:
            eid = str(hit.get("id") or "")
            if not eid:
                continue
            prev = best.get(eid)
            if prev is None or float(hit.get("score") or 0) > float(prev.get("score") or 0):
                best[eid] = hit
    merged = sorted(
        best.values(),
        key=lambda h: (
            float(h.get("score") or 0),
            len(h.get("matched_hints") or []),
        ),
        reverse=True,
    )
    return merged[:top_k]
