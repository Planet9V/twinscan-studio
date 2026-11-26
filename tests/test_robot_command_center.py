"""Comprehensive pytest suite for PuppyPi Discovery, Robot Store, SSH Configurator, ROSBridge Proxy, and API routes."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from src.app.config import Settings
from src.app.factory import create_app
from src.db.repository import InMemoryTwinRepository
from src.db.robot_store import InMemoryRobotStore
from src.robot.discovery import (
    classify_robot_candidate,
    discover_robots_on_lan,
    expand_target_ips,
    parse_lobot_udp_reply,
)
from src.robot.rosbridge_proxy import (
    DeadManWatchdog,
    clamp_gait,
    clamp_pose,
    clamp_servo,
    clamp_velocity,
    laserscan_to_lidar_points,
    normalize_action_group_name,
    sanitize_outbound_rosbridge_message,
    validate_video_topic,
)
from src.robot.ssh_manager import (
    build_robot_cyclonedx_hbom_sbom,
    normalize_catalogue_payload,
    render_wifi_conf_py,
    validate_mechanics_params,
    validate_password_change_params,
    validate_ros_ai_params,
    validate_wifi_params,
)


def _make_jpeg_bytes() -> bytes:
    img = np.full((120, 160, 3), 180, dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


def _build_client(tmp_path) -> TestClient:
    cfg = Settings(
        openrouter_api_key="",
        database_url="",
        neo4j_uri="",
        twinscan_storage_dir=str(tmp_path),
        twinscan_encryption_key="test-robot-store-key",
    )
    app = create_app(
        settings=cfg,
        repository=InMemoryTwinRepository(encryption_key=cfg.twinscan_encryption_key),
        robot_store=InMemoryRobotStore(encryption_key=cfg.twinscan_encryption_key),
    )
    return TestClient(app)


# --- 1. Discovery Tests ---


def test_parse_lobot_udp_reply() -> None:
    """Verify UDP 9027 Lobot discovery response parsing."""
    parsed = parse_lobot_udp_reply(b"PUPPY_1.0:AABBCCDDEEFF00112233445566778899\n")
    assert parsed == {
        "protocol": "PUPPY_1.0",
        "serial_number": "AABBCCDDEEFF00112233445566778899",
    }
    assert parse_lobot_udp_reply("RANDOM_NOISE") is None
    assert parse_lobot_udp_reply(b"") is None
    assert parse_lobot_udp_reply(b"PUPPY_1.0:") is None


def test_expand_target_ips_and_classification() -> None:
    """Verify CIDR expansion deduplication and candidate classification."""
    ips = expand_target_ips(cidrs=["192.168.1.230/30"], saved_ips=["192.168.1.231", "10.0.0.5", "not-an-ip"])
    assert ips[0] == "192.168.1.231"
    assert "10.0.0.5" in ips
    assert "192.168.1.230" in ips
    assert len(ips) == len(set(ips))

    cand = classify_robot_candidate(
        ip="192.168.1.231",
        serial_number="SN1234",
        rosbridge_open=True,
        video_open=True,
        ssh_open=True,
        ssh_banner="SSH-2.0-OpenSSH_9.2p1",
        protocol="PUPPY_1.0",
    )
    assert cand is not None
    assert cand["model_guess"] == "Hiwonder PuppyPi Pro"
    assert classify_robot_candidate("192.168.1.50", None, False, False, True, "SSH-2.0") is None
    # Windows host with TCP 8080 + SSH must NOT false-positive as a PuppyPi/ROS node
    assert (
        classify_robot_candidate(
            ip="192.168.1.87",
            serial_number=None,
            rosbridge_open=False,
            video_open=True,
            ssh_open=True,
            ssh_banner="SSH-2.0-OpenSSH_for_Windows_9.5",
        )
        is None
    )


@pytest.mark.asyncio
async def test_discover_robots_on_lan_mocked() -> None:
    """Verify parallel 3-tier LAN discovery ranks PuppyPi candidates first."""
    async def fake_tcp(ip: str, port: int, timeout: float = 0.45, read_banner: bool = False):
        if ip == "192.168.1.231" and port in (9090, 8080, 22):
            return True, "SSH-2.0-OpenSSH_9.2p1" if read_banner else ""
        if ip == "192.168.1.232" and port == 9090:
            return True, ""
        return False, ""

    async def fake_udp(ip: str, port: int = 9027, timeout: float = 0.5):
        if ip == "192.168.1.231":
            return {"protocol": "PUPPY_1.0", "serial_number": "PUPPY-SN-999"}
        return None

    with patch("src.robot.discovery.probe_tcp_port", side_effect=fake_tcp), patch(
        "src.robot.discovery.probe_udp_lobot", side_effect=fake_udp
    ):
        found = await discover_robots_on_lan(cidrs=["192.168.1.224/28"], saved_ips=["192.168.1.231"])
    assert len(found) == 2
    assert found[0]["ip"] == "192.168.1.231"
    assert found[0]["serial_number"] == "PUPPY-SN-999"
    assert found[0]["rosbridge_open"] is True
    assert found[0]["video_open"] is True
    assert found[1]["ip"] == "192.168.1.232"


# --- 2. Safety Clampers & Dead-Man's Switch Tests ---


def test_puppy_safety_clampers() -> None:
    """Verify exact puppy.py velocity, pose, gait, servo, and action safety clamps."""
    vel = clamp_velocity(x=99.5, y=12.0, yaw_rate=-2.5)
    assert vel == {"x": 35.0, "y": 0.0, "yaw_rate": -0.89}
    assert clamp_velocity(x=-50.0, y=-5.0, yaw_rate=1.2) == {"x": -35.0, "y": 0.0, "yaw_rate": 0.89}

    pose = clamp_pose(roll=1.5, pitch=-2.0, yaw=0.4, height=-20.0, x_shift=15.0, stance_x=-9.0, stance_y=8.0, run_time=5)
    assert pose["roll"] == 0.54
    assert pose["pitch"] == -0.54
    assert pose["yaw"] == 0.0
    assert pose["height"] == -15.0
    assert pose["x_shift"] == 10.0
    assert pose["stance_x"] == -5.0
    assert pose["stance_y"] == 5.0
    assert pose["run_time"] == 10

    gait = clamp_gait(overlap_time=-1.0, swing_time=5.0, clearance_time=2.0, z_clearance=20.0)
    assert gait == {"overlap_time": 0.0, "swing_time": 1.0, "clearance_time": 1.0, "z_clearance": 10.0}

    assert clamp_servo(9, 100, 5) == {"id": 9, "pulse": 500, "time": 10}
    assert clamp_servo(11, 3500, 99999) == {"id": 11, "pulse": 2500, "time": 30000}
    with pytest.raises(ValueError):
        clamp_servo(0, 1500, 500)

    assert normalize_action_group_name("wave") == "wave.d6ac"
    assert normalize_action_group_name("grab") == "grab.d6a"
    with pytest.raises(ValueError):
        normalize_action_group_name("../etc/passwd")

    assert validate_video_topic("/usb_cam/image_raw") == "/usb_cam/image_raw"
    with pytest.raises(ValueError):
        validate_video_topic("http://evil.com/x")


def test_sanitize_outbound_and_laserscan_conversion() -> None:
    """Verify outbound WS sanitization and LaserScan -> LidarPoint conversion."""
    sanitized, vel = sanitize_outbound_rosbridge_message(
        {"op": "publish", "topic": "/puppy_control/velocity/autogait", "msg": {"x": 80, "y": 5, "yaw_rate": 2.0}}
    )
    assert sanitized["msg"] == {"x": 35.0, "y": 0.0, "yaw_rate": 0.89}
    assert vel == (35.0, 0.89)

    pts = laserscan_to_lidar_points(
        {
            "angle_min": 0.0,
            "angle_increment": 0.5,
            "range_min": 0.1,
            "range_max": 10.0,
            "ranges": [1.5, float("inf"), 0.01, 2.5],
            "intensities": [200, 100, 50, 180],
        }
    )
    assert len(pts) == 2
    assert pts[0].distance_m == 1.5
    assert pts[1].distance_m == 2.5


@pytest.mark.asyncio
async def test_deadman_watchdog_triggers_after_500ms() -> None:
    """Verify 0.5s dead-man's switch emits zero velocity when heartbeats stop."""
    now = [100.0]
    stops = 0

    async def send_zero() -> None:
        nonlocal stops
        stops += 1

    wd = DeadManWatchdog(send_zero_velocity=send_zero, timeout_s=0.5, clock=lambda: now[0])
    wd.record_velocity(15.0, 0.0)
    assert wd.is_moving is True

    now[0] = 100.4
    assert await wd.check_once() is False
    assert stops == 0

    now[0] = 100.6
    assert await wd.check_once() is True
    assert stops == 1
    assert wd.is_moving is False

    # Force stop on disconnect while moving
    wd.record_velocity(10.0, 0.2)
    await wd.force_stop()
    assert stops == 2
    assert wd.is_moving is False


