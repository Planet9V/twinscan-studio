"""Unit and FastAPI integration tests for 3D Real-Room Fusion (Stage 1 & Stage 2)."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from src.app.config import Settings
from src.app.factory import create_app
from src.db.repository import InMemoryTwinRepository
from src.db.robot_ai_store import InMemoryRobotAiStore
from src.db.robot_store import InMemoryRobotStore
from src.lidar.ld19_parser import LidarPoint
from src.lidar.scene_reconstructor import (
    RESOLUTION_GRID_MAP,
    build_relief_mesh_payload,
    calibrate_depth_with_lidar,
    estimate_geometric_relief,
    estimate_relative_depth,
    export_panel_glb,
    reconstruct_wall_panel,
)


def _make_sample_jpeg(width: int = 160, height: int = 120) -> bytes:
    """Create a synthetic textured room-wall JPEG with foreground box and wall stripes."""
    img = np.zeros((height, width, 3), dtype=np.uint8)
    # Warm wall gradient
    for r in range(height):
        img[r, :, 0] = int(60 + 80 * (r / height))
        img[r, :, 1] = int(90 + 70 * (r / height))
        img[r, :, 2] = int(120 + 60 * (r / height))
    # Foreground equipment cabinet rectangle
    cv2.rectangle(img, (width // 3, height // 4), (2 * width // 3, 3 * height // 4), (40, 140, 220), -1)
    cv2.rectangle(img, (width // 3, height // 4), (2 * width // 3, 3 * height // 4), (250, 250, 250), 2)
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
    assert ok
    return bytes(buf)


def _build_test_client() -> TestClient:
    """Create an isolated in-memory FastAPI TestClient with a registered robot."""
    settings = Settings(database_url="", neo4j_uri="", openrouter_api_key="")
    repo = InMemoryTwinRepository()
    robot_store = InMemoryRobotStore()
    ai_store = InMemoryRobotAiStore()
    app = create_app(
        settings=settings,
        repository=repo,
        robot_store=robot_store,
        robot_ai_store=ai_store,
    )
    return TestClient(app)


def test_calibrate_depth_with_lidar_affine_accuracy() -> None:
    """Verify robust affine calibration maps inverse relative depth to metric LD19 wall rays."""
    h, w = 60, 80
    # Relative depth ramps linearly from 0.15 (left, farther) to 0.85 (right, closer).
    rel_col = np.linspace(0.15, 0.85, w, dtype=np.float32)
    rel_depth = np.tile(rel_col[None, :], (h, 1))

    # Ground truth metric depth: z = -2.0 * rel + 3.5 -> ranges 3.2m (left) down to 1.8m (right).
    hfov_deg = 65.0
    fx = 0.5 / math.tan(math.radians(hfov_deg / 2.0))
    lidar_pts: List[Tuple[float, float]] = []
    for col in range(6, w - 6, 3):
        u = col / (w - 1)
        z_true = -2.0 * float(rel_col[col]) + 3.5
        x_right = ((u - 0.5) / fx) * z_true
        lidar_pts.append((x_right, z_true))
    # Inject 2 gross outliers to test MAD outlier rejection.
    lidar_pts.append((0.0, 7.5))
    lidar_pts.append((0.1, 0.3))

    depth_m, calibrated, ray_count, source = calibrate_depth_with_lidar(
        rel_depth=rel_depth,
        lidar_points_xy=lidar_pts,
        hfov_deg=hfov_deg,
        yaw_deg=0.0,
        fallback_distance_m=1.8,
        depth_relief_scale=1.0,
        base_depth_source="depth_anything",
    )

    assert calibrated is True
    assert ray_count >= 12
    assert source == "lidar_depth_anything"
    expected_mid = -2.0 * rel_depth + 3.5
    mae = float(np.mean(np.abs(depth_m - expected_mid)))
    assert mae < 0.08, f"Expected accurate metric calibration (MAE < 0.08m), got {mae:.4f}m"


def test_calibrate_depth_without_lidar_fallback() -> None:
    """Verify offline LiDAR fallback scales relative depth cleanly around fallback_distance_m."""
    rel = np.linspace(0.0, 1.0, 48 * 36, dtype=np.float32).reshape(36, 48)
    depth_m, calibrated, ray_count, source = calibrate_depth_with_lidar(
        rel_depth=rel,
        lidar_points_xy=None,
        fallback_distance_m=2.4,
        depth_relief_scale=1.0,
        base_depth_source="geometric_relief",
    )
    assert calibrated is False
    assert ray_count == 0
    assert source == "geometric_relief"
    assert abs(float(np.median(depth_m)) - 2.4) < 0.05
    # Higher relative depth (bottom-right) must be closer than lower relative depth (top-left).
    assert float(depth_m[-1, -1]) < float(depth_m[0, 0])
    assert float(depth_m.min()) >= 0.35
    assert float(depth_m.max()) <= 6.5


def test_build_relief_mesh_payload_geometry_tear_filter_and_pose() -> None:
    """Verify grid dimensions, tear filtering across depth jumps, unit normals, UVs, and yaw rotation."""
    # Construct a wall with a sharp step discontinuity down the center (1.0m left vs 3.5m right).
    depth_step = np.full((60, 80), 3.5, dtype=np.float32)
    depth_step[:, :40] = 1.0

    res = build_relief_mesh_payload(
        depth_m=depth_step,
        image_bgr=None,
        pose={"x": 0.0, "y": 0.0, "z": 0.22, "yaw_deg": 0.0, "pitch_deg": 0.0, "roll_deg": 0.0},
        resolution="low",
        hfov_deg=65.0,
        vfov_deg=50.0,
        tear_threshold_ratio=0.14,
    )
    mesh = res["mesh"]
    gw, gh = RESOLUTION_GRID_MAP["low"]
    assert mesh["grid_w"] == gw == 48
    assert mesh["grid_h"] == gh == 36
    assert res["vertex_count"] == gw * gh
    assert len(mesh["positions"]) == 3 * gw * gh
    assert len(mesh["normals"]) == 3 * gw * gh
    assert len(mesh["uvs"]) == 2 * gw * gh

    max_possible_tris = 2 * (gw - 1) * (gh - 1)
    assert 0 < res["triangle_count"] < max_possible_tris, "Tear filter must drop step-bridge triangles"

    # Verify UVs are within [0, 1] and follow OpenGL convention (top-left v=1, bottom-right v=0).
    uvs = np.asarray(mesh["uvs"], dtype=np.float64).reshape(-1, 2)
    assert float(uvs.min()) >= 0.0 and float(uvs.max()) <= 1.0
    assert abs(uvs[0, 0] - 0.0) < 1e-4 and abs(uvs[0, 1] - 1.0) < 1e-4
    assert abs(uvs[-1, 0] - 1.0) < 1e-4 and abs(uvs[-1, 1] - 0.0) < 1e-4

    # Verify unit normals and bottom edge sits on/above floor (y >= 0).
    norms = np.asarray(mesh["normals"], dtype=np.float64).reshape(-1, 3)
    norm_lens = np.linalg.norm(norms, axis=1)
    assert np.allclose(norm_lens, 1.0, atol=1e-2)
    verts = np.asarray(mesh["positions"], dtype=np.float64).reshape(-1, 3)
    assert float(verts[:, 1].min()) >= -1e-4

    # Verify 90-degree yaw rotation rotates camera forward (-Z) to (-X).
    flat_depth = np.full((36, 48), 2.0, dtype=np.float32)
    res_yaw = build_relief_mesh_payload(
        depth_m=flat_depth,
        image_bgr=None,
        pose={"x": 0.0, "y": 0.0, "z": 0.22, "yaw_deg": 90.0, "pitch_deg": 0.0, "roll_deg": 0.0},
        resolution="low",
    )
    verts_yaw = np.asarray(res_yaw["mesh"]["positions"], dtype=np.float64).reshape(-1, 3)
    assert float(np.mean(verts_yaw[:, 0])) < -1.8, "At yaw=90 deg, wall center should lie near X=-2m"
    assert abs(float(np.mean(verts_yaw[:, 2]))) < 0.15, "At yaw=90 deg, wall center Z should be near 0"


def test_export_panel_glb_valid_header_and_fallback_depth() -> None:
    """Verify textured GLB export starts with b'glTF' magic bytes and fallback depth works offline."""
    jpeg = _make_sample_jpeg()
    arr = np.frombuffer(jpeg, dtype=np.uint8)
    bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    assert bgr is not None

    rel = estimate_geometric_relief(bgr)
    assert rel.shape == bgr.shape[:2]
    assert 0.0 <= float(rel.min()) <= float(rel.max()) <= 1.0

    # Verify offline reconstruction without downloading ONNX model.
    result, glb_bytes = reconstruct_wall_panel(
        jpeg_bytes=jpeg,
        lidar_points_xy=None,
        pose={"x": 0.0, "y": 0.0, "z": 0.22, "yaw_deg": 0.0, "pitch_deg": 0.0, "roll_deg": 0.0},
        resolution="low",
        allow_model_download=False,
        models_dir="/tmp/twinscan_nonexistent_models_dir_test",
    )
    assert glb_bytes[:4] == b"glTF"
    assert len(glb_bytes) > 500
    assert result["vertex_count"] == 48 * 36
    assert result["triangle_count"] > 0

    # Direct export_panel_glb call check + glTF 2.0 structural integrity verification
    import json
    import struct

    mesh = result["mesh"]
    glb_direct = export_panel_glb(
        mesh["positions"], mesh["normals"], mesh["uvs"], mesh["indices"], jpeg
    )
    magic, version, total_len = struct.unpack_from("<4sII", glb_direct, 0)
    assert magic == b"glTF"
    assert version == 2
    assert total_len == len(glb_direct)
    json_len, json_type = struct.unpack_from("<II", glb_direct, 12)
    assert json_type == 0x4E4F534A
    gltf_doc = json.loads(glb_direct[20 : 20 + json_len].decode("utf-8"))
    assert gltf_doc["images"][0]["mimeType"] == "image/jpeg"
    assert gltf_doc["accessors"][0]["count"] == result["vertex_count"]
    assert gltf_doc["accessors"][3]["count"] == result["triangle_count"] * 3


def test_estimate_relative_depth_with_mocked_onnx_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify Depth Anything ONNX inference path handles 4D (1,1,H,W) outputs cleanly."""
    class _FakeInput:
        name = "pixel_values"
        shape = [1, 3, 56, 56]

    class _FakeSession:
        def get_inputs(self) -> List[Any]:
            return [_FakeInput()]

        def run(self, _outputs: Any, feed: Dict[str, np.ndarray]) -> List[np.ndarray]:
            inp = feed["pixel_values"]
            assert inp.shape == (1, 3, 56, 56)
            grad = np.linspace(0.0, 10.0, 56 * 56, dtype=np.float32).reshape(1, 1, 56, 56)
            return [grad]

    monkeypatch.setattr("src.lidar.scene_reconstructor._get_depth_session", lambda **_kw: _FakeSession())
    bgr = np.zeros((120, 160, 3), dtype=np.uint8)
    rel, engine = estimate_relative_depth(bgr, allow_download=False)
    assert engine == "depth_anything"
    assert rel.shape == (120, 160)
    assert float(rel.min()) >= 0.0 and float(rel.max()) <= 1.0


