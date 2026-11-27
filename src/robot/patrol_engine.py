"""Autonomous Multi-Waypoint Patrol Engine with Real Robot ROSBridge /scan Fail-Safe & Active Front-Camera Avoidance.

Provides:
- ``compute_vfh_avoidance``: Pure 5-sector Vector Field Histogram reactive avoidance computing safe
  ``(vx_cms, yaw_rate_rads, status, sectors)`` clamped to PuppyPi Pro physical limits.
- ``detect_front_camera_obstacle``: Active YOLO11n + OpenCV close-wall/clutter front-camera obstacle detector.
- ``RobotPatrolManager``: Background per-robot patrol controller subscribing directly to PuppyPi's live
  ROSBridge ``/scan`` topic (NEVER simulated demo-room scans), refusing blind motion when ``require_lidar=True``
  and ``/scan`` is absent/stale, and fusing active front-camera snapshots when ``camera_avoidance=True``.
"""

from __future__ import annotations

import asyncio
import json
import math
import sys
import time
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np
import websockets

from src.robot.ros_profiles import get_ros_profile
from src.robot.rosbridge_proxy import (
    clamp_velocity,
    fetch_robot_snapshot,
    publish_gait,
    publish_pose,
    publish_velocity,
)
from src.robot.stability_guard import (
    DEFAULT_STABILITY_PRESET,
    VelocitySlewLimiter,
    VisualSlipDetector,
    evaluate_imu_tilt_guard,
    get_stability_preset,
)

NULL_SECTORS: Dict[str, Optional[float]] = {
    "front": None,
    "front_left": None,
    "front_right": None,
    "left": None,
    "right": None,
}


def compute_vfh_avoidance(
    ranges: Sequence[float],
    angle_min: float,
    angle_increment: float,
    target_heading_rad: float = 0.0,
    clearance_m: float = 0.45,
    max_speed_cms: float = 12.0,
    visual_obstacle: bool = False,
    visual_turn_dir: Optional[str] = None,
) -> Tuple[float, float, str, Dict[str, float]]:
    """Compute 5-sector LiDAR reactive obstacle avoidance velocity and steering command.

    Sectors (relative to robot forward 0 rad, CCW positive):
    - ``front``: ``[-25°, +25°]``
    - ``front_left``: ``[+25°, +70°]``
    - ``front_right``: ``[-70°, -25°]``
    - ``left``: ``[+70°, +120°]``
    - ``right``: ``[-120°, -70°]``

    Args:
        ranges: Sequence of radial distances in meters.
        angle_min: Starting scan angle in radians.
        angle_increment: Angular step between consecutive rays in radians.
        target_heading_rad: Desired heading toward current waypoint in radians (0 = straight ahead).
        clearance_m: Minimum safe forward obstacle clearance in meters (default ``0.45``).
        max_speed_cms: Maximum forward speed in cm/s (clamped ``<= 25``).
        visual_obstacle: ``True`` when front camera detects a close blocking object/person/wall.
        visual_turn_dir: Optional preferred turn direction (``"left"`` or ``"right"``) from camera.

    Returns:
        Tuple ``(vx_cms, yaw_rate_rads, status, sectors)``.
    """
    sectors: Dict[str, float] = {
        "front": 9.9,
        "front_left": 9.9,
        "front_right": 9.9,
        "left": 9.9,
        "right": 9.9,
    }
    for idx, raw_r in enumerate(ranges):
        if raw_r is None:
            continue
        try:
            d = float(raw_r)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(d) or d < 0.05 or d > 12.0:
            continue
        ang_deg = math.degrees(angle_min + idx * angle_increment)
        ang_deg = ((ang_deg + 180.0) % 360.0) - 180.0
        if -25.0 <= ang_deg <= 25.0:
            sectors["front"] = min(sectors["front"], d)
        elif 25.0 < ang_deg <= 70.0:
            sectors["front_left"] = min(sectors["front_left"], d)
        elif -70.0 <= ang_deg < -25.0:
            sectors["front_right"] = min(sectors["front_right"], d)
        elif 70.0 < ang_deg <= 120.0:
            sectors["left"] = min(sectors["left"], d)
        elif -120.0 <= ang_deg < -70.0:
            sectors["right"] = min(sectors["right"], d)

    sectors = {k: round(v, 3) for k, v in sectors.items()}
    safe_speed = max(4.0, min(25.0, float(max_speed_cms)))
    safe_clear = max(0.20, min(2.0, float(clearance_m)))

    if visual_obstacle or sectors["front"] < safe_clear:
        left_open = min(sectors["front_left"], sectors["left"])
        right_open = min(sectors["front_right"], sectors["right"])
        if max(left_open, right_open) < safe_clear * 0.75:
            return 0.0, 0.45, "avoiding_trapped_rotate", sectors
        if visual_obstacle and visual_turn_dir in ("left", "right"):
            yaw = 0.48 if visual_turn_dir == "left" else -0.48
        else:
            yaw = 0.48 if left_open >= right_open else -0.48
        status = "avoiding_visual_obstacle" if visual_obstacle else "avoiding_lidar_obstacle"
        return 0.0, yaw, status, sectors

    side_bias = 0.0
    if sectors["front_left"] < safe_clear * 1.25:
        side_bias -= 0.25
    if sectors["front_right"] < safe_clear * 1.25:
        side_bias += 0.25

    yaw = max(-0.55, min(0.55, target_heading_rad * 0.8 + side_bias))
    vx = safe_speed * max(0.35, 1.0 - abs(yaw) * 0.8)
    clamped = clamp_velocity(vx, 0.0, yaw)
    return clamped["x"], clamped["yaw_rate"], "navigating", sectors


