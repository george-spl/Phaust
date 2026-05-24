from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import requests

from phaust.config import SynthesisConfig
from phaust.memory import (
    Compactor,
    ContextMemory,
    LongTermMemory,
    MemoryStore,
    SemanticMemory,
)
from phaust.tool_parse import parse_text_tool_calls
from phaust.tools import Tools
from phaust.workspace import Workspace
from phaust.shell import (
    SHELL_TOOL_NAMES,
    ShellConfig,
    execute_command,
    print_command_proposal,
    prompt_run,
)
from phaust.orchestration import (
    NudgeBudget,
    build_turn_directives,
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
from phaust.orchestration.constants import MEMORY_RECALL_TOOLS, MEMORY_STORE_TOOLS
from phaust.orchestration.policy import (
    build_tool_recovery_nudge,
    round_includes_tools,
    should_nudge_logging,
    should_nudge_memorize,
    should_nudge_recall,
    should_nudge_shell_staging,
    should_nudge_tool_recovery,
    should_nudge_write,
)
from phaust.orchestration.nudges import (
    LOGGING_NUDGE,
    META_NARRATION_NUDGE,
    SHELL_STAGING_NUDGE,
    memorize_nudge_message,
    recall_nudge_message,
    write_nudge_message,
)
from phaust.workspace_write import (
    WRITE_TOOL_NAMES,
    apply_proposal,
    print_proposal,
    prompt_apply,
)

from phaust.tasks import TaskManager, build_task_directive, handle_task_command
from phaust.tasks.models import TaskStatus
from phaust.reply import is_meta_narration, message_text
from phaust.tool_ui import print_tool_result
from phaust.turn_runner import (
    grounding_from_tool_results,
    llm_extra,
    raise_for_llm_error,
    sanitize_messages_for_api,
    synthesize_from_sources,
)

MEMORY_RECALL_TOOL_NAMES = MEMORY_RECALL_TOOLS
MEMORY_STORE_TOOL_NAMES = MEMORY_STORE_TOOLS

@dataclass
class Agent:
    system_prompt: str = ""
    model: str = "qwen/qwen3.5-9b"
    base_url: str = "http://127.0.0.1:1234/v1"
    api_key: str = field(default="NO_API_KEY", repr=False)
    temperature: float = 0.3
    max_tokens: int = 8192
    max_tool_rounds: int = 12
    max_write_proposals: int = 2
    semantic_top_k: int = 5
    max_messages: int = 50
    compact_batch: int = 10
    max_episodes: int = 500

    tools: Tools = field(default_factory=Tools)
    db: MemoryStore = field(default_factory=MemoryStore)
    context_memory: ContextMemory | None = None
    long_term: LongTermMemory | None = None
    semantic: SemanticMemory | None = None
    compactor: Compactor | None = None
    workspace: Workspace | None = None
    require_write_approval: bool = True
    shell_config: ShellConfig = field(default_factory=ShellConfig)
    config_path: Path | None = None
    config_name: str = "Phaust-2"
    agents_md_path: Path | None = None
    task_manager: TaskManager | None = None
    synthesis: SynthesisConfig = field(default_factory=SynthesisConfig)
    _files_read_this_turn: set[str] = field(default_factory=set, repr=False)

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")

        if self.context_memory is None:
            self.context_memory = ContextMemory(
                db=self.db,
                max_messages=self.max_messages,
                compact_batch=self.compact_batch,
            )
        if self.long_term is None:
            self.long_term = LongTermMemory(db=self.db)
        if self.semantic is None:
            self.semantic = SemanticMemory(
                db=self.db,
                max_episodes=self.max_episodes,
            )
        self.semantic.base_url = self.base_url
        self.semantic.api_key = self.api_key
        self.semantic.model = self.model

        if self.compactor is None:
            self.compactor = Compactor(
                base_url=self.base_url,
                api_key=self.api_key,
                model=self.model,
            )

        self._load_all()

    def _load_all(self) -> None:
        self.context_memory.load() # type: ignore

    def begin_session(self) -> None:
        self.context_memory.begin_session() # type: ignore

    def finalize_session(self) -> dict[str, Any] | None:
        if self.compactor is None:
            return None
        return self.context_memory.finalize_session( # type: ignore
            self.long_term, self.semantic, self.compactor # type: ignore
        )

    def _persist(self) -> None:
        result = self.context_memory.maybe_compact( # type: ignore
            self.long_term, self.semantic, self.compactor # type: ignore
        )
        if result and result.get("episode_saved"):
            eid = result.get("episode_id")
            id_note = f" id={eid}" if eid else ""
            print(
                f"Memory: compacted {result.get('compacted', 0)} messages "
                f"→ episode{id_note} + {result.get('facts_saved', 0)} facts"
            )

    def tool(self, func: Callable[..., Any]) -> Callable[..., Any]:
        return self.tools.register(func)

    def context(self, func: Callable[[], str]) -> Callable[[], str]:
        return self.context_memory.register_provider(func.__name__, func) # type: ignore

    def _build_system_messages(
        self,
        user_message: str,
        *,
        empty_write_paths: set[str] | None = None,
        file_snapshots: dict[str, str] | None = None,
    ) -> list[dict[str, str]]:
        intent = classify_turn(user_message)
        blocks = [self.system_prompt]

        context_block = self.context_memory.build_prompt_block() # type: ignore
        if context_block:
            blocks.append(context_block)

        long_term_block = self.long_term.summary_for_prompt() # type: ignore
        if long_term_block:
            blocks.append(long_term_block)

        if intent.memory_question:
            recall_block = self.semantic.build_recall_block( # type: ignore
                user_message, top_k=max(self.semantic_top_k, 8)
            )
            if recall_block:
                blocks.append(recall_block)
        elif not intent.file_change:
            semantic_block = self.semantic.build_prompt_block( # type: ignore
                user_message, top_k=self.semantic_top_k
            )
            if semantic_block:
                blocks.append(semantic_block)

        blocks.extend(
            build_turn_directives(
                intent,
                session_has_prior_reply=self._session_has_prior_assistant_reply(),
                memory_writes_enabled=self.context_memory.memory_writes_enabled(), # type: ignore
                empty_write_paths=empty_write_paths,
                file_snapshots=file_snapshots,
            )
        )

        if self.task_manager:
            task = self.task_manager.get_active()
            if task is not None and task.status == TaskStatus.ACTIVE:
                blocks.append(build_task_directive(task))

        return [{"role": "system", "content": "\n\n".join(blocks)}]

    def _session_has_prior_assistant_reply(self) -> bool:
        if not self.context_memory:
            return False
        for msg in self.context_memory.messages: # type: ignore
            if msg.get("role") == "assistant":
                return True
        return False

    def _last_user_message(self) -> str:
        for msg in reversed(self.context_memory.messages): # type: ignore
            if msg.get("role") == "user":
                return str(msg.get("content") or "")
        return ""

    def _synthesis_llm(self) -> tuple[str, str, str, float, int]:
        s = self.synthesis
        return (
            s.model or self.model,
            (s.base_url or self.base_url).rstrip("/"),
            s.api_key or self.api_key,
            s.temperature,
            s.max_tokens,
        )

    def _api_messages(self, prefix: list[dict[str, str]]) -> list[dict[str, Any]]:
        return sanitize_messages_for_api(
            list(prefix) + list(self.context_memory.messages)  # type: ignore
        )

    def _normalize_rel_path(self, path: str) -> str:
        if not path.strip() or self.workspace is None:
            return path.strip()
        try:
            return self.workspace.resolve(path).relative_to(self.workspace.root).as_posix()
        except (PermissionError, ValueError):
            return path.strip().replace("\\", "/").lstrip("/")

    def _path_is_existing_file(self, rel_path: str) -> bool:
        if not self.workspace or not rel_path:
            return False
        try:
            return self.workspace.resolve(rel_path).is_file()
        except PermissionError:
            return False

    def _write_requires_read_first(self, tool_name: str | None, rel_path: str) -> bool:
        """New files can be created without read_file; edits/deletes need a fresh read."""
        if not rel_path or rel_path in self._files_read_this_turn:
            return False
        if tool_name == "create_file":
            return False
        if tool_name == "write_file" and not self._path_is_existing_file(rel_path):
            return False
        return True

    def chat(self, user_message: str) -> str:
        if self.context_memory.user_requests_memory_again(user_message): # type: ignore
            if not self.context_memory.memory_writes_enabled(): # type: ignore
                self.context_memory.set_memory_writes_disabled(False) # type: ignore
                print("  ○ Memory writes re-enabled for this session (will archive on exit).")
        elif self.context_memory.user_requests_no_memory(user_message): # type: ignore
            self.context_memory.set_memory_writes_disabled(True) # type: ignore
            print(
                "  ○ Memory writes disabled this session "
                "(remember/memorize blocked; exit will not archive)."
            )

        self.context_memory.append_message({"role": "user", "content": user_message}) # type: ignore

        self._files_read_this_turn = set()
        tool_rounds = 0
        intent = classify_turn(user_message)
        wants_edit = intent.wants_write
        wants_create = intent.create
        wants_memorize = intent.memorize
        nudge_budget = NudgeBudget()
        if wants_memorize and not self.context_memory.memory_writes_enabled(): # type: ignore
            reply = (
                "Memory writes are disabled this session. "
                "Say 'enable remembering' if you want to memorize that."
            )
            self.context_memory.append_message( # type: ignore
                {"role": "assistant", "content": reply}
            )
            self._persist()
            return reply

        write_applied = False
        write_declined = False
        command_applied = False
        command_declined = False
        memory_stored = False
        write_proposals = 0
        memory_recall_this_turn = False
        shell_allowlist_blocked = False
        write_policy_blocked = False
        read_paths: list[str] = []
        empty_write_paths: set[str] = set()
        file_snapshots: dict[str, str] = {}
        last_write_path: str | None = None

        while True:
            prefix = self._build_system_messages(
                user_message,
                empty_write_paths=empty_write_paths,
                file_snapshots=file_snapshots,
            )
            payload: dict[str, Any] = {
                "model": self.model,
                "messages": self._api_messages(prefix),
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "extra_body": llm_extra(),
            }

            schemas = self.tools.get_schemas()
            if schemas:
                payload["tools"] = schemas

            r = requests.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=300,
            )
            try:
                raise_for_llm_error(r)
            except requests.HTTPError as exc:
                if "No user query found" in str(exc):
                    self.context_memory.db.repair_message_history() # type: ignore
                    self.context_memory.db.pop_last_message() # type: ignore
                    raise requests.HTTPError(
                        f"{exc}\n"
                        "  → Repaired context and rolled back this message. "
                        "Try again (do not press Enter on an empty prompt).",
                        response=getattr(exc, "response", None),
                    ) from exc
                self.context_memory.db.pop_last_message() # type: ignore
                raise
            msg = r.json()["choices"][0]["message"]
            tool_calls = list(msg.get("tool_calls") or [])
            if not tool_calls:
                parsed = parse_text_tool_calls(str(msg.get("content") or ""))
                if parsed:
                    tool_calls = parsed
                    print(
                        f"  → parsed {len(tool_calls)} tool call(s) from assistant text"
                    )

            self.context_memory.append_message( # type: ignore
                {
                    "role": "assistant",
                    "content": msg.get("content"),
                    "tool_calls": tool_calls or None,
                }
            )

            if not tool_calls:
                if should_nudge_memorize(
                    intent, memory_stored=memory_stored, budget=nudge_budget
                ):
                    nudge_budget.memorize += 1
                    print("  → memorize pending — nudging model…")
                    self.context_memory.append_message( # type: ignore
                        {
                            "role": "user",
                            "content": memorize_nudge_message(
                                user_message,
                                suggested_text=memorize_text_from_message(user_message),
                            ),
                        }
                    )
                    self._persist()
                    continue
                if should_nudge_write(
                    intent,
                    write_applied=write_applied,
                    write_declined=write_declined,
                    write_policy_blocked=write_policy_blocked,
                    write_proposals=write_proposals,
                    max_write_proposals=self.max_write_proposals,
                    budget=nudge_budget,
                ):
                    nudge_budget.write += 1
                    label = (
                        "read_file first, then write…"
                        if not read_paths
                        else "write pending — nudging model…"
                    )
                    print(f"  → {label}")
                    self.context_memory.append_message( # type: ignore
                        {
                            "role": "user",
                            "content": write_nudge_message(
                                read_paths, create_ok=wants_create
                            ),
                        }
                    )
                    self._persist()
                    continue
                reply = message_text(msg) or (
                    "(no response from model — check LM Studio has a chat model loaded)"
                )
                if should_nudge_shell_staging(
                    intent,
                    command_applied=command_applied,
                    shell_allowlist_blocked=shell_allowlist_blocked,
                    budget=nudge_budget,
                ):
                    nudge_budget.shell_staging += 1
                    print("  → shell pending — nudging model…")
                    self.context_memory.append_message( # type: ignore
                        {"role": "user", "content": SHELL_STAGING_NUDGE}
                    )
                    self._persist()
                    continue
                if should_nudge_logging(intent, reply, nudge_budget):
                    nudge_budget.logging += 1
                    print("  → logging append — nudging model…")
                    self.context_memory.append_message( # type: ignore
                        {"role": "user", "content": LOGGING_NUDGE}
                    )
                    self._persist()
                    continue
                if should_nudge_recall(
                    intent,
                    memory_recall_this_turn=memory_recall_this_turn,
                    budget=nudge_budget,
                ):
                    nudge_budget.recall += 1
                    print("  → recall pending — nudging model…")
                    self.context_memory.append_message( # type: ignore
                        {
                            "role": "user",
                            "content": recall_nudge_message(
                                user_message,
                                fact_recall_key=intent.fact_recall_key,
                            ),
                        }
                    )
                    self._persist()
                    continue
                if (
                    is_meta_narration(reply)
                    and nudge_budget.meta < 1
                    and not memory_recall_this_turn
                ):
                    nudge_budget.meta += 1
                    print("  → meta narration — nudging model…")
                    self.context_memory.append_message( # type: ignore
                        {"role": "user", "content": META_NARRATION_NUDGE}
                    )
                    self._persist()
                    continue
                self._persist()
                return reply

            tool_rounds += 1
            if tool_rounds > self.max_tool_rounds:
                self._persist()
                return "Stopped: too many tool-call rounds."

            round_results: list[dict[str, Any]] = []
            for call in tool_calls:
                fn = call.get("function", {})
                name = fn.get("name")
                if write_declined and name in WRITE_TOOL_NAMES:
                    continue
                if command_declined and name in SHELL_TOOL_NAMES:
                    continue
                if shell_allowlist_blocked and name in SHELL_TOOL_NAMES:
                    continue
                if (
                    wants_edit
                    and not write_applied
                    and name in WRITE_TOOL_NAMES
                    and write_proposals >= self.max_write_proposals
                ):
                    continue
                print(f"  → {name}({fn.get('arguments', '')})")
                result = self._execute_tool_call(call)
                round_results.append(result)
                if name == "read_file" and not result.get("error"):
                    rel = str(result.get("path") or "")
                    if rel:
                        self._files_read_this_turn.add(rel)
                if name in WRITE_TOOL_NAMES:
                    last_write_path = str(result.get("path") or last_write_path or "")
                    if is_write_policy_error(result):
                        write_policy_blocked = True
                    if result.get("error") is None and not result.get("skipped"):
                        write_proposals += 1
                    if result.get("applied"):
                        write_applied = True
                    if result.get("cancelled"):
                        write_declined = True
                if name in SHELL_TOOL_NAMES:
                    if result.get("executed"):
                        command_applied = True
                    if result.get("cancelled"):
                        command_declined = True
                    if result.get("error") == "Command not on allowlist":
                        shell_allowlist_blocked = True
                if name in MEMORY_RECALL_TOOL_NAMES:
                    memory_recall_this_turn = True
                if name == "memorize" and result.get("stored"):
                    memory_stored = True
                if name == "remember" and result.get("saved"):
                    memory_stored = True
                print_tool_result(name, result)
                self.context_memory.append_message( # type: ignore
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id"),
                        "content": json.dumps(self._slim_tool_result(name, result)),
                    }
                )

            read_paths = paths_read_this_round(round_results) or read_paths
            empty_write_paths |= empty_files_from_results(round_results)
            file_snapshots.update(snapshots_from_results(round_results))

            if (
                shell_allowlist_blocked
                and not command_applied
                and not command_declined
            ):
                reply = format_command_outcome(round_results)
                self.context_memory.append_message( # type: ignore
                    {"role": "assistant", "content": reply}
                )
                self._persist()
                return reply

            if write_policy_blocked and not write_applied and not write_declined:
                reply = format_write_policy_outcome(round_results)
                self.context_memory.append_message( # type: ignore
                    {"role": "assistant", "content": reply}
                )
                self._persist()
                return reply

            if round_includes_tools(tool_calls, MEMORY_RECALL_TOOL_NAMES):
                recall_reply = format_memory_recall_outcome(round_results)
                if recall_reply and not wants_edit:
                    self.context_memory.append_message( # type: ignore
                        {"role": "assistant", "content": recall_reply}
                    )
                    self._persist()
                    return recall_reply

            if write_applied:
                reply = format_write_outcome(round_results)
                self.context_memory.append_message( # type: ignore
                    {"role": "assistant", "content": reply}
                )
                self._persist()
                return reply

            if memory_stored:
                reply = format_memorize_outcome(round_results)
                self.context_memory.append_message( # type: ignore
                    {"role": "assistant", "content": reply}
                )
                self._persist()
                return reply

            if command_applied:
                reply = format_command_outcome(round_results)
                self.context_memory.append_message( # type: ignore
                    {"role": "assistant", "content": reply}
                )
                self._persist()
                return reply

            if write_declined:
                reply = format_write_outcome(round_results)
                self.context_memory.append_message( # type: ignore
                    {"role": "assistant", "content": reply}
                )
                self._persist()
                return reply

            if command_declined:
                reply = format_command_outcome(round_results)
                self.context_memory.append_message( # type: ignore
                    {"role": "assistant", "content": reply}
                )
                self._persist()
                return reply

            if (
                wants_edit
                and write_proposals >= self.max_write_proposals
                and not write_applied
            ):
                reply = format_write_stopped(
                    last_write_path,
                    reason=(
                        f"max {self.max_write_proposals} write previews this turn "
                        "(approve one or ask again)."
                    ),
                )
                self.context_memory.append_message( # type: ignore
                    {"role": "assistant", "content": reply}
                )
                self._persist()
                return reply

            if should_nudge_tool_recovery(round_results, nudge_budget):
                nudge_budget.tool_recovery += 1
                recovery = build_tool_recovery_nudge(round_results)
                print("  → tool error — recovery nudge…")
                self.context_memory.append_message(  # type: ignore
                    {"role": "user", "content": recovery or ""}
                )
                self._persist()
                continue

            sources = grounding_from_tool_results(round_results)
            if sources and not should_skip_synthesis(intent, tool_calls):
                print("  → synthesizing answer from file contents…")
                synth_model, synth_url, synth_key, synth_temp, synth_max = (
                    self._synthesis_llm()
                )
                answer = synthesize_from_sources(
                    question=self._last_user_message(),
                    sources=sources,
                    model=synth_model,
                    base_url=synth_url,
                    api_key=synth_key,
                    temperature=synth_temp,
                    max_tokens=synth_max,
                )
                self.context_memory.append_message( # type: ignore
                    {"role": "assistant", "content": answer}
                )
                self._persist()
                return answer

            self._persist()

    def _execute_tool_call(self, tool_call: dict[str, Any]) -> dict[str, Any]:
        fn = tool_call.get("function", {})
        name = fn.get("name")

        if name in WRITE_TOOL_NAMES:
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            rel = self._normalize_rel_path(str(args.get("path", "")))
            if self._write_requires_read_first(name, rel):
                return {
                    "error": "Call read_file on this path before edit_file/delete_file",
                    "path": rel,
                    "hint": (
                        "For a NEW file use create_file (no read needed). "
                        "Prior chat about file contents may be stale."
                    ),
                }

        result = self.tools.execute(tool_call)

        if name in SHELL_TOOL_NAMES:
            if result.get("error"):
                print_command_proposal(result)
                return result

            print_command_proposal(result)

            if self.shell_config.require_approval:
                if not prompt_run():
                    return {
                        "cancelled": True,
                        "command": result.get("command"),
                        "cwd": result.get("cwd"),
                        "message": "User declined. Command was not run.",
                    }

            return execute_command(result, self.shell_config)

        if name not in WRITE_TOOL_NAMES:
            return result

        if result.get("error"):
            print_proposal(result)
            return result

        print_proposal(result)

        if self.require_write_approval:
            if not prompt_apply():
                return {
                    "applied": False,
                    "cancelled": True,
                    "path": result.get("path"),
                    "message": "User declined. No changes were written to disk.",
                }

        if self.workspace is None:
            return {"error": "Workspace not configured on agent"}

        return apply_proposal(result, self.workspace)

    @staticmethod
    def _slim_tool_result(name: str | None, result: dict[str, Any]) -> dict[str, Any]:
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


