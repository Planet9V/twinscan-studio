"""5-Pass Composite Enhancement Engine for 3D Real-Room Fusion.

Provides zero-extra-dependency computer vision and geometry refinement passes built on
OpenCV, NumPy, and SciPy:
- Pass 1: Temporal burst camera stacking with ``cv2.phaseCorrelate`` alignment and blur rejection.
- Pass 2: Gray-world white balance, LAB CLAHE, bilateral/NLM denoising, edge-masked sharpening,
  and optional 2x Lanczos4 super-resolution.
- Pass 3: Multi-sweep LD19 polar bucketing (0.5 deg bins) and 1D bilateral angular denoising.
- Pass 4: Pure ``cv2.boxFilter`` O(N) He et al. RGB-guided depth filtering, LiDAR column residual
  warping, tangent-space PBR normal map baking, and non-shrinking Taubin mesh polishing.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

QUALITY_PRESETS: Dict[str, Dict[str, Any]] = {
    "fast": {
        "quality_preset": "fast",
        "burst_frames": 1,
        "lidar_sweeps": 1,
        "clahe_sharpen": False,
        "upscale_2x": False,
        "flip_tta": False,
        "guided_depth": False,
        "normal_map": False,
        "taubin_smooth": False,
        "ultra_nlm": False,
    },
    "balanced": {
        "quality_preset": "balanced",
        "burst_frames": 3,
        "lidar_sweeps": 3,
        "clahe_sharpen": True,
        "upscale_2x": False,
        "flip_tta": True,
        "guided_depth": True,
        "normal_map": True,
        "taubin_smooth": True,
        "ultra_nlm": False,
    },
    "studio_ultra": {
        "quality_preset": "studio_ultra",
        "burst_frames": 5,
        "lidar_sweeps": 5,
        "clahe_sharpen": True,
        "upscale_2x": True,
        "flip_tta": True,
        "guided_depth": True,
        "normal_map": True,
        "taubin_smooth": True,
        "ultra_nlm": True,
    },
}


def resolve_enhance_preset(
    quality_preset: str = "balanced",
    overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Resolve enhancement preset defaults merged with optional per-pass overrides.

    Args:
        quality_preset: Preset name (``"fast"``, ``"balanced"``, or ``"studio_ultra"``).
        overrides: Optional dictionary of explicit pass overrides. ``None`` values are ignored.

    Returns:
        Normalized configuration dictionary controlling all 5 composite enhancement passes.
    """
    key = str(quality_preset or "balanced").strip().lower()
    if key not in QUALITY_PRESETS:
        key = "balanced"
    cfg = dict(QUALITY_PRESETS[key])
    if overrides:
        for k in ("clahe_sharpen", "upscale_2x", "flip_tta", "guided_depth", "normal_map", "taubin_smooth", "ultra_nlm"):
            if overrides.get(k) is not None:
                cfg[k] = bool(overrides[k])
        if overrides.get("burst_frames") is not None:
            cfg["burst_frames"] = int(max(1, min(5, int(overrides["burst_frames"]))))
        if overrides.get("lidar_sweeps") is not None:
            cfg["lidar_sweeps"] = int(max(1, min(5, int(overrides["lidar_sweeps"]))))
    return cfg


def measure_image_quality(
    image_bgr: np.ndarray,
    ref_shape: Optional[Tuple[int, int]] = None,
) -> Dict[str, float]:
    """Measure objective sharpness (Laplacian variance) and RMS luminance contrast.

    Args:
        image_bgr: Input BGR image array of shape ``(H, W, 3)``.
        ref_shape: Optional ``(ref_h, ref_w)`` used to normalize spatial frequency scale
            when comparing sharpness before and after 2x upscaling (while ``width`` and
            ``height`` still report the true dimensions of ``image_bgr``).

    Returns:
        Dictionary with ``sharpness``, ``contrast``, ``width``, and ``height``.
    """
    if image_bgr is None or image_bgr.size == 0:
        return {"sharpness": 0.0, "contrast": 0.0, "width": 0, "height": 0}
    h, w = image_bgr.shape[:2]
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY) if image_bgr.ndim == 3 else image_bgr
    eval_gray = gray
    if ref_shape is not None and (int(ref_shape[0]), int(ref_shape[1])) != (h, w):
        eval_gray = cv2.resize(
            gray,
            (int(ref_shape[1]), int(ref_shape[0])),
            interpolation=cv2.INTER_AREA if h > int(ref_shape[0]) else cv2.INTER_LINEAR,
        )
    gray_f = eval_gray.astype(np.float64)
    sharpness = float(cv2.Laplacian(gray_f, cv2.CV_64F).var())
    contrast = float(np.std(gray_f))
    return {
        "sharpness": round(sharpness, 2),
        "contrast": round(contrast, 2),
        "width": int(w),
        "height": int(h),
    }


