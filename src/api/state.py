"""Shared runtime state coordinating LiDAR, Dark Zones, OpenRouter Vision/Research, Postgres 18, and Neo4j."""

from __future__ import annotations

import asyncio
import json
import math
import sys
import time
from typing import Any, List, Optional, Sequence, Set

import numpy as np
import websockets
from fastapi import WebSocket

from src.app.config import Settings
from src.db.repository import InMemoryTwinRepository, PostgresTwinRepository, TwinRepositoryProtocol
from src.enrichment.research_enricher import DirectResearchEnricher
from src.graph.neo4j_store import Neo4jKnowledgeGraphStore
from src.lidar.change_detection import LogOddsOccupancyGrid
from src.lidar.dark_zones import SpatialDarkZone, detect_spatial_dark_zones
from src.lidar.filters import FilterConfig, apply_lidar_filters, detect_zone_intrusions
from src.lidar.ld19_parser import LD19StreamDecoder, LidarPoint
from src.lidar.mapping import (
    ObjectCluster,
    WallSegment,
    compute_room_metrics,
    extract_walls_ransac,
    segment_object_clusters,
)
from src.lidar.motion_tracker import MovingObjectTracker
from src.lidar.simulator import FacilityRoomSimulator
from src.robot.rosbridge_proxy import laserscan_to_lidar_points
from src.vision.openrouter_client import OpenRouterVisionClient


def compute_cardinal_distances_m(
    points: Sequence[LidarPoint],
    half_window_deg: float = 15.0,
) -> dict[str, Optional[float]]:
    """Compute median radial distances in meters along the 4 canonical 2D radar cardinals.

    Canonical 2D radar / Three.js horizontal axes:
    - ``front``: ``+Y`` (90 deg, aligned with PuppyPi camera forward ``-Z`` in Three.js)
    - ``right``: ``+X`` (0 deg)
    - ``back``:  ``-Y`` (270 deg)
    - ``left``:  ``-X`` (180 deg)

    Args:
        points: Filtered and rotation-calibrated ``LidarPoint`` measurements.
        half_window_deg: Angular half-width around each cardinal heading in degrees.

    Returns:
        Dictionary ``{"front", "right", "back", "left"}`` with median meters or ``None``.
    """
    buckets: dict[str, List[float]] = {"front": [], "right": [], "back": [], "left": []}
    centers = {"front": 90.0, "right": 0.0, "back": 270.0, "left": 180.0}
    hw = max(1.0, float(half_window_deg))

    for pt in points:
        dist = float(pt.distance_m)
        if not math.isfinite(dist) or dist <= 0.02:
            continue
        ang = math.degrees(math.atan2(float(pt.y), float(pt.x))) % 360.0
        for name, center in centers.items():
            diff = abs(((ang - center + 180.0) % 360.0) - 180.0)
            if diff <= hw:
                buckets[name].append(dist)

    return {
        name: (round(float(np.median(vals)), 3) if vals else None)
        for name, vals in buckets.items()
    }


