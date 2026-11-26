"""FastAPI router for 4K/1080p USB & MacBook Overwatch Vision and 3D Triangulation."""

from __future__ import annotations

import asyncio
import sys
from typing import Any, AsyncIterator, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from src.vision.overwatch_triangulator import (
    DEFAULT_CAMERA_ID,
    OverwatchCameraManager,
    sanitize_camera_id,
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
