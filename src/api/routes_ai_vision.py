"""FastAPI endpoints for ROS 2/1 Offloaded AI Vision Studio, Known People Face Recognition Registry, and Autonomous Patrol."""

from __future__ import annotations

import asyncio
import sys
import time
from typing import Any, Dict, List, Literal, Optional

import cv2
import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.api.state import TwinScanRuntimeState
from src.db.robot_ai_store import RobotAiStoreProtocol
from src.db.robot_store import RobotStoreProtocol
from src.lidar.composite_enhancer import resolve_enhance_preset
from src.lidar.scene_reconstructor import reconstruct_enhanced_wall_panel
from src.lidar.spatial_3d import raycast_camera_to_lidar
from src.robot.explorer_engine import (
    AutonomousExplorerManager,
    compute_battery_pct_2s,
    compute_room_coverage_pct,
    detect_apriltag_home_in_jpeg,
)
from src.robot.patrol_engine import RobotPatrolManager, compute_live_sectors_from_points
from src.robot.ros_profiles import get_ros_profile, normalize_ros_mode
from src.robot.rosbridge_proxy import fetch_robot_snapshot, run_action
from src.robot.sentry_manager import RobotSentryManager
from src.robot.ssh_manager import SSHAuthError, SSHCommandError, start_robot_lidar_node
from src.robot.voice_manager import speak_text_on_robot
from src.vision.robot_ai_vision import RobotAiVisionEngine, deep_identify_frame

router = APIRouter(tags=["ai-vision"])


# --- Request Models ---


class AiVisionModeRequest(BaseModel):
    """Switch active AI Vision mode, FPS/confidence tuning, and safety/autonomy flags."""

    mode: str = "raw"
    follow_enabled: Optional[bool] = None
    line_follow_enabled: Optional[bool] = None
    auto_greet_enabled: Optional[bool] = None
    lidar_stop_m: Optional[float] = Field(default=None, ge=0.15, le=2.0)
    line_color: Optional[str] = None
    target_fps: Optional[float] = Field(default=None, ge=1.0, le=20.0)
    conf_threshold: Optional[float] = Field(default=None, ge=0.20, le=0.80)


class SentryConfigUpdateRequest(BaseModel):
    """Autonomous Sentry Guard Mode rules & alert preferences."""

    watch_motion: Optional[bool] = None
    watch_unknown_faces: Optional[bool] = None
    watch_animals: Optional[bool] = None
    speak_challenge: Optional[bool] = None
    flash_rgb: Optional[bool] = None
    cooldown_sec: Optional[int] = Field(default=None, ge=5, le=300)
    custom_challenge: Optional[str] = None


class SelectTargetRequest(BaseModel):
    """Normalized ``(0..1, 0..1)`` click coordinates for Click-to-Track target lock."""

    norm_x: float = Field(ge=0.0, le=1.0)
    norm_y: float = Field(ge=0.0, le=1.0)
    clear: bool = False


class PickColorRequest(BaseModel):
    """Normalized ``(0..1, 0..1)`` click coordinates for Line Follow v2 HSV eyedropper."""

    norm_x: float = Field(ge=0.0, le=1.0)
    norm_y: float = Field(ge=0.0, le=1.0)


class DeepIdentifyRequest(BaseModel):
    """On-demand OpenRouter VLM deep identification request for live PuppyPi FPV."""

    speak_result: bool = False
    prompt: Optional[str] = None


class EnrollCameraPersonRequest(BaseModel):
    """Enroll a known person for face recognition from PuppyPi's live camera."""

    name: str
    role: str = "Operator"
    greeting_phrase: Optional[str] = None
    greet_action: str = "none"
    auto_speak: bool = True
    notes: str = ""


class UpdatePersonRequest(BaseModel):
    """Editable fields on a known person record."""

    name: Optional[str] = None
    role: Optional[str] = None
    greeting_phrase: Optional[str] = None
    greet_action: Optional[str] = None
    auto_speak: Optional[bool] = None
    notes: Optional[str] = None


class PatrolWaypointPayload(BaseModel):
    """Single 2D patrol waypoint in meters relative to robot start frame."""

    x: float
    y: float
    label: str = ""
    pause_sec: float = Field(default=0.5, ge=0.0, le=30.0)


class SavePatrolRouteRequest(BaseModel):
    """Create a named multi-waypoint patrol route."""

    name: str
    space_id: Optional[str] = None
    waypoints: List[PatrolWaypointPayload]
    loop_enabled: bool = True
    max_speed_cms: float = Field(default=12.0, ge=4.0, le=25.0)
    obstacle_clearance_m: float = Field(default=0.45, ge=0.20, le=2.0)


class StartPatrolRequest(BaseModel):
    """Start an autonomous patrol from a saved ``route_id`` or ad-hoc ``waypoints``."""

    route_id: Optional[str] = None
    waypoints: Optional[List[PatrolWaypointPayload]] = None
    loop_enabled: bool = True
    max_speed_cms: float = Field(default=12.0, ge=4.0, le=25.0)
    obstacle_clearance_m: float = Field(default=0.45, ge=0.20, le=2.0)
    announce_voice: bool = False
    require_lidar: bool = True
    camera_avoidance: bool = True


# --- Helpers ---


def _robot_store(request: Request) -> RobotStoreProtocol:
    return request.app.state.robot_store


def _ai_store(request: Request) -> RobotAiStoreProtocol:
    return request.app.state.robot_ai_store


def _ai_vision(request: Request) -> RobotAiVisionEngine:
    return request.app.state.ai_vision_engine


def _patrol_manager(request: Request) -> RobotPatrolManager:
    return request.app.state.patrol_manager


def _sentry_manager(request: Request) -> RobotSentryManager:
    return request.app.state.sentry_manager


def _runtime(request: Request) -> TwinScanRuntimeState:
    return request.app.state.runtime


def _require_robot(store: RobotStoreProtocol, robot_id: str) -> Dict[str, Any]:
    robot = store.get_robot(robot_id)
    if not robot:
        raise HTTPException(status_code=404, detail=f"Robot {robot_id} not found.")
    return robot


def _front_lidar_clearance_m(rt: TwinScanRuntimeState) -> float:
    """Compute minimum front-sector ([-25°, +25°]) LiDAR distance in meters from runtime points."""
    min_d = 9.9
    for pt in rt.latest_points or []:
        ang = float(getattr(pt, "angle_deg", 0.0))
        norm = ((ang + 180.0) % 360.0) - 180.0
        if -25.0 <= norm <= 25.0:
            dist = float(getattr(pt, "distance_m", 9.9))
            if 0.05 <= dist <= 12.0:
                min_d = min(min_d, dist)
    return min_d


