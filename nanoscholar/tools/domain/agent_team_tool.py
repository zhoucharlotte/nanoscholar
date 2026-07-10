"""Planner -> Researcher collaboration tool."""

from __future__ import annotations

from collections.abc import Callable

from nanoscholar.tools.domain.sub_agent_tool import _sub_agent_wrapper
from nanoscholar.tools.tool import Tool, register


RoleRunner = Callable[[str, list[str] | None, str], str]

_PLANNER_TOOLS = ["read_file", "search_my_notes"]
_RESEARCHER_TOOLS = [
    "read_file",
    "read_web",
    "arxiv_search",
    "semantic_scholar_search",
    "ingest_paper",
    "download_arxiv_pdf",
    "pdf_extract_text",
    "search_my_notes",
    "execute_command",
]


def _run_role(prompt: str, tool_names: list[str] | None, role: str) -> str:
    return _sub_agent_wrapper(prompt=prompt, tool_names=tool_names, role=role)


def run_agent_team(
    goal: str,
    runner: RoleRunner = _run_role,
) -> str:
    """Run a two-agent pipeline: Planner -> Researcher.

    Planner produces the plan. Researcher gathers evidence and writes the final
    user-facing result. The team does not receive write_file by default.
    """
    planner_prompt = (
        "Create a concise execution plan for this goal. Include assumptions, "
        "information needed, recommended tools, and done criteria. Do not write "
        "the final answer; your job is only to plan the research.\n\n"
        f"Goal:\n{goal}"
    )
    plan = runner(planner_prompt, _PLANNER_TOOLS, "planner")

    researcher_prompt = (
        "Use the planner output to complete the task. Gather concrete evidence, "
        "inspect relevant files or sources as needed, and then write the final "
        "answer for the user. Your response should be the final result, not just "
        "notes for another agent. Include exact paths, commands, observations, "
        "and caveats where relevant.\n\n"
        f"Goal:\n{goal}\n\n"
        f"Planner output:\n{plan}"
    )
    final_result = runner(researcher_prompt, _RESEARCHER_TOOLS, "researcher")

    return (
        "# Agent Team Result\n\n"
        f"## Goal\n{goal}\n\n"
        f"## Planner\n{plan}\n\n"
        f"## Researcher Final Result\n{final_result}"
    )


agent_team_tool = Tool(
    name="run_agent_team",
    description=(
        "Run a Planner -> Researcher agent pipeline for complex analysis, research, "
        "debugging, architecture review, or codebase inspection. Planner creates "
        "the plan; Researcher gathers evidence and writes the final result."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "goal": {
                "type": "string",
                "description": "The user goal for the agent team to analyze and answer.",
            },
        },
        "required": ["goal"],
    },
    handler=run_agent_team,
    category="general",
    approval_required=False,
)
register(agent_team_tool)

