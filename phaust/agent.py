from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable

import requests

from phaust.memory import (
    Compactor,
    ContextMemory,
    LongTermMemory,
    MemoryStore,
    SemanticMemory,
)
from phaust.tool_parse import parse_text_tool_calls
from phaust.tools import Tools
from phaust.workspace import Workspace
from phaust.workspace_write import (
    WRITE_TOOL_NAMES,
    apply_proposal,
    print_proposal,
    prompt_apply,
)

MAX_SYNTHESIS_CHARS = 12_000

_WRITE_INTENT_RE = re.compile(
    r"\b(write|add|insert|append|edit|replace|overwrite|create|put|comment\s+in|update\s+the\s+file)\b",
    re.I,
)


@dataclass
class Agent:
    system_prompt: str = ""
    model: str = "qwen/qwen3.5-9b"
    base_url: str = "http://127.0.0.1:1234/v1"
    api_key: str = field(default="NO_API_KEY", repr=False)
    max_tool_rounds: int = 12
    max_write_proposals: int = 2
    semantic_top_k: int = 5
    max_messages: int = 50
    compact_batch: int = 10
    max_episodes: int = 500

    tools: Tools = field(default_factory=Tools)
    db: MemoryStore = field(default_factory=MemoryStore)
    context_memory: ContextMemory | None = None
    long_term: LongTermMemory | None = None
    semantic: SemanticMemory | None = None
    compactor: Compactor | None = None
    workspace: Workspace | None = None
    require_write_approval: bool = True

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")

        if self.context_memory is None:
            self.context_memory = ContextMemory(
                db=self.db,
                max_messages=self.max_messages,
                compact_batch=self.compact_batch,
            )
        if self.long_term is None:
            self.long_term = LongTermMemory(db=self.db)
        if self.semantic is None:
            self.semantic = SemanticMemory(
                db=self.db,
                max_episodes=self.max_episodes,
            )
        self.semantic.base_url = self.base_url
        self.semantic.api_key = self.api_key
        self.semantic.model = self.model

        if self.compactor is None:
            self.compactor = Compactor(
                base_url=self.base_url,
                api_key=self.api_key,
                model=self.model,
            )

        self._load_all()

    def _load_all(self) -> None:
        self.context_memory.load() # type: ignore

    def begin_session(self) -> None:
        self.context_memory.begin_session() # type: ignore

    def finalize_session(self) -> dict[str, Any] | None:
        if self.compactor is None:
            return None
        return self.context_memory.finalize_session( # type: ignore
            self.long_term, self.semantic, self.compactor # type: ignore
        )

    def _persist(self) -> None:
        result = self.context_memory.maybe_compact( # type: ignore
            self.long_term, self.semantic, self.compactor # type: ignore
        )
        if result and result.get("episode_saved"):
            print(
                f"Memory: compacted {result.get('compacted', 0)} messages "
                f"→ episode + {result.get('facts_saved', 0)} facts"
            )

    def tool(self, func: Callable[..., Any]) -> Callable[..., Any]:
        return self.tools.register(func)

    def context(self, func: Callable[[], str]) -> Callable[[], str]:
        return self.context_memory.register_provider(func.__name__, func) # type: ignore

    def _build_system_messages(
        self,
        user_message: str,
        *,
        empty_write_paths: set[str] | None = None,
        file_snapshots: dict[str, str] | None = None,
    ) -> list[dict[str, str]]:
        blocks = [self.system_prompt]

        context_block = self.context_memory.build_prompt_block() # type: ignore
        if context_block:
            blocks.append(context_block)

        long_term_block = self.long_term.summary_for_prompt() # type: ignore
        if long_term_block:
            blocks.append(long_term_block)

        file_change = self._user_requests_file_change(user_message)
        if not file_change:
            semantic_block = self.semantic.build_prompt_block( # type: ignore
                user_message, top_k=self.semantic_top_k
            )
            if semantic_block:
                blocks.append(semantic_block)

        if file_change:
            blocks.append(
                "<write_rules>\n"
                "For file edits, trust read_file on disk — not old chat or episodic memory. "
                "If the file is empty, write only what the user asked now (plain lines, "
                "no N| prefixes, do not continue numbering from earlier turns).\n"
                "</write_rules>"
            )

        if empty_write_paths:
            paths = ", ".join(sorted(empty_write_paths))
            blocks.append(
                f"<write_context>\n"
                f"Confirmed empty on disk: {paths}. "
                f"write_file must contain only the new lines the user requested.\n"
                f"</write_context>"
            )

        if file_snapshots:
            parts: list[str] = []
            for path in sorted(file_snapshots):
                parts.append(f"### {path}\n{file_snapshots[path]}")
            blocks.append(
                "<file_on_disk>\n"
                + "\n\n".join(parts)
                + "\n\nCopy this text exactly for edit_file old_string (no added prefixes).\n"
                "</file_on_disk>"
            )

        if self.context_memory and not self.context_memory.memory_writes_enabled(): # type: ignore
            blocks.append(
                "<session_memory_policy>\n"
                "Memory writes are OFF for this session. Do not call remember or memorize. "
                "On exit, nothing from this chat will be archived.\n"
                "</session_memory_policy>"
            )

        return [{"role": "system", "content": "\n\n".join(blocks)}]

    def _last_user_message(self) -> str:
        for msg in reversed(self.context_memory.messages): # type: ignore
            if msg.get("role") == "user":
                return str(msg.get("content") or "")
        return ""

    @staticmethod
    def _grounding_from_tool_results(results: list[dict[str, Any]]) -> str:
        parts: list[str] = []
        for result in results:
            if result.get("error"):
                continue
            if result.get("content") and result.get("path"):
                parts.append(
                    f"### FILE: {result['path']} ({result.get('total_lines', '?')} lines)\n"
                    f"{result['content']}"
                )
            elif result.get("matches"):
                lines = [
                    f"{m['file']}:{m['line']}: {m['text']}"
                    for m in result["matches"][:40]
                ]
                parts.append(
                    f"### GREP: {result.get('pattern', '')}\n" + "\n".join(lines)
                )
        return "\n\n".join(parts)

    @staticmethod
    def _clean_reply(text: str) -> str:
        """Strip Qwen chain-of-thought / thinking blocks from user-facing text."""
        text = text.strip()
        text = re.sub(
            r"<think(?:ing)?>[\s\S]*?</think(?:ing)?>",
            "",
            text,
            flags=re.IGNORECASE,
        ).strip()
        text = re.sub(
            r"<tool_call>[\s\S]*?</tool_call>",
            "",
            text,
            flags=re.IGNORECASE,
        ).strip()

        if "Thinking Process" not in text and not re.search(
            r"^\d+\.\s+\*\*Analyze", text, re.MULTILINE
        ):
            return text

        draft = re.search(
            r"\*Draft:\*\*\s*\n([\s\S]+?)(?:\n\d+\.\s+\*\*Review|\n\*\*Review against|$)",
            text,
        )
        if draft:
            body = draft.group(1).strip()
            body = re.sub(r"^\*?Draft:?\*?\s*", "", body)
            if len(body) > 80:
                return body

        paragraphs = [p.strip() for p in re.split(r"\n\n+", text) if len(p.strip()) > 100]
        for para in reversed(paragraphs):
            if re.match(r"^\d+\.", para):
                continue
            if any(
                skip in para[:60]
                for skip in ("Analyze the", "Constraint", "Drafting the", "**")
            ):
                continue
            return para
        return text

    @staticmethod
    def _message_text(msg: dict[str, Any]) -> str:
        """Prefer final content; avoid dumping raw reasoning traces to the user."""
        content = msg.get("content")
        if content and str(content).strip():
            return Agent._clean_reply(str(content))

        for key in ("reasoning_content", "reasoning"):
            val = msg.get(key)
            if val and str(val).strip():
                return Agent._clean_reply(str(val))
        return ""

    @staticmethod
    def _llm_extra() -> dict[str, Any]:
        return {"chat_template_kwargs": {"enable_thinking": False}}

    @staticmethod
    def _truncate_sources(sources: str, max_chars: int = MAX_SYNTHESIS_CHARS) -> str:
        if len(sources) <= max_chars:
            return sources
        return sources[:max_chars] + "\n… [truncated for context limit]"

    @staticmethod
    def _fallback_summary(sources: str) -> str:
        imports = re.findall(r"^from .+|^import .+", sources, re.MULTILINE)[:12]
        symbols = re.findall(r"^(?:class|def) \w+", sources, re.MULTILINE)[:25]
        lines = ["The model returned an empty reply. From the file read:"]
        if symbols:
            lines.append("Symbols: " + ", ".join(symbols))
        if imports:
            lines.append("Imports: " + "; ".join(imports))
        return "\n".join(lines)

    def _synthesize_from_sources(self, question: str, sources: str) -> str:
        """Second pass: answer only from file text (no tools — reduces hallucination)."""
        sources = self._truncate_sources(sources)
        messages = [
            {
                "role": "system",
                "content": (
                    "Answer the user's question about the code in 2–4 short paragraphs. "
                    "Use only names that appear in SOURCE. "
                    "Do not show planning, analysis, or numbered steps."
                ),
            },
            {
                "role": "user",
                "content": f"Question: {question}\n\n--- SOURCE ---\n{sources}\n--- END SOURCE ---",
            },
            # LM Studio / Qwen workaround: skip reasoning-only empty content
            {"role": "assistant", "content": " \n"},
        ]
        r = requests.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": messages,
                "temperature": 0.2,
                "max_tokens": 1024,
                "extra_body": self._llm_extra(),
            },
            timeout=300,
        )
        r.raise_for_status()
        answer = self._message_text(r.json()["choices"][0]["message"])
        if answer:
            return answer
        print("     ⚠ synthesis returned empty — using fallback summary")
        return self._fallback_summary(sources)

    @staticmethod
    def _sanitize_messages_for_api(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """LM Studio/Qwen reject prompts when a user turn has empty content."""
        cleaned: list[dict[str, Any]] = []
        for msg in messages:
            role = msg.get("role")
            if role == "user" and not str(msg.get("content") or "").strip():
                continue
            cleaned.append(msg)
        return cleaned

    def _api_messages(self, prefix: list[dict[str, str]]) -> list[dict[str, Any]]:
        return self._sanitize_messages_for_api(
            list(prefix) + list(self.context_memory.messages) # type: ignore
        )

    @staticmethod
    def _raise_for_llm_error(response: requests.Response) -> None:
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            detail = response.text.strip()
            if detail:
                raise requests.HTTPError(
                    f"{exc} — {detail[:800]}",
                    response=response,
                ) from exc
            raise

    @staticmethod
    def _user_requests_file_change(message: str) -> bool:
        return bool(_WRITE_INTENT_RE.search(message))

    @staticmethod
    def _round_includes_write_tools(tool_calls: list[dict[str, Any]]) -> bool:
        for call in tool_calls:
            name = call.get("function", {}).get("name")
            if name in WRITE_TOOL_NAMES:
                return True
        return False

    _WRITE_NUDGE = (
        "Apply the file change now using the edit_file or write_file tool "
        "(native function calling — not XML). "
        "For one line or a comment, use edit_file with a unique old_string. "
        "Place comments where the user asked (e.g. after the title block), not at the file end unless they said so."
    )

    @staticmethod
    def _paths_read_this_round(results: list[dict[str, Any]]) -> list[str]:
        paths: list[str] = []
        for result in results:
            path = result.get("path")
            if path and result.get("content") is not None:
                paths.append(str(path))
        return paths

    @staticmethod
    def _format_write_outcome(results: list[dict[str, Any]]) -> str:
        for result in results:
            if result.get("applied"):
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

    @staticmethod
    def _format_write_stopped(path: str | None, *, reason: str) -> str:
        where = f" to {path}" if path else ""
        return f"Stopped proposing changes{where}: {reason}"

    def _write_nudge_message(self, read_paths: list[str]) -> str:
        if read_paths:
            joined = ", ".join(read_paths)
            return f"{self._WRITE_NUDGE} File(s) already read: {joined}."
        return self._WRITE_NUDGE

    @staticmethod
    def _snapshots_from_results(results: list[dict[str, Any]]) -> dict[str, str]:
        snaps: dict[str, str] = {}
        for result in results:
            path = result.get("path")
            if path is None or result.get("content") is None:
                continue
            if "total_lines" not in result:
                continue
            snaps[str(path)] = str(result["content"])
        return snaps

    @staticmethod
    def _empty_files_from_results(results: list[dict[str, Any]]) -> set[str]:
        empty: set[str] = set()
        for result in results:
            path = result.get("path")
            if not path:
                continue
            lines = result.get("total_lines")
            if lines == 0 or result.get("content") == "":
                empty.add(str(path))
        return empty

    def chat(self, user_message: str) -> str:
        if self.context_memory.user_requests_no_memory(user_message): # type: ignore
            self.context_memory.set_memory_writes_disabled(True) # type: ignore
            print(
                "  ○ Memory writes disabled this session "
                "(remember/memorize blocked; exit will not archive)."
            )

        self.context_memory.append_message({"role": "user", "content": user_message}) # type: ignore

        tool_rounds = 0
        wants_edit = self._user_requests_file_change(user_message)
        write_applied = False
        write_declined = False
        write_proposals = 0
        write_nudges = 0
        read_paths: list[str] = []
        empty_write_paths: set[str] = set()
        file_snapshots: dict[str, str] = {}
        last_write_path: str | None = None

        while True:
            prefix = self._build_system_messages(
                user_message,
                empty_write_paths=empty_write_paths,
                file_snapshots=file_snapshots,
            )
            payload: dict[str, Any] = {
                "model": self.model,
                "messages": self._api_messages(prefix),
                "temperature": 0.3,
                "max_tokens": 8192,
                "extra_body": self._llm_extra(),
            }

            schemas = self.tools.get_schemas()
            if schemas:
                payload["tools"] = schemas

            r = requests.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=300,
            )
            self._raise_for_llm_error(r)
            msg = r.json()["choices"][0]["message"]
            tool_calls = list(msg.get("tool_calls") or [])
            if not tool_calls:
                parsed = parse_text_tool_calls(str(msg.get("content") or ""))
                if parsed:
                    tool_calls = parsed
                    print(
                        f"  → parsed {len(tool_calls)} tool call(s) from assistant text"
                    )

            self.context_memory.append_message( # type: ignore
                {
                    "role": "assistant",
                    "content": msg.get("content"),
                    "tool_calls": tool_calls or None,
                }
            )

            if not tool_calls:
                if (
                    wants_edit
                    and not write_applied
                    and not write_declined
                    and write_proposals < self.max_write_proposals
                    and write_nudges < 1
                ):
                    write_nudges += 1
                    print("  → write pending — nudging model to call edit_file/write_file…")
                    self.context_memory.append_message( # type: ignore
                        {"role": "user", "content": self._write_nudge_message(read_paths)}
                    )
                    self._persist()
                    continue
                self._persist()
                return self._message_text(msg) or (
                    "(no response from model — check LM Studio has a chat model loaded)"
                )

            tool_rounds += 1
            if tool_rounds > self.max_tool_rounds:
                self._persist()
                return "Stopped: too many tool-call rounds."

            round_results: list[dict[str, Any]] = []
            for call in tool_calls:
                fn = call.get("function", {})
                name = fn.get("name")
                if write_declined and name in WRITE_TOOL_NAMES:
                    continue
                if (
                    wants_edit
                    and not write_applied
                    and name in WRITE_TOOL_NAMES
                    and write_proposals >= self.max_write_proposals
                ):
                    continue
                print(f"  → {name}({fn.get('arguments', '')})")
                result = self._execute_tool_call(call)
                round_results.append(result)
                if name in WRITE_TOOL_NAMES:
                    last_write_path = str(result.get("path") or last_write_path or "")
                    if result.get("error") is None and not result.get("skipped"):
                        write_proposals += 1
                    if result.get("applied"):
                        write_applied = True
                    if result.get("cancelled"):
                        write_declined = True
                _print_tool_result(name, result)
                self.context_memory.append_message( # type: ignore
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id"),
                        "content": json.dumps(self._slim_tool_result(name, result)),
                    }
                )

            read_paths = self._paths_read_this_round(round_results) or read_paths
            empty_write_paths |= self._empty_files_from_results(round_results)
            file_snapshots.update(self._snapshots_from_results(round_results))

            if write_applied:
                reply = self._format_write_outcome(round_results)
                self.context_memory.append_message( # type: ignore
                    {"role": "assistant", "content": reply}
                )
                self._persist()
                return reply

            if write_declined:
                reply = self._format_write_outcome(round_results)
                self.context_memory.append_message( # type: ignore
                    {"role": "assistant", "content": reply}
                )
                self._persist()
                return reply

            if (
                wants_edit
                and write_proposals >= self.max_write_proposals
                and not write_applied
            ):
                reply = self._format_write_stopped(
                    last_write_path,
                    reason=(
                        f"max {self.max_write_proposals} write previews this turn "
                        "(approve one or ask again)."
                    ),
                )
                self.context_memory.append_message( # type: ignore
                    {"role": "assistant", "content": reply}
                )
                self._persist()
                return reply

            sources = self._grounding_from_tool_results(round_results)
            skip_synthesis = wants_edit or self._round_includes_write_tools(tool_calls)
            if sources and not skip_synthesis:
                print("  → synthesizing answer from file contents…")
                answer = self._synthesize_from_sources(
                    self._last_user_message(), sources
                )
                self.context_memory.append_message( # type: ignore
                    {"role": "assistant", "content": answer}
                )
                self._persist()
                return answer

            self._persist()

    def _execute_tool_call(self, tool_call: dict[str, Any]) -> dict[str, Any]:
        fn = tool_call.get("function", {})
        name = fn.get("name")
        result = self.tools.execute(tool_call)

        if name not in WRITE_TOOL_NAMES:
            return result

        if result.get("error"):
            print_proposal(result)
            return result

        print_proposal(result)

        if self.require_write_approval:
            if not prompt_apply():
                return {
                    "applied": False,
                    "cancelled": True,
                    "path": result.get("path"),
                    "message": "User declined. No changes were written to disk.",
                }

        if self.workspace is None:
            return {"error": "Workspace not configured on agent"}

        return apply_proposal(result, self.workspace)

    @staticmethod
    def _slim_tool_result(name: str | None, result: dict[str, Any]) -> dict[str, Any]:
        if name not in WRITE_TOOL_NAMES:
            return result
        return {
            k: v
            for k, v in result.items()
            if k not in ("before", "after", "diff")
        }


