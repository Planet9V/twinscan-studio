"""Unit and FastAPI integration tests for the 5-pass 3D Real-Room Composite Enhancement Engine."""

from __future__ import annotations

import json
import math
import struct
from typing import Any, List, Tuple

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from src.app.config import Settings
from src.app.factory import create_app
from src.db.repository import InMemoryTwinRepository
from src.db.robot_ai_store import InMemoryRobotAiStore
from src.db.robot_store import InMemoryRobotStore
from src.lidar.composite_enhancer import (
    apply_lidar_residual_warp,
    bake_tangent_normal_map,
    enhance_camera_image,
    guided_filter_depth,
    measure_image_quality,
    refine_lidar_sweeps,
    resolve_enhance_preset,
    stack_camera_burst,
    taubin_smooth_mesh,
)
from src.lidar.scene_reconstructor import build_relief_mesh_payload, export_panel_glb


def _make_clean_wall_bgr(width: int = 160, height: int = 120) -> np.ndarray:
    """Build a crisp synthetic room wall image with sharp cabinet edges and subtle color cast."""
    img = np.zeros((height, width, 3), dtype=np.uint8)
    for r in range(height):
        img[r, :, 0] = int(75 + 45 * (r / height))
        img[r, :, 1] = int(95 + 45 * (r / height))
        img[r, :, 2] = int(125 + 40 * (r / height))
    cv2.rectangle(img, (35, 25), (125, 95), (50, 120, 195), -1)
    cv2.rectangle(img, (35, 25), (125, 95), (235, 235, 235), 2)
    cv2.line(img, (55, 40), (105, 40), (245, 245, 245), 2)
    cv2.line(img, (55, 60), (105, 60), (20, 30, 45), 2)
    return img


