"""Turn-loop policy: synthesis, nudges, tool-round guards."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from phaust.orchestration.constants import MEMORY_RECALL_TOOLS
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
    if intent.skip_synthesis_default:
        return True
    return round_includes_tools(tool_calls, WRITE_TOOL_NAMES) or round_includes_tools(
        tool_calls, SHELL_TOOL_NAMES
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
    return intent.memorize and not memory_stored and budget.memorize < 1


def should_nudge_write(
    intent: TurnIntent,
    *,
    write_applied: bool,
    write_declined: bool,
    write_policy_blocked: bool,
    write_proposals: int,
    max_write_proposals: int,
    budget: NudgeBudget,
) -> bool:
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
    from phaust.orchestration.nudges import is_logging_refusal

    return intent.logging_task and budget.logging < 1 and is_logging_refusal(reply)


def should_nudge_recall(
    intent: TurnIntent,
    *,
    memory_recall_this_turn: bool,
    budget: NudgeBudget,
) -> bool:
    return (
        (intent.fact_recall or intent.recall_past)
        and not intent.explicit_memory_tool
        and not memory_recall_this_turn
        and budget.recall < 1
        and not intent.logging_task
    )


def should_return_recall_outcome(
    tool_calls: list[dict[str, Any]],
    recall_reply: str | None,
    intent: TurnIntent,
) -> bool:
    return bool(
        recall_reply
        and not intent.wants_write
        and round_includes_tools(tool_calls, MEMORY_RECALL_TOOLS)
    )