# --- 3. SSH Config Validation & CycloneDX HBOM+SBOM Tests ---


def test_ssh_validators_and_wifi_renderer() -> None:
    """Verify strict input validators reject shell/newline/colon injection and render valid Python."""
    rendered = render_wifi_conf_py(mode=2, ssid="Wildcat", wifi_password="secret'\"pw")
    compile(rendered, "wifi_conf.py", "exec")
    assert "WIFI_MODE = 2" in rendered
    assert 'WIFI_STA_SSID = "Wildcat"' in rendered

    with pytest.raises(ValueError):
        validate_wifi_params(mode=3, ssid="Wildcat", wifi_password="abc")
    with pytest.raises(ValueError):
        validate_wifi_params(mode=2, ssid="Bad\nSSID", wifi_password="abc")
    with pytest.raises(ValueError):
        validate_wifi_params(mode=2, ssid="Wildcat", wifi_password="abc", country_code="USA")

    assert validate_password_change_params("pi", "NewPass123!") == ("pi", "NewPass123!")
    with pytest.raises(ValueError):
        validate_password_change_params("ubuntu", "NewPass123!")
    with pytest.raises(ValueError):
        validate_password_change_params("pi", "bad:pass")
    with pytest.raises(ValueError):
        validate_password_change_params("pi", "bad\npass")

    assert validate_mechanics_params(with_arm=1, x_shift=-0.5, servo_deviations={"9": 10})["with_arm"] == 1
    with pytest.raises(ValueError):
        validate_mechanics_params(with_arm=2)
    with pytest.raises(ValueError):
        validate_mechanics_params(x_shift=25.0)

    assert validate_ros_ai_params(target_ros="humble", asr_language="English") == {
        "target_ros": "ros2",
        "asr_language": "English",
        "ros_domain_id": None,
        "rmw_implementation": None,
        "persist_boot": True,
    }
    with pytest.raises(ValueError):
        validate_ros_ai_params(target_ros="foxy")


