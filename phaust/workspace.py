"""Read-only workspace tools (files under a single project root)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

if TYPE_CHECKING:
    from phaust.agent import Agent

MAX_READ_BYTES = 512_000
MAX_LINES_DEFAULT = 200
MAX_LIST_FILES = 300
MAX_GREP_MATCHES = 80

SKIP_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    "node_modules",
    ".cursor",
    "agent-transcripts",
}


class Workspace:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).resolve()

    def resolve(self, path: str = ".") -> Path:
        raw = (path or ".").strip().lstrip("/\\")
        if not raw:
            raw = "."
        target = (self.root / raw).resolve()
        try:
            target.relative_to(self.root)
        except ValueError as e:
            raise PermissionError(f"Path outside workspace: {path}") from e
        return target

    def read_file(
        self,
        path: str,
        offset: int = 1,
        limit: int = MAX_LINES_DEFAULT,
    ) -> dict[str, Any]:
        target = self.resolve(path)
        if not target.is_file():
            return {"error": f"Not a file: {path}"}

        size = target.stat().st_size
        if size > MAX_READ_BYTES:
            return {
                "error": f"File too large ({size} bytes). Max {MAX_READ_BYTES}. "
                "Use offset/limit or grep.",
                "path": path,
                "size": size,
            }

        text = target.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        start = max(0, offset - 1)
        end = start + max(1, min(limit, MAX_LINES_DEFAULT))
        chunk = lines[start:end]

        content = "\n".join(
            f"{start + i + 1}|{line}" for i, line in enumerate(chunk)
        )
        return {
            "path": path,
            "total_lines": len(lines),
            "offset": offset,
            "limit": limit,
            "content": content,
        }

    def list_files(self, glob_pattern: str = "**/*") -> dict[str, Any]:
        pattern = (glob_pattern or "**/*").strip()
        matches: list[str] = []

        for path in sorted(self.root.glob(pattern)):
            if len(matches) >= MAX_LIST_FILES:
                break
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            rel = path.relative_to(self.root).as_posix()
            if path.is_dir():
                matches.append(f"{rel}/")
            else:
                matches.append(rel)

        return {
            "workspace": str(self.root),
            "pattern": pattern,
            "count": len(matches),
            "truncated": len(matches) >= MAX_LIST_FILES,
            "paths": matches,
        }

    def grep(
        self,
        pattern: str,
        path: str = ".",
        glob: str = "**/*",
    ) -> dict[str, Any]:
        try:
            regex = re.compile(pattern)
        except re.error as e:
            return {"error": f"Invalid regex: {e}"}

        base = self.resolve(path)
        files: list[Path] = []
        if base.is_file():
            files = [base]
        elif base.is_dir():
            files = [
                p
                for p in base.glob(glob)
                if p.is_file() and not any(part in SKIP_DIRS for part in p.parts)
            ]
        else:
            return {"error": f"Not found: {path}"}

        hits: list[dict[str, Any]] = []
        for file_path in sorted(files):
            if len(hits) >= MAX_GREP_MATCHES:
                break
            try:
                if file_path.stat().st_size > MAX_READ_BYTES:
                    continue
                text = file_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            rel = file_path.relative_to(self.root).as_posix()
            for i, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    hits.append({"file": rel, "line": i, "text": line[:300]})
                    if len(hits) >= MAX_GREP_MATCHES:
                        break

        return {
            "pattern": pattern,
            "matches": hits,
            "truncated": len(hits) >= MAX_GREP_MATCHES,
        }

    def summary(self) -> str:
        entries = []
        try:
            for child in sorted(self.root.iterdir()):
                if child.name in SKIP_DIRS:
                    continue
                suffix = "/" if child.is_dir() else ""
                entries.append(child.name + suffix)
        except OSError:
            entries = ["(unreadable)"]
        return f"workspace: {self.root}\nentries: {', '.join(entries[:40])}"


def register_readonly_tools(agent: Agent, workspace: Workspace) -> None:
    """Attach read_file, list_files, grep to an agent."""

    @agent.tool
    def read_file(
        path: str,
        offset: Annotated[int, "Start line (1-based)"] = 1,
        limit: Annotated[int, "Max lines to return"] = 200,
    ) -> dict:
        """Read a text file under the workspace. Use before answering code questions."""
        return workspace.read_file(path, offset=offset, limit=limit)

    @agent.tool
    def list_files(
        glob_pattern: Annotated[str, "Glob under workspace, e.g. **/*.py"] = "**/*",
    ) -> dict:
        """List files matching a glob pattern under the workspace."""
        return workspace.list_files(glob_pattern)

    @agent.tool
    def grep(
        pattern: str,
        path: Annotated[str, "File or folder relative to workspace"] = ".",
        glob: Annotated[str, "File filter when path is a directory"] = "**/*",
    ) -> dict:
        """Search file contents with a regex pattern under the workspace."""
        return workspace.grep(pattern, path=path, glob=glob)
