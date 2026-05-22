"""Local embedding helpers (API + bag-of-words fallback)."""

from __future__ import annotations

import math
import re
import struct
from typing import Any

import requests


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def bow_vector(tokens: list[str], vocab: dict[str, int]) -> list[float]:
    vec = [0.0] * len(vocab)
    for token in tokens:
        if token in vocab:
            vec[vocab[token]] += 1.0
    return vec


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def pack_embedding(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def unpack_embedding(blob: bytes | None) -> list[float] | None:
    if not blob:
        return None
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


def embed_via_api(
    text: str,
    *,
    base_url: str,
    api_key: str,
    model: str,
) -> list[float] | None:
    try:
        r = requests.post(
            f"{base_url.rstrip('/')}/embeddings",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={"model": model, "input": text},
            timeout=60,
        )
        if not r.ok:
            return None
        data = r.json()["data"][0]["embedding"]
        return [float(x) for x in data]
    except (requests.RequestException, KeyError, IndexError, TypeError, ValueError):
        return None


def embed_fallback(text: str, corpus: list[str]) -> list[float]:
    tokens = tokenize(text)
    vocab: dict[str, int] = {}
    for chunk in corpus:
        for token in tokenize(chunk):
            if token not in vocab:
                vocab[token] = len(vocab)
    if not vocab:
        return [1.0]
    return bow_vector(tokens, vocab)


def embed_pair(
    text: str,
    *,
    base_url: str,
    api_key: str,
    model: str,
    corpus: list[str],
    backend: str | None = None,
) -> tuple[list[float], str]:
    if backend == "api" or backend is None:
        api_vec = embed_via_api(text, base_url=base_url, api_key=api_key, model=model)
        if api_vec:
            return api_vec, "api"
    return embed_fallback(text, corpus), "bow"
