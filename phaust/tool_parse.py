"""Parse tool invocations embedded in assistant text (Qwen / LM Studio XML format)."""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

_TOOL_CALL_RE = re.compile(
    r"<tool_call>\s*([\s\S]*?)\s*</tool_call>",
    re.IGNORECASE,
)
_FUNCTION_RE = re.compile(r"<function=([^>\s]+)>", re.IGNORECASE)
_PARAMETER_RE = re.compile(
    r"<parameter=([^>]+)>\s*([\s\S]*?)\s*</parameter>",
    re.IGNORECASE,
)


def _call_from_xml_block(block: str) -> dict[str, Any] | None:
    fn = _FUNCTION_RE.search(block)
    if not fn:
        return None
    name = fn.group(1).strip()
    args: dict[str, str] = {}
    for match in _PARAMETER_RE.finditer(block):
        args[match.group(1).strip()] = match.group(2).strip()
    return {
        "id": f"call_{uuid.uuid4().hex[:12]}",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


def _call_from_json_obj(obj: dict[str, Any]) -> dict[str, Any] | None:
    name = obj.get("name") or obj.get("function")
    if not name:
        return None
    args = obj.get("arguments") or obj.get("parameters") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}
    if not isinstance(args, dict):
        return None
    return {
        "id": f"call_{uuid.uuid4().hex[:12]}",
        "type": "function",
        "function": {"name": str(name), "arguments": json.dumps(args)},
    }


def parse_text_tool_calls(text: str) -> list[dict[str, Any]]:
    """Turn <tool_call> XML (or JSON blobs) in content into OpenAI-style tool_calls."""
    if not text or "<" not in text:
        return []

    blocks = _TOOL_CALL_RE.findall(text)
    if not blocks and re.search(r"<function=", text, re.IGNORECASE):
        blocks = [text]

    calls: list[dict[str, Any]] = []
    for block in blocks:
        call = _call_from_xml_block(block)
        if call:
            calls.append(call)
            continue
        for match in re.finditer(r"\{[\s\S]*\}", block):
            try:
                obj = json.loads(match.group())
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                call = _call_from_json_obj(obj)
                if call:
                    calls.append(call)
                    break

    return calls
