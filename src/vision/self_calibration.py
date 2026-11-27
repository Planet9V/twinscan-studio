"""On-Demand Self-Calibration Sequence Engine for Multi-Camera Overwatch.

Supports two guided workflows that can be run any time a camera is added or
repositioned:
1. **PuppyPi Robot-Assisted Self-Calibration:** Captures 4+ paired
   ``(robot_world_xy, camera_pixel_uv)`` samples as PuppyPi sits at visible
   floor positions (either automatically detected via Overwatch or clicked by
   the user), then solves each camera's floor homography + 3D extrinsics
   automatically and persists them to PostgreSQL 18.
2. **1-Click AprilTag Auto-Calibrate All:** Runs ``solvePnP`` across every
   online camera simultaneously and returns per-camera status + guidance.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from src.vision.overwatch_triangulator import OverwatchCameraManager, sanitize_camera_id


@dataclass
class SelfCalibrationSample:
    """Single robot-world to camera-pixel correspondence captured during self-calibration."""

    sample_id: str
    world_xy: Tuple[float, float]
    observations: Dict[str, Tuple[float, float]]
    captured_at: float
    source: str = "manual_pose"


@dataclass
class SelfCalibrationSession:
    """In-memory state for an active on-demand multi-camera self-calibration run."""

    session_id: str
    target_cameras: List[str]
    started_at: float = field(default_factory=time.time)
    samples: List[SelfCalibrationSample] = field(default_factory=list)
    solved_results: Dict[str, Any] = field(default_factory=dict)

    def per_camera_counts(self) -> Dict[str, int]:
        """Count how many valid floor correspondences each camera has collected."""
        counts: Dict[str, int] = {cid: 0 for cid in self.target_cameras}
        for sample in self.samples:
            for cid in sample.observations:
                counts[cid] = counts.get(cid, 0) + 1
        return counts

    def to_dict(self) -> Dict[str, Any]:
        """Serialize session progress for the Calibration Wizard UI."""
        counts = self.per_camera_counts()
        ready_cameras = [cid for cid, cnt in counts.items() if cnt >= 4]
        return {
            "session_id": self.session_id,
            "target_cameras": list(self.target_cameras),
            "started_at": self.started_at,
            "sample_count": len(self.samples),
            "per_camera_counts": counts,
            "ready_cameras": ready_cameras,
            "samples": [
                {
                    "sample_id": s.sample_id,
                    "world_xy": [round(s.world_xy[0], 4), round(s.world_xy[1], 4)],
                    "observations": {
                        cid: [round(uv[0], 4), round(uv[1], 4)]
                        for cid, uv in s.observations.items()
                    },
                    "captured_at": s.captured_at,
                    "source": s.source,
                }
                for s in self.samples
            ],
            "solved_results": dict(self.solved_results),
        }


class SelfCalibrationCoordinator:
    """Thread-safe manager for on-demand Overwatch self-calibration sessions."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._session: Optional[SelfCalibrationSession] = None

    def start_session(
        self,
        *,
        overwatch_manager: OverwatchCameraManager,
        camera_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Start a fresh self-calibration session for selected or all active cameras.

        Args:
            overwatch_manager: Active ``OverwatchCameraManager``.
            camera_ids: Optional list of camera IDs (or ``["all"]`` / ``None`` for all slots).

        Returns:
            Serialized new ``SelfCalibrationSession``.
        """
        status = overwatch_manager.get_status()
        all_slots = list((status.get("cameras") or {}).keys())
        if not camera_ids or "all" in [c.lower() for c in camera_ids]:
            targets = all_slots or ["usb_4k"]
        else:
            targets = [sanitize_camera_id(c) for c in camera_ids]

        session = SelfCalibrationSession(
            session_id=f"selfcal_{uuid.uuid4().hex[:8]}",
            target_cameras=targets,
        )
        with self._lock:
            self._session = session
            return session.to_dict()

    def get_session(self) -> Optional[Dict[str, Any]]:
        """Return current active session state if one exists."""
        with self._lock:
            return self._session.to_dict() if self._session is not None else None

    def record_sample(
        self,
        *,
        overwatch_manager: OverwatchCameraManager,
        world_xy: Tuple[float, float],
        manual_observations: Optional[Dict[str, Tuple[float, float]]] = None,
        source: str = "robot_pose",
    ) -> Dict[str, Any]:
        """Record one floor correspondence across all cameras observing the robot.

        Args:
            overwatch_manager: Active ``OverwatchCameraManager`` for auto-detecting PuppyPi.
            world_xy: Ground-truth robot/marker floor position ``(x_m, y_m)`` in meters.
            manual_observations: Optional explicit ``{camera_id: (u_norm, v_norm)}`` clicks.
            source: Label describing how ``world_xy`` was obtained.

        Returns:
            Updated serialized session plus ``captured_cameras`` list.

        Raises:
            ValueError: If no session is active or zero camera observations were found.
        """
        wx, wy = float(world_xy[0]), float(world_xy[1])
        obs: Dict[str, Tuple[float, float]] = {}

        if manual_observations:
            for cid, uv in manual_observations.items():
                clean_cid = sanitize_camera_id(cid)
                u, v = float(uv[0]), float(uv[1])
                if 0.0 <= u <= 1.0 and 0.0 <= v <= 1.0:
                    obs[clean_cid] = (u, v)

        # Also attempt automatic visual lookup of PuppyPi / robot / AprilTag detections per target camera
        with self._lock:
            if self._session is None:
                raise ValueError("No active self-calibration session. Call /self-calibrate/start first.")
            targets = list(self._session.target_cameras)

        for cid in targets:
            if cid in obs:
                continue
            try:
                st = overwatch_manager.get_status(camera_id=cid)
                for det in st.get("detections") or []:
                    lbl = str(det.get("label") or "").lower()
                    kind = str(det.get("kind") or "").lower()
                    if any(tok in lbl for tok in ("puppy", "robot", "dog", "tag", "apriltag")) or kind == "apriltag":
                        bb = det.get("bbox_norm")
                        if isinstance(bb, (list, tuple)) and len(bb) == 4:
                            # Use bottom-center of bounding box (floor contact point!)
                            u = (float(bb[0]) + float(bb[2])) * 0.5
                            v = float(bb[3])
                            obs[cid] = (max(0.0, min(1.0, u)), max(0.0, min(1.0, v)))
                            break
            except Exception:
                continue

        if not obs:
            raise ValueError(
                "No robot/target observation detected in active cameras. "
                "Click where PuppyPi stands in the camera preview or ensure PuppyPi is visible."
            )

        sample = SelfCalibrationSample(
            sample_id=f"pt_{uuid.uuid4().hex[:6]}",
            world_xy=(wx, wy),
            observations=obs,
            captured_at=time.time(),
            source=source,
        )
        with self._lock:
            assert self._session is not None
            self._session.samples.append(sample)
            out = self._session.to_dict()
        out["captured_cameras"] = sorted(obs.keys())
        return out

    def solve_session(
        self,
        *,
        overwatch_manager: OverwatchCameraManager,
    ) -> Dict[str, Any]:
        """Solve 4-point floor homography & extrinsics for every camera with >= 4 samples.

        Args:
            overwatch_manager: Active ``OverwatchCameraManager`` to update & persist.

        Returns:
            Per-camera calibration results and updated session state.

        Raises:
            ValueError: If no active session exists or no camera has >= 4 samples.
        """
        with self._lock:
            if self._session is None:
                raise ValueError("No active self-calibration session.")
            samples = list(self._session.samples)
            targets = list(self._session.target_cameras)

        per_cam_pixels: Dict[str, List[Tuple[float, float]]] = {cid: [] for cid in targets}
        per_cam_world: Dict[str, List[Tuple[float, float]]] = {cid: [] for cid in targets}
        for s in samples:
            for cid, uv in s.observations.items():
                per_cam_pixels.setdefault(cid, []).append(uv)
                per_cam_world.setdefault(cid, []).append(s.world_xy)

        results: Dict[str, Any] = {}
        solved_any = False
        for cid, pix_pts in per_cam_pixels.items():
            world_pts = per_cam_world.get(cid, [])
            if len(pix_pts) < 4:
                results[cid] = {
                    "ok": False,
                    "samples": len(pix_pts),
                    "error": f"Need at least 4 floor points (have {len(pix_pts)}).",
                }
                continue
            try:
                res = overwatch_manager.calibrate_homography(
                    camera_id=cid,
                    pixel_points_norm=pix_pts,
                    world_points_xy=world_pts,
                )
                overwatch_manager.update_calibration(
                    {
                        "calibration_method": "robot_self_cal",
                        "reprojection_error_px": res.get("reprojection_error_px"),
                    },
                    camera_id=cid,
                )
                results[cid] = {
                    "ok": True,
                    "samples": len(pix_pts),
                    "reprojection_error_px": res["reprojection_error_px"],
                    "calibration": res["calibration"],
                }
                solved_any = True
            except Exception as exc:
                results[cid] = {"ok": False, "samples": len(pix_pts), "error": str(exc)}

        if not solved_any:
            raise ValueError("Could not solve any camera yet — capture at least 4 non-collinear floor points per camera.")

        with self._lock:
            assert self._session is not None
            self._session.solved_results = results
            session_dict = self._session.to_dict()

        return {
            "ok": True,
            "results": results,
            "session": session_dict,
            "geometry": overwatch_manager.get_geometry_snapshot(),
        }
