"""Stage 3 Autonomous Frontier Explorer, Multi-Angle Pitch/Yaw 3D Mapper & Low-Battery Return-to-Home.

Provides:
- ``compute_battery_pct_2s``: Maps 2S LiPo pack voltage (``6.4V..8.4V``) to ``0..100%``.
- ``build_capture_pose_schedule``: Generates ``(yaw_deg, pitch_deg)`` schedules for
  ``quick_3``, ``level_360``, and ``multi_pitch`` 3D room capture modes.
- ``select_next_dark_zone_frontier``: Picks the highest-priority unvisited Spatial Dark Zone
  Next-Best-View waypoint (supporting both dict and ``SpatialDarkZone`` dataclass inputs).
- ``detect_apriltag_home_in_jpeg``: Optional OpenCV AprilTag ``36h11`` home-dock detector.
- ``compute_room_coverage_pct``: Estimates room coverage percentage from LiDAR room area and dark zones.
- ``AutonomousExplorerManager``: Background per-robot exploration loop combining multi-angle
  3D panel + Spatial Memory capture, VFH collision-free dark-zone frontier transit, and
  continuous 2S LiPo low-battery Return-to-Home (RTH) with safe zero-velocity + ``go_home`` parking.
"""

from __future__ import annotations

import asyncio
import math
import sys
import time
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from src.robot.patrol_engine import (
    compute_vfh_avoidance,
    detect_front_camera_obstacle,
    lidar_points_to_sectors,
)
from src.robot.rosbridge_proxy import call_go_home, publish_pose, publish_velocity


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_battery_pct_2s(battery_v: Optional[float]) -> Optional[int]:
    """Convert a 2S LiPo pack voltage (``6.4V..8.4V``) into an integer percentage ``0..100``.

    Args:
        battery_v: Measured 2S LiPo pack voltage in volts, or ``None`` if unavailable.

    Returns:
        Clamped integer percentage ``0..100``, or ``None`` when input is absent/non-finite.
    """
    if battery_v is None:
        return None
    try:
        v = float(battery_v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    pct = ((v - 6.4) / (8.4 - 6.4)) * 100.0
    return int(round(max(0.0, min(100.0, pct))))


def build_capture_pose_schedule(capture_mode: str = "multi_pitch") -> List[Tuple[float, float]]:
    """Build the ordered ``(yaw_deg, pitch_deg)`` capture schedule for a room-mapping station.

    Args:
        capture_mode: One of ``"quick_3"``, ``"level_360"``, or ``"multi_pitch"``.

    Returns:
        Ordered list of ``(relative_yaw_deg, body_pitch_deg)`` tuples.
    """
    mode = str(capture_mode or "multi_pitch").strip().lower()
    if mode == "quick_3":
        return [(0.0, 0.0), (-45.0, 0.0), (45.0, 0.0)]
    if mode == "level_360":
        return [(float(i * 60), 0.0) for i in range(6)]
    return [
        (0.0, -10.0),
        (0.0, 0.0),
        (0.0, 10.0),
        (60.0, 0.0),
        (120.0, 0.0),
        (180.0, 0.0),
        (240.0, 0.0),
        (300.0, 0.0),
    ]


def _extract_dz_field(dz: Any, key: str, default: Any = None) -> Any:
    if isinstance(dz, dict):
        return dz.get(key, default)
    return getattr(dz, key, default)


def select_next_dark_zone_frontier(
    dark_zones: Sequence[Any],
    visited_xy: Sequence[Tuple[float, float]],
    current_xy: Tuple[float, float],
    min_sep_m: float = 0.55,
) -> Optional[Dict[str, Any]]:
    """Select the highest-priority unvisited Spatial Dark Zone Next-Best-View frontier.

    Supports both ``SpatialDarkZone`` dataclasses (``nbv_x``, ``nbv_y``, ``nbv_yaw_deg``)
    and dictionary representations (flat ``nbv_x``/``nbv_y`` or nested ``next_best_view``).

    Args:
        dark_zones: Current detected dark zones.
        visited_xy: Sequence of already-visited ``(x, y)`` station coordinates in meters.
        current_xy: Robot's current estimated ``(x, y)`` position in meters.
        min_sep_m: Minimum Euclidean separation in meters from any previously visited station.

    Returns:
        Normalized frontier dictionary ``{id, label, kind, priority_score, nbv_x, nbv_y,
        nbv_yaw_deg, centroid_x, centroid_y}``, or ``None`` if no unvisited frontier exists.
    """
    candidates: List[Tuple[int, float, Dict[str, Any]]] = []
    sep = max(0.05, float(min_sep_m))
    cx_cur, cy_cur = float(current_xy[0]), float(current_xy[1])

    for idx, dz in enumerate(dark_zones):
        nbv_obj = _extract_dz_field(dz, "next_best_view", None)
        if isinstance(nbv_obj, dict):
            raw_x = nbv_obj.get("x", _extract_dz_field(dz, "nbv_x"))
            raw_y = nbv_obj.get("y", _extract_dz_field(dz, "nbv_y"))
            raw_yaw = nbv_obj.get("yaw_deg", _extract_dz_field(dz, "nbv_yaw_deg", 0.0))
        else:
            raw_x = _extract_dz_field(dz, "nbv_x")
            raw_y = _extract_dz_field(dz, "nbv_y")
            raw_yaw = _extract_dz_field(dz, "nbv_yaw_deg", 0.0)

        if raw_x is None or raw_y is None:
            raw_x = _extract_dz_field(dz, "centroid_x")
            raw_y = _extract_dz_field(dz, "centroid_y")
        if raw_x is None or raw_y is None:
            continue

        try:
            nx = float(raw_x)
            ny = float(raw_y)
            nyaw = float(raw_yaw or 0.0)
        except (TypeError, ValueError):
            continue
        if not (math.isfinite(nx) and math.isfinite(ny)):
            continue

        too_close = any(math.hypot(nx - float(vx), ny - float(vy)) < sep for vx, vy in visited_xy)
        if too_close:
            continue

        priority = int(_extract_dz_field(dz, "priority_score", 50) or 50)
        dist_from_cur = math.hypot(nx - cx_cur, ny - cy_cur)
        item = {
            "id": str(_extract_dz_field(dz, "id", f"dz-{idx}")),
            "label": str(_extract_dz_field(dz, "label", f"Dark Zone {idx + 1}")),
            "kind": str(_extract_dz_field(dz, "kind", "occlusion_shadow")),
            "priority_score": priority,
            "nbv_x": round(nx, 4),
            "nbv_y": round(ny, 4),
            "nbv_yaw_deg": round(nyaw, 1),
            "centroid_x": round(float(_extract_dz_field(dz, "centroid_x", nx) or nx), 4),
            "centroid_y": round(float(_extract_dz_field(dz, "centroid_y", ny) or ny), 4),
        }
        # Higher priority first; closer frontier breaks ties
        candidates.append((priority, -dist_from_cur, item))

    if not candidates:
        return None
    candidates.sort(key=lambda c: (c[0], c[1]), reverse=True)
    return candidates[0][2]


def detect_apriltag_home_in_jpeg(jpeg_bytes: bytes, target_id: int = 0) -> bool:
    """Detect whether an AprilTag ``36h11`` marker with ID ``target_id`` is visible in a JPEG frame.

    Args:
        jpeg_bytes: Raw JPEG image bytes from the robot camera.
        target_id: Expected AprilTag ID marking the home base (default ``0``).

    Returns:
        ``True`` if the requested AprilTag ``36h11`` ID is detected, else ``False``.
    """
    if not jpeg_bytes:
        return False
    try:
        arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
        if frame is None or frame.size == 0:
            return False
        aruco = getattr(cv2, "aruco", None)
        if aruco is None:
            return False
        dict_id = getattr(aruco, "DICT_APRILTAG_36h11", None)
        if dict_id is None:
            return False
        dictionary = aruco.getPredefinedDictionary(dict_id)
        if hasattr(aruco, "ArucoDetector"):
            detector = aruco.ArucoDetector(dictionary, aruco.DetectorParameters())
            _, ids, _ = detector.detectMarkers(frame)
        else:
            _, ids, _ = aruco.detectMarkers(frame, dictionary)
        if ids is None:
            return False
        return any(int(tag_id) == int(target_id) for tag_id in ids.flatten().tolist())
    except Exception as exc:
        sys.stderr.write(f"[explorer.apriltag] AprilTag detection error: {exc}\n")
        return False


def compute_room_coverage_pct(
    metrics: Optional[Dict[str, Any]],
    dark_zones: Sequence[Any],
    panels_captured: int = 0,
) -> float:
    """Estimate current room scan coverage percentage from LiDAR footprint and Spatial Dark Zones.

    Args:
        metrics: Latest ``compute_room_metrics`` dictionary (containing ``area_m2``).
        dark_zones: Current list of ``SpatialDarkZone`` objects or dicts.
        panels_captured: Number of 3D panels captured in the current session.

    Returns:
        Coverage percentage clamped to ``[0.0, 100.0]`` rounded to 1 decimal place.
    """
    area_m2 = float((metrics or {}).get("area_m2") or 0.0)
    if area_m2 <= 0.05:
        return round(min(95.0, panels_captured * 12.0), 1)
    shadow_area = 0.0
    for dz in dark_zones:
        try:
            shadow_area += max(0.0, float(_extract_dz_field(dz, "area_m2", 0.0) or 0.0))
        except (TypeError, ValueError):
            continue
    ratio = max(0.0, min(1.0, 1.0 - (shadow_area / max(area_m2, 0.5))))
    pct = ratio * 100.0
    if dark_zones:
        pct = min(98.5, pct)
    return round(max(0.0, min(100.0, pct)), 1)


class AutonomousExplorerManager:
    """Manages per-robot Stage 3 Autonomous Frontier Exploration, Multi-Angle Mapping & Low-Battery RTH."""

    def __init__(self) -> None:
        """Initialize per-robot explorer task, RTH trigger, and telemetry registries."""
        self._tasks: Dict[str, asyncio.Task[None]] = {}
        self._rth_flags: Dict[str, bool] = {}
        self._status: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def _default_status(robot_id: str) -> Dict[str, Any]:
        return {
            "robot_id": robot_id,
            "space_id": None,
            "active": False,
            "state": "idle",
            "iteration": 0,
            "max_iterations": 6,
            "coverage_pct": 0.0,
            "target_coverage_pct": 85.0,
            "dark_zones_remaining": 0,
            "panels_captured": 0,
            "objects_identified": 0,
            "battery_v": None,
            "battery_pct": None,
            "rth_battery_v": 7.1,
            "capture_mode": "multi_pitch",
            "quality_preset": "balanced",
            "current_pitch_deg": 0.0,
            "current_yaw_deg": 0.0,
            "home_xy": [0.0, 0.0],
            "current_xy": [0.0, 0.0],
            "target_xy": None,
            "path_xy": [[0.0, 0.0]],
            "apriltag_home_seen": False,
            "lidar_live": False,
            "started_at": None,
            "error": None,
            "event_log": [],
        }

    def _log(self, robot_id: str, level: str, message: str) -> None:
        st = self._status.setdefault(robot_id, self._default_status(robot_id))
        logs: List[Dict[str, str]] = st.setdefault("event_log", [])
        logs.append({"ts": _now_iso(), "level": level, "message": message})
        if len(logs) > 80:
            del logs[:-80]

    def get_status(self, robot_id: str) -> Dict[str, Any]:
        """Return a shallow copy of the current ``ExplorerStatus`` for ``robot_id``."""
        base = self._status.get(robot_id) or self._default_status(robot_id)
        out = dict(base)
        out["home_xy"] = list(base.get("home_xy") or [0.0, 0.0])
        out["current_xy"] = list(base.get("current_xy") or [0.0, 0.0])
        out["target_xy"] = list(base["target_xy"]) if base.get("target_xy") is not None else None
        out["path_xy"] = [list(pt) for pt in (base.get("path_xy") or [])]
        out["event_log"] = [dict(ev) for ev in (base.get("event_log") or [])]
        return out

    def trigger_rth(self, robot_id: str) -> Dict[str, Any]:
        """Request immediate Return-to-Home Base (RTH) for ``robot_id``."""
        self._rth_flags[robot_id] = True
        st = self._status.setdefault(robot_id, self._default_status(robot_id))
        self._log(robot_id, "warn", "Return-to-Home Base (RTH) requested by operator.")
        if st.get("active"):
            st["state"] = "returning_home"
            st["target_xy"] = list(st.get("home_xy") or [0.0, 0.0])
        return self.get_status(robot_id)

    async def stop(
        self,
        robot_id: str,
        ip: Optional[str] = None,
        rosbridge_port: int = 9090,
        ros_version: str = "ros2",
    ) -> Dict[str, Any]:
        """Cancel any active exploration task, publish zero velocity, and reset body pitch to ``0°``."""
        self._rth_flags[robot_id] = False
        task = self._tasks.pop(robot_id, None)
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if ip:
            try:
                await publish_velocity(ip, rosbridge_port, 0.0, 0.0, 0.0, ros_version=ros_version, robot_id=robot_id)
            except Exception as exc:
                sys.stderr.write(f"[explorer] Zero-velocity on stop failed for {robot_id}: {exc}\n")
            try:
                await publish_pose(
                    ip=ip,
                    port=rosbridge_port,
                    pitch=0.0,
                    run_time=350,
                    ros_version=ros_version,
                    robot_id=robot_id,
                )
            except Exception as exc:
                sys.stderr.write(f"[explorer] Pitch reset on stop failed for {robot_id}: {exc}\n")

        st = self._status.setdefault(robot_id, self._default_status(robot_id))
        st["active"] = False
        st["state"] = "stopped"
        st["current_pitch_deg"] = 0.0
        st["target_xy"] = None
        self._log(robot_id, "info", "Explorer stopped safely (velocity=0, pitch=0°).")
        return self.get_status(robot_id)

    async def stop_all(self) -> None:
        """Stop all active autonomous explorer loops on application shutdown."""
        for rid in list(self._tasks.keys()):
            await self.stop(rid)

    async def start(
        self,
        robot_id: str,
        ip: str,
        rosbridge_port: int = 9090,
        ros_version: str = "ros2",
        space_id: Optional[str] = None,
        max_iterations: int = 6,
        target_coverage_pct: float = 85.0,
        capture_mode: str = "multi_pitch",
        quality_preset: str = "balanced",
        rth_battery_v: float = 7.1,
        max_speed_cms: float = 10.0,
        obstacle_clearance_m: float = 0.5,
        apriltag_home_id: int = 0,
        require_lidar: bool = True,
        capture_station_fn: Optional[Callable[[float, float, float, float], Coroutine[Any, Any, Dict[str, Any]]]] = None,
        get_lidar_points: Optional[Callable[[], Sequence[Any]]] = None,
        get_dark_zones: Optional[Callable[[], Sequence[Any]]] = None,
        get_coverage_pct: Optional[Callable[[], float]] = None,
        get_battery_v: Optional[Callable[[], Optional[float]]] = None,
        get_imu_yaw_deg: Optional[Callable[[], Optional[float]]] = None,
        get_camera_jpeg: Optional[Callable[[], Coroutine[Any, Any, Optional[bytes]]]] = None,
        ai_vision_engine: Optional[Any] = None,
        announce_fn: Optional[Callable[[str], Coroutine[Any, Any, None]]] = None,
        tick_sleep_s: float = 0.25,
        settle_sleep_s: float = 0.35,
        max_transit_ticks: int = 40,
    ) -> Dict[str, Any]:
        """Start an autonomous Dark-Zone Frontier Explorer & Multi-Angle 3D Mapping mission.

        Args:
            robot_id: Registered robot ID.
            ip: Robot IPv4 address.
            rosbridge_port: ROSBridge WebSocket port.
            ros_version: ``"ros2"`` or ``"ros1"``.
            space_id: Target TwinScan space UUID for 3D scene panels & Spatial Memory sightings.
            max_iterations: Maximum frontier capture stations (``1..15``).
            target_coverage_pct: Coverage percentage target triggering completion RTH (``40..99``).
            capture_mode: ``"quick_3"``, ``"level_360"``, or ``"multi_pitch"``.
            quality_preset: ``"fast"``, ``"balanced"``, or ``"studio_ultra"``.
            rth_battery_v: 2S LiPo low-battery Return-to-Home voltage threshold (``6.6..7.8`` V).
            max_speed_cms: Maximum forward transit speed in cm/s (``5..20``).
            obstacle_clearance_m: VFH minimum obstacle clearance in meters (``0.3..1.2``).
            apriltag_home_id: AprilTag ``36h11`` ID identifying the home dock (default ``0``).
            require_lidar: Block autonomous motion when live LD19 ``/scan`` is absent.
            capture_station_fn: Async callback ``(x, y, yaw_deg, pitch_deg) -> {panels, objects, apriltag_home_seen}``.
            get_lidar_points: Callback returning verified live LD19 ``LidarPoint`` list.
            get_dark_zones: Callback returning current Spatial Dark Zones.
            get_coverage_pct: Callback returning current room coverage ``0..100%``.
            get_battery_v: Callback returning live 2S LiPo voltage in volts (or ``None``).
            get_camera_jpeg: Optional async callback returning live camera JPEG bytes for avoidance & AprilTag.
            ai_vision_engine: Optional ``RobotAiVisionEngine`` for front-camera obstacle detection.
            announce_fn: Optional async voice announcement callback.
            tick_sleep_s: Control loop tick sleep in seconds (default ``0.25``).
            settle_sleep_s: Pose pitch settle pause in seconds before capture (default ``0.35``).
            max_transit_ticks: Safety cap on VFH transit steps per leg (default ``40``).

        Returns:
            Initial ``ExplorerStatus`` dictionary.
        """
        await self.stop(robot_id, ip=ip, rosbridge_port=rosbridge_port, ros_version=ros_version)
        self._rth_flags[robot_id] = False

        safe_mode = capture_mode if capture_mode in ("quick_3", "level_360", "multi_pitch") else "multi_pitch"
        safe_preset = quality_preset if quality_preset in ("fast", "balanced", "studio_ultra") else "balanced"
        safe_iters = max(1, min(15, int(max_iterations)))
        safe_cov_target = max(40.0, min(99.0, float(target_coverage_pct)))
        safe_rth_v = max(6.6, min(7.8, float(rth_battery_v)))
        from src.robot.stability_guard import DEFAULT_STABILITY_PRESET, get_stability_preset
        from src.robot.rosbridge_proxy import publish_gait

        preset_cfg = get_stability_preset(DEFAULT_STABILITY_PRESET)
        safe_speed = max(5.0, min(preset_cfg.max_vx_cms, float(max_speed_cms)))
        safe_clear = max(0.3, min(1.2, float(obstacle_clearance_m)))

        # Non-blocking low-CG carpet_lidar gait init for top-heavy Explorer safety
        async def _apply_explorer_stable_gait() -> None:
            try:
                await asyncio.wait_for(
                    publish_pose(
                        ip=ip,
                        port=rosbridge_port,
                        height=preset_cfg.height_cm,
                        x_shift=preset_cfg.x_shift_cm,
                        run_time=450,
                        ros_version=ros_version,
                        robot_id=robot_id,
                    ),
                    timeout=1.5,
                )
                await asyncio.wait_for(
                    publish_gait(
                        ip=ip,
                        port=rosbridge_port,
                        overlap_time=preset_cfg.overlap_time_s,
                        swing_time=preset_cfg.swing_time_s,
                        clearance_time=preset_cfg.clearance_time_s,
                        z_clearance=preset_cfg.z_clearance_cm,
                        ros_version=ros_version,
                        robot_id=robot_id,
                    ),
                    timeout=1.5,
                )
            except Exception as exc:
                sys.stderr.write(f"[explorer.stability] Stance/gait init skipped for {robot_id}: {exc}\n")

        asyncio.create_task(_apply_explorer_stable_gait())

        initial_pts = list(get_lidar_points() or []) if get_lidar_points else []
        lidar_live = len(initial_pts) > 0
        batt_v = get_battery_v() if get_battery_v else None
        init_dz = list(get_dark_zones() or []) if get_dark_zones else []
        init_cov = float(get_coverage_pct()) if get_coverage_pct else 0.0

        self._status[robot_id] = {
            "robot_id": robot_id,
            "space_id": space_id,
            "active": False,
            "state": "idle",
            "iteration": 0,
            "max_iterations": safe_iters,
            "coverage_pct": round(init_cov, 1),
            "target_coverage_pct": round(safe_cov_target, 1),
            "dark_zones_remaining": len(init_dz),
            "panels_captured": 0,
            "objects_identified": 0,
            "battery_v": round(float(batt_v), 2) if batt_v is not None else None,
            "battery_pct": compute_battery_pct_2s(batt_v),
            "rth_battery_v": round(safe_rth_v, 2),
            "capture_mode": safe_mode,
            "quality_preset": safe_preset,
            "current_pitch_deg": 0.0,
            "current_yaw_deg": 0.0,
            "home_xy": [0.0, 0.0],
            "current_xy": [0.0, 0.0],
            "target_xy": None,
            "path_xy": [[0.0, 0.0]],
            "apriltag_home_seen": False,
            "lidar_live": lidar_live,
            "started_at": _now_iso(),
            "error": None,
            "event_log": [],
        }

        if require_lidar and not lidar_live:
            err = (
                "LD19 LiDAR /scan is offline. Start live LiDAR before Autonomous Explore "
                "or disable 'Require Live LiDAR'."
            )
            self._status[robot_id]["state"] = "blocked_no_lidar"
            self._status[robot_id]["error"] = err
            self._log(robot_id, "warn", err)
            return self.get_status(robot_id)

        self._status[robot_id]["active"] = True
        self._status[robot_id]["state"] = "capturing_multi_angle"
        self._log(
            robot_id,
            "info",
            f"Autonomous Explorer started ({safe_mode}, {safe_preset}, target {safe_cov_target:.0f}%, RTH <= {safe_rth_v:.2f}V).",
        )

        async def _safe_announce(msg: str) -> None:
            if announce_fn:
                try:
                    await announce_fn(msg)
                except Exception as exc:
                    sys.stderr.write(f"[explorer.voice] Announcement failed: {exc}\n")

        async def _safe_zero_vel() -> None:
            try:
                await publish_velocity(ip, rosbridge_port, 0.0, 0.0, 0.0, ros_version=ros_version, robot_id=robot_id)
            except Exception as exc:
                sys.stderr.write(f"[explorer.vel] Zero-velocity publish failed: {exc}\n")

        async def _safe_set_pitch(pitch_deg: float) -> None:
            clamped_deg = max(-15.0, min(15.0, float(pitch_deg)))
            try:
                await publish_pose(
                    ip=ip,
                    port=rosbridge_port,
                    pitch=math.radians(clamped_deg),
                    run_time=350,
                    ros_version=ros_version,
                    robot_id=robot_id,
                )
            except Exception as exc:
                sys.stderr.write(f"[explorer.pose] Pitch {clamped_deg}° failed: {exc}\n")
            self._status[robot_id]["current_pitch_deg"] = round(clamped_deg, 1)

        def _refresh_battery() -> Optional[float]:
            v = get_battery_v() if get_battery_v else None
            if v is not None:
                self._status[robot_id]["battery_v"] = round(float(v), 2)
                self._status[robot_id]["battery_pct"] = compute_battery_pct_2s(v)
            return float(v) if v is not None else None

        def _needs_rth() -> Tuple[bool, str]:
            v = _refresh_battery()
            if v is not None and v <= safe_rth_v:
                return True, f"Battery low ({v:.2f}V) — returning to home base."
            if self._rth_flags.get(robot_id):
                return True, "Returning to home base on operator request."
            return False, ""

        imu_anchor_deg: List[Optional[float]] = [None]

        def _sync_imu_yaw(pose: List[float]) -> Optional[float]:
            """Read live IMU yaw if available, anchor on first sample, and fuse into ``pose[2]``."""
            if get_imu_yaw_deg is None:
                return None
            try:
                raw_yaw = get_imu_yaw_deg()
            except Exception:
                return None
            if raw_yaw is None:
                return None
            try:
                val = float(raw_yaw)
            except (TypeError, ValueError):
                return None
            if not math.isfinite(val):
                return None
            if imu_anchor_deg[0] is None:
                imu_anchor_deg[0] = val
            rel_deg = ((val - imu_anchor_deg[0] + 180.0) % 360.0) - 180.0
            pose[2] = math.radians(rel_deg)
            self._status[robot_id]["current_yaw_deg"] = round(rel_deg % 360.0, 1)
            return rel_deg

        async def _transit_to(
            goal_x: float,
            goal_y: float,
            pose: List[float],
            is_rth: bool = False,
        ) -> str:
            """Navigate collision-free toward ``(goal_x, goal_y)``.

            Returns:
                ``"arrived"`` when goal reached, ``"rth"`` when preempted by RTH/low battery,
                or ``"lidar_lost"`` when live LD19 ``/scan`` stays absent for ``>4.5s``.
            """
            self._status[robot_id]["target_xy"] = [round(goal_x, 3), round(goal_y, 3)]
            dt_step = max(0.05, min(0.4, float(tick_sleep_s)))
            last_lidar_ok_ts = time.monotonic()
            active_transit_state = "returning_home" if is_rth else "exploring_transit"

            for tick in range(max(1, int(max_transit_ticks))):
                if not is_rth:
                    rth_now, _ = _needs_rth()
                    if rth_now:
                        await _safe_zero_vel()
                        return "rth"
                else:
                    _refresh_battery()

                _sync_imu_yaw(pose)

                dx = goal_x - pose[0]
                dy = goal_y - pose[1]
                dist = math.hypot(dx, dy)
                if dist <= 0.25:
                    await _safe_zero_vel()
                    return "arrived"

                pts = list(get_lidar_points() or []) if get_lidar_points else []
                self._status[robot_id]["lidar_live"] = len(pts) > 0

                if pts:
                    last_lidar_ok_ts = time.monotonic()
                    if self._status[robot_id].get("state") == "paused_lidar_wait":
                        self._status[robot_id]["state"] = active_transit_state
                elif require_lidar:
                    await _safe_zero_vel()
                    gap_s = time.monotonic() - last_lidar_ok_ts
                    if gap_s <= 4.5:
                        self._status[robot_id]["state"] = "paused_lidar_wait"
                        await asyncio.sleep(max(0.0, float(tick_sleep_s)))
                        continue
                    err_msg = (
                        "Live LD19 LiDAR /scan stream went stale (>4.5s) during exploration; "
                        "halted for safety."
                    )
                    self._status[robot_id]["state"] = "blocked_no_lidar"
                    self._status[robot_id]["active"] = False
                    self._status[robot_id]["lidar_live"] = False
                    self._status[robot_id]["target_xy"] = None
                    self._status[robot_id]["error"] = err_msg
                    self._log(robot_id, "warn", err_msg)
                    await _safe_announce("LiDAR signal lost during exploration. Halting safely.")
                    return "lidar_lost"

                vis_obs: Optional[str] = None
                vis_turn: Optional[str] = None
                if get_camera_jpeg and tick % 2 == 0:
                    try:
                        jpg = await get_camera_jpeg()
                    except Exception:
                        jpg = None
                    if jpg:
                        if is_rth and detect_apriltag_home_in_jpeg(jpg, apriltag_home_id):
                            self._status[robot_id]["apriltag_home_seen"] = True
                            if dist <= 0.65:
                                await _safe_zero_vel()
                                self._log(robot_id, "ok", f"AprilTag #{apriltag_home_id} home dock visually locked.")
                                return "arrived"
                        obs_lbl, obs_turn = await asyncio.to_thread(
                            detect_front_camera_obstacle, jpg, ai_vision_engine
                        )
                        vis_obs, vis_turn = obs_lbl, obs_turn

                desired_heading = math.atan2(dy, dx) - pose[2]
                desired_heading = (desired_heading + math.pi) % (2.0 * math.pi) - math.pi

                if pts:
                    ranges, ang_min, ang_inc = lidar_points_to_sectors(pts)
                    vx, yaw_rate, _, _ = compute_vfh_avoidance(
                        ranges=ranges,
                        angle_min=ang_min,
                        angle_increment=ang_inc,
                        target_heading_rad=desired_heading,
                        clearance_m=safe_clear,
                        max_speed_cms=safe_speed,
                        visual_obstacle=bool(vis_obs),
                        visual_turn_dir=vis_turn,
                    )
                else:
                    if vis_obs:
                        vx = 0.0
                        yaw_rate = 0.45 if vis_turn != "right" else -0.45
                    else:
                        yaw_rate = max(-0.55, min(0.55, desired_heading * 0.8))
                        vx = min(8.0, safe_speed) * max(0.35, 1.0 - abs(yaw_rate) * 0.8)

                try:
                    await publish_velocity(
                        ip, rosbridge_port, vx, 0.0, yaw_rate, ros_version=ros_version, robot_id=robot_id
                    )
                except Exception as exc:
                    sys.stderr.write(f"[explorer.transit] Velocity publish failed: {exc}\n")

                # Update odometry dead-reckoning & fuse live IMU yaw when available
                step_dt = max(0.15, dt_step)
                if _sync_imu_yaw(pose) is None:
                    pose[2] = (pose[2] + yaw_rate * step_dt + math.pi) % (2.0 * math.pi) - math.pi
                    self._status[robot_id]["current_yaw_deg"] = round(math.degrees(pose[2]) % 360.0, 1)
                pose[0] += (vx / 100.0) * math.cos(pose[2]) * step_dt
                pose[1] += (vx / 100.0) * math.sin(pose[2]) * step_dt
                self._status[robot_id]["current_xy"] = [round(pose[0], 3), round(pose[1], 3)]

                path_xy = self._status[robot_id]["path_xy"]
                if not path_xy or math.hypot(pose[0] - path_xy[-1][0], pose[1] - path_xy[-1][1]) >= 0.08:
                    path_xy.append([round(pose[0], 3), round(pose[1], 3)])
                    if len(path_xy) > 300:
                        del path_xy[:-300]

                await asyncio.sleep(max(0.0, float(tick_sleep_s)))

            await _safe_zero_vel()
            return "arrived"

        async def _execute_rth(reason: str, pose: List[float]) -> None:
            self._status[robot_id]["state"] = "returning_home"
            self._log(robot_id, "warn", reason)
            await _safe_announce(reason)
            await _safe_set_pitch(0.0)
            outcome = await _transit_to(0.0, 0.0, pose, is_rth=True)
            await _safe_zero_vel()
            if outcome == "lidar_lost":
                await _safe_set_pitch(0.0)
                return
            try:
                await call_go_home(ip=ip, port=rosbridge_port, ros_version=ros_version, robot_id=robot_id)
            except Exception as exc:
                sys.stderr.write(f"[explorer.rth] call_go_home failed for {robot_id}: {exc}\n")
            self._status[robot_id]["state"] = "parked_home"
            self._status[robot_id]["active"] = False
            self._status[robot_id]["target_xy"] = None
            self._status[robot_id]["current_pitch_deg"] = 0.0
            self._log(robot_id, "ok", "Parked safely at home base (go_home crouch complete).")
            await _safe_announce("Returned safely to home base.")

        async def _explore_loop() -> None:
            pose = [0.0, 0.0, 0.0]  # [x_m, y_m, yaw_rad]
            visited_xy: List[Tuple[float, float]] = []
            schedule = build_capture_pose_schedule(safe_mode)
            _sync_imu_yaw(pose)

            await _safe_announce(f"Starting autonomous room exploration in {safe_mode.replace('_', ' ')} mode.")
            try:
                for iteration in range(1, safe_iters + 1):
                    rth_now, rth_reason = _needs_rth()
                    if rth_now:
                        await _execute_rth(rth_reason, pose)
                        return

                    self._status[robot_id]["iteration"] = iteration
                    self._status[robot_id]["state"] = "capturing_multi_angle"
                    visited_xy.append((pose[0], pose[1]))
                    await _safe_zero_vel()
                    self._log(
                        robot_id,
                        "info",
                        f"Station {iteration}/{safe_iters} at ({pose[0]:.2f}m, {pose[1]:.2f}m): capturing {len(schedule)} angles.",
                    )

                    _sync_imu_yaw(pose)
                    base_yaw_deg = math.degrees(pose[2]) % 360.0
                    last_pitch = 0.0
                    rth_triggered_mid_capture = ""
                    try:
                        for rel_yaw, pitch_deg in schedule:
                            rth_mid, rth_msg = _needs_rth()
                            if rth_mid:
                                rth_triggered_mid_capture = rth_msg
                                break

                            _sync_imu_yaw(pose)
                            abs_yaw = (base_yaw_deg + rel_yaw) % 360.0
                            self._status[robot_id]["current_yaw_deg"] = round(abs_yaw, 1)
                            if abs(pitch_deg - last_pitch) > 0.1:
                                await _safe_set_pitch(pitch_deg)
                                last_pitch = pitch_deg
                                if settle_sleep_s > 0:
                                    await asyncio.sleep(settle_sleep_s)

                            if capture_station_fn is not None:
                                try:
                                    res = await capture_station_fn(pose[0], pose[1], abs_yaw, pitch_deg)
                                    if isinstance(res, dict):
                                        self._status[robot_id]["panels_captured"] += int(res.get("panels", 1))
                                        self._status[robot_id]["objects_identified"] += int(res.get("objects", 0))
                                        if res.get("apriltag_home_seen"):
                                            self._status[robot_id]["apriltag_home_seen"] = True
                                except Exception as exc:
                                    sys.stderr.write(f"[explorer.capture] Station capture failed: {exc}\n")
                                    self._log(robot_id, "warn", f"Capture angle ({abs_yaw:.0f}°/{pitch_deg:+.0f}°) skipped: {exc}")
                    finally:
                        if abs(last_pitch) > 0.1:
                            await _safe_set_pitch(0.0)

                    if rth_triggered_mid_capture:
                        await _execute_rth(rth_triggered_mid_capture, pose)
                        return

                    # Re-evaluate coverage & remaining dark zones
                    dz_list = list(get_dark_zones() or []) if get_dark_zones else []
                    cov = float(get_coverage_pct()) if get_coverage_pct else self._status[robot_id]["coverage_pct"]
                    self._status[robot_id]["dark_zones_remaining"] = len(dz_list)
                    self._status[robot_id]["coverage_pct"] = round(cov, 1)

                    if cov >= safe_cov_target:
                        await _execute_rth(
                            f"Target room coverage reached ({cov:.1f}% >= {safe_cov_target:.0f}%) — returning to home base.",
                            pose,
                        )
                        return

                    if iteration >= safe_iters:
                        await _execute_rth(
                            f"Completed all {safe_iters} exploration stations — returning to home base.",
                            pose,
                        )
                        return

                    frontier = select_next_dark_zone_frontier(
                        dark_zones=dz_list,
                        visited_xy=visited_xy,
                        current_xy=(pose[0], pose[1]),
                    )
                    if frontier is None:
                        await _execute_rth(
                            "No unvisited Spatial Dark Zones remain — returning to home base.",
                            pose,
                        )
                        return

                    self._status[robot_id]["state"] = "exploring_transit"
                    self._log(
                        robot_id,
                        "info",
                        f"Transiting to frontier '{frontier['label']}' ({frontier['nbv_x']:.2f}m, {frontier['nbv_y']:.2f}m, priority {frontier['priority_score']}).",
                    )
                    transit_outcome = await _transit_to(frontier["nbv_x"], frontier["nbv_y"], pose, is_rth=False)
                    if transit_outcome == "lidar_lost":
                        await _safe_set_pitch(0.0)
                        return
                    if transit_outcome == "rth":
                        _, rth_reason2 = _needs_rth()
                        await _execute_rth(rth_reason2 or "Returning to home base.", pose)
                        return

                await _execute_rth("Exploration mission complete — returning to home base.", pose)
            except asyncio.CancelledError:
                await _safe_zero_vel()
                await _safe_set_pitch(0.0)
                return
            except Exception as exc:
                sys.stderr.write(f"[explorer] Loop error for {robot_id}: {exc}\n")
                await _safe_zero_vel()
                await _safe_set_pitch(0.0)
                self._status[robot_id]["active"] = False
                self._status[robot_id]["state"] = "stopped"
                self._status[robot_id]["error"] = str(exc)
                self._log(robot_id, "warn", f"Explorer halted on error: {exc}")

        self._tasks[robot_id] = asyncio.create_task(_explore_loop())
        return self.get_status(robot_id)
