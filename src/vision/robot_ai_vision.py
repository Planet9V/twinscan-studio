"""ROS 2 & ROS 1 Offloaded AI Vision Studio: Face Recognition, Animals/Objects, Click-to-Track, Line Follow v2, and AprilTag.

Runs on the TwinScan backend using already-installed ``opencv-python-headless`` (5.x),
``numpy``, and auto-cached YuNet/SFace/YOLO11n ONNX weights (with automatic OpenCV
Haar/contour/HSV fallback when offline or weights are unavailable).
"""

from __future__ import annotations

import asyncio
import base64
import math
import os
import sys
import time
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Coroutine, Dict, List, Optional, Sequence, Tuple

import cv2
import httpx
import numpy as np

from src.db.robot_ai_store import RobotAiStoreProtocol
from src.robot.ros_profiles import get_ros_profile
from src.robot.rosbridge_proxy import fetch_robot_snapshot, publish_velocity, run_action

VALID_AI_VISION_MODES = frozenset(
    {"raw", "face_recognition", "object_animal", "track_follow", "line_follow", "apriltag"}
)

COCO_CLASSES: Tuple[str, ...] = (
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat", "traffic light",
    "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep", "cow",
    "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
    "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket", "bottle",
    "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch", "potted plant", "bed",
    "dining table", "toilet", "tv", "laptop", "mouse", "remote", "keyboard", "cell phone", "microwave", "oven",
    "toaster", "sink", "refrigerator", "book", "clock", "vase", "scissors", "teddy bear", "hair drier", "toothbrush",
)

ANIMAL_CLASSES = frozenset(
    {"bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe"}
)

ONNX_MODEL_URLS: Dict[str, str] = {
    "face_detection_yunet_2023mar.onnx": (
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
    ),
    "face_recognition_sface_2021dec.onnx": (
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx"
    ),
    "yolo11n.onnx": (
        "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n.onnx"
    ),
}

# HSV color presets: list of (lower_hsv, upper_hsv) tuples
LINE_COLOR_PRESETS: Dict[str, List[Tuple[Tuple[int, int, int], Tuple[int, int, int]]]] = {
    "black": [((0, 0, 0), (180, 255, 65))],
    "red": [((0, 90, 70), (10, 255, 255)), ((170, 90, 70), (180, 255, 255))],
    "blue": [((95, 80, 60), (135, 255, 255))],
    "green": [((38, 70, 60), (85, 255, 255))],
    "yellow": [((18, 90, 80), (36, 255, 255))],
}


async def ensure_onnx_models(models_dir: str | Path) -> Dict[str, bool]:
    """Ensure YuNet, SFace, and YOLO11n ONNX weights exist in ``models_dir`` (3x retry + stderr).

    Args:
        models_dir: Persistent directory path (e.g. ``/app/data/models``).

    Returns:
        Dictionary mapping model filename -> ``True`` if cached and ready, else ``False``.
    """
    root = Path(models_dir)
    root.mkdir(parents=True, exist_ok=True)
    status: Dict[str, bool] = {}

    async def _download_one(fname: str, url: str) -> bool:
        dest = root / fname
        if dest.is_file() and dest.stat().st_size > 10_000:
            return True
        for attempt in range(1, 4):
            try:
                async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    if len(resp.content) > 10_000:
                        tmp = root / f"{fname}.tmp"
                        tmp.write_bytes(resp.content)
                        tmp.replace(dest)
                        return True
            except Exception as exc:
                sys.stderr.write(f"[ai_vision.models] Download {fname} failed (attempt {attempt}/3): {exc}\n")
                if attempt < 3:
                    await asyncio.sleep(0.5 * attempt)
        return False

    results = await asyncio.gather(*(_download_one(fn, u) for fn, u in ONNX_MODEL_URLS.items()))
    for fn, ok in zip(ONNX_MODEL_URLS.keys(), results):
        status[fn] = ok
    return status


