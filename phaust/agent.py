from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
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
from phaust.shell import (
    SHELL_TOOL_NAMES,
    ShellConfig,
    execute_command,
    format_command_output,
    print_command_proposal,
    print_command_result,
    prompt_run,
)
from phaust.workspace_write import (
    WRITE_TOOL_NAMES,
    apply_proposal,
    print_proposal,
    prompt_apply,
)

MAX_SYNTHESIS_CHARS = 12_000

_WRITE_INTENT_RE = re.compile(
    r"\b(write|add|insert|append|edit|replace|overwrite|create|make|put|delete|remove|clear|empty|"
    r"comment\s+in|update\s+the\s+file|new\s+file)\b",
    re.I,
)
_APPEND_INTENT_RE = re.compile(
    r"\b(?:more|another|additional|\d+\s+more)\s+lines?\b|\bappend\b",
    re.I,
)
_MEMORY_RECALL_RE = re.compile(
    r"\b(?:do you remember|don'?t you remember|you don'?t remember"
    r"|recall\s+episode|what did we (?:say|discuss|talk about)"
    r"|something we discussed|discussed earlier|previous(?:ly)?\s+(?:session|conversation)"
    r"|sent .* message|message to cursor|earlier today)\b",
    re.I,
)
_MEMORIZE_INTENT_RE = re.compile(
    r"^\s*memorize\b|\bmemorize\s*:|\bremember\s+that\b"
    r"|\b(?:please|make sure to)\s+remember\s+(?:this|that)\b",
    re.I,
)
MEMORY_STORE_TOOL_NAMES = frozenset({"memorize", "remember"})


