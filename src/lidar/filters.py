"""Real-time LiDAR filtering, angular sector masking, and safety zone detection."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, List, Sequence

import numpy as np
from shapely.geometry import Point, Polygon

from src.lidar.ld19_parser import LidarPoint


@dataclass
class FilterConfig:
    """Configuration for real-time LiDAR point-cloud filtering.

    Attributes:
        min_range_m: Minimum valid radial range in meters.
        max_range_m: Maximum valid radial range in meters.
        min_intensity: Minimum signal reflectance confidence (0–255).
        sector_start_deg: Start of active/masked angular sector in degrees.
        sector_end_deg: End of active/masked angular sector in degrees.
        exclude_sector: When True, exclude points inside ``[sector_start_deg, sector_end_deg]``;
            when False, keep only points inside the sector.
        rotation_offset_deg: Rotational calibration offset added to all angles.
        enable_outlier_filter: Whether to remove isolated speckle noise points.
        outlier_radius_m: Neighborhood radius in meters for statistical outlier removal.
        outlier_min_neighbors: Minimum neighbor count required to keep a point.
    """

    min_range_m: float = 0.08
    max_range_m: float = 12.0
    min_intensity: int = 15
    sector_start_deg: float = 0.0
    sector_end_deg: float = 360.0
    exclude_sector: bool = False
    rotation_offset_deg: float = 0.0
    enable_outlier_filter: bool = False
    outlier_radius_m: float = 0.15
    outlier_min_neighbors: int = 2


def _angle_in_sector(angle_deg: float, start_deg: float, end_deg: float) -> bool:
    """Return True if ``angle_deg`` falls within the clockwise sector ``[start_deg, end_deg]``."""
    span = end_deg - start_deg
    if abs(span) >= 360.0:
        return True
    a = angle_deg % 360.0
    s = start_deg % 360.0
    e = end_deg % 360.0
    if s <= e:
        return s <= a <= e
    return a >= s or a <= e


def apply_lidar_filters(points: Sequence[LidarPoint], config: FilterConfig) -> List[LidarPoint]:
    """Apply range, intensity, angular sector, rotation, and optional outlier filters.

    Args:
        points: Raw ``LidarPoint`` measurements from a scan.
        config: Active ``FilterConfig`` parameters.

    Returns:
        Filtered list of ``LidarPoint`` objects with rotation offset applied.
    """
    filtered: List[LidarPoint] = []
    full_circle = abs(config.sector_end_deg - config.sector_start_deg) >= 360.0

    for pt in points:
        if pt.distance_m < config.min_range_m or pt.distance_m > config.max_range_m:
            continue
        if pt.intensity < config.min_intensity:
            continue

        adj_angle = (pt.angle_deg + config.rotation_offset_deg) % 360.0
        if not full_circle:
            in_sector = _angle_in_sector(adj_angle, config.sector_start_deg, config.sector_end_deg)
            if config.exclude_sector and in_sector:
                continue
            if not config.exclude_sector and not in_sector:
                continue

        if config.rotation_offset_deg != 0.0:
            rad = math.radians(adj_angle)
            x = pt.distance_m * math.cos(rad)
            y = pt.distance_m * math.sin(rad)
        else:
            x, y = pt.x, pt.y

        filtered.append(
            LidarPoint(
                angle_deg=adj_angle,
                distance_m=pt.distance_m,
                intensity=pt.intensity,
                x=x,
                y=y,
            )
        )

    if not config.enable_outlier_filter or len(filtered) <= config.outlier_min_neighbors:
        return filtered

    coords = np.array([[p.x, p.y] for p in filtered], dtype=np.float64)
    diff = coords[:, None, :] - coords[None, :, :]
    dist_sq = np.sum(diff * diff, axis=-1)
    radius_sq = config.outlier_radius_m ** 2
    neighbor_counts = np.sum(dist_sq <= radius_sq, axis=1) - 1
    return [pt for pt, count in zip(filtered, neighbor_counts) if count >= config.outlier_min_neighbors]


def detect_zone_intrusions(
    points: Sequence[LidarPoint],
    zones: Sequence[dict[str, Any]],
) -> List[dict[str, Any]]:
    """Evaluate how many live LiDAR returns fall inside configured polygon zones.

    Args:
        points: Filtered LiDAR points in Cartesian coordinates.
        zones: Zone dictionaries with keys ``id``, ``name``, ``polygon`` (list of ``[x, y]``),
            and optional ``threshold`` (minimum points to trigger alert).

    Returns:
        List of intrusion report dicts for every zone with ``hit_count >= threshold``.
    """
    alerts: List[dict[str, Any]] = []
    if not points or not zones:
        return alerts

    for zone in zones:
        verts = zone.get("polygon") or []
        if len(verts) < 3:
            continue
        poly = Polygon(verts)
        if not poly.is_valid:
            poly = poly.buffer(0)
        threshold = int(zone.get("threshold", 3))
        hits = [pt for pt in points if poly.contains(Point(pt.x, pt.y))]
        if len(hits) >= threshold:
            cx = float(np.mean([p.x for p in hits]))
            cy = float(np.mean([p.y for p in hits]))
            alerts.append(
                {
                    "zone_id": zone.get("id", "unknown"),
                    "zone_name": zone.get("name", "Unnamed Zone"),
                    "hit_count": len(hits),
                    "centroid": [round(cx, 3), round(cy, 3)],
                    "severity": "critical" if len(hits) >= threshold * 3 else "warning",
                }
            )
    return alerts
