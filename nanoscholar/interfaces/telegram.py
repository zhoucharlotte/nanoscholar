"""Telegram bot interface."""

from typing import Any

from openai import OpenAI

from nanoscholar.core.agent import run_agent


async def tg_handle(update: "Update", ctx: Any):
    bd = ctx.application.bot_data
    if update.effective_user.username not in bd["cfg"].telegram.allowed_usernames:
        return
    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    reply = await run_agent(
        update.effective_chat.id, update.message.text, bd["client"], bd["cfg"]
    )
    await update.message.reply_text(reply)