def test_catalogue_normalization_and_cyclonedx() -> None:
    """Verify raw SSH catalogue normalizes BOM/SBOM + unattached peripherals + CycloneDX 1.6."""
    raw = {
        "board": {"model": "Raspberry Pi 5 Model B Rev 1.0", "revision": "d04170", "serial": "10000000abc", "cpu_temp_c": 48.2},
        "network_interfaces": [{"name": "eth1", "mac": "dc:a6:32:11:22:33", "state": "UP", "ipv4": ["192.168.1.231"]}],
        "usb_devices": [{"bus": "001", "device": "002", "usb_id": "0c45:636b", "description": "Microdia USB 2.0 Camera"}],
        "serial_ports": ["/dev/ttyAMA0"],
        "video_devices": ["/dev/video0"],
        "audio_playback": "",
        "audio_capture": "",
        "i2c_buses": ["/dev/i2c-1"],
        "i2c_addresses": ["0x7a"],
        "containers": [{"name": "puppypi", "image": "hiwonder/puppypi:noetic", "state": "running", "status": "Up 2 hours", "ros_distro": "ROS1 Noetic"}],
        "live_config": {"with_arm": 0, "x_shift": -0.5, "asr_language": "English", "servo_deviations": {"1": 0}},
        "sbom": {
            "host_dpkg": [{"name": "openssh-server", "version": "9.2p1"}],
            "host_pip": [{"name": "pyserial", "version": "3.5"}],
            "ros1_dpkg": [{"name": "ros-noetic-rosbridge-server", "version": "0.11.16"}],
            "ros1_pip": [{"name": "rospkg", "version": "1.5.0"}],
            "ros2_dpkg": [],
            "ros2_pip": [],
        },
    }
    norm = normalize_catalogue_payload(raw, robot_meta={"id": "r1", "ip_address": "192.168.1.231", "name": "PuppyPi-1"})
    assert norm["robot_updates"]["active_ros_distro"] == "noetic"
    assert norm["robot_updates"]["mac_address"] == "dc:a6:32:11:22:33"
    # LD19 LiDAR wasn't in USB/ttyUSB, so it must be surfaced as unattached!
    assert any(d["subsystem"] == "lidar" and d["status"] == "unattached" for d in norm["devices"])
    assert len(norm["sbom_packages"]) == 4
    assert any(p["purl"] == "pkg:pypi/pyserial@3.5" for p in norm["sbom_packages"])

    cdx = norm["hbom_sbom"]
    assert cdx["bomFormat"] == "CycloneDX"
    assert cdx["specVersion"] == "1.6"
    assert any(c["type"] == "device" for c in cdx["components"])
    assert any(c["type"] == "container" and c["name"] == "puppypi" for c in cdx["components"])
    assert any(c["type"] == "library" and c.get("purl") == "pkg:deb/ubuntu/ros-noetic-rosbridge-server@0.11.16" for c in cdx["components"])

    # Standalone CycloneDX builder smoke check
    cdx2 = build_robot_cyclonedx_hbom_sbom({"id": "r1", "ip_address": "192.168.1.231"}, [], [])
    assert cdx2["bomFormat"] == "CycloneDX"


