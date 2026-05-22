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
        if summary:
            semantic.store(
                f"[{period}] {summary}",
                source=source,
                tags=["episode", period[:7]],
            )

        facts = extracted.get("facts") or []
        saved = 0
        for item in facts:
            key = (item.get("key") or "").strip()
            value = (item.get("value") or "").strip()
            if key and value:
                long_term.remember(key, value)
                saved += 1

        return {
            "compacted": len(messages),
            "episode_saved": bool(summary),
            "facts_saved": saved,
        }

    def _extract(self, transcript: str, period: str) -> dict[str, Any]:
        system = (
            "You compress chat logs into durable memory. "
            "Reply with ONLY valid JSON, no markdown:\n"
            '{"summary": "2-4 sentences with date and main topics/decisions", '
            '"facts": [{"key": "snake_case_key", "value": "short fact"}]}\n'
            "facts: only stable preferences, identity, decisions (max 8). "
            "Skip greetings and small talk."
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
