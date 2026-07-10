"""Lightweight JSON-RPC 2.0 protocol over stdio (newline-delimited JSON)."""

from __future__ import annotations

import json
from typing import Any

_next_id: int = 0


def next_id() -> int:
    global _next_id
    _next_id += 1
    return _next_id


def encode(msg: dict) -> bytes:
    """Serialize a JSON-RPC message to bytes (one compact JSON line)."""
    return json.dumps(msg, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"


def decode(line: bytes) -> dict:
    """Parse a JSON-RPC message from bytes."""
    return json.loads(line.decode("utf-8"))


def make_request(method: str, params: dict | None = None) -> dict:
    return {"jsonrpc": "2.0", "id": next_id(), "method": method, "params": params or {}}


def make_response(req_id: int, result: Any = None, error: dict | None = None) -> dict:
    if error:
        return {"jsonrpc": "2.0", "id": req_id, "error": error}
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def make_error(req_id: int, code: int, message: str, data: Any = None) -> dict:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return make_response(req_id, error=err)

