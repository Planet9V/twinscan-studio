"""Pytest suite for Kaizen P0/P1/P2 safety, accuracy, maintenance, and full-room GLB hardening."""

from __future__ import annotations

import asyncio
import json
import math
import struct
import time
import types
from typing import Any, Dict, List

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from src.api import routes_robots, routes_twin
from src.app import factory as app_factory
from src.app.config import Settings
from src.app.factory import _auto_attach_live_robot_lidar, create_app
from src.db.repository import InMemoryTwinRepository
from src.db.robot_ai_store import InMemoryRobotAiStore
from src.db.robot_store import InMemoryRobotStore
from src.lidar.ld19_parser import LidarPoint
from src.lidar.scene_reconstructor import build_relief_mesh_payload, export_combined_room_glb
from src.robot.explorer_engine import AutonomousExplorerManager


def _pt(angle_deg: float, distance_m: float) -> LidarPoint:
    rad = math.radians(angle_deg)
    return LidarPoint(
        angle_deg=angle_deg,
        distance_m=distance_m,
        intensity=200,
        x=distance_m * math.cos(rad),
        y=distance_m * math.sin(rad),
    )


def _sample_jpeg(color: tuple[int, int, int] = (70, 110, 160)) -> bytes:
    img = np.full((96, 128, 3), color, dtype=np.uint8)
    cv2.rectangle(img, (16, 16), (112, 80), (235, 195, 60), 2)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


@pytest.fixture()
def client_and_robot() -> tuple[TestClient, str]:
    """Create an isolated TestClient with one registered ROS 2 PuppyPi robot."""
    settings = Settings(database_url="", openrouter_api_key="", neo4j_uri="")
    robot_store = InMemoryRobotStore()
    app = create_app(
        settings=settings,
        repository=InMemoryTwinRepository(),
        robot_store=robot_store,
        robot_ai_store=InMemoryRobotAiStore(),
    )
    robot = robot_store.upsert_robot(
        {
            "id": "puppypi-kaizen",
            "name": "PuppyPi Kaizen",
            "ip_address": "192.168.1.119",
            "ssh_user": "ubuntu",
            "ssh_password": "secret",
            "rosbridge_port": 9090,
            "video_port": 8080,
            "active_ros_distro": "humble",
        }
    )
    with TestClient(app) as tc:
        yield tc, robot["id"]


