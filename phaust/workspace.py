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
        try:
            offset = int(offset)
        except (TypeError, ValueError):
            offset = 1
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = MAX_LINES_DEFAULT
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
        rel = target.relative_to(self.root).as_posix()

        return {
            "path": rel,
            "total_lines": len(lines),
            "offset": offset,
            "limit": limit,
            "content": "\n".join(chunk),
        }

    def list_files(
        self,
        glob_pattern: str = "**/*",
        path: str = ".",
    ) -> dict[str, Any]:
        """List files matching a glob, optionally scoped to a subdirectory."""
        pattern = (glob_pattern or "**/*").strip()
        try:
            base = self.resolve(path)
        except PermissionError as e:
            return {"error": str(e)}

        if base.is_file():
            rel = base.relative_to(self.root).as_posix()
            return {
                "workspace": str(self.root),
                "path": rel,
                "pattern": pattern,
                "count": 1,
                "truncated": False,
                "paths": [rel],
            }

        if not base.is_dir():
            return {"error": f"Not a directory: {path}"}

        search_root = base
        matches: list[str] = []

        for item in sorted(search_root.glob(pattern)):
            if len(matches) >= MAX_LIST_FILES:
                break
            if any(part in SKIP_DIRS for part in item.parts):
                continue
            rel = item.relative_to(self.root).as_posix()
            if item.is_dir():
                matches.append(f"{rel}/")
            else:
                matches.append(rel)

        return {
            "workspace": str(self.root),
            "path": base.relative_to(self.root).as_posix(),
            "pattern": pattern,
            "count": len(matches),
            "truncated": len(matches) >= MAX_LIST_FILES,
            "paths": matches,
        }

    def list_directory(
        self,
        path: str = ".",
        recursive: bool = False,
    ) -> dict[str, Any]:
        """List files and folders under a directory (non-glob)."""
        try:
            base = self.resolve(path)
        except PermissionError as e:
            return {"error": str(e)}

        if base.is_file():
            rel = base.relative_to(self.root).as_posix()
            return {
                "path": rel,
                "recursive": False,
                "count": 1,
                "truncated": False,
                "entries": [{"path": rel, "type": "file"}],
            }

        if not base.is_dir():
            return {"error": f"Not a directory: {path}"}

        rel_base = base.relative_to(self.root).as_posix()
        pattern = "**/*" if recursive else "*"
        entries: list[dict[str, str]] = []

        for item in sorted(base.glob(pattern)):
            if len(entries) >= MAX_LIST_FILES:
                break
            if any(part in SKIP_DIRS for part in item.parts):
                continue
            rel = item.relative_to(self.root).as_posix()
            kind = "dir" if item.is_dir() else "file"
            entries.append({"path": rel, "type": kind})

        return {
            "path": rel_base,
            "recursive": recursive,
            "count": len(entries),
            "truncated": len(entries) >= MAX_LIST_FILES,
            "entries": entries,
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
        """Read a text file under the workspace. Returns exact file text in content (for edit_file)."""
        return workspace.read_file(path, offset=offset, limit=limit)

    @agent.tool
    def list_files(
        glob_pattern: Annotated[str, "Glob under path, e.g. **/*.py"] = "**/*",
        path: Annotated[str, "Folder or file relative to workspace root"] = ".",
    ) -> dict:
        """List files matching a glob pattern, optionally under a subdirectory."""
        return workspace.list_files(glob_pattern, path=path)

    @agent.tool
    def list_directory(
        path: Annotated[str, "Folder relative to workspace, e.g. phaust or phaust/memory"] = ".",
        recursive: Annotated[bool, "If true, list all nested files and folders"] = False,
    ) -> dict:
        """List contents of a directory. Use recursive=true to include subfolders (e.g. read all files in phaust/)."""
        return workspace.list_directory(path, recursive=recursive)

    @agent.tool
    def grep(
        pattern: str,
        path: Annotated[str, "File or folder relative to workspace"] = ".",
        glob: Annotated[str, "File filter when path is a directory"] = "**/*",
    ) -> dict:
        """Search file contents with a regex pattern under the workspace."""
        return workspace.grep(pattern, path=path, glob=glob)
