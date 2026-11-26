"""ROSBridge WebSocket proxy with 0.5s dead-man's switch, PuppyPi safety clamps, and MJPEG video proxy.

Implements exact ``puppy.py`` motion & servo bounds verified on PuppyPi Pro,
server-side 0.5-second dead-man's switch watchdog, optional ``/scan`` LaserScan
ingestion into ``TwinScanRuntimeState``, and single-origin MJPEG/JPEG proxying
via ``httpx.AsyncClient``.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
import sys
import time
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional, Tuple

import httpx
import websockets
from fastapi import WebSocket, WebSocketDisconnect

from src.lidar.ld19_parser import LidarPoint, polar_to_cartesian
from src.robot.ros_profiles import get_ros_profile, normalize_ros_mode

# Verified PuppyPi ROS1 Noetic topics and bounds from puppy.py audit.
VELOCITY_AUTOGAIT_TOPIC = "/puppy_control/velocity/autogait"
VELOCITY_TOPIC = "/puppy_control/velocity"
VELOCITY_TYPE = "puppy_control/Velocity"
POSE_TOPIC = "/puppy_control/pose"
POSE_TYPE = "puppy_control/Pose"
GAIT_TOPIC = "/puppy_control/gait"
GAIT_TYPE = "puppy_control/Gait"
SERVO_TOPIC = "/puppy_control/setServo"
SERVO_TYPE = "puppy_control/SetServo"
BUZZER_TOPIC = "/ros_robot_controller/set_buzzer"
BUZZER_TYPE = "ros_robot_controller/BuzzerState"
RGB_TOPIC = "/ros_robot_controller/set_rgb"
RGB_TYPE = "ros_robot_controller/RGBsState"
OLED_TOPIC = "/ros_robot_controller/set_oled"
OLED_TYPE = "ros_robot_controller/OLEDState"

VELOCITY_WATCHED_TOPICS = {
    "/puppy_control/velocity/autogait",
    "/puppy_control/velocity",
    "/puppy_control/velocity_move",
    "/cmd_vel",
    "/cmd_vel_nav",
}

POSE_PRESETS: Dict[str, Dict[str, Any]] = {
    "Stand": {"roll": 0.0, "pitch": 0.0, "yaw": 0.0, "height": -10.0, "x_shift": -0.5, "stance_x": 0.0, "stance_y": 0.0, "run_time": 500},
    "LieDown": {"roll": 0.0, "pitch": 0.0, "yaw": 0.0, "height": -5.0, "x_shift": 2.0, "stance_x": 0.0, "stance_y": 0.0, "run_time": 500},
    "StandLow": {"roll": 0.0, "pitch": 0.0, "yaw": 0.0, "height": -7.0, "x_shift": -0.5, "stance_x": 0.0, "stance_y": 0.0, "run_time": 500},
    "LookDown": {"roll": 0.0, "pitch": -0.2618, "yaw": 0.0, "height": -10.0, "x_shift": -0.5, "stance_x": 0.0, "stance_y": 0.0, "run_time": 500},
}

GAIT_PRESETS: Dict[str, Dict[str, float]] = {
    "Fast": {"overlap_time": 0.1, "swing_time": 0.15, "clearance_time": 0.0, "z_clearance": 5.0},
    "Slow": {"overlap_time": 0.4, "swing_time": 0.3, "clearance_time": 0.26, "z_clearance": 4.0},
    "Trot": {"overlap_time": 0.2, "swing_time": 0.3, "clearance_time": 0.0, "z_clearance": 8.0},
    "Amble": {"overlap_time": 0.1, "swing_time": 0.2, "clearance_time": 0.1, "z_clearance": 5.0},
    "Walk": {"overlap_time": 0.1, "swing_time": 0.2, "clearance_time": 0.3, "z_clearance": 5.0},
    "Crawl": {"overlap_time": 0.4, "swing_time": 0.3, "clearance_time": 0.2, "z_clearance": 3.0},
    "MarkTime": {"overlap_time": 0.2, "swing_time": 0.1, "clearance_time": 0.0, "z_clearance": 5.0},
}

BODY_ACTION_GROUPS = {
    "stand", "lie_down", "sit", "bow", "wave", "shake_hands", "shake_head", "nod",
    "stretch", "push-up", "press-up", "boxing", "boxing2", "jump", "2_legs_stand",
    "moonwalk", "spacewalk", "pee", "kick_ball_left", "kick_ball_right", "look_down",
    "up_stairs_2cm", "up_stairs_3.5cm", "demo",
}
ARM_ACTION_GROUPS = {
    "stand_with_arm", "grab", "place", "place1", "Clamping", "arm_test", "1",
}
KNOWN_ACTION_GROUPS = BODY_ACTION_GROUPS | ARM_ACTION_GROUPS

SAFE_TOPIC_RE = re.compile(r"^/[A-Za-z0-9_/]{1,128}$")
SAFE_ACTION_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")

VISION_MODES: Dict[str, str] = {
    "raw": "/usb_cam/image_raw",
    "apriltag_detect": "/apriltag_detect/image_result",
    "color_detect": "/color_detect/image_result",
    "face_detect": "/face_detect/image_result",
    "object_tracking": "/object_tracking/image_result",
    "visual_patrol": "/visual_patrol/image_result",
    "lab_config_manager": "/lab_config_manager/image_result",
}
_TOPIC_TO_VISION_MODE: Dict[str, str] = {
    "/usb_cam/image_raw": "raw",
    "/image_raw": "raw",
    **{topic: mode for mode, topic in VISION_MODES.items() if mode != "raw"},
}
_ACTIVE_VISION_MODES: Dict[str, Dict[str, Any]] = {}


def _clamp(val: float, low: float, high: float) -> float:
    return max(low, min(high, float(val)))


def clamp_velocity(x: float, y: float = 0.0, yaw_rate: float = 0.0) -> Dict[str, float]:
    """Clamp PuppyPi velocity command to strict ``puppy.py`` safety bounds.

    Per PuppyPi firmware: ``abs(x) <= 35`` cm/s, ``y`` MUST be ``0.0`` (non-zero is
    silently dropped), and ``abs(yaw_rate) <= 0.89`` rad/s (~51 deg/s).

    Args:
        x: Forward/backward speed in cm/s.
        y: Lateral speed (forced to ``0.0``).
        yaw_rate: Angular yaw rate in rad/s.

    Returns:
        Clamped ``{"x", "y", "yaw_rate"}`` dictionary.
    """
    _ = y  # PuppyPi drops any message with y != 0
    return {
        "x": round(_clamp(x, -35.0, 35.0), 4),
        "y": 0.0,
        "yaw_rate": round(_clamp(yaw_rate, -0.89, 0.89), 4),
    }


def clamp_pose(
    roll: float = 0.0,
    pitch: float = 0.0,
    yaw: float = 0.0,
    height: float = -10.0,
    x_shift: float = -0.5,
    stance_x: float = 0.0,
    stance_y: float = 0.0,
    run_time: int = 500,
) -> Dict[str, float | int]:
    """Clamp PuppyPi body pose parameters to strict ``puppy.py`` safety bounds.

    Per PuppyPi firmware: ``roll`` and ``pitch`` in ``[-0.54, 0.54]`` rad, ``yaw`` MUST
    be ``0.0``, ``height`` in ``[-15.0, -5.0]`` cm, ``x_shift`` in ``[-10.0, 10.0]`` cm,
    and ``stance_x``/``stance_y`` in ``[-5.0, 5.0]`` cm.

    Args:
        roll: Body roll angle in radians.
        pitch: Body pitch angle in radians.
        yaw: Body yaw angle (forced to ``0.0``).
        height: Standing height in cm (more negative = taller).
        x_shift: Center-of-gravity forward/back offset in cm.
        stance_x: Foot stance X offset in cm.
        stance_y: Foot stance Y offset in cm.
        run_time: Interpolation duration in milliseconds.

    Returns:
        Clamped ``puppy_control/Pose`` message dictionary.
    """
    _ = yaw  # PuppyPi drops any pose message with yaw != 0
    return {
        "roll": round(_clamp(roll, -0.54, 0.54), 4),
        "pitch": round(_clamp(pitch, -0.54, 0.54), 4),
        "yaw": 0.0,
        "height": round(_clamp(height, -15.0, -5.0), 3),
        "x_shift": round(_clamp(x_shift, -10.0, 10.0), 3),
        "stance_x": round(_clamp(stance_x, -5.0, 5.0), 3),
        "stance_y": round(_clamp(stance_y, -5.0, 5.0), 3),
        "run_time": int(max(10, min(30000, int(run_time)))),
    }


def clamp_gait(
    overlap_time: float = 0.2,
    swing_time: float = 0.2,
    clearance_time: float = 0.0,
    z_clearance: float = 4.0,
) -> Dict[str, float]:
    """Clamp PuppyPi gait timing parameters to safe operational bounds.

    Args:
        overlap_time: Four-leg stance overlap duration in seconds.
        swing_time: Leg swing duration in seconds.
        clearance_time: Additional phase clearance duration in seconds.
        z_clearance: Foot lift height in cm.

    Returns:
        Clamped ``puppy_control/Gait`` message dictionary.
    """
    return {
        "overlap_time": round(_clamp(overlap_time, 0.0, 1.0), 3),
        "swing_time": round(_clamp(swing_time, 0.05, 1.0), 3),
        "clearance_time": round(_clamp(clearance_time, 0.0, 1.0), 3),
        "z_clearance": round(_clamp(z_clearance, 1.0, 10.0), 3),
    }


def clamp_servo(servo_id: int, pulse: int, time_ms: int = 500) -> Dict[str, int]:
    """Clamp direct servo command to safe PWM pulse and transition timing bounds.

    Args:
        servo_id: Servo bus ID (legs 1..8, 2-DOF arm 9..11).
        pulse: Target PWM pulse in ``[500, 2500]``.
        time_ms: Motion duration in ms in ``[10, 30000]``.

    Returns:
        Clamped ``puppy_control/SetServo`` dictionary ``{"id", "pulse", "time"}``.

    Raises:
        ValueError: If ``servo_id`` is outside valid range ``1..16``.
    """
    sid = int(servo_id)
    if sid < 1 or sid > 16:
        raise ValueError(f"servo_id must be between 1 and 16, got {sid}")
    clamped_pulse = int(max(500, min(2500, int(pulse))))
    clamped_time = int(max(10, min(30000, int(time_ms))))
    return {"id": sid, "pulse": clamped_pulse, "time": clamped_time}


def normalize_action_group_name(name: str) -> str:
    """Validate and normalize an action group filename (appending ``.d6ac``/``.d6a`` if omitted).

    Args:
        name: Action group short name (e.g. ``"wave"``, ``"grab"``) or filename.

    Returns:
        Normalized filename safe for ``/puppy_control/runActionGroup``.

    Raises:
        ValueError: When the name contains unsafe characters or path traversal tokens.
    """
    cleaned = name.strip()
    if not cleaned or ".." in cleaned or "/" in cleaned or "\\" in cleaned or not SAFE_ACTION_RE.match(cleaned):
        raise ValueError(f"Invalid action group name: {name!r}")
    if cleaned.endswith((".d6ac", ".d6a")):
        return cleaned
    if cleaned in ARM_ACTION_GROUPS:
        return f"{cleaned}.d6a"
    return f"{cleaned}.d6ac"


def validate_video_topic(topic: str) -> str:
    """Validate a ROS image topic name before proxying to ``web_video_server``.

    Args:
        topic: ROS image topic path (e.g. ``"/usb_cam/image_raw"``).

    Returns:
        Validated topic string.

    Raises:
        ValueError: If the topic does not match safe ROS topic syntax.
    """
    cleaned = (topic or "/usb_cam/image_raw").strip()
    if not SAFE_TOPIC_RE.match(cleaned):
        raise ValueError(f"Invalid ROS video topic: {topic!r}")
    return cleaned


def laserscan_to_lidar_points(scan_msg: Dict[str, Any]) -> List[LidarPoint]:
    """Convert a ROS ``sensor_msgs/LaserScan`` JSON message into ``LidarPoint`` objects.

    Args:
        scan_msg: ROSBridge JSON payload for ``sensor_msgs/LaserScan``.

    Returns:
        List of valid ``LidarPoint`` entries within ``[range_min, range_max]``.
    """
    ranges = scan_msg.get("ranges") or []
    intensities = scan_msg.get("intensities") or []
    angle_min = float(scan_msg.get("angle_min", 0.0))
    angle_inc = float(scan_msg.get("angle_increment", 0.0))
    range_min = float(scan_msg.get("range_min", 0.05))
    range_max = float(scan_msg.get("range_max", 12.0))

    points: List[LidarPoint] = []
    for idx, raw_r in enumerate(ranges):
        if raw_r is None:
            continue
        try:
            dist = float(raw_r)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(dist) or dist < range_min or dist > range_max:
            continue
        angle_rad = angle_min + idx * angle_inc
        angle_deg = math.degrees(angle_rad) % 360.0
        x, y = polar_to_cartesian(angle_deg, dist)
        raw_i = intensities[idx] if idx < len(intensities) and intensities[idx] is not None else 180
        intensity = int(max(0, min(255, int(float(raw_i)))))
        points.append(LidarPoint(angle_deg=angle_deg, distance_m=dist, intensity=intensity, x=x, y=y))
    return points


async def send_rosbridge_command(
    ip: str,
    port: int,
    op_payload: Dict[str, Any],
    msg_type: Optional[str] = None,
    wait_response: bool = False,
    timeout: float = 4.0,
    retries: int = 3,
    extra_publishes: Optional[List[Dict[str, Any]]] = None,
    extra_publish_delay_s: float = 0.06,
) -> Dict[str, Any]:
    """Send a ROSBridge v2 JSON operation to a robot with TCPROS settle timing and 3x retry.

    For ``publish`` operations, waits 250ms after ``advertise`` so ROS 1 TCPROS subscriber
    negotiation completes before publishing, and 80ms after publishing before closing the WS.

    Args:
        ip: Robot IPv4 address.
        port: ROSBridge WebSocket port (default ``9090``).
        op_payload: ROSBridge JSON operation dict (``publish``, ``call_service``, etc.).
        msg_type: Optional ROS message type to advertise prior to publishing.
        wait_response: When ``True``, wait for a JSON reply frame (e.g. ``service_response``).
        timeout: WebSocket connect and receive timeout in seconds.
        retries: Maximum retry attempts on transient network failures.
        extra_publishes: Optional follow-up publish payloads sent on the same advertised WS.
        extra_publish_delay_s: Delay in seconds before each follow-up publish (default ``0.06s``).

    Returns:
        Dictionary with ``sent: True`` and optional ``response`` frame.
    """
    uri = f"ws://{ip}:{port}"
    last_exc: Optional[Exception] = None
    is_publish = op_payload.get("op") == "publish"
    for attempt in range(1, max(1, retries) + 1):
        try:
            async with websockets.connect(uri, open_timeout=timeout, close_timeout=2.0) as ws:
                if is_publish and msg_type and op_payload.get("topic"):
                    await ws.send(json.dumps({"op": "advertise", "topic": op_payload["topic"], "type": msg_type}))
                    await asyncio.sleep(0.25)
                await ws.send(json.dumps(op_payload))
                for follow_up in extra_publishes or ():
                    if extra_publish_delay_s > 0:
                        await asyncio.sleep(extra_publish_delay_s)
                    await ws.send(json.dumps(follow_up))
                response: Optional[Dict[str, Any]] = None
                if wait_response:
                    raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
                    if isinstance(raw, (bytes, bytearray)):
                        raw = raw.decode("utf-8", errors="replace")
                    response = json.loads(raw)
                elif is_publish:
                    await asyncio.sleep(0.08)
                return {"sent": True, "uri": uri, "payload": op_payload, "response": response}
        except Exception as exc:
            last_exc = exc
            sys.stderr.write(
                f"[rosbridge] Command to {uri} failed (attempt {attempt}/{retries}): {exc}\n"
            )
            if attempt < retries:
                await asyncio.sleep(min(0.25 * attempt, 1.0))
    raise ConnectionError(f"ROSBridge command to {uri} failed after {retries} attempts: {last_exc}")


def normalize_vision_mode(mode_or_topic: str) -> str:
    """Normalize a CV mode name or ROS image topic into a validated vision mode key.

    Args:
        mode_or_topic: Mode key (e.g. ``"visual_patrol"``, ``"raw"``) or topic path
            (e.g. ``"/visual_patrol/image_result"``, ``"/usb_cam/image_raw"``).

    Returns:
        Validated vision mode key in ``VISION_MODES``.

    Raises:
        ValueError: If ``mode_or_topic`` is not a supported CV mode or camera topic.
    """
    raw = str(mode_or_topic or "raw").strip()
    if raw in VISION_MODES:
        return raw
    if raw in _TOPIC_TO_VISION_MODE:
        return _TOPIC_TO_VISION_MODE[raw]
    stripped = raw.lstrip("/").split("/", 1)[0]
    if stripped in VISION_MODES:
        return stripped
    raise ValueError(f"Unsupported vision mode {mode_or_topic!r}; expected one of {sorted(VISION_MODES)}")


async def stop_vision_mode(
    robot_id: str,
    ip: Optional[str] = None,
    port: int = 9090,
    ros_version: str = "ros1",
) -> Optional[str]:
    """Cancel any active CV heartbeat task for ``robot_id`` and call ``/<mode>/exit``.

    Args:
        robot_id: Robot identifier whose active CV node should be stopped.
        ip: Optional robot IP override if not stored in session state.
        port: ROSBridge port override.
        ros_version: Active ROS mode override.

    Returns:
        The previously active CV mode name if one was stopped, else ``None``.
    """
    session = _ACTIVE_VISION_MODES.pop(robot_id, None)
    if not session:
        return None
    task: Optional[asyncio.Task[None]] = session.get("task")
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    prev_mode = str(session.get("mode") or "raw")
    target_ip = str(session.get("ip") or ip or "")
    target_port = int(session.get("port") or port)
    target_ros = str(session.get("ros_version") or ros_version)
    if prev_mode != "raw" and target_ip:
        is_ros2 = normalize_ros_mode(target_ros) == "ros2"
        trigger_type = "std_srvs/srv/Trigger" if is_ros2 else "std_srvs/Trigger"
        set_bool_type = "std_srvs/srv/SetBool" if is_ros2 else "std_srvs/SetBool"
        for svc, stype, args in (
            (f"/{prev_mode}/set_running", set_bool_type, {"data": False}),
            (f"/{prev_mode}/exit", trigger_type, {}),
        ):
            try:
                await send_rosbridge_command(
                    ip=target_ip,
                    port=target_port,
                    op_payload={"op": "call_service", "service": svc, "type": stype, "args": args},
                    wait_response=False,
                    timeout=3.0,
                    retries=2,
                )
            except Exception as exc:
                sys.stderr.write(f"[rosbridge.vision] Failed stopping {svc} on {target_ip}: {exc}\n")
    return prev_mode


async def set_vision_mode(
    robot_id: str,
    ip: str,
    mode: str,
    port: int = 9090,
    ros_version: str = "ros1",
    heartbeat_interval_s: float = 2.5,
) -> Dict[str, Any]:
    """Activate or deactivate a dormant Hiwonder CV node with automatic 2.5s watchdog heartbeat.

    Calls ``/<mode>/enter`` (``Trigger``), ``/<mode>/set_running`` (``SetBool(True)``),
    and starts a background heartbeat task calling ``/<mode>/heartbeat`` every 2.5s.

    Args:
        robot_id: Robot identifier used to track and clean up heartbeat tasks.
        ip: Robot IPv4 address.
        mode: Target mode (``"raw"`` or one of the 6 Hiwonder CV nodes).
        port: ROSBridge port (default ``9090``).
        ros_version: Active ROS mode (``"ros1"`` or ``"ros2"``).
        heartbeat_interval_s: Seconds between watchdog heartbeat service calls (default ``2.5``).

    Returns:
        Dictionary ``{"ok": True, "mode": str, "topic": str, "heartbeat_active": bool}``.
    """
    norm_mode = normalize_vision_mode(mode)
    norm_ros = normalize_ros_mode(ros_version)
    profile = get_ros_profile(norm_ros)

    # Always clean up any previous CV node first so Hiwonder CV apps don't fight over /usb_cam.
    await stop_vision_mode(robot_id=robot_id, ip=ip, port=port, ros_version=norm_ros)

    if norm_mode == "raw":
        return {
            "ok": True,
            "mode": "raw",
            "topic": profile["camera_topic"],
            "heartbeat_active": False,
        }

    is_ros2 = norm_ros == "ros2"
    trigger_type = "std_srvs/srv/Trigger" if is_ros2 else "std_srvs/Trigger"
    set_bool_type = "std_srvs/srv/SetBool" if is_ros2 else "std_srvs/SetBool"

    await send_rosbridge_command(
        ip=ip,
        port=port,
        op_payload={"op": "call_service", "service": f"/{norm_mode}/enter", "type": trigger_type, "args": {}},
        wait_response=False,
        timeout=4.0,
        retries=3,
    )
    await send_rosbridge_command(
        ip=ip,
        port=port,
        op_payload={"op": "call_service", "service": f"/{norm_mode}/set_running", "type": set_bool_type, "args": {"data": True}},
        wait_response=False,
        timeout=4.0,
        retries=3,
    )
    try:
        await send_rosbridge_command(
            ip=ip,
            port=port,
            op_payload={"op": "call_service", "service": f"/{norm_mode}/heartbeat", "type": set_bool_type, "args": {"data": True}},
            wait_response=False,
            timeout=3.0,
            retries=2,
        )
    except Exception as exc:
        sys.stderr.write(f"[rosbridge.vision] Initial heartbeat for {norm_mode} failed: {exc}\n")

    async def _heartbeat_loop() -> None:
        while True:
            try:
                await asyncio.sleep(max(0.02, heartbeat_interval_s))
                await send_rosbridge_command(
                    ip=ip,
                    port=port,
                    op_payload={
                        "op": "call_service",
                        "service": f"/{norm_mode}/heartbeat",
                        "type": set_bool_type,
                        "args": {"data": True},
                    },
                    wait_response=False,
                    timeout=3.0,
                    retries=2,
                )
            except asyncio.CancelledError:
                return
            except Exception as exc:
                sys.stderr.write(f"[rosbridge.vision] Heartbeat loop error for {norm_mode} on {ip}: {exc}\n")

    hb_task = asyncio.create_task(_heartbeat_loop())
    _ACTIVE_VISION_MODES[robot_id] = {
        "mode": norm_mode,
        "ip": ip,
        "port": port,
        "ros_version": norm_ros,
        "task": hb_task,
    }
    return {
        "ok": True,
        "mode": norm_mode,
        "topic": VISION_MODES[norm_mode],
        "heartbeat_active": True,
    }


async def trigger_estop(
    ip: str,
    port: int = 9090,
    timeout: float = 4.0,
    retries: int = 3,
    ros_version: str = "ros1",
    robot_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Trigger immediate PuppyPi emergency stop (zero velocity + ``/puppy_control/go_home`` + exit active CV mode).

    Args:
        ip: Robot IPv4 address.
        port: ROSBridge WebSocket port (default ``9090``).
        timeout: Connection timeout in seconds.
        retries: Maximum retry attempts on transient network errors.
        ros_version: Active ROS mode (``"ros1"`` or ``"ros2"``).
        robot_id: Optional robot ID whose active CV heartbeat mode should be stopped.

    Returns:
        Dictionary summarizing the zero-velocity and go_home operations sent.
    """
    # Stop any active CV mode heartbeat first so tracking nodes don't override E-STOP.
    if robot_id:
        await stop_vision_mode(robot_id=robot_id, ip=ip, port=port, ros_version=ros_version)
    else:
        for rid, sess in list(_ACTIVE_VISION_MODES.items()):
            if sess.get("ip") == ip:
                await stop_vision_mode(robot_id=rid, ip=ip, port=port, ros_version=ros_version)

    profile = get_ros_profile(ros_version)
    vel_type = profile["message_types"]["velocity"]
    go_home_type = profile["service_types"]["go_home"]
    uri = f"ws://{ip}:{port}"
    zero_vel = clamp_velocity(0.0, 0.0, 0.0)
    last_exc: Optional[Exception] = None
    for attempt in range(1, max(1, retries) + 1):
        try:
            async with websockets.connect(uri, open_timeout=timeout, close_timeout=2.0) as ws:
                frames = [
                    {"op": "advertise", "topic": VELOCITY_AUTOGAIT_TOPIC, "type": vel_type},
                    {"op": "publish", "topic": VELOCITY_AUTOGAIT_TOPIC, "msg": zero_vel},
                    {"op": "publish", "topic": VELOCITY_TOPIC, "msg": zero_vel},
                    {"op": "call_service", "service": "/puppy_control/go_home", "type": go_home_type, "args": {}},
                ]
                for frame in frames:
                    await ws.send(json.dumps(frame))
                return {
                    "estop": True,
                    "uri": uri,
                    "ros_version": profile["id"],
                    "velocity": zero_vel,
                    "service": "/puppy_control/go_home",
                }
        except Exception as exc:
            last_exc = exc
            sys.stderr.write(
                f"[rosbridge] E-STOP to {uri} failed (attempt {attempt}/{retries}): {exc}\n"
            )
            if attempt < retries:
                await asyncio.sleep(min(0.2 * attempt, 0.8))
    raise ConnectionError(f"E-STOP to {uri} failed after {retries} attempts: {last_exc}")


