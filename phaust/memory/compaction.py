"""Compact old chat messages into semantic episodes + long-term facts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

import requests

if TYPE_CHECKING:
    from phaust.memory.long_term import LongTermMemory
    from phaust.memory.semantic import SemanticMemory


def _format_messages_for_prompt(messages: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for msg in messages:
        role = msg.get("role", "?")
        content = (msg.get("content") or "").strip()
        if role == "tool":
            lines.append(f"tool: {content[:500]}")
            continue
        if role == "assistant" and msg.get("tool_calls"):
            names = [
                tc.get("function", {}).get("name", "?")
                for tc in msg["tool_calls"]
            ]
            lines.append(f"assistant: [called {', '.join(names)}]")
            if content:
                lines.append(f"assistant: {content}")
            continue
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


@dataclass
class Compactor:
    base_url: str = "http://127.0.0.1:1234/v1"
    api_key: str = "NO_API_KEY"
    model: str = "qwen/qwen3.5-9b"
    timeout: int = 120

    def compact(
        self,
        messages: list[dict[str, Any]],
        long_term: LongTermMemory,
        semantic: SemanticMemory,
        *,
        source: str = "compaction",
        period: str | None = None,
    ) -> dict[str, Any]:
        if not messages:
            return {"compacted": 0}

        transcript = _format_messages_for_prompt(messages)
        if not transcript.strip():
            return {"compacted": 0}

        period = period or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        extracted = self._extract(transcript, period)

        summary = extracted.get("summary", "").strip()
        highlights = extracted.get("highlights") or []
        episode_id: str | None = None
        if summary:
            body = f"[{period}] {summary}"
            if highlights:
                bullets = "\n".join(f"- {h.strip()}" for h in highlights if str(h).strip())
                if bullets:
                    body = f"{body}\n\nHighlights:\n{bullets}"
            stored = semantic.store(body, source=source, tags=["episode", period[:7]])
            episode_id = stored.get("id")

        facts = extracted.get("facts") or []
        saved = 0
        for item in facts:
            key = (item.get("key") or "").strip()
            value = (item.get("value") or "").strip()
            if key and value and self._should_save_fact(key, value):
                long_term.remember(key, value)
                saved += 1

        return {
            "compacted": len(messages),
            "episode_saved": bool(summary),
            "episode_id": episode_id,
            "facts_saved": saved,
        }

    def _extract(self, transcript: str, period: str) -> dict[str, Any]:
        system = (
            "You compress chat logs into durable memory. "
            "Reply with ONLY valid JSON, no markdown:\n"
            '{"summary": "2-4 sentences with date and main topics/decisions", '
            '"highlights": ["notable quote or moment", "..."], '
            '"facts": [{"key": "snake_case_key", "value": "short fact"}]}\n'
            "summary: what happened overall. "
            "highlights: 0-5 specific moments (messages sent, decisions, tests passed, "
            "requests to other agents). Use the user's or assistant's words when important. "
            "facts: ONLY durable info about the human user (name, job, employer, age, "
            "stable preferences). Use keys like user_name, user_job_title, user_company. "
            "Do NOT save: file names edited, dates, agent name (Phaust), README text, "
            "tool/API settings, one-off tasks, or anything from the assistant's identity. "
            "Max 5 facts. Skip greetings and small talk."
        )
        user = f"Period: {period}\n\nChat log:\n{transcript[:12000]}"

        try:
            r = requests.post(
                f"{self.base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.2,
                },
                timeout=self.timeout,
            )
            r.raise_for_status()
            content = r.json()["choices"][0]["message"].get("content") or ""
            return self._parse_json(content)
        except (requests.RequestException, KeyError, json.JSONDecodeError) as e:
            fallback = transcript[:400].replace("\n", " ")
            return {
                "summary": f"[{period}] Conversation archived ({len(transcript)} chars). "
                f"Excerpt: {fallback}...",
                "facts": [],
                "_error": str(e),
            }

    _SKIP_FACT_PREFIXES = (
        "file_",
        "target_",
        "modification_",
        "interaction_",
        "llm_",
        "memory_",
        "system_",
        "assistant_",
        "agent_",
        "model_",
        "python_",
        "edit_",
        "current_",
        "iteration_",
        "next_",
    )
    _SKIP_FACT_KEYS = frozenset(
        {
            "identity",
            "ai_role_preference",
            "employer",
            "occupation",
        }
    )

    @classmethod
    def _should_save_fact(cls, key: str, value: str) -> bool:
        """Drop session noise the model often mis-labels as facts."""
        key = key.strip().lower()
        if key in cls._SKIP_FACT_KEYS:
            return False
        if any(key.startswith(p) for p in cls._SKIP_FACT_PREFIXES):
            return False
        if "phaust" in value.lower() and not key.startswith("user_"):
            return False
        if key.endswith("_file") or key.endswith("_target"):
            return False
        return True

    @staticmethod
    def _parse_json(content: str) -> dict[str, Any]:
        content = content.strip()
        fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
        if fence:
            content = fence.group(1).strip()
        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            content = content[start : end + 1]
        return json.loads(content)
