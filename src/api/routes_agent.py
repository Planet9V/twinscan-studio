"""FastAPI endpoints for the Unified 10-Tool Robot Agent Registry & OpenClaw MCP Bundle."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from src.agent.robot_tools import (
    ROBOT_TOOL_SPECS,
    execute_robot_tool,
    get_mcp_tool_schemas,
    get_openrouter_tool_schemas,
)

router = APIRouter(prefix="/api/agent", tags=["agent-mcp-openclaw"])


class AgentExecuteRequest(BaseModel):
    """Payload to execute one of the 10 validated safe PuppyPi robot tools."""

    tool: str = Field(..., min_length=1, max_length=64)
    arguments: Dict[str, Any] = Field(default_factory=dict)
    robot_id: Optional[str] = Field(default=None, max_length=120)


@router.get("/tools")
async def list_agent_tools() -> Dict[str, Any]:
    """Return both OpenRouter function-calling schemas and MCP tool schemas for all 10 robot tools."""
    return {
        "count": len(ROBOT_TOOL_SPECS),
        "openrouter_tools": get_openrouter_tool_schemas(),
        "mcp_tools": get_mcp_tool_schemas(),
    }


@router.post("/execute")
async def execute_agent_tool_route(body: AgentExecuteRequest, request: Request) -> Dict[str, Any]:
    """Execute a validated safe robot tool on PuppyPi Pro and return structured summary + telemetry."""
    try:
        return await execute_robot_tool(
            app=request.app,
            tool_name=body.tool,
            arguments=body.arguments,
            robot_id=body.robot_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/openclaw-bundle")
async def get_openclaw_bundle(
    request: Request,
    robot_id: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    """Return a copy-paste-ready OpenClaw MCP configuration bundle and skill install instructions."""
    store = getattr(request.app.state, "robot_store", None)
    robot = None
    if store is not None:
        robot = store.get_robot(robot_id) if robot_id else (store.list_robots()[0] if store.list_robots() else None)

    api_url = os.getenv("TWINSCAN_PUBLIC_API_URL", "http://localhost:8000").rstrip("/")
    resolved_id = robot["id"] if robot else robot_id
    resolved_name = str(robot.get("name") or "Hiwonder PuppyPi Pro") if robot else "Hiwonder PuppyPi Pro"

    mcp_config = {
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
        "robot_id": resolved_id,
        "robot_name": resolved_name,
        "tool_count": len(ROBOT_TOOL_SPECS),
        "skill_path": "openclaw/skills/puppypi-twinscan/SKILL.md",
        "mcp_config": mcp_config,
        "install_commands": [
            "cp -r openclaw/skills/puppypi-twinscan ~/.openclaw/skills/",
            "Merge openclaw/mcp-config.json into your OpenClaw MCP config",
            f"Test MCP bridge: echo '{{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\"}}' | TWINSCAN_API_URL={api_url} .venv/bin/python -m src.agent.mcp_bridge",
        ],
    }
