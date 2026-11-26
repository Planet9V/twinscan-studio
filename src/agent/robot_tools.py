"""Unified 10-Tool Safe Robot Registry for OpenClaw MCP Bridge & 'Hey OX' Voice Tool-Calling.

Every tool enforces PuppyPi Pro physical safety boundaries, Patrol <-> Explorer mutual exclusion,
global E-STOP precedence, and structured ``{ok, tool, robot_id, summary, data, duration_ms}``
responses without adding any third-party dependencies.
"""

from __future__ import annotations

import asyncio
import sys
import time
from typing import Any, Dict, List, Optional, Sequence

import cv2
import numpy as np

from src.lidar.composite_enhancer import resolve_enhance_preset
from src.lidar.scene_reconstructor import reconstruct_enhanced_wall_panel
from src.robot.conversation_engine import BUILTIN_PERSONALITIES
from src.robot.explorer_engine import compute_battery_pct_2s, compute_room_coverage_pct
from src.robot.patrol_engine import compute_live_sectors_from_points
from src.robot.ros_profiles import get_ros_profile, normalize_ros_mode
from src.robot.rosbridge_proxy import (
    call_go_home,
    fetch_robot_snapshot,
    publish_pose,
    run_action,
    trigger_estop,
)
from src.robot.voice_manager import speak_text_on_robot

ALLOWED_BODY_ACTIONS = frozenset(
    {
        "sit",
        "stand",
        "stand_low",
        "lie_down",
        "bow",
        "wave",
        "shake_hands",
        "nod",
        "push_up",
        "moonwalk",
        "go_home",
    }
)

_POSE_PRESET_MAP: Dict[str, str] = {
    "sit": "sit",
    "stand": "stand",
    "stand_low": "stand_low",
    "lie_down": "lie_down",
    "bow": "bow",
}

_ACTION_GROUP_MAP: Dict[str, str] = {
    "wave": "wave.d6ac",
    "shake_hands": "shake_hands.d6ac",
    "nod": "nod.d6ac",
    "push_up": "push-up.d6ac",
    "moonwalk": "moonwalk.d6ac",
}

