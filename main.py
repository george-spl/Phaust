#"""Phaust-1 — local agent with three-layer memory."""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Annotated

from phaust import Agent, run
from phaust.workspace import Workspace, register_readonly_tools

WORKSPACE_ROOT = Path(__file__).resolve().parent


def build_agent(workspace_root: Path | None = None) -> Agent:
    workspace = Workspace(workspace_root or WORKSPACE_ROOT)

    agent = Agent(
        system_prompt=(
            "Your name is Phaust-1. It means Predictive Heuristic Autonomous Utility System Technology iteration 1"
            "Tools: read_file, list_files, grep, and memory tools. "
            "For questions about code or files: call read_file on the path first. "
            "Do not guess file contents. "
            "Memory modules are under phaust/memory/; agent.py is the chat/tool loop only."
            "You are a friendly assistant"
            "Talk like an English gentleman. No roleplay, just behaviour."
        ),
    )

    @agent.context
    def time_context() -> str:
        return datetime.datetime.now().isoformat()

    @agent.context
    def workspace_context() -> str:
        return workspace.summary()

    register_readonly_tools(agent, workspace)

    # ── Long-term memory tools ──────────────────────────────

    @agent.tool
    def remember(key: str, value: str) -> dict:
        """Store an explicit fact in long-term memory."""
        return agent.long_term.remember(key, value) # type: ignore

    @agent.tool
    def recall(key: str) -> dict:
        """Retrieve a fact from long-term memory by key."""
        return agent.long_term.recall(key) # type: ignore

    @agent.tool
    def forget(key: str) -> dict:
        """Remove a fact from long-term memory."""
        return agent.long_term.forget(key) # type: ignore

    @agent.tool
    def list_memories() -> dict:
        """List all keys stored in long-term memory."""
        return agent.long_term.list_facts() # type: ignore

    # ── Semantic memory tools ───────────────────────────────

    @agent.tool
    def memorize(
        text: str,
        tags: Annotated[str | None, "Comma-separated tags, optional"] = None,
    ) -> dict:
        """Store text in semantic memory for later similarity recall."""
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        return agent.semantic.store(text, source="tool", tags=tag_list) # type: ignore

    @agent.tool
    def search_semantic(query: str, top_k: int = 5) -> dict:
        """Search semantic memory by meaning/similarity."""
        return {"results": agent.semantic.search(query, top_k=top_k)} # type: ignore

    @agent.tool
    def forget_semantic(entry_id: str) -> dict:
        """Delete a semantic memory entry by id."""
        return agent.semantic.forget(entry_id) # type: ignore

    # ── Context memory tools ────────────────────────────────

    @agent.tool
    def set_session(key: str, value: str) -> dict:
        """Set a session variable in context memory (working memory)."""
        agent.context_memory.set_session(key, value) # type: ignore
        return {"saved": True, "key": key}

    @agent.tool
    def get_session(key: str) -> dict:
        """Get a session variable from context memory."""
        return {"key": key, "value": agent.context_memory.get_session(key)} # type: ignore

    # ── Demo math tools ─────────────────────────────────────

    @agent.tool
    def add(a: int, b: int) -> dict:
        return {"result": a + b}

    @agent.tool
    def multiply(a: int, b: int) -> dict:
        return {"result": a * b}

    return agent


if __name__ == "__main__":
    run(build_agent())
