"""Comprehensive pytest suite for ROS 1/2 dual-mode profiles, network telemetry, update checks, CV vision modes, and snap-to-vision resilience."""

from __future__ import annotations

import asyncio
import json
from typing import Any, List
from unittest.mock import AsyncMock, patch

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from src.app.config import Settings
from src.app.factory import create_app
from src.db.repository import InMemoryTwinRepository
from src.db.robot_store import InMemoryRobotStore
from src.robot.ros_profiles import (
    ROS_PROFILES,
    get_ros_comparison_payload,
    get_ros_profile,
    normalize_ros_mode,
)
from src.robot.rosbridge_proxy import (
    _ACTIVE_VISION_MODES,
    publish_gait,
    publish_pose,
    publish_velocity,
    run_action,
    set_buzzer,
    set_oled,
    set_rgb,
    set_servo,
    set_vision_mode,
    stop_vision_mode,
    trigger_estop,
)
from src.robot.ssh_manager import (
    _ROS_AI_REMOTE_SCRIPT,
    _WIFI_REMOTE_SCRIPT,
    configure_mechanics,
    configure_ros_and_ai,
    parse_network_interfaces,
)
from src.robot.update_checker import (
    compare_version_status,
    fetch_pypi_latest_version,
    run_robot_update_and_feature_check,
)


def _build_client(tmp_path) -> TestClient:
    cfg = Settings(
        openrouter_api_key="",
        database_url="",
        neo4j_uri="",
        twinscan_storage_dir=str(tmp_path),
        twinscan_encryption_key="dual-mode-test-key",
    )
    app = create_app(
        settings=cfg,
        repository=InMemoryTwinRepository(encryption_key=cfg.twinscan_encryption_key),
        robot_store=InMemoryRobotStore(encryption_key=cfg.twinscan_encryption_key),
    )
    return TestClient(app)


