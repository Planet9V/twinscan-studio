"""3D Real-Room Fusion: Depth Anything V2 Small ONNX, LD19 LiDAR Metric Calibration, and Textured GLB Builder.

Implements zero-movement single-wall 3D textured relief reconstruction and multi-view 360-degree
capture support for PuppyPi Pro:
- Depth Anything V2 Small ONNX auto-download + cached inference with offline OpenCV geometric relief fallback.
- Robust Huber/MAD affine metric calibration against live LD19 LiDAR 2D rays in the camera FOV.
- Canonical right-handed Three.js/glTF metric 3D mesh generation (`+X` right, `+Y` up, `-Z` forward at `yaw=0`),
  depth-discontinuity tear filtering, area-weighted smooth vertex normals, and OpenGL/glTF UVs.
- Textured binary `.glb` export via ``trimesh`` + Pillow ``PBRMaterial``.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import struct
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
import httpx
import numpy as np
import onnxruntime as ort

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
from src.robot.ros_profiles import get_ros_profile
from src.robot.rosbridge_proxy import fetch_robot_snapshot

DEPTH_MODEL_FILENAME = "depth_anything_v2_vits.onnx"
DEPTH_MODEL_URLS: Tuple[str, ...] = (
    "https://huggingface.co/onnx-community/depth-anything-v2-small/resolve/main/onnx/model.onnx",
    "https://huggingface.co/fabio-sim/Depth-Anything-ONNX/resolve/main/depth_anything_v2_vits.onnx",
)

RESOLUTION_GRID_MAP: Dict[str, Tuple[int, int]] = {
    "low": (48, 36),
    "medium": (80, 60),
    "high": (120, 90),
}

_IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32).reshape(1, 1, 3)
_IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32).reshape(1, 1, 3)

_SESSION_LOCK = threading.Lock()
_DEPTH_SESSION: Optional[ort.InferenceSession] = None
_DEPTH_SESSION_PATH: Optional[str] = None


def get_models_dir(models_dir: Optional[str | Path] = None) -> Path:
    """Resolve and create a writable model cache directory for ONNX weights.

    Checks ``models_dir`` or ``TWINSCAN_MODELS_DIR`` (default ``/app/data/models``)
    and falls back cleanly to local ``data/models`` when the primary path is not writable.

    Args:
        models_dir: Optional explicit cache directory path.

    Returns:
        Writable ``Path`` directory for cached ONNX models.
    """
    candidates: List[Path] = []
    if models_dir is not None:
        candidates.append(Path(models_dir))
    env_dir = os.environ.get("TWINSCAN_MODELS_DIR", "").strip()
    if env_dir:
        candidates.append(Path(env_dir))
    candidates.extend([Path("/app/data/models"), Path("data/models")])

    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".write_probe"
            probe.write_bytes(b"ok")
            probe.unlink(missing_ok=True)
            return candidate
        except OSError:
            continue

    fallback = Path("data/models")
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def ensure_depth_model(
    models_dir: Optional[str | Path] = None,
    timeout: float = 45.0,
    max_retries: int = 3,
) -> Optional[Path]:
    """Ensure ``depth_anything_v2_vits.onnx`` is cached locally, downloading once if needed.

    Retries up to ``max_retries`` times across HuggingFace ONNX mirrors, logging failures
    to ``sys.stderr``. Never raises on offline/network failure so reconstruction can fall
    back gracefully to geometric relief.

    Args:
        models_dir: Optional explicit directory for ONNX model storage.
        timeout: HTTP timeout in seconds per download attempt.
        max_retries: Maximum download attempts per mirror URL.

    Returns:
        Path to the local ``depth_anything_v2_vits.onnx`` file, or ``None`` if unavailable.
    """
    cache_dir = get_models_dir(models_dir)
    target = cache_dir / DEPTH_MODEL_FILENAME
    if target.exists() and target.stat().st_size > 1_000_000:
        return target

    tmp_path = target.with_suffix(".onnx.tmp")
    for url in DEPTH_MODEL_URLS:
        for attempt in range(1, max(1, int(max_retries)) + 1):
            try:
                http_timeout = httpx.Timeout(connect=10.0, read=timeout, write=15.0, pool=10.0)
                with httpx.Client(follow_redirects=True, timeout=http_timeout) as client:
                    with client.stream("GET", url) as resp:
                        resp.raise_for_status()
                        with tmp_path.open("wb") as fh:
                            for chunk in resp.iter_bytes(chunk_size=131072):
                                if chunk:
                                    fh.write(chunk)
                if tmp_path.exists() and tmp_path.stat().st_size > 1_000_000:
                    tmp_path.replace(target)
                    return target
                raise ValueError("Downloaded ONNX file was unexpectedly small")
            except Exception as exc:
                tmp_path.unlink(missing_ok=True)
                sys.stderr.write(
                    f"[scene_reconstructor] Depth model download failed ({url}, attempt {attempt}/{max_retries}): {exc}\n"
                )
                if attempt < max_retries:
                    time.sleep(min(0.6 * attempt, 2.0))
    return None


def _get_depth_session(
    models_dir: Optional[str | Path] = None,
    allow_download: bool = True,
) -> Optional[ort.InferenceSession]:
    """Load and cache the ONNX Runtime session for Depth Anything V2 Small."""
    global _DEPTH_SESSION, _DEPTH_SESSION_PATH

    cache_dir = get_models_dir(models_dir)
    target = cache_dir / DEPTH_MODEL_FILENAME

    with _SESSION_LOCK:
        if _DEPTH_SESSION is not None and _DEPTH_SESSION_PATH == str(target):
            return _DEPTH_SESSION

        model_path: Optional[Path] = target if (target.exists() and target.stat().st_size > 1_000_000) else None
        if model_path is None and allow_download:
            model_path = ensure_depth_model(models_dir=cache_dir)
        if model_path is None:
            return None

        try:
            sess_opts = ort.SessionOptions()
            sess_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            session = ort.InferenceSession(
                str(model_path),
                sess_options=sess_opts,
                providers=["CPUExecutionProvider"],
            )
            _DEPTH_SESSION = session
            _DEPTH_SESSION_PATH = str(model_path)
            return session
        except Exception as exc:
            sys.stderr.write(f"[scene_reconstructor] Failed to initialize ONNX depth session: {exc}\n")
            return None


def _normalize_rel_depth(raw: np.ndarray) -> np.ndarray:
    """Normalize a 2D relative inverse-depth map robustly into float32 ``[0, 1]``."""
    arr = np.asarray(raw, dtype=np.float32)
    arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
    lo = float(np.percentile(arr, 2))
    hi = float(np.percentile(arr, 98))
    if hi - lo < 1e-6:
        lo = float(arr.min())
        hi = float(arr.max())
    if hi - lo < 1e-6:
        return np.full(arr.shape, 0.5, dtype=np.float32)
    norm = (arr - lo) / (hi - lo)
    return np.clip(norm, 0.0, 1.0).astype(np.float32)


def estimate_geometric_relief(image_bgr: np.ndarray) -> np.ndarray:
    """Estimate fast edge-preserving relative inverse depth using OpenCV when ONNX is offline.

    Combines bilateral-filtered luminance, multi-scale gradient/structure salience, and a gentle
    vertical perspective prior (lower floor/foreground slightly closer than upper wall/ceiling).

    Args:
        image_bgr: Input BGR image array of shape ``(H, W, 3)``.

    Returns:
        Float32 relative inverse-depth map of shape ``(H, W)`` normalized to ``[0, 1]``
        (higher values indicate surfaces closer to the camera).
    """
    h, w = image_bgr.shape[:2]
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    smooth = cv2.bilateralFilter(gray, d=9, sigmaColor=0.18, sigmaSpace=12.0)

    gx = cv2.Sobel(smooth, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(smooth, cv2.CV_32F, 0, 1, ksize=3)
    grad_mag = cv2.GaussianBlur(np.hypot(gx, gy), (15, 15), 0)

    # Gentle perspective prior: lower image rows tend to be closer foreground/floor objects.
    y_prior = np.linspace(0.25, 0.78, h, dtype=np.float32).reshape(h, 1)
    y_prior = np.broadcast_to(y_prior, (h, w))

    # Mild horizontal center prominence for foreground objects in front of a room wall.
    x_coord = np.linspace(-1.0, 1.0, w, dtype=np.float32).reshape(1, w)
    center_prior = 0.12 * (1.0 - np.clip(x_coord * x_coord, 0.0, 1.0))

    raw = 0.52 * y_prior + 0.30 * smooth + 0.28 * grad_mag + center_prior
    raw = cv2.GaussianBlur(raw.astype(np.float32), (9, 9), 0)
    return _normalize_rel_depth(raw)


def _infer_depth_anything_session(session: ort.InferenceSession, image_bgr: np.ndarray) -> np.ndarray:
    """Run Depth Anything V2 Small ONNX inference on ``image_bgr`` and return ``[0, 1]`` inverse depth."""
    orig_h, orig_w = image_bgr.shape[:2]
    inp = session.get_inputs()[0]
    shape = list(inp.shape)

    in_h, in_w = 518, 518
    if len(shape) == 4:
        if isinstance(shape[2], int) and shape[2] > 0:
            in_h = shape[2]
        if isinstance(shape[3], int) and shape[3] > 0:
            in_w = shape[3]
    in_h = max(14, (int(in_h) // 14) * 14)
    in_w = max(14, (int(in_w) // 14) * 14)

    rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    resized = cv2.resize(rgb, (in_w, in_h), interpolation=cv2.INTER_CUBIC).astype(np.float32) / 255.0
    normalized = (resized - _IMAGENET_MEAN) / _IMAGENET_STD
    tensor = np.transpose(normalized, (2, 0, 1))[np.newaxis, :, :, :].astype(np.float32)

    output = session.run(None, {inp.name: tensor})[0]
    pred = np.asarray(output, dtype=np.float32)
    while pred.ndim > 2:
        pred = pred[0]
    if pred.ndim != 2:
        raise ValueError(f"Unexpected Depth Anything output shape: {output.shape}")

    if pred.shape != (orig_h, orig_w):
        pred = cv2.resize(pred, (orig_w, orig_h), interpolation=cv2.INTER_LINEAR)
    return _normalize_rel_depth(pred)


def estimate_relative_depth(
    image_bgr: np.ndarray,
    allow_download: bool = True,
    models_dir: Optional[str | Path] = None,
    flip_tta: bool = False,
) -> Tuple[np.ndarray, str]:
    """Estimate relative inverse depth using Depth Anything V2 Small ONNX with automatic fallback.

    Args:
        image_bgr: Input BGR image of shape ``(H, W, 3)``.
        allow_download: When ``True``, download ``depth_anything_v2_vits.onnx`` if not cached.
        models_dir: Optional model cache directory override.
        flip_tta: When ``True``, average inference on original and horizontally flipped image
            (Test-Time Augmentation) to suppress asymmetric edge wobble.

    Returns:
        Tuple ``(rel_depth, engine_source)`` where ``rel_depth`` is float32 ``(H, W)`` in ``[0, 1]``
        (higher = closer) and ``engine_source`` is ``"depth_anything"`` or ``"geometric_relief"``.
    """
    session = _get_depth_session(models_dir=models_dir, allow_download=allow_download)
    if session is not None:
        try:
            rel_depth = _infer_depth_anything_session(session, image_bgr)
            if flip_tta:
                flipped_bgr = cv2.flip(image_bgr, 1)
                rel_flip = cv2.flip(_infer_depth_anything_session(session, flipped_bgr), 1)
                rel_depth = _normalize_rel_depth(0.5 * (rel_depth + rel_flip))
            return rel_depth, "depth_anything"
        except Exception as exc:
            sys.stderr.write(f"[scene_reconstructor] ONNX depth inference failed, falling back: {exc}\n")

    rel_geo = estimate_geometric_relief(image_bgr)
    if flip_tta:
        rel_geo_flip = cv2.flip(estimate_geometric_relief(cv2.flip(image_bgr, 1)), 1)
        rel_geo = _normalize_rel_depth(0.5 * (rel_geo + rel_geo_flip))
    return rel_geo, "geometric_relief"


def calibrate_depth_with_lidar(
    rel_depth: np.ndarray,
    lidar_points_xy: Optional[Sequence[Tuple[float, float]]],
    hfov_deg: float = 65.0,
    yaw_deg: float = 0.0,
    fallback_distance_m: float = 1.8,
    depth_relief_scale: float = 1.0,
    base_depth_source: str = "depth_anything",
) -> Tuple[np.ndarray, bool, int, str]:
    """Calibrate a relative inverse-depth map into metric meters using live LD19 LiDAR rays.

    Accepts 2D LiDAR points ``[(lx, ly), ...]`` where ``+Y`` is forward at ``yaw_deg=0`` and
    ``+X`` is right (matching TwinScan 2D/3D canvas coordinates where Three.js ``-Z == 2D +Y``).
    When ``>= 6`` valid rays fall inside the horizontal camera FOV (``0.25..8.0 m``), projects
    each ray onto the middle horizontal band (``0.38*H .. 0.62*H``) of ``rel_depth`` and fits a
    robust MAD-trimmed affine mapping ``z_metric = clip(a * rel_depth + b, 0.25, 8.0)``.
    Otherwise maps ``rel_depth`` cleanly around ``fallback_distance_m`` with realistic physical relief.

    Args:
        rel_depth: Relative inverse-depth map ``(H, W)`` in ``[0, 1]`` (higher = closer).
        lidar_points_xy: Optional sequence of ``(lx, ly)`` 2D LiDAR points in meters.
        hfov_deg: Camera horizontal field of view in degrees.
        yaw_deg: Camera yaw heading in degrees (counter-clockwise around ``+Y`` up).
        fallback_distance_m: Reference wall distance in meters when LiDAR is offline.
        depth_relief_scale: Multiplier for 3D depth relief amplitude around median distance.
        base_depth_source: Underlying depth estimator (``"depth_anything"`` or ``"geometric_relief"``).

    Returns:
        Tuple ``(depth_m, lidar_calibrated, ray_count, depth_source)``.
    """
    rel = np.clip(np.asarray(rel_depth, dtype=np.float32), 0.0, 1.0)
    h, w = rel.shape[:2]
    relief_scale = float(np.clip(depth_relief_scale, 0.1, 3.0))
    half_fov_rad = math.radians(max(10.0, min(160.0, float(hfov_deg))) / 2.0)
    fx = 0.5 / math.tan(half_fov_rad)

    yaw_rad = math.radians(float(yaw_deg))
    cos_y = math.cos(yaw_rad)
    sin_y = math.sin(yaw_rad)

    band_r0 = max(0, int(round(0.38 * h)))
    band_r1 = min(h, max(band_r0 + 1, int(round(0.62 * h))))

    sample_r: List[float] = []
    sample_z: List[float] = []

    if lidar_points_xy:
        for pt in lidar_points_xy:
            if len(pt) < 2:
                continue
            lx, ly = float(pt[0]), float(pt[1])
            if not (math.isfinite(lx) and math.isfinite(ly)):
                continue
            dist = math.hypot(lx, ly)
            if dist < 0.25 or dist > 8.0:
                continue
            # Rotate world 2D point into camera local frame (forward = -sin(yaw)*x + cos(yaw)*y).
            forward = -sin_y * lx + cos_y * ly
            right = cos_y * lx + sin_y * ly
            if forward <= 0.05:
                continue
            angle = math.atan2(right, forward)
            if abs(angle) > half_fov_rad:
                continue
            u = 0.5 + (right / forward) * fx
            col = int(round(u * (w - 1)))
            if col < 0 or col >= w:
                continue
            rel_val = float(np.median(rel[band_r0:band_r1, col]))
            sample_r.append(rel_val)
            sample_z.append(forward)

    ray_count = len(sample_z)
    if ray_count >= 6:
        r_arr = np.asarray(sample_r, dtype=np.float64)
        z_arr = np.asarray(sample_z, dtype=np.float64)

        def _fit_affine(rv: np.ndarray, zv: np.ndarray) -> Tuple[float, float]:
            if float(np.std(rv)) < 1e-4 or len(rv) < 2:
                return 0.0, float(np.median(zv))
            design = np.column_stack([rv, np.ones_like(rv)])
            coeffs, _, _, _ = np.linalg.lstsq(design, zv, rcond=None)
            return float(coeffs[0]), float(coeffs[1])

        a, b = _fit_affine(r_arr, z_arr)
        residuals = z_arr - (a * r_arr + b)
        med_res = float(np.median(residuals))
        mad = float(np.median(np.abs(residuals - med_res)))
        scale_mad = max(1.4826 * mad, 0.025)
        inlier_mask = np.abs(residuals - med_res) <= (2.0 * scale_mad)
        if int(np.sum(inlier_mask)) >= 4:
            a, b = _fit_affine(r_arr[inlier_mask], z_arr[inlier_mask])

        # Enforce physically consistent inverse-depth sign (higher rel_depth => closer => smaller z).
        if a > 0.0:
            z_inliers = z_arr[inlier_mask] if int(np.sum(inlier_mask)) >= 4 else z_arr
            a = 0.0
            b = float(np.median(z_inliers))

        z_metric = np.clip(a * rel.astype(np.float64) + b, 0.25, 8.0)
        med_z = float(np.median(z_metric))
        z_final = np.clip(med_z + (z_metric - med_z) * relief_scale, 0.25, 8.0).astype(np.float32)
        depth_source = "lidar_depth_anything" if base_depth_source == "depth_anything" else "lidar_only"
        return z_final, True, ray_count, depth_source

    fb = float(np.clip(fallback_distance_m, 0.35, 6.5))
    span = 0.42 * fb * relief_scale
    med_rel = float(np.median(rel))
    # Map relative inverse depth (higher = closer) cleanly around fallback_distance_m.
    z_fallback = fb - 2.0 * (rel.astype(np.float64) - med_rel) * span
    z_final = np.clip(z_fallback, 0.35, 6.5).astype(np.float32)
    depth_source = "depth_anything" if base_depth_source == "depth_anything" else "geometric_relief"
    return z_final, False, ray_count, depth_source


def _rotation_matrix_yxz(yaw_deg: float, pitch_deg: float, roll_deg: float) -> np.ndarray:
    """Compute canonical right-handed 3x3 rotation matrix (yaw +Y, pitch +X, roll -Z)."""
    yr = math.radians(float(yaw_deg))
    pr = math.radians(float(pitch_deg))
    rr = math.radians(float(roll_deg))

    cy, sy = math.cos(yr), math.sin(yr)
    cp, sp = math.cos(pr), math.sin(pr)
    cr, sr = math.cos(-rr), math.sin(-rr)

    ry = np.array([[cy, 0.0, sy], [0.0, 1.0, 0.0], [-sy, 0.0, cy]], dtype=np.float64)
    rx = np.array([[1.0, 0.0, 0.0], [0.0, cp, -sp], [0.0, sp, cp]], dtype=np.float64)
    rz = np.array([[cr, -sr, 0.0], [sr, cr, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64)
    return ry @ rx @ rz


def build_relief_mesh_payload(
    depth_m: np.ndarray,
    image_bgr: Optional[np.ndarray],
    pose: Dict[str, Any],
    resolution: str = "medium",
    hfov_deg: float = 65.0,
    vfov_deg: float = 50.0,
    tear_threshold_ratio: float = 0.14,
    taubin_smooth: bool = False,
) -> Dict[str, Any]:
    """Build a canonical right-handed Three.js/glTF 3D relief mesh payload from a metric depth map.

    Args:
        depth_m: Metric planar depth map ``(H, W)`` in meters.
        image_bgr: Optional source BGR image (unused for geometry, accepted for signature parity).
        pose: 6-DOF pose dictionary ``{x, y, z, yaw_deg, pitch_deg, roll_deg}``.
        resolution: Grid density preset (``"low"`` 48x36, ``"medium"`` 80x60, ``"high"`` 120x90).
        hfov_deg: Horizontal camera FOV in degrees.
        vfov_deg: Vertical camera FOV in degrees.
        tear_threshold_ratio: Skip triangles whose ``(max_d - min_d) / median_d`` exceeds this ratio.
        taubin_smooth: When ``True``, apply 2-pass non-shrinking Taubin smoothing to non-tear
            interior vertices before computing final vertex normals.

    Returns:
        Dictionary containing ``mesh`` (compact 4-decimal JSON payload matching ``ScenePanelMesh``),
        ``vertex_count``, ``triangle_count``, ``mean_distance_m``, ``min_distance_m``,
        and ``max_distance_m``.
    """
    _ = image_bgr
    grid_w, grid_h = RESOLUTION_GRID_MAP.get(str(resolution).lower(), RESOLUTION_GRID_MAP["medium"])
    depth_grid = cv2.resize(
        np.asarray(depth_m, dtype=np.float32),
        (grid_w, grid_h),
        interpolation=cv2.INTER_AREA if depth_m.shape[0] > grid_h else cv2.INTER_LINEAR,
    ).astype(np.float64)
    depth_grid = np.clip(np.nan_to_num(depth_grid, nan=1.8, posinf=6.5, neginf=0.35), 0.25, 8.0)

    u_1d = np.linspace(0.0, 1.0, grid_w, dtype=np.float64)
    v_1d = 1.0 - np.linspace(0.0, 1.0, grid_h, dtype=np.float64)
    u_grid, v_grid = np.meshgrid(u_1d, v_1d)

    fx = 0.5 / math.tan(math.radians(max(10.0, min(160.0, float(hfov_deg))) / 2.0))
    fy = 0.5 / math.tan(math.radians(max(10.0, min(150.0, float(vfov_deg))) / 2.0))

    px = ((u_grid - 0.5) / fx) * depth_grid
    py = ((v_grid - 0.5) / fy) * depth_grid
    pz = -depth_grid

    local_verts = np.stack([px, py, pz], axis=-1).reshape(-1, 3)

    rot = _rotation_matrix_yxz(
        yaw_deg=float(pose.get("yaw_deg", 0.0)),
        pitch_deg=float(pose.get("pitch_deg", 0.0)),
        roll_deg=float(pose.get("roll_deg", 0.0)),
    )
    tx = float(pose.get("x", 0.0))
    ty = float(pose.get("z", 0.22))
    tz = -float(pose.get("y", 0.0))

    world_verts = (local_verts @ rot.T) + np.array([tx, ty, tz], dtype=np.float64)

    # Keep bottom of reconstructed wall sitting cleanly at or above the floor grid (y >= 0.0).
    min_y = float(world_verts[:, 1].min())
    if min_y < 0.0:
        world_verts[:, 1] -= min_y

    # Build quad-split CCW triangles facing the camera (+Z local).
    r_idx = np.arange(grid_h - 1, dtype=np.int32)[:, None]
    c_idx = np.arange(grid_w - 1, dtype=np.int32)[None, :]
    i00 = (r_idx * grid_w + c_idx).ravel()
    i01 = i00 + 1
    i10 = i00 + grid_w
    i11 = i10 + 1

    tri1 = np.stack([i00, i10, i01], axis=-1)
    tri2 = np.stack([i01, i10, i11], axis=-1)
    all_tris = np.concatenate([tri1, tri2], axis=0)

    flat_d = depth_grid.ravel()
    tri_d = flat_d[all_tris]
    tri_d_sorted = np.sort(tri_d, axis=1)
    d_min = tri_d_sorted[:, 0]
    d_med = np.maximum(tri_d_sorted[:, 1], 1e-4)
    d_max = tri_d_sorted[:, 2]

    keep_mask = (d_max - d_min) <= (float(tear_threshold_ratio) * d_med)
    kept_tris = all_tris[keep_mask]
    if len(kept_tris) == 0:
        kept_tris = all_tris

    if taubin_smooth:
        smoothed_flat = taubin_smooth_mesh(
            positions=world_verts.ravel(),
            indices=kept_tris.ravel(),
            grid_w=grid_w,
            grid_h=grid_h,
            iterations=2,
        )
        world_verts = np.asarray(smoothed_flat, dtype=np.float64).reshape(-1, 3)

    # Compute area-weighted smooth vertex normals oriented toward camera.
    normals = np.zeros_like(world_verts, dtype=np.float64)
    v0 = world_verts[kept_tris[:, 0]]
    v1 = world_verts[kept_tris[:, 1]]
    v2 = world_verts[kept_tris[:, 2]]
    face_normals = np.cross(v1 - v0, v2 - v0)

    np.add.at(normals, kept_tris[:, 0], face_normals)
    np.add.at(normals, kept_tris[:, 1], face_normals)
    np.add.at(normals, kept_tris[:, 2], face_normals)

    fallback_n = rot @ np.array([0.0, 0.0, 1.0], dtype=np.float64)
    norms = np.linalg.norm(normals, axis=1, keepdims=True)
    zero_mask = (norms[:, 0] < 1e-8)
    normals = np.divide(normals, np.where(norms > 1e-8, norms, 1.0))
    if np.any(zero_mask):
        normals[zero_mask] = fallback_n

    uvs = np.stack([u_grid.ravel(), v_grid.ravel()], axis=-1)

    mesh_payload: Dict[str, Any] = {
        "grid_w": int(grid_w),
        "grid_h": int(grid_h),
        "hfov_deg": round(float(hfov_deg), 2),
        "vfov_deg": round(float(vfov_deg), 2),
        "positions": [round(float(v), 4) for v in world_verts.ravel()],
        "normals": [round(float(v), 4) for v in normals.ravel()],
        "uvs": [round(float(v), 4) for v in uvs.ravel()],
        "indices": [int(i) for i in kept_tris.ravel()],
    }

    return {
        "mesh": mesh_payload,
        "vertex_count": int(world_verts.shape[0]),
        "triangle_count": int(kept_tris.shape[0]),
        "mean_distance_m": round(float(np.mean(depth_grid)), 3),
        "min_distance_m": round(float(np.min(depth_grid)), 3),
        "max_distance_m": round(float(np.max(depth_grid)), 3),
    }


def export_panel_glb(
    positions: Sequence[float],
    normals: Sequence[float],
    uvs: Sequence[float],
    indices: Sequence[int],
    jpeg_bytes: bytes,
    normal_jpeg_bytes: Optional[bytes] = None,
) -> bytes:
    """Export a textured 3D scene relief panel into binary glTF 2.0 (``.glb``) bytes.

    Embeds vertex positions, normals, glTF-convention UVs, uint32 triangle indices, the
    raw ``image/jpeg`` albedo texture, and an optional tangent-space ``normalTexture`` directly
    into a spec-compliant binary GLB container without re-encoding JPEGs or requiring Pillow.

    Args:
        positions: Flat XYZ vertex coordinate sequence (length ``3 * N``).
        normals: Flat XYZ unit vertex normal sequence (length ``3 * N``).
        uvs: Flat OpenGL UV texture coordinate sequence in ``[0, 1]`` (length ``2 * N``).
        indices: Flat triangle vertex index sequence (length ``3 * M``).
        jpeg_bytes: Encoded JPEG texture image bytes embedded into the GLB material.
        normal_jpeg_bytes: Optional encoded tangent-space normal map JPEG bytes.

    Returns:
        Binary ``.glb`` file bytes starting with the ``b"glTF"`` magic header.
    """
    verts = np.ascontiguousarray(np.asarray(positions, dtype="<f4").reshape(-1, 3))
    norms = np.ascontiguousarray(np.asarray(normals, dtype="<f4").reshape(-1, 3))
    # Convert OpenGL UVs (v=1 top, v=0 bottom) to glTF 2.0 UVs (v=0 top, v=1 bottom).
    uv_arr = np.asarray(uvs, dtype="<f4").reshape(-1, 2).copy()
    uv_arr[:, 1] = 1.0 - uv_arr[:, 1]
    uv_arr = np.ascontiguousarray(uv_arr)
    idx_arr = np.ascontiguousarray(np.asarray(indices, dtype="<u4").reshape(-1))

    pos_bytes = verts.tobytes()
    norm_bytes = norms.tobytes()
    uv_bytes = uv_arr.tobytes()
    idx_bytes = idx_arr.tobytes()
    img_bytes = bytes(jpeg_bytes)

    bin_chunks: List[bytes] = []
    buffer_views: List[Dict[str, Any]] = []
    offset = 0

    def _append_view(data: bytes, target: Optional[int] = None) -> int:
        nonlocal offset
        pad = (4 - (offset % 4)) % 4
        if pad:
            bin_chunks.append(b"\x00" * pad)
            offset += pad
        view: Dict[str, Any] = {"buffer": 0, "byteOffset": offset, "byteLength": len(data)}
        if target is not None:
            view["target"] = target
        bin_chunks.append(data)
        offset += len(data)
        idx = len(buffer_views)
        buffer_views.append(view)
        return idx

    bv_pos = _append_view(pos_bytes, target=34962)
    bv_norm = _append_view(norm_bytes, target=34962)
    bv_uv = _append_view(uv_bytes, target=34962)
    bv_idx = _append_view(idx_bytes, target=34963)
    bv_img = _append_view(img_bytes, target=None)

    images_list: List[Dict[str, Any]] = [{"bufferView": bv_img, "mimeType": "image/jpeg"}]
    textures_list: List[Dict[str, Any]] = [{"sampler": 0, "source": 0}]
    material_def: Dict[str, Any] = {
        "name": "RoomWallPBR",
        "doubleSided": True,
        "pbrMetallicRoughness": {
            "baseColorTexture": {"index": 0},
            "metallicFactor": 0.05,
            "roughnessFactor": 0.85,
        },
    }

    if normal_jpeg_bytes:
        bv_norm_img = _append_view(bytes(normal_jpeg_bytes), target=None)
        images_list.append({"bufferView": bv_norm_img, "mimeType": "image/jpeg"})
        textures_list.append({"sampler": 0, "source": 1})
        material_def["normalTexture"] = {"index": 1, "scale": 1.15}

    pad_end = (4 - (offset % 4)) % 4
    if pad_end:
        bin_chunks.append(b"\x00" * pad_end)
        offset += pad_end
    bin_blob = b"".join(bin_chunks)

    v_min = [float(x) for x in verts.min(axis=0)] if len(verts) else [0.0, 0.0, 0.0]
    v_max = [float(x) for x in verts.max(axis=0)] if len(verts) else [0.0, 0.0, 0.0]

    gltf: Dict[str, Any] = {
        "asset": {"version": "2.0", "generator": "Eigenia TwinScan 3D Room Fusion"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": "ReconstructedWallPanel", "mesh": 0}],
        "meshes": [
            {
                "name": "ReconstructedWallMesh",
                "primitives": [
                    {
                        "attributes": {
                            "POSITION": 0,
                            "NORMAL": 1,
                            "TEXCOORD_0": 2,
                        },
                        "indices": 3,
                        "material": 0,
                        "mode": 4,
                    }
                ],
            }
        ],
        "materials": [material_def],
        "textures": textures_list,
        "samplers": [
            {
                "magFilter": 9729,
                "minFilter": 9987,
                "wrapS": 33071,
                "wrapT": 33071,
            }
        ],
        "images": images_list,
        "accessors": [
            {
                "bufferView": bv_pos,
                "componentType": 5126,
                "count": int(verts.shape[0]),
                "type": "VEC3",
                "min": v_min,
                "max": v_max,
            },
            {
                "bufferView": bv_norm,
                "componentType": 5126,
                "count": int(norms.shape[0]),
                "type": "VEC3",
            },
            {
                "bufferView": bv_uv,
                "componentType": 5126,
                "count": int(uv_arr.shape[0]),
                "type": "VEC2",
            },
            {
                "bufferView": bv_idx,
                "componentType": 5125,
                "count": int(idx_arr.shape[0]),
                "type": "SCALAR",
            },
        ],
        "bufferViews": buffer_views,
        "buffers": [{"byteLength": len(bin_blob)}],
    }

    json_bytes = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    json_pad = (4 - (len(json_bytes) % 4)) % 4
    if json_pad:
        json_bytes += b" " * json_pad

    total_len = 12 + 8 + len(json_bytes) + 8 + len(bin_blob)
    header = struct.pack("<4sII", b"glTF", 2, total_len)
    json_chunk = struct.pack("<II", len(json_bytes), 0x4E4F534A) + json_bytes
    bin_chunk = struct.pack("<II", len(bin_blob), 0x004E4942) + bin_blob
    return header + json_chunk + bin_chunk


def export_combined_room_glb(panel_entries: Sequence[Dict[str, Any]]) -> bytes:
    """Export multiple reconstructed 3D room panels into a single binary glTF 2.0 (``.glb``) scene.

    Embeds every panel's geometry (``positions``, ``normals``, glTF-flipped ``uvs``, uint32
    ``indices``), raw ``image/jpeg`` ``baseColorTexture``, and optional tangent-space
    ``normalTexture`` into one spec-compliant multi-mesh binary GLB container using pure stdlib
    ``struct``/``json`` and ``numpy`` (zero Pillow dependency).

    Args:
        panel_entries: Sequence of dictionaries each containing ``label`` (optional), ``jpeg_bytes``,
            optional ``normal_jpeg_bytes``, and geometry arrays either at top-level
            (``positions``, ``normals``, ``uvs``, ``indices``) or nested under ``mesh``.

    Returns:
        Binary ``.glb`` file bytes starting with the ``b"glTF"`` magic header.

    Raises:
        ValueError: If no valid renderable panels are supplied.
    """
    bin_chunks: List[bytes] = []
    buffer_views: List[Dict[str, Any]] = []
    accessors: List[Dict[str, Any]] = []
    images_list: List[Dict[str, Any]] = []
    textures_list: List[Dict[str, Any]] = []
    materials_list: List[Dict[str, Any]] = []
    meshes_list: List[Dict[str, Any]] = []
    nodes_list: List[Dict[str, Any]] = []
    offset = 0

    def _append_view(data: bytes, target: Optional[int] = None) -> int:
        nonlocal offset
        pad = (4 - (offset % 4)) % 4
        if pad:
            bin_chunks.append(b"\x00" * pad)
            offset += pad
        view: Dict[str, Any] = {"buffer": 0, "byteOffset": offset, "byteLength": len(data)}
        if target is not None:
            view["target"] = target
        bin_chunks.append(data)
        offset += len(data)
        idx = len(buffer_views)
        buffer_views.append(view)
        return idx

    for p_idx, entry in enumerate(panel_entries):
        mesh_src = entry.get("mesh") if isinstance(entry.get("mesh"), dict) else entry
        raw_pos = mesh_src.get("positions")
        raw_norm = mesh_src.get("normals")
        raw_uv = mesh_src.get("uvs")
        raw_idx = mesh_src.get("indices")
        jpeg_bytes = entry.get("jpeg_bytes")
        if not raw_pos or not raw_norm or not raw_uv or not raw_idx or not jpeg_bytes:
            continue

        verts = np.ascontiguousarray(np.asarray(raw_pos, dtype="<f4").reshape(-1, 3))
        norms = np.ascontiguousarray(np.asarray(raw_norm, dtype="<f4").reshape(-1, 3))
        uv_arr = np.asarray(raw_uv, dtype="<f4").reshape(-1, 2).copy()
        uv_arr[:, 1] = 1.0 - uv_arr[:, 1]
        uv_arr = np.ascontiguousarray(uv_arr)
        idx_arr = np.ascontiguousarray(np.asarray(raw_idx, dtype="<u4").reshape(-1))
        if verts.shape[0] == 0 or idx_arr.size == 0:
            continue

        bv_pos = _append_view(verts.tobytes(), target=34962)
        bv_norm = _append_view(norms.tobytes(), target=34962)
        bv_uv = _append_view(uv_arr.tobytes(), target=34962)
        bv_idx = _append_view(idx_arr.tobytes(), target=34963)
        bv_img = _append_view(bytes(jpeg_bytes), target=None)

        acc_pos = len(accessors)
        accessors.append(
            {
                "bufferView": bv_pos,
                "componentType": 5126,
                "count": int(verts.shape[0]),
                "type": "VEC3",
                "min": [float(x) for x in verts.min(axis=0)],
                "max": [float(x) for x in verts.max(axis=0)],
            }
        )
        acc_norm = len(accessors)
        accessors.append(
            {
                "bufferView": bv_norm,
                "componentType": 5126,
                "count": int(norms.shape[0]),
                "type": "VEC3",
            }
        )
        acc_uv = len(accessors)
        accessors.append(
            {
                "bufferView": bv_uv,
                "componentType": 5126,
                "count": int(uv_arr.shape[0]),
                "type": "VEC2",
            }
        )
        acc_idx = len(accessors)
        accessors.append(
            {
                "bufferView": bv_idx,
                "componentType": 5125,
                "count": int(idx_arr.shape[0]),
                "type": "SCALAR",
            }
        )

        img_base_idx = len(images_list)
        images_list.append({"bufferView": bv_img, "mimeType": "image/jpeg"})
        tex_base_idx = len(textures_list)
        textures_list.append({"sampler": 0, "source": img_base_idx})

        mat_def: Dict[str, Any] = {
            "name": f"RoomWallPBR_{p_idx}",
            "doubleSided": True,
            "pbrMetallicRoughness": {
                "baseColorTexture": {"index": tex_base_idx},
                "metallicFactor": 0.05,
                "roughnessFactor": 0.85,
            },
        }

        normal_bytes = entry.get("normal_jpeg_bytes")
        if normal_bytes:
            bv_norm_img = _append_view(bytes(normal_bytes), target=None)
            img_norm_idx = len(images_list)
            images_list.append({"bufferView": bv_norm_img, "mimeType": "image/jpeg"})
            tex_norm_idx = len(textures_list)
            textures_list.append({"sampler": 0, "source": img_norm_idx})
            mat_def["normalTexture"] = {"index": tex_norm_idx, "scale": 1.15}

        mat_idx = len(materials_list)
        materials_list.append(mat_def)

        label = str(entry.get("label") or f"WallPanel_{p_idx + 1}")
        mesh_idx = len(meshes_list)
        meshes_list.append(
            {
                "name": f"Mesh_{label}",
                "primitives": [
                    {
                        "attributes": {
                            "POSITION": acc_pos,
                            "NORMAL": acc_norm,
                            "TEXCOORD_0": acc_uv,
                        },
                        "indices": acc_idx,
                        "material": mat_idx,
                        "mode": 4,
                    }
                ],
            }
        )
        nodes_list.append({"name": label, "mesh": mesh_idx})

    if not nodes_list:
        raise ValueError("No valid reconstructed 3D panels with geometry and texture bytes to export.")

    pad_end = (4 - (offset % 4)) % 4
    if pad_end:
        bin_chunks.append(b"\x00" * pad_end)
        offset += pad_end
    bin_blob = b"".join(bin_chunks)

    gltf: Dict[str, Any] = {
        "asset": {"version": "2.0", "generator": "Eigenia TwinScan Full-Room 3D Exporter"},
        "scene": 0,
        "scenes": [{"name": "TwinScanRoom", "nodes": list(range(len(nodes_list)))}],
        "nodes": nodes_list,
        "meshes": meshes_list,
        "materials": materials_list,
        "textures": textures_list,
        "samplers": [
            {
                "magFilter": 9729,
                "minFilter": 9987,
                "wrapS": 33071,
                "wrapT": 33071,
            }
        ],
        "images": images_list,
        "accessors": accessors,
        "bufferViews": buffer_views,
        "buffers": [{"byteLength": len(bin_blob)}],
    }

    json_bytes = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    json_pad = (4 - (len(json_bytes) % 4)) % 4
    if json_pad:
        json_bytes += b" " * json_pad

    total_len = 12 + 8 + len(json_bytes) + 8 + len(bin_blob)
    header = struct.pack("<4sII", b"glTF", 2, total_len)
    json_chunk = struct.pack("<II", len(json_bytes), 0x4E4F534A) + json_bytes
    bin_chunk = struct.pack("<II", len(bin_blob), 0x004E4942) + bin_blob
    return header + json_chunk + bin_chunk


async def capture_live_camera_frame(
    ip: str,
    video_port: int = 8080,
    ros_version: str = "ros2",
    timeout: float = 5.0,
    retries: int = 3,
) -> Tuple[bytes, str]:
    """Capture a live JPEG snapshot from PuppyPi ``web_video_server`` across ROS 1 & ROS 2 topics.

    Tries the active ROS profile's primary camera topic first (``/image_raw`` on ROS 2 Humble,
    ``/usb_cam/image_raw`` on ROS 1 Noetic), automatically falling back to the alternate topic
    with up to ``retries`` attempts and ``sys.stderr`` error logging.

    Args:
        ip: Robot IPv4 address.
        video_port: ``web_video_server`` HTTP port (default ``8080``).
        ros_version: Active ROS mode (``"ros1"`` or ``"ros2"``).
        timeout: Per-attempt HTTP read timeout in seconds.
        retries: Maximum retry attempts per topic.

    Returns:
        Tuple ``(jpeg_bytes, topic_used)``.

    Raises:
        ConnectionError: When no camera topic yields a valid JPEG snapshot.
    """
    profile = get_ros_profile(ros_version)
    primary = str(profile.get("camera_topic") or "/image_raw")
    alternate = "/usb_cam/image_raw" if primary == "/image_raw" else "/image_raw"
    topics = [primary, alternate]

    last_exc: Optional[Exception] = None
    for topic in topics:
        try:
            data = await fetch_robot_snapshot(
                ip=ip,
                port=int(video_port),
                topic=topic,
                timeout=timeout,
                retries=retries,
            )
            if data and len(data) > 100:
                return data, topic
        except Exception as exc:
            last_exc = exc
            sys.stderr.write(
                f"[scene_reconstructor] Camera snapshot on {ip}:{video_port}{topic} failed: {exc}\n"
            )
    raise ConnectionError(f"Unable to capture camera frame from {ip}:{video_port}: {last_exc}")


async def capture_camera_burst(
    robot: Dict[str, Any],
    count: int = 3,
    interval_s: float = 0.06,
    timeout: float = 5.0,
    retries: int = 3,
) -> Tuple[List[bytes], str]:
    """Capture a short burst of live JPEG frames from PuppyPi for temporal denoising.

    Args:
        robot: Robot record dictionary containing ``ip_address``, optional ``video_port``,
            and ``ros_version``.
        count: Number of frames to capture (clamped ``1..5``).
        interval_s: Delay in seconds between burst frames.
        timeout: Per-attempt HTTP read timeout in seconds.
        retries: Maximum retry attempts per frame.

    Returns:
        Tuple ``(jpeg_frames_list, topic_used)``.
    """
    ip = str(robot["ip_address"])
    video_port = int(robot.get("video_port") or 8080)
    ros_version = str(robot.get("ros_version") or "ros2")
    n = max(1, min(5, int(count)))

    frames: List[bytes] = []
    topic_used = "/image_raw"
    for idx in range(n):
        try:
            frame, topic_used = await capture_live_camera_frame(
                ip=ip,
                video_port=video_port,
                ros_version=ros_version,
                timeout=timeout,
                retries=retries,
            )
            frames.append(frame)
        except Exception as exc:
            if not frames:
                raise
            sys.stderr.write(
                f"[scene_reconstructor] Burst frame {idx + 1}/{n} failed on {ip}, continuing with {len(frames)} frames: {exc}\n"
            )
            break
        if idx < n - 1 and interval_s > 0:
            await asyncio.sleep(interval_s)
    return frames, topic_used


def reconstruct_enhanced_wall_panel(
    jpeg_frames: Sequence[bytes],
    lidar_sweeps_xy: Optional[Sequence[Sequence[Tuple[float, float]]]] = None,
    pose: Optional[Dict[str, Any]] = None,
    resolution: str = "medium",
    fallback_distance_m: float = 1.8,
    depth_relief_scale: float = 1.0,
    hfov_deg: float = 65.0,
    vfov_deg: float = 50.0,
    tear_threshold_ratio: float = 0.14,
    enhance_options: Optional[Dict[str, Any]] = None,
    allow_model_download: bool = True,
    models_dir: Optional[str | Path] = None,
) -> Tuple[Dict[str, Any], bytes, Optional[bytes], bytes]:
    """Run the 5-pass composite enhancement + 3D wall reconstruction pipeline.

    Args:
        jpeg_frames: One or more raw JPEG frame byte buffers captured from PuppyPi camera.
        lidar_sweeps_xy: Optional sequence of real hardware 2D LiDAR sweeps.
        pose: 6-DOF pose dictionary ``{x, y, z, yaw_deg, pitch_deg, roll_deg}``.
        resolution: Mesh density preset (``"low"``, ``"medium"``, ``"high"``).
        fallback_distance_m: Reference wall distance in meters when LiDAR is offline.
        depth_relief_scale: Depth relief amplitude multiplier.
        hfov_deg: Camera horizontal FOV in degrees.
        vfov_deg: Camera vertical FOV in degrees.
        tear_threshold_ratio: Depth-step ratio threshold for triangle tear filtering.
        enhance_options: Optional ``SceneEnhanceOptions`` dictionary.
        allow_model_download: Whether to download ``depth_anything_v2_vits.onnx`` if absent.
        models_dir: Optional ONNX model cache directory override.

    Returns:
        Tuple ``(result_dict, enhanced_jpeg_bytes, normal_map_jpeg_bytes, glb_bytes)``.

    Raises:
        ValueError: When no valid JPEG/PNG image can be decoded.
    """
    t0 = time.perf_counter()
    opts = enhance_options or {}
    preset_name = str(opts.get("quality_preset") or "balanced")
    cfg = resolve_enhance_preset(quality_preset=preset_name, overrides=opts)

    decoded: List[np.ndarray] = []
    for raw in jpeg_frames:
        if not raw:
            continue
        arr = np.frombuffer(raw, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is not None and img.size > 0:
            decoded.append(img)
    if not decoded:
        raise ValueError("Could not decode camera snapshot as a valid JPEG/PNG image.")

    passes_applied: List[str] = []
    q_before = measure_image_quality(decoded[0])

    # Pass 1: Temporal burst camera stacking.
    if len(decoded) > 1 and int(cfg["burst_frames"]) > 1:
        stacked_bgr, frames_stacked = stack_camera_burst(decoded[: int(cfg["burst_frames"])])
        if frames_stacked > 1:
            passes_applied.append(f"burst_stack_{frames_stacked}")
    else:
        stacked_bgr = decoded[0]
        frames_stacked = 1

    # Pass 2: Photometric enhancement + sharpening + optional 2x Lanczos4 upscale.
    enhanced_bgr, img_passes = enhance_camera_image(
        stacked_bgr,
        clahe_sharpen=bool(cfg["clahe_sharpen"]),
        upscale_2x=bool(cfg["upscale_2x"]),
        ultra_nlm=bool(cfg["ultra_nlm"]),
    )
    passes_applied.extend(img_passes)
    q_after = measure_image_quality(
        enhanced_bgr,
        ref_shape=(int(q_before["height"]), int(q_before["width"])),
    )

    ok_enc, enc_buf = cv2.imencode(".jpg", enhanced_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 93])
    if not ok_enc:
        raise ValueError("Failed to encode enhanced wall texture JPEG.")
    enhanced_jpeg_bytes = bytes(enc_buf)

    norm_pose: Dict[str, float] = {
        "x": round(float((pose or {}).get("x", 0.0)), 4),
        "y": round(float((pose or {}).get("y", 0.0)), 4),
        "z": round(float((pose or {}).get("z", 0.22)), 4),
        "yaw_deg": round(float((pose or {}).get("yaw_deg", 0.0)), 2),
        "pitch_deg": round(float((pose or {}).get("pitch_deg", 0.0)), 2),
        "roll_deg": round(float((pose or {}).get("roll_deg", 0.0)), 2),
    }

    # Pass 3: Multi-sweep LiDAR denoising.
    lidar_xy: Optional[List[Tuple[float, float]]] = None
    lidar_sweeps_stacked = 0
    if lidar_sweeps_xy:
        non_empty_sweeps = [sw for sw in lidar_sweeps_xy if sw]
        if len(non_empty_sweeps) > 1:
            lidar_xy, lidar_sweeps_stacked = refine_lidar_sweeps(non_empty_sweeps)
            passes_applied.append(f"lidar_refine_{lidar_sweeps_stacked}")
        elif len(non_empty_sweeps) == 1:
            lidar_xy = [(float(p[0]), float(p[1])) for p in non_empty_sweeps[0]]
            lidar_sweeps_stacked = 1

    # Pass 4A: Depth estimation with optional Flip-TTA.
    use_tta = bool(cfg["flip_tta"])
    rel_depth, base_engine = estimate_relative_depth(
        enhanced_bgr,
        allow_download=allow_model_download,
        models_dir=models_dir,
        flip_tta=use_tta,
    )
    if use_tta:
        passes_applied.append("flip_tta")

    # Pass 4B: O(N) He et al. RGB-Guided Depth Filter.
    if bool(cfg["guided_depth"]):
        guide_gray = cv2.cvtColor(enhanced_bgr, cv2.COLOR_BGR2GRAY)
        rel_depth = guided_filter_depth(guide_gray, rel_depth, radius=8, eps=1e-4)
        passes_applied.append("guided_depth")

    # Metric calibration + Pass 4C LiDAR column residual warp.
    depth_m, lidar_calibrated, ray_count, depth_source = calibrate_depth_with_lidar(
        rel_depth=rel_depth,
        lidar_points_xy=lidar_xy,
        hfov_deg=hfov_deg,
        yaw_deg=norm_pose["yaw_deg"],
        fallback_distance_m=fallback_distance_m,
        depth_relief_scale=depth_relief_scale,
        base_depth_source=base_engine,
    )

    lidar_residual_rmse_m: Optional[float] = None
    if lidar_calibrated and lidar_xy:
        depth_m, lidar_residual_rmse_m = apply_lidar_residual_warp(
            depth_m=depth_m,
            lidar_points_xy=lidar_xy,
            hfov_deg=hfov_deg,
            yaw_deg=norm_pose["yaw_deg"],
        )
        if lidar_residual_rmse_m is not None:
            passes_applied.append("lidar_residual_warp")

    # Pass 4D: Tangent-space PBR normal map baking.
    normal_jpeg_bytes: Optional[bytes] = None
    if bool(cfg["normal_map"]):
        normal_jpeg_bytes = bake_tangent_normal_map(depth_m=depth_m, image_bgr=enhanced_bgr, strength=1.6)
        passes_applied.append("normal_map")

    # Pass 4E: Relief mesh + optional non-shrinking Taubin smoothing.
    use_taubin = bool(cfg["taubin_smooth"])
    built = build_relief_mesh_payload(
        depth_m=depth_m,
        image_bgr=enhanced_bgr,
        pose=norm_pose,
        resolution=resolution,
        hfov_deg=hfov_deg,
        vfov_deg=vfov_deg,
        tear_threshold_ratio=tear_threshold_ratio,
        taubin_smooth=use_taubin,
    )
    if use_taubin:
        passes_applied.append("taubin_smooth")

    mesh = built["mesh"]
    glb_bytes = export_panel_glb(
        positions=mesh["positions"],
        normals=mesh["normals"],
        uvs=mesh["uvs"],
        indices=mesh["indices"],
        jpeg_bytes=enhanced_jpeg_bytes,
        normal_jpeg_bytes=normal_jpeg_bytes,
    )

    sharp_before = float(q_before["sharpness"])
    sharp_after = float(q_after["sharpness"])
    sharp_gain_pct = round(((sharp_after - sharp_before) / max(sharp_before, 1.0)) * 100.0, 1)
    processing_ms = int(round((time.perf_counter() - t0) * 1000.0))

    quality_metrics: Dict[str, Any] = {
        "preset": cfg["quality_preset"],
        "passes_applied": passes_applied,
        "frames_stacked": int(frames_stacked),
        "lidar_sweeps_stacked": int(lidar_sweeps_stacked),
        "sharpness_before": round(sharp_before, 2),
        "sharpness_after": round(sharp_after, 2),
        "sharpness_gain_pct": sharp_gain_pct,
        "contrast_before": round(float(q_before["contrast"]), 2),
        "contrast_after": round(float(q_after["contrast"]), 2),
        "texture_width": int(q_after["width"]),
        "texture_height": int(q_after["height"]),
        "has_normal_map": normal_jpeg_bytes is not None,
        "lidar_residual_rmse_m": lidar_residual_rmse_m,
        "processing_ms": processing_ms,
    }

    result: Dict[str, Any] = {
        "pose": norm_pose,
        "lidar_calibrated": bool(lidar_calibrated),
        "lidar_ray_count": int(ray_count),
        "depth_source": depth_source,
        "mean_distance_m": built["mean_distance_m"],
        "min_distance_m": built["min_distance_m"],
        "max_distance_m": built["max_distance_m"],
        "vertex_count": built["vertex_count"],
        "triangle_count": built["triangle_count"],
        "mesh": mesh,
        "quality_metrics": quality_metrics,
    }
    return result, enhanced_jpeg_bytes, normal_jpeg_bytes, glb_bytes


def reconstruct_wall_panel(
    jpeg_bytes: bytes,
    lidar_points_xy: Optional[Sequence[Tuple[float, float]]] = None,
    pose: Optional[Dict[str, Any]] = None,
    resolution: str = "medium",
    fallback_distance_m: float = 1.8,
    depth_relief_scale: float = 1.0,
    hfov_deg: float = 65.0,
    vfov_deg: float = 50.0,
    tear_threshold_ratio: float = 0.14,
    allow_model_download: bool = True,
    models_dir: Optional[str | Path] = None,
) -> Tuple[Dict[str, Any], bytes]:
    """Run full Stage-1 single-wall 3D reconstruction from JPEG bytes + optional live LD19 rays.

    Args:
        jpeg_bytes: Raw JPEG image bytes captured from PuppyPi camera.
        lidar_points_xy: Optional live 2D LiDAR points ``[(lx, ly), ...]`` (real hardware only).
        pose: 6-DOF pose dictionary ``{x, y, z, yaw_deg, pitch_deg, roll_deg}``.
        resolution: Mesh density preset (``"low"``, ``"medium"``, ``"high"``).
        fallback_distance_m: Reference wall distance in meters if LiDAR rays are unavailable.
        depth_relief_scale: Relief amplitude multiplier around median distance.
        hfov_deg: Camera horizontal FOV in degrees.
        vfov_deg: Camera vertical FOV in degrees.
        tear_threshold_ratio: Depth-step ratio threshold for triangle tear filtering.
        allow_model_download: Whether to download ``depth_anything_v2_vits.onnx`` if absent.
        models_dir: Optional ONNX model cache directory override.

    Returns:
        Tuple ``(result_dict, glb_bytes)`` ready for PostgreSQL storage and JSON serialization.

    Raises:
        ValueError: When ``jpeg_bytes`` cannot be decoded as a valid image.
    """
    arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
    image_bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if image_bgr is None or image_bgr.size == 0:
        raise ValueError("Could not decode camera snapshot as a valid JPEG/PNG image.")

    norm_pose: Dict[str, float] = {
        "x": round(float((pose or {}).get("x", 0.0)), 4),
        "y": round(float((pose or {}).get("y", 0.0)), 4),
        "z": round(float((pose or {}).get("z", 0.22)), 4),
        "yaw_deg": round(float((pose or {}).get("yaw_deg", 0.0)), 2),
        "pitch_deg": round(float((pose or {}).get("pitch_deg", 0.0)), 2),
        "roll_deg": round(float((pose or {}).get("roll_deg", 0.0)), 2),
    }

    rel_depth, base_engine = estimate_relative_depth(
        image_bgr,
        allow_download=allow_model_download,
        models_dir=models_dir,
    )
    depth_m, lidar_calibrated, ray_count, depth_source = calibrate_depth_with_lidar(
        rel_depth=rel_depth,
        lidar_points_xy=lidar_points_xy,
        hfov_deg=hfov_deg,
        yaw_deg=norm_pose["yaw_deg"],
        fallback_distance_m=fallback_distance_m,
        depth_relief_scale=depth_relief_scale,
        base_depth_source=base_engine,
    )
    built = build_relief_mesh_payload(
        depth_m=depth_m,
        image_bgr=image_bgr,
        pose=norm_pose,
        resolution=resolution,
        hfov_deg=hfov_deg,
        vfov_deg=vfov_deg,
        tear_threshold_ratio=tear_threshold_ratio,
    )
    mesh = built["mesh"]
    glb_bytes = export_panel_glb(
        positions=mesh["positions"],
        normals=mesh["normals"],
        uvs=mesh["uvs"],
        indices=mesh["indices"],
        jpeg_bytes=jpeg_bytes,
    )
    result: Dict[str, Any] = {
        "pose": norm_pose,
        "lidar_calibrated": bool(lidar_calibrated),
        "lidar_ray_count": int(ray_count),
        "depth_source": depth_source,
        "mean_distance_m": built["mean_distance_m"],
        "min_distance_m": built["min_distance_m"],
        "max_distance_m": built["max_distance_m"],
        "vertex_count": built["vertex_count"],
        "triangle_count": built["triangle_count"],
        "mesh": mesh,
    }
    return result, glb_bytes
