"""Compositional Photo-to-3D PBR ``.glb`` Factory & Multi-Photo Wall Stitcher.

Converts any tagged/boxed room object (guitar, lamp, ceramic mug, books) into
a real Three.js-ready ``.glb`` mesh via:
- **Local Instant 3D (``local_depth3d``):** Zero-cost offline textured 3D relief
  & extruded box/slab mesh using OpenCV + ``trimesh`` + PIL.
- **Cloud Full-360° PBR 3D (``fal.ai``):** Calls ``fal-ai/trellis-2``,
  ``fal-ai/hunyuan-3d/v3.1/pro/image-to-3d``, ``fal-ai/hunyuan-3d/v3.1/rapid/image-to-3d``,
  or ``tripo3d/tripo/v2.5/image-to-3d`` using the encrypted ``fal_api_key`` in
  PostgreSQL 18 (3x retry + ``sys.stderr`` logging).
"""

from __future__ import annotations

import asyncio
import base64
import sys
from typing import Any, Dict, List, Sequence, Tuple

import cv2
import httpx
import numpy as np
import trimesh

ALLOWED_3D_ENGINES = frozenset(
    {
        "local_depth3d",
        "fal-ai/trellis-2",
        "fal-ai/hunyuan-3d/v3.1/pro/image-to-3d",
        "fal-ai/hunyuan-3d/v3.1/rapid/image-to-3d",
        "tripo3d/tripo/v2.5/image-to-3d",
    }
)

MAX_FAL_RETRIES = 3


def crop_object_from_photo(
    photo_bytes: bytes,
    bbox_norm: Sequence[float],
    padding_ratio: float = 0.08,
) -> Tuple[bytes, str, Tuple[int, int]]:
    """Crop an object region from a room photo and return PNG bytes + base64 preview.

    Args:
        photo_bytes: Original uploaded room photo bytes.
        bbox_norm: Normalized ``[x1, y1, x2, y2]`` coordinates.
        padding_ratio: Context border fraction around the box.

    Returns:
        Tuple ``(png_bytes, data_url_preview, (crop_w, crop_h))``.
    """
    arr = np.frombuffer(photo_bytes, dtype=np.uint8)
    bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if bgr is None or bgr.size == 0:
        raise ValueError("Invalid source photo bytes.")
    h, w = bgr.shape[:2]
    x1, y1, x2, y2 = [max(0.0, min(1.0, float(v))) for v in (list(bbox_norm) + [0.1, 0.1, 0.9, 0.9])[:4]]
    if x2 <= x1 or y2 <= y1:
        raise ValueError("Invalid bbox_norm: x2 > x1 and y2 > y1 required.")

    pad_x = (x2 - x1) * padding_ratio
    pad_y = (y2 - y1) * padding_ratio
    px1 = max(0, min(w - 2, int((x1 - pad_x) * w)))
    py1 = max(0, min(h - 2, int((y1 - pad_y) * h)))
    px2 = max(px1 + 2, min(w, int((x2 + pad_x) * w)))
    py2 = max(py1 + 2, min(h, int((y2 + pad_y) * h)))
    crop = bgr[py1:py2, px1:px2]

    # Limit max crop dimension to 1024px for fast cloud/local 3D synthesis
    ch, cw = crop.shape[:2]
    max_dim = max(cw, ch)
    if max_dim > 1024:
        scale = 1024.0 / max_dim
        crop = cv2.resize(crop, (max(2, int(cw * scale)), max(2, int(ch * scale))), interpolation=cv2.INTER_AREA)
        ch, cw = crop.shape[:2]

    ok, enc = cv2.imencode(".png", crop)
    if not ok:
        raise RuntimeError("Failed encoding cropped object PNG.")
    png_bytes = enc.tobytes()
    preview_b64 = "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")
    return png_bytes, preview_b64, (int(cw), int(ch))


