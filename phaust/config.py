"""Load Phaust settings from phaust.toml (stdlib tomllib)."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PhaustConfig:
    model: str = "qwen/qwen3.5-9b"
    base_url: str = "http://127.0.0.1:1234/v1"
    api_key: str = "NO_API_KEY"
    temperature: float = 0.3
    max_tokens: int = 8192
    workspace_root: Path | None = None
    max_messages: int = 50
    compact_batch: int = 10
    max_episodes: int = 500
    semantic_top_k: int = 5
    max_tool_rounds: int = 12
    max_write_proposals: int = 2
    require_write_approval: bool = True
    iteration: int = 1
    name: str = "Phaust-1"
    agents_md: str = "AGENTS.md"


def _resolve_path(value: str, base: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    return (base / path).resolve()


def _coerce_table(raw: dict[str, Any], config: PhaustConfig, base: Path) -> PhaustConfig:
    """Build a new config from defaults + TOML tables."""
    llm = raw.get("llm") or {}
    workspace = raw.get("workspace") or {}
    memory = raw.get("memory") or {}
    agent = raw.get("agent") or {}
    meta = raw.get("phaust") or {}

    ws_root = config.workspace_root
    if isinstance(workspace.get("root"), str) and workspace["root"].strip():
        ws_root = _resolve_path(workspace["root"].strip(), base)

    return PhaustConfig(
        model=str(llm.get("model", config.model)),
        base_url=str(llm.get("base_url", config.base_url)).rstrip("/"),
        api_key=str(llm.get("api_key", config.api_key)),
        temperature=float(llm.get("temperature", config.temperature)),
        max_tokens=int(llm.get("max_tokens", config.max_tokens)),
        workspace_root=ws_root,
        max_messages=int(memory.get("max_messages", config.max_messages)),
        compact_batch=int(memory.get("compact_batch", config.compact_batch)),
        max_episodes=int(memory.get("max_episodes", config.max_episodes)),
        semantic_top_k=int(memory.get("semantic_top_k", config.semantic_top_k)),
        max_tool_rounds=int(agent.get("max_tool_rounds", config.max_tool_rounds)),
        max_write_proposals=int(
            agent.get("max_write_proposals", config.max_write_proposals)
        ),
        require_write_approval=bool(
            agent.get("require_write_approval", config.require_write_approval)
        ),
        iteration=int(meta.get("iteration", config.iteration)),
        name=str(meta.get("name", config.name)),
        agents_md=str(agent.get("agents_md", config.agents_md)),
    )


def find_config_path(project_root: Path) -> Path | None:
    """Locate phaust.toml: env override, then project root."""
    env_path = os.environ.get("PHAUST_CONFIG", "").strip()
    if env_path:
        path = Path(env_path).expanduser()
        if path.is_file():
            return path.resolve()

    for candidate in (
        project_root / "phaust.toml",
        Path.cwd() / "phaust.toml",
    ):
        if candidate.is_file():
            return candidate.resolve()
    return None


def load_config(
    *,
    project_root: Path | None = None,
    config_path: Path | None = None,
) -> tuple[PhaustConfig, Path | None]:
    """
    Load configuration. Missing file returns defaults.
    Returns (config, path_or_none).
    """
    base = (project_root or Path.cwd()).resolve()
    path = config_path.resolve() if config_path else find_config_path(base)
    config = PhaustConfig(workspace_root=base)

    if path is None:
        return config, None

    with open(path, "rb") as f:
        raw = tomllib.load(f)
    if not isinstance(raw, dict):
        return config, path

    return _coerce_table(raw, config, path.parent), path
