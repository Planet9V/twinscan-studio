"""Unit tests for src/lidar/multicam_room_fuser.py and new Overwatch 3D fusion routes."""

from __future__ import annotations

import cv2
import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes_overwatch import router as overwatch_router
from src.db.repository import InMemoryTwinRepository
from src.lidar.multicam_room_fuser import (
    fuse_multicam_room_digital_twin,
    suggest_blind_spot_mapping_route,
)
from src.vision.overwatch_triangulator import OverwatchCameraManager


def _make_room_jpeg(color_bgr: tuple[int, int, int] = (120, 160, 210)) -> bytes:
    img = np.full((240, 320, 3), color_bgr, dtype=np.uint8)
    cv2.rectangle(img, (40, 40), (280, 200), (40, 80, 140), 3)
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
    assert ok
    return buf.tobytes()


def test_multicam_room_fuser_merges_two_cameras_and_stores_glb() -> None:
    """Two live Overwatch cameras fuse into one non-empty GLB persisted in InMemoryTwinRepository."""
    mgr = OverwatchCameraManager()
    repo = InMemoryTwinRepository()
    mgr.ingest_frame(_make_room_jpeg((100, 150, 200)), camera_id="usb_4k", camera_name="4k Webcam")
    mgr.ingest_frame(_make_room_jpeg((150, 120, 180)), camera_id="macbook_cam", camera_name="MacBook Pro Camera")

    res = fuse_multicam_room_digital_twin(
        overwatch_manager=mgr,
        runtime=None,
        repo=repo,
        space_id=None,
        puppypi_jpeg=_make_room_jpeg((80, 180, 120)),
        resolution="low",
        allow_model_download=False,
    )
    assert res["ok"] is True
    assert res["camera_count"] == 3
    assert res["total_vertices"] > 100
    assert res["total_triangles"] > 100
    assert res["glb_bytes_len"] > 500
    assert res["glb_file_id"] is not None


def test_suggest_blind_spot_mapping_route_returns_safe_waypoints() -> None:
    """Blind-spot waypoint planner emits 2-6 safe indoor waypoints inside safe_radius_m."""
    mgr = OverwatchCameraManager()
    geo = mgr.get_geometry_snapshot()
    plan = suggest_blind_spot_mapping_route(geo, max_waypoints=4, safe_radius_m=2.0)
    assert plan["ok"] is True
    assert 2 <= len(plan["waypoints"]) <= 4
    for wp in plan["waypoints"]:
        assert (wp["x"] ** 2 + wp["y"] ** 2) ** 0.5 <= 2.05


def test_overwatch_3d_fusion_and_stability_routes() -> None:
    """FastAPI endpoints expose stability presets, mapping route suggestion, and 3D fusion."""
    app = FastAPI()
    app.include_router(overwatch_router)
    app.state.twin_repo = InMemoryTwinRepository()
    client = TestClient(app)

    r_pre = client.get("/api/overwatch/stability-presets")
    assert r_pre.status_code == 200
    assert r_pre.json()["default"] == "carpet_lidar"

    r_route = client.post("/api/overwatch/suggest-mapping-route", json={"max_waypoints": 4, "safe_radius_m": 2.0})
    assert r_route.status_code == 200
    assert len(r_route.json()["waypoints"]) >= 2

    # Ingest one camera and fuse
    r_ing = client.post(
        "/api/overwatch/ingest?camera_id=usb_4k",
        content=_make_room_jpeg(),
        headers={"Content-Type": "image/jpeg"},
    )
    assert r_ing.status_code == 200

    r_fuse = client.post(
        "/api/overwatch/reconstruct-multicam",
        json={"include_puppypi_fpv": False, "resolution": "low"},
    )
    assert r_fuse.status_code == 200
    data = r_fuse.json()
    assert data["ok"] is True
    assert data["camera_count"] == 1
    assert data["glb_bytes_len"] > 500


def test_overwatch_calibration_persistence_and_bev_task_dispatch() -> None:
    """Calibrations + 4-point homography persist across manager restarts via repo, and BEV target_xy dispatches."""
    repo = InMemoryTwinRepository()
    mgr1 = OverwatchCameraManager()
    mgr1.attach_repository(repo)
    mgr1.update_calibration({"x_m": 1.25, "y_m": -1.8, "yaw_deg": 110.0}, camera_id="usb_4k")

    # Simulate backend restart with a fresh OverwatchCameraManager
    mgr2 = OverwatchCameraManager()
    mgr2.attach_repository(repo)
    cal2 = mgr2.get_status(camera_id="usb_4k")["calibration"]
    assert abs(cal2["x_m"] - 1.25) < 1e-3
    assert abs(cal2["y_m"] - (-1.8)) < 1e-3
    assert abs(cal2["yaw_deg"] - 110.0) < 0.1

    # Direct BEV target_xy preview via /api/overwatch/task-point
    app = FastAPI()
    app.include_router(overwatch_router)
    app.state.twin_repo = repo
    app.state.overwatch_manager = mgr2
    client = TestClient(app)

    r_bev = client.post(
        "/api/overwatch/task-point",
        json={"camera_id": "bev_map", "target_xy": [0.8, 1.2], "dispatch": False},
    )
    assert r_bev.status_code == 200
    body = r_bev.json()
    assert body["projection_method"] == "bev_direct_click"
    assert abs(body["target_xy"][0] - 0.8) < 1e-3
    assert abs(body["target_xy"][1] - 1.2) < 1e-3