def stack_camera_burst(frames_bgr: Sequence[np.ndarray]) -> Tuple[np.ndarray, int]:
    """Align and temporally stack a camera burst to suppress sensor noise without motion smear.

    Drops empty frames, discards the lowest-sharpness frame when ``len >= 4``, aligns
    remaining frames to the sharpest reference via ``cv2.phaseCorrelate`` + ``cv2.warpAffine``
    (clamping shift to ``<= 8 px``), and computes a temporal median / trimmed blend.

    Args:
        frames_bgr: Sequence of BGR ``uint8`` frames captured in rapid succession.

    Returns:
        Tuple ``(stacked_bgr, frames_used)``.

    Raises:
        ValueError: When no valid non-empty frames are provided.
    """
    valid: List[np.ndarray] = [
        f for f in frames_bgr if f is not None and isinstance(f, np.ndarray) and f.ndim == 3 and f.size > 0
    ]
    if not valid:
        raise ValueError("stack_camera_burst requires at least one non-empty BGR frame.")
    if len(valid) == 1:
        return valid[0].copy(), 1

    ref_h, ref_w = valid[0].shape[:2]
    sized = [
        f if f.shape[:2] == (ref_h, ref_w) else cv2.resize(f, (ref_w, ref_h), interpolation=cv2.INTER_LINEAR)
        for f in valid
    ]

    scores = [measure_image_quality(f)["sharpness"] for f in sized]
    order = sorted(range(len(sized)), key=lambda idx: scores[idx], reverse=True)
    if len(order) >= 4:
        order = order[:-1]

    ref_idx = order[0]
    ref_frame = sized[ref_idx]
    ref_gray = cv2.cvtColor(ref_frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
    hann = cv2.createHanningWindow((ref_w, ref_h), cv2.CV_32F)

    aligned: List[np.ndarray] = [ref_frame]
    for idx in order[1:]:
        cand = sized[idx]
        cand_gray = cv2.cvtColor(cand, cv2.COLOR_BGR2GRAY).astype(np.float32)
        try:
            (dx, dy), _ = cv2.phaseCorrelate(cand_gray, ref_gray, hann)
            dx = float(np.clip(dx, -8.0, 8.0))
            dy = float(np.clip(dy, -8.0, 8.0))
            if abs(dx) > 0.05 or abs(dy) > 0.05:
                mat = np.array([[1.0, 0.0, dx], [0.0, 1.0, dy]], dtype=np.float32)
                warped = cv2.warpAffine(
                    cand,
                    mat,
                    (ref_w, ref_h),
                    flags=cv2.INTER_LINEAR,
                    borderMode=cv2.BORDER_REPLICATE,
                )
            else:
                warped = cand
        except Exception:
            warped = cand
        aligned.append(warped)

    stack = np.stack([f.astype(np.float32) for f in aligned], axis=0)
    if len(aligned) >= 3:
        merged = np.median(stack, axis=0)
    else:
        merged = np.mean(stack, axis=0)
    return np.clip(merged, 0.0, 255.0).astype(np.uint8), len(aligned)


def enhance_camera_image(
    image_bgr: np.ndarray,
    clahe_sharpen: bool = True,
    upscale_2x: bool = False,
    ultra_nlm: bool = False,
) -> Tuple[np.ndarray, List[str]]:
    """Apply photometric enhancement, edge-preserving denoise, sharpening, and optional 2x upscale.

    Args:
        image_bgr: Input BGR ``uint8`` image.
        clahe_sharpen: Enable gray-world WB (35% blend), LAB CLAHE, edge-preserving denoise,
            and edge-masked unsharp + subtle ``cv2.detailEnhance``.
        upscale_2x: Upscale 2x with ``INTER_LANCZOS4`` (capped to 1600px wide) + micro-sharpening.
        ultra_nlm: Use ``cv2.fastNlMeansDenoisingColored`` instead of bilateral filter when
            ``clahe_sharpen`` is enabled.

    Returns:
        Tuple ``(enhanced_bgr, passes_applied)``.
    """
    img = image_bgr.copy()
    passes: List[str] = []

    if clahe_sharpen:
        # 1. Gentle gray-world white balance blended 35% to keep natural room color faithful.
        f_img = img.astype(np.float32)
        ch_means = np.mean(f_img.reshape(-1, 3), axis=0)
        avg_mean = float(np.mean(ch_means))
        gains = np.clip(avg_mean / np.maximum(ch_means, 1.0), 0.80, 1.25).astype(np.float32)
        wb = np.clip(f_img * gains.reshape(1, 1, 3), 0.0, 255.0)
        img = np.clip(0.65 * f_img + 0.35 * wb, 0.0, 255.0).astype(np.uint8)

        # 2. LAB luminance CLAHE.
        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
        l_ch, a_ch, b_ch = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        l_eq = clahe.apply(l_ch)
        img = cv2.cvtColor(cv2.merge([l_eq, a_ch, b_ch]), cv2.COLOR_LAB2BGR)

        # 3. Edge-preserving denoise.
        if ultra_nlm:
            img = cv2.fastNlMeansDenoisingColored(
                img,
                None,
                h=5,
                hColor=5,
                templateWindowSize=7,
                searchWindowSize=15,
            )
            passes.append("nlm_denoise")
        else:
            img = cv2.bilateralFilter(img, d=5, sigmaColor=24.0, sigmaSpace=24.0)
            passes.append("bilateral_denoise")

        # 4. Edge-masked unsharp mask + subtle detailEnhance (25% blend).
        gray_f = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
        gx = cv2.Sobel(gray_f, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(gray_f, cv2.CV_32F, 0, 1, ksize=3)
        grad = np.hypot(gx, gy)
        p95 = max(float(np.percentile(grad, 95)), 1e-3)
        edge_mask = np.clip(grad / p95, 0.2, 1.0)[:, :, None]

        img_f = img.astype(np.float32)
        blurred = cv2.GaussianBlur(img_f, (0, 0), sigmaX=1.2)
        sharpened = np.clip(img_f + (1.15 * edge_mask) * (img_f - blurred), 0.0, 255.0).astype(np.uint8)

        try:
            detailed = cv2.detailEnhance(sharpened, sigma_s=8, sigma_r=0.10)
            img = cv2.addWeighted(sharpened, 0.75, detailed, 0.25, 0.0)
        except Exception:
            img = sharpened
        passes.append("clahe_sharpen")

    if upscale_2x:
        h, w = img.shape[:2]
        target_w = min(1600, max(w, int(round(w * 2.0))))
        scale = target_w / max(1, w)
        target_h = max(h, int(round(h * scale)))
        up = cv2.resize(img, (target_w, target_h), interpolation=cv2.INTER_LANCZOS4)
        up_f = up.astype(np.float32)
        blur_u = cv2.GaussianBlur(up_f, (0, 0), sigmaX=0.9)
        img = np.clip(up_f + 0.55 * (up_f - blur_u), 0.0, 255.0).astype(np.uint8)
        passes.append("upscale_2x")

    return img, passes


def refine_lidar_sweeps(
    sweeps_xy: Sequence[Sequence[Tuple[float, float]]],
) -> Tuple[List[Tuple[float, float]], int]:
    """Fuse multiple 2D LiDAR sweeps into 0.5-deg polar bins with 1D edge-preserving bilateral filtering.

    Args:
        sweeps_xy: Sequence of LiDAR sweeps, each containing ``(lx, ly)`` 2D meter tuples.

    Returns:
        Tuple ``(denoised_points_xy, sweeps_stacked)``.
    """
    non_empty = [sw for sw in sweeps_xy if sw]
    if not non_empty:
        return [], 0

    num_bins = 720  # 0.5 degree buckets
    bin_ranges: List[List[float]] = [[] for _ in range(num_bins)]
    bin_angles: List[List[float]] = [[] for _ in range(num_bins)]

    for sweep in non_empty:
        for pt in sweep:
            if len(pt) < 2:
                continue
            lx, ly = float(pt[0]), float(pt[1])
            if not (math.isfinite(lx) and math.isfinite(ly)):
                continue
            r = math.hypot(lx, ly)
            if r < 0.15 or r > 12.0:
                continue
            ang_deg = math.degrees(math.atan2(ly, lx)) % 360.0
            b_idx = int(ang_deg * 2.0) % num_bins
            bin_ranges[b_idx].append(r)
            bin_angles[b_idx].append(ang_deg)

    # Trimmed median per polar bin.
    med_r = np.full(num_bins, np.nan, dtype=np.float64)
    med_ang = np.full(num_bins, np.nan, dtype=np.float64)
    for b_idx in range(num_bins):
        vals = bin_ranges[b_idx]
        if not vals:
            continue
        arr = np.asarray(vals, dtype=np.float64)
        m = float(np.median(arr))
        if len(arr) >= 3:
            mad = max(1.4826 * float(np.median(np.abs(arr - m))), 0.02)
            inliers = arr[np.abs(arr - m) <= 2.0 * mad]
            if len(inliers) > 0:
                m = float(np.median(inliers))
        med_r[b_idx] = m
        # Circularly safe mean angle inside this 0.5 deg bucket.
        med_ang[b_idx] = float(np.median(bin_angles[b_idx]))

    # 1D edge-preserving bilateral filter across adjacent polar bins.
    sigma_space = 1.5
    sigma_range = 0.06
    inv_2ss = 1.0 / (2.0 * sigma_space * sigma_space)
    inv_2sr = 1.0 / (2.0 * sigma_range * sigma_range)

    out_points: List[Tuple[float, float]] = []
    for b_idx in range(num_bins):
        r0 = med_r[b_idx]
        if not math.isfinite(r0):
            continue
        w_sum = 0.0
        r_sum = 0.0
        for delta in range(-4, 5):
            nb = (b_idx + delta) % num_bins
            rn = med_r[nb]
            if not math.isfinite(rn):
                continue
            ws = math.exp(-(delta * delta) * inv_2ss)
            dr = rn - r0
            wr = math.exp(-(dr * dr) * inv_2sr)
            wt = ws * wr
            w_sum += wt
            r_sum += wt * rn
        r_filt = r_sum / w_sum if w_sum > 1e-12 else r0
        rad = math.radians(float(med_ang[b_idx]))
        out_points.append((round(r_filt * math.cos(rad), 4), round(r_filt * math.sin(rad), 4)))

    return out_points, len(non_empty)


def guided_filter_depth(
    guide_gray: np.ndarray,
    depth: np.ndarray,
    radius: int = 8,
    eps: float = 1e-4,
) -> np.ndarray:
    """Snap depth discontinuities cleanly to RGB edges using the O(N) He et al. guided filter.

    Implemented purely with ``cv2.boxFilter`` (zero ``opencv-contrib`` / ``ximgproc`` dependency).

    Args:
        guide_gray: Single-channel guidance image (``uint8`` or ``float32``) or 3-channel BGR image.
        depth: 2D depth map ``(H, W)`` to filter.
        radius: Box filter half-window radius in pixels.
        eps: Regularization epsilon controlling edge preservation.

    Returns:
        Edge-aligned ``float32`` depth map of shape matching ``depth``.
    """
    p = np.asarray(depth, dtype=np.float32)
    h, w = p.shape[:2]

    if guide_gray.ndim == 3:
        g = cv2.cvtColor(guide_gray, cv2.COLOR_BGR2GRAY)
    else:
        g = guide_gray
    if g.shape[:2] != (h, w):
        g = cv2.resize(g, (w, h), interpolation=cv2.INTER_AREA if g.shape[0] > h else cv2.INTER_LINEAR)

    guide = g.astype(np.float32)
    if float(guide.max()) > 1.5:
        guide = guide / 255.0

    ksize = (2 * max(1, int(radius)) + 1, 2 * max(1, int(radius)) + 1)
    mean_i = cv2.boxFilter(guide, cv2.CV_32F, ksize, borderType=cv2.BORDER_REFLECT)
    mean_p = cv2.boxFilter(p, cv2.CV_32F, ksize, borderType=cv2.BORDER_REFLECT)
    corr_i = cv2.boxFilter(guide * guide, cv2.CV_32F, ksize, borderType=cv2.BORDER_REFLECT)
    corr_ip = cv2.boxFilter(guide * p, cv2.CV_32F, ksize, borderType=cv2.BORDER_REFLECT)

    var_i = np.maximum(corr_i - mean_i * mean_i, 0.0)
    cov_ip = corr_ip - mean_i * mean_p

    a = cov_ip / (var_i + float(eps))
    b = mean_p - a * mean_i

    mean_a = cv2.boxFilter(a, cv2.CV_32F, ksize, borderType=cv2.BORDER_REFLECT)
    mean_b = cv2.boxFilter(b, cv2.CV_32F, ksize, borderType=cv2.BORDER_REFLECT)

    filtered = mean_a * guide + mean_b
    p_min = float(np.min(p))
    p_max = float(np.max(p))
    return np.clip(filtered, p_min, p_max).astype(np.float32)


def apply_lidar_residual_warp(
    depth_m: np.ndarray,
    lidar_points_xy: Optional[Sequence[Tuple[float, float]]],
    hfov_deg: float = 65.0,
    yaw_deg: float = 0.0,
) -> Tuple[np.ndarray, Optional[float]]:
    """Warp a calibrated metric depth map horizontally toward live LiDAR ray residuals.

    Projects in-FOV LiDAR rays to image columns, computes median residual
    ``delta_z(u) = z_lidar - z_pred_band``, smooths ``delta_z(u)`` across columns,
    warps ``depth_m`` toward ground-truth LiDAR geometry, and returns the post-warp RMSE.

    Args:
        depth_m: Calibrated metric depth map ``(H, W)`` in meters.
        lidar_points_xy: Optional sequence of ``(lx, ly)`` 2D LiDAR points in meters.
        hfov_deg: Camera horizontal FOV in degrees.
        yaw_deg: Camera yaw heading in degrees.

    Returns:
        Tuple ``(warped_depth_m, lidar_residual_rmse_m)``.
    """
    dm = np.asarray(depth_m, dtype=np.float32)
    if not lidar_points_xy:
        return dm, None

    h, w = dm.shape[:2]
    half_fov_rad = math.radians(max(10.0, min(160.0, float(hfov_deg))) / 2.0)
    fx = 0.5 / math.tan(half_fov_rad)
    yaw_rad = math.radians(float(yaw_deg))
    cos_y, sin_y = math.cos(yaw_rad), math.sin(yaw_rad)

    band_r0 = max(0, int(round(0.38 * h)))
    band_r1 = min(h, max(band_r0 + 1, int(round(0.62 * h))))

    col_residuals: Dict[int, List[float]] = {}
    ray_samples: List[Tuple[int, float]] = []

    for pt in lidar_points_xy:
        if len(pt) < 2:
            continue
        lx, ly = float(pt[0]), float(pt[1])
        if not (math.isfinite(lx) and math.isfinite(ly)):
            continue
        dist = math.hypot(lx, ly)
        if dist < 0.25 or dist > 8.0:
            continue
        forward = -sin_y * lx + cos_y * ly
        right = cos_y * lx + sin_y * ly
        if forward <= 0.05 or abs(math.atan2(right, forward)) > half_fov_rad:
            continue
        u = 0.5 + (right / forward) * fx
        col = int(round(u * (w - 1)))
        if 0 <= col < w:
            pred = float(np.median(dm[band_r0:band_r1, col]))
            col_residuals.setdefault(col, []).append(forward - pred)
            ray_samples.append((col, forward))

    if len(ray_samples) < 6 or len(col_residuals) < 3:
        return dm, None

    cols_sorted = sorted(col_residuals.keys())
    deltas_sorted = [float(np.median(col_residuals[c])) for c in cols_sorted]

    # Reject gross residual outliers (> 2.5 MAD).
    d_arr = np.asarray(deltas_sorted, dtype=np.float64)
    med_d = float(np.median(d_arr))
    mad_d = max(1.4826 * float(np.median(np.abs(d_arr - med_d))), 0.05)
    keep = np.abs(d_arr - med_d) <= (2.5 * mad_d)
    if int(np.sum(keep)) >= 3:
        cols_arr = np.asarray(cols_sorted, dtype=np.float64)[keep]
        d_arr = d_arr[keep]
    else:
        cols_arr = np.asarray(cols_sorted, dtype=np.float64)

    all_cols = np.arange(w, dtype=np.float64)
    interp_delta = np.interp(all_cols, cols_arr, d_arr).astype(np.float32)

    sigma_cols = max(1.5, w * 0.02)
    k_w = max(3, int(round(sigma_cols * 4.0)) | 1)
    smooth_delta = cv2.GaussianBlur(interp_delta.reshape(1, w), (k_w, 1), sigmaX=sigma_cols).ravel()
    smooth_delta = np.clip(smooth_delta, -1.5, 1.5)

    warped = np.clip(dm + smooth_delta[None, :], 0.25, 8.0).astype(np.float32)

    sq_errs = [
        (float(np.median(warped[band_r0:band_r1, col])) - z_true) ** 2
        for col, z_true in ray_samples
    ]
    rmse = math.sqrt(float(np.mean(sq_errs))) if sq_errs else 0.0
    return warped, round(rmse, 4)


def bake_tangent_normal_map(
    depth_m: np.ndarray,
    image_bgr: np.ndarray,
    strength: float = 1.6,
) -> bytes:
    """Bake a tangent-space RGB PBR normal map from metric depth + fine luminance micro-relief.

    Args:
        depth_m: Metric depth map ``(H, W)`` in meters.
        image_bgr: Enhanced BGR texture image defining output normal map resolution.
        strength: Tangent-space gradient relief multiplier (default ``1.6``).

    Returns:
        Encoded JPEG bytes (quality 95) of the tangent-space normal map.
    """
    h, w = image_bgr.shape[:2]
    dm = cv2.resize(
        np.asarray(depth_m, dtype=np.float32),
        (w, h),
        interpolation=cv2.INTER_CUBIC,
    )
    d_lo = float(np.percentile(dm, 2))
    d_hi = float(np.percentile(dm, 98))
    if d_hi - d_lo < 1e-5:
        norm_depth = np.full((h, w), 0.5, dtype=np.float32)
    else:
        norm_depth = np.clip((dm - d_lo) / (d_hi - d_lo), 0.0, 1.0)

    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    smooth_gray = cv2.GaussianBlur(gray, (3, 3), 0)

    # Combine macro depth relief (78%) with fine surface luminance micro-detail (22%).
    height_field = (0.78 * (1.0 - norm_depth) + 0.22 * smooth_gray).astype(np.float32)

    dx = cv2.Sobel(height_field, cv2.CV_32F, 1, 0, ksize=3) * float(strength)
    dy = cv2.Sobel(height_field, cv2.CV_32F, 0, 1, ksize=3) * float(strength)

    # OpenGL/Three.js/glTF tangent space: +X right, +Y up (invert image dy), +Z outward.
    nx = -dx
    ny = dy
    nz = np.ones_like(nx, dtype=np.float32)
    inv_len = 1.0 / np.maximum(np.sqrt(nx * nx + ny * ny + nz * nz), 1e-6)
    nx *= inv_len
    ny *= inv_len
    nz *= inv_len

    rgb = np.stack(
        [
            np.clip((nx * 0.5 + 0.5) * 255.0, 0.0, 255.0),
            np.clip((ny * 0.5 + 0.5) * 255.0, 0.0, 255.0),
            np.clip((nz * 0.5 + 0.5) * 255.0, 0.0, 255.0),
        ],
        axis=-1,
    ).astype(np.uint8)
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
    if not ok:
        raise ValueError("Failed to encode tangent-space normal map JPEG.")
    return bytes(buf)


def taubin_smooth_mesh(
    positions: Sequence[float],
    indices: Sequence[int],
    grid_w: int,
    grid_h: int,
    iterations: int = 2,
    lam: float = 0.45,
    mu: float = -0.47,
) -> List[float]:
    """Apply non-shrinking Taubin smoothing to interior vertices belonging to intact quads.

    Tear-boundary and perimeter border vertices remain completely locked so object silhouettes
    stay crisp while stair-step quantization jitter on smooth surfaces is removed.

    Args:
        positions: Flat XYZ vertex coordinates (length ``3 * grid_w * grid_h``).
        indices: Flat triangle vertex index list (length ``3 * M``).
        grid_w: Grid column count.
        grid_h: Grid row count.
        iterations: Number of ``(lambda, mu)`` Taubin smoothing cycles.
        lam: Positive forward Laplacian smoothing factor.
        mu: Negative reverse un-shrinking factor (typically slightly smaller magnitude than ``-lam``).

    Returns:
        Smoothed flat XYZ coordinate list rounded to 4 decimal places.
    """
    n_verts = int(grid_w) * int(grid_h)
    verts = np.asarray(positions, dtype=np.float64).reshape(-1, 3).copy()
    if verts.shape[0] != n_verts or grid_w < 3 or grid_h < 3 or len(indices) == 0:
        return [round(float(v), 4) for v in verts.ravel()]

    tris = np.asarray(indices, dtype=np.int32).reshape(-1, 3)
    # Identify complete non-tear quads: each quad (r, c) spans rows [r, r+1] and cols [c, c+1].
    tri_rows = tris // grid_w
    tri_cols = tris % grid_w
    q_r = np.min(tri_rows, axis=1)
    q_c = np.min(tri_cols, axis=1)
    valid_q = (q_r >= 0) & (q_r < grid_h - 1) & (q_c >= 0) & (q_c < grid_w - 1)

    quad_counts = np.zeros((grid_h - 1, grid_w - 1), dtype=np.int32)
    np.add.at(quad_counts, (q_r[valid_q], q_c[valid_q]), 1)
    intact_quad = quad_counts >= 2

    # An interior vertex (r, c) is smoothable iff all 4 incident quads are intact (no tear edge).
    smooth_mask = np.zeros((grid_h, grid_w), dtype=bool)
    smooth_mask[1:-1, 1:-1] = (
        intact_quad[:-1, :-1]
        & intact_quad[:-1, 1:]
        & intact_quad[1:, :-1]
        & intact_quad[1:, 1:]
    )

    if not np.any(smooth_mask):
        return [round(float(v), 4) for v in verts.ravel()]

    grid_xyz = verts.reshape(grid_h, grid_w, 3)
    mask_3d = smooth_mask[:, :, None]

    for _ in range(max(1, int(iterations))):
        for factor in (float(lam), float(mu)):
            avg = 0.25 * (
                grid_xyz[:-2, 1:-1, :]
                + grid_xyz[2:, 1:-1, :]
                + grid_xyz[1:-1, :-2, :]
                + grid_xyz[1:-1, 2:, :]
            )
            inner_mask = mask_3d[1:-1, 1:-1, :]
            grid_xyz[1:-1, 1:-1, :] = np.where(
                inner_mask,
                grid_xyz[1:-1, 1:-1, :] + factor * (avg - grid_xyz[1:-1, 1:-1, :]),
                grid_xyz[1:-1, 1:-1, :],
            )

    return [round(float(v), 4) for v in grid_xyz.ravel()]
