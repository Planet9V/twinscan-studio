"""100% Cloud-Free Local Camera Array & Raspberry Pi Zero 2 W USB Clip Harvester Bridge.

Zero Amazon/vendor cloud dependencies and ZERO new pip packages:
- Generates a ready-to-run Raspberry Pi Zero 2 W ``g_mass_storage`` + read-only loop-mount
  clip forwarder script so Blink Sync Module 2 local USB clips push straight over ``Wildcat``
  Wi-Fi to ``POST /api/devices/cameras/ingest-media``.
- Extracts sharpest frames from local ``.jpg/.png`` or ``.mp4/.mov/.avi`` clips via OpenCV.
- Fetches live LAN HTTP JPEG snapshots (``httpx``, 3x retry) or ``rtsp://`` frames (OpenCV).
- Runs local offline AI Vision (YOLO11n + YuNet/SFace) and stores detections in Spatial Memory.
"""

from __future__ import annotations

import asyncio
import base64
import os
import re
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple

import cv2
import httpx
import numpy as np


def _sanitize_host(host: str) -> str:
    clean = str(host or "192.168.1.89:8000").strip()
    clean = re.sub(r"^https?://", "", clean).rstrip("/")
    clean = re.sub(r"[^A-Za-z0-9._:\-]", "", clean)
    return clean or "192.168.1.89:8000"


def _sanitize_device_id(device_id: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9._\-]", "", str(device_id or "pizero-sync-bridge").strip())
    return clean[:48] or "pizero-sync-bridge"


def generate_pi_zero_gadget_setup_script(
    docker_host: str = "192.168.1.89:8000",
    device_id: str = "pizero-sync-bridge",
) -> Dict[str, Any]:
    """Generate a cloud-free Raspberry Pi Zero 2 W USB Mass Storage Gadget clip harvester script.

    Emulates a FAT32 USB flash drive (``g_mass_storage``) plugged into a Blink Sync Module 2
    (or any local camera DVR USB port). A systemd watcher periodically mounts the backing
    image read-only to discover new ``.mp4`` clips and POSTs them directly over local Wi-Fi
    to Eigenia TwinScan's ``/api/devices/cameras/ingest-media`` endpoint — zero cloud required.

    Args:
        docker_host: Hostname/IP and port of the local Eigenia TwinScan backend (e.g. ``"192.168.1.89:8000"``).
        device_id: Human-readable camera/bridge identifier tagged into ``camera_source``.

    Returns:
        Dictionary ``{"filename": str, "script": str, "instructions": List[str]}``.
    """
    host = _sanitize_host(docker_host)
    dev_id = _sanitize_device_id(device_id)
    script = f"""#!/usr/bin/env bash
# ==============================================================================
# Eigenia TwinScan — 100% Cloud-Free Pi Zero 2 W USB Clip Harvester Setup
# Emulates a FAT32 USB drive for Blink Sync Module 2 (g_mass_storage) and pushes
# newly recorded .mp4 clips over local Wi-Fi to http://{host}
# ==============================================================================
set -euo pipefail

TWINSCAN_HOST="{host}"
DEVICE_ID="{dev_id}"
IMG_PATH="/piusb.bin"
IMG_SIZE_MB=2048
MNT_RO="/mnt/piusb_ro"
STATE_FILE="/var/lib/eigenia_harvested.txt"

echo "[1/5] Enabling dwc2 USB-OTG overlay in /boot/firmware/config.txt ..."
CFG="/boot/firmware/config.txt"
[ -f "$CFG" ] || CFG="/boot/config.txt"
grep -q "^dtoverlay=dwc2" "$CFG" || echo "dtoverlay=dwc2" | sudo tee -a "$CFG" >/dev/null
grep -q "^dwc2$" /etc/modules || echo "dwc2" | sudo tee -a /etc/modules >/dev/null

echo "[2/5] Creating ${{IMG_SIZE_MB}}MB FAT32 backing image at $IMG_PATH ..."
if [ ! -f "$IMG_PATH" ]; then
  sudo dd if=/dev/zero of="$IMG_PATH" bs=1M count="$IMG_SIZE_MB" status=progress
  sudo mkfs.vfat -F 32 -n EIGENIAUSB "$IMG_PATH"
fi
sudo mkdir -p "$MNT_RO"
sudo touch "$STATE_FILE"

echo "[3/5] Installing read-only clip harvester /usr/local/bin/eigenia-harvest-clips.sh ..."
sudo tee /usr/local/bin/eigenia-harvest-clips.sh >/dev/null <<'HARVESTER'
#!/usr/bin/env bash
set -euo pipefail
TWINSCAN_HOST="__HOST__"
DEVICE_ID="__DEVID__"
IMG_PATH="/piusb.bin"
MNT_RO="/mnt/piusb_ro"
STATE_FILE="/var/lib/eigenia_harvested.txt"

# Ensure USB gadget is loaded
if ! lsmod | grep -q g_mass_storage; then
  modprobe g_mass_storage file="$IMG_PATH" stall=0 removable=1 ro=0 || true
fi

# Safely inspect via read-only loop mount (never mount RW while USB host owns FAT)
mount -o loop,ro,noload "$IMG_PATH" "$MNT_RO" 2>/dev/null || mount -o loop,ro "$IMG_PATH" "$MNT_RO"
trap 'umount "$MNT_RO" 2>/dev/null || true' EXIT

find "$MNT_RO" -type f \\( -iname "*.mp4" -o -iname "*.jpg" \\) -mmin +0.5 2>/dev/null | sort | while read -r f; do
  rel="${{f#$MNT_RO/}}"
  if ! grep -Fxq "$rel" "$STATE_FILE"; then
    echo "[eigenia] Uploading local clip: $rel"
    if curl -fsS -m 25 -X POST "http://${{TWINSCAN_HOST}}/api/devices/cameras/ingest-media" \\
         -F "file=@${{f}}" \\
         -F "camera_name=${{DEVICE_ID}}" >/dev/null; then
      echo "$rel" >> "$STATE_FILE"
    fi
  fi
done
HARVESTER
sudo sed -i "s|__HOST__|${{TWINSCAN_HOST}}|g; s|__DEVID__|${{DEVICE_ID}}|g" /usr/local/bin/eigenia-harvest-clips.sh
sudo chmod +x /usr/local/bin/eigenia-harvest-clips.sh

echo "[4/5] Installing systemd service + 20s timer ..."
sudo tee /etc/systemd/system/eigenia-clip-harvester.service >/dev/null <<'EOF'
[Unit]
Description=Eigenia Local USB Clip Harvester (Read-Only Loop Mount)
After=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/eigenia-harvest-clips.sh
EOF

sudo tee /etc/systemd/system/eigenia-clip-harvester.timer >/dev/null <<'EOF'
[Unit]
Description=Run Eigenia Local USB Clip Harvester every 20 seconds

[Timer]
OnBootSec=25s
OnUnitActiveSec=20s
Unit=eigenia-clip-harvester.service

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now eigenia-clip-harvester.timer

echo "[5/5] Done! Reboot Pi Zero 2 W and plug its DATA micro-USB OTG port into Blink Sync Module 2."
"""
    return {
        "filename": f"setup_{dev_id}_gadget.sh",
        "script": script,
        "instructions": [
            "1. Connect Raspberry Pi Zero 2 W to your local Wildcat 2.4 GHz Wi-Fi network.",
            f"2. Copy and run `bash setup_{dev_id}_gadget.sh` on the Pi Zero 2 W, then `sudo reboot`.",
            "3. Plug a 4-wire micro-USB DATA cable from the Pi Zero's inner USB OTG port into the Blink Sync Module 2 USB-A slot.",
            f"4. Every 20s, new local .mp4 motion clips are read-only harvested and analyzed offline by TwinScan at http://{host}/api/devices/cameras/ingest-media (zero Amazon cloud!).",
        ],
    }


