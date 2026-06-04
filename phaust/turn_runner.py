"""Turn-loop helpers: synthesis pass and API message sanitization."""

from __future__ import annotations

import re
from typing import Any

import requests

from phaust.reply import message_text

MAX_SYNTHESIS_CHARS = 12_000


def llm_extra() -> dict[str, Any]:
    return {"chat_template_kwargs": {"enable_thinking": False}}


def grounding_from_tool_results(results: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for result in results:
        if result.get("error"):
            continue
        if result.get("content") and result.get("path"):
            parts.append(
                f"### FILE: {result['path']} ({result.get('total_lines', '?')} lines)\n"
                f"{result['content']}"
            )
        elif result.get("matches"):
            lines = [
                f"{m['file']}:{m['line']}: {m['text']}"
                for m in result["matches"][:40]
            ]
            parts.append(
                f"### GREP: {result.get('pattern', '')}\n" + "\n".join(lines)
            )
    return "\n\n".join(parts)


def truncate_sources(sources: str, max_chars: int = MAX_SYNTHESIS_CHARS) -> str:
    if len(sources) <= max_chars:
        return sources
    return sources[:max_chars] + "\n… [truncated for context limit]"


def fallback_summary(sources: str) -> str:
    imports = re.findall(r"^from .+|^import .+", sources, re.MULTILINE)[:12]
    symbols = re.findall(r"^(?:class|def) \w+", sources, re.MULTILINE)[:25]
    lines = ["The model returned an empty reply. From the file read:"]
    if symbols:
        lines.append("Symbols: " + ", ".join(symbols))
    if imports:
        lines.append("Imports: " + "; ".join(imports))
    return "\n".join(lines)


def synthesize_from_sources(
    *,
    question: str,
    sources: str,
    model: str,
    base_url: str,
    api_key: str,
    temperature: float = 0.15,
    max_tokens: int = 2048,
) -> str:
    """Second pass: answer only from file text (no tools — reduces hallucination)."""
    sources = truncate_sources(sources)
    messages = [
        {
            "role": "system",
            "content": (
                "Answer the user's question about the code in 2–4 short paragraphs. "
                "If SOURCE shows a line count in the FILE header, mention total file size "
                "when relevant. Use only names that appear in SOURCE. "
                "Do not show planning, analysis, or numbered steps."
            ),
        },
        {
            "role": "user",
            "content": f"Question: {question}\n\n--- SOURCE ---\n{sources}\n--- END SOURCE ---",
        },
        {"role": "assistant", "content": " \n"},
    ]
    r = requests.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "extra_body": llm_extra(),
        },
        timeout=300,
    )
    raise_for_llm_error(r)
    answer = message_text(r.json()["choices"][0]["message"])
    if answer:
        return answer
    print("     ⚠ synthesis returned empty — using fallback summary")
    return fallback_summary(sources)


def to_api_message(msg: dict[str, Any]) -> dict[str, Any] | None:
    role = msg.get("role")
    if role not in ("system", "user", "assistant", "tool"):
        return None
    out: dict[str, Any] = {"role": role}
    content = msg.get("content")
    if content is not None and str(content).strip():
        out["content"] = str(content)
    tool_calls = msg.get("tool_calls")
    if tool_calls:
        out["tool_calls"] = tool_calls
    if msg.get("tool_call_id"):
        out["tool_call_id"] = msg["tool_call_id"]
    if role == "user":
        if not str(out.get("content") or "").strip():
            return None
    elif role == "assistant":
        if tool_calls and "content" not in out:
            out["content"] = ""
        elif "content" not in out and not tool_calls:
            return None
    elif role == "tool":
        if "content" not in out:
            out["content"] = ""
    elif role == "system" and "content" not in out:
        return None
    return out


def merge_consecutive_users(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for msg in messages:
        if (
            msg.get("role") == "user"
            and merged
            and merged[-1].get("role") == "user"
        ):
            prev = str(merged[-1].get("content") or "")
            cur = str(msg.get("content") or "")
            merged[-1]["content"] = f"{prev}\n\n{cur}".strip()
        else:
            merged.append(msg)
    return merged


def sanitize_messages_for_api(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """LM Studio/Qwen reject prompts when user turns are missing or malformed."""
    cleaned: list[dict[str, Any]] = []
    for msg in messages:
        api_msg = to_api_message(msg)
        if api_msg is None:
            continue
        if api_msg.get("role") == "user" and not str(api_msg.get("content") or "").strip():
            continue
        cleaned.append(api_msg)
    cleaned = merge_consecutive_users(cleaned)
    if not any(m.get("role") == "user" for m in cleaned):
        raise ValueError(
            "No user message in prompt — context may be corrupt. "
            "Restart Phaust or clear Memory/phaust.db messages."
        )
    return cleaned


def raise_for_llm_error(response: requests.Response) -> None:
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        detail = response.text.strip()
        if detail:
            raise requests.HTTPError(
                f"{exc} — {detail[:800]}",
                response=response,
            ) from exc
        raise
