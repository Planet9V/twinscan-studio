"""Autonomous Sentry Guard Mode (Add-On C): Watches LiDAR Motion, Unknown Faces, and Animals with Evidence & Alerts.

When armed for a robot, continuously monitors:
- LiDAR moving objects from ``TwinScanRuntimeState.latest_moving_objects``
- AI Vision detections (Unknown faces and animals) from ``RobotAiVisionEngine``

On trigger (respecting ``cooldown_sec``), captures an evidence JPEG into PostgreSQL 18
``stored_files``, flashes the PuppyPi STM32 RGB LEDs, speaks a personality-flavored challenge
via Offline Piper Neural TTS, and records an immutable row in ``sentry_events``.
"""

from __future__ import annotations

import asyncio
import sys
import time
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Dict, List, Optional, Sequence

from src.robot.ros_profiles import get_ros_profile
from src.robot.rosbridge_proxy import fetch_robot_snapshot, set_rgb
from src.robot.voice_manager import speak_text_on_robot

DEFAULT_SENTRY_CONFIG: Dict[str, Any] = {
    "armed": False,
    "watch_motion": True,
    "watch_unknown_faces": True,
    "watch_animals": True,
    "speak_challenge": True,
    "flash_rgb": True,
    "cooldown_sec": 25,
    "custom_challenge": "",
}


def _build_personality_challenge(
    trigger_type: str,
    label: str,
    personality_id: str,
    assistant_name: str,
    custom_challenge: str = "",
) -> str:
    """Build a spoken security challenge in the robot's active personality voice."""
    if custom_challenge and custom_challenge.strip():
        return custom_challenge.strip()[:240]
    pid = str(personality_id or "dog").lower()
    if trigger_type == "animal":
        by_p = {
            "dog": f"Woof! Hey there {label}! {assistant_name} sees you patrolling the room!",
            "cat": f"A {label} has entered my territory. Bold move.",
            "marvin": f"Great, a {label}. As if my circuits did not already have enough to worry about.",
            "dad_joke_nerd": f"Alert! A {label} detected. That is paws-itively adorable security news.",
            "lab_assistant": f"Sentry notice: {label} detected in the monitored zone.",
        }
        return by_p.get(pid, by_p["lab_assistant"])
    if trigger_type == "unknown_face":
        by_p = {
            "dog": f"Woof! {assistant_name} here — I do not recognize you yet! Please introduce yourself!",
            "cat": f"Excuse me, unfamiliar human. State your business in {assistant_name}'s room.",
            "marvin": f"An unrecognized human. Not that anyone ever bothers enrolling themselves for me.",
            "dad_joke_nerd": f"Halt! Unknown face detected. You are currently in incognito mode!",
            "lab_assistant": f"Security alert: unrecognized person detected. Please identify yourself.",
        }
        return by_p.get(pid, by_p["lab_assistant"])
    by_p = {
        "dog": f"Woof! Motion detected in the room! {assistant_name} is on guard duty!",
        "cat": f"I saw something move over there. You are officially being watched.",
        "marvin": f"Motion detected. Probably something terribly uninteresting, yet I am forced to log it.",
        "dad_joke_nerd": f"Motion alert! Something is on the move, and my LiDAR never misses a beat!",
        "lab_assistant": f"Sentry alert: moving object detected ({label}). Logging snapshot.",
    }
    return by_p.get(pid, by_p["lab_assistant"])