def test_in_memory_store_scene_panels_crud() -> None:
    """Verify InMemoryRobotAiStore scene panel save, list, get, delete, and clear operations."""
    store = InMemoryRobotAiStore()
    store.initialize()

    p1 = store.save_scene_panel(
        {
            "space_id": "space-1",
            "robot_id": "rob-1",
            "label": "North Wall",
            "stage": "single_wall",
            "pose": {"x": 0.0, "y": 0.0, "z": 0.22, "yaw_deg": 0.0, "pitch_deg": 0.0, "roll_deg": 0.0},
            "lidar_calibrated": True,
            "lidar_ray_count": 24,
            "depth_source": "lidar_depth_anything",
            "mean_distance_m": 2.1,
            "min_distance_m": 1.4,
            "max_distance_m": 2.8,
            "vertex_count": 100,
            "triangle_count": 150,
            "texture_file_id": "tex-1",
            "glb_file_id": "glb-1",
            "mesh": {"grid_w": 10, "grid_h": 10, "hfov_deg": 65, "vfov_deg": 50, "positions": [], "normals": [], "uvs": [], "indices": []},
        }
    )
    assert p1["texture_url"] == "/api/files/tex-1"
    assert p1["glb_url"] == "/api/files/glb-1"
    assert store.get_scene_panel(p1["id"]) is not None
    assert len(store.list_scene_panels("space-1")) == 1

    store.save_scene_panel({"space_id": "space-1", "label": "East Wall"})
    assert len(store.list_scene_panels("space-1")) == 2
    assert store.delete_scene_panel(p1["id"]) is True
    assert store.delete_scene_panel("nonexistent") is False
    assert store.clear_scene_panels("space-1") == 1
    assert store.list_scene_panels("space-1") == []