def lidar_points_to_sectors(points: Sequence[Any]) -> Tuple[List[float], float, float]:
    """Convert polar ``LidarPoint`` objects into synthetic uniform-angle ranges for VFH."""
    bins = [9.9] * 72
    for pt in points:
        dist = float(getattr(pt, "distance_m", 9.9))
        ang = float(getattr(pt, "angle_deg", 0.0))
        norm = ((ang + 180.0) % 360.0) - 180.0
        idx = int(((norm + 180.0) / 360.0) * 72) % 72
        if 0.05 <= dist <= 12.0:
            bins[idx] = min(bins[idx], dist)
    return bins, math.radians(-180.0), math.radians(5.0)


def compute_live_sectors_from_points(
    points: Sequence[Any],
    rotation_offset_deg: float = 0.0,
) -> Dict[str, Optional[float]]:
    """Bin raw LD19 ``LidarPoint`` rays into 5 live patrol obstacle-clearance sectors.

    Raw LD19 points have ``angle_deg = 0°`` pointing forward along the sensor arrow,
    ``+90°`` to the left, and ``-90°`` (``270°``) to the right. Uses the exact same 5 angular
    sectors as :func:`compute_vfh_avoidance`:
    - ``front``: ``[-25°, +25°]``
    - ``front_left``: ``(+25°, +70°]``
    - ``front_right``: ``[-70°, -25°)``
    - ``left``: ``(+70°, +120°]``
    - ``right``: ``[-120°, -70°)``

    Args:
        points: Sequence of ``LidarPoint`` objects exposing ``angle_deg`` and ``distance_m``.
        rotation_offset_deg: Optional mounting angle offset in degrees (default ``0.0``).

    Returns:
        Dictionary mapping each of the 5 sector names to minimum distance in meters rounded
        to 3 decimals, or ``None`` if no valid return fell in that sector.
    """
    mins: Dict[str, Optional[float]] = {
        "front": None,
        "front_left": None,
        "front_right": None,
        "left": None,
        "right": None,
    }
    offset = float(rotation_offset_deg)
    for pt in points:
        try:
            d = float(getattr(pt, "distance_m", float("nan")))
            raw_ang = float(getattr(pt, "angle_deg", float("nan")))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(d) or not math.isfinite(raw_ang) or d < 0.05 or d > 12.0:
            continue
        ang = ((raw_ang + offset + 180.0) % 360.0) - 180.0
        sector: Optional[str] = None
        if -25.0 <= ang <= 25.0:
            sector = "front"
        elif 25.0 < ang <= 70.0:
            sector = "front_left"
        elif -70.0 <= ang < -25.0:
            sector = "front_right"
        elif 70.0 < ang <= 120.0:
            sector = "left"
        elif -120.0 <= ang < -70.0:
            sector = "right"
        if sector is not None:
            cur = mins[sector]
            if cur is None or d < cur:
                mins[sector] = d

    return {k: (round(v, 3) if v is not None else None) for k, v in mins.items()}


