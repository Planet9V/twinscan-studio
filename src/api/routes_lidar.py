"""LiDAR streaming, hardware bridge ingest, filtering, wall extraction, change detection, and ICP routes."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, List, Optional

import numpy as np
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from src.api.state import TwinScanRuntimeState
from src.lidar.filters import FilterConfig
from src.lidar.registration import register_scans_2d
from src.robot.ros_profiles import normalize_ros_mode

router = APIRouter(prefix="/api/lidar", tags=["lidar"])


class FilterUpdateRequest(BaseModel):
    """Payload to update active LiDAR filter parameters (supports partial updates)."""

    min_range_m: Optional[float] = Field(default=None, ge=0.0, le=12.0)
    max_range_m: Optional[float] = Field(default=None, ge=0.2, le=20.0)
    min_intensity: Optional[int] = Field(default=None, ge=0, le=255)
    sector_start_deg: Optional[float] = Field(default=None, ge=0.0, le=360.0)
    sector_end_deg: Optional[float] = Field(default=None, ge=0.0, le=360.0)
    exclude_sector: Optional[bool] = None
    rotation_offset_deg: Optional[float] = Field(default=None, ge=-360.0, le=360.0)
    enable_outlier_filter: Optional[bool] = None


class ModeUpdateRequest(BaseModel):
    """Payload to toggle simulator/hardware/robot_ros2 source or inject a simulated rogue object."""

    source_mode: Optional[str] = Field(default=None, pattern="^(simulator|hardware|robot_ros2)$")
    inject_rogue_object: Optional[bool] = None


class LidarSettingsUpdateRequest(BaseModel):
    """Payload to update LiDAR source, polling rate, analytics cadence, and moving-object tracking."""

    source_mode: Optional[str] = Field(default=None, pattern="^(simulator|hardware|robot_ros2)$")
    robot_id: Optional[str] = None
    poll_interval_ms: Optional[int] = Field(default=None, ge=50, le=1000)
    analytics_every_n_scans: Optional[int] = Field(default=None, ge=1, le=16)
    motion_tracking_enabled: Optional[bool] = None
    simulate_moving_targets: Optional[bool] = None


class RegisterScanRequest(BaseModel):
    """Payload for multi-station 2D ICP scan registration."""

    source_points: List[List[float]]
    target_points: Optional[List[List[float]]] = None


def _state(request: Request) -> TwinScanRuntimeState:
    return request.app.state.runtime


@router.get("/status")
async def get_lidar_status(request: Request) -> dict[str, Any]:
    """Return current LiDAR telemetry status, filter config, and latest metrics."""
    rt = _state(request)
    return {
        "source_mode": rt.source_mode,
        "scan_count": rt.scan_count,
        "rpm": rt.rpm,
        "point_count": len(rt.latest_points),
        "wall_count": len(rt.latest_walls),
        "cluster_count": len(rt.latest_clusters),
        "baseline_active": rt.occupancy_grid.baseline is not None,
        "rogue_injected": rt.simulator.inject_rogue_object,
        "active_space_id": rt.active_space_id,
        "filters": asdict(rt.filter_config),
        "metrics": rt.latest_metrics,
        "anomalies": rt.latest_anomalies,
        "zone_alerts": rt.latest_zone_alerts,
    }


@router.get("/snapshot")
async def get_lidar_snapshot(request: Request) -> dict[str, Any]:
    """Return the latest full LiDAR frame payload via HTTP."""
    return _state(request).build_frame_payload()


@router.get("/settings")
async def get_lidar_settings(request: Request) -> dict[str, Any]:
    """Return active LiDAR source mode, polling interval, analytics cadence, and motion tracker settings."""
    return _state(request).get_lidar_settings()


@router.post("/settings")
async def update_lidar_settings(body: LidarSettingsUpdateRequest, request: Request) -> dict[str, Any]:
    """Update LiDAR source (``simulator``/``hardware``/``robot_ros2``), polling rate, and moving-object tracking."""
    rt = _state(request)
    if body.poll_interval_ms is not None:
        rt.poll_interval_ms = max(50, min(1000, int(body.poll_interval_ms)))
    if body.analytics_every_n_scans is not None:
        rt.analytics_every_n_scans = max(1, min(16, int(body.analytics_every_n_scans)))
    if body.motion_tracking_enabled is not None:
        rt.motion_tracking_enabled = bool(body.motion_tracking_enabled)
        if not rt.motion_tracking_enabled:
            rt.motion_tracker.reset()
            rt.latest_moving_objects = []
    if body.simulate_moving_targets is not None:
        rt.simulator.simulate_moving_targets = bool(body.simulate_moving_targets)
    if body.source_mode is not None:
        rt.source_mode = body.source_mode

    if rt.source_mode == "robot_ros2":
        if not rt._rotation_user_overridden and rt.filter_config.rotation_offset_deg == 0.0:
            rt.filter_config.rotation_offset_deg = 90.0
        robot_store = getattr(request.app.state, "robot_store", None)
        target_robot = None
        if robot_store is not None:
            if body.robot_id:
                target_robot = robot_store.get_robot(body.robot_id)
            else:
                robots = robot_store.list_robots()
                target_robot = robots[0] if robots else None
        if target_robot:
            await rt.start_robot_ros2_bridge(
                robot_id=target_robot["id"],
                ip=target_robot["ip_address"],
                rosbridge_port=int(target_robot.get("rosbridge_port") or 9090),
                ros_version=normalize_ros_mode(target_robot.get("active_ros_distro")),
            )
    else:
        await rt.stop_robot_ros2_bridge()
        if rt.source_mode == "simulator":
            frame = rt.process_scan(
                rt.simulator.generate_scan(dt_s=rt.poll_interval_ms / 1000.0),
                rpm=600.0,
                run_analytics=True,
            )
            await rt.broadcast_frame(frame)

    return rt.get_lidar_settings()


@router.post("/filters")
async def update_lidar_filters(body: FilterUpdateRequest, request: Request) -> dict[str, Any]:
    """Update real-time LiDAR filter parameters (merging partial updates) and reprocess latest scan."""
    rt = _state(request)
    merged = asdict(rt.filter_config)
    updates = body.model_dump(exclude_none=True)
    if "rotation_offset_deg" in updates:
        updates["rotation_offset_deg"] = round(float(updates["rotation_offset_deg"]) % 360.0, 2)
        rt._rotation_user_overridden = True
    merged.update(updates)
    rt.filter_config = FilterConfig(**merged)
    if rt.latest_raw_points:
        frame = rt.process_scan(rt.latest_raw_points, run_analytics=True)
        await rt.broadcast_frame(frame)
    return {
        "filters": asdict(rt.filter_config),
        "point_count": len(rt.latest_points),
        "rotation_offset_deg": round(float(rt.filter_config.rotation_offset_deg) % 360.0, 2),
    }


@router.post("/mode")
async def update_lidar_mode(body: ModeUpdateRequest, request: Request) -> dict[str, Any]:
    """Switch between built-in facility simulator and live hardware bridge ingest."""
    rt = _state(request)
    if body.source_mode is not None:
        rt.source_mode = body.source_mode
    if body.inject_rogue_object is not None:
        rt.simulator.inject_rogue_object = body.inject_rogue_object
    if rt.source_mode == "simulator":
        frame = rt.process_scan(rt.simulator.generate_scan(), rpm=600.0, run_analytics=True)
        await rt.broadcast_frame(frame)
        if rt.latest_anomalies and rt.active_space_id:
            rt.repo.record_anomalies(rt.active_space_id, rt.latest_anomalies)
    return {
        "source_mode": rt.source_mode,
        "rogue_injected": rt.simulator.inject_rogue_object,
        "anomalies": rt.latest_anomalies,
    }


@router.post("/baseline")
async def capture_room_baseline(request: Request) -> dict[str, Any]:
    """Capture the current room occupancy grid as the reference baseline for change detection."""
    rt = _state(request)
    rt.occupancy_grid.reset()
    if rt.source_mode == "simulator":
        for _ in range(3):
            rt.occupancy_grid.update(rt.simulator.generate_scan())
    elif rt.latest_points:
        for _ in range(3):
            rt.occupancy_grid.update(rt.latest_points)
    rt.occupancy_grid.capture_baseline()
    return {"baseline_active": True, "grid_dim": rt.occupancy_grid.dim}


@router.post("/extract-walls")
async def extract_and_save_walls(request: Request, space_id: Optional[str] = None) -> dict[str, Any]:
    """Run RANSAC wall extraction and persist walls and room metrics to the space."""
    rt = _state(request)
    target_space_id = space_id or rt.active_space_id
    if not target_space_id or not rt.repo.get_space(target_space_id):
        raise HTTPException(status_code=404, detail="Target space not found")

    if rt.latest_raw_points:
        rt.process_scan(rt.latest_raw_points, run_analytics=True)
    wall_dicts = [w.to_dict() for w in rt.latest_walls]
    updated = rt.repo.save_walls(target_space_id, wall_dicts, rt.latest_metrics)
    return {
        "space_id": updated["id"],
        "walls": updated["walls"],
        "metrics": updated["metrics"],
        "clusters": [c.to_dict() for c in rt.latest_clusters],
    }


@router.post("/register")
async def register_multi_station_scan(body: RegisterScanRequest, request: Request) -> dict[str, Any]:
    """Align a secondary station scan against the active room reference scan via small_gicp/ICP."""
    rt = _state(request)
    target = (
        np.asarray(body.target_points, dtype=np.float64)
        if body.target_points
        else np.array([[p.x, p.y] for p in rt.latest_points], dtype=np.float64)
    )
    source = np.asarray(body.source_points, dtype=np.float64)
    try:
        return register_scans_2d(source, target)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.websocket("/stream")
async def websocket_lidar_stream(ws: WebSocket) -> None:
    """Stream real-time filtered LiDAR scans, walls, clusters, and anomalies to web clients."""
    await ws.accept()
    rt: TwinScanRuntimeState = ws.app.state.runtime
    rt.clients.add(ws)
    try:
        await ws.send_json(rt.build_frame_payload())
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        rt.clients.discard(ws)


@router.websocket("/ingest")
async def websocket_hardware_ingest(ws: WebSocket) -> None:
    """Ingest raw binary LD19 UART packets from the Mac USB bridge or PuppyPi."""
    await ws.accept()
    rt: TwinScanRuntimeState = ws.app.state.runtime
    rt.source_mode = "hardware"
    try:
        while True:
            raw_bytes = await ws.receive_bytes()
            scans = rt.decoder.feed(raw_bytes)
            for scan in scans:
                frame = rt.process_scan(scan, rpm=rt.decoder.last_rpm)
                await rt.broadcast_frame(frame)
    except WebSocketDisconnect:
        pass
