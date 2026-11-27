"""4K/1080p USB & MacBook Overwatch Vision & Dual-Ray 3D Triangulation Engine.

Provides pure-NumPy pinhole ray projection, ground-plane intersection, closed-form
3D dual-ray least-squares triangulation, and multi-camera HUD frame management
(``usb_4k`` external 4K webcam + ``macbook_cam`` built-in MacBook Pro Camera)
using only already-installed ``numpy`` and ``opencv-python-headless`` (``cv2``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import re
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

VALID_OVERWATCH_MODES = frozenset({"yolo", "face", "apriltag", "triangulate"})
DEFAULT_CAMERA_ID = "usb_4k"
_CAMERA_ID_RE = re.compile(r"^[a-z0-9_-]{1,32}$")
_ONLINE_TTL_SEC = 5.0

KNOWN_CAMERA_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "usb_4k": {
        "camera_name": "4k Webcam",
        "x_m": 0.0,
        "y_m": -2.2,
        "z_m": 1.45,
        "yaw_deg": 90.0,
        "pitch_deg": -22.0,
        "hfov_deg": 78.0,
        "vfov_deg": 48.0,
        "mode": "triangulate",
    },
    "macbook_cam": {
        "camera_name": "MacBook Pro Camera",
        "x_m": -0.35,
        "y_m": -2.1,
        "z_m": 1.15,
        "yaw_deg": 85.0,
        "pitch_deg": -15.0,
        "hfov_deg": 72.0,
        "vfov_deg": 44.0,
        "mode": "triangulate",
    },
}


def sanitize_camera_id(camera_id: Optional[str]) -> str:
    """Validate and normalize an overwatch camera slot identifier.

    Args:
        camera_id: Requested camera identifier (e.g. ``usb_4k``, ``macbook_cam``).

    Returns:
        Normalized lowercase identifier, defaulting to ``usb_4k`` when omitted.

    Raises:
        ValueError: If ``camera_id`` contains unsupported characters.
    """
    if camera_id is None or not str(camera_id).strip():
        return DEFAULT_CAMERA_ID
    cleaned = str(camera_id).strip().lower()
    if not _CAMERA_ID_RE.match(cleaned):
        raise ValueError(f"Invalid camera_id {camera_id!r}: must match [a-z0-9_-]{{1,32}}")
    return cleaned


@dataclass
class OverwatchCalibration:
    """Extrinsic & intrinsic pinhole calibration for a fixed overwatch camera.

    World coordinate convention (matching TwinScan 2D LiDAR radar):
    - ``+X`` right (meters), ``+Y`` forward (meters), ``+Z`` up (meters).
    - ``yaw_deg``: camera azimuth in world XY plane (``0° = +X``, ``90° = +Y``).
    - ``pitch_deg``: camera elevation (negative pitches downward toward the floor).
    - ``hfov_deg`` / ``vfov_deg``: full horizontal & vertical fields of view in degrees.
    """

    x_m: float = 0.0
    y_m: float = -2.2
    z_m: float = 1.45
    yaw_deg: float = 90.0
    pitch_deg: float = -22.0
    hfov_deg: float = 78.0
    vfov_deg: float = 48.0
    mode: str = "triangulate"
    homography_3x3: Optional[List[List[float]]] = None
    space_id: Optional[str] = None
    calibration_method: str = "default"
    calibrated_at: Optional[float] = None
    reprojection_error_px: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize calibration parameters to a JSON-safe dictionary."""
        return {
            "x_m": round(float(self.x_m), 4),
            "y_m": round(float(self.y_m), 4),
            "z_m": round(float(self.z_m), 4),
            "yaw_deg": round(float(self.yaw_deg), 2),
            "pitch_deg": round(float(self.pitch_deg), 2),
            "hfov_deg": round(float(self.hfov_deg), 2),
            "vfov_deg": round(float(self.vfov_deg), 2),
            "mode": str(self.mode),
            "has_homography": self.homography_3x3 is not None,
            "space_id": self.space_id,
            "calibration_method": str(self.calibration_method or "default"),
            "calibrated": self.calibration_method != "default" or self.homography_3x3 is not None,
            "calibrated_at": self.calibrated_at,
            "reprojection_error_px": (
                round(float(self.reprojection_error_px), 2)
                if self.reprojection_error_px is not None
                else None
            ),
        }


def pixel_to_world_ray(
    u: float,
    v: float,
    width: int,
    height: int,
    cal: OverwatchCalibration,
) -> Tuple[np.ndarray, np.ndarray]:
    """Project an image pixel ``(u, v)`` into a 3D world-frame ray ``(origin, unit_dir)``.

    Args:
        u: Horizontal pixel coordinate (``0`` = left edge, ``width`` = right edge).
        v: Vertical pixel coordinate (``0`` = top edge, ``height`` = bottom edge).
        width: Image width in pixels.
        height: Image height in pixels.
        cal: Overwatch camera extrinsic/intrinsic calibration.

    Returns:
        Tuple ``(origin_3d, unit_dir_3d)`` of float64 NumPy vectors in world meters.
    """
    w = max(1.0, float(width))
    h = max(1.0, float(height))
    nx = ((float(u) / w) - 0.5) * 2.0  # [-1, +1], positive right
    ny = (0.5 - (float(v) / h)) * 2.0  # [-1, +1], positive up

    yaw = math.radians(float(cal.yaw_deg))
    pitch = math.radians(float(cal.pitch_deg))
    tan_h = math.tan(math.radians(max(5.0, min(170.0, float(cal.hfov_deg)))) / 2.0)
    tan_v = math.tan(math.radians(max(5.0, min(170.0, float(cal.vfov_deg)))) / 2.0)

    forward = np.array(
        [
            math.cos(pitch) * math.cos(yaw),
            math.cos(pitch) * math.sin(yaw),
            math.sin(pitch),
        ],
        dtype=np.float64,
    )
    world_up = np.array([0.0, 0.0, 1.0], dtype=np.float64)
    right = np.cross(forward, world_up)
    r_norm = float(np.linalg.norm(right))
    if r_norm < 1e-8:
        right = np.array([math.sin(yaw), -math.cos(yaw), 0.0], dtype=np.float64)
        r_norm = float(np.linalg.norm(right))
    right = right / max(r_norm, 1e-12)

    cam_up = np.cross(right, forward)
    u_norm = float(np.linalg.norm(cam_up))
    cam_up = cam_up / max(u_norm, 1e-12)

    ray = forward + (nx * tan_h) * right + (ny * tan_v) * cam_up
    ray_norm = float(np.linalg.norm(ray))
    unit_dir = ray / max(ray_norm, 1e-12)
    origin = np.array([float(cal.x_m), float(cal.y_m), float(cal.z_m)], dtype=np.float64)
    return origin, unit_dir