@dataclass
class Agent:
    system_prompt: str = ""
    model: str = "qwen/qwen3.5-9b"
    base_url: str = "http://127.0.0.1:1234/v1"
    api_key: str = field(default="NO_API_KEY", repr=False)
    temperature: float = 0.3
    max_tokens: int = 8192
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
    shell_config: ShellConfig = field(default_factory=ShellConfig)
    config_path: Path | None = None
    config_name: str = "Phaust-1"
    agents_md_path: Path | None = None
    _files_read_this_turn: set[str] = field(default_factory=set, repr=False)

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
            eid = result.get("episode_id")
            id_note = f" id={eid}" if eid else ""
            print(
                f"Memory: compacted {result.get('compacted', 0)} messages "
                f"→ episode{id_note} + {result.get('facts_saved', 0)} facts"
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
        memory_question = self._user_asks_about_past(user_message)

        if memory_question:
            recall_block = self.semantic.build_recall_block( # type: ignore
                user_message, top_k=max(self.semantic_top_k, 8)
            )
            if recall_block:
                blocks.append(recall_block)
        elif not file_change:
            semantic_block = self.semantic.build_prompt_block( # type: ignore
                user_message, top_k=self.semantic_top_k
            )
            if semantic_block:
                blocks.append(semantic_block)

        if memory_question:
            blocks.append(
                "<memory_rules>\n"
                "User is asking about past conversations. Check <memory_recall> and use "
                "recall_episode, list_episodes, or search_semantic before saying you have "
                "no record. Episodes are summaries — if a detail is missing, say the "
                "episode mentions X but not Y; do not invent.\n"
                "</memory_rules>"
            )

        if self._user_requests_memorize(user_message):
            text = self._memorize_text_from_message(user_message)
            blocks.append(
                "<memory_store_request>\n"
                "User asked to store something now. Call memorize (for notes/snippets) or "
                "remember (for key-value facts) — native function call, not text only.\n"
                + (f"Suggested text for memorize: {text}\n" if text else "")
                + "</memory_store_request>"
            )

        if file_change:
            blocks.append(
                "<write_rules>\n"
                "For file edits, trust read_file on disk — not old chat or episodic memory. "
                "To create a NEW file: create_file (no read_file needed). "
                "To change an EXISTING file: read_file first, then edit_file or write_file. "
                "To delete a file: delete_file (after read_file). "
                "To clear contents only: write_file with empty content or edit_file.\n"
                "If the file is empty, write only what the user asked now (plain lines, "
                "no N| prefixes, do not continue numbering from earlier turns).\n"
                "</write_rules>"
            )

        if empty_write_paths:
            paths = ", ".join(sorted(empty_write_paths))
            empty_msg = (
                f"Confirmed empty on disk: {paths}. "
                f"write_file must contain only the new lines the user requested."
            )
            if self._user_requests_append(user_message):
                empty_msg = (
                    f"Confirmed empty on disk: {paths}. "
                    f"User asked for MORE lines but the file has 0 lines — use write_file "
                    f"with fresh lines starting at 1 (or plain unnumbered lines). "
                    f"Ignore any prior chat claiming earlier lines exist."
                )
            blocks.append(f"<write_context>\n{empty_msg}\n</write_context>")

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
                "On exit, nothing from this chat will be archived. "
                "If the user asks to re-enable memory, they can say 'enable remembering' or "
                "'save this session'.\n"
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
    def _user_requests_append(message: str) -> bool:
        return bool(_APPEND_INTENT_RE.search(message))

    def _normalize_rel_path(self, path: str) -> str:
        if not path.strip() or self.workspace is None:
            return path.strip()
        try:
            return self.workspace.resolve(path).relative_to(self.workspace.root).as_posix()
        except (PermissionError, ValueError):
            return path.strip().replace("\\", "/").lstrip("/")

    def _path_is_existing_file(self, rel_path: str) -> bool:
        if not self.workspace or not rel_path:
            return False
        try:
            return self.workspace.resolve(rel_path).is_file()
        except PermissionError:
            return False

    def _write_requires_read_first(self, tool_name: str | None, rel_path: str) -> bool:
        """New files can be created without read_file; edits/deletes need a fresh read."""
        if not rel_path or rel_path in self._files_read_this_turn:
            return False
        if tool_name == "create_file":
            return False
        if tool_name == "write_file" and not self._path_is_existing_file(rel_path):
            return False
        return True

    @staticmethod
    def _round_includes_write_tools(tool_calls: list[dict[str, Any]]) -> bool:
        for call in tool_calls:
            name = call.get("function", {}).get("name")
            if name in WRITE_TOOL_NAMES:
                return True
        return False

    @staticmethod
    def _round_includes_shell_tools(tool_calls: list[dict[str, Any]]) -> bool:
        for call in tool_calls:
            name = call.get("function", {}).get("name")
            if name in SHELL_TOOL_NAMES:
                return True
        return False

    _WRITE_NUDGE = (
        "Apply the file change now using create_file, write_file, edit_file, or delete_file "
        "(native function calling — not XML). "
        "For a NEW file use create_file (no read_file needed). "
        "For an EXISTING file use read_file first, then edit_file or write_file."
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

    @staticmethod
    def _format_command_outcome(results: list[dict[str, Any]]) -> str:
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
                return f"Command failed: {result['error']}"
        return "Command proposal reviewed."

    @staticmethod
    def _format_write_stopped(path: str | None, *, reason: str) -> str:
        where = f" to {path}" if path else ""
        return f"Stopped proposing changes{where}: {reason}"

    def _write_nudge_message(self, read_paths: list[str], *, create_ok: bool = False) -> str:
        if create_ok and not read_paths:
            return (
                "Call create_file for a new file (no read_file needed), "
                "or read_file then edit_file/write_file for an existing file."
            )
        if not read_paths:
            return (
                "Call read_file on the target path first. "
                "Then use write_file or edit_file with exact on-disk text — not old chat."
            )
        joined = ", ".join(read_paths)
        return f"{self._WRITE_NUDGE} File(s) already read: {joined}."

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

    @staticmethod
    def _user_requests_create(message: str) -> bool:
        return bool(
            re.search(
                r"\b(create|make|new)\b.*\b(file|\.txt|\.md|\.py)\b|\bcreate\s+a\s+file\b",
                message,
                re.I,
            )
        )

    @staticmethod
    def _user_asks_about_past(message: str) -> bool:
        return bool(_MEMORY_RECALL_RE.search(message))

    @staticmethod
    def _user_requests_memorize(message: str) -> bool:
        if _MEMORY_RECALL_RE.search(message) and not re.search(
            r"\bmemorize\b", message, re.I
        ):
            return False
        return bool(_MEMORIZE_INTENT_RE.search(message))

    @staticmethod
    def _memorize_text_from_message(message: str) -> str | None:
        for pattern in (
            r"^\s*memorize\s*:\s*(.+)",
            r"^\s*memorize\s+(.+)",
            r"\bremember\s+that\s+(.+)",
        ):
            match = re.search(pattern, message, re.I | re.S)
            if match:
                text = match.group(1).strip()
                if text:
                    return text
        return None

    _MEMORIZE_NUDGE = (
        "Call memorize or remember now (native function call — not text only). "
        "For a note/snippet use memorize(text=...). For one fact use remember(key=..., value=...)."
    )

    def _memorize_nudge_message(self, user_message: str) -> str:
        text = self._memorize_text_from_message(user_message)
        if text:
            return f"{self._MEMORIZE_NUDGE}\nText to store:\n{text}"
        return f"{self._MEMORIZE_NUDGE}\nUse the user's message as the memorize text."

    @staticmethod
    def _format_memorize_outcome(results: list[dict[str, Any]]) -> str:
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

    def chat(self, user_message: str) -> str:
        if self.context_memory.user_requests_memory_again(user_message): # type: ignore
            if not self.context_memory.memory_writes_enabled(): # type: ignore
                self.context_memory.set_memory_writes_disabled(False) # type: ignore
                print("  ○ Memory writes re-enabled for this session (will archive on exit).")
        elif self.context_memory.user_requests_no_memory(user_message): # type: ignore
            self.context_memory.set_memory_writes_disabled(True) # type: ignore
            print(
                "  ○ Memory writes disabled this session "
                "(remember/memorize blocked; exit will not archive)."
            )

        self.context_memory.append_message({"role": "user", "content": user_message}) # type: ignore

        self._files_read_this_turn = set()
        tool_rounds = 0
        wants_edit = self._user_requests_file_change(user_message)
        wants_create = self._user_requests_create(user_message)
        wants_memorize = self._user_requests_memorize(user_message)
        if wants_memorize and not self.context_memory.memory_writes_enabled(): # type: ignore
            reply = (
                "Memory writes are disabled this session. "
                "Say 'enable remembering' if you want to memorize that."
            )
            self.context_memory.append_message( # type: ignore
                {"role": "assistant", "content": reply}
            )
            self._persist()
            return reply

        write_applied = False
        write_declined = False
        command_applied = False
        command_declined = False
        memory_stored = False
        write_proposals = 0
        write_nudges = 0
        memorize_nudges = 0
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
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
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
                    wants_memorize
                    and not memory_stored
                    and memorize_nudges < 1
                ):
                    memorize_nudges += 1
                    print("  → memorize pending — nudging model…")
                    self.context_memory.append_message( # type: ignore
                        {
                            "role": "user",
                            "content": self._memorize_nudge_message(user_message),
                        }
                    )
                    self._persist()
                    continue
                if (
                    wants_edit
                    and not write_applied
                    and not write_declined
                    and write_proposals < self.max_write_proposals
                    and write_nudges < 1
                ):
                    write_nudges += 1
                    label = (
                        "read_file first, then write…"
                        if not read_paths
                        else "write pending — nudging model…"
                    )
                    print(f"  → {label}")
                    self.context_memory.append_message( # type: ignore
                        {
                            "role": "user",
                            "content": self._write_nudge_message(
                                read_paths, create_ok=wants_create
                            ),
                        }
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
                if command_declined and name in SHELL_TOOL_NAMES:
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
                if name == "read_file" and not result.get("error"):
                    rel = str(result.get("path") or "")
                    if rel:
                        self._files_read_this_turn.add(rel)
                if name in WRITE_TOOL_NAMES:
                    last_write_path = str(result.get("path") or last_write_path or "")
                    if result.get("error") is None and not result.get("skipped"):
                        write_proposals += 1
                    if result.get("applied"):
                        write_applied = True
                    if result.get("cancelled"):
                        write_declined = True
                if name in SHELL_TOOL_NAMES:
                    if result.get("executed"):
                        command_applied = True
                    if result.get("cancelled"):
                        command_declined = True
                if name == "memorize" and result.get("stored"):
                    memory_stored = True
                if name == "remember" and result.get("saved"):
                    memory_stored = True
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

            if memory_stored:
                reply = self._format_memorize_outcome(round_results)
                self.context_memory.append_message( # type: ignore
                    {"role": "assistant", "content": reply}
                )
                self._persist()
                return reply

            if command_applied:
                reply = self._format_command_outcome(round_results)
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

            if command_declined:
                reply = self._format_command_outcome(round_results)
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
            skip_synthesis = (
                wants_edit
                or self._round_includes_write_tools(tool_calls)
                or self._round_includes_shell_tools(tool_calls)
            )
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

        if name in WRITE_TOOL_NAMES:
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            rel = self._normalize_rel_path(str(args.get("path", "")))
            if self._write_requires_read_first(name, rel):
                return {
                    "error": "Call read_file on this path before edit_file/delete_file",
                    "path": rel,
                    "hint": (
                        "For a NEW file use create_file (no read needed). "
                        "Prior chat about file contents may be stale."
                    ),
                }

        result = self.tools.execute(tool_call)

        if name in SHELL_TOOL_NAMES:
            if result.get("error"):
                print_command_proposal(result)
                return result

            print_command_proposal(result)

            if self.shell_config.require_approval:
                if not prompt_run():
                    return {
                        "cancelled": True,
                        "command": result.get("command"),
                        "cwd": result.get("cwd"),
                        "message": "User declined. Command was not run.",
                    }

            return execute_command(result, self.shell_config)

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
        if name in WRITE_TOOL_NAMES:
            return {
                k: v
                for k, v in result.items()
                if k not in ("before", "after", "diff")
            }
        if name in SHELL_TOOL_NAMES:
            return {
                k: v
                for k, v in result.items()
                if k not in ("args", "cwd_abs", "matched_allow")
            }
        return result


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
    elif name in WRITE_TOOL_NAMES:
        if result.get("applied") and result.get("deleted"):
            print(f"     ✓ deleted {result.get('path')}")
        elif result.get("applied"):
            print(f"     ✓ written {result.get('path')} ({result.get('bytes', '?')} bytes)")
        elif result.get("cancelled"):
            print("     ○ cancelled (disk unchanged)")
        elif result.get("error"):
            print(f"     ✗ {result['error']}")


def run(agent: Agent) -> None:
    name = agent.config_name
    config_path = agent.config_path
    agents_path = agent.agents_md_path
    if config_path:
        print(f"{name} ready (config: {config_path})")
    else:
        print(f"{name} ready (defaults — no phaust.toml found)")
    if agents_path:
        print(f"  rules: {agents_path}")
    else:
        print("  rules: built-in fallback (no AGENTS.md)")
    print("Memory: SQLite + auto-compaction")
    extras = ["writes need approval"]
    if agent.shell_config.enabled:
        extras.append("shell allowlist (run_command needs approval)")
    print(f"  context | long-term | semantic | workspace ({'; '.join(extras)})")
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
                    eid = result.get("episode_id")
                    id_note = f", episode id={eid}" if eid else ""
                    print(
                        f"  Session archived: {result.get('compacted', 0)} messages, "
                        f"{result.get('facts_saved', 0)} facts{id_note}"
                    )
            break
        reply = agent.chat(user)
        print("Agent:", reply if reply else "(empty)")
