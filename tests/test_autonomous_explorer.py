"""Unit and FastAPI integration tests for Stage 3 Autonomous Frontier Explorer & Low-Battery RTH."""

from __future__ import annotations

import asyncio
import math
import time
from typing import Any, Dict, List

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from src.api import routes_ai_vision
from src.app.config import Settings
from src.app.factory import create_app
from src.db.repository import InMemoryTwinRepository
from src.db.robot_ai_store import InMemoryRobotAiStore
from src.db.robot_store import InMemoryRobotStore
from src.lidar.dark_zones import SpatialDarkZone
from src.lidar.ld19_parser import LidarPoint
from src.robot.explorer_engine import (
    AutonomousExplorerManager,
    build_capture_pose_schedule,
    compute_battery_pct_2s,
    compute_room_coverage_pct,
    select_next_dark_zone_frontier,
)


def _pt(angle_deg: float, distance_m: float) -> LidarPoint:
    rad = math.radians(angle_deg)
    return LidarPoint(
        angle_deg=angle_deg,
        distance_m=distance_m,
        intensity=200,
        x=distance_m * math.cos(rad),
        y=distance_m * math.sin(rad),
    )


def _sample_jpeg() -> bytes:
    img = np.full((120, 160, 3), 80, dtype=np.uint8)
    cv2.rectangle(img, (25, 25), (135, 95), (210, 120, 40), 2)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


@pytest.fixture()
def client_and_robot() -> tuple[TestClient, str]:
    """Create an isolated FastAPI TestClient with a registered PuppyPi ROS 2 robot."""
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
            "id": "puppypi-explore-test",
            "name": "PuppyPi Explorer",
            "ip_address": "192.168.1.119",
            "ssh_user": "ubuntu",
            "ssh_password": "secret",
            "rosbridge_port": 9090,
            "video_port": 8080,
            "active_ros_distro": "ros2",
            "battery_mv": 7800,
        }
    )
    with TestClient(app) as tc:
        yield tc, robot["id"]


def test_battery_pct_schedule_and_frontier_selection() -> None:
    """Verify 2S LiPo battery mapping, all 3 pose schedules, and dark-zone priority/visited exclusion."""
    assert compute_battery_pct_2s(None) is None
    assert compute_battery_pct_2s(6.4) == 0
    assert compute_battery_pct_2s(6.0) == 0
    assert compute_battery_pct_2s(7.4) == 50
    assert compute_battery_pct_2s(8.4) == 100
    assert compute_battery_pct_2s(8.8) == 100

    assert build_capture_pose_schedule("quick_3") == [(0.0, 0.0), (-45.0, 0.0), (45.0, 0.0)]
    assert build_capture_pose_schedule("level_360") == [(i * 60.0, 0.0) for i in range(6)]
    multi = build_capture_pose_schedule("multi_pitch")
    assert len(multi) == 8
    assert multi[:3] == [(0.0, -10.0), (0.0, 0.0), (0.0, 10.0)]

    dz_high_visited = SpatialDarkZone(
        id="dz-1",
        kind="occlusion_shadow",
        label="Visited Corner",
        centroid_x=1.0,
        centroid_y=0.0,
        area_m2=1.2,
        priority_score=95,
        nbv_x=1.0,
        nbv_y=0.0,
        nbv_yaw_deg=45.0,
        polygon=[[0.8, -0.2], [1.2, -0.2], [1.2, 0.2], [0.8, 0.2]],
        recommended_action="Scan visited corner",
    )
    dz_mid_dict = {
        "id": "dz-2",
        "kind": "unidentified_cluster",
        "label": "Back Shelf",
        "centroid_x": 2.4,
        "centroid_y": 1.1,
        "area_m2": 0.9,
        "priority_score": 82,
        "next_best_view": {"x": 2.1, "y": 0.9, "yaw_deg": 30.0},
    }
    dz_low = SpatialDarkZone(
        id="dz-3",
        kind="occlusion_shadow",
        label="Far Alcove",
        centroid_x=-2.0,
        centroid_y=-1.5,
        area_m2=0.5,
        priority_score=40,
        nbv_x=-1.8,
        nbv_y=-1.3,
        nbv_yaw_deg=210.0,
        polygon=[],
        recommended_action="Scan alcove",
    )

    picked = select_next_dark_zone_frontier(
        dark_zones=[dz_low, dz_high_visited, dz_mid_dict],
        visited_xy=[(0.0, 0.0), (1.05, 0.05)],
        current_xy=(0.0, 0.0),
        min_sep_m=0.55,
    )
    assert picked is not None
    assert picked["id"] == "dz-2"
    assert picked["nbv_x"] == 2.1
    assert picked["nbv_y"] == 0.9

    # Once all frontiers are visited, returns None
    none_left = select_next_dark_zone_frontier(
        dark_zones=[dz_high_visited],
        visited_xy=[(1.0, 0.0)],
        current_xy=(0.0, 0.0),
        min_sep_m=0.55,
    )
    assert none_left is None

    # Coverage metric calculation
    cov = compute_room_coverage_pct({"area_m2": 10.0}, [dz_high_visited], panels_captured=2)
    assert cov == 88.0


