"""ROS 2 Humble SLAM Controller, Live OccupancyGrid Renderer & 3D Wall GLB Exporter.

Manages real ``hiwonder_slam`` / ``slam_toolbox`` execution inside PuppyPi's
``puppypi_ros2`` container, streams live ``/map`` (``nav_msgs/OccupancyGrid``),
``/scan``, and ``/tf`` over ``rosbridge_websocket``, renders crisp high-contrast
PNG maps, and exports extruded 3D wall ``.glb`` meshes + metric room dimensions
directly into Room Twin Studio and the 3D Digital Twin.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import pty
import select
import sys
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np
import trimesh
import websockets

MAX_SSH_RETRIES = 3


def render_occupancy_grid_png(
    *,
    width: int,
    height: int,
    data: Sequence[int],
    resolution: float = 0.05,
    origin_xy: Tuple[float, float] = (0.0, 0.0),
    robot_xy: Optional[Tuple[float, float]] = None,
    trail_xy: Sequence[Tuple[float, float]] = (),
    scale_factor: int = 3,
) -> bytes:
    """Render a ROS ``nav_msgs/OccupancyGrid`` into a crisp high-contrast PNG.

    Args:
        width: Grid width in cells.
        height: Grid height in cells.
        data: Flat row-major occupancy values (``-1`` unknown, ``0`` free, ``100`` wall).
        resolution: Meters per cell.
        origin_xy: World ``(x, y)`` of grid cell ``(0, 0)``.
        robot_xy: Optional current robot world ``(x, y)`` in meters.
        trail_xy: Optional list of historical robot ``(x, y)`` positions.
        scale_factor: Nearest-neighbor upscaling factor for crisp pixel walls.

    Returns:
        Encoded PNG bytes.
    """
    w = max(1, int(width))
    h = max(1, int(height))
    arr = np.asarray(data, dtype=np.int16)
    if arr.size != w * h:
        arr = np.full((h, w), -1, dtype=np.int16)
    else:
        arr = arr.reshape((h, w))

    # Flip Y so +Y (north) is up in image coordinates
    arr = np.flipud(arr)

    img = np.zeros((h, w, 3), dtype=np.uint8)
    # Unknown (-1): deep obsidian
    img[:, :] = (24, 16, 11)  # BGR for #0b1018
    # Free (0..49): clean slate blue
    free_mask = (arr >= 0) & (arr < 50)
    img[free_mask] = (58, 41, 30)  # BGR for #1e293a
    # Occupied (>=50): crisp cyan-white walls
    occ_mask = arr >= 50
    img[occ_mask] = (255, 238, 125)  # BGR bright cyan-white

    sf = max(1, min(6, int(scale_factor)))
    if sf > 1 and max(w, h) * sf <= 2048:
        img = cv2.resize(img, (w * sf, h * sf), interpolation=cv2.INTER_NEAREST)
    else:
        sf = 1

    ih, iw = img.shape[:2]
    res = max(0.005, float(resolution))
    ox, oy = float(origin_xy[0]), float(origin_xy[1])

    def _world_to_px(wx: float, wy: float) -> Tuple[int, int]:
        gx = int(round(((wx - ox) / res) * sf))
        gy = int(round((h - 1 - ((wy - oy) / res)) * sf))
        return max(0, min(iw - 1, gx)), max(0, min(ih - 1, gy))

    # Draw robot breadcrumb trail
    if len(trail_xy) >= 2:
        pts = np.asarray([_world_to_px(px, py) for px, py in trail_xy], dtype=np.int32)
        cv2.polylines(img, [pts], isClosed=False, color=(180, 220, 60), thickness=max(1, sf // 2))

    # Draw robot marker
    if robot_xy is not None:
        rx, ry = _world_to_px(robot_xy[0], robot_xy[1])
        cv2.circle(img, (rx, ry), max(3, sf * 2), (80, 235, 16), -1)
        cv2.circle(img, (rx, ry), max(4, sf * 2 + 1), (255, 255, 255), 1)

    ok, enc = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError("Failed encoding SLAM occupancy grid PNG.")
    return enc.tobytes()


def extract_room_and_wall_glb_from_grid(
    *,
    width: int,
    height: int,
    resolution: float,
    origin_xy: Tuple[float, float],
    data: Sequence[int],
    wall_height_m: float = 2.5,
) -> Dict[str, Any]:
    """Extract metric room dimensions and an extruded 3D wall ``.glb`` from a SLAM OccupancyGrid.

    Args:
        width: Grid width in cells.
        height: Grid height in cells.
        resolution: Meters per cell.
        origin_xy: Grid origin ``(x, y)`` in meters.
        data: Flat row-major occupancy values.
        wall_height_m: Extruded 3D wall height in meters.

    Returns:
        Dictionary with ``width_m``, ``length_m``, ``wall_segments``, ``glb_bytes``,
        and ``triangle_count``.
    """
    w = max(1, int(width))
    h = max(1, int(height))
    res = max(0.005, float(resolution))
    arr = np.asarray(data, dtype=np.int16)
    if arr.size != w * h:
        raise ValueError("OccupancyGrid data size does not match width * height.")
    grid = arr.reshape((h, w))

    occ_ys, occ_xs = np.where(grid >= 50)
    if occ_xs.size < 4:
        raise ValueError("SLAM map does not have enough occupied wall cells yet. Drive PuppyPi around the room first.")

    min_x_m = float(origin_xy[0]) + float(occ_xs.min()) * res
    max_x_m = float(origin_xy[0]) + float(occ_xs.max()) * res
    min_y_m = float(origin_xy[1]) + float(occ_ys.min()) * res
    max_y_m = float(origin_xy[1]) + float(occ_ys.max()) * res
    cx = (min_x_m + max_x_m) * 0.5
    cy = (min_y_m + max_y_m) * 0.5

    room_w_m = round(max(1.8, min(25.0, max_x_m - min_x_m)), 2)
    room_l_m = round(max(1.8, min(25.0, max_y_m - min_y_m)), 2)
    wh = max(1.5, min(6.0, float(wall_height_m)))

    # Binary wall mask -> morphological close -> polygon contours -> extruded 3D walls
    mask = (grid >= 50).astype(np.uint8) * 255
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.dilate(mask, kernel, iterations=1)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    scene = trimesh.Scene()
    # Floor slab centered at origin (Three.js Y-up: X=east, Y=up, Z=south)
    floor = trimesh.creation.box(extents=[room_w_m, 0.04, room_l_m])
    floor.apply_translation([0.0, -0.02, 0.0])
    floor.visual.face_colors = [24, 34, 54, 255]
    scene.add_geometry(floor, node_name="slam_floor")

    wall_segments: List[Dict[str, float]] = []
    seg_idx = 0
    for cnt in contours:
        if len(cnt) < 2:
            continue
        approx = cv2.approxPolyDP(cnt, epsilon=2.0, closed=False)
        for i in range(len(approx) - 1):
            p1 = approx[i][0]
            p2 = approx[i + 1][0]
            x1 = (float(origin_xy[0]) + float(p1[0]) * res) - cx
            z1 = -((float(origin_xy[1]) + float(p1[1]) * res) - cy)
            x2 = (float(origin_xy[0]) + float(p2[0]) * res) - cx
            z2 = -((float(origin_xy[1]) + float(p2[1]) * res) - cy)
            seg_len = math.hypot(x2 - x1, z2 - z1)
            if seg_len < 0.15:
                continue
            mid_x = (x1 + x2) * 0.5
            mid_z = (z1 + z2) * 0.5
            angle = math.atan2(z2 - z1, x2 - x1)
            wall = trimesh.creation.box(extents=[seg_len, wh, 0.08])
            rot = trimesh.transformations.rotation_matrix(-angle, [0, 1, 0])
            wall.apply_transform(rot)
            wall.apply_translation([mid_x, wh * 0.5, mid_z])
            wall.visual.face_colors = [64, 175, 225, 255]
            scene.add_geometry(wall, node_name=f"slam_wall_{seg_idx}")
            wall_segments.append({"x1": round(x1, 3), "z1": round(z1, 3), "x2": round(x2, 3), "z2": round(z2, 3)})
            seg_idx += 1

    total_tris = sum(int(len(g.faces)) for g in scene.geometry.values() if hasattr(g, "faces"))
    glb_bytes = bytes(scene.export(file_type="glb"))
    return {
        "width_m": room_w_m,
        "length_m": room_l_m,
        "wall_height_m": wh,
        "wall_segment_count": len(wall_segments),
        "wall_segments": wall_segments[:120],
        "triangle_count": total_tris,
        "glb_bytes": glb_bytes,
    }


def _run_ssh_command_sync(ip: str, user: str, password: str, cmd: str, timeout_s: float = 18.0) -> str:
    """Execute a shell command over SSH with PTY password auth and 3x retry."""
    last_err = "unknown"
    for attempt in range(1, MAX_SSH_RETRIES + 1):
        try:
            pid, fd = pty.fork()
            if pid == 0:
                os.execvp(
                    "ssh",
                    [
                        "ssh",
                        "-o",
                        "StrictHostKeyChecking=no",
                        "-o",
                        "ConnectTimeout=6",
                        f"{user}@{ip}",
                        cmd,
                    ],
                )
            out = bytearray()
            sent_pw = False
            deadline = time.time() + timeout_s
            while time.time() < deadline:
                r, _, _ = select.select([fd], [], [], 0.25)
                if not r:
                    continue
                try:
                    chunk = os.read(fd, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                out.extend(chunk)
                if not sent_pw and b"password:" in out.lower():
                    os.write(fd, (password + "\n").encode("utf-8"))
                    sent_pw = True
            try:
                os.waitpid(pid, 0)
            except Exception:
                pass
            return out.decode("utf-8", errors="replace")
        except Exception as exc:
            last_err = str(exc)
            sys.stderr.write(f"[slam.ssh] Command failed attempt {attempt}/{MAX_SSH_RETRIES}: {exc}\n")
            time.sleep(0.5 * attempt)
    raise RuntimeError(f"SSH to {ip} failed after {MAX_SSH_RETRIES} retries: {last_err}")


class SlamSessionManager:
    """Manages live ROS 2 SLAM execution on PuppyPi and real-time ``/map`` streaming."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._running: bool = False
        self._robot_id: Optional[str] = None
        self._robot_ip: Optional[str] = None
        self._started_at: Optional[float] = None
        self._stream_task: Optional[asyncio.Task[None]] = None
        self._last_error: Optional[str] = None
        self._map_source: str = "idle"  # "ros_map" | "scan_accumulator" | "idle"

        # Live occupancy grid state
        self._grid_w: int = 200
        self._grid_h: int = 200
        self._grid_res: float = 0.05
        self._grid_origin: Tuple[float, float] = (-5.0, -5.0)
        self._grid_data: List[int] = [-1] * (200 * 200)
        self._has_map_data: bool = False
        self._map_seq: int = 0
        self._scan_count: int = 0
        self._scan_hz: float = 0.0
        self._robot_xy: Tuple[float, float] = (0.0, 0.0)
        self._trail_xy: List[Tuple[float, float]] = []
        self._saved_maps: List[Dict[str, Any]] = []

    def _resolve_robot(self, robot_store: Any, robot_id: Optional[str] = None) -> Tuple[Dict[str, Any], str]:
        if robot_store is None:
            raise ValueError("Robot store unavailable.")
        robots = list(robot_store.list_robots() or [])
        target = None
        if robot_id:
            target = next((r for r in robots if r.get("id") == robot_id), None)
        if target is None:
            target = next((r for r in robots if "puppy" in str(r.get("name", "")).lower()), None)
        if target is None and robots:
            target = robots[0]
        if target is None:
            raise ValueError("No PuppyPi robot registered.")
        pw = ""
        if hasattr(robot_store, "get_robot_ssh_password"):
            pw = robot_store.get_robot_ssh_password(target["id"]) or ""
        return target, pw

    async def start_slam(self, *, robot_store: Any, robot_id: Optional[str] = None) -> Dict[str, Any]:
        """Start real ROS 2 ``hiwonder_slam`` / ``slam_toolbox`` on PuppyPi and stream ``/map``."""
        robot, pw = self._resolve_robot(robot_store, robot_id)
        ip = str(robot.get("ip_address") or "").strip()
        user = str(robot.get("ssh_user") or "pi").strip()
        if not ip:
            raise ValueError("Selected robot has no IP address.")

        launch_cmd = r'''
CID=$(docker ps --format "{{.Names}}" | grep -E "^puppypi_ros2$" | head -n 1)
if [ -z "$CID" ]; then CID=$(docker ps -q | head -n 1); fi
if [ -z "$CID" ]; then echo "NO_ROS2_CONTAINER"; exit 1; fi
docker exec "$CID" bash -c 'pkill -f "slam_toolbox|hiwonder_slam|static_transform_publisher.*lidar_frame" 2>/dev/null || true'
docker exec -d "$CID" bash -c '
  source /opt/ros/humble/setup.bash
  source /home/ubuntu/ros2_ws/install/setup.bash 2>/dev/null || true
  source /home/ubuntu/third_party_ros2/third_party_ws/install/setup.bash 2>/dev/null || true
  # Publish clean static TF base_link -> lidar_frame and odom -> base_link fallback if needed, plus slam_toolbox
  ros2 run tf2_ros static_transform_publisher 0 0 0.14 0 0 0 base_link lidar_frame >/tmp/eigenia_tf.log 2>&1 &
  sleep 0.5
  if [ -f /home/ubuntu/ros2_ws/src/hiwonder_slam/launch/slam.launch.py ]; then
    ros2 launch hiwonder_slam slam.launch.py >/tmp/eigenia_slam.log 2>&1
  else
    ros2 launch slam_toolbox online_async_launch.py use_sim_time:=false >/tmp/eigenia_slam.log 2>&1
  fi
'
echo "SLAM_STARTED_IN=$CID"
'''
        try:
            ssh_out = await asyncio.to_thread(_run_ssh_command_sync, ip, user, pw, launch_cmd, 15.0)
        except Exception as exc:
            self._last_error = str(exc)
            raise RuntimeError(f"Failed launching SLAM on PuppyPi ({ip}): {exc}") from exc

        await self._cancel_stream()
        with self._lock:
            self._running = True
            self._robot_id = str(robot["id"])
            self._robot_ip = ip
            self._started_at = time.time()
            self._last_error = None
            self._grid_w = 200
            self._grid_h = 200
            self._grid_res = 0.05
            self._grid_origin = (-5.0, -5.0)
            self._grid_data = [-1] * (200 * 200)
            self._has_map_data = False
            self._map_seq = 0
            self._scan_count = 0
            self._trail_xy = [(0.0, 0.0)]
            self._map_source = "warming_up"

        port = int(robot.get("rosbridge_port") or 9090)
        self._stream_task = asyncio.create_task(self._rosbridge_loop(ip, port))
        st = self.get_status()
        st["launch_log"] = ssh_out.strip()[-240:]
        return st

    async def stop_slam(self, *, robot_store: Any = None, robot_id: Optional[str] = None) -> Dict[str, Any]:
        """Stop live SLAM streaming and terminate the ROS 2 SLAM nodes on PuppyPi."""
        await self._cancel_stream()
        ip = self._robot_ip
        if robot_store is not None:
            try:
                robot, pw = self._resolve_robot(robot_store, robot_id or self._robot_id)
                ip = str(robot.get("ip_address") or ip or "")
                user = str(robot.get("ssh_user") or "pi")
                if ip:
                    stop_cmd = r'''
CID=$(docker ps --format "{{.Names}}" | grep -E "^puppypi_ros2$" | head -n 1)
if [ -n "$CID" ]; then
  docker exec "$CID" bash -c 'pkill -f "slam_toolbox|hiwonder_slam|static_transform_publisher.*lidar_frame" 2>/dev/null || true'
fi
echo "SLAM_STOPPED"
'''
                    await asyncio.to_thread(_run_ssh_command_sync, ip, user, pw, stop_cmd, 10.0)
            except Exception as exc:
                sys.stderr.write(f"[slam.stop] Remote stop warning: {exc}\n")

        with self._lock:
            self._running = False
            self._map_source = "idle"
        return self.get_status()

    async def _cancel_stream(self) -> None:
        task = self._stream_task
        self._stream_task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

    async def _rosbridge_loop(self, ip: str, port: int) -> None:
        """Subscribe to PuppyPi's ``/map``, ``/scan``, and ``/tf`` over rosbridge."""
        url = f"ws://{ip}:{port}"
        while self._running:
            try:
                async with websockets.connect(url, open_timeout=6, max_size=16 * 1024 * 1024) as ws:
                    await ws.send(json.dumps({"op": "subscribe", "topic": "/map", "id": "slam_map", "throttle_rate": 400}))
                    await ws.send(json.dumps({"op": "subscribe", "topic": "/scan", "id": "slam_scan", "throttle_rate": 120}))
                    await ws.send(json.dumps({"op": "subscribe", "topic": "/tf", "id": "slam_tf", "throttle_rate": 200}))
                    scan_window_t0 = time.monotonic()
                    scan_window_n = 0
                    got_ros_map = False

                    while self._running:
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=1.5)
                        except asyncio.TimeoutError:
                            continue
                        msg = json.loads(raw)
                        topic = msg.get("topic")
                        body = msg.get("msg") or {}

                        if topic == "/map":
                            info = body.get("info") or {}
                            w = int(info.get("width") or 0)
                            h = int(info.get("height") or 0)
                            res = float(info.get("resolution") or 0.05)
                            pos = ((info.get("origin") or {}).get("position") or {})
                            ox = float(pos.get("x") or 0.0)
                            oy = float(pos.get("y") or 0.0)
                            data = body.get("data") or []
                            if w > 0 and h > 0 and len(data) == w * h:
                                got_ros_map = True
                                with self._lock:
                                    self._grid_w = w
                                    self._grid_h = h
                                    self._grid_res = res
                                    self._grid_origin = (ox, oy)
                                    self._grid_data = [int(v) for v in data]
                                    self._has_map_data = True
                                    self._map_seq += 1
                                    self._map_source = "ros_map"

                        elif topic == "/tf":
                            for tr in body.get("transforms") or []:
                                child = str(tr.get("child_frame_id") or "").lstrip("/")
                                if child in {"base_link", "base_footprint"}:
                                    t = ((tr.get("transform") or {}).get("translation") or {})
                                    rx = float(t.get("x") or 0.0)
                                    ry = float(t.get("y") or 0.0)
                                    with self._lock:
                                        self._robot_xy = (rx, ry)
                                        if not self._trail_xy or math.hypot(rx - self._trail_xy[-1][0], ry - self._trail_xy[-1][1]) >= 0.08:
                                            self._trail_xy.append((rx, ry))
                                            if len(self._trail_xy) > 500:
                                                self._trail_xy = self._trail_xy[-500:]

                        elif topic == "/scan":
                            scan_window_n += 1
                            now_m = time.monotonic()
                            if now_m - scan_window_t0 >= 1.5:
                                hz = round(scan_window_n / (now_m - scan_window_t0), 1)
                                scan_window_n = 0
                                scan_window_t0 = now_m
                                with self._lock:
                                    self._scan_hz = hz
                            with self._lock:
                                self._scan_count += 1
                            # Live scan-to-grid accumulator so map draws immediately even before slam_toolbox publishes first /map
                            if not got_ros_map:
                                self._accumulate_scan_into_grid(body)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                with self._lock:
                    self._last_error = str(exc)
                sys.stderr.write(f"[slam.ws] Rosbridge stream error ({url}): {exc}\n")
                await asyncio.sleep(2.0)

    def _accumulate_scan_into_grid(self, scan_msg: Dict[str, Any]) -> None:
        ranges = scan_msg.get("ranges") or []
        if not ranges:
            return
        a_min = float(scan_msg.get("angle_min") or 0.0)
        a_inc = float(scan_msg.get("angle_increment") or 0.0)
        r_min = float(scan_msg.get("range_min") or 0.05)
        r_max = min(8.0, float(scan_msg.get("range_max") or 8.0))
        with self._lock:
            w, h, res = self._grid_w, self._grid_h, self._grid_res
            ox, oy = self._grid_origin
            rx, ry = self._robot_xy
            grid = self._grid_data
            for i, r in enumerate(ranges):
                if r is None:
                    continue
                rf = float(r)
                if not math.isfinite(rf) or rf <= r_min or rf >= r_max:
                    continue
                ang = a_min + i * a_inc
                wx = rx + rf * math.cos(ang)
                wy = ry + rf * math.sin(ang)
                # Mark free ray points (coarse step) and occupied endpoint
                for frac in (0.25, 0.5, 0.75):
                    fx = int((rx + rf * frac * math.cos(ang) - ox) / res)
                    fy = int((ry + rf * frac * math.sin(ang) - oy) / res)
                    if 0 <= fx < w and 0 <= fy < h:
                        idx = fy * w + fx
                        if grid[idx] < 50:
                            grid[idx] = 0
                gx = int((wx - ox) / res)
                gy = int((wy - oy) / res)
                if 0 <= gx < w and 0 <= gy < h:
                    grid[gy * w + gx] = 100
            self._has_map_data = True
            self._map_seq += 1
            if self._map_source != "ros_map":
                self._map_source = "scan_accumulator"

    def get_status(self) -> Dict[str, Any]:
        """Return live SLAM status, metrics, and saved map history."""
        with self._lock:
            arr = np.asarray(self._grid_data, dtype=np.int16)
            occ = int(np.sum(arr >= 50))
            free = int(np.sum((arr >= 0) & (arr < 50)))
            area_m2 = round((occ + free) * (self._grid_res ** 2), 2)
            return {
                "running": self._running,
                "robot_id": self._robot_id,
                "robot_ip": self._robot_ip,
                "map_source": self._map_source,
                "has_map_data": self._has_map_data,
                "map_seq": self._map_seq,
                "width": self._grid_w,
                "height": self._grid_h,
                "resolution_m": self._grid_res,
                "origin_xy": list(self._grid_origin),
                "occupied_cells": occ,
                "free_cells": free,
                "mapped_area_m2": area_m2,
                "scan_count": self._scan_count,
                "scan_hz": self._scan_hz,
                "robot_xy": [round(self._robot_xy[0], 3), round(self._robot_xy[1], 3)],
                "trail_count": len(self._trail_xy),
                "uptime_s": round(time.time() - self._started_at, 1) if (self._running and self._started_at) else 0.0,
                "last_error": self._last_error,
                "saved_maps": list(self._saved_maps),
            }

    def get_map_png(self) -> bytes:
        """Render the latest live SLAM occupancy grid as a PNG image."""
        with self._lock:
            w, h, res = self._grid_w, self._grid_h, self._grid_res
            ox, oy = self._grid_origin
            data = list(self._grid_data)
            rxy = self._robot_xy
            trail = list(self._trail_xy)
        return render_occupancy_grid_png(
            width=w,
            height=h,
            data=data,
            resolution=res,
            origin_xy=(ox, oy),
            robot_xy=rxy,
            trail_xy=trail,
        )

    def save_map(self, *, repo: Any, name: str = "SLAM Floor Map") -> Dict[str, Any]:
        """Persist the current SLAM map PNG to PostgreSQL 18 ``stored_files``."""
        if repo is None:
            raise ValueError("Repository unavailable.")
        png = self.get_map_png()
        st = self.get_status()
        stored = repo.store_file(
            filename=f"slam_map_{uuid.uuid4().hex[:6]}.png",
            content_type="image/png",
            data=png,
            category="slam_map_png",
            metadata={"name": name, "mapped_area_m2": st["mapped_area_m2"], "occupied_cells": st["occupied_cells"]},
        )
        entry = {
            "id": stored["id"],
            "name": name,
            "url": f"/api/files/{stored['id']}/download",
            "mapped_area_m2": st["mapped_area_m2"],
            "occupied_cells": st["occupied_cells"],
            "created_at": time.time(),
        }
        with self._lock:
            self._saved_maps.insert(0, entry)
            self._saved_maps = self._saved_maps[:20]
        return entry

    def export_to_digital_twin(
        self,
        *,
        repo: Any,
        room_studio_store: Any = None,
        name: str = "SLAM Scanned Room",
        wall_height_m: float = 2.5,
    ) -> Dict[str, Any]:
        """Extrude SLAM walls to a 3D ``.glb`` and create a Room Twin Studio project."""
        if repo is None:
            raise ValueError("Repository unavailable.")
        with self._lock:
            w, h, res = self._grid_w, self._grid_h, self._grid_res
            origin = self._grid_origin
            data = list(self._grid_data)

        extracted = extract_room_and_wall_glb_from_grid(
            width=w,
            height=h,
            resolution=res,
            origin_xy=origin,
            data=data,
            wall_height_m=wall_height_m,
        )
        stored_glb = repo.store_file(
            filename=f"slam_room_3d_{uuid.uuid4().hex[:6]}.glb",
            content_type="model/gltf-binary",
            data=extracted["glb_bytes"],
            category="reconstruction_glb",
            metadata={
                "kind": "slam_extruded_room",
                "width_m": extracted["width_m"],
                "length_m": extracted["length_m"],
                "wall_segment_count": extracted["wall_segment_count"],
            },
        )

        room_project = None
        if room_studio_store is not None:
            proj = room_studio_store.create_project(
                name=name,
                width_m=extracted["width_m"],
                length_m=extracted["length_m"],
                height_m=extracted["wall_height_m"],
            )
            proj["splat_file_id"] = stored_glb["id"]
            proj["splat_url"] = f"/api/files/{stored_glb['id']}/download"
            proj["splat_filename"] = stored_glb["filename"]
            proj["splat_format"] = "glb"
            room_project = room_studio_store.save_project(proj)

        return {
            "ok": True,
            "glb_file_id": stored_glb["id"],
            "glb_url": f"/api/files/{stored_glb['id']}/download",
            "width_m": extracted["width_m"],
            "length_m": extracted["length_m"],
            "wall_segment_count": extracted["wall_segment_count"],
            "triangle_count": extracted["triangle_count"],
            "room_studio_project_id": room_project["id"] if room_project else None,
        }
