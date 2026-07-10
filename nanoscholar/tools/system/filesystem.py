"""File read / write tools."""

from pathlib import Path

from nanoscholar.tools.tool import Tool, register
import nanoscholar._runtime as runtime
from nanoscholar.tools.system.shell import _in_workspace


def read_file(path: str) -> str:
    try:
        if runtime.WORKSPACE_RESTRICT and not _in_workspace(path):
            return "Error: disallowed"
        with Path(path).open("r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Error: {e}"


def write_file(path: str, content: str) -> str:
    try:
        if runtime.WORKSPACE_RESTRICT and not _in_workspace(path):
            return "Error: disallowed"
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with Path(path).open("w", encoding="utf-8") as f:
            f.write(content)
        return "[Written]"
    except Exception as e:
        return f"Error: {e}"


read_tool = Tool(
    name="read_file",
    description="Read file text",
    input_schema={
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
    handler=read_file,
    category="file_read",
    approval_required=False,
)

write_tool = Tool(
    name="write_file",
    description="Write file text",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["path", "content"],
    },
    handler=write_file,
    category="file_write",
    approval_required=True,
)

register(read_tool)
register(write_tool)

