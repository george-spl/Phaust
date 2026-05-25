"""Assemble system prompt blocks for one chat turn."""

from __future__ import annotations

from typing import TYPE_CHECKING

from phaust.orchestration import build_turn_directives, classify_turn
from phaust.tasks import build_task_directive
from phaust.tasks.models import TaskStatus

if TYPE_CHECKING:
    from phaust.agent import Agent


def session_has_prior_assistant_reply(agent: Agent) -> bool:
    if not agent.context_memory:
        return False
    for msg in agent.context_memory.messages:  # type: ignore
        if msg.get("role") == "assistant":
            return True
    return False


def build_system_messages(
    agent: Agent,
    user_message: str,
    *,
    empty_write_paths: set[str] | None = None,
    file_snapshots: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    intent = classify_turn(user_message)
    blocks = [agent.system_prompt]

    context_block = agent.context_memory.build_prompt_block()  # type: ignore
    if context_block:
        blocks.append(context_block)

    long_term_block = agent.long_term.summary_for_prompt()  # type: ignore
    if long_term_block:
        blocks.append(long_term_block)

    if intent.memory_question:
        recall_block = agent.semantic.build_recall_block(  # type: ignore
            user_message, top_k=max(agent.semantic_top_k, 8)
        )
        if recall_block:
            blocks.append(recall_block)
    elif not intent.file_change:
        semantic_block = agent.semantic.build_prompt_block(  # type: ignore
            user_message, top_k=agent.semantic_top_k
        )
        if semantic_block:
            blocks.append(semantic_block)

    blocks.extend(
        build_turn_directives(
            intent,
            session_has_prior_reply=session_has_prior_assistant_reply(agent),
            memory_writes_enabled=agent.context_memory.memory_writes_enabled(),  # type: ignore
            empty_write_paths=empty_write_paths,
            file_snapshots=file_snapshots,
        )
    )

    if agent.task_manager:
        task = agent.task_manager.get_active()
        if task is not None and task.status == TaskStatus.ACTIVE:
            blocks.append(build_task_directive(task))

    return [{"role": "system", "content": "\n\n".join(blocks)}]
