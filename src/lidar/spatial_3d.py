"""3D spatial twin mesh synthesis (trimesh) and camera-to-LiDAR raycast auto-placement."""

from __future__ import annotations

import math
from typing import Any, Sequence

import numpy as np
import trimesh

from src.lidar.ld19_parser import LidarPoint
from src.lidar.mapping import WallSegment


def build_room_3d_scene(
    walls: Sequence[WallSegment],
    equipment: Sequence[dict[str, Any]],
    wall_height_m: float = 2.8,
    wall_thickness_m: float = 0.14,
) -> trimesh.Scene:
    """Extrude 2D wall segments and placed equipment into a 3D ``trimesh.Scene``.

    Args:
        walls: Architectural wall segments extracted from LiDAR.
        equipment: Placed equipment dicts with ``x``, ``y``, optional ``z``,
            ``width_m``, ``depth_m``, ``height_m``, ``yaw_deg``, and ``name``.
        wall_height_m: Extrusion height of walls in meters.
        wall_thickness_m: Wall thickness in meters.

    Returns:
        ``trimesh.Scene`` ready for glTF/GLB export or raycasting.
    """
    scene = trimesh.Scene()

    for idx, w in enumerate(walls):
        length = max(w.length_m, 0.05)
        box = trimesh.creation.box(extents=[length, wall_thickness_m, wall_height_m])
        cx = (w.x1 + w.x2) / 2.0
        cy = (w.y1 + w.y2) / 2.0
        angle = math.atan2(w.y2 - w.y1, w.x2 - w.x1)
        transform = trimesh.transformations.rotation_matrix(angle, [0, 0, 1])
        transform[0, 3] = cx
        transform[1, 3] = cy
        transform[2, 3] = wall_height_m / 2.0
        box.apply_transform(transform)
        scene.add_geometry(box, node_name=f"wall_{idx}", geom_name=f"wall_{idx}")

    for idx, eq in enumerate(equipment):
        w_m = float(eq.get("width_m") or 0.65)
        d_m = float(eq.get("depth_m") or 0.65)
        h_m = float(eq.get("height_m") or 1.4)
        x = float(eq.get("x", 0.0))
        y = float(eq.get("y", 0.0))
        z = float(eq.get("z", 0.0))
        yaw = math.radians(float(eq.get("yaw_deg", 0.0)))

        mesh = trimesh.creation.box(extents=[w_m, d_m, h_m])
        transform = trimesh.transformations.rotation_matrix(yaw, [0, 0, 1])
        transform[0, 3] = x
        transform[1, 3] = y
        transform[2, 3] = z + h_m / 2.0
        mesh.apply_transform(transform)
        eq_name = str(eq.get("id") or f"equipment_{idx}")
        scene.add_geometry(mesh, node_name=eq_name, geom_name=eq_name)

    return scene


def raycast_camera_to_lidar(
    bbox_norm: Sequence[float],
    lidar_points: Sequence[LidarPoint],
    camera_fov_deg: float = 68.0,
    camera_yaw_deg: float = 0.0,
    lidar_pose: tuple[float, float, float] = (0.0, 0.0, 0.0),
    angular_window_deg: float = 5.0,
) -> dict[str, Any]:
    """Project a normalized VLM bounding box ray onto live LiDAR returns for auto-placement.

    Accepts either 0–1000 normalized boxes (Gemini/Qwen convention) or 0–1 boxes
    in ``[ymin, xmin, ymax, xmax]`` order.

    Args:
        bbox_norm: 4-element bounding box ``[ymin, xmin, ymax, xmax]``.
        lidar_points: Current filtered LiDAR point cloud.
        camera_fov_deg: Horizontal camera field of view in degrees.
        camera_yaw_deg: Camera boresight heading relative to LiDAR 0 deg.
        lidar_pose: World pose ``(px, py, pyaw_deg)`` of the LiDAR sensor.
        angular_window_deg: Half-width angular cone to sample LiDAR hits along the ray.

    Returns:
        Dictionary containing estimated ``x``, ``y``, ``distance_m``, ``bearing_deg``,
        ``supporting_points``, and ``confidence``.
    """
    if len(bbox_norm) != 4:
        raise ValueError("bbox_norm must have 4 elements: [ymin, xmin, ymax, xmax].")

    ymin, xmin, ymax, xmax = [float(v) for v in bbox_norm]
    scale = 1000.0 if max(ymin, xmin, ymax, xmax) > 1.0 else 1.0
    u_center = ((xmin + xmax) / 2.0) / scale
    u_center = max(0.0, min(1.0, u_center))

    # Horizontal image center u=0.5 aligns with camera_yaw_deg.
    bearing_local = (camera_yaw_deg + (0.5 - u_center) * camera_fov_deg) % 360.0

    candidates: list[LidarPoint] = []
    for pt in lidar_points:
        delta = abs(((pt.angle_deg - bearing_local + 180.0) % 360.0) - 180.0)
        if delta <= angular_window_deg and pt.distance_m > 0.05:
            candidates.append(pt)

    px, py, pyaw_deg = lidar_pose
    world_bearing = (bearing_local + pyaw_deg) % 360.0

    if not candidates:
        fallback_dist = 2.0
        rad = math.radians(world_bearing)
        return {
            "x": round(px + fallback_dist * math.cos(rad), 4),
            "y": round(py + fallback_dist * math.sin(rad), 4),
            "distance_m": fallback_dist,
            "bearing_deg": round(world_bearing, 2),
            "supporting_points": 0,
            "confidence": 0.25,
        }

    # Use the 25th percentile distance to lock onto the front surface of the equipment
    # rather than background wall returns peeking around the edges.
    dists = np.array([c.distance_m for c in candidates], dtype=np.float64)
    surface_dist = float(np.percentile(dists, 25))
    rad = math.radians(world_bearing)
    return {
        "x": round(px + surface_dist * math.cos(rad), 4),
        "y": round(py + surface_dist * math.sin(rad), 4),
        "distance_m": round(surface_dist, 4),
        "bearing_deg": round(world_bearing, 2),
        "supporting_points": len(candidates),
        "confidence": round(min(0.98, 0.55 + 0.05 * len(candidates)), 2),
    }
