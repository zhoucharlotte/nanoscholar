"""Runtime state — set by main.py at startup, imported by other modules."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nanoscholar.core.permission import PermissionManager
    from nanoscholar.core.approval import ApprovalUI

WORKSPACE_ROOT: Path = Path(".")
WORKSPACE_RESTRICT: bool = False
DB_PATH: Path = Path("nanoscholar.db")
TG_TOKEN: str = ""

# Permission layer (set by main.py at startup)
PERMISSION_MANAGER: PermissionManager | None = None
APPROVAL_UI: ApprovalUI | None = None

# MCP client (set by main.py)
MCP_CLIENT = None

