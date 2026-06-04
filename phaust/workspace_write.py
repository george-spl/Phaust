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

WRITE_TOOL_NAMES = frozenset(
    {"create_file", "edit_file", "write_file", "delete_file", "append_to_file"}
)

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


def _strip_pasted_file_body(extra: str, before: str) -> str:
    """Drop a full copy of the file the model pasted into append content."""
    text = str(extra).lstrip("\n")
    if not before.strip():
        return text
    b = before.rstrip("\n")
    if text.startswith(b):
        return text[len(b) :].lstrip("\n")
    if text.startswith(b[: min(len(b), 400)]):
        return text[min(len(b), 400) :].lstrip("\n")
    if b in text:
        parts = text.split(b)
        tail = parts[-1].strip() if parts else text
        if tail:
            return tail
    return text


def prepare_append_to_file(ws: Workspace, path: str, content: str) -> dict[str, Any]:
    """Append new text after existing file contents (read_file required first)."""
    target, err = _check_writable_path(ws, path)
    if err:
        return err
    if not target.is_file():  # type: ignore
        return {
            "error": f"Not a file: {path}",
            "hint": "Use create_file for new paths.",
        }

    before = target.read_text(encoding="utf-8", errors="replace")  # type: ignore
    text = _strip_pasted_file_body(content, before)
    if not text.strip():
        return {
            "error": "Append content is empty after removing duplicated file body",
            "path": path,
            "hint": "Pass only NEW lines to append, not the full file from read_file.",
        }
    sep = "\n" if before and not before.endswith("\n") else ""
    return prepare_write_file(ws, path, before + sep + text)


def normalize_edit_file_args(ws: Workspace, args: dict[str, Any]) -> dict[str, Any] | None:
    """If model used edit_file append aliases, return None to signal append_to_file instead."""
    if args.get("old_string") is not None and args.get("new_string") is not None:
        return args
    extra = args.get("content_to_append") or args.get("append")
    if extra is None and args.get("content") is not None and "old_string" not in args:
        extra = args.get("content")
    if extra is None:
        return args
    return None


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

    if not target.is_file(): # type: ignore
        return {"error": f"Not a file (edit requires existing file): {path}"}

    before = target.read_text(encoding="utf-8", errors="replace") # type: ignore
    if not before.strip():
        return {
            "error": "File is empty — use write_file, not edit_file",
            "path": path,
            "hint": "read_file shows 0 lines. write_file new content from scratch.",
        }
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
    rel = target.relative_to(ws.root).as_posix() # type: ignore

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

    rel = target.relative_to(ws.root).as_posix() # type: ignore
    exists = target.exists() # type: ignore

    if exists and target.is_dir(): # type: ignore
        return {"error": f"Path is a directory: {path}"}

    before = ""
    if exists and target.is_file(): # type: ignore
        before = target.read_text(encoding="utf-8", errors="replace") # type: ignore
        summary = f"Overwrite {rel} ({len(before)} → {len(content)} chars)"
    else:
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


def prepare_create_file(ws: Workspace, path: str, content: str) -> dict[str, Any]:
    """Validate creating a new file only (fails if path already exists)."""
    target, err = _check_writable_path(ws, path)
    if err:
        return err

    if target.exists(): # type: ignore
        if target.is_file(): # type: ignore
            return {
                "error": f"File already exists: {path}",
                "path": path,
                "hint": "Use read_file then edit_file or write_file to change it.",
            }
        return {"error": f"Path already exists as a directory: {path}"}

    proposal = prepare_write_file(ws, path, content)
    if proposal.get("error"):
        return proposal
    proposal["action"] = "create_file"
    return proposal


def prepare_delete_file(ws: Workspace, path: str) -> dict[str, Any]:
    """Validate file deletion and return a proposal (no disk change)."""
    target, err = _check_writable_path(ws, path)
    if err:
        return err

    if not target.exists(): # type: ignore
        return {"error": f"File not found: {path}"}
    if target.is_dir(): # type: ignore
        return {"error": f"Path is a directory: {path}"}
    if not target.is_file(): # type: ignore
        return {"error": f"Not a file: {path}"}

    before = target.read_text(encoding="utf-8", errors="replace") # type: ignore
    rel = target.relative_to(ws.root).as_posix() # type: ignore
    lines = before.splitlines()
    preview = "\n".join(f"- {line}" for line in lines[:15])
    if len(lines) > 15:
        preview += f"\n... ({len(lines) - 15} more lines) ..."
    diff = preview if preview else "(empty file)"
    diff += "\n\n>>> FILE WILL BE DELETED FROM DISK <<<"

    return {
        "action": "delete_file",
        "path": rel,
        "before": before,
        "after": "",
        "delete": True,
        "diff": diff,
        "summary": f"Delete file {rel} ({len(before)} chars)",
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

    if proposal.get("delete"):
        target.unlink() # type: ignore
        return {
            "applied": True,
            "deleted": True,
            "path": path,
            "action": "delete_file",
        }

    after = proposal.get("after", "")
    target.parent.mkdir(parents=True, exist_ok=True) # type: ignore
    target.write_text(after, encoding="utf-8", newline="\n") # type: ignore

    result: dict[str, Any] = {
        "applied": True,
        "path": path,
        "action": proposal.get("action"),
        "bytes": len(after.encode("utf-8")),
    }
    if proposal.get("action") == "create_file" or proposal.get("is_new_file"):
        result["created"] = True
    return result


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
        """Propose replacing exactly one occurrence of old_string in a file."""
        return prepare_edit_file(workspace, path, old_string, new_string)

    @agent.tool
    def append_to_file(path: str, content: str) -> dict:
        """Append new text to an existing file after read_file. Pass NEW content only."""
        return prepare_append_to_file(workspace, path, content)

    @agent.tool
    def create_file(path: str, content: str) -> dict:
        """Create a new file that must not exist yet. No read_file needed. User must approve."""
        return prepare_create_file(workspace, path, content)

    @agent.tool
    def write_file(path: str, content: str) -> dict:
        """Propose creating or overwriting a file. Empty content clears the file. User must approve."""
        return prepare_write_file(workspace, path, content)

    @agent.tool
    def delete_file(path: str) -> dict:
        """Propose deleting a file from disk. User must approve."""
        return prepare_delete_file(workspace, path)
