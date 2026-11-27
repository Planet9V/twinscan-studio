"""Tip-Proof Physical Stability Guard for Hiwonder PuppyPi Pro.

Prevents autonomous tip-overs on carpet, rugs, and top-heavy LD19 LiDAR builds via:
- Surface-tuned conservative stance & gait presets (lower CG, longer foot overlap,
  higher toe clearance, gentle velocity & turn caps).
- Smooth velocity slew-rate limiting (eliminates sudden angular jerk).
- Real-time IMU roll/pitch tilt-guard auto-stop with low-CG crouch recovery.
- Overhead Overwatch camera visual slip/stall spotter.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Any, Dict, Optional, Tuple


@dataclass(frozen=True)
class StabilityPreset:
    """Validated stance, gait, and velocity limits for safe quadruped locomotion."""

    name: str
    label: str
    height_cm: float
    x_shift_cm: float
    overlap_time_s: float
    swing_time_s: float
    clearance_time_s: float
    z_clearance_cm: float
    max_vx_cms: float
    max_yaw_rads: float
    max_accel_vx_cms2: float
    max_accel_yaw_rads2: float
    max_tilt_deg: float

    def to_dict(self) -> Dict[str, Any]:
        """Serialize preset parameters to a JSON-safe dictionary."""
        return {
            "name": self.name,
            "label": self.label,
            "height_cm": self.height_cm,
            "x_shift_cm": self.x_shift_cm,
            "overlap_time_s": self.overlap_time_s,
            "swing_time_s": self.swing_time_s,
            "clearance_time_s": self.clearance_time_s,
            "z_clearance_cm": self.z_clearance_cm,
            "max_vx_cms": self.max_vx_cms,
            "max_yaw_rads": self.max_yaw_rads,
            "max_accel_vx_cms2": self.max_accel_vx_cms2,
            "max_accel_yaw_rads2": self.max_accel_yaw_rads2,
            "max_tilt_deg": self.max_tilt_deg,
        }


STABLE_GAIT_PRESETS: Dict[str, StabilityPreset] = {
    "carpet_lidar": StabilityPreset(
        name="carpet_lidar",
        label="Carpet + LiDAR Safe (Recommended)",
        height_cm=-9.0,
        x_shift_cm=-0.6,
        overlap_time_s=0.25,
        swing_time_s=0.25,
        clearance_time_s=0.05,
        z_clearance_cm=3.5,
        max_vx_cms=7.0,
        max_yaw_rads=0.24,
        max_accel_vx_cms2=12.0,
        max_accel_yaw_rads2=0.45,
        max_tilt_deg=22.0,
    ),
    "hardwood_lidar": StabilityPreset(
        name="hardwood_lidar",
        label="Hardwood + LiDAR Balanced",
        height_cm=-9.5,
        x_shift_cm=-0.5,
        overlap_time_s=0.20,
        swing_time_s=0.22,
        clearance_time_s=0.02,
        z_clearance_cm=2.8,
        max_vx_cms=9.0,
        max_yaw_rads=0.30,
        max_accel_vx_cms2=16.0,
        max_accel_yaw_rads2=0.55,
        max_tilt_deg=24.0,
    ),
    "ultra_safe": StabilityPreset(
        name="ultra_safe",
        label="Ultra-Safe Slow Crawl",
        height_cm=-8.5,
        x_shift_cm=-0.7,
        overlap_time_s=0.30,
        swing_time_s=0.28,
        clearance_time_s=0.06,
        z_clearance_cm=3.8,
        max_vx_cms=5.0,
        max_yaw_rads=0.18,
        max_accel_vx_cms2=9.0,
        max_accel_yaw_rads2=0.35,
        max_tilt_deg=18.0,
    ),
}

DEFAULT_STABILITY_PRESET = "carpet_lidar"


def get_stability_preset(name: Optional[str] = None) -> StabilityPreset:
    """Resolve a stability preset by name, defaulting to ``carpet_lidar``."""
    key = (name or DEFAULT_STABILITY_PRESET).strip().lower()
    return STABLE_GAIT_PRESETS.get(key, STABLE_GAIT_PRESETS[DEFAULT_STABILITY_PRESET])


class VelocitySlewLimiter:
    """Smoothly ramps forward velocity and yaw rate to prevent sudden tip-inducing jerks."""

    def __init__(self, preset: StabilityPreset) -> None:
        """Initialize slew limiter with acceleration & speed caps from ``preset``."""
        self.preset = preset
        self.vx_cms: float = 0.0
        self.yaw_rads: float = 0.0

    def reset(self) -> None:
        """Zero internal velocity state (e.g., after E-STOP or waypoint settle)."""
        self.vx_cms = 0.0
        self.yaw_rads = 0.0

    def step(self, target_vx_cms: float, target_yaw_rads: float, dt: float) -> Tuple[float, float]:
        """Clamp target velocities to preset caps and slew-limit over ``dt`` seconds.

        Args:
            target_vx_cms: Desired forward velocity in cm/s.
            target_yaw_rads: Desired yaw rate in rad/s.
            dt: Time delta since last tick in seconds.

        Returns:
            Smoothly ramped ``(vx_cms, yaw_rads)`` tuple.
        """
        dt_c = max(0.02, min(1.0, float(dt)))
        tgt_vx = max(-self.preset.max_vx_cms, min(self.preset.max_vx_cms, float(target_vx_cms)))
        tgt_yaw = max(-self.preset.max_yaw_rads, min(self.preset.max_yaw_rads, float(target_yaw_rads)))

        # Reduce forward speed while turning sharply to prevent lateral roll
        if abs(tgt_yaw) > 0.14:
            tgt_vx *= max(0.35, 1.0 - abs(tgt_yaw) * 1.8)

        max_dvx = self.preset.max_accel_vx_cms2 * dt_c
        max_dyaw = self.preset.max_accel_yaw_rads2 * dt_c

        dvx = max(-max_dvx, min(max_dvx, tgt_vx - self.vx_cms))
        dyaw = max(-max_dyaw, min(max_dyaw, tgt_yaw - self.yaw_rads))

        self.vx_cms = round(self.vx_cms + dvx, 3)
        self.yaw_rads = round(self.yaw_rads + dyaw, 4)
        return self.vx_cms, self.yaw_rads


def evaluate_imu_tilt_guard(
    roll_deg: Optional[float],
    pitch_deg: Optional[float],
    max_tilt_deg: float = 22.0,
) -> Dict[str, Any]:
    """Check whether live IMU roll or pitch exceeds the safe tip-over threshold.

    Args:
        roll_deg: Current chassis roll angle in degrees (``None`` if IMU unavailable).
        pitch_deg: Current chassis pitch angle in degrees (``None`` if IMU unavailable).
        max_tilt_deg: Maximum safe tilt magnitude in degrees before emergency halt.

    Returns:
        Dictionary ``{safe, roll_deg, pitch_deg, max_tilt_deg, recovery_action, reason}``.
    """
    r = float(roll_deg) if (roll_deg is not None and math.isfinite(float(roll_deg))) else 0.0
    p = float(pitch_deg) if (pitch_deg is not None and math.isfinite(float(pitch_deg))) else 0.0
    limit = max(10.0, min(40.0, float(max_tilt_deg)))

    if abs(r) > limit or abs(p) > limit:
        axis = "roll" if abs(r) >= abs(p) else "pitch"
        val = r if axis == "roll" else p
        return {
            "safe": False,
            "roll_deg": round(r, 2),
            "pitch_deg": round(p, 2),
            "max_tilt_deg": round(limit, 1),
            "recovery_action": "halt_and_crouch",
            "reason": f"IMU Tilt-Guard triggered ({axis}={val:+.1f}° exceeds ±{limit:.0f}° limit). Halted & crouched safely.",
        }

    return {
        "safe": True,
        "roll_deg": round(r, 2),
        "pitch_deg": round(p, 2),
        "max_tilt_deg": round(limit, 1),
        "recovery_action": "ok",
        "reason": "Chassis level within safe tilt envelope.",
    }


class VisualSlipDetector:
    """Detects carpet/cord foot-slip stalls using Overwatch overhead visual tracking."""

    def __init__(self, stall_window_sec: float = 4.0, min_progress_m: float = 0.04) -> None:
        """Initialize visual stall monitor."""
        self._window_sec = max(1.5, float(stall_window_sec))
        self._min_progress_m = max(0.01, float(min_progress_m))
        self._anchor_xy: Optional[Tuple[float, float]] = None
        self._anchor_ts: Optional[float] = None

    def reset(self) -> None:
        """Clear anchor when robot intentionally stops or reaches a waypoint."""
        self._anchor_xy = None
        self._anchor_ts = None

    def update(
        self,
        commanded_vx_cms: float,
        visual_pose: Optional[Dict[str, Any]],
        now_mono: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Evaluate whether PuppyPi is commanded to walk but visually stuck in place.

        Args:
            commanded_vx_cms: Forward speed currently being commanded in cm/s.
            visual_pose: Optional ``overwatch_manager.puppy_visual_pose`` dict.
            now_mono: Optional monotonic timestamp for deterministic testing.

        Returns:
            Dictionary ``{stalled, elapsed_sec, moved_m, reason}``.
        """
        ts = float(now_mono if now_mono is not None else time.monotonic())
        if abs(float(commanded_vx_cms)) < 2.0 or not visual_pose or not visual_pose.get("seen"):
            self.reset()
            return {"stalled": False, "elapsed_sec": 0.0, "moved_m": 0.0, "reason": "idle_or_untracked"}

        vx = float(visual_pose.get("x", 0.0))
        vy = float(visual_pose.get("y", 0.0))
        if self._anchor_xy is None or self._anchor_ts is None:
            self._anchor_xy = (vx, vy)
            self._anchor_ts = ts
            return {"stalled": False, "elapsed_sec": 0.0, "moved_m": 0.0, "reason": "tracking_started"}

        moved_m = math.hypot(vx - self._anchor_xy[0], vy - self._anchor_xy[1])
        elapsed = ts - self._anchor_ts
        if moved_m >= self._min_progress_m:
            # Making healthy forward progress -> advance anchor
            self._anchor_xy = (vx, vy)
            self._anchor_ts = ts
            return {"stalled": False, "elapsed_sec": round(elapsed, 2), "moved_m": round(moved_m, 3), "reason": "moving"}

        if elapsed >= self._window_sec:
            return {
                "stalled": True,
                "elapsed_sec": round(elapsed, 2),
                "moved_m": round(moved_m, 3),
                "reason": (
                    f"Overwatch Spotter detected slip/stall: moved only {moved_m * 100:.1f} cm "
                    f"in {elapsed:.1f} s while walking. Paused to prevent tip-over."
                ),
            }

        return {"stalled": False, "elapsed_sec": round(elapsed, 2), "moved_m": round(moved_m, 3), "reason": "monitoring"}