def run(agent: Agent) -> None:
    name = agent.config_name
    config_path = agent.config_path
    agents_path = agent.agents_md_path
    if config_path:
        print(f"{name} ready (config: {config_path})")
    else:
        print(f"{name} ready (defaults — no phaust.toml found)")
    if agents_path:
        print(f"  rules: {agents_path}")
    else:
        print("  rules: built-in fallback (no AGENTS.md)")
    print("Memory: SQLite + auto-compaction")
    extras = ["writes need approval"]
    if agent.shell_config.enabled:
        extras.append("shell allowlist (run_command needs approval)")
    print(f"  context | long-term | semantic | workspace ({'; '.join(extras)})")
    if agent.task_manager is not None:
        print("  tasks: type `task help` (multi-step mode with checkpoints)")
    print("Type 'exit' to quit.\n")

    agent.begin_session()

    while True:
        user = input("You: ").strip()
        if not user:
            continue
        if user.lower() in {"exit", "quit"}:
            if agent.context_memory and not agent.context_memory.memory_writes_enabled(): # type: ignore
                print("Ending session (memory writes were disabled — discarding transcript).")
            else:
                print("Saving session memory...")
            result = agent.finalize_session()
            if result:
                if result.get("memory_skipped"):
                    print(
                        f"  Discarded {result.get('compacted', 0)} messages "
                        "(no episode, no new facts)."
                    )
                else:
                    eid = result.get("episode_id")
                    id_note = f", episode id={eid}" if eid else ""
                    print(
                        f"  Session archived: {result.get('compacted', 0)} messages, "
                        f"{result.get('facts_saved', 0)} facts{id_note}"
                    )
            break
        if agent.task_manager is not None:
            task_reply = handle_task_command(agent.task_manager, user)
            if task_reply is not None:
                print(task_reply)
                continue
        reply = agent.chat(user)
        if agent.task_manager is not None:
            agent.task_manager.record_turn(user, reply or "")
        print("Agent:", reply if reply else "(empty)")
