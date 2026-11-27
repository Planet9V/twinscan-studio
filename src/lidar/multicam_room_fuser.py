"""Multi-Camera + LD19 LiDAR High-Resolution 3D Room Digital Twin Fuser.

Combines synchronized live frames from ALL active cameras:
- ``usb_4k`` (1920x1080 / QHD external overhead webcam)
- ``macbook_cam`` (1920x1080 cross-angle flanking camera)
- ``puppypi_fpv`` (640x480 low-altitude mobile ground scout)
anchored to live **LD19 360° LiDAR** rays via **Depth Anything V2 Small ONNX**,
merges them into a single multi-material textured ``.glb`` Digital Twin, and
provides Shapely blind-spot patrol waypoint suggestion.
"""

from __future__ import annotations

import io
import math
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from shapely.geometry import Point, Polygon
import trimesh

from src.lidar.scene_reconstructor import reconstruct_wall_panel
from src.vision.overwatch_triangulator import OverwatchCameraManager


def _transform_lidar_to_camera_frame(
    lidar_points_xy: Sequence[Tuple[float, float]],
    robot_xy: Tuple[float, float],
    cam_x: float,
    cam_y: float,
    cam_yaw_deg: float,
) -> List[Tuple[float, float]]:
    """Transform room-frame LD19 LiDAR points into a fixed camera's local forward/left frame.

    Args:
        lidar_points_xy: Live LiDAR 2D points relative to PuppyPi ``(lx, ly)``.
        robot_xy: PuppyPi world position ``(rx, ry)`` in meters.
        cam_x: Camera world X coordinate in meters.
        cam_y: Camera world Y coordinate in meters.
        cam_yaw_deg: Camera world azimuth in degrees (``0° = +X``, ``90° = +Y``).

    Returns:
        List of ``(local_x, local_y)`` points in the camera's local frame (``+X`` forward).
    """
    if not lidar_points_xy:
        return []
    rx, ry = float(robot_xy[0]), float(robot_xy[1])
    yaw_rad = math.radians(float(cam_yaw_deg))
    c = math.cos(-yaw_rad)
    s = math.sin(-yaw_rad)
    out: List[Tuple[float, float]] = []
    for lx, ly in lidar_points_xy:
        wx = rx + float(lx) - float(cam_x)
        wy = ry + float(ly) - float(cam_y)
        cx = wx * c - wy * s
        cy = wx * s + wy * c
        if cx > 0.15 and math.hypot(cx, cy) <= 10.0:
            out.append((cx, cy))
    return out


