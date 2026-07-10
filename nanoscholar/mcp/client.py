"""MCP Client 鈥?spawns server subprocess, sends JSON-RPC over stdio."""

from __future__ import annotations

import logging
import subprocess
import os
import sys
import threading
from typing import Any

from nanoscholar.mcp.protocol import decode, encode, make_request

logger = logging.getLogger("nanoscholar.mcp")


class MCPError(Exception):
    pass


class MCPClient:
    """Manages an MCP Server subprocess and exposes tool discovery / execution."""

    def __init__(self, server_args: list[str] | None = None):
        self._proc: subprocess.Popen | None = None
        self._server_args = server_args or []

    def connect(self, cwd: str | None = None):
        """Spawn the MCP server subprocess and perform handshake."""
        cmd = [sys.executable, "-m", "nanoscholar.mcp.server", *self._server_args]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=cwd,
            env=env,
        )
        # Send initialize
        self._send_and_recv(make_request("initialize", {
            "protocolVersion": "0.1.0",
            "capabilities": {},
        }))
        logger.info("MCP client connected (pid=%d)", self._proc.pid)

    def disconnect(self):
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            self._proc.wait(timeout=5)
            self._proc = None

    def _send_and_recv(self, msg: dict, timeout: float = 120.0) -> dict:
        if not self._proc or not self._proc.stdin or not self._proc.stdout:
            raise MCPError("Not connected")
        self._proc.stdin.write(encode(msg))
        self._proc.stdin.flush()

        # Read with timeout to prevent hanging forever
        result: list[bytes | None] = [None]
        exc: list[Exception | None] = [None]
        def _read():
            try:
                result[0] = self._proc.stdout.readline()
            except Exception as e:
                exc[0] = e
        t = threading.Thread(target=_read, daemon=True)
        t.start()
        t.join(timeout)
        if t.is_alive():
            # Thread still running -> timeout
            raise MCPError(f"Server response timeout ({timeout}s) for method {msg.get('method')}")
        if exc[0]:
            raise MCPError(f"Read error: {exc[0]}")

        line = result[0]
        if not line:
            raise MCPError("Server closed connection")
        resp = decode(line)
        if "error" in resp:
            err = resp["error"]
            raise MCPError(f"MCP error [{err.get('code')}]: {err.get('message')}")
        return resp

    # 鈹€鈹€ Public API 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

    def list_tools_raw(self) -> list[dict]:
        """Fetch tool list from server as raw dicts (including custom metadata)."""
        resp = self._send_and_recv(make_request("tools/list"))
        return resp["result"]["tools"]

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> str:
        """Execute a tool on the server and return the text result."""
        logger.info("call_tool: %s %s", name, arguments)
        resp = self._send_and_recv(make_request("tools/call", {
            "name": name,
            "arguments": arguments or {},
        }))
        content = resp["result"]["content"]
        texts = [c["text"] for c in content if c.get("type") == "text"]
        return "\n".join(texts)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.disconnect()


