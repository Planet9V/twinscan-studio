"""Unit tests for src/vision/overwatch_upscaler.py and tactical overwatch API routes."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import cv2
import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes_overwatch import router as overwatch_router
from src.db.repository import InMemoryTwinRepository
from src.vision.overwatch_upscaler import extract_and_enhance_local_roi, upscale_roi_fal_ai


def _make_sample_jpeg(w: int = 320, h: int = 240) -> bytes:
    img = np.zeros((h, w, 3), dtype=np.uint8)
    cv2.rectangle(img, (80, 60), (240, 180), (40, 200, 255), -1)
    cv2.putText(img, "TARGET", (100, 130), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (20, 20, 20), 2)
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    assert ok
    return buf.tobytes()


def test_local_roi_enhance_outputs_side_by_side() -> None:
    """Local Lanczos + CLAHE ROI enhancer returns both raw and 2x enhanced data URLs."""
    jpg = _make_sample_jpeg()
    res = extract_and_enhance_local_roi(jpg, [0.25, 0.25, 0.75, 0.75], scale=2)
    assert res["ok"] is True
    assert res["method"] == "local_lanczos_clahe"
    assert res["ai_generated_warning"] is False
    assert res["raw_crop_b64"].startswith("data:image/jpeg;base64,")
    assert res["enhanced_b64"].startswith("data:image/jpeg;base64,")
    assert res["enhanced_size"][0] == res["raw_size"][0] * 2


@pytest.mark.asyncio
async def test_fal_upscale_missing_key_raises() -> None:
    """Missing fal_api_key raises clear ValueError pointing to /config."""
    jpg = _make_sample_jpeg()
    with pytest.raises(ValueError, match="fal_api_key"):
        await upscale_roi_fal_ai(jpg, [0.2, 0.2, 0.8, 0.8], api_key="")


@pytest.mark.asyncio
async def test_fal_upscale_mocked_success_and_warning() -> None:
    """Mocked fal.ai call sets ai_generated_warning=True and returns enhanced image."""
    jpg = _make_sample_jpeg()
    mock_post_resp = MagicMock()
    mock_post_resp.raise_for_status = MagicMock()
    mock_post_resp.json.return_value = {"image": {"url": "https://fal.media/out.png", "width": 400, "height": 300}}

    mock_get_resp = MagicMock()
    mock_get_resp.raise_for_status = MagicMock()
    mock_get_resp.headers = {"content-type": "image/png"}
    mock_get_resp.content = b"\x89PNG\r\n\x1a\nfake"

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_post_resp)
    mock_client.get = AsyncMock(return_value=mock_get_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("src.vision.overwatch_upscaler.httpx.AsyncClient", return_value=mock_client):
        res = await upscale_roi_fal_ai(jpg, [0.2, 0.2, 0.8, 0.8], api_key="fal_test_key", model="fal-ai/esrgan", scale=2)

    assert res["ok"] is True
    assert res["ai_generated_warning"] is True
    assert res["enhanced_b64"].startswith("data:image/png;base64,")


def test_overwatch_tactical_routes_end_to_end() -> None:
    """FastAPI overwatch tactical endpoints return geometry, homography, task-point, and local upscale."""
    app = FastAPI()
    app.include_router(overwatch_router)
    app.state.twin_repo = InMemoryTwinRepository()
    client = TestClient(app)

    # Ingest a frame first
    jpg = _make_sample_jpeg()
    r_ing = client.post("/api/overwatch/ingest?camera_id=usb_4k", content=jpg, headers={"Content-Type": "image/jpeg"})
    assert r_ing.status_code == 200

    # 1) Geometry endpoint
    r_geo = client.get("/api/overwatch/geometry")
    assert r_geo.status_code == 200
    geo = r_geo.json()
    assert "frustums" in geo and "zones" in geo and "placement_advisor" in geo

    # 2) Task-point preview (no dispatch)
    r_tp = client.post(
        "/api/overwatch/task-point",
        json={"camera_id": "usb_4k", "u_norm": 0.5, "v_norm": 0.8, "dispatch": False},
    )
    assert r_tp.status_code == 200
    assert r_tp.json()["dispatched"] is False
    assert len(r_tp.json()["target_xy"]) == 2

    # 3) Local ROI upscale
    r_up = client.post(
        "/api/overwatch/upscale-roi",
        json={"camera_id": "usb_4k", "bbox_norm": [0.2, 0.2, 0.8, 0.8], "mode": "local", "scale": 2},
    )
    assert r_up.status_code == 200
    assert r_up.json()["ok"] is True
    assert r_up.json()["ai_generated_warning"] is False

    # 4) fal.ai upscale without key returns clean 400
    r_fal = client.post(
        "/api/overwatch/upscale-roi",
        json={"camera_id": "usb_4k", "bbox_norm": [0.2, 0.2, 0.8, 0.8], "mode": "fal", "scale": 2},
    )
    assert r_fal.status_code == 400
    assert "fal_api_key" in r_fal.json()["detail"]
