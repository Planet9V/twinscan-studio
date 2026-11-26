"""Expressive PuppyPi Mood Synchronization over ROSBridge (RGB LEDs + OLED Eyes + Optional Gesture).

Maps conversational turn states (``thinking``) and inferred assistant reply emotions
(``happy``, ``curious``, ``thinking``, ``alert``, ``sleepy``, ``neutral``) onto PuppyPi Pro's
STM32 RGB LEDs, 0.96-inch OLED display, and optional gentle body gesture with strict offline
graceful degradation (never blocks or raises when the robot is offline).
"""

from __future__ import annotations

import sys
from typing import Any, Dict, List, Optional, Tuple

from src.robot.rosbridge_proxy import run_action, set_oled, set_rgb

MOOD_PROFILES: Dict[str, Dict[str, Any]] = {
    "happy": {
        "rgb": (40, 220, 120),
        "oled_line1": "^   ^  OX",
        "oled_line2": "  \\___/  HAPPY",
        "gesture": "nod",
    },
    "curious": {
        "rgb": (56, 189, 248),
        "oled_line1": "o   O  OX",
        "oled_line2": "   ---   CURIOUS",
        "gesture": None,
    },
    "thinking": {
        "rgb": (168, 85, 247),
        "oled_line1": ". . .  OX",
        "oled_line2": "  THINKING...",
        "gesture": None,
    },
    "alert": {
        "rgb": (244, 63, 94),
        "oled_line1": "!   !  OX",
        "oled_line2": "  ALERT / STOP",
        "gesture": None,
    },
    "sleepy": {
        "rgb": (99, 102, 241),
        "oled_line1": "-   -  OX",
        "oled_line2": "  zzz... REST",
        "gesture": None,
    },
    "neutral": {
        "rgb": (224, 90, 16),
        "oled_line1": "o   o  OX",
        "oled_line2": "  READY",
        "gesture": None,
    },
}

_ALERT_KEYWORDS: Tuple[str, ...] = (
    "warning",
    "danger",
    "emergency",
    "e-stop",
    "estop",
    "blocked",
    "obstacle",
    "refused",
    "error",
    "failed",
    "caution",
    "low battery",
    "critical",
    "alert",
    "snag",
    "abort",
)

_THINKING_KEYWORDS: Tuple[str, ...] = (
    "thinking",
    "checking",
    "analyzing",
    "scanning",
    "searching",
    "calculating",
    "processing",
    "let me check",
    "let me look",
    "one moment",
    "hold on",
)

_SLEEPY_KEYWORDS: Tuple[str, ...] = (
    "sleep",
    "sleepy",
    "nap",
    "tired",
    "goodnight",
    "resting",
    "yawn",
    "bedtime",
    "shutting down",
    "futility",
    "depressing",
    "sigh",
)

_CURIOUS_KEYWORDS: Tuple[str, ...] = (
    "wonder",
    "curious",
    "interesting",
    "intriguing",
    "hmm",
    "explore",
    "discover",
    "overwatch",
    "spotted",
    "found",
    "investigat",
)

_HAPPY_KEYWORDS: Tuple[str, ...] = (
    "woof",
    "yay",
    "awesome",
    "happy",
    "great",
    "haha",
    "joke",
    "pun",
    "love",
    "glad",
    "welcome",
    "hello",
    "greetings",
    "fantastic",
    "remembered",
    "saved",
    "delighted",
)


def infer_reply_mood(text: str, personality_id: str = "dog") -> str:
    """Classify an assistant reply into one of 6 canonical PuppyPi expression moods.

    Args:
        text: Assistant reply text to inspect.
        personality_id: Active personality ID (e.g. ``"dog"``, ``"cat"``, ``"marvin"``).

    Returns:
        One of ``"happy"``, ``"curious"``, ``"thinking"``, ``"alert"``, ``"sleepy"``,
        or ``"neutral"``.
    """
    raw = str(text or "").strip()
    if not raw:
        return "neutral"
    low = raw.lower()
    pid = str(personality_id or "dog").strip().lower()

    if any(kw in low for kw in _ALERT_KEYWORDS):
        return "alert"
    if any(kw in low for kw in _THINKING_KEYWORDS):
        return "thinking"
    if any(kw in low for kw in _SLEEPY_KEYWORDS):
        return "sleepy"
    if "?" in raw or any(kw in low for kw in _CURIOUS_KEYWORDS):
        return "curious"
    if "!" in raw or any(kw in low for kw in _HAPPY_KEYWORDS):
        return "happy"
    if pid == "marvin" and any(kw in low for kw in ("ache", "tragic", "miserable", "exist")):
        return "sleepy"
    return "neutral"