def fuse_multicam_room_digital_twin(
    overwatch_manager: OverwatchCameraManager,
    runtime: Any = None,
    repo: Any = None,
    space_id: Optional[str] = None,
    puppypi_jpeg: Optional[bytes] = None,
    resolution: str = "medium",
    allow_model_download: bool = True,
    camera_ids: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Fuse all active Overwatch cameras + optional PuppyPi FPV + LD19 LiDAR into one 3D ``.glb``.

    Args:
        overwatch_manager: Active ``OverwatchCameraManager`` holding calibrated camera slots.
        runtime: Optional ``TwinScanRuntimeState`` supplying live LD19 points & robot pose.
        repo: Optional ``TwinRepositoryProtocol`` to persist the combined ``.glb`` in PostgreSQL 18.
        space_id: Optional active space UUID for PostgreSQL file attachment.
        puppypi_jpeg: Optional fresh JPEG bytes from PuppyPi's mobile FPV camera.
        resolution: Mesh density (``"low"``, ``"medium"``, ``"high"``).
        allow_model_download: Whether Depth Anything V2 ONNX may auto-download if absent.

    Returns:
        Summary dictionary with ``ok``, ``cameras_fused``, ``total_vertices``, ``total_triangles``,
        ``glb_bytes_len``, ``glb_file_id``, and per-camera reconstruction metadata.

    Raises:
        ValueError: If no live cameras are available to fuse.
    """
    status = overwatch_manager.get_status()
    cameras_map = status.get("cameras") or {}

    robot_pose = getattr(runtime, "robot_pose", None) if runtime is not None else None
    rx = float((robot_pose or {}).get("x") or 0.0)
    ry = float((robot_pose or {}).get("y") or 0.0)
    ryaw = float((robot_pose or {}).get("yaw_deg") or 0.0)
    raw_pts = getattr(runtime, "latest_points", None) if runtime is not None else None
    lidar_xy: List[Tuple[float, float]] = [
        (float(getattr(p, "x", 0.0)), float(getattr(p, "y", 0.0)))
        for p in (raw_pts or [])
        if math.isfinite(float(getattr(p, "x", 0.0))) and math.isfinite(float(getattr(p, "y", 0.0)))
    ]

    combined_scene = trimesh.Scene()
    fused_entries: List[Dict[str, Any]] = []
    total_verts = 0
    total_tris = 0

    # 1) Reconstruct each online Overwatch fixed camera (usb_4k, macbook_cam, pi5_4k, pi4_cam, ...)
    allowed_cids = set(camera_ids) if camera_ids else None
    for cid, meta in cameras_map.items():
        if not meta.get("online"):
            continue
        if allowed_cids is not None and cid not in allowed_cids:
            continue
        cal = meta.get("calibration") or {}
        cam_space = cal.get("space_id")
        if space_id and cam_space and str(cam_space) != str(space_id):
            continue
        raw_jpeg = overwatch_manager.get_raw_frame_jpeg(camera_id=cid)
        if not raw_jpeg:
            continue
        cam_x = float(cal.get("x_m", 0.0))
        cam_y = float(cal.get("y_m", -2.2))
        cam_z = float(cal.get("z_m", 1.4))
        cam_yaw = float(cal.get("yaw_deg", 90.0))
        cam_pitch = float(cal.get("pitch_deg", -20.0))
        hfov = float(cal.get("hfov_deg", 78.0))
        vfov = float(cal.get("vfov_deg", 48.0))

        cam_lidar = _transform_lidar_to_camera_frame(lidar_xy, (rx, ry), cam_x, cam_y, cam_yaw)
        try:
            res_dict, glb_bytes = reconstruct_wall_panel(
                jpeg_bytes=raw_jpeg,
                lidar_points_xy=cam_lidar if len(cam_lidar) >= 4 else None,
                pose={
                    "x": cam_x,
                    "y": cam_y,
                    "z": cam_z,
                    "yaw_deg": cam_yaw,
                    "pitch_deg": cam_pitch,
                    "roll_deg": 0.0,
                },
                resolution=resolution,
                fallback_distance_m=2.4,
                hfov_deg=hfov,
                vfov_deg=vfov,
                allow_model_download=allow_model_download,
            )
            sub_scene = trimesh.load(io.BytesIO(glb_bytes), file_type="glb")
            if isinstance(sub_scene, trimesh.Scene):
                for gname, geom in sub_scene.geometry.items():
                    combined_scene.add_geometry(geom, node_name=f"{cid}_{gname}", geom_name=f"{cid}_{gname}")
            elif isinstance(sub_scene, trimesh.Trimesh):
                combined_scene.add_geometry(sub_scene, node_name=cid, geom_name=cid)

            vc = int(res_dict.get("vertex_count") or 0)
            tc = int(res_dict.get("triangle_count") or 0)
            total_verts += vc
            total_tris += tc
            fused_entries.append(
                {
                    "camera_id": cid,
                    "camera_name": str(meta.get("camera_name") or cid),
                    "resolution_px": f"{meta.get('width', 0)}x{meta.get('height', 0)}",
                    "lidar_calibrated": bool(res_dict.get("lidar_calibrated", False)),
                    "vertex_count": vc,
                    "triangle_count": tc,
                    "depth_source": res_dict.get("depth_source", "unknown"),
                }
            )
        except Exception as exc:
            sys.stderr.write(f"[multicam_fuser] Camera {cid} reconstruction skipped: {exc}\n")

    # 2) Optionally fuse PuppyPi's live mobile FPV camera for low-altitude ground detail
    if puppypi_jpeg:
        try:
            res_dict, glb_bytes = reconstruct_wall_panel(
                jpeg_bytes=puppypi_jpeg,
                lidar_points_xy=lidar_xy if len(lidar_xy) >= 4 else None,
                pose={"x": rx, "y": ry, "z": 0.22, "yaw_deg": ryaw, "pitch_deg": 0.0, "roll_deg": 0.0},
                resolution=resolution,
                fallback_distance_m=1.6,
                hfov_deg=65.0,
                vfov_deg=50.0,
                allow_model_download=allow_model_download,
            )
            sub_scene = trimesh.load(io.BytesIO(glb_bytes), file_type="glb")
            if isinstance(sub_scene, trimesh.Scene):
                for gname, geom in sub_scene.geometry.items():
                    combined_scene.add_geometry(geom, node_name=f"puppypi_{gname}", geom_name=f"puppypi_{gname}")
            elif isinstance(sub_scene, trimesh.Trimesh):
                combined_scene.add_geometry(sub_scene, node_name="puppypi_fpv", geom_name="puppypi_fpv")
            vc = int(res_dict.get("vertex_count") or 0)
            tc = int(res_dict.get("triangle_count") or 0)
            total_verts += vc
            total_tris += tc
            fused_entries.append(
                {
                    "camera_id": "puppypi_fpv",
                    "camera_name": "PuppyPi Mobile FPV",
                    "resolution_px": "640x480",
                    "lidar_calibrated": bool(res_dict.get("lidar_calibrated", False)),
                    "vertex_count": vc,
                    "triangle_count": tc,
                    "depth_source": res_dict.get("depth_source", "unknown"),
                }
            )
        except Exception as exc:
            sys.stderr.write(f"[multicam_fuser] PuppyPi FPV reconstruction skipped: {exc}\n")

    if not fused_entries:
        raise ValueError("No online cameras were available to fuse into a 3D Digital Twin.")

    merged_glb = combined_scene.export(file_type="glb")
    glb_bytes_out = bytes(merged_glb) if isinstance(merged_glb, (bytes, bytearray)) else b""

    glb_file_id: Optional[str] = None
    if repo is not None and glb_bytes_out:
        try:
            stored = repo.store_file(
                filename="multicam_digital_twin.glb",
                content_type="model/gltf-binary",
                data=glb_bytes_out,
                category="reconstruction_glb",
                space_id=space_id,
                metadata={
                    "kind": "multicam_digital_twin",
                    "cameras_fused": [e["camera_id"] for e in fused_entries],
                    "total_vertices": total_verts,
                    "total_triangles": total_tris,
                    "lidar_points": len(lidar_xy),
                },
            )
            glb_file_id = str(stored.get("id") or "")
        except Exception as exc:
            sys.stderr.write(f"[multicam_fuser] Failed to store merged GLB in DB: {exc}\n")

    return {
        "ok": True,
        "cameras_fused": fused_entries,
        "camera_count": len(fused_entries),
        "lidar_points_used": len(lidar_xy),
        "total_vertices": total_verts,
        "total_triangles": total_tris,
        "glb_bytes_len": len(glb_bytes_out),
        "glb_file_id": glb_file_id,
        "download_url": f"/api/files/{glb_file_id}/download" if glb_file_id else None,
    }


def suggest_blind_spot_mapping_route(
    geometry_snapshot: Dict[str, Any],
    max_waypoints: int = 4,
    safe_radius_m: float = 2.2,
) -> Dict[str, Any]:
    """Generate safe, conservative patrol waypoints targeting 0-camera blind spots & mono zones.

    Args:
        geometry_snapshot: Output from ``OverwatchCameraManager.get_geometry_snapshot()``.
        max_waypoints: Maximum number of waypoints to emit (clamped to ``[2, 6]``).
        safe_radius_m: Maximum radial distance from origin ``(0, 0)`` for safe indoor travel.

    Returns:
        Dictionary with ``waypoints`` (``[{x, y, pause_sec, reason}]``) and ``summary``.
    """
    limit = max(2, min(6, int(max_waypoints)))
    radius = max(0.8, min(4.0, float(safe_radius_m)))
    zones = geometry_snapshot.get("zones") or {}

    candidates: List[Tuple[float, float, str]] = []
    for tier_key, reason_label in (("dead_0", "0-cam blind spot"), ("mono_1", "1-cam mono fill")):
        rings = (zones.get(tier_key) or {}).get("polygons") or []
        for ring in rings:
            if len(ring) < 4:
                continue
            try:
                poly = Polygon(ring)
                if not poly.is_valid or poly.area < 0.25:
                    continue
                rep = poly.representative_point()
                cx, cy = float(rep.x), float(rep.y)
                dist = math.hypot(cx, cy)
                if dist > radius and dist > 1e-6:
                    cx = cx * (radius / dist)
                    cy = cy * (radius / dist)
                candidates.append((round(cx, 2), round(cy, 2), reason_label))
            except Exception:
                continue

    # Deduplicate waypoints closer than 0.65m and ensure at least 3 gentle mapping points
    waypoints: List[Dict[str, Any]] = []
    for cx, cy, reason in candidates:
        if len(waypoints) >= limit:
            break
        if any(math.hypot(cx - w["x"], cy - w["y"]) < 0.65 for w in waypoints):
            continue
        waypoints.append({"x": cx, "y": cy, "pause_sec": 1.5, "reason": reason})

    if len(waypoints) < 3:
        fallback = [
            {"x": 0.6, "y": 0.4, "pause_sec": 1.5, "reason": "front-right 3D scan"},
            {"x": -0.6, "y": 0.4, "pause_sec": 1.5, "reason": "front-left 3D scan"},
            {"x": 0.0, "y": 0.0, "pause_sec": 1.5, "reason": "return to origin"},
        ]
        for fb in fallback:
            if len(waypoints) >= min(limit, 3):
                break
            if not any(math.hypot(fb["x"] - w["x"], fb["y"] - w["y"]) < 0.5 for w in waypoints):
                waypoints.append(fb)

    return {
        "ok": True,
        "waypoints": waypoints,
        "summary": f"Generated {len(waypoints)} safe mapping waypoints targeting overhead blind spots & mono coverage zones.",
    }
