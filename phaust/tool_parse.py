"""Parse tool invocations embedded in assistant text (Qwen / LM Studio XML format)."""

from __future__ import annotations

import ast
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

_PYTHON_FENCE_RE = re.compile(r"```(?:python)?\s*([\s\S]*?)```", re.IGNORECASE)
_FUNC_CALL_RE = re.compile(
    r"\b(remember|recall|memorize|read_file|write_file|create_file|edit_file|"
    r"delete_file|list_directory|list_files|grep|run_command|search_semantic|"
    r"recall_episode|list_episodes)\s*\(\s*([^)]*)\s*\)",
    re.IGNORECASE,
)

_ARG_KV_RE = re.compile(
    r"([a-zA-Z_][\w]*)\s*=\s*"
    r'(?:"([^"]*)"|\'([^\']*)\'|([^,\)]+))',
)

_PATH_KEYS = frozenset({"path", "filename", "file", "filepath"})
_COMMAND_KEYS = frozenset({"command", "cmd"})
_TEXT_KEYS = frozenset({"text", "content", "note", "message"})


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


def _normalize_tool_args(name: str, raw: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, val in raw.items():
        if val is None:
            continue
        k = str(key).strip().lower()
        if k in _PATH_KEYS:
            out["path"] = str(val)
        elif k in _COMMAND_KEYS:
            out["command"] = str(val)
        elif k in _TEXT_KEYS:
            out["text"] = str(val)
        else:
            out[k] = val
    if name in ("read_file", "write_file", "create_file", "edit_file", "delete_file"):
        if "path" not in out and "filename" in raw:
            out["path"] = str(raw["filename"])
    return out


def _parse_call_args(argstr: str) -> dict[str, Any]:
    argstr = argstr.strip()
    if not argstr:
        return {}
    if argstr.startswith("{"):
        try:
            obj = json.loads(argstr)
            return obj if isinstance(obj, dict) else {}
        except json.JSONDecodeError:
            pass
    raw: dict[str, Any] = {}
    for match in _ARG_KV_RE.finditer(argstr):
        key = match.group(1)
        val = match.group(2) or match.group(3) or (match.group(4) or "").strip()
        raw[key] = val
    if raw:
        return raw
    try:
        parsed = ast.literal_eval(f"dict({argstr})")
        if isinstance(parsed, dict):
            return parsed
    except (SyntaxError, ValueError):
        pass
    return {}


def _calls_from_python_text(text: str) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    chunks = _PYTHON_FENCE_RE.findall(text)
    if not chunks and _FUNC_CALL_RE.search(text):
        chunks = [text]
    for chunk in chunks:
        for match in _FUNC_CALL_RE.finditer(chunk):
            name = match.group(1).strip()
            raw_args = _parse_call_args(match.group(2))
            args = _normalize_tool_args(name, raw_args)
            calls.append(
                {
                    "id": f"call_{uuid.uuid4().hex[:12]}",
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args)},
                }
            )
    return calls


def parse_text_tool_calls(text: str) -> list[dict[str, Any]]:
    """Turn XML, JSON, or ```python``` tool-like calls into OpenAI-style tool_calls."""
    if not text:
        return []

    calls: list[dict[str, Any]] = []

    if "<" in text:
        blocks = _TOOL_CALL_RE.findall(text)
        if not blocks and re.search(r"<function=", text, re.IGNORECASE):
            blocks = [text]
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

    for call in _calls_from_python_text(text):
        if call not in calls:
            calls.append(call)

    return calls


def reply_simulates_tools(text: str) -> bool:
    """True when the model fenced Python or fake errors instead of calling tools."""
    if not text:
        return False
    lower = text.lower()
    if "simulated" in lower and ("error" in lower or "run_command" in lower):
        return True
    if "```python" not in lower:
        return False
    return bool(_FUNC_CALL_RE.search(text))
