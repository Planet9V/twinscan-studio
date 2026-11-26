"""Pytest suite for Unified 10-Tool Robot Registry, /api/agent/* routes, and Stdio MCP Bridge."""

from __future__ import annotations

import json
import math
import time
from typing import Any, Dict

import httpx
import pytest
from fastapi.testclient import TestClient

from src.agent import robot_tools
from src.agent.mcp_bridge import MCP_PROTOCOL_VERSION, handle_mcp_request
from src.agent.robot_tools import (
    ALLOWED_BODY_ACTIONS,
    ROBOT_TOOL_SPECS,
    get_mcp_tool_schemas,
    get_openrouter_tool_schemas,
)
from src.app.config import Settings
from src.app.factory import create_app
from src.db.repository import InMemoryTwinRepository
from src.db.robot_ai_store import InMemoryRobotAiStore
from src.db.robot_store import InMemoryRobotStore
from src.lidar.ld19_parser import LidarPoint


def _pt(angle_deg: float, distance_m: float) -> LidarPoint:
    rad = math.radians(angle_deg)
    return LidarPoint(
        angle_deg=angle_deg,
        distance_m=distance_m,
        intensity=200,
        x=distance_m * math.cos(rad),
        y=distance_m * math.sin(rad),
    )


@pytest.fixture()
def agent_client() -> tuple[TestClient, str]:
    """Create an isolated TestClient with a registered PuppyPi Pro robot and sample Spatial Memory."""
    settings = Settings(database_url="", openrouter_api_key="", neo4j_uri="")
    robot_store = InMemoryRobotStore()
    ai_store = InMemoryRobotAiStore()
    app = create_app(
        settings=settings,
        repository=InMemoryTwinRepository(),
        robot_store=robot_store,
        robot_ai_store=ai_store,
    )
    robot = robot_store.upsert_robot(
        {
            "id": "puppypi-agent-1",
            "name": "PuppyPi Pro Lab",
            "ip_address": "192.168.1.119",
            "ssh_user": "ubuntu",
            "ssh_password": "secret",
            "rosbridge_port": 9090,
            "video_port": 8080,
            "active_ros_distro": "humble",
            "status": "online",
            "battery_mv": 7840,
        }
    )
    ai_store.record_spatial_sighting(
        robot["id"],
        {
            "label": "Blue Backpack",
            "kind": "object",
            "x_m": 1.4,
            "y_m": -0.6,
            "confidence": 0.92,
            "notes": "By the workbench",
            "tags": ["gear"],
        },
    )
    with TestClient(app) as tc:
        yield tc, robot["id"]