def intersect_ray_ground_plane(
    origin: Sequence[float],
    direction: Sequence[float],
    z_plane: float = 0.0,
) -> Optional[Dict[str, float]]:
    """Intersect a 3D ray with a horizontal plane ``z = z_plane``.

    Args:
        origin: Ray origin ``[x, y, z]`` in meters.
        direction: Ray direction ``[dx, dy, dz]`` (normalized automatically).
        z_plane: Plane height in meters (default ``0.0`` floor plane).

    Returns:
        Dictionary ``{x, y, z, distance_m}`` if the ray intersects in front of the
        origin (``t > 0``), otherwise ``None``.
    """
    o = np.asarray(origin, dtype=np.float64)
    d = np.asarray(direction, dtype=np.float64)
    d_norm = float(np.linalg.norm(d))
    if d_norm < 1e-12:
        return None
    d = d / d_norm
    if abs(float(d[2])) < 1e-6:
        return None
    t = (float(z_plane) - float(o[2])) / float(d[2])
    if t <= 0.0 or not math.isfinite(t):
        return None
    hit = o + t * d
    return {
        "x": round(float(hit[0]), 4),
        "y": round(float(hit[1]), 4),
        "z": round(float(hit[2]), 4),
        "distance_m": round(float(t), 4),
    }


def triangulate_dual_rays(
    origin1: Sequence[float],
    dir1: Sequence[float],
    origin2: Sequence[float],
    dir2: Sequence[float],
) -> Dict[str, Any]:
    """Compute the closed-form 3D least-squares closest-point midpoint between two rays.

    Args:
        origin1: First ray origin ``[x, y, z]``.
        dir1: First ray direction vector.
        origin2: Second ray origin ``[x, y, z]``.
        dir2: Second ray direction vector.

    Returns:
        Dictionary ``{x, y, z, error_m, confidence}`` where ``error_m`` is the
        Euclidean skew distance between the closest points on the two rays.
    """
    o1 = np.asarray(origin1, dtype=np.float64)
    o2 = np.asarray(origin2, dtype=np.float64)
    d1 = np.asarray(dir1, dtype=np.float64)
    d2 = np.asarray(dir2, dtype=np.float64)

    n1 = float(np.linalg.norm(d1))
    n2 = float(np.linalg.norm(d2))
    if n1 < 1e-12 or n2 < 1e-12:
        mid = 0.5 * (o1 + o2)
        return {
            "x": round(float(mid[0]), 4),
            "y": round(float(mid[1]), 4),
            "z": round(float(mid[2]), 4),
            "error_m": round(float(np.linalg.norm(o1 - o2)), 4),
            "confidence": 0.05,
        }
    d1 = d1 / n1
    d2 = d2 / n2

    w0 = o1 - o2
    b = float(np.dot(d1, d2))
    d_dot = float(np.dot(d1, w0))
    e_dot = float(np.dot(d2, w0))
    denom = 1.0 - b * b

    if denom < 1e-8:
        t = max(0.0, -d_dot)
        s = 0.0
        p1 = o1 + t * d1
        p2 = o2 + s * d2
        mid = 0.5 * (p1 + p2)
        err = float(np.linalg.norm(p1 - p2))
        return {
            "x": round(float(mid[0]), 4),
            "y": round(float(mid[1]), 4),
            "z": round(float(mid[2]), 4),
            "error_m": round(err, 4),
            "confidence": 0.1,
        }

    t = max(0.0, (b * e_dot - d_dot) / denom)
    s = max(0.0, (e_dot - b * d_dot) / denom)
    p1 = o1 + t * d1
    p2 = o2 + s * d2
    mid = 0.5 * (p1 + p2)
    err = float(np.linalg.norm(p1 - p2))
    conf = round(max(0.05, min(1.0, 1.0 / (1.0 + err * 2.5))), 3)
    return {
        "x": round(float(mid[0]), 4),
        "y": round(float(mid[1]), 4),
        "z": round(float(mid[2]), 4),
        "error_m": round(err, 4),
        "confidence": conf,
    }


@dataclass
class _CameraSlot:
    """Mutable per-camera runtime buffer for an overwatch feed."""

    camera_id: str
    camera_name: str
    calibration: OverwatchCalibration
    width: int = 0
    height: int = 0
    fps: float = 0.0
    last_frame_mono: float = 0.0
    last_ai_mono: float = 0.0
    raw_jpeg: Optional[bytes] = None
    annotated_jpeg: Optional[bytes] = None
    detections: List[Dict[str, Any]] = field(default_factory=list)
    triangulated_targets: List[Dict[str, Any]] = field(default_factory=list)
    puppy_visual_pose: Optional[Dict[str, Any]] = None
    rays_by_label: Dict[str, Tuple[np.ndarray, np.ndarray, float]] = field(default_factory=dict)


