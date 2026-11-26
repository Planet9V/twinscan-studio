"""Pytest suite for Portable HTTP MCP (/api/agent/mcp), Bearer Auth, and DB-Encrypted OpenClaw Secrets."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from src.app.config import Settings
from src.app.factory import create_app
from src.db.repository import InMemoryTwinRepository
from src.db.robot_ai_store import InMemoryRobotAiStore
from src.db.robot_store import InMemoryRobotStore


@pytest.fixture()
def client() -> TestClient:
    """Create an isolated TestClient with one registered PuppyPi robot and sample Spatial Memory."""
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
            "id": "puppypi-portable-1",
            "name": "PuppyPi Portable",
            "ip_address": "192.168.1.119",
            "active_ros_distro": "humble",
            "status": "online",
            "battery_mv": 7920,
        }
    )
    ai_store.record_spatial_sighting(
        robot["id"],
        {"label": "Orange Toolbox", "kind": "object", "x_m": 1.1, "y_m": 0.4, "confidence": 0.9},
    )
    with TestClient(app) as tc:
        yield tc


def test_openclaw_db_encrypted_settings_masking_and_hot_reload(client: TestClient) -> None:
    """All 5 OpenClaw settings persist via /api/admin/settings, mask 4 secrets, and exclude secrets from export."""
    r_put = client.put(
        "/api/admin/settings",
        json={
            "settings": {
                "openclaw_gateway_url": "http://openclaw-gateway:18789",
                "openclaw_gateway_token": "oc_gw_super_secret_token_99",
                "openclaw_mcp_bearer_token": "mcp_bearer_secret_42_xyz",
                "openclaw_telegram_bot_token": "123456:AAH_telegram_secret",
                "openclaw_discord_bot_token": "MTIz.discord.secret_token",
            }
        },
    )
    assert r_put.status_code == 200
    assert r_put.json()["updated_count"] >= 4

    # GET /api/admin/settings returns masked values for all 4 secret keys, plain for gateway_url
    r_get = client.get("/api/admin/settings")
    assert r_get.status_code == 200
    by_key = {item["key"]: item for item in r_get.json()["settings"]}

    assert by_key["openclaw_gateway_url"]["is_secret"] is False
    assert by_key["openclaw_gateway_url"]["value"] == "http://openclaw-gateway:18789"

    for skey, raw_secret in (
        ("openclaw_gateway_token", "oc_gw_super_secret_token_99"),
        ("openclaw_mcp_bearer_token", "mcp_bearer_secret_42_xyz"),
        ("openclaw_telegram_bot_token", "123456:AAH_telegram_secret"),
        ("openclaw_discord_bot_token", "MTIz.discord.secret_token"),
    ):
        assert by_key[skey]["is_secret"] is True
        assert by_key[skey]["is_set"] is True
        assert by_key[skey]["persisted"] is True
        assert raw_secret not in by_key[skey]["value"]
        assert "••••" in by_key[skey]["value"]

    # Non-secret config export must include gateway_url and NEVER leak the 4 secret keys
    exported = client.get("/api/admin/config-export").json()["settings"]
    assert exported["openclaw_gateway_url"] == "http://openclaw-gateway:18789"
    for skey in (
        "openclaw_gateway_token",
        "openclaw_mcp_bearer_token",
        "openclaw_telegram_bot_token",
        "openclaw_discord_bot_token",
    ):
        assert skey not in exported

    # Hot-reloaded runtime effective_config holds decrypted values in memory
    rt = client.app.state.runtime
    assert rt.effective_config["openclaw_mcp_bearer_token"] == "mcp_bearer_secret_42_xyz"


def test_http_mcp_jsonrpc_and_bearer_auth_enforcement(client: TestClient) -> None:
    """POST /api/agent/mcp works openly by default and enforces 401/200 Bearer auth once token is set in /config."""
    # 1. Default local mode (no bearer token set): initialize, ping, tools/list, tools/call all return 200
    r_init = client.post("/api/agent/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert r_init.status_code == 200
    assert r_init.json()["result"]["protocolVersion"] == "2024-11-05"
    assert r_init.json()["result"]["serverInfo"]["name"] == "eigenia-twinscan-mcp"

    r_list = client.post("/api/agent/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert r_list.status_code == 200
    assert len(r_list.json()["result"]["tools"]) == 10

    r_call = client.post(
        "/api/agent/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "recall_spatial_memory", "arguments": {"query": "toolbox"}},
        },
    )
    assert r_call.status_code == 200
    call_res = r_call.json()["result"]
    assert call_res["isError"] is False
    parsed = json.loads(call_res["content"][0]["text"])
    assert parsed["ok"] is True
    assert "Orange Toolbox" in parsed["summary"]

    # Unknown JSON-RPC method -> -32601
    r_unk = client.post("/api/agent/mcp", json={"jsonrpc": "2.0", "id": 4, "method": "prompts/missing"})
    assert r_unk.status_code == 200
    assert r_unk.json()["error"]["code"] == -32601

    # 2. Configure openclaw_mcp_bearer_token in DB -> immediately protects /api/agent/mcp & /api/agent/execute!
    token = "top_secret_mcp_token_2026"
    assert client.put("/api/admin/settings", json={"settings": {"openclaw_mcp_bearer_token": token}}).status_code == 200

    # Missing header -> 401 on BOTH endpoints
    assert client.post("/api/agent/mcp", json={"jsonrpc": "2.0", "id": 5, "method": "tools/list"}).status_code == 401
    assert client.post("/api/agent/execute", json={"tool": "get_robot_status"}).status_code == 401

    # Wrong token -> 401 on BOTH endpoints
    bad_hdr = {"Authorization": "Bearer wrong_token"}
    assert client.post("/api/agent/mcp", headers=bad_hdr, json={"jsonrpc": "2.0", "id": 6, "method": "ping"}).status_code == 401
    assert client.post("/api/agent/execute", headers=bad_hdr, json={"tool": "get_robot_status"}).status_code == 401

    # Valid Bearer token -> 200 on BOTH endpoints!
    ok_hdr = {"Authorization": f"Bearer {token}"}
    r_mcp_ok = client.post("/api/agent/mcp", headers=ok_hdr, json={"jsonrpc": "2.0", "id": 7, "method": "tools/list"})
    assert r_mcp_ok.status_code == 200
    assert len(r_mcp_ok.json()["result"]["tools"]) == 10

    r_exec_ok = client.post("/api/agent/execute", headers=ok_hdr, json={"tool": "get_robot_status"})
    assert r_exec_ok.status_code == 200
    assert r_exec_ok.json()["ok"] is True

    # 3. GET /api/agent/openclaw-bundle reports bearer_auth_enabled=True & HTTP/stdio configs without leaking secret!
    bundle = client.get("/api/agent/openclaw-bundle").json()
    assert bundle["http_mcp_url"] == "http://backend:8000/api/agent/mcp"
    assert bundle["bearer_auth_enabled"] is True
    assert "docker_mcp_config" in bundle
    assert "stdio_mcp_config" in bundle
    assert token not in json.dumps(bundle)
