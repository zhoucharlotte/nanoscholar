"""Run Python code in an isolated temp file with timeout."""

import subprocess
import sys
import tempfile
from pathlib import Path

from nanoscholar.tools.tool import Tool, register


def run_python_isolated(code: str, timeout: int = 10) -> str:
    """Write code to a temp file and execute it, returning stdout/stderr."""
    tmp = tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w", encoding="utf-8")
    try:
        tmp.write(code)
        tmp.close()
        result = subprocess.run(
            [sys.executable, tmp.name],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        output = stdout + ("\n[stderr]\n" + stderr if stderr else "")
        return output.strip() or "[No output]"
    except subprocess.TimeoutExpired:
        return f"[Timed out after {timeout}s]"
    except Exception as e:
        return f"[Execution error: {e}]"
    finally:
        Path(tmp.name).unlink(missing_ok=True)


python_tool = Tool(
    name="run_python_isolated",
    description="Execute Python code in a temporary file with timeout. Returns stdout/stderr. USE WITH CAUTION.",
    input_schema={
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Python code to execute"},
            "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 10},
        },
        "required": ["code"],
    },
    handler=run_python_isolated,
    category="command",
    approval_required=True,
)
register(python_tool)


