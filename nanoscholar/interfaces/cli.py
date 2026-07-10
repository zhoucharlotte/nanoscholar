"""Non-blocking CLI with async queue 鈥?user can type while agent works."""

import asyncio
import queue
import threading
from typing import Any

from openai import OpenAI

from nanoscholar.config import AppConfig
from nanoscholar.core.agent import run_agent, compact_context
from nanoscholar.core.context import load_chats
from nanoscholar.db import clear_memory, memory_stats


def run_cli(client: OpenAI, cfg: AppConfig):
    load_chats()
    q: queue.Queue[str | None] = queue.Queue()
    lock = threading.Lock()

    def _worker():
        while True:
            text = q.get()
            if text is None:
                break
            try:
                result = asyncio.run(run_agent(0, text, client, cfg))
                with lock:
                    print(f"\nBot: {result}")
                    print("You: ", end="", flush=True)
            except Exception as e:
                with lock:
                    print(f"\n[Error: {e}]")
                    print("You: ", end="", flush=True)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()

    print("CLI mode active (async). Ctrl-C to exit.")
    try:
        while True:
            text = input("You: ").strip()
            if not text:
                continue
            if text in {"/clear", "/reset"}:
                from nanoscholar.core.context import clear_chat_context, save_chats
                clear_chat_context(0, cfg.system_prompt)
                save_chats()
                print("[Context cleared]")
                continue
            if text == "/clear-all":
                from nanoscholar.core.context import clear_all_contexts, save_chats
                clear_all_contexts()
                save_chats()
                print("[All chat contexts cleared]")
                continue
            if text == "/memory-clear":
                removed = clear_memory()
                print(f"[Memory cleared: {removed} rows]")
                continue
            if text == "/memory-stats":
                print(f"[{memory_stats()}]")
                continue
            if text == "/compact":
                compact_context(0, client, cfg)
                print("[Context compacted]")
                continue
            if text == "/rewind":
                from nanoscholar.core.context import _chats, _chats_backup
                if 0 in _chats_backup:
                    _chats[0] = _chats_backup.pop(0)
                    print("[Context restored from backup]")
                else:
                    print("[No backup available]")
                continue
            if text == "/exit" or text == "/quit":
                q.put(None)
                break
            q.put(text)
    except (EOFError, KeyboardInterrupt):
        q.put(None)
        print("\nOffline.")