def _sample_jpeg() -> bytes:
    img = np.full((80, 120, 3), 160, dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


# --- 1. ROS 1 vs ROS 2 Profiles & Dual-Mode Message Types ---


def test_ros_profiles_and_comparison_payload() -> None:
    """Verify authoritative ROS 1 Noetic and ROS 2 Humble profiles & comparison payload."""
    assert normalize_ros_mode("ROS2 Humble") == "ros2"
    assert normalize_ros_mode("humble") == "ros2"
    assert normalize_ros_mode("puppypi_ros2") == "ros2"
    assert normalize_ros_mode("noetic") == "ros1"
    assert normalize_ros_mode(None) == "ros1"

    r1 = get_ros_profile("ros1")
    r2 = get_ros_profile("ros2")
    assert r1["message_types"]["velocity"] == "puppy_control/Velocity"
    assert r2["message_types"]["velocity"] == "puppy_control_msgs/msg/Velocity"
    assert r1["message_types"]["rgb"] == "ros_robot_controller/RGBsState"
    assert r2["message_types"]["rgb"] == "ros_robot_controller_msgs/msg/RGBsState"
    assert r2["service_types"]["run_action"] == "puppy_control_msgs/srv/SetRunActionName"
    assert r2["puppy_py_path"] == "/home/ubuntu/ros2_ws/src/driver/puppy_control/puppy_control/puppy.py"

    comp = get_ros_comparison_payload()
    assert set(comp["profiles"].keys()) == {"ros1", "ros2"}
    assert len(comp["comparison_rows"]) >= 7


@pytest.mark.asyncio
async def test_rosbridge_dual_mode_message_types() -> None:
    """Verify ROS 1 and ROS 2 publish exact verified message/service types."""
    mock_send = AsyncMock(return_value={"sent": True})
    with patch("src.robot.rosbridge_proxy.send_rosbridge_command", new=mock_send):
        await publish_velocity("192.168.1.119", 9090, 15.0, 0.0, 0.2, ros_version="ros1")
        await publish_velocity("192.168.1.119", 9090, 15.0, 0.0, 0.2, ros_version="ros2")
        await publish_pose("192.168.1.119", 9090, preset="Stand", ros_version="ros2")
        await publish_gait("192.168.1.119", 9090, preset="Fast", ros_version="ros2")
        await run_action("192.168.1.119", 9090, "wave", ros_version="ros2")
        await set_servo("192.168.1.119", 9090, 9, 1200, 300, ros_version="ros2")
        await set_buzzer("192.168.1.119", 9090, 2000, ros_version="ros2")
        await set_rgb("192.168.1.119", 9090, [{"id": 1, "r": 255, "g": 90, "b": 0}], ros_version="ros2")
        await set_oled("192.168.1.119", 9090, 1, "ROS2 OK", ros_version="ros2")

    calls = mock_send.call_args_list
    assert calls[0].kwargs["msg_type"] == "puppy_control/Velocity"
    assert calls[1].kwargs["msg_type"] == "puppy_control_msgs/msg/Velocity"
    assert calls[2].kwargs["msg_type"] == "puppy_control_msgs/msg/Pose"
    assert calls[3].kwargs["msg_type"] == "puppy_control_msgs/msg/Gait"
    assert calls[4].kwargs["op_payload"]["type"] == "puppy_control_msgs/srv/SetRunActionName"
    assert calls[5].kwargs["msg_type"] == "puppy_control_msgs/msg/SetServo"
    assert calls[6].kwargs["msg_type"] == "ros_robot_controller_msgs/msg/BuzzerState"
    assert calls[7].kwargs["msg_type"] == "ros_robot_controller_msgs/msg/RGBsState"
    assert calls[8].kwargs["msg_type"] == "ros_robot_controller_msgs/msg/OLEDState"


# --- 2. Network Interfaces Parser & Wi-Fi Reboot Hardening ---


def test_parse_network_interfaces_handles_ip_brief_without_family() -> None:
    """Verify parse_network_interfaces detects IPv4 when ip -j -br addr omits 'family'."""
    ip_br_json = json.dumps(
        [
            {
                "ifname": "wlan0",
                "operstate": "UP",
                "addr_info": [
                    {"local": "192.168.1.119", "prefixlen": 24},
                    {"local": "fe80::9afe:54ff:fe00:f0e1", "prefixlen": 64},
                ],
            },
            {
                "ifname": "eth1",
                "operstate": "UP",
                "addr_info": [{"local": "192.168.1.231", "prefixlen": 24}],
            },
            {"ifname": "eth0", "operstate": "DOWN", "addr_info": []},
        ]
    )
    nmcli_text = "\n".join(
        [
            "eth1:ethernet:connected:Wired connection 3",
            "wlan0:wifi:connected:Wildcat",
            "eth0:ethernet:unavailable:",
            "eth2:ethernet:unavailable:",
        ]
    )
    iw_text = "Connected to ec:c3:02:32:aa:48 (on wlan0)\n\tSSID: Wildcat\n\tfreq: 5260\n\tsignal: -56 dBm\n"
    parsed = parse_network_interfaces(
        ip_json_text=ip_br_json,
        nmcli_text=nmcli_text,
        iw_link_text=iw_text,
        mac_map={"wlan0": "98:fe:54:00:f0:e1", "eth1": "00:e0:4c:68:01:22"},
    )
    assert parsed["wifi"]["enabled"] is True
    assert parsed["wifi"]["ipv4"] == "192.168.1.119"
    assert parsed["wifi"]["ssid"] == "Wildcat"
    assert parsed["wifi"]["freq_mhz"] == 5260
    assert parsed["wifi"]["signal_pct"] == 88
    assert parsed["wifi"]["mac"] == "98:fe:54:00:f0:e1"
    assert parsed["wifi"]["mode"] == "sta"

    eth_by_name = {e["ifname"]: e for e in parsed["ethernet"]}
    assert eth_by_name["eth1"]["enabled"] is True
    assert eth_by_name["eth1"]["ipv4"] == "192.168.1.231"
    assert eth_by_name["eth0"]["enabled"] is False
    assert eth_by_name["eth2"]["enabled"] is False


def test_wifi_and_ros2_scripts_contain_reboot_and_bringup_hardening() -> None:
    """Verify Wi-Fi script disables wifi.service + powersave in STA mode, and ROS 2 script launches bringup."""
    compile(_WIFI_REMOTE_SCRIPT, "_WIFI_REMOTE_SCRIPT", "exec")
    assert '"systemctl", "disable", "wifi.service"' in _WIFI_REMOTE_SCRIPT
    assert '"802-11-wireless.powersave", "2"' in _WIFI_REMOTE_SCRIPT
    assert '"connection.autoconnect-priority", "10"' in _WIFI_REMOTE_SCRIPT
    assert '"systemctl", "enable", "wifi.service"' in _WIFI_REMOTE_SCRIPT

    compile(_ROS_AI_REMOTE_SCRIPT, "_ROS_AI_REMOTE_SCRIPT", "exec")
    assert "ros2 launch ros_robot_controller ros_robot_controller.launch.py" in _ROS_AI_REMOTE_SCRIPT
    assert "ros2 launch puppy_control puppy_control.launch.py" in _ROS_AI_REMOTE_SCRIPT
    assert "ros2 launch peripherals web_video_server.launch.py" in _ROS_AI_REMOTE_SCRIPT
    assert "ros2 launch rosbridge_server rosbridge_websocket_launch.xml" in _ROS_AI_REMOTE_SCRIPT


@pytest.mark.asyncio
async def test_configure_mechanics_and_ros2_params() -> None:
    """Verify configure_mechanics forwards ros_version and configure_ros_and_ai forwards DDS params."""
    mock_remote = AsyncMock(return_value={"puppy_py_updated": True, "container": "puppypi_ros2"})
    with patch("src.robot.ssh_manager.run_remote_python", new=mock_remote):
        await configure_mechanics("192.168.1.119", "pi", "pw", with_arm=1, ros_version="ros2")
    assert mock_remote.call_args.kwargs["payload"]["ros_version"] == "ros2"

    mock_ros = AsyncMock(return_value={"updated": True, "active_ros_distro": "humble"})
    with patch("src.robot.ssh_manager.run_remote_python", new=mock_ros):
        await configure_ros_and_ai(
            "192.168.1.119", "pi", "pw", target_ros="ros2", asr_language="English", ros_domain_id=7
        )
    assert mock_ros.call_args.kwargs["payload"]["ros_domain_id"] == 7
    assert mock_ros.call_args.kwargs["payload"]["rmw_implementation"] == "rmw_cyclonedds_cpp"


# --- 3. CV Vision Mode Activation, Heartbeat & E-STOP Cleanup ---


@pytest.mark.asyncio
async def test_vision_mode_enter_running_heartbeat_exit_and_estop_cleanup() -> None:
    """Verify CV vision mode calls enter/set_running/heartbeat and exits cleanly on raw or E-STOP."""
    _ACTIVE_VISION_MODES.clear()
    called_services: List[tuple[str, str, Any]] = []

    async def fake_send(ip: str, port: int, op_payload: dict[str, Any], **kwargs: Any):
        called_services.append((op_payload["service"], op_payload.get("type", ""), op_payload.get("args")))
        return {"sent": True}

    with patch("src.robot.rosbridge_proxy.send_rosbridge_command", side_effect=fake_send):
        res = await set_vision_mode(
            robot_id="bot-1",
            ip="192.168.1.119",
            mode="visual_patrol",
            ros_version="ros1",
            heartbeat_interval_s=0.05,
        )
        assert res == {
            "ok": True,
            "mode": "visual_patrol",
            "topic": "/visual_patrol/image_result",
            "heartbeat_active": True,
        }
        assert "bot-1" in _ACTIVE_VISION_MODES
        await asyncio.sleep(0.12)  # let background heartbeat fire at least once

        # Switching back to raw stops heartbeat & exits visual_patrol
        raw_res = await set_vision_mode(robot_id="bot-1", ip="192.168.1.119", mode="raw", ros_version="ros1")
        assert raw_res["heartbeat_active"] is False
        assert "bot-1" not in _ACTIVE_VISION_MODES

        svc_names = [s[0] for s in called_services]
        assert "/visual_patrol/enter" in svc_names
        assert "/visual_patrol/set_running" in svc_names
        assert svc_names.count("/visual_patrol/heartbeat") >= 2
        assert "/visual_patrol/exit" in svc_names

        # Re-enter in ROS 2 mode and verify E-STOP stops heartbeat & calls ROS 2 exit service type
        called_services.clear()
        await set_vision_mode(
            robot_id="bot-1",
            ip="192.168.1.119",
            mode="apriltag_detect",
            ros_version="ros2",
            heartbeat_interval_s=0.5,
        )
        assert "bot-1" in _ACTIVE_VISION_MODES

        class DummyWS:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def send(self, msg: str) -> None:
                return None

        with patch("src.robot.rosbridge_proxy.websockets.connect", return_value=DummyWS()):
            estop_res = await trigger_estop("192.168.1.119", 9090, ros_version="ros2", robot_id="bot-1")
        assert estop_res["estop"] is True
        assert "bot-1" not in _ACTIVE_VISION_MODES
        assert any(s == "/apriltag_detect/exit" and t == "std_srvs/srv/Trigger" for s, t, _ in called_services)
        await stop_vision_mode("bot-1")


# --- 4. Update & Feature Readiness Checker ---


@pytest.mark.asyncio
async def test_update_checker_compares_versions_and_retries_pypi(capsys) -> None:
    """Verify PyPI lookup retries 3x on transient errors and update report flags readiness."""
    assert compare_version_status("1.2.0", "1.3.0") == "update_available"
    assert compare_version_status("2.0.0", "2.0.0") == "up_to_date"
    assert compare_version_status(None, "2.0.0") == "not_installed"

    attempts = 0

    class FailingClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url: str):
            nonlocal attempts
            attempts += 1
            raise RuntimeError("pypi unreachable")

    with patch("src.robot.update_checker.httpx.AsyncClient", FailingClient), patch("asyncio.sleep", new=AsyncMock()):
        ver = await fetch_pypi_latest_version("torch", retries=3)
    assert ver is None
    assert attempts == 3
    assert "[update_checker]" in capsys.readouterr().err

    with patch("src.robot.update_checker.fetch_pypi_latest_version", new=AsyncMock(return_value="9.9.9")), patch(
        "src.robot.update_checker._query_apt_upgradable_count", new=AsyncMock(return_value=12)
    ):
        report = await run_robot_update_and_feature_check(
            robot={
                "id": "r1",
                "ip_address": "192.168.1.119",
                "active_ros_distro": "noetic",
                "status": "online",
                "capabilities": {"has_camera": True, "live_config": {"with_arm": 0, "asr_language": "English"}},
            },
            devices=[
                {"subsystem": "camera", "device_path": "/dev/video0", "status": "online"},
                {"subsystem": "lidar", "device_path": "/dev/ttyUSB0", "status": "unattached"},
            ],
            sbom=[{"name": "pyserial", "version": "3.5", "layer": "host_pip"}],
            openrouter_configured=False,
        )
    assert report["ros_lifecycle"]["active_mode"] == "ros1"
    assert report["ros_lifecycle"]["is_eol"] is True
    assert report["ros_lifecycle"]["apt_upgradable_count"] == 12
    assert any(f["subsystem"] == "lidar" and f["status"] == "warning" for f in report["features"])
    assert any(f["subsystem"] == "camera" and f["status"] == "ready" for f in report["features"])
    assert report["summary"]["updates_available"] >= 1


