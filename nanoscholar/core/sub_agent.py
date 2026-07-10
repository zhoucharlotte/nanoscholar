"""Sub-agent 鈥?isolated agent loop with tool whitelist, runs inside the MCP server process."""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

from openai import OpenAI

from nanoscholar.config import load_config
from nanoscholar.tools.tool import get_tool, list_tools
import nanoscholar._runtime as runtime

logger = logging.getLogger("nanoscholar.sub_agent")

_ROLE_SYSTEM_PROMPTS: dict[str, str] = {
    "general": (
        "You are a sub-agent. Execute the task using the available tools. "
        "When done, provide a clear summary."
    ),
    "planner": (
        "You are the Planner agent. Break the user's goal into a concise, "
        "ordered plan. Identify what needs to be investigated, what evidence "
        "is needed, and what done criteria should be used. Do not modify files."
    ),
    "researcher": (
        "You are the Researcher agent. Gather evidence, inspect relevant files "
        "or sources, and report concrete findings with paths, commands, and "
        "observations. Do not modify files."
    ),
}


def _build_schema(tool_names: list[str] | None) -> list[dict]:
    """Build filtered tool schema from the local registry."""
    all_tools = list_tools()
    if tool_names is not None:
        available = [t for t in all_tools if t.name in tool_names]
    else:
        available = all_tools
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.input_schema,
            },
        }
        for t in available
    ]


def run_sub_agent(
    prompt: str,
    tool_names: list[str] | None = None,
    max_iterations: int = 10,
    role: str = "general",
) -> str:
    """Execute a prompt in an isolated sub-agent with optional tool whitelist."""
    role = role.lower().strip() or "general"
    role_prompt = _ROLE_SYSTEM_PROMPTS.get(role, _ROLE_SYSTEM_PROMPTS["general"])
    logger.info("sub_agent start (role=%s, prompt=%.60s..., tools=%s)", role, prompt, tool_names)

    # Load config from environment (set by main.py)
    cfg_path = os.environ.get("NANOSCHOLAR_CONFIG_PATH", "configs/config.yaml")
    cfg = load_config(cfg_path)
    runtime.WORKSPACE_ROOT = Path(cfg.workspace.path).resolve()
    runtime.WORKSPACE_RESTRICT = cfg.workspace.restrict
    runtime.DB_PATH = runtime.WORKSPACE_ROOT / cfg.db_name
    runtime.TG_TOKEN = cfg.telegram.token

    client = OpenAI(base_url=cfg.llm.base_url, api_key=cfg.llm.api_key, timeout=30.0)
    schema = _build_schema(tool_names)

    messages: list[dict] = [
        {
            "role": "system",
            "content": (
                f"{role_prompt}\n\n"
                f"Task:\n{prompt}\n\n"
                "Respond with a compact, structured result."
            ),
        },
    ]

    _start_time = time.time()
    _time_limit = 120.0  # max 2 minutes total
    for _ in range(max_iterations):
        if time.time() - _start_time > _time_limit:
            return f"[Sub-agent timed out after {_time_limit}s]"
        try:
            res = client.chat.completions.create(
                model=cfg.llm.model,
                messages=messages,
                tools=schema or None,
                tool_choice="auto" if schema else None,
            )
        except Exception as e:
            return f"[Sub-agent LLM error: {e}]"

        sys.stderr.write(f"[sub_agent] LLM response: tool_calls={len(res.choices[0].message.tool_calls or [])}\n")
        msg = res.choices[0].message
        msg_dict = {"role": msg.role}
        if msg.tool_calls and not msg.content:
            msg_dict["content"] = None
        elif msg.content:
            msg_dict["content"] = msg.content
        if msg.tool_calls:
            msg_dict["tool_calls"] = [
                {
                    "id": getattr(tc, "id", None),
                    "type": getattr(tc, "type", "function"),
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]
        messages.append(msg_dict)

        if not msg.tool_calls:
            return msg.content or "[Sub-agent returned empty]"

        for tc in msg.tool_calls:
            fn = getattr(tc, "function", tc)
            name = (
                fn.get("name") if isinstance(fn, dict) else getattr(fn, "name", None)
            ) or "error"
            raw = (
                fn.get("arguments")
                if isinstance(fn, dict)
                else getattr(fn, "arguments", None)
            )
            args = raw if isinstance(raw, dict) else (json.loads(raw) if raw else {})

            sys.stderr.write(f"[sub_agent] calling tool: {name}\n")
            logger.info("Sub-agent calling tool: %s", name)
            tool = get_tool(name)
            if tool and tool.handler:
                try:
                    result = tool.handler(**args)
                except Exception as e:
                    result = f"[Tool error: {e}]"
            else:
                result = f"[Tool {name} not available]"

            messages.append({
                "role": "tool",
                "tool_call_id": getattr(tc, "id", None),
                "name": name,
                "content": str(result),
            })

    return "[Sub-agent reached max iterations without final answer]"


