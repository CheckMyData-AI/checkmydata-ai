from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Message:
    role: str  # system | user | assistant | tool
    content: str
    tool_call_id: str | None = None
    name: str | None = None
    tool_calls: list["ToolCall"] | None = None


@dataclass
class ToolParameter:
    name: str
    type: str
    description: str
    required: bool = True
    enum: list[str] | None = None
    # For ``type == "array"`` this is the JSON-Schema ``items`` clause (required
    # by strict OpenAI function-calling); for ``type == "object"`` it holds the
    # nested ``properties`` map. Defaults are applied in ``_tools_to_schema``.
    items: dict[str, Any] | None = None


@dataclass
class Tool:
    name: str
    description: str
    parameters: list[ToolParameter] = field(default_factory=list)


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


# A tool spec may be a ``Tool`` dataclass or an already-formatted OpenAI
# function-schema ``dict`` (passed straight through by the adapters).
ToolSpec = Tool | dict[str, Any]


@dataclass
class LLMResponse:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    model: str = ""
    provider: str = ""
    finish_reason: str = ""


class BaseLLMProvider(ABC):
    @abstractmethod
    async def complete(
        self,
        messages: list[Message],
        tools: Sequence[ToolSpec] | None = None,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """Generate a completion."""

    @abstractmethod
    def stream(
        self,
        messages: list[Message],
        tools: Sequence[ToolSpec] | None = None,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        """Stream a completion token by token."""
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the provider identifier."""

    def _tools_to_schema(self, tools: Sequence[ToolSpec]) -> list[dict]:
        """Convert Tool dataclasses to the OpenAI-compatible function schema format.

        Callers may also pass an already-formatted OpenAI function-schema ``dict``
        (e.g. the planner's ``_CREATE_PLAN_TOOL``); such items pass through
        unchanged so a single tools list can mix dataclasses and raw schemas.
        """
        result = []
        for tool in tools:
            if isinstance(tool, dict):
                result.append(tool)
                continue
            properties = {}
            required = []
            for p in tool.parameters:
                prop: dict[str, Any] = {"type": p.type, "description": p.description}
                if p.enum:
                    prop["enum"] = p.enum
                if p.type == "array":
                    # OpenAI/strict function-calling rejects array params with no
                    # ``items``; default to a list of strings when unspecified.
                    prop["items"] = p.items or {"type": "string"}
                elif p.type == "object":
                    prop["properties"] = p.items or {}
                properties[p.name] = prop
                if p.required:
                    required.append(p.name)

            result.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": {
                            "type": "object",
                            "properties": properties,
                            "required": required,
                        },
                    },
                }
            )
        return result