def _compute_fallback_face_embedding(face_bgr: np.ndarray) -> List[float]:
    """Compute a deterministic L2-normalized 128-D visual descriptor when SFace ONNX is unavailable."""
    resized = cv2.resize(face_bgr, (32, 32), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    hsv = cv2.cvtColor(resized, cv2.COLOR_BGR2HSV)
    # 64 spatial block averages (8x8) + 64 HSV/grayscale histogram bins = 128-D descriptor
    blocks = cv2.resize(gray, (8, 8), interpolation=cv2.INTER_AREA).flatten()
    h_hist = cv2.calcHist([hsv], [0], None, [32], [0, 180]).flatten()
    v_hist = cv2.calcHist([hsv], [2], None, [32], [0, 256]).flatten()
    vec = np.concatenate([blocks, h_hist, v_hist]).astype(np.float32)
    norm = float(np.linalg.norm(vec))
    if norm > 1e-8:
        vec = vec / norm
    return [round(float(x), 6) for x in vec[:128]]


def compute_line_centroid_and_steer(
    frame_bgr: np.ndarray,
    line_color: str = "black",
    custom_hsv: Optional[Tuple[int, int, int]] = None,
) -> Dict[str, Any]:
    """Detect a colored floor line across 3 bottom ROI bands and compute PID steering.

    Args:
        frame_bgr: OpenCV BGR camera image.
        line_color: Preset name (``black``, ``red``, ``blue``, ``green``, ``yellow``, ``custom``).
        custom_hsv: Optional ``(H, S, V)`` tuple picked via live eyedropper.

    Returns:
        Dictionary ``{found, cx_norm, error, yaw_rate_rads, vx_cms, bands, bbox_norm}``.
    """
    h, w = frame_bgr.shape[:2]
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)

    if line_color == "custom" and custom_hsv is not None:
        ch, cs, cv_val = custom_hsv
        ranges = [
            (
                (max(0, ch - 18), max(30, cs - 60), max(30, cv_val - 60)),
                (min(180, ch + 18), min(255, cs + 60), min(255, cv_val + 60)),
            )
        ]
    else:
        ranges = LINE_COLOR_PRESETS.get(line_color, LINE_COLOR_PRESETS["black"])

    mask = np.zeros((h, w), dtype=np.uint8)
    for lo, hi in ranges:
        mask = cv2.bitwise_or(mask, cv2.inRange(hsv, np.array(lo, dtype=np.uint8), np.array(hi, dtype=np.uint8)))
    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

    band_specs = [(0.55, 0.70, 0.2), (0.70, 0.85, 0.35), (0.85, 0.98, 0.45)]
    weighted_cx = 0.0
    total_w = 0.0
    bands_out: List[Dict[str, Any]] = []
    min_x, max_x = w, 0

    for y0_f, y1_f, weight in band_specs:
        y0, y1 = int(h * y0_f), int(h * y1_f)
        roi = mask[y0:y1, :]
        moments = cv2.moments(roi)
        if moments["m00"] > max(200.0, (y1 - y0) * w * 0.015):
            cx = moments["m10"] / moments["m00"]
            cx_norm = cx / float(w)
            weighted_cx += cx_norm * weight
            total_w += weight
            ys, xs = np.where(roi > 0)
            if xs.size:
                min_x = min(min_x, int(xs.min()))
                max_x = max(max_x, int(xs.max()))
            bands_out.append({"y0": y0_f, "y1": y1_f, "cx_norm": round(cx_norm, 3), "found": True})
        else:
            bands_out.append({"y0": y0_f, "y1": y1_f, "cx_norm": None, "found": False})

    if total_w <= 0.0:
        return {
            "found": False,
            "cx_norm": 0.5,
            "error": 0.0,
            "yaw_rate_rads": 0.0,
            "vx_cms": 0.0,
            "bands": bands_out,
            "bbox_norm": [0.0, 0.55, 0.0, 0.98],
        }

    cx_norm = weighted_cx / total_w
    error = cx_norm - 0.5  # >0 means line is to the right -> steer right (negative yaw_rate)
    yaw_rate = max(-0.55, min(0.55, -error * 1.4))
    vx_cms = max(4.0, 10.0 * (1.0 - min(0.7, abs(error) * 1.4)))
    return {
        "found": True,
        "cx_norm": round(cx_norm, 4),
        "error": round(error, 4),
        "yaw_rate_rads": round(yaw_rate, 3),
        "vx_cms": round(vx_cms, 2),
        "bands": bands_out,
        "bbox_norm": [round(min_x / float(w), 3), 0.55, round(max_x / float(w), 3), 0.98],
    }


def compute_follow_pd_command(
    bbox_norm: Sequence[float],
    lidar_front_m: float = 9.9,
    lidar_stop_m: float = 0.35,
) -> Dict[str, Any]:
    """Compute safe PD steering & forward/back speed for Click-to-Track Target Following.

    Args:
        bbox_norm: Target normalized box ``[x1, y1, x2, y2]`` in ``[0, 1]``.
        lidar_front_m: Closest forward LiDAR obstacle distance in meters.
        lidar_stop_m: Hard safety stop threshold in meters (default ``0.35m``).

    Returns:
        Dictionary ``{vx_cms, yaw_rate_rads, blocked_by_lidar}``.
    """
    x1, y1, x2, y2 = [float(v) for v in bbox_norm[:4]]
    cx = (x1 + x2) / 2.0
    area = max(0.0, (x2 - x1) * (y2 - y1))

    err_x = cx - 0.5
    yaw_rate = max(-0.55, min(0.55, -err_x * 1.25)) if abs(err_x) > 0.06 else 0.0

    # Desired apparent target area ~0.16 (too small -> move forward; too large -> back up slightly)
    if area < 0.12:
        vx = min(12.0, (0.14 - area) * 95.0)
    elif area > 0.28:
        vx = max(-10.0, -(area - 0.25) * 45.0)
    else:
        vx = 0.0

    blocked = False
    if vx > 0.0 and lidar_front_m < lidar_stop_m:
        vx = 0.0
        blocked = True

    return {
        "vx_cms": round(vx, 2),
        "yaw_rate_rads": round(yaw_rate, 3),
        "blocked_by_lidar": blocked,
    }


def _compute_box_hsv_hist(frame_bgr: np.ndarray, bbox_norm: Sequence[float]) -> Optional[np.ndarray]:
    h, w = frame_bgr.shape[:2]
    x1 = max(0, min(w - 2, int(bbox_norm[0] * w)))
    y1 = max(0, min(h - 2, int(bbox_norm[1] * h)))
    x2 = max(x1 + 2, min(w, int(bbox_norm[2] * w)))
    y2 = max(y1 + 2, min(h, int(bbox_norm[3] * h)))
    crop = frame_bgr[y1:y2, x1:x2]
    if crop.size == 0:
        return None
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [16, 16], [0, 180, 0, 256])
    cv2.normalize(hist, hist)
    return hist.flatten()


def _box_iou(a: Sequence[float], b: Sequence[float]) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - inter
    return inter / union if union > 1e-6 else 0.0


