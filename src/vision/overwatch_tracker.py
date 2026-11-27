"""N-Ray Weighted Triangulation, 2-Sigma GDOP Ellipses & Cross-View Persistent Re-ID.

Upgrades multi-camera overwatch tracking from simple 2-ray midpoints to:
- Angular-resolution weighted N-ray least-squares 3D triangulation.
- Analytical 2D covariance & 2-sigma uncertainty ellipses + GDOP rating.
- Cross-camera association using 3D ray-skew gating + normalized HSV color histograms.
- Persistent global Track IDs (``TRK-01``, ``TRK-02``, ...) with smooth velocity estimation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np


def compute_hsv_descriptor(frame_bgr: np.ndarray, bbox_norm: Sequence[float]) -> Optional[np.ndarray]:
    """Compute a lightweight L2-normalized HSV color histogram for cross-view Re-ID.

    Args:
        frame_bgr: Decoded BGR camera frame.
        bbox_norm: Normalized bounding box ``[x1, y1, x2, y2]`` in ``[0, 1]``.

    Returns:
        1D float32 normalized histogram vector (24 bins), or ``None`` if crop is empty.
    """
    if frame_bgr is None or frame_bgr.size == 0 or len(bbox_norm) < 4:
        return None
    h, w = frame_bgr.shape[:2]
    x1 = max(0, min(w - 1, int(float(bbox_norm[0]) * w)))
    y1 = max(0, min(h - 1, int(float(bbox_norm[1]) * h)))
    x2 = max(x1 + 1, min(w, int(float(bbox_norm[2]) * w)))
    y2 = max(y1 + 1, min(h, int(float(bbox_norm[3]) * h)))
    crop = frame_bgr[y1:y2, x1:x2]
    if crop.size == 0:
        return None
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    hist_h = cv2.calcHist([hsv], [0], None, [16], [0, 180]).ravel()
    hist_s = cv2.calcHist([hsv], [1], None, [8], [0, 256]).ravel()
    vec = np.concatenate([hist_h, hist_s]).astype(np.float32)
    norm = float(np.linalg.norm(vec))
    if norm < 1e-6:
        return None
    return vec / norm


def hsv_cosine_similarity(a: Optional[np.ndarray], b: Optional[np.ndarray]) -> float:
    """Return cosine similarity in ``[0, 1]`` between two normalized HSV descriptors."""
    if a is None or b is None or a.shape != b.shape:
        return 0.5
    return float(max(0.0, min(1.0, float(np.dot(a, b)))))


def _ray_skew_distance(
    o1: np.ndarray,
    d1: np.ndarray,
    o2: np.ndarray,
    d2: np.ndarray,
) -> Tuple[float, float, float]:
    """Return ``(skew_distance_m, t1, t2)`` between two 3D unit rays."""
    w0 = o1 - o2
    b = float(np.dot(d1, d2))
    d_dot = float(np.dot(d1, w0))
    e_dot = float(np.dot(d2, w0))
    denom = 1.0 - b * b
    if denom < 1e-7:
        t1 = max(0.0, -d_dot)
        p1 = o1 + t1 * d1
        return float(np.linalg.norm(p1 - o2)), t1, 0.0
    t1 = (b * e_dot - d_dot) / denom
    t2 = (e_dot - b * d_dot) / denom
    p1 = o1 + max(0.0, t1) * d1
    p2 = o2 + max(0.0, t2) * d2
    return float(np.linalg.norm(p1 - p2)), t1, t2


def triangulate_n_rays_weighted(rays: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute angular-weighted N-ray least-squares 3D triangulation + 2-sigma GDOP ellipse.

    Each ray entry should contain:
    - ``origin``: 3D origin ``[x, y, z]`` in meters
    - ``direction``: 3D direction vector (normalized internally)
    - ``angular_sigma_rad`` (optional): per-ray angular uncertainty in radians (default ``0.012``)
    - ``camera_id`` (optional): source sensor ID

    Args:
        rays: Sequence of 2+ ray dictionaries.

    Returns:
        Dictionary with ``x, y, z, error_m, confidence, gdop, gdop_rating,
        ellipse_2sigma {semi_major_m, semi_minor_m, angle_deg}, num_rays``.

    Raises:
        ValueError: If fewer than 2 valid rays are supplied.
    """
    valid: List[Tuple[np.ndarray, np.ndarray, float]] = []
    for r in rays:
        o = np.asarray(r["origin"], dtype=np.float64).ravel()[:3]
        d = np.asarray(r["direction"], dtype=np.float64).ravel()[:3]
        n = float(np.linalg.norm(d))
        if n < 1e-9:
            continue
        d = d / n
        sigma = max(0.002, min(0.15, float(r.get("angular_sigma_rad", 0.012))))
        valid.append((o, d, sigma))

    if len(valid) < 2:
        raise ValueError("triangulate_n_rays_weighted requires at least 2 valid rays.")

    # Build weighted normal equations: sum w_i (I - d_i d_i^T) P = sum w_i (I - d_i d_i^T) o_i
    H = np.zeros((3, 3), dtype=np.float64)
    rhs = np.zeros(3, dtype=np.float64)
    H_unit = np.zeros((3, 3), dtype=np.float64)
    eye3 = np.eye(3, dtype=np.float64)

    for o, d, sigma in valid:
        proj = eye3 - np.outer(d, d)
        w = 1.0 / (sigma * sigma)
        H += w * proj
        rhs += w * (proj @ o)
        H_unit += proj

    # Small Tikhonov regularization for near-collinear rays
    reg = 1e-4 * np.trace(H) / 3.0 if np.trace(H) > 0 else 1e-4
    H_reg = H + reg * eye3
    try:
        P = np.linalg.solve(H_reg, rhs)
    except np.linalg.LinAlgError:
        P = np.mean([o for o, _, _ in valid], axis=0)

    # Compute perpendicular residual error and range-scaled covariance
    perp_dists: List[float] = []
    H_metric = np.zeros((3, 3), dtype=np.float64)
    for o, d, sigma in valid:
        v = P - o
        along = max(0.25, float(np.dot(v, d)))
        closest = o + along * d
        perp_dists.append(float(np.linalg.norm(P - closest)))
        pos_sigma = max(0.02, along * sigma)
        proj = eye3 - np.outer(d, d)
        H_metric += (1.0 / (pos_sigma * pos_sigma)) * proj

    err_m = float(np.mean(perp_dists)) if perp_dists else 0.0

    # 2D XY covariance & 2-sigma uncertainty ellipse
    H_xy = H_metric[:2, :2] + 1e-4 * np.eye(2, dtype=np.float64)
    try:
        cov_xy = np.linalg.inv(H_xy)
        eigvals, eigvecs = np.linalg.eigh(cov_xy)
        order = np.argsort(eigvals)[::-1]
        eigvals = np.maximum(1e-6, eigvals[order])
        eigvecs = eigvecs[:, order]
        # 2-sigma (95% confidence ~ sqrt(5.991) = 2.4477, capped to readable tactical bounds)
        semi_major = min(2.5, max(0.03, float(math.sqrt(eigvals[0]) * 2.0)))
        semi_minor = min(2.5, max(0.03, float(math.sqrt(eigvals[1]) * 2.0)))
        angle_deg = math.degrees(math.atan2(float(eigvecs[1, 0]), float(eigvecs[0, 0])))
    except np.linalg.LinAlgError:
        semi_major, semi_minor, angle_deg = 0.35, 0.35, 0.0

    # Dimensionless GDOP from unit-ray geometry in XY
    H_unit_xy = H_unit[:2, :2] + 1e-4 * np.eye(2, dtype=np.float64)
    try:
        gdop_raw = math.sqrt(max(0.0, float(np.trace(np.linalg.inv(H_unit_xy)))))
    except np.linalg.LinAlgError:
        gdop_raw = 9.9
    gdop = round(min(9.9, max(0.7, gdop_raw)), 2)

    if gdop <= 1.6:
        gdop_rating = "OPTIMAL"
    elif gdop <= 2.6:
        gdop_rating = "GOOD"
    elif gdop <= 4.5:
        gdop_rating = "FAIR"
    else:
        gdop_rating = "POOR"

    conf = round(max(0.05, min(1.0, 1.0 / (1.0 + err_m * 2.2 + max(0.0, gdop - 1.5) * 0.15))), 3)

    return {
        "x": round(float(P[0]), 4),
        "y": round(float(P[1]), 4),
        "z": round(float(P[2]), 4),
        "error_m": round(err_m, 4),
        "confidence": conf,
        "gdop": gdop,
        "gdop_rating": gdop_rating,
        "num_rays": len(valid),
        "ellipse_2sigma": {
            "semi_major_m": round(semi_major, 3),
            "semi_minor_m": round(semi_minor, 3),
            "angle_deg": round(angle_deg, 1),
        },
    }


