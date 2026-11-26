"""Unit tests for automatic ROS 2 Humble boot persistence and ROSBridge watchdog recovery."""

from __future__ import annotations

import asyncio
import json
from typing import Any, List
from unittest.mock import AsyncMock, patch

import pytest

from src.api.state import TwinScanRuntimeState
from src.app.config import Settings
from src.db.repository import InMemoryTwinRepository
from src.robot.ssh_manager import (
    _POWER_REMOTE_SCRIPT,
    _ROS_AI_REMOTE_SCRIPT,
    configure_ros_and_ai,
    render_ros2_boot_script,
    render_ros2_systemd_unit,
    validate_ros_ai_params,
)


def test_validate_ros_ai_params_persist_boot_default_and_override() -> None:
    """``validate_ros_ai_params`` defaults ``persist_boot`` to True and preserves False."""
    default_cfg = validate_ros_ai_params(target_ros="ros2", ros_domain_id=0, rmw_implementation="rmw_cyclonedds_cpp")
    assert default_cfg["target_ros"] == "ros2"
    assert default_cfg["persist_boot"] is True

    ephemeral_cfg = validate_ros_ai_params(target_ros="ros1", persist_boot=False)
    assert ephemeral_cfg["target_ros"] == "ros1"
    assert ephemeral_cfg["persist_boot"] is False


def test_render_ros2_boot_script_and_systemd_unit() -> None:
    """Rendered boot script & unit start ``puppypi_ros2``, fix video perms, and deduplicate LD19."""
    script = render_ros2_boot_script(ros_domain_id=7, rmw_implementation="rmw_cyclonedds_cpp")
    assert script.startswith("#!/bin/bash\n")
    assert "docker stop puppypi" in script
    assert "docker start puppypi_ros2" in script
    assert "chmod 666" in script
    assert "ROS_DOMAIN_ID=7" in script
    assert "RMW_IMPLEMENTATION=rmw_cyclonedds_cpp" in script
    assert "ldlidar_stl_ros2_node" in script
    assert "awk -v self=" in script
    assert "pkill -f 'ros2 launch" not in script
    assert "rm -f /tmp/ros2_rrc.log" in script

    unit = render_ros2_systemd_unit()
    assert unit.startswith("[Unit]\n")
    assert "After=docker.service" in unit
    assert "ExecStart=/bin/bash /home/pi/puppypi/start_node_ros2.sh" in unit
    assert "WantedBy=multi-user.target" in unit
    assert "tee" not in _ROS_AI_REMOTE_SCRIPT
    assert "install" in _ROS_AI_REMOTE_SCRIPT


@pytest.mark.asyncio
async def test_configure_ros_and_ai_attaches_boot_artifacts_for_ros2() -> None:
    """Switching to ROS 2 sends rendered boot script, systemd unit, and ``persist_boot=True``."""
    mock_run = AsyncMock(return_value={"updated": True, "active_ros_distro": "humble", "boot_default": "ros2"})
    with patch("src.robot.ssh_manager.run_remote_python", mock_run):
        res = await configure_ros_and_ai(
            ip="192.168.1.119",
            user="pi",
            password="pw",
            target_ros="ros2",
            ros_domain_id=0,
            rmw_implementation="rmw_cyclonedds_cpp",
            persist_boot=True,
        )
    assert res["boot_default"] == "ros2"
    payload = mock_run.call_args.kwargs["payload"]
    assert payload["persist_boot"] is True
    assert "start_node_ros2.sh" in payload["ros2_systemd_unit"]
    assert "ldlidar_stl_ros2_node" in payload["ros2_boot_script"]
    assert "persisted_ros2_boot_default" in _ROS_AI_REMOTE_SCRIPT
    assert "persisted_ros1_boot_default" in _ROS_AI_REMOTE_SCRIPT
    assert "start_node_ros2.service" in _POWER_REMOTE_SCRIPT


@pytest.mark.asyncio
async def test_rosbridge_subscribes_without_hardcoded_type_and_recovers_on_timeout() -> None:
    """``start_robot_ros2_bridge`` omits hardcoded ROS 1/2 ``type`` and reconnects on silence."""
    rt = TwinScanRuntimeState(Settings(), repository=InMemoryTwinRepository())
    rt.source_mode = "robot_ros2"

    sent_payloads: List[dict[str, Any]] = []
    connect_calls = 0
    real_sleep = asyncio.sleep

    class _FakeWS:
        def __init__(self, idx: int) -> None:
            self.idx = idx
            self.recv_count = 0

        async def __aenter__(self) -> "_FakeWS":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def send(self, text: str) -> None:
            sent_payloads.append(json.loads(text))

        async def recv(self) -> str:
            self.recv_count += 1
            if self.idx == 1:
                raise asyncio.TimeoutError()
            if self.recv_count == 1:
                return json.dumps({
                    "op": "publish",
                    "topic": "/ros_robot_controller/battery",
                    "msg": {"data": 8270},
                })
            await real_sleep(5.0)
            return "{}"

    def _fake_connect(*args: Any, **kwargs: Any) -> _FakeWS:
        nonlocal connect_calls
        connect_calls += 1
        return _FakeWS(connect_calls)

    async def _fast_sleep(_delay: float) -> None:
        await real_sleep(0.01)

    with (
        patch("src.api.state.websockets.connect", side_effect=_fake_connect),
        patch("src.api.state.asyncio.sleep", side_effect=_fast_sleep),
    ):
        await rt.start_robot_ros2_bridge("r1", "192.168.1.119", 9090, recv_timeout_s=1.0)
        for _ in range(50):
            if rt.robot_pose.get("battery_v") == 8.27:
                break
            await real_sleep(0.02)
        await rt.stop_robot_ros2_bridge()

    assert connect_calls >= 2
    assert rt.robot_pose["battery_v"] == 8.27
    assert sent_payloads, "Expected ROSBridge subscribe messages"
    for sub in sent_payloads:
        assert sub["op"] == "subscribe"
        assert "type" not in sub, f"Hardcoded ROS type breaks ROS1/ROS2 compatibility: {sub}"
