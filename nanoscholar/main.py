"""Nanoscholar - local research assistant with tool-calling, Telegram & CLI."""

import argparse
import os
import logging
from pathlib import Path

from openai import OpenAI

from nanoscholar import __version__
import nanoscholar._runtime as runtime
from nanoscholar.config import load_config, ValidationError
from nanoscholar.db import init_db
from nanoscholar.mcp.client import MCPClient
from nanoscholar.tools.tool import Tool, register, list_tools
from nanoscholar.tools import build_tools_schema
from nanoscholar.core.permission import PermissionManager
from nanoscholar.core.approval import CLIApprovalUI
from nanoscholar.scheduler import start_scheduler

logger = logging.getLogger("nanoscholar")

try:
    from telegram import Update
    from telegram.ext import ApplicationBuilder, MessageHandler, filters
except ImportError:
    Update = None


def _inject_docs(cfg):
    """Auto-inject AGENT.md and SKILLS.md into the system prompt."""
    root_dir = Path(__file__).resolve().parent.parent
    docs_dir = root_dir / "docs"
    for doc in ["AGENT.md", "SKILLS.md"]:
        doc_path = docs_dir / doc
        if doc_path.exists():
            with doc_path.open(encoding="utf-8") as f:
                cfg.system_prompt += "\n\n" + f.read()

    research_path = root_dir / "RESEARCH.md"
    if research_path.exists():
        with research_path.open(encoding="utf-8") as f:
            cfg.system_prompt += "\n\n" + f.read()
    return cfg


def main():
    parser = argparse.ArgumentParser(description="Nanoscholar AI Assistant")
    parser.add_argument("-c", "--config", default="./configs/config.yaml")
    args = parser.parse_args()

    cfg_path = Path(args.config)
    if not cfg_path.exists():
        logger.error("Config file not found: %s", cfg_path)
        exit(1)

    try:
        cfg = load_config(cfg_path)
    except ValidationError as e:
        exit(f"Config error:\n{e}")
    except Exception as e:
        exit(f"Failed to load config: {e}")

    cfg = _inject_docs(cfg)

    runtime.WORKSPACE_ROOT = Path(cfg.workspace.path).resolve()
    runtime.WORKSPACE_RESTRICT = cfg.workspace.restrict
    runtime.DB_PATH = runtime.WORKSPACE_ROOT / cfg.db_name
    runtime.TG_TOKEN = cfg.telegram.token

    level = getattr(logging, cfg.logging.level.upper(), logging.INFO)
    handlers = [logging.StreamHandler()]

    if cfg.logging.enabled:
        log_path = runtime.WORKSPACE_ROOT / cfg.logging.file
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_path, encoding="utf-8"))

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
    )

    init_db()
    client = OpenAI(base_url=cfg.llm.base_url, api_key=cfg.llm.api_key)

    os.environ["NANOSCHOLAR_CONFIG_PATH"] = str(cfg_path.resolve())

    try:
        mcp_client = MCPClient()
        mcp_client.connect(cwd=str(runtime.WORKSPACE_ROOT))
        runtime.MCP_CLIENT = mcp_client

        for td in mcp_client.list_tools_raw():
            t = Tool(
                name=td["name"],
                description=td["description"],
                input_schema=td["inputSchema"],
                category=td.get("category", "general"),
                approval_required=td.get("approval_required", True),
            )
            register(t)
        logger.info("Discovered %d tools via MCP", len(list_tools()))
    except Exception as e:
        logger.error("Failed to start MCP client: %s", e)
        raise

    if not cfg.tools_schema:
        cfg.tools_schema = build_tools_schema()
        logger.info("Tools schema built from MCP registry (%d tools).", len(cfg.tools_schema))

    runtime.PERMISSION_MANAGER = PermissionManager(cfg, runtime.WORKSPACE_ROOT)
    runtime.APPROVAL_UI = CLIApprovalUI()
    logger.info(
        "Permission layer loaded (sandbox=%s, approval=%s)",
        cfg.permissions.sandbox_enabled,
        cfg.permissions.approval.mode,
    )

    start_scheduler(cfg.scheduler_interval, client, cfg)

    from nanoscholar.core.context import save_chats, load_chats

    load_chats()
    import atexit

    atexit.register(save_chats)

    logger.info("Nanoscholar %s loaded. DB: %s", __version__, runtime.DB_PATH)

    if (
        cfg.telegram.token
        and Update is not None
        and "YOUR_TELEGRAM_BOT_TOKEN" not in cfg.telegram.token
    ):
        from nanoscholar.interfaces.telegram import tg_handle

        app = ApplicationBuilder().token(cfg.telegram.token).build()
        app.bot_data.update({"cfg": cfg, "client": client})
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, tg_handle))
        app.run_polling()
    else:
        from nanoscholar.interfaces.cli import run_cli

        run_cli(client, cfg)


if __name__ == "__main__":
    main()

