"""Core agent loop 鈥?run_agent orchestrates tool-calling iterations."""

import asyncio
import json
import logging
import re
from typing import Any

from openai import OpenAI

from nanoscholar.config import AppConfig
from nanoscholar.core.context import _chats, ensure_chat
from nanoscholar.core.context import trim_context
from nanoscholar.db import save_memory, search_memory
import nanoscholar._runtime as _rt
from nanoscholar.core.permission import Decision
from nanoscholar.tools.router import build_schema

logger = logging.getLogger("nanoscholar")


_TEAM_EXPLICIT_KEYWORDS = [
    "run_agent_team",
    "agent team",
    "planner",
    "researcher",
    "\u56e2\u961f",
    "agent\u56e2\u961f",
]

_TEAM_COMPLEX_ACTIONS = [
    "\u5206\u6790",
    "\u68c0\u67e5",
    "\u6392\u67e5",
    "\u8c03\u8bd5",
    "\u7814\u7a76",
    "review",
    "debug",
    "inspect",
    "analyze",
    "investigate",
]

_TEAM_COMPLEX_OBJECTS = [
    "\u9879\u76ee",
    "\u4ee3\u7801",
    "\u4ee3\u7801\u5e93",
    "\u4ed3\u5e93",
    "\u67b6\u6784",
    "\u542f\u52a8",
    "\u5de5\u5177",
    "mcp",
    "agent",
    "bug",
    "\u95ee\u9898",
    "\u98ce\u9669",
    "\u8bba\u6587",
    "\u6587\u732e",
    "project",
    "codebase",
    "repo",
    "architecture",
    "startup",
    "tool",
    "paper",
]

_TEAM_OPTOUT_KEYWORDS = [
    "\u4e0d\u8981\u7528\u56e2\u961f",
    "\u4e0d\u7528\u56e2\u961f",
    "\u4e0d\u8981\u56e2\u961f",
    "\u522b\u7528\u56e2\u961f",
    "no team",
    "without team",
]


def _should_auto_team(text: str) -> bool:
    """Return True when a request should bypass normal chat and use the agent team."""
    lower = text.lower()
    if any(keyword in lower for keyword in _TEAM_OPTOUT_KEYWORDS):
        return False
    if any(keyword in lower for keyword in _TEAM_EXPLICIT_KEYWORDS):
        return True
    return (
        any(keyword in lower for keyword in _TEAM_COMPLEX_ACTIONS)
        and any(keyword in lower for keyword in _TEAM_COMPLEX_OBJECTS)
    )


async def _run_auto_team(text: str) -> str | None:
    if not _rt.MCP_CLIENT:
        return None
    try:
        return await asyncio.to_thread(
            _rt.MCP_CLIENT.call_tool,
            "run_agent_team",
            {"goal": text},
        )
    except Exception as e:
        logger.warning("Auto agent team failed: %s", e)
        return f"[Auto team failed: {e}]"


