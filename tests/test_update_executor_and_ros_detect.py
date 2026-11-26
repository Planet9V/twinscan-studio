"""Pytest suite for sudo-docker ROS detection, Safe Robot Update Engine, Rollback, 6-Point Smoke Tests, and /updates/* routes."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.app.config import Settings
from src.app.factory import create_app
from src.db.repository import InMemoryTwinRepository
from src.db.robot_store import InMemoryRobotStore
from src.robot.ssh_manager import (
    _CATALOGUE_REMOTE_SCRIPT,
    _NETWORK_REMOTE_SCRIPT,
    collect_network_interfaces,
)
from src.robot.update_executor import (
    ABI_SENSITIVE_PACKAGES,
    PROTECTED_APT_PACKAGES,
    apply_apt_updates,
    apply_pip_updates,
    parse_apt_simulation,
    parse_pip_dry_run,
    parse_snapshot_list,
    rollback_container_snapshot,
    run_post_update_smoke_tests,
)


def _build_client(tmp_path) -> TestClient:
    cfg = Settings(
        openrouter_api_key="",
        database_url="",
        neo4j_uri="",
        twinscan_storage_dir=str(tmp_path),
        twinscan_encryption_key="update-exec-test-key",
    )
    app = create_app(
        settings=cfg,
        repository=InMemoryTwinRepository(encryption_key=cfg.twinscan_encryption_key),
        robot_store=InMemoryRobotStore(encryption_key=cfg.twinscan_encryption_key),
    )
    return TestClient(app)


# --- 1. sudo -S docker ROS Detection Tests ---


def test_remote_scripts_use_sudo_pw_env_and_docker_fallback() -> None:
    """Verify catalogue and network scripts compile and use SUDO_PW env + sudo -S docker fallback."""
    compile(_CATALOGUE_REMOTE_SCRIPT, "_CATALOGUE_REMOTE_SCRIPT", "exec")
    compile(_NETWORK_REMOTE_SCRIPT, "_NETWORK_REMOTE_SCRIPT", "exec")
    assert 'os.environ.get("SUDO_PW"' in _CATALOGUE_REMOTE_SCRIPT
    assert '"sudo", "-S", "-p", "", "docker"' in _CATALOGUE_REMOTE_SCRIPT
    assert 'os.environ.get("SUDO_PW"' in _NETWORK_REMOTE_SCRIPT
    assert '"sudo", "-S", "-p", "", "docker"' in _NETWORK_REMOTE_SCRIPT


@pytest.mark.asyncio
async def test_collect_network_interfaces_passes_sudo_pw_and_returns_ros_distro() -> None:
    """Verify collect_network_interfaces passes SUDO_PW env var and returns active_ros_distro + ros_containers."""
    mock_remote = AsyncMock(
        return_value={
            "ip_br_json": json.dumps([{"ifname": "wlan0", "operstate": "UP", "addr_info": [{"local": "192.168.1.119"}]}]),
            "nmcli_status": "wlan0:wifi:connected:Wildcat",
            "iw_link": "SSID: Wildcat\nfreq: 5260\nsignal: -54 dBm",
            "mac_map": {"wlan0": "98:fe:54:00:f0:e1"},
            "active_ros_distro": "ROS1 Noetic",
            "ros_containers": [{"name": "puppypi", "state": "running", "status": "Up 2 hours", "ros_distro": "ROS1 Noetic"}],
        }
    )
    with patch("src.robot.ssh_manager.run_remote_python", new=mock_remote):
        res = await collect_network_interfaces("192.168.1.119", "pi", "raspberrypi")

    assert mock_remote.call_args.kwargs["env_vars"] == {"SUDO_PW": "raspberrypi"}
    assert res["active_ros_distro"] == "ROS1 Noetic"
    assert len(res["ros_containers"]) == 1
    assert res["wifi"]["ipv4"] == "192.168.1.119"


# --- 2. Apt & Pip Parsers & Safety Guard Tests ---


def test_parse_apt_simulation_and_protected_blocking() -> None:
    """Verify apt simulation parser extracts Inst upgrades, security flag, and blocked protected Remv packages."""
    sim_out = "\n".join(
        [
            "Inst curl [7.88.1-10+deb12u6] (7.88.1-10+deb12u8 Debian-Security:12/stable-security [arm64])",
            "Inst git [1:2.39.2-1.1] (1:2.39.5-0+deb12u1 Debian:12.8/stable [arm64])",
            "Remv network-manager [1.42.4-1]",
        ]
    )
    parsed = parse_apt_simulation(sim_out)
    assert parsed["upgradable_count"] == 2
    assert parsed["packages"][0]["name"] == "curl"
    assert parsed["packages"][0]["is_security"] is True
    assert parsed["packages"][1]["is_security"] is False
    assert parsed["protected_blocked"] == ["network-manager"]


def test_parse_pip_dry_run_and_snapshots() -> None:
    """Verify pip dry-run parser flags ABI-sensitive libs and snapshot parser filters pre-update-* tags."""
    pip_out = "Would install openai-1.60.0 opencv-python-4.11.0.86\n"
    parsed = parse_pip_dry_run(pip_out, requested=["openai", "opencv-python"])
    assert parsed["upgradable_count"] == 2
    assert parsed["abi_sensitive_packages"] == ["opencv-python"]
    assert "torch" in ABI_SENSITIVE_PACKAGES
    assert "openssh-server" in PROTECTED_APT_PACKAGES

    snaps = parse_snapshot_list(
        "puppypi:latest\t2 weeks ago\t5.1GB\npuppypi:pre-update-20261125-040000\t2 minutes ago\t5.2GB\n"
    )
    assert len(snaps) == 1
    assert snaps[0]["tag"] == "puppypi:pre-update-20261125-040000"


@pytest.mark.asyncio
async def test_apt_protected_block_and_pip_abi_guard_and_snapshot_order() -> None:
    """Verify protected apt removal blocks apply, ABI pip guard blocks unless overridden, and snapshot runs before pip install."""
    # 1. Protected apt package removal blocks apply_apt_updates before running apply
    with patch(
        "src.robot.update_executor.preview_apt_updates",
        new=AsyncMock(return_value={"ok": True, "protected_blocked": ["openssh-server"], "stdout_tail": "", "stderr_tail": ""}),
    ):
        blocked = await apply_apt_updates("192.168.1.119", "pi", "pw")
    assert blocked["ok"] is False
    assert blocked["status"] == "blocked_protected_packages"
    assert blocked["protected_blocked"] == ["openssh-server"]

    # 2. ABI-sensitive pip package blocks when allow_abi_sensitive=False
    abi_blocked = await apply_pip_updates(
        "192.168.1.119", "pi", "pw", "puppypi", ["torch", "openai"], allow_abi_sensitive=False
    )
    assert abi_blocked["ok"] is False
    assert abi_blocked["status"] == "blocked_abi_sensitive"
    assert abi_blocked["abi_sensitive_packages"] == ["torch"]

    # 3. When allowed, snapshot_ros_container executes BEFORE pip install
    call_order: list[str] = []

    async def fake_snap(*args, **kwargs):
        call_order.append("snapshot")
        return {"ok": True, "rollback_tag": "puppypi:pre-update-20261125-040500", "container": "puppypi"}

    async def fake_remote(*args, **kwargs):
        call_order.append("pip_apply")
        return {"returncode": 0, "stdout": "Successfully installed openai-1.60.0", "stderr": ""}

    with patch("src.robot.update_executor.snapshot_ros_container", side_effect=fake_snap), patch(
        "src.robot.update_executor.run_remote_python", side_effect=fake_remote
    ):
        applied = await apply_pip_updates(
            "192.168.1.119", "pi", "pw", "puppypi", ["openai"], allow_abi_sensitive=False
        )
    assert applied["ok"] is True
    assert applied["rollback_tag"] == "puppypi:pre-update-20261125-040500"
    assert call_order == ["snapshot", "pip_apply"]


@pytest.mark.asyncio
async def test_rollback_validation_and_execution() -> None:
    """Verify rollback validates tag format & container match and returns rolled_back on success."""
    with pytest.raises(ValueError):
        await rollback_container_snapshot("192.168.1.119", "pi", "pw", "puppypi", "evil;rm -rf /")
    with pytest.raises(ValueError):
        await rollback_container_snapshot("192.168.1.119", "pi", "pw", "puppypi", "puppypi_ros2:pre-update-20261125-040500")

    with patch(
        "src.robot.update_executor.run_remote_python",
        new=AsyncMock(return_value={"ok": True, "container": "puppypi", "rollback_tag": "puppypi:pre-update-20261125-040500", "stdout": "abc", "stderr": ""}),
    ):
        rb = await rollback_container_snapshot(
            "192.168.1.119", "pi", "pw", "puppypi", "puppypi:pre-update-20261125-040500"
        )
    assert rb["ok"] is True
    assert rb["status"] == "rolled_back"


# --- 3. 6-Point Smoke Test Suite ---


@pytest.mark.asyncio
async def test_run_post_update_smoke_tests_all_six_pass() -> None:
    """Verify all 6 post-update smoke checks execute and report structured pass results."""
    class FakeWS:
        def __init__(self) -> None:
            self._msgs = [
                json.dumps({"op": "service_response", "service": "/rosapi/nodes", "values": {"nodes": ["/puppy_control", "/usb_cam"]}}),
                json.dumps({"op": "publish", "topic": "/ros_robot_controller/battery", "msg": {"data": 7450}}),
            ]

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def send(self, msg: str) -> None:
            return None

        async def recv(self) -> str:
            return self._msgs.pop(0)

    with patch("src.robot.update_executor.run_ssh_command", new=AsyncMock(return_value=(0, "SSH_READY\n192.168.1.119"))), patch(
        "src.robot.update_executor.run_remote_python",
        new=AsyncMock(
            return_value={
                "container_running": True,
                "container_status": "Up 10 minutes",
                "import_ok": True,
                "import_detail": "Verified 3 imports (cv2, numpy, openai)",
                "rrc_exists": True,
            }
        ),
    ), patch("src.robot.update_executor.websockets.connect", return_value=FakeWS()), patch(
        "src.robot.update_executor.fetch_robot_snapshot", new=AsyncMock(return_value=b"\xff\xd8\xff" + b"0" * 200)
    ):
        report = await run_post_update_smoke_tests(
            "192.168.1.119", "pi", "pw", ros_mode="ros1", updated_packages=["openai"]
        )

    assert report["passed"] is True
    assert report["passed_count"] == 6
    assert report["total_count"] == 6
    ids = [c["id"] for c in report["checks"]]
    assert ids == [
        "wifi_ssh",
        "docker_ros_container",
        "package_imports",
        "ros_graph_rosbridge",
        "fpv_camera",
        "stm32_battery",
    ]


# --- 4. Store Jobs + All 6 FastAPI /updates/* Routes + /network ROS Distro Persistence ---


def test_update_jobs_store_and_all_six_update_routes(tmp_path) -> None:
    """Verify robot_update_jobs persistence, /network ROS persistence, and all 6 /updates/* FastAPI endpoints."""
    with _build_client(tmp_path) as client:
        reg = client.post(
            "/api/robots",
            json={"ip_address": "192.168.1.119", "name": "PuppyPi Wi-Fi", "ssh_user": "pi", "ssh_password": "pw"},
        )
        assert reg.status_code == 200
        rid = reg.json()["robot"]["id"]

        # 1. GET /network persists detected active_ros_distro into robot row!
        fake_net = {
            "wifi": {"ifname": "wlan0", "enabled": True, "state": "UP", "mode": "sta", "ssid": "Wildcat", "ipv4": "192.168.1.119"},
            "ethernet": [],
            "interfaces": [],
            "active_ros_distro": "ROS1 Noetic",
            "ros_containers": [{"name": "puppypi", "state": "running", "status": "Up 1h", "ros_distro": "ROS1 Noetic"}],
        }
        with patch("src.api.routes_robots.collect_network_interfaces", new=AsyncMock(return_value=fake_net)):
            nr = client.get(f"/api/robots/{rid}/network")
        assert nr.status_code == 200
        assert nr.json()["active_ros_distro"] == "ROS1 Noetic"
        assert client.get(f"/api/robots/{rid}").json()["robot"]["active_ros_distro"] == "ROS1 Noetic"

        # 2. Dry-run (host_apt + ros_pip)
        with patch(
            "src.api.routes_robots.preview_apt_updates",
            new=AsyncMock(return_value={"ok": True, "track": "host_apt", "action": "dry_run", "status": "preview_ready", "upgradable_count": 1, "packages": [{"name": "curl", "current_version": "7.88", "candidate_version": "7.89", "is_security": True}], "protected_blocked": []}),
        ):
            dr = client.post(f"/api/robots/{rid}/updates/dry-run", json={"track": "host_apt"})
        assert dr.status_code == 200
        assert dr.json()["upgradable_count"] == 1
        assert dr.json()["job"]["action"] == "dry_run"

        # 3. Download
        with patch(
            "src.api.routes_robots.download_pip_updates",
            new=AsyncMock(return_value={"ok": True, "track": "ros_pip", "action": "download", "container": "puppypi", "status": "downloaded", "packages": [{"name": "openai"}]}),
        ):
            dl = client.post(f"/api/robots/{rid}/updates/download", json={"track": "ros_pip", "packages": ["openai"]})
        assert dl.status_code == 200
        assert dl.json()["status"] == "downloaded"

        # 4. Apply + Smoke Tests + Re-catalogue
        fake_smoke = {"passed": True, "passed_count": 6, "total_count": 6, "checks": [{"id": "wifi_ssh", "name": "SSH", "status": "pass", "detail": "ok"}]}
        with patch(
            "src.api.routes_robots.apply_pip_updates",
            new=AsyncMock(return_value={"ok": True, "track": "ros_pip", "action": "apply", "container": "puppypi", "status": "applied", "rollback_tag": "puppypi:pre-update-20261125-041000", "packages": [{"name": "openai"}]}),
        ), patch("src.api.routes_robots.run_post_update_smoke_tests", new=AsyncMock(return_value=fake_smoke)), patch(
            "src.api.routes_robots.collect_robot_catalogue",
            new=AsyncMock(return_value={"devices": [], "sbom_packages": [], "hbom_sbom": {"bomFormat": "CycloneDX", "specVersion": "1.6"}, "robot_updates": {"active_ros_distro": "noetic"}}),
        ):
            ap = client.post(
                f"/api/robots/{rid}/updates/apply",
                json={"track": "ros_pip", "packages": ["openai"], "allow_abi_sensitive": False, "run_tests": True},
            )
        assert ap.status_code == 200
        assert ap.json()["rollback_tag"] == "puppypi:pre-update-20261125-041000"
        assert ap.json()["smoke_tests"]["passed"] is True

        # 5. Standalone Smoke Test endpoint
        with patch("src.api.routes_robots.run_post_update_smoke_tests", new=AsyncMock(return_value=fake_smoke)):
            ts = client.post(f"/api/robots/{rid}/updates/test", json={"packages": ["openai"]})
        assert ts.status_code == 200
        assert ts.json()["ok"] is True

        # 6. Rollback endpoint
        with patch(
            "src.api.routes_robots.rollback_container_snapshot",
            new=AsyncMock(return_value={"ok": True, "track": "ros_pip", "action": "rollback", "container": "puppypi", "status": "rolled_back", "rollback_tag": "puppypi:pre-update-20261125-041000"}),
        ), patch("src.api.routes_robots.run_post_update_smoke_tests", new=AsyncMock(return_value=fake_smoke)):
            rb = client.post(
                f"/api/robots/{rid}/updates/rollback",
                json={"rollback_tag": "puppypi:pre-update-20261125-041000", "container": "puppypi"},
            )
        assert rb.status_code == 200
        assert rb.json()["status"] == "rolled_back"

        # 7. History endpoint returns all 5 recorded jobs + live snapshots
        with patch(
            "src.api.routes_robots.list_container_snapshots",
            new=AsyncMock(return_value=[{"tag": "puppypi:pre-update-20261125-041000", "created": "1m ago", "size": "5.2GB"}]),
        ):
            hist = client.get(f"/api/robots/{rid}/updates/history")
        assert hist.status_code == 200
        assert len(hist.json()["jobs"]) == 5
        assert len(hist.json()["snapshots"]) == 1


# --- 5. #94 PuppyPi Control Fixes (Two-Step Pose, Auto-Stop CV, Go-Home, Mark-Time, Autogait, ActionGroups) ---


@pytest.mark.asyncio
async def test_two_step_pose_auto_stop_cv_go_home_mark_time_and_autogait() -> None:
    """Verify two-step Pose (run_time=0 then 500), auto-stop CV before motion, go_home, mark_time, autogait toggle, and .d6ac/.d6a."""
    from src.robot.rosbridge_proxy import (
        _ACTIVE_VISION_MODES,
        call_go_home,
        normalize_action_group_name,
        publish_pose,
        publish_velocity,
        set_mark_time,
        set_vision_mode,
    )

    assert normalize_action_group_name("sit") == "sit.d6ac"
    assert normalize_action_group_name("bow") == "bow.d6ac"
    assert normalize_action_group_name("look_down.d6ac") == "look_down.d6ac"
    assert normalize_action_group_name("look_down.d6a") == "look_down.d6a"
    assert normalize_action_group_name("Clamping") == "Clamping.d6a"
    assert normalize_action_group_name("1") == "1.d6a"

    _ACTIVE_VISION_MODES.clear()
    calls: list[dict[str, Any]] = []

    async def fake_send(ip: str, port: int, op_payload: dict[str, Any], **kwargs: Any):
        calls.append({"op_payload": op_payload, **kwargs})
        return {"sent": True}

    with patch("src.robot.rosbridge_proxy.send_rosbridge_command", side_effect=fake_send):
        # Activate face_detect CV mode
        await set_vision_mode("r-cv", "192.168.1.119", "face_detect", ros_version="ros1", heartbeat_interval_s=5.0)
        assert "r-cv" in _ACTIVE_VISION_MODES

        # Manual publish_pose MUST stop face_detect FIRST, then send two-step Pose (run_time=0 -> run_time=500)
        calls.clear()
        await publish_pose("192.168.1.119", 9090, preset="Stand", ros_version="ros1", robot_id="r-cv")
        assert "r-cv" not in _ACTIVE_VISION_MODES
        services = [c["op_payload"].get("service") for c in calls]
        assert "/face_detect/set_running" in services
        assert "/face_detect/exit" in services
        pose_call = calls[-1]
        assert pose_call["op_payload"]["topic"] == "/puppy_control/pose"
        assert pose_call["op_payload"]["msg"]["run_time"] == 0
        assert len(pose_call["extra_publishes"]) == 1
        assert pose_call["extra_publishes"][0]["msg"]["run_time"] == 500

        # Velocity with use_autogait=False uses /puppy_control/velocity
        calls.clear()
        await publish_velocity("192.168.1.119", 9090, 12.0, 0.0, 0.0, use_autogait=False)
        assert calls[0]["op_payload"]["topic"] == "/puppy_control/velocity"

        # go_home & set_mark_time
        calls.clear()
        await call_go_home("192.168.1.119", 9090, ros_version="ros2")
        assert calls[0]["op_payload"]["service"] == "/puppy_control/go_home"
        assert calls[0]["op_payload"]["type"] == "std_srvs/srv/Empty"

        calls.clear()
        await set_mark_time("192.168.1.119", True, 9090, ros_version="ros1")
        assert calls[0]["op_payload"]["service"] == "/puppy_control/set_mark_time"
        assert calls[0]["op_payload"]["args"] == {"data": True}


def test_go_home_mark_time_and_autogait_routes(tmp_path) -> None:
    """Verify FastAPI /control/go-home, /control/mark-time, and /control/velocity use_autogait=false."""
    with _build_client(tmp_path) as client:
        rid = client.post(
            "/api/robots",
            json={"ip_address": "192.168.1.119", "name": "PuppyPi", "ssh_user": "pi", "ssh_password": "pw"},
        ).json()["robot"]["id"]
        mock_send = AsyncMock(return_value={"sent": True})
        with patch("src.robot.rosbridge_proxy.send_rosbridge_command", new=mock_send):
            assert client.post(f"/api/robots/{rid}/control/go-home").status_code == 200
            assert client.post(f"/api/robots/{rid}/control/mark-time", json={"enabled": True}).status_code == 200
            assert (
                client.post(
                    f"/api/robots/{rid}/control/velocity",
                    json={"x": 15, "y": 0, "yaw_rate": 0, "use_autogait": False},
                ).status_code
                == 200
            )
        assert mock_send.call_args_list[0].kwargs["op_payload"]["service"] == "/puppy_control/go_home"
        assert mock_send.call_args_list[1].kwargs["op_payload"]["service"] == "/puppy_control/set_mark_time"
        assert mock_send.call_args_list[2].kwargs["op_payload"]["topic"] == "/puppy_control/velocity"
