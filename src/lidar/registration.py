"""Multi-station 2D/3D LiDAR scan registration using small_gicp with SVD ICP fallback."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from sklearn.neighbors import NearestNeighbors

try:
    import small_gicp  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - optional C++ extension
    small_gicp = None


def _apply_transform_2d(points_xy: np.ndarray, dx: float, dy: float, dyaw_rad: float) -> np.ndarray:
    """Apply rigid 2D rotation + translation to an ``(N, 2)`` array."""
    c, s = math.cos(dyaw_rad), math.sin(dyaw_rad)
    rot = np.array([[c, -s], [s, c]], dtype=np.float64)
    return (points_xy @ rot.T) + np.array([dx, dy], dtype=np.float64)


def register_scans_2d(
    source_xy: np.ndarray,
    target_xy: np.ndarray,
    max_iterations: int = 40,
    tolerance: float = 1e-5,
    max_correspondence_m: float = 1.5,
) -> dict[str, Any]:
    """Align a 2D ``source_xy`` scan onto a ``target_xy`` reference scan.

    Uses ``small_gicp`` C++ registration when installed, otherwise falls back to
    a deterministic SVD Point-to-Point ICP implementation.

    Args:
        source_xy: ``(N, 2)`` array of source scan points in meters.
        target_xy: ``(M, 2)`` array of target reference scan points in meters.
        max_iterations: Maximum ICP iterations.
        tolerance: Convergence delta threshold on RMSE.
        max_correspondence_m: Outlier correspondence rejection radius in meters.

    Returns:
        Dictionary containing ``dx_m``, ``dy_m``, ``dyaw_deg``, ``rmse_m``,
        ``converged``, ``engine``, and ``aligned_points``.
    """
    src = np.asarray(source_xy, dtype=np.float64)
    tgt = np.asarray(target_xy, dtype=np.float64)
    if src.ndim != 2 or tgt.ndim != 2 or src.shape[0] < 3 or tgt.shape[0] < 3:
        raise ValueError("Both source_xy and target_xy must contain at least 3 2D points.")

    if small_gicp is not None:  # pragma: no cover - verified when C++ wheel present
        try:
            src3 = np.hstack([src, np.zeros((len(src), 1), dtype=np.float64)])
            tgt3 = np.hstack([tgt, np.zeros((len(tgt), 1), dtype=np.float64)])
            result = small_gicp.align(tgt3, src3, max_correspondence_distance=max_correspondence_m)
            t_mat = np.asarray(result.T_target_source, dtype=np.float64)
            dx = float(t_mat[0, 3])
            dy = float(t_mat[1, 3])
            dyaw_rad = math.atan2(float(t_mat[1, 0]), float(t_mat[0, 0]))
            aligned = _apply_transform_2d(src, dx, dy, dyaw_rad)
            nn = NearestNeighbors(n_neighbors=1).fit(tgt)
            dists, _ = nn.kneighbors(aligned)
            rmse = float(np.sqrt(np.mean(dists ** 2)))
            return {
                "dx_m": round(dx, 4),
                "dy_m": round(dy, 4),
                "dyaw_deg": round(math.degrees(dyaw_rad), 3),
                "rmse_m": round(rmse, 4),
                "converged": bool(result.converged),
                "engine": "small_gicp",
                "aligned_points": aligned.tolist(),
            }
        except Exception:
            pass

    nn = NearestNeighbors(n_neighbors=1).fit(tgt)
    current = src.copy()
    total_rot = np.eye(2, dtype=np.float64)
    total_t = np.zeros(2, dtype=np.float64)
    prev_rmse = float("inf")
    converged = False

    for _ in range(max_iterations):
        dists, indices = nn.kneighbors(current)
        dists = dists.ravel()
        indices = indices.ravel()
        valid = dists <= max_correspondence_m
        if int(np.sum(valid)) < 3:
            break

        p = current[valid]
        q = tgt[indices[valid]]
        p_mean = np.mean(p, axis=0)
        q_mean = np.mean(q, axis=0)
        h_mat = (p - p_mean).T @ (q - q_mean)
        u_mat, _, vt_mat = np.linalg.svd(h_mat)
        rot = vt_mat.T @ u_mat.T
        if np.linalg.det(rot) < 0:
            vt_mat[-1, :] *= -1
            rot = vt_mat.T @ u_mat.T
        trans = q_mean - rot @ p_mean

        current = (current @ rot.T) + trans
        total_rot = rot @ total_rot
        total_t = rot @ total_t + trans

        rmse = float(np.sqrt(np.mean(dists[valid] ** 2)))
        if abs(prev_rmse - rmse) < tolerance:
            converged = True
            prev_rmse = rmse
            break
        prev_rmse = rmse

    dyaw_rad = math.atan2(float(total_rot[1, 0]), float(total_rot[0, 0]))
    return {
        "dx_m": round(float(total_t[0]), 4),
        "dy_m": round(float(total_t[1]), 4),
        "dyaw_deg": round(math.degrees(dyaw_rad), 3),
        "rmse_m": round(float(prev_rmse if math.isfinite(prev_rmse) else 0.0), 4),
        "converged": converged or prev_rmse < 0.05,
        "engine": "svd_icp",
        "aligned_points": [[round(float(x), 4), round(float(y), 4)] for x, y in current],
    }