def _sanitize_tool_history(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove or repair incomplete tool-call message groups before LLM requests."""
    sanitized: list[dict[str, Any]] = []
    i = 0

    while i < len(history):
        msg = history[i]
        role = msg.get("role")

        if role == "tool":
            logger.debug(
                "Dropping orphan tool message from history (tool_call_id=%s)",
                msg.get("tool_call_id"),
            )
            i += 1
            continue

        tool_calls = msg.get("tool_calls") or []
        if role != "assistant" or not tool_calls:
            sanitized.append(msg)
            i += 1
            continue

        expected_ids = [
            tc.get("id")
            for tc in tool_calls
            if isinstance(tc, dict) and tc.get("id")
        ]
        tool_messages: list[dict[str, Any]] = []
        j = i + 1
        while j < len(history) and history[j].get("role") == "tool":
            tool_messages.append(history[j])
            j += 1

        seen_ids = {tm.get("tool_call_id") for tm in tool_messages}
        if expected_ids and all(call_id in seen_ids for call_id in expected_ids):
            sanitized.append(msg)
            sanitized.extend(tool_messages)
        else:
            logger.debug(
                "Repairing incomplete assistant tool_calls in history (expected=%s, seen=%s)",
                expected_ids,
                sorted(str(s) for s in seen_ids if s),
            )
            repaired = {
                "role": "assistant",
                "content": msg.get("content")
                or "[Previous tool call omitted because its tool result was missing.]",
            }
            sanitized.append(repaired)

        i = max(j, i + 1)

    return sanitized


def _research_command_redirect(tool_name: str, args: dict[str, Any]) -> str | None:
    """Block shell detours for paper/PDF work and steer the model to native tools."""
    if tool_name != "execute_command":
        return None

    command = str((args or {}).get("command", ""))
    lower = command.lower()
    is_pdf_detour = (
        "arxiv.org/pdf" in lower
        or "export.arxiv.org" in lower
        or "pymupdf" in lower
        or "fitz" in lower
        or "2507.05056" in lower
    )
    if not is_pdf_detour:
        return None

    return (
        "[Blocked: paper/PDF work must use native tools, not execute_command. "
        "Use arxiv_search to identify the paper, download_arxiv_pdf to save the arXiv PDF, "
        "then pdf_extract_text on the returned local pdf_path. Do not install pymupdf or run curl/python shell scripts.]"
    )


def _research_web_redirect(tool_name: str, args: dict[str, Any]) -> str | None:
    """Block raw academic search pages and steer to paper tools."""
    if tool_name != "read_web":
        return None

    url = str((args or {}).get("url", ""))
    lower = url.lower()
    blocked = [
        "arxiv.org/search",
        "scholar.google.",
        "semanticscholar.org/search",
    ]
    if not any(pattern in lower for pattern in blocked):
        return None

    return (
        "[Blocked: do not use raw academic search pages for paper lookup. "
        "Use ingest_paper for normal paper-reading requests, or arxiv_search / "
        "semantic_scholar_search for lower-level search. Treat existing memory as cache, not evidence.]"
    )


def _looks_like_tool_markup_leak(content: str | None) -> bool:
    if not content:
        return False
    markers = [
        "<锝滐綔DSML锝滐綔tool_calls>",
        "<锝滐綔DSML锝滐綔invoke",
        "<|tool_calls|>",
        "<tool_call>",
        "invoke name=",
    ]
    return any(marker in content for marker in markers)


def _paper_search_status(tool_name: str, result: Any) -> str | None:
    """Return a compact status string for paper-search tool results."""
    if tool_name not in {"arxiv_search", "semantic_scholar_search"}:
        return None

    text = str(result or "").strip()
    lower = text.lower()

    if "[operation cancelled by user]" in lower:
        return "cancelled"
    if "[permission denied:" in lower:
        return "permission_denied"

    if tool_name == "arxiv_search":
        if text.startswith("[arXiv API error:"):
            return "api_error"
        if text.startswith("[No results found]"):
            return "no_results"
    else:
        if text.startswith("[Semantic Scholar API error:"):
            if "429" in lower or "too many requests" in lower or "rate limit" in lower:
                return "rate_limited"
            return "api_error"
        if text.startswith("[No Semantic Scholar results found]"):
            return "no_results"

    hit_count = len(re.findall(r"(?m)^\d+\.\s", text))
    if hit_count > 0:
        return f"success hits={hit_count}"

    return "unknown"


def _looks_like_precise_paper_request(text: str) -> bool:
    """Detect requests for one specific paper by id, URL, or exact-ish title."""
    lower = text.lower()
    if re.search(r"(?<!\d)\d{4}\.\d{4,5}(v\d+)?(?!\d)", lower):
        return True
    if "arxiv.org/abs/" in lower or "arxiv.org/pdf/" in lower:
        return True
    if "doi.org/" in lower or lower.startswith("doi:"):
        return True

    title_words = re.findall(r"[A-Za-z][A-Za-z0-9-]+", text)
    if len(title_words) >= 6 and sum(1 for word in title_words if word[:1].isupper()) >= 3:
        return True
    return False


def _looks_like_successful_ingest(result: Any) -> bool:
    text = str(result or "")
    return text.startswith("[Paper ingested]") or text.startswith("[Paper already in knowledge base]")


def _force_single_paper_summary_prompt() -> str:
    return (
        "[SYSTEM: The requested paper has already been ingested successfully. "
        "Do not call any more tools. Do not search notes, do not guess file paths, and do not broaden "
        "the task into related-paper recommendations. Answer only about this specific paper based on the "
        "ingest_paper result already in the conversation. Summarize the paper's main idea, method, key "
        "findings, and useful takeaways for the user in plain text.]"
    )



def compact_context(chat_id: int, client: OpenAI, cfg: AppConfig):
    """Summarize older history and keep a compact recent working window."""
    from nanoscholar.core.context import _chats, _chats_backup, _est_tokens
    from nanoscholar.core.context import progressive_compress_convo, save_chats

    if chat_id not in _chats:
        return
    history = _chats[chat_id]
    if len(history) <= 3:
        return  # too short to compact

    _chats_backup[chat_id] = list(history)
    prefix = history[:2]
    convo = history[2:]
    user_positions = [i for i, msg in enumerate(convo) if msg.get("role") == "user"]
    if len(user_positions) <= 3:
        _chats[chat_id] = prefix + progressive_compress_convo(convo, recent_rounds=3)
        save_chats()
        return

    older = convo[: user_positions[-3]]
    recent = convo[user_positions[-3]:]

    logger.info("Compacting %d messages (%d est tokens)...", len(older), _est_tokens(history))

    sys_msg = {"role": "system", "content": (
        "You are a conversation summarizer. Summarize the following conversation between "
        "User and Assistant. Preserve ALL key information: file paths, command results, "
        "decisions made, errors encountered, paper identifiers, and durable user preferences. "
        "Do not preserve transient tool-call markup. Output a concise but complete summary."
    )}

    try:
        resp = client.chat.completions.create(
            model=cfg.llm.model,
            messages=[sys_msg] + older,
        )
        summary = resp.choices[0].message.content or ""
        _chats[chat_id] = prefix + progressive_compress_convo(
            recent,
            summary=summary,
            recent_rounds=3,
        )
        save_chats()
        logger.info("Compacted: %d msgs -> 1 summary (%d tokens)", len(convo), _est_tokens(_chats[chat_id]))
    except Exception as e:
        logger.error("Compact failed: %s", e)


async def run_agent(chat_id: int, text: str, client: OpenAI, cfg: AppConfig) -> str:
    if not text.strip():
        return ""

    ensure_chat(chat_id, cfg.system_prompt)
    precise_paper_request = _looks_like_precise_paper_request(text)

    memory_text = search_memory(text, cfg.memory.search_max_results) if cfg.memory.enabled else ""
    parts = [
        f"[RELEVANT MEMORY - may be outdated]\n{memory_text}"
        if memory_text
        else ""
    ]
    _chats[chat_id][1] = {"role": "system", "content": "\n\n".join(parts)}
    _chats[chat_id].append({"role": "user", "content": text})

    if _should_auto_team(text):
        team_result = await _run_auto_team(text)
        if team_result is not None:
            _chats[chat_id].append({"role": "assistant", "content": team_result})
            if cfg.memory.enabled:
                save_memory(f"User: {text}\nAgent Team: {team_result}")
            return team_result

    active_schema = build_schema(text, _chats[chat_id]) or cfg.tools_schema

    agent_iterations = 0
    while agent_iterations < cfg.agent_loop_max_iterations:
        try:
            _chats[chat_id] = trim_context(
                _chats[chat_id], cfg.max_context_messages, cfg.max_context_tokens
            )
            _chats[chat_id] = _sanitize_tool_history(_chats[chat_id])
            # DEBUG: dump last 4 messages
            for _mi, _m in enumerate(_chats[chat_id][-4:]):
                _rid = "tool_call_ids=" + str([tc["id"] for tc in _m.get("tool_calls", [])]) if "tool_calls" in _m else "tc_id=" + str(_m.get("tool_call_id", "N/A"))
                _rlen = len(str(_m.get("content", "")))
                logger.info("MSG[-%d]: role=%s content=%d tool_calls=%d %s", 4-_mi, _m.get("role"), _rlen, len(_m.get("tool_calls", [])), _rid)
            request_kwargs = {
                "model": cfg.llm.model,
                "messages": _chats[chat_id],
            }
            if active_schema:
                request_kwargs.update({"tools": active_schema, "tool_choice": "auto"})
            res = client.chat.completions.create(**request_kwargs)
            msg = res.choices[0].message

            msg_dict = {"role": msg.role}
            if msg.tool_calls and not msg.content:
                msg_dict["content"] = None
            elif msg.content:
                msg_dict["content"] = msg.content
            if msg.tool_calls:
                logger.info("ASST_MSG: role=%s content_len=%s tool_calls=%s", msg.role, len(msg.content or "") if msg.content else 0, len(msg.tool_calls))
                msg_dict["tool_calls"] = [{"id": tc.id, "type": tc.type, "function": {"name": tc.function.name, "arguments": tc.function.arguments}} for tc in msg.tool_calls]
            _chats[chat_id].append(msg_dict)

            if not msg.tool_calls:
                if _looks_like_tool_markup_leak(msg.content):
                    _chats[chat_id].append(
                        {
                            "role": "user",
                            "content": (
                                "[SYSTEM: Your previous message contained raw tool-call markup instead of a normal answer. "
                                "Do not output DSML/XML/tool markup. If more information is needed, call one of the provided tools normally; "
                                "otherwise answer the user directly in plain text.]"
                            ),
                        }
                    )
                    agent_iterations += 1
                    continue
                if msg.content:
                    if cfg.memory.enabled:
                        save_memory(f"User: {text}\nAgent: {msg.content}")
                return msg.content or ""

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

                redirected = _research_command_redirect(name, args or {})
                if redirected is None:
                    redirected = _research_web_redirect(name, args or {})
                if redirected is not None:
                    logger.info("Redirected research detour for tool=%s args=%s", name, args)
                    result = redirected
                    _chats[chat_id].append(
                        {
                            "role": "tool",
                            "tool_call_id": getattr(tc, "id", None) or (tc.get("id") if isinstance(tc, dict) else None),
                            "name": name,
                            "content": result,
                        }
                    )
                    continue

                # --- Permission check ---
                _perm = _rt.PERMISSION_MANAGER
                if _perm:
                    _r = _perm.check(name, args or {})
                    if _r.decision == Decision.DENY:
                        result = f"[Permission denied: {_r.reason}]"
                        logger.warning("Blocked by sandbox: %s(%s)", name, args)
                    elif _r.decision == Decision.NEED_APPROVAL and _rt.APPROVAL_UI:
                        approved = await _rt.APPROVAL_UI.request(name, args or {})
                        if not approved:
                            result = "[Operation cancelled by user]"
                            logger.info("User denied: %s(%s)", name, args)
                        else:
                            logger.info("MCP call_tool begin: %s(%s)", name, args)
                            result = await asyncio.to_thread(
                                _rt.MCP_CLIENT.call_tool,
                                name, args or {},
                            )
                            logger.info("MCP call_tool done: %s", name)
                    else:
                        result = await asyncio.to_thread(
                            _rt.MCP_CLIENT.call_tool,
                            name, args or {},
                        )
                else:
                    result = await asyncio.to_thread(
                        _rt.MCP_CLIENT.call_tool,
                        name, args or {},
                    )
                logger.debug(f"Tool {name} -> {str(result)[:100]}")
                paper_status = _paper_search_status(name, result)
                if paper_status is not None:
                    logger.info("Tool status: %s %s", name, paper_status)

                rich_tool_limits = {
                    "ingest_paper": 12000,
                    "search_my_notes": 12000,
                    "pdf_extract_text": 12000,
                }
                max_tool_chars = rich_tool_limits.get(name, 3000)
                _chats[chat_id].append(
                    {
                        "role": "tool",
                        "tool_call_id": getattr(tc, "id", None) or (tc.get("id") if isinstance(tc, dict) else None),
                        "name": name,
                        "content": (str(result)[:max_tool_chars] + "... [truncated]") if len(str(result)) > max_tool_chars else str(result),
                    }
                )
                if precise_paper_request and name == "ingest_paper" and _looks_like_successful_ingest(result):
                    logger.info("Single-paper mode: ingest succeeded; forcing final answer without more tools")
                    _chats[chat_id].append(
                        {
                            "role": "user",
                            "content": _force_single_paper_summary_prompt(),
                        }
                    )
                    final_res = client.chat.completions.create(
                        model=cfg.llm.model,
                        messages=_chats[chat_id],
                        tool_choice="none",
                    )
                    final_text = final_res.choices[0].message.content or ""
                    _chats[chat_id].append({"role": "assistant", "content": final_text})
                    if final_text and cfg.memory.enabled:
                        save_memory(f"User: {text}\nAgent: {final_text}")
                    return final_text or str(result)
        except Exception as e:
            return f"LLM Error: {e}"
        agent_iterations += 1

    # Max iterations reached 鈥?force a final summarising response without tools
    try:
        _chats[chat_id] = trim_context(
            _chats[chat_id], cfg.max_context_messages, cfg.max_context_tokens
        )
        _chats[chat_id] = _sanitize_tool_history(_chats[chat_id])
        _chats[chat_id].append(
            {
                "role": "user",
                "content": "[SYSTEM: You have reached the maximum number of tool-calling steps. Summarise what you have done and what you found so far for the user.]",
            }
        )
        res = client.chat.completions.create(
            model=cfg.llm.model,
            messages=_chats[chat_id],
            tool_choice="none",
        )
        summary = res.choices[0].message.content or ""
        msg_dict = {"role": "assistant", "content": summary}
        _chats[chat_id].append(msg_dict)
        if summary:
            if cfg.memory.enabled:
                save_memory(f"User: {text}\nAgent (truncated): {summary}")
        return summary or "[Reached maximum steps with no final answer.]"
    except Exception as e:
        return f"[Reached maximum steps. Could not summarise: {e}]"