def _encode_jpeg(img_bgr: np.ndarray, quality: int = 90) -> bytes:
    ok, buf = cv2.imencode(".jpg", img_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    assert ok
    return bytes(buf)


def _build_test_client() -> TestClient:
    settings = Settings(database_url="", neo4j_uri="", openrouter_api_key="")
    app = create_app(
        settings=settings,
        repository=InMemoryTwinRepository(),
        robot_store=InMemoryRobotStore(),
        robot_ai_store=InMemoryRobotAiStore(),
    )
    return TestClient(app)


def test_resolve_enhance_preset_and_overrides() -> None:
    """Verify fast, balanced, and studio_ultra preset defaults and explicit overrides."""
    fast = resolve_enhance_preset("fast")
    assert fast["burst_frames"] == 1 and fast["clahe_sharpen"] is False and fast["normal_map"] is False

    bal = resolve_enhance_preset("balanced")
    assert bal["burst_frames"] == 3 and bal["clahe_sharpen"] is True and bal["upscale_2x"] is False
    assert bal["flip_tta"] is True and bal["guided_depth"] is True and bal["normal_map"] is True and bal["taubin_smooth"] is True

    ultra = resolve_enhance_preset("studio_ultra", overrides={"upscale_2x": False, "burst_frames": 9})
    assert ultra["upscale_2x"] is False
    assert ultra["burst_frames"] == 5  # Clamped to max 5


def test_pass1_stack_camera_burst_reduces_sensor_noise() -> None:
    """Verify temporal burst alignment & stacking reduces Gaussian sensor noise and drops blurry frame."""
    rng = np.random.default_rng(42)
    clean = _make_clean_wall_bgr(160, 120)

    noisy_frames: List[np.ndarray] = []
    for i in range(4):
        noise = rng.normal(0.0, 14.0, size=clean.shape)
        noisy = np.clip(clean.astype(np.float32) + noise, 0.0, 255.0).astype(np.uint8)
        # Apply small 1px shift on one frame to verify phaseCorrelate alignment.
        if i == 1:
            mat = np.array([[1.0, 0.0, 1.0], [0.0, 1.0, -1.0]], dtype=np.float32)
            noisy = cv2.warpAffine(noisy, mat, (160, 120), borderMode=cv2.BORDER_REPLICATE)
        noisy_frames.append(noisy)
    # Add a heavily blurred 5th frame that should be dropped.
    noisy_frames.append(cv2.GaussianBlur(clean, (15, 15), 4.0))

    stacked, used = stack_camera_burst(noisy_frames)
    assert used == 4  # 5th lowest-sharpness frame dropped

    single_err = float(np.mean(np.abs(noisy_frames[0].astype(np.float32) - clean.astype(np.float32))))
    stacked_err = float(np.mean(np.abs(stacked.astype(np.float32) - clean.astype(np.float32))))
    assert stacked_err < single_err * 0.85, f"Expected burst stacking noise reduction ({stacked_err:.2f} vs {single_err:.2f})"


def test_pass2_enhance_camera_image_sharpness_and_2x_upscale() -> None:
    """Verify CLAHE + sharpening improves image sharpness/contrast and 2x Lanczos4 upscales cleanly."""
    # Start with a slightly soft, low-contrast frame.
    base = cv2.GaussianBlur(_make_clean_wall_bgr(160, 120), (3, 3), 0.9)
    low_contrast = np.clip(base.astype(np.float32) * 0.65 + 40.0, 0, 255).astype(np.uint8)
    q_before = measure_image_quality(low_contrast)

    enh_1x, passes_1x = enhance_camera_image(low_contrast, clahe_sharpen=True, upscale_2x=False, ultra_nlm=False)
    q_1x = measure_image_quality(enh_1x)
    assert "clahe_sharpen" in passes_1x
    assert enh_1x.shape[:2] == (120, 160)
    assert q_1x["contrast"] > q_before["contrast"]
    assert q_1x["sharpness"] > q_before["sharpness"] * 1.1

    enh_2x, passes_2x = enhance_camera_image(low_contrast, clahe_sharpen=True, upscale_2x=True, ultra_nlm=False)
    q_2x = measure_image_quality(enh_2x, ref_shape=(120, 160))
    assert "upscale_2x" in passes_2x
    assert enh_2x.shape[:2] == (240, 320)
    assert q_2x["width"] == 320 and q_2x["height"] == 240
    assert q_2x["contrast"] > q_before["contrast"]
    assert q_2x["sharpness"] > q_before["sharpness"] * 1.1


def test_pass3_refine_lidar_sweeps_removes_spikes() -> None:
    """Verify multi-sweep polar binning + 1D bilateral filter rejects single-sweep outlier spikes."""
    sweeps: List[List[Tuple[float, float]]] = []
    for s in range(5):
        pts: List[Tuple[float, float]] = []
        for deg in range(60, 121, 1):
            rad = math.radians(deg)
            dist = 2.0 + (0.015 if s % 2 == 0 else -0.015)
            # Inject a massive outlier spike on sweep 2 at 90 deg.
            if s == 2 and deg == 90:
                dist = 6.5
            pts.append((dist * math.cos(rad), dist * math.sin(rad)))
        sweeps.append(pts)

    refined, sweeps_used = refine_lidar_sweeps(sweeps)
    assert sweeps_used == 5
    assert len(refined) >= 50
    # Verify the 90 deg spike was completely eliminated (all points stay near r=2.0m).
    dists = [math.hypot(x, y) for x, y in refined]
    assert max(dists) < 2.25
    assert abs(float(np.median(dists)) - 2.0) < 0.04


def test_pass4_guided_filter_lidar_warp_normal_map_and_taubin() -> None:
    """Verify guided depth alignment, LiDAR residual RMSE drop, normal map JPEG, and Taubin smoothing."""
    h, w = 60, 80
    # 1. Guided filter snaps blurred depth edge back toward crisp RGB vertical edge at col=40.
    guide = np.zeros((h, w), dtype=np.uint8)
    guide[:, 40:] = 220
    sharp_depth = np.full((h, w), 1.5, dtype=np.float32)
    sharp_depth[:, 40:] = 3.0
    blur_depth = cv2.GaussianBlur(sharp_depth, (15, 15), 4.0)
    guided = guided_filter_depth(guide, blur_depth, radius=6, eps=1e-4)

    err_blur = float(np.mean(np.abs(blur_depth[:, 36:44] - sharp_depth[:, 36:44])))
    err_guided = float(np.mean(np.abs(guided[:, 36:44] - sharp_depth[:, 36:44])))
    assert err_guided < err_blur, f"Guided filter should sharpen depth transition ({err_guided:.4f} vs {err_blur:.4f})"

    # 2. LiDAR residual warp corrects systematic horizontal drift and drops RMSE.
    hfov_deg = 65.0
    fx = 0.5 / math.tan(math.radians(hfov_deg / 2.0))
    drifted_depth = np.full((h, w), 2.0, dtype=np.float32)
    lidar_pts: List[Tuple[float, float]] = []
    for col in range(8, w - 8, 4):
        u = col / (w - 1)
        z_true = 2.0 + 0.5 * (u - 0.5)  # True slanted wall
        x_right = ((u - 0.5) / fx) * z_true
        lidar_pts.append((x_right, z_true))

    warped, rmse = apply_lidar_residual_warp(drifted_depth, lidar_pts, hfov_deg=hfov_deg, yaw_deg=0.0)
    assert rmse is not None and rmse < 0.05
    # Verify right side moved farther (> 2.1m) and left side moved closer (< 1.9m).
    assert float(warped[h // 2, -10]) > 2.1
    assert float(warped[h // 2, 10]) < 1.9

    # 3. Normal map baking produces valid JPEG with bluish (+Z outward) average channel.
    wall_bgr = _make_clean_wall_bgr(160, 120)
    norm_jpeg = bake_tangent_normal_map(warped, wall_bgr, strength=1.6)
    assert norm_jpeg[:2] == b"\xff\xd8"
    norm_img = cv2.imdecode(np.frombuffer(norm_jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert norm_img is not None and norm_img.shape[:2] == (120, 160)
    # In BGR, channel 0 is B = tangent +Z (should dominate > 180 on average).
    assert float(np.mean(norm_img[:, :, 0])) > 180.0

    # 4. Taubin smoothing reduces interior jitter without moving outer border vertices.
    rng = np.random.default_rng(7)
    noisy_depth = np.full((36, 48), 2.0, dtype=np.float32) + rng.normal(0.0, 0.05, (36, 48)).astype(np.float32)
    raw_built = build_relief_mesh_payload(
        depth_m=noisy_depth,
        image_bgr=None,
        pose={"x": 0, "y": 0, "z": 0.22, "yaw_deg": 0, "pitch_deg": 0, "roll_deg": 0},
        resolution="low",
        taubin_smooth=False,
    )
    mesh = raw_built["mesh"]
    smoothed_pos = taubin_smooth_mesh(mesh["positions"], mesh["indices"], mesh["grid_w"], mesh["grid_h"], iterations=2)
    raw_v = np.asarray(mesh["positions"], dtype=np.float64).reshape(36, 48, 3)
    sm_v = np.asarray(smoothed_pos, dtype=np.float64).reshape(36, 48, 3)
    # Border row 0 must remain locked.
    assert np.allclose(raw_v[0, :, :], sm_v[0, :, :], atol=1e-4)
    # Interior Z variance must decrease after Taubin smoothing.
    assert float(np.var(sm_v[2:-2, 2:-2, 2])) < float(np.var(raw_v[2:-2, 2:-2, 2]))

    # 5. GLB export with normal_jpeg_bytes embeds normalTexture (index 1).
    glb = export_panel_glb(
        mesh["positions"],
        mesh["normals"],
        mesh["uvs"],
        mesh["indices"],
        _encode_jpeg(wall_bgr),
        normal_jpeg_bytes=norm_jpeg,
    )
    assert glb[:4] == b"glTF"
    json_len, _ = struct.unpack_from("<II", glb, 12)
    doc = json.loads(glb[20 : 20 + json_len].decode("utf-8"))
    assert len(doc["images"]) == 2
    assert doc["materials"][0]["normalTexture"]["index"] == 1


def test_routes_capture_wall_studio_ultra_and_enhance_existing_panel(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify FastAPI capture-wall (studio_ultra) and POST /reconstruct/panels/{id}/enhance."""
    sample_jpeg = _encode_jpeg(_make_clean_wall_bgr(160, 120))
    call_count = {"n": 0}

    async def _fake_capture(ip: str, video_port: int = 8080, ros_version: str = "ros2", **_kw: Any) -> Tuple[bytes, str]:
        call_count["n"] += 1
        return sample_jpeg, "/image_raw"

    monkeypatch.setattr("src.api.routes_twin.capture_live_camera_frame", _fake_capture)
    monkeypatch.setattr("src.lidar.scene_reconstructor._get_depth_session", lambda **_kw: None)

    with _build_test_client() as client:
        space_id = client.app.state.runtime.active_space_id
        robot = client.app.state.robot_store.upsert_robot(
            {"ip_address": "192.168.1.119", "name": "PuppyPi-Ultra", "status": "online", "ros_version": "ros2"}
        )

        # 1. Capture with fast preset first (no normal map, 1 frame).
        resp_fast = client.post(
            f"/api/spaces/{space_id}/reconstruct/capture-wall",
            json={
                "robot_id": robot["id"],
                "label": "Fast Wall",
                "resolution": "low",
                "quality_preset": "fast",
            },
        )
        assert resp_fast.status_code == 200, resp_fast.text
        fast_panel = resp_fast.json()["panel"]
        assert fast_panel["normal_map_url"] is None
        assert fast_panel["quality_metrics"]["preset"] == "fast"
        assert fast_panel["quality_metrics"]["frames_stacked"] == 1
        assert fast_panel["quality_metrics"]["texture_width"] == 160

        # 2. Re-enhance the existing fast panel to studio_ultra via POST /enhance!
        resp_enh = client.post(
            f"/api/spaces/{space_id}/reconstruct/panels/{fast_panel['id']}/enhance",
            json={"quality_preset": "studio_ultra", "resolution": "low"},
        )
        assert resp_enh.status_code == 200, resp_enh.text
        enh_data = resp_enh.json()
        assert enh_data["ok"] is True
        enh_panel = enh_data["panel"]
        assert enh_panel["id"] == fast_panel["id"]
        assert enh_panel["normal_map_url"] is not None
        assert enh_panel["normal_map_url"].startswith("/api/files/")
        qm = enh_panel["quality_metrics"]
        assert qm["preset"] == "studio_ultra"
        assert qm["has_normal_map"] is True
        assert qm["texture_width"] == 320  # 2x upscaled from 160x120!
        assert qm["texture_height"] == 240
        assert "clahe_sharpen" in qm["passes_applied"]
        assert "upscale_2x" in qm["passes_applied"]
        assert "normal_map" in qm["passes_applied"]
        assert "taubin_smooth" in qm["passes_applied"]

        # Verify baked normal map JPEG serves cleanly via /api/files/{id}.
        norm_resp = client.get(enh_panel["normal_map_url"])
        assert norm_resp.status_code == 200
        assert norm_resp.headers["content-type"].startswith("image/jpeg")
        assert norm_resp.content[:2] == b"\xff\xd8"

        # 3. Direct studio_ultra capture-wall executes 5-frame burst!
        call_count["n"] = 0
        resp_ultra = client.post(
            f"/api/spaces/{space_id}/reconstruct/capture-wall",
            json={
                "robot_id": robot["id"],
                "label": "Studio Ultra Wall",
                "resolution": "low",
                "quality_preset": "studio_ultra",
            },
        )
        assert resp_ultra.status_code == 200, resp_ultra.text
        ultra_panel = resp_ultra.json()["panel"]
        assert call_count["n"] == 5
        assert ultra_panel["quality_metrics"]["frames_stacked"] == 4  # 5 captured -> 1 lowest-sharpness dropped!
        assert ultra_panel["quality_metrics"]["has_normal_map"] is True
        assert ultra_panel["quality_metrics"]["texture_width"] == 320
