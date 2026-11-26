"""FastAPI endpoints for the Unified 10-Tool Robot Agent Registry, HTTP MCP, and OpenClaw Bundle."""

from __future__ import annotations

import hmac
import json
import os
import sys
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from src.agent.robot_tools import (
    ROBOT_TOOL_SPECS,
    execute_robot_tool,
    get_mcp_tool_schemas,
    get_openrouter_tool_schemas,
)

router = APIRouter(prefix="/api/agent", tags=["agent-mcp-openclaw"])

MCP_PROTOCOL_VERSION = "2024-11-05"
MCP_SERVER_INFO = {"name": "eigenia-twinscan-mcp", "version": "2.0.0"}


class AgentExecuteRequest(BaseModel):
    """Payload to execute one of the 10 validated safe PuppyPi robot tools."""

    tool: str = Field(..., min_length=1, max_length=64)
    arguments: Dict[str, Any] = Field(default_factory=dict)
    robot_id: Optional[str] = Field(default=None, max_length=120)


def _get_configured_mcp_bearer_token(request: Request) -> str:
    """Read the hot-reloaded Fernet-decrypted MCP bearer token from runtime effective config."""
    rt = getattr(request.app.state, "runtime", None)
    cfg = getattr(rt, "effective_config", {}) or {}
    return str(cfg.get("openclaw_mcp_bearer_token") or "").strip()


def _verify_mcp_bearer_auth(request: Request, authorization: Optional[str]) -> None:
    """Enforce ``Authorization: Bearer <token>`` when ``openclaw_mcp_bearer_token`` is set in PostgreSQL.

    When no token is configured (local Docker default), access is allowed without a header.
    Uses constant-time ``hmac.compare_digest`` comparison when a token is active.

    Args:
        request: Incoming FastAPI request.
        authorization: Optional HTTP ``Authorization`` header value.

    Raises:
        HTTPException: HTTP ``401`` when a bearer token is configured and missing or mismatched.
    """
    expected = _get_configured_mcp_bearer_token(request)
    if not expected:
        return
    raw = str(authorization or "").strip()
    parts = raw.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Missing or malformed Authorization: Bearer <token> header for MCP / Agent endpoint.",
        )
    supplied = parts[1].strip()
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=401,
            detail="Invalid Bearer token for MCP / Agent endpoint.",
        )


@router.get("/tools")
async def list_agent_tools() -> Dict[str, Any]:
    """Return both OpenRouter function-calling schemas and MCP tool schemas for all 10 robot tools."""
    return {
        "count": len(ROBOT_TOOL_SPECS),
        "openrouter_tools": get_openrouter_tool_schemas(),
        "mcp_tools": get_mcp_tool_schemas(),
    }


