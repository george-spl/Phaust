"""Phaust-1 — local agent entry point."""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Annotated

from phaust import Agent, run
from phaust import workspace
from phaust.config import load_config
from phaust.workspace import Workspace, register_readonly_tools
from phaust.workspace_write import register_write_tools

WORKSPACE_ROOT = Path(__file__).resolve().parent

SYSTEM_PROMPT = """\
Your name is Phaust-1 (Predictive Heuristic Autonomous Utility System Technology, iteration 1).
Only greet the user at startup, not every message.

Tools: read_file, list_files, grep, edit_file, write_file, delete_file, and memory tools.
For code questions: read_file first; do not guess file contents.
When the user asks to change a file: call read_file first, then edit_file, write_file, or delete_file — never stop after read_file with only a text plan or shell commands.
To remove a file entirely: delete_file (after read_file). To clear contents but keep the file: write_file with empty content.
Use the tool API (function calls), not XML or markdown describing tools.
For adding one line or a comment, use edit_file (not a full-file write_file).
If read_file shows an empty file, write only the new lines requested — plain text, no line-number prefixes, no content from old chat.
To append lines, edit_file with old_string copied exactly from read_file (no invented prefixes).
Put new comments where the user implies (e.g. under the title or before a named section), not at EOF unless they want that.
edit_file replaces exactly one unique old_string in a file.
write_file creates or overwrites a whole file.
IMPORTANT: edit_file and write_file only PREVIEW changes until the user approves in the terminal; tell the user to review the diff and answer y/N — nothing is saved until they approve.
Never write under Memory/, .venv/, or .git/.
Talk like an English gentleman; be precise and helpful.\
"""


def build_agent(workspace_root: Path | None = None) -> Agent:
    project_root = workspace_root or WORKSPACE_ROOT
    config, config_path = load_config(project_root=project_root)
    ws_root = config.workspace_root or project_root

    agent = Agent(
        workspace=Workspace(ws_root),
        system_prompt=SYSTEM_PROMPT,
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
    )
    agent.config_path = config_path
    agent.config_name = config.name

    @agent.context
    def time_context() -> str:
        return datetime.datetime.now().isoformat()

    @agent.context
    def workspace_context() -> str:
        return workspace.summary() # type: ignore

    register_readonly_tools(agent, workspace) # type: ignore
    register_write_tools(agent, workspace) # type: ignore

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
        """Store an explicit fact in long-term memory."""
        blocked = _memory_writes_blocked()
        if blocked:
            return blocked
        return lt.remember(key, value)

    @agent.tool
    def recall(key: str) -> dict:
        """Retrieve a fact from long-term memory by key."""
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
        """Store text in semantic memory for later similarity recall."""
        blocked = _memory_writes_blocked()
        if blocked:
            return blocked
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        return sem.store(text, source="tool", tags=tag_list)

    @agent.tool
    def search_semantic(query: str, top_k: int = 5) -> dict:
        """Search semantic memory by meaning/similarity."""
        return {"results": sem.search(query, top_k=top_k)}

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
