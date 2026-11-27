"""Cross-OS Host USB 4K Webcam & Built-in MacBook Pro Camera Bridge for TwinScan Overwatch.

Captures live frames from local OpenCV cameras (auto-detecting BOTH external
``4k Webcam`` as ``usb_4k`` and built-in ``MacBook Pro Camera`` as ``macbook_cam``)
and pushes JPEG frames to ``POST /api/overwatch/ingest`` with automatic retry.

Usage:
    python -m src.bridge.mac_camera_bridge
    python -m src.bridge.mac_camera_bridge --device-index auto --width 1920 --height 1080 --fps 10
    python -m src.bridge.mac_camera_bridge --device-index 1 --camera-id usb_4k --camera-name "4k Webcam"
"""

from __future__ import annotations

import argparse
import json
import platform
import signal
import subprocess
import sys
import threading
import time
from typing import Any, Dict, List, Optional

import cv2
import httpx


def _get_capture_backend() -> int:
    """Return the preferred OpenCV capture backend for the current OS."""
    if platform.system() == "Darwin" and hasattr(cv2, "CAP_AVFOUNDATION"):
        return int(cv2.CAP_AVFOUNDATION)
    return int(cv2.CAP_ANY)


def _list_macos_camera_names() -> List[str]:
    """Query macOS ``system_profiler SPCameraDataType`` for human-readable camera names."""
    if platform.system() != "Darwin":
        return []
    try:
        proc = subprocess.run(
            ["system_profiler", "SPCameraDataType", "-json"],
            capture_output=True,
            text=True,
            timeout=3.0,
            check=False,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return []
        parsed = json.loads(proc.stdout)
        cams = parsed.get("SPCameraDataType") or []
        return [str(c.get("_name") or "").strip() for c in cams if isinstance(c, dict) and c.get("_name")]
    except Exception as exc:
        sys.stderr.write(f"[mac_camera_bridge] system_profiler probe skipped: {exc}\n")
        return []


def detect_available_cameras(max_index: int = 4) -> List[Dict[str, Any]]:
    """Probe local OpenCV camera indices and assign ``usb_4k`` / ``macbook_cam`` slots.

    Args:
        max_index: Exclusive upper bound of OpenCV indices to probe (default ``4``).

    Returns:
        List of camera descriptor dicts ``{index, camera_id, camera_name}``.
    """
    backend = _get_capture_backend()
    mac_names = _list_macos_camera_names()
    found_indices: List[int] = []
    for idx in range(max(1, int(max_index))):
        cap = None
        try:
            cap = cv2.VideoCapture(idx, backend)
            if cap is not None and cap.isOpened():
                ok, frame = cap.read()
                if ok and frame is not None and frame.size > 0:
                    found_indices.append(idx)
        except Exception as exc:
            sys.stderr.write(f"[mac_camera_bridge] Probe index {idx} failed: {exc}\n")
        finally:
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    pass

    if not found_indices:
        return []

    # On macOS, OpenCV AVFoundation indices do NOT always match system_profiler order:
    # probe each camera's native max width (4K USB supports >= 2560px or MJPG 3840x2160,
    # whereas built-in MacBook Pro Camera caps at 1920x1080).
    probed: List[Dict[str, Any]] = []
    for idx in found_indices:
        max_w = 0
        cap = None
        try:
            cap = cv2.VideoCapture(idx, backend)
            if cap is not None and cap.isOpened():
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 3840)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 2160)
                max_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        except Exception:
            max_w = 0
        finally:
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    pass
        probed.append({"index": idx, "max_w": max_w})

    cameras: List[Dict[str, Any]] = []
    used_ids: set[str] = set()
    # Identify the true 4K USB camera first (highest max_w >= 2560, else index 1 when >=2 cams)
    usb_4k_idx: Optional[int] = None
    if len(probed) >= 2:
        by_res = sorted(probed, key=lambda p: (p["max_w"], p["index"]), reverse=True)
        if by_res[0]["max_w"] > by_res[1]["max_w"] and by_res[0]["max_w"] >= 2000:
            usb_4k_idx = int(by_res[0]["index"])
        else:
            # On macOS AVFoundation, index 0 is normally built-in FaceTime/MacBook Pro Camera
            usb_4k_idx = int(probed[1]["index"])

    usb_name = next((n for n in mac_names if any(k in n.lower() for k in ("4k", "usb", "webcam", "logitech", "brio"))), "4k Webcam")
    mac_name = next((n for n in mac_names if any(k in n.lower() for k in ("macbook", "facetime", "built-in"))), "MacBook Pro Camera")

    for item in probed:
        idx = int(item["index"])
        if len(probed) >= 2:
            if idx == usb_4k_idx and "usb_4k" not in used_ids:
                cid, cname = "usb_4k", usb_name
            elif "macbook_cam" not in used_ids:
                cid, cname = "macbook_cam", mac_name
            else:
                cid, cname = f"cam_{idx}", f"USB Camera #{idx}"
        else:
            if item["max_w"] >= 2000:
                cid, cname = "usb_4k", usb_name
            else:
                cid, cname = "macbook_cam", mac_name

        used_ids.add(cid)
        cameras.append({"index": idx, "camera_id": cid, "camera_name": cname, "max_width": item["max_w"]})

    # Prefer streaming usb_4k first in log output
    cameras.sort(key=lambda c: (0 if c["camera_id"] == "usb_4k" else 1 if c["camera_id"] == "macbook_cam" else 2))
    return cameras


