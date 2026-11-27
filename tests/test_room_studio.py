"""Unit and API tests for the standalone High-Fidelity Room Twin Studio."""

from __future__ import annotations

import cv2
import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes_room_studio import router as room_studio_router
from src.db.repository import InMemoryTwinRepository
from src.room_studio.models import RoomStudioStore
from src.room_studio.object_to_glb import generate_local_depth_glb, stitch_surface_photos
from src.room_studio.vision_scene_graph import compute_next_best_view, compute_physics_placement


def _make_sample_jpeg(color_bgr=(120, 160, 210), width: int = 320, height: int = 240) -> bytes:
    img = np.zeros((height, width, 3), dtype=np.uint8)
    img[:, :] = color_bgr
    cv2.rectangle(img, (60, 40), (240, 200), (40, 220, 180), -1)
    ok, enc = cv2.imencode(".jpg", img)
    assert ok
    return enc.tobytes()


def test_physics_placement_wall_mounted_vs_on_surface() -> None:
    """Wall-mounted guitars snap to the wall normal; table mugs sit at desk height."""
    guitar_pose = compute_physics_placement(
        room_width_m=4.6,
        room_length_m=4.2,
        room_height_m=2.6,
        support_type="WALL_MOUNTED",
        support_surface="west_wall",
        bbox_norm=[0.4, 0.25, 0.6, 0.75],
        dimensions_m=[0.38, 1.0, 0.12],
    )
    assert guitar_pose["x"] < -2.0  # flush against West wall (-2.3m)
    assert guitar_pose["ry"] == 90.0

    mug_pose = compute_physics_placement(
        room_width_m=4.6,
        room_length_m=4.2,
        room_height_m=2.6,
        support_type="ON_SURFACE",
        support_surface="north_wall",
        bbox_norm=[0.45, 0.5, 0.55, 0.6],
        dimensions_m=[0.1, 0.12, 0.1],
    )
    assert 0.78 <= mug_pose["y"] <= 0.90  # resting on ~0.76m desk surface


def test_local_depth_glb_and_wall_stitch() -> None:
    """Offline 3D GLB synthesizer produces valid binary glTF and wall stitcher returns JPEG."""
    jpg = _make_sample_jpeg()
    glb = generate_local_depth_glb(jpg, dimensions_m=[0.4, 1.0, 0.12])
    assert glb[:4] == b"glTF"
    assert len(glb) > 1000

    stitched, method = stitch_surface_photos([jpg, _make_sample_jpeg((140, 180, 220))])
    assert stitched[:2] == b"\xff\xd8"
    assert method in {"opencv_homography_stitch", "horizontal_mosaic_fallback"}


def test_room_studio_end_to_end_api() -> None:
    """Create project -> upload photo -> tag guitar -> generate local 3D .glb -> verify NBV coach."""
    app = FastAPI()
    repo = InMemoryTwinRepository()
    store = RoomStudioStore()
    store.attach_repository(repo)
    app.state.twin_repo = repo
    app.state.room_studio_store = store
    app.include_router(room_studio_router)
    client = TestClient(app)

    r_create = client.post(
        "/api/room-studio/projects",
        json={"name": "Music & Lab Room", "width_m": 5.0, "length_m": 4.4, "height_m": 2.7},
    )
    assert r_create.status_code == 200
    pid = r_create.json()["project"]["id"]
    assert r_create.json()["coach"]["coverage_pct"] == 0

    jpg = _make_sample_jpeg()
    r_up = client.post(
        f"/api/room-studio/projects/{pid}/photos",
        files={"file": ("west_wall.jpg", jpg, "image/jpeg")},
        data={"name": "West Wall Guitar", "surface": "west_wall", "tags": "guitar,wall"},
    )
    assert r_up.status_code == 200
    photo_id = r_up.json()["photo"]["id"]
    assert r_up.json()["coach"]["coverage_pct"] > 0

    r_obj = client.post(
        f"/api/room-studio/projects/{pid}/objects",
        json={
            "source_photo_id": photo_id,
            "name": "Acoustic Guitar",
            "category": "instrument",
            "support_type": "WALL_MOUNTED",
            "support_surface": "west_wall",
            "bbox_norm": [0.2, 0.15, 0.75, 0.85],
            "dimensions_m": [0.38, 1.02, 0.12],
        },
    )
    assert r_obj.status_code == 200
    oid = r_obj.json()["object"]["id"]

    r_3d = client.post(
        f"/api/room-studio/projects/{pid}/objects/{oid}/generate-3d",
        json={"engine": "local_depth3d"},
    )
    assert r_3d.status_code == 200
    assert r_3d.json()["object"]["mesh_engine"] == "local_depth3d"
    assert r_3d.json()["object"]["mesh_url"].startswith("/api/files/")

    coach = compute_next_best_view(r_3d.json()["project"])
    assert coach["converted_3d_count"] == 1
    assert len(coach["ghost_cameras"]) >= 1