@router.post("/execute")
async def execute_agent_tool_route(
    body: AgentExecuteRequest,
    request: Request,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """Execute a validated safe robot tool on PuppyPi Pro and return structured summary + telemetry."""
    _verify_mcp_bearer_auth(request, authorization)
    try:
        return await execute_robot_tool(
            app=request.app,
            tool_name=body.tool,
            arguments=body.arguments,
            robot_id=body.robot_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/mcp")
async def http_mcp_jsonrpc_endpoint(
    request: Request,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """Portable Streamable HTTP JSON-RPC 2.0 MCP server endpoint for Docker/Railway OpenClaw gateways.

    Supports ``initialize``, ``notifications/initialized``, ``ping``, ``tools/list`` (10 tools),
    and ``tools/call`` delegating directly to ``execute_robot_tool(...)``.
    """
    _verify_mcp_bearer_auth(request, authorization)
    try:
        req = await request.json()
    except Exception as exc:
        return {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32700, "message": f"Parse error: {exc}"},
        }
    if not isinstance(req, dict):
        return {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32600, "message": "Invalid Request: JSON-RPC payload must be an object."},
        }

    method = str(req.get("method") or "").strip()
    req_id = req.get("id")
    params = req.get("params") if isinstance(req.get("params"), dict) else {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": dict(MCP_SERVER_INFO),
            },
        }

    if method == "notifications/initialized" or (method.startswith("notifications/") and req_id is None):
        return {"jsonrpc": "2.0", "id": req_id, "result": {"ok": True}}

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": get_mcp_tool_schemas()},
        }

    if method == "tools/call":
        tool_name = str(params.get("name") or "").strip()
        raw_args = dict(params.get("arguments")) if isinstance(params.get("arguments"), dict) else {}
        robot_id = raw_args.pop("robot_id", None) if "robot_id" in raw_args else params.get("robot_id")
        if not tool_name:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32602, "message": "Missing required parameter 'name' for tools/call."},
            }
        try:
            res = await execute_robot_tool(
                app=request.app,
                tool_name=tool_name,
                arguments=raw_args,
                robot_id=robot_id,
            )
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False)}],
                    "isError": not bool(res.get("ok", False)),
                },
            }
        except ValueError as exc:
            err_payload = {"ok": False, "tool": tool_name, "summary": str(exc), "data": {}}
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(err_payload, ensure_ascii=False)}],
                    "isError": True,
                },
            }
        except Exception as exc:
            sys.stderr.write(f"[agent.mcp] tools/call '{tool_name}' failed: {exc}\n")
            err_payload = {"ok": False, "tool": tool_name, "summary": f"Execution error: {exc}", "data": {}}
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(err_payload, ensure_ascii=False)}],
                    "isError": True,
                },
            }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


@router.get("/openclaw-bundle")
async def get_openclaw_bundle(
    request: Request,
    robot_id: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    """Return copy-paste-ready Docker HTTP MCP & host stdio MCP configs for OpenClaw (never leaks secrets)."""
    store = getattr(request.app.state, "robot_store", None)
    robot = None
    if store is not None:
        robot = store.get_robot(robot_id) if robot_id else (store.list_robots()[0] if store.list_robots() else None)

    api_url = os.getenv("TWINSCAN_PUBLIC_API_URL", "http://localhost:8000").rstrip("/")
    http_mcp_url = "http://backend:8000/api/agent/mcp"
    bearer_enabled = bool(_get_configured_mcp_bearer_token(request))
    resolved_id = robot["id"] if robot else robot_id
    resolved_name = str(robot.get("name") or "Hiwonder PuppyPi Pro") if robot else "Hiwonder PuppyPi Pro"

    docker_server_entry: Dict[str, Any] = {
        "transport": "http",
        "url": http_mcp_url,
    }
    if bearer_enabled:
        docker_server_entry["headers"] = {"Authorization": "Bearer <YOUR_OPENCLAW_MCP_BEARER_TOKEN>"}

    docker_mcp_config = {"mcpServers": {"eigenia-puppypi-http": docker_server_entry}}
    stdio_mcp_config = {
        "mcpServers": {
            "eigenia-puppypi": {
                "command": ".venv/bin/python",
                "args": ["-m", "src.agent.mcp_bridge"],
                "env": {
                    "TWINSCAN_API_URL": api_url,
                },
            }
        }
    }

    return {
        "api_url": api_url,
        "http_mcp_url": http_mcp_url,
        "bearer_auth_enabled": bearer_enabled,
        "robot_id": resolved_id,
        "robot_name": resolved_name,
        "tool_count": len(ROBOT_TOOL_SPECS),
        "skill_path": "openclaw/skills/puppypi-twinscan/SKILL.md",
        "mcp_config": stdio_mcp_config,
        "docker_mcp_config": docker_mcp_config,
        "stdio_mcp_config": stdio_mcp_config,
        "install_commands": [
            "docker compose --profile openclaw up -d --build",
            "cp -r openclaw/skills/puppypi-twinscan ~/.openclaw/skills/",
            f"Test portable HTTP MCP: curl -sS -X POST {api_url}/api/agent/mcp -H 'Content-Type: application/json' -d '{{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\"}}'",
        ],
    }