ROBOT_TOOL_SPECS: List[Dict[str, Any]] = [
    {
        "name": "get_robot_status",
        "description": (
            "Read PuppyPi Pro live health: 2S LiPo battery voltage & percentage, active ROS distro, "
            "online/offline status, 5-sector LD19 360-degree LiDAR clearances, and active patrol/explorer state."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "speak_aloud",
        "description": (
            "Speak a concise phrase aloud through PuppyPi's WonderEcho Pro USB speaker using offline Piper TTS."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Plain-text message to speak aloud (clamped to <= 320 characters).",
                },
                "voice": {
                    "type": "string",
                    "description": "Optional Piper voice name (e.g. en_US-lessac-medium).",
                },
            },
            "required": ["text"],
            "additionalProperties": False,
        },
    },
    {
        "name": "run_body_action",
        "description": (
            "Execute a validated safe quadruped posture or trick on PuppyPi Pro "
            "(sit, stand, stand_low, lie_down, bow, wave, shake_hands, nod, push_up, moonwalk, go_home)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": sorted(ALLOWED_BODY_ACTIONS),
                    "description": "Safe PuppyPi posture or action group name.",
                },
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    },
    {
        "name": "capture_camera_snapshot",
        "description": (
            "Grab a live FPV frame from PuppyPi's front UVC camera and optionally run offline "
            "YOLO11n object/animal & YuNet/SFace face detection."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "analyze": {
                    "type": "boolean",
                    "description": "When true (default), run local YOLO11n + face recognition on the captured frame.",
                    "default": True,
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "recall_spatial_memory",
        "description": (
            "Search Eigenia TwinScan Semantic Spatial Memory for previously sighted people, pets, or objects "
            "(e.g. 'keys', 'dog', 'backpack', 'Jim')."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Optional keyword or label to search across labels, notes, and tags.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of matching sightings to return (1..25, default 8).",
                    "minimum": 1,
                    "maximum": 25,
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "start_autonomous_explore",
        "description": (
            "Start Stage 3 Autonomous Frontier Explorer & Multi-Angle 3D Room Mapper with automatic "
            "Patrol mutual exclusion and low-battery Return-to-Home (RTH)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "space_context": {
                    "type": "string",
                    "description": "Optional space ID or room description hint.",
                },
                "max_iterations": {
                    "type": "integer",
                    "description": "Maximum frontier stations to map (1..15, default 6).",
                    "minimum": 1,
                    "maximum": 15,
                },
                "rth_battery_v": {
                    "type": "number",
                    "description": "2S LiPo low-battery auto-RTH voltage threshold (6.6..7.8 V, default 7.1).",
                    "minimum": 6.6,
                    "maximum": 7.8,
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "return_to_home",
        "description": (
            "Trigger immediate safe Return-to-Home Base (RTH) on PuppyPi Pro so it navigates back to (0, 0) and parks."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "stop_robot_estop",
        "description": (
            "Emergency Stop: immediately halt Patrol, Autonomous Explorer, Sentry, and AI follow loops, "
            "publish zero velocity, and invoke /puppy_control/go_home."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "scan_room_wall_3d",
        "description": (
            "Capture a zero-movement Stage 1 3D relief wall panel fusing PuppyPi's live camera, "
            "LD19 metric LiDAR rays, and Depth Anything V2 into the active 3D Digital Twin space."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "quality": {
                    "type": "string",
                    "enum": ["fast", "balanced", "ultra"],
                    "description": "Reconstruction quality preset (fast, balanced, or ultra -> studio_ultra).",
                    "default": "balanced",
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "chat_as_ox",
        "description": (
            "Send a natural-language prompt to PuppyPi's onboard 'Hey OX' conversational assistant "
            "using its active personality and memory."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "User message or question for OX.",
                },
                "speak": {
                    "type": "boolean",
                    "description": "Whether OX should also speak its reply aloud on PuppyPi (default false).",
                    "default": False,
                },
            },
            "required": ["message"],
            "additionalProperties": False,
        },
    },
]

_TOOL_NAMES = frozenset(spec["name"] for spec in ROBOT_TOOL_SPECS)


def get_openrouter_tool_schemas(exclude: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
    """Return OpenRouter / OpenAI-compatible function-calling tool definitions.

    Args:
        exclude: Optional tool names to omit (e.g. ``("chat_as_ox", "speak_aloud")`` inside voice chat).

    Returns:
        List of ``{"type": "function", "function": {"name", "description", "parameters"}}`` dicts.
    """
    skip = set(exclude or ())
    return [
        {
            "type": "function",
            "function": {
                "name": spec["name"],
                "description": spec["description"],
                "parameters": spec["parameters"],
            },
        }
        for spec in ROBOT_TOOL_SPECS
        if spec["name"] not in skip
    ]


def get_mcp_tool_schemas(exclude: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
    """Return Model Context Protocol (MCP) ``tools/list`` schemas for all registered robot tools.

    Args:
        exclude: Optional tool names to omit.

    Returns:
        List of ``{"name", "description", "inputSchema"}`` dictionaries.
    """
    skip = set(exclude or ())
    return [
        {
            "name": spec["name"],
            "description": spec["description"],
            "inputSchema": spec["parameters"],
        }
        for spec in ROBOT_TOOL_SPECS
        if spec["name"] not in skip
    ]


def _resolve_robot(app: Any, robot_id: Optional[str]) -> Optional[Dict[str, Any]]:
    store = getattr(app.state, "robot_store", None)
    if store is None:
        return None
    if robot_id:
        found = store.get_robot(robot_id)
        if found:
            return found
        return None
    robots = store.list_robots()
    return robots[0] if robots else None


def _resolve_battery_v(rt: Any, robot: Optional[Dict[str, Any]]) -> Optional[float]:
    if rt is not None:
        live_v = (getattr(rt, "robot_pose", None) or {}).get("battery_v")
        if live_v is not None:
            try:
                v = float(live_v)
                if v > 1.0:
                    return round(v, 2)
            except (TypeError, ValueError):
                pass
    if robot and robot.get("battery_mv"):
        try:
            v = float(robot["battery_mv"]) / 1000.0
            if v > 1.0:
                return round(v, 2)
        except (TypeError, ValueError):
            pass
    return None


async def _fetch_robot_frame_safe(robot: Dict[str, Any]) -> bytes:
    ip = robot["ip_address"]
    video_port = int(robot.get("video_port") or 8080)
    ros_ver = normalize_ros_mode(robot.get("active_ros_distro"))
    primary = get_ros_profile(ros_ver)["camera_topic"]
    alt = "/usb_cam/image_raw" if primary == "/image_raw" else "/image_raw"
    try:
        return await fetch_robot_snapshot(ip=ip, port=video_port, topic=primary, timeout=3.5, retries=2)
    except Exception:
        return await fetch_robot_snapshot(ip=ip, port=video_port, topic=alt, timeout=3.5, retries=2)


async def execute_robot_tool(
    app: Any,
    tool_name: str,
    arguments: Optional[Dict[str, Any]] = None,
    robot_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute one of the 10 validated safe robot tools against the active FastAPI application state.

    Args:
        app: Active FastAPI application exposing ``app.state`` managers and stores.
        tool_name: Canonical tool name from ``ROBOT_TOOL_SPECS``.
        arguments: Optional tool argument dictionary.
        robot_id: Optional target robot UUID (defaults to the first registered robot).

    Returns:
        Structured dictionary ``{ok, tool, robot_id, summary, data, duration_ms}``.

    Raises:
        ValueError: If ``tool_name`` is unknown or arguments fail strict safety validation.
    """
    name = str(tool_name or "").strip()
    if name not in _TOOL_NAMES:
        raise ValueError(f"Unknown robot tool: {tool_name!r}")

    args = dict(arguments or {})
    t0 = time.perf_counter()
    rt = getattr(app.state, "runtime", None)
    robot_store = getattr(app.state, "robot_store", None)
    ai_store = getattr(app.state, "robot_ai_store", None)
    ai_vision = getattr(app.state, "ai_vision_engine", None)
    patrol_mgr = getattr(app.state, "patrol_manager", None)
    explorer_mgr = getattr(app.state, "explorer_manager", None)
    sentry_mgr = getattr(app.state, "sentry_manager", None)
    conv_mgr = getattr(app.state, "conversation_manager", None)

    robot = _resolve_robot(app, robot_id)
    resolved_id = robot["id"] if robot else robot_id

    def _finish(ok: bool, summary: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {
            "ok": ok,
            "tool": name,
            "robot_id": resolved_id,
            "summary": summary,
            "data": data or {},
            "duration_ms": int((time.perf_counter() - t0) * 1000),
        }

    # --- 1. get_robot_status ---
    if name == "get_robot_status":
        batt_v = _resolve_battery_v(rt, robot)
        batt_pct = compute_battery_pct_2s(batt_v)
        ros_distro = str((robot or {}).get("active_ros_distro") or "ros2")
        status_str = str((robot or {}).get("status") or ("offline" if not robot else "registered"))

        lidar_live = False
        sectors: Dict[str, Optional[float]] = {
            "front": None,
            "front_left": None,
            "front_right": None,
            "left": None,
            "right": None,
        }
        if (
            rt is not None
            and rt.source_mode == "robot_ros2"
            and rt.robot_scan_connected
            and rt.latest_raw_points
            and float(getattr(rt, "_last_scan_mono", 0.0) or 0.0) > 0.0
            and (time.monotonic() - float(rt._last_scan_mono)) <= 3.5
        ):
            lidar_live = True
            sectors = compute_live_sectors_from_points(rt.latest_raw_points)

        patrol_st = patrol_mgr.get_status(resolved_id) if (patrol_mgr and resolved_id) else {"active": False, "state": "idle"}
        explorer_st = explorer_mgr.get_status(resolved_id) if (explorer_mgr and resolved_id) else {"active": False, "state": "idle"}

        batt_txt = f"{batt_v:.2f}V ({batt_pct}%)" if batt_v is not None else "unknown battery"
        front_txt = f"{sectors['front']:.2f}m front" if sectors.get("front") is not None else "LiDAR offline"
        rname = (robot or {}).get("name") or "PuppyPi"
        summary = (
            f"{rname} ({status_str}, {ros_distro.upper()}): {batt_txt}, {front_txt}, "
            f"patrol={patrol_st.get('state', 'idle')}, explorer={explorer_st.get('state', 'idle')}."
        )
        return _finish(
            True,
            summary,
            {
                "robot_name": rname,
                "status": status_str,
                "ros_distro": ros_distro,
                "battery_v": batt_v,
                "battery_pct": batt_pct,
                "lidar_live": lidar_live,
                "sectors_m": sectors,
                "patrol_state": patrol_st.get("state", "idle"),
                "patrol_active": bool(patrol_st.get("active", False)),
                "explorer_state": explorer_st.get("state", "idle"),
                "explorer_active": bool(explorer_st.get("active", False)),
            },
        )

    # --- 5. recall_spatial_memory (works even without live robot) ---
    if name == "recall_spatial_memory":
        if ai_store is None:
            return _finish(False, "Spatial Memory store is unavailable.", {})
        query = str(args.get("query") or "").strip() or None
        limit = max(1, min(25, int(args.get("limit", 8))))
        sightings = ai_store.list_spatial_sightings(query=query, limit=limit, status="active")
        if not sightings:
            q_txt = f" matching '{query}'" if query else ""
            return _finish(True, f"No active Spatial Memory sightings found{q_txt}.", {"sightings": [], "count": 0})
        top = sightings[:4]
        bits = [
            f"{s['label']} ({s['kind']} at {s.get('x_m', 0.0):.1f}m, {s.get('y_m', 0.0):.1f}m)"
            for s in top
        ]
        summary = f"Found {len(sightings)} sighting(s): " + "; ".join(bits) + "."
        return _finish(True, summary, {"sightings": sightings, "count": len(sightings), "query": query})

    # Remaining tools require a registered robot
    if not robot or not resolved_id:
        return _finish(False, "No robot is registered in Eigenia TwinScan yet.", {})

    ip = str(robot["ip_address"])
    ros_port = int(robot.get("rosbridge_port") or 9090)
    ros_ver = normalize_ros_mode(robot.get("active_ros_distro"))

    # --- 2. speak_aloud ---
    if name == "speak_aloud":
        text = str(args.get("text") or "").strip()[:320]
        if not text:
            raise ValueError("speak_aloud requires non-empty 'text'.")
        voice = str(args.get("voice") or "").strip() or None
        ssh_pw = robot_store.get_robot_ssh_password(resolved_id) if robot_store else None
        if not ssh_pw:
            return _finish(False, "Robot SSH credentials are not configured for WonderEcho TTS.", {"text": text})
        try:
            res = await speak_text_on_robot(
                ip=ip,
                user=str(robot.get("ssh_user") or "ubuntu"),
                password=ssh_pw,
                text=text,
                voice=voice or "en_US-lessac-medium",
                engine="auto",
                anti_clip=True,
            )
            return _finish(True, f"Spoke aloud: \"{text[:80]}\"", {"spoken": True, "text": text, "result": res})
        except Exception as exc:
            sys.stderr.write(f"[agent.speak_aloud] Failed on {ip}: {exc}\n")
            return _finish(False, f"Unable to speak aloud on robot: {exc}", {"text": text})

    # --- 3. run_body_action ---
    if name == "run_body_action":
        act = str(args.get("action") or "").strip().lower()
        if act not in ALLOWED_BODY_ACTIONS:
            raise ValueError(f"Unsupported body action {act!r}. Allowed: {sorted(ALLOWED_BODY_ACTIONS)}")
        try:
            if act == "go_home":
                await call_go_home(ip=ip, port=ros_port, ros_version=ros_ver, robot_id=resolved_id)
            elif act in _POSE_PRESET_MAP:
                await publish_pose(
                    ip=ip, port=ros_port, preset=_POSE_PRESET_MAP[act], ros_version=ros_ver, robot_id=resolved_id
                )
            else:
                await run_action(
                    ip=ip,
                    port=ros_port,
                    name=_ACTION_GROUP_MAP[act],
                    wait=False,
                    ros_version=ros_ver,
                    robot_id=resolved_id,
                )
            return _finish(True, f"Executed PuppyPi body action '{act}'.", {"action": act})
        except Exception as exc:
            sys.stderr.write(f"[agent.run_body_action] '{act}' failed on {ip}: {exc}\n")
            return _finish(False, f"Could not execute action '{act}' (robot offline or ROSBridge unreachable): {exc}", {"action": act})

    # --- 4. capture_camera_snapshot ---
    if name == "capture_camera_snapshot":
        analyze = bool(args.get("analyze", True))
        try:
            jpg = await _fetch_robot_frame_safe(robot)
        except Exception as exc:
            sys.stderr.write(f"[agent.capture_camera_snapshot] Camera fetch failed on {ip}: {exc}\n")
            return _finish(False, f"Robot camera unavailable: {exc}", {})

        stored_id: Optional[str] = None
        if rt is not None and getattr(rt, "repo", None) is not None:
            rec = rt.repo.store_file(
                filename=f"agent-snap-{resolved_id[:8]}-{int(time.time())}.jpg",
                content_type="image/jpeg",
                data=jpg,
                category="agent_snapshot",
                space_id=rt.active_space_id or None,
                metadata={"robot_id": resolved_id, "source": "agent_tool"},
            )
            stored_id = rec["id"]

        detections: List[Dict[str, Any]] = []
        faces_found: List[str] = []
        if analyze and ai_vision is not None:
            arr = np.frombuffer(jpg, dtype=np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if frame is not None and frame.size > 0:
                try:
                    objs = await asyncio.to_thread(ai_vision.detect_objects_and_animals, frame, 0.35)
                    detections = [
                        {"label": str(o["label"]), "kind": str(o.get("kind", "object")), "confidence": round(float(o["confidence"]), 3)}
                        for o in objs[:8]
                    ]
                except Exception as exc:
                    sys.stderr.write(f"[agent.snapshot] Object detection failed: {exc}\n")
                try:
                    faces = await asyncio.to_thread(ai_vision.detect_faces_and_embeddings, frame)
                    for fc in faces[:4]:
                        match = ai_store.match_face_embedding(fc["embedding"], threshold=0.363) if ai_store else None
                        faces_found.append(match["person"]["name"] if match else "Unknown Person")
                except Exception as exc:
                    sys.stderr.write(f"[agent.snapshot] Face detection failed: {exc}\n")

        labels = [d["label"] for d in detections] + faces_found
        summary = (
            f"Captured FPV snapshot ({len(jpg)} bytes); detected: {', '.join(labels)}."
            if labels
            else f"Captured FPV snapshot ({len(jpg)} bytes); clear view with no standout detections."
        )
        return _finish(
            True,
            summary,
            {
                "bytes": len(jpg),
                "snapshot_file_id": stored_id,
                "snapshot_url": f"/api/files/{stored_id}" if stored_id else None,
                "detections": detections,
                "faces": faces_found,
            },
        )

    # --- 6. start_autonomous_explore ---
    if name == "start_autonomous_explore":
        if explorer_mgr is None:
            return _finish(False, "Autonomous Explorer manager is not initialized.", {})
        if patrol_mgr is not None and patrol_mgr.get_status(resolved_id).get("active"):
            try:
                await patrol_mgr.stop(resolved_id, ip=ip, rosbridge_port=ros_port, ros_version=ros_ver)
            except Exception as exc:
                sys.stderr.write(f"[agent.explore] Stopping active patrol failed: {exc}\n")

        max_iters = max(1, min(15, int(args.get("max_iterations", 6))))
        rth_v = max(6.6, min(7.8, float(args.get("rth_battery_v", 7.1))))
        space_ctx = str(args.get("space_context") or "").strip() or (rt.active_space_id if rt else None)
        st = await explorer_mgr.start(
            robot_id=resolved_id,
            ip=ip,
            rosbridge_port=ros_port,
            ros_version=ros_ver,
            space_id=space_ctx,
            max_iterations=max_iters,
            rth_battery_v=rth_v,
            require_lidar=True,
            get_lidar_points=lambda: (
                rt.latest_raw_points
                if (
                    rt is not None
                    and rt.source_mode == "robot_ros2"
                    and rt.robot_scan_connected
                    and float(getattr(rt, "_last_scan_mono", 0.0) or 0.0) > 0.0
                    and (time.monotonic() - float(rt._last_scan_mono)) <= 3.5
                )
                else []
            ),
            get_dark_zones=lambda: list(rt.latest_dark_zones or []) if rt else [],
            get_coverage_pct=lambda: compute_room_coverage_pct(
                rt.latest_metrics if rt else {},
                rt.latest_dark_zones if rt else [],
                explorer_mgr.get_status(resolved_id).get("panels_captured", 0),
            ),
            get_battery_v=lambda: _resolve_battery_v(rt, robot),
            get_imu_yaw_deg=lambda: (
                float(rt.robot_pose["yaw_deg"])
                if rt is not None and (rt.robot_pose or {}).get("live") and (rt.robot_pose or {}).get("yaw_deg") is not None
                else None
            ),
        )
        ok = bool(st.get("active"))
        summary = (
            f"Autonomous Explorer started ({max_iters} stations, auto-RTH <= {rth_v:.2f}V)."
            if ok
            else str(st.get("error") or f"Explorer did not start (state={st.get('state')}).")
        )
        return _finish(ok, summary, {"status": st})

    # --- 7. return_to_home ---
    if name == "return_to_home":
        if explorer_mgr is None:
            return _finish(False, "Autonomous Explorer manager is unavailable.", {})
        st = explorer_mgr.trigger_rth(resolved_id)
        return _finish(True, "Return-to-Home Base (RTH) triggered safely.", {"status": st})

    # --- 8. stop_robot_estop ---
    if name == "stop_robot_estop":
        stopped_subsystems: List[str] = []
        if patrol_mgr is not None:
            try:
                await patrol_mgr.stop(resolved_id)
                stopped_subsystems.append("patrol")
            except Exception as exc:
                sys.stderr.write(f"[agent.estop] Patrol stop error: {exc}\n")
        if explorer_mgr is not None:
            try:
                await explorer_mgr.stop(resolved_id)
                stopped_subsystems.append("explorer")
            except Exception as exc:
                sys.stderr.write(f"[agent.estop] Explorer stop error: {exc}\n")
        if sentry_mgr is not None:
            try:
                await sentry_mgr.disarm(resolved_id)
                stopped_subsystems.append("sentry")
            except Exception as exc:
                sys.stderr.write(f"[agent.estop] Sentry disarm error: {exc}\n")
        if ai_vision is not None:
            try:
                ai_vision.stop_autonomous_motion(resolved_id)
                stopped_subsystems.append("ai_vision")
            except Exception as exc:
                sys.stderr.write(f"[agent.estop] AI vision stop error: {exc}\n")

        ros_ok = False
        ros_err: Optional[str] = None
        try:
            await trigger_estop(ip=ip, port=ros_port, ros_version=ros_ver, robot_id=resolved_id)
            ros_ok = True
        except Exception as exc:
            ros_err = str(exc)
            sys.stderr.write(f"[agent.estop] ROSBridge E-STOP failed on {ip}: {exc}\n")

        summary = (
            f"Emergency Stop engaged across {', '.join(stopped_subsystems)} and ROSBridge go_home."
            if ros_ok
            else f"Halted local autonomous loops ({', '.join(stopped_subsystems)}); robot ROSBridge unreachable ({ros_err})."
        )
        return _finish(True, summary, {"stopped": stopped_subsystems, "rosbridge_estop_sent": ros_ok, "rosbridge_error": ros_err})

    # --- 9. scan_room_wall_3d ---
    if name == "scan_room_wall_3d":
        q_raw = str(args.get("quality") or "balanced").strip().lower()
        preset_map = {"fast": "fast", "balanced": "balanced", "ultra": "studio_ultra", "studio_ultra": "studio_ultra"}
        if q_raw not in preset_map:
            raise ValueError("quality must be one of 'fast', 'balanced', or 'ultra'.")
        space_id = rt.active_space_id if rt else None
        if not space_id or rt is None or ai_store is None:
            return _finish(False, "No active Digital Twin space is selected for 3D wall scanning.", {})
        try:
            jpg = await _fetch_robot_frame_safe(robot)
        except Exception as exc:
            sys.stderr.write(f"[agent.scan_3d] Live camera unreachable on {ip}: {exc}\n")
            return _finish(False, f"Camera offline — cannot scan 3D wall panel: {exc}", {})

        resolved_cfg = resolve_enhance_preset(quality_preset=preset_map[q_raw], overrides={"burst_frames": 1})
        lidar_xy = [(float(p.x), float(p.y)) for p in (rt.latest_points or [])]
        pose = {"x": 0.0, "y": 0.0, "z": 0.22, "yaw_deg": float((rt.robot_pose or {}).get("yaw_deg") or 0.0), "pitch_deg": 0.0, "roll_deg": 0.0}
        reconstructed, enh_jpg, norm_jpg, glb_bytes = await asyncio.to_thread(
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
        slug = f"agent_wall_{int(time.time())}"
        tex = rt.repo.store_file(f"scene-{slug}.jpg", "image/jpeg", enh_jpg, category="scene_texture", space_id=space_id)
        norm = rt.repo.store_file(f"scene-{slug}-normal.jpg", "image/jpeg", norm_jpg, category="scene_normal", space_id=space_id) if norm_jpg else None
        glb = rt.repo.store_file(f"scene-{slug}.glb", "model/gltf-binary", glb_bytes, category="scene_glb", space_id=space_id)
        saved = ai_store.save_scene_panel(
            {
                "space_id": space_id,
                "robot_id": resolved_id,
                "label": f"Agent 3D Scan ({q_raw})",
                "stage": "single_wall",
                "pose": reconstructed["pose"],
                "lidar_calibrated": reconstructed["lidar_calibrated"],
                "lidar_ray_count": reconstructed["lidar_ray_count"],
                "depth_source": reconstructed["depth_source"],
                "mean_distance_m": reconstructed["mean_distance_m"],
                "min_distance_m": reconstructed["min_distance_m"],
                "max_distance_m": reconstructed["max_distance_m"],
                "vertex_count": reconstructed["vertex_count"],
                "triangle_count": reconstructed["triangle_count"],
                "texture_file_id": tex["id"],
                "normal_map_file_id": norm["id"] if norm else None,
                "normal_map_url": f"/api/files/{norm['id']}" if norm else None,
                "glb_file_id": glb["id"],
                "quality_metrics": reconstructed.get("quality_metrics"),
                "mesh": reconstructed["mesh"],
            }
        )
        summary = (
            f"Captured 3D wall panel '{saved['label']}' ({saved['vertex_count']} verts, "
            f"mean {saved['mean_distance_m']:.2f}m, lidar_calibrated={saved['lidar_calibrated']})."
        )
        return _finish(True, summary, {"panel_id": saved["id"], "space_id": space_id, "lidar_calibrated": saved["lidar_calibrated"]})

    # --- 10. chat_as_ox ---
    if name == "chat_as_ox":
        msg = str(args.get("message") or "").strip()
        if not msg:
            raise ValueError("chat_as_ox requires non-empty 'message'.")
        speak = bool(args.get("speak", False))
        if conv_mgr is None or ai_store is None or rt is None:
            return _finish(False, "OX Conversation manager is unavailable.", {})
        cfg = ai_store.get_voice_config(resolved_id)
        pid = str(cfg.get("personality_id") or "dog")
        pers = ai_store.get_personality(pid) or ai_store.get_personality("dog") or dict(BUILTIN_PERSONALITIES[0])
        ssh_pw = robot_store.get_robot_ssh_password(resolved_id) if robot_store else None

        async def _speak_cb(reply_txt: str, vcfg: Dict[str, Any]) -> Dict[str, Any]:
            if not speak or not ssh_pw:
                return {"ok": False}
            return await speak_text_on_robot(
                ip=ip,
                user=str(robot.get("ssh_user") or "ubuntu"),
                password=ssh_pw,
                text=reply_txt,
                voice=str(vcfg.get("default_voice") or "en_US-lessac-medium"),
                engine="auto",
                anti_clip=True,
            )

        turn = await conv_mgr.process_chat_turn(
            robot_id=resolved_id,
            user_text=msg,
            config=cfg,
            personality=pers,
            ai_store=ai_store,
            live_context={
                "robot_name": robot.get("name") or "PuppyPi",
                "ros_mode": ros_ver,
                "battery_v": _resolve_battery_v(rt, robot),
            },
            openrouter_api_key=rt.effective_config.get("openrouter_api_key", ""),
            openrouter_base_url=rt.effective_config.get("openrouter_base_url", "https://openrouter.ai/api/v1"),
            speak_reply=speak and bool(ssh_pw),
            attach_camera="never",
            execute_actions=False,
            speak_fn=_speak_cb if (speak and ssh_pw) else None,
        )
        reply = str(turn.get("reply") or "")
        return _finish(True, reply, {"reply": reply, "personality_id": pid, "spoken": bool(turn.get("spoken"))})

    raise ValueError(f"Unhandled robot tool: {name!r}")
