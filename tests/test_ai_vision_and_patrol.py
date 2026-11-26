"""Unit and API tests for Offloaded AI Vision Studio, Known People pgvector Registry, and Autonomous VFH Patrol."""

from __future__ import annotations

import math
from unittest.mock import AsyncMock, patch

import cv2
import numpy as np
from fastapi.testclient import TestClient

from src.app.config import Settings
from src.app.factory import create_app
from src.db.repository import InMemoryTwinRepository
from src.db.robot_ai_store import InMemoryRobotAiStore
from src.db.robot_store import InMemoryRobotStore
from src.robot.patrol_engine import (
    RobotPatrolManager,
    compute_vfh_avoidance,
    detect_front_camera_obstacle,
)
from src.vision.robot_ai_vision import (
    RobotAiVisionEngine,
    compute_follow_pd_command,
    compute_line_centroid_and_steer,
)


def _synthetic_jpeg(color_bgr: tuple[int, int, int] = (40, 120, 210), stripe_x: int | None = None) -> bytes:
    """Create a synthetic 160x120 BGR image encoded as JPEG for deterministic vision tests."""
    img = np.full((120, 160, 3), color_bgr, dtype=np.uint8)
    if stripe_x is not None:
        cv2.rectangle(img, (stripe_x - 10, 60), (stripe_x + 10, 119), (10, 10, 10), -1)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


def _make_test_client() -> tuple[TestClient, str]:
    settings = Settings(database_url="", neo4j_uri="", openrouter_api_key="")
    repo = InMemoryTwinRepository()
    robot_store = InMemoryRobotStore()
    ai_store = InMemoryRobotAiStore()
    app = create_app(settings=settings, repository=repo, robot_store=robot_store, robot_ai_store=ai_store)
    robot = robot_store.upsert_robot(
        {
            "ip_address": "192.168.1.119",
            "name": "PuppyPi Vision",
            "model": "Hiwonder PuppyPi Pro",
            "active_ros_distro": "ROS2 Humble",
            "ssh_user": "pi",
            "rosbridge_port": 9090,
            "video_port": 8080,
        },
        ssh_password="raspberrypi",
    )
    return TestClient(app), robot["id"]


def test_in_memory_robot_ai_store_people_embeddings_routes_and_logs() -> None:
    """Verify people CRUD, 128-D cosine similarity matching, patrol routes, and voice logs."""
    store = InMemoryRobotAiStore()
    store.initialize()

    alice = store.create_person({"name": "Alice", "role": "Owner", "greeting_phrase": "Welcome back Alice!"})
    bob = store.create_person({"name": "Bob", "role": "Engineer"})

    vec_a = [1.0] + [0.0] * 127
    vec_b = [0.0, 1.0] + [0.0] * 126
    store.add_face_embedding(alice["id"], vec_a, source_file_id="f-alice")
    store.add_face_embedding(bob["id"], vec_b, source_file_id="f-bob")

    match_a = store.match_face_embedding([0.99, 0.05] + [0.0] * 126, threshold=0.363)
    assert match_a is not None
    assert match_a["person"]["id"] == alice["id"]
    assert match_a["similarity"] > 0.95

    no_match = store.match_face_embedding([0.0, 0.0, 1.0] + [0.0] * 125, threshold=0.363)
    assert no_match is None

    updated = store.update_person(alice["id"], {"greet_action": "shake_hands.d6ac"})
    assert updated is not None and updated["greet_action"] == "shake_hands.d6ac"
    assert updated["embedding_count"] == 1

    route = store.create_patrol_route(
        "r-1",
        {"name": "Lab Perimeter", "waypoints": [{"x": 1.0, "y": 0.0}, {"x": 1.0, "y": 1.0}]},
    )
    assert len(store.list_patrol_routes("r-1")) == 1
    assert store.get_patrol_route(route["id"]) is not None
    assert store.delete_patrol_route(route["id"]) is True

    store.record_voice_log("r-1", "in", "sit down", "pose:sit", "Sitting down.")
    logs = store.list_voice_logs("r-1")
    assert len(logs) == 1 and logs[0]["action_taken"] == "pose:sit"

    assert store.delete_person(alice["id"]) is True
    assert store.match_face_embedding(vec_a, threshold=0.363) is None


