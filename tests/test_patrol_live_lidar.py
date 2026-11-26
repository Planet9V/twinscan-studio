"""Unit and API tests for live Standby LD19 LiDAR sector readout and patrol start-lidar bridge wiring."""

from __future__ import annotations

import asyncio
import inspect
import math
import time
import types
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

from src.api import routes_ai_vision
from src.app.config import Settings
from src.app.factory import create_app
from src.db.repository import InMemoryTwinRepository
from src.db.robot_ai_store import InMemoryRobotAiStore
from src.db.robot_store import InMemoryRobotStore
from src.lidar.ld19_parser import LidarPoint
from src.robot import ssh_manager
from src.robot.patrol_engine import NULL_SECTORS, RobotPatrolManager, compute_live_sectors_from_points


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
def client_and_robot() -> tuple[TestClient, str]:
    """Create an isolated TestClient with one registered PuppyPi ROS 2 robot."""
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
            "id": "puppypi-live-test",
            "name": "PuppyPi Test",
            "ip_address": "192.168.1.119",
            "ssh_user": "ubuntu",
            "ssh_password": "secret",
            "rosbridge_port": 9090,
            "video_port": 8080,
            "active_ros_distro": "ros2",
        }
    )
    with TestClient(app) as tc:
        yield tc, robot["id"]


def test_compute_live_sectors_from_points_maps_all_five_sectors() -> None:
    """Verify exact 5-sector angular binning, min-distance selection, out-of-range filtering, and rotation offset."""
    pts = [
        _pt(0.0, 1.42),       # front
        _pt(10.0, 1.15),      # front (closer -> wins)
        _pt(45.0, 0.88),      # front_left
        _pt(315.0, 1.75),     # -45° -> front_right
        _pt(95.0, 2.34),      # left
        _pt(260.0, 0.62),     # -100° -> right
        _pt(180.0, 0.30),     # rear (outside 5 front/side sectors)
        _pt(0.0, 0.02),       # too close (<0.05m) -> ignored
        _pt(0.0, 15.0),       # too far (>12.0m) -> ignored
    ]
    sectors = compute_live_sectors_from_points(pts)
    assert sectors == {
        "front": 1.15,
        "front_left": 0.88,
        "front_right": 1.75,
        "left": 2.34,
        "right": 0.62,
    }

    # Missing sectors cleanly return None
    partial = compute_live_sectors_from_points([_pt(5.0, 2.0)])
    assert partial == {
        "front": 2.0,
        "front_left": None,
        "front_right": None,
        "left": None,
        "right": None,
    }

    # Rotation offset shifts a 270° (-90°) return into front (0°) when offset=+90°
    rotated = compute_live_sectors_from_points([_pt(270.0, 1.25)], rotation_offset_deg=90.0)
    assert rotated["front"] == 1.25
    assert rotated["right"] is None


