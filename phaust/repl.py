"""Interactive REPL session for Phaust."""

from __future__ import annotations

from phaust.agent import Agent
from phaust.tasks import handle_task_command
from phaust.turn_loop import run_chat_turn


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
            if agent.context_memory and not agent.context_memory.memory_writes_enabled():  # type: ignore
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
        reply = run_chat_turn(agent, user)
        if agent.task_manager is not None:
            agent.task_manager.record_turn(user, reply or "")
        print("Agent:", reply if reply else "(empty)")
