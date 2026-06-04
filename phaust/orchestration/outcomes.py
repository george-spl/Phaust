"""Format tool-round results into user-facing assistant replies."""

from __future__ import annotations

from typing import Any

from phaust.shell import format_command_output

_EPISODE_BODY_LIMIT = 2400
_SEMANTIC_HIT_PREVIEW = 240
_SEMANTIC_SEARCH_LIMIT = 1200


def _format_semantic_search_hit(hit: dict[str, Any]) -> str:
    score = hit.get("score", "?")
    eid = hit.get("id", "?")
    text = str(hit.get("text") or "")
    if len(text) > _SEMANTIC_SEARCH_LIMIT:
        text = text[:_SEMANTIC_SEARCH_LIMIT] + "\n… [truncated]"
    hint = hit.get("matched_hints")
    hint_note = f" hints={hint}" if hint else ""
    return f"### ({score}) {eid}{hint_note}\n{text}"


def format_memory_recall_outcome(results: list[dict[str, Any]]) -> str | None:
    lines: list[str] = []
    for result in results:
        if result.get("error"):
            err = result["error"]
            hint = result.get("hint")
            lines.append(str(err) + (f" {hint}" if hint else ""))
            continue
        if result.get("text") and result.get("id"):
            body = str(result["text"])
            if len(body) > _EPISODE_BODY_LIMIT:
                body = body[:_EPISODE_BODY_LIMIT] + "\n… [episode truncated]"
            lines.append(f"Episode {result['id']}:\n{body}")
            continue
        if result.get("episode"):
            ep = result["episode"]
            body = str(ep.get("text") or "")
            if len(body) > _EPISODE_BODY_LIMIT:
                body = body[:_EPISODE_BODY_LIMIT] + "\n… [episode truncated]"
            lines.append(
                "That value is an episode id, not a fact key.\n\n"
                f"Episode {ep.get('id')}:\n{body}"
            )
            continue
        if result.get("key") is not None:
            val = result.get("value")
            if val is not None:
                lines.append(f"{result['key']} = {val}")
            else:
                hint = result.get("hint") or "Use recall_episode for episode UUIDs."
                lines.append(f"No fact stored for `{result['key']}`. {hint}")
            continue
        if "results" in result:
            hits = result.get("results") or []
            if not hits:
                lines.append("No matching episodes in semantic memory.")
            else:
                for hit in hits[:8]:
                    lines.append(_format_semantic_search_hit(hit))
            continue
        if result.get("episodes") is not None:
            eps = result.get("episodes") or []
            if not eps:
                lines.append("No archived episodes yet.")
            else:
                for ep in eps[:12]:
                    lines.append(f"- {ep.get('id')}: {ep.get('preview', '')}")
            continue
        if result.get("keys") is not None:
            keys = result.get("keys") or []
            if not keys:
                lines.append("No long-term facts stored.")
            else:
                lines.append("Stored fact keys: " + ", ".join(keys))
    return "\n\n".join(lines) if lines else None


def paths_read_this_round(results: list[dict[str, Any]]) -> list[str]:
    paths: list[str] = []
    for result in results:
        path = result.get("path")
        if path and result.get("content") is not None:
            paths.append(str(path))
    return paths


def format_write_outcome(results: list[dict[str, Any]]) -> str:
    for result in results:
        if result.get("applied"):
            if result.get("deleted"):
                return f"Deleted {result.get('path', 'file')}."
            if result.get("created"):
                return (
                    f"Created {result.get('path', 'file')}. "
                    "You can ask me to read the file to verify."
                )
            return (
                f"Change applied to {result.get('path', 'file')}. "
                "You can ask me to read the file to verify."
            )
        if result.get("cancelled"):
            return (
                f"Change to {result.get('path', 'file')} was not applied "
                "(you declined at the prompt)."
            )
    return "Write proposal reviewed."


def format_command_outcome(results: list[dict[str, Any]]) -> str:
    for result in results:
        if result.get("executed"):
            code = result.get("exit_code")
            cmd = result.get("command", "command")
            status = f"exit {code}" if code is not None else "done"
            output = format_command_output(result)
            if output == "(no output)":
                return f"Ran `{cmd}` ({status}) — no output."
            return f"Ran `{cmd}` ({status}):\n\n{output}"
        if result.get("cancelled"):
            return (
                f"Command `{result.get('command', 'command')}` was not run "
                "(you declined at the prompt)."
            )
        if result.get("error") and result.get("command"):
            hint = result.get("hint")
            msg = f"Could not run `{result.get('command')}`: {result['error']}"
            if hint:
                msg += f"\n\n{hint}"
            return msg
    return "Command proposal reviewed."


def format_write_stopped(path: str | None, *, reason: str) -> str:
    where = f" to {path}" if path else ""
    return f"Stopped proposing changes{where}: {reason}"


def format_write_policy_outcome(results: list[dict[str, Any]]) -> str:
    for result in results:
        if result.get("error"):
            hint = result.get("hint")
            msg = str(result["error"])
            if hint:
                msg += f" {hint}"
            return msg
    return "Write blocked by workspace policy."


def format_memorize_outcome(results: list[dict[str, Any]]) -> str:
    for result in results:
        if result.get("stored"):
            eid = result.get("id", "?")
            return f"Memorized ({result.get('chars', '?')} chars, id={eid})."
        if result.get("saved") and result.get("key"):
            return f"Remembered fact `{result['key']}`."
        if result.get("skipped"):
            return str(result.get("reason", "Memory write skipped."))
        if result.get("error"):
            return f"Could not save memory: {result['error']}"
    return "Memory stored."


def snapshots_from_results(results: list[dict[str, Any]]) -> dict[str, str]:
    snaps: dict[str, str] = {}
    for result in results:
        path = result.get("path")
        if path is None or result.get("content") is None:
            continue
        if "total_lines" not in result:
            continue
        snaps[str(path)] = str(result["content"])
    return snaps


def empty_files_from_results(results: list[dict[str, Any]]) -> set[str]:
    empty: set[str] = set()
    for result in results:
        path = result.get("path")
        if not path:
            continue
        lines = result.get("total_lines")
        if lines == 0 or result.get("content") == "":
            empty.add(str(path))
    return empty
