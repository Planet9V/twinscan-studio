"""Comprehensive pytest suite for Phase 1 Supercharge Pack & HD Dual-Camera Overwatch.

Covers:
- Streaming sentence splitter, warm SSH ControlMaster flags, and pipelined TTS streaming.
- Expressive PuppyPi mood inference & ROSBridge RGB/OLED mood sync (including offline safety).
- Offline deterministic voice routing for all 6 new tools.
- Tool #11 ``search_web_live`` (mocked Perplexity Sonar + offline no-key fallback).
- Tools #12 & #13 ``remember_fact`` / ``recall_facts`` episodic persistence.
- Tool #14 ``walk_distance`` LD19 ``< 0.38m`` hard-stop refusal, ``[-0.6, +0.8]`` clamping, and zero-velocity stop.
- Tool #15 ``turn_angle`` ``[-180, +180]`` clamping and zero-velocity stop.
- Tool #16 ``get_overwatch_view`` + pure-NumPy ``triangulate_dual_rays`` (``< 0.01m`` exact ray error).
- ``/api/overwatch/{ingest,status,calibration,snapshot}`` for both ``usb_4k`` and ``macbook_cam`` slots.
- ``GET /api/agent/tools`` reporting ``count == 16``.
"""

from __future__ import annotations

import asyncio
import math
import time
from typing import Any, Dict, List, Tuple
from unittest.mock import AsyncMock, MagicMock, patch

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from src.agent import robot_tools
from src.agent.robot_tools import execute_robot_tool
from src.app.config import Settings
from src.app.factory import create_app
from src.db.repository import InMemoryTwinRepository
from src.db.robot_ai_store import InMemoryRobotAiStore
from src.db.robot_store import InMemoryRobotStore
from src.lidar.ld19_parser import LidarPoint
from src.robot import mood_sync, voice_manager
from src.robot.conversation_engine import detect_offline_tool_intent
from src.robot.mood_sync import MOOD_PROFILES, apply_robot_mood_expression, infer_reply_mood
from src.robot.voice_manager import (
    _ssh_control_args,
    speak_sentences_streaming,
    split_into_speech_sentences,
)
from src.vision.overwatch_triangulator import (
    OverwatchCalibration,
    intersect_ray_ground_plane,
    pixel_to_world_ray,
    triangulate_dual_rays,
)


def _lidar_pt(angle_deg: float, distance_m: float) -> LidarPoint:
    rad = math.radians(angle_deg)
    return LidarPoint(
        angle_deg=angle_deg,
        distance_m=distance_m,
        intensity=200,
        x=distance_m * math.cos(rad),
        y=distance_m * math.sin(rad),
    )


def _encode_test_jpeg(width: int = 320, height: int = 240) -> bytes:
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    cv2.rectangle(frame, (40, 40), (width - 40, height - 40), (240, 180, 40), 3)
    ok, buf = cv2.imencode(".jpg", frame)
    assert ok
    return buf.tobytes()


@pytest.fixture()
def supercharge_client() -> tuple[TestClient, str]:
    """Create an isolated TestClient with a registered PuppyPi Pro robot and in-memory stores."""
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
            "id": "puppypi-supercharge-1",
            "name": "PuppyPi Pro",
            "ip_address": "192.168.1.119",
            "ssh_user": "pi",
            "rosbridge_port": 9090,
            "video_port": 8080,
            "active_ros_distro": "ros2",
            "status": "online",
            "battery_mv": 8020,
        },
        ssh_password="raspberrypi",
    )
    with TestClient(app) as tc:
        yield tc, robot["id"]


def test_split_into_speech_sentences_and_ssh_control_args() -> None:
    """Verify sentence splitting preserves decimals/abbreviations and warm SSH ControlMaster flags."""
    assert split_into_speech_sentences("") == []
    text = "Dr. OX reports battery at 7.82 V. Front clearance is 0.38 m! Ready to explore?"
    parts = split_into_speech_sentences(text)
    assert parts == [
        "Dr. OX reports battery at 7.82 V.",
        "Front clearance is 0.38 m!",
        "Ready to explore?",
    ]

    args = _ssh_control_args("192.168.1.119", "pi")
    assert "ControlMaster=auto" in args
    assert "ControlPersist=120" in args
    assert any(a.startswith("ControlPath=/tmp/eigenia_ssh_") for a in args)