class TwinScanRuntimeState:
    """Central runtime hub coordinating live perception, hot-reloadable config, and databases."""

    def __init__(self, settings: Settings, repository: Optional[TwinRepositoryProtocol] = None) -> None:
        """Initialize runtime services, load persisted PostgreSQL settings, and prime scan state."""
        self.settings = settings
        self.repo: TwinRepositoryProtocol = repository or self._init_repository(settings)
        self.repo.initialize()

        self.neo4j = Neo4jKnowledgeGraphStore(uri=settings.neo4j_uri, user=settings.neo4j_user, password=settings.neo4j_password)
        self.vision = OpenRouterVisionClient(api_key=settings.openrouter_api_key)
        self.enricher = DirectResearchEnricher(openrouter_api_key=settings.openrouter_api_key)
        self.effective_config: dict[str, str] = {}
        self.apply_runtime_settings()

        self.simulator = FacilityRoomSimulator()
        self.decoder = LD19StreamDecoder()
        self.filter_config = FilterConfig()
        self._rotation_user_overridden: bool = False
        self.occupancy_grid = LogOddsOccupancyGrid(size_m=14.0, resolution_m=0.08)
        self.motion_tracker = MovingObjectTracker()

        self.source_mode: str = "simulator"
        self.poll_interval_ms: int = 100
        self.analytics_every_n_scans: int = 2
        self.motion_tracking_enabled: bool = True
        self.active_lidar_robot_id: Optional[str] = None
        self.actual_hz: float = 0.0
        self.robot_scan_connected: bool = False
        self.robot_pose: dict[str, Any] = {
            "x": 0.0,
            "y": 0.0,
            "roll_deg": 0.0,
            "pitch_deg": 0.0,
            "yaw_deg": 0.0,
            "battery_v": None,
            "live": False,
        }
        self._last_scan_mono: float = 0.0
        self._robot_bridge_task: Optional[asyncio.Task[None]] = None

        self.latest_raw_points: List[LidarPoint] = []
        self.latest_points: List[LidarPoint] = []
        self.latest_walls: List[WallSegment] = []
        self.latest_clusters: List[ObjectCluster] = []
        self.latest_moving_objects: List[dict[str, Any]] = []
        self.latest_dark_zones: List[SpatialDarkZone] = []
        self.latest_metrics: dict[str, Any] = {}
        self.latest_anomalies: List[dict[str, Any]] = []
        self.latest_zone_alerts: List[dict[str, Any]] = []
        self.scan_count: int = 0
        self.last_scan_ts: float = 0.0
        self.rpm: float = 600.0
        self.clients: Set[WebSocket] = set()
        self._sim_task: Optional[asyncio.Task[None]] = None

        spaces = self.repo.list_spaces()
        self.active_space_id: str = spaces[0]["id"] if spaces else ""

        self.process_scan(self.simulator.generate_scan(), rpm=600.0, run_analytics=True)

    @staticmethod
    def _init_repository(settings: Settings) -> TwinRepositoryProtocol:
        if settings.database_url:
            try:
                pg_repo = PostgresTwinRepository(
                    database_url=settings.database_url,
                    embedding_dimensions=settings.embedding_dimensions,
                    encryption_key=settings.twinscan_encryption_key,
                )
                pg_repo.initialize()
                return pg_repo
            except Exception as exc:
                sys.stderr.write(f"[db] PostgreSQL 18 unavailable, falling back to InMemoryTwinRepository: {exc}\n")
        return InMemoryTwinRepository(encryption_key=settings.twinscan_encryption_key)

    def default_settings_map(self) -> dict[str, str]:
        """Return environment-derived baseline values for all managed configuration keys."""
        s = self.settings
        return {
            "openrouter_api_key": s.openrouter_api_key,
            "openrouter_base_url": s.openrouter_base_url,
            "openrouter_default_vision_model": s.openrouter_default_vision_model,
            "openrouter_secondary_vision_model": s.openrouter_secondary_vision_model,
            "openrouter_research_model": s.openrouter_research_model,
            "openrouter_embedding_model": s.openrouter_embedding_model,
            "neo4j_uri": s.neo4j_uri,
            "neo4j_user": s.neo4j_user,
            "neo4j_password": s.neo4j_password,
            "facility_name": s.facility_name,
            "near_proximity_m": str(s.near_proximity_m),
            "default_camera_fov_deg": str(s.default_camera_fov_deg),
            "default_camera_yaw_offset_deg": str(s.default_camera_yaw_offset_deg),
            "default_wall_height_m": str(s.default_wall_height_m),
            "max_upload_mb": str(s.max_upload_mb),
            "openclaw_gateway_url": "http://openclaw-gateway:18789",
            "openclaw_gateway_token": "",
            "openclaw_mcp_bearer_token": "",
            "openclaw_telegram_bot_token": "",
            "openclaw_discord_bot_token": "",
        }

    def apply_runtime_settings(self) -> dict[str, str]:
        """Merge persisted PostgreSQL app_settings over .env defaults and hot-reload clients."""
        merged = {**self.default_settings_map(), **self.repo.get_settings_raw()}
        self.effective_config = merged

        self.vision = OpenRouterVisionClient(
            api_key=merged["openrouter_api_key"],
            base_url=merged["openrouter_base_url"],
            default_model=merged["openrouter_default_vision_model"],
            secondary_model=merged["openrouter_secondary_vision_model"],
            embedding_model=merged["openrouter_embedding_model"],
            embedding_dimensions=self.settings.embedding_dimensions,
        )
        self.enricher = DirectResearchEnricher(
            openrouter_api_key=merged["openrouter_api_key"],
            openrouter_base_url=merged["openrouter_base_url"],
            research_model=merged["openrouter_research_model"],
        )
        if (
            self.neo4j.uri != merged["neo4j_uri"].strip()
            or self.neo4j.user != merged["neo4j_user"]
            or self.neo4j.password != merged["neo4j_password"]
        ):
            self.neo4j.close()
            self.neo4j = Neo4jKnowledgeGraphStore(
                uri=merged["neo4j_uri"],
                user=merged["neo4j_user"],
                password=merged["neo4j_password"],
            )
        return merged

    @property
    def near_proximity_m(self) -> float:
        """Active spatial NEAR radius in meters."""
        return float(self.effective_config.get("near_proximity_m", self.settings.near_proximity_m))

    @property
    def default_camera_fov_deg(self) -> float:
        """Active camera horizontal FOV in degrees."""
        return float(self.effective_config.get("default_camera_fov_deg", self.settings.default_camera_fov_deg))

    @property
    def default_wall_height_m(self) -> float:
        """Active 3D wall extrusion height in meters."""
        return float(self.effective_config.get("default_wall_height_m", self.settings.default_wall_height_m))

    @property
    def max_upload_bytes(self) -> int:
        """Active maximum file upload size in bytes."""
        return int(float(self.effective_config.get("max_upload_mb", self.settings.max_upload_mb)) * 1024 * 1024)

    @property
    def openrouter_configured(self) -> bool:
        """Return True when a real OpenRouter API key is active."""
        key = self.effective_config.get("openrouter_api_key", "").strip()
        return bool(key and key != "your_openrouter_api_key_here")

    def process_scan(
        self,
        raw_points: List[LidarPoint],
        rpm: Optional[float] = None,
        run_analytics: bool = False,
    ) -> dict[str, Any]:
        """Filter raw scan, update occupancy/anomalies, extract walls/clusters/moving-tracks/dark-zones."""
        now_mono = time.monotonic()
        if self._last_scan_mono > 0.0:
            dt_scan = max(0.01, now_mono - self._last_scan_mono)
            inst_hz = min(60.0, 1.0 / dt_scan)
            self.actual_hz = round(0.75 * self.actual_hz + 0.25 * inst_hz, 1) if self.actual_hz > 0 else round(inst_hz, 1)
        self._last_scan_mono = now_mono

        self.latest_raw_points = raw_points
        filtered = apply_lidar_filters(raw_points, self.filter_config)
        self.latest_points = filtered
        self.scan_count += 1
        self.last_scan_ts = time.time()
        if rpm is not None:
            self.rpm = rpm

        self.occupancy_grid.update(filtered)
        placed = self.repo.list_equipment(self.active_space_id) if self.active_space_id else []

        cadence = max(1, int(self.analytics_every_n_scans))
        if run_analytics or self.scan_count % cadence == 0 or not self.latest_walls:
            walls, residuals = extract_walls_ransac(filtered)
            clusters = segment_object_clusters(residuals)
            self.latest_walls = walls
            self.latest_clusters = clusters
            self.latest_metrics = compute_room_metrics(walls, filtered)
            self.latest_dark_zones = detect_spatial_dark_zones(filtered, clusters, placed)
            if self.motion_tracking_enabled:
                self.latest_moving_objects = self.motion_tracker.update(clusters, timestamp_s=now_mono)
            else:
                self.latest_moving_objects = []

        anomalies = self.occupancy_grid.detect_changes(filtered)
        self.latest_anomalies = [a.to_dict() for a in anomalies]

        active_space = self.repo.get_space(self.active_space_id) if self.active_space_id else None
        zones = (active_space or {}).get("zones") or []
        self.latest_zone_alerts = detect_zone_intrusions(filtered, zones)
        return self.build_frame_payload()

    def build_frame_payload(self) -> dict[str, Any]:
        """Build a compact telemetry frame payload for 2D/3D/Babylon canvases."""
        return {
            "type": "lidar_frame",
            "timestamp": self.last_scan_ts,
            "scan_count": self.scan_count,
            "source_mode": self.source_mode,
            "rpm": self.rpm,
            "point_count": len(self.latest_points),
            "baseline_active": self.occupancy_grid.baseline is not None,
            "rogue_injected": self.simulator.inject_rogue_object,
            "simulate_moving_targets": self.simulator.simulate_moving_targets,
            "poll_interval_ms": self.poll_interval_ms,
            "analytics_every_n_scans": self.analytics_every_n_scans,
            "actual_hz": self.actual_hz,
            "robot_scan_connected": self.robot_scan_connected,
            "robot_pose": dict(self.robot_pose),
            "wall_height_m": self.default_wall_height_m,
            "rotation_offset_deg": round(float(self.filter_config.rotation_offset_deg) % 360.0, 2),
            "cardinal_m": compute_cardinal_distances_m(self.latest_points),
            "points": [
                [round(p.x, 3), round(p.y, 3), int(p.intensity), round(p.distance_m, 3), round(p.angle_deg, 1)]
                for p in self.latest_points
            ],
            "walls": [w.to_dict() for w in self.latest_walls],
            "clusters": [c.to_dict() for c in self.latest_clusters],
            "moving_objects": list(self.latest_moving_objects),
            "dark_zones": [d.to_dict() for d in self.latest_dark_zones],
            "metrics": self.latest_metrics,
            "anomalies": self.latest_anomalies,
            "zone_alerts": self.latest_zone_alerts,
        }

    def get_lidar_settings(self) -> dict[str, Any]:
        """Return current LiDAR source, polling rate, analytics cadence, and motion tracking settings."""
        return {
            "source_mode": self.source_mode,
            "robot_id": self.active_lidar_robot_id,
            "poll_interval_ms": self.poll_interval_ms,
            "analytics_every_n_scans": self.analytics_every_n_scans,
            "motion_tracking_enabled": self.motion_tracking_enabled,
            "simulate_moving_targets": self.simulator.simulate_moving_targets,
            "actual_hz": self.actual_hz,
            "robot_scan_connected": self.robot_scan_connected,
            "robot_pose": dict(self.robot_pose),
        }

    async def stop_robot_ros2_bridge(self) -> None:
        """Stop any running ROSBridge ``/scan`` + IMU telemetry subscriber task."""
        if self._robot_bridge_task is not None and not self._robot_bridge_task.done():
            self._robot_bridge_task.cancel()
            try:
                await self._robot_bridge_task
            except asyncio.CancelledError:
                pass
        self._robot_bridge_task = None
        self.robot_scan_connected = False
        self.robot_pose["live"] = False

    async def start_robot_ros2_bridge(
        self,
        robot_id: str,
        ip: str,
        rosbridge_port: int = 9090,
        ros_version: str = "ros2",
        recv_timeout_s: float = 6.0,
    ) -> None:
        """Start background ROSBridge subscription to robot ``/scan``, IMU, and battery topics.

        Omits hardcoded ROS 1 vs ROS 2 ``type`` strings on subscribe so ROSBridge auto-resolves
        topic types across both ROS 1 Noetic and ROS 2 Humble, and enforces a stale-socket
        receive watchdog so power-cycles and reboots reconnect automatically.
        """
        await self.stop_robot_ros2_bridge()
        self.active_lidar_robot_id = robot_id
        if not self._rotation_user_overridden and self.filter_config.rotation_offset_deg == 0.0:
            self.filter_config.rotation_offset_deg = 90.0
        url = f"ws://{ip}:{int(rosbridge_port)}"
        watchdog_s = max(1.0, float(recv_timeout_s))

        async def _bridge_loop() -> None:
            last_imu_t = time.monotonic()
            last_broadcast_t = 0.0
            last_scan_t = 0.0
            while True:
                try:
                    async with websockets.connect(url, open_timeout=3.0, close_timeout=1.5) as ws:
                        for sub in (
                            {"op": "subscribe", "topic": "/scan", "throttle_rate": max(50, self.poll_interval_ms)},
                            {"op": "subscribe", "topic": "/ros_robot_controller/imu_raw", "throttle_rate": 120},
                            {"op": "subscribe", "topic": "/ros_robot_controller/battery", "throttle_rate": 1000},
                        ):
                            await ws.send(json.dumps(sub))
                        last_scan_t = time.monotonic()
                        while True:
                            try:
                                raw = await asyncio.wait_for(ws.recv(), timeout=watchdog_s)
                            except asyncio.TimeoutError:
                                self.robot_scan_connected = False
                                self.robot_pose["live"] = False
                                sys.stderr.write(
                                    f"[lidar.ros2_bridge] No telemetry on {url} for {watchdog_s:.1f}s; reconnecting\n"
                                )
                                break
                            try:
                                msg = json.loads(raw)
                            except Exception:
                                continue
                            if msg.get("op") != "publish":
                                continue
                            topic = msg.get("topic")
                            body = msg.get("msg") or {}
                            if topic == "/ros_robot_controller/battery":
                                mv = body.get("data")
                                if isinstance(mv, (int, float)) and mv > 0:
                                    self.robot_pose["battery_v"] = round(float(mv) / 1000.0, 2)
                                    self.robot_pose["live"] = True
                            elif topic == "/ros_robot_controller/imu_raw":
                                acc = body.get("linear_acceleration") or {}
                                gyr = body.get("angular_velocity") or {}
                                ax, ay, az = float(acc.get("x", 0.0)), float(acc.get("y", 0.0)), float(acc.get("z", 9.81))
                                gz = float(gyr.get("z", 0.0))
                                now_i = time.monotonic()
                                dt_i = min(0.5, max(0.0, now_i - last_imu_t))
                                last_imu_t = now_i
                                roll_deg = math.degrees(math.atan2(ay, max(0.01, abs(az)) * (1.0 if az >= 0 else -1.0)))
                                pitch_deg = math.degrees(math.atan2(-ax, max(0.01, math.hypot(ay, az))))
                                yaw_deg = (float(self.robot_pose.get("yaw_deg", 0.0)) + math.degrees(gz * dt_i)) % 360.0
                                self.robot_pose["roll_deg"] = round(max(-45.0, min(45.0, roll_deg)), 1)
                                self.robot_pose["pitch_deg"] = round(max(-45.0, min(45.0, pitch_deg)), 1)
                                self.robot_pose["yaw_deg"] = round(yaw_deg, 1)
                                self.robot_pose["live"] = True
                            elif topic == "/scan" and self.source_mode == "robot_ros2":
                                pts = laserscan_to_lidar_points(body)
                                if pts:
                                    self.robot_scan_connected = True
                                    last_scan_t = time.monotonic()
                                    if (last_scan_t - last_broadcast_t) >= max(0.04, self.poll_interval_ms / 1000.0):
                                        last_broadcast_t = last_scan_t
                                        frame = self.process_scan(pts, rpm=600.0)
                                        await self.broadcast_frame(frame)
                            if self.robot_scan_connected and (time.monotonic() - last_scan_t) > watchdog_s:
                                self.robot_scan_connected = False
                    await asyncio.sleep(2.0)
                except asyncio.CancelledError:
                    self.robot_scan_connected = False
                    self.robot_pose["live"] = False
                    return
                except Exception as exc:
                    self.robot_scan_connected = False
                    sys.stderr.write(f"[lidar.ros2_bridge] ROSBridge error on {url}: {exc}\n")
                    await asyncio.sleep(2.0)

        self._robot_bridge_task = asyncio.create_task(_bridge_loop())

    async def broadcast_frame(self, payload: dict[str, Any]) -> None:
        """Broadcast a frame payload to all connected WebSocket clients."""
        dead: List[WebSocket] = []
        for ws in list(self.clients):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    async def _simulator_loop(self) -> None:
        while True:
            try:
                step_s = max(0.05, min(1.0, self.poll_interval_ms / 1000.0))
                if self.source_mode == "simulator" and self.clients:
                    frame = self.process_scan(self.simulator.generate_scan(dt_s=step_s), rpm=600.0)
                    await self.broadcast_frame(frame)
                await asyncio.sleep(step_s)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                sys.stderr.write(f"[lidar.sim_loop] Error: {exc}\n")
                await asyncio.sleep(0.5)

    def start_background_tasks(self) -> None:
        """Start the simulator broadcast loop."""
        if self._sim_task is None or self._sim_task.done():
            self._sim_task = asyncio.create_task(self._simulator_loop())

    async def shutdown(self) -> None:
        """Cancel background tasks and close Neo4j & PostgreSQL pools cleanly."""
        await self.stop_robot_ros2_bridge()
        if self._sim_task is not None:
            self._sim_task.cancel()
            try:
                await self._sim_task
            except asyncio.CancelledError:
                pass
        self.neo4j.close()
        self.repo.close()
