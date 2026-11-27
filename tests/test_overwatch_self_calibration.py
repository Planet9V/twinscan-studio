"""Unit tests for fleet camera discovery and on-demand Overwatch self-calibration."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes_overwatch import router as overwatch_router
from src.vision.fleet_camera_discovery import discover_fleet_cameras
from src.vision.overwatch_triangulator import OverwatchCameraManager
from src.vision.remote_camera_puller import RemoteOverwatchPullerManager


class _StubRobotStore:
    def list_robots(self) -> List[Dict[str, Any]]:
        return [
            {"id": "pi5", "name": "Raspberry Pi 5 16GB", "ip_address": "192.168.1.140", "is_online": True},
            {
                "id": "puppy",
                "name": "PuppyPi Pro",
                "robot_type": "puppypi_pro",
                "ip_address": "192.168.1.119",
                "video_port": 8080,
                "is_online": True,
            },
        ]


def test_discover_fleet_cameras_detects_pi_mjpg_and_puppypi() -> None:
    """Fleet discovery returns both Pi :8090 MJPG servers and PuppyPi ROS FPV streams."""
    mgr = OverwatchCameraManager()
    puller = RemoteOverwatchPullerManager()

    async def _fake_json(url: str, timeout_s: float = 2.0):
        if "192.168.1.140:8090" in url:
            return {"ok": True, "resolution": "1920x1080", "target_fps": 15.0}
        return None

    with (
        patch("src.vision.fleet_camera_discovery._probe_http_json", side_effect=_fake_json),
        patch("src.vision.fleet_camera_discovery._probe_http_alive", new=AsyncMock(return_value=True)),
    ):
        res = asyncio.run(
            discover_fleet_cameras(
                robot_store=_StubRobotStore(),
                remote_puller=puller,
                overwatch_manager=mgr,
            )
        )

    assert res["ok"] is True
    kinds = {c["kind"] for c in res["discovered"]}
    assert "pi_mjpg" in kinds
    assert "robot_fpv" in kinds


def test_self_calibration_workflow_solves_and_persists_homography() -> None:
    """Start -> capture 4 floor correspondences -> solve updates calibration metadata cleanly."""
    app = FastAPI()
    app.include_router(overwatch_router)
    app.state.overwatch_manager = OverwatchCameraManager()
    app.state.remote_overwatch_puller = RemoteOverwatchPullerManager()
    client = TestClient(app)

    r_start = client.post("/api/overwatch/self-calibrate/start", json={"camera_ids": ["usb_4k"]})
    assert r_start.status_code == 200
    assert r_start.json()["session"]["target_cameras"] == ["usb_4k"]

    samples = [
        ([-1.0, 0.5], [0.22, 0.78]),
        ([1.0, 0.5], [0.78, 0.78]),
        ([1.0, 2.5], [0.68, 0.42]),
        ([-1.0, 2.5], [0.32, 0.42]),
    ]
    for world_xy, uv in samples:
        r_pt = client.post(
            "/api/overwatch/self-calibrate/sample",
            json={"world_xy": world_xy, "manual_observations": {"usb_4k": uv}},
        )
        assert r_pt.status_code == 200

    r_solve = client.post("/api/overwatch/self-calibrate/solve")
    assert r_solve.status_code == 200
    body = r_solve.json()
    assert body["ok"] is True
    assert body["results"]["usb_4k"]["ok"] is True

    st = client.get("/api/overwatch/status?camera_id=usb_4k").json()
    assert st["calibration"]["calibrated"] is True
    assert st["calibration"]["calibration_method"] == "robot_self_cal"
    assert st["calibration"]["has_homography"] is True
