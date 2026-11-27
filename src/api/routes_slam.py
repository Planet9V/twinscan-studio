"""FastAPI router for the dedicated SLAM Mapping Studio (/slam)."""

from __future__ import annotations

import sys
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from src.slam.slam_controller import SlamSessionManager

router = APIRouter(prefix="/api/slam", tags=["slam"])


def _get_slam(request: Request) -> SlamSessionManager:
    mgr = getattr(request.app.state, "slam_manager", None)
    if mgr is None:
        mgr = SlamSessionManager()
        request.app.state.slam_manager = mgr
    return mgr


def _get_repo(request: Request) -> Any:
    runtime = getattr(request.app.state, "runtime", None)
    return getattr(request.app.state, "twin_repo", None) or getattr(runtime, "repo", None)


class SlamStartRequest(BaseModel):
    """Start ROS 2 SLAM on the target PuppyPi robot."""

    robot_id: Optional[str] = Field(default=None, max_length=64)


class SlamSaveRequest(BaseModel):
    """Save current SLAM map snapshot to PostgreSQL 18."""

    name: str = Field(default="SLAM Floor Map", min_length=1, max_length=96)


class SlamExportTwinRequest(BaseModel):
    """Export current SLAM map into an extruded 3D wall .glb and Room Twin Studio project."""

    name: str = Field(default="SLAM Scanned Room", min_length=1, max_length=96)
    wall_height_m: float = Field(default=2.5, ge=1.5, le=6.0)


@router.get("/status")
async def get_slam_status(request: Request) -> Dict[str, Any]:
    """Return live SLAM session status, coverage metrics, and saved maps."""
    return {"ok": True, **_get_slam(request).get_status()}


@router.post("/start")
async def start_slam_session(request: Request, payload: SlamStartRequest) -> Dict[str, Any]:
    """Launch ROS 2 hiwonder_slam / slam_toolbox on PuppyPi and stream live /map."""
    mgr = _get_slam(request)
    robot_store = getattr(request.app.state, "robot_store", None)
    try:
        st = await mgr.start_slam(robot_store=robot_store, robot_id=payload.robot_id)
        return {"ok": True, **st}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        sys.stderr.write(f"[api.slam.start] Error: {exc}\n")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/stop")
async def stop_slam_session(request: Request, payload: Optional[SlamStartRequest] = None) -> Dict[str, Any]:
    """Stop live SLAM streaming and terminate remote ROS 2 SLAM nodes."""
    mgr = _get_slam(request)
    robot_store = getattr(request.app.state, "robot_store", None)
    rid = payload.robot_id if payload else None
    st = await mgr.stop_slam(robot_store=robot_store, robot_id=rid)
    return {"ok": True, **st}


@router.get("/map-image")
async def get_slam_map_image(request: Request) -> Response:
    """Return a crisp PNG render of the live SLAM OccupancyGrid."""
    png = _get_slam(request).get_map_png()
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.post("/save")
async def save_slam_map(request: Request, payload: SlamSaveRequest) -> Dict[str, Any]:
    """Save the current SLAM map snapshot into PostgreSQL 18."""
    mgr = _get_slam(request)
    repo = _get_repo(request)
    try:
        saved = mgr.save_map(repo=repo, name=payload.name)
        return {"ok": True, "map": saved}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/export-to-twin")
async def export_slam_to_digital_twin(request: Request, payload: SlamExportTwinRequest) -> Dict[str, Any]:
    """Extrude SLAM walls to a 3D .glb and create a matching Room Twin Studio project."""
    mgr = _get_slam(request)
    repo = _get_repo(request)
    room_store = getattr(request.app.state, "room_studio_store", None)
    if room_store is None and repo is not None:
        from src.room_studio.models import RoomStudioStore

        room_store = RoomStudioStore()
        room_store.attach_repository(repo)
        request.app.state.room_studio_store = room_store
    try:
        return mgr.export_to_digital_twin(
            repo=repo,
            room_studio_store=room_store,
            name=payload.name,
            wall_height_m=payload.wall_height_m,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        sys.stderr.write(f"[api.slam.export] Error: {exc}\n")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