def test_patrol_status_standby_live_lidar_and_simulator_isolation(
    client_and_robot: tuple[TestClient, str],
) -> None:
    """Standby patrol status shows live sectors ONLY when robot_ros2 is connected & fresh, NEVER in simulator."""
    client, robot_id = client_and_robot
    rt = client.app.state.runtime

    # 1. Default simulator mode -> MUST be lidar_live=False and NULL_SECTORS
    rt.source_mode = "simulator"
    rt.robot_scan_connected = False
    r_sim = client.get(f"/api/robots/{robot_id}/patrol/status")
    assert r_sim.status_code == 200
    sim_body = r_sim.json()
    assert sim_body["active"] is False
    assert sim_body["lidar_live"] is False
    assert sim_body["sectors_m"] == NULL_SECTORS

    # 2. Live robot_ros2 connected with fresh raw LD19 points -> lidar_live=True & exact sectors_m
    rt.source_mode = "robot_ros2"
    rt.robot_scan_connected = True
    rt.latest_raw_points = [
        _pt(0.0, 0.95),
        _pt(40.0, 1.2),
        _pt(-40.0, 1.5),
        _pt(90.0, 2.1),
        _pt(-90.0, 0.75),
    ]
    rt._last_scan_mono = time.monotonic()

    r_live = client.get(f"/api/robots/{robot_id}/patrol/status")
    assert r_live.status_code == 200
    live_body = r_live.json()
    assert live_body["active"] is False
    assert live_body["lidar_live"] is True
    assert live_body["lidar_age_sec"] is not None
    assert live_body["lidar_age_sec"] <= 3.5
    assert live_body["sectors_m"] == {
        "front": 0.95,
        "front_left": 1.2,
        "front_right": 1.5,
        "left": 2.1,
        "right": 0.75,
    }

    # 3. Stale scan (>3.5s) -> falls back strictly to lidar_live=False + NULL_SECTORS
    rt._last_scan_mono = time.monotonic() - 5.0
    r_stale = client.get(f"/api/robots/{robot_id}/patrol/status")
    assert r_stale.status_code == 200
    assert r_stale.json()["lidar_live"] is False
    assert r_stale.json()["sectors_m"] == NULL_SECTORS

    # 4. Disconnected robot_ros2 -> lidar_live=False + NULL_SECTORS
    rt._last_scan_mono = time.monotonic()
    rt.robot_scan_connected = False
    r_disc = client.get(f"/api/robots/{robot_id}/patrol/status")
    assert r_disc.status_code == 200
    assert r_disc.json()["lidar_live"] is False
    assert r_disc.json()["sectors_m"] == NULL_SECTORS


