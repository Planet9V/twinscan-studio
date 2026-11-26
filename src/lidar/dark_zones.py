"""Spatial Dark-Zone (LiDAR occlusion shadow) detection and Next-Best-View (NBV) planner.

Computes the exact 2D radial visibility polygon from live LiDAR points, subtracts
it from the room's convex footprint via Shapely to locate occluded shadow wedges,
detects unidentified DBSCAN equipment clusters, and ranks Next-Best-View waypoints.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, List, Sequence

import numpy as np
from shapely.geometry import MultiPoint, Polygon

from src.lidar.ld19_parser import LidarPoint
from src.lidar.mapping import ObjectCluster


@dataclass(frozen=True)
class SpatialDarkZone:
    """An occluded shadow region or unidentified physical cluster needing further scanning.

    Attributes:
        id: Deterministic identifier for UI/graph focus targeting.
        kind: ``"occlusion_shadow"`` or ``"unidentified_cluster"``.
        label: Human-readable operator title.
        centroid_x: Target center X in meters.
        centroid_y: Target center Y in meters.
        area_m2: Approximate dark-zone footprint area in square meters.
        priority_score: Urgency score ``0–100`` (higher = inspect first).
        nbv_x: Recommended Next-Best-View LiDAR/PuppyPi X position in meters.
        nbv_y: Recommended Next-Best-View LiDAR/PuppyPi Y position in meters.
        nbv_yaw_deg: Recommended heading in degrees facing the dark zone.
        polygon: List of ``[x, y]`` polygon boundary vertices.
        recommended_action: Actionable operator instruction.
    """

    id: str
    kind: str
    label: str
    centroid_x: float
    centroid_y: float
    area_m2: float
    priority_score: int
    nbv_x: float
    nbv_y: float
    nbv_yaw_deg: float
    polygon: List[List[float]]
    recommended_action: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize dark zone to a JSON-ready dictionary."""
        return {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "centroid_x": round(self.centroid_x, 4),
            "centroid_y": round(self.centroid_y, 4),
            "area_m2": round(self.area_m2, 3),
            "priority_score": int(self.priority_score),
            "nbv_x": round(self.nbv_x, 4),
            "nbv_y": round(self.nbv_y, 4),
            "nbv_yaw_deg": round(self.nbv_yaw_deg, 1),
            "polygon": [[round(float(x), 4), round(float(y), 4)] for x, y in self.polygon],
            "recommended_action": self.recommended_action,
        }


def _compute_nbv_waypoint(
    target_x: float,
    target_y: float,
    sensor_origin: tuple[float, float] = (0.0, 0.0),
    standoff_m: float = 1.1,
) -> tuple[float, float, float]:
    """Compute a safe Next-Best-View vantage point offset laterally to peer behind an occlusion."""
    dx = target_x - sensor_origin[0]
    dy = target_y - sensor_origin[1]
    dist = math.hypot(dx, dy)
    if dist < 0.25:
        return sensor_origin[0], sensor_origin[1], 0.0
    # Step partway toward target and sidestep perpendicular by 0.65m to look behind the occluder.
    ux, uy = dx / dist, dy / dist
    px, py = -uy, ux
    step = max(0.3, dist - standoff_m)
    nbv_x = sensor_origin[0] + ux * step + px * 0.65
    nbv_y = sensor_origin[1] + uy * step + py * 0.65
    yaw_deg = math.degrees(math.atan2(target_y - nbv_y, target_x - nbv_x)) % 360.0
    return nbv_x, nbv_y, yaw_deg


