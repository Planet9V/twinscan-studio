"""FastAPI router for 4K/1080p USB & MacBook Overwatch Vision and 3D Triangulation."""

from __future__ import annotations

import asyncio
import sys
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from src.vision.overwatch_triangulator import (
    DEFAULT_CAMERA_ID,
    OverwatchCameraManager,
    sanitize_camera_id,
)
from src.vision.overwatch_upscaler import (
    ALLOWED_FAL_UPSCALE_MODELS,
    extract_and_enhance_local_roi,
    upscale_roi_fal_ai,
)

router = APIRouter(prefix="/api/overwatch", tags=["overwatch"])


class OverwatchCalibrationUpdate(BaseModel):
    """Partial calibration & detection mode update for an overwatch camera slot."""

    camera_id: Optional[str] = Field(default=None, max_length=32)
    x_m: Optional[float] = Field(default=None, ge=-50.0, le=50.0)
    y_m: Optional[float] = Field(default=None, ge=-50.0, le=50.0)
    z_m: Optional[float] = Field(default=None, ge=0.05, le=20.0)
    yaw_deg: Optional[float] = Field(default=None, ge=-360.0, le=360.0)
    pitch_deg: Optional[float] = Field(default=None, ge=-89.0, le=89.0)
    hfov_deg: Optional[float] = Field(default=None, ge=10.0, le=165.0)
    vfov_deg: Optional[float] = Field(default=None, ge=10.0, le=145.0)
    mode: Optional[str] = Field(default=None, max_length=32)


def _get_overwatch_manager(request: Request) -> OverwatchCameraManager:
    mgr = getattr(request.app.state, "overwatch_manager", None)
    if mgr is None:
        mgr = OverwatchCameraManager()
        request.app.state.overwatch_manager = mgr
    return mgr