def test_patrol_start_lidar_switches_runtime_to_robot_ros2(
    client_and_robot: tuple[TestClient, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /api/robots/{id}/patrol/start-lidar switches runtime to robot_ros2 and binds active_lidar_robot_id."""
    client, robot_id = client_and_robot
    rt = client.app.state.runtime
    bridge_calls: list[Dict[str, Any]] = []

    async def _fake_start_robot_lidar_node(**kwargs: Any) -> Dict[str, Any]:
        return {
            "ok": True,
            "device_present": True,
            "scan_active": True,
            "message": "LD19 /scan streaming cleanly",
        }

    async def _fake_start_bridge(
        robot_id: str,
        ip: str,
        rosbridge_port: int = 9090,
        ros_version: str = "ros2",
    ) -> None:
        rt.active_lidar_robot_id = robot_id
        bridge_calls.append(
            {
                "robot_id": robot_id,
                "ip": ip,
                "rosbridge_port": rosbridge_port,
                "ros_version": ros_version,
            }
        )

    monkeypatch.setattr(routes_ai_vision, "start_robot_lidar_node", _fake_start_robot_lidar_node)
    monkeypatch.setattr(rt, "start_robot_ros2_bridge", _fake_start_bridge)

    resp = client.post(f"/api/robots/{robot_id}/patrol/start-lidar")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert rt.source_mode == "robot_ros2"
    assert rt.simulator.simulate_moving_targets is False
    assert rt.active_lidar_robot_id == robot_id
    assert len(bridge_calls) == 1
    assert bridge_calls[0]["ip"] == "192.168.1.119"
    assert bridge_calls[0]["ros_version"] == "ros2"


@pytest.mark.asyncio
async def test_patrol_manager_warm_starts_from_verified_live_points(monkeypatch: pytest.MonkeyPatch) -> None:
    """RobotPatrolManager.start warm-starts immediately when get_lidar_points returns verified live robot points."""
    mgr = RobotPatrolManager()

    async def _fake_publish_velocity(*args: Any, **kwargs: Any) -> None:
        return None

    async def _idle_scan_subscriber(*args: Any, **kwargs: Any) -> None:
        try:
            await pytest.importorskip("asyncio").sleep(10)
        except Exception:
            return

    monkeypatch.setattr("src.robot.patrol_engine.publish_velocity", _fake_publish_velocity)
    monkeypatch.setattr(mgr, "_run_scan_subscriber", _idle_scan_subscriber)

    live_pts = [_pt(0.0, 1.8), _pt(45.0, 2.0), _pt(-45.0, 2.0)]
    status = await mgr.start(
        robot_id="puppypi-warm",
        ip="192.168.1.119",
        rosbridge_port=9090,
        ros_version="ros2",
        waypoints=[{"x": 1.0, "y": 0.0, "pause_sec": 0.5}],
        require_lidar=True,
        camera_avoidance=False,
        scan_wait_sec=0.1,
        get_lidar_points=lambda: live_pts,
    )
    try:
        assert status["active"] is True
        assert status["lidar_live"] is True
    finally:
        await mgr.stop("puppypi-warm")


def test_ssh_manager_uses_awk_cleanup_and_direct_ldlidar_binary() -> None:
    """Verify ssh_manager kills duplicate ldlidar via ps -eww + awk ($1!=self && $2!=self, no !/bash/) and execs binary."""
    src = inspect.getsource(ssh_manager)
    assert "pkill -x ldlidar_stl_ros2_node" not in src
    assert "pkill -f ldlidar_stl_ros2_node" not in src
    assert "!/bash/" not in src
    assert src.count("ps -eww -o pid,ppid,args") >= 4
    assert src.count("$1 != self && $2 != self && !/awk/ && /ldlidar_stl_ros2/") >= 4
    assert (
        src.count(
            "exec /home/ubuntu/third_party_ros2/third_party_ws/install/ldlidar_stl_ros2/lib/ldlidar_stl_ros2/ldlidar_stl_ros2_node --ros-args"
        )
        >= 2
    )


@pytest.mark.asyncio
async def test_patrol_continuous_live_fallback_prevents_false_lidar_lost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Patrol stays active and navigating via verified live-points callback even if direct /scan subscriber stalls."""
    mgr = RobotPatrolManager()
    vel_cmds: list[tuple[float, float]] = []
    fake_now = [1000.0]
    step_done = asyncio.Event()
    real_sleep = asyncio.sleep

    async def _fake_publish_velocity(ip: str, port: int, x: float, y: float, yaw: float, **kwargs: Any) -> None:
        vel_cmds.append((x, yaw))

    async def _idle_scan_subscriber(*args: Any, **kwargs: Any) -> None:
        never = asyncio.Event()
        await never.wait()

    async def _step_sleep(delay: float) -> None:
        fake_now[0] += max(0.05, delay)
        step_done.set()
        await real_sleep(0.001)

    fake_time_mod = types.SimpleNamespace(monotonic=lambda: fake_now[0])
    fake_asyncio_mod = types.SimpleNamespace(
        sleep=_step_sleep,
        create_task=asyncio.create_task,
        to_thread=asyncio.to_thread,
        CancelledError=asyncio.CancelledError,
        Task=asyncio.Task,
    )

    monkeypatch.setattr("src.robot.patrol_engine.publish_velocity", _fake_publish_velocity)
    monkeypatch.setattr("src.robot.patrol_engine.time", fake_time_mod)
    monkeypatch.setattr("src.robot.patrol_engine.asyncio", fake_asyncio_mod)
    monkeypatch.setattr(mgr, "_run_scan_subscriber", _idle_scan_subscriber)

    live_pts = [_pt(0.0, 2.2), _pt(45.0, 2.2), _pt(-45.0, 2.2)]
    await mgr.start(
        robot_id="puppypi-fallback",
        ip="192.168.1.119",
        rosbridge_port=9090,
        ros_version="ros2",
        waypoints=[{"x": 5.0, "y": 0.0, "pause_sec": 0.5}],
        require_lidar=True,
        camera_avoidance=False,
        scan_wait_sec=0.1,
        get_lidar_points=lambda: live_pts,
    )
    try:
        # Advance simulated patrol clock past 5.0s while live_pts stays fresh
        for _ in range(25):
            step_done.clear()
            await asyncio.wait_for(step_done.wait(), timeout=2.0)
        st = mgr.get_status("puppypi-fallback")
        assert st["active"] is True
        assert st["state"] == "navigating"
        assert st["lidar_live"] is True
        assert any(vx > 0.0 for vx, _ in vel_cmds)
    finally:
        await mgr.stop("puppypi-fallback")


@pytest.mark.asyncio
async def test_patrol_brief_lidar_gap_pauses_then_resumes_and_long_loss_halts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Brief 2s /scan gap holds zero velocity (paused_lidar_wait) and resumes; >4.5s loss halts (stopped_lidar_lost)."""
    mgr = RobotPatrolManager()
    zero_pubs: list[float] = []
    fake_now = [2000.0]
    points_enabled = [True]
    step_done = asyncio.Event()
    allow_next = asyncio.Event()
    real_sleep = asyncio.sleep

    async def _fake_publish_velocity(ip: str, port: int, x: float, y: float, yaw: float, **kwargs: Any) -> None:
        if x == 0.0 and yaw == 0.0:
            zero_pubs.append(fake_now[0])

    async def _idle_scan_subscriber(*args: Any, **kwargs: Any) -> None:
        never = asyncio.Event()
        await never.wait()

    async def _controlled_sleep(delay: float) -> None:
        step_done.set()
        await allow_next.wait()
        allow_next.clear()
        fake_now[0] += max(0.05, delay)
        await real_sleep(0)

    fake_time_mod = types.SimpleNamespace(monotonic=lambda: fake_now[0])
    fake_asyncio_mod = types.SimpleNamespace(
        sleep=_controlled_sleep,
        create_task=asyncio.create_task,
        to_thread=asyncio.to_thread,
        CancelledError=asyncio.CancelledError,
        Task=asyncio.Task,
    )

    monkeypatch.setattr("src.robot.patrol_engine.publish_velocity", _fake_publish_velocity)
    monkeypatch.setattr("src.robot.patrol_engine.time", fake_time_mod)
    monkeypatch.setattr("src.robot.patrol_engine.asyncio", fake_asyncio_mod)
    monkeypatch.setattr(mgr, "_run_scan_subscriber", _idle_scan_subscriber)

    async def _advance(steps: int) -> None:
        for _ in range(steps):
            await asyncio.wait_for(step_done.wait(), timeout=2.0)
            step_done.clear()
            allow_next.set()

    live_pts = [_pt(0.0, 2.5), _pt(45.0, 2.5), _pt(-45.0, 2.5)]
    await mgr.start(
        robot_id="puppypi-resilience",
        ip="192.168.1.119",
        rosbridge_port=9090,
        ros_version="ros2",
        waypoints=[{"x": 8.0, "y": 0.0, "pause_sec": 0.5}],
        require_lidar=True,
        camera_avoidance=False,
        scan_wait_sec=0.1,
        get_lidar_points=lambda: live_pts if points_enabled[0] else [],
    )
    try:
        # 1. Start navigating
        await _advance(2)
        await asyncio.wait_for(step_done.wait(), timeout=2.0)
        assert mgr.get_status("puppypi-resilience")["state"] == "navigating"

        # 2. Simulate brief ~2.0s Wi-Fi jitter gap (within 1.5s..4.5s pause window)
        points_enabled[0] = False
        await _advance(8)  # 8 * 0.25s = 2.0s since last scan
        await asyncio.wait_for(step_done.wait(), timeout=2.0)
        paused = mgr.get_status("puppypi-resilience")
        assert paused["active"] is True
        assert paused["state"] == "paused_lidar_wait"
        assert paused["last_command"] == {"vx_cms": 0.0, "yaw_rate_rads": 0.0}
        assert len(zero_pubs) >= 1

        # 3. /scan returns -> automatically resumes navigating!
        points_enabled[0] = True
        await _advance(2)
        await asyncio.wait_for(step_done.wait(), timeout=2.0)
        resumed = mgr.get_status("puppypi-resilience")
        assert resumed["active"] is True
        assert resumed["state"] == "navigating"
        assert resumed["lidar_live"] is True

        # 4. Simulate true sustained >4.5s loss -> safely halts as stopped_lidar_lost
        points_enabled[0] = False
        for _ in range(25):
            if mgr.get_status("puppypi-resilience")["state"] == "stopped_lidar_lost":
                break
            await asyncio.wait_for(step_done.wait(), timeout=2.0)
            step_done.clear()
            allow_next.set()
            await real_sleep(0.002)
        halted = mgr.get_status("puppypi-resilience")
        assert halted["active"] is False
        assert halted["state"] == "stopped_lidar_lost"
        assert halted["sectors_m"] == NULL_SECTORS
    finally:
        allow_next.set()
        await mgr.stop("puppypi-resilience")