def _camera_topic_for_robot(robot: Dict[str, Any]) -> str:
    return get_ros_profile(normalize_ros_mode(robot.get("active_ros_distro")))["camera_topic"]


async def _fetch_live_frame_bytes(robot: Dict[str, Any]) -> bytes:
    """Fetch a live JPEG snapshot from the robot using its ROS-mode camera topic (with fallback)."""
    ip = robot["ip_address"]
    video_port = int(robot.get("video_port") or 8080)
    ros_mode = normalize_ros_mode(robot.get("active_ros_distro"))
    primary = get_ros_profile(ros_mode)["camera_topic"]
    fallback = "/usb_cam/image_raw" if primary != "/usb_cam/image_raw" else "/image_raw"
    try:
        return await fetch_robot_snapshot(ip=ip, port=video_port, topic=primary, timeout=4.0, retries=2)
    except Exception:
        return await fetch_robot_snapshot(ip=ip, port=video_port, topic=fallback, timeout=4.0, retries=1)


# --- AI Vision Studio Endpoints ---


@router.get("/api/robots/{robot_id}/ai-vision/stream")
async def robot_ai_vision_stream(robot_id: str, request: Request) -> StreamingResponse:
    """Stream live backend-annotated AI Vision MJPEG overlays for PuppyPi."""
    store = _robot_store(request)
    robot = _require_robot(store, robot_id)
    rt = _runtime(request)
    engine = _ai_vision(request)
    ai_store = _ai_store(request)
    ssh_pw = store.get_robot_ssh_password(robot_id)
    ros_mode = normalize_ros_mode(robot.get("active_ros_distro"))
    rosbridge_port = int(robot.get("rosbridge_port") or 9090)

    async def _on_greet(person: Dict[str, Any]) -> None:
        phrase = str(person.get("greeting_phrase") or f"Hello {person.get('name', 'friend')}!")
        action_name = str(person.get("greet_action") or "none")
        if person.get("auto_speak", True) and ssh_pw:
            try:
                vcfg = ai_store.get_voice_config(robot_id)
                await speak_text_on_robot(
                    ip=robot["ip_address"],
                    user=robot["ssh_user"],
                    password=ssh_pw,
                    text=phrase,
                    engine=str(vcfg.get("default_engine") or "piper_tts"),
                    voice=vcfg.get("default_voice"),
                    anti_clip=bool(vcfg.get("anti_clip", True)),
                )
                ai_store.record_voice_log(
                    robot_id=robot_id,
                    direction="out",
                    transcript=f"[auto-greet:{person.get('name')}]",
                    action_taken=f"greet:{action_name}",
                    reply_text=phrase,
                )
            except Exception as exc:
                sys.stderr.write(f"[ai_vision.greet] TTS failed: {exc}\n")
        if action_name and action_name != "none":
            try:
                await run_action(
                    ip=robot["ip_address"],
                    port=rosbridge_port,
                    name=action_name,
                    wait=False,
                    ros_version=ros_mode,
                    robot_id=robot_id,
                )
            except Exception as exc:
                sys.stderr.write(f"[ai_vision.greet] Action {action_name} failed: {exc}\n")

    async def _on_sighting(det: Dict[str, Any], raw_jpg: bytes) -> None:
        try:
            stored = rt.repo.store_file(
                filename=f"sighting-{robot_id[:8]}-{int(time.time())}.jpg",
                content_type="image/jpeg",
                data=raw_jpg,
                category="spatial_sighting",
                space_id=rt.active_space_id or None,
                metadata={"robot_id": robot_id, "label": det.get("label")},
            )
            pose = raycast_camera_to_lidar(
                bbox_norm=det.get("bbox_norm"),
                lidar_points=rt.latest_points,
                camera_fov_deg=rt.default_camera_fov_deg,
                camera_yaw_deg=float(rt.robot_pose.get("yaw_deg", 0.0)),
            )
            ai_store.record_spatial_sighting(
                robot_id,
                {
                    "space_id": rt.active_space_id or None,
                    "label": str(det.get("label") or "object").split(" (")[0],
                    "kind": str(det.get("kind") or "object"),
                    "x_m": float((pose or {}).get("x", rt.robot_pose.get("x", 0.0))),
                    "y_m": float((pose or {}).get("y", rt.robot_pose.get("y", 0.0))),
                    "confidence": float(det.get("confidence", 0.5)),
                    "snapshot_file_id": stored["id"],
                    "notes": f"Observed automatically in {engine.get_state(robot_id)['mode']} mode",
                },
            )
        except Exception as exc:
            sys.stderr.write(f"[spatial_memory] Auto-sighting failed: {exc}\n")

    return StreamingResponse(
        engine.stream_annotated_mjpeg(
            robot_id=robot_id,
            robot_ip=robot["ip_address"],
            video_port=int(robot.get("video_port") or 8080),
            rosbridge_port=rosbridge_port,
            ros_version=ros_mode,
            get_front_lidar_m=lambda: _front_lidar_clearance_m(rt),
            on_greet=_on_greet,
            is_disconnected=request.is_disconnected,
            on_sighting=_on_sighting,
        ),
        media_type="multipart/x-mixed-replace; boundary=boundarydonotcross",
    )


@router.get("/api/robots/{robot_id}/ai-vision/state")
async def robot_ai_vision_state(robot_id: str, request: Request) -> Dict[str, Any]:
    """Return current AI Vision mode, ONNX readiness, tracked target, and latest detections."""
    _require_robot(_robot_store(request), robot_id)
    return _ai_vision(request).get_state(robot_id)


