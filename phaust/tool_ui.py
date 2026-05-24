"""Terminal formatting for tool results."""

from __future__ import annotations

from typing import Any

from phaust.shell import print_command_result
from phaust.workspace_write import WRITE_TOOL_NAMES


def print_tool_result(name: str | None, result: dict[str, Any]) -> None:
    if result.get("skipped"):
        print(f"     ○ {name}: {result.get('reason', 'skipped')}")
        return
    if result.get("error"):
        print(f"     ✗ {result['error']}")
        if result.get("hint"):
            for line in str(result["hint"]).splitlines()[:4]:
                print(f"       {line}")
        return
    if name == "read_file":
        lines = result.get("total_lines", "?")
        path = result.get("path", "?")
        print(f"     ✓ read {path} ({lines} lines)")
    elif name == "grep":
        n = len(result.get("matches") or [])
        print(f"     ✓ {n} match(es)")
    elif name in ("list_files", "list_directory"):
        print(f"     ✓ {result.get('count', 0)} path(s)")
    elif name == "run_command":
        if result.get("executed"):
            code = result.get("exit_code", "?")
            print(f"     ✓ exit {code}")
            print_command_result(result)
        elif result.get("cancelled"):
            print("     ○ cancelled (not run)")
        elif result.get("error"):
            print(f"     ✗ {result['error']}")
    elif name == "memorize":
        if result.get("stored"):
            print(f"     ✓ memorized id={result.get('id', '?')}")
        elif result.get("skipped"):
            print(f"     ○ {name}: {result.get('reason', 'skipped')}")
        elif result.get("error"):
            print(f"     ✗ {result['error']}")
    elif name == "remember":
        if result.get("saved"):
            print(f"     ✓ remembered {result.get('key')}")
        elif result.get("skipped"):
            print(f"     ○ {name}: {result.get('reason', 'skipped')}")
        elif result.get("error"):
            print(f"     ✗ {result['error']}")
    elif name in ("recall_episode", "recall"):
        if result.get("error"):
            print(f"     ✗ {result['error']}")
            if result.get("hint"):
                print(f"       {result['hint']}")
        elif result.get("text"):
            eid = result.get("id", "?")
            chars = len(str(result.get("text") or ""))
            print(f"     ✓ episode {eid} ({chars} chars)")
        elif result.get("value") is not None:
            print(f"     ✓ {result.get('key')} = {result.get('value')}")
        elif result.get("key"):
            print(f"     ○ no fact for {result.get('key')}")
    elif name == "search_semantic":
        hits = result.get("results") or []
        print(f"     ✓ {len(hits)} hit(s)")
    elif name in WRITE_TOOL_NAMES:
        if result.get("applied") and result.get("deleted"):
            print(f"     ✓ deleted {result.get('path')}")
        elif result.get("applied"):
            print(f"     ✓ written {result.get('path')} ({result.get('bytes', '?')} bytes)")
        elif result.get("cancelled"):
            print("     ○ cancelled (disk unchanged)")
        elif result.get("error"):
            print(f"     ✗ {result['error']}")
