"""2D spatial mapping: RANSAC architectural wall extraction, DBSCAN object clustering, and Shapely room metrology."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Sequence, Tuple

import numpy as np
from shapely.geometry import MultiPoint
from sklearn.cluster import DBSCAN

from src.lidar.ld19_parser import LidarPoint


@dataclass(frozen=True)
class WallSegment:
    """Extracted straight architectural wall segment in meters.

    Attributes:
        x1: Start X coordinate in meters.
        y1: Start Y coordinate in meters.
        x2: End X coordinate in meters.
        y2: End Y coordinate in meters.
        length_m: Euclidean wall segment length in meters.
        inlier_count: Number of LiDAR points supporting this wall.
    """

    x1: float
    y1: float
    x2: float
    y2: float
    length_m: float
    inlier_count: int

    def to_dict(self) -> dict[str, Any]:
        """Serialize wall segment to a JSON-ready dictionary."""
        return {
            "x1": round(self.x1, 4),
            "y1": round(self.y1, 4),
            "x2": round(self.x2, 4),
            "y2": round(self.y2, 4),
            "length_m": round(self.length_m, 4),
            "inlier_count": int(self.inlier_count),
        }


@dataclass(frozen=True)
class ObjectCluster:
    """Segmented physical object cluster detected inside a scanned space.

    Attributes:
        cluster_id: Deterministic zero-based cluster index.
        centroid_x: Cluster center X in meters.
        centroid_y: Cluster center Y in meters.
        width_m: Oriented bounding box width in meters.
        depth_m: Oriented bounding box depth in meters.
        point_count: Number of LiDAR points in this cluster.
        mean_intensity: Average reflectance intensity (0–255).
        polygon: List of ``[x, y]`` hull vertices describing the object footprint.
    """

    cluster_id: int
    centroid_x: float
    centroid_y: float
    width_m: float
    depth_m: float
    point_count: int
    mean_intensity: float
    polygon: List[List[float]]

    def to_dict(self) -> dict[str, Any]:
        """Serialize object cluster to a JSON-ready dictionary."""
        return {
            "cluster_id": self.cluster_id,
            "centroid_x": round(self.centroid_x, 4),
            "centroid_y": round(self.centroid_y, 4),
            "width_m": round(self.width_m, 4),
            "depth_m": round(self.depth_m, 4),
            "point_count": self.point_count,
            "mean_intensity": round(self.mean_intensity, 2),
            "polygon": [[round(x, 4), round(y, 4)] for x, y in self.polygon],
        }


def _fit_line_ransac(
    coords: np.ndarray,
    distance_threshold: float,
    max_trials: int,
    rng: np.random.Generator,
) -> Tuple[np.ndarray, np.ndarray]:
    """Fit a 2D line via orthogonal-distance RANSAC and refine with PCA."""
    n = len(coords)
    best_inliers = np.zeros(n, dtype=bool)
    best_count = 0

    for _ in range(max_trials):
        idx1, idx2 = rng.choice(n, size=2, replace=False)
        p1, p2 = coords[idx1], coords[idx2]
        vec = p2 - p1
        norm = float(np.hypot(vec[0], vec[1]))
        if norm < 1e-4:
            continue
        nx, ny = -vec[1] / norm, vec[0] / norm
        dists = np.abs((coords[:, 0] - p1[0]) * nx + (coords[:, 1] - p1[1]) * ny)
        inliers = dists <= distance_threshold
        count = int(np.sum(inliers))
        if count > best_count:
            best_count = count
            best_inliers = inliers

    if best_count < 2:
        return np.zeros(2), best_inliers

    inlier_pts = coords[best_inliers]
    mean = np.mean(inlier_pts, axis=0)
    centered = inlier_pts - mean
    _, _, vt = np.linalg.svd(centered, full_matrices=False)
    direction = vt[0]
    return direction, best_inliers


def extract_walls_ransac(
    points: Sequence[LidarPoint],
    distance_threshold_m: float = 0.06,
    min_inliers: int = 12,
    min_wall_length_m: float = 0.6,
    max_walls: int = 12,
    gap_break_m: float = 0.55,
    seed: int = 42,
) -> Tuple[List[WallSegment], List[LidarPoint]]:
    """Extract straight architectural wall segments using iterative orthogonal RANSAC.

    Splits collinear wall segments across wide doorways/gaps and returns residual
    non-wall points suitable for downstream equipment/object clustering.

    Args:
        points: Filtered 2D LiDAR points.
        distance_threshold_m: Maximum perpendicular distance in meters to count as a wall inlier.
        min_inliers: Minimum supporting points required to accept a wall.
        min_wall_length_m: Minimum length in meters for a valid wall segment.
        max_walls: Maximum number of wall extraction iterations.
        gap_break_m: Maximum gap along a wall before splitting into separate segments (doorways).
        seed: Random generator seed for deterministic extraction.

    Returns:
        Tuple ``(walls, residual_points)``.
    """
    if len(points) < min_inliers:
        return [], list(points)

    rng = np.random.default_rng(seed)
    remaining_indices = np.arange(len(points))
    all_coords = np.array([[p.x, p.y] for p in points], dtype=np.float64)
    walls: List[WallSegment] = []

    for _ in range(max_walls):
        if len(remaining_indices) < min_inliers:
            break
        sub_coords = all_coords[remaining_indices]
        direction, local_inliers = _fit_line_ransac(
            sub_coords,
            distance_threshold=distance_threshold_m,
            max_trials=160,
            rng=rng,
        )
        if int(np.sum(local_inliers)) < min_inliers:
            break

        inlier_coords = sub_coords[local_inliers]
        origin = np.mean(inlier_coords, axis=0)
        projections = (inlier_coords - origin) @ direction
        order = np.argsort(projections)
        sorted_proj = projections[order]

        # Split contiguous runs separated by doorway gaps.
        splits = np.where(np.diff(sorted_proj) > gap_break_m)[0] + 1
        runs = np.split(order, splits)

        accepted_local_mask = np.zeros(len(sub_coords), dtype=bool)
        inlier_positions = np.flatnonzero(local_inliers)
        found_valid_run = False

        for run in runs:
            if len(run) < max(6, min_inliers // 2):
                continue
            p_start = origin + sorted_proj[np.searchsorted(sorted_proj, projections[run[0]])] * direction
            p_end = origin + sorted_proj[np.searchsorted(sorted_proj, projections[run[-1]])] * direction
            length = float(np.hypot(p_end[0] - p_start[0], p_end[1] - p_start[1]))
            if length < min_wall_length_m:
                continue
            walls.append(
                WallSegment(
                    x1=float(p_start[0]),
                    y1=float(p_start[1]),
                    x2=float(p_end[0]),
                    y2=float(p_end[1]),
                    length_m=length,
                    inlier_count=len(run),
                )
            )
            accepted_local_mask[inlier_positions[run]] = True
            found_valid_run = True

        if not found_valid_run:
            break
        remaining_indices = remaining_indices[~accepted_local_mask]

    residuals = [points[int(i)] for i in remaining_indices]
    return walls, residuals


def segment_object_clusters(
    points: Sequence[LidarPoint],
    eps_m: float = 0.22,
    min_samples: int = 5,
) -> List[ObjectCluster]:
    """Segment non-wall LiDAR points into discrete physical equipment/object clusters.

    Args:
        points: Residual LiDAR points (typically after wall extraction).
        eps_m: DBSCAN neighborhood radius in meters.
        min_samples: Minimum points required to form an object cluster.

    Returns:
        List of ``ObjectCluster`` candidates with oriented bounding dimensions and hull polygons.
    """
    if len(points) < min_samples:
        return []

    coords = np.array([[p.x, p.y] for p in points], dtype=np.float64)
    intensities = np.array([p.intensity for p in points], dtype=np.float64)
    labels = DBSCAN(eps=eps_m, min_samples=min_samples).fit_predict(coords)

    clusters: List[ObjectCluster] = []
    for cid in sorted(set(int(x) for x in labels if x >= 0)):
        mask = labels == cid
        pts = coords[mask]
        cx = float(np.mean(pts[:, 0]))
        cy = float(np.mean(pts[:, 1]))
        mean_int = float(np.mean(intensities[mask]))

        mp = MultiPoint([(float(x), float(y)) for x, y in pts])
        hull = mp.convex_hull
        min_rect = mp.minimum_rotated_rectangle

        if hasattr(min_rect, "exterior"):
            rc = list(min_rect.exterior.coords)
            edge1 = float(np.hypot(rc[1][0] - rc[0][0], rc[1][1] - rc[0][1]))
            edge2 = float(np.hypot(rc[2][0] - rc[1][0], rc[2][1] - rc[1][1]))
            width_m, depth_m = max(edge1, edge2), min(edge1, edge2)
        else:
            width_m = float(np.ptp(pts[:, 0]))
            depth_m = float(np.ptp(pts[:, 1]))

        if hasattr(hull, "exterior"):
            polygon = [[float(x), float(y)] for x, y in list(hull.exterior.coords)[:-1]]
        else:
            polygon = [[float(x), float(y)] for x, y in pts[:8]]

        clusters.append(
            ObjectCluster(
                cluster_id=cid,
                centroid_x=cx,
                centroid_y=cy,
                width_m=max(width_m, 0.05),
                depth_m=max(depth_m, 0.05),
                point_count=int(np.sum(mask)),
                mean_intensity=mean_int,
                polygon=polygon,
            )
        )
    return clusters


def compute_room_metrics(
    walls: Sequence[WallSegment],
    points: Sequence[LidarPoint],
) -> dict[str, Any]:
    """Compute room area, perimeter, and bounding-box dimensions using Shapely.

    Args:
        walls: Extracted architectural wall segments.
        points: Full filtered point cloud for the room.

    Returns:
        Dictionary with ``area_m2``, ``perimeter_m``, ``width_m``, ``depth_m``,
        ``wall_count``, and ``footprint_polygon``.
    """
    all_xy: List[tuple[float, float]] = [(p.x, p.y) for p in points]
    for w in walls:
        all_xy.append((w.x1, w.y1))
        all_xy.append((w.x2, w.y2))

    if len(all_xy) < 3:
        return {
            "area_m2": 0.0,
            "perimeter_m": 0.0,
            "width_m": 0.0,
            "depth_m": 0.0,
            "wall_count": len(walls),
            "footprint_polygon": [],
        }

    hull = MultiPoint(all_xy).convex_hull
    minx, miny, maxx, maxy = hull.bounds
    polygon = (
        [[round(float(x), 4), round(float(y), 4)] for x, y in list(hull.exterior.coords)[:-1]]
        if hasattr(hull, "exterior")
        else []
    )
    return {
        "area_m2": round(float(hull.area), 3),
        "perimeter_m": round(float(hull.length), 3),
        "width_m": round(float(maxx - minx), 3),
        "depth_m": round(float(maxy - miny), 3),
        "wall_count": len(walls),
        "footprint_polygon": polygon,
    }
