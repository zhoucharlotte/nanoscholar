"""SQLite database operations for memory and scheduled tasks."""

from __future__ import annotations

import hashlib
import re
import sqlite3

import nanoscholar._runtime as runtime


def init_db(db_path: str | None = None) -> None:
    """Initialize the SQLite schema for memory and scheduling."""
    path = db_path or runtime.DB_PATH
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                kind TEXT DEFAULT 'conversation',
                content_hash TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_hash ON memory(content_hash)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                description TEXT,
                command TEXT NOT NULL,
                due_date DATETIME,
                repeat_seconds INTEGER,
                last_run DATETIME
            )
            """
        )

        columns = {row[1] for row in conn.execute("PRAGMA table_info(memory)").fetchall()}
        if "kind" not in columns:
            conn.execute("ALTER TABLE memory ADD COLUMN kind TEXT DEFAULT 'conversation'")
        if "content_hash" not in columns:
            conn.execute("ALTER TABLE memory ADD COLUMN content_hash TEXT")


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _hash(content: str) -> str:
    return hashlib.sha256(_normalize_text(content).encode("utf-8")).hexdigest()


def _looks_worth_remembering(content: str) -> bool:
    text = _normalize_text(content)
    if len(text) < 40:
        return False
    low = text.lower()
    noisy_markers = [
        "llm error:",
        "operation cancelled",
        "approval required",
        "tool_calls",
        "<锝滐綔dsml锝滐綔",
        "[blocked:",
    ]
    return not any(marker in low for marker in noisy_markers)


def save_memory(content: str, kind: str = "conversation", force: bool = False) -> bool:
    """Save one memory item with de-duplication.

    Returns True when a new row was inserted.
    """
    content = content.strip()
    if not force and not _looks_worth_remembering(content):
        return False

    content_hash = _hash(content)
    with sqlite3.connect(runtime.DB_PATH) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO memory (content, kind, content_hash)
            VALUES (?, ?, ?)
            """,
            (content, kind, content_hash),
        )
        return conn.total_changes > 0


def _tokens(query: str) -> list[str]:
    words = [w.lower() for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9_.:-]{2,}", query)]
    cjk = [c for c in query if "\u4e00" <= c <= "\u9fff"]
    words.extend(cjk[i] + cjk[i + 1] for i in range(len(cjk) - 1))
    return list(dict.fromkeys(words))[:8]


def search_memory(query: str, limit: int) -> str:
    """Keyword-ranked search against durable memory."""
    terms = _tokens(query)
    if not terms:
        return ""

    with sqlite3.connect(runtime.DB_PATH) as conn:
        rows = conn.execute(
            "SELECT content, kind, timestamp FROM memory ORDER BY timestamp DESC LIMIT 200"
        ).fetchall()

    scored: list[tuple[int, str, str, str]] = []
    for content, kind, timestamp in rows:
        low = content.lower()
        score = sum(3 if term in low else 0 for term in terms)
        score += sum(low.count(term) for term in terms)
        if score > 0:
            scored.append((score, timestamp, kind, content))

    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return "\n---\n".join(content for _score, _ts, _kind, content in scored[:limit])


def clear_memory(kind: str | None = None) -> int:
    """Delete memory rows and return the number of affected rows."""
    with sqlite3.connect(runtime.DB_PATH) as conn:
        if kind:
            cur = conn.execute("DELETE FROM memory WHERE kind=?", (kind,))
        else:
            cur = conn.execute("DELETE FROM memory")
        return cur.rowcount


def memory_stats() -> str:
    with sqlite3.connect(runtime.DB_PATH) as conn:
        rows = conn.execute(
            "SELECT COALESCE(kind, 'unknown'), COUNT(*) FROM memory GROUP BY kind"
        ).fetchall()
    if not rows:
        return "Memory is empty."
    total = sum(count for _kind, count in rows)
    parts = [f"{kind}: {count}" for kind, count in rows]
    return f"Memory rows: {total} ({', '.join(parts)})"

