"""Log-odds 2D occupancy grid mapping and temporal physical change detection.

Tracks room occupancy probability across scans and diffs live returns against a
captured baseline map to detect added, moved, or removed physical equipment.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Sequence

import numpy as np
from sklearn.cluster import DBSCAN

from src.lidar.ld19_parser import LidarPoint


@dataclass(frozen=True)
class PhysicalChangeAnomaly:
    """Detected spatial change between a baseline room scan and live LiDAR scan.

    Attributes:
        anomaly_type: ``"added"`` (newly occupied space) or ``"removed"`` (vacated baseline space).
        centroid_x: Center X coordinate in meters.
        centroid_y: Center Y coordinate in meters.
        area_m2: Approximate changed footprint area in square meters.
        cell_count: Number of grid cells contributing to this anomaly.
        severity: ``"critical"`` or ``"warning"``.
    """

    anomaly_type: str
    centroid_x: float
    centroid_y: float
    area_m2: float
    cell_count: int
    severity: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize anomaly to a JSON-ready dictionary."""
        return {
            "anomaly_type": self.anomaly_type,
            "centroid_x": round(self.centroid_x, 4),
            "centroid_y": round(self.centroid_y, 4),
            "area_m2": round(self.area_m2, 4),
            "cell_count": self.cell_count,
            "severity": self.severity,
        }


class LogOddsOccupancyGrid:
    """2D probabilistic log-odds occupancy grid with baseline snapshot diffing."""

    def __init__(
        self,
        size_m: float = 16.0,
        resolution_m: float = 0.08,
        l_occ: float = 0.85,
        l_free: float = -0.4,
        l_min: float = -4.0,
        l_max: float = 5.0,
    ) -> None:
        """Initialize a centered square occupancy grid.

        Args:
            size_m: Total width and height of the grid in meters.
            resolution_m: Edge length of each cell in meters.
            l_occ: Log-odds increment for hit cells.
            l_free: Log-odds decrement for free cells along rays.
            l_min: Minimum log-odds clamp.
            l_max: Maximum log-odds clamp.
        """
        self.size_m = size_m
        self.resolution_m = resolution_m
        self.dim = int(round(size_m / resolution_m))
        self.half_m = size_m / 2.0
        self.l_occ = l_occ
        self.l_free = l_free
        self.l_min = l_min
        self.l_max = l_max
        self.grid = np.zeros((self.dim, self.dim), dtype=np.float32)
        self.baseline: Optional[np.ndarray] = None

    def world_to_cell(self, x: float, y: float) -> Optional[tuple[int, int]]:
        """Convert world meters ``(x, y)`` to grid ``(col, row)`` indices.

        Args:
            x: World X in meters.
            y: World Y in meters.

        Returns:
            Tuple ``(col, row)`` if within grid bounds, otherwise ``None``.
        """
        col = int((x + self.half_m) / self.resolution_m)
        row = int((y + self.half_m) / self.resolution_m)
        if 0 <= col < self.dim and 0 <= row < self.dim:
            return col, row
        return None

    def cell_to_world(self, col: int, row: int) -> tuple[float, float]:
        """Convert grid cell ``(col, row)`` back to cell-center world meters."""
        x = (col + 0.5) * self.resolution_m - self.half_m
        y = (row + 0.5) * self.resolution_m - self.half_m
        return x, y

    def update(self, points: Sequence[LidarPoint], origin: tuple[float, float] = (0.0, 0.0)) -> None:
        """Integrate a LiDAR scan into the log-odds occupancy grid.

        Args:
            points: Filtered LiDAR points in world coordinates.
            origin: Sensor origin ``(ox, oy)`` in world meters.
        """
        o_cell = self.world_to_cell(origin[0], origin[1])
        if o_cell is None:
            return
        ox, oy = o_cell

        for pt in points:
            end_cell = self.world_to_cell(pt.x, pt.y)
            if end_cell is None:
                continue
            ex, ey = end_cell
            steps = max(abs(ex - ox), abs(ey - oy))
            if steps > 1:
                xs = np.linspace(ox, ex, steps, endpoint=False).astype(np.int32)
                ys = np.linspace(oy, ey, steps, endpoint=False).astype(np.int32)
                self.grid[ys, xs] = np.clip(self.grid[ys, xs] + self.l_free, self.l_min, self.l_max)
            self.grid[ey, ex] = float(np.clip(self.grid[ey, ex] + self.l_occ, self.l_min, self.l_max))

    def probability_grid(self, log_odds: Optional[np.ndarray] = None) -> np.ndarray:
        """Convert log-odds matrix to occupancy probabilities in ``[0, 1]``."""
        arr = self.grid if log_odds is None else log_odds
        return 1.0 / (1.0 + np.exp(-arr))

    def capture_baseline(self) -> None:
        """Snapshot the current occupancy grid as the reference room baseline."""
        self.baseline = self.grid.copy()

    def reset(self) -> None:
        """Clear live grid values while keeping baseline intact."""
        self.grid.fill(0.0)

    def detect_changes(
        self,
        live_points: Sequence[LidarPoint],
        occ_threshold: float = 0.65,
        min_cells: int = 3,
    ) -> List[PhysicalChangeAnomaly]:
        """Diff live scan points against the stored baseline occupancy grid.

        Args:
            live_points: Latest filtered LiDAR points.
            occ_threshold: Probability threshold defining occupied cells.
            min_cells: Minimum contiguous changed cells required to report an anomaly.

        Returns:
            List of ``PhysicalChangeAnomaly`` objects for added or removed physical geometry.
        """
        if self.baseline is None or not live_points:
            return []

        base_prob = self.probability_grid(self.baseline)
        live_occ = np.zeros((self.dim, self.dim), dtype=bool)
        for pt in live_points:
            cell = self.world_to_cell(pt.x, pt.y)
            if cell is not None:
                live_occ[cell[1], cell[0]] = True

        # Dilate baseline slightly (1 cell) so minor 5cm sensor jitter does not false-alarm.
        base_occ = base_prob >= occ_threshold
        padded = np.pad(base_occ, 1, mode="constant", constant_values=False)
        dilated_base = (
            padded[:-2, :-2] | padded[:-2, 1:-1] | padded[:-2, 2:]
            | padded[1:-1, :-2] | padded[1:-1, 1:-1] | padded[1:-1, 2:]
            | padded[2:, :-2] | padded[2:, 1:-1] | padded[2:, 2:]
        )

        added_mask = live_occ & (~dilated_base)
        added_rows, added_cols = np.where(added_mask)
        if len(added_rows) < min_cells:
            return []

        world_pts = np.array(
            [self.cell_to_world(int(c), int(r)) for r, c in zip(added_rows, added_cols)],
            dtype=np.float64,
        )
        labels = DBSCAN(eps=self.resolution_m * 3.5, min_samples=min_cells).fit_predict(world_pts)

        anomalies: List[PhysicalChangeAnomaly] = []
        cell_area = self.resolution_m * self.resolution_m
        for cid in sorted(set(int(x) for x in labels if x >= 0)):
            pts = world_pts[labels == cid]
            count = len(pts)
            area = count * cell_area
            anomalies.append(
                PhysicalChangeAnomaly(
                    anomaly_type="added",
                    centroid_x=float(np.mean(pts[:, 0])),
                    centroid_y=float(np.mean(pts[:, 1])),
                    area_m2=area,
                    cell_count=count,
                    severity="critical" if count >= min_cells * 3 else "warning",
                )
            )
        return anomalies