def test_ten_tool_schemas_and_agent_endpoints(
    agent_client: tuple[TestClient, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify all 10 tool schemas, /api/agent/tools, /api/agent/execute, and /api/agent/openclaw-bundle."""
    client, robot_id = agent_client
    rt = client.app.state.runtime
    rt.source_mode = "robot_ros2"
    rt.robot_scan_connected = True
    rt._last_scan_mono = time.monotonic()
    rt.latest_raw_points = [_pt(0.0, 1.5), _pt(45.0, 1.8), _pt(-45.0, 1.9), _pt(90.0, 2.0), _pt(-90.0, 1.1)]
    rt.robot_pose["battery_v"] = 7.82

    # 1. Schema helpers & GET /api/agent/tools
    assert len(ROBOT_TOOL_SPECS) == 16
    assert len(get_openrouter_tool_schemas(exclude=("chat_as_ox", "speak_aloud"))) == 14
    assert len(get_mcp_tool_schemas()) == 16

    r_tools = client.get("/api/agent/tools")
    assert r_tools.status_code == 200
    t_body = r_tools.json()
    assert t_body["count"] == 16
    assert len(t_body["openrouter_tools"]) == 16
    assert len(t_body["mcp_tools"]) == 16

    # 2. Execute get_robot_status
    r_st = client.post("/api/agent/execute", json={"tool": "get_robot_status", "arguments": {}, "robot_id": robot_id})
    assert r_st.status_code == 200
    st = r_st.json()
    assert st["ok"] is True
    assert st["tool"] == "get_robot_status"
    assert st["data"]["battery_v"] == 7.82
    assert st["data"]["lidar_live"] is True
    assert st["data"]["sectors_m"]["front"] == 1.5

    # 3. Execute recall_spatial_memory
    r_mem = client.post("/api/agent/execute", json={"tool": "recall_spatial_memory", "arguments": {"query": "backpack"}})
    assert r_mem.status_code == 200
    mem = r_mem.json()
    assert mem["ok"] is True
    assert mem["data"]["count"] == 1
    assert "Blue Backpack" in mem["summary"]

    # 4. Execute stop_robot_estop (mocked ROSBridge E-STOP)
    async def _fake_estop(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {"estop": True}

    monkeypatch.setattr(robot_tools, "trigger_estop", _fake_estop)
    r_estop = client.post("/api/agent/execute", json={"tool": "stop_robot_estop", "robot_id": robot_id})
    assert r_estop.status_code == 200
    assert r_estop.json()["ok"] is True
    assert r_estop.json()["data"]["rosbridge_estop_sent"] is True

    # 5. Unknown tool & disallowed body action -> HTTP 400
    assert client.post("/api/agent/execute", json={"tool": "delete_everything"}).status_code == 400
    assert "backflip" not in ALLOWED_BODY_ACTIONS
    assert client.post("/api/agent/execute", json={"tool": "run_body_action", "arguments": {"action": "backflip"}}).status_code == 400

    # 6. GET /api/agent/openclaw-bundle
    r_bundle = client.get("/api/agent/openclaw-bundle", params={"robot_id": robot_id})
    assert r_bundle.status_code == 200
    bundle = r_bundle.json()
    assert bundle["tool_count"] == 16
    assert bundle["robot_id"] == robot_id
    assert bundle["skill_path"] == "openclaw/skills/puppypi-twinscan/SKILL.md"
    assert "eigenia-puppypi" in bundle["mcp_config"]["mcpServers"]


@pytest.mark.asyncio
async def test_mcp_bridge_jsonrpc_lifecycle_and_tool_forwarding(
    agent_client: tuple[TestClient, str],
) -> None:
    """Verify JSON-RPC 2.0 MCP initialize, notifications/initialized, ping, tools/list, tools/call, and -32601."""
    client, robot_id = agent_client

    # Route httpx requests directly into the in-process FastAPI ASGI app!
    transport = httpx.ASGITransport(app=client.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        # 1. initialize
        init_resp = await handle_mcp_request(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            client=async_client,
            api_url="http://testserver",
        )
        assert init_resp is not None
        assert init_resp["result"]["protocolVersion"] == MCP_PROTOCOL_VERSION
        assert init_resp["result"]["serverInfo"]["name"] == "eigenia-twinscan-mcp"

        # 2. notifications/initialized -> None (no response)
        notif_resp = await handle_mcp_request(
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            client=async_client,
            api_url="http://testserver",
        )
        assert notif_resp is None

        # 3. ping
        ping_resp = await handle_mcp_request(
            {"jsonrpc": "2.0", "id": 2, "method": "ping"},
            client=async_client,
            api_url="http://testserver",
        )
        assert ping_resp == {"jsonrpc": "2.0", "id": 2, "result": {}}

        # 4. tools/list
        list_resp = await handle_mcp_request(
            {"jsonrpc": "2.0", "id": 3, "method": "tools/list"},
            client=async_client,
            api_url="http://testserver",
        )
        assert list_resp is not None
        tools = list_resp["result"]["tools"]
        assert len(tools) == 16
        assert any(t["name"] == "get_robot_status" for t in tools)

        # 5. tools/call -> forwards to POST /api/agent/execute
        call_resp = await handle_mcp_request(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "recall_spatial_memory", "arguments": {"query": "backpack", "robot_id": robot_id}},
            },
            client=async_client,
            api_url="http://testserver",
        )
        assert call_resp is not None
        assert call_resp["result"]["isError"] is False
        parsed_text = json.loads(call_resp["result"]["content"][0]["text"])
        assert parsed_text["ok"] is True
        assert parsed_text["data"]["count"] == 1

        # 6. Unknown method -> JSON-RPC -32601 error
        unk_resp = await handle_mcp_request(
            {"jsonrpc": "2.0", "id": 5, "method": "resources/nonexistent"},
            client=async_client,
            api_url="http://testserver",
        )
        assert unk_resp is not None
        assert unk_resp["error"]["code"] == -32601