# --- 5. FastAPI Routes Integration Tests ---


def test_new_dual_mode_network_update_vision_mode_and_snap_502_routes(tmp_path) -> None:
    """Verify /ros-comparison, /network, /active-ip, /update-check, /control/vision-mode, and graceful 502 on snap-to-vision."""
    with _build_client(tmp_path) as client:
        # 1. ROS comparison endpoint (must NOT be shadowed by /{robot_id})
        comp = client.get("/api/robots/ros-comparison")
        assert comp.status_code == 200
        assert comp.json()["profiles"]["ros2"]["distro"] == "humble"

        # Register robot
        reg = client.post(
            "/api/robots",
            json={"ip_address": "192.168.1.231", "name": "PuppyPi Pro", "ssh_user": "pi", "ssh_password": "pw"},
        )
        assert reg.status_code == 200
        rid = reg.json()["robot"]["id"]

        # 2. Live network endpoint + caching
        fake_net = {
            "wifi": {"ifname": "wlan0", "enabled": True, "state": "UP", "mode": "sta", "ssid": "Wildcat", "ipv4": "192.168.1.119", "mac": "98:fe:54:00:f0:e1", "freq_mhz": 5260, "signal_pct": 80, "connection": "Wildcat"},
            "ethernet": [{"ifname": "eth1", "enabled": True, "state": "UP", "ipv4": "192.168.1.231", "mac": "aa:bb:cc:dd:ee:ff", "connection": "Wired", "kind": "usb"}],
            "interfaces": [],
        }
        with patch("src.api.routes_robots.collect_network_interfaces", new=AsyncMock(return_value=fake_net)):
            net_res = client.get(f"/api/robots/{rid}/network")
        assert net_res.status_code == 200
        assert net_res.json()["wifi"]["ipv4"] == "192.168.1.119"
        assert net_res.json()["source"] == "live"

        # 3. Switch active IP to Wi-Fi
        sw = client.put(f"/api/robots/{rid}/active-ip", json={"ip_address": "192.168.1.119"})
        assert sw.status_code == 200
        assert sw.json()["robot"]["ip_address"] == "192.168.1.119"
        assert client.put(f"/api/robots/{rid}/active-ip", json={"ip_address": "not-an-ip"}).status_code == 400

        # 4. Update & Feature Readiness check
        with patch("src.robot.update_checker.fetch_pypi_latest_version", new=AsyncMock(return_value="3.5")), patch(
            "src.robot.update_checker._query_apt_upgradable_count", new=AsyncMock(return_value=0)
        ):
            upd = client.post(f"/api/robots/{rid}/update-check")
        assert upd.status_code == 200
        assert "features" in upd.json()
        assert "ros_lifecycle" in upd.json()

        # 5. CV Vision Mode route
        with patch(
            "src.api.routes_robots.set_vision_mode",
            new=AsyncMock(return_value={"ok": True, "mode": "visual_patrol", "topic": "/visual_patrol/image_result", "heartbeat_active": True}),
        ):
            vm = client.post(f"/api/robots/{rid}/control/vision-mode", json={"mode": "visual_patrol"})
        assert vm.status_code == 200
        assert vm.json()["heartbeat_active"] is True

        # 6. Snap-to-vision returns graceful HTTP 502 with CORS-safe JSON detail when OpenRouter fails (e.g. 401)
        jpg = _sample_jpeg()
        with patch("src.api.routes_robots.fetch_robot_snapshot", new=AsyncMock(return_value=jpg)), patch.object(
            client.app.state.runtime.vision,
            "analyze_equipment_image",
            new=AsyncMock(side_effect=RuntimeError("OpenRouter 401 Unauthorized")),
        ):
            snap_err = client.post(
                f"/api/robots/{rid}/video/snap-to-vision",
                json={"topic": "/usb_cam/image_raw"},
                headers={"Origin": "http://localhost:3000"},
            )
        assert snap_err.status_code == 502
        assert "OpenRouter 401 Unauthorized" in snap_err.json()["detail"]
        assert snap_err.headers.get("access-control-allow-origin") in ("*", "http://localhost:3000")

        # 7. Config ROS persists exact distro ("humble") in DB
        with patch(
            "src.api.routes_robots.configure_ros_and_ai",
            new=AsyncMock(return_value={"updated": True, "active_ros_distro": "humble", "asr_language": "English", "actions": ["switched_to_ros2_humble"]}),
        ):
            r_ros = client.put(
                f"/api/robots/{rid}/config/ros",
                json={"target_ros": "ros2", "asr_language": "English", "ros_domain_id": 0},
            )
        assert r_ros.status_code == 200
        assert client.get(f"/api/robots/{rid}").json()["robot"]["active_ros_distro"] == "humble"