def test_p0_1_estop_and_manual_controls_stop_autonomous_loops(
    client_and_robot: tuple[TestClient, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P0-1: Global E-STOP stops explorer_manager; velocity, action, and go-home preempt active autonomous loops."""
    client, robot_id = client_and_robot
    patrol_mgr = client.app.state.patrol_manager
    explorer_mgr = client.app.state.explorer_manager
    stop_calls: List[str] = []

    async def _fake_estop(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {"estop": True}

    async def _fake_vel(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {"sent": True}

    async def _fake_action(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {"sent": True}

    async def _fake_go_home(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {"sent": True}

    async def _track_patrol_stop(rid: str, **kwargs: Any) -> Dict[str, Any]:
        stop_calls.append(f"patrol:{rid}")
        patrol_mgr._status.setdefault(rid, {"active": False})["active"] = False
        return {"active": False}

    async def _track_explorer_stop(rid: str, **kwargs: Any) -> Dict[str, Any]:
        stop_calls.append(f"explorer:{rid}")
        explorer_mgr._status.setdefault(rid, {"active": False})["active"] = False
        return {"active": False}

    monkeypatch.setattr(routes_robots, "trigger_estop", _fake_estop)
    monkeypatch.setattr(routes_robots, "publish_velocity", _fake_vel)
    monkeypatch.setattr(routes_robots, "run_action", _fake_action)
    monkeypatch.setattr(routes_robots, "call_go_home", _fake_go_home)
    monkeypatch.setattr(patrol_mgr, "stop", _track_patrol_stop)
    monkeypatch.setattr(explorer_mgr, "stop", _track_explorer_stop)

    # 1. E-STOP always stops BOTH patrol and explorer
    explorer_mgr._status[robot_id] = {"robot_id": robot_id, "active": True, "state": "exploring_transit"}
    r_estop = client.post(f"/api/robots/{robot_id}/estop")
    assert r_estop.status_code == 200
    assert f"patrol:{robot_id}" in stop_calls
    assert f"explorer:{robot_id}" in stop_calls

    # 2. Manual velocity preempts active explorer
    stop_calls.clear()
    explorer_mgr._status[robot_id] = {"robot_id": robot_id, "active": True, "state": "exploring_transit"}
    assert client.post(f"/api/robots/{robot_id}/control/velocity", json={"x": 8.0, "y": 0.0, "yaw_rate": 0.0}).status_code == 200
    assert stop_calls == [f"explorer:{robot_id}"]

    # 3. Manual action preempts active patrol
    stop_calls.clear()
    patrol_mgr._status[robot_id] = {"robot_id": robot_id, "active": True, "state": "navigating"}
    assert client.post(f"/api/robots/{robot_id}/control/action", json={"name": "wave"}).status_code == 200
    assert stop_calls == [f"patrol:{robot_id}"]

    # 4. Manual go-home preempts both active loops
    stop_calls.clear()
    patrol_mgr._status[robot_id] = {"robot_id": robot_id, "active": True, "state": "navigating"}
    explorer_mgr._status[robot_id] = {"robot_id": robot_id, "active": True, "state": "exploring_transit"}
    assert client.post(f"/api/robots/{robot_id}/control/go-home").status_code == 200
    assert set(stop_calls) == {f"patrol:{robot_id}", f"explorer:{robot_id}"}


def test_p0_2_patrol_and_explorer_mutual_exclusion(
    client_and_robot: tuple[TestClient, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P0-2: Starting Explorer stops active Patrol, and starting Patrol stops active Explorer."""
    client, robot_id = client_and_robot
    patrol_mgr = client.app.state.patrol_manager
    explorer_mgr = client.app.state.explorer_manager
    events: List[str] = []

    async def _track_patrol_stop(robot_id: str, **kwargs: Any) -> Dict[str, Any]:
        events.append("stop_patrol")
        patrol_mgr._status[robot_id] = {"active": False, "state": "stopped"}
        return {"active": False}

    async def _track_explorer_stop(robot_id: str, **kwargs: Any) -> Dict[str, Any]:
        events.append("stop_explorer")
        explorer_mgr._status[robot_id] = {"active": False, "state": "stopped"}
        return {"active": False}

    async def _fake_patrol_start(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        events.append("start_patrol")
        return {"active": True, "state": "starting"}

    async def _fake_explorer_start(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        events.append("start_explorer")
        return {"active": True, "state": "capturing_multi_angle"}

    monkeypatch.setattr(patrol_mgr, "stop", _track_patrol_stop)
    monkeypatch.setattr(explorer_mgr, "stop", _track_explorer_stop)
    monkeypatch.setattr(patrol_mgr, "start", _fake_patrol_start)
    monkeypatch.setattr(explorer_mgr, "start", _fake_explorer_start)

    # Active patrol -> starting explorer stops patrol first
    patrol_mgr._status[robot_id] = {"active": True, "state": "navigating"}
    r1 = client.post(f"/api/robots/{robot_id}/explore/start", json={"require_lidar": False, "announce_voice": False})
    assert r1.status_code == 200
    assert events == ["stop_patrol", "start_explorer"]

    # Active explorer -> starting patrol stops explorer first
    events.clear()
    explorer_mgr._status[robot_id] = {"active": True, "state": "exploring_transit"}
    r2 = client.post(
        f"/api/robots/{robot_id}/patrol/start",
        json={"waypoints": [{"x": 1.0, "y": 0.0}], "require_lidar": False, "announce_voice": False},
    )
    assert r2.status_code == 200
    assert events == ["stop_explorer", "start_patrol"]


@pytest.mark.asyncio
async def test_p0_3_explorer_mid_transit_lidar_dropout_pauses_then_halts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P0-3: Mid-transit LD19 dropout pauses at zero velocity (<=4.5s) then halts safely (>4.5s) with pitch 0°."""
    mgr = AutonomousExplorerManager()
    fake_now = [3000.0]
    real_sleep = asyncio.sleep
    points_live = [True]
    seen_paused = [False]
    pitch_resets: List[float] = []

    async def _fake_vel(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {"sent": True}

    async def _fake_pose(ip: str, port: int, pitch: float = 0.0, **kwargs: Any) -> Dict[str, Any]:
        pitch_resets.append(round(math.degrees(pitch), 1))
        return {"sent": True}

    async def _fake_sleep(delay: float) -> None:
        fake_now[0] += max(0.25, delay)
        if mgr.get_status("puppypi-drop")["state"] == "paused_lidar_wait":
            seen_paused[0] = True
        await real_sleep(0.001)

    fake_time_mod = types.SimpleNamespace(monotonic=lambda: fake_now[0])
    fake_asyncio_mod = types.SimpleNamespace(
        sleep=_fake_sleep,
        create_task=asyncio.create_task,
        to_thread=asyncio.to_thread,
        CancelledError=asyncio.CancelledError,
        Task=asyncio.Task,
    )

    monkeypatch.setattr("src.robot.explorer_engine.publish_velocity", _fake_vel)
    monkeypatch.setattr("src.robot.explorer_engine.publish_pose", _fake_pose)
    monkeypatch.setattr("src.robot.explorer_engine.time", fake_time_mod)
    monkeypatch.setattr("src.robot.explorer_engine.asyncio", fake_asyncio_mod)

    live_pts = [_pt(float(a), 2.5) for a in range(0, 360, 15)]

    async def _fake_capture(x: float, y: float, yaw_deg: float, pitch_deg: float) -> Dict[str, Any]:
        # Drop LiDAR right as we finish station 1 and enter transit to far dark zone!
        points_live[0] = False
        return {"panels": 1, "objects": 0}

    await mgr.start(
        robot_id="puppypi-drop",
        ip="192.168.1.119",
        rosbridge_port=9090,
        ros_version="ros2",
        max_iterations=3,
        target_coverage_pct=95.0,
        capture_mode="quick_3",
        require_lidar=True,
        capture_station_fn=_fake_capture,
        get_lidar_points=lambda: live_pts if points_live[0] else [],
        get_dark_zones=lambda: [{"id": "dz-1", "label": "Dark Alcove", "priority_score": 90, "nbv_x": 2.5, "nbv_y": 0.0}],
        get_coverage_pct=lambda: 40.0,
        get_battery_v=lambda: 7.8,
        tick_sleep_s=0.5,
        settle_sleep_s=0.0,
        max_transit_ticks=30,
    )

    for _ in range(150):
        st = mgr.get_status("puppypi-drop")
        if not st["active"] and st["state"] == "blocked_no_lidar":
            break
        await real_sleep(0.01)

    final = mgr.get_status("puppypi-drop")
    assert seen_paused[0] is True
    assert final["active"] is False
    assert final["state"] == "blocked_no_lidar"
    assert ">4.5s" in (final["error"] or "")
    assert final["current_pitch_deg"] == 0.0
    assert pitch_resets and pitch_resets[-1] == 0.0


@pytest.mark.asyncio
async def test_p1_1_auto_attach_live_robot_lidar_on_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    """P1-1: Auto-attach switches runtime to robot_ros2 with 90° default rotation when ROSBridge TCP is reachable."""
    settings = Settings(database_url="", openrouter_api_key="", neo4j_uri="")
    robot_store = InMemoryRobotStore()
    robot = robot_store.upsert_robot(
        {
            "id": "puppypi-auto",
            "name": "PuppyPi Auto",
            "ip_address": "192.168.1.119",
            "rosbridge_port": 9090,
            "active_ros_distro": "humble",
        }
    )
    app = create_app(
        settings=settings,
        repository=InMemoryTwinRepository(),
        robot_store=robot_store,
        robot_ai_store=InMemoryRobotAiStore(),
    )
    rt = app.state.runtime
    bridge_calls: List[Dict[str, Any]] = []

    async def _fake_probe(ip: str, port: int, timeout_s: float = 1.5) -> bool:
        return ip == "192.168.1.119" and port == 9090

    async def _fake_start_bridge(**kwargs: Any) -> None:
        bridge_calls.append(kwargs)

    monkeypatch.setattr(app_factory, "_probe_tcp_port", _fake_probe)
    monkeypatch.setattr(rt, "start_robot_ros2_bridge", _fake_start_bridge)

    attached = await _auto_attach_live_robot_lidar(app)
    assert attached is True
    assert rt.source_mode == "robot_ros2"
    assert rt.active_lidar_robot_id == robot["id"]
    assert rt.filter_config.rotation_offset_deg == 90.0
    assert len(bridge_calls) == 1
    assert bridge_calls[0]["ros_version"] == "ros2"


@pytest.mark.asyncio
async def test_p1_2_imu_yaw_fusion_in_explorer_and_capture_360(
    client_and_robot: tuple[TestClient, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P1-2: Live IMU yaw anchors and fuses into Explorer yaw and capture-360 panel poses (with nominal fallback)."""
    # Part A: Explorer live IMU yaw fusion
    mgr = AutonomousExplorerManager()
    captured_yaws: List[float] = []

    async def _noop(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {"sent": True}

    monkeypatch.setattr("src.robot.explorer_engine.publish_velocity", _noop)
    monkeypatch.setattr("src.robot.explorer_engine.publish_pose", _noop)
    monkeypatch.setattr("src.robot.explorer_engine.call_go_home", _noop)

    imu_val = [100.0]

    async def _cap(x: float, y: float, yaw_deg: float, pitch_deg: float) -> Dict[str, Any]:
        captured_yaws.append(yaw_deg)
        imu_val[0] = 142.0  # +42° real IMU rotation before next station
        return {"panels": 1, "objects": 0}

    live_pts = [_pt(float(a), 2.5) for a in range(0, 360, 15)]
    await mgr.start(
        robot_id="puppypi-imu",
        ip="192.168.1.119",
        max_iterations=2,
        target_coverage_pct=99.0,
        capture_mode="quick_3",
        require_lidar=True,
        capture_station_fn=_cap,
        get_lidar_points=lambda: live_pts,
        get_dark_zones=lambda: [{"id": "dz-1", "label": "Corner", "priority_score": 80, "nbv_x": 0.6, "nbv_y": 0.0}],
        get_coverage_pct=lambda: 50.0,
        get_battery_v=lambda: 7.9,
        get_imu_yaw_deg=lambda: imu_val[0],
        tick_sleep_s=0.01,
        settle_sleep_s=0.0,
        max_transit_ticks=10,
    )
    for _ in range(100):
        if not mgr.get_status("puppypi-imu")["active"]:
            break
        await asyncio.sleep(0.02)
    # Station 1 starts at anchored 0°, Station 2 starts at IMU-fused +42°!
    assert captured_yaws[0] == 0.0
    assert any(abs(y - 42.0) < 1.0 for y in captured_yaws[3:])

    # Part B: capture-360 live IMU yaw fusion
    client, robot_id = client_and_robot
    rt = client.app.state.runtime
    space_id = rt.active_space_id
    imu_steps = [10.0, 108.0, 205.0, 300.0]
    step_counter = [0]
    rt.robot_pose["live"] = True
    rt.robot_pose["yaw_deg"] = imu_steps[0]

    async def _fake_turn(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        # Advance IMU only when non-zero yaw_rate turn command is sent
        if float(kwargs.get("yaw_rate", 0.0)) != 0.0:
            step_counter[0] = min(len(imu_steps) - 1, step_counter[0] + 1)
            rt.robot_pose["yaw_deg"] = imu_steps[step_counter[0]]
        return {"sent": True}

    async def _fake_capture_frame(*args: Any, **kwargs: Any) -> tuple[bytes, str]:
        return _sample_jpeg(), "/image_raw"

    monkeypatch.setattr(routes_twin, "publish_velocity", _fake_turn)
    monkeypatch.setattr("src.api.routes_twin.capture_live_camera_frame", _fake_capture_frame)

    resp = client.post(
        f"/api/spaces/{space_id}/reconstruct/capture-360",
        json={"robot_id": robot_id, "steps": 4, "turn_duration_s": 0.1, "settle_s": 0.0, "resolution": "low"},
    )
    assert resp.status_code == 200
    panels = resp.json()["panels"]
    assert len(panels) == 4
    yaws = [p["pose"]["yaw_deg"] for p in panels]
    assert yaws[0] == 0.0
    assert yaws[1] == 98.0
    assert yaws[2] == 195.0
    assert yaws[3] == 290.0


def test_p1_3_clean_stale_logs_endpoint(
    client_and_robot: tuple[TestClient, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P1-3: POST /api/robots/{id}/maintenance/clean-logs returns pruned count, MB reclaimed, and disk use."""
    client, robot_id = client_and_robot

    async def _fake_clean_logs(ip: str, user: str, password: str, timeout: float = 15.0) -> Dict[str, Any]:
        assert ip == "192.168.1.119"
        return {
            "ok": True,
            "files_removed": 14,
            "reclaimed_mb": 42.5,
            "disk_use_pct": "61%",
            "detail": "Removed 14 stale ROS/LiDAR log(s) (>24h), reclaimed 42.50 MB (disk 61%).",
        }

    monkeypatch.setattr(routes_robots, "clean_robot_stale_logs", _fake_clean_logs)
    resp = client.post(f"/api/robots/{robot_id}/maintenance/clean-logs")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["files_removed"] == 14
    assert body["reclaimed_mb"] == 42.5
    assert body["disk_use_pct"] == "61%"


def test_p2_2_combined_full_room_glb_export_and_route(client_and_robot: tuple[TestClient, str]) -> None:
    """P2-2: export_combined_room_glb and GET /api/spaces/{id}/reconstruct/export-room.glb emit valid multi-mesh GLB."""
    client, robot_id = client_and_robot
    rt = client.app.state.runtime
    ai_store = client.app.state.robot_ai_store
    space_id = rt.active_space_id

    # Empty space -> 404
    assert client.get(f"/api/spaces/{space_id}/reconstruct/export-room.glb").status_code == 404

    depth = np.full((36, 48), 2.0, dtype=np.float32)
    m1 = build_relief_mesh_payload(depth, None, {"x": 0.0, "y": 0.0, "z": 0.22, "yaw_deg": 0.0, "pitch_deg": 0.0, "roll_deg": 0.0}, resolution="low")
    m2 = build_relief_mesh_payload(depth, None, {"x": 0.0, "y": 0.0, "z": 0.22, "yaw_deg": 90.0, "pitch_deg": 0.0, "roll_deg": 0.0}, resolution="low")
    jpg1 = _sample_jpeg((60, 120, 180))
    jpg2 = _sample_jpeg((140, 80, 90))
    norm1 = _sample_jpeg((128, 128, 255))

    # Direct unit test of export_combined_room_glb
    direct_glb = export_combined_room_glb(
        [
            {"label": "North Wall", "mesh": m1["mesh"], "jpeg_bytes": jpg1, "normal_jpeg_bytes": norm1},
            {"label": "East Wall", "mesh": m2["mesh"], "jpeg_bytes": jpg2},
        ]
    )
    assert direct_glb[:4] == b"glTF"
    magic, version, total_len = struct.unpack("<4sII", direct_glb[:12])
    assert magic == b"glTF" and version == 2 and total_len == len(direct_glb)
    json_len, json_type = struct.unpack("<II", direct_glb[12:20])
    assert json_type == 0x4E4F534A
    gltf_json = json.loads(direct_glb[20 : 20 + json_len].decode("utf-8"))
    assert len(gltf_json["meshes"]) == 2
    assert len(gltf_json["nodes"]) == 2
    assert len(gltf_json["materials"]) == 2
    assert len(gltf_json["images"]) == 3  # 2 baseColor + 1 normalTexture
    assert "normalTexture" in gltf_json["materials"][0]

    # Route test: store two panels in space and download combined room GLB
    t1 = rt.repo.store_file("p1.jpg", "image/jpeg", jpg1, category="scene_texture", space_id=space_id)
    n1 = rt.repo.store_file("p1n.jpg", "image/jpeg", norm1, category="scene_normal", space_id=space_id)
    t2 = rt.repo.store_file("p2.jpg", "image/jpeg", jpg2, category="scene_texture", space_id=space_id)
    ai_store.save_scene_panel({"space_id": space_id, "robot_id": robot_id, "label": "North Wall", "texture_file_id": t1["id"], "normal_map_file_id": n1["id"], "mesh": m1["mesh"]})
    ai_store.save_scene_panel({"space_id": space_id, "robot_id": robot_id, "label": "East Wall", "texture_file_id": t2["id"], "mesh": m2["mesh"]})

    resp = client.get(f"/api/spaces/{space_id}/reconstruct/export-room.glb")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "model/gltf-binary"
    assert "-room.glb" in resp.headers.get("content-disposition", "")
    assert resp.content[:4] == b"glTF"