@dataclass
class _Observation:
    """Single-camera ray observation for cross-view fusion."""

    camera_id: str
    label: str
    kind: str
    confidence: float
    origin: np.ndarray
    direction: np.ndarray
    angular_sigma_rad: float
    ground_xy: Optional[Tuple[float, float]]
    bbox_norm: List[float]
    hsv_desc: Optional[np.ndarray]
    timestamp: float


@dataclass
class _GlobalTrack:
    """Persistent multi-camera target track in world BEV coordinates."""

    track_id: str
    label: str
    kind: str
    x: float
    y: float
    z: float
    vx: float = 0.0
    vy: float = 0.0
    confidence: float = 0.5
    error_m: float = 0.15
    gdop: float = 2.0
    gdop_rating: str = "MONO"
    ellipse_2sigma: Dict[str, float] = field(
        default_factory=lambda: {"semi_major_m": 0.25, "semi_minor_m": 0.25, "angle_deg": 0.0}
    )
    cameras: List[str] = field(default_factory=list)
    sightlines: List[Dict[str, Any]] = field(default_factory=list)
    hsv_desc: Optional[np.ndarray] = None
    last_seen: float = 0.0
    hits: int = 1

    def to_dict(self) -> Dict[str, Any]:
        """Serialize track state to a JSON-safe dictionary."""
        return {
            "track_id": self.track_id,
            "label": self.label,
            "kind": self.kind,
            "x": round(self.x, 3),
            "y": round(self.y, 3),
            "z": round(self.z, 3),
            "vx": round(self.vx, 3),
            "vy": round(self.vy, 3),
            "confidence": round(self.confidence, 3),
            "error_m": round(self.error_m, 3),
            "gdop": round(self.gdop, 2),
            "gdop_rating": self.gdop_rating,
            "ellipse_2sigma": dict(self.ellipse_2sigma),
            "cameras": list(self.cameras),
            "sightlines": list(self.sightlines),
            "hits": self.hits,
        }