@pytest.mark.asyncio
async def test_explorer_multi_pitch_capture_and_low_battery_rth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Full mocked run: multi-pitch capture -> panels & objects increment -> low battery (<7.1V) triggers RTH -> parked_home."""
    mgr = AutonomousExplorerManager()
    vel_log: List[tuple[float, float]] = []
    pitch_log: List[float] = []
    go_home_calls: List[str] = []
    announcements: List[str] = []

    async def _fake_vel(ip: str, port: int, x: float, y: float, yaw: float, **kwargs: Any) -> Dict[str, Any]:
        vel_log.append((x, yaw))
        return {"sent": True}

    async def _fake_pose(ip: str, port: int, pitch: float = 0.0, **kwargs: Any) -> Dict[str, Any]:
        pitch_log.append(round(math.degrees(pitch), 1))
        return {"sent": True}

    async def _fake_go_home(ip: str, port: int = 9090, **kwargs: Any) -> Dict[str, Any]:
        go_home_calls.append(ip)
        return {"sent": True}

    monkeypatch.setattr("src.robot.explorer_engine.publish_velocity", _fake_vel)
    monkeypatch.setattr("src.robot.explorer_engine.publish_pose", _fake_pose)
    monkeypatch.setattr("src.robot.explorer_engine.call_go_home", _fake_go_home)

    live_pts = [_pt(float(a), 2.5) for a in range(0, 360, 15)]
    capture_count = [0]
    battery_v = [7.75]

    async def _fake_capture(x: float, y: float, yaw_deg: float, pitch_deg: float) -> Dict[str, Any]:
        capture_count[0] += 1
        # After capturing 3 angles at station 1, simulate 2S LiPo dropping below 7.1V threshold!
        if capture_count[0] >= 3:
            battery_v[0] = 6.95
        return {"panels": 1, "objects": 2, "apriltag_home_seen": False}

    async def _fake_announce(msg: str) -> None:
        announcements.append(msg)

    await mgr.start(
        robot_id="puppypi-rth-sim",
        ip="192.168.1.119",
        rosbridge_port=9090,
        ros_version="ros2",
        space_id="space-lab",
        max_iterations=4,
        target_coverage_pct=95.0,
        capture_mode="multi_pitch",
        quality_preset="balanced",
        rth_battery_v=7.1,
        require_lidar=True,
        capture_station_fn=_fake_capture,
        get_lidar_points=lambda: live_pts,
        get_dark_zones=lambda: [
            {"id": "dz-far", "label": "Far Corner", "priority_score": 90, "nbv_x": 1.8, "nbv_y": 0.0, "area_m2": 1.5}
        ],
        get_coverage_pct=lambda: 50.0,
        get_battery_v=lambda: battery_v[0],
        announce_fn=_fake_announce,
        tick_sleep_s=0.01,
        settle_sleep_s=0.0,
        max_transit_ticks=15,
    )

    # Wait briefly for explorer task to finish RTH & park cleanly
    for _ in range(100):
        st = mgr.get_status("puppypi-rth-sim")
        if not st["active"] and st["state"] == "parked_home":
            break
        await asyncio.sleep(0.02)

    final_st = mgr.get_status("puppypi-rth-sim")
    assert final_st["active"] is False
    assert final_st["state"] == "parked_home"
    assert final_st["panels_captured"] == 3
    assert final_st["objects_identified"] == 6
    assert final_st["battery_v"] == 6.95
    assert final_st["battery_pct"] == compute_battery_pct_2s(6.95)
    assert final_st["current_pitch_deg"] == 0.0
    assert len(go_home_calls) == 1
    # Pitch tilted down (-10°), level (0°), up (+10°), and restored back to 0°!
    assert -10.0 in pitch_log
    assert 10.0 in pitch_log
    assert pitch_log[-1] == 0.0
    # Final velocity command was zero
    assert vel_log[-1] == (0.0, 0.0)
    assert any("Battery low (6.95V)" in msg for msg in announcements)


def test_explorer_fastapi_routes_status_start_rth_and_stop(
    client_and_robot: tuple[TestClient, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify all 4 /api/robots/{id}/explore/* endpoints, idle enrichment, blocked_no_lidar, RTH, and stop."""
    client, robot_id = client_and_robot
    rt = client.app.state.runtime

    async def _noop_vel(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {"sent": True}

    async def _noop_pose(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {"sent": True}

    async def _noop_go_home(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {"sent": True}

    async def _fake_frame(robot: Dict[str, Any]) -> bytes:
        return _sample_jpeg()

    monkeypatch.setattr("src.robot.explorer_engine.publish_velocity", _noop_vel)
    monkeypatch.setattr("src.robot.explorer_engine.publish_pose", _noop_pose)
    monkeypatch.setattr("src.robot.explorer_engine.call_go_home", _noop_go_home)
    monkeypatch.setattr(routes_ai_vision, "_fetch_live_frame_bytes", _fake_frame)

    # 1. Idle GET /explore/status enriches live battery, coverage, dark zones, and lidar_live
    rt.source_mode = "simulator"
    rt.robot_scan_connected = False
    rt.robot_pose["battery_v"] = 7.62
    r_idle = client.get(f"/api/robots/{robot_id}/explore/status")
    assert r_idle.status_code == 200
    idle = r_idle.json()
    assert idle["state"] == "idle"
    assert idle["battery_v"] == 7.62
    assert idle["battery_pct"] == compute_battery_pct_2s(7.62)
    assert idle["lidar_live"] is False

    # 2. Start with require_lidar=True while LiDAR offline -> blocked_no_lidar
    r_blk = client.post(
        f"/api/robots/{robot_id}/explore/start",
        json={"require_lidar": True, "announce_voice": False, "capture_mode": "quick_3"},
    )
    assert r_blk.status_code == 200
    assert r_blk.json()["state"] == "blocked_no_lidar"
    assert r_blk.json()["active"] is False

    # 3. Connect live robot_ros2 LD19 scan, start explorer, trigger RTH, then stop safely
    rt.source_mode = "robot_ros2"
    rt.robot_scan_connected = True
    rt._last_scan_mono = time.monotonic()
    rt.latest_raw_points = [_pt(float(a), 2.4) for a in range(0, 360, 15)]

    r_start = client.post(
        f"/api/robots/{robot_id}/explore/start",
        json={
            "max_iterations": 2,
            "target_coverage_pct": 95,
            "capture_mode": "quick_3",
            "quality_preset": "fast",
            "rth_battery_v": 7.1,
            "announce_voice": False,
            "require_lidar": True,
        },
    )
    assert r_start.status_code == 200
    started = r_start.json()
    assert started["robot_id"] == robot_id
    assert started["lidar_live"] is True

    r_rth = client.post(f"/api/robots/{robot_id}/explore/rth")
    assert r_rth.status_code == 200
    assert any("RTH" in ev["message"] for ev in r_rth.json()["event_log"])

    r_stop = client.post(f"/api/robots/{robot_id}/explore/stop")
    assert r_stop.status_code == 200
    stopped = r_stop.json()
    assert stopped["active"] is False
    assert stopped["state"] == "stopped"
    assert stopped["current_pitch_deg"] == 0.0