@router.post("/ingest")
async def ingest_overwatch_frame(
    request: Request,
    camera_id: str = Query(default=DEFAULT_CAMERA_ID),
    camera_name: Optional[str] = Query(default=None),
    fps: float = Query(default=10.0, ge=0.1, le=60.0),
) -> Dict[str, Any]:
    """Ingest a JPEG frame from the host camera bridge (multipart ``frame`` or raw JPEG body)."""
    try:
        clean_cid = sanitize_camera_id(camera_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    content_type = (request.headers.get("content-type") or "").lower()
    jpeg_bytes = b""
    if "multipart/form-data" in content_type:
        try:
            form = await request.form()
            upload = form.get("frame") or form.get("file") or form.get("image")
            if upload is None:
                raise HTTPException(status_code=400, detail="Missing 'frame' file field in multipart upload.")
            jpeg_bytes = await upload.read() if hasattr(upload, "read") else bytes(upload)
        except HTTPException:
            raise
        except Exception as exc:
            sys.stderr.write(f"[overwatch.ingest] Multipart read error: {exc}\n")
            raise HTTPException(status_code=400, detail=f"Invalid multipart payload: {exc}") from exc
    else:
        jpeg_bytes = await request.body()

    if not jpeg_bytes:
        raise HTTPException(status_code=400, detail="Empty JPEG frame payload.")

    mgr = _get_overwatch_manager(request)
    ai_vision_engine = getattr(request.app.state, "ai_vision_engine", None)
    ai_store = getattr(request.app.state, "robot_ai_store", None)
    runtime = getattr(request.app.state, "runtime", None)

    try:
        return mgr.ingest_frame(
            jpeg_bytes=jpeg_bytes,
            camera_name=camera_name,
            fps=fps,
            ai_vision_engine=ai_vision_engine,
            ai_store=ai_store,
            runtime=runtime,
            camera_id=clean_cid,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        sys.stderr.write(f"[overwatch.ingest] Frame processing error: {exc}\n")
        raise HTTPException(status_code=500, detail=f"Overwatch frame processing failed: {exc}") from exc


@router.get("/status")
async def get_overwatch_status(
    request: Request,
    camera_id: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    """Return live Overwatch status, active detections, triangulated targets, and all camera slots."""
    mgr = _get_overwatch_manager(request)
    try:
        return mgr.get_status(camera_id=camera_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/calibration")
async def update_overwatch_calibration(
    request: Request,
    payload: OverwatchCalibrationUpdate,
    camera_id: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    """Update extrinsic pose, FOV, or AI vision mode for an overwatch camera slot."""
    mgr = _get_overwatch_manager(request)
    target_cid = camera_id or payload.camera_id or DEFAULT_CAMERA_ID
    updates = payload.model_dump(exclude_none=True, exclude={"camera_id"})
    try:
        return mgr.update_calibration(updates=updates, camera_id=target_cid)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/snapshot")
async def get_overwatch_snapshot(
    request: Request,
    annotated: bool = Query(default=True),
    camera_id: Optional[str] = Query(default=None),
) -> Response:
    """Return the latest annotated or raw JPEG snapshot for the selected overwatch camera."""
    mgr = _get_overwatch_manager(request)
    try:
        jpg = mgr.get_snapshot_bytes(annotated=annotated, camera_id=camera_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(content=jpg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.get("/stream")
async def stream_overwatch_mjpeg(
    request: Request,
    annotated: bool = Query(default=True),
    camera_id: Optional[str] = Query(default=None),
) -> StreamingResponse:
    """Stream live annotated or raw Overwatch frames as ``multipart/x-mixed-replace`` MJPEG."""
    mgr = _get_overwatch_manager(request)
    try:
        clean_cid = sanitize_camera_id(camera_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    async def _mjpeg_gen() -> AsyncIterator[bytes]:
        try:
            while True:
                if await request.is_disconnected():
                    break
                frame = mgr.get_snapshot_bytes(annotated=annotated, camera_id=clean_cid)
                if frame:
                    header = (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n"
                        + f"Content-Length: {len(frame)}\r\n\r\n".encode("ascii")
                    )
                    yield header + frame + b"\r\n"
                await asyncio.sleep(0.11)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            sys.stderr.write(f"[overwatch.stream] Stream error ({clean_cid}): {exc}\n")

    return StreamingResponse(
        _mjpeg_gen(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store"},
    )


class AprilTagCalibrateRequest(BaseModel):
    """Request body for 1-click AprilTag solvePnP auto-calibration."""

    camera_id: str = Field(default="all", max_length=32)
    tag_size_m: float = Field(default=0.12, ge=0.02, le=1.5)
    tag_world_x: float = Field(default=0.0, ge=-20.0, le=20.0)
    tag_world_y: float = Field(default=0.0, ge=-20.0, le=20.0)
    tag_world_z: float = Field(default=0.0, ge=0.0, le=5.0)
    tag_world_yaw_deg: float = Field(default=0.0, ge=-360.0, le=360.0)
    target_tag_id: Optional[int] = Field(default=None, ge=0, le=586)


class HomographyCalibrateRequest(BaseModel):
    """Request body for interactive 4-point floor click homography calibration."""

    camera_id: str = Field(default=DEFAULT_CAMERA_ID, max_length=32)
    pixel_points_norm: List[Tuple[float, float]] = Field(..., min_length=4, max_length=16)
    world_points_xy: List[Tuple[float, float]] = Field(..., min_length=4, max_length=16)


class TaskPointRequest(BaseModel):
    """Request body for Click-on-Camera or direct BEV floor projection and optional PuppyPi dispatch."""

    camera_id: str = Field(default=DEFAULT_CAMERA_ID, max_length=32)
    u_norm: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    v_norm: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    target_xy: Optional[Tuple[float, float]] = Field(default=None)
    standoff_m: float = Field(default=0.30, ge=0.0, le=2.0)
    dispatch: bool = Field(default=False)


class UpscaleRoiRequest(BaseModel):
    """Request body for Tiered ROI Super-Resolution (Local Lanczos/CLAHE or fal.ai)."""

    camera_id: str = Field(default=DEFAULT_CAMERA_ID, max_length=32)
    bbox_norm: List[float] = Field(..., min_length=4, max_length=4)
    mode: str = Field(default="local", pattern="^(local|fal)$")
    scale: int = Field(default=2, ge=2, le=4)
    model: Optional[str] = Field(default=None, max_length=64)


@router.get("/geometry")
async def get_overwatch_geometry(
    request: Request,
    max_range_m: float = Query(default=6.0, ge=1.0, le=15.0),
) -> Dict[str, Any]:
    """Return camera frustum polygons, 0/1/2/3+ overlap zones, Placement Advisor, and global tracks."""
    mgr = _get_overwatch_manager(request)
    runtime = getattr(request.app.state, "runtime", None)
    return mgr.get_geometry_snapshot(runtime=runtime, max_range_m=max_range_m)


@router.post("/calibrate/apriltag")
async def calibrate_overwatch_apriltag(
    request: Request,
    payload: AprilTagCalibrateRequest,
) -> Dict[str, Any]:
    """Auto-calibrate one or all active overwatch cameras via a visible AprilTag (solvePnP)."""
    mgr = _get_overwatch_manager(request)
    try:
        return mgr.calibrate_apriltag(
            camera_id=payload.camera_id,
            tag_size_m=payload.tag_size_m,
            tag_world_xyz=(payload.tag_world_x, payload.tag_world_y, payload.tag_world_z),
            tag_world_yaw_deg=payload.tag_world_yaw_deg,
            target_tag_id=payload.target_tag_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/calibrate/homography")
async def calibrate_overwatch_homography(
    request: Request,
    payload: HomographyCalibrateRequest,
) -> Dict[str, Any]:
    """Calibrate an overwatch camera from 4+ clicked floor points (zero printed tags required)."""
    mgr = _get_overwatch_manager(request)
    try:
        return mgr.calibrate_homography(
            camera_id=payload.camera_id,
            pixel_points_norm=payload.pixel_points_norm,
            world_points_xy=payload.world_points_xy,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/task-point")
async def project_or_dispatch_task_point(
    request: Request,
    payload: TaskPointRequest,
) -> Dict[str, Any]:
    """Project a clicked camera pixel or BEV floor coordinate and optionally dispatch PuppyPi."""
    import math as _math

    mgr = _get_overwatch_manager(request)
    runtime = getattr(request.app.state, "runtime", None)
    if payload.target_xy is not None:
        tx, ty = float(payload.target_xy[0]), float(payload.target_xy[1])
        rpose = getattr(runtime, "robot_pose", None) if runtime is not None else None
        rx = float((rpose or {}).get("x") or 0.0)
        ry = float((rpose or {}).get("y") or 0.0)
        ryaw = float((rpose or {}).get("yaw_deg") or 0.0)
        dx, dy = tx - rx, ty - ry
        dist_r = _math.hypot(dx, dy)
        walk_dist = max(0.0, dist_r - max(0.0, float(payload.standoff_m)))
        heading = _math.degrees(_math.atan2(dy, dx)) if dist_r > 1e-4 else ryaw
        rel_turn = ((heading - ryaw + 180.0) % 360.0) - 180.0
        proj = {
            "ok": True,
            "camera_id": payload.camera_id or "bev_map",
            "target_xy": [round(tx, 3), round(ty, 3)],
            "waypoint_xy": [round(rx + (dx / dist_r) * walk_dist, 3) if dist_r > 1e-4 else rx, round(ry + (dy / dist_r) * walk_dist, 3) if dist_r > 1e-4 else ry],
            "projection_method": "bev_direct_click",
            "distance_from_robot_m": round(dist_r, 3),
            "walk_distance_m": round(walk_dist, 3),
            "target_heading_deg": round(heading, 1),
            "relative_turn_deg": round(rel_turn, 1),
        }
    elif payload.u_norm is not None and payload.v_norm is not None:
        try:
            proj = mgr.project_task_point(
                camera_id=payload.camera_id,
                u_norm=payload.u_norm,
                v_norm=payload.v_norm,
                runtime=runtime,
                standoff_m=payload.standoff_m,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    else:
        raise HTTPException(status_code=400, detail="Provide either (u_norm, v_norm) or target_xy.")

    dispatched = False
    dispatch_note = "Preview only (dispatch=false)."
    if payload.dispatch:
        # Guard against active E-STOP
        if getattr(request.app.state, "estop_active", False):
            raise HTTPException(status_code=409, detail="Global E-STOP is active. Clear E-STOP before dispatching PuppyPi.")
        from src.agent.robot_tools import execute_robot_tool

        turn_deg = float(proj.get("relative_turn_deg") or 0.0)
        walk_m = min(2.0, float(proj.get("walk_distance_m") or 0.0))
        notes: List[str] = []
        try:
            if abs(turn_deg) >= 8.0:
                res_turn = await execute_robot_tool(
                    "turn_angle",
                    {"degrees": round(turn_deg, 1)},
                    app_state=request.app.state,
                )
                notes.append(f"turn={res_turn.get('ok', False)}")
            if walk_m >= 0.12:
                res_walk = await execute_robot_tool(
                    "walk_distance",
                    {"meters": round(walk_m, 2)},
                    app_state=request.app.state,
                )
                notes.append(f"walk={res_walk.get('ok', False)}")
            dispatched = True
            dispatch_note = "Dispatched PuppyPi to floor waypoint (" + (", ".join(notes) or "already in standoff range") + ")."
        except Exception as exc:
            sys.stderr.write(f"[overwatch.task_point] Dispatch error: {exc}\n")
            dispatch_note = f"Projection succeeded, robot dispatch error: {exc}"

    return {
        **proj,
        "dispatched": dispatched,
        "dispatch_note": dispatch_note,
    }


@router.post("/upscale-roi")
async def upscale_overwatch_roi(
    request: Request,
    payload: UpscaleRoiRequest,
) -> Dict[str, Any]:
    """Extract a target ROI crop and enhance locally (Lanczos+CLAHE) or via fal.ai."""
    mgr = _get_overwatch_manager(request)
    try:
        clean_cid = sanitize_camera_id(payload.camera_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    raw_jpeg = mgr.get_raw_frame_jpeg(camera_id=clean_cid)
    if not raw_jpeg:
        raise HTTPException(status_code=404, detail=f"No frame available for camera {clean_cid}.")

    if payload.mode == "local":
        try:
            return extract_and_enhance_local_roi(raw_jpeg=raw_jpeg, bbox_norm=payload.bbox_norm, scale=payload.scale)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Cloud fal.ai upscale using Fernet-encrypted fal_api_key from PostgreSQL app_settings
    runtime = getattr(request.app.state, "runtime", None)
    repo = getattr(request.app.state, "twin_repo", None) or getattr(runtime, "repo", None)
    raw_settings = repo.get_settings_raw() if repo is not None else {}
    api_key = str(raw_settings.get("fal_api_key") or "").strip()
    configured_model = str(raw_settings.get("fal_upscale_model") or "fal-ai/esrgan").strip()
    chosen_model = (payload.model or configured_model or "fal-ai/esrgan").strip()
    if chosen_model not in ALLOWED_FAL_UPSCALE_MODELS:
        chosen_model = "fal-ai/esrgan"

    try:
        return await upscale_roi_fal_ai(
            raw_jpeg=raw_jpeg,
            bbox_norm=payload.bbox_norm,
            api_key=api_key,
            model=chosen_model,
            scale=payload.scale,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


class MulticamReconstructRequest(BaseModel):
    """Request body for fusing all active Overwatch cameras + PuppyPi FPV + LD19 LiDAR into a 3D GLB."""

    space_id: Optional[str] = Field(default=None, max_length=64)
    robot_id: Optional[str] = Field(default=None, max_length=64)
    include_puppypi_fpv: bool = Field(default=True)
    resolution: str = Field(default="medium", pattern="^(low|medium|high)$")


class SuggestMappingRouteRequest(BaseModel):
    """Request body for generating blind-spot patrol waypoints."""

    max_waypoints: int = Field(default=4, ge=2, le=6)
    safe_radius_m: float = Field(default=2.2, ge=0.8, le=4.0)


@router.get("/stability-presets")
async def get_stability_presets() -> Dict[str, Any]:
    """Return all tip-proof PuppyPi Pro surface/gait stability presets."""
    from src.robot.stability_guard import DEFAULT_STABILITY_PRESET, STABLE_GAIT_PRESETS

    return {
        "default": DEFAULT_STABILITY_PRESET,
        "presets": [p.to_dict() for p in STABLE_GAIT_PRESETS.values()],
    }


@router.post("/suggest-mapping-route")
async def suggest_overwatch_mapping_route(
    request: Request,
    payload: SuggestMappingRouteRequest,
) -> Dict[str, Any]:
    """Suggest safe indoor patrol waypoints targeting 0-camera blind spots & mono zones."""
    from src.lidar.multicam_room_fuser import suggest_blind_spot_mapping_route

    mgr = _get_overwatch_manager(request)
    runtime = getattr(request.app.state, "runtime", None)
    geo = mgr.get_geometry_snapshot(runtime=runtime)
    return suggest_blind_spot_mapping_route(
        geometry_snapshot=geo,
        max_waypoints=payload.max_waypoints,
        safe_radius_m=payload.safe_radius_m,
    )


@router.post("/reconstruct-multicam")
async def reconstruct_multicam_digital_twin(
    request: Request,
    payload: MulticamReconstructRequest,
) -> Dict[str, Any]:
    """Fuse all active Overwatch cameras + optional PuppyPi FPV + LD19 LiDAR into a 3D .glb Digital Twin."""
    from src.lidar.multicam_room_fuser import fuse_multicam_room_digital_twin
    from src.robot.rosbridge_proxy import fetch_robot_snapshot

    mgr = _get_overwatch_manager(request)
    runtime = getattr(request.app.state, "runtime", None)
    repo = getattr(request.app.state, "twin_repo", None) or getattr(runtime, "repo", None)

    puppypi_jpeg: Optional[bytes] = None
    if payload.include_puppypi_fpv:
        # Try fetching a fresh snapshot from the active robot if registered
        robot_store = getattr(request.app.state, "robot_store", None)
        target_robot = None
        if robot_store is not None:
            try:
                robots = robot_store.list_robots()
                if payload.robot_id:
                    target_robot = next((r for r in robots if r.get("id") == payload.robot_id), None)
                elif robots:
                    target_robot = robots[0]
            except Exception as exc:
                sys.stderr.write(f"[overwatch.reconstruct] Robot lookup warning: {exc}\n")
        if target_robot and target_robot.get("ip_address"):
            from src.robot.ros_profiles import get_ros_profile, normalize_ros_mode

            ros_ver = normalize_ros_mode(target_robot.get("active_ros_distro"))
            primary_topic = get_ros_profile(ros_ver)["camera_topic"]
            alt_topic = "/usb_cam/image_raw" if primary_topic == "/image_raw" else "/image_raw"
            for topic_try in (primary_topic, alt_topic):
                try:
                    snap = await fetch_robot_snapshot(
                        ip=str(target_robot["ip_address"]),
                        video_port=int(target_robot.get("video_port") or 8080),
                        topic=topic_try,
                    )
                    if snap and len(snap) > 1000:
                        puppypi_jpeg = snap
                        break
                except Exception as exc:
                    sys.stderr.write(f"[overwatch.reconstruct] PuppyPi FPV snapshot ({topic_try}) skipped: {exc}\n")

    try:
        return await asyncio.to_thread(
            fuse_multicam_room_digital_twin,
            overwatch_manager=mgr,
            runtime=runtime,
            repo=repo,
            space_id=payload.space_id,
            puppypi_jpeg=puppypi_jpeg,
            resolution=payload.resolution,
            allow_model_download=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        sys.stderr.write(f"[overwatch.reconstruct] Multi-camera fusion failed: {exc}\n")
        raise HTTPException(status_code=500, detail=f"Multi-camera 3D fusion failed: {exc}") from exc


@router.get("/latest-twin-glb")
async def get_latest_multicam_twin_glb(
    request: Request,
    space_id: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    """Return metadata and download URL for the most recent fused multi-camera 3D .glb Digital Twin."""
    runtime = getattr(request.app.state, "runtime", None)
    repo = getattr(request.app.state, "twin_repo", None) or getattr(runtime, "repo", None)
    if repo is None:
        return {"found": False}
    files = repo.list_files(category="reconstruction_glb", space_id=space_id)
    for f in files:
        meta = f.get("metadata") or {}
        if meta.get("kind") == "multicam_digital_twin" or str(f.get("filename", "")).startswith("multicam_"):
            fid = str(f.get("id") or "")
            return {
                "found": True,
                "file_id": fid,
                "filename": f.get("filename"),
                "size_bytes": f.get("size_bytes"),
                "created_at": f.get("created_at"),
                "metadata": meta,
                "download_url": f"/api/files/{fid}/download",
            }
    return {"found": False}


class RemoteOverwatchSourceRequest(BaseModel):
    """Register or update a remote HTTP MJPEG/snapshot camera feeding Overwatch."""

    camera_id: str = Field(default=DEFAULT_CAMERA_ID, max_length=32)
    stream_url: str = Field(..., min_length=8, max_length=512)
    camera_name: Optional[str] = Field(default=None, max_length=96)
    fps: float = Field(default=15.0, ge=0.5, le=60.0)
    enabled: bool = Field(default=True)


def _get_remote_puller(request: Request):
    from src.vision.remote_camera_puller import RemoteOverwatchPullerManager

    puller = getattr(request.app.state, "remote_overwatch_puller", None)
    if puller is None:
        puller = RemoteOverwatchPullerManager()
        request.app.state.remote_overwatch_puller = puller
    return puller


@router.get("/remote-sources")
async def list_remote_overwatch_sources(request: Request) -> Dict[str, Any]:
    """List all persisted remote Pi/IP Overwatch camera pullers and their live stats."""
    puller = _get_remote_puller(request)
    sources = puller.list_sources()
    return {"sources": sources, "count": len(sources)}


@router.post("/remote-sources")
async def upsert_remote_overwatch_source(
    request: Request,
    payload: RemoteOverwatchSourceRequest,
) -> Dict[str, Any]:
    """Register or update a remote HTTP MJPEG/snapshot camera and start pulling it into Overwatch."""
    puller = _get_remote_puller(request)
    mgr = _get_overwatch_manager(request)
    puller.bind_runtime(
        overwatch_manager=mgr,
        ai_vision_engine=getattr(request.app.state, "ai_vision_engine", None),
        ai_store=getattr(request.app.state, "robot_ai_store", None),
        runtime=getattr(request.app.state, "runtime", None),
    )
    try:
        source = await puller.upsert_source(
            camera_id=payload.camera_id,
            stream_url=payload.stream_url,
            camera_name=payload.camera_name,
            fps=payload.fps,
            enabled=payload.enabled,
        )
        return {"ok": True, "source": source}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        sys.stderr.write(f"[overwatch.remote_sources] Registration failed: {exc}\n")
        raise HTTPException(status_code=500, detail=f"Failed to register remote source: {exc}") from exc


@router.delete("/remote-sources/{camera_id}")
async def delete_remote_overwatch_source(request: Request, camera_id: str) -> Dict[str, Any]:
    """Stop and remove a persisted remote Overwatch camera puller."""
    puller = _get_remote_puller(request)
    try:
        removed = await puller.remove_source(camera_id)
        return {"ok": True, "removed": removed, "camera_id": camera_id}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
