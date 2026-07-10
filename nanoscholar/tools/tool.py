"""Tool dataclass and registry — shared by server (with handler) and client (schema only)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

_registry: dict[str, "Tool"] = {}


@dataclass
class Tool:
    """MCP-style tool definition.

    Server side: handler is set, category + approval_required drive permission checks.
    Client side: handler is None (tool executed via MCP protocol).
    """
    name: str
    description: str
    input_schema: dict
    handler: Callable | None = None
    category: str = "general"
    approval_required: bool = True


# ── Registry API ──────────────────────────────────────────────

def register(tool: Tool):
    _registry[tool.name] = tool


def get_tool(name: str) -> Tool | None:
    return _registry.get(name)


def list_tools() -> list[Tool]:
    return list(_registry.values())


def build_tools_schema() -> list[dict]:
    """Build an OpenAI-compatible tools schema list from the registry."""
    result = []
    for t in _registry.values():
        result.append({
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.input_schema,
            },
        })
    return result