async def _ensure_cv_stopped(
    robot_id: Optional[str],
    ip: str,
    port: int,
    ros_version: str,
) -> None:
    """Stop any active Hiwonder CV node for ``robot_id`` or ``ip`` before manual leg/body control."""
    if robot_id and robot_id in _ACTIVE_VISION_MODES:
        await stop_vision_mode(robot_id=robot_id, ip=ip, port=port, ros_version=ros_version)
        return
    for rid, sess in list(_ACTIVE_VISION_MODES.items()):
        if sess.get("ip") == ip:
            await stop_vision_mode(robot_id=rid, ip=ip, port=port, ros_version=ros_version)


async def call_go_home(
    ip: str,
    port: int = 9090,
    ros_version: str = "ros1",
    robot_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Stop any active CV node and invoke ``/puppy_control/go_home`` (``std_srvs/Empty``).

    Args:
        ip: Robot IPv4 address.
        port: ROSBridge port (default ``9090``).
        ros_version: Active ROS mode (``"ros1"`` or ``"ros2"``).
        robot_id: Optional robot ID for stopping active CV modes first.

    Returns:
        ROSBridge service invocation confirmation dictionary.
    """
    await _ensure_cv_stopped(robot_id, ip, port, ros_version)
    profile = get_ros_profile(ros_version)
    return await send_rosbridge_command(
        ip=ip,
        port=port,
        op_payload={
            "op": "call_service",
            "service": "/puppy_control/go_home",
            "type": profile["service_types"]["go_home"],
            "args": {},
        },
        wait_response=False,
    )


async def set_mark_time(
    ip: str,
    enabled: bool,
    port: int = 9090,
    ros_version: str = "ros1",
    robot_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Stop any active CV node and toggle ``/puppy_control/set_mark_time`` (``std_srvs/SetBool``).

    Args:
        ip: Robot IPv4 address.
        enabled: ``True`` to march in place, ``False`` to stop.
        port: ROSBridge port (default ``9090``).
        ros_version: Active ROS mode (``"ros1"`` or ``"ros2"``).
        robot_id: Optional robot ID for stopping active CV modes first.

    Returns:
        ROSBridge service invocation confirmation dictionary.
    """
    await _ensure_cv_stopped(robot_id, ip, port, ros_version)
    profile = get_ros_profile(ros_version)
    return await send_rosbridge_command(
        ip=ip,
        port=port,
        op_payload={
            "op": "call_service",
            "service": "/puppy_control/set_mark_time",
            "type": profile["service_types"]["set_bool"],
            "args": {"data": bool(enabled)},
        },
        wait_response=False,
    )


async def publish_velocity(
    ip: str,
    port: int,
    x: float,
    y: float = 0.0,
    yaw_rate: float = 0.0,
    ros_version: str = "ros1",
    use_autogait: bool = True,
    robot_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Publish a safety-clamped velocity command using ROS 1 or ROS 2 message types.

    Automatically stops any active CV node before commanding manual motion. When
    ``use_autogait=False``, publishes to ``/puppy_control/velocity`` so manual gait
    presets are preserved.

    Args:
        ip: Robot IPv4 address.
        port: ROSBridge port.
        x: Forward/backward speed in cm/s.
        y: Lateral speed (forced to 0.0).
        yaw_rate: Yaw rate in rad/s.
        ros_version: Active ROS mode (``"ros1"`` or ``"ros2"``).
        use_autogait: When ``True`` publish to ``/puppy_control/velocity/autogait``, else ``/puppy_control/velocity``.
        robot_id: Optional robot ID for auto-stopping active CV modes.

    Returns:
        ROSBridge send confirmation dictionary.
    """
    await _ensure_cv_stopped(robot_id, ip, port, ros_version)
    profile = get_ros_profile(ros_version)
    clamped = clamp_velocity(x, y, yaw_rate)
    topic = VELOCITY_AUTOGAIT_TOPIC if use_autogait else VELOCITY_TOPIC
    return await send_rosbridge_command(
        ip=ip,
        port=port,
        op_payload={"op": "publish", "topic": topic, "msg": clamped},
        msg_type=profile["message_types"]["velocity"],
    )


async def publish_pose(
    ip: str,
    port: int,
    roll: float = 0.0,
    pitch: float = 0.0,
    yaw: float = 0.0,
    height: float = -10.0,
    x_shift: float = -0.5,
    stance_x: float = 0.0,
    stance_y: float = 0.0,
    run_time: int = 500,
    preset: Optional[str] = None,
    ros_version: str = "ros1",
    robot_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Publish a safety-clamped pose using two-step ``run_time=0`` -> ``run_time=N`` sequencing.

    Works around Hiwonder ``puppy.py``'s ``PoseFun`` ordering bug (which executes
    ``move_stop(run_time)`` before updating ``stance_config`` when ``run_time != 0``):
    first publishes the new pose with ``run_time=0`` to update ``stance_config``, then
    publishes the same pose with ``run_time=N`` after 60ms on the same advertised WS.

    Args:
        ip: Robot IPv4 address.
        port: ROSBridge port.
        roll: Roll radians.
        pitch: Pitch radians.
        yaw: Yaw radians (forced 0.0).
        height: Height cm in ``[-15, -5]``.
        x_shift: X center-of-gravity shift in cm.
        stance_x: Foot stance X in cm.
        stance_y: Foot stance Y in cm.
        run_time: Interpolation duration in ms (``0`` skips second step).
        preset: Optional named preset (``Stand``, ``LieDown``, ``StandLow``, ``LookDown``, ``GoHome``).
        ros_version: Active ROS mode (``"ros1"`` or ``"ros2"``).
        robot_id: Optional robot ID for auto-stopping active CV modes.

    Returns:
        ROSBridge send confirmation dictionary.
    """
    await _ensure_cv_stopped(robot_id, ip, port, ros_version)
    profile = get_ros_profile(ros_version)
    if preset and preset.lower() in {"gohome", "go_home"}:
        return await call_go_home(ip=ip, port=port, ros_version=ros_version, robot_id=robot_id)

    preset_vals = POSE_PRESETS.get(preset or "", {})
    req_run_time = int(preset_vals.get("run_time", run_time))
    clamped = clamp_pose(
        roll=float(preset_vals.get("roll", roll)),
        pitch=float(preset_vals.get("pitch", pitch)),
        yaw=float(preset_vals.get("yaw", yaw)),
        height=float(preset_vals.get("height", height)),
        x_shift=float(preset_vals.get("x_shift", x_shift)),
        stance_x=float(preset_vals.get("stance_x", stance_x)),
        stance_y=float(preset_vals.get("stance_y", stance_y)),
        run_time=max(10, req_run_time) if req_run_time > 0 else 10,
    )
    stage1_msg = {**clamped, "run_time": 0}
    extra: List[Dict[str, Any]] = []
    if req_run_time > 0:
        extra.append({"op": "publish", "topic": POSE_TOPIC, "msg": clamped})

    return await send_rosbridge_command(
        ip=ip,
        port=port,
        op_payload={"op": "publish", "topic": POSE_TOPIC, "msg": stage1_msg},
        msg_type=profile["message_types"]["pose"],
        extra_publishes=extra,
        extra_publish_delay_s=0.06,
    )


async def publish_gait(
    ip: str,
    port: int,
    overlap_time: float = 0.2,
    swing_time: float = 0.2,
    clearance_time: float = 0.0,
    z_clearance: float = 4.0,
    preset: Optional[str] = None,
    ros_version: str = "ros1",
    robot_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Stop any active CV node and publish safety-clamped gait timing parameters."""
    await _ensure_cv_stopped(robot_id, ip, port, ros_version)
    profile = get_ros_profile(ros_version)
    preset_vals = GAIT_PRESETS.get(preset or "", {})
    clamped = clamp_gait(
        overlap_time=float(preset_vals.get("overlap_time", overlap_time)),
        swing_time=float(preset_vals.get("swing_time", swing_time)),
        clearance_time=float(preset_vals.get("clearance_time", clearance_time)),
        z_clearance=float(preset_vals.get("z_clearance", z_clearance)),
    )
    return await send_rosbridge_command(
        ip=ip,
        port=port,
        op_payload={"op": "publish", "topic": GAIT_TOPIC, "msg": clamped},
        msg_type=profile["message_types"]["gait"],
    )


async def run_action(
    ip: str,
    port: int,
    name: str,
    wait: bool = False,
    ros_version: str = "ros1",
    robot_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Stop any active CV node and invoke ``/puppy_control/runActionGroup``."""
    await _ensure_cv_stopped(robot_id, ip, port, ros_version)
    profile = get_ros_profile(ros_version)
    action_file = normalize_action_group_name(name)
    return await send_rosbridge_command(
        ip=ip,
        port=port,
        op_payload={
            "op": "call_service",
            "service": "/puppy_control/runActionGroup",
            "type": profile["service_types"]["run_action"],
            "args": {"name": action_file, "wait": bool(wait)},
        },
        wait_response=False,
    )


async def set_servo(
    ip: str,
    port: int,
    servo_id: int,
    pulse: int,
    time_ms: int = 500,
    ros_version: str = "ros1",
    robot_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Stop any active CV node and publish a safety-clamped direct servo PWM pulse."""
    await _ensure_cv_stopped(robot_id, ip, port, ros_version)
    profile = get_ros_profile(ros_version)
    clamped = clamp_servo(servo_id, pulse, time_ms)
    return await send_rosbridge_command(
        ip=ip,
        port=port,
        op_payload={"op": "publish", "topic": SERVO_TOPIC, "msg": clamped},
        msg_type=profile["message_types"]["servo"],
    )


async def set_buzzer(
    ip: str,
    port: int,
    freq: int = 1900,
    on_time: float = 0.1,
    off_time: float = 0.1,
    repeat: int = 1,
    ros_version: str = "ros1",
) -> Dict[str, Any]:
    """Publish STM32 buzzer command using ROS 1 or ROS 2 message types."""
    profile = get_ros_profile(ros_version)
    msg = {
        "freq": max(100, min(10000, int(freq))),
        "on_time": round(max(0.01, min(5.0, float(on_time))), 3),
        "off_time": round(max(0.01, min(5.0, float(off_time))), 3),
        "repeat": max(1, min(20, int(repeat))),
    }
    return await send_rosbridge_command(
        ip=ip,
        port=port,
        op_payload={"op": "publish", "topic": BUZZER_TOPIC, "msg": msg},
        msg_type=profile["message_types"]["buzzer"],
    )


async def set_rgb(
    ip: str,
    port: int,
    data: List[Dict[str, int]],
    ros_version: str = "ros1",
) -> Dict[str, Any]:
    """Publish STM32 RGB LED states using ROS 1 or ROS 2 message types."""
    profile = get_ros_profile(ros_version)
    pixels = [
        {
            "id": int(p["id"]),
            "r": max(0, min(255, int(p["r"]))),
            "g": max(0, min(255, int(p["g"]))),
            "b": max(0, min(255, int(p["b"]))),
        }
        for p in data
    ]
    return await send_rosbridge_command(
        ip=ip,
        port=port,
        op_payload={"op": "publish", "topic": RGB_TOPIC, "msg": {"data": pixels}},
        msg_type=profile["message_types"]["rgb"],
    )


async def set_oled(
    ip: str,
    port: int,
    index: int = 1,
    text: str = "",
    ros_version: str = "ros1",
) -> Dict[str, Any]:
    """Publish STM32 OLED line text using ROS 1 or ROS 2 message types."""
    profile = get_ros_profile(ros_version)
    clean_text = "".join(ch for ch in text if 32 <= ord(ch) <= 126)[:32]
    msg = {"index": max(1, min(4, int(index))), "text": clean_text}
    return await send_rosbridge_command(
        ip=ip,
        port=port,
        op_payload={"op": "publish", "topic": OLED_TOPIC, "msg": msg},
        msg_type=profile["message_types"]["oled"],
    )


class DeadManWatchdog:
    """Server-side dead-man's switch that zeroes robot velocity after ``timeout_s`` of silence.

    Ensures a robot never keeps walking if browser heartbeats stop, network latency
    spikes, or the WebSocket client disconnects abruptly.
    """

    def __init__(
        self,
        send_zero_velocity: Callable[[], Awaitable[None]],
        timeout_s: float = 0.5,
        poll_interval_s: float = 0.05,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Configure the dead-man's switch watchdog.

        Args:
            send_zero_velocity: Async callback that sends ``{x:0, y:0, yaw_rate:0}`` to the robot.
            timeout_s: Maximum allowed silence after a non-zero motion command (default ``0.5s``).
            poll_interval_s: Watchdog check interval in seconds.
            clock: Monotonic clock function (injectable for deterministic unit testing).
        """
        self._send_zero_velocity = send_zero_velocity
        self.timeout_s = max(0.05, float(timeout_s))
        self.poll_interval_s = max(0.01, float(poll_interval_s))
        self._clock = clock
        self.is_moving: bool = False
        self.last_motion_ts: float = 0.0
        self.stops_triggered: int = 0

    def record_velocity(self, x: float, yaw_rate: float) -> None:
        """Record an outgoing velocity command to arm or disarm the watchdog.

        Args:
            x: Commanded forward/backward velocity.
            yaw_rate: Commanded yaw rate.
        """
        if abs(float(x)) > 1e-6 or abs(float(yaw_rate)) > 1e-6:
            self.is_moving = True
            self.last_motion_ts = self._clock()
        else:
            self.is_moving = False

    async def check_once(self) -> bool:
        """Evaluate watchdog expiry once and trigger zero velocity if overdue.

        Returns:
            ``True`` if a dead-man stop was triggered on this tick, else ``False``.
        """
        if not self.is_moving:
            return False
        if (self._clock() - self.last_motion_ts) > self.timeout_s:
            self.is_moving = False
            self.stops_triggered += 1
            await self._send_zero_velocity()
            return True
        return False

    async def force_stop(self) -> None:
        """Force an immediate zero-velocity command when disconnecting while moving."""
        if self.is_moving:
            self.is_moving = False
            self.stops_triggered += 1
            await self._send_zero_velocity()

    async def run(self, stop_event: asyncio.Event) -> None:
        """Run the periodic watchdog loop until ``stop_event`` is set."""
        while not stop_event.is_set():
            try:
                await self.check_once()
                await asyncio.sleep(self.poll_interval_s)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                sys.stderr.write(f"[rosbridge.watchdog] Error: {exc}\n")
                await asyncio.sleep(self.poll_interval_s)


def sanitize_outbound_rosbridge_message(
    payload: Dict[str, Any],
) -> Tuple[Dict[str, Any], Optional[Tuple[float, float]]]:
    """Clamp safety-critical ROSBridge publish messages before forwarding to PuppyPi.

    Args:
        payload: Parsed JSON frame sent by the browser client.

    Returns:
        Tuple ``(sanitized_payload, velocity_tuple_or_none)`` where
        ``velocity_tuple_or_none`` is ``(x, yaw_rate)`` for velocity topics.
    """
    if payload.get("op") != "publish":
        return payload, None
    topic = str(payload.get("topic") or "")
    msg = payload.get("msg")
    if not isinstance(msg, dict):
        return payload, None

    out = dict(payload)
    if topic in {VELOCITY_AUTOGAIT_TOPIC, VELOCITY_TOPIC, "/puppy_control/velocity_move"}:
        clamped = clamp_velocity(
            float(msg.get("x", 0.0)),
            float(msg.get("y", 0.0)),
            float(msg.get("yaw_rate", 0.0)),
        )
        out["msg"] = clamped
        return out, (clamped["x"], clamped["yaw_rate"])

    if topic in {"/cmd_vel", "/cmd_vel_nav"}:
        linear = msg.get("linear") if isinstance(msg.get("linear"), dict) else {}
        angular = msg.get("angular") if isinstance(msg.get("angular"), dict) else {}
        lin_x = _clamp(float(linear.get("x", 0.0)), -0.35, 0.35)
        ang_z = _clamp(float(angular.get("z", 0.0)), -0.89, 0.89)
        out["msg"] = {"linear": {"x": lin_x, "y": 0.0, "z": 0.0}, "angular": {"x": 0.0, "y": 0.0, "z": ang_z}}
        return out, (lin_x * 100.0, ang_z)

    if topic == POSE_TOPIC:
        out["msg"] = clamp_pose(
            roll=float(msg.get("roll", 0.0)),
            pitch=float(msg.get("pitch", 0.0)),
            yaw=float(msg.get("yaw", 0.0)),
            height=float(msg.get("height", -10.0)),
            x_shift=float(msg.get("x_shift", -0.5)),
            stance_x=float(msg.get("stance_x", 0.0)),
            stance_y=float(msg.get("stance_y", 0.0)),
            run_time=int(msg.get("run_time", 500)),
        )
        return out, None

    if topic == GAIT_TOPIC:
        out["msg"] = clamp_gait(
            overlap_time=float(msg.get("overlap_time", 0.2)),
            swing_time=float(msg.get("swing_time", 0.2)),
            clearance_time=float(msg.get("clearance_time", 0.0)),
            z_clearance=float(msg.get("z_clearance", 4.0)),
        )
        return out, None

    if topic == SERVO_TOPIC:
        out["msg"] = clamp_servo(
            servo_id=int(msg.get("id", 9)),
            pulse=int(msg.get("pulse", 1500)),
            time_ms=int(msg.get("time", 500)),
        )
        return out, None

    return out, None


async def proxy_rosbridge_websocket(
    client_ws: WebSocket,
    robot_ip: str,
    robot_port: int = 9090,
    runtime_state: Any = None,
    deadman_timeout_s: float = 0.5,
    on_battery_mv: Optional[Callable[[int], None]] = None,
) -> None:
    """Bidirectional ROSBridge WebSocket proxy with 0.5s dead-man's switch and ``/scan`` bridge.

    Args:
        client_ws: Accepted FastAPI client ``WebSocket``.
        robot_ip: Target PuppyPi IPv4 address.
        robot_port: Target ROSBridge TCP port (default ``9090``).
        runtime_state: Optional ``TwinScanRuntimeState`` for forwarding ``/scan`` LaserScans
            when ``runtime_state.source_mode == "hardware"``.
        deadman_timeout_s: Watchdog timeout in seconds before publishing zero velocity.
        on_battery_mv: Optional callback invoked whenever battery telemetry arrives.
    """
    uri = f"ws://{robot_ip}:{robot_port}"
    upstream: Optional[Any] = None
    last_exc: Optional[Exception] = None
    for attempt in range(1, 4):
        try:
            upstream = await websockets.connect(uri, open_timeout=5.0, close_timeout=2.0)
            break
        except Exception as exc:
            last_exc = exc
            sys.stderr.write(f"[rosbridge.proxy] Upstream connect to {uri} failed (attempt {attempt}/3): {exc}\n")
            if attempt < 3:
                await asyncio.sleep(0.3 * attempt)

    if upstream is None:
        await client_ws.send_json({"op": "proxy_error", "error": f"Unable to connect to {uri}: {last_exc}"})
        await client_ws.close(code=1011)
        return

    stop_event = asyncio.Event()
    send_lock = asyncio.Lock()

    async def _send_zero_vel() -> None:
        zero_frame = json.dumps(
            {"op": "publish", "topic": VELOCITY_AUTOGAIT_TOPIC, "msg": clamp_velocity(0.0, 0.0, 0.0)}
        )
        async with send_lock:
            try:
                await upstream.send(zero_frame)
            except Exception as exc:
                sys.stderr.write(f"[rosbridge.proxy] Failed to publish dead-man zero velocity: {exc}\n")
        try:
            await client_ws.send_json({"op": "watchdog_stop", "reason": "deadman_timeout"})
        except Exception:
            pass

    watchdog = DeadManWatchdog(send_zero_velocity=_send_zero_vel, timeout_s=deadman_timeout_s)

    async def _client_to_robot() -> None:
        try:
            while not stop_event.is_set():
                text = await client_ws.receive_text()
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    sanitized, vel = sanitize_outbound_rosbridge_message(payload)
                    if vel is not None:
                        watchdog.record_velocity(vel[0], vel[1])
                    async with send_lock:
                        await upstream.send(json.dumps(sanitized))
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            sys.stderr.write(f"[rosbridge.proxy] client->robot loop ended: {exc}\n")
        finally:
            stop_event.set()

    async def _robot_to_client() -> None:
        try:
            async for raw in upstream:
                if stop_event.is_set():
                    break
                text = raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    parsed = None

                if isinstance(parsed, dict) and parsed.get("op") == "publish":
                    topic = str(parsed.get("topic") or "")
                    msg = parsed.get("msg")
                    if topic == "/ros_robot_controller/battery" and isinstance(msg, dict) and "data" in msg:
                        if on_battery_mv is not None:
                            try:
                                on_battery_mv(int(msg["data"]))
                            except Exception:
                                pass
                    elif (
                        topic == "/scan"
                        and isinstance(msg, dict)
                        and runtime_state is not None
                        and getattr(runtime_state, "source_mode", "") == "hardware"
                    ):
                        pts = laserscan_to_lidar_points(msg)
                        if pts:
                            frame = runtime_state.process_scan(pts)
                            await runtime_state.broadcast_frame(frame)

                await client_ws.send_text(text)
        except Exception as exc:
            sys.stderr.write(f"[rosbridge.proxy] robot->client loop ended: {exc}\n")
        finally:
            stop_event.set()

    tasks = [
        asyncio.create_task(_client_to_robot()),
        asyncio.create_task(_robot_to_client()),
        asyncio.create_task(watchdog.run(stop_event)),
    ]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        stop_event.set()
        for t in tasks:
            if not t.done():
                t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await watchdog.force_stop()
        try:
            await upstream.close()
        except Exception:
            pass


async def fetch_robot_snapshot(
    ip: str,
    port: int = 8080,
    topic: str = "/usb_cam/image_raw",
    timeout: float = 5.0,
    retries: int = 2,
) -> bytes:
    """Fetch a single JPEG snapshot from PuppyPi ``web_video_server`` with crisp timeout & retry.

    Args:
        ip: Robot IPv4 address.
        port: ``web_video_server`` HTTP port (default ``8080``).
        topic: ROS image topic path (default ``"/usb_cam/image_raw"``).
        timeout: Per-attempt read timeout in seconds (default ``5.0``).
        retries: Maximum retry attempts on transient errors (default ``2``).

    Returns:
        Raw JPEG image bytes.

    Raises:
        ConnectionError: When the camera or CV topic cannot return a JPEG frame in time.
    """
    safe_topic = validate_video_topic(topic)
    # ROS web_video_server (async_web_server_cpp) rejects %2F-encoded slashes in query params.
    url = f"http://{ip}:{port}/snapshot?topic={safe_topic}"
    is_cv_topic = safe_topic.endswith("/image_result")
    http_timeout = httpx.Timeout(connect=3.0, read=min(timeout, 5.0), write=3.0, pool=3.0)
    last_exc: Optional[Exception] = None
    for attempt in range(1, max(1, retries) + 1):
        try:
            async with httpx.AsyncClient(timeout=http_timeout) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                if not resp.content:
                    raise ValueError("Empty snapshot response from robot camera")
                return resp.content
        except Exception as exc:
            last_exc = exc
            sys.stderr.write(
                f"[video.snapshot] Fetch {url} failed (attempt {attempt}/{retries}): {exc}\n"
            )
            if attempt < retries:
                await asyncio.sleep(min(0.3 * attempt, 0.8))
    if is_cv_topic:
        raise ConnectionError(
            f"CV topic {safe_topic} returned no frame (activate CV vision mode first or switch to raw camera): {last_exc}"
        )
    raise ConnectionError(f"Failed to fetch snapshot from {url}: {last_exc}")


async def stream_robot_video(
    ip: str,
    port: int = 8080,
    topic: str = "/usb_cam/image_raw",
    timeout: float = 6.0,
    is_disconnected: Optional[Callable[[], Coroutine[Any, Any, bool]]] = None,
) -> AsyncIterator[bytes]:
    """Stream raw MJPEG bytes from PuppyPi ``web_video_server`` for single-origin proxying.

    Uses bounded connect/read timeouts and checks client disconnect on every chunk so
    switching topics or hitting an inactive topic never leaves zombie connections open.

    Args:
        ip: Robot IPv4 address.
        port: ``web_video_server`` HTTP port (default ``8080``).
        topic: ROS image topic path (default ``"/usb_cam/image_raw"``).
        timeout: Read timeout per stream chunk in seconds (capped to ``<= 6.0``).
        is_disconnected: Optional async predicate (e.g. ``request.is_disconnected``).

    Yields:
        Raw multipart MJPEG byte chunks.
    """
    safe_topic = validate_video_topic(topic)
    url = f"http://{ip}:{port}/stream?topic={safe_topic}"
    stream_timeout = httpx.Timeout(connect=3.0, read=min(float(timeout), 6.0), write=5.0, pool=5.0)
    try:
        async with httpx.AsyncClient(timeout=stream_timeout) as client:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes(chunk_size=16384):
                    if is_disconnected is not None and await is_disconnected():
                        return
                    if chunk:
                        yield chunk
    except asyncio.CancelledError:
        return
    except Exception as exc:
        sys.stderr.write(f"[video.stream] Stream from {url} interrupted: {exc}\n")
        return
