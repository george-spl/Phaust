import requests
import inspect
import json
from typing import Annotated, get_origin, get_args, Any, Callable, Union, Final
from dataclasses import dataclass, field
from pathlib import Path


# ─────────────────────────────────────────────
# 🧰 TOOLS SYSTEM
# ─────────────────────────────────────────────

@dataclass
class Tools:
    TOOL_SCHEMA_ATTR: Final[str] = "__tool_schema__"
    tools: dict[str, Callable[..., Any]] = field(default_factory=dict)

    @staticmethod
    def _annotation_to_schema(annotation: Any) -> dict[str, Any]:
        schema: dict[str, Any] = {"type": "string"}
        description: str | None = None
        origin = get_origin(annotation)

        if origin is Annotated:
            base, *meta = get_args(annotation)
            schema = Tools._annotation_to_schema(base)
            if meta:
                description = str(meta[0])

        elif annotation in (int, float):
            schema = {"type": "number"}
        elif annotation is bool:
            schema = {"type": "boolean"}
        elif annotation is str:
            schema = {"type": "string"}
        elif annotation is dict:
            schema = {"type": "object"}
        elif annotation is list:
            schema = {"type": "array"}

        elif origin is list:
            schema = {
                "type": "array",
                "items": Tools._annotation_to_schema(get_args(annotation)[0]),
            }

        elif origin is dict:
            schema = {"type": "object"}

        elif origin is Union:
            options = [
                Tools._annotation_to_schema(a)
                for a in get_args(annotation)
                if a is not type(None)
            ]
            if options:
                schema = options[0]

        if description:
            schema["description"] = description

        return schema

    @classmethod
    def schema_for_callable(cls, func: Callable[..., Any]) -> dict[str, Any]:
        sig = inspect.signature(func)
        annotations = inspect.get_annotations(func)

        parameters = {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        }

        for name, param in sig.parameters.items():
            annotation = annotations.get(name, inspect.Parameter.empty)
            if annotation is inspect.Parameter.empty:
                continue

            parameters["properties"][name] = cls._annotation_to_schema(annotation)

            if param.default is param.empty:
                parameters["required"].append(name)

        return {
            "type": "function",
            "function": {
                "name": func.__name__,
                "description": func.__doc__ or "No description provided.",
                "parameters": parameters,
                "strict": True,
            },
        }

    def register(self, func: Callable[..., Any]) -> Callable[..., Any]:
        if getattr(func, self.TOOL_SCHEMA_ATTR, None) is None:
            setattr(func, self.TOOL_SCHEMA_ATTR, self.schema_for_callable(func))
        self.tools[func.__name__] = func
        return func

    def get_schemas(self) -> list[dict[str, Any]]:
        return [
            getattr(fn, self.TOOL_SCHEMA_ATTR)
            for fn in self.tools.values()
            if getattr(fn, self.TOOL_SCHEMA_ATTR, None)
        ]

    def execute(self, tool_call: dict[str, Any]) -> dict[str, Any]:
        fn = tool_call.get("function", {})
        name = fn.get("name")
        args_raw = fn.get("arguments") or "{}"

        if name not in self.tools:
            return {"error": f"Tool '{name}' not found"}

        try:
            args = json.loads(args_raw)
            result = self.tools[name](**args)
            return result if isinstance(result, dict) else {"result": result}

        except Exception as e:
            return {"error": str(e)}


# ─────────────────────────────────────────────
# 🧠 AGENT CORE
# ─────────────────────────────────────────────

@dataclass
class Agent:
    system_prompt: str = "You are a helpful assistant."
    model: str = "qwen/qwen3.5-9b"
    base_url: str = "http://127.0.0.1:1234/v1"
    api_key: str = field(default="NO_API_KEY", repr=False)

    tools: Tools = field(default_factory=Tools)
    contexts: dict[str, Callable[[], str]] = field(default_factory=dict)

    messages: list[dict[str, Any]] = field(default_factory=list)
    memory: dict[str, Any] = field(default_factory=dict)

    memory_file: Path = Path(r"D:\GitHub\Phaust-1\Memory\memory.json")

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        self.load_memory()

    # ─── decorators ─────────────────────────

    def tool(self, func: Callable[..., Any]) -> Callable[..., Any]:
        return self.tools.register(func)

    def context(self, func: Callable[[], str]) -> Callable[[], str]:
        self.contexts[func.__name__] = func
        return func

    # ─── MEMORY FIX (IMPORTANT) ─────────────────────────

    def load_memory(self) -> None:
        if not self.memory_file.exists():
            return

        try:
            with open(self.memory_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.messages = data.get("messages", [])
            self.memory = data.get("memory", {})

        except Exception as e:
            print(f"Memory load failed: {e}")

    def save_memory(self) -> None:
        try:
            self.memory_file.parent.mkdir(parents=True, exist_ok=True)

            data = {
                "messages": self.messages[-50:],
                "memory": self.memory,
            }

            with open(self.memory_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

        except Exception as e:
            print(f"Memory save failed: {e}")

    # ─── CHAT ─────────────────────────

    def chat(self, user_message: str) -> str:
        self.messages.append({"role": "user", "content": user_message})

        context_block = "\n\n".join(
            f"<context>\n<{n}>{fn()}</{n}>\n</context>"
            for n, fn in self.contexts.items()
        )

        prefix = [
            {"role": "system", "content": self.system_prompt},
            {"role": "system", "content": context_block},
        ]

        while True:
            payload = {
                "model": self.model,
                "messages": prefix + self.messages,
            }

            tools = self.tools.get_schemas()
            if tools:
                payload["tools"] = tools

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

            self.messages.append({
                "role": "assistant",
                "content": msg.get("content"),
                "tool_calls": tool_calls,
            })

            if not tool_calls:
                self.save_memory()
                return msg.get("content") or ""

            for call in tool_calls:
                result = self.tools.execute(call)

                self.messages.append({
                    "role": "tool",
                    "tool_call_id": call.get("id"),
                    "content": json.dumps(result),
                })

            self.save_memory()


# ─────────────────────────────────────────────
# 🎮 RUN LOOP
# ─────────────────────────────────────────────

def run(agent: Agent):
    print("Agent ready. Type 'exit' to quit.")

    while True:
        user = input("You: ")

        if user.lower() in {"exit", "quit"}:
            break

        print("Agent:", agent.chat(user))


# ─────────────────────────────────────────────
# 🚀 MAIN
# ─────────────────────────────────────────────

if __name__ == "__main__":

    import datetime

    agent = Agent()

    @agent.context
    def time_context():
        return datetime.datetime.now().isoformat()

    @agent.tool
    def remember(key: str, value: str) -> dict:
        agent.memory[key] = value
        agent.save_memory()
        return {"saved": True}

    @agent.tool
    def recall(key: str) -> dict:
        return {"key": key, "value": agent.memory.get(key)}

    @agent.tool
    def forget(key: str) -> dict:
        agent.memory.pop(key, None)
        agent.save_memory()
        return {"deleted": key}

    @agent.tool
    def add(a: int, b: int) -> dict:
        return {"result": a + b}

    @agent.tool
    def multiply(a: int, b: int) -> dict:
        return {"result": a * b}

    run(agent)
