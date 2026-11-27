"""Tactical Multi-Camera Overwatch Geometry, Overlap Mapping & Auto-Calibration.

Provides:
- Shapely 2D Bird's-Eye View (BEV) ground-plane camera frustum footprints.
- Multi-tier sensor coverage & overlap polygons (0-cam dead zones, 1-cam mono,
  2-cam stereo triangulation zones, and 3+-cam precision fusion zones).
- Stereo baseline & convergence-angle Placement Advisor.
- 1-click AprilTag ``cv2.solvePnP`` 6-DOF extrinsic auto-calibration.
- Interactive 4-Point Floor Click Homography + PnP calibration (zero printed tags).
- Click-on-camera pixel-to-floor waypoint projection with safe standoff clamping.
"""

from __future__ import annotations

import math
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np
from shapely.geometry import MultiPolygon, Polygon, box
from shapely.ops import unary_union

from src.vision.overwatch_triangulator import (
    OverwatchCalibration,
    intersect_ray_ground_plane,
    pixel_to_world_ray,
)

CAMERA_COLORS: Dict[str, str] = {
    "usb_4k": "#22d3ee",       # cyan-400
    "macbook_cam": "#a78bfa",  # violet-400
    "puppypi_fpv": "#34d399",  # emerald-400
}


def _extract_polygon_rings(geom: Any) -> List[List[List[float]]]:
    """Convert a Shapely Polygon/MultiPolygon/GeometryCollection into JSON-safe XY rings."""
    if geom is None or geom.is_empty:
        return []
    rings: List[List[List[float]]] = []
    if isinstance(geom, Polygon):
        coords = [[round(float(x), 3), round(float(y), 3)] for x, y in geom.exterior.coords]
        if len(coords) >= 4:
            rings.append(coords)
    elif isinstance(geom, MultiPolygon):
        for poly in geom.geoms:
            rings.extend(_extract_polygon_rings(poly))
    elif hasattr(geom, "geoms"):
        for sub in geom.geoms:
            rings.extend(_extract_polygon_rings(sub))
    return rings


