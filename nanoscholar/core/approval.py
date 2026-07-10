"""Approval UI abstraction — asks the user to approve or deny tool execution."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger("nanoscholar")


class ApprovalUI:
    """Abstract interface for user approval. Subclass for different frontends."""

    async def request(self, tool_name: str, tool_args: dict[str, Any]) -> bool:
        """Return True if the user approves, False if denied."""
        raise NotImplementedError


class CLIApprovalUI(ApprovalUI):
    """CLI-based approval: prompts the user with input()."""

    async def request(self, tool_name: str, tool_args: dict[str, Any]) -> bool:
        print(f"\n=== Approval Required ===")
        print(f"Tool: {tool_name}")
        print(f"Args: {tool_args}")
        resp = await asyncio.to_thread(input, "Proceed? (y/N): ")
        return resp.strip().lower() == "y"

