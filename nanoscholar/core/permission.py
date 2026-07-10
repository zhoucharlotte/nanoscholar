"""Two-layer permission model: sandbox (static policy) + approval (human-in-the-loop)."""

from __future__ import annotations

import fnmatch
import re
import shlex
from dataclasses import dataclass
from enum import auto, Enum
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


class Access(Enum):
    ALLOW = auto()
    DENY = auto()
    PROMPT = auto()

    @classmethod
    def from_str(cls, s: str) -> "Access":
        mapping = {"allow": cls.ALLOW, "deny": cls.DENY, "prompt": cls.PROMPT}
        return mapping.get(s.lower(), cls.PROMPT)


class Decision(Enum):
    ALLOW = auto()
    DENY = auto()
    NEED_APPROVAL = auto()


@dataclass
class CheckResult:
    decision: Decision
    reason: str = ""

    @classmethod
    def allow(cls) -> "CheckResult":
        return cls(Decision.ALLOW)

    @classmethod
    def deny(cls, reason: str) -> "CheckResult":
        return cls(Decision.DENY, reason)

    @classmethod
    def need_approval(cls) -> "CheckResult":
        return cls(Decision.NEED_APPROVAL)

    @property
    def is_allowed(self) -> bool:
        return self.decision == Decision.ALLOW


class SandboxEngine:
    """Layer 1: static policy rules — deny dangerous / restricted operations."""

    def __init__(self, cfg: Any):
        self.cfg = cfg

    def _match_glob(self, pattern: str, value: str) -> bool:
        return fnmatch.fnmatch(value.lower(), pattern.lower())

    def _path_in_allowed(self, path: str, allowed_paths: list[str], root: Path) -> bool:
        try:
            resolved = Path(path).resolve()
            for ap in allowed_paths:
                base = (root / ap).resolve()
                if resolved == base or base in resolved.parents:
                    return True
            return False
        except Exception:
            return False

    def check(self, tool: "Tool", args: dict[str, Any], root: Path) -> CheckResult:
        sandbox = self.cfg.permissions.sandbox
        cat = tool.category

        if cat == "command":
            cmd = args.get("command", "")
            rules = sandbox.commands
            for pattern in rules.denied:
                if self._match_glob(pattern, cmd):
                    return CheckResult.deny(f"Command blocked by sandbox: {cmd}")
            for pattern in rules.allowed:
                if self._match_glob(pattern, cmd):
                    return CheckResult.allow()
            access = Access.from_str(rules.default)
            if access == Access.DENY:
                return CheckResult.deny(f"Command not in allowed list: {cmd}")
            return CheckResult.allow()

        if cat == "file_read":
            path = args.get("path", "")
            if self._path_in_allowed(path, sandbox.files.read_allowed_paths, root):
                return CheckResult.allow()
            access = Access.from_str(sandbox.files.default)
            if access == Access.DENY:
                return CheckResult.deny(f"File read blocked by sandbox: {path}")
            return CheckResult.allow()

        if cat == "file_write":
            path = args.get("path", "")
            if self._path_in_allowed(path, sandbox.files.write_allowed_paths, root):
                return CheckResult.allow()
            access = Access.from_str(sandbox.files.default)
            if access == Access.DENY:
                return CheckResult.deny(f"File write blocked by sandbox: {path}")
            return CheckResult.allow()

        if cat == "network":
            url = args.get("url", "")
            host = urlparse(url).hostname or url
            rules = sandbox.network
            for pattern in rules.denied_domains:
                if self._match_glob(pattern, host):
                    return CheckResult.deny(f"URL blocked by sandbox: {url}")
            for pattern in rules.allowed_domains:
                if self._match_glob(pattern, host):
                    return CheckResult.allow()
            access = Access.from_str(rules.default)
            if access == Access.DENY:
                return CheckResult.deny(f"URL not in allowed list: {url}")
            return CheckResult.allow()

        return CheckResult.allow()


class ApprovalEngine:
    """Layer 2: decide whether the user needs to approve this operation."""

    def __init__(self, cfg: Any):
        self.cfg = cfg

    def _first_token(self, command: str) -> str:
        try:
            return (shlex.split(command, posix=False)[0] if command.strip() else "").lower()
        except ValueError:
            return command.strip().split(maxsplit=1)[0].lower() if command.strip() else ""

    def _is_safe_read_only_command(self, command: str) -> bool:
        cmd = command.strip()
        lower = cmd.lower()
        if not cmd:
            return True

        dangerous_patterns = [
            r"\b(del|erase|rm|rmdir|rd|move|mv|copy|cp|ren|rename|format|shutdown|taskkill)\b",
            r"\b(reg|set-content|out-file|new-item|remove-item|start-process|invoke-expression)\b",
            r">\s*[^&|]+",
            r">>",
            r"\|\s*(set-content|out-file|tee-object)\b",
        ]
        if any(re.search(pattern, lower) for pattern in dangerous_patterns):
            return False

        first = self._first_token(cmd).strip("\"'")
        safe_first_tokens = {
            "dir",
            "ls",
            "pwd",
            "whoami",
            "hostname",
            "date",
            "time",
            "type",
            "cat",
            "get-content",
            "select-string",
            "findstr",
            "rg",
            "where",
            "where.exe",
            "git",
        }
        if first not in safe_first_tokens:
            return False

        if first == "git":
            parts = re.split(r"\s+", lower)
            return len(parts) >= 2 and parts[1] in {
                "status",
                "diff",
                "log",
                "show",
                "branch",
                "rev-parse",
                "describe",
            }

        return True

    def needs_approval(self, tool: "Tool", args: dict[str, Any] | None = None) -> bool:
        approval = self.cfg.permissions.approval

        if approval.mode == "deny-all":
            return True
        if approval.mode == "auto-approve":
            return False
        if approval.mode == "never":
            return False
        if (
            approval.bypass_safe_commands
            and tool.name == "execute_command"
            and self._is_safe_read_only_command((args or {}).get("command", ""))
        ):
            return False

        if approval.require_for:
            return tool.name in approval.require_for
        return tool.approval_required


class PermissionManager:
    """Orchestrates sandbox + approval checks."""

    def __init__(self, cfg: Any, workspace_root: Path):
        self.cfg = cfg
        self.workspace_root = workspace_root
        self.sandbox = SandboxEngine(cfg)
        self.approval = ApprovalEngine(cfg)

    def check(self, tool_name: str, args: dict[str, Any]) -> CheckResult:
        """Run both permission layers. Returns the final decision."""
        from nanoscholar.tools.tool import get_tool
        tool = get_tool(tool_name)
        if not tool:
            return CheckResult.allow()

        if self.cfg.permissions.sandbox_enabled:
            result = self.sandbox.check(tool, args, self.workspace_root)
            if result.decision == Decision.DENY:
                return result

        if self.approval.needs_approval(tool, args):
            return CheckResult.need_approval()

        return CheckResult.allow()