def post_frame_with_retry(
    client: httpx.Client,
    api_url: str,
    jpeg_bytes: bytes,
    camera_id: str,
    camera_name: str,
    fps: float,
    max_retries: int = 3,
) -> bool:
    """POST a JPEG frame to ``/api/overwatch/ingest`` with up to 3x retry & stderr logging.

    Args:
        client: Reusable synchronous ``httpx.Client``.
        api_url: TwinScan backend base URL (e.g. ``http://localhost:8000``).
        jpeg_bytes: Encoded JPEG frame bytes.
        camera_id: Overwatch camera slot ID (e.g. ``usb_4k`` or ``macbook_cam``).
        camera_name: Human-readable camera display name.
        fps: Target capture FPS.
        max_retries: Maximum HTTP retry attempts on transient errors (default ``3``).

    Returns:
        ``True`` if the frame was accepted by the backend, ``False`` otherwise.
    """
    endpoint = f"{api_url.rstrip('/')}/api/overwatch/ingest"
    params = {"camera_id": camera_id, "camera_name": camera_name, "fps": f"{fps:.1f}"}
    for attempt in range(1, max(1, int(max_retries)) + 1):
        try:
            resp = client.post(
                endpoint,
                params=params,
                content=jpeg_bytes,
                headers={"Content-Type": "image/jpeg"},
            )
            if resp.status_code < 400:
                return True
            sys.stderr.write(
                f"[mac_camera_bridge:{camera_id}] HTTP {resp.status_code} (attempt {attempt}/{max_retries}): "
                f"{resp.text[:160]}\n"
            )
        except Exception as exc:
            sys.stderr.write(
                f"[mac_camera_bridge:{camera_id}] Upload failed (attempt {attempt}/{max_retries}): {exc}\n"
            )
        if attempt < max_retries:
            time.sleep(0.15 * attempt)
    return False


def _camera_capture_loop(
    device_index: int,
    camera_id: str,
    camera_name: str,
    api_url: str,
    width: int,
    height: int,
    fps: float,
    quality: int,
    stop_event: threading.Event,
) -> None:
    """Capture loop for a single OpenCV camera pushing frames to TwinScan Overwatch."""
    backend = _get_capture_backend()
    interval = 1.0 / max(0.5, float(fps))
    cap = cv2.VideoCapture(device_index, backend)
    if not cap.isOpened():
        sys.stderr.write(f"[mac_camera_bridge:{camera_id}] Unable to open camera index {device_index}.\n")
        return

    # Enable hardware MJPG so USB 2.0 4K webcams negotiate crisp 1080p/4K instead of blurry YUYV
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(width))
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(height))
    cap.set(cv2.CAP_PROP_FPS, float(fps))
    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or width)
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or height)
    print(
        f"[mac_camera_bridge] Streaming [{camera_id}] '{camera_name}' (index={device_index}, "
        f"{actual_w}x{actual_h} @ {fps:.1f}fps) -> {api_url}/api/overwatch/ingest",
        flush=True,
    )

    encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), max(40, min(98, int(quality)))]
    sent_count = 0
    try:
        with httpx.Client(timeout=5.0) as client:
            while not stop_event.is_set():
                t0 = time.monotonic()
                ok, frame = cap.read()
                if not ok or frame is None or frame.size == 0:
                    sys.stderr.write(f"[mac_camera_bridge:{camera_id}] Empty frame from index {device_index}, retrying...\n")
                    time.sleep(0.25)
                    continue
                enc_ok, buf = cv2.imencode(".jpg", frame, encode_params)
                if enc_ok:
                    if post_frame_with_retry(
                        client=client,
                        api_url=api_url,
                        jpeg_bytes=buf.tobytes(),
                        camera_id=camera_id,
                        camera_name=camera_name,
                        fps=fps,
                        max_retries=3,
                    ):
                        sent_count += 1
                elapsed = time.monotonic() - t0
                sleep_s = interval - elapsed
                if sleep_s > 0.0:
                    stop_event.wait(sleep_s)
    finally:
        cap.release()
        print(f"[mac_camera_bridge] Stopped [{camera_id}] after {sent_count} frames.", flush=True)