def test_line_centroid_and_follow_pd_safety_clamps() -> None:
    """Verify Line Follow v2 centroid steering and Click-to-Track LiDAR hard-stop safety."""
    # White floor with black vertical line on the RIGHT side (x=130 of 160 -> positive error -> negative yaw turn right)
    img = np.full((120, 160, 3), (240, 240, 240), dtype=np.uint8)
    cv2.rectangle(img, (122, 60), (140, 119), (5, 5, 5), -1)
    lf = compute_line_centroid_and_steer(img, line_color="black")
    assert lf["found"] is True
    assert lf["error"] > 0.2
    assert lf["yaw_rate_rads"] < 0.0
    assert lf["vx_cms"] > 0.0

    # Follow target far away (small bbox) with clear LiDAR -> moves forward
    cmd_clear = compute_follow_pd_command([0.45, 0.45, 0.55, 0.55], lidar_front_m=1.8, lidar_stop_m=0.35)
    assert cmd_clear["vx_cms"] > 0.0
    assert cmd_clear["blocked_by_lidar"] is False

    # Same small bbox but LD19 LiDAR sees obstacle at 0.25m (< 0.35m) -> HARD STOP forward velocity!
    cmd_blocked = compute_follow_pd_command([0.45, 0.45, 0.55, 0.55], lidar_front_m=0.25, lidar_stop_m=0.35)
    assert cmd_blocked["vx_cms"] == 0.0
    assert cmd_blocked["blocked_by_lidar"] is True


def test_vfh_obstacle_avoidance_all_cases() -> None:
    """Verify 5-sector LiDAR VFH avoidance for clear path, front obstacle, visual obstacle, and trapped rotation."""
    ang_min = math.radians(-180.0)
    ang_inc = math.radians(5.0)

    # 1. All clear (5m everywhere) -> drives forward toward waypoint
    clear_ranges = [5.0] * 72
    vx, yaw, state, sectors = compute_vfh_avoidance(clear_ranges, ang_min, ang_inc, target_heading_rad=0.0)
    assert state == "navigating"
    assert vx > 0.0
    assert abs(yaw) < 0.05
    assert sectors["front"] == 5.0

    # 2. Front blocked (0.25m) and right blocked (0.30m), left open (4.0m) -> stops forward and turns LEFT (+yaw)
    front_right_blocked = [4.0] * 72
    for idx in range(72):
        deg = -180.0 + idx * 5.0
        if -20.0 <= deg <= 20.0:
            front_right_blocked[idx] = 0.25
        elif -70.0 <= deg < -25.0:
            front_right_blocked[idx] = 0.30
    vx2, yaw2, state2, _ = compute_vfh_avoidance(front_right_blocked, ang_min, ang_inc, clearance_m=0.45)
    assert state2 == "avoiding_lidar_obstacle"
    assert vx2 == 0.0
    assert yaw2 > 0.0

    # 3. Visual obstacle flag overrides clear LiDAR -> stops forward & turns
    vx3, yaw3, state3, _ = compute_vfh_avoidance(clear_ranges, ang_min, ang_inc, visual_obstacle=True)
    assert state3 == "avoiding_visual_obstacle"
    assert vx3 == 0.0
    assert yaw3 != 0.0

    # 4. Boxed in on front, left, and right -> trapped rotate in place
    trapped = [0.20] * 72
    vx4, yaw4, state4, _ = compute_vfh_avoidance(trapped, ang_min, ang_inc, clearance_m=0.45)
    assert state4 == "avoiding_trapped_rotate"
    assert vx4 == 0.0
    assert yaw4 > 0.0


