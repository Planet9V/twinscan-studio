"""Unit tests for src/robot/stability_guard.py."""

from __future__ import annotations

import pytest

from src.robot.stability_guard import (
    DEFAULT_STABILITY_PRESET,
    STABLE_GAIT_PRESETS,
    VelocitySlewLimiter,
    VisualSlipDetector,
    evaluate_imu_tilt_guard,
    get_stability_preset,
)


def test_stability_presets_and_slew_limiter() -> None:
    """Carpet preset clamps aggressive speeds and ramps smoothly over dt."""
    preset = get_stability_preset(DEFAULT_STABILITY_PRESET)
    assert preset.name == "carpet_lidar"
    assert preset.max_vx_cms <= 7.5
    assert preset.max_yaw_rads <= 0.25
    assert len(STABLE_GAIT_PRESETS) >= 3

    slew = VelocitySlewLimiter(preset)
    vx1, yaw1 = slew.step(20.0, 0.8, dt=0.25)
    # First step must ramp gradually, not snap immediately to max
    assert 0.0 < vx1 <= preset.max_accel_vx_cms2 * 0.25 + 1e-6
    assert 0.0 < yaw1 <= preset.max_accel_yaw_rads2 * 0.25 + 1e-6

    # Converges smoothly below preset caps
    for _ in range(10):
        vx_end, yaw_end = slew.step(20.0, 0.8, dt=0.25)
    assert vx_end <= preset.max_vx_cms
    assert yaw_end <= preset.max_yaw_rads


def test_imu_tilt_guard_triggers_above_threshold() -> None:
    """IMU tilt guard flags roll or pitch > 22 deg and orders halt_and_crouch."""
    ok = evaluate_imu_tilt_guard(roll_deg=5.0, pitch_deg=-8.0, max_tilt_deg=22.0)
    assert ok["safe"] is True
    assert ok["recovery_action"] == "ok"

    tipped = evaluate_imu_tilt_guard(roll_deg=26.5, pitch_deg=4.0, max_tilt_deg=22.0)
    assert tipped["safe"] is False
    assert tipped["recovery_action"] == "halt_and_crouch"
    assert "roll" in tipped["reason"]


def test_visual_slip_detector_catches_carpet_stall() -> None:
    """Walking for >4s with <4cm overhead movement triggers stall pause."""
    det = VisualSlipDetector(stall_window_sec=4.0, min_progress_m=0.04)
    pose_stuck = {"seen": True, "x": 0.5, "y": 0.5}
    assert det.update(6.0, pose_stuck, now_mono=10.0)["stalled"] is False
    assert det.update(6.0, pose_stuck, now_mono=12.0)["stalled"] is False
    res = det.update(6.0, {"seen": True, "x": 0.51, "y": 0.50}, now_mono=14.5)
    assert res["stalled"] is True
    assert "slip/stall" in res["reason"]

    # Moving >= 4cm resets stall timer
    det.reset()
    det.update(6.0, {"seen": True, "x": 0.0, "y": 0.0}, now_mono=20.0)
    ok = det.update(6.0, {"seen": True, "x": 0.25, "y": 0.0}, now_mono=23.0)
    assert ok["stalled"] is False


@pytest.mark.asyncio
async def test_auto_attach_applies_default_dark_mode_leds() -> None:
    """Startup auto-attach turns PuppyPi RGB LEDs off (0,0,0) by default."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch

    from src.app.factory import _auto_attach_live_robot_lidar
    from src.db.repository import InMemoryTwinRepository

    repo = InMemoryTwinRepository()
    rt = SimpleNamespace(
        source_mode="simulator",
        active_lidar_robot_id=None,
        _rotation_user_overridden=False,
        filter_config=SimpleNamespace(rotation_offset_deg=0.0),
        start_robot_ros2_bridge=AsyncMock(),
        repo=repo,
    )
    store = SimpleNamespace(
        list_robots=lambda: [
            {"id": "r1", "ip_address": "192.168.1.119", "active_ros_distro": "ros2", "rosbridge_port": 9090}
        ]
    )
    app = SimpleNamespace(state=SimpleNamespace(runtime=rt, robot_store=store))
    rgb_mock = AsyncMock(return_value={"sent": True})

    with (
        patch("src.app.factory._probe_tcp_port", new=AsyncMock(return_value=True)),
        patch("src.robot.rosbridge_proxy.set_rgb", new=rgb_mock),
    ):
        attached = await _auto_attach_live_robot_lidar(app)

    assert attached is True
    rgb_mock.assert_awaited_once()
    call_kwargs = rgb_mock.await_args.kwargs
    assert call_kwargs["data"] == [{"id": 1, "r": 0, "g": 0, "b": 0}, {"id": 2, "r": 0, "g": 0, "b": 0}]
