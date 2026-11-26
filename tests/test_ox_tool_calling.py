"""Unit and API tests for the 'Hey OX' Live Voice Tool-Calling Agent layer."""

from __future__ import annotations

import json
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.app.config import Settings
from src.app.factory import create_app
from src.db.repository import InMemoryTwinRepository
from src.db.robot_ai_store import InMemoryRobotAiStore
from src.db.robot_store import InMemoryRobotStore
from src.robot.conversation_engine import (
    detect_offline_tool_intent,
    generate_conversational_reply,
)


def _make_test_client() -> tuple[TestClient, str]:
    settings = Settings(database_url="", neo4j_uri="", openrouter_api_key="")
    repo = InMemoryTwinRepository()
    robot_store = InMemoryRobotStore()
    ai_store = InMemoryRobotAiStore()
    app = create_app(settings=settings, repository=repo, robot_store=robot_store, robot_ai_store=ai_store)
    robot = robot_store.upsert_robot(
        {
            "ip_address": "192.168.1.119",
            "name": "PuppyPi Pro",
            "model": "Hiwonder PuppyPi Pro",
            "active_ros_distro": "ROS2 Humble",
            "ssh_user": "pi",
            "rosbridge_port": 9090,
            "video_port": 8080,
            "battery_mv": 8120,
        },
        ssh_password="raspberrypi",
    )
    return TestClient(app), robot["id"]


def test_detect_offline_tool_intent_all_categories() -> None:
    """Verify deterministic offline routing for all 6 live robot tool categories plus chit-chat."""
    assert detect_offline_tool_intent("Emergency stop right now!") == ("stop_robot_estop", {})
    assert detect_offline_tool_intent("Hey OX, return to charger please") == ("return_to_home", {})
    assert detect_offline_tool_intent("Trigger RTH now") == ("return_to_home", {})

    exp = detect_offline_tool_intent("Can you explore the living room?")
    assert exp is not None and exp[0] == "start_autonomous_explore"
    assert "living room" in exp[1]["space_context"]

    assert detect_offline_tool_intent("Please run a 3D scan of this wall") == ("scan_room_wall_3d", {})

    mem = detect_offline_tool_intent("Where did you see my backpack earlier?")
    assert mem is not None and mem[0] == "recall_spatial_memory"
    assert mem[1]["query"] == "backpack"

    assert detect_offline_tool_intent("What is your battery and lidar status?") == ("get_robot_status", {})
    assert detect_offline_tool_intent("Tell me a funny joke about robots") is None


