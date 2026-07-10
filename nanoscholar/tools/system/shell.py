"""Shell-command execution tool."""

import re
import subprocess
from pathlib import Path

from nanoscholar.tools.tool import Tool, register
import nanoscholar._runtime as runtime


def _in_workspace(path: str) -> bool:
    try:
        return Path(path).resolve().is_relative_to(runtime.WORKSPACE_ROOT.resolve())
    except Exception:
        return False


def execute_command(command: str) -> str:
    try:
        if runtime.WORKSPACE_RESTRICT and re.search(r"[A-Za-z]:\\|^/|\bcd\b\s+", command):
            return "Error: command disallowed under workspace restriction"
        res = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=runtime.WORKSPACE_ROOT if runtime.WORKSPACE_RESTRICT else None,
        )
        return ((res.stdout or "") + (res.stderr or "")).strip() or "[Success]"
    except Exception as e:
        return f"Error: {e}"


shell_tool = Tool(
    name="execute_command",
    description="Run shell command",
    input_schema={
        "type": "object",
        "properties": {
            "command": {"type": "string"},
        },
        "required": ["command"],
    },
    handler=execute_command,
    category="command",
    approval_required=True,
)

register(shell_tool)

