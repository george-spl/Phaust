"""Load project agent instructions from AGENTS.md."""

from __future__ import annotations

from pathlib import Path

DEFAULT_AGENTS_MD = "AGENTS.md"

# Minimal fallback if AGENTS.md is missing
_FALLBACK = """\
Use read_file before answering about code. Use list_directory or list_files to explore folders; use create_file for new files; use edit_file, write_file, or delete_file for existing files (after read_file). Use run_command for allowlisted shell commands (user approves at terminal).
Writes require user approval at the terminal. Do not greet on every message.\
"""


def resolve_agents_path(
    project_root: Path,
    agents_md: str | None = None,
) -> Path | None:
    """Resolve AGENTS.md path relative to project root. Empty string disables."""
    if agents_md is not None and not str(agents_md).strip():
        return None
    rel = (agents_md or DEFAULT_AGENTS_MD).strip()
    path = Path(rel)
    if path.is_absolute():
        return path if path.is_file() else None
    candidate = (project_root / path).resolve()
    return candidate if candidate.is_file() else None


def load_agents_instructions(
    project_root: Path,
    agents_md: str | None = None,
) -> tuple[str, Path | None]:
    """
    Read AGENTS.md body (without markdown title if you want — we pass full file).
    Returns (instructions_text, path_or_none).
    """
    path = resolve_agents_path(project_root, agents_md)
    if path is None:
        return _FALLBACK, None
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return _FALLBACK, path
    return text, path


def build_system_prompt(
    agent_name: str,
    instructions: str,
) -> str:
    """Combine agent name with AGENTS.md (or fallback) instructions."""
    return f"# System instructions for {agent_name}\n\n{instructions}"
