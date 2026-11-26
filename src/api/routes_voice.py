"""FastAPI endpoints for Conversational Voice Assistant ("Hey OX"), Personalities, WonderEcho Pro Mixer/TTS/STT & Udev Rules."""

from __future__ import annotations

import sys
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from src.api.state import TwinScanRuntimeState
from src.db.robot_ai_store import RobotAiStoreProtocol
from src.db.robot_store import RobotStoreProtocol
from src.robot.conversation_engine import (
    BUILTIN_PERSONALITIES,
    RobotConversationManager,
    run_voice_diagnostics,
    transcribe_wav_offline,
)
from src.robot.patrol_engine import RobotPatrolManager
from src.robot.ros_profiles import get_ros_profile, normalize_ros_mode
from src.robot.rosbridge_proxy import (
    call_go_home,
    fetch_robot_snapshot,
    publish_pose,
    run_action,
    set_rgb,
    trigger_estop,
)
from src.robot.ssh_manager import SSHAuthError, SSHCommandError, install_puppypi_udev_rules
from src.robot.voice_manager import (
    WonderEchoWakeManager,
    get_voice_status,
    list_available_voices,
    listen_and_process_voice_command,
    play_speaker_chime,
    record_mic_on_robot,
    set_audio_mixer,
    speak_text_on_robot,
)
from src.vision.robot_ai_vision import RobotAiVisionEngine, deep_identify_frame

router = APIRouter(tags=["voice"])


# --- Request Models ---


class VoiceMixerRequest(BaseModel):
    """ALSA speaker/mic volume and mute update payload."""

    speaker_volume_pct: Optional[int] = Field(default=None, ge=0, le=100)
    mic_gain_pct: Optional[int] = Field(default=None, ge=0, le=100)
    speaker_mute: Optional[bool] = None
    mic_mute: Optional[bool] = None


class VoiceSpeakRequest(BaseModel):
    """Text-to-Speech request payload for WonderEcho Pro speaker (Offline Piper default)."""

    text: str
    engine: str = "piper_tts"
    voice: Optional[str] = None
    speed: int = Field(default=155, ge=80, le=320)
    anti_clip: bool = True


class VoiceChimeRequest(BaseModel):
    """Synthesized chime test request payload."""

    chime: str = "dong"


class VoiceListenRequest(BaseModel):
    """Push-to-Talk listen (offline Faster-Whisper STT) or simulated transcript execution payload."""

    duration_sec: int = Field(default=4, ge=1, le=10)
    execute_commands: bool = True
    speak_reply: bool = True
    simulated_transcript: Optional[str] = None


class WakeListenerToggleRequest(BaseModel):
    """Enable or disable WonderEcho Pro background serial wake-word listener."""

    enabled: bool = True


class VoiceConfigUpdateRequest(BaseModel):
    """Partial update for per-robot conversational voice assistant configuration."""

    assistant_name: Optional[str] = None
    wake_word: Optional[str] = None
    wake_aliases: Optional[List[str]] = None
    wake_mode: Optional[str] = None
    default_engine: Optional[str] = None
    default_voice: Optional[str] = None
    default_speed: Optional[int] = Field(default=None, ge=80, le=320)
    anti_clip: Optional[bool] = None
    followup_window_sec: Optional[int] = Field(default=None, ge=0, le=60)
    personality_id: Optional[str] = None
    llm_model: Optional[str] = None
    attach_camera_on_visual: Optional[bool] = None
    allow_body_actions: Optional[bool] = None


class CreatePersonalityRequest(BaseModel):
    """Create a custom conversational personality."""

    name: str
    badge: str = "CUSTOM"
    description: str = ""
    system_prompt: str
    default_voice: str = "en_US-lessac-medium"
    allow_body_actions: bool = True


class UpdatePersonalityRequest(BaseModel):
    """Update editable fields on an existing personality."""

    name: Optional[str] = None
    badge: Optional[str] = None
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    default_voice: Optional[str] = None
    allow_body_actions: Optional[bool] = None


class VoiceChatRequest(BaseModel):
    """Conversational chat turn payload (type-to-chat or hands-free STT)."""

    message: str
    speak_reply: bool = True
    attach_camera: str = "auto"
    execute_actions: bool = True


class VoiceDiagnosticsRequest(BaseModel):
    """6-point WonderEcho USB, ALSA, Piper+Whisper loopback & live mic diagnostics payload."""

    record_live_sec: int = Field(default=4, ge=0, le=8)
    test_speaker: bool = False


# --- Helpers ---