def _print_tool_result(name: str | None, result: dict[str, Any]) -> None:
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
    elif name == "list_files":
        print(f"     ✓ {result.get('count', 0)} path(s)")
    elif name in WRITE_TOOL_NAMES:
        if result.get("applied"):
            print(f"     ✓ written {result.get('path')} ({result.get('bytes', '?')} bytes)")
        elif result.get("cancelled"):
            print("     ○ cancelled (disk unchanged)")
        elif result.get("error"):
            print(f"     ✗ {result['error']}")


def run(agent: Agent) -> None:
    print("Phaust-1 ready. Memory: SQLite + auto-compaction")
    print("  context | long-term | semantic | workspace (writes need your approval)")
    print("Type 'exit' to quit.\n")

    agent.begin_session()

    while True:
        user = input("You: ").strip()
        if not user:
            continue
        if user.lower() in {"exit", "quit"}:
            if agent.context_memory and not agent.context_memory.memory_writes_enabled(): # type: ignore
                print("Ending session (memory writes were disabled — discarding transcript).")
            else:
                print("Saving session memory...")
            result = agent.finalize_session()
            if result:
                if result.get("memory_skipped"):
                    print(
                        f"  Discarded {result.get('compacted', 0)} messages "
                        "(no episode, no new facts)."
                    )
                else:
                    print(
                        f"  Session archived: {result.get('compacted', 0)} messages, "
                        f"{result.get('facts_saved', 0)} facts"
                    )
            break
        reply = agent.chat(user)
        print("Agent:", reply if reply else "(empty)")
