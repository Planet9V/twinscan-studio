"""Unit and API tests for 1:1 mm Hardware Catalog, Parametric Enclosure CAD & Photo-to-3D Shapes."""

from __future__ import annotations

import base64
import json

import cv2
import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes_microbit import router as microbit_router
from src.microbit.ai_copilot import apply_deterministic_copilot_fallback
from src.microbit.catalog import BOARD_PROFILES, MICROBIT_ACCESSORIES
from src.microbit.enclosure_cad import (
    auto_fit_enclosure_config,
    compute_layout_envelope,
    create_photo_shape_spec,
    export_enclosure_stl,
)


def _make_test_client() -> TestClient:
    app = FastAPI()
    app.include_router(microbit_router)
    return TestClient(app)


def test_catalog_has_metric_dimensions_and_svg_icons() -> None:
    """Every board and Hiwonder/prototyping accessory must expose 1:1 mm dimensions and icon metadata."""
    for bid, board in BOARD_PROFILES.items():
        dims = board.get("dimensions_mm")
        assert isinstance(dims, list) and len(dims) == 3, f"Board {bid} missing dimensions_mm"
        assert all(float(d) > 0 for d in dims)
        assert board.get("svg_icon_kind")

    for acc in MICROBIT_ACCESSORIES:
        dims = acc.get("dimensions_mm")
        assert isinstance(dims, list) and len(dims) == 3, f"Accessory {acc['id']} missing dimensions_mm"
        assert all(float(d) > 0 for d in dims)
        assert acc.get("svg_icon_kind")


def test_auto_fit_enclosure_and_binary_stl_export() -> None:
    """Auto-fit computes a valid envelope around placed parts and exports a binary STL with print stats."""
    attachments = [
        {"id": "a1", "accessory_id": "hiwonder_ultrasonic_v56", "pin": "P19", "position_mm": [0.0, -42.0, 0.0]},
        {"id": "a2", "accessory_id": "hiwonder_temp_hum_v11", "pin": "P19", "position_mm": [48.0, -42.0, 0.0]},
    ]
    env = compute_layout_envelope("microbit_v2", attachments)
    assert env["size_mm"][0] > 70.0
    assert env["size_mm"][1] > 60.0
    assert len(env["standoffs_mm"]) >= 4

    cfg = auto_fit_enclosure_config("microbit_v2", attachments)
    assert cfg["enabled"] is True
    assert cfg["width_mm"] >= env["size_mm"][0]

    stl_bytes, stats = export_enclosure_stl(cfg)
    assert len(stl_bytes) > 84
    assert stats["triangle_count"] > 12
    assert stats["volume_cm3"] > 0
    assert stats["estimated_filament_g"] > 0
    assert stats["units"] == "mm"


def test_photo_relief_shape_generation() -> None:
    """Uploaded image bytes convert cleanly into a 3D-printable relief shape spec and STL mesh."""
    img = np.zeros((64, 64), dtype=np.uint8)
    cv2.circle(img, (32, 32), 20, 220, -1)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    shape = create_photo_shape_spec(buf.tobytes(), name="Logo Badge", width_mm=36.0, length_mm=36.0, height_mm=8.0)
    assert shape["kind"] == "photo_relief"
    assert shape["size_mm"] == [36.0, 36.0, 8.0]
    assert str(shape["heightmap_b64"]).startswith("data:image/png;base64,")

    cfg = auto_fit_enclosure_config("microbit_v2", [], [shape])
    stl_bytes, stats = export_enclosure_stl(cfg, [shape])
    assert len(stl_bytes) > 200
    assert stats["triangle_count"] > 200


def test_ai_copilot_generates_enclosure_and_bracket() -> None:
    """AI Co-Pilot parses 3D-printable enclosure and custom bracket requests."""
    project = {"name": "Desk Bot", "board_id": "microbit_v2", "attachments": [], "sim_rules": []}
    res = apply_deterministic_copilot_fallback(
        project,
        "Attach Hiwonder ultrasonic and build a 3.0mm wall snap-fit 3D-printable enclosure with vents",
    )
    assert any(a["accessory_id"] == "hiwonder_ultrasonic_v56" for a in res["attachments"])
    assert res["enclosure_config"]["enabled"] is True
    assert res["enclosure_config"]["style"] == "snap_fit_case"
    assert res["enclosure_config"]["wall_mm"] == 3.0
    assert res["enclosure_config"]["include_vent_slots"] is True


def test_enclosure_and_photo_shape_api_routes() -> None:
    """FastAPI routes auto-fit enclosure, import photo-to-3D shapes, and download binary STL."""
    client = _make_test_client()
    created = client.post("/api/microbit/projects", json={"name": "CAD Test", "board_id": "microbit_v2"})
    assert created.status_code == 200
    pid = created.json()["project"]["id"]

    # Auto-fit enclosure
    fit_res = client.post(f"/api/microbit/projects/{pid}/enclosure/auto-fit")
    assert fit_res.status_code == 200
    assert fit_res.json()["enclosure_config"]["enabled"] is True

    # Photo-to-3D shape
    img = np.full((32, 32), 180, dtype=np.uint8)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    b64 = base64.b64encode(buf.tobytes()).decode("ascii")
    shp_res = client.post(
        f"/api/microbit/projects/{pid}/shapes/from-photo",
        json={"name": "Test Plate", "image_b64": f"data:image/png;base64,{b64}", "width_mm": 30, "length_mm": 30, "height_mm": 6},
    )
    assert shp_res.status_code == 200
    assert len(shp_res.json()["project"]["custom_shapes"]) == 1

    # Export binary STL
    stl_res = client.post(f"/api/microbit/projects/{pid}/enclosure/export.stl")
    assert stl_res.status_code == 200
    assert len(stl_res.content) > 84
    stats = json.loads(stl_res.headers["X-STL-Stats"])
    assert stats["triangle_count"] > 20