def detect_spatial_dark_zones(
    points: Sequence[LidarPoint],
    clusters: Sequence[ObjectCluster],
    placed_equipment: Sequence[dict[str, Any]],
    sensor_origin: tuple[float, float] = (0.0, 0.0),
    min_shadow_area_m2: float = 0.25,
    cluster_match_radius_m: float = 0.75,
) -> List[SpatialDarkZone]:
    """Detect LiDAR occlusion shadow dark zones and unidentified physical equipment clusters.

    Args:
        points: Current filtered 360-degree LiDAR points.
        clusters: DBSCAN segmented physical object clusters.
        placed_equipment: Already identified and pinned equipment assets.
        sensor_origin: World ``(x, y)`` of the LiDAR sensor.
        min_shadow_area_m2: Minimum shadow polygon area in m^2 to report.
        cluster_match_radius_m: Distance threshold matching a cluster to an identified asset.

    Returns:
        List of ``SpatialDarkZone`` objects sorted descending by ``priority_score``.
    """
    dark_zones: List[SpatialDarkZone] = []

    # 1. Occlusion shadows: Room convex footprint minus actual LiDAR visibility star polygon.
    if len(points) >= 12:
        sorted_pts = sorted(points, key=lambda p: p.angle_deg)
        vis_ring = [(p.x, p.y) for p in sorted_pts]
        vis_poly = Polygon(vis_ring).buffer(0)
        room_hull = MultiPoint(vis_ring).convex_hull.buffer(0)

        if vis_poly.is_valid and room_hull.is_valid and room_hull.area > 0.5:
            occluded = room_hull.difference(vis_poly)
            geoms = list(occluded.geoms) if hasattr(occluded, "geoms") else [occluded]
            shadow_idx = 0
            for geom in geoms:
                if geom.geom_type != "Polygon" or geom.area < min_shadow_area_m2:
                    continue
                centroid = geom.centroid
                nbv_x, nbv_y, nbv_yaw = _compute_nbv_waypoint(centroid.x, centroid.y, sensor_origin)
                score = min(98, int(45 + geom.area * 18))
                coords = [[float(x), float(y)] for x, y in list(geom.exterior.coords)[:-1]]
                dark_zones.append(
                    SpatialDarkZone(
                        id=f"dark-shadow-{shadow_idx}",
                        kind="occlusion_shadow",
                        label=f"Occluded Blind Spot #{shadow_idx + 1}",
                        centroid_x=float(centroid.x),
                        centroid_y=float(centroid.y),
                        area_m2=float(geom.area),
                        priority_score=score,
                        nbv_x=nbv_x,
                        nbv_y=nbv_y,
                        nbv_yaw_deg=nbv_yaw,
                        polygon=coords,
                        recommended_action=(
                            f"Move LiDAR/PuppyPi to ({nbv_x:.1f}m, {nbv_y:.1f}m) facing {nbv_yaw:.0f}° "
                            f"to illuminate {geom.area:.2f} m² shadow behind obstacle."
                        ),
                    )
                )
                shadow_idx += 1

    # 2. Unidentified physical clusters (objects visible to LiDAR but missing Vision/Twin identity).
    for c in clusters:
        matched = any(
            math.hypot(float(eq["x"]) - c.centroid_x, float(eq["y"]) - c.centroid_y) <= cluster_match_radius_m
            for eq in placed_equipment
        )
        if matched:
            continue
        area = max(0.05, c.width_m * c.depth_m)
        nbv_x, nbv_y, nbv_yaw = _compute_nbv_waypoint(c.centroid_x, c.centroid_y, sensor_origin, standoff_m=0.9)
        # High metallic reflectance clusters (e.g. racks/PLCs) receive higher inspection priority.
        metallic_bonus = 12 if c.mean_intensity >= 210 else 0
        score = min(99, int(62 + min(22, area * 15) + metallic_bonus))
        dark_zones.append(
            SpatialDarkZone(
                id=f"dark-cluster-{c.cluster_id}",
                kind="unidentified_cluster",
                label=f"Unidentified Hardware Cluster C{c.cluster_id}",
                centroid_x=c.centroid_x,
                centroid_y=c.centroid_y,
                area_m2=area,
                priority_score=score,
                nbv_x=nbv_x,
                nbv_y=nbv_y,
                nbv_yaw_deg=nbv_yaw,
                polygon=c.polygon,
                recommended_action=(
                    f"Capture nameplate photo of {c.width_m:.2f}x{c.depth_m:.2f}m metallic object "
                    f"at ({c.centroid_x:.2f}m, {c.centroid_y:.2f}m) to identify Make/Model/Serial."
                ),
            )
        )

    dark_zones.sort(key=lambda z: z.priority_score, reverse=True)
    return dark_zones
