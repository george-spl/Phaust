import inspect
import json
from dataclasses import dataclass, field
from typing import Annotated, Any, Callable, Final, Union, get_args, get_origin


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