# --- 4. Robot Store CRUD & Encryption Tests ---


def test_in_memory_robot_store_crud_and_encryption() -> None:
    """Verify robot store never seeds automatically, encrypts passwords, and persists BOM/SBOM."""
    store = InMemoryRobotStore(encryption_key="unit-test-secret-key")
    store.initialize()
    assert store.list_robots() == []

    rec = store.upsert_robot(
        {"ip_address": "192.168.1.231", "name": "PuppyPi Alpha", "ssh_user": "pi"},
        ssh_password="raspberrypi",
    )
    assert "ssh_password" not in rec
    assert "ssh_password_enc" not in rec
    assert store.get_robot_ssh_password(rec["id"]) == "raspberrypi"
    # Raw internal storage must be Fernet-encrypted
    assert store._robots[rec["id"]]["ssh_password_enc"].startswith("enc:v1:")

    store.update_robot_credentials(rec["id"], ssh_password="new-secure-password")
    assert store.get_robot_ssh_password(rec["id"]) == "new-secure-password"

    # Re-upsert by IP without password preserves existing encrypted password
    rec2 = store.upsert_robot({"ip_address": "192.168.1.231", "status": "online"})
    assert rec2["id"] == rec["id"]
    assert store.get_robot_ssh_password(rec["id"]) == "new-secure-password"

    updated = store.save_robot_catalogue(
        robot_id=rec["id"],
        devices=[{"subsystem": "compute", "make": "Raspberry Pi", "model": "Pi 5", "bus_type": "soc", "status": "online"}],
        sbom_packages=[
            {"layer": "host_dpkg", "name": "bash", "version": "5.2", "purl": "pkg:deb/debian/bash@5.2"},
            {"layer": "ros1_pip", "name": "numpy", "version": "1.24", "purl": "pkg:pypi/numpy@1.24"},
        ],
        hbom_sbom={"bomFormat": "CycloneDX", "specVersion": "1.6", "components": []},
        robot_updates={"active_ros_distro": "ROS1 Noetic", "cpu_temp_c": 46.5},
    )
    assert updated is not None
    assert updated["active_ros_distro"] == "ROS1 Noetic"
    assert len(store.list_robot_devices(rec["id"])) == 1
    assert len(store.list_robot_sbom(rec["id"], layer="ros1_pip")) == 1
    assert len(store.list_robot_sbom(rec["id"], query="bash")) == 1

    assert store.delete_robot(rec["id"]) is True
    assert store.get_robot(rec["id"]) is None
    assert store.list_robot_devices(rec["id"]) == []


# --- 5. FastAPI /api/robots/* Endpoints Integration Tests ---