def detect_front_camera_obstacle(
    jpeg_bytes: bytes,
    ai_vision_engine: Optional[Any] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """Detect close blocking objects, people, or plain walls from a live front-camera JPEG.

    Combines YOLO11n bounding-box geometry (when ``ai_vision_engine`` is available) with a fast
    OpenCV lower-center ROI texture/edge detector so plain walls and furniture still trigger avoidance.

    Args:
        jpeg_bytes: Raw JPEG image bytes from PuppyPi's front camera.
        ai_vision_engine: Optional ``RobotAiVisionEngine`` providing ``detect_objects_and_animals``.

    Returns:
        Tuple ``(obstacle_label, preferred_turn_dir)`` where ``preferred_turn_dir`` is
        ``"left"`` or ``"right"`` when an obstacle is detected, else ``(None, None)``.
    """
    if not jpeg_bytes:
        return None, None
    arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if frame is None or frame.size == 0:
        return None, None

    # Stage 1: YOLO11n semantic object/person/animal box check
    if ai_vision_engine is not None and hasattr(ai_vision_engine, "detect_objects_and_animals"):
        try:
            dets = ai_vision_engine.detect_objects_and_animals(frame, conf_thresh=0.35)
            blocking: Optional[Dict[str, Any]] = None
            best_area = 0.0
            for d in dets:
                x1, y1, x2, y2 = d["bbox_norm"]
                bh = max(0.0, y2 - y1)
                bw = max(0.0, x2 - x1)
                area = bw * bh
                cx = (x1 + x2) / 2.0
                center_overlap = 0.20 <= cx <= 0.80
                if center_overlap and (bh >= 0.36 or (y2 >= 0.65 and area >= 0.14)):
                    if area > best_area:
                        best_area = area
                        blocking = d
            if blocking is not None:
                bx1, _, bx2, _ = blocking["bbox_norm"]
                cx = (bx1 + bx2) / 2.0
                turn = "left" if cx >= 0.5 else "right"
                return f"Close {blocking['label']}", turn
        except Exception as exc:
            sys.stderr.write(f"[patrol.cam] YOLO obstacle check failed: {exc}\n")

    # Stage 2: Lightweight OpenCV close-wall / plain-surface & bottom-center clutter heuristic
    h, w = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 55, 140)

    y0, y1 = int(h * 0.45), int(h * 0.96)
    cx0, cx1 = int(w * 0.25), int(w * 0.75)

    center_gray = gray[y0:y1, cx0:cx1]
    center_edges = edges[y0:y1, cx0:cx1]
    left_edges = edges[y0:y1, 0:cx0]
    right_edges = edges[y0:y1, cx1:w]

    center_std = float(np.std(center_gray)) if center_gray.size else 50.0
    center_edge_ratio = float(np.count_nonzero(center_edges)) / max(1, center_edges.size)
    left_edge_ratio = float(np.count_nonzero(left_edges)) / max(1, left_edges.size)
    right_edge_ratio = float(np.count_nonzero(right_edges)) / max(1, right_edges.size)

    # A uniform close wall/box right in front of the lens collapses center variance & edges
    if center_std < 18.0 and center_edge_ratio < 0.015:
        left_std = float(np.std(gray[y0:y1, 0:cx0])) if cx0 > 0 else 0.0
        right_std = float(np.std(gray[y0:y1, cx1:w])) if cx1 < w else 0.0
        turn = "left" if left_std >= right_std else "right"
        return "Close Wall / Flat Obstacle", turn

    # Dense close clutter/furniture directly blocking bottom-center path
    if center_edge_ratio > 0.22:
        turn = "left" if left_edge_ratio <= right_edge_ratio else "right"
        return "Close Front Clutter", turn

    return None, None