def test_ai_vision_engine_frame_processing_and_eyedropper() -> None:
    """Verify RobotAiVisionEngine mode switches, click-to-track lock, color eyedropper, and HUD annotation."""
    store = InMemoryRobotAiStore()
    engine = RobotAiVisionEngine(ai_store=store, models_dir="/tmp/twinscan_nonexistent_models_dir")

    # Blue-green frame with dark vertical line
    frame = np.full((120, 160, 3), (200, 180, 40), dtype=np.uint8)
    cv2.rectangle(frame, (70, 60), (90, 119), (8, 8, 8), -1)

    engine.set_mode("r1", mode="line_follow", line_follow_enabled=True, line_color="black")
    annotated, meta = engine.process_frame("r1", frame, lidar_front_m=2.0)
    assert annotated.shape == frame.shape
    assert meta["motion_cmd"] is not None
    assert meta["motion_cmd"]["x"] > 0.0

    # Eyedropper picks custom HSV color at top-left
    picked = engine.pick_line_color("r1", norm_x=0.1, norm_y=0.1)
    assert picked["line_color"] == "custom"
    assert picked["custom_hsv"] is not None and len(picked["custom_hsv"]) == 3

    # Click-to-Track synthetic ROI lock + clear
    locked = engine.select_target("r1", norm_x=0.5, norm_y=0.5)
    assert locked["tracked_target"] is not None
    cleared = engine.select_target("r1", norm_x=0.5, norm_y=0.5, clear=True)
    assert cleared["tracked_target"] is None
    assert cleared["follow_enabled"] is False


def test_ai_vision_people_patrol_and_estop_api_routes() -> None:
    """Exercise all FastAPI AI Vision, People Registry, Autonomous Patrol, and E-STOP disarm routes."""
    client, robot_id = _make_test_client()
    fake_jpg = _synthetic_jpeg(color_bgr=(30, 180, 50), stripe_x=80)

    with client:
        # 1. AI Vision state, mode, select-target, pick-color, deep-identify
        st = client.get(f"/api/robots/{robot_id}/ai-vision/state")
        assert st.status_code == 200
        assert st.json()["mode"] == "raw"

        st_mode = client.post(
            f"/api/robots/{robot_id}/ai-vision/mode",
            json={"mode": "track_follow", "follow_enabled": True, "lidar_stop_m": 0.4},
        )
        assert st_mode.status_code == 200
        assert st_mode.json()["mode"] == "track_follow"
        assert st_mode.json()["follow_enabled"] is True

        st_tgt = client.post(
            f"/api/robots/{robot_id}/ai-vision/select-target",
            json={"norm_x": 0.5, "norm_y": 0.5},
        )
        assert st_tgt.status_code == 200
        assert st_tgt.json()["tracked_target"] is not None

        with patch("src.api.routes_ai_vision.fetch_robot_snapshot", new=AsyncMock(return_value=fake_jpg)):
            st_pick = client.post(
                f"/api/robots/{robot_id}/ai-vision/pick-color",
                json={"norm_x": 0.2, "norm_y": 0.2},
            )
            assert st_pick.status_code == 200
            assert st_pick.json()["line_color"] == "custom"

            st_deep = client.post(
                f"/api/robots/{robot_id}/ai-vision/deep-identify",
                json={"speak_result": False},
            )
            assert st_deep.status_code == 200
            assert st_deep.json()["ok"] is True

        # 2. Known People Enrollment (camera + upload), list, update, delete
        with patch("src.api.routes_ai_vision.fetch_robot_snapshot", new=AsyncMock(return_value=fake_jpg)):
            enr_cam = client.post(
                f"/api/people/enroll-camera/{robot_id}",
                json={"name": "Jim", "role": "Owner", "greeting_phrase": "Hi Jim!", "greet_action": "shake_hands.d6ac"},
            )
            assert enr_cam.status_code == 200
            person_id = enr_cam.json()["person"]["id"]
            assert enr_cam.json()["person"]["embedding_count"] == 1

        enr_up = client.post(
            "/api/people/enroll-upload",
            data={"name": "Jim", "role": "Owner", "auto_speak": "true"},
            files={"file": ("jim2.jpg", fake_jpg, "image/jpeg")},
        )
        assert enr_up.status_code == 200
        assert enr_up.json()["person"]["embedding_count"] == 2

        people_list = client.get("/api/people")
        assert people_list.status_code == 200
        assert len(people_list.json()["people"]) == 1

        upd = client.put(f"/api/people/{person_id}", json={"notes": "Primary operator"})
        assert upd.status_code == 200
        assert upd.json()["person"]["notes"] == "Primary operator"

        # 3. Patrol Routes CRUD + Start + Status + E-STOP cancels patrol & autonomous follow
        saved = client.post(
            f"/api/robots/{robot_id}/patrol/routes",
            json={
                "name": "Office Loop",
                "waypoints": [{"x": 1.0, "y": 0.0, "label": "Desk"}, {"x": 1.0, "y": 1.0, "label": "Door"}],
                "loop_enabled": True,
                "max_speed_cms": 10.0,
                "obstacle_clearance_m": 0.45,
            },
        )
        assert saved.status_code == 200
        route_id = saved.json()["route"]["id"]

        listed = client.get(f"/api/robots/{robot_id}/patrol/routes")
        assert listed.status_code == 200
        assert len(listed.json()["routes"]) == 1

        with (
            patch("src.robot.patrol_engine.publish_velocity", new=AsyncMock(return_value={"published": True})),
            patch("src.robot.patrol_engine.fetch_robot_snapshot", new=AsyncMock(return_value=fake_jpg)),
            patch("src.robot.patrol_engine.RobotPatrolManager._run_scan_subscriber", new=AsyncMock(return_value=None)),
            patch("src.api.routes_robots.trigger_estop", new=AsyncMock(return_value={"estop": True})),
        ):
            # Camera-Only mode (require_lidar=False) starts cleanly when /scan is offline
            started = client.post(
                f"/api/robots/{robot_id}/patrol/start",
                json={"route_id": route_id, "require_lidar": False, "camera_avoidance": True},
            )
            assert started.status_code == 200
            assert started.json()["active"] is True
            assert started.json()["route_name"] == "Office Loop"
            assert started.json()["lidar_live"] is False
            assert started.json()["sectors_m"]["front"] is None

            pstat = client.get(f"/api/robots/{robot_id}/patrol/status")
            assert pstat.status_code == 200
            assert pstat.json()["active"] is True

            # Triggering robot E-STOP must immediately halt patrol AND disarm AI vision follow
            client.post(f"/api/robots/{robot_id}/ai-vision/mode", json={"mode": "track_follow", "follow_enabled": True})
            estop = client.post(f"/api/robots/{robot_id}/estop")
            assert estop.status_code == 200

            pstat_after = client.get(f"/api/robots/{robot_id}/patrol/status")
            assert pstat_after.json()["active"] is False

            vstat_after = client.get(f"/api/robots/{robot_id}/ai-vision/state")
            assert vstat_after.json()["follow_enabled"] is False

            stopped = client.post(f"/api/robots/{robot_id}/patrol/stop")
            assert stopped.status_code == 200
            assert stopped.json()["active"] is False

        # Start-LiDAR probe route (device absent vs present)
        with patch(
            "src.api.routes_ai_vision.start_robot_lidar_node",
            new=AsyncMock(
                return_value={
                    "ok": False,
                    "device_present": False,
                    "ros_version": "ros2",
                    "detail": "LD19 LiDAR not detected on USB (/dev/ldlidar absent).",
                }
            ),
        ):
            r_lid = client.post(f"/api/robots/{robot_id}/patrol/start-lidar")
            assert r_lid.status_code == 200
            assert r_lid.json()["ok"] is False
            assert r_lid.json()["device_present"] is False

        assert client.delete(f"/api/robots/{robot_id}/patrol/routes/{route_id}").json()["deleted"] is True
        assert client.delete(f"/api/people/{person_id}").json()["deleted"] is True