class RobotSentryManager:
    """Manages per-robot Sentry Guard Mode configuration, trigger evaluation, and background monitoring."""

    def __init__(self) -> None:
        """Initialize per-robot sentry configs, cooldown clocks, and background watcher tasks."""
        self._configs: Dict[str, Dict[str, Any]] = {}
        self._tasks: Dict[str, asyncio.Task[None]] = {}
        self._last_alert_ts: Dict[str, float] = {}
        self._last_alert_iso: Dict[str, Optional[str]] = {}
        self._last_trigger: Dict[str, Optional[str]] = {}

    def get_config(self, robot_id: str) -> Dict[str, Any]:
        """Return the active sentry configuration dictionary for ``robot_id``."""
        if robot_id not in self._configs:
            self._configs[robot_id] = dict(DEFAULT_SENTRY_CONFIG)
        return dict(self._configs[robot_id])

    def update_config(self, robot_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Merge configuration updates for ``robot_id``."""
        cfg = self.get_config(robot_id)
        for bkey in ("watch_motion", "watch_unknown_faces", "watch_animals", "speak_challenge", "flash_rgb"):
            if bkey in updates and updates[bkey] is not None:
                cfg[bkey] = bool(updates[bkey])
        if "cooldown_sec" in updates and updates["cooldown_sec"] is not None:
            cfg["cooldown_sec"] = max(5, min(300, int(updates["cooldown_sec"])))
        if "custom_challenge" in updates and updates["custom_challenge"] is not None:
            cfg["custom_challenge"] = str(updates["custom_challenge"]).strip()[:240]
        self._configs[robot_id] = cfg
        return dict(cfg)

    def get_status(self, robot_id: str, event_count: int = 0) -> Dict[str, Any]:
        """Return full ``SentryStatus`` combining config, armed state, and alert counters."""
        cfg = self.get_config(robot_id)
        task = self._tasks.get(robot_id)
        if task is not None and task.done():
            cfg["armed"] = False
            self._configs[robot_id]["armed"] = False
        return {
            **cfg,
            "robot_id": robot_id,
            "event_count": int(event_count),
            "last_alert_at": self._last_alert_iso.get(robot_id),
            "last_trigger": self._last_trigger.get(robot_id),
        }

    def evaluate_triggers(
        self,
        robot_id: str,
        moving_objects: Sequence[Dict[str, Any]],
        vision_detections: Sequence[Dict[str, Any]],
        now_s: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """Evaluate LiDAR moving tracks and AI vision detections against armed sentry rules.

        Args:
            robot_id: Target robot UUID.
            moving_objects: Current list of Kalman tracks from ``MovingObjectTracker``.
            vision_detections: Current list of detections from ``RobotAiVisionEngine``.
            now_s: Optional monotonic timestamp for deterministic cooldown testing.

        Returns:
            Trigger dictionary ``{trigger_type, label, severity, detail}`` or ``None``.
        """
        cfg = self.get_config(robot_id)
        if not cfg.get("armed"):
            return None
        now = float(now_s if now_s is not None else time.monotonic())
        cooldown = float(cfg.get("cooldown_sec", 25))
        last_ts = self._last_alert_ts.get(robot_id, -1e9)
        if (now - last_ts) < cooldown:
            return None

        if cfg.get("watch_unknown_faces"):
            for det in vision_detections or []:
                if det.get("kind") == "face" and not det.get("person_id"):
                    return {
                        "trigger_type": "unknown_face",
                        "label": str(det.get("label") or "Unknown Face"),
                        "severity": "high",
                        "detail": f"Unrecognized face detected ({int(float(det.get('confidence', 0.8)) * 100)}% conf).",
                    }

        if cfg.get("watch_animals"):
            for det in vision_detections or []:
                if det.get("kind") == "animal" or det.get("is_animal"):
                    lbl = str(det.get("label") or "animal")
                    return {
                        "trigger_type": "animal",
                        "label": lbl,
                        "severity": "medium",
                        "detail": f"Animal detected on camera: {lbl} ({int(float(det.get('confidence', 0.5)) * 100)}%).",
                    }

        if cfg.get("watch_motion"):
            for trk in moving_objects or []:
                if trk.get("is_moving") and float(trk.get("speed_mps", 0.0)) >= 0.12:
                    spd = float(trk.get("speed_mps", 0.0))
                    tid = trk.get("track_id", 0)
                    return {
                        "trigger_type": "lidar_motion",
                        "label": f"Moving Track #{tid}",
                        "severity": "high" if spd >= 0.35 else "medium",
                        "detail": (
                            f"LiDAR moving object Track #{tid} at ({trk.get('x', 0.0):.2f}m, "
                            f"{trk.get('y', 0.0):.2f}m), speed {spd:.2f} m/s."
                        ),
                    }

        return None

    async def handle_trigger(
        self,
        robot_id: str,
        trigger: Dict[str, Any],
        ai_store: Any,
        repo: Any,
        robot: Dict[str, Any],
        ssh_pw: str,
        ros_version: str,
        space_id: Optional[str] = None,
        now_s: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Execute alert actions for a matched trigger: snapshot -> RGB flash -> voice challenge -> DB log."""
        cfg = self.get_config(robot_id)
        now = float(now_s if now_s is not None else time.monotonic())
        self._last_alert_ts[robot_id] = now
        self._last_alert_iso[robot_id] = datetime.now(timezone.utc).isoformat()
        self._last_trigger[robot_id] = f"{trigger['trigger_type']}:{trigger['label']}"

        ip = robot["ip_address"]
        video_port = int(robot.get("video_port") or 8080)
        ros_port = int(robot.get("rosbridge_port") or 9090)

        snapshot_file_id: Optional[str] = None
        topic = get_ros_profile(ros_version)["camera_topic"]
        try:
            jpg = await fetch_robot_snapshot(ip=ip, port=video_port, topic=topic, timeout=3.0, retries=1)
            stored = repo.store_file(
                filename=f"sentry-{robot_id[:8]}-{int(time.time())}.jpg",
                content_type="image/jpeg",
                data=jpg,
                category="sentry_evidence",
                space_id=space_id or None,
                metadata={"robot_id": robot_id, "trigger": trigger["trigger_type"], "label": trigger["label"]},
            )
            snapshot_file_id = stored["id"]
        except Exception as exc:
            sys.stderr.write(f"[sentry.snapshot] Evidence snap skipped for {robot_id}: {exc}\n")

        if cfg.get("flash_rgb"):
            try:
                await set_rgb(
                    ip=ip,
                    port=ros_port,
                    data=[{"id": 1, "r": 255, "g": 45, "b": 10}, {"id": 2, "r": 255, "g": 45, "b": 10}],
                    ros_version=ros_version,
                )
            except Exception as exc:
                sys.stderr.write(f"[sentry.rgb] RGB flash failed on {ip}: {exc}\n")

        spoken_alert: Optional[str] = None
        if cfg.get("speak_challenge") and ssh_pw:
            vcfg = ai_store.get_voice_config(robot_id)
            challenge = _build_personality_challenge(
                trigger_type=trigger["trigger_type"],
                label=trigger["label"],
                personality_id=str(vcfg.get("personality_id") or "dog"),
                assistant_name=str(vcfg.get("assistant_name") or "OX"),
                custom_challenge=str(cfg.get("custom_challenge") or ""),
            )
            try:
                await speak_text_on_robot(
                    ip=ip,
                    user=robot["ssh_user"],
                    password=ssh_pw,
                    text=challenge,
                    engine=str(vcfg.get("default_engine") or "piper_tts"),
                    voice=vcfg.get("default_voice"),
                    anti_clip=bool(vcfg.get("anti_clip", True)),
                )
                spoken_alert = challenge
            except Exception as exc:
                sys.stderr.write(f"[sentry.tts] Voice challenge failed on {ip}: {exc}\n")

        return ai_store.record_sentry_event(
            robot_id,
            {
                "trigger_type": trigger["trigger_type"],
                "label": trigger["label"],
                "severity": trigger.get("severity", "medium"),
                "detail": trigger.get("detail", ""),
                "snapshot_file_id": snapshot_file_id,
                "spoken_alert": spoken_alert,
            },
        )

    async def arm(
        self,
        robot_id: str,
        get_moving_objects: Callable[[], Sequence[Dict[str, Any]]],
        get_vision_detections: Callable[[], Sequence[Dict[str, Any]]],
        on_trigger: Callable[[Dict[str, Any]], Coroutine[Any, Any, Dict[str, Any]]],
        event_count_fn: Callable[[], int],
    ) -> Dict[str, Any]:
        """Arm Sentry Guard Mode and launch the background monitoring task for ``robot_id``."""
        await self.disarm(robot_id, event_count=event_count_fn())
        cfg = self.get_config(robot_id)
        cfg["armed"] = True
        self._configs[robot_id] = cfg

        async def _watch_loop() -> None:
            while True:
                try:
                    trig = self.evaluate_triggers(
                        robot_id=robot_id,
                        moving_objects=get_moving_objects(),
                        vision_detections=get_vision_detections(),
                    )
                    if trig is not None:
                        await on_trigger(trig)
                    await asyncio.sleep(0.6)
                except asyncio.CancelledError:
                    return
                except Exception as exc:
                    sys.stderr.write(f"[sentry.loop] Watcher error for {robot_id}: {exc}\n")
                    await asyncio.sleep(1.5)

        self._tasks[robot_id] = asyncio.create_task(_watch_loop())
        return self.get_status(robot_id, event_count=event_count_fn())

    async def disarm(self, robot_id: str, event_count: int = 0) -> Dict[str, Any]:
        """Disarm Sentry Guard Mode and stop the background watcher task for ``robot_id``."""
        cfg = self.get_config(robot_id)
        cfg["armed"] = False
        self._configs[robot_id] = cfg
        task = self._tasks.pop(robot_id, None)
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        return self.get_status(robot_id, event_count=event_count)

    async def stop_all(self) -> None:
        """Disarm all active sentry watchers on application shutdown."""
        for rid in list(self._tasks.keys()):
            await self.disarm(rid)
