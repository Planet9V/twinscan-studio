"""Unit and API tests for Kaizen Vision V1-V4, Kalman MovingObjectTracker, LiDAR Settings, Spatial Memory (Add-On B), and Sentry Guard Mode (Add-On C)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from src.app.config import Settings
from src.app.factory import create_app
from src.db.repository import InMemoryTwinRepository
from src.db.robot_ai_store import InMemoryRobotAiStore
from src.db.robot_store import InMemoryRobotStore
from src.lidar.motion_tracker import MovingObjectTracker
from src.robot.sentry_manager import RobotSentryManager
from src.vision.robot_ai_vision import RobotAiVisionEngine


def _make_jpeg(color_bgr: tuple[int, int, int] = (50, 90, 140)) -> bytes:
    img = np.full((120, 160, 3), color_bgr, dtype=np.uint8)
    cv2.rectangle(img, (50, 30), (110, 90), (20, 200, 240), -1)
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
            "name": "PuppyPi Kaizen",
            "model": "Hiwonder PuppyPi Pro",
            "active_ros_distro": "ROS2 Humble",
            "ssh_user": "pi",
            "rosbridge_port": 9090,
            "video_port": 8080,
            "battery_mv": 7720,
        },
        ssh_password="raspberrypi",
    )
    return TestClient(app), robot["id"]


def test_v1_apriltag_handles_opencv5_1d_ids_array() -> None:
    """Verify V1 fix: detect_apriltags works cleanly when OpenCV 5.1 returns 1D (N,) ids array."""
    store = InMemoryRobotAiStore()
    engine = RobotAiVisionEngine(ai_store=store, models_dir="/tmp/twinscan_nonexistent_models_dir")

    class _FakeAruco1D:
        def detectMarkers(self, gray):
            corners = [np.array([[[20.0, 20.0], [60.0, 20.0], [60.0, 60.0], [20.0, 60.0]]], dtype=np.float32)]
            ids_1d = np.array([42], dtype=np.int32)  # OpenCV 5.1 1D shape (N,) instead of (N, 1)
            return corners, ids_1d, []

    engine._aruco_detector = _FakeAruco1D()
    frame = np.zeros((120, 160, 3), dtype=np.uint8)
    dets = engine.detect_apriltags(frame)
    assert len(dets) == 1
    assert dets[0]["id"] == "tag-42"
    assert dets[0]["label"] == "AprilTag #42"


def test_v2_offline_hud_frame_and_v3_tracker_lost_frames_safety_stop() -> None:
    """Verify V2 offline HUD JPEG renders cleanly and V3 stops follow motion after >=5 lost frames."""
    store = InMemoryRobotAiStore()
    engine = RobotAiVisionEngine(ai_store=store, models_dir="/tmp/twinscan_nonexistent_models_dir")

    # V2: Offline HUD JPEG is valid and decodable (640x360)
    hud_bytes = engine._render_offline_hud_frame("robot-1", "face_recognition", "Connection timeout")
    assert hud_bytes[:2] == b"\xff\xd8"
    hud_img = cv2.imdecode(np.frombuffer(hud_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert hud_img is not None and hud_img.shape == (360, 640, 3)

    # V3: Select target on frame, simulate 5 failed tracker updates -> lost_frames >= 5 forces zero velocity!
    frame = np.full((120, 160, 3), (30, 30, 30), dtype=np.uint8)
    engine.set_mode("r1", mode="track_follow", follow_enabled=True, target_fps=15.0, conf_threshold=0.45)
    engine.process_frame("r1", frame, lidar_front_m=2.0)
    engine.select_target("r1", norm_x=0.5, norm_y=0.5)

    class _FailingTracker:
        def update(self, img):
            return False, (0, 0, 0, 0)

    engine._states["r1"]["tracker"] = _FailingTracker()
    engine._states["r1"]["tracker_template"] = None

    last_meta = {}
    for _ in range(5):
        _, last_meta = engine.process_frame("r1", frame, lidar_front_m=2.0)

    st = engine.get_state("r1")
    assert st["lost_frames"] >= 5
    assert st["target_fps"] == 15.0
    assert st["conf_threshold"] == 0.45
    assert last_meta["motion_cmd"] == {"x": 0.0, "yaw_rate": 0.0}


def test_kalman_moving_object_tracker_velocity_and_trails() -> None:
    """Verify 4-state Constant-Velocity Kalman Filter tracks moving object speed, heading, and comet trail."""
    tracker = MovingObjectTracker()
    tracks = []
    # Object moving smoothly along +X at 0.50 m/s for 10 scans at 10 Hz (dt = 0.1s)
    for step in range(10):
        t = step * 0.1
        clusters = [
            {"centroid_x": 0.5 + 0.50 * t, "centroid_y": 1.2, "point_count": 14},  # moving
            {"centroid_x": -1.8, "centroid_y": -1.0, "point_count": 20},  # stationary
        ]
        tracks = tracker.update(clusters, timestamp_s=100.0 + t)

    assert len(tracks) == 2
    moving = [tr for tr in tracks if tr["is_moving"]]
    stationary = [tr for tr in tracks if not tr["is_moving"]]
    assert len(moving) == 1
    assert len(stationary) == 1
    assert 0.35 <= moving[0]["speed_mps"] <= 0.65
    assert moving[0]["vx"] > 0.3
    assert len(moving[0]["trail"]) == 10
    assert stationary[0]["speed_mps"] < 0.08


def test_lidar_settings_and_moving_targets_and_robot_pose_snapshot() -> None:
    """Verify GET/POST /api/lidar/settings updates polling rate, moving targets, and emits robot_pose."""
    client, _ = _make_test_client()
    with client:
        r0 = client.get("/api/lidar/settings")
        assert r0.status_code == 200
        assert r0.json()["poll_interval_ms"] == 100

        r1 = client.post(
            "/api/lidar/settings",
            json={
                "source_mode": "simulator",
                "poll_interval_ms": 50,
                "analytics_every_n_scans": 1,
                "motion_tracking_enabled": True,
                "simulate_moving_targets": True,
            },
        )
        assert r1.status_code == 200
        s = r1.json()
        assert s["poll_interval_ms"] == 50
        assert s["analytics_every_n_scans"] == 1
        assert s["simulate_moving_targets"] is True

        snap = client.get("/api/lidar/snapshot").json()
        assert snap["poll_interval_ms"] == 50
        assert snap["simulate_moving_targets"] is True
        assert "moving_objects" in snap
        assert "robot_pose" in snap
        assert "roll_deg" in snap["robot_pose"]


def test_spatial_memory_crud_and_ox_where_did_you_see_query() -> None:
    """Verify Add-On B Semantic Spatial Memory capture/search/delete and OX answering 'where did you see my laptop?'."""
    client, robot_id = _make_test_client()
    fake_jpg = _make_jpeg()

    with client:
        # Capture spatial memory with mocked YOLO returning a laptop
        fake_det = [
            {
                "id": "obj-0",
                "kind": "object",
                "label": "laptop",
                "confidence": 0.91,
                "is_animal": False,
                "person_id": None,
                "bbox_norm": [0.35, 0.35, 0.65, 0.65],
                "tracked": False,
            }
        ]
        with (
            patch("src.api.routes_ai_vision.fetch_robot_snapshot", new=AsyncMock(return_value=fake_jpg)),
            patch.object(client.app.state.ai_vision_engine, "detect_objects_and_animals", return_value=fake_det),
            patch.object(client.app.state.ai_vision_engine, "detect_faces_and_embeddings", return_value=[]),
        ):
            cap = client.post(f"/api/spatial-memory/capture/{robot_id}")
            assert cap.status_code == 200
            cdata = cap.json()
            assert cdata["ok"] is True
            assert cdata["recorded_count"] == 1
            sighting_id = cdata["sightings"][0]["id"]
            assert cdata["sightings"][0]["label"] == "laptop"

        # Query spatial memory
        listed = client.get("/api/spatial-memory?query=laptop")
        assert listed.status_code == 200
        assert len(listed.json()["sightings"]) == 1

        # Ask OX by chat: "Where did you last see my laptop?" -> answers with coordinates from Spatial Memory!
        chat = client.post(
            f"/api/robots/{robot_id}/voice/chat",
            json={"message": "Where did you last see my laptop?", "speak_reply": False, "attach_camera": "never"},
        )
        assert chat.status_code == 200
        reply = chat.json()["reply"].lower()
        assert "laptop" in reply
        assert "meters" in reply

        # Delete sighting
        assert client.delete(f"/api/spatial-memory/{sighting_id}").json()["deleted"] is True


@pytest.mark.asyncio
async def test_sentry_guard_mode_arm_triggers_cooldown_events_and_estop_disarm() -> None:
    """Verify Add-On C Sentry Guard Mode config, arm, trigger evaluation, evidence logging, cooldown, and E-STOP disarm."""
    client, robot_id = _make_test_client()
    fake_jpg = _make_jpeg()

    # Unit check on RobotSentryManager trigger evaluation & cooldown
    mgr = RobotSentryManager()
    mgr.update_config("r-s", {"watch_motion": True, "watch_unknown_faces": True, "watch_animals": True, "cooldown_sec": 30})
    mgr._configs["r-s"]["armed"] = True

    t_face = mgr.evaluate_triggers("r-s", [], [{"kind": "face", "label": "Unknown Face", "person_id": None, "confidence": 0.9}], now_s=100.0)
    assert t_face is not None and t_face["trigger_type"] == "unknown_face"

    t_animal = mgr.evaluate_triggers("r-s", [], [{"kind": "animal", "label": "dog", "is_animal": True, "confidence": 0.85}], now_s=100.0)
    assert t_animal is not None and t_animal["trigger_type"] == "animal"

    t_motion = mgr.evaluate_triggers("r-s", [{"track_id": 2, "is_moving": True, "speed_mps": 0.42, "x": 1.1, "y": 0.3}], [], now_s=100.0)
    assert t_motion is not None and t_motion["trigger_type"] == "lidar_motion"

    # Simulate cooldown active after alert at t=100 -> suppressed at t=110, allowed again at t=135
    mgr._last_alert_ts["r-s"] = 100.0
    assert mgr.evaluate_triggers("r-s", [{"track_id": 2, "is_moving": True, "speed_mps": 0.42, "x": 1.1, "y": 0.3}], [], now_s=110.0) is None
    assert mgr.evaluate_triggers("r-s", [{"track_id": 2, "is_moving": True, "speed_mps": 0.42, "x": 1.1, "y": 0.3}], [], now_s=135.0) is not None

    # API lifecycle: status -> config -> arm -> record alert -> list events -> E-STOP disarms -> clear events
    with client:
        st0 = client.get(f"/api/robots/{robot_id}/sentry/status")
        assert st0.status_code == 200
        assert st0.json()["armed"] is False

        cfg = client.put(
            f"/api/robots/{robot_id}/sentry/config",
            json={"cooldown_sec": 15, "custom_challenge": "Halt! Who goes there?"},
        )
        assert cfg.status_code == 200
        assert cfg.json()["cooldown_sec"] == 15

        with (
            patch("src.robot.sentry_manager.fetch_robot_snapshot", new=AsyncMock(return_value=fake_jpg)),
            patch("src.robot.sentry_manager.set_rgb", new=AsyncMock(return_value={"published": True})),
            patch("src.robot.sentry_manager.speak_text_on_robot", new=AsyncMock(return_value={"ok": True})),
            patch("src.api.routes_robots.trigger_estop", new=AsyncMock(return_value={"estop": True})),
        ):
            armed = client.post(f"/api/robots/{robot_id}/sentry/arm")
            assert armed.status_code == 200
            assert armed.json()["armed"] is True

            # Manually trigger one alert through handle_trigger to verify evidence photo + event log
            await client.app.state.sentry_manager.handle_trigger(
                robot_id=robot_id,
                trigger=t_motion,
                ai_store=client.app.state.robot_ai_store,
                repo=client.app.state.runtime.repo,
                robot=client.app.state.robot_store.get_robot(robot_id),
                ssh_pw="raspberrypi",
                ros_version="ros2",
            )

            ev = client.get(f"/api/robots/{robot_id}/sentry/events")
            assert ev.status_code == 200
            assert len(ev.json()["events"]) == 1
            assert ev.json()["events"][0]["snapshot_file_id"] is not None
            assert ev.json()["events"][0]["spoken_alert"] == "Halt! Who goes there?"

            # Global E-STOP must disarm Sentry cleanly!
            estop = client.post(f"/api/robots/{robot_id}/estop")
            assert estop.status_code == 200
            assert client.get(f"/api/robots/{robot_id}/sentry/status").json()["armed"] is False

            dis = client.post(f"/api/robots/{robot_id}/sentry/disarm")
            assert dis.status_code == 200 and dis.json()["armed"] is False

            clr = client.delete(f"/api/robots/{robot_id}/sentry/events")
            assert clr.status_code == 200 and clr.json()["cleared"] == 1