def test_reconstruct_routes_capture_wall_list_files_and_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify FastAPI single-wall capture, file serving, listing, delete, and clear endpoints."""
    sample_jpeg = _make_sample_jpeg()

    async def _fake_capture(ip: str, video_port: int = 8080, ros_version: str = "ros2", **_kw: Any) -> Tuple[bytes, str]:
        return sample_jpeg, "/image_raw"

    monkeypatch.setattr("src.api.routes_twin.capture_live_camera_frame", _fake_capture)
    monkeypatch.setattr("src.lidar.scene_reconstructor._get_depth_session", lambda **_kw: None)

    with _build_test_client() as client:
        rt = client.app.state.runtime
        space_id = rt.active_space_id
        robot = client.app.state.robot_store.upsert_robot(
            {"ip_address": "192.168.1.148", "name": "PuppyPi-Test", "status": "online", "ros_version": "ros2"}
        )

        # 1. Capture while in simulator mode -> must NOT falsely claim lidar_calibrated=True!
        resp = client.post(
            f"/api/spaces/{space_id}/reconstruct/capture-wall",
            json={
                "robot_id": robot["id"],
                "label": "Office Front Wall",
                "resolution": "low",
                "fallback_distance_m": 2.0,
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["ok"] is True
        panel = data["panel"]
        assert panel["label"] == "Office Front Wall"
        assert panel["stage"] == "single_wall"
        assert panel["lidar_calibrated"] is False
        assert panel["texture_url"].startswith("/api/files/")
        assert panel["glb_url"].startswith("/api/files/")

        # Verify texture JPEG and GLB binary serve cleanly via /api/files/{id}
        tex_resp = client.get(panel["texture_url"])
        assert tex_resp.status_code == 200
        assert tex_resp.headers["content-type"].startswith("image/jpeg")
        assert len(tex_resp.content) > 100

        glb_resp = client.get(panel["glb_url"])
        assert glb_resp.status_code == 200
        assert glb_resp.headers["content-type"].startswith("model/gltf-binary")
        assert glb_resp.content[:4] == b"glTF"

        # 2. Simulate real ROS2 live LD19 scan connected -> must calibrate with LiDAR!
        rt.source_mode = "robot_ros2"
        rt.robot_scan_connected = True
        rt.latest_points = [
            LidarPoint(angle_deg=90.0 + a, distance_m=2.2, intensity=200, x=2.2 * math.sin(math.radians(a)), y=2.2 * math.cos(math.radians(a)))
            for a in range(-28, 29, 2)
        ]
        resp2 = client.post(
            f"/api/spaces/{space_id}/reconstruct/capture-wall",
            json={"robot_id": robot["id"], "resolution": "low"},
        )
        assert resp2.status_code == 200
        panel2 = resp2.json()["panel"]
        assert panel2["lidar_calibrated"] is True
        assert panel2["lidar_ray_count"] >= 10

        # 3. List panels
        list_resp = client.get(f"/api/spaces/{space_id}/reconstruct/panels")
        assert list_resp.status_code == 200
        assert len(list_resp.json()["panels"]) == 2

        # 4. Delete single panel
        del_resp = client.delete(f"/api/spaces/{space_id}/reconstruct/panels/{panel['id']}")
        assert del_resp.status_code == 200
        assert del_resp.json() == {"deleted": True, "panel_id": panel["id"]}

        # 5. Clear remaining panels
        clr_resp = client.delete(f"/api/spaces/{space_id}/reconstruct/panels")
        assert clr_resp.status_code == 200
        assert clr_resp.json()["deleted_count"] == 1


def test_reconstruct_route_capture_360_with_mocked_robot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify Stage-2 360-degree turn capture rotates in steps and always sends zero-velocity stop."""
    sample_jpeg = _make_sample_jpeg()
    vel_commands: List[Tuple[float, float]] = []

    async def _fake_capture(ip: str, video_port: int = 8080, ros_version: str = "ros2", **_kw: Any) -> Tuple[bytes, str]:
        return sample_jpeg, "/image_raw"

    async def _fake_pub_vel(ip: str, port: int, x: float, y: float = 0.0, yaw_rate: float = 0.0, **_kw: Any) -> Dict[str, Any]:
        vel_commands.append((x, yaw_rate))
        return {"sent": True}

    monkeypatch.setattr("src.api.routes_twin.capture_live_camera_frame", _fake_capture)
    monkeypatch.setattr("src.api.routes_twin.publish_velocity", _fake_pub_vel)
    monkeypatch.setattr("src.lidar.scene_reconstructor._get_depth_session", lambda **_kw: None)

    with _build_test_client() as client:
        space_id = client.app.state.runtime.active_space_id
        robot = client.app.state.robot_store.upsert_robot(
            {"ip_address": "192.168.1.148", "name": "PuppyPi-360", "status": "online", "ros_version": "ros2"}
        )

        resp = client.post(
            f"/api/spaces/{space_id}/reconstruct/capture-360",
            json={
                "robot_id": robot["id"],
                "steps": 4,
                "resolution": "low",
                "turn_duration_s": 0.1,
                "settle_s": 0.0,
                "yaw_rate_rad_s": 0.85,
            },
        )
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        assert payload["ok"] is True
        assert payload["aborted"] is False
        assert payload["completed_steps"] == 4
        assert payload["total_steps"] == 4
        assert len(payload["panels"]) == 4

        yaws = [p["pose"]["yaw_deg"] for p in payload["panels"]]
        assert yaws == [0.0, 90.0, 180.0, 270.0]
        assert all(p["stage"] == "pano_360" for p in payload["panels"])
        # Verify robot turned 3 times (between 4 steps) and ended with zero-velocity stop.
        assert any(yr > 0.5 for _, yr in vel_commands)
        assert vel_commands[-1] == (0.0, 0.0)