def test_robot_api_full_lifecycle(tmp_path) -> None:
    """Exercise discovery, registration, catalogue, CycloneDX export, control, video snap-to-vision, and remote config routes."""
    with _build_client(tmp_path) as client:
        assert client.get("/api/robots").json() == {"robots": [], "count": 0}

        # 1. Discover & auto-register
        fake_candidates = [
            {
                "ip": "192.168.1.231",
                "serial_number": "PUPPY-SN-001",
                "rosbridge_open": True,
                "video_open": True,
                "ssh_open": True,
                "ssh_banner": "SSH-2.0-OpenSSH_9.2p1",
                "model_guess": "Hiwonder PuppyPi Pro",
            }
        ]
        with patch("src.api.routes_robots.discover_robots_on_lan", new=AsyncMock(return_value=fake_candidates)):
            disc = client.post("/api/robots/discover", json={"cidrs": ["192.168.1.0/24"]})
        assert disc.status_code == 200
        assert disc.json()["count"] == 1
        robot_id = disc.json()["robots"][0]["id"]

        # 2. Manual register second robot
        reg = client.post(
            "/api/robots",
            json={"ip_address": "192.168.1.232", "name": "PuppyPi Lab 2", "ssh_user": "pi", "ssh_password": "secret"},
        )
        assert reg.status_code == 200
        robot2_id = reg.json()["robot"]["id"]
        assert client.get("/api/robots").json()["count"] == 2

        # 3. Catalogue BOM + SBOM via mocked SSH
        fake_cat = normalize_catalogue_payload(
            {
                "board": {"model": "Raspberry Pi 5", "serial": "SN-RPI5", "cpu_temp_c": 49.0},
                "network_interfaces": [{"name": "eth1", "mac": "aa:bb:cc:dd:ee:ff", "state": "UP", "ipv4": ["192.168.1.231"]}],
                "usb_devices": [],
                "serial_ports": [],
                "video_devices": ["/dev/video0"],
                "containers": [{"name": "puppypi", "image": "puppypi:latest", "state": "running", "ros_distro": "ROS1 Noetic"}],
                "live_config": {"with_arm": 0, "x_shift": -0.5, "asr_language": "English"},
                "sbom": {"host_dpkg": [{"name": "curl", "version": "8.0"}], "host_pip": [], "ros1_dpkg": [], "ros1_pip": [], "ros2_dpkg": [], "ros2_pip": []},
            },
            robot_meta={"id": robot_id, "ip_address": "192.168.1.231", "name": "PuppyPi (192.168.1.231)"},
        )
        with patch("src.api.routes_robots.collect_robot_catalogue", new=AsyncMock(return_value=fake_cat)):
            cat_res = client.post(f"/api/robots/{robot_id}/catalogue")
        assert cat_res.status_code == 200
        assert cat_res.json()["sbom_count"] == 1
        assert cat_res.json()["robot"]["active_ros_distro"] == "noetic"

        detail = client.get(f"/api/robots/{robot_id}")
        assert detail.status_code == 200
        assert len(detail.json()["devices"]) >= 2
        assert len(detail.json()["sbom"]) == 1

        # 4. CycloneDX 1.6 Export
        cdx_res = client.get(f"/api/robots/{robot_id}/export/cyclonedx")
        assert cdx_res.status_code == 200
        assert cdx_res.json()["bomFormat"] == "CycloneDX"
        assert cdx_res.json()["specVersion"] == "1.6"

        # 5. Control endpoints (velocity, pose, gait, action, servo, buzzer, rgb, oled, estop)
        mock_send = AsyncMock(return_value={"sent": True})
        mock_estop = AsyncMock(return_value={"estop": True})
        with patch("src.robot.rosbridge_proxy.send_rosbridge_command", new=mock_send), patch(
            "src.api.routes_robots.trigger_estop", new=mock_estop
        ):
            assert client.post(f"/api/robots/{robot_id}/estop").status_code == 200
            assert client.post(f"/api/robots/{robot_id}/control/velocity", json={"x": 90, "y": 5, "yaw_rate": 2}).status_code == 200
            assert client.post(f"/api/robots/{robot_id}/control/pose", json={"preset": "Stand"}).status_code == 200
            assert client.post(f"/api/robots/{robot_id}/control/gait", json={"preset": "Fast"}).status_code == 200
            assert client.post(f"/api/robots/{robot_id}/control/action", json={"name": "wave"}).status_code == 200
            assert client.post(f"/api/robots/{robot_id}/control/servo", json={"id": 9, "pulse": 1200, "time": 400}).status_code == 200
            assert client.post(f"/api/robots/{robot_id}/control/buzzer", json={"freq": 2000}).status_code == 200
            assert client.post(f"/api/robots/{robot_id}/control/rgb", json={"data": [{"id": 1, "r": 255, "g": 80, "b": 0}]}).status_code == 200
            assert client.post(f"/api/robots/{robot_id}/control/oled", json={"index": 1, "text": "EIGENIA OK"}).status_code == 200
            # Verify clamped velocity was sent
            vel_call = mock_send.call_args_list[0].kwargs["op_payload"]
            assert vel_call["msg"] == {"x": 35.0, "y": 0.0, "yaw_rate": 0.89}

        # 6. Snapshot & Snap-to-Vision pipeline
        jpg_bytes = _make_jpeg_bytes()
        with patch("src.api.routes_robots.fetch_robot_snapshot", new=AsyncMock(return_value=jpg_bytes)):
            snap_res = client.get(f"/api/robots/{robot_id}/video/snapshot?topic=/usb_cam/image_raw")
            assert snap_res.status_code == 200
            assert snap_res.headers["content-type"] == "image/jpeg"

            s2v = client.post(
                f"/api/robots/{robot_id}/video/snap-to-vision",
                json={"topic": "/usb_cam/image_raw", "camera_yaw_deg": 0.0},
            )
            assert s2v.status_code == 200
            s2v_json = s2v.json()
            assert "extraction" in s2v_json
            assert s2v_json["image_url"].startswith("/api/files/")
            assert "suggested_pose" in s2v_json

        # 7. Remote SSH Config endpoints (wifi, password + auto credential sync, mechanics, ros, power)
        with patch("src.api.routes_robots.configure_wifi", new=AsyncMock(return_value={"updated": True, "country_code": "US"})), patch(
            "src.api.routes_robots.change_password", new=AsyncMock(return_value={"updated": True, "target_user": "pi"})
        ), patch(
            "src.api.routes_robots.configure_mechanics", new=AsyncMock(return_value={"puppy_py_updated": True, "servo_deviations": {"9": 5}})
        ), patch(
            "src.api.routes_robots.configure_ros_and_ai", new=AsyncMock(return_value={"updated": True, "active_ros_distro": "ROS2 Humble", "asr_language": "English"})
        ), patch(
            "src.api.routes_robots.power_action", new=AsyncMock(return_value={"executed": True, "action": "restart_ros"})
        ):
            assert client.put(f"/api/robots/{robot_id}/config/wifi", json={"mode": 2, "ssid": "Wildcat", "password": "pw"}).status_code == 200
            pw_res = client.put(f"/api/robots/{robot_id}/config/password", json={"target_user": "pi", "new_password": "NewPiPassword99"})
            assert pw_res.status_code == 200
            assert pw_res.json()["credential_synced"] is True
            assert client.app.state.robot_store.get_robot_ssh_password(robot_id) == "NewPiPassword99"

            assert client.put(f"/api/robots/{robot_id}/config/mechanics", json={"with_arm": True, "x_shift": -0.5}).status_code == 200
            ros_res = client.put(f"/api/robots/{robot_id}/config/ros", json={"target_ros": "ros2", "asr_language": "English"})
            assert ros_res.status_code == 200
            assert client.get(f"/api/robots/{robot_id}").json()["robot"]["active_ros_distro"] == "ROS2 Humble"
            assert client.post(f"/api/robots/{robot_id}/config/power", json={"action": "restart_ros"}).status_code == 200

        # 8. Video MJPEG stream proxy & WS unknown-robot guard
        async def fake_mjpeg(ip: str, port: int = 8080, topic: str = "/usb_cam/image_raw", timeout: float = 15.0):
            yield b"--boundarydonotcross\r\nContent-Type: image/jpeg\r\n\r\n" + jpg_bytes + b"\r\n"

        with patch("src.api.routes_robots.stream_robot_video", side_effect=fake_mjpeg):
            st_res = client.get(f"/api/robots/{robot_id}/video/stream?topic=/usb_cam/image_raw")
            assert st_res.status_code == 200
            assert b"boundarydonotcross" in st_res.content

        with client.websocket_connect("/api/robots/nonexistent-id/rosbridge") as ws:
            err = ws.receive_json()
            assert err["op"] == "proxy_error"

        # 9. Delete robot
        assert client.delete(f"/api/robots/{robot2_id}").status_code == 200
        assert client.get(f"/api/robots/{robot2_id}").status_code == 404


