"""Sub-agent tool: spawn one isolated process per delegated task."""

from __future__ import annotations

import multiprocessing as mp
from concurrent.futures import ThreadPoolExecutor, as_completed

from nanoscholar.tools.tool import Tool, register


def _register_child_tools() -> None:
    from nanoscholar.tools.system import shell, filesystem, web  # noqa: F401
    from nanoscholar.tools.domain import tasks  # noqa: F401
    import nanoscholar.tools.domain.arxiv_search as _arxiv_search  # noqa: F401
    import nanoscholar.tools.domain.paper_ingest as _paper_ingest  # noqa: F401
    import nanoscholar.tools.domain.pdf_tools as _pdf_tools  # noqa: F401
    import nanoscholar.tools.domain.log_experiment as _log_experiment  # noqa: F401
    import nanoscholar.tools.domain.compare_experiments as _compare_experiments  # noqa: F401
    import nanoscholar.tools.domain.run_python as _run_python  # noqa: F401
    import nanoscholar.tools.domain.wiki_search as _wiki_search  # noqa: F401
    import nanoscholar.tools.domain.wiki_add_note as _wiki_add_note  # noqa: F401


def _worker_run(prompt: str, tool_names: list[str] | None, role: str, q: mp.Queue) -> None:
    """Run in a child process so a failed sub-agent cannot crash the MCP server."""
    _register_child_tools()
    from nanoscholar.core.sub_agent import run_sub_agent

    try:
        q.put(run_sub_agent(prompt, tool_names, role=role))
    except Exception as e:
        q.put(f"[Sub-agent process error: {e}]")


def _sub_agent_wrapper(
    prompt: str,
    tool_names: list[str] | None = None,
    role: str = "general",
) -> str:
    """Spawn a dedicated sub-agent process and return its final summary."""
    q: mp.Queue = mp.Queue()
    p = mp.Process(target=_worker_run, args=(prompt, tool_names, role, q), daemon=True)
    p.start()
    p.join(timeout=120)
    if p.is_alive():
        p.terminate()
        p.join()
        return "[Sub-agent timed out after 120s]"
    try:
        return q.get(timeout=5)
    except Exception:
        return "[Sub-agent failed - worker exited without result]"


def run_sub_agents(tasks: list[dict], max_workers: int = 3) -> str:
    """Run multiple isolated sub-agents concurrently.

    Each task is executed in its own child process. The thread pool only
    coordinates those processes and collects queue results.
    """
    if not tasks:
        return "[No sub-agent tasks provided]"

    max_workers = max(1, min(int(max_workers or 3), 6))
    normalized = []
    for idx, task in enumerate(tasks, 1):
        normalized.append(
            {
                "id": task.get("id") or f"task_{idx}",
                "prompt": task.get("prompt") or "",
                "role": task.get("role") or "general",
                "tool_names": task.get("tool_names"),
            }
        )

    results: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(
                _sub_agent_wrapper,
                task["prompt"],
                task["tool_names"],
                task["role"],
            ): task
            for task in normalized
            if task["prompt"].strip()
        }
        for future in as_completed(future_map):
            task = future_map[future]
            try:
                results[task["id"]] = future.result()
            except Exception as e:
                results[task["id"]] = f"[Sub-agent task error: {e}]"

    lines = ["# Sub-agent Batch Result"]
    for task in normalized:
        task_id = task["id"]
        lines.append(f"\n## {task_id} ({task['role']})")
        lines.append(results.get(task_id, "[Skipped: empty prompt]"))
    return "\n".join(lines)


sub_agent_tool = Tool(
    name="run_sub_agent",
    description=(
        "Delegate a complex task to one isolated role-based sub-agent. "
        "Use role='planner' or 'researcher' when a task benefits from specialization."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "The task to execute."},
            "role": {
                "type": "string",
                "description": "Sub-agent role: general, planner, or researcher.",
                "default": "general",
            },
            "tool_names": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Tool whitelist. Omit or null for all tools.",
            },
        },
        "required": ["prompt"],
    },
    handler=_sub_agent_wrapper,
    category="general",
    approval_required=False,
)
register(sub_agent_tool)


sub_agents_tool = Tool(
    name="run_sub_agents",
    description=(
        "Run multiple isolated role-based sub-agents concurrently. Each task runs "
        "in a separate child process; a thread pool coordinates concurrent execution "
        "and collects results safely."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "tasks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "Optional task id"},
                        "prompt": {"type": "string", "description": "Task prompt"},
                        "role": {"type": "string", "description": "general, planner, or researcher", "default": "general"},
                        "tool_names": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional tool whitelist",
                        },
                    },
                    "required": ["prompt"],
                },
            },
            "max_workers": {"type": "integer", "description": "Concurrent workers, 1-6", "default": 3},
        },
        "required": ["tasks"],
    },
    handler=run_sub_agents,
    category="general",
    approval_required=False,
)
register(sub_agents_tool)

