"""Configuration models and file loading (YAML / JSON)."""

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError
import yaml


class TelegramCfg(BaseModel):
    token: str = ""
    allowed_usernames: list[str] = []


class LLMCfg(BaseModel):
    base_url: str
    api_key: str = "not-needed"
    model: str


class LoggingCfg(BaseModel):
    enabled: bool = True
    file: str = "nanoscholar.log"
    level: str = "INFO"



class CommandPolicyCfg(BaseModel):
    """Allowed / denied command patterns."""
    allowed: list[str] = ["*"]
    denied: list[str] = []
    default: str = "prompt"


class FilePolicyCfg(BaseModel):
    """Allowed read / write paths."""
    read_allowed_paths: list[str] = ["."]
    write_allowed_paths: list[str] = ["."]
    default: str = "prompt"


class NetworkPolicyCfg(BaseModel):
    """Allowed / denied network domains."""
    allowed_domains: list[str] = []
    denied_domains: list[str] = [
        "localhost", "127.0.0.1", "10.*", "172.*", "192.168.*"
    ]
    default: str = "prompt"


class SandboxCfg(BaseModel):
    commands: CommandPolicyCfg = CommandPolicyCfg()
    files: FilePolicyCfg = FilePolicyCfg()
    network: NetworkPolicyCfg = NetworkPolicyCfg()


class ApprovalCfg(BaseModel):
    mode: str = "always-ask"
    require_for: list[str] = ["execute_command", "write_file"]
    bypass_safe_commands: bool = True


class PermissionCfg(BaseModel):
    sandbox_enabled: bool = True
    sandbox: SandboxCfg = SandboxCfg()
    approval: ApprovalCfg = ApprovalCfg()

class WorkspaceCfg(BaseModel):
    path: str = "."
    restrict: bool = False


class MemoryCfg(BaseModel):
    search_max_results: int = 10
    enabled: bool = True


class AppConfig(BaseModel):
    telegram: TelegramCfg = TelegramCfg()
    llm: LLMCfg
    system_prompt: str = (
        "You are Nanoscholar - a local research assistant. Use your tools to help the user."
    )
    logging: LoggingCfg = LoggingCfg()
    workspace: WorkspaceCfg = WorkspaceCfg()
    scheduler_interval: int = 60
    memory: MemoryCfg = MemoryCfg()
    db_name: str = "nanoscholar.db"
    agent_loop_max_iterations: int = Field(
        5, description="Max iterations for tool-calling loops in a single agent response"
    )
    max_context_messages: int = Field(40, description="Max messages kept per chat")
    max_context_tokens: int = Field(
        8000, description="Soft token budget for conversation history"
    )
    tools_schema: list[dict[str, Any]] = Field(default_factory=list)
    permissions: PermissionCfg = PermissionCfg()


def load_config(path: str | Path) -> AppConfig:
    """Load config from a YAML (.yaml / .yml) or JSON file."""
    path = Path(path)
    raw: dict[str, Any]

    if path.suffix in (".yaml", ".yml"):
        with path.open(encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    else:
        with path.open(encoding="utf-8") as f:
            raw = json.load(f)

    return AppConfig(**raw)