@router.post("/api/robots/{robot_id}/ai-vision/mode")
async def robot_ai_vision_mode(
    robot_id: str,
    body: AiVisionModeRequest,
    request: Request,
) -> Dict[str, Any]:
    """Switch AI Vision mode, FPS/confidence tuning, and autonomous follow/line-follow/auto-greet toggles."""
    _require_robot(_robot_store(request), robot_id)
    try:
        return _ai_vision(request).set_mode(
            robot_id=robot_id,
            mode=body.mode,
            follow_enabled=body.follow_enabled,
            line_follow_enabled=body.line_follow_enabled,
            auto_greet_enabled=body.auto_greet_enabled,
            lidar_stop_m=body.lidar_stop_m,
            line_color=body.line_color,
            target_fps=body.target_fps,
            conf_threshold=body.conf_threshold,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/robots/{robot_id}/ai-vision/select-target")
async def robot_ai_vision_select_target(
    robot_id: str,
    body: SelectTargetRequest,
    request: Request,
) -> Dict[str, Any]:
    """Lock or clear the Click-to-Track target box at normalized ``(norm_x, norm_y)``."""
    _require_robot(_robot_store(request), robot_id)
    return _ai_vision(request).select_target(
        robot_id=robot_id,
        norm_x=body.norm_x,
        norm_y=body.norm_y,
        clear=body.clear,
    )


@router.post("/api/robots/{robot_id}/ai-vision/pick-color")
async def robot_ai_vision_pick_color(
    robot_id: str,
    body: PickColorRequest,
    request: Request,
) -> Dict[str, Any]:
    """Sample a custom HSV floor-line color from the live camera frame at ``(norm_x, norm_y)``."""
    robot = _require_robot(_robot_store(request), robot_id)
    engine = _ai_vision(request)
    frame_bgr: Optional[np.ndarray] = None
    if robot_id not in engine._last_frames:
        try:
            jpg = await _fetch_live_frame_bytes(robot)
            arr = np.frombuffer(jpg, dtype=np.uint8)
            frame_bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        except Exception as exc:
            sys.stderr.write(f"[ai_vision.pick_color] Live snapshot fallback failed: {exc}\n")
    return engine.pick_line_color(
        robot_id=robot_id,
        norm_x=body.norm_x,
        norm_y=body.norm_y,
        frame_bgr=frame_bgr,
    )


@router.post("/api/robots/{robot_id}/ai-vision/deep-identify")
async def robot_ai_vision_deep_identify(
    robot_id: str,
    body: DeepIdentifyRequest,
    request: Request,
) -> Dict[str, Any]:
    """Snap a live PuppyPi frame, identify animals/objects via OpenRouter VLM, and optionally speak it."""
    store = _robot_store(request)
    robot = _require_robot(store, robot_id)
    rt = _runtime(request)
    try:
        image_bytes = await _fetch_live_frame_bytes(robot)
    except ConnectionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    res = await deep_identify_frame(
        image_bytes=image_bytes,
        api_key=rt.effective_config.get("openrouter_api_key", ""),
        base_url=rt.effective_config.get("openrouter_base_url", rt.settings.openrouter_base_url),
        model=rt.effective_config.get(
            "openrouter_default_vision_model", rt.settings.openrouter_default_vision_model
        ),
        prompt=body.prompt,
    )
    spoken = False
    if body.speak_result and res.get("description"):
        ssh_pw = store.get_robot_ssh_password(robot_id)
        if ssh_pw:
            try:
                await speak_text_on_robot(
                    ip=robot["ip_address"],
                    user=robot["ssh_user"],
                    password=ssh_pw,
                    text=str(res["description"])[:240],
                    engine="auto",
                    anti_clip=True,
                )
                spoken = True
                _ai_store(request).record_voice_log(
                    robot_id=robot_id,
                    direction="out",
                    transcript="[deep-identify]",
                    action_taken="ai_vision:deep_identify",
                    reply_text=str(res["description"])[:240],
                )
            except Exception as exc:
                sys.stderr.write(f"[ai_vision.deep_identify] Speak failed: {exc}\n")

    return {
        "ok": bool(res.get("ok", True)),
        "description": str(res.get("description") or ""),
        "objects": list(res.get("objects") or []),
        "animals": list(res.get("animals") or []),
        "spoken": spoken,
        "model_used": res.get("model_used"),
    }


# --- Known People Face Recognition Registry ---


def _enroll_person_from_bytes(
    request: Request,
    image_bytes: bytes,
    filename: str,
    name: str,
    role: str,
    greeting_phrase: Optional[str],
    greet_action: str,
    auto_speak: bool,
    notes: str,
) -> Dict[str, Any]:
    """Store avatar in PG18 ``stored_files``, extract 128-D embedding, and create/append person."""
    ai_store = _ai_store(request)
    engine = _ai_vision(request)
    rt = _runtime(request)

    clean_name = name.strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail="Person name is required.")

    try:
        embedding, face_detected = engine.extract_enrollment_embedding(image_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    stored = rt.repo.store_file(
        filename=filename,
        content_type="image/jpeg",
        data=image_bytes,
        category="person_face_avatar",
        space_id=rt.active_space_id or None,
        metadata={"person_name": clean_name, "face_detected": face_detected},
    )

    # Append embedding if a person with the exact same name already exists, else create new
    existing = next((p for p in ai_store.list_people() if p["name"].lower() == clean_name.lower()), None)
    if existing is not None:
        person = ai_store.update_person(
            existing["id"],
            {
                "role": role or existing["role"],
                "greeting_phrase": greeting_phrase or existing["greeting_phrase"],
                "greet_action": greet_action or existing["greet_action"],
                "auto_speak": auto_speak,
                "avatar_file_id": stored["id"],
                "notes": notes if notes else existing["notes"],
            },
        )
        assert person is not None
    else:
        person = ai_store.create_person(
            {
                "name": clean_name,
                "role": role or "Operator",
                "greeting_phrase": greeting_phrase or f"Hello {clean_name}!",
                "greet_action": greet_action or "none",
                "auto_speak": auto_speak,
                "avatar_file_id": stored["id"],
                "notes": notes,
            }
        )

    ai_store.add_face_embedding(person["id"], embedding, source_file_id=stored["id"])
    refreshed = ai_store.get_person(person["id"]) or person
    return {"ok": True, "person": refreshed, "face_detected": face_detected}


@router.get("/api/people")
async def list_known_people(request: Request) -> Dict[str, List[Dict[str, Any]]]:
    """List all enrolled known people for PuppyPi face recognition."""
    return {"people": _ai_store(request).list_people()}


@router.post("/api/people/enroll-camera/{robot_id}")
async def enroll_person_from_camera(
    robot_id: str,
    body: EnrollCameraPersonRequest,
    request: Request,
) -> Dict[str, Any]:
    """Snap a live photo from PuppyPi's camera and enroll a known person's 128-D face embedding."""
    robot = _require_robot(_robot_store(request), robot_id)
    try:
        image_bytes = await _fetch_live_frame_bytes(robot)
    except ConnectionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    fname = f"person-{body.name.strip().lower().replace(' ', '_')}-{int(time.time())}.jpg"
    return _enroll_person_from_bytes(
        request=request,
        image_bytes=image_bytes,
        filename=fname,
        name=body.name,
        role=body.role,
        greeting_phrase=body.greeting_phrase,
        greet_action=body.greet_action,
        auto_speak=body.auto_speak,
        notes=body.notes,
    )


@router.post("/api/people/enroll-upload")
async def enroll_person_from_upload(
    request: Request,
    file: UploadFile = File(...),
    name: str = Form(...),
    role: str = Form(default="Operator"),
    greeting_phrase: Optional[str] = Form(default=None),
    greet_action: str = Form(default="none"),
    auto_speak: bool = Form(default=True),
    notes: str = Form(default=""),
) -> Dict[str, Any]:
    """Enroll a known person's 128-D face embedding from an uploaded photo."""
    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Uploaded image file is empty.")
    fname = file.filename or f"person-upload-{int(time.time())}.jpg"
    return _enroll_person_from_bytes(
        request=request,
        image_bytes=image_bytes,
        filename=fname,
        name=name,
        role=role,
        greeting_phrase=greeting_phrase,
        greet_action=greet_action,
        auto_speak=auto_speak,
        notes=notes,
    )


@router.put("/api/people/{person_id}")
async def update_known_person(
    person_id: str,
    body: UpdatePersonRequest,
    request: Request,
) -> Dict[str, Any]:
    """Update profile fields, greeting phrase, or opt-in greet action for a known person."""
    updated = _ai_store(request).update_person(person_id, body.model_dump(exclude_none=True))
    if not updated:
        raise HTTPException(status_code=404, detail=f"Person {person_id} not found.")
    return {"person": updated}


@router.delete("/api/people/{person_id}")
async def delete_known_person(person_id: str, request: Request) -> Dict[str, Any]:
    """Delete an enrolled person and all associated 128-D face embeddings."""
    if not _ai_store(request).delete_person(person_id):
        raise HTTPException(status_code=404, detail=f"Person {person_id} not found.")
    return {"deleted": True}


# --- Autonomous Multi-Waypoint Patrol Endpoints ---


@router.get("/api/robots/{robot_id}/patrol/routes")
async def list_patrol_routes(robot_id: str, request: Request) -> Dict[str, List[Dict[str, Any]]]:
    """List saved multi-waypoint patrol routes for ``robot_id``."""
    _require_robot(_robot_store(request), robot_id)
    return {"routes": _ai_store(request).list_patrol_routes(robot_id)}


@router.post("/api/robots/{robot_id}/patrol/routes")
async def save_patrol_route(
    robot_id: str,
    body: SavePatrolRouteRequest,
    request: Request,
) -> Dict[str, Any]:
    """Create and persist a named multi-waypoint patrol route in PostgreSQL."""
    _require_robot(_robot_store(request), robot_id)
    if not body.waypoints:
        raise HTTPException(status_code=400, detail="At least one waypoint is required.")
    try:
        route = _ai_store(request).create_patrol_route(
            robot_id=robot_id,
            data={
                "name": body.name,
                "space_id": body.space_id or _runtime(request).active_space_id or None,
                "waypoints": [wp.model_dump() for wp in body.waypoints],
                "loop_enabled": body.loop_enabled,
                "max_speed_cms": body.max_speed_cms,
                "obstacle_clearance_m": body.obstacle_clearance_m,
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"route": route}


@router.delete("/api/robots/{robot_id}/patrol/routes/{route_id}")
async def delete_patrol_route(robot_id: str, route_id: str, request: Request) -> Dict[str, Any]:
    """Delete a saved patrol route."""
    _require_robot(_robot_store(request), robot_id)
    if not _ai_store(request).delete_patrol_route(route_id):
        raise HTTPException(status_code=404, detail=f"Patrol route {route_id} not found.")
    return {"deleted": True}


@router.post("/api/robots/{robot_id}/patrol/start")
async def start_robot_patrol(
    robot_id: str,
    body: StartPatrolRequest,
    request: Request,
) -> Dict[str, Any]:
    """Start an autonomous multi-waypoint patrol with LD19 LiDAR VFH obstacle avoidance."""
    store = _robot_store(request)
    robot = _require_robot(store, robot_id)
    ai_store = _ai_store(request)
    patrol_mgr = _patrol_manager(request)
    ai_vision = _ai_vision(request)
    rt = _runtime(request)

    route_name = "Ad-hoc Patrol"
    waypoints: List[Dict[str, Any]] = []
    loop_enabled = body.loop_enabled
    max_speed = body.max_speed_cms
    clearance = body.obstacle_clearance_m

    if body.route_id:
        saved = ai_store.get_patrol_route(body.route_id)
        if not saved:
            raise HTTPException(status_code=404, detail=f"Patrol route {body.route_id} not found.")
        route_name = saved["name"]
        waypoints = list(saved["waypoints"])
        loop_enabled = bool(saved.get("loop_enabled", loop_enabled))
        max_speed = float(saved.get("max_speed_cms", max_speed))
        clearance = float(saved.get("obstacle_clearance_m", clearance))
    elif body.waypoints:
        waypoints = [wp.model_dump() for wp in body.waypoints]

    if not waypoints:
        raise HTTPException(status_code=400, detail="Provide either route_id or non-empty waypoints.")

    announce_fn = None
    if body.announce_voice:
        ssh_pw = store.get_robot_ssh_password(robot_id)
        if ssh_pw:

            async def _announce(msg: str) -> None:
                await speak_text_on_robot(
                    ip=robot["ip_address"],
                    user=robot["ssh_user"],
                    password=ssh_pw,
                    text=msg,
                    engine="auto",
                    anti_clip=True,
                )

            announce_fn = _announce

    # Mutual exclusion (P0-2): stop active Autonomous Explorer before starting Waypoint Patrol
    explorer_mgr = _explorer_manager(request)
    if explorer_mgr.get_status(robot_id).get("active"):
        await explorer_mgr.stop(
            robot_id=robot_id,
            ip=robot["ip_address"],
            rosbridge_port=int(robot.get("rosbridge_port") or 9090),
            ros_version=normalize_ros_mode(robot.get("active_ros_distro")),
        )

    return await patrol_mgr.start(
        robot_id=robot_id,
        ip=robot["ip_address"],
        rosbridge_port=int(robot.get("rosbridge_port") or 9090),
        ros_version=normalize_ros_mode(robot.get("active_ros_distro")),
        waypoints=waypoints,
        route_name=route_name,
        loop_enabled=loop_enabled,
        max_speed_cms=max_speed,
        obstacle_clearance_m=clearance,
        require_lidar=body.require_lidar,
        camera_avoidance=body.camera_avoidance,
        video_port=int(robot.get("video_port") or 8080),
        ai_vision_engine=ai_vision,
        get_lidar_points=lambda: (
            rt.latest_raw_points
            if (
                rt.source_mode == "robot_ros2"
                and rt.robot_scan_connected
                and float(rt._last_scan_mono or 0.0) > 0.0
                and (time.monotonic() - float(rt._last_scan_mono)) <= 2.5
            )
            else []
        ),
        get_visual_obstacle=lambda: ai_vision.get_visual_obstacle(robot_id),
        announce_fn=announce_fn,
    )


@router.post("/api/robots/{robot_id}/patrol/start-lidar")
async def robot_patrol_start_lidar(robot_id: str, request: Request) -> Dict[str, Any]:
    """Probe ``/dev/ldlidar`` and launch the ROS 2/1 LD19 LiDAR node publishing ``/scan``."""
    store = _robot_store(request)
    robot = _require_robot(store, robot_id)
    ssh_pw = store.get_robot_ssh_password(robot_id)
    ros_ver = normalize_ros_mode(robot.get("active_ros_distro"))
    try:
        result = await start_robot_lidar_node(
            ip=robot["ip_address"],
            user=robot["ssh_user"],
            password=ssh_pw,
            ros_version=ros_ver,
        )
    except SSHAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except SSHCommandError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if result.get("ok"):
        rt = _runtime(request)
        rt.source_mode = "robot_ros2"
        rt.simulator.simulate_moving_targets = False
        await rt.start_robot_ros2_bridge(
            robot_id=robot_id,
            ip=robot["ip_address"],
            rosbridge_port=int(robot.get("rosbridge_port") or 9090),
            ros_version=ros_ver,
        )
    return result


@router.post("/api/robots/{robot_id}/patrol/stop")
async def stop_robot_patrol(robot_id: str, request: Request) -> Dict[str, Any]:
    """Stop any active autonomous patrol for ``robot_id`` and publish zero velocity."""
    robot = _require_robot(_robot_store(request), robot_id)
    return await _patrol_manager(request).stop(
        robot_id=robot_id,
        ip=robot["ip_address"],
        rosbridge_port=int(robot.get("rosbridge_port") or 9090),
        ros_version=normalize_ros_mode(robot.get("active_ros_distro")),
    )


@router.get("/api/robots/{robot_id}/patrol/status")
async def get_robot_patrol_status(robot_id: str, request: Request) -> Dict[str, Any]:
    """Return live patrol progress, 5-sector LD19 LiDAR clearances, and visual obstacle state."""
    _require_robot(_robot_store(request), robot_id)
    status = _patrol_manager(request).get_status(robot_id)
    rt = _runtime(request)
    if (
        not status.get("active")
        and rt.source_mode == "robot_ros2"
        and rt.robot_scan_connected
        and rt.latest_raw_points
        and float(rt._last_scan_mono or 0.0) > 0.0
    ):
        age_sec = max(0.0, round(time.monotonic() - float(rt._last_scan_mono), 2))
        if age_sec <= 3.5:
            status["lidar_live"] = True
            status["lidar_age_sec"] = age_sec
            status["sectors_m"] = compute_live_sectors_from_points(rt.latest_raw_points)
    return status


# --- Stage 3: Autonomous Frontier Explorer, Multi-Angle 3D Mapper & Low-Battery RTH ---


class StartExplorerRequest(BaseModel):
    """Payload to start Stage 3 Autonomous Frontier Explorer & Multi-Angle 3D Room Mapper."""

    space_id: Optional[str] = None
    max_iterations: int = Field(default=6, ge=1, le=15)
    target_coverage_pct: float = Field(default=85.0, ge=40.0, le=99.0)
    capture_mode: Literal["quick_3", "level_360", "multi_pitch"] = "multi_pitch"
    quality_preset: Literal["fast", "balanced", "studio_ultra"] = "balanced"
    rth_battery_v: float = Field(default=7.1, ge=6.6, le=7.8)
    max_speed_cms: float = Field(default=10.0, ge=5.0, le=20.0)
    obstacle_clearance_m: float = Field(default=0.5, ge=0.3, le=1.2)
    apriltag_home_id: int = Field(default=0, ge=0, le=100)
    announce_voice: bool = True
    require_lidar: bool = True


def _explorer_manager(request: Request) -> AutonomousExplorerManager:
    mgr = getattr(request.app.state, "explorer_manager", None)
    if mgr is None:
        mgr = AutonomousExplorerManager()
        request.app.state.explorer_manager = mgr
    return mgr


def _resolve_live_battery_v(rt: TwinScanRuntimeState, robot: Dict[str, Any]) -> Optional[float]:
    live_v = (rt.robot_pose or {}).get("battery_v")
    if live_v is not None:
        try:
            v = float(live_v)
            if v > 1.0:
                return round(v, 2)
        except (TypeError, ValueError):
            pass
    mv = robot.get("battery_mv")
    if mv is not None:
        try:
            v = float(mv) / 1000.0
            if v > 1.0:
                return round(v, 2)
        except (TypeError, ValueError):
            pass
    return None


@router.post("/api/robots/{robot_id}/explore/start")
async def start_robot_explorer(
    robot_id: str,
    body: StartExplorerRequest,
    request: Request,
) -> Dict[str, Any]:
    """Start Stage 3 Autonomous Frontier Exploration, Multi-Angle 3D Mapping, and Low-Battery RTH."""
    store = _robot_store(request)
    robot = _require_robot(store, robot_id)
    rt = _runtime(request)
    ai_store = _ai_store(request)
    ai_vision = _ai_vision(request)
    explorer = _explorer_manager(request)
    target_space_id = body.space_id or rt.active_space_id or None
    ros_ver = normalize_ros_mode(robot.get("active_ros_distro"))
    resolved_cfg = resolve_enhance_preset(quality_preset=body.quality_preset, overrides={"burst_frames": 1})

    # Mutual exclusion (P0-2): stop active Waypoint Patrol before starting Autonomous Explorer
    patrol_mgr = _patrol_manager(request)
    if patrol_mgr.get_status(robot_id).get("active"):
        await patrol_mgr.stop(
            robot_id=robot_id,
            ip=robot["ip_address"],
            rosbridge_port=int(robot.get("rosbridge_port") or 9090),
            ros_version=ros_ver,
        )

    announce_fn = None
    if body.announce_voice:
        ssh_pw = store.get_robot_ssh_password(robot_id)
        if ssh_pw:

            async def _announce(msg: str) -> None:
                await speak_text_on_robot(
                    ip=robot["ip_address"],
                    user=robot["ssh_user"],
                    password=ssh_pw,
                    text=msg,
                    engine="auto",
                    anti_clip=True,
                )

            announce_fn = _announce

    async def _get_cam_jpeg() -> Optional[bytes]:
        try:
            return await _fetch_live_frame_bytes(robot)
        except Exception:
            return None

    async def _capture_station(x: float, y: float, yaw_deg: float, pitch_deg: float) -> Dict[str, Any]:
        jpg = await _fetch_live_frame_bytes(robot)
        apriltag_seen = detect_apriltag_home_in_jpeg(jpg, body.apriltag_home_id)
        panels_added = 0
        objects_added = 0

        # 1. Reconstruct and save 3D scene panel in PG18 when a target space exists
        if target_space_id:
            lidar_xy = [(float(p.x), float(p.y)) for p in (rt.latest_points or [])]
            pose = {
                "x": round(float(x), 3),
                "y": round(float(y), 3),
                "z": 0.22,
                "yaw_deg": round(float(yaw_deg), 1),
                "pitch_deg": round(float(pitch_deg), 1),
                "roll_deg": 0.0,
            }
            reconstructed, enhanced_jpeg, normal_jpeg, glb_bytes = await asyncio.to_thread(
                reconstruct_enhanced_wall_panel,
                jpeg_frames=[jpg],
                lidar_sweeps_xy=[lidar_xy] if lidar_xy else None,
                pose=pose,
                resolution="medium",
                fallback_distance_m=1.8,
                depth_relief_scale=1.0,
                hfov_deg=rt.default_camera_fov_deg,
                vfov_deg=50.0,
                enhance_options=resolved_cfg,
            )
            slug = f"exp_{int(yaw_deg)}_{int(pitch_deg)}_{int(time.time())}"
            tex_rec = rt.repo.store_file(
                filename=f"scene-{slug}.jpg",
                content_type="image/jpeg",
                data=enhanced_jpeg,
                category="scene_texture",
                space_id=target_space_id,
                metadata={"robot_id": robot_id, "stage": "explorer_auto", "preset": body.quality_preset},
            )
            norm_rec = (
                rt.repo.store_file(
                    filename=f"scene-{slug}-normal.jpg",
                    content_type="image/jpeg",
                    data=normal_jpeg,
                    category="scene_normal",
                    space_id=target_space_id,
                    metadata={"robot_id": robot_id, "stage": "explorer_auto"},
                )
                if normal_jpeg
                else None
            )
            glb_rec = rt.repo.store_file(
                filename=f"scene-{slug}.glb",
                content_type="model/gltf-binary",
                data=glb_bytes,
                category="scene_glb",
                space_id=target_space_id,
                metadata={"robot_id": robot_id, "stage": "explorer_auto"},
            )
            ai_store.save_scene_panel(
                {
                    "space_id": target_space_id,
                    "robot_id": robot_id,
                    "label": f"Explore {yaw_deg:.0f}° / {pitch_deg:+.0f}°",
                    "stage": "explorer_auto",
                    "pose": reconstructed["pose"],
                    "lidar_calibrated": reconstructed["lidar_calibrated"],
                    "lidar_ray_count": reconstructed["lidar_ray_count"],
                    "depth_source": reconstructed["depth_source"],
                    "mean_distance_m": reconstructed["mean_distance_m"],
                    "min_distance_m": reconstructed["min_distance_m"],
                    "max_distance_m": reconstructed["max_distance_m"],
                    "vertex_count": reconstructed["vertex_count"],
                    "triangle_count": reconstructed["triangle_count"],
                    "texture_file_id": tex_rec["id"],
                    "normal_map_file_id": norm_rec["id"] if norm_rec else None,
                    "normal_map_url": f"/api/files/{norm_rec['id']}" if norm_rec else None,
                    "glb_file_id": glb_rec["id"],
                    "quality_metrics": reconstructed.get("quality_metrics"),
                    "mesh": reconstructed["mesh"],
                }
            )
            panels_added = 1

        # 2. Run local YOLO11n + YuNet/SFace and record Semantic Spatial Memory sightings
        arr = np.frombuffer(jpg, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is not None and frame.size > 0:
            snap_rec = rt.repo.store_file(
                filename=f"explore-sighting-{robot_id[:8]}-{int(time.time())}.jpg",
                content_type="image/jpeg",
                data=jpg,
                category="spatial_sighting",
                space_id=target_space_id,
                metadata={"robot_id": robot_id, "source": "autonomous_explorer"},
            )
            conf_t = float(ai_vision.get_state(robot_id).get("conf_threshold", 0.35))
            objs = await asyncio.to_thread(ai_vision.detect_objects_and_animals, frame, conf_t)
            faces = await asyncio.to_thread(ai_vision.detect_faces_and_embeddings, frame)
            for det in objs[:6]:
                ai_store.record_spatial_sighting(
                    robot_id,
                    {
                        "space_id": target_space_id,
                        "label": str(det["label"]),
                        "kind": str(det.get("kind") or ("animal" if det.get("is_animal") else "object")),
                        "x_m": round(float(x), 3),
                        "y_m": round(float(y), 3),
                        "confidence": float(det["confidence"]),
                        "snapshot_file_id": snap_rec["id"],
                        "notes": f"Autonomous Explorer ({yaw_deg:.0f}° / {pitch_deg:+.0f}°)",
                        "camera_source": "puppypi_fpv",
                        "tags": ["autonomous-explorer"],
                    },
                )
                objects_added += 1
            for face in faces[:4]:
                match = ai_store.match_face_embedding(face["embedding"], threshold=0.363)
                lbl = match["person"]["name"] if match else "Person"
                ai_store.record_spatial_sighting(
                    robot_id,
                    {
                        "space_id": target_space_id,
                        "label": lbl,
                        "kind": "face",
                        "x_m": round(float(x), 3),
                        "y_m": round(float(y), 3),
                        "confidence": float(face["confidence"]),
                        "snapshot_file_id": snap_rec["id"],
                        "notes": f"Autonomous Explorer face ({yaw_deg:.0f}° / {pitch_deg:+.0f}°)",
                        "camera_source": "puppypi_fpv",
                        "tags": ["autonomous-explorer", "face"],
                    },
                )
                objects_added += 1

        return {
            "panels": panels_added,
            "objects": objects_added,
            "apriltag_home_seen": apriltag_seen,
        }

    return await explorer.start(
        robot_id=robot_id,
        ip=robot["ip_address"],
        rosbridge_port=int(robot.get("rosbridge_port") or 9090),
        ros_version=ros_ver,
        space_id=target_space_id,
        max_iterations=body.max_iterations,
        target_coverage_pct=body.target_coverage_pct,
        capture_mode=body.capture_mode,
        quality_preset=body.quality_preset,
        rth_battery_v=body.rth_battery_v,
        max_speed_cms=body.max_speed_cms,
        obstacle_clearance_m=body.obstacle_clearance_m,
        apriltag_home_id=body.apriltag_home_id,
        require_lidar=body.require_lidar,
        capture_station_fn=_capture_station,
        get_lidar_points=lambda: (
            rt.latest_raw_points
            if (
                rt.source_mode == "robot_ros2"
                and rt.robot_scan_connected
                and float(rt._last_scan_mono or 0.0) > 0.0
                and (time.monotonic() - float(rt._last_scan_mono)) <= 3.5
            )
            else []
        ),
        get_dark_zones=lambda: list(rt.latest_dark_zones or []),
        get_coverage_pct=lambda: compute_room_coverage_pct(
            rt.latest_metrics,
            rt.latest_dark_zones,
            explorer.get_status(robot_id).get("panels_captured", 0),
        ),
        get_battery_v=lambda: _resolve_live_battery_v(rt, robot),
        get_imu_yaw_deg=lambda: (
            float(rt.robot_pose["yaw_deg"])
            if (rt.robot_pose or {}).get("live") and (rt.robot_pose or {}).get("yaw_deg") is not None
            else None
        ),
        get_camera_jpeg=_get_cam_jpeg,
        ai_vision_engine=ai_vision,
        announce_fn=announce_fn,
    )


@router.post("/api/robots/{robot_id}/explore/rth")
async def trigger_robot_explorer_rth(robot_id: str, request: Request) -> Dict[str, Any]:
    """Trigger immediate Return-to-Home Base (RTH) for an active autonomous explorer."""
    _require_robot(_robot_store(request), robot_id)
    return _explorer_manager(request).trigger_rth(robot_id)


@router.post("/api/robots/{robot_id}/explore/stop")
async def stop_robot_explorer(robot_id: str, request: Request) -> Dict[str, Any]:
    """Immediately stop Autonomous Explorer, zero velocity, and reset body pitch to ``0°``."""
    robot = _require_robot(_robot_store(request), robot_id)
    return await _explorer_manager(request).stop(
        robot_id=robot_id,
        ip=robot["ip_address"],
        rosbridge_port=int(robot.get("rosbridge_port") or 9090),
        ros_version=normalize_ros_mode(robot.get("active_ros_distro")),
    )


@router.get("/api/robots/{robot_id}/explore/status")
async def get_robot_explorer_status(robot_id: str, request: Request) -> Dict[str, Any]:
    """Return live Autonomous Explorer telemetry, enriching live battery/coverage/LiDAR when idle."""
    robot = _require_robot(_robot_store(request), robot_id)
    status = _explorer_manager(request).get_status(robot_id)
    rt = _runtime(request)
    if not status.get("active"):
        batt_v = _resolve_live_battery_v(rt, robot)
        status["battery_v"] = batt_v
        status["battery_pct"] = compute_battery_pct_2s(batt_v)
        status["coverage_pct"] = compute_room_coverage_pct(
            rt.latest_metrics,
            rt.latest_dark_zones,
            int(status.get("panels_captured") or 0),
        )
        status["dark_zones_remaining"] = len(rt.latest_dark_zones or [])
        status["lidar_live"] = bool(
            rt.source_mode == "robot_ros2"
            and rt.robot_scan_connected
            and float(rt._last_scan_mono or 0.0) > 0.0
            and (time.monotonic() - float(rt._last_scan_mono)) <= 3.5
        )
        if not status.get("space_id"):
            status["space_id"] = rt.active_space_id or None
    return status


# --- Add-On B: Semantic Spatial Memory Endpoints ---


class UpdateSpatialSightingRequest(BaseModel):
    """Payload to edit metadata or archive/retrieve a Spatial Memory sighting."""

    label: Optional[str] = Field(default=None, min_length=1, max_length=120)
    kind: Optional[str] = Field(default=None, min_length=1, max_length=40)
    notes: Optional[str] = Field(default=None, max_length=1000)
    tags: Optional[List[str]] = None
    archived: Optional[bool] = None
    space_id: Optional[str] = None


class BulkSpatialSightingsRequest(BaseModel):
    """Payload for multi-select bulk archive, retrieve, or delete on Spatial Memory sightings."""

    action: Literal["archive", "retrieve", "delete"]
    ids: List[str] = Field(default_factory=list)


@router.get("/api/spatial-memory")
async def list_spatial_memory(
    request: Request,
    query: Optional[str] = None,
    status: str = "active",
    kind: Optional[str] = None,
    space_id: Optional[str] = None,
    limit: int = 200,
) -> Dict[str, Any]:
    """Search or list Semantic Spatial Memory sightings with lifecycle status, kind, and space filters."""
    ai_store = _ai_store(request)
    sightings = ai_store.list_spatial_sightings(
        query=query,
        limit=max(1, min(500, int(limit))),
        status=status,
        kind=kind,
        space_id=space_id,
    )
    counts = ai_store.count_spatial_sightings(space_id=space_id, kind=kind, query=query)
    return {"sightings": sightings, "counts": counts}


@router.patch("/api/spatial-memory/{sighting_id}")
async def update_spatial_memory_item(
    sighting_id: str,
    body: UpdateSpatialSightingRequest,
    request: Request,
) -> Dict[str, Any]:
    """Update label, kind, notes, tags, space, or archived status on a Spatial Memory sighting."""
    updates = body.model_dump(exclude_unset=True)
    updated = _ai_store(request).update_spatial_sighting(sighting_id, updates)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Sighting {sighting_id} not found.")
    return {"ok": True, "sighting": updated}


@router.post("/api/spatial-memory/bulk")
async def bulk_spatial_memory_action(
    body: BulkSpatialSightingsRequest,
    request: Request,
) -> Dict[str, Any]:
    """Archive, retrieve, or delete multiple Spatial Memory sightings in one call."""
    affected = _ai_store(request).bulk_update_spatial_sightings(body.action, body.ids)
    return {"ok": True, "affected": affected}


@router.post("/api/spatial-memory/capture/{robot_id}")
async def capture_spatial_memory_now(robot_id: str, request: Request) -> Dict[str, Any]:
    """Snap a live PuppyPi frame, detect objects/animals/known faces, and log sightings into Spatial Memory."""
    store = _robot_store(request)
    robot = _require_robot(store, robot_id)
    rt = _runtime(request)
    engine = _ai_vision(request)
    ai_store = _ai_store(request)

    try:
        jpg = await _fetch_live_frame_bytes(robot)
    except ConnectionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    arr = np.frombuffer(jpg, dtype=np.uint8)
    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if frame is None or frame.size == 0:
        raise HTTPException(status_code=502, detail="Robot camera returned an invalid JPEG frame.")

    stored = rt.repo.store_file(
        filename=f"memory-{robot_id[:8]}-{int(time.time())}.jpg",
        content_type="image/jpeg",
        data=jpg,
        category="spatial_sighting",
        space_id=rt.active_space_id or None,
        metadata={"robot_id": robot_id, "source": "manual_scan"},
    )

    conf_t = float(engine.get_state(robot_id).get("conf_threshold", 0.35))
    objs = engine.detect_objects_and_animals(frame, conf_thresh=conf_t)
    faces = engine.detect_faces_and_embeddings(frame)

    recorded: List[Dict[str, Any]] = []
    for det in objs:
        pose = raycast_camera_to_lidar(
            bbox_norm=det.get("bbox_norm"),
            lidar_points=rt.latest_points,
            camera_fov_deg=rt.default_camera_fov_deg,
            camera_yaw_deg=float(rt.robot_pose.get("yaw_deg", 0.0)),
        )
        recorded.append(
            ai_store.record_spatial_sighting(
                robot_id,
                {
                    "space_id": rt.active_space_id or None,
                    "label": str(det["label"]),
                    "kind": str(det["kind"]),
                    "x_m": float((pose or {}).get("x", rt.robot_pose.get("x", 0.0))),
                    "y_m": float((pose or {}).get("y", rt.robot_pose.get("y", 0.0))),
                    "confidence": float(det["confidence"]),
                    "snapshot_file_id": stored["id"],
                    "notes": "Captured via Scan & Remember Room",
                },
            )
        )

    for face in faces:
        match = ai_store.match_face_embedding(face["embedding"], threshold=0.363)
        lbl = match["person"]["name"] if match else "Person"
        pose = raycast_camera_to_lidar(
            bbox_norm=face.get("bbox_norm"),
            lidar_points=rt.latest_points,
            camera_fov_deg=rt.default_camera_fov_deg,
            camera_yaw_deg=float(rt.robot_pose.get("yaw_deg", 0.0)),
        )
        recorded.append(
            ai_store.record_spatial_sighting(
                robot_id,
                {
                    "space_id": rt.active_space_id or None,
                    "label": lbl,
                    "kind": "face",
                    "x_m": float((pose or {}).get("x", rt.robot_pose.get("x", 0.0))),
                    "y_m": float((pose or {}).get("y", rt.robot_pose.get("y", 0.0))),
                    "confidence": float(face["confidence"]),
                    "snapshot_file_id": stored["id"],
                    "notes": "Recognized face via Scan & Remember Room",
                },
            )
        )

    # Always record at least a room scene snapshot entry if YOLO+faces found nothing
    if not recorded:
        recorded.append(
            ai_store.record_spatial_sighting(
                robot_id,
                {
                    "space_id": rt.active_space_id or None,
                    "label": "Room Snapshot",
                    "kind": "scene",
                    "x_m": float(rt.robot_pose.get("x", 0.0)),
                    "y_m": float(rt.robot_pose.get("y", 0.0)),
                    "confidence": 1.0,
                    "snapshot_file_id": stored["id"],
                    "notes": "Room view captured cleanly",
                },
            )
        )

    return {"ok": True, "recorded_count": len(recorded), "sightings": recorded}


@router.delete("/api/spatial-memory/{sighting_id}")
async def delete_spatial_memory_item(sighting_id: str, request: Request) -> Dict[str, Any]:
    """Delete one spatial memory sighting by ID."""
    if not _ai_store(request).delete_spatial_sighting(sighting_id):
        raise HTTPException(status_code=404, detail=f"Sighting {sighting_id} not found.")
    return {"deleted": True}


# --- Add-On C: Autonomous Sentry Guard Mode Endpoints ---


@router.get("/api/robots/{robot_id}/sentry/status")
async def get_robot_sentry_status(robot_id: str, request: Request) -> Dict[str, Any]:
    """Return Sentry Guard Mode armed status, rules, and event count for ``robot_id``."""
    _require_robot(_robot_store(request), robot_id)
    events = _ai_store(request).list_sentry_events(robot_id, limit=200)
    return _sentry_manager(request).get_status(robot_id, event_count=len(events))


@router.put("/api/robots/{robot_id}/sentry/config")
async def update_robot_sentry_config(
    robot_id: str,
    body: SentryConfigUpdateRequest,
    request: Request,
) -> Dict[str, Any]:
    """Update Sentry Guard Mode trigger toggles, cooldown, and custom spoken challenge."""
    _require_robot(_robot_store(request), robot_id)
    mgr = _sentry_manager(request)
    mgr.update_config(robot_id, body.model_dump(exclude_none=True))
    events = _ai_store(request).list_sentry_events(robot_id, limit=200)
    return mgr.get_status(robot_id, event_count=len(events))


@router.post("/api/robots/{robot_id}/sentry/arm")
async def arm_robot_sentry(robot_id: str, request: Request) -> Dict[str, Any]:
    """Arm Autonomous Sentry Guard Mode to monitor LiDAR motion, unknown faces, and animals."""
    store = _robot_store(request)
    robot = _require_robot(store, robot_id)
    ssh_pw = store.get_robot_ssh_password(robot_id)
    rt = _runtime(request)
    ai_store = _ai_store(request)
    engine = _ai_vision(request)
    mgr = _sentry_manager(request)
    ros_mode = normalize_ros_mode(robot.get("active_ros_distro"))

    async def _on_trigger(trig: Dict[str, Any]) -> Dict[str, Any]:
        return await mgr.handle_trigger(
            robot_id=robot_id,
            trigger=trig,
            ai_store=ai_store,
            repo=rt.repo,
            robot=robot,
            ssh_pw=ssh_pw,
            ros_version=ros_mode,
            space_id=rt.active_space_id or None,
        )

    return await mgr.arm(
        robot_id=robot_id,
        get_moving_objects=lambda: rt.latest_moving_objects,
        get_vision_detections=lambda: engine.get_state(robot_id).get("detections") or [],
        on_trigger=_on_trigger,
        event_count_fn=lambda: len(ai_store.list_sentry_events(robot_id, limit=200)),
    )


@router.post("/api/robots/{robot_id}/sentry/disarm")
async def disarm_robot_sentry(robot_id: str, request: Request) -> Dict[str, Any]:
    """Disarm Autonomous Sentry Guard Mode for ``robot_id``."""
    _require_robot(_robot_store(request), robot_id)
    events = _ai_store(request).list_sentry_events(robot_id, limit=200)
    return await _sentry_manager(request).disarm(robot_id, event_count=len(events))


@router.get("/api/robots/{robot_id}/sentry/events")
async def list_robot_sentry_events(
    robot_id: str,
    request: Request,
    limit: int = 50,
) -> Dict[str, List[Dict[str, Any]]]:
    """List recorded Sentry Guard Mode security alerts with evidence snapshots."""
    _require_robot(_robot_store(request), robot_id)
    return {"events": _ai_store(request).list_sentry_events(robot_id, limit=max(1, min(200, int(limit))))}


@router.delete("/api/robots/{robot_id}/sentry/events")
async def clear_robot_sentry_events(robot_id: str, request: Request) -> Dict[str, int]:
    """Clear all recorded Sentry Guard Mode alert events for ``robot_id``."""
    _require_robot(_robot_store(request), robot_id)
    return {"cleared": _ai_store(request).clear_sentry_events(robot_id)}