async def test_patrol_require_lidar_blocks_blind_driving_and_camera_only_avoids_wall() -> None:
    """Verify require_lidar=True blocks with blocked_no_lidar, and camera_avoidance detects close walls."""
    import asyncio

    mgr = RobotPatrolManager()

    # 1. require_lidar=True with no /scan arriving -> blocked_no_lidar and ZERO forward velocity
    sent_cmds: list[tuple[float, float]] = []

    async def _capture_vel(ip, port, x, y, yaw_rate, **kwargs):
        sent_cmds.append((x, yaw_rate))
        return {"published": True}

    with (
        patch("src.robot.patrol_engine.publish_velocity", side_effect=_capture_vel),
        patch.object(mgr, "_run_scan_subscriber", new=AsyncMock(return_value=None)),
    ):
        st = await mgr.start(
            robot_id="r-safe",
            ip="192.168.1.119",
            rosbridge_port=9090,
            ros_version="ros2",
            waypoints=[{"x": 2.0, "y": 0.0}],
            require_lidar=True,
            scan_wait_sec=0.1,
        )
        assert st["active"] is False
        assert st["state"] == "blocked_no_lidar"
        assert st["lidar_live"] is False
        assert st["sectors_m"]["front"] is None
        assert all(vx == 0.0 for vx, _ in sent_cmds)

    # 2. Flat close wall JPEG triggers detect_front_camera_obstacle AND camera-only patrol turns away with vx=0
    blank_wall_jpg = _synthetic_jpeg(color_bgr=(190, 190, 190))
    obs_label, turn_dir = detect_front_camera_obstacle(blank_wall_jpg)
    assert obs_label is not None
    assert turn_dir in ("left", "right")

    cam_cmds: list[tuple[float, float]] = []

    async def _capture_cam_vel(ip, port, x, y, yaw_rate, **kwargs):
        cam_cmds.append((x, yaw_rate))
        return {"published": True}

    with (
        patch("src.robot.patrol_engine.publish_velocity", side_effect=_capture_cam_vel),
        patch("src.robot.patrol_engine.fetch_robot_snapshot", new=AsyncMock(return_value=blank_wall_jpg)),
        patch.object(mgr, "_run_scan_subscriber", new=AsyncMock(return_value=None)),
    ):
        st_cam = await mgr.start(
            robot_id="r-cam",
            ip="192.168.1.119",
            rosbridge_port=9090,
            ros_version="ros2",
            waypoints=[{"x": 2.0, "y": 0.0}],
            require_lidar=False,
            camera_avoidance=True,
        )
        assert st_cam["active"] is True
        await asyncio.sleep(0.35)
        cur = mgr.get_status("r-cam")
        assert cur["lidar_live"] is False
        assert cur["sectors_m"]["front"] is None
        assert cur["visual_obstacle"] is not None
        assert any(vx == 0.0 and yaw != 0.0 for vx, yaw in cam_cmds)
        await mgr.stop("r-cam")


