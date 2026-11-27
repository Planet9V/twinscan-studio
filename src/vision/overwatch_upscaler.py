"""Tiered ROI Super-Resolution for Overwatch Target Inspection.

Provides:
- Tier 2 (Offline, <50 ms, $0): High-res ROI crop + Lanczos 2x/4x + LAB CLAHE + Unsharp Mask.
- Tier 3 (Optional Cloud AI via ``fal.ai``): Sends ONLY the cropped target ROI to
  ``fal-ai/esrgan`` or ``fal-ai/clarity-upscaler`` using a Fernet-encrypted ``fal_api_key``
  from PostgreSQL ``app_settings`` (wrapped in ``try/except``, logging to ``sys.stderr``,
  retrying up to 3x, with mandatory ``ai_generated_warning=True``).
"""

from __future__ import annotations

import asyncio
import base64
import sys
import time
from typing import Any, Dict, Sequence, Tuple

import cv2
import httpx
import numpy as np

ALLOWED_FAL_UPSCALE_MODELS = frozenset({"fal-ai/esrgan", "fal-ai/clarity-upscaler"})


def _b64_data_url(jpeg_bytes: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(jpeg_bytes).decode("ascii")


def _crop_roi(
    raw_jpeg: bytes,
    bbox_norm: Sequence[float],
    padding_ratio: float = 0.12,
) -> Tuple[np.ndarray, Tuple[int, int]]:
    """Decode ``raw_jpeg`` and crop ``bbox_norm`` with safe context padding."""
    if not raw_jpeg:
        raise ValueError("Empty JPEG frame; cannot extract ROI crop.")
    arr = np.frombuffer(raw_jpeg, dtype=np.uint8)
    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if frame is None or frame.size == 0:
        raise ValueError("Invalid JPEG frame bytes.")

    h, w = frame.shape[:2]
    if len(bbox_norm) < 4:
        raise ValueError("bbox_norm must contain 4 normalized coordinates [x1, y1, x2, y2].")
    x1, y1, x2, y2 = [max(0.0, min(1.0, float(v))) for v in bbox_norm[:4]]
    if x2 <= x1 or y2 <= y1:
        raise ValueError("Invalid bounding box: x2 must be > x1 and y2 must be > y1.")

    bw = x2 - x1
    bh = y2 - y1
    pad_x = bw * padding_ratio
    pad_y = bh * padding_ratio
    px1 = max(0, min(w - 2, int((x1 - pad_x) * w)))
    py1 = max(0, min(h - 2, int((y1 - pad_y) * h)))
    px2 = max(px1 + 2, min(w, int((x2 + pad_x) * w)))
    py2 = max(py1 + 2, min(h, int((y2 + pad_y) * h)))
    crop = frame[py1:py2, px1:px2]
    return crop, (int(crop.shape[1]), int(crop.shape[0]))


def extract_and_enhance_local_roi(
    raw_jpeg: bytes,
    bbox_norm: Sequence[float],
    scale: int = 2,
) -> Dict[str, Any]:
    """Extract a target ROI crop and run fast local Lanczos + LAB CLAHE + Unsharp Mask enhancement.

    Args:
        raw_jpeg: Raw full-resolution JPEG bytes from the camera buffer.
        bbox_norm: Normalized target bounding box ``[x1, y1, x2, y2]``.
        scale: Upscale factor (``2`` or ``4``, clamped to ``[1, 4]``).

    Returns:
        Dictionary containing ``raw_crop_b64``, ``enhanced_b64``, dimensions, latency, and
        ``ai_generated_warning: False``.
    """
    t0 = time.perf_counter()
    crop, (cw, ch) = _crop_roi(raw_jpeg, bbox_norm)
    s = max(1, min(4, int(scale)))
    # Cap max output dimension to 2048px to protect memory
    target_w = min(2048, max(2, cw * s))
    target_h = min(2048, max(2, ch * s))

    upscaled = cv2.resize(crop, (target_w, target_h), interpolation=cv2.INTER_LANCZOS4)
    # Local contrast enhancement in LAB space (preserves color fidelity)
    lab = cv2.cvtColor(upscaled, cv2.COLOR_BGR2LAB)
    l_chan, a_chan, b_chan = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.2, tileGridSize=(8, 8))
    l_eq = clahe.apply(l_chan)
    enhanced = cv2.cvtColor(cv2.merge([l_eq, a_chan, b_chan]), cv2.COLOR_LAB2BGR)
    # Gentle unsharp mask for crisp edges/text
    blurred = cv2.GaussianBlur(enhanced, (0, 0), sigmaX=1.2)
    enhanced = cv2.addWeighted(enhanced, 1.35, blurred, -0.35, 0)

    ok_raw, raw_buf = cv2.imencode(".jpg", crop, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    ok_enh, enh_buf = cv2.imencode(".jpg", enhanced, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    if not ok_raw or not ok_enh:
        raise ValueError("Failed to encode ROI crop JPEG.")

    latency_ms = round((time.perf_counter() - t0) * 1000.0, 1)
    return {
        "ok": True,
        "method": "local_lanczos_clahe",
        "model": "opencv_lanczos_clahe",
        "scale": s,
        "raw_size": [cw, ch],
        "enhanced_size": [target_w, target_h],
        "raw_crop_b64": _b64_data_url(raw_buf.tobytes()),
        "enhanced_b64": _b64_data_url(enh_buf.tobytes()),
        "latency_ms": latency_ms,
        "ai_generated_warning": False,
    }


async def upscale_roi_fal_ai(
    raw_jpeg: bytes,
    bbox_norm: Sequence[float],
    api_key: str,
    model: str = "fal-ai/esrgan",
    scale: int = 2,
    timeout_sec: float = 45.0,
) -> Dict[str, Any]:
    """Crop a target ROI and upscale it via ``fal.ai`` with 3x retry and side-by-side raw output.

    Args:
        raw_jpeg: Raw full-resolution JPEG bytes from the camera buffer.
        bbox_norm: Normalized target bounding box ``[x1, y1, x2, y2]``.
        api_key: Decrypted ``fal_api_key`` from PostgreSQL ``app_settings``.
        model: ``fal-ai/esrgan`` or ``fal-ai/clarity-upscaler``.
        scale: Upscale factor (``2`` or ``4``).
        timeout_sec: HTTP request timeout per attempt.

    Returns:
        Dictionary containing ``raw_crop_b64``, ``enhanced_b64`` (or remote URL), latency,
        and mandatory ``ai_generated_warning: True``.

    Raises:
        ValueError: If ``api_key`` is missing or ``model`` is unsupported.
        RuntimeError: If all 3 ``fal.ai`` attempts fail.
    """
    clean_key = (api_key or "").strip()
    if not clean_key:
        raise ValueError("fal_api_key is not configured. Add it in /config (Vision & AI section) to enable cloud AI upscaling.")

    clean_model = (model or "fal-ai/esrgan").strip()
    if clean_model not in ALLOWED_FAL_UPSCALE_MODELS:
        raise ValueError(f"Unsupported fal.ai model {clean_model!r}; allowed: {sorted(ALLOWED_FAL_UPSCALE_MODELS)}")

    t0 = time.perf_counter()
    crop, (cw, ch) = _crop_roi(raw_jpeg, bbox_norm)
    s = max(2, min(4, int(scale)))
    ok_raw, raw_buf = cv2.imencode(".jpg", crop, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    if not ok_raw:
        raise ValueError("Failed to encode ROI crop JPEG.")
    raw_data_url = _b64_data_url(raw_buf.tobytes())

    endpoint = f"https://fal.run/{clean_model}"
    payload: Dict[str, Any] = {"image_url": raw_data_url}
    if clean_model == "fal-ai/esrgan":
        payload["scale"] = s
    else:
        payload["upscale_factor"] = s
        payload["creativity"] = 0.2
        payload["resemblance"] = 0.85

    headers = {
        "Authorization": f"Key {clean_key}",
        "Content-Type": "application/json",
    }

    last_err: Exception | None = None
    result_json: Dict[str, Any] | None = None
    for attempt in range(1, 4):
        try:
            async with httpx.AsyncClient(timeout=timeout_sec) as client:
                resp = await client.post(endpoint, json=payload, headers=headers)
                resp.raise_for_status()
                result_json = resp.json()
                break
        except Exception as exc:
            last_err = exc
            sys.stderr.write(f"[overwatch.fal_upscale] Attempt {attempt}/3 failed ({clean_model}): {exc}\n")
            if attempt < 3:
                await asyncio.sleep(0.5 * attempt)

    if result_json is None:
        raise RuntimeError(f"fal.ai upscale failed after 3 attempts: {last_err}")

    image_obj = result_json.get("image") or {}
    out_url = str(image_obj.get("url") or "")
    if not out_url:
        raise RuntimeError("fal.ai response did not include an output image URL.")

    # Fetch upscaled image bytes so UI renders reliably even without external CORS
    enhanced_b64 = out_url
    out_w = int(image_obj.get("width") or (cw * s))
    out_h = int(image_obj.get("height") or (ch * s))
    if out_url.startswith("http://") or out_url.startswith("https://"):
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                img_resp = await client.get(out_url)
                img_resp.raise_for_status()
                ctype = img_resp.headers.get("content-type", "image/png").split(";")[0].strip()
                enhanced_b64 = f"data:{ctype};base64," + base64.b64encode(img_resp.content).decode("ascii")
        except Exception as exc:
            sys.stderr.write(f"[overwatch.fal_upscale] Image download fallback to URL: {exc}\n")

    latency_ms = round((time.perf_counter() - t0) * 1000.0, 1)
    return {
        "ok": True,
        "method": "fal_ai_upscale",
        "model": clean_model,
        "scale": s,
        "raw_size": [cw, ch],
        "enhanced_size": [out_w, out_h],
        "raw_crop_b64": raw_data_url,
        "enhanced_b64": enhanced_b64,
        "latency_ms": latency_ms,
        "ai_generated_warning": True,
        "warning_text": "AI-ENHANCED — Verify fine text, serials, or faces against the untouched Raw Crop.",
    }