def _robot_store(request: Request) -> RobotStoreProtocol:
    return request.app.state.robot_store


def _ai_store(request: Request) -> RobotAiStoreProtocol:
    return request.app.state.robot_ai_store


def _wake_manager(request: Request) -> WonderEchoWakeManager:
    return request.app.state.wake_manager


def _conversation_manager(request: Request) -> RobotConversationManager:
    return request.app.state.conversation_manager


def _patrol_manager(request: Request) -> RobotPatrolManager:
    return request.app.state.patrol_manager


def _ai_vision(request: Request) -> RobotAiVisionEngine:
    return request.app.state.ai_vision_engine


def _runtime(request: Request) -> TwinScanRuntimeState:
    return request.app.state.runtime


def _require_robot(store: RobotStoreProtocol, robot_id: str) -> Dict[str, Any]:
    robot = store.get_robot(robot_id)
    if not robot:
        raise HTTPException(status_code=404, detail=f"Robot {robot_id} not found.")
    return robot


def _front_lidar_clearance_m(rt: TwinScanRuntimeState) -> float:
    min_d = 9.9
    for pt in rt.latest_points or []:
        ang = float(getattr(pt, "angle_deg", 0.0))
        norm = ((ang + 180.0) % 360.0) - 180.0
        if -25.0 <= norm <= 25.0:
            dist = float(getattr(pt, "distance_m", 9.9))
            if 0.05 <= dist <= 12.0:
                min_d = min(min_d, dist)
    return round(min_d, 2)