def test_ros2_camera_topic_resolution_and_fallback_on_snapshot_and_snap_to_vision() -> None:
    """Verify ROS 2 robots resolve omitted or legacy /usb_cam/image_raw topics to /image_raw with fallback."""
    client, robot_id = _make_test_client()
    fake_jpg = _synthetic_jpeg()

    with client:
        seen_topics: list[str] = []

        async def _capture_topic(*, ip, port, topic, timeout=5.0, retries=2):
            seen_topics.append(topic)
            return fake_jpg

        with patch("src.api.routes_robots.fetch_robot_snapshot", side_effect=_capture_topic):
            # 1. GET /video/snapshot with omitted topic -> /image_raw
            r1 = client.get(f"/api/robots/{robot_id}/video/snapshot")
            assert r1.status_code == 200
            assert seen_topics[-1] == "/image_raw"

            # 2. GET /video/snapshot with legacy ROS 1 topic on ROS 2 robot -> normalized to /image_raw
            r2 = client.get(f"/api/robots/{robot_id}/video/snapshot?topic=/usb_cam/image_raw")
            assert r2.status_code == 200
            assert seen_topics[-1] == "/image_raw"

            # 3. POST /video/snap-to-vision with {} and with {"topic": "/usb_cam/image_raw"} -> /image_raw
            r3 = client.post(f"/api/robots/{robot_id}/video/snap-to-vision", json={})
            assert r3.status_code == 200
            assert r3.json()["topic"] == "/image_raw"
            assert seen_topics[-1] == "/image_raw"

            r4 = client.post(
                f"/api/robots/{robot_id}/video/snap-to-vision",
                json={"topic": "/usb_cam/image_raw"},
            )
            assert r4.status_code == 200
            assert r4.json()["topic"] == "/image_raw"
            assert seen_topics[-1] == "/image_raw"

        # 4. Automatic fallback: if /image_raw fails with ConnectionError, falls back once to /usb_cam/image_raw
        fallback_calls: list[str] = []

        async def _fail_first(*, ip, port, topic, timeout=5.0, retries=2):
            fallback_calls.append(topic)
            if topic == "/image_raw":
                raise ConnectionError("topic not active")
            return fake_jpg

        with patch("src.api.routes_robots.fetch_robot_snapshot", side_effect=_fail_first):
            r5 = client.get(f"/api/robots/{robot_id}/video/snapshot")
            assert r5.status_code == 200
            assert fallback_calls == ["/image_raw", "/usb_cam/image_raw"]