@pytest.mark.asyncio
async def test_ssh_command_retries_three_times_and_logs_stderr(capsys) -> None:
    """Verify run_ssh_command retries 3 times on transient errors and logs to stderr."""
    from src.robot.ssh_manager import SSHCommandError, run_ssh_command

    attempts = 0

    def always_fail(*args: Any, **kwargs: Any):
        nonlocal attempts
        attempts += 1
        raise TimeoutError("simulated transient ssh timeout")

    with patch("src.robot.ssh_manager._run_ssh_pty_sync", side_effect=always_fail), patch(
        "asyncio.sleep", new=AsyncMock()
    ):
        with pytest.raises(SSHCommandError):
            await run_ssh_command("192.168.1.231", "pi", "raspberrypi", "echo hi", retries=3)

    assert attempts == 3
    captured = capsys.readouterr()
    assert "[ssh]" in captured.err
    assert "attempt 3/3" in captured.err


@pytest.mark.asyncio
async def test_fetch_robot_snapshot_preserves_literal_topic_slashes() -> None:
    """Verify web_video_server snapshot URL keeps literal '/' instead of %2F."""
    from src.robot.rosbridge_proxy import fetch_robot_snapshot

    seen_urls: List[str] = []

    class FakeResp:
        content = b"\xff\xd8\xff\xe0test-jpeg"

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def get(self, url: str, **kwargs: Any) -> FakeResp:
            assert "params" not in kwargs
            seen_urls.append(url)
            return FakeResp()

    with patch("src.robot.rosbridge_proxy.httpx.AsyncClient", FakeClient):
        data = await fetch_robot_snapshot("192.168.1.231", 8080, "/usb_cam/image_raw")
    assert data.startswith(b"\xff\xd8\xff")
    assert seen_urls == ["http://192.168.1.231:8080/snapshot?topic=/usb_cam/image_raw"]


