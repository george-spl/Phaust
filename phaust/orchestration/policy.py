"""Turn-loop policy: synthesis, nudges, tool-round guards."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from phaust.orchestration.constants import MEMORY_LOOKUP_TOOLS, MEMORY_RECALL_TOOLS
from phaust.orchestration.intent import TurnIntent
from phaust.shell import SHELL_TOOL_NAMES
from phaust.workspace_write import WRITE_TOOL_NAMES


@dataclass
class NudgeBudget:
    memorize: int = 0
    write: int = 0
    logging: int = 0
    recall: int = 0
    shell_staging: int = 0
    meta: int = 0
    tool_recovery: int = 0


def round_includes_tools(tool_calls: list[dict[str, Any]], names: frozenset[str]) -> bool:
    for call in tool_calls:
        fn = call.get("function") or {}
        if fn.get("name") in names:
            return True
    return False


def should_skip_synthesis(
    intent: TurnIntent,
    tool_calls: list[dict[str, Any]],
) -> bool:
    if intent.skip_synthesis_default or intent.logging_task:
        return True
    return round_includes_tools(tool_calls, WRITE_TOOL_NAMES) or round_includes_tools(
        tool_calls, SHELL_TOOL_NAMES
    )


def _read_test_logging(read_paths: list[str]) -> bool:
    return any("test_logging" in (p or "").replace("\\", "/").lower() for p in read_paths)


def should_nudge_logging_edit(
    intent: TurnIntent,
    *,
    read_paths: list[str],
    write_applied: bool,
    budget: NudgeBudget,
) -> bool:
    return (
        intent.logging_task
        and _read_test_logging(read_paths)
        and not write_applied
        and budget.logging < 2
    )


def is_write_policy_error(result: dict[str, Any]) -> bool:
    err = str(result.get("error") or "")
    return (
        "Writes blocked under protected path" in err
        or "Extension not allowed for writes" in err
    )


def should_nudge_memorize(
    intent: TurnIntent,
    *,
    memory_stored: bool,
    budget: NudgeBudget,
) -> bool:
    return (
        (intent.memorize or intent.store_fact)
        and not memory_stored
        and budget.memorize < 1
    )


def should_nudge_write(
    intent: TurnIntent,
    *,
    read_paths: list[str],
    write_applied: bool,
    write_declined: bool,
    write_policy_blocked: bool,
    write_proposals: int,
    max_write_proposals: int,
    budget: NudgeBudget,
) -> bool:
    if intent.logging_task and _read_test_logging(read_paths):
        return False
    return (
        intent.wants_write
        and not write_applied
        and not write_declined
        and not write_policy_blocked
        and write_proposals < max_write_proposals
        and budget.write < 1
    )


def should_nudge_shell_staging(
    intent: TurnIntent,
    *,
    command_applied: bool,
    shell_allowlist_blocked: bool,
    budget: NudgeBudget,
) -> bool:
    return (
        intent.git_staging
        and not command_applied
        and not shell_allowlist_blocked
        and budget.shell_staging < 1
    )


def should_nudge_logging(
    intent: TurnIntent,
    reply: str,
    budget: NudgeBudget,
) -> bool:
    from phaust.orchestration.nudges import is_logging_hallucination, is_logging_refusal

    if not intent.logging_task or budget.logging >= 1:
        return False
    return is_logging_refusal(reply) or is_logging_hallucination(reply)


def should_nudge_recall(
    intent: TurnIntent,
    *,
    memory_recall_this_turn: bool,
    budget: NudgeBudget,
    session_state: dict[str, Any] | None = None,
) -> bool:
    from phaust.memory.last_session import is_generic_last_session_query
    from phaust.orchestration.intent import (
        is_feedback_not_memory,
        is_supplying_new_context,
    )

    if is_supplying_new_context(intent.message):
        return False
    if is_feedback_not_memory(intent.message):
        return False
    if intent.profile_question:
        return False
    if (
        is_generic_last_session_query(intent.message)
        and session_state
        and (
            session_state.get("last_topic")
            or session_state.get("last_episode_id")
            or session_state.get("last_user_preview")
        )
    ):
        return False
    return (
        (intent.fact_recall or intent.recall_past)
        and not intent.explicit_memory_tool
        and not memory_recall_this_turn
        and budget.recall < 1
        and not intent.logging_task
        and not intent.memorize
        and not intent.store_fact
    )


def should_auto_return_recall_outcome(
    tool_calls: list[dict[str, Any]],
    recall_reply: str | None,
    intent: TurnIntent,
) -> bool:
    """Only dump tool output for explicit lookups — conversational recall gets prose."""
    if not recall_reply or intent.wants_write:
        return False
    if intent.explicit_memory_tool:
        return True
    if intent.fact_recall and round_includes_tools(tool_calls, frozenset({"recall"})):
        return True
    return False


def is_recoverable_tool_error(result: dict[str, Any]) -> bool:
    if result.get("cancelled") or result.get("skipped"):
        return False
    if not result.get("error"):
        return False
    if result.get("hint"):
        return True
    err = str(result.get("error"))
    return "Call read_file" in err


def build_tool_recovery_nudge(round_results: list[dict[str, Any]]) -> str | None:
    errors = [r for r in round_results if is_recoverable_tool_error(r)]
    if not errors:
        return None
    lines = [
        "One or more tools failed. Follow the hint and retry the tool call.",
        "Do not give a long apology — fix the issue and act.",
    ]
    for result in errors:
        lines.append(f"- {result.get('error')}")
        hint = result.get("hint")
        if hint:
            lines.append(f"  Hint: {hint}")
    return "\n".join(lines)


def should_nudge_tool_recovery(
    round_results: list[dict[str, Any]],
    budget: NudgeBudget,
) -> bool:
    return budget.tool_recovery < 1 and build_tool_recovery_nudge(round_results) is not None
