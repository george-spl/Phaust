"""Main chat turn loop — LLM rounds, tools, nudges, outcomes (Phaust-2)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

import requests

from phaust.orchestration import (
    NudgeBudget,
    TurnIntent,
    classify_turn,
    empty_files_from_results,
    format_command_outcome,
    format_memorize_outcome,
    format_memory_recall_outcome,
    format_write_outcome,
    format_write_policy_outcome,
    format_write_stopped,
    is_write_policy_error,
    memorize_text_from_message,
    paths_read_this_round,
    should_skip_synthesis,
    snapshots_from_results,
)
from phaust.orchestration.outcomes import format_profile_facts_reply
from phaust.orchestration.stress_log import extract_test_ids
from phaust.orchestration.constants import MEMORY_RECALL_TOOLS
from phaust.orchestration.policy import (
    build_tool_recovery_nudge,
    should_auto_return_recall_outcome,
    should_nudge_logging,
    should_nudge_logging_edit,
    should_nudge_memorize,
    should_nudge_recall,
    should_nudge_shell_staging,
    should_nudge_tool_recovery,
    should_nudge_write,
)
from phaust.orchestration.nudges import (
    LOGGING_EDIT_NUDGE,
    LOGGING_NUDGE,
    META_NARRATION_NUDGE,
    NATIVE_TOOL_NUDGE,
    SHELL_STAGING_NUDGE,
    memorize_nudge_message,
    recall_nudge_message,
    write_nudge_message,
)
from phaust.prompt_context import build_system_messages
from phaust.errors import format_user_error
from phaust.reply import clean_reply, is_meta_narration, is_planning_monologue, message_text
from phaust.tool_labels import label_for_tool
from phaust.shell import SHELL_TOOL_NAMES
from phaust.tool_executor import execute_tool_call, slim_tool_result
from phaust.tool_parse import parse_text_tool_calls, reply_simulates_tools
from phaust.tool_ui import print_tool_result
from phaust.turn_runner import (
    grounding_from_tool_results,
    llm_extra,
    raise_for_llm_error,
    sanitize_messages_for_api,
    synthesize_from_sources,
)
from phaust.workspace_write import WRITE_TOOL_NAMES

if TYPE_CHECKING:
    from phaust.agent import Agent

MEMORY_RECALL_TOOL_NAMES = MEMORY_RECALL_TOOLS


@dataclass
class TurnState:
    user_message: str
    intent: TurnIntent
    nudge_budget: NudgeBudget = field(default_factory=NudgeBudget)
    files_read_this_turn: set[str] = field(default_factory=set)
    write_applied: bool = False
    write_declined: bool = False
    command_applied: bool = False
    command_declined: bool = False
    memory_stored: bool = False
    write_proposals: int = 0
    memory_recall_this_turn: bool = False
    shell_allowlist_blocked: bool = False
    write_policy_blocked: bool = False
    read_paths: list[str] = field(default_factory=list)
    empty_write_paths: set[str] = field(default_factory=set)
    file_snapshots: dict[str, str] = field(default_factory=dict)
    last_write_path: str | None = None
    paths_touched: set[str] = field(default_factory=set)
    tool_rounds: int = 0

    @property
    def wants_edit(self) -> bool:
        return self.intent.wants_write

    @property
    def wants_create(self) -> bool:
        return self.intent.create

    @property
    def wants_memorize(self) -> bool:
        return self.intent.memorize or self.intent.store_fact


def _only_single_recall_tool(tool_calls: list[dict[str, Any]]) -> bool:
    names = [
        (call.get("function") or {}).get("name")
        for call in tool_calls
        if (call.get("function") or {}).get("name")
    ]
    return names == ["recall"]


def _last_user_message(agent: Agent) -> str:
    for msg in reversed(agent.context_memory.messages):  # type: ignore
        if msg.get("role") == "user":
            return str(msg.get("content") or "")
    return ""


def _synthesis_llm(agent: Agent) -> tuple[str, str, str, float, int]:
    s = agent.synthesis
    return (
        s.model or agent.model,
        (s.base_url or agent.base_url).rstrip("/"),
        s.api_key or agent.api_key,
        s.temperature,
        s.max_tokens,
    )


def _api_messages(agent: Agent, prefix: list[dict[str, str]]) -> list[dict[str, Any]]:
    return sanitize_messages_for_api(
        list(prefix) + list(agent.context_memory.messages_for_api())  # type: ignore
    )


def _chat_temperature(agent: Agent) -> float:
    if agent.chat_temperature is not None:
        return agent.chat_temperature
    return agent.temperature


def _request_llm(agent: Agent, prefix: list[dict[str, str]]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": agent.model,
        "messages": _api_messages(agent, prefix),
        "temperature": _chat_temperature(agent),
        "max_tokens": agent.max_tokens,
        "extra_body": llm_extra(),
    }
    schemas = agent.tools.get_schemas()
    if schemas:
        payload["tools"] = schemas

    r = requests.post(
        f"{agent.base_url}/chat/completions",
        headers={
            "Authorization": f"Bearer {agent.api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=300,
    )
    try:
        raise_for_llm_error(r)
    except requests.HTTPError as exc:
        if "No user query found" in str(exc):
            agent.context_memory.db.repair_message_history()  # type: ignore
            agent.context_memory.db.pop_last_message()  # type: ignore
            raise requests.HTTPError(
                f"{exc}\n"
                "  -> Repaired context and rolled back this message. "
                "Try again (do not press Enter on an empty prompt).",
                response=getattr(exc, "response", None),
            ) from exc
        agent.context_memory.db.pop_last_message()  # type: ignore
        raise
    return r.json()["choices"][0]["message"]


def _apply_session_memory_policy(agent: Agent, user_message: str) -> None:
    if agent.context_memory.user_requests_memory_again(user_message):  # type: ignore
        if not agent.context_memory.memory_writes_enabled():  # type: ignore
            agent.context_memory.set_memory_writes_disabled(False)  # type: ignore
            print("  ○ Memory writes re-enabled for this session (will archive on exit).")
    elif agent.context_memory.user_requests_no_memory(user_message):  # type: ignore
        agent.context_memory.set_memory_writes_disabled(True)  # type: ignore
        print(
            "  ○ Memory writes disabled this session "
            "(remember/memorize blocked; exit will not archive)."
        )


def _memorize_blocked_reply(agent: Agent) -> str:
    reply = (
        "Memory writes are disabled this session. "
        "Say 'enable remembering' if you want to memorize that."
    )
    agent.context_memory.append_message({"role": "assistant", "content": reply})  # type: ignore
    agent._persist()
    return reply


def _finish_turn(agent: Agent, reply: str) -> str:
    reply = clean_reply(reply)
    agent.context_memory.append_message({"role": "assistant", "content": reply})  # type: ignore
    agent._persist()
    return clean_reply(reply)


def _nudge_user(agent: Agent, content: str) -> None:
    agent.context_memory.append_message({"role": "user", "content": content})  # type: ignore
    agent._persist()


def _handle_no_tool_calls(agent: Agent, state: TurnState, msg: dict[str, Any]) -> str | None:
    if should_nudge_memorize(
        state.intent, memory_stored=state.memory_stored, budget=state.nudge_budget
    ):
        state.nudge_budget.memorize += 1
        print("  -> memorize pending — nudging model…")
        _nudge_user(
            agent,
            memorize_nudge_message(
                state.user_message,
                suggested_text=memorize_text_from_message(state.user_message),
            ),
        )
        return None

    if should_nudge_logging_edit(
        state.intent,
        read_paths=state.read_paths,
        write_applied=state.write_applied,
        budget=state.nudge_budget,
    ):
        state.nudge_budget.logging += 1
        print("  -> logging edit — nudging model…")
        _nudge_user(agent, LOGGING_EDIT_NUDGE)
        return None

    if should_nudge_write(
        state.intent,
        read_paths=state.read_paths,
        write_applied=state.write_applied,
        write_declined=state.write_declined,
        write_policy_blocked=state.write_policy_blocked,
        write_proposals=state.write_proposals,
        max_write_proposals=agent.max_write_proposals,
        budget=state.nudge_budget,
    ):
        state.nudge_budget.write += 1
        label = (
            "read_file first, then write…"
            if not state.read_paths
            else "write pending — nudging model…"
        )
        print(f"  -> {label}")
        _nudge_user(
            agent,
            write_nudge_message(state.read_paths, create_ok=state.wants_create),
        )
        return None

    reply = message_text(msg) or (
        "(no response from model — check LM Studio has a chat model loaded)"
    )

    if should_nudge_shell_staging(
        state.intent,
        command_applied=state.command_applied,
        shell_allowlist_blocked=state.shell_allowlist_blocked,
        budget=state.nudge_budget,
    ):
        state.nudge_budget.shell_staging += 1
        print("  -> shell pending — nudging model…")
        _nudge_user(agent, SHELL_STAGING_NUDGE)
        return None

    if should_nudge_logging(state.intent, reply, state.nudge_budget) or (
        state.intent.logging_task
        and is_planning_monologue(reply)
        and state.nudge_budget.logging < 2
    ):
        state.nudge_budget.logging += 1
        print("  -> logging append — nudging model…")
        _nudge_user(
            agent,
            LOGGING_EDIT_NUDGE if state.read_paths else LOGGING_NUDGE,
        )
        return None

    session_snapshot = None
    if agent.workspace is not None:
        from phaust.session_state import load_session_state

        session_snapshot = load_session_state(agent.workspace.root)

    if should_nudge_recall(
        state.intent,
        memory_recall_this_turn=state.memory_recall_this_turn,
        budget=state.nudge_budget,
        session_state=session_snapshot,
    ):
        state.nudge_budget.recall += 1
        print("  -> recall pending — nudging model…")
        _nudge_user(
            agent,
            recall_nudge_message(
                state.user_message,
                fact_recall_key=state.intent.fact_recall_key,
                session_state=session_snapshot,
            ),
        )
        return None

    if (
        is_meta_narration(reply)
        and state.nudge_budget.meta < 1
        and not state.memory_recall_this_turn
        and not state.intent.logging_task
    ):
        state.nudge_budget.meta += 1
        print("  -> meta narration — nudging model…")
        _nudge_user(agent, META_NARRATION_NUDGE)
        return None

    if reply_simulates_tools(reply) and state.nudge_budget.tool_recovery < 1:
        state.nudge_budget.tool_recovery += 1
        print("  -> simulated tools in chat — nudging native calls…")
        _nudge_user(agent, NATIVE_TOOL_NUDGE)
        return None

    agent._persist()
    return reply


def _run_tool_round(
    agent: Agent,
    state: TurnState,
    tool_calls: list[dict[str, Any]],
) -> str | None:
    round_results: list[dict[str, Any]] = []
    for call in tool_calls:
        fn = call.get("function", {})
        name = fn.get("name")
        if state.write_declined and name in WRITE_TOOL_NAMES:
            continue
        if state.command_declined and name in SHELL_TOOL_NAMES:
            continue
        if state.shell_allowlist_blocked and name in SHELL_TOOL_NAMES:
            continue
        if (
            state.wants_edit
            and not state.write_applied
            and name in WRITE_TOOL_NAMES
            and state.write_proposals >= agent.max_write_proposals
        ):
            continue
        print(f"  -> {label_for_tool(name)}…")
        result = execute_tool_call(agent, call, state.files_read_this_turn)
        round_results.append(result)
        if name == "read_file" and not result.get("error"):
            rel = str(result.get("path") or "")
            if rel:
                state.files_read_this_turn.add(rel)
                state.paths_touched.add(rel)
        if name in WRITE_TOOL_NAMES:
            state.last_write_path = str(result.get("path") or state.last_write_path or "")
            if is_write_policy_error(result):
                state.write_policy_blocked = True
            if result.get("error") is None and not result.get("skipped"):
                state.write_proposals += 1
            if result.get("applied"):
                state.write_applied = True
            if result.get("path"):
                state.paths_touched.add(str(result["path"]))
            if result.get("cancelled"):
                state.write_declined = True
        if name in SHELL_TOOL_NAMES:
            if result.get("executed"):
                state.command_applied = True
            if result.get("cancelled"):
                state.command_declined = True
            if result.get("error") == "Command not on allowlist":
                state.shell_allowlist_blocked = True
        if name in MEMORY_RECALL_TOOL_NAMES:
            state.memory_recall_this_turn = True
        if name == "memorize" and result.get("stored"):
            state.memory_stored = True
        if name == "remember" and result.get("saved"):
            state.memory_stored = True
        print_tool_result(name, result, quiet=agent.quiet_memory_tools)
        agent.context_memory.append_message(  # type: ignore
            {
                "role": "tool",
                "tool_call_id": call.get("id"),
                "content": json.dumps(slim_tool_result(name, result)),
            }
        )

    state.read_paths = paths_read_this_round(round_results) or state.read_paths
    state.empty_write_paths |= empty_files_from_results(round_results)
    state.file_snapshots.update(snapshots_from_results(round_results))

    if (
        state.shell_allowlist_blocked
        and not state.command_applied
        and not state.command_declined
    ):
        return _finish_turn(agent, format_command_outcome(round_results))

    if state.write_policy_blocked and not state.write_applied and not state.write_declined:
        return _finish_turn(agent, format_write_policy_outcome(round_results))

    if state.intent.profile_question and agent.long_term and _only_single_recall_tool(
        tool_calls
    ):
        facts = agent.long_term.db.list_facts()  # type: ignore[union-attr]
        if len(facts) > 1:
            profile_reply = format_profile_facts_reply(facts)
            if profile_reply:
                return _finish_turn(agent, profile_reply)

    recall_reply = format_memory_recall_outcome(round_results)
    if should_auto_return_recall_outcome(tool_calls, recall_reply, state.intent):
        return _finish_turn(agent, recall_reply or "")

    if state.write_applied:
        return _finish_turn(agent, format_write_outcome(round_results))

    if state.memory_stored:
        return _finish_turn(agent, format_memorize_outcome(round_results))

    if state.command_applied:
        return _finish_turn(agent, format_command_outcome(round_results))

    if state.write_declined:
        return _finish_turn(agent, format_write_outcome(round_results))

    if state.command_declined:
        return _finish_turn(agent, format_command_outcome(round_results))

    if (
        state.wants_edit
        and state.write_proposals >= agent.max_write_proposals
        and not state.write_applied
    ):
        return _finish_turn(
            agent,
            format_write_stopped(
                state.last_write_path,
                reason=(
                    f"max {agent.max_write_proposals} write previews this turn "
                    "(approve one or ask again)."
                ),
            ),
        )

    if should_nudge_tool_recovery(round_results, state.nudge_budget):
        state.nudge_budget.tool_recovery += 1
        recovery = build_tool_recovery_nudge(round_results)
        print("  -> tool error — recovery nudge…")
        _nudge_user(agent, recovery or "")
        return None

    sources = grounding_from_tool_results(round_results)
    if sources and not should_skip_synthesis(state.intent, tool_calls):
        print("  -> synthesizing answer from file contents…")
        synth_model, synth_url, synth_key, synth_temp, synth_max = _synthesis_llm(agent)
        answer = synthesize_from_sources(
            question=_last_user_message(agent),
            sources=sources,
            model=synth_model,
            base_url=synth_url,
            api_key=synth_key,
            temperature=synth_temp,
            max_tokens=synth_max,
        )
        return _finish_turn(agent, answer)

    agent._persist()
    return None


def _persist_session_pointer(agent: Agent, state: TurnState, reply: str) -> None:
    if agent.workspace is None:
        return
    from phaust.memory.topics import infer_topic_tags
    from phaust.session_state import update_session_state

    topics = infer_topic_tags(f"{state.user_message} {reply}")
    task_id = None
    task_title = None
    if agent.task_manager:
        task = agent.task_manager.get_active()
        if task is not None:
            task_id = task.id
            task_title = task.title
    last_ep: str | None = None
    episodes = agent.db.list_episodes()
    if episodes:
        last_ep = str(episodes[-1].get("id") or "") or None

    update_session_state(
        agent.workspace.root,
        user_message=state.user_message,
        assistant_reply=reply,
        topic=topics[0] if topics else None,
        topics=topics,
        files=sorted(state.paths_touched),
        task_id=task_id,
        task_title=task_title,
        last_episode_id=last_ep,
    )


def run_chat_turn(agent: Agent, user_message: str) -> str:
    """Run one user message through the tool loop; return the assistant reply."""
    try:
        return _run_chat_turn_inner(agent, user_message)
    except Exception as exc:
        try:
            agent.context_memory.db.pop_last_message()  # type: ignore
        except Exception:
            pass
        return format_user_error(exc)


def _run_chat_turn_inner(agent: Agent, user_message: str) -> str:
    _apply_session_memory_policy(agent, user_message)
    agent.context_memory.append_message({"role": "user", "content": user_message})  # type: ignore

    state = TurnState(
        user_message=user_message,
        intent=classify_turn(user_message),
    )

    if state.intent.logging_task:
        ids = extract_test_ids(user_message)
        if ids:
            agent.context_memory.set_session("_stress_log_expected_ids", ids)  # type: ignore

    if state.wants_memorize and not agent.context_memory.memory_writes_enabled():  # type: ignore
        reply = _memorize_blocked_reply(agent)
        _persist_session_pointer(agent, state, reply)
        return reply

    def _return(reply: str) -> str:
        reply = clean_reply(reply)
        _persist_session_pointer(agent, state, reply)
        return reply

    if (
        agent.conversational_first
        and state.intent.profile_question
        and agent.long_term
    ):
        facts = agent.long_term.db.list_facts()  # type: ignore[union-attr]
        if facts:
            profile_reply = format_profile_facts_reply(facts)
            if profile_reply:
                agent.context_memory.append_message(  # type: ignore
                    {"role": "assistant", "content": profile_reply}
                )
                agent._persist()
                return _return(profile_reply)

    while True:
        prefix = build_system_messages(
            agent,
            user_message,
            empty_write_paths=state.empty_write_paths,
            file_snapshots=state.file_snapshots,
        )
        msg = _request_llm(agent, prefix)
        tool_calls = list(msg.get("tool_calls") or [])
        if not tool_calls:
            parsed = parse_text_tool_calls(str(msg.get("content") or ""))
            if parsed:
                tool_calls = parsed
                print(f"  -> parsed {len(tool_calls)} tool call(s) from assistant text")

        agent.context_memory.append_message(  # type: ignore
            {
                "role": "assistant",
                "content": msg.get("content"),
                "tool_calls": tool_calls or None,
            }
        )

        if not tool_calls:
            reply = _handle_no_tool_calls(agent, state, msg)
            if reply is not None:
                return _return(reply)
            continue

        state.tool_rounds += 1
        if state.tool_rounds > agent.max_tool_rounds:
            agent._persist()
            return _return("Stopped: too many tool-call rounds.")

        done = _run_tool_round(agent, state, tool_calls)
        if done is not None:
            return _return(done)

    return _return("(no response — try again)")
