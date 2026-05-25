"""Tool execution with write/shell approval gates (Phaust-2)."""

from __future__ import annotations

import json
from typing import Any, TYPE_CHECKING

from phaust.shell import (
    SHELL_TOOL_NAMES,
    execute_command,
    print_command_proposal,
    prompt_run,
)
from phaust.workspace_write import (
    WRITE_TOOL_NAMES,
    apply_proposal,
    print_proposal,
    prompt_apply,
)

if TYPE_CHECKING:
    from phaust.agent import Agent


def normalize_rel_path(agent: Agent, path: str) -> str:
    if not path.strip() or agent.workspace is None:
        return path.strip()
    try:
        return agent.workspace.resolve(path).relative_to(agent.workspace.root).as_posix()
    except (PermissionError, ValueError):
        return path.strip().replace("\\", "/").lstrip("/")


def path_is_existing_file(agent: Agent, rel_path: str) -> bool:
    if not agent.workspace or not rel_path:
        return False
    try:
        return agent.workspace.resolve(rel_path).is_file()
    except PermissionError:
        return False


def write_requires_read_first(
    agent: Agent, tool_name: str | None, rel_path: str, files_read_this_turn: set[str]
) -> bool:
    if not rel_path or rel_path in files_read_this_turn:
        return False
    if tool_name == "create_file":
        return False
    if tool_name == "write_file" and not path_is_existing_file(agent, rel_path):
        return False
    return True


def slim_tool_result(name: str | None, result: dict[str, Any]) -> dict[str, Any]:
    if name in WRITE_TOOL_NAMES:
        return {
            k: v
            for k, v in result.items()
            if k not in ("before", "after", "diff")
        }
    if name in SHELL_TOOL_NAMES:
        return {
            k: v
            for k, v in result.items()
            if k not in ("args", "cwd_abs", "matched_allow")
        }
    return result


def execute_tool_call(
    agent: Agent, tool_call: dict[str, Any], files_read_this_turn: set[str]
) -> dict[str, Any]:
    fn = tool_call.get("function", {})
    name = fn.get("name")

    if name in WRITE_TOOL_NAMES:
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {}
        rel = normalize_rel_path(agent, str(args.get("path", "")))
        if write_requires_read_first(agent, name, rel, files_read_this_turn):
            return {
                "error": "Call read_file on this path before edit_file/delete_file",
                "path": rel,
                "hint": (
                    "For a NEW file use create_file (no read needed). "
                    "Prior chat about file contents may be stale."
                ),
            }

    result = agent.tools.execute(tool_call)

    if name in SHELL_TOOL_NAMES:
        if result.get("error"):
            print_command_proposal(result)
            return result

        print_command_proposal(result)

        if agent.shell_config.require_approval:
            if not prompt_run():
                return {
                    "cancelled": True,
                    "command": result.get("command"),
                    "cwd": result.get("cwd"),
                    "message": "User declined. Command was not run.",
                }

        return execute_command(result, agent.shell_config)

    if name not in WRITE_TOOL_NAMES:
        return result

    if result.get("error"):
        print_proposal(result)
        return result

    print_proposal(result)

    if agent.require_write_approval:
        if not prompt_apply():
            return {
                "applied": False,
                "cancelled": True,
                "path": result.get("path"),
                "message": "User declined. No changes were written to disk.",
            }

    if agent.workspace is None:
        return {"error": "Workspace not configured on agent"}

    return apply_proposal(result, agent.workspace)
