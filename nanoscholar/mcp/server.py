"""MCP Server 鈥?runs as subprocess, hosts all tool handlers."""

from __future__ import annotations

import logging
import os
import sys
import traceback
from typing import Any

from nanoscholar.mcp.protocol import decode, encode, make_error, make_request, make_response
from nanoscholar.tools.tool import get_tool, list_tools

logger = logging.getLogger("nanoscholar.mcp")

_log_file = None
def _log(msg):
    global _log_file
    if _log_file is None:
        import atexit
        _log_file = open("mcp_server_debug.log", "a", encoding="utf-8")
        atexit.register(_log_file.close)
    _log_file.write(f"[{os.getpid()}] {msg}\n")
    _log_file.flush()


class MCPServer:
    """Listens for JSON-RPC requests on stdin, dispatches to registered tools."""

    def __init__(self):
        self._running = True

    def _handle_request(self, req: dict) -> dict:
        method: str = req.get("method", "")
        params: dict = req.get("params", {})
        req_id = req.get("id")

        if method == "initialize":
            return make_response(req_id, {
                "protocolVersion": "0.1.0",
                "serverInfo": {"name": "nanoscholar-mcp", "version": "0.1.0"},
                "capabilities": {"tools": {}},
            })

        if method == "notifications/initialized":
            return None  # no response

        if method == "tools/list":
            tools_list = []
            for tool in list_tools():
                tools_list.append({
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": tool.input_schema,
                    "category": tool.category,
                    "approval_required": tool.approval_required,
                })
            return make_response(req_id, {"tools": tools_list})

        if method == "tools/call":
            name = params.get("name", "")
            arguments = params.get("arguments", {})
            _log("handler: tools/call name=" + str(name))
            tool = get_tool(name)
            if not tool:
                return make_error(req_id, -32602, f"Unknown tool: {name}")
            if tool.handler is None:
                return make_error(req_id, -32603, f"Tool {name} has no handler registered")
            try:
                result = tool.handler(**arguments)
                logger.info("tools/call done: %s", name)
                return make_response(req_id, {
                    "content": [{"type": "text", "text": str(result)}],
                })
            except Exception as e:
                return make_error(req_id, -32603, str(e), traceback.format_exc())

        return make_error(req_id, -32601, f"Method not found: {method}")

    def run(self):
        """Read requests from stdin, write responses to stdout."""
        _log("run() started")
        logger.info("MCP server started")
        for line in sys.stdin:
            _log("got line: " + line.rstrip()[:80])
            line = line.strip()
            if not line:
                continue
            try:
                req = decode(line.encode("utf-8"))
            except Exception:
                continue
            try:
                resp = self._handle_request(req)
            except Exception:
                resp = make_error(req.get("id"), -32603, "Internal server error")
            if resp is not None:
                sys.stdout.buffer.write(encode(resp))
                sys.stdout.buffer.flush()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    server = MCPServer()
    server.run()


if __name__ == "__main__":
    # Register all built-in tools
    from nanoscholar.tools.system import shell, filesystem, web  # noqa: F401
    from nanoscholar.tools.domain import tasks  # noqa: F401
    from nanoscholar.tools.domain import sub_agent_tool  # noqa: F401
    from nanoscholar.tools.domain import agent_team_tool  # noqa: F401
    from nanoscholar.tools.domain import arxiv_search  # noqa: F401
    from nanoscholar.tools.domain import paper_ingest  # noqa: F401
    from nanoscholar.tools.domain import pdf_tools  # noqa: F401
    from nanoscholar.tools.domain import log_experiment  # noqa: F401
    from nanoscholar.tools.domain import compare_experiments  # noqa: F401
    from nanoscholar.tools.domain import run_python  # noqa: F401
    from nanoscholar.tools.domain import wiki_search  # noqa: F401
    from nanoscholar.tools.domain import wiki_add_note  # noqa: F401
    main()