class CrossViewTargetTracker:
    """Cross-camera epipolar + HSV Re-ID multi-target tracker with persistent ``TRK-*`` IDs."""

    def __init__(self, track_ttl_sec: float = 6.0, obs_ttl_sec: float = 2.0) -> None:
        """Initialize empty observation buffer and track registry."""
        self._track_ttl_sec = max(1.0, float(track_ttl_sec))
        self._obs_ttl_sec = max(0.5, float(obs_ttl_sec))
        self._obs_by_camera: Dict[str, List[_Observation]] = {}
        self._tracks: Dict[str, _GlobalTrack] = {}
        self._next_id = 1

    def update_camera_observations(
        self,
        camera_id: str,
        observations: Sequence[Dict[str, Any]],
        now_mono: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """Ingest latest ray observations for one camera and fuse across all active cameras.

        Args:
            camera_id: Source camera slot ID.
            observations: List of dicts with ``label, kind, confidence, origin, direction,
                angular_sigma_rad, ground_xy, bbox_norm, hsv_desc``.
            now_mono: Optional monotonic timestamp for deterministic testing.

        Returns:
            List of active global track dictionaries sorted by track ID.
        """
        ts = float(now_mono if now_mono is not None else time.monotonic())
        parsed: List[_Observation] = []
        for o in observations:
            origin = np.asarray(o["origin"], dtype=np.float64).ravel()[:3]
            direction = np.asarray(o["direction"], dtype=np.float64).ravel()[:3]
            n = float(np.linalg.norm(direction))
            if n < 1e-9:
                continue
            parsed.append(
                _Observation(
                    camera_id=str(camera_id),
                    label=str(o.get("label") or "object"),
                    kind=str(o.get("kind") or "object"),
                    confidence=float(o.get("confidence", 0.5)),
                    origin=origin,
                    direction=direction / n,
                    angular_sigma_rad=float(o.get("angular_sigma_rad", 0.012)),
                    ground_xy=tuple(o["ground_xy"]) if o.get("ground_xy") is not None else None,
                    bbox_norm=list(o.get("bbox_norm") or [0.4, 0.4, 0.6, 0.6]),
                    hsv_desc=o.get("hsv_desc"),
                    timestamp=ts,
                )
            )
        self._obs_by_camera[str(camera_id)] = parsed

        # Prune stale camera observation lists
        active_obs: List[_Observation] = []
        for cid in list(self._obs_by_camera.keys()):
            fresh = [ob for ob in self._obs_by_camera[cid] if (ts - ob.timestamp) <= self._obs_ttl_sec]
            if fresh:
                self._obs_by_camera[cid] = fresh
                active_obs.extend(fresh)
            else:
                del self._obs_by_camera[cid]

        # Cluster observations across different cameras by label + ray skew + HSV similarity
        clusters: List[List[_Observation]] = []
        for ob in active_obs:
            best_cluster: Optional[List[_Observation]] = None
            best_cost = 1e9
            for cl in clusters:
                # One observation per camera per cluster
                if any(existing.camera_id == ob.camera_id for existing in cl):
                    continue
                if cl[0].label.lower() != ob.label.lower():
                    continue
                # Check ray skew against anchor observation in cluster
                skew, t1, t2 = _ray_skew_distance(cl[0].origin, cl[0].direction, ob.origin, ob.direction)
                if t1 < -0.1 or t2 < -0.1 or skew > 0.55:
                    continue
                sim = hsv_cosine_similarity(cl[0].hsv_desc, ob.hsv_desc)
                cost = skew + (1.0 - sim) * 0.25
                if cost < best_cost:
                    best_cost = cost
                    best_cluster = cl
            if best_cluster is not None:
                best_cluster.append(ob)
            else:
                clusters.append([ob])

        # Convert each cluster into a 3D fused measurement and match to persistent tracks
        fused_measurements: List[Dict[str, Any]] = []
        for cl in clusters:
            if len(cl) >= 2:
                tri = triangulate_n_rays_weighted(
                    [
                        {
                            "camera_id": ob.camera_id,
                            "origin": ob.origin,
                            "direction": ob.direction,
                            "angular_sigma_rad": ob.angular_sigma_rad,
                        }
                        for ob in cl
                    ]
                )
                sightlines = [
                    {
                        "camera_id": ob.camera_id,
                        "from_xy": [round(float(ob.origin[0]), 3), round(float(ob.origin[1]), 3)],
                        "to_xy": [round(float(tri["x"]), 3), round(float(tri["y"]), 3)],
                    }
                    for ob in cl
                ]
                mean_conf = float(np.mean([ob.confidence for ob in cl]))
                fused_measurements.append(
                    {
                        "label": cl[0].label,
                        "kind": cl[0].kind,
                        "x": tri["x"],
                        "y": tri["y"],
                        "z": tri["z"],
                        "confidence": round(min(1.0, (mean_conf + tri["confidence"]) * 0.5), 3),
                        "error_m": tri["error_m"],
                        "gdop": tri["gdop"],
                        "gdop_rating": tri["gdop_rating"],
                        "ellipse_2sigma": tri["ellipse_2sigma"],
                        "cameras": sorted({ob.camera_id for ob in cl}),
                        "sightlines": sightlines,
                        "hsv_desc": cl[0].hsv_desc,
                    }
                )
            else:
                ob = cl[0]
                if ob.ground_xy is None:
                    continue
                gx, gy = float(ob.ground_xy[0]), float(ob.ground_xy[1])
                fused_measurements.append(
                    {
                        "label": ob.label,
                        "kind": ob.kind,
                        "x": round(gx, 3),
                        "y": round(gy, 3),
                        "z": 1.25 if ob.kind == "face" else 0.0,
                        "confidence": round(ob.confidence * 0.82, 3),
                        "error_m": 0.18,
                        "gdop": 4.8,
                        "gdop_rating": "MONO",
                        "ellipse_2sigma": {"semi_major_m": 0.32, "semi_minor_m": 0.16, "angle_deg": 0.0},
                        "cameras": [ob.camera_id],
                        "sightlines": [
                            {
                                "camera_id": ob.camera_id,
                                "from_xy": [round(float(ob.origin[0]), 3), round(float(ob.origin[1]), 3)],
                                "to_xy": [round(gx, 3), round(gy, 3)],
                            }
                        ],
                        "hsv_desc": ob.hsv_desc,
                    }
                )

        # Match fused measurements to existing tracks by nearest XY + label + HSV
        matched_track_ids: set[str] = set()
        for meas in fused_measurements:
            best_tid: Optional[str] = None
            best_dist = 0.85
            for tid, trk in self._tracks.items():
                if tid in matched_track_ids:
                    continue
                if trk.label.lower() != meas["label"].lower():
                    continue
                dist = math.hypot(trk.x - meas["x"], trk.y - meas["y"])
                sim_penalty = (1.0 - hsv_cosine_similarity(trk.hsv_desc, meas["hsv_desc"])) * 0.25
                score = dist + sim_penalty
                if score < best_dist:
                    best_dist = score
                    best_tid = tid

            if best_tid is not None:
                trk = self._tracks[best_tid]
                dt = max(0.05, ts - trk.last_seen)
                alpha = 0.55
                new_x = alpha * meas["x"] + (1.0 - alpha) * trk.x
                new_y = alpha * meas["y"] + (1.0 - alpha) * trk.y
                new_z = alpha * meas["z"] + (1.0 - alpha) * trk.z
                trk.vx = 0.4 * ((new_x - trk.x) / dt) + 0.6 * trk.vx
                trk.vy = 0.4 * ((new_y - trk.y) / dt) + 0.6 * trk.vy
                trk.x, trk.y, trk.z = new_x, new_y, new_z
                trk.confidence = meas["confidence"]
                trk.error_m = meas["error_m"]
                trk.gdop = meas["gdop"]
                trk.gdop_rating = meas["gdop_rating"]
                trk.ellipse_2sigma = meas["ellipse_2sigma"]
                trk.cameras = meas["cameras"]
                trk.sightlines = meas["sightlines"]
                if meas["hsv_desc"] is not None:
                    trk.hsv_desc = meas["hsv_desc"]
                trk.last_seen = ts
                trk.hits += 1
                matched_track_ids.add(best_tid)
            else:
                tid = f"TRK-{self._next_id:02d}"
                self._next_id += 1
                self._tracks[tid] = _GlobalTrack(
                    track_id=tid,
                    label=meas["label"],
                    kind=meas["kind"],
                    x=meas["x"],
                    y=meas["y"],
                    z=meas["z"],
                    confidence=meas["confidence"],
                    error_m=meas["error_m"],
                    gdop=meas["gdop"],
                    gdop_rating=meas["gdop_rating"],
                    ellipse_2sigma=meas["ellipse_2sigma"],
                    cameras=meas["cameras"],
                    sightlines=meas["sightlines"],
                    hsv_desc=meas["hsv_desc"],
                    last_seen=ts,
                    hits=1,
                )
                matched_track_ids.add(tid)

        # Expire stale tracks
        for tid in list(self._tracks.keys()):
            if (ts - self._tracks[tid].last_seen) > self._track_ttl_sec:
                del self._tracks[tid]

        return self.list_tracks(now_mono=ts)

    def list_tracks(self, now_mono: Optional[float] = None) -> List[Dict[str, Any]]:
        """Return all active persistent global tracks."""
        ts = float(now_mono if now_mono is not None else time.monotonic())
        out = [
            trk.to_dict()
            for trk in self._tracks.values()
            if (ts - trk.last_seen) <= self._track_ttl_sec
        ]
        out.sort(key=lambda t: t["track_id"])
        return out