def generate_local_depth_glb(
    crop_png_bytes: bytes,
    dimensions_m: Sequence[float] = (0.35, 0.45, 0.12),
) -> bytes:
    """Synthesize a real colored 3D ``.glb`` relief mesh offline from a cropped object photo.

    Builds a front-facing high-detail vertex-colored heightfield mesh with smooth
    luminance-derived relief + solid back volume using only ``cv2``, ``numpy``, and
    ``trimesh`` so it renders cleanly from any Three.js orbit angle.

    Args:
        crop_png_bytes: Cropped object image bytes (PNG/JPEG).
        dimensions_m: Target physical ``[width_m, height_m, depth_m]`` in meters.

    Returns:
        Binary ``.glb`` bytes ready for ``GLTFLoader``.
    """
    arr = np.frombuffer(crop_png_bytes, dtype=np.uint8)
    bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if bgr is None or bgr.size == 0:
        raise ValueError("Invalid cropped image bytes for local 3D generation.")
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

    w_m = max(0.05, float(dimensions_m[0]) if len(dimensions_m) > 0 else 0.35)
    h_m = max(0.05, float(dimensions_m[1]) if len(dimensions_m) > 1 else 0.45)
    d_m = max(0.03, float(dimensions_m[2]) if len(dimensions_m) > 2 else 0.12)

    gx, gy = 48, 48
    rgb_grid = cv2.resize(rgb, (gx, gy), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(rgb_grid, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255.0

    u_lin = np.linspace(0.0, 1.0, gx)
    v_lin = np.linspace(0.0, 1.0, gy)
    uu, vv = np.meshgrid(u_lin, v_lin)
    pillow = np.sin(np.pi * uu) * np.sin(np.pi * vv)
    z_front = (0.25 + 0.55 * pillow + 0.20 * gray) * d_m - (d_m * 0.5)

    xs = (uu - 0.5) * w_m
    ys = (0.5 - vv) * h_m

    verts_front = np.stack([xs, ys, z_front], axis=-1).reshape(-1, 3)
    alpha_col = np.full((gx * gy, 1), 255, dtype=np.uint8)
    vcolors = np.concatenate([rgb_grid.reshape(-1, 3), alpha_col], axis=1)

    faces_front: List[List[int]] = []
    for r in range(gy - 1):
        for c in range(gx - 1):
            i0 = r * gx + c
            i1 = i0 + 1
            i2 = i0 + gx
            i3 = i2 + 1
            faces_front.append([i0, i2, i1])
            faces_front.append([i1, i2, i3])

    front_mesh = trimesh.Trimesh(
        vertices=verts_front,
        faces=np.asarray(faces_front, dtype=np.int64),
        vertex_colors=vcolors,
        process=False,
    )

    avg_rgb = rgb_grid.reshape(-1, 3).astype(np.float32).mean(axis=0).astype(np.uint8)
    back_box = trimesh.creation.box(extents=[w_m * 0.96, h_m * 0.96, d_m * 0.45])
    back_box.apply_translation([0.0, 0.0, -d_m * 0.26])
    back_box.visual.face_colors = [int(avg_rgb[0]), int(avg_rgb[1]), int(avg_rgb[2]), 255]

    scene = trimesh.Scene()
    scene.add_geometry(front_mesh, node_name="object_front_relief")
    scene.add_geometry(back_box, node_name="object_body_volume")
    glb_data = scene.export(file_type="glb")
    return bytes(glb_data)


async def generate_fal_3d_glb(
    *,
    crop_png_bytes: bytes,
    fal_api_key: str,
    model_id: str = "fal-ai/trellis-2",
) -> bytes:
    """Call ``fal.ai`` Image-to-3D (TRELLIS-2 / Hunyuan3D v3.1 / Tripo) to synthesize a full-360° PBR ``.glb``.

    Args:
        crop_png_bytes: Cropped PNG image bytes of the target object.
        fal_api_key: Decrypted ``fal.ai`` API key from PostgreSQL ``app_settings``.
        model_id: Allowed fal.ai 3D endpoint identifier.

    Returns:
        Downloaded binary ``.glb`` mesh payload.
    """
    if model_id not in ALLOWED_3D_ENGINES or model_id == "local_depth3d":
        raise ValueError(f"Unsupported cloud 3D engine: {model_id}")
    if not fal_api_key:
        raise ValueError("fal_api_key is not configured in Settings (/config).")

    data_url = "data:image/png;base64," + base64.b64encode(crop_png_bytes).decode("ascii")
    if "hunyuan" in model_id:
        payload: Dict[str, Any] = {"input_image_url": data_url}
    else:
        payload = {"image_url": data_url}

    endpoint = f"https://fal.run/{model_id}"
    headers = {
        "Authorization": f"Key {fal_api_key}",
        "Content-Type": "application/json",
    }

    last_err = "unknown"
    for attempt in range(1, MAX_FAL_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=180.0, follow_redirects=True) as client:
                resp = await client.post(endpoint, headers=headers, json=payload)
                resp.raise_for_status()
                body = resp.json()
                mesh_url = (
                    (body.get("model_mesh") or {}).get("url")
                    or (body.get("model_glb") or {}).get("url")
                    or (body.get("glb") or {}).get("url")
                    or (body.get("mesh") or {}).get("url")
                    or body.get("model_url")
                )
                if not mesh_url:
                    raise RuntimeError(f"fal.ai response did not include a .glb mesh URL: {list(body.keys())}")
                dl = await client.get(str(mesh_url))
                dl.raise_for_status()
                return bytes(dl.content)
        except Exception as exc:
            last_err = str(exc)
            sys.stderr.write(
                f"[room_studio.fal3d] {model_id} failed attempt {attempt}/{MAX_FAL_RETRIES}: {exc}\n"
            )
            if attempt < MAX_FAL_RETRIES:
                await asyncio.sleep(2.0 * attempt)

    raise RuntimeError(f"fal.ai 3D generation ({model_id}) failed after {MAX_FAL_RETRIES} retries: {last_err}")


def stitch_surface_photos(photo_blobs: Sequence[bytes]) -> Tuple[bytes, str]:
    """Stitch multiple photos of the same wall into one high-resolution panorama texture.

    Uses OpenCV ``Stitcher`` when >= 2 overlapping images are provided, falling back
    gracefully to seamless horizontal compositing when overlap is too sparse.

    Args:
        photo_blobs: Sequence of raw JPEG/PNG image payloads.

    Returns:
        Tuple ``(jpeg_bytes, method_used)``.
    """
    imgs: List[np.ndarray] = []
    for raw in photo_blobs:
        arr = np.frombuffer(raw, dtype=np.uint8)
        im = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if im is not None and im.size > 0:
            # Cap each input to 1600px wide for reliable RAM usage
            h, w = im.shape[:2]
            if w > 1600:
                scale = 1600.0 / w
                im = cv2.resize(im, (1600, max(2, int(h * scale))), interpolation=cv2.INTER_AREA)
            imgs.append(im)

    if not imgs:
        raise ValueError("No valid images provided for wall stitching.")

    method = "single_photo"
    stitched = imgs[0]
    if len(imgs) >= 2:
        try:
            stitcher = cv2.Stitcher_create(cv2.Stitcher_SCANS)
            status, pano = stitcher.stitch(imgs)
            if status == cv2.Stitcher_OK and pano is not None and pano.size > 0:
                stitched = pano
                method = "opencv_homography_stitch"
            else:
                raise RuntimeError(f"Stitcher status={status}")
        except Exception as exc:
            sys.stderr.write(f"[room_studio.stitch] OpenCV Stitcher fallback ({exc}); horizontal blend.\n")
            target_h = min(1024, min(im.shape[0] for im in imgs))
            resized = [
                cv2.resize(im, (max(2, int(im.shape[1] * (target_h / im.shape[0]))), target_h), interpolation=cv2.INTER_AREA)
                for im in imgs
            ]
            stitched = np.concatenate(resized, axis=1)
            method = "horizontal_mosaic_fallback"

    ok, enc = cv2.imencode(".jpg", stitched, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    if not ok:
        raise RuntimeError("Failed encoding stitched wall JPEG.")
    return enc.tobytes(), method