@pytest.mark.asyncio
async def test_speak_sentences_streaming_pipelines_synthesis_and_playback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify pipelined multi-sentence streaming synthesizes and plays every sentence in order."""
    events: List[Tuple[str, str]] = []

    async def _fake_synth(text: str, **kwargs: Any) -> Tuple[bytes, str, str]:
        events.append(("synth", text))
        await asyncio.sleep(0.01)
        return (b"RIFF" + text.encode("utf-8"), "piper_tts", "en_US-lessac-medium")

    async def _fake_play(ip: str, user: str, password: str, wav_bytes: bytes, card_index: Any = None) -> Dict[str, Any]:
        events.append(("play", wav_bytes[4:].decode("utf-8")))
        await asyncio.sleep(0.02)
        return {"ok": True, "bytes_played": len(wav_bytes)}

    monkeypatch.setattr(voice_manager, "synthesize_speech_wav", _fake_synth)
    monkeypatch.setattr(voice_manager, "play_wav_on_robot", _fake_play)

    res = await speak_sentences_streaming(
        ip="192.168.1.119",
        user="pi",
        password="secret",
        text="Hello pilot. Battery is full! Ready to roll.",
    )
    assert res["ok"] is True
    assert res["sentences_spoken"] == 3
    assert res["engine"] == "piper_tts"
    played = [txt for kind, txt in events if kind == "play"]
    assert played == ["Hello pilot.", "Battery is full!", "Ready to roll."]


def test_infer_reply_mood_all_six_profiles() -> None:
    """Verify mood inference accurately classifies all 6 canonical expression states."""
    assert set(MOOD_PROFILES.keys()) == {"happy", "curious", "thinking", "alert", "sleepy", "neutral"}
    assert infer_reply_mood("Warning: obstacle blocked ahead!", "dog") == "alert"
    assert infer_reply_mood("Let me check the sensors, scanning now.", "lab_assistant") == "thinking"
    assert infer_reply_mood("Goodnight, going to take a quick nap.", "cat") == "sleepy"
    assert infer_reply_mood("What is that over by the desk?", "dog") == "curious"
    assert infer_reply_mood("Woof! That was awesome!", "dog") == "happy"
    assert infer_reply_mood("Systems are nominal.", "lab_assistant") == "neutral"


@pytest.mark.asyncio
async def test_apply_robot_mood_expression_mocked_and_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify mood sync publishes RGB + OLED and degrades gracefully when robot is offline."""
    rgb_calls: List[Any] = []
    oled_calls: List[Tuple[int, str]] = []
    act_calls: List[str] = []

    async def _fake_rgb(ip: str, port: int, data: List[Dict[str, int]], ros_version: str = "ros2") -> Dict[str, Any]:
        rgb_calls.append(data)
        return {"sent": True}

    async def _fake_oled(ip: str, port: int, index: int = 1, text: str = "", ros_version: str = "ros2") -> Dict[str, Any]:
        oled_calls.append((index, text))
        return {"sent": True}

    async def _fake_action(ip: str, port: int, name: str, **kwargs: Any) -> Dict[str, Any]:
        act_calls.append(name)
        return {"sent": True}

    monkeypatch.setattr(mood_sync, "set_rgb", _fake_rgb)
    monkeypatch.setattr(mood_sync, "set_oled", _fake_oled)
    monkeypatch.setattr(mood_sync, "run_action", _fake_action)

    res = await apply_robot_mood_expression("192.168.1.119", 9090, "ros2", "happy", allow_gesture=True)
    assert res["ok"] is True
    assert res["mood"] == "happy"
    assert len(rgb_calls) == 1
    assert len(oled_calls) == 2
    assert act_calls == ["nod"]

    # Offline graceful degradation (never raises)
    async def _boom(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        raise ConnectionError("ROSBridge unreachable")

    monkeypatch.setattr(mood_sync, "set_rgb", _boom)
    monkeypatch.setattr(mood_sync, "set_oled", _boom)
    offline_res = await apply_robot_mood_expression("192.168.1.119", 9090, "ros2", "alert", allow_gesture=False)
    assert offline_res["ok"] is False
    assert len(offline_res["errors"]) == 2


def test_detect_offline_tool_intent_new_supercharge_tools() -> None:
    """Verify deterministic offline voice routing covers all 6 new tools without regressions."""
    web = detect_offline_tool_intent("Search the web for ROS 2 Humble release date")
    assert web == ("search_web_live", {"query": "ros 2 humble release date"})

    rem = detect_offline_tool_intent("Remember that the charger dock is under the workbench.")
    assert rem == ("remember_fact", {"fact": "the charger dock is under the workbench"})

    rec = detect_offline_tool_intent("What do you remember about the charger dock?")
    assert rec == ("recall_facts", {"query": "the charger dock"})

    walk_fwd = detect_offline_tool_intent("Walk forward 0.5 meters")
    assert walk_fwd == ("walk_distance", {"meters": 0.5})

    walk_back = detect_offline_tool_intent("Move backward 30 cm")
    assert walk_back == ("walk_distance", {"meters": -0.3})

    turn_l = detect_offline_tool_intent("Turn left 90 degrees")
    assert turn_l == ("turn_angle", {"degrees": 90.0})

    turn_r = detect_offline_tool_intent("Rotate right 45 degrees")
    assert turn_r == ("turn_angle", {"degrees": -45.0})

    ov = detect_offline_tool_intent("Check the HD overwatch room camera")
    assert ov == ("get_overwatch_view", {"include_detections": True})

    # Non-regression checks
    assert detect_offline_tool_intent("Emergency stop now!") == ("stop_robot_estop", {})
    assert detect_offline_tool_intent("Where did you see my backpack earlier?") == (
        "recall_spatial_memory",
        {"query": "backpack"},
    )


@pytest.mark.asyncio
async def test_search_web_live_offline_and_mocked_sonar(
    supercharge_client: tuple[TestClient, str],
) -> None:
    """Verify search_web_live handles offline no-key cleanly and parses mocked Perplexity Sonar."""
    client, robot_id = supercharge_client
    app = client.app

    # 1. Offline without OpenRouter API key
    res_off = await execute_robot_tool(app, "search_web_live", {"query": "ROS 2 Humble"}, robot_id=robot_id)
    assert res_off["ok"] is False
    assert "not configured" in res_off["summary"].lower()

    # 2. Online mocked Perplexity Sonar
    app.state.runtime.effective_config["openrouter_api_key"] = "sk-or-test-key"
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "ROS 2 Humble Hawksbill is an LTS release supported until 2027."}}],
        "citations": ["https://docs.ros.org/en/humble/"],
    }
    mock_http = AsyncMock()
    mock_http.__aenter__.return_value = mock_http
    mock_http.post = AsyncMock(return_value=mock_resp)

    with patch("src.agent.robot_tools.httpx.AsyncClient", return_value=mock_http):
        res_on = await execute_robot_tool(app, "search_web_live", {"query": "ROS 2 Humble LTS"}, robot_id=robot_id)

    assert res_on["ok"] is True
    assert "Humble Hawksbill" in res_on["summary"]
    assert res_on["data"]["model"] == "perplexity/sonar"
    assert len(res_on["data"]["citations"]) == 1


