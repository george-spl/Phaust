"""Phaust-1 — local agent entry point."""

from __future__ import annotations

import datetime
import re
from pathlib import Path
from typing import Annotated

from phaust import Agent, run
from phaust.config import load_config
from phaust.prompts import build_system_prompt, load_agents_instructions
from phaust.workspace import Workspace, register_readonly_tools
from phaust.workspace_write import register_write_tools
from phaust.shell import register_shell_tools

WORKSPACE_ROOT = Path(__file__).resolve().parent

_EPISODE_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def build_agent(workspace_root: Path | None = None) -> Agent:
    project_root = workspace_root or WORKSPACE_ROOT
    config, config_path = load_config(project_root=project_root)
    ws_root = config.workspace_root or project_root

    instructions, agents_path = load_agents_instructions(ws_root, config.agents_md)
    system_prompt = build_system_prompt(config.name, instructions)

    workspace = Workspace(ws_root)
    agent = Agent(
        workspace=workspace,
        system_prompt=system_prompt,
        model=config.model,
        base_url=config.base_url,
        api_key=config.api_key,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        max_messages=config.max_messages,
        compact_batch=config.compact_batch,
        max_episodes=config.max_episodes,
        semantic_top_k=config.semantic_top_k,
        max_tool_rounds=config.max_tool_rounds,
        max_write_proposals=config.max_write_proposals,
        require_write_approval=config.require_write_approval,
        shell_config=config.shell,
    )
    agent.config_path = config_path
    agent.config_name = config.name
    agent.agents_md_path = agents_path

    @agent.context
    def time_context() -> str:
        return datetime.datetime.now().isoformat()

    @agent.context
    def workspace_context() -> str:
        return workspace.summary()

    register_readonly_tools(agent, workspace)
    register_write_tools(agent, workspace)
    register_shell_tools(agent, workspace, config.shell)

    assert agent.long_term and agent.semantic and agent.context_memory
    lt = agent.long_term
    sem = agent.semantic
    ctx = agent.context_memory

    def _memory_writes_blocked() -> dict | None:
        if not ctx.memory_writes_enabled():
            return {
                "saved": False,
                "skipped": True,
                "reason": "Memory writes disabled for this session.",
            }
        return None

    @agent.tool
    def remember(key: str, value: str) -> dict:
        """Store one key-value fact in long-term memory (e.g. key=user_name, value=George). Not for episodes or long text — use memorize."""
        blocked = _memory_writes_blocked()
        if blocked:
            return blocked
        return lt.remember(key, value)

    @agent.tool
    def recall(key: str) -> dict:
        """Retrieve a fact from long-term memory by key (snake_case). Not for episode UUIDs — use recall_episode."""
        key = key.strip()
        if _EPISODE_ID_RE.match(key):
            episode = sem.recall_episode(key)
            if not episode.get("error"):
                return {
                    "key": key,
                    "value": None,
                    "hint": "That is an episode id, not a fact key.",
                    "episode": episode,
                }
            return {
                **lt.recall(key),
                "hint": "Looks like an episode UUID. Use recall_episode or search_semantic.",
            }
        return lt.recall(key)

    @agent.tool
    def forget(key: str) -> dict:
        """Remove a fact from long-term memory."""
        return lt.forget(key)

    @agent.tool
    def list_memories() -> dict:
        """List all keys stored in long-term memory."""
        return lt.list_facts()

    @agent.tool
    def memorize(
        text: str,
        tags: Annotated[str | None, "Comma-separated tags, optional"] = None,
    ) -> dict:
        """Store a note or conversation snippet in episodic semantic memory. Use text=..., not remember()."""
        blocked = _memory_writes_blocked()
        if blocked:
            return blocked
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        return sem.store(text, source="tool", tags=tag_list)

    @agent.tool
    def search_semantic(query: str, top_k: int = 5) -> dict:
        """Search episodic memory by meaning/similarity (not exact UUID lookup)."""
        return {"results": sem.search(query, top_k=top_k)}

    @agent.tool
    def recall_episode(entry_id: str) -> dict:
        """Retrieve one archived conversation episode by its UUID."""
        return sem.recall_episode(entry_id)

    @agent.tool
    def list_episodes(limit: int = 20) -> dict:
        """List recent episode ids with short previews."""
        return {"episodes": sem.list_episode_summaries(limit=limit)}

    @agent.tool
    def forget_semantic(entry_id: str) -> dict:
        """Delete a semantic memory entry by id."""
        return sem.forget(entry_id)

    @agent.tool
    def set_session(key: str, value: str) -> dict:
        """Set a session variable in context memory."""
        ctx.set_session(key, value)
        return {"saved": True, "key": key}

    @agent.tool
    def get_session(key: str) -> dict:
        """Get a session variable from context memory."""
        return {"key": key, "value": ctx.get_session(key)}

    return agent


if __name__ == "__main__":
    run(build_agent())
