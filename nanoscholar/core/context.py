"""In-memory chat context management."""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

SYSTEM_SLOTS = 2

_chats: dict[int, list[dict[str, Any]]] = {}
_chats_backup: dict[int, list[dict[str, Any]]] = {}


def _est_tokens(messages: list) -> int:
    """Estimate token count using a rough chars-per-token heuristic."""
    return sum(len(json.dumps(m, ensure_ascii=False)) for m in messages) // 4


def _message_units(convo: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Group assistant tool_calls with their following tool messages.

    OpenAI-compatible APIs require tool_call messages and tool responses to stay
    adjacent. Context trimming and compression must therefore keep or drop them
    as one unit.
    """
    units: list[list[dict[str, Any]]] = []
    i = 0
    while i < len(convo):
        msg = convo[i]
        unit = [msg]
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            i += 1
            while i < len(convo) and convo[i].get("role") == "tool":
                unit.append(convo[i])
                i += 1
            units.append(unit)
            continue
        units.append(unit)
        i += 1
    return units


def _flatten(units: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    return [msg for unit in units for msg in unit]


def trim_context(history: list, max_messages: int, max_tokens: int) -> list:
    """Keep system slots and trim conversation without splitting tool groups."""
    prefix, convo = history[:SYSTEM_SLOTS], history[SYSTEM_SLOTS:]
    units = _message_units(convo)

    kept: list[list[dict[str, Any]]] = []
    count = 0
    for unit in reversed(units):
        if kept and count + len(unit) > max_messages:
            break
        kept.insert(0, unit)
        count += len(unit)

    while _est_tokens(prefix + _flatten(kept)) > max_tokens and len(kept) > 1:
        kept.pop(0)

    return prefix + _flatten(kept)


def progressive_compress_convo(
    convo: list[dict[str, Any]],
    summary: str | None = None,
    recent_rounds: int = 3,
    max_msg_len: int = 2500,
    merge_short_total: int = 320,
) -> list[dict[str, Any]]:
    """Four-level context compression pipeline.

    1. Optional summary of older context.
    2. Sliding window retaining recent user rounds.
    3. Long message truncation.
    4. Consecutive short assistant-message merge.
    """
    compressed: list[dict[str, Any]] = []
    if summary:
        compressed.append(
            {
                "role": "system",
                "content": f"[Compressed earlier context]\n{summary.strip()}",
            }
        )

    user_positions = [i for i, msg in enumerate(convo) if msg.get("role") == "user"]
    if len(user_positions) > recent_rounds:
        convo = convo[user_positions[-recent_rounds]:]

    truncated: list[dict[str, Any]] = []
    for msg in convo:
        content = msg.get("content")
        if isinstance(content, str) and len(content) > max_msg_len:
            msg = {**msg, "content": content[:max_msg_len] + "... [truncated]"}
        truncated.append(msg)

    for msg in truncated:
        if (
            compressed
            and compressed[-1].get("role") == "assistant"
            and msg.get("role") == "assistant"
            and not compressed[-1].get("tool_calls")
            and not msg.get("tool_calls")
        ):
            prev = compressed[-1].get("content") or ""
            curr = msg.get("content") or ""
            merged = f"{prev}\n\n{curr}".strip()
            if len(merged) <= merge_short_total:
                compressed[-1]["content"] = merged
                continue
        compressed.append(msg)

    return compressed


def get_chat(chat_id: int) -> list[dict[str, Any]]:
    return _chats.setdefault(chat_id, [])


def init_chat(chat_id: int, system_prompt: str) -> None:
    _chats[chat_id] = [
        {"role": "system", "content": system_prompt},
        {"role": "system", "content": ""},
    ]


def ensure_chat(chat_id: int, system_prompt: str) -> None:
    if chat_id not in _chats:
        init_chat(chat_id, system_prompt)


def active_chat_ids() -> list[int]:
    return list(_chats.keys())


def clear_chat_context(chat_id: int, system_prompt: str, persist: bool = True) -> None:
    """Reset one chat to only the system slots."""
    _chats_backup[chat_id] = list(_chats.get(chat_id, []))
    init_chat(chat_id, system_prompt)
    if persist:
        delete_chat_context(chat_id)


def clear_all_contexts(persist: bool = True) -> None:
    """Clear active and persisted chat contexts."""
    _chats_backup.clear()
    _chats.clear()
    if not persist:
        return
    from nanoscholar._runtime import DB_PATH

    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS chat_context "
                "(chat_id INTEGER PRIMARY KEY, data TEXT, updated_at REAL)"
            )
            conn.execute("DELETE FROM chat_context")
    except Exception:
        pass


def delete_chat_context(chat_id: int) -> None:
    """Delete one persisted chat context."""
    from nanoscholar._runtime import DB_PATH

    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS chat_context "
                "(chat_id INTEGER PRIMARY KEY, data TEXT, updated_at REAL)"
            )
            conn.execute("DELETE FROM chat_context WHERE chat_id=?", (chat_id,))
    except Exception:
        pass


def save_chats() -> None:
    """Serialize active chats to SQLite."""
    from nanoscholar._runtime import DB_PATH

    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS chat_context "
                "(chat_id INTEGER PRIMARY KEY, data TEXT, updated_at REAL)"
            )
            active = set(_chats)
            if active:
                placeholders = ",".join("?" for _ in active)
                conn.execute(
                    f"DELETE FROM chat_context WHERE chat_id NOT IN ({placeholders})",
                    tuple(active),
                )
            else:
                conn.execute("DELETE FROM chat_context")

            for cid, msgs in _chats.items():
                conn.execute(
                    "INSERT OR REPLACE INTO chat_context "
                    "(chat_id, data, updated_at) VALUES (?, ?, ?)",
                    (cid, json.dumps(msgs, ensure_ascii=False), time.time()),
                )
    except Exception:
        pass


def load_chats() -> None:
    """Restore chats from SQLite."""
    from nanoscholar._runtime import DB_PATH

    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS chat_context "
                "(chat_id INTEGER PRIMARY KEY, data TEXT, updated_at REAL)"
            )
            cur = conn.execute(
                "SELECT chat_id, data FROM chat_context ORDER BY updated_at DESC LIMIT 10"
            )
            for cid, data in cur.fetchall():
                _chats[cid] = json.loads(data)
    except Exception:
        pass


def _count_user_msgs(convo: list) -> int:
    return sum(1 for msg in convo if msg.get("role") == "user")


def _sliding_window(convo: list, max_rounds: int = 6) -> list:
    positions = [i for i, msg in enumerate(convo) if msg.get("role") == "user"]
    if len(positions) <= max_rounds:
        return convo
    return convo[positions[-max_rounds]:]


def _truncate_long_msgs(convo: list, max_len: int = 3000) -> list:
    result = []
    for msg in convo:
        content = msg.get("content", "")
        if isinstance(content, str) and len(content) > max_len:
            msg = {**msg, "content": content[:max_len] + "... [truncated]"}
        result.append(msg)
    return result


def _merge_short_assistant(convo: list, max_total: int = 200) -> list:
    result = []
    for msg in convo:
        if (
            result
            and result[-1].get("role") == "assistant"
            and msg.get("role") == "assistant"
            and not result[-1].get("tool_calls")
            and not msg.get("tool_calls")
        ):
            merged = (result[-1].get("content") or "") + "\n\n" + (msg.get("content") or "")
            if len(merged) <= max_total:
                result[-1]["content"] = merged
                continue
        result.append(msg)
    return result