def build_camera_matrix(width: int, height: int, hfov_deg: float, vfov_deg: float) -> np.ndarray:
    """Build a standard 3x3 pinhole camera intrinsics matrix ``K`` from FOVs.

    Args:
        width: Image width in pixels.
        height: Image height in pixels.
        hfov_deg: Full horizontal field of view in degrees.
        vfov_deg: Full vertical field of view in degrees.

    Returns:
        3x3 float64 NumPy intrinsics matrix ``K``.
    """
    w = max(2.0, float(width))
    h = max(2.0, float(height))
    fx = (w * 0.5) / math.tan(math.radians(max(5.0, min(170.0, float(hfov_deg)))) * 0.5)
    fy = (h * 0.5) / math.tan(math.radians(max(5.0, min(170.0, float(vfov_deg)))) * 0.5)
    return np.array(
        [
            [fx, 0.0, w * 0.5],
            [0.0, fy, h * 0.5],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )


def compute_camera_frustum_polygon(
    cal: OverwatchCalibration,
    max_range_m: float = 6.0,
    width: int = 1280,
    height: int = 720,
) -> Polygon:
    """Project a camera's 4 corner rays onto the floor plane ``z = 0`` to build a BEV frustum polygon.

    Args:
        cal: Camera extrinsic and intrinsic calibration.
        max_range_m: Maximum effective visual range in meters (clamps horizon/upward rays).
        width: Nominal image width in pixels.
        height: Nominal image height in pixels.

    Returns:
        Valid Shapely ``Polygon`` representing the camera's ground-plane footprint in meters.
    """
    max_r = max(0.5, min(25.0, float(max_range_m)))
    origin_xy = np.array([float(cal.x_m), float(cal.y_m)], dtype=np.float64)
    # Cast bottom-left, bottom-right, top-right, top-left corners
    corners_px = [(0.0, float(height)), (float(width), float(height)), (float(width), 0.0), (0.0, 0.0)]
    ground_pts: List[Tuple[float, float]] = []

    for u, v in corners_px:
        origin, direction = pixel_to_world_ray(u, v, width, height, cal)
        hit = intersect_ray_ground_plane(origin, direction, z_plane=0.0)
        if hit is not None:
            vec = np.array([hit["x"] - origin_xy[0], hit["y"] - origin_xy[1]], dtype=np.float64)
            dist = float(np.linalg.norm(vec))
            if dist > max_r and dist > 1e-6:
                vec = vec * (max_r / dist)
            ground_pts.append((float(origin_xy[0] + vec[0]), float(origin_xy[1] + vec[1])))
        else:
            # Ray points at or above horizon -> clamp along XY ray direction at max_range_m
            xy_dir = np.array([float(direction[0]), float(direction[1])], dtype=np.float64)
            norm = float(np.linalg.norm(xy_dir))
            if norm < 1e-6:
                yaw_rad = math.radians(float(cal.yaw_deg))
                xy_dir = np.array([math.cos(yaw_rad), math.sin(yaw_rad)], dtype=np.float64)
            else:
                xy_dir = xy_dir / norm
            ground_pts.append((float(origin_xy[0] + xy_dir[0] * max_r), float(origin_xy[1] + xy_dir[1] * max_r)))

    # Ensure convex hull / clean valid polygon
    poly = Polygon(ground_pts)
    if not poly.is_valid or poly.area < 1e-4:
        poly = poly.convex_hull
    if not isinstance(poly, Polygon) or poly.area < 1e-4:
        # Fallback narrow wedge along yaw
        yaw_rad = math.radians(float(cal.yaw_deg))
        half = math.radians(max(10.0, float(cal.hfov_deg)) * 0.5)
        p1 = (float(origin_xy[0]), float(origin_xy[1]))
        p2 = (float(origin_xy[0] + math.cos(yaw_rad - half) * max_r), float(origin_xy[1] + math.sin(yaw_rad - half) * max_r))
        p3 = (float(origin_xy[0] + math.cos(yaw_rad + half) * max_r), float(origin_xy[1] + math.sin(yaw_rad + half) * max_r))
        poly = Polygon([p1, p2, p3])
    return poly


def compute_placement_advisor(cameras: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Evaluate pairwise stereo baseline distance & convergence angle between fixed cameras.

    Args:
        cameras: Sequence of camera descriptors containing ``camera_id``, ``camera_name``,
            and ``calibration`` (``OverwatchCalibration`` or dict).

    Returns:
        Placement advisory dictionary with ``rating``, ``best_angle_deg``, ``baseline_m``,
        ``estimated_gdop``, ``pair``, and human-readable ``recommendation``.
    """
    fixed = [c for c in cameras if str(c.get("camera_id", "")) != "puppypi_fpv"]
    if len(fixed) < 2:
        return {
            "rating": "SINGLE_VIEW",
            "best_angle_deg": 0.0,
            "baseline_m": 0.0,
            "estimated_gdop": 9.9,
            "pair": [],
            "recommendation": "Connect a second camera (e.g. 4K USB + MacBook Cam) to unlock stereo 3D triangulation.",
        }

    best: Optional[Dict[str, Any]] = None
    best_score = -1.0

    for i in range(len(fixed)):
        for j in range(i + 1, len(fixed)):
            c1, c2 = fixed[i], fixed[j]
            cal1 = c1["calibration"]
            cal2 = c2["calibration"]
            x1 = float(cal1.x_m if isinstance(cal1, OverwatchCalibration) else cal1["x_m"])
            y1 = float(cal1.y_m if isinstance(cal1, OverwatchCalibration) else cal1["y_m"])
            yaw1 = math.radians(float(cal1.yaw_deg if isinstance(cal1, OverwatchCalibration) else cal1["yaw_deg"]))
            x2 = float(cal2.x_m if isinstance(cal2, OverwatchCalibration) else cal2["x_m"])
            y2 = float(cal2.y_m if isinstance(cal2, OverwatchCalibration) else cal2["y_m"])
            yaw2 = math.radians(float(cal2.yaw_deg if isinstance(cal2, OverwatchCalibration) else cal2["yaw_deg"]))

            baseline_m = math.hypot(x2 - x1, y2 - y1)
            # Optical-axis convergence angle (0..180 deg)
            v1 = np.array([math.cos(yaw1), math.sin(yaw1)], dtype=np.float64)
            v2 = np.array([math.cos(yaw2), math.sin(yaw2)], dtype=np.float64)
            cos_a = max(-1.0, min(1.0, float(np.dot(v1, v2))))
            angle_deg = math.degrees(math.acos(cos_a))
            # Also account for baseline parallax toward room center (0, 0)
            to_origin1 = np.array([-x1, -y1], dtype=np.float64)
            to_origin2 = np.array([-x2, -y2], dtype=np.float64)
            n1 = float(np.linalg.norm(to_origin1))
            n2 = float(np.linalg.norm(to_origin2))
            if n1 > 0.1 and n2 > 0.1:
                parallax_cos = max(-1.0, min(1.0, float(np.dot(to_origin1 / n1, to_origin2 / n2))))
                parallax_deg = math.degrees(math.acos(parallax_cos))
                effective_angle = max(angle_deg, parallax_deg)
            else:
                effective_angle = angle_deg

            sin_eff = max(0.08, math.sin(math.radians(min(172.0, max(8.0, effective_angle)))))
            est_gdop = round(min(9.9, 1.0 / sin_eff), 2)
            # Score peaks at 90 degrees with decent baseline
            score = sin_eff * min(1.5, max(0.2, baseline_m))
            if score > best_score:
                best_score = score
                best = {
                    "angle_deg": round(effective_angle, 1),
                    "baseline_m": round(baseline_m, 2),
                    "estimated_gdop": est_gdop,
                    "pair": [str(c1["camera_id"]), str(c2["camera_id"])],
                }

    assert best is not None
    ang = best["angle_deg"]
    base = best["baseline_m"]
    if 55.0 <= ang <= 125.0 and base >= 0.6:
        rating = "OPTIMAL"
        rec = f"Optimal {ang:.0f}° cross-angle ({base:.2f} m baseline, GDOP ~{best['estimated_gdop']}). High-precision 3D lock active."
    elif 30.0 <= ang <= 150.0 and base >= 0.35:
        rating = "GOOD"
        rec = f"Good {ang:.0f}° stereo angle ({base:.2f} m baseline). Spreading cameras slightly wider improves depth precision."
    elif 15.0 <= ang < 30.0 or (150.0 < ang <= 165.0):
        rating = "FAIR"
        rec = f"Narrow {ang:.0f}° stereo angle ({base:.2f} m baseline, GDOP ~{best['estimated_gdop']}). Move one camera 0.8–1.5 m sideways for a cleaner 60°–90° crossfire."
    else:
        rating = "POOR"
        rec = f"Nearly collinear {ang:.0f}° view ({base:.2f} m baseline, GDOP ~{best['estimated_gdop']}). Depth error is elongated — separate cameras across two walls or desk corners."

    return {
        "rating": rating,
        "best_angle_deg": ang,
        "baseline_m": base,
        "estimated_gdop": best["estimated_gdop"],
        "pair": best["pair"],
        "recommendation": rec,
    }


def compute_coverage_overlap_zones(
    cameras: Sequence[Dict[str, Any]],
    room_bounds: Optional[Tuple[float, float, float, float]] = None,
    max_range_m: float = 6.0,
) -> Dict[str, Any]:
    """Compute per-camera frustums and exact 0/1/2/3+ sensor overlap polygons using Shapely.

    Args:
        cameras: Sequence of camera dicts with ``camera_id``, ``camera_name``, ``online``,
            ``calibration`` (``OverwatchCalibration``), and optional ``width``/``height``.
        room_bounds: Optional ``(min_x, min_y, max_x, max_y)`` tactical area in meters
            used to compute 0-camera dead zones (defaults to ``(-4.0, -4.0, 4.0, 4.0)``).
        max_range_m: Maximum frustum reach in meters.

    Returns:
        Dictionary containing ``frustums``, ``zones`` (``dead_0``, ``mono_1``, ``stereo_2``,
        ``fusion_3plus``), ``metrics`` (areas in ``m²`` and coverage percentages), and
        ``placement_advisor``.
    """
    bounds = room_bounds or (-4.0, -4.0, 4.0, 4.0)
    arena = box(float(bounds[0]), float(bounds[1]), float(bounds[2]), float(bounds[3]))

    frustums_out: List[Dict[str, Any]] = []
    polys: List[Polygon] = []

    for idx, cam in enumerate(cameras):
        cid = str(cam.get("camera_id") or f"cam_{idx}")
        cal = cam["calibration"]
        if not isinstance(cal, OverwatchCalibration):
            cal = OverwatchCalibration(**{k: v for k, v in cal.items() if hasattr(OverwatchCalibration, k)})
        w = int(cam.get("width") or 1280)
        h = int(cam.get("height") or 720)
        poly = compute_camera_frustum_polygon(cal, max_range_m=max_range_m, width=w, height=h)
        clipped = poly.intersection(arena)
        if not clipped.is_empty:
            polys.append(clipped)
        frustums_out.append(
            {
                "camera_id": cid,
                "camera_name": str(cam.get("camera_name") or cid),
                "online": bool(cam.get("online", False)),
                "origin_xy": [round(float(cal.x_m), 3), round(float(cal.y_m), 3)],
                "yaw_deg": round(float(cal.yaw_deg), 1),
                "color": CAMERA_COLORS.get(cid, "#38bdf8"),
                "area_m2": round(float(clipped.area), 2),
                "polygons": _extract_polygon_rings(clipped),
            }
        )

    # Exact inclusion-exclusion decomposition by coverage multiplicity
    union_all = unary_union(polys) if polys else Polygon()
    dead_geom = arena.difference(union_all) if not union_all.is_empty else arena

    # Pairwise intersections (covered by >= 2 cameras)
    pair_intersections = []
    for i in range(len(polys)):
        for j in range(i + 1, len(polys)):
            inter = polys[i].intersection(polys[j])
            if not inter.is_empty:
                pair_intersections.append(inter)
    ge2_geom = unary_union(pair_intersections) if pair_intersections else Polygon()

    # Triple intersections (covered by >= 3 cameras)
    triple_intersections = []
    for i in range(len(polys)):
        for j in range(i + 1, len(polys)):
            for k in range(j + 1, len(polys)):
                inter = polys[i].intersection(polys[j]).intersection(polys[k])
                if not inter.is_empty:
                    triple_intersections.append(inter)
    ge3_geom = unary_union(triple_intersections) if triple_intersections else Polygon()

    mono_geom = union_all.difference(ge2_geom) if not union_all.is_empty else Polygon()
    stereo_geom = ge2_geom.difference(ge3_geom) if not ge2_geom.is_empty else Polygon()

    total_area = max(1e-6, float(arena.area))
    dead_area = float(dead_geom.area)
    mono_area = float(mono_geom.area)
    stereo_area = float(stereo_geom.area)
    fusion_area = float(ge3_geom.area)
    covered_pct = round(100.0 * (1.0 - (dead_area / total_area)), 1)
    overlap_pct = round(100.0 * ((stereo_area + fusion_area) / total_area), 1)

    return {
        "room_bounds": [round(float(v), 2) for v in bounds],
        "frustums": frustums_out,
        "zones": {
            "dead_0": {"area_m2": round(dead_area, 2), "polygons": _extract_polygon_rings(dead_geom)},
            "mono_1": {"area_m2": round(mono_area, 2), "polygons": _extract_polygon_rings(mono_geom)},
            "stereo_2": {"area_m2": round(stereo_area, 2), "polygons": _extract_polygon_rings(stereo_geom)},
            "fusion_3plus": {"area_m2": round(fusion_area, 2), "polygons": _extract_polygon_rings(ge3_geom)},
        },
        "metrics": {
            "arena_area_m2": round(total_area, 2),
            "dead_area_m2": round(dead_area, 2),
            "mono_area_m2": round(mono_area, 2),
            "stereo_area_m2": round(stereo_area, 2),
            "fusion_area_m2": round(fusion_area, 2),
            "covered_pct": covered_pct,
            "overlap_pct": overlap_pct,
        },
        "placement_advisor": compute_placement_advisor(cameras),
    }


def _rotation_to_world_yaw_pitch(r_cam_to_world: np.ndarray) -> Tuple[float, float]:
    """Extract TwinScan world ``(yaw_deg, pitch_deg)`` from a camera-to-world rotation matrix.

    OpenCV camera convention: ``+X`` right, ``+Y`` down, ``+Z`` forward (optical axis).
    TwinScan world convention: ``+X`` right, ``+Y`` forward, ``+Z`` up.
    """
    forward_world = r_cam_to_world @ np.array([0.0, 0.0, 1.0], dtype=np.float64)
    norm = float(np.linalg.norm(forward_world))
    if norm < 1e-9:
        return 90.0, -20.0
    fwd = forward_world / norm
    pitch_deg = math.degrees(math.asin(max(-1.0, min(1.0, float(fwd[2])))))
    yaw_deg = math.degrees(math.atan2(float(fwd[1]), float(fwd[0])))
    return round(yaw_deg, 2), round(max(-85.0, min(85.0, pitch_deg)), 2)


def calibrate_camera_apriltag_pnp(
    frame_bgr: np.ndarray,
    cal: OverwatchCalibration,
    tag_size_m: float = 0.12,
    tag_world_xyz: Tuple[float, float, float] = (0.0, 0.0, 0.0),
    tag_world_yaw_deg: float = 0.0,
    target_tag_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Auto-solve 6-DOF camera extrinsics from a visible AprilTag (``DICT_APRILTAG_36h11``) via ``cv2.solvePnP``.

    Assumes the tag lies flat on the horizontal plane ``z = tag_world_xyz[2]`` centered
    at ``tag_world_xyz`` with its top edge facing ``tag_world_yaw_deg``.

    Args:
        frame_bgr: Decoded BGR camera frame.
        cal: Existing camera calibration (supplies FOV intrinsics).
        tag_size_m: Physical side length of the printed AprilTag in meters.
        tag_world_xyz: World coordinates ``(x, y, z)`` of the tag center in meters.
        tag_world_yaw_deg: World azimuth of the tag in degrees.
        target_tag_id: Optional specific AprilTag ID to lock onto (defaults to first detected).

    Returns:
        Dictionary with ``ok``, ``tag_id``, ``calibration`` updates, and ``reprojection_error_px``.

    Raises:
        ValueError: If no matching AprilTag is visible or ``solvePnP`` fails.
    """
    if frame_bgr is None or frame_bgr.size == 0:
        raise ValueError("Empty camera frame; cannot run AprilTag auto-calibration.")
    h, w = frame_bgr.shape[:2]
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
    detector = cv2.aruco.ArucoDetector(aruco_dict, cv2.aruco.DetectorParameters())
    corners, ids, _ = detector.detectMarkers(gray)
    if ids is None or len(ids) == 0:
        raise ValueError("No AprilTag (36h11) detected in frame. Place a printed AprilTag in view or use 4-Point Floor Click calibration.")

    chosen_idx = 0
    chosen_id = int(np.asarray(ids[0]).ravel()[0])
    if target_tag_id is not None:
        found = False
        for i, tid_arr in enumerate(ids):
            tid = int(np.asarray(tid_arr).ravel()[0])
            if tid == int(target_tag_id):
                chosen_idx = i
                chosen_id = tid
                found = True
                break
        if not found:
            raise ValueError(f"AprilTag #{target_tag_id} not found in frame.")

    img_pts = corners[chosen_idx][0].astype(np.float64)  # shape (4, 2): TL, TR, BR, BL
    half = max(0.02, float(tag_size_m)) * 0.5
    # Local flat tag corners on z=0: TL(-h,+h), TR(+h,+h), BR(+h,-h), BL(-h,-h)
    local_pts = np.array(
        [
            [-half, half, 0.0],
            [half, half, 0.0],
            [half, -half, 0.0],
            [-half, -half, 0.0],
        ],
        dtype=np.float64,
    )
    cy = math.cos(math.radians(float(tag_world_yaw_deg)))
    sy = math.sin(math.radians(float(tag_world_yaw_deg)))
    rot_z = np.array([[cy, -sy, 0.0], [sy, cy, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64)
    world_pts = (local_pts @ rot_z.T) + np.array(tag_world_xyz, dtype=np.float64)

    K = build_camera_matrix(w, h, cal.hfov_deg, cal.vfov_deg)
    dist = np.zeros((4, 1), dtype=np.float64)

    ok, rvec, tvec = cv2.solvePnP(world_pts, img_pts, K, dist, flags=cv2.SOLVEPNP_IPPE_SQUARE)
    if not ok:
        ok, rvec, tvec = cv2.solvePnP(world_pts, img_pts, K, dist, flags=cv2.SOLVEPNP_ITERATIVE)
    if not ok:
        raise ValueError("cv2.solvePnP failed to converge on detected AprilTag corners.")

    R_w2c, _ = cv2.Rodrigues(rvec)
    R_c2w = R_w2c.T
    cam_pos = (-R_c2w @ tvec.reshape(3, 1)).ravel()
    yaw_deg, pitch_deg = _rotation_to_world_yaw_pitch(R_c2w)

    proj, _ = cv2.projectPoints(world_pts, rvec, tvec, K, dist)
    reproj_err = float(np.mean(np.linalg.norm(proj.reshape(-1, 2) - img_pts, axis=1)))

    return {
        "ok": True,
        "method": "apriltag_pnp",
        "tag_id": chosen_id,
        "reprojection_error_px": round(reproj_err, 2),
        "calibration": {
            "x_m": round(float(cam_pos[0]), 4),
            "y_m": round(float(cam_pos[1]), 4),
            "z_m": round(max(0.1, float(cam_pos[2])), 4),
            "yaw_deg": yaw_deg,
            "pitch_deg": pitch_deg,
        },
    }


def calibrate_camera_four_point_homography(
    pixel_points_norm: Sequence[Sequence[float]],
    world_points_xy: Sequence[Sequence[float]],
    width: int,
    height: int,
    cal: OverwatchCalibration,
) -> Dict[str, Any]:
    """Calibrate a camera from 4+ clicked floor points via ``cv2.findHomography`` + ``cv2.solvePnP``.

    Requires zero printed tags: the operator clicks 4 known floor coordinates on the camera
    feed and pairs them with ``(x, y)`` world coordinates on the BEV floor map.

    Args:
        pixel_points_norm: Sequence of 4+ normalized image coordinates ``[u_norm, v_norm]`` in ``[0, 1]``.
        world_points_xy: Sequence of 4+ corresponding floor points ``[x_m, y_m]`` on ``z = 0``.
        width: Image width in pixels.
        height: Image height in pixels.
        cal: Existing camera calibration (supplies FOV intrinsics).

    Returns:
        Dictionary containing solved 6-DOF ``calibration``, ``homography_3x3`` (normalized
        image ``[u_norm, v_norm, 1]`` -> world floor ``[x, y, 1]``), and ``reprojection_error_px``.

    Raises:
        ValueError: If fewer than 4 points are provided, points are degenerate/collinear, or solving fails.
    """
    if len(pixel_points_norm) < 4 or len(world_points_xy) < 4:
        raise ValueError("At least 4 matched floor points are required for homography calibration.")
    if len(pixel_points_norm) != len(world_points_xy):
        raise ValueError("pixel_points_norm and world_points_xy must have the same length.")

    w = max(2, int(width))
    h = max(2, int(height))
    norm_pts = np.array([[float(p[0]), float(p[1])] for p in pixel_points_norm], dtype=np.float64)
    img_pts = np.column_stack([norm_pts[:, 0] * w, norm_pts[:, 1] * h])
    world_xy = np.array([[float(p[0]), float(p[1])] for p in world_points_xy], dtype=np.float64)
    world_3d = np.column_stack([world_xy, np.zeros((len(world_xy), 1), dtype=np.float64)])

    # Verify non-collinearity of world points
    hull_area = Polygon(world_xy.tolist()).convex_hull.area
    if hull_area < 0.02:
        raise ValueError("World floor points are too close or collinear (area < 0.02 m²). Spread the 4 points wider.")

    # 1) Exact planar homography: normalized image coords -> world floor XY
    H_norm_to_world, _ = cv2.findHomography(norm_pts, world_xy, method=0)
    if H_norm_to_world is None or not np.all(np.isfinite(H_norm_to_world)):
        raise ValueError("Failed to compute planar homography from the supplied 4 points.")

    # 2) Solve 6-DOF extrinsics via solvePnP (planar IPPE or EPNP -> iterative refinement)
    K = build_camera_matrix(w, h, cal.hfov_deg, cal.vfov_deg)
    dist = np.zeros((4, 1), dtype=np.float64)
    ok = False
    rvec = None
    tvec = None
    for flag in (cv2.SOLVEPNP_IPPE, cv2.SOLVEPNP_EPNP, cv2.SOLVEPNP_ITERATIVE):
        try:
            ok, rvec, tvec = cv2.solvePnP(world_3d, img_pts, K, dist, flags=flag)
            if ok:
                break
        except Exception:
            continue
    if not ok or rvec is None or tvec is None:
        raise ValueError("cv2.solvePnP failed to recover 6-DOF camera pose from the 4 floor points.")

    # Refine with Levenberg-Marquardt / iterative
    try:
        ok_ref, rvec_ref, tvec_ref = cv2.solvePnP(
            world_3d, img_pts, K, dist, rvec=rvec, tvec=tvec, useExtrinsicGuess=True, flags=cv2.SOLVEPNP_ITERATIVE
        )
        if ok_ref:
            rvec, tvec = rvec_ref, tvec_ref
    except Exception as exc:
        sys.stderr.write(f"[overwatch.homography] PnP refinement warning: {exc}\n")

    R_w2c, _ = cv2.Rodrigues(rvec)
    R_c2w = R_w2c.T
    cam_pos = (-R_c2w @ tvec.reshape(3, 1)).ravel()
    # If planar PnP picked the mirrored below-floor solution (z < 0), flip z sign cleanly
    if cam_pos[2] < 0.05:
        cam_pos[2] = abs(float(cam_pos[2])) if abs(float(cam_pos[2])) >= 0.1 else max(0.3, float(cal.z_m))
    yaw_deg, pitch_deg = _rotation_to_world_yaw_pitch(R_c2w)
    if pitch_deg > 10.0:
        pitch_deg = -abs(pitch_deg)

    proj, _ = cv2.projectPoints(world_3d, rvec, tvec, K, dist)
    reproj_err = float(np.mean(np.linalg.norm(proj.reshape(-1, 2) - img_pts, axis=1)))

    return {
        "ok": True,
        "method": "four_point_homography",
        "reprojection_error_px": round(reproj_err, 2),
        "homography_3x3": [[round(float(val), 6) for val in row] for row in H_norm_to_world.tolist()],
        "calibration": {
            "x_m": round(float(cam_pos[0]), 4),
            "y_m": round(float(cam_pos[1]), 4),
            "z_m": round(max(0.1, float(cam_pos[2])), 4),
            "yaw_deg": yaw_deg,
            "pitch_deg": pitch_deg,
        },
    }


def project_pixel_to_task_waypoint(
    u_norm: float,
    v_norm: float,
    cal: OverwatchCalibration,
    width: int = 1280,
    height: int = 720,
    homography_3x3: Optional[Sequence[Sequence[float]]] = None,
    robot_pose: Optional[Dict[str, Any]] = None,
    standoff_m: float = 0.30,
    max_dispatch_m: float = 6.0,
) -> Dict[str, Any]:
    """Project a clicked camera pixel to a world floor coordinate & safe PuppyPi dispatch vector.

    Args:
        u_norm: Normalized horizontal pixel coordinate in ``[0, 1]``.
        v_norm: Normalized vertical pixel coordinate in ``[0, 1]``.
        cal: Camera calibration.
        width: Image width in pixels.
        height: Image height in pixels.
        homography_3x3: Optional stored 3x3 normalized-image-to-world-floor homography.
        robot_pose: Optional current robot pose ``{x, y, yaw_deg}`` for relative turn/walk vector.
        standoff_m: Safe approach standoff distance in meters.
        max_dispatch_m: Maximum allowable floor projection radius in meters.

    Returns:
        Dictionary with ``target_xy``, ``waypoint_xy``, ``projection_method``,
        ``relative_turn_deg``, and ``walk_distance_m``.

    Raises:
        ValueError: If the clicked ray points above the horizon with no floor intersection.
    """
    u_c = max(0.0, min(1.0, float(u_norm)))
    v_c = max(0.0, min(1.0, float(v_norm)))

    tx: float
    ty: float
    method = "pinhole_ray"

    if homography_3x3 is not None:
        H = np.asarray(homography_3x3, dtype=np.float64)
        if H.shape == (3, 3):
            p = H @ np.array([u_c, v_c, 1.0], dtype=np.float64)
            if abs(float(p[2])) > 1e-8:
                tx = float(p[0] / p[2])
                ty = float(p[1] / p[2])
                method = "homography_4pt"
            else:
                homography_3x3 = None

    if method == "pinhole_ray":
        origin, direction = pixel_to_world_ray(u_c * width, v_c * height, width, height, cal)
        hit = intersect_ray_ground_plane(origin, direction, z_plane=0.0)
        if hit is None:
            raise ValueError("Clicked pixel points at or above the horizon (no floor intersection). Click lower in the frame.")
        tx, ty = float(hit["x"]), float(hit["y"])

    # Clamp to safe tactical radius from camera origin
    dx_cam = tx - float(cal.x_m)
    dy_cam = ty - float(cal.y_m)
    dist_cam = math.hypot(dx_cam, dy_cam)
    if dist_cam > max_dispatch_m and dist_cam > 1e-6:
        scale = max_dispatch_m / dist_cam
        tx = float(cal.x_m) + dx_cam * scale
        ty = float(cal.y_m) + dy_cam * scale

    rx = float((robot_pose or {}).get("x") or 0.0)
    ry = float((robot_pose or {}).get("y") or 0.0)
    ryaw = float((robot_pose or {}).get("yaw_deg") or 0.0)

    dx_r = tx - rx
    dy_r = ty - ry
    dist_r = math.hypot(dx_r, dy_r)
    walk_dist = max(0.0, dist_r - max(0.0, float(standoff_m)))
    if dist_r > 1e-4:
        wx = rx + (dx_r / dist_r) * walk_dist
        wy = ry + (dy_r / dist_r) * walk_dist
        target_heading = math.degrees(math.atan2(dy_r, dx_r))
    else:
        wx, wy = rx, ry
        target_heading = ryaw

    rel_turn = ((target_heading - ryaw + 180.0) % 360.0) - 180.0
    return {
        "target_xy": [round(tx, 3), round(ty, 3)],
        "waypoint_xy": [round(wx, 3), round(wy, 3)],
        "projection_method": method,
        "distance_from_robot_m": round(dist_r, 3),
        "walk_distance_m": round(walk_dist, 3),
        "target_heading_deg": round(target_heading, 1),
        "relative_turn_deg": round(rel_turn, 1),
    }
