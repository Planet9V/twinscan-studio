"""Real-Time Moving-Object Tracker: 4-State Constant-Velocity Kalman Filter + Hungarian Association.

Tracks clustered LiDAR objects across consecutive scans in pure NumPy + SciPy
(``scipy.optimize.linear_sum_assignment``) to estimate 2D position, velocity
``(vx, vy)``, speed (m/s), heading (deg), and comet motion trails for 2D/3D radar.
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Sequence, Tuple

import numpy as np
from scipy.optimize import linear_sum_assignment


@dataclass
class _KalmanTrack:
    """Internal 4-state constant-velocity Kalman track ``[x, y, vx, vy]``."""

    track_id: int
    x: np.ndarray  # shape (4,)
    P: np.ndarray  # shape (4, 4)
    last_ts: float
    age: int = 1
    missed: int = 0
    point_count: int = 0
    trail: Deque[Tuple[float, float]] = field(default_factory=lambda: deque(maxlen=16))

    def predict(self, dt: float, process_noise: float = 0.8) -> None:
        """Advance state and covariance by ``dt`` seconds."""
        dt = max(0.01, min(1.0, float(dt)))
        F = np.array(
            [
                [1.0, 0.0, dt, 0.0],
                [0.0, 1.0, 0.0, dt],
                [0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ],
            dtype=np.float64,
        )
        dt2 = dt * dt
        dt3 = dt2 * dt
        dt4 = dt2 * dt2
        q = float(process_noise)
        Q = q * np.array(
            [
                [0.25 * dt4, 0.0, 0.5 * dt3, 0.0],
                [0.0, 0.25 * dt4, 0.0, 0.5 * dt3],
                [0.5 * dt3, 0.0, dt2, 0.0],
                [0.0, 0.5 * dt3, 0.0, dt2],
            ],
            dtype=np.float64,
        )
        self.x = F @ self.x
        self.P = F @ self.P @ F.T + Q

    def update(self, z_xy: np.ndarray, meas_std_m: float = 0.06) -> None:
        """Incorporate a 2D centroid measurement ``[zx, zy]``."""
        H = np.array([[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]], dtype=np.float64)
        R = (meas_std_m * meas_std_m) * np.eye(2, dtype=np.float64)
        y = z_xy - (H @ self.x)
        S = H @ self.P @ H.T + R
        K = self.P @ H.T @ np.linalg.inv(S)
        self.x = self.x + K @ y
        I = np.eye(4, dtype=np.float64)
        self.P = (I - K @ H) @ self.P

    def to_dict(self) -> Dict[str, Any]:
        """Serialize track into JSON-friendly telemetry payload."""
        px, py, vx, vy = [float(v) for v in self.x]
        speed = math.hypot(vx, vy)
        heading_deg = math.degrees(math.atan2(vy, vx)) if speed > 1e-4 else 0.0
        is_moving = bool(speed >= 0.08 and self.age >= 2)
        return {
            "track_id": self.track_id,
            "x": round(px, 3),
            "y": round(py, 3),
            "vx": round(vx, 3),
            "vy": round(vy, 3),
            "speed_mps": round(speed, 3),
            "heading_deg": round(heading_deg, 1),
            "is_moving": is_moving,
            "age": self.age,
            "point_count": self.point_count,
            "trail": [[round(tx, 3), round(ty, 3)] for tx, ty in self.trail],
        }


class MovingObjectTracker:
    """Multi-target LiDAR cluster tracker using 4-state Kalman Filters and Hungarian matching."""

    def __init__(
        self,
        max_match_dist_m: float = 0.65,
        max_missed: int = 5,
        process_noise: float = 0.85,
        meas_std_m: float = 0.05,
    ) -> None:
        """Initialize the moving-object tracker.

        Args:
            max_match_dist_m: Maximum Euclidean gating distance (m) for cluster-to-track association.
            max_missed: Consecutive missed scans before pruning a track.
            process_noise: Acceleration process noise variance for Kalman prediction.
            meas_std_m: Centroid measurement noise standard deviation in meters.
        """
        self.max_match_dist_m = float(max_match_dist_m)
        self.max_missed = int(max_missed)
        self.process_noise = float(process_noise)
        self.meas_std_m = float(meas_std_m)
        self._tracks: List[_KalmanTrack] = []
        self._next_id: int = 1
        self._last_ts: Optional[float] = None

    def reset(self) -> None:
        """Clear all active tracks and reset track ID counter."""
        self._tracks.clear()
        self._next_id = 1
        self._last_ts = None

    @staticmethod
    def _extract_centroid(cluster: Any) -> Tuple[float, float, int]:
        if isinstance(cluster, dict):
            return (
                float(cluster.get("centroid_x", cluster.get("x", 0.0))),
                float(cluster.get("centroid_y", cluster.get("y", 0.0))),
                int(cluster.get("point_count", 0)),
            )
        return (
            float(getattr(cluster, "centroid_x", 0.0)),
            float(getattr(cluster, "centroid_y", 0.0)),
            int(getattr(cluster, "point_count", 0)),
        )

    def update(
        self,
        clusters: Sequence[Any],
        timestamp_s: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """Update active tracks with the latest segmented LiDAR clusters.

        Args:
            clusters: Sequence of ``ObjectCluster`` objects or dicts with ``centroid_x``/``centroid_y``.
            timestamp_s: Monotonic or wall-clock scan timestamp in seconds.

        Returns:
            List of active track dictionaries sorted by ``is_moving`` then ``track_id``.
        """
        now = float(timestamp_s if timestamp_s is not None else time.monotonic())
        dt = (now - self._last_ts) if self._last_ts is not None else 0.1
        if dt <= 0.0:
            dt = 0.1
        self._last_ts = now

        # 1. Predict all existing tracks forward by dynamic dt
        for trk in self._tracks:
            trk.predict(dt, process_noise=self.process_noise)

        measurements = [self._extract_centroid(c) for c in clusters]
        matched_tracks: set[int] = set()
        matched_meas: set[int] = set()

        # 2. Optimal Hungarian assignment on pairwise Euclidean distance matrix
        if self._tracks and measurements:
            n_t = len(self._tracks)
            n_m = len(measurements)
            cost = np.full((n_t, n_m), 1e6, dtype=np.float64)
            for ti, trk in enumerate(self._tracks):
                tx, ty = float(trk.x[0]), float(trk.x[1])
                for mi, (mx, my, _) in enumerate(measurements):
                    d = math.hypot(mx - tx, my - ty)
                    if d <= self.max_match_dist_m:
                        cost[ti, mi] = d
            row_ind, col_ind = linear_sum_assignment(cost)
            for ti, mi in zip(row_ind, col_ind):
                if cost[ti, mi] <= self.max_match_dist_m:
                    trk = self._tracks[ti]
                    mx, my, pcnt = measurements[mi]
                    trk.update(np.array([mx, my], dtype=np.float64), meas_std_m=self.meas_std_m)
                    trk.last_ts = now
                    trk.age += 1
                    trk.missed = 0
                    trk.point_count = pcnt
                    trk.trail.append((float(trk.x[0]), float(trk.x[1])))
                    matched_tracks.add(ti)
                    matched_meas.add(mi)

        # 3. Age unmatched tracks & prune stale ones
        surviving: List[_KalmanTrack] = []
        for ti, trk in enumerate(self._tracks):
            if ti not in matched_tracks:
                trk.missed += 1
            if trk.missed <= self.max_missed:
                surviving.append(trk)
        self._tracks = surviving

        # 4. Spawn new tracks for unmatched clusters
        for mi, (mx, my, pcnt) in enumerate(measurements):
            if mi in matched_meas:
                continue
            x0 = np.array([mx, my, 0.0, 0.0], dtype=np.float64)
            P0 = np.diag([0.05, 0.05, 1.5, 1.5]).astype(np.float64)
            trk = _KalmanTrack(
                track_id=self._next_id,
                x=x0,
                P=P0,
                last_ts=now,
                age=1,
                missed=0,
                point_count=pcnt,
            )
            trk.trail.append((mx, my))
            self._next_id += 1
            self._tracks.append(trk)

        out = [trk.to_dict() for trk in self._tracks if trk.missed == 0]
        out.sort(key=lambda t: (not t["is_moving"], -t["speed_mps"], t["track_id"]))
        return out
