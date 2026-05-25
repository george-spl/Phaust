from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from phaust.config import SynthesisConfig
from phaust.memory import (
    Compactor,
    ContextMemory,
    LongTermMemory,
    MemoryStore,
    SemanticMemory,
)
from phaust.shell import ShellConfig
from phaust.tools import Tools
from phaust.workspace import Workspace
from phaust.tasks import TaskManager
from phaust.turn_loop import run_chat_turn


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
    config_name: str = "Phaust-2"
    agents_md_path: Path | None = None
    task_manager: TaskManager | None = None
    synthesis: SynthesisConfig = field(default_factory=SynthesisConfig)

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
        self.context_memory.load()  # type: ignore

    def begin_session(self) -> None:
        self.context_memory.begin_session()  # type: ignore

    def finalize_session(self) -> dict[str, Any] | None:
        if self.compactor is None:
            return None
        return self.context_memory.finalize_session(  # type: ignore
            self.long_term, self.semantic, self.compactor  # type: ignore
        )

    def _persist(self) -> None:
        result = self.context_memory.maybe_compact(  # type: ignore
            self.long_term, self.semantic, self.compactor  # type: ignore
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
        return self.context_memory.register_provider(func.__name__, func)  # type: ignore

    def chat(self, user_message: str) -> str:
        return run_chat_turn(self, user_message)
