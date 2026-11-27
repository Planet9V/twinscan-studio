"""Unit tests for src/vision/overwatch_geometry.py."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from src.vision.overwatch_geometry import (
    build_camera_matrix,
    calibrate_camera_apriltag_pnp,
    calibrate_camera_four_point_homography,
    compute_camera_frustum_polygon,
    compute_coverage_overlap_zones,
    compute_placement_advisor,
    project_pixel_to_task_waypoint,
)
from src.vision.overwatch_triangulator import OverwatchCalibration


def test_frustum_polygon_and_overlap_zones() -> None:
    """Two converging cameras produce valid frustums, stereo overlap, and dead zones."""
    cam1 = {
        "camera_id": "usb_4k",
        "camera_name": "4K USB",
        "online": True,
        "width": 1920,
        "height": 1080,
        "calibration": OverwatchCalibration(x_m=-1.5, y_m=-2.0, z_m=1.6, yaw_deg=60.0, pitch_deg=-25.0),
    }
    cam2 = {
        "camera_id": "macbook_cam",
        "camera_name": "MacBook Cam",
        "online": True,
        "width": 1280,
        "height": 720,
        "calibration": OverwatchCalibration(x_m=1.5, y_m=-2.0, z_m=1.4, yaw_deg=120.0, pitch_deg=-25.0),
    }
    poly1 = compute_camera_frustum_polygon(cam1["calibration"], max_range_m=5.0)
    assert poly1.is_valid
    assert poly1.area > 1.0

    geo = compute_coverage_overlap_zones([cam1, cam2], room_bounds=(-4.0, -4.0, 4.0, 4.0), max_range_m=6.0)
    assert len(geo["frustums"]) == 2
    assert geo["metrics"]["stereo_area_m2"] > 0.5
    assert geo["metrics"]["covered_pct"] > 0.0
    assert geo["placement_advisor"]["rating"] in ("OPTIMAL", "GOOD")
    assert 40.0 <= geo["placement_advisor"]["best_angle_deg"] <= 110.0


def test_placement_advisor_collinear_warns_poor() -> None:
    """Nearly identical camera positions and headings produce POOR or FAIR placement rating."""
    cams = [
        {"camera_id": "usb_4k", "calibration": OverwatchCalibration(x_m=0.0, y_m=-2.0, yaw_deg=90.0)},
        {"camera_id": "macbook_cam", "calibration": OverwatchCalibration(x_m=0.05, y_m=-2.0, yaw_deg=91.0)},
    ]
    adv = compute_placement_advisor(cams)
    assert adv["rating"] == "POOR"
    assert adv["best_angle_deg"] < 15.0


def test_four_point_floor_homography_roundtrip() -> None:
    """Synthetic 4 floor points recover sub-pixel reprojection and accurate pixel-to-floor mapping."""
    w, h = 1280, 720
    cal = OverwatchCalibration(x_m=0.0, y_m=-2.5, z_m=1.5, yaw_deg=90.0, pitch_deg=-25.0, hfov_deg=78.0, vfov_deg=48.0)
    K = build_camera_matrix(w, h, cal.hfov_deg, cal.vfov_deg)

    # Synthetic camera looking along +Y, pitched down 25 deg
    yaw = np.radians(90.0)
    pitch = np.radians(-25.0)
    fwd = np.array([np.cos(pitch) * np.cos(yaw), np.cos(pitch) * np.sin(yaw), np.sin(pitch)])
    right = np.cross(fwd, np.array([0.0, 0.0, 1.0]))
    right /= np.linalg.norm(right)
    down = np.cross(fwd, right)
    R_c2w = np.column_stack([right, down, fwd])
    R_w2c = R_c2w.T
    cam_pos = np.array([0.0, -2.5, 1.5])
    tvec = -R_w2c @ cam_pos
    rvec, _ = cv2.Rodrigues(R_w2c)

    world_xy = [(-1.0, 0.0), (1.0, 0.0), (1.0, 2.0), (-1.0, 2.0)]
    world_3d = np.array([[x, y, 0.0] for x, y in world_xy], dtype=np.float64)
    proj, _ = cv2.projectPoints(world_3d, rvec, tvec, K, np.zeros((4, 1)))
    pixel_norm = [(float(p[0] / w), float(p[1] / h)) for p in proj.reshape(-1, 2)]

    solved = calibrate_camera_four_point_homography(pixel_norm, world_xy, w, h, cal)
    assert solved["ok"] is True
    assert solved["reprojection_error_px"] < 2.0
    assert len(solved["homography_3x3"]) == 3

    # Project center of the 4 points -> should land near (0.0, 1.0)
    center_3d = np.array([[0.0, 1.0, 0.0]], dtype=np.float64)
    c_proj, _ = cv2.projectPoints(center_3d, rvec, tvec, K, np.zeros((4, 1)))
    cu, cv_y = float(c_proj[0, 0, 0] / w), float(c_proj[0, 0, 1] / h)
    task = project_pixel_to_task_waypoint(
        u_norm=cu,
        v_norm=cv_y,
        cal=cal,
        width=w,
        height=h,
        homography_3x3=solved["homography_3x3"],
        robot_pose={"x": 0.0, "y": 0.0, "yaw_deg": 90.0},
        standoff_m=0.3,
    )
    assert task["projection_method"] == "homography_4pt"
    assert abs(task["target_xy"][0] - 0.0) < 0.05
    assert abs(task["target_xy"][1] - 1.0) < 0.05
    assert abs(task["walk_distance_m"] - 0.7) < 0.1


def test_four_point_homography_rejects_collinear() -> None:
    """Collinear world points raise ValueError."""
    cal = OverwatchCalibration()
    with pytest.raises(ValueError, match="collinear"):
        calibrate_camera_four_point_homography(
            [(0.1, 0.5), (0.3, 0.5), (0.6, 0.5), (0.9, 0.5)],
            [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0), (3.0, 0.0)],
            1280,
            720,
            cal,
        )


def test_apriltag_pnp_raises_when_no_tag_visible() -> None:
    """Blank frame raises a helpful ValueError when no AprilTag is visible."""
    blank = np.zeros((480, 640, 3), dtype=np.uint8)
    with pytest.raises(ValueError, match="No AprilTag"):
        calibrate_camera_apriltag_pnp(blank, OverwatchCalibration())