@pytest.mark.asyncio
async def test_remember_and_recall_facts_persistence(
    supercharge_client: tuple[TestClient, str],
) -> None:
    """Verify remember_fact persists episodic memories and recall_facts retrieves them."""
    client, robot_id = supercharge_client
    app = client.app

    r1 = await execute_robot_tool(
        app,
        "remember_fact",
        {"fact": "Jim prefers Piper Ryan voice at 80% volume.", "category": "preference"},
        robot_id=robot_id,
    )
    assert r1["ok"] is True
    assert r1["data"]["memory"]["category"] == "preference"

    r2 = await execute_robot_tool(
        app,
        "remember_fact",
        {"fact": "Charging pad sits next to the lab bookshelf.", "category": "room"},
        robot_id=robot_id,
    )
    assert r2["ok"] is True

    found = await execute_robot_tool(app, "recall_facts", {"query": "Piper Ryan"}, robot_id=robot_id)
    assert found["ok"] is True
    assert found["data"]["count"] == 1
    assert "Piper Ryan" in found["summary"]

    all_mems = await execute_robot_tool(app, "recall_facts", {"query": ""}, robot_id=robot_id)
    assert all_mems["ok"] is True
    assert all_mems["data"]["count"] == 2


@pytest.mark.asyncio
async def test_walk_distance_ld19_safety_gate_clamping_and_zero_stop(
    supercharge_client: tuple[TestClient, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify walk_distance refuses < 0.38m obstacles, clamps [-0.6, +0.8], and always zero-stops."""
    client, robot_id = supercharge_client
    app = client.app
    rt = app.state.runtime

    vel_calls: List[Dict[str, Any]] = []

    async def _fake_vel(**kwargs: Any) -> Dict[str, Any]:
        vel_calls.append(kwargs)
        return {"sent": True}

    async def _fast_sleep(_sec: float) -> None:
        return None

    monkeypatch.setattr(robot_tools, "publish_velocity", _fake_vel)
    monkeypatch.setattr(robot_tools.asyncio, "sleep", _fast_sleep)

    # 1. Blocked obstacle at 0.25m (< 0.38m) -> MUST refuse with ZERO velocity commands!
    rt._last_scan_mono = time.monotonic()
    rt.latest_raw_points = [_lidar_pt(0.0, 0.25), _lidar_pt(90.0, 1.5)]
    blocked = await execute_robot_tool(app, "walk_distance", {"meters": 0.4}, robot_id=robot_id)
    assert blocked["ok"] is False
    assert blocked["data"]["blocked"] is True
    assert vel_calls == []

    # 2. Clear front (1.6m), request +2.5m -> clamped to +0.8m and ends with zero-velocity stop
    rt._last_scan_mono = time.monotonic()
    rt.latest_raw_points = [_lidar_pt(0.0, 1.6), _lidar_pt(45.0, 1.8)]
    fwd = await execute_robot_tool(app, "walk_distance", {"meters": 2.5, "speed_mps": 0.5}, robot_id=robot_id)
    assert fwd["ok"] is True
    assert fwd["data"]["clamped_meters"] == pytest.approx(0.8)
    assert fwd["data"]["speed_mps"] == pytest.approx(0.14)
    assert len(vel_calls) == 2
    assert vel_calls[0]["x"] > 0
    assert vel_calls[-1]["x"] == 0.0 and vel_calls[-1]["yaw_rate"] == 0.0

    # 3. Backward -1.5m -> clamped to -0.6m and ends with zero-velocity stop
    vel_calls.clear()
    back = await execute_robot_tool(app, "walk_distance", {"meters": -1.5}, robot_id=robot_id)
    assert back["ok"] is True
    assert back["data"]["clamped_meters"] == pytest.approx(-0.6)
    assert vel_calls[0]["x"] < 0
    assert vel_calls[-1]["x"] == 0.0


@pytest.mark.asyncio
async def test_turn_angle_clamping_and_zero_velocity_guarantee(
    supercharge_client: tuple[TestClient, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify turn_angle clamps to [-180, +180] and always sends a zero-velocity stop in finally."""
    client, robot_id = supercharge_client
    app = client.app

    vel_calls: List[Dict[str, Any]] = []

    async def _fake_vel(**kwargs: Any) -> Dict[str, Any]:
        vel_calls.append(kwargs)
        return {"sent": True}

    async def _fast_sleep(_sec: float) -> None:
        return None

    monkeypatch.setattr(robot_tools, "publish_velocity", _fake_vel)
    monkeypatch.setattr(robot_tools.asyncio, "sleep", _fast_sleep)

    left = await execute_robot_tool(app, "turn_angle", {"degrees": 360.0}, robot_id=robot_id)
    assert left["ok"] is True
    assert left["data"]["clamped_degrees"] == pytest.approx(180.0)
    assert len(vel_calls) == 2
    assert vel_calls[0]["yaw_rate"] > 0
    assert vel_calls[-1]["yaw_rate"] == 0.0

    vel_calls.clear()
    right = await execute_robot_tool(app, "turn_angle", {"degrees": -270.0}, robot_id=robot_id)
    assert right["ok"] is True
    assert right["data"]["clamped_degrees"] == pytest.approx(-180.0)
    assert vel_calls[0]["yaw_rate"] < 0
    assert vel_calls[-1]["yaw_rate"] == 0.0


def test_triangulate_dual_rays_exact_3d_intersection() -> None:
    """Verify pure-NumPy dual-ray triangulation recovers exact 3D intersections with < 0.01m error."""
    target = np.array([1.2, 0.8, 0.35], dtype=np.float64)
    cam1 = np.array([0.0, -2.0, 1.5], dtype=np.float64)
    cam2 = np.array([2.4, -0.5, 0.35], dtype=np.float64)
    dir1 = target - cam1
    dir2 = target - cam2

    res = triangulate_dual_rays(cam1, dir1, cam2, dir2)
    assert res["error_m"] < 0.01
    assert res["x"] == pytest.approx(1.2, abs=0.01)
    assert res["y"] == pytest.approx(0.8, abs=0.01)
    assert res["z"] == pytest.approx(0.35, abs=0.01)
    assert res["confidence"] > 0.8

    # Also validate pixel_to_world_ray -> intersect_ray_ground_plane geometry
    cal = OverwatchCalibration(x_m=0.0, y_m=-2.0, z_m=1.0, yaw_deg=90.0, pitch_deg=-45.0)
    origin, unit_dir = pixel_to_world_ray(u=320.0, v=240.0, width=640, height=480, cal=cal)
    hit = intersect_ray_ground_plane(origin, unit_dir, z_plane=0.0)
    assert hit is not None
    assert hit["x"] == pytest.approx(0.0, abs=0.02)
    assert hit["y"] == pytest.approx(-1.0, abs=0.02)


@pytest.mark.asyncio
async def test_overwatch_endpoints_dual_camera_and_16_tools_count(
    supercharge_client: tuple[TestClient, str],
) -> None:
    """Verify /api/overwatch/{ingest,status,calibration,snapshot}, get_overwatch_view, and 16 tools."""
    client, robot_id = supercharge_client
    jpg = _encode_test_jpeg(640, 360)

    # 1. GET /api/agent/tools reports 16 tools
    r_tools = client.get("/api/agent/tools")
    assert r_tools.status_code == 200
    body = r_tools.json()
    assert body["count"] == 16
    tool_names = {t["name"] for t in body["mcp_tools"]}
    for expected in (
        "search_web_live",
        "remember_fact",
        "recall_facts",
        "walk_distance",
        "turn_angle",
        "get_overwatch_view",
    ):
        assert expected in tool_names

    # 2. Update calibration for usb_4k
    r_cal = client.put(
        "/api/overwatch/calibration",
        params={"camera_id": "usb_4k"},
        json={"x_m": 0.25, "y_m": -2.4, "z_m": 1.6, "yaw_deg": 92.0, "pitch_deg": -20.0, "mode": "triangulate"},
    )
    assert r_cal.status_code == 200
    assert r_cal.json()["calibration"]["x_m"] == pytest.approx(0.25)

    # 3. Ingest JPEG frames on BOTH usb_4k and macbook_cam slots
    r_ing1 = client.post(
        "/api/overwatch/ingest",
        params={"camera_id": "usb_4k", "camera_name": "4k Webcam", "fps": 12.0},
        files={"frame": ("frame.jpg", jpg, "image/jpeg")},
    )
    assert r_ing1.status_code == 200
    assert r_ing1.json()["ok"] is True
    assert r_ing1.json()["width"] == 640

    r_ing2 = client.post(
        "/api/overwatch/ingest",
        params={"camera_id": "macbook_cam", "camera_name": "MacBook Pro Camera", "fps": 10.0},
        content=jpg,
        headers={"Content-Type": "image/jpeg"},
    )
    assert r_ing2.status_code == 200
    assert r_ing2.json()["ok"] is True

    # 4. GET /api/overwatch/status exposes top-level primary + both cameras in slot map
    r_st = client.get("/api/overwatch/status")
    assert r_st.status_code == 200
    st = r_st.json()
    assert st["online"] is True
    assert st["width"] == 640
    assert "usb_4k" in st["cameras"]
    assert "macbook_cam" in st["cameras"]
    assert st["cameras"]["usb_4k"]["online"] is True
    assert st["cameras"]["macbook_cam"]["online"] is True

    # 5. GET /api/overwatch/snapshot returns valid JPEG bytes for both cameras
    for cid in ("usb_4k", "macbook_cam"):
        r_snap = client.get("/api/overwatch/snapshot", params={"camera_id": cid, "annotated": True})
        assert r_snap.status_code == 200
        assert r_snap.headers["content-type"].startswith("image/jpeg")
        assert r_snap.content[:2] == b"\xff\xd8"

    # 6. Execute get_overwatch_view tool via execute_robot_tool
    ov_res = await execute_robot_tool(client.app, "get_overwatch_view", {"include_detections": True}, robot_id=robot_id)
    assert ov_res["ok"] is True
    assert ov_res["data"]["online"] is True
    assert "640x360" in ov_res["summary"]