@pytest.mark.asyncio
async def test_offline_tool_execution_and_personality_narration() -> None:
    """Verify offline mode executes the matched tool and weaves its summary into the spoken reply."""
    called: List[tuple[str, Dict[str, Any]]] = []

    async def fake_executor(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        called.append((name, args))
        return {
            "ok": True,
            "tool": name,
            "summary": "Battery is 8.12 V (84%) and front LiDAR clearance is 1.45 m.",
            "data": {"battery_v": 8.12},
        }

    res = await generate_conversational_reply(
        user_text="Hey OX, how is your battery status?",
        config={"assistant_name": "OX", "personality_id": "dog"},
        personality={"id": "dog", "name": "Playful Dog", "allow_body_actions": True},
        history=[],
        openrouter_api_key="",
        tool_executor=fake_executor,
    )
    assert called == [("get_robot_status", {})]
    assert res["source"] == "offline_tool"
    assert "8.12 V" in res["reply"]
    assert len(res["tool_calls"]) == 1
    assert res["tool_calls"][0]["tool"] == "get_robot_status"
    assert res["tool_calls"][0]["ok"] is True


@pytest.mark.asyncio
async def test_openrouter_multi_step_tool_calls_and_three_round_cap() -> None:
    """Verify mocked OpenRouter tool_calls loop executes tools and caps strictly at 3 rounds."""
    tool_schemas = [
        {
            "type": "function",
            "function": {
                "name": "get_robot_status",
                "description": "Read live robot telemetry.",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    executed: List[str] = []

    async def fake_executor(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        executed.append(name)
        return {"ok": True, "tool": name, "summary": f"Checked {name} round {len(executed)}.", "data": {}}

    # Case 1: 1 tool round -> final JSON response
    resp_round1 = MagicMock()
    resp_round1.raise_for_status = MagicMock()
    resp_round1.json.return_value = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "get_robot_status", "arguments": "{}"},
                        }
                    ],
                }
            }
        ]
    }
    resp_final = MagicMock()
    resp_final.raise_for_status = MagicMock()
    resp_final.json.return_value = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": json.dumps(
                        {"reply": "Woof! Battery and LiDAR look great!", "action": "nod", "rgb": [16, 185, 129]}
                    ),
                }
            }
        ]
    }

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.post = AsyncMock(side_effect=[resp_round1, resp_final])

    with patch("src.robot.conversation_engine.httpx.AsyncClient", return_value=mock_client):
        res = await generate_conversational_reply(
            user_text="Check status and nod.",
            config={"assistant_name": "OX", "personality_id": "dog", "allow_body_actions": True},
            personality={"id": "dog", "system_prompt": "You are OX.", "allow_body_actions": True},
            history=[],
            openrouter_api_key="sk-or-test-key",
            tools=tool_schemas,
            tool_executor=fake_executor,
        )

    assert res["source"] == "openrouter"
    assert res["reply"] == "Woof! Battery and LiDAR look great!"
    assert res["action"] == "nod"
    assert len(res["tool_calls"]) == 1
    assert executed == ["get_robot_status"]

    # Case 2: Runaway model trying to call tools forever is strictly capped at 3 tool rounds
    executed.clear()
    loop_resp = MagicMock()
    loop_resp.raise_for_status = MagicMock()
    loop_resp.json.return_value = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_loop",
                            "type": "function",
                            "function": {"name": "get_robot_status", "arguments": "{}"},
                        }
                    ],
                }
            }
        ]
    }
    final_cap_resp = MagicMock()
    final_cap_resp.raise_for_status = MagicMock()
    final_cap_resp.json.return_value = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": json.dumps({"reply": "All three checks complete.", "action": "none", "rgb": None}),
                }
            }
        ]
    }

    mock_client_cap = AsyncMock()
    mock_client_cap.__aenter__.return_value = mock_client_cap
    mock_client_cap.post = AsyncMock(side_effect=[loop_resp, loop_resp, loop_resp, final_cap_resp])

    with patch("src.robot.conversation_engine.httpx.AsyncClient", return_value=mock_client_cap):
        res_cap = await generate_conversational_reply(
            user_text="Keep checking everything.",
            config={"assistant_name": "OX", "personality_id": "lab_assistant", "allow_body_actions": True},
            personality={"id": "lab_assistant", "system_prompt": "You are OX.", "allow_body_actions": True},
            history=[],
            openrouter_api_key="sk-or-test-key",
            tools=tool_schemas,
            tool_executor=fake_executor,
            max_tool_rounds=5,  # Must be clamped to 3!
        )

    assert len(executed) == 3
    assert len(res_cap["tool_calls"]) == 3
    assert res_cap["reply"] == "All three checks complete."


def test_voice_chat_endpoint_returns_tool_calls_and_excludes_recursive_tools() -> None:
    """Verify POST /api/robots/{id}/voice/chat executes offline robot tool and omits recursive tools."""
    client, robot_id = _make_test_client()
    resp = client.post(
        f"/api/robots/{robot_id}/voice/chat",
        json={"message": "Hey OX, what is your battery status?", "speak_reply": False, "execute_actions": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert isinstance(data.get("tool_calls"), list)
    assert len(data["tool_calls"]) == 1
    assert data["tool_calls"][0]["tool"] == "get_robot_status"
    assert data["tool_calls"][0]["ok"] is True

    # Confirm voice tool bridge exposes 14 non-recursive tools (excludes chat_as_ox and speak_aloud)
    from src.api.routes_voice import _build_voice_tool_bridge

    fake_req = MagicMock()
    fake_req.app = client.app
    tools, _ = _build_voice_tool_bridge(fake_req, robot_id)
    tool_names = {(t.get("function") or {}).get("name") for t in tools}
    assert len(tools) == 14
    assert "chat_as_ox" not in tool_names
    assert "speak_aloud" not in tool_names
    assert "get_robot_status" in tool_names
    assert "stop_robot_estop" in tool_names
    assert "search_web_live" in tool_names
    assert "remember_fact" in tool_names
    assert "recall_facts" in tool_names
    assert "walk_distance" in tool_names
    assert "turn_angle" in tool_names
    assert "get_overwatch_view" in tool_names
