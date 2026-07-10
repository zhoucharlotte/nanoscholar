"""Background task scheduler — periodically checks SQLite for due tasks."""

import asyncio
import json
import logging
import sqlite3
import time
from pathlib import Path
from urllib.request import Request, urlopen

from openai import OpenAI

from nanoscholar.config import AppConfig
from nanoscholar.core.agent import run_agent
from nanoscholar.core.context import active_chat_ids
import nanoscholar._runtime as runtime

logger = logging.getLogger("nanoscholar")


def _notify(text: str):
    chat_ids = active_chat_ids()
    if not chat_ids:
        return

    chat_id = chat_ids[0]
    if not runtime.TG_TOKEN:
        print(f"\n[Task notification] {text}\nYou: ", end="", flush=True)
        return

    try:
        req = Request(
            f"https://api.telegram.org/bot{runtime.TG_TOKEN}/sendMessage",
            data=json.dumps({"chat_id": chat_id, "text": text}).encode(),
            headers={"Content-Type": "application/json"},
        )
        urlopen(req, timeout=5)
    except Exception as e:
        logger.error(f"Notify err: {e}")


def _scheduler_loop(interval: int, client: OpenAI, cfg: AppConfig):
    while True:
        try:
            chat_ids = active_chat_ids()
            chat_id = chat_ids[0] if chat_ids else 0

            with sqlite3.connect(runtime.DB_PATH) as conn:
                cur = conn.execute("""
                    SELECT id, command, repeat_seconds FROM tasks
                    WHERE (last_run IS NULL
                          AND (due_date IS NULL OR due_date <= datetime('now','localtime')))
                       OR (last_run IS NOT NULL AND repeat_seconds IS NOT NULL
                          AND datetime(last_run, '+' || repeat_seconds || ' seconds')
                              <= datetime('now','localtime'))
                """)
                for tid, prompt, rep in cur.fetchall():
                    logger.info(f"Triggering Agent Task {tid} -> {prompt}")

                    agent_prompt = (
                        f"[SYSTEM: AUTOMATED BACKGROUND TASK TRIGGERED]: {prompt}. "
                        f"Execute this and summarize the result."
                    )
                    res = asyncio.run(run_agent(chat_id, agent_prompt, client, cfg))
                    _notify(f"[Task {tid}] completed:\n\n{res}")

                    if rep:
                        conn.execute(
                            "UPDATE tasks SET last_run = datetime('now','localtime') WHERE id = ?",
                            (tid,),
                        )
                    else:
                        conn.execute("DELETE FROM tasks WHERE id = ?", (tid,))
                conn.commit()
        except Exception as e:
            logger.error(f"Scheduler error: {e}")
        time.sleep(interval)


def start_scheduler(interval: int, client: OpenAI, cfg: AppConfig):
    """Start the background scheduler in a daemon thread."""
    import threading

    threading.Thread(
        target=_scheduler_loop, args=(interval, client, cfg), daemon=True
    ).start()
    logger.info(f"Scheduler started (interval={interval}s)")