class RobotAiVisionEngine:
    """Stateful offloaded AI Vision processor managing Face Recognition, YOLO11n, Tracking, Line Follow, and AprilTags."""

    def __init__(
        self,
        ai_store: RobotAiStoreProtocol,
        models_dir: Optional[str] = None,
    ) -> None:
        """Initialize the vision engine with optional ONNX model directory."""
        self.ai_store = ai_store
        self.models_dir = Path(models_dir or os.environ.get("TWINSCAN_MODELS_DIR", "./data/models"))
        self._models_ready: Dict[str, bool] = {fn: (self.models_dir / fn).is_file() for fn in ONNX_MODEL_URLS}
        self._yunet: Any = None
        self._sface: Any = None
        self._yolo_net: Any = None
        self._haar_face: Any = None
        self._aruco_detector: Any = None
        self._states: Dict[str, Dict[str, Any]] = {}
        self._last_frames: Dict[str, np.ndarray] = {}
        self._greet_cooldown: Dict[Tuple[str, str], float] = {}
        self._init_opencv_fallbacks()

    def _init_opencv_fallbacks(self) -> None:
        try:
            haar_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
            if haar_path.is_file():
                self._haar_face = cv2.CascadeClassifier(str(haar_path))
        except Exception:
            self._haar_face = None
        try:
            aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
            params = cv2.aruco.DetectorParameters()
            self._aruco_detector = cv2.aruco.ArucoDetector(aruco_dict, params)
        except Exception:
            self._aruco_detector = None

    def _load_onnx_if_present(self, width: int = 320, height: int = 240) -> None:
        yn_path = self.models_dir / "face_detection_yunet_2023mar.onnx"
        sf_path = self.models_dir / "face_recognition_sface_2021dec.onnx"
        yo_path = self.models_dir / "yolo11n.onnx"

        if self._yunet is None and yn_path.is_file():
            try:
                self._yunet = cv2.FaceDetectorYN.create(str(yn_path), "", (width, height), 0.65, 0.3, 100)
                self._models_ready["face_detection_yunet_2023mar.onnx"] = True
            except Exception as exc:
                sys.stderr.write(f"[ai_vision] YuNet init failed: {exc}\n")
        if self._sface is None and sf_path.is_file():
            try:
                self._sface = cv2.FaceRecognizerSF.create(str(sf_path), "")
                self._models_ready["face_recognition_sface_2021dec.onnx"] = True
            except Exception as exc:
                sys.stderr.write(f"[ai_vision] SFace init failed: {exc}\n")
        if self._yolo_net is None and yo_path.is_file():
            try:
                self._yolo_net = cv2.dnn.readNetFromONNX(str(yo_path))
                self._models_ready["yolo11n.onnx"] = True
            except Exception as exc:
                sys.stderr.write(f"[ai_vision] YOLO11n init failed: {exc}\n")

    def get_state(self, robot_id: str) -> Dict[str, Any]:
        """Return the current AI vision configuration, camera health, and latest detections for ``robot_id``."""
        st = self._states.setdefault(
            robot_id,
            {
                "robot_id": robot_id,
                "mode": "raw",
                "follow_enabled": False,
                "line_follow_enabled": False,
                "auto_greet_enabled": False,
                "lidar_stop_m": 0.35,
                "line_color": "black",
                "custom_hsv": None,
                "tracked_target": None,
                "tracked_hist": None,
                "tracker": None,
                "tracker_template": None,
                "lost_frames": 0,
                "target_fps": 10.0,
                "conf_threshold": 0.35,
                "camera_connected": True,
                "last_error": None,
                "fps": 0.0,
                "detections": [],
                "last_greeting": None,
                "visual_obstacle": None,
            },
        )
        return {
            "robot_id": robot_id,
            "mode": st["mode"],
            "follow_enabled": st["follow_enabled"],
            "line_follow_enabled": st["line_follow_enabled"],
            "auto_greet_enabled": st["auto_greet_enabled"],
            "lidar_stop_m": st["lidar_stop_m"],
            "line_color": st["line_color"],
            "custom_hsv": list(st["custom_hsv"]) if st["custom_hsv"] else None,
            "tracked_target": st["tracked_target"],
            "lost_frames": int(st.get("lost_frames", 0)),
            "target_fps": float(st.get("target_fps", 10.0)),
            "conf_threshold": float(st.get("conf_threshold", 0.35)),
            "camera_connected": bool(st.get("camera_connected", True)),
            "last_error": st.get("last_error"),
            "fps": round(float(st["fps"]), 1),
            "models_ready": dict(self._models_ready),
            "detections": list(st["detections"]),
            "last_greeting": st["last_greeting"],
        }

    def set_mode(
        self,
        robot_id: str,
        mode: str,
        follow_enabled: Optional[bool] = None,
        line_follow_enabled: Optional[bool] = None,
        auto_greet_enabled: Optional[bool] = None,
        lidar_stop_m: Optional[float] = None,
        line_color: Optional[str] = None,
        target_fps: Optional[float] = None,
        conf_threshold: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Update active AI vision mode, FPS/confidence tuning, and autonomous safety toggles."""
        if mode not in VALID_AI_VISION_MODES:
            raise ValueError(f"Unsupported AI vision mode: {mode!r}")
        self.get_state(robot_id)
        st = self._states[robot_id]
        st["mode"] = mode
        if mode == "raw":
            st["follow_enabled"] = False
            st["line_follow_enabled"] = False
            st["tracked_target"] = None
            st["tracked_hist"] = None
            st["tracker"] = None
            st["tracker_template"] = None
            st["lost_frames"] = 0
        if follow_enabled is not None:
            st["follow_enabled"] = bool(follow_enabled)
        if line_follow_enabled is not None:
            st["line_follow_enabled"] = bool(line_follow_enabled)
        if auto_greet_enabled is not None:
            st["auto_greet_enabled"] = bool(auto_greet_enabled)
        if lidar_stop_m is not None:
            st["lidar_stop_m"] = max(0.15, min(2.0, float(lidar_stop_m)))
        if line_color is not None and line_color in (*LINE_COLOR_PRESETS.keys(), "custom"):
            st["line_color"] = line_color
        if target_fps is not None:
            st["target_fps"] = round(max(1.0, min(20.0, float(target_fps))), 1)
        if conf_threshold is not None:
            st["conf_threshold"] = round(max(0.20, min(0.80, float(conf_threshold))), 2)
        return self.get_state(robot_id)

    def stop_autonomous_motion(self, robot_id: str) -> None:
        """Immediately disarm autonomous follow & line-follow driving (invoked on E-STOP)."""
        st = self._states.get(robot_id)
        if st:
            st["follow_enabled"] = False
            st["line_follow_enabled"] = False
            st["tracked_target"] = None
            st["tracked_hist"] = None
            st["tracker"] = None
            st["tracker_template"] = None
            st["lost_frames"] = 0

    def get_visual_obstacle(self, robot_id: str) -> Optional[str]:
        """Return the label of any large central front-camera obstacle, or ``None``."""
        st = self._states.get(robot_id)
        return st.get("visual_obstacle") if st else None

    @staticmethod
    def _init_visual_tracker(frame_bgr: np.ndarray, bbox_norm: Sequence[float]) -> Tuple[Any, Optional[np.ndarray]]:
        """Initialize OpenCV ``TrackerMIL`` (and grayscale template crop fallback) on ``bbox_norm``."""
        h, w = frame_bgr.shape[:2]
        x1 = max(0, min(w - 4, int(bbox_norm[0] * w)))
        y1 = max(0, min(h - 4, int(bbox_norm[1] * h)))
        bw = max(8, min(w - x1, int((bbox_norm[2] - bbox_norm[0]) * w)))
        bh = max(8, min(h - y1, int((bbox_norm[3] - bbox_norm[1]) * h)))
        tpl: Optional[np.ndarray] = None
        crop = frame_bgr[y1 : y1 + bh, x1 : x1 + bw]
        if crop.size > 0:
            tpl = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        tracker = None
        try:
            if hasattr(cv2, "TrackerMIL_create"):
                t = cv2.TrackerMIL_create()
                t.init(frame_bgr, (x1, y1, bw, bh))
                tracker = t
        except Exception as exc:
            sys.stderr.write(f"[ai_vision.tracker] TrackerMIL init failed (using template fallback): {exc}\n")
        return tracker, tpl

    def select_target(
        self,
        robot_id: str,
        norm_x: float,
        norm_y: float,
        clear: bool = False,
    ) -> Dict[str, Any]:
        """Lock Click-to-Track onto the detection box containing ``(norm_x, norm_y)`` (or synthetic ROI)."""
        self.get_state(robot_id)
        st = self._states[robot_id]
        if clear:
            st["tracked_target"] = None
            st["tracked_hist"] = None
            st["tracker"] = None
            st["tracker_template"] = None
            st["lost_frames"] = 0
            st["follow_enabled"] = False
            return self.get_state(robot_id)

        nx = max(0.0, min(1.0, float(norm_x)))
        ny = max(0.0, min(1.0, float(norm_y)))
        chosen: Optional[Dict[str, Any]] = None
        for det in st.get("detections") or []:
            bx1, by1, bx2, by2 = det["bbox_norm"]
            if bx1 <= nx <= bx2 and by1 <= ny <= by2:
                chosen = det
                break

        if chosen is not None:
            bbox = list(chosen["bbox_norm"])
            label = str(chosen["label"])
        else:
            bbox = [max(0.0, nx - 0.1), max(0.0, ny - 0.12), min(1.0, nx + 0.1), min(1.0, ny + 0.12)]
            label = "Clicked Target"

        st["tracked_target"] = {"label": label, "bbox_norm": [round(v, 4) for v in bbox]}
        st["lost_frames"] = 0
        frame = self._last_frames.get(robot_id)
        if frame is not None:
            st["tracked_hist"] = _compute_box_hsv_hist(frame, bbox)
            st["tracker"], st["tracker_template"] = self._init_visual_tracker(frame, bbox)
        if st["mode"] in ("raw", "face_recognition", "apriltag"):
            st["mode"] = "track_follow"
        return self.get_state(robot_id)

    def pick_line_color(
        self,
        robot_id: str,
        norm_x: float,
        norm_y: float,
        frame_bgr: Optional[np.ndarray] = None,
    ) -> Dict[str, Any]:
        """Sample HSV color at ``(norm_x, norm_y)`` from the latest camera frame for Line Follow v2."""
        self.get_state(robot_id)
        st = self._states[robot_id]
        img = frame_bgr if frame_bgr is not None else self._last_frames.get(robot_id)
        if img is not None and img.size > 0:
            h, w = img.shape[:2]
            px = max(0, min(w - 1, int(float(norm_x) * w)))
            py = max(0, min(h - 1, int(float(norm_y) * h)))
            patch = img[max(0, py - 3) : min(h, py + 4), max(0, px - 3) : min(w, px + 4)]
            hsv_patch = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
            med = np.median(hsv_patch.reshape(-1, 3), axis=0)
            st["custom_hsv"] = (int(med[0]), int(med[1]), int(med[2]))
            st["line_color"] = "custom"
        st["mode"] = "line_follow"
        return self.get_state(robot_id)

    def detect_faces_and_embeddings(self, frame_bgr: np.ndarray) -> List[Dict[str, Any]]:
        """Detect faces and extract 128-D embeddings using YuNet+SFace (with Haar+descriptor fallback)."""
        h, w = frame_bgr.shape[:2]
        self._load_onnx_if_present(w, h)
        results: List[Dict[str, Any]] = []

        if self._yunet is not None:
            try:
                self._yunet.setInputSize((w, h))
                _, faces = self._yunet.detect(frame_bgr)
                if faces is not None:
                    for row in faces:
                        x, y, bw, bh = int(row[0]), int(row[1]), int(row[2]), int(row[3])
                        conf = float(row[-1])
                        if bw < 16 or bh < 16:
                            continue
                        if self._sface is not None:
                            aligned = self._sface.alignCrop(frame_bgr, row)
                            feat = self._sface.feature(aligned).flatten().tolist()
                        else:
                            crop = frame_bgr[max(0, y) : min(h, y + bh), max(0, x) : min(w, x + bw)]
                            feat = _compute_fallback_face_embedding(crop) if crop.size else [0.0] * 128
                        results.append(
                            {
                                "bbox_norm": [
                                    round(max(0.0, x / w), 4),
                                    round(max(0.0, y / h), 4),
                                    round(min(1.0, (x + bw) / w), 4),
                                    round(min(1.0, (y + bh) / h), 4),
                                ],
                                "confidence": round(conf, 3),
                                "embedding": feat,
                            }
                        )
                return results
            except Exception as exc:
                sys.stderr.write(f"[ai_vision.faces] YuNet error, falling back to Haar: {exc}\n")

        if self._haar_face is not None:
            gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
            rects = self._haar_face.detectMultiScale(gray, scaleFactor=1.15, minNeighbors=4, minSize=(36, 36))
            for x, y, bw, bh in rects:
                crop = frame_bgr[max(0, y) : min(h, y + bh), max(0, x) : min(w, x + bw)]
                feat = _compute_fallback_face_embedding(crop) if crop.size else [0.0] * 128
                results.append(
                    {
                        "bbox_norm": [
                            round(max(0.0, x / w), 4),
                            round(max(0.0, y / h), 4),
                            round(min(1.0, (x + bw) / w), 4),
                            round(min(1.0, (y + bh) / h), 4),
                        ],
                        "confidence": 0.82,
                        "embedding": feat,
                    }
                )
        return results

    def extract_enrollment_embedding(self, image_bytes: bytes) -> Tuple[List[float], bool]:
        """Decode an uploaded/snapped JPEG and extract a 128-D face embedding for enrollment.

        Returns:
            Tuple ``(embedding_128d, face_detected)``.
        """
        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None or img.size == 0:
            raise ValueError("Invalid image data for person enrollment")
        faces = self.detect_faces_and_embeddings(img)
        if faces:
            # Largest face wins during enrollment
            faces.sort(
                key=lambda f: (f["bbox_norm"][2] - f["bbox_norm"][0]) * (f["bbox_norm"][3] - f["bbox_norm"][1]),
                reverse=True,
            )
            return faces[0]["embedding"], True
        # Deterministic center-crop descriptor when enrolling synthetic/distant photo
        h, w = img.shape[:2]
        crop = img[h // 6 : (5 * h) // 6, w // 6 : (5 * w) // 6]
        return _compute_fallback_face_embedding(crop if crop.size else img), False

    def detect_objects_and_animals(self, frame_bgr: np.ndarray, conf_thresh: float = 0.35) -> List[Dict[str, Any]]:
        """Run YOLO11n ONNX inference via ``cv2.dnn`` to detect 80 COCO classes including animals."""
        h, w = frame_bgr.shape[:2]
        self._load_onnx_if_present(w, h)
        if self._yolo_net is None:
            return []
        try:
            blob = cv2.dnn.blobFromImage(frame_bgr, 1.0 / 255.0, (320, 320), swapRB=True, crop=False)
            self._yolo_net.setInput(blob)
            out = self._yolo_net.forward()
            preds = out[0] if out.ndim == 3 else out
            if preds.shape[0] == 84:
                preds = preds.T  # (N, 84) -> [cx, cy, bw, bh, 80 class scores]
            boxes: List[List[int]] = []
            scores: List[float] = []
            class_ids: List[int] = []
            sx, sy = w / 320.0, h / 320.0
            for row in preds:
                cls_scores = row[4:]
                cid = int(np.argmax(cls_scores))
                score = float(cls_scores[cid])
                if score < conf_thresh or cid >= len(COCO_CLASSES):
                    continue
                cx, cy, bw, bh = row[0] * sx, row[1] * sy, row[2] * sx, row[3] * sy
                x1 = int(max(0, cx - bw / 2.0))
                y1 = int(max(0, cy - bh / 2.0))
                boxes.append([x1, y1, int(bw), int(bh)])
                scores.append(score)
                class_ids.append(cid)

            if not boxes:
                return []
            idxs = cv2.dnn.NMSBoxes(boxes, scores, conf_thresh, 0.45)
            detections: List[Dict[str, Any]] = []
            for raw_i in (idxs.flatten() if hasattr(idxs, "flatten") else idxs):
                i = int(raw_i)
                x1, y1, bw, bh = boxes[i]
                cls_name = COCO_CLASSES[class_ids[i]]
                is_animal = cls_name in ANIMAL_CLASSES
                detections.append(
                    {
                        "id": f"obj-{i}",
                        "kind": "animal" if is_animal else "object",
                        "label": cls_name,
                        "confidence": round(scores[i], 3),
                        "is_animal": is_animal,
                        "person_id": None,
                        "bbox_norm": [
                            round(max(0.0, x1 / w), 4),
                            round(max(0.0, y1 / h), 4),
                            round(min(1.0, (x1 + bw) / w), 4),
                            round(min(1.0, (y1 + bh) / h), 4),
                        ],
                        "tracked": False,
                    }
                )
            return detections
        except Exception as exc:
            sys.stderr.write(f"[ai_vision.yolo] Inference error: {exc}\n")
            return []

    def detect_apriltags(self, frame_bgr: np.ndarray) -> List[Dict[str, Any]]:
        """Detect AprilTag 36h11 markers passively using ``cv2.aruco``."""
        if self._aruco_detector is None:
            return []
        h, w = frame_bgr.shape[:2]
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        corners, ids, _ = self._aruco_detector.detectMarkers(gray)
        detections: List[Dict[str, Any]] = []
        if ids is None:
            return detections
        for idx, tag_id_arr in enumerate(ids):
            pts = corners[idx][0]
            tag_id = int(np.asarray(tag_id_arr).ravel()[0])
            x1, y1 = float(pts[:, 0].min()) / w, float(pts[:, 1].min()) / h
            x2, y2 = float(pts[:, 0].max()) / w, float(pts[:, 1].max()) / h
            detections.append(
                {
                    "id": f"tag-{tag_id}",
                    "kind": "apriltag",
                    "label": f"AprilTag #{tag_id}",
                    "confidence": 1.0,
                    "is_animal": False,
                    "person_id": None,
                    "bbox_norm": [round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4)],
                    "tracked": False,
                }
            )
        return detections

    def process_frame(
        self,
        robot_id: str,
        frame_bgr: np.ndarray,
        lidar_front_m: float = 9.9,
    ) -> Tuple[np.ndarray, Dict[str, Any]]:
        """Process one camera frame according to active mode, draw Eigenia HUD overlays, and compute control cues."""
        self.get_state(robot_id)
        st = self._states[robot_id]
        self._last_frames[robot_id] = frame_bgr
        mode = st["mode"]
        out = frame_bgr.copy()
        h, w = out.shape[:2]
        detections: List[Dict[str, Any]] = []
        motion_cmd: Optional[Dict[str, float]] = None
        greet_trigger: Optional[Dict[str, Any]] = None

        if mode == "face_recognition":
            faces = self.detect_faces_and_embeddings(frame_bgr)
            for idx, f in enumerate(faces):
                match = self.ai_store.match_face_embedding(f["embedding"], threshold=0.363)
                if match:
                    person = match["person"]
                    label = f"{person['name']} ({int(match['similarity'] * 100)}%)"
                    color = (90, 210, 110)  # Green BGR
                    pid = person["id"]
                    self.ai_store.touch_person_seen(pid)
                    now_ts = time.monotonic()
                    cd_key = (robot_id, pid)
                    if st["auto_greet_enabled"] and (now_ts - self._greet_cooldown.get(cd_key, 0.0)) > 30.0:
                        self._greet_cooldown[cd_key] = now_ts
                        greet_trigger = person
                        st["last_greeting"] = person.get("greeting_phrase") or f"Hello {person['name']}!"
                else:
                    label = f"Unknown Face ({int(f['confidence'] * 100)}%)"
                    color = (16, 165, 245)  # Amber BGR
                    pid = None
                det = {
                    "id": f"face-{idx}",
                    "kind": "face",
                    "label": label,
                    "confidence": f["confidence"],
                    "is_animal": False,
                    "person_id": pid,
                    "bbox_norm": f["bbox_norm"],
                    "tracked": False,
                }
                detections.append(det)
                self._draw_box(out, f["bbox_norm"], label, color)

        elif mode in ("object_animal", "track_follow"):
            detections = self.detect_objects_and_animals(frame_bgr, conf_thresh=float(st.get("conf_threshold", 0.35)))
            tracked = st.get("tracked_target")
            if tracked is not None:
                best_score = 0.0
                best_det: Optional[Dict[str, Any]] = None
                for det in detections:
                    iou = _box_iou(tracked["bbox_norm"], det["bbox_norm"])
                    hist_sim = 0.0
                    if st.get("tracked_hist") is not None:
                        dh = _compute_box_hsv_hist(frame_bgr, det["bbox_norm"])
                        if dh is not None:
                            hist_sim = max(0.0, float(cv2.compareHist(st["tracked_hist"], dh, cv2.HISTCMP_CORREL)))
                    score = iou * 0.65 + hist_sim * 0.35
                    if score > best_score and score > 0.22:
                        best_score = score
                        best_det = det

                target_updated = False
                if best_det is not None:
                    best_det["tracked"] = True
                    st["tracked_target"] = {"label": best_det["label"], "bbox_norm": best_det["bbox_norm"]}
                    st["lost_frames"] = 0
                    target_updated = True
                else:
                    # V3: Fall back to TrackerMIL (or normalized template matching) when YOLO misses
                    tracker = st.get("tracker")
                    if tracker is not None:
                        try:
                            ok_trk, box = tracker.update(frame_bgr)
                            if ok_trk:
                                tx, ty, tw, th = [float(v) for v in box]
                                if tw >= 8 and th >= 8 and 0 <= tx < w and 0 <= ty < h:
                                    new_box = [
                                        round(max(0.0, tx / w), 4),
                                        round(max(0.0, ty / h), 4),
                                        round(min(1.0, (tx + tw) / w), 4),
                                        round(min(1.0, (ty + th) / h), 4),
                                    ]
                                    st["tracked_target"] = {"label": tracked["label"], "bbox_norm": new_box}
                                    st["lost_frames"] = 0
                                    target_updated = True
                        except Exception:
                            target_updated = False
                    elif st.get("tracker_template") is not None:
                        tpl = st["tracker_template"]
                        gray_f = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
                        if tpl.shape[0] < gray_f.shape[0] and tpl.shape[1] < gray_f.shape[1]:
                            res_tm = cv2.matchTemplate(gray_f, tpl, cv2.TM_CCOEFF_NORMED)
                            _, max_val, _, max_loc = cv2.minMaxLoc(res_tm)
                            if max_val >= 0.52:
                                tx, ty = float(max_loc[0]), float(max_loc[1])
                                tw, th = float(tpl.shape[1]), float(tpl.shape[0])
                                new_box = [
                                    round(max(0.0, tx / w), 4),
                                    round(max(0.0, ty / h), 4),
                                    round(min(1.0, (tx + tw) / w), 4),
                                    round(min(1.0, (ty + th) / h), 4),
                                ]
                                st["tracked_target"] = {"label": tracked["label"], "bbox_norm": new_box}
                                st["lost_frames"] = 0
                                target_updated = True

                    if not target_updated:
                        st["lost_frames"] = int(st.get("lost_frames", 0)) + 1

                is_lost = int(st.get("lost_frames", 0)) >= 5
                if st["follow_enabled"]:
                    if is_lost:
                        motion_cmd = {"x": 0.0, "yaw_rate": 0.0}
                    else:
                        cmd = compute_follow_pd_command(
                            st["tracked_target"]["bbox_norm"],
                            lidar_front_m=lidar_front_m,
                            lidar_stop_m=st["lidar_stop_m"],
                        )
                        motion_cmd = {"x": cmd["vx_cms"], "yaw_rate": cmd["yaw_rate_rads"]}
                lock_label = f"LOST ({st['lost_frames']})" if is_lost else st["tracked_target"]["label"]
                self._draw_crosshair(out, st["tracked_target"]["bbox_norm"], lock_label)

            for det in detections:
                if det.get("is_animal"):
                    col = (16, 90, 224)  # Eigenia Signal Orange BGR
                elif det.get("tracked"):
                    col = (90, 210, 110)
                else:
                    col = (248, 189, 56)  # Eigenia Telemetry Sky BGR
                self._draw_box(out, det["bbox_norm"], f"{det['label']} {int(det['confidence']*100)}%", col)

        elif mode == "line_follow":
            lf = compute_line_centroid_and_steer(frame_bgr, st["line_color"], st.get("custom_hsv"))
            for band in lf["bands"]:
                y0, y1 = int(band["y0"] * h), int(band["y1"] * h)
                cv2.rectangle(out, (0, y0), (w - 1, y1), (90, 90, 110), 1)
                if band["found"] and band["cx_norm"] is not None:
                    cx = int(band["cx_norm"] * w)
                    cv2.circle(out, (cx, (y0 + y1) // 2), 6, (16, 90, 224), -1)
            if lf["found"]:
                detections.append(
                    {
                        "id": "line-0",
                        "kind": "line",
                        "label": f"Line ({st['line_color']}) err={lf['error']:+.2f}",
                        "confidence": 0.95,
                        "is_animal": False,
                        "person_id": None,
                        "bbox_norm": lf["bbox_norm"],
                        "tracked": True,
                    }
                )
                if st["line_follow_enabled"]:
                    vx = 0.0 if lidar_front_m < st["lidar_stop_m"] else lf["vx_cms"]
                    motion_cmd = {"x": vx, "yaw_rate": lf["yaw_rate_rads"]}

        elif mode == "apriltag":
            detections = self.detect_apriltags(frame_bgr)
            for det in detections:
                self._draw_box(out, det["bbox_norm"], det["label"], (248, 189, 56))

        # Check front visual obstacle heuristic (large central person/chair/animal box > 35% frame area)
        vis_obs: Optional[str] = None
        for det in detections:
            bx1, by1, bx2, by2 = det["bbox_norm"]
            if (bx2 - bx1) * (by2 - by1) > 0.35 and 0.25 <= (bx1 + bx2) / 2.0 <= 0.75:
                vis_obs = det["label"]
                break
        st["visual_obstacle"] = vis_obs
        st["detections"] = detections

        # Draw compact Eigenia HUD bar
        cv2.rectangle(out, (0, 0), (w, 26), (16, 13, 11), -1)
        hud = f"EIGENIA AI // {mode.upper()} | {len(detections)} det | {st['fps']:.1f} FPS"
        cv2.putText(out, hud, (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (248, 189, 56), 1, cv2.LINE_AA)

        return out, {"detections": detections, "motion_cmd": motion_cmd, "greet_trigger": greet_trigger}

    @staticmethod
    def _draw_box(img: np.ndarray, bbox_norm: Sequence[float], label: str, color: Tuple[int, int, int]) -> None:
        h, w = img.shape[:2]
        x1, y1 = int(bbox_norm[0] * w), int(bbox_norm[1] * h)
        x2, y2 = int(bbox_norm[2] * w), int(bbox_norm[3] * h)
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
        cv2.rectangle(img, (x1, max(0, y1 - 18)), (min(w, x1 + len(label) * 7 + 8), y1), color, -1)
        cv2.putText(img, label, (x1 + 4, max(12, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (11, 13, 16), 1, cv2.LINE_AA)

    @staticmethod
    def _draw_crosshair(img: np.ndarray, bbox_norm: Sequence[float], label: str) -> None:
        h, w = img.shape[:2]
        cx = int(((bbox_norm[0] + bbox_norm[2]) / 2.0) * w)
        cy = int(((bbox_norm[1] + bbox_norm[3]) / 2.0) * h)
        cv2.drawMarker(img, (cx, cy), (16, 90, 224), cv2.MARKER_CROSS, 22, 2)
        cv2.putText(img, f"LOCK: {label}", (max(4, cx - 40), max(38, cy - 14)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (16, 90, 224), 1, cv2.LINE_AA)

    @staticmethod
    def _render_offline_hud_frame(robot_id: str, mode: str, error_msg: str) -> bytes:
        """Render a crisp 640x360 dark Eigenia HUD JPEG so offline cameras never hang 0-byte streams."""
        canvas = np.full((360, 640, 3), (16, 13, 11), dtype=np.uint8)
        cv2.rectangle(canvas, (0, 0), (640, 36), (28, 22, 18), -1)
        cv2.putText(
            canvas,
            f"EIGENIA AI VISION // {mode.upper()} // CAMERA OFFLINE",
            (14, 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (16, 90, 224),
            1,
            cv2.LINE_AA,
        )
        cv2.rectangle(canvas, (36, 90), (604, 270), (50, 44, 38), 1)
        cv2.putText(
            canvas,
            "Waiting for PuppyPi FPV camera stream...",
            (125, 165),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (235, 240, 245),
            1,
            cv2.LINE_AA,
        )
        short_err = str(error_msg or "Camera unreachable")[:72]
        cv2.putText(
            canvas,
            short_err,
            (54, 210),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.46,
            (140, 155, 175),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            canvas,
            f"Robot: {robot_id[:16]}  |  Auto-reconnecting",
            (175, 248),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.44,
            (248, 189, 56),
            1,
            cv2.LINE_AA,
        )
        ok, enc = cv2.imencode(".jpg", canvas, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        return enc.tobytes() if ok else b""

    async def stream_annotated_mjpeg(
        self,
        robot_id: str,
        robot_ip: str,
        video_port: int,
        rosbridge_port: int,
        ros_version: str,
        get_front_lidar_m: Callable[[], float],
        on_greet: Optional[Callable[[Dict[str, Any]], Coroutine[Any, Any, None]]] = None,
        is_disconnected: Optional[Callable[[], Coroutine[Any, Any, bool]]] = None,
        on_sighting: Optional[Callable[[Dict[str, Any], bytes], Coroutine[Any, Any, None]]] = None,
    ) -> AsyncIterator[bytes]:
        """Continuously fetch PuppyPi FPV frames over a pooled HTTP client, run non-blocking AI vision, and yield MJPEG."""
        self.get_state(robot_id)
        profile = get_ros_profile(ros_version)
        topic = profile["camera_topic"]
        fallback_topic = "/usb_cam/image_raw" if topic == "/image_raw" else "/image_raw"
        last_motion_ts = 0.0
        sighting_cooldown: Dict[Tuple[str, str], float] = {}
        http_timeout = httpx.Timeout(connect=2.5, read=3.5, write=3.0, pool=3.0)

        async with httpx.AsyncClient(timeout=http_timeout) as client:
            while True:
                if is_disconnected is not None and await is_disconnected():
                    return
                t0 = time.perf_counter()
                st = self._states[robot_id]
                target_fps = max(1.0, min(20.0, float(st.get("target_fps", 10.0))))
                frame_period = 1.0 / target_fps

                try:
                    raw_jpg: Optional[bytes] = None
                    try:
                        resp = await client.get(f"http://{robot_ip}:{video_port}/snapshot?topic={topic}")
                        resp.raise_for_status()
                        if resp.content:
                            raw_jpg = resp.content
                    except Exception:
                        resp2 = await client.get(f"http://{robot_ip}:{video_port}/snapshot?topic={fallback_topic}")
                        resp2.raise_for_status()
                        if resp2.content:
                            raw_jpg = resp2.content
                            topic, fallback_topic = fallback_topic, topic

                    if not raw_jpg:
                        raise ConnectionError("Empty camera frame")

                    arr = np.frombuffer(raw_jpg, dtype=np.uint8)
                    frame = await asyncio.to_thread(cv2.imdecode, arr, cv2.IMREAD_COLOR)
                    if frame is None or frame.size == 0:
                        raise ValueError("Corrupt JPEG frame")

                    st["camera_connected"] = True
                    st["last_error"] = None
                    lidar_front = get_front_lidar_m()
                    annotated, meta = await asyncio.to_thread(self.process_frame, robot_id, frame, lidar_front)
                    dt = max(0.01, time.perf_counter() - t0)
                    st["fps"] = 0.7 * st["fps"] + 0.3 * (1.0 / dt)

                    if meta["motion_cmd"] is not None and (time.monotonic() - last_motion_ts) > 0.2:
                        last_motion_ts = time.monotonic()
                        try:
                            await publish_velocity(
                                ip=robot_ip,
                                port=rosbridge_port,
                                x=meta["motion_cmd"]["x"],
                                y=0.0,
                                yaw_rate=meta["motion_cmd"]["yaw_rate"],
                                ros_version=ros_version,
                                robot_id=robot_id,
                            )
                        except Exception as exc:
                            sys.stderr.write(f"[ai_vision.motion] Publish failed: {exc}\n")

                    if meta["greet_trigger"] is not None and on_greet is not None:
                        asyncio.create_task(on_greet(meta["greet_trigger"]))

                    # Add-On B: Record recognized faces & high-confidence objects/animals into Spatial Memory (15s throttle)
                    if on_sighting is not None:
                        now_m = time.monotonic()
                        for det in meta.get("detections") or []:
                            conf = float(det.get("confidence", 0.0))
                            kind = str(det.get("kind") or "object")
                            label = str(det.get("label") or "").strip()
                            if not label or label.startswith("Unknown Face") or kind == "line":
                                continue
                            if conf >= 0.45 or det.get("person_id"):
                                ckey = (robot_id, label.lower())
                                if (now_m - sighting_cooldown.get(ckey, -999.0)) >= 15.0:
                                    sighting_cooldown[ckey] = now_m
                                    asyncio.create_task(on_sighting(det, raw_jpg))

                    ok, enc = await asyncio.to_thread(
                        cv2.imencode, ".jpg", annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 80]
                    )
                    if ok:
                        yield (
                            b"--boundarydonotcross\r\n"
                            b"Content-Type: image/jpeg\r\n\r\n" + enc.tobytes() + b"\r\n"
                        )
                    elapsed = time.perf_counter() - t0
                    await asyncio.sleep(max(0.01, frame_period - elapsed))
                except asyncio.CancelledError:
                    return
                except Exception as exc:
                    sys.stderr.write(f"[ai_vision.stream] Frame error for {robot_id}: {exc}\n")
                    st["camera_connected"] = False
                    st["last_error"] = str(exc)
                    hud_jpg = await asyncio.to_thread(
                        self._render_offline_hud_frame, robot_id, st["mode"], str(exc)
                    )
                    if hud_jpg:
                        yield (
                            b"--boundarydonotcross\r\n"
                            b"Content-Type: image/jpeg\r\n\r\n" + hud_jpg + b"\r\n"
                        )
                    await asyncio.sleep(0.8)


async def deep_identify_frame(
    image_bytes: bytes,
    api_key: str,
    base_url: str = "https://openrouter.ai/api/v1",
    model: str = "google/gemini-2.5-flash",
    prompt: Optional[str] = None,
) -> Dict[str, Any]:
    """Identify objects, animals, and room scene in a live PuppyPi JPEG using OpenRouter VLM."""
    clean_key = (api_key or "").strip()
    if not clean_key or clean_key == "your_openrouter_api_key_here":
        return {
            "ok": True,
            "description": "OpenRouter API key not configured; local camera frame captured cleanly.",
            "objects": [],
            "animals": [],
            "model_used": "offline-local",
        }
    b64 = base64.b64encode(image_bytes).decode("ascii")
    user_prompt = prompt or (
        "Briefly describe what the PuppyPi robot camera sees in 2 sentences, listing any animals, people, "
        "or notable objects. Return JSON: {\"description\": str, \"objects\": [str], \"animals\": [str]}."
    )
    body = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ],
            }
        ],
        "max_tokens": 300,
    }
    root = base_url.rstrip("/")
    for attempt in range(1, 4):
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(
                    f"{root}/chat/completions",
                    headers={"Authorization": f"Bearer {clean_key}", "Content-Type": "application/json"},
                    json=body,
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                # Parse JSON if wrapped in fences
                cleaned = content.strip()
                if "```" in cleaned:
                    parts = cleaned.split("```")
                    for p in parts:
                        p = p.lstrip("json").strip()
                        if p.startswith("{"):
                            cleaned = p
                            break
                try:
                    import json as _json

                    parsed = _json.loads(cleaned)
                    return {
                        "ok": True,
                        "description": str(parsed.get("description") or content),
                        "objects": [str(x) for x in (parsed.get("objects") or [])],
                        "animals": [str(x) for x in (parsed.get("animals") or [])],
                        "model_used": model,
                    }
                except Exception:
                    return {"ok": True, "description": content, "objects": [], "animals": [], "model_used": model}
        except Exception as exc:
            sys.stderr.write(f"[ai_vision.deep_identify] Attempt {attempt}/3 failed: {exc}\n")
            if attempt < 3:
                await asyncio.sleep(0.5 * attempt)
    return {
        "ok": False,
        "description": "OpenRouter VLM identification failed after retries.",
        "objects": [],
        "animals": [],
        "model_used": model,
    }