class OverwatchCameraManager:
    """Thread-safe multi-camera 4K/1080p Overwatch vision & triangulation manager.

    Supports simultaneous ingestion from ``usb_4k`` (external 4K USB webcam),
    ``macbook_cam`` (built-in MacBook Pro Camera), and arbitrary custom camera IDs,
    while preserving full single-camera backward compatibility on ``usb_4k``.
    """

    def __init__(self) -> None:
        """Initialize default camera slots and OpenCV AprilTag detector."""
        self._lock = threading.RLock()
        self._ai_lock = threading.Lock()
        self._slots: Dict[str, _CameraSlot] = {}
        for cid, cfg in KNOWN_CAMERA_DEFAULTS.items():
            self._slots[cid] = _CameraSlot(
                camera_id=cid,
                camera_name=str(cfg["camera_name"]),
                calibration=OverwatchCalibration(
                    x_m=float(cfg["x_m"]),
                    y_m=float(cfg["y_m"]),
                    z_m=float(cfg["z_m"]),
                    yaw_deg=float(cfg["yaw_deg"]),
                    pitch_deg=float(cfg["pitch_deg"]),
                    hfov_deg=float(cfg["hfov_deg"]),
                    vfov_deg=float(cfg["vfov_deg"]),
                    mode=str(cfg["mode"]),
                ),
            )
        self._aruco_detector: Any = None
        try:
            aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
            self._aruco_detector = cv2.aruco.ArucoDetector(aruco_dict, cv2.aruco.DetectorParameters())
        except Exception:
            self._aruco_detector = None
        from src.vision.overwatch_tracker import CrossViewTargetTracker

        self._tracker = CrossViewTargetTracker()
        self._repo: Any = None

    def attach_repository(self, repo: Any) -> None:
        """Attach a PostgreSQL/in-memory repository and restore persisted camera calibrations."""
        self._repo = repo
        if repo is None:
            return
        try:
            import json as _json

            raw = repo.get_settings_raw() or {}
            blob = str(raw.get("overwatch_calibrations_json") or "").strip()
            if not blob:
                return
            parsed = _json.loads(blob)
            if not isinstance(parsed, dict):
                return
            with self._lock:
                for cid, cfg in parsed.items():
                    if not isinstance(cfg, dict):
                        continue
                    slot = self._get_or_create_slot(cid)
                    cal = slot.calibration
                    for fld in ("x_m", "y_m", "z_m", "yaw_deg", "pitch_deg", "hfov_deg", "vfov_deg"):
                        if fld in cfg and cfg[fld] is not None:
                            setattr(cal, fld, float(cfg[fld]))
                    if cfg.get("mode") in VALID_OVERWATCH_MODES:
                        cal.mode = str(cfg["mode"])
                    h_mat = cfg.get("homography_3x3")
                    if isinstance(h_mat, list) and len(h_mat) == 3:
                        cal.homography_3x3 = h_mat
                    if "space_id" in cfg:
                        cal.space_id = str(cfg["space_id"]) if cfg["space_id"] else None
                    if cfg.get("calibration_method"):
                        cal.calibration_method = str(cfg["calibration_method"])
                    if cfg.get("calibrated_at") is not None:
                        cal.calibrated_at = float(cfg["calibrated_at"])
                    if cfg.get("reprojection_error_px") is not None:
                        cal.reprojection_error_px = float(cfg["reprojection_error_px"])
        except Exception as exc:
            sys.stderr.write(f"[overwatch.persist] Failed to load calibrations from DB: {exc}\n")

    def _persist_calibrations(self) -> None:
        """Persist all camera calibrations and 4-point homographies to PostgreSQL ``app_settings``."""
        if self._repo is None:
            return
        try:
            import json as _json

            with self._lock:
                payload: Dict[str, Any] = {}
                for cid, slot in self._slots.items():
                    d = slot.calibration.to_dict()
                    if slot.calibration.homography_3x3 is not None:
                        d["homography_3x3"] = slot.calibration.homography_3x3
                    payload[cid] = d
            self._repo.upsert_settings({"overwatch_calibrations_json": _json.dumps(payload)}, source_ip="overwatch")
        except Exception as exc:
            sys.stderr.write(f"[overwatch.persist] Failed to save calibrations to DB: {exc}\n")

    @property
    def calibration(self) -> OverwatchCalibration:
        """Primary ``usb_4k`` camera calibration (backward-compatible accessor)."""
        return self._slots[DEFAULT_CAMERA_ID].calibration

    @property
    def detections(self) -> List[Dict[str, Any]]:
        """Primary ``usb_4k`` latest detections (backward-compatible accessor)."""
        return list(self._slots[DEFAULT_CAMERA_ID].detections)

    @property
    def triangulated_targets(self) -> List[Dict[str, Any]]:
        """Primary ``usb_4k`` latest triangulated targets (backward-compatible accessor)."""
        return list(self._slots[DEFAULT_CAMERA_ID].triangulated_targets)

    @property
    def puppy_visual_pose(self) -> Optional[Dict[str, Any]]:
        """Latest visually localized PuppyPi pose across active cameras."""
        primary = self._slots[DEFAULT_CAMERA_ID].puppy_visual_pose
        if primary is not None:
            return dict(primary)
        for slot in self._slots.values():
            if slot.puppy_visual_pose is not None:
                return dict(slot.puppy_visual_pose)
        return None

    def _get_or_create_slot(self, camera_id: Optional[str]) -> _CameraSlot:
        cid = sanitize_camera_id(camera_id)
        if cid not in self._slots:
            self._slots[cid] = _CameraSlot(
                camera_id=cid,
                camera_name=cid.replace("_", " ").title(),
                calibration=OverwatchCalibration(),
            )
        return self._slots[cid]

    def _detect_local_apriltags(self, frame_bgr: np.ndarray) -> List[Dict[str, Any]]:
        if self._aruco_detector is None:
            return []
        try:
            h, w = frame_bgr.shape[:2]
            gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
            corners, ids, _ = self._aruco_detector.detectMarkers(gray)
            if ids is None:
                return []
            out: List[Dict[str, Any]] = []
            for idx, tag_arr in enumerate(ids):
                pts = corners[idx][0]
                tag_id = int(np.asarray(tag_arr).ravel()[0])
                x1, y1 = float(pts[:, 0].min()) / w, float(pts[:, 1].min()) / h
                x2, y2 = float(pts[:, 0].max()) / w, float(pts[:, 1].max()) / h
                out.append(
                    {
                        "id": f"tag-{tag_id}",
                        "kind": "apriltag",
                        "label": f"AprilTag #{tag_id}",
                        "confidence": 1.0,
                        "bbox_norm": [round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4)],
                    }
                )
            return out
        except Exception as exc:
            sys.stderr.write(f"[overwatch.apriltag] Detection error: {exc}\n")
            return []

    @staticmethod
    def _render_offline_jpeg(camera_id: str, camera_name: str) -> bytes:
        canvas = np.zeros((360, 640, 3), dtype=np.uint8)
        canvas[:, :] = (18, 22, 30)
        cv2.rectangle(canvas, (14, 14), (626, 346), (56, 72, 96), 1)
        cv2.putText(
            canvas,
            f"OVERWATCH STANDBY | {camera_name} ({camera_id})",
            (28, 56),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.58,
            (100, 210, 255),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            canvas,
            "Click 'Enable Local Cameras' in /overwatch (Zero CLI required)",
            (28, 190),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.50,
            (180, 195, 215),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            canvas,
            "Or run auto-start background service for 4K USB + MacBook Cam",
            (28, 225),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.46,
            (130, 150, 175),
            1,
            cv2.LINE_AA,
        )
        ok, buf = cv2.imencode(".jpg", canvas, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
        return buf.tobytes() if ok else b""

    @staticmethod
    def _draw_hud_overlay(
        frame_bgr: np.ndarray,
        slot: _CameraSlot,
        detections: List[Dict[str, Any]],
        triangulated: List[Dict[str, Any]],
    ) -> bytes:
        out = frame_bgr.copy()
        h, w = out.shape[:2]
        # Top HUD banner
        cv2.rectangle(out, (0, 0), (w, 34), (15, 20, 28), -1)
        banner = (
            f"OVERWATCH [{slot.camera_id}] {slot.camera_name} | "
            f"{w}x{h} @ {slot.fps:.1f}fps | mode={slot.calibration.mode} | "
            f"det={len(detections)} tri={len(triangulated)}"
        )
        cv2.putText(out, banner, (10, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (95, 235, 255), 1, cv2.LINE_AA)

        color_map = {
            "face": (255, 190, 60),
            "animal": (80, 240, 150),
            "apriltag": (255, 110, 210),
            "object": (90, 205, 255),
        }
        for det in detections:
            bbox = det.get("bbox_norm") or [0.0, 0.0, 0.0, 0.0]
            x1 = max(0, min(w - 1, int(float(bbox[0]) * w)))
            y1 = max(0, min(h - 1, int(float(bbox[1]) * h)))
            x2 = max(x1 + 1, min(w, int(float(bbox[2]) * w)))
            y2 = max(y1 + 1, min(h, int(float(bbox[3]) * h)))
            col = color_map.get(str(det.get("kind") or "object"), (90, 205, 255))
            cv2.rectangle(out, (x1, y1), (x2, y2), col, 2)
            label = str(det.get("label") or "object")
            conf = float(det.get("confidence") or 0.0)
            wx, wy = det.get("x"), det.get("y")
            text = f"{label} {conf:.2f}"
            if wx is not None and wy is not None:
                text += f" ({wx:+.2f},{wy:+.2f}m)"
            ty = max(48, y1 - 8)
            cv2.putText(out, text, (x1, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.48, col, 1, cv2.LINE_AA)

        ok, buf = cv2.imencode(".jpg", out, [int(cv2.IMWRITE_JPEG_QUALITY), 84])
        return buf.tobytes() if ok else b""

    def ingest_frame(
        self,
        jpeg_bytes: bytes,
        camera_name: Optional[str] = None,
        fps: float = 10.0,
        ai_vision_engine: Any = None,
        ai_store: Any = None,
        runtime: Any = None,
        camera_id: str = DEFAULT_CAMERA_ID,
    ) -> Dict[str, Any]:
        """Ingest one JPEG frame, run active vision detectors, and triangulate 3D targets.

        Args:
            jpeg_bytes: Encoded JPEG image bytes.
            camera_name: Optional human-readable camera label.
            fps: Reported capture frame rate.
            ai_vision_engine: Optional ``RobotAiVisionEngine`` instance for YOLO/Face/AprilTag.
            ai_store: Optional ``RobotAiStoreProtocol`` for face embedding matching.
            runtime: Optional ``TwinScanRuntimeState`` for PuppyPi pose & LD19 ray fusion.
            camera_id: Target camera slot ID (default ``usb_4k``; e.g. ``macbook_cam``).

        Returns:
            Summary dict ``{ok, camera_id, camera_name, width, height, detections_count, triangulated_count}``.
        """
        if not jpeg_bytes:
            raise ValueError("Empty JPEG payload.")
        arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
        frame_bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame_bgr is None or frame_bgr.size == 0:
            raise ValueError("Invalid JPEG frame bytes.")

        h, w = frame_bgr.shape[:2]
        now_mono = time.monotonic()

        with self._lock:
            slot = self._get_or_create_slot(camera_id)
            if camera_name and str(camera_name).strip():
                slot.camera_name = str(camera_name).strip()[:80]
            cal = slot.calibration
            mode = cal.mode
            should_run_ai = (now_mono - slot.last_ai_mono) >= 0.40 or not slot.detections
            cached_dets = list(slot.detections)
            cached_tri = list(slot.triangulated_targets)

        if not should_run_ai:
            # Fast-path video pass-through (10 FPS smooth video while AI runs safely at ~2.5 Hz)
            annotated = self._draw_hud_overlay(frame_bgr, slot, cached_dets, cached_tri)
            with self._lock:
                slot.width = w
                slot.height = h
                slot.fps = round(max(0.1, float(fps)), 1)
                slot.last_frame_mono = now_mono
                slot.raw_jpeg = bytes(jpeg_bytes)
                slot.annotated_jpeg = annotated or bytes(jpeg_bytes)
            return {
                "ok": True,
                "camera_id": slot.camera_id,
                "camera_name": slot.camera_name,
                "width": w,
                "height": h,
                "detections_count": len(cached_dets),
                "triangulated_count": len(cached_tri),
                "global_tracks_count": len(self._tracker.list_tracks(now_mono=now_mono)),
            }

        raw_dets: List[Dict[str, Any]] = []
        # Serialize OpenCV DNN (YOLO11n + YuNet + SFace) with _ai_lock to prevent concurrent forwardGraph crashes
        with self._ai_lock:
            if mode in ("yolo", "triangulate") and ai_vision_engine is not None:
                try:
                    raw_dets.extend(ai_vision_engine.detect_objects_and_animals(frame_bgr, conf_thresh=0.35))
                except Exception as exc:
                    sys.stderr.write(f"[overwatch.yolo] Inference error: {exc}\n")

            if mode in ("face", "triangulate") and ai_vision_engine is not None:
                try:
                    faces = ai_vision_engine.detect_faces_and_embeddings(frame_bgr)
                    for idx, face in enumerate(faces):
                        label = "Unknown Person"
                        person_id = None
                        if ai_store is not None and face.get("embedding"):
                            try:
                                matcher = getattr(ai_store, "match_face_embedding", None) or getattr(
                                    ai_store, "match_person_by_embedding", None
                                )
                                match = matcher(face["embedding"], threshold=0.38) if callable(matcher) else None
                                if match:
                                    label = str(match.get("name") or "Known Person")
                                    person_id = match.get("id")
                            except Exception as exc:
                                sys.stderr.write(f"[overwatch.face_match] Error: {exc}\n")
                        raw_dets.append(
                            {
                                "id": f"face-{idx}",
                                "kind": "face",
                                "label": label,
                                "person_id": person_id,
                                "confidence": float(face.get("confidence", 0.8)),
                                "bbox_norm": face["bbox_norm"],
                            }
                        )
                except Exception as exc:
                    sys.stderr.write(f"[overwatch.face] Inference error: {exc}\n")

            if mode in ("apriltag", "triangulate"):
                if ai_vision_engine is not None and hasattr(ai_vision_engine, "detect_apriltags"):
                    try:
                        raw_dets.extend(ai_vision_engine.detect_apriltags(frame_bgr))
                    except Exception as exc:
                        sys.stderr.write(f"[overwatch.apriltag] Engine error: {exc}\n")
                else:
                    raw_dets.extend(self._detect_local_apriltags(frame_bgr))

        from src.vision.overwatch_tracker import compute_hsv_descriptor

        # Project each detection into 3D world coordinates & attempt dual-ray triangulation
        detections_out: List[Dict[str, Any]] = []
        triangulated_out: List[Dict[str, Any]] = []
        tracker_obs: List[Dict[str, Any]] = []
        rays_for_slot: Dict[str, Tuple[np.ndarray, np.ndarray, float]] = {}
        puppy_pose_est: Optional[Dict[str, Any]] = None
        ang_sigma_rad = max(0.004, math.radians(float(cal.hfov_deg)) / max(160.0, float(w) * 0.25))

        robot_pose = getattr(runtime, "robot_pose", None) if runtime is not None else None
        lidar_points = getattr(runtime, "latest_points", None) if runtime is not None else None

        with self._lock:
            peer_slots = [
                s
                for cid, s in self._slots.items()
                if cid != slot.camera_id and s.last_frame_mono > 0 and (now_mono - s.last_frame_mono) <= _ONLINE_TTL_SEC
            ]

        for idx, det in enumerate(raw_dets):
            bbox = det.get("bbox_norm") or [0.4, 0.4, 0.6, 0.6]
            x1, y1, x2, y2 = [float(v) for v in bbox[:4]]
            # Use bottom-center of bbox for floor-standing targets, center for faces/tags
            u_px = ((x1 + x2) * 0.5) * w
            v_px = (y2 if det.get("kind") in ("object", "animal") else (y1 + y2) * 0.5) * h
            origin1, dir1 = pixel_to_world_ray(u_px, v_px, w, h, cal)
            label = str(det.get("label") or "object")
            kind = str(det.get("kind") or "object")
            conf = round(float(det.get("confidence", 0.5)), 3)
            label_key = label.lower()
            rays_for_slot[label_key] = (origin1, dir1, conf)

            z_plane = 1.25 if kind == "face" else 0.0
            ground_hit = intersect_ray_ground_plane(origin1, dir1, z_plane=z_plane)
            world_xy = [ground_hit["x"], ground_hit["y"]] if ground_hit else None

            det_record: Dict[str, Any] = {
                "id": str(det.get("id") or f"det-{idx}"),
                "label": label,
                "kind": kind,
                "confidence": conf,
                "bbox_norm": [round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4)],
                "world_xy": world_xy,
                "x": ground_hit["x"] if ground_hit else None,
                "y": ground_hit["y"] if ground_hit else None,
            }
            detections_out.append(det_record)
            tracker_obs.append(
                {
                    "label": label,
                    "kind": kind,
                    "confidence": conf,
                    "origin": origin1,
                    "direction": dir1,
                    "angular_sigma_rad": ang_sigma_rad,
                    "ground_xy": (ground_hit["x"], ground_hit["y"]) if ground_hit else None,
                    "bbox_norm": det_record["bbox_norm"],
                    "hsv_desc": compute_hsv_descriptor(frame_bgr, det_record["bbox_norm"]),
                }
            )

            # 1) Try cross-camera dual-ray triangulation with another online overwatch camera
            tri_record: Optional[Dict[str, Any]] = None
            for peer in peer_slots:
                peer_ray = peer.rays_by_label.get(label_key)
                if peer_ray is not None:
                    o2, d2, _ = peer_ray
                    tri = triangulate_dual_rays(origin1, dir1, o2, d2)
                    tri_record = {
                        "label": label,
                        "kind": kind,
                        "x": tri["x"],
                        "y": tri["y"],
                        "z": tri["z"],
                        "error_m": tri["error_m"],
                        "confidence": round(min(1.0, (conf + tri["confidence"]) * 0.5), 3),
                        "source": f"dual_camera:{slot.camera_id}+{peer.camera_id}",
                    }
                    break

            # 2) Otherwise try Overwatch + PuppyPi LD19/Pose dual-ray fusion
            if tri_record is None and ground_hit is not None:
                if isinstance(robot_pose, dict) and robot_pose.get("live") and lidar_points:
                    rx = float(robot_pose.get("x") or 0.0)
                    ry = float(robot_pose.get("y") or 0.0)
                    # Find closest LiDAR point to ground_hit in XY
                    best_pt = None
                    best_d = 0.85
                    for pt in lidar_points[:360]:
                        px = rx + float(getattr(pt, "x", 0.0))
                        py = ry + float(getattr(pt, "y", 0.0))
                        dist = math.hypot(px - ground_hit["x"], py - ground_hit["y"])
                        if dist < best_d:
                            best_d = dist
                            best_pt = (px, py)
                    if best_pt is not None:
                        o2 = np.array([rx, ry, 0.18], dtype=np.float64)
                        d2 = np.array([best_pt[0] - rx, best_pt[1] - ry, 0.0], dtype=np.float64)
                        if float(np.linalg.norm(d2)) > 1e-4:
                            tri = triangulate_dual_rays(origin1, dir1, o2, d2)
                            tri_record = {
                                "label": label,
                                "kind": kind,
                                "x": tri["x"],
                                "y": tri["y"],
                                "z": tri["z"],
                                "error_m": tri["error_m"],
                                "confidence": round(min(1.0, (conf + tri["confidence"]) * 0.5), 3),
                                "source": "overwatch+lidar",
                            }

                if tri_record is None:
                    tri_record = {
                        "label": label,
                        "kind": kind,
                        "x": ground_hit["x"],
                        "y": ground_hit["y"],
                        "z": ground_hit["z"],
                        "error_m": 0.12,
                        "confidence": round(conf * 0.85, 3),
                        "source": f"overwatch_ground:{slot.camera_id}",
                    }

            if tri_record is not None:
                triangulated_out.append(tri_record)
                if label_key in ("dog", "puppypi", "apriltag #0", "apriltag #1"):
                    puppy_pose_est = {
                        "x": tri_record["x"],
                        "y": tri_record["y"],
                        "z": tri_record["z"],
                        "confidence": tri_record["confidence"],
                        "seen": True,
                    }

        annotated = self._draw_hud_overlay(frame_bgr, slot, detections_out, triangulated_out)

        with self._lock:
            slot.width = w
            slot.height = h
            slot.fps = round(max(0.1, float(fps)), 1)
            slot.last_frame_mono = now_mono
            slot.last_ai_mono = now_mono
            slot.raw_jpeg = bytes(jpeg_bytes)
            slot.annotated_jpeg = annotated or bytes(jpeg_bytes)
            slot.detections = detections_out
            slot.triangulated_targets = triangulated_out
            slot.rays_by_label = rays_for_slot
            if puppy_pose_est is not None:
                slot.puppy_visual_pose = puppy_pose_est
            global_tracks = self._tracker.update_camera_observations(
                camera_id=slot.camera_id,
                observations=tracker_obs,
                now_mono=now_mono,
            )

        return {
            "ok": True,
            "camera_id": slot.camera_id,
            "camera_name": slot.camera_name,
            "width": w,
            "height": h,
            "detections_count": len(detections_out),
            "triangulated_count": len(triangulated_out),
            "global_tracks_count": len(global_tracks),
        }

    def get_status(self, camera_id: Optional[str] = None) -> Dict[str, Any]:
        """Return live overwatch status for the requested/primary camera plus all known camera slots.

        Args:
            camera_id: Optional camera slot ID (defaults to ``usb_4k``).

        Returns:
            Status dictionary backward-compatible with single-camera consumers, plus
            a ``cameras`` map covering ``usb_4k``, ``macbook_cam``, and any custom slots.
        """
        now_mono = time.monotonic()
        with self._lock:
            slot = self._get_or_create_slot(camera_id)
            age = round(now_mono - slot.last_frame_mono, 2) if slot.last_frame_mono > 0 else None
            online = bool(age is not None and age <= _ONLINE_TTL_SEC)

            cameras_map: Dict[str, Dict[str, Any]] = {}
            for cid, s in self._slots.items():
                s_age = round(now_mono - s.last_frame_mono, 2) if s.last_frame_mono > 0 else None
                s_online = bool(s_age is not None and s_age <= _ONLINE_TTL_SEC)
                cameras_map[cid] = {
                    "camera_id": cid,
                    "camera_name": s.camera_name,
                    "online": s_online,
                    "width": s.width,
                    "height": s.height,
                    "fps": s.fps,
                    "age_sec": s_age,
                    "detections_count": len(s.detections) if s_online else 0,
                    "detections": list(s.detections) if s_online else [],
                    "calibration": s.calibration.to_dict(),
                }

            return {
                "camera_id": slot.camera_id,
                "online": online,
                "camera_name": slot.camera_name,
                "width": slot.width,
                "height": slot.height,
                "fps": slot.fps,
                "age_sec": age,
                "mode": slot.calibration.mode,
                "calibration": slot.calibration.to_dict(),
                "detections": list(slot.detections) if online else [],
                "triangulated_targets": list(slot.triangulated_targets) if online else [],
                "puppy_visual_pose": dict(slot.puppy_visual_pose) if (online and slot.puppy_visual_pose) else None,
                "cameras": cameras_map,
            }

    def update_calibration(
        self,
        updates: Dict[str, Any],
        camera_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update extrinsic/intrinsic calibration or vision mode for a camera slot.

        Args:
            updates: Partial mapping of ``OverwatchCalibration`` fields.
            camera_id: Target camera slot ID (defaults to ``usb_4k``).

        Returns:
            Updated ``get_status(camera_id=...)`` dictionary.

        Raises:
            ValueError: If an unsupported vision ``mode`` is supplied.
        """
        with self._lock:
            slot = self._get_or_create_slot(camera_id)
            cal = slot.calibration
            if "mode" in updates and updates["mode"] is not None:
                mode_val = str(updates["mode"]).strip().lower()
                if mode_val not in VALID_OVERWATCH_MODES:
                    raise ValueError(f"Unsupported overwatch mode {mode_val!r}; expected one of {sorted(VALID_OVERWATCH_MODES)}")
                cal.mode = mode_val
            for fld, lo, hi in (
                ("x_m", -50.0, 50.0),
                ("y_m", -50.0, 50.0),
                ("z_m", 0.05, 20.0),
                ("yaw_deg", -360.0, 360.0),
                ("pitch_deg", -89.0, 89.0),
                ("hfov_deg", 10.0, 165.0),
                ("vfov_deg", 10.0, 145.0),
            ):
                if fld in updates and updates[fld] is not None:
                    val = float(updates[fld])
                    setattr(cal, fld, max(lo, min(hi, val)))
            if "space_id" in updates:
                cal.space_id = str(updates["space_id"]).strip() or None if updates["space_id"] is not None else None
            if "calibration_method" in updates and updates["calibration_method"]:
                cal.calibration_method = str(updates["calibration_method"]).strip()
                cal.calibrated_at = time.time()
            elif any(k in updates and updates[k] is not None for k in ("x_m", "y_m", "z_m", "yaw_deg", "pitch_deg")):
                if cal.calibration_method == "default":
                    cal.calibration_method = "manual"
                cal.calibrated_at = time.time()
            if "reprojection_error_px" in updates and updates["reprojection_error_px"] is not None:
                cal.reprojection_error_px = float(updates["reprojection_error_px"])
        self._persist_calibrations()
        return self.get_status(camera_id=slot.camera_id)

    def get_snapshot_bytes(self, annotated: bool = True, camera_id: Optional[str] = None) -> bytes:
        """Return the latest annotated or raw JPEG frame for ``camera_id`` (or a standby HUD JPEG)."""
        now_mono = time.monotonic()
        with self._lock:
            slot = self._get_or_create_slot(camera_id)
            is_fresh = slot.last_frame_mono > 0 and (now_mono - slot.last_frame_mono) <= _ONLINE_TTL_SEC
            if is_fresh:
                if annotated and slot.annotated_jpeg:
                    return slot.annotated_jpeg
                if slot.raw_jpeg:
                    return slot.raw_jpeg
            cid = slot.camera_id
            cname = slot.camera_name
        return self._render_offline_jpeg(cid, cname)

    def get_raw_frame_jpeg(self, camera_id: Optional[str] = None) -> bytes:
        """Return the raw unannotated JPEG buffer for ``camera_id`` (or standby JPEG)."""
        return self.get_snapshot_bytes(annotated=False, camera_id=camera_id)

    def get_geometry_snapshot(
        self,
        runtime: Any = None,
        room_bounds: Optional[Tuple[float, float, float, float]] = None,
        max_range_m: float = 6.0,
    ) -> Dict[str, Any]:
        """Return frustum polygons, 0/1/2/3+ overlap zones, Placement Advisor, and global tracks.

        Args:
            runtime: Optional ``TwinScanRuntimeState`` to include mobile ``puppypi_fpv`` frustum.
            room_bounds: Optional ``(min_x, min_y, max_x, max_y)`` arena bounds in meters.
            max_range_m: Maximum frustum reach in meters.

        Returns:
            Full tactical BEV geometry dictionary for ``/overwatch`` and ``Lidar2DCanvas``.
        """
        from src.vision.overwatch_geometry import compute_coverage_overlap_zones

        now_mono = time.monotonic()
        with self._lock:
            cams: List[Dict[str, Any]] = []
            for cid, s in self._slots.items():
                age = (now_mono - s.last_frame_mono) if s.last_frame_mono > 0 else None
                online = bool(age is not None and age <= _ONLINE_TTL_SEC)
                cams.append(
                    {
                        "camera_id": cid,
                        "camera_name": s.camera_name,
                        "online": online,
                        "width": s.width or 1280,
                        "height": s.height or 720,
                        "calibration": s.calibration,
                    }
                )
            tracks = self._tracker.list_tracks(now_mono=now_mono)

        # Include PuppyPi mobile FPV camera frustum when live pose is available
        robot_pose = getattr(runtime, "robot_pose", None) if runtime is not None else None
        if isinstance(robot_pose, dict):
            rx = float(robot_pose.get("x") or 0.0)
            ry = float(robot_pose.get("y") or 0.0)
            ryaw = float(robot_pose.get("yaw_deg") or 0.0)
            cams.append(
                {
                    "camera_id": "puppypi_fpv",
                    "camera_name": "PuppyPi Mobile FPV",
                    "online": bool(robot_pose.get("live", False)),
                    "width": 640,
                    "height": 480,
                    "calibration": OverwatchCalibration(
                        x_m=rx,
                        y_m=ry,
                        z_m=0.22,
                        yaw_deg=ryaw,
                        pitch_deg=-10.0,
                        hfov_deg=62.0,
                        vfov_deg=46.0,
                        mode="triangulate",
                    ),
                }
            )

        geo = compute_coverage_overlap_zones(cams, room_bounds=room_bounds, max_range_m=max_range_m)
        geo["tracks"] = tracks
        return geo

    def calibrate_apriltag(
        self,
        camera_id: Optional[str] = None,
        tag_size_m: float = 0.12,
        tag_world_xyz: Tuple[float, float, float] = (0.0, 0.0, 0.0),
        tag_world_yaw_deg: float = 0.0,
        target_tag_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Auto-calibrate one or all active cameras using a visible AprilTag (``solvePnP``)."""
        from src.vision.overwatch_geometry import calibrate_camera_apriltag_pnp

        now_mono = time.monotonic()
        target_ids: List[str]
        with self._lock:
            if camera_id and str(camera_id).strip().lower() == "all":
                target_ids = [
                    cid
                    for cid, s in self._slots.items()
                    if s.raw_jpeg is not None and (now_mono - s.last_frame_mono) <= _ONLINE_TTL_SEC
                ]
                if not target_ids:
                    target_ids = list(self._slots.keys())
            else:
                target_ids = [sanitize_camera_id(camera_id)]

        results: Dict[str, Any] = {}
        calibrated_any = False
        for cid in target_ids:
            with self._lock:
                slot = self._get_or_create_slot(cid)
                raw = slot.raw_jpeg
                cal = slot.calibration
            if not raw:
                results[cid] = {"ok": False, "error": f"No live frame buffered for {cid}."}
                continue
            arr = np.frombuffer(raw, dtype=np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            try:
                solved = calibrate_camera_apriltag_pnp(
                    frame_bgr=frame,
                    cal=cal,
                    tag_size_m=tag_size_m,
                    tag_world_xyz=tag_world_xyz,
                    tag_world_yaw_deg=tag_world_yaw_deg,
                    target_tag_id=target_tag_id,
                )
                self.update_calibration(solved["calibration"], camera_id=cid)
                results[cid] = solved
                calibrated_any = True
            except Exception as exc:
                results[cid] = {"ok": False, "error": str(exc)}

        return {
            "ok": calibrated_any,
            "results": results,
            "geometry": self.get_geometry_snapshot(),
        }

    def calibrate_homography(
        self,
        camera_id: Optional[str],
        pixel_points_norm: Sequence[Sequence[float]],
        world_points_xy: Sequence[Sequence[float]],
    ) -> Dict[str, Any]:
        """Calibrate a camera from 4+ clicked floor points via ``findHomography`` + ``solvePnP``."""
        from src.vision.overwatch_geometry import calibrate_camera_four_point_homography

        cid = sanitize_camera_id(camera_id)
        with self._lock:
            slot = self._get_or_create_slot(cid)
            w = slot.width or 1280
            h = slot.height or 720
            cal = slot.calibration

        solved = calibrate_camera_four_point_homography(
            pixel_points_norm=pixel_points_norm,
            world_points_xy=world_points_xy,
            width=w,
            height=h,
            cal=cal,
        )
        self.update_calibration(
            {
                **solved["calibration"],
                "calibration_method": "homography",
                "reprojection_error_px": solved.get("reprojection_error_px"),
            },
            camera_id=cid,
        )
        with self._lock:
            slot = self._get_or_create_slot(cid)
            slot.calibration.homography_3x3 = solved["homography_3x3"]
        self._persist_calibrations()
        return {
            "ok": True,
            "camera_id": cid,
            **solved,
            "status": self.get_status(camera_id=cid),
            "geometry": self.get_geometry_snapshot(),
        }

    def project_task_point(
        self,
        camera_id: Optional[str],
        u_norm: float,
        v_norm: float,
        runtime: Any = None,
        standoff_m: float = 0.30,
    ) -> Dict[str, Any]:
        """Project a clicked pixel on ``camera_id`` to a floor target & safe PuppyPi waypoint."""
        from src.vision.overwatch_geometry import project_pixel_to_task_waypoint

        cid = sanitize_camera_id(camera_id)
        with self._lock:
            slot = self._get_or_create_slot(cid)
            w = slot.width or 1280
            h = slot.height or 720
            cal = slot.calibration
            H = cal.homography_3x3

        robot_pose = getattr(runtime, "robot_pose", None) if runtime is not None else None
        proj = project_pixel_to_task_waypoint(
            u_norm=u_norm,
            v_norm=v_norm,
            cal=cal,
            width=w,
            height=h,
            homography_3x3=H,
            robot_pose=robot_pose if isinstance(robot_pose, dict) else None,
            standoff_m=standoff_m,
        )
        return {"ok": True, "camera_id": cid, **proj}
