"""Unit and API tests for the dedicated SLAM Mapping Studio (/slam)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes_slam import router as slam_router
from src.db.repository import InMemoryTwinRepository
from src.room_studio.models import RoomStudioStore
from src.slam.slam_controller import (
    SlamSessionManager,
    extract_room_and_wall_glb_from_grid,
    render_occupancy_grid_png,
)


def _make_box_occupancy_grid(w: int = 80, h: int = 80) -> list[int]:
    grid = [-1] * (w * h)
    # Free interior (20..60) with occupied perimeter walls (100)
    for y in range(20, 61):
        for x in range(20, 61):
            if x in (20, 60) or y in (20, 60):
                grid[y * w + x] = 100
            else:
                grid[y * w + x] = 0
    return grid


def test_render_occupancy_grid_png_and_3d_wall_extrusion() -> None:
    """OccupancyGrid renders to valid PNG and extrudes accurate metric 3D room walls (.glb)."""
    grid = _make_box_occupancy_grid(80, 80)
    png = render_occupancy_grid_png(
        width=80,
        height=80,
        data=grid,
        resolution=0.05,
        origin_xy=(-2.0, -2.0),
        robot_xy=(0.0, 0.0),
        trail_xy=[(0.0, 0.0), (0.3, 0.2)],
    )
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(png) > 500

    res = extract_room_and_wall_glb_from_grid(
        width=80,
        height=80,
        resolution=0.05,
        origin_xy=(-2.0, -2.0),
        data=grid,
        wall_height_m=2.6,
    )
    # 40 cells * 0.05m = 2.0m x 2.0m room
    assert 1.8 <= res["width_m"] <= 2.2
    assert 1.8 <= res["length_m"] <= 2.2
    assert res["glb_bytes"][:4] == b"glTF"
    assert res["triangle_count"] > 10


def test_slam_api_save_and_export_to_digital_twin() -> None:
    """/api/slam/status, /map-image, /save, and /export-to-twin integrate with Room Studio."""
    app = FastAPI()
    repo = InMemoryTwinRepository()
    room_store = RoomStudioStore()
    room_store.attach_repository(repo)
    mgr = SlamSessionManager()
    mgr._grid_w = 80
    mgr._grid_h = 80
    mgr._grid_res = 0.05
    mgr._grid_origin = (-2.0, -2.0)
    mgr._grid_data = _make_box_occupancy_grid(80, 80)
    mgr._has_map_data = True

    app.state.twin_repo = repo
    app.state.room_studio_store = room_store
    app.state.slam_manager = mgr
    app.include_router(slam_router)
    client = TestClient(app)

    r_st = client.get("/api/slam/status")
    assert r_st.status_code == 200
    assert r_st.json()["occupied_cells"] > 100

    r_img = client.get("/api/slam/map-image")
    assert r_img.status_code == 200
    assert r_img.content[:8] == b"\x89PNG\r\n\x1a\n"

    r_save = client.post("/api/slam/save", json={"name": "Office SLAM"})
    assert r_save.status_code == 200
    assert r_save.json()["map"]["url"].startswith("/api/files/")

    r_exp = client.post("/api/slam/export-to-twin", json={"name": "Office 3D Twin", "wall_height_m": 2.5})
    assert r_exp.status_code == 200
    body = r_exp.json()
    assert body["ok"] is True
    assert body["glb_url"].startswith("/api/files/")
    assert body["room_studio_project_id"] is not None
