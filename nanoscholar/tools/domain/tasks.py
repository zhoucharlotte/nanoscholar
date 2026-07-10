"""Background task management tools (add / list / remove)."""

import logging
import sqlite3

from nanoscholar.tools.tool import Tool, register
import nanoscholar._runtime as runtime

logger = logging.getLogger("nanoscholar")


def add_task(
    description: str, prompt: str, delay_seconds: int = 0, repeat_seconds: int = None
) -> str:
    try:
        with sqlite3.connect(runtime.DB_PATH) as conn:
            cur = conn.execute(
                "INSERT INTO tasks (description, command, due_date, repeat_seconds) "
                "VALUES (?, ?, datetime('now', 'localtime', ?), ?)",
                (description, prompt, f"+{delay_seconds or 0} seconds", repeat_seconds),
            )
            conn.commit()
            return (
                f"[Task added with ID: {cur.lastrowid}. "
                f"Will trigger in {delay_seconds or 0} seconds]"
            )
    except Exception as e:
        return f"Error: {e}"


def list_tasks() -> str:
    try:
        with sqlite3.connect(runtime.DB_PATH) as conn:
            cur = conn.execute(
                "SELECT id, description, command, due_date, repeat_seconds, last_run "
                "FROM tasks"
            )
            rows = cur.fetchall()
            if not rows:
                return "No tasks scheduled."
            return "\n".join(
                [
                    f"[{r[0]}] {r[1]} | Cmd: {r[2]} | Due: {r[3]} | "
                    f"Repeat: {r[4]}s | Last: {r[5]}"
                    for r in rows
                ]
            )
    except Exception as e:
        return f"Error: {e}"


def remove_task(task_id: int) -> str:
    logger.debug(f"Attempting to remove task {task_id}")
    try:
        with sqlite3.connect(runtime.DB_PATH) as conn:
            if task_id == 0:
                conn.execute("DELETE FROM tasks")
            else:
                conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            conn.commit()
            return f"[Task {task_id} removed]"
    except Exception as e:
        return f"Error: {e}"


add_task_tool = Tool(
    name="add_task",
    description="Schedule a background task for YOURSELF to execute later.",
    input_schema={
        "type": "object",
        "properties": {
            "description": {"type": "string"},
            "prompt": {"type": "string", "description": "What you should do when the task fires"},
            "delay_seconds": {"type": "integer", "description": "Seconds to wait before first execution"},
            "repeat_seconds": {"type": "integer", "description": "Interval for recurring execution"},
        },
        "required": ["description", "prompt"],
    },
    handler=add_task,
    category="task",
    approval_required=False,
)

list_tasks_tool = Tool(
    name="list_tasks",
    description="List all background tasks",
    input_schema={
        "type": "object",
        "properties": {},
    },
    handler=list_tasks,
    category="task",
    approval_required=False,
)

remove_tasks_tool = Tool(
    name="remove_task",
    description="Delete task by ID (0 for all)",
    input_schema={
        "type": "object",
        "properties": {
            "task_id": {"type": "integer"},
        },
        "required": ["task_id"],
    },
    handler=remove_task,
    category="task",
    approval_required=False,
)

register(add_task_tool)
register(list_tasks_tool)
register(remove_tasks_tool)