class RobotPatrolManager:
    """Manages active autonomous multi-waypoint patrols with real ROSBridge ``/scan`` fail-safe & camera fusion."""

    def __init__(self) -> None:
        """Initialize per-robot patrol task, scan subscriber, and status registries."""
        self._tasks: Dict[str, asyncio.Task[None]] = {}
        self._scan_tasks: Dict[str, asyncio.Task[None]] = {}
        self._status: Dict[str, Dict[str, Any]] = {}

    def get_status(self, robot_id: str) -> Dict[str, Any]:
        """Return current patrol status, live LiDAR health, and 5-sector clearances for ``robot_id``."""
        return dict(
            self._status.get(
                robot_id,
                {
                    "robot_id": robot_id,
                    "active": False,
                    "state": "idle",
                    "route_name": None,
                    "current_waypoint_idx": 0,
                    "total_waypoints": 0,
                    "loop_enabled": False,
                    "lidar_live": False,
                    "lidar_age_sec": None,
                    "require_lidar": True,
                    "camera_avoidance_active": True,
                    "sectors_m": dict(NULL_SECTORS),
                    "visual_obstacle": None,
                    "last_command": None,
                    "started_at": None,
                    "error": None,
                },
            )
        )

    async def _run_scan_subscriber(
        self,
        ip: str,
        rosbridge_port: int,
        ros_version: str,
        scan_state: Dict[str, Any],
    ) -> None:
        """Subscribe directly to PuppyPi's live ``/scan`` LaserScan topic over ROSBridge WS."""
        url = f"ws://{ip}:{int(rosbridge_port)}"
        scan_type = "sensor_msgs/msg/LaserScan" if ros_version == "ros2" else "sensor_msgs/LaserScan"
        while True:
            try:
                async with websockets.connect(url, open_timeout=2.5, close_timeout=1.5) as ws:
                    await ws.send(
                        json.dumps(
                            {
                                "op": "subscribe",
                                "topic": "/scan",
                                "type": scan_type,
                                "throttle_rate": 100,
                            }
                        )
                    )
                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                        except Exception:
                            continue
                        if msg.get("op") != "publish" or msg.get("topic") != "/scan":
                            continue
                        body = msg.get("msg") or {}
                        ranges = body.get("ranges")
                        if isinstance(ranges, list) and len(ranges) >= 16:
                            scan_state["ranges"] = ranges
                            scan_state["angle_min"] = float(body.get("angle_min", 0.0))
                            scan_state["angle_increment"] = float(
                                body.get("angle_increment", (2.0 * math.pi) / max(1, len(ranges)))
                            )
                            scan_state["last_scan_ts"] = time.monotonic()
            except asyncio.CancelledError:
                return
            except Exception as exc:
                sys.stderr.write(f"[patrol.scan] ROSBridge /scan stream error on {url}: {exc}\n")
                await asyncio.sleep(1.0)

    async def start(
        self,
        robot_id: str,
        ip: str,
        rosbridge_port: int,
        ros_version: str,
        waypoints: Sequence[Dict[str, Any]],
        route_name: str = "Ad-hoc Patrol",
        loop_enabled: bool = True,
        max_speed_cms: float = 12.0,
        obstacle_clearance_m: float = 0.45,
        require_lidar: bool = True,
        camera_avoidance: bool = True,
        video_port: int = 8080,
        ai_vision_engine: Optional[Any] = None,
        scan_wait_sec: float = 2.0,
        get_lidar_points: Optional[Callable[[], Sequence[Any]]] = None,
        get_visual_obstacle: Optional[Callable[[], Optional[str]]] = None,
        announce_fn: Optional[Callable[[str], Coroutine[Any, Any, None]]] = None,
        stability_preset: str = DEFAULT_STABILITY_PRESET,
        get_imu_attitude: Optional[Callable[[], Optional[Dict[str, Any]]]] = None,
        get_overwatch_pose: Optional[Callable[[], Optional[Dict[str, Any]]]] = None,
        on_waypoint_capture: Optional[Callable[[int], Coroutine[Any, Any, None]]] = None,
    ) -> Dict[str, Any]:
        """Start an autonomous multi-waypoint patrol loop with strict real-robot ``/scan`` & tilt fail-safes."""
        if not waypoints:
            raise ValueError("At least one patrol waypoint is required.")
        await self.stop(robot_id, ip=ip, rosbridge_port=rosbridge_port, ros_version=ros_version)
        preset_cfg = get_stability_preset(stability_preset)
        max_speed_cms = min(float(max_speed_cms), preset_cfg.max_vx_cms)

        wps = list(waypoints)
        now_iso = datetime.now(timezone.utc).isoformat()
        scan_state: Dict[str, Any] = {
            "ranges": [],
            "angle_min": 0.0,
            "angle_increment": 0.0,
            "last_scan_ts": 0.0,
        }

        scan_task = asyncio.create_task(
            self._run_scan_subscriber(ip=ip, rosbridge_port=rosbridge_port, ros_version=ros_version, scan_state=scan_state)
        )
        self._scan_tasks[robot_id] = scan_task

        def _try_warm_start_from_live_points() -> bool:
            if get_lidar_points is None:
                return False
            try:
                pts = list(get_lidar_points() or [])
            except Exception as exc:
                sys.stderr.write(f"[patrol.scan] Warm-start live points callback failed: {exc}\n")
                return False
            if not pts:
                return False
            ranges, ang_min, ang_inc = lidar_points_to_sectors(pts)
            scan_state["ranges"] = ranges
            scan_state["angle_min"] = ang_min
            scan_state["angle_increment"] = ang_inc
            scan_state["last_scan_ts"] = time.monotonic()
            return True

        # Warm-start from verified live robot /scan points if direct subscriber hasn't arrived yet
        if scan_state["last_scan_ts"] <= 0.0:
            _try_warm_start_from_live_points()

        # FAIL-SAFE GATE: When require_lidar=True, wait up to scan_wait_sec for a REAL /scan message
        if require_lidar:
            deadline = time.monotonic() + max(0.05, float(scan_wait_sec))
            while time.monotonic() < deadline and scan_state["last_scan_ts"] <= 0.0:
                if _try_warm_start_from_live_points():
                    break
                await asyncio.sleep(0.05)

            if scan_state["last_scan_ts"] <= 0.0:
                await self._cancel_scan_task(robot_id)
                try:
                    await publish_velocity(ip, rosbridge_port, 0.0, 0.0, 0.0, ros_version=ros_version, robot_id=robot_id)
                except Exception:
                    pass
                err_msg = (
                    "LD19 LiDAR /scan is not streaming on the robot. Check the LD19 USB cable/power "
                    "or disable 'Require Live LiDAR' to use Camera-Only Avoidance."
                )
                self._status[robot_id] = {
                    "robot_id": robot_id,
                    "active": False,
                    "state": "blocked_no_lidar",
                    "route_name": route_name,
                    "current_waypoint_idx": 0,
                    "total_waypoints": len(wps),
                    "loop_enabled": bool(loop_enabled),
                    "lidar_live": False,
                    "lidar_age_sec": None,
                    "require_lidar": True,
                    "camera_avoidance_active": bool(camera_avoidance),
                    "sectors_m": dict(NULL_SECTORS),
                    "visual_obstacle": None,
                    "last_command": {"vx_cms": 0.0, "yaw_rate_rads": 0.0},
                    "started_at": now_iso,
                    "error": err_msg,
                }
                if announce_fn:
                    try:
                        await announce_fn("Patrol blocked. Live LD19 LiDAR scan is offline.")
                    except Exception:
                        pass
                return self.get_status(robot_id)

        self._status[robot_id] = {
            "robot_id": robot_id,
            "active": True,
            "state": "starting",
            "route_name": route_name,
            "stability_preset": preset_cfg.name,
            "current_waypoint_idx": 0,
            "total_waypoints": len(wps),
            "loop_enabled": bool(loop_enabled),
            "lidar_live": scan_state["last_scan_ts"] > 0.0,
            "lidar_age_sec": 0.0 if scan_state["last_scan_ts"] > 0.0 else None,
            "require_lidar": bool(require_lidar),
            "camera_avoidance_active": bool(camera_avoidance),
            "sectors_m": dict(NULL_SECTORS),
            "visual_obstacle": None,
            "last_command": {"vx_cms": 0.0, "yaw_rate_rads": 0.0},
            "started_at": now_iso,
            "error": None,
        }

        primary_cam_topic = get_ros_profile(ros_version)["camera_topic"]
        alt_cam_topic = "/usb_cam/image_raw" if primary_cam_topic == "/image_raw" else "/image_raw"

        async def _patrol_loop() -> None:
            pose_x, pose_y, pose_yaw = 0.0, 0.0, 0.0
            wp_idx = 0
            last_t = time.monotonic()
            last_cam_check = 0.0
            active_cam_obs: Optional[str] = None
            active_cam_turn: Optional[str] = None
            slew = VelocitySlewLimiter(preset_cfg)
            slip_detector = VisualSlipDetector()

            # Auto-initialize low-CG stable stance & carpet-safe gait without blocking tick-0 safety checks
            async def _apply_stable_gait() -> None:
                try:
                    await asyncio.wait_for(
                        publish_pose(
                            ip,
                            rosbridge_port,
                            roll=0.0,
                            pitch=0.0,
                            yaw=0.0,
                            height=preset_cfg.height_cm,
                            x_shift=preset_cfg.x_shift_cm,
                            run_time=500,
                            ros_version=ros_version,
                            robot_id=robot_id,
                        ),
                        timeout=1.5,
                    )
                    await asyncio.wait_for(
                        publish_gait(
                            ip,
                            rosbridge_port,
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
                    sys.stderr.write(f"[patrol.stability] Stance/gait init skipped for {robot_id}: {exc}\n")

            asyncio.create_task(_apply_stable_gait())

            if announce_fn:
                try:
                    await announce_fn(f"Starting patrol route {route_name} with {len(wps)} waypoints.")
                except Exception:
                    pass
            try:
                while True:
                    now = time.monotonic()
                    last_scan_ts = float(scan_state["last_scan_ts"])
                    lidar_age = (now - last_scan_ts) if last_scan_ts > 0.0 else None
                    # Continuous verified live-points fallback when direct /scan subscriber pauses (>1.0s)
                    if lidar_age is None or lidar_age > 1.0:
                        if _try_warm_start_from_live_points():
                            last_scan_ts = float(scan_state["last_scan_ts"])
                            lidar_age = max(0.0, now - last_scan_ts)

                    lidar_live = bool(lidar_age is not None and lidar_age <= 1.5)

                    if require_lidar and not lidar_live:
                        try:
                            await publish_velocity(
                                ip, rosbridge_port, 0.0, 0.0, 0.0, ros_version=ros_version, robot_id=robot_id
                            )
                        except Exception:
                            pass
                        # Brief Wi-Fi jitter pause window (1.5s < age <= 4.5s): hold zero velocity and wait
                        if lidar_age is not None and lidar_age <= 4.5:
                            self._status[robot_id].update(
                                {
                                    "state": "paused_lidar_wait",
                                    "lidar_live": False,
                                    "lidar_age_sec": round(lidar_age, 2),
                                    "last_command": {"vx_cms": 0.0, "yaw_rate_rads": 0.0},
                                    "error": None,
                                }
                            )
                            last_t = now
                            await asyncio.sleep(0.25)
                            continue

                        self._status[robot_id].update(
                            {
                                "active": False,
                                "state": "stopped_lidar_lost",
                                "lidar_live": False,
                                "lidar_age_sec": round(lidar_age, 2) if lidar_age is not None else None,
                                "sectors_m": dict(NULL_SECTORS),
                                "last_command": {"vx_cms": 0.0, "yaw_rate_rads": 0.0},
                                "error": "Live LD19 LiDAR /scan stream went stale (>4.5s); halted patrol for safety.",
                            }
                        )
                        if announce_fn:
                            try:
                                await announce_fn("LiDAR signal lost. Stopping patrol for safety.")
                            except Exception:
                                pass
                        return

                    # Active front-camera snapshot polling (~0.45s) independent of /vision page
                    if camera_avoidance and (now - last_cam_check) >= 0.45:
                        last_cam_check = now
                        jpg: Optional[bytes] = None
                        try:
                            jpg = await fetch_robot_snapshot(
                                ip=ip, port=video_port, topic=primary_cam_topic, timeout=2.0, retries=1
                            )
                        except Exception:
                            try:
                                jpg = await fetch_robot_snapshot(
                                    ip=ip, port=video_port, topic=alt_cam_topic, timeout=2.0, retries=1
                                )
                            except Exception:
                                jpg = None
                        if jpg:
                            active_cam_obs, active_cam_turn = await asyncio.to_thread(
                                detect_front_camera_obstacle, jpg, ai_vision_engine
                            )
                        else:
                            active_cam_obs = get_visual_obstacle() if get_visual_obstacle else None
                            active_cam_turn = None

                    vis_obs = active_cam_obs or (get_visual_obstacle() if get_visual_obstacle else None)

                    wp = wps[wp_idx]
                    tx, ty = float(wp.get("x", 0.0)), float(wp.get("y", 0.0))
                    dx, dy = tx - pose_x, ty - pose_y
                    dist = math.hypot(dx, dy)
                    desired_heading = math.atan2(dy, dx) - pose_yaw
                    desired_heading = (desired_heading + math.pi) % (2.0 * math.pi) - math.pi

                    # IMU Tilt-Guard: halt & crouch immediately if roll or pitch exceeds safe limit
                    if get_imu_attitude is not None:
                        try:
                            att = get_imu_attitude() or {}
                            guard = evaluate_imu_tilt_guard(
                                att.get("roll_deg"),
                                att.get("pitch_deg"),
                                max_tilt_deg=preset_cfg.max_tilt_deg,
                            )
                            if not guard["safe"]:
                                slew.reset()
                                await publish_velocity(
                                    ip, rosbridge_port, 0.0, 0.0, 0.0, ros_version=ros_version, robot_id=robot_id
                                )
                                await publish_pose(
                                    ip,
                                    rosbridge_port,
                                    height=-7.5,
                                    x_shift=preset_cfg.x_shift_cm,
                                    run_time=400,
                                    ros_version=ros_version,
                                    robot_id=robot_id,
                                )
                                self._status[robot_id].update(
                                    {
                                        "active": False,
                                        "state": "tilt_guard_paused",
                                        "last_command": {"vx_cms": 0.0, "yaw_rate_rads": 0.0},
                                        "error": guard["reason"],
                                    }
                                )
                                return
                        except Exception as exc:
                            sys.stderr.write(f"[patrol.tilt_guard] Check warning: {exc}\n")

                    # Blend overhead Overwatch visual pose (25%) to cancel odometry drift
                    vis_pose = get_overwatch_pose() if get_overwatch_pose is not None else None
                    if isinstance(vis_pose, dict) and vis_pose.get("seen"):
                        pose_x = 0.75 * pose_x + 0.25 * float(vis_pose.get("x", pose_x))
                        pose_y = 0.75 * pose_y + 0.25 * float(vis_pose.get("y", pose_y))

                    if dist < 0.25:
                        pause_s = float(wp.get("pause_sec", 0.5))
                        slew.reset()
                        slip_detector.reset()
                        self._status[robot_id]["state"] = f"reached_wp_{wp_idx + 1}"
                        await publish_velocity(
                            ip, rosbridge_port, 0.0, 0.0, 0.0, ros_version=ros_version, robot_id=robot_id
                        )
                        await asyncio.sleep(min(3.0, max(0.6, pause_s)))
                        if on_waypoint_capture is not None:
                            try:
                                self._status[robot_id]["state"] = f"capturing_3d_wp_{wp_idx + 1}"
                                await on_waypoint_capture(wp_idx)
                            except Exception as exc:
                                sys.stderr.write(f"[patrol.capture] Waypoint 3D capture error: {exc}\n")
                        wp_idx += 1
                        if wp_idx >= len(wps):
                            if loop_enabled:
                                wp_idx = 0
                            else:
                                self._status[robot_id]["active"] = False
                                self._status[robot_id]["state"] = "completed"
                                if announce_fn:
                                    try:
                                        await announce_fn("Patrol route complete.")
                                    except Exception:
                                        pass
                                return
                        self._status[robot_id]["current_waypoint_idx"] = wp_idx
                        last_t = time.monotonic()
                        continue

                    if lidar_live:
                        vx, yaw_rate, nav_state, sectors = compute_vfh_avoidance(
                            ranges=scan_state["ranges"],
                            angle_min=float(scan_state["angle_min"]),
                            angle_increment=float(scan_state["angle_increment"]),
                            target_heading_rad=desired_heading,
                            clearance_m=obstacle_clearance_m,
                            max_speed_cms=max_speed_cms,
                            visual_obstacle=bool(vis_obs),
                            visual_turn_dir=active_cam_turn,
                        )
                        reported_sectors: Dict[str, Optional[float]] = dict(sectors)
                    else:
                        # Camera-Only Avoidance mode (require_lidar=False): cap speed <= 10 cm/s, NEVER fake 9.9m
                        reported_sectors = dict(NULL_SECTORS)
                        if vis_obs:
                            vx = 0.0
                            yaw_rate = preset_cfg.max_yaw_rads if active_cam_turn != "right" else -preset_cfg.max_yaw_rads
                            nav_state = "avoiding_visual_obstacle"
                        else:
                            safe_cam_speed = max(4.0, min(preset_cfg.max_vx_cms, float(max_speed_cms)))
                            yaw = max(-preset_cfg.max_yaw_rads, min(preset_cfg.max_yaw_rads, desired_heading * 0.6))
                            clamped = clamp_velocity(safe_cam_speed * max(0.35, 1.0 - abs(yaw) * 0.8), 0.0, yaw)
                            vx, yaw_rate = clamped["x"], clamped["yaw_rate"]
                            nav_state = "navigating_camera_only"

                    dt = min(0.5, max(0.05, now - last_t))
                    last_t = now
                    vx, yaw_rate = slew.step(vx, yaw_rate, dt)

                    # Overwatch Visual Slip Spotter: pause safely if stuck on carpet/cord
                    slip = slip_detector.update(vx, vis_pose, now_mono=now)
                    if slip["stalled"]:
                        slew.reset()
                        await publish_velocity(
                            ip, rosbridge_port, 0.0, 0.0, 0.0, ros_version=ros_version, robot_id=robot_id
                        )
                        self._status[robot_id].update(
                            {
                                "active": False,
                                "state": "slip_stall_paused",
                                "last_command": {"vx_cms": 0.0, "yaw_rate_rads": 0.0},
                                "error": slip["reason"],
                            }
                        )
                        return
                    pose_yaw += yaw_rate * dt
                    pose_x += (vx / 100.0) * math.cos(pose_yaw) * dt
                    pose_y += (vx / 100.0) * math.sin(pose_yaw) * dt

                    self._status[robot_id].update(
                        {
                            "state": nav_state,
                            "current_waypoint_idx": wp_idx,
                            "lidar_live": lidar_live,
                            "lidar_age_sec": round(lidar_age, 2) if lidar_age is not None else None,
                            "sectors_m": reported_sectors,
                            "visual_obstacle": vis_obs,
                            "last_command": {"vx_cms": vx, "yaw_rate_rads": yaw_rate},
                        }
                    )
                    try:
                        await publish_velocity(
                            ip, rosbridge_port, vx, 0.0, yaw_rate, ros_version=ros_version, robot_id=robot_id
                        )
                    except Exception as exc:
                        sys.stderr.write(f"[patrol] Velocity publish failed for {robot_id}: {exc}\n")
                        self._status[robot_id]["error"] = str(exc)
                    await asyncio.sleep(0.25)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                sys.stderr.write(f"[patrol] Loop error for {robot_id}: {exc}\n")
                self._status[robot_id]["active"] = False
                self._status[robot_id]["state"] = "error"
                self._status[robot_id]["error"] = str(exc)
            finally:
                await self._cancel_scan_task(robot_id)

        self._tasks[robot_id] = asyncio.create_task(_patrol_loop())
        return self.get_status(robot_id)

    async def _cancel_scan_task(self, robot_id: str) -> None:
        stask = self._scan_tasks.pop(robot_id, None)
        if stask is not None and not stask.done():
            stask.cancel()
            try:
                await stask
            except asyncio.CancelledError:
                pass

    async def stop(
        self,
        robot_id: str,
        ip: Optional[str] = None,
        rosbridge_port: int = 9090,
        ros_version: str = "ros1",
    ) -> Dict[str, Any]:
        """Stop an active patrol & ``/scan`` subscriber for ``robot_id`` and publish zero velocity."""
        task = self._tasks.pop(robot_id, None)
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await self._cancel_scan_task(robot_id)
        if ip:
            try:
                await publish_velocity(ip, rosbridge_port, 0.0, 0.0, 0.0, ros_version=ros_version, robot_id=robot_id)
            except Exception as exc:
                sys.stderr.write(f"[patrol] Zero-velocity on stop failed for {robot_id}: {exc}\n")
        st = self.get_status(robot_id)
        st["active"] = False
        st["state"] = "stopped"
        st["last_command"] = {"vx_cms": 0.0, "yaw_rate_rads": 0.0}
        self._status[robot_id] = st
        return dict(st)

    async def stop_all(self) -> None:
        """Stop all active patrol loops and scan subscribers on application shutdown."""
        for rid in list(set(self._tasks.keys()) | set(self._scan_tasks.keys())):
            await self.stop(rid)
