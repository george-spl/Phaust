"""Allowlisted shell commands under the workspace root."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Any

if TYPE_CHECKING:
    from phaust.agent import Agent
    from phaust.workspace import Workspace

SHELL_TOOL_NAMES = frozenset({"run_command"})

DEFAULT_SHELL_ALLOW: tuple[str, ...] = (
    "python --version",
    "python -m pytest",
    "python -m pip list",
    "python -m pip show",
    "python -m py_compile",
    "git status",
    "git diff",
    "git branch",
    "git log",
)

_FORBIDDEN_SHELL_CHARS = re.compile(r"[;&|`<>]|\$\(")


@dataclass(frozen=True)
class ShellConfig:
    enabled: bool = True
    require_approval: bool = True
    timeout_seconds: int = 120
    max_output_bytes: int = 65_536
    allow: tuple[str, ...] = DEFAULT_SHELL_ALLOW


def default_shell_config() -> ShellConfig:
    return ShellConfig()


def _normalize_command(command: str) -> str:
    return " ".join((command or "").strip().split())


def _command_allowed(command: str, allow: tuple[str, ...]) -> str | None:
    """Return matched allow prefix, or None if not allowed."""
    normalized = _normalize_command(command)
    if not normalized:
        return None
    lower = normalized.lower()
    for entry in allow:
        prefix = _normalize_command(entry)
        if lower.startswith(prefix.lower()):
            return prefix
    return None


def _split_command(command: str) -> list[str]:
    return shlex.split(command, posix=(os.name != "nt"))


def _resolve_cwd(ws: Workspace, cwd: str) -> tuple[Any | None, dict[str, Any] | None]:
    try:
        target = ws.resolve(cwd or ".")
    except PermissionError as e:
        return None, {"error": str(e)}

    if not target.exists():
        return None, {"error": f"Working directory not found: {cwd}"}
    if not target.is_dir():
        return None, {"error": f"Not a directory: {cwd}"}
    return target, None


def _cap_output(text: str, max_bytes: int) -> tuple[str, bool]:
    if not text:
        return "", False
    raw = text.encode("utf-8", errors="replace")
    if len(raw) <= max_bytes:
        return text, False
    clipped = raw[:max_bytes].decode("utf-8", errors="ignore")
    return clipped + "\n... output truncated ...", True


def prepare_run_command(
    ws: Workspace,
    config: ShellConfig,
    command: str,
    cwd: str = ".",
) -> dict[str, Any]:
    """Validate a command proposal (no execution)."""
    if not config.enabled:
        return {
            "error": "Shell commands are disabled in phaust.toml ([shell] enabled = false).",
        }

    normalized = _normalize_command(command)
    if not normalized:
        return {"error": "Empty command"}

    if _FORBIDDEN_SHELL_CHARS.search(normalized):
        return {
            "error": "Command contains forbidden shell metacharacters",
            "hint": "Use a single simple command (no ; | & redirects).",
        }

    matched = _command_allowed(normalized, config.allow)
    if not matched:
        return {
            "error": "Command not on allowlist",
            "command": normalized,
            "hint": f"Allowed prefixes include: {', '.join(config.allow[:8])}"
            + (" …" if len(config.allow) > 8 else ""),
        }

    cwd_path, err = _resolve_cwd(ws, cwd)
    if err:
        return err

    try:
        args = _split_command(normalized)
    except ValueError as e:
        return {"error": f"Could not parse command: {e}"}

    if not args:
        return {"error": "Empty command after parsing"}

    rel_cwd = cwd_path.relative_to(ws.root).as_posix()  # type: ignore[union-attr]

    return {
        "action": "run_command",
        "command": normalized,
        "args": args,
        "cwd": rel_cwd,
        "cwd_abs": str(cwd_path),
        "matched_allow": matched,
        "summary": f"Run: {normalized}\ncwd: {rel_cwd}",
    }


def execute_command(proposal: dict[str, Any], config: ShellConfig) -> dict[str, Any]:
    """Run a previously approved command proposal."""
    if proposal.get("error"):
        return proposal

    args = proposal.get("args")
    cwd_abs = proposal.get("cwd_abs")
    command = proposal.get("command", "")

    if not args or not cwd_abs:
        return {"error": "invalid proposal: missing args or cwd"}

    try:
        completed = subprocess.run(
            args,
            cwd=str(cwd_abs),
            capture_output=True,
            text=True,
            timeout=config.timeout_seconds,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "executed": False,
            "command": command,
            "cwd": proposal.get("cwd"),
            "error": f"Command timed out after {config.timeout_seconds}s",
            "exit_code": None,
        }
    except OSError as e:
        return {
            "executed": False,
            "command": command,
            "cwd": proposal.get("cwd"),
            "error": str(e),
            "exit_code": None,
        }

    stdout, stdout_trunc = _cap_output(completed.stdout or "", config.max_output_bytes)
    stderr, stderr_trunc = _cap_output(completed.stderr or "", config.max_output_bytes)

    return {
        "executed": True,
        "command": command,
        "cwd": proposal.get("cwd"),
        "exit_code": completed.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "stdout_truncated": stdout_trunc,
        "stderr_truncated": stderr_trunc,
    }


def print_command_proposal(proposal: dict[str, Any]) -> None:
    print("\n" + "=" * 60)
    print("PROPOSED COMMAND (not run yet)")
    print("=" * 60)
    if proposal.get("error"):
        print(f"Error: {proposal['error']}")
        if proposal.get("hint"):
            print(f"Hint: {proposal['hint']}")
        print("=" * 60 + "\n")
        return
    print(proposal.get("summary", proposal.get("command", "")))
    print("=" * 60)


def prompt_run() -> bool:
    answer = input("Run this command? [y/N]: ").strip().lower()
    return answer in ("y", "yes")


def format_command_output(result: dict[str, Any], *, max_chars: int = 2000) -> str:
    """Human-readable stdout/stderr from an executed run_command result."""
    stdout = (result.get("stdout") or "").strip()
    stderr = (result.get("stderr") or "").strip()
    parts: list[str] = []
    if stdout:
        parts.append(stdout)
    if stderr:
        parts.append(f"[stderr]\n{stderr}")
    if not parts:
        return "(no output)"
    text = "\n".join(parts)
    if len(text) > max_chars:
        return text[:max_chars] + "\n... (output truncated in reply) ..."
    return text


def print_command_result(result: dict[str, Any], *, max_lines: int = 30) -> None:
    """Print command output to the terminal after execution."""
    if not result.get("executed"):
        return
    text = format_command_output(result, max_chars=50_000)
    if text == "(no output)":
        return
    lines = text.splitlines()
    if len(lines) > max_lines:
        lines = lines[:max_lines] + [f"... ({len(text.splitlines()) - max_lines} more lines) ..."]
    for line in lines:
        print(f"       {line}")


def register_shell_tools(
    agent: Agent,
    workspace: Workspace,
    config: ShellConfig,
) -> None:
    """Attach run_command when shell is enabled in config."""

    if not config.enabled:
        return

    @agent.tool
    def run_command(
        command: str,
        cwd: Annotated[str, "Working directory relative to workspace root"] = ".",
    ) -> dict:
        """Run an allowlisted shell command under the workspace. User must approve before execution."""
        return prepare_run_command(workspace, config, command, cwd=cwd)