def _laplacian_sharpness(frame_bgr: np.ndarray) -> float:
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def extract_frames_from_media(
    media_bytes: bytes,
    filename: str = "frame.jpg",
    max_frames: int = 3,
) -> List[np.ndarray]:
    """Extract up to ``max_frames`` sharpest BGR frames from a local image or video clip.

    Supports ``.jpg/.jpeg/.png/.webp/.bmp`` directly via ``cv2.imdecode``, and
    ``.mp4/.mov/.avi/.mkv`` via temporary file + ``cv2.VideoCapture``, scoring evenly
    spaced samples by Laplacian variance so blurry motion frames are rejected.

    Args:
        media_bytes: Raw file bytes of an image or video clip.
        filename: Original filename (used to infer extension).
        max_frames: Maximum number of frames to return (clamped ``1..8``).

    Returns:
        List of OpenCV BGR ``np.ndarray`` frames.
    """
    if not media_bytes:
        return []
    limit = max(1, min(8, int(max_frames)))
    ext = os.path.splitext(str(filename or "frame.jpg"))[1].lower()

    # Try direct image decode first unless clearly a video container
    if ext not in (".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"):
        arr = np.frombuffer(media_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is not None and img.size > 0:
            return [img]

    suffix = ext if ext in (".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v") else ".mp4"
    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(media_bytes)
            tmp_path = tmp.name

        cap = cv2.VideoCapture(tmp_path)
        if not cap.isOpened():
            return []
        try:
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            candidates: List[Tuple[float, int, np.ndarray]] = []
            sample_budget = max(limit * 3, 9)

            if total > 0:
                step = max(1, total // sample_budget)
                indices = list(range(0, total, step))[:sample_budget]
                for idx in indices:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                    ok, frm = cap.read()
                    if ok and frm is not None and frm.size > 0:
                        candidates.append((_laplacian_sharpness(frm), idx, frm))
            else:
                idx = 0
                while len(candidates) < sample_budget and idx < 240:
                    ok, frm = cap.read()
                    if not ok or frm is None or frm.size == 0:
                        break
                    if idx % 5 == 0:
                        candidates.append((_laplacian_sharpness(frm), idx, frm))
                    idx += 1

            if not candidates:
                return []
            # Pick top `limit` sharpest frames, then restore chronological order
            candidates.sort(key=lambda item: item[0], reverse=True)
            chosen = sorted(candidates[:limit], key=lambda item: item[1])
            return [item[2] for item in chosen]
        finally:
            cap.release()
    except Exception as exc:
        sys.stderr.write(f"[local_camera_bridge] Video frame extraction failed for {filename}: {exc}\n")
        return []
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _grab_rtsp_frame_sync(stream_url: str, timeout: float = 6.0) -> bytes:
    cap = cv2.VideoCapture(stream_url)
    if not cap.isOpened():
        raise ConnectionError(f"Unable to open RTSP/video stream: {stream_url}")
    try:
        deadline = time.monotonic() + max(1.0, float(timeout))
        while time.monotonic() < deadline:
            ok, frm = cap.read()
            if ok and frm is not None and frm.size > 0:
                enc_ok, buf = cv2.imencode(".jpg", frm, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
                if enc_ok:
                    return buf.tobytes()
            time.sleep(0.05)
        raise TimeoutError(f"Timed out reading frame from {stream_url}")
    finally:
        cap.release()


async def fetch_lan_camera_frame(stream_url: str, timeout: float = 6.0) -> bytes:
    """Fetch a single JPEG frame from a local LAN HTTP snapshot or ``rtsp://`` camera URL.

    Retries up to 3 times on transient network failures and logs errors to ``sys.stderr``.

    Args:
        stream_url: Local ``http://...``, ``https://...``, or ``rtsp://...`` camera endpoint.
        timeout: Per-attempt timeout in seconds.

    Returns:
        Raw JPEG image bytes.

    Raises:
        ValueError: If the URL scheme is unsupported.
        ConnectionError: If all 3 attempts fail.
    """
    url = str(stream_url or "").strip()
    low = url.lower()
    if not low.startswith(("http://", "https://", "rtsp://")):
        raise ValueError("stream_url must start with http://, https://, or rtsp://")

    last_exc: Optional[Exception] = None
    for attempt in range(1, 4):
        try:
            if low.startswith("rtsp://"):
                return await asyncio.to_thread(_grab_rtsp_frame_sync, url, timeout)
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                if not resp.content:
                    raise ConnectionError("Empty response body from camera snapshot URL")
                return resp.content
        except Exception as exc:
            last_exc = exc
            sys.stderr.write(
                f"[local_camera_bridge] Fetch {url} failed (attempt {attempt}/3): {exc}\n"
            )
            if attempt < 3:
                await asyncio.sleep(0.4 * attempt)

    raise ConnectionError(f"Failed to fetch frame from {url} after 3 attempts: {last_exc}")


async def ingest_local_media_to_spatial_memory(
    ai_vision_engine: Any,
    ai_store: Any,
    repo: Any,
    camera_name: str,
    space_id: Optional[str] = None,
    robot_id: str = "local-camera",
    media_bytes: Optional[bytes] = None,
    filename: str = "frame.jpg",
    image_base64: Optional[str] = None,
    stream_url: Optional[str] = None,
    max_frames: int = 3,
) -> Dict[str, Any]:
    """Analyze a local camera image, video clip, or LAN stream offline and save sightings.

    Runs the existing local ONNX ``RobotAiVisionEngine`` (YOLO11n objects/animals +
    YuNet/SFace known people) completely offline inside Docker, stores JPEG frames in
    ``repo.store_file``, and records enriched entries in ``ai_store.record_spatial_sighting``
    tagged with ``camera_source="local_cam:<camera_name>"``.

    Args:
        ai_vision_engine: Active ``RobotAiVisionEngine`` instance.
        ai_store: ``RobotAiStoreProtocol`` implementation.
        repo: ``TwinScanRepositoryProtocol`` implementation for JPEG storage.
        camera_name: Display name of the local camera or clip source.
        space_id: Optional TwinScan space UUID.
        robot_id: Associated robot or device ID (defaults to ``"local-camera"``).
        media_bytes: Optional raw uploaded ``.jpg/.png/.mp4`` file bytes.
        filename: Original media filename.
        image_base64: Optional base64-encoded image string.
        stream_url: Optional LAN HTTP/RTSP camera URL.
        max_frames: Maximum frames extracted from video clips.

    Returns:
        Dictionary ``{ok, camera_source, frames_analyzed, recorded_count, sightings}``.
    """
    clean_cam = re.sub(r"[^A-Za-z0-9 _.\-]", "", str(camera_name or "Local Cam").strip())[:48] or "Local Cam"
    camera_source = f"local_cam:{clean_cam}"

    raw = media_bytes
    if raw is None and image_base64:
        b64 = image_base64.split(",", 1)[-1].strip()
        raw = base64.b64decode(b64)
    if raw is None and stream_url:
        raw = await fetch_lan_camera_frame(stream_url)
        filename = "snapshot.jpg"

    if not raw:
        raise ValueError("Provide an uploaded file, image_base64, or stream_url.")

    frames = await asyncio.to_thread(extract_frames_from_media, raw, filename, max_frames)
    if not frames:
        raise ValueError(f"Could not decode any video/image frames from {filename!r}.")

    recorded: List[Dict[str, Any]] = []
    ts_tag = int(time.time())

    for idx, frame_bgr in enumerate(frames):
        enc_ok, jpg_buf = cv2.imencode(".jpg", frame_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 86])
        if not enc_ok:
            continue
        jpg_bytes = jpg_buf.tobytes()
        stored = repo.store_file(
            filename=f"local-cam-{clean_cam.lower().replace(' ', '_')}-{ts_tag}-{idx}.jpg",
            content_type="image/jpeg",
            data=jpg_bytes,
            category="spatial_sighting",
            space_id=space_id,
            metadata={"camera_source": camera_source, "frame_index": idx},
        )
        snap_id = stored["id"]

        frame_sightings = 0
        # 1. Local face detection & recognition (YuNet + SFace)
        try:
            faces = await asyncio.to_thread(ai_vision_engine.detect_faces_and_embeddings, frame_bgr)
        except Exception as exc:
            sys.stderr.write(f"[local_camera_bridge] Face detection skipped: {exc}\n")
            faces = []

        for face in faces:
            match = ai_store.match_face_embedding(face["embedding"], threshold=0.363)
            label = match["person"]["name"] if match else "Unknown Person"
            conf = float(match["similarity"] if match else face.get("confidence", 0.7))
            rec = ai_store.record_spatial_sighting(
                robot_id,
                {
                    "space_id": space_id,
                    "label": label,
                    "kind": "face",
                    "x_m": 0.0,
                    "y_m": 0.0,
                    "confidence": round(conf, 3),
                    "snapshot_file_id": snap_id,
                    "notes": f"Captured locally from {clean_cam} (frame #{idx + 1})",
                    "camera_source": camera_source,
                    "tags": ["local-camera", clean_cam.lower().replace(" ", "-"), "face"],
                },
            )
            recorded.append(rec)
            frame_sightings += 1

        # 2. Local YOLO11n object & animal detection
        try:
            objs = await asyncio.to_thread(ai_vision_engine.detect_objects_and_animals, frame_bgr, 0.35)
        except Exception as exc:
            sys.stderr.write(f"[local_camera_bridge] Object detection skipped: {exc}\n")
            objs = []

        seen_labels = set()
        for obj in objs[:6]:
            lbl = str(obj.get("label") or "object")
            if lbl in seen_labels:
                continue
            seen_labels.add(lbl)
            kind = "animal" if obj.get("is_animal") else "object"
            rec = ai_store.record_spatial_sighting(
                robot_id,
                {
                    "space_id": space_id,
                    "label": lbl,
                    "kind": kind,
                    "x_m": 0.0,
                    "y_m": 0.0,
                    "confidence": round(float(obj.get("confidence", 0.5)), 3),
                    "snapshot_file_id": snap_id,
                    "notes": f"Detected offline on {clean_cam} (frame #{idx + 1})",
                    "camera_source": camera_source,
                    "tags": ["local-camera", clean_cam.lower().replace(" ", "-"), kind],
                },
            )
            recorded.append(rec)
            frame_sightings += 1

        # 3. Always retain at least one scene snapshot record if frame had no detections
        if frame_sightings == 0:
            rec = ai_store.record_spatial_sighting(
                robot_id,
                {
                    "space_id": space_id,
                    "label": f"{clean_cam} Scene",
                    "kind": "scene",
                    "x_m": 0.0,
                    "y_m": 0.0,
                    "confidence": 1.0,
                    "snapshot_file_id": snap_id,
                    "notes": f"Offline local camera capture from {clean_cam} ({filename})",
                    "camera_source": camera_source,
                    "tags": ["local-camera", clean_cam.lower().replace(" ", "-"), "scene"],
                },
            )
            recorded.append(rec)

    return {
        "ok": True,
        "camera_source": camera_source,
        "frames_analyzed": len(frames),
        "recorded_count": len(recorded),
        "sightings": recorded,
    }