@pytest.mark.asyncio
async def test_configure_wifi_sta_uses_nmcli_rescan_and_returns_wlan0_ip() -> None:
    """Verify configure_wifi passes STA profile payload and uses nmcli rescan + con up workflow."""
    from src.robot.ssh_manager import _WIFI_REMOTE_SCRIPT, configure_wifi

    # Ensure remote helper compiles cleanly and contains the AP teardown + rescan + NM profile steps
    compile(_WIFI_REMOTE_SCRIPT, "_WIFI_REMOTE_SCRIPT", "exec")
    assert '"nmcli", "dev", "wifi", "rescan", "ifname", "wlan0"' in _WIFI_REMOTE_SCRIPT
    assert '"nmcli", "con", "add"' in _WIFI_REMOTE_SCRIPT
    assert '"nmcli", "con", "up", ssid' in _WIFI_REMOTE_SCRIPT
    assert "wlan0_ip" in _WIFI_REMOTE_SCRIPT

    mock_remote = AsyncMock(
        return_value={
            "updated": True,
            "mode": 2,
            "ssid": "Wildcat",
            "country_code": "US",
            "nm_connected": True,
            "wlan0_ip": "192.168.1.188",
        }
    )
    with patch("src.robot.ssh_manager.run_remote_python", new=mock_remote):
        res = await configure_wifi(
            ip="192.168.1.231",
            user="pi",
            password="raspberrypi",
            mode=2,
            ssid="Wildcat",
            wifi_password="my-sta-password",
            country_code="US",
        )
    assert res["nm_connected"] is True
    assert res["wlan0_ip"] == "192.168.1.188"
    called_payload = mock_remote.call_args.kwargs["payload"]
    assert called_payload["mode"] == 2
    assert called_payload["ssid"] == "Wildcat"
    assert called_payload["wifi_password"] == "my-sta-password"
    assert called_payload["country_code"] == "US"
    assert 'WIFI_STA_SSID = "Wildcat"' in called_payload["wifi_conf_content"]
