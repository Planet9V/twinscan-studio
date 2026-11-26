"""Stage 1 multi-variant industrial image enhancement (CLAHE + Unsharp + Adaptive) and barcode decoding."""

from __future__ import annotations

import sys
from typing import Any, List, Tuple

import cv2
import numpy as np
import zxingcpp

from src.vision.schemas import BarcodeMatch


def preprocess_industrial_image(image_bytes: bytes) -> Tuple[bytes, dict[str, Any]]:
    """Apply CLAHE glare normalization and unsharp-mask clarity enhancement for metallic plates.

    Args:
        image_bytes: Raw uploaded image bytes (JPEG/PNG/WEBP).

    Returns:
        Tuple ``(enhanced_jpeg_bytes, metadata_dict)``.

    Raises:
        ValueError: If the byte buffer cannot be decoded as a valid image.
    """
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Unable to decode image bytes with OpenCV.")

    height, width = img.shape[:2]
    max_edge = 1800
    if max(height, width) > max_edge:
        scale = max_edge / float(max(height, width))
        img = cv2.resize(img, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_AREA)
        height, width = img.shape[:2]

    # Pass A: Luminance CLAHE to tame metallic glare without shifting color labels.
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l_chan, a_chan, b_chan = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.2, tileGridSize=(8, 8))
    l_enhanced = clahe.apply(l_chan)
    merged = cv2.merge((l_enhanced, a_chan, b_chan))
    enhanced_bgr = cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)

    # Pass B: Gentle unsharp mask to sharpen stamped/laser-etched serial digits.
    blurred = cv2.GaussianBlur(enhanced_bgr, (0, 0), sigmaX=1.2)
    sharpened = cv2.addWeighted(enhanced_bgr, 1.35, blurred, -0.35, 0)

    ok, encoded = cv2.imencode(".jpg", sharpened, [int(cv2.IMWRITE_JPEG_QUALITY), 93])
    if not ok:
        raise ValueError("Failed to encode preprocessed JPEG image.")

    return encoded.tobytes(), {
        "width": int(width),
        "height": int(height),
        "clahe_applied": True,
        "unsharp_applied": True,
    }


def decode_industrial_barcodes(image_bytes: bytes) -> List[BarcodeMatch]:
    """Run multi-pass zxing-cpp decoding (raw, CLAHE, sharpened, adaptive threshold) for DPM/DataMatrix.

    Args:
        image_bytes: Raw image bytes.

    Returns:
        Deduplicated list of ``BarcodeMatch`` objects.
    """
    try:
        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        gray = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
        if gray is None:
            return []

        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        blurred = cv2.GaussianBlur(enhanced, (0, 0), sigmaX=1.0)
        sharpened = cv2.addWeighted(enhanced, 1.5, blurred, -0.5, 0)
        adaptive = cv2.adaptiveThreshold(
            enhanced, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 7
        )

        seen: set[tuple[str, str]] = set()
        matches: List[BarcodeMatch] = []

        for frame in (gray, enhanced, sharpened, adaptive):
            results = zxingcpp.read_barcodes(frame)
            for res in results:
                fmt = str(res.format).split(".")[-1]
                text = (res.text or "").strip()
                if not text or (fmt, text) in seen:
                    continue
                seen.add((fmt, text))
                pos = res.position
                corners = [
                    [int(pos.top_left.x), int(pos.top_left.y)],
                    [int(pos.top_right.x), int(pos.top_right.y)],
                    [int(pos.bottom_right.x), int(pos.bottom_right.y)],
                    [int(pos.bottom_left.x), int(pos.bottom_left.y)],
                ]
                matches.append(BarcodeMatch(format=fmt, text=text, position=corners))
        return matches
    except Exception as exc:
        sys.stderr.write(f"[vision.preprocessor] Barcode decode error: {exc}\n")
        return []
