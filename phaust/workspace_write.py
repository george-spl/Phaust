"""Write/edit workspace files — preview first, apply only after user approval."""

from __future__ import annotations

import difflib
import re
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

if TYPE_CHECKING:
    from phaust.agent import Agent
    from phaust.workspace import Workspace

MAX_WRITE_BYTES = 512_000
MAX_DIFF_LINES = 120

WRITE_TOOL_NAMES = frozenset({"edit_file", "write_file"})

WRITE_BLOCKED_DIR_NAMES = {
    ".git",
    ".venv",
    "__pycache__",
    "node_modules",
    ".cursor",
    "agent-transcripts",
    "Memory",
}

ALLOWED_SUFFIXES = {
    ".py",
    ".md",
    ".json",
    ".txt",
    ".yaml",
    ".yml",
    ".toml",
    ".bat",
    ".gitignore",
    ".cursorignore",
}


def _check_writable_path(ws: Workspace, path: str) -> tuple[Path | None, dict[str, Any] | None]:
    try:
        target = ws.resolve(path)
    except PermissionError as e:
        return None, {"error": str(e)}

    if any(part in WRITE_BLOCKED_DIR_NAMES for part in target.parts):
        return None, {"error": f"Writes blocked under protected path: {path}"}

    suffix = target.suffix.lower()
    if target.name not in (".gitignore", ".cursorignore") and suffix not in ALLOWED_SUFFIXES:
        return None, {
            "error": f"Extension not allowed for writes: {suffix or '(none)'}. "
            f"Allowed: {', '.join(sorted(ALLOWED_SUFFIXES))}",
        }

    return target, None


def _format_diff(rel_path: str, before: str, after: str) -> str:
    diff = difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=f"{rel_path} (before)",
        tofile=f"{rel_path} (after)",
        lineterm="",
    )
    lines = list(diff)
    if len(lines) > MAX_DIFF_LINES:
        extra = len(lines) - MAX_DIFF_LINES
        lines = lines[:MAX_DIFF_LINES] + [f"... diff truncated ({extra} more lines) ..."]
    return "\n".join(lines) if lines else "(no line changes)\n"


def prepare_edit_file(
    ws: Workspace,
    path: str,
    old_string: str,
    new_string: str,
) -> dict[str, Any]:
    """Validate a search/replace edit and return a proposal (no disk write)."""
    target, err = _check_writable_path(ws, path)
    if err:
        return err

    if not target.is_file():
        return {"error": f"Not a file (edit requires existing file): {path}"}

    before = target.read_text(encoding="utf-8", errors="replace")
    count = before.count(old_string)
    if count == 0:
        lines = before.splitlines()
        tail = "\n".join(lines[-3:]) if lines else "(empty file)"
        return {
            "error": "old_string not found in file",
            "path": path,
            "hint": f"Last lines on disk:\n{tail}",
        }
    if count > 1:
        return {
            "error": f"old_string matches {count} times; must be unique",
            "path": path,
        }

    after = before.replace(old_string, new_string, 1)
    rel = target.relative_to(ws.root).as_posix()

    return {
        "action": "edit_file",
        "path": rel,
        "before": before,
        "after": after,
        "diff": _format_diff(rel, before, after),
        "summary": f"Replace 1 occurrence in {rel} ({len(old_string)} → {len(new_string)} chars)",
    }


def prepare_write_file(ws: Workspace, path: str, content: str) -> dict[str, Any]:
    """Validate a full write and return a proposal (no disk write)."""
    target, err = _check_writable_path(ws, path)
    if err:
        return err

    if len(content.encode("utf-8")) > MAX_WRITE_BYTES:
        return {"error": f"Content too large (max {MAX_WRITE_BYTES} bytes)"}

    rel = target.relative_to(ws.root).as_posix()
    exists = target.exists()

    if exists and target.is_dir():
        return {"error": f"Path is a directory: {path}"}

    before = ""
    if exists and target.is_file():
        before = target.read_text(encoding="utf-8", errors="replace")
        action = "overwrite"
        summary = f"Overwrite {rel} ({len(before)} → {len(content)} chars)"
    else:
        action = "create"
        summary = f"Create new file {rel} ({len(content)} chars)"

    if re.search(r"^\d+\|", content, re.MULTILINE):
        summary = (
            f"{summary} [warning: N| line prefixes — use plain lines unless user asked]"
        )

    return {
        "action": "write_file",
        "path": rel,
        "before": before,
        "after": content,
        "diff": _format_diff(rel, before, content),
        "summary": summary,
        "is_new_file": not exists,
    }


def apply_proposal(proposal: dict[str, Any], ws: Workspace) -> dict[str, Any]:
    """Write a previously approved proposal to disk."""
    if proposal.get("error"):
        return proposal

    path = proposal.get("path")
    if not path:
        return {"error": "invalid proposal: missing path"}

    target, err = _check_writable_path(ws, path)
    if err:
        return err

    after = proposal.get("after", "")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(after, encoding="utf-8", newline="\n")

    return {
        "applied": True,
        "path": path,
        "action": proposal.get("action"),
        "bytes": len(after.encode("utf-8")),
    }


def print_proposal(proposal: dict[str, Any]) -> None:
    print("\n" + "=" * 60)
    print("PROPOSED CHANGE (nothing written yet)")
    print("=" * 60)
    if proposal.get("error"):
        print(f"Error: {proposal['error']}")
        print("=" * 60 + "\n")
        return
    print(proposal.get("summary", ""))
    print("-" * 60)
    print(proposal.get("diff", ""))
    print("=" * 60)


def prompt_apply() -> bool:
    answer = input("Apply this change to disk? [y/N]: ").strip().lower()
    return answer in ("y", "yes")


def register_write_tools(agent: Agent, workspace: Workspace) -> None:
    """Tools that preview edits; agent applies only after user confirms."""

    @agent.tool
    def edit_file(path: str, old_string: str, new_string: str) -> dict:
        """Propose replacing exactly one occurrence of old_string in a file. User must approve before write."""
        return prepare_edit_file(workspace, path, old_string, new_string)

    @agent.tool
    def write_file(path: str, content: str) -> dict:
        """Propose creating or overwriting a file. Empty file = only new content user asked for; plain lines, no N| prefixes."""
        return prepare_write_file(workspace, path, content)
