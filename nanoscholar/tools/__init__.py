"""Tool registry 鈥?re-exports from tool.py. Tools are registered by the MCP server process."""

from nanoscholar.tools.tool import get_tool, list_tools, build_tools_schema, register

# TOOLS_MAP is intentionally removed in MCP mode.
# Tool execution goes through the MCP client (mcp_client.call_tool).
# The local registry is populated either by:
#   - server: importing tool modules (register with handler)
#   - client: MCP discovery (register without handler, for permission checking)