async def apply_robot_mood_expression(
    ip: str,
    rosbridge_port: int,
    ros_version: str,
    mood: str,
    allow_gesture: bool = False,
    robot_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Synchronize PuppyPi RGB LEDs, OLED display lines, and optional gentle gesture for ``mood``.

    Every ROSBridge call is wrapped in ``try/except`` with ``stderr`` logging so an offline
    or unreachable robot degrades gracefully without blocking conversation or voice playback.

    Args:
        ip: Robot IPv4 address.
        rosbridge_port: ROSBridge WebSocket port (default ``9090``).
        ros_version: Active ROS mode (``"ros1"`` or ``"ros2"``).
        mood: Mood key from ``MOOD_PROFILES`` (falls back to ``"neutral"`` if unknown).
        allow_gesture: When ``True``, also trigger the profile's optional gentle gesture (e.g. ``nod``).
        robot_id: Optional robot UUID forwarded to ``run_action``.

    Returns:
        Summary dictionary ``{ok, mood, rgb, oled, gesture, errors}``.
    """
    mood_key = str(mood or "neutral").strip().lower()
    if mood_key not in MOOD_PROFILES:
        mood_key = "neutral"
    profile = MOOD_PROFILES[mood_key]
    rgb = tuple(int(c) for c in profile["rgb"])
    line1 = str(profile["oled_line1"])
    line2 = str(profile["oled_line2"])
    gesture_name: Optional[str] = profile.get("gesture") if allow_gesture else None

    if not str(ip or "").strip():
        return {
            "ok": False,
            "mood": mood_key,
            "rgb": list(rgb),
            "oled": [line1, line2],
            "gesture": None,
            "errors": ["Robot IP is empty; mood expression skipped."],
        }

    errors: List[str] = []
    rgb_ok = False
    oled_ok = False
    gesture_ran: Optional[str] = None

    try:
        await set_rgb(
            ip=ip,
            port=int(rosbridge_port),
            data=[
                {"id": 1, "r": rgb[0], "g": rgb[1], "b": rgb[2]},
                {"id": 2, "r": rgb[0], "g": rgb[1], "b": rgb[2]},
            ],
            ros_version=ros_version,
        )
        rgb_ok = True
    except Exception as exc:
        sys.stderr.write(f"[mood_sync.rgb] Failed applying '{mood_key}' RGB on {ip}: {exc}\n")
        errors.append(f"rgb: {exc}")

    try:
        await set_oled(ip=ip, port=int(rosbridge_port), index=1, text=line1, ros_version=ros_version)
        await set_oled(ip=ip, port=int(rosbridge_port), index=2, text=line2, ros_version=ros_version)
        oled_ok = True
    except Exception as exc:
        sys.stderr.write(f"[mood_sync.oled] Failed applying '{mood_key}' OLED on {ip}: {exc}\n")
        errors.append(f"oled: {exc}")

    if gesture_name:
        try:
            await run_action(
                ip=ip,
                port=int(rosbridge_port),
                name=gesture_name,
                wait=False,
                ros_version=ros_version,
                robot_id=robot_id,
            )
            gesture_ran = gesture_name
        except Exception as exc:
            sys.stderr.write(f"[mood_sync.gesture] Failed running '{gesture_name}' on {ip}: {exc}\n")
            errors.append(f"gesture: {exc}")

    return {
        "ok": rgb_ok or oled_ok,
        "mood": mood_key,
        "rgb": list(rgb),
        "oled": [line1, line2],
        "gesture": gesture_ran,
        "errors": errors,
    }