def run_bridge(
    device_index: str = "auto",
    width: int = 1920,
    height: int = 1080,
    fps: float = 10.0,
    quality: int = 85,
    api_url: str = "http://localhost:8000",
    camera_name: Optional[str] = None,
    camera_id: str = "usb_4k",
    all_cameras: bool = True,
) -> int:
    """Start capturing from one or all detected host cameras until interrupted.

    Returns:
        Process exit code (``0`` on clean shutdown, ``1`` if no cameras opened).
    """
    targets: List[Dict[str, Any]] = []
    if str(device_index).strip().lower() == "auto":
        detected = detect_available_cameras(max_index=4)
        if not detected:
            sys.stderr.write("[mac_camera_bridge] No accessible cameras found on indices 0..3.\n")
            return 1
        targets = detected if all_cameras else [detected[0]]
        if camera_name and len(targets) == 1:
            targets[0]["camera_name"] = camera_name
    else:
        idx = int(device_index)
        targets = [
            {
                "index": idx,
                "camera_id": camera_id or "usb_4k",
                "camera_name": camera_name or ("MacBook Pro Camera" if idx == 0 else "4k Webcam"),
            }
        ]

    stop_event = threading.Event()

    def _handle_sig(_signum: int, _frame: Any) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_sig)
    signal.signal(signal.SIGTERM, _handle_sig)

    threads: List[threading.Thread] = []
    for t in targets:
        th = threading.Thread(
            target=_camera_capture_loop,
            kwargs={
                "device_index": int(t["index"]),
                "camera_id": str(t["camera_id"]),
                "camera_name": str(t["camera_name"]),
                "api_url": api_url,
                "width": width,
                "height": height,
                "fps": fps,
                "quality": quality,
                "stop_event": stop_event,
            },
            daemon=True,
        )
        th.start()
        threads.append(th)

    try:
        while not stop_event.is_set() and any(th.is_alive() for th in threads):
            time.sleep(0.2)
    except KeyboardInterrupt:
        stop_event.set()
    finally:
        stop_event.set()
        for th in threads:
            th.join(timeout=3.0)
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    """Construct the CLI argument parser for ``mac_camera_bridge``."""
    parser = argparse.ArgumentParser(
        description="Stream USB 4K Webcam and/or Built-in MacBook Pro Camera to Eigenia TwinScan Overwatch."
    )
    parser.add_argument(
        "--device-index",
        default="auto",
        help="Camera index ('auto' for dual USB 4K + MacBook Pro Cam, or integer like 0, 1).",
    )
    parser.add_argument("--all-cameras", dest="all_cameras", action="store_true", default=True)
    parser.add_argument("--single-camera", dest="all_cameras", action="store_false")
    parser.add_argument("--width", type=int, default=1920, help="Requested capture width (default: 1920).")
    parser.add_argument("--height", type=int, default=1080, help="Requested capture height (default: 1080).")
    parser.add_argument("--fps", type=float, default=10.0, help="Target upload FPS (default: 10.0).")
    parser.add_argument("--quality", type=int, default=85, help="JPEG compression quality 40..98 (default: 85).")
    parser.add_argument("--api-url", default="http://localhost:8000", help="TwinScan backend base URL.")
    parser.add_argument("--camera-id", default="usb_4k", help="Camera slot ID when using an explicit --device-index.")
    parser.add_argument("--camera-name", default=None, help="Optional camera display name override.")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entrypoint for the host Overwatch camera bridge."""
    args = build_arg_parser().parse_args(argv)
    return run_bridge(
        device_index=args.device_index,
        width=args.width,
        height=args.height,
        fps=args.fps,
        quality=args.quality,
        api_url=args.api_url,
        camera_name=args.camera_name,
        camera_id=args.camera_id,
        all_cameras=args.all_cameras,
    )


if __name__ == "__main__":
    raise SystemExit(main())