def _resolve_config_and_personality(
    ai_store: RobotAiStoreProtocol, robot_id: str
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    cfg = ai_store.get_voice_config(robot_id)
    pid = str(cfg.get("personality_id") or "dog")
    pers = ai_store.get_personality(pid) or ai_store.get_personality("dog") or dict(BUILTIN_PERSONALITIES[0])
    return cfg, pers


def _build_voice_action_executor(
    request: Request,
    robot: Dict[str, Any],
    ssh_pw: str,
):
    """Create an async intent executor routing voice intents to ROSBridge, Patrol, and AI Vision."""
    robot_id = robot["id"]
    ip = robot["ip_address"]
    port = int(robot.get("rosbridge_port") or 9090)
    video_port = int(robot.get("video_port") or 8080)
    ros_mode = normalize_ros_mode(robot.get("active_ros_distro"))
    patrol_mgr = _patrol_manager(request)
    ai_vision = _ai_vision(request)
    ai_store = _ai_store(request)
    rt = _runtime(request)

    async def _execute(parsed: Dict[str, Any]) -> Tuple[str, str]:
        intent = str(parsed.get("intent") or "none")
        if intent in ("stop", "estop"):
            await patrol_mgr.stop(robot_id)
            ai_vision.stop_autonomous_motion(robot_id)
            await trigger_estop(ip, port, ros_version=ros_mode, robot_id=robot_id)
            return "estop", "Emergency stop engaged."
        if intent in ("go_home", "stand"):
            await call_go_home(ip=ip, port=port, ros_version=ros_mode, robot_id=robot_id)
            return "go_home", "Standing ready."
        if intent == "sit":
            await publish_pose(ip=ip, port=port, preset="sit", ros_version=ros_mode, robot_id=robot_id)
            return "pose:sit", "Sitting down."
        if intent == "lie_down":
            await publish_pose(ip=ip, port=port, preset="lie_down", ros_version=ros_mode, robot_id=robot_id)
            return "pose:lie_down", "Lying down."
        if intent == "bow":
            await publish_pose(ip=ip, port=port, preset="bow", ros_version=ros_mode, robot_id=robot_id)
            return "pose:bow", "Bowing for you."
        if intent in ("wave", "shake_hands"):
            act_name = "shake_hands.d6ac" if intent == "shake_hands" else "wave.d6ac"
            await run_action(ip=ip, port=port, name=act_name, wait=False, ros_version=ros_mode, robot_id=robot_id)
            return f"action:{act_name}", "Hello there!"
        if intent in ("nod", "push_up"):
            act_name = "nod.d6ac" if intent == "nod" else "push-up.d6ac"
            await run_action(ip=ip, port=port, name=act_name, wait=False, ros_version=ros_mode, robot_id=robot_id)
            return f"action:{act_name}", str(parsed.get("reply_hint") or "Done!")
        if intent == "stop_patrol":
            await patrol_mgr.stop(robot_id, ip=ip, rosbridge_port=port, ros_version=ros_mode)
            return "patrol:stop", "Patrol stopped."
        if intent == "start_patrol":
            routes = ai_store.list_patrol_routes(robot_id)
            if not routes:
                return "patrol:no_routes", "No saved patrol routes yet. Please save a route in Patrol Planner."
            route = routes[0]
            await patrol_mgr.start(
                robot_id=robot_id,
                ip=ip,
                rosbridge_port=port,
                ros_version=ros_mode,
                waypoints=route["waypoints"],
                route_name=route["name"],
                loop_enabled=bool(route.get("loop_enabled", True)),
                max_speed_cms=float(route.get("max_speed_cms", 12.0)),
                obstacle_clearance_m=float(route.get("obstacle_clearance_m", 0.45)),
                require_lidar=True,
                camera_avoidance=True,
                video_port=video_port,
                ai_vision_engine=ai_vision,
                get_visual_obstacle=lambda: ai_vision.get_visual_obstacle(robot_id),
            )
            return f"patrol:start:{route['name']}", f"Starting patrol route {route['name']}."
        if intent in ("follow_target", "follow_me"):
            ai_vision.set_mode(robot_id, mode="track_follow", follow_enabled=True)
            return "ai_vision:track_follow", str(parsed.get("reply_hint") or "Track and follow mode enabled.")
        if intent in ("line_follow", "follow_line"):
            ai_vision.set_mode(robot_id, mode="line_follow", line_follow_enabled=True)
            return "ai_vision:line_follow", "Line follow mode enabled."
        if intent == "who_is_there":
            ai_vision.set_mode(robot_id, mode="face_recognition", auto_greet_enabled=True)
            return "ai_vision:face_recognition", "Face recognition enabled."
        if intent in ("describe_scene", "deep_identify"):
            topic = get_ros_profile(ros_mode)["camera_topic"]
            try:
                jpg = await fetch_robot_snapshot(ip=ip, port=video_port, topic=topic, timeout=4.0, retries=2)
                ident = await deep_identify_frame(
                    image_bytes=jpg,
                    api_key=rt.effective_config.get("openrouter_api_key", ""),
                    base_url=rt.effective_config.get("openrouter_base_url", rt.settings.openrouter_base_url),
                    model=rt.effective_config.get(
                        "openrouter_default_vision_model", rt.settings.openrouter_default_vision_model
                    ),
                )
                return "ai_vision:deep_identify", str(ident.get("description") or "I captured the view.")
            except Exception as exc:
                sys.stderr.write(f"[voice.deep_identify] Failed on {ip}: {exc}\n")
                return "ai_vision:deep_identify_error", "I could not reach the camera right now."
        if intent == "status_report":
            batt = robot.get("battery_mv")
            batt_txt = f"{batt / 1000.0:.2f} volts" if isinstance(batt, (int, float)) and batt > 0 else "unknown voltage"
            return "status_report", f"PuppyPi is online on {ros_mode.upper()} with battery at {batt_txt}."
        return "none", str(parsed.get("reply_hint") or "")

    return _execute


def _build_conversation_callbacks(request: Request, robot: Dict[str, Any], ssh_pw: str):
    """Build camera, body-action/RGB, and TTS callbacks bound to a specific robot."""
    robot_id = robot["id"]
    ip = robot["ip_address"]
    port = int(robot.get("rosbridge_port") or 9090)
    video_port = int(robot.get("video_port") or 8080)
    ros_mode = normalize_ros_mode(robot.get("active_ros_distro"))
    patrol_mgr = _patrol_manager(request)
    ai_vision = _ai_vision(request)

    async def _fetch_camera() -> Optional[bytes]:
        primary = get_ros_profile(ros_mode)["camera_topic"]
        alt = "/usb_cam/image_raw" if primary == "/image_raw" else "/image_raw"
        try:
            return await fetch_robot_snapshot(ip=ip, port=video_port, topic=primary, timeout=4.0, retries=1)
        except Exception:
            return await fetch_robot_snapshot(ip=ip, port=video_port, topic=alt, timeout=4.0, retries=1)

    async def _execute_action(action_name: Optional[str], rgb_val: Optional[List[int]]) -> Optional[str]:
        taken: Optional[str] = None
        if rgb_val and len(rgb_val) == 3:
            try:
                await set_rgb(
                    ip=ip,
                    port=port,
                    data=[
                        {"id": 1, "r": int(rgb_val[0]), "g": int(rgb_val[1]), "b": int(rgb_val[2])},
                        {"id": 2, "r": int(rgb_val[0]), "g": int(rgb_val[1]), "b": int(rgb_val[2])},
                    ],
                    ros_version=ros_mode,
                )
            except Exception as exc:
                sys.stderr.write(f"[conversation.rgb] Failed setting RGB on {ip}: {exc}\n")

        if not action_name or action_name == "none":
            return taken
        if action_name == "estop":
            await patrol_mgr.stop(robot_id)
            ai_vision.stop_autonomous_motion(robot_id)
            await trigger_estop(ip, port, ros_version=ros_mode, robot_id=robot_id)
            return "estop"
        if action_name in ("stand", "go_home"):
            await call_go_home(ip=ip, port=port, ros_version=ros_mode, robot_id=robot_id)
            return "go_home"
        if action_name in ("sit", "lie_down", "bow"):
            await publish_pose(ip=ip, port=port, preset=action_name, ros_version=ros_mode, robot_id=robot_id)
            return f"pose:{action_name}"
        action_map = {
            "wave": "wave.d6ac",
            "shake_hands": "shake_hands.d6ac",
            "nod": "nod.d6ac",
            "push_up": "push-up.d6ac",
        }
        if action_name in action_map:
            fname = action_map[action_name]
            await run_action(ip=ip, port=port, name=fname, wait=False, ros_version=ros_mode, robot_id=robot_id)
            return f"action:{fname}"
        return taken

    async def _speak(reply_text: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
        return await speak_text_on_robot(
            ip=ip,
            user=robot["ssh_user"],
            password=ssh_pw,
            text=reply_text,
            engine=str(cfg.get("default_engine") or "piper_tts"),
            voice=cfg.get("default_voice"),
            speed=int(cfg.get("default_speed") or 155),
            anti_clip=bool(cfg.get("anti_clip", True)),
        )

    return _fetch_camera, _execute_action, _speak


# --- Conversational Assistant Config, Personalities & Multi-Turn Chat Endpoints ---


@router.get("/api/robots/{robot_id}/voice/config")
async def get_robot_voice_config(robot_id: str, request: Request) -> Dict[str, Any]:
    """Return per-robot conversational assistant settings (wake word, Piper default, personality, LLM model)."""
    _require_robot(_robot_store(request), robot_id)
    return _ai_store(request).get_voice_config(robot_id)


@router.put("/api/robots/{robot_id}/voice/config")
async def update_robot_voice_config(
    robot_id: str,
    body: VoiceConfigUpdateRequest,
    request: Request,
) -> Dict[str, Any]:
    """Update per-robot conversational assistant settings (wake word, aliases, Piper/Edge engine, personality, LLM)."""
    _require_robot(_robot_store(request), robot_id)
    updates = body.model_dump(exclude_none=True)
    if "wake_mode" in updates and updates["wake_mode"] not in ("custom_software", "hardware_wonderecho", "both"):
        raise HTTPException(status_code=400, detail="wake_mode must be custom_software, hardware_wonderecho, or both.")
    return _ai_store(request).upsert_voice_config(robot_id, updates)


@router.get("/api/voice/personalities")
async def list_voice_personalities(request: Request) -> Dict[str, List[Dict[str, Any]]]:
    """List all 5 built-in personalities (Dog, Cat, Marvin, Dad-Joke Nerd, Lab Ops) plus saved custom ones."""
    return {"personalities": _ai_store(request).list_personalities()}


@router.post("/api/voice/personalities")
async def create_voice_personality(
    body: CreatePersonalityRequest,
    request: Request,
) -> Dict[str, Any]:
    """Create a custom conversational personality."""
    try:
        pers = _ai_store(request).create_personality(body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"personality": pers}


@router.put("/api/voice/personalities/{personality_id}")
async def update_voice_personality(
    personality_id: str,
    body: UpdatePersonalityRequest,
    request: Request,
) -> Dict[str, Any]:
    """Update an existing conversational personality."""
    updated = _ai_store(request).update_personality(personality_id, body.model_dump(exclude_none=True))
    if not updated:
        raise HTTPException(status_code=404, detail=f"Personality {personality_id} not found.")
    return {"personality": updated}


@router.delete("/api/voice/personalities/{personality_id}")
async def delete_voice_personality(personality_id: str, request: Request) -> Dict[str, Any]:
    """Delete a custom conversational personality (refuses deleting built-in personalities)."""
    try:
        removed = _ai_store(request).delete_personality(personality_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(status_code=404, detail=f"Personality {personality_id} not found.")
    return {"deleted": True}


_VOICE_EXCLUDED_TOOLS = frozenset({"chat_as_ox", "speak_aloud"})


def _build_voice_tool_bridge(request: Request, robot_id: str):
    """Build OpenRouter tool schemas and an async executor for voice turns (excluding recursive tools).

    Excludes ``chat_as_ox`` (prevents recursion) and ``speak_aloud`` (prevents double-speaking
    since ``process_chat_turn`` speaks the final assistant reply via Piper TTS).

    Args:
        request: Active FastAPI request carrying ``request.app``.
        robot_id: Target robot identifier.

    Returns:
        Tuple ``(filtered_tool_schemas, async_tool_executor)``.
    """
    try:
        from src.agent.robot_tools import execute_robot_tool, get_openrouter_tool_schemas
    except Exception as exc:
        sys.stderr.write(f"[voice.tools] Robot tool registry unavailable: {exc}\n")
        return [], None

    raw_schemas = get_openrouter_tool_schemas()
    voice_tools = [
        schema
        for schema in raw_schemas
        if str((schema.get("function") or {}).get("name") or "") not in _VOICE_EXCLUDED_TOOLS
    ]

    async def _exec_tool(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if tool_name in _VOICE_EXCLUDED_TOOLS:
            return {
                "ok": False,
                "tool": tool_name,
                "robot_id": robot_id,
                "summary": f"Tool {tool_name} is disabled inside voice conversation turns to prevent recursion.",
                "data": {},
            }
        return await execute_robot_tool(request.app, tool_name, arguments or {}, robot_id=robot_id)

    return voice_tools, _exec_tool


@router.post("/api/robots/{robot_id}/voice/chat")
async def robot_voice_chat(
    robot_id: str,
    body: VoiceChatRequest,
    request: Request,
) -> Dict[str, Any]:
    """Run one embodied multi-turn conversational turn with personality, optional camera vision, tools, actions, and TTS."""
    store = _robot_store(request)
    robot = _require_robot(store, robot_id)
    ssh_pw = store.get_robot_ssh_password(robot_id)
    ai_store = _ai_store(request)
    rt = _runtime(request)
    conv_mgr = _conversation_manager(request)

    cfg, pers = _resolve_config_and_personality(ai_store, robot_id)
    fetch_cam, exec_act, speak_fn = _build_conversation_callbacks(request, robot, ssh_pw)
    voice_tools, tool_exec = _build_voice_tool_bridge(request, robot_id)
    batt_mv = robot.get("battery_mv")
    live_ctx = {
        "ros_mode": str(robot.get("active_ros_distro") or "ROS 2 Humble"),
        "battery_v": round(batt_mv / 1000.0, 2) if isinstance(batt_mv, (int, float)) and batt_mv > 0 else None,
        "front_lidar_m": _front_lidar_clearance_m(rt),
        "spatial_sightings": ai_store.list_spatial_sightings(limit=20),
    }

    try:
        return await conv_mgr.process_chat_turn(
            robot_id=robot_id,
            user_text=body.message,
            config=cfg,
            personality=pers,
            ai_store=ai_store,
            live_context=live_ctx,
            openrouter_api_key=rt.effective_config.get("openrouter_api_key", ""),
            openrouter_base_url=rt.effective_config.get("openrouter_base_url", rt.settings.openrouter_base_url),
            speak_reply=body.speak_reply,
            attach_camera=body.attach_camera,
            execute_actions=body.execute_actions,
            fetch_camera_fn=fetch_cam,
            execute_action_fn=exec_act,
            speak_fn=speak_fn,
            tools=voice_tools if body.execute_actions else None,
            tool_executor=tool_exec if body.execute_actions else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/robots/{robot_id}/voice/conversation/start")
async def start_robot_conversation(robot_id: str, request: Request) -> Dict[str, Any]:
    """Start hands-free continuous wake-word ("Hey OX") & follow-up conversation mode for ``robot_id``."""
    store = _robot_store(request)
    robot = _require_robot(store, robot_id)
    ssh_pw = store.get_robot_ssh_password(robot_id)
    ai_store = _ai_store(request)
    rt = _runtime(request)
    conv_mgr = _conversation_manager(request)
    fetch_cam, exec_act, speak_fn = _build_conversation_callbacks(request, robot, ssh_pw)
    voice_tools, tool_exec = _build_voice_tool_bridge(request, robot_id)

    async def _run_turn(utterance: str) -> Dict[str, Any]:
        cfg, pers = _resolve_config_and_personality(ai_store, robot_id)
        latest_robot = store.get_robot(robot_id) or robot
        batt_mv = latest_robot.get("battery_mv")
        live_ctx = {
            "ros_mode": str(latest_robot.get("active_ros_distro") or "ROS 2 Humble"),
            "battery_v": round(batt_mv / 1000.0, 2) if isinstance(batt_mv, (int, float)) and batt_mv > 0 else None,
            "front_lidar_m": _front_lidar_clearance_m(rt),
            "spatial_sightings": ai_store.list_spatial_sightings(limit=20),
        }
        return await conv_mgr.process_chat_turn(
            robot_id=robot_id,
            user_text=utterance,
            config=cfg,
            personality=pers,
            ai_store=ai_store,
            live_context=live_ctx,
            openrouter_api_key=rt.effective_config.get("openrouter_api_key", ""),
            openrouter_base_url=rt.effective_config.get("openrouter_base_url", rt.settings.openrouter_base_url),
            speak_reply=True,
            attach_camera="auto",
            execute_actions=True,
            fetch_camera_fn=fetch_cam,
            execute_action_fn=exec_act,
            speak_fn=speak_fn,
            tools=voice_tools,
            tool_executor=tool_exec,
        )

    return await conv_mgr.start(
        robot_id=robot_id,
        ip=robot["ip_address"],
        user=robot["ssh_user"],
        password=ssh_pw,
        get_config_and_personality=lambda: _resolve_config_and_personality(ai_store, robot_id),
        run_turn=_run_turn,
    )


@router.post("/api/robots/{robot_id}/voice/conversation/stop")
async def stop_robot_conversation(robot_id: str, request: Request) -> Dict[str, Any]:
    """Stop hands-free continuous conversation mode for ``robot_id``."""
    _require_robot(_robot_store(request), robot_id)
    return await _conversation_manager(request).stop(robot_id)


@router.get("/api/robots/{robot_id}/voice/conversation/state")
async def get_robot_conversation_state(robot_id: str, request: Request) -> Dict[str, Any]:
    """Return live hands-free conversation state (listening_wake / followup_window / thinking / speaking)."""
    _require_robot(_robot_store(request), robot_id)
    cfg, pers = _resolve_config_and_personality(_ai_store(request), robot_id)
    return _conversation_manager(request).get_state(robot_id, config=cfg, personality=pers)


@router.get("/api/robots/{robot_id}/voice/conversation/history")
async def get_robot_conversation_history(
    robot_id: str,
    request: Request,
    limit: int = Query(default=30, ge=1, le=200),
) -> Dict[str, List[Dict[str, Any]]]:
    """Return multi-turn conversation history for ``robot_id`` ordered oldest-first."""
    _require_robot(_robot_store(request), robot_id)
    return {"turns": _ai_store(request).list_conversation_turns(robot_id, limit=limit)}


@router.delete("/api/robots/{robot_id}/voice/conversation/history")
async def clear_robot_conversation_history(robot_id: str, request: Request) -> Dict[str, int]:
    """Clear stored multi-turn conversation memory for ``robot_id``."""
    _require_robot(_robot_store(request), robot_id)
    cleared = _ai_store(request).clear_conversation_turns(robot_id)
    return {"cleared": cleared}


# --- Voice Hardware, Mixer, TTS, Push-to-Talk & Udev Endpoints ---


@router.get("/api/robots/{robot_id}/voice/status")
async def robot_voice_status(robot_id: str, request: Request) -> Dict[str, Any]:
    """Return live WonderEcho Pro ALSA speaker/mic status, serial symlink state, and wake listener state."""
    store = _robot_store(request)
    robot = _require_robot(store, robot_id)
    ssh_pw = store.get_robot_ssh_password(robot_id)
    wake_mgr = _wake_manager(request)
    live_cfg = (robot.get("capabilities") or {}).get("live_config") or {}
    asr_lang = str(live_cfg.get("asr_language") or "English")

    return await get_voice_status(
        ip=robot["ip_address"],
        user=robot["ssh_user"],
        password=ssh_pw,
        robot_id=robot_id,
        asr_language=asr_lang,
        wake_manager=wake_mgr,
    )


@router.put("/api/robots/{robot_id}/voice/mixer")
async def robot_voice_mixer(
    robot_id: str,
    body: VoiceMixerRequest,
    request: Request,
) -> Dict[str, Any]:
    """Adjust WonderEcho Pro ALSA speaker volume, microphone gain, and mute toggles."""
    store = _robot_store(request)
    robot = _require_robot(store, robot_id)
    ssh_pw = store.get_robot_ssh_password(robot_id)
    wake_mgr = _wake_manager(request)
    live_cfg = (robot.get("capabilities") or {}).get("live_config") or {}
    asr_lang = str(live_cfg.get("asr_language") or "English")

    try:
        mixer = await set_audio_mixer(
            ip=robot["ip_address"],
            user=robot["ssh_user"],
            password=ssh_pw,
            speaker_volume_pct=body.speaker_volume_pct,
            mic_gain_pct=body.mic_gain_pct,
            speaker_mute=body.speaker_mute,
            mic_mute=body.mic_mute,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SSHAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except SSHCommandError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    wake_info = wake_mgr.get_status(robot_id)
    return {
        "robot_id": robot_id,
        "audio_card_detected": True,
        "card_index": 2,
        "device_name": "USB PnP Audio Device",
        "serial_symlink_present": True,
        "serial_device": "/dev/wonderecho",
        "asr_language": asr_lang,
        "wake_listener_active": bool(wake_info["active"]),
        "last_wake_event": wake_info["last_event"],
        "error": None,
        **mixer,
    }


@router.get("/api/robots/{robot_id}/voice/voices")
async def robot_voice_catalog(robot_id: str, request: Request) -> Dict[str, Any]:
    """Return available Offline Piper (default), Edge Neural, Auto, and legacy eSpeak voices."""
    _require_robot(_robot_store(request), robot_id)
    return list_available_voices()


@router.post("/api/robots/{robot_id}/voice/speak")
async def robot_voice_speak(
    robot_id: str,
    body: VoiceSpeakRequest,
    request: Request,
) -> Dict[str, Any]:
    """Synthesize speech (default: offline Piper Neural) with WonderEcho anti-clipping EQ and play live."""
    store = _robot_store(request)
    robot = _require_robot(store, robot_id)
    ssh_pw = store.get_robot_ssh_password(robot_id)

    try:
        res = await speak_text_on_robot(
            ip=robot["ip_address"],
            user=robot["ssh_user"],
            password=ssh_pw,
            text=body.text,
            engine=body.engine,
            voice=body.voice,
            speed=body.speed,
            anti_clip=body.anti_clip,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SSHAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except (SSHCommandError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    _ai_store(request).record_voice_log(
        robot_id=robot_id,
        direction="out",
        transcript=res["text"],
        action_taken=f"tts:{res['engine']}:{res.get('voice', '')}".rstrip(":"),
        reply_text=res["text"],
    )
    return res


@router.post("/api/robots/{robot_id}/voice/chime")
async def robot_voice_chime(
    robot_id: str,
    body: VoiceChimeRequest,
    request: Request,
) -> Dict[str, Any]:
    """Play a synthesized test chime (``dong``, ``wakeup``, ``success``, or ``alert``) on WonderEcho Pro."""
    store = _robot_store(request)
    robot = _require_robot(store, robot_id)
    ssh_pw = store.get_robot_ssh_password(robot_id)

    try:
        res = await play_speaker_chime(
            ip=robot["ip_address"],
            user=robot["ssh_user"],
            password=ssh_pw,
            chime=body.chime,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SSHAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except SSHCommandError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    _ai_store(request).record_voice_log(
        robot_id=robot_id,
        direction="out",
        transcript=f"[chime:{res['chime']}]",
        action_taken=f"chime:{res['chime']}",
        reply_text="",
    )
    return res


@router.post("/api/robots/{robot_id}/voice/listen")
async def robot_voice_listen(
    robot_id: str,
    body: VoiceListenRequest,
    request: Request,
) -> Dict[str, Any]:
    """Capture WonderEcho mic audio, transcribe locally via ``faster-whisper`` STT, execute intent, and log it."""
    store = _robot_store(request)
    robot = _require_robot(store, robot_id)
    ssh_pw = store.get_robot_ssh_password(robot_id)

    transcript = (body.simulated_transcript or "").strip()
    audio_bytes = 0
    if not transcript:
        try:
            wav_data = await record_mic_on_robot(
                ip=robot["ip_address"],
                user=robot["ssh_user"],
                password=ssh_pw,
                duration_sec=body.duration_sec,
            )
            audio_bytes = len(wav_data)
            vcfg = _ai_store(request).get_voice_config(robot_id)
            transcript = await transcribe_wav_offline(
                wav_data, wake_word=str(vcfg.get("wake_word") or "Hey OX")
            )
        except SSHAuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except SSHCommandError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    executor = _build_voice_action_executor(request, robot, ssh_pw)
    try:
        res = await listen_and_process_voice_command(
            robot_id=robot_id,
            ip=robot["ip_address"],
            user=robot["ssh_user"],
            password=ssh_pw,
            duration_sec=body.duration_sec,
            execute_commands=body.execute_commands,
            speak_reply=body.speak_reply,
            simulated_transcript=transcript,
            action_executor=executor,
        )
    except SSHAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except SSHCommandError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if audio_bytes > 0:
        res["audio_bytes"] = audio_bytes
    _ai_store(request).record_voice_log(
        robot_id=robot_id,
        direction="in",
        transcript=res.get("transcript") or "",
        action_taken=res.get("action_taken") or "none",
        reply_text=res.get("reply_text") or "",
    )
    return res


@router.post("/api/robots/{robot_id}/voice/wake-listener")
async def robot_voice_wake_listener(
    robot_id: str,
    body: WakeListenerToggleRequest,
    request: Request,
) -> Dict[str, Any]:
    """Start or stop the background WonderEcho Pro serial wake-word listener for ``/dev/wonderecho``."""
    store = _robot_store(request)
    robot = _require_robot(store, robot_id)
    ssh_pw = store.get_robot_ssh_password(robot_id)
    wake_mgr = _wake_manager(request)
    ai_store = _ai_store(request)

    if not body.enabled:
        return await wake_mgr.stop(robot_id)

    executor = _build_voice_action_executor(request, robot, ssh_pw)

    async def _on_frame(frame: Dict[str, Any]) -> None:
        intent = str(frame.get("intent") or "unknown")
        label = str(frame.get("label") or intent)
        action_taken = f"wonderecho:{intent}"
        reply_text = ""
        if intent == "wake":
            try:
                await play_speaker_chime(robot["ip_address"], robot["ssh_user"], ssh_pw, chime="wakeup")
                reply_text = "Wake chime played."
            except Exception:
                pass
        elif intent in ("stand", "sit", "lie_down", "wave", "stop"):
            mapped = "estop" if intent == "stop" else intent
            try:
                action_taken, reply_text = await executor({"intent": mapped, "reply_hint": ""})
            except Exception as exc:
                sys.stderr.write(f"[voice.wake] Offline command execution failed: {exc}\n")
        ai_store.record_voice_log(
            robot_id=robot_id,
            direction="wake",
            transcript=label,
            action_taken=action_taken,
            reply_text=reply_text,
        )

    return await wake_mgr.start(
        robot_id=robot_id,
        ip=robot["ip_address"],
        user=robot["ssh_user"],
        password=ssh_pw,
        on_frame=_on_frame,
    )


@router.post("/api/robots/{robot_id}/voice/diagnostics")
async def robot_voice_diagnostics(
    robot_id: str,
    request: Request,
    body: Optional[VoiceDiagnosticsRequest] = None,
) -> Dict[str, Any]:
    """Run the 6-point WonderEcho USB, ALSA, serial, Piper+Whisper loopback & live mic diagnostic suite."""
    store = _robot_store(request)
    robot = _require_robot(store, robot_id)
    ssh_pw = store.get_robot_ssh_password(robot_id)
    cfg = _ai_store(request).get_voice_config(robot_id)
    req = body or VoiceDiagnosticsRequest()
    return await run_voice_diagnostics(
        robot_id=robot_id,
        ip=robot["ip_address"],
        user=robot["ssh_user"],
        password=ssh_pw,
        wake_word=str(cfg.get("wake_word") or "Hey OX"),
        wake_aliases=cfg.get("wake_aliases"),
        record_live_sec=req.record_live_sec,
        test_speaker=req.test_speaker,
        conversation_manager=_conversation_manager(request),
    )


@router.get("/api/robots/{robot_id}/voice/logs")
async def robot_voice_logs(
    robot_id: str,
    request: Request,
    limit: int = Query(default=30, ge=1, le=200),
) -> Dict[str, List[Dict[str, Any]]]:
    """List recent voice utterances, commands, and wake events recorded for ``robot_id``."""
    _require_robot(_robot_store(request), robot_id)
    entries = _ai_store(request).list_voice_logs(robot_id=robot_id, limit=limit)
    return {"entries": entries}


@router.post("/api/robots/{robot_id}/hardware/udev-rules")
async def robot_install_udev_rules(robot_id: str, request: Request) -> Dict[str, Any]:
    """Install persistent ``/etc/udev/rules.d/99-puppypi-serial.rules`` creating ``/dev/wonderecho`` and ``/dev/ldlidar``."""
    store = _robot_store(request)
    robot = _require_robot(store, robot_id)
    ssh_pw = store.get_robot_ssh_password(robot_id)
    try:
        return await install_puppypi_udev_rules(
            ip=robot["ip_address"],
            user=robot["ssh_user"],
            password=ssh_pw,
        )
    except SSHAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except SSHCommandError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
