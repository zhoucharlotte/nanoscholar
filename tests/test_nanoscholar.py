"""Tests for the modular Nanoscholar package."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

import nanoscholar._runtime as runtime
from nanoscholar.config import AppConfig
from nanoscholar.core.agent import _sanitize_tool_history, _should_auto_team, run_agent
from nanoscholar.core.context import _chats, _est_tokens, trim_context
from nanoscholar.core.permission import Decision, PermissionManager
from nanoscholar.db import init_db, save_memory, search_memory
import nanoscholar.tools.domain.arxiv_search as _arxiv_search  # noqa: F401
import nanoscholar.tools.domain.pdf_tools as _pdf_tools  # noqa: F401
from nanoscholar.tools.domain.agent_team_tool import run_agent_team
from nanoscholar.tools.domain.tasks import add_task, list_tasks, remove_task
from nanoscholar.tools.router import build_schema, route
from nanoscholar.tools.system.filesystem import read_file, write_file
from nanoscholar.tools.system.shell import execute_command
from nanoscholar.tools.tool import get_tool


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path):
    runtime.WORKSPACE_ROOT = tmp_path
    runtime.WORKSPACE_RESTRICT = False
    runtime.DB_PATH = tmp_path / "nanoscholar_test.db"
    runtime.TG_TOKEN = ""
    runtime.PERMISSION_MANAGER = None
    runtime.APPROVAL_UI = None
    runtime.MCP_CLIENT = None
    _chats.clear()
    init_db()
    yield
    _chats.clear()


def test_valid_config_defaults():
    cfg = AppConfig(llm={"base_url": "http://localhost:8088/v1", "model": "test-model"})
    assert cfg.llm.model == "test-model"
    assert cfg.max_context_messages == 40
    assert cfg.telegram.token == ""


def test_missing_llm_raises():
    with pytest.raises(ValidationError):
        AppConfig()


def test_execute_command_success():
    result = execute_command("echo hello")
    assert "hello" in result.lower()


def test_workspace_restrict_blocks_absolute_cd(tmp_path):
    runtime.WORKSPACE_ROOT = tmp_path / "sandbox"
    runtime.WORKSPACE_ROOT.mkdir()
    runtime.WORKSPACE_RESTRICT = True
    result = execute_command("cd C:\\")
    assert "disallowed" in result.lower()


def test_read_and_write_file(tmp_path):
    path = tmp_path / "test.txt"
    assert write_file(str(path), "test content 123") == "[Written]"
    assert read_file(str(path)) == "test content 123"


def test_workspace_restrict_blocks_file_outside_root(tmp_path):
    runtime.WORKSPACE_ROOT = tmp_path / "sandbox"
    runtime.WORKSPACE_ROOT.mkdir()
    runtime.WORKSPACE_RESTRICT = True
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    assert "disallowed" in read_file(str(outside)).lower()


def test_save_and_search_memory():
    save_memory("User asked for the python version 3.10")
    save_memory("User likes chocolate cake")
    result = search_memory("python version", limit=5)
    assert "3.10" in result
    assert "chocolate" not in result


def test_add_list_and_remove_tasks():
    added = add_task("test task", "echo hi", delay_seconds=60)
    assert "Task added with ID:" in added
    tasks = list_tasks()
    assert "test task" in tasks
    task_id = int(tasks.split("]")[0].replace("[", ""))
    assert "removed" in remove_task(task_id)
    assert list_tasks() == "No tasks scheduled."


def test_trim_context_by_count():
    history = [
        {"role": "system", "content": "sys1"},
        {"role": "system", "content": "sys2"},
        {"role": "user", "content": "msg1"},
        {"role": "user", "content": "msg2"},
        {"role": "user", "content": "msg3"},
    ]
    trimmed = trim_context(history, max_messages=2, max_tokens=1000)
    assert [m["content"] for m in trimmed] == ["sys1", "sys2", "msg2", "msg3"]
    assert 5 < _est_tokens([{"role": "user", "content": "hello world!"}]) < 20


def test_router_selects_research_tools():
    selected = route("鎼滅储 transformer 璁烘枃")
    assert "arxiv_search" in selected
    assert "pdf_extract_text" in selected
    assert "run_agent_team" in selected


def test_research_schema_hides_command_tools():
    schema = build_schema("INTER: Mitigating Hallucination paper 找一下这篇论文")
    names = {item["function"]["name"] for item in schema}
    assert "arxiv_search" in names
    assert "pdf_extract_text" in names
    assert "execute_command" not in names
    assert "run_python_isolated" not in names


def test_bypass_safe_commands_allows_read_only_commands(tmp_path):
    cfg = AppConfig(llm={"base_url": "http://localhost/v1", "model": "test"})
    manager = PermissionManager(cfg, tmp_path)

    assert manager.check("execute_command", {"command": "dir"}).decision == Decision.ALLOW
    assert manager.check("execute_command", {"command": "rg paper nanoscholar"}).decision == Decision.ALLOW
    assert manager.check("execute_command", {"command": "git status --short"}).decision == Decision.ALLOW


def test_bypass_safe_commands_still_prompts_for_risky_commands(tmp_path):
    cfg = AppConfig(llm={"base_url": "http://localhost/v1", "model": "test"})
    manager = PermissionManager(cfg, tmp_path)

    assert manager.check("execute_command", {"command": "python -c \"print(1)\""}).decision == Decision.NEED_APPROVAL
    assert manager.check("execute_command", {"command": "dir > out.txt"}).decision == Decision.NEED_APPROVAL


def test_run_agent_team_pipeline_uses_planner_and_researcher():
    calls = []

    def fake_runner(prompt, tool_names, role):
        calls.append((role, tool_names, prompt))
        return f"{role.upper()}_RESULT"

    result = run_agent_team("inspect startup path", runner=fake_runner)

    assert [c[0] for c in calls] == ["planner", "researcher"]
    assert "write_file" not in calls[0][1]
    assert "write_file" not in calls[1][1]
    assert "final answer for the user" in calls[1][2]
    assert "PLANNER_RESULT" in result
    assert "RESEARCHER_RESULT" in result
    assert "## Researcher Final Result" in result


def test_run_agent_team_tool_registered():
    tool = get_tool("run_agent_team")
    assert tool is not None
    assert tool.input_schema["required"] == ["goal"]


def test_sanitize_tool_history_repairs_incomplete_tool_call_group():
    history = [
        {"role": "system", "content": "sys"},
        {"role": "system", "content": ""},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_missing",
                    "type": "function",
                    "function": {"name": "x", "arguments": "{}"},
                }
            ],
        },
        {"role": "user", "content": "next"},
    ]

    sanitized = _sanitize_tool_history(history)

    assert "tool_calls" not in sanitized[2]
    assert sanitized[2]["role"] == "assistant"
    assert sanitized[3] == {"role": "user", "content": "next"}


def test_should_auto_team_for_complex_requests():
    assert _should_auto_team("分析一下这个项目的启动风险")
    assert _should_auto_team("用 Planner 和 Researcher 团队检查工具系统")
    assert not _should_auto_team("浣犲ソ")
    assert not _should_auto_team("不用团队，简单回答这个项目叫什么")


@pytest.mark.asyncio
async def test_run_agent_simple_reply():
    msg = SimpleNamespace(role="assistant", content="Hello, human!", tool_calls=None)
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=msg)]
    )
    cfg = AppConfig(llm={"base_url": "http://localhost/v1", "model": "test"})

    reply = await run_agent(99, "hi", mock_client, cfg)

    assert reply == "Hello, human!"
    assert "Hello, human!" in search_memory("Hello, human!", limit=1)


@pytest.mark.asyncio
async def test_run_agent_uses_dynamic_schema_over_full_config_schema_for_papers():
    msg = SimpleNamespace(role="assistant", content="Paper summary.", tool_calls=None)
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=msg)]
    )
    cfg = AppConfig(
        llm={"base_url": "http://localhost/v1", "model": "test"},
        tools_schema=[
            {
                "type": "function",
                "function": {
                    "name": "execute_command",
                    "description": "Run command",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
    )

    reply = await run_agent(8, "INTER: Mitigating Hallucination paper 找一下这篇论文", mock_client, cfg)

    sent_tools = mock_client.chat.completions.create.call_args.kwargs["tools"]
    sent_names = {tool["function"]["name"] for tool in sent_tools}
    assert reply == "Paper summary."
    assert "execute_command" not in sent_names
    assert "arxiv_search" in sent_names


@pytest.mark.asyncio
async def test_run_agent_sanitizes_orphan_tool_calls_before_request():
    _chats[7] = [
        {"role": "system", "content": "sys"},
        {"role": "system", "content": ""},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_missing",
                    "type": "function",
                    "function": {"name": "x", "arguments": "{}"},
                }
            ],
        },
    ]
    msg = SimpleNamespace(role="assistant", content="Recovered.", tool_calls=None)
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=msg)]
    )
    cfg = AppConfig(llm={"base_url": "http://localhost/v1", "model": "test"})

    reply = await run_agent(7, "continue", mock_client, cfg)

    sent_messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
    assert reply == "Recovered."
    assert all(not m.get("tool_calls") for m in sent_messages)


@pytest.mark.asyncio
async def test_run_agent_auto_team_bypasses_llm_for_complex_request():
    runtime.MCP_CLIENT = MagicMock()
    runtime.MCP_CLIENT.call_tool.return_value = "TEAM_RESULT"
    mock_client = MagicMock()
    cfg = AppConfig(llm={"base_url": "http://localhost/v1", "model": "test"})

    reply = await run_agent(5, "分析一下这个项目的启动风险", mock_client, cfg)

    assert reply == "TEAM_RESULT"
    runtime.MCP_CLIENT.call_tool.assert_called_once_with(
        "run_agent_team",
        {"goal": "分析一下这个项目的启动风险"},
    )
    mock_client.chat.completions.create.assert_not_called()


@pytest.mark.asyncio
async def test_run_agent_tool_call_roundtrip():
    runtime.MCP_CLIENT = MagicMock()
    runtime.MCP_CLIENT.call_tool.return_value = "No tasks scheduled."

    tool_call = SimpleNamespace(
        id="call_1",
        type="function",
        function=SimpleNamespace(name="list_tasks", arguments="{}"),
    )
    first_msg = SimpleNamespace(role="assistant", content=None, tool_calls=[tool_call])
    final_msg = SimpleNamespace(role="assistant", content="No pending tasks.", tool_calls=None)
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = [
        SimpleNamespace(choices=[SimpleNamespace(message=first_msg)]),
        SimpleNamespace(choices=[SimpleNamespace(message=final_msg)]),
    ]
    cfg = AppConfig(
        llm={"base_url": "http://localhost/v1", "model": "test"},
        tools_schema=[
            {
                "type": "function",
                "function": {
                    "name": "list_tasks",
                    "description": "List tasks",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
    )

    reply = await run_agent(1, "list tasks", mock_client, cfg)

    assert reply == "No pending tasks."
    runtime.MCP_CLIENT.call_tool.assert_called_once_with("list_tasks", {})

