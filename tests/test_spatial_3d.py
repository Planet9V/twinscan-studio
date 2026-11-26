"""Unit tests for 3D trimesh scene synthesis and camera-to-LiDAR raycast auto-placement."""

from __future__ import annotations

import pytest

from src.lidar.ld19_parser import LidarPoint, polar_to_cartesian
from src.lidar.mapping import WallSegment
from src.lidar.spatial_3d import build_room_3d_scene, raycast_camera_to_lidar


def test_build_room_3d_scene_contains_walls_and_equipment() -> None:
    """3D room builder extrudes walls and equipment into a valid glTF-exportable scene."""
    walls = [WallSegment(0.0, 0.0, 4.0, 0.0, 4.0, 50)]
    equipment = [{"id": "rack_a1", "x": 2.0, "y": 1.0, "width_m": 0.8, "depth_m": 0.9, "height_m": 2.0}]
    scene = build_room_3d_scene(walls, equipment, wall_height_m=2.8)
    assert "wall_0" in scene.geometry
    assert "rack_a1" in scene.geometry
    glb_bytes = scene.export(file_type="glb")
    assert isinstance(glb_bytes, bytes) and len(glb_bytes) > 100


def test_raycast_camera_to_lidar_locks_onto_front_surface() -> None:
    """Center bounding box projects along camera boresight and locks onto front LiDAR surface."""
    pts = []
    for angle in (-3.0, -1.5, 0.0, 1.5, 3.0):
        x, y = polar_to_cartesian(angle % 360.0, 2.4)
        pts.append(LidarPoint(angle % 360.0, 2.4, 220, x, y))
    # Background wall return further back at 4.0m
    xb, yb = polar_to_cartesian(1.0, 4.0)
    pts.append(LidarPoint(1.0, 4.0, 180, xb, yb))

    est = raycast_camera_to_lidar([200, 450, 800, 550], pts, camera_fov_deg=68.0, camera_yaw_deg=0.0)
    assert pytest.approx(est["distance_m"], abs=0.1) == 2.4
    assert pytest.approx(est["x"], abs=0.1) == 2.4
    assert est["supporting_points"] == 6
    assert est["confidence"] >= 0.7


def test_raycast_camera_to_lidar_validates_bbox() -> None:
    """Invalid bounding box length raises ValueError."""
    with pytest.raises(ValueError):
        raycast_camera_to_lidar([0.1, 0.2], [])
