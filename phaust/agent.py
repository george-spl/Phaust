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
from phaust.tools import Tools

MAX_SYNTHESIS_CHARS = 12_000


@dataclass
class Agent:
    system_prompt: str = ""
    model: str = "qwen/qwen3.5-9b"
    base_url: str = "http://127.0.0.1:1234/v1"
    api_key: str = field(default="NO_API_KEY", repr=False)
    max_tool_rounds: int = 12
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

    def _build_system_messages(self, user_message: str) -> list[dict[str, str]]:
        blocks = [self.system_prompt]

        context_block = self.context_memory.build_prompt_block() # type: ignore
        if context_block:
            blocks.append(context_block)

        long_term_block = self.long_term.summary_for_prompt() # type: ignore
        if long_term_block:
            blocks.append(long_term_block)

        semantic_block = self.semantic.build_prompt_block( # type: ignore
            user_message, top_k=self.semantic_top_k
        )
        if semantic_block:
            blocks.append(semantic_block)

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

    def _api_messages(self, prefix: list[dict[str, str]]) -> list[dict[str, Any]]:
        return list(prefix) + list(self.context_memory.messages) # type: ignore

    def chat(self, user_message: str) -> str:
        self.context_memory.append_message({"role": "user", "content": user_message}) # type: ignore

        prefix = self._build_system_messages(user_message)
        tool_rounds = 0

        while True:
            payload: dict[str, Any] = {
                "model": self.model,
                "messages": self._api_messages(prefix),
                "temperature": 0.3,
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
            r.raise_for_status()
            msg = r.json()["choices"][0]["message"]
            tool_calls = msg.get("tool_calls") or []

            self.context_memory.append_message( # type: ignore
                {
                    "role": "assistant",
                    "content": msg.get("content"),
                    "tool_calls": tool_calls,
                }
            )

            if not tool_calls:
                self._persist()
                return self._message_text(msg) or "(no response from model)"

            tool_rounds += 1
            if tool_rounds > self.max_tool_rounds:
                self._persist()
                return "Stopped: too many tool-call rounds."

            round_results: list[dict[str, Any]] = []
            for call in tool_calls:
                fn = call.get("function", {})
                print(f"  → {fn.get('name', '?')}({fn.get('arguments', '')})")
                result = self.tools.execute(call)
                round_results.append(result)
                _print_tool_result(fn.get("name"), result)
                self.context_memory.append_message( # type: ignore
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id"),
                        "content": json.dumps(result),
                    }
                )

            sources = self._grounding_from_tool_results(round_results)
            if sources:
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


def _print_tool_result(name: str | None, result: dict[str, Any]) -> None:
    if result.get("error"):
        print(f"     ✗ {result['error']}")
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


def run(agent: Agent) -> None:
    print("Phaust-1 ready. Memory: SQLite + auto-compaction")
    print("  context | long-term | semantic | read-only workspace tools")
    print("Type 'exit' to quit.\n")

    agent.begin_session()

    while True:
        user = input("You: ")
        if user.lower() in {"exit", "quit"}:
            print("Saving session memory...")
            result = agent.finalize_session()
            if result:
                print(
                    f"  Session archived: {result.get('compacted', 0)} messages, "
                    f"{result.get('facts_saved', 0)} facts"
                )
            break
        reply = agent.chat(user)
        print("Agent:", reply if reply else "(empty)")
