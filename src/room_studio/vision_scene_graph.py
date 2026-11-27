"""CAST-inspired Vision Scene Graph Parser, Physics-Aware 6-DoF Placement & Next-Best-View Coach.

Parses uploaded room photos into a structured compositional scene graph
(objects, bounding boxes, support relationships like ``WALL_MOUNTED`` or
``ON_SURFACE``, physical dimensions), computes collision-free 6-DoF Three.js
transforms inside the room shell, and generates Next-Best-View 3D ghost camera
frustums to guide high-coverage capture.
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

import httpx

from src.room_studio.models import DEFAULT_SURFACE_CAMERA_POSES

MAX_VISION_RETRIES = 3

VISION_SCENE_PROMPT = """You are a 3D Computer Vision Scene-Graph Analyst (CAST / MIDI-3D pipeline).
Inspect this room photo (tagged surface: {surface}, user notes: {notes}).
Identify every distinct physical object that should become an individual Three.js 3D asset
(e.g., guitar on wall, desk lamp, ceramic mug, books, chair, monitor, speaker, plant, shelf, frame).

Return ONLY valid JSON matching this exact schema:
{{
  "summary": "1-sentence description of what this photo shows",
  "objects": [
    {{
      "name": "Acoustic Guitar",
      "category": "instrument",
      "bbox_norm": [0.15, 0.20, 0.38, 0.72],
      "support_type": "WALL_MOUNTED",
      "support_surface": "{surface}",
      "dimensions_m": [0.38, 1.02, 0.12],
      "color_hex": "#c68b59",
      "confidence": 0.94,
      "notes": "Hanging vertically on wall mount"
    }}
  ]
}}

Rules:
- bbox_norm is [x1, y1, x2, y2] normalized 0..1 with x2 > x1 and y2 > y1.
- support_type MUST be one of: WALL_MOUNTED, ON_FLOOR, ON_SURFACE, CEILING.
- dimensions_m is [width_m, height_m, depth_m] in realistic meters.
- Return up to 12 most prominent objects. Return raw JSON only, no markdown fences.
"""


def compute_physics_placement(
    *,
    room_width_m: float,
    room_length_m: float,
    room_height_m: float,
    support_type: str,
    support_surface: str,
    bbox_norm: Sequence[float],
    dimensions_m: Sequence[float],
) -> Dict[str, float]:
    """Compute a physics-grounded Three.js 6-DoF pose ``(x, y, z, rx, ry, rz, scale)``.

    Uses Three.js Y-up right-handed room coordinates centered on the floor:
    - ``X`` in ``[-W/2, +W/2]`` (West = ``-W/2``, East = ``+W/2``)
    - ``Y`` in ``[0, H]`` (Floor = ``0``, Ceiling = ``H``)
    - ``Z`` in ``[-L/2, +L/2]`` (North = ``-L/2``, South = ``+L/2``)

    Args:
        room_width_m: Room width along X in meters.
        room_length_m: Room length along Z in meters.
        room_height_m: Room ceiling height along Y in meters.
        support_type: ``WALL_MOUNTED``, ``ON_FLOOR``, ``ON_SURFACE``, or ``CEILING``.
        support_surface: Tagged wall/surface identifier (e.g. ``west_wall``).
        bbox_norm: Normalized ``[x1, y1, x2, y2]`` box in the source photo.
        dimensions_m: Estimated object ``[width, height, depth]`` in meters.

    Returns:
        Dictionary with ``x, y, z, rx, ry, rz, scale`` ready for Three.js.
    """
    w = max(1.5, float(room_width_m))
    l = max(1.5, float(room_length_m))
    h = max(1.8, float(room_height_m))

    ow = max(0.05, float(dimensions_m[0]) if len(dimensions_m) > 0 else 0.35)
    oh = max(0.05, float(dimensions_m[1]) if len(dimensions_m) > 1 else 0.45)
    od = max(0.05, float(dimensions_m[2]) if len(dimensions_m) > 2 else 0.25)

    x1, y1, x2, y2 = [max(0.0, min(1.0, float(v))) for v in (list(bbox_norm) + [0.3, 0.3, 0.7, 0.7])[:4]]
    u_center = (x1 + x2) * 0.5  # 0 left -> 1 right
    v_center = (y1 + y2) * 0.5  # 0 top -> 1 bottom
    lateral = (u_center - 0.5) * 0.82  # keep within 82% of wall span to prevent corner clipping

    st = str(support_type or "ON_FLOOR").upper()
    surf = str(support_surface or "north_wall").lower()

    # Default floor Y based on support physics
    if st == "ON_FLOOR":
        y_pos = oh * 0.5
    elif st == "ON_SURFACE":
        y_pos = 0.76 + oh * 0.5  # Standard desk/table height (0.76m)
    elif st == "CEILING":
        y_pos = max(0.4, h - oh * 0.5 - 0.02)
    else:
        # WALL_MOUNTED: map image vertical position onto wall height
        y_pos = max(oh * 0.5 + 0.15, min(h - oh * 0.5 - 0.15, (1.0 - v_center) * h))

    # Wall normal offset so objects sit flush against walls without Z-fighting
    wall_offset = od * 0.5 + 0.02
    if st in {"ON_FLOOR", "ON_SURFACE"}:
        # Place slightly in front of the tagged wall
        wall_offset = max(od * 0.5 + 0.28, 0.42)

    rx, ry, rz = 0.0, 0.0, 0.0
    if surf == "north_wall":
        x_pos = lateral * w
        z_pos = -l * 0.5 + wall_offset
        ry = 0.0
    elif surf == "south_wall":
        x_pos = -lateral * w
        z_pos = l * 0.5 - wall_offset
        ry = 180.0
    elif surf == "west_wall":
        x_pos = -w * 0.5 + wall_offset
        z_pos = -lateral * l
        ry = 90.0
    elif surf == "east_wall":
        x_pos = w * 0.5 - wall_offset
        z_pos = lateral * l
        ry = -90.0
    else:
        x_pos = lateral * w * 0.7
        z_pos = (v_center - 0.5) * l * 0.6
        ry = 0.0

    return {
        "x": round(x_pos, 3),
        "y": round(y_pos, 3),
        "z": round(z_pos, 3),
        "rx": round(rx, 2),
        "ry": round(ry, 2),
        "rz": round(rz, 2),
        "scale": 1.0,
    }


def _extract_json_block(text: str) -> Dict[str, Any]:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        cleaned = cleaned[start : end + 1]
    parsed = json.loads(cleaned)
    return parsed if isinstance(parsed, dict) else {}


async def parse_room_photo_objects(
    *,
    image_bytes: bytes,
    surface: str,
    notes: str = "",
    openrouter_api_key: Optional[str] = None,
    openrouter_model: str = "google/gemini-2.5-flash",
) -> Dict[str, Any]:
    """Parse an uploaded room photo into a CAST-style semantic object scene graph.

    Calls OpenRouter Vision when configured (3x retry + ``sys.stderr`` logging).
    Falls back gracefully to a structured manual-ready response if no API key is set.

    Args:
        image_bytes: Raw JPEG/PNG image bytes.
        surface: Tagged wall/surface name (e.g. ``west_wall``).
        notes: Optional user tags or description.
        openrouter_api_key: Decrypted OpenRouter API key.
        openrouter_model: Vision-capable OpenRouter model ID.

    Returns:
        Dictionary with ``ok``, ``provider``, ``summary``, and ``objects`` list.
    """
    if not image_bytes:
        raise ValueError("Empty image payload.")

    if not openrouter_api_key:
        return {
            "ok": True,
            "provider": "manual_ready",
            "summary": "Photo stored. Configure OpenRouter API key in Settings for automatic Vision object extraction, or draw boxes manually.",
            "objects": [],
        }

    b64 = base64.b64encode(image_bytes).decode("ascii")
    mime = "image/png" if image_bytes[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
    prompt = VISION_SCENE_PROMPT.format(surface=surface, notes=notes or "none")

    payload = {
        "model": openrouter_model or "google/gemini-2.5-flash",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                ],
            }
        ],
        "temperature": 0.15,
        "max_tokens": 1800,
    }
    headers = {
        "Authorization": f"Bearer {openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://twinscan.eigenia.local",
        "X-Title": "Eigenia Room Twin Studio",
    }

    last_err = "unknown"
    for attempt in range(1, MAX_VISION_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                resp = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers=headers,
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
            content = str(data["choices"][0]["message"]["content"] or "")
            parsed = _extract_json_block(content)
            raw_objs = parsed.get("objects") or []
            clean_objs: List[Dict[str, Any]] = []
            for item in raw_objs:
                if not isinstance(item, dict):
                    continue
                bb = item.get("bbox_norm")
                if not isinstance(bb, list) or len(bb) < 4:
                    continue
                x1, y1, x2, y2 = [max(0.0, min(1.0, float(v))) for v in bb[:4]]
                if x2 <= x1 + 0.01 or y2 <= y1 + 0.01:
                    continue
                dims = item.get("dimensions_m")
                if not isinstance(dims, list) or len(dims) < 3:
                    dims = [0.35, 0.45, 0.25]
                st = str(item.get("support_type") or "ON_FLOOR").upper()
                if st not in {"WALL_MOUNTED", "ON_FLOOR", "ON_SURFACE", "CEILING"}:
                    st = "ON_FLOOR"
                clean_objs.append(
                    {
                        "name": str(item.get("name") or "Object").strip()[:64],
                        "category": str(item.get("category") or "prop").strip()[:32],
                        "bbox_norm": [round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4)],
                        "support_type": st,
                        "support_surface": str(item.get("support_surface") or surface).strip().lower(),
                        "dimensions_m": [round(max(0.04, float(d)), 3) for d in dims[:3]],
                        "color_hex": str(item.get("color_hex") or "#38bdf8"),
                        "confidence": round(max(0.0, min(1.0, float(item.get("confidence") or 0.85))), 2),
                        "notes": str(item.get("notes") or "")[:160],
                    }
                )
            return {
                "ok": True,
                "provider": openrouter_model,
                "summary": str(parsed.get("summary") or f"Detected {len(clean_objs)} objects."),
                "objects": clean_objs,
            }
        except Exception as exc:
            last_err = str(exc)
            sys.stderr.write(
                f"[room_studio.vision] OpenRouter scene-graph error attempt {attempt}/{MAX_VISION_RETRIES}: {exc}\n"
            )
            if attempt < MAX_VISION_RETRIES:
                await asyncio.sleep(1.2 * attempt)

    raise RuntimeError(f"Vision scene-graph analysis failed after {MAX_VISION_RETRIES} retries: {last_err}")


def compute_next_best_view(project: Dict[str, Any]) -> Dict[str, Any]:
    """Compute 3D room capture coverage and Next-Best-View (NBV) ghost camera frustums.

    Evaluates which walls, floor, overview angles, and close-up objects still lack
    high-resolution photographic coverage and returns ranked 3D ghost camera poses
    ready to render directly inside the Three.js viewport.

    Args:
        project: Room Studio project dictionary.

    Returns:
        Coverage summary with ``coverage_pct``, ``surface_counts``, ``ghost_cameras``,
        and ``next_instruction``.
    """
    photos = list(project.get("photos") or [])
    objects = list(project.get("objects") or [])
    w = float(project.get("width_m") or 4.6)
    l = float(project.get("length_m") or 4.2)

    core_surfaces = ["north_wall", "east_wall", "south_wall", "west_wall", "floor", "overview"]
    surface_counts: Dict[str, int] = {s: 0 for s in core_surfaces}
    for p in photos:
        surf = str(p.get("surface") or "overview")
        surface_counts[surf] = surface_counts.get(surf, 0) + 1

    covered_core = sum(1 for s in core_surfaces if surface_counts.get(s, 0) >= 1)
    # Bonus points for multi-angle wall overlap (>=2 photos on a wall) and 3D-converted objects
    overlap_bonus = min(15, sum(3 for s in ("north_wall", "east_wall", "south_wall", "west_wall") if surface_counts.get(s, 0) >= 2))
    mesh_count = sum(1 for o in objects if o.get("mesh_file_id"))
    object_bonus = min(15, mesh_count * 5)
    base_pct = int(round((covered_core / len(core_surfaces)) * 70))
    coverage_pct = min(100, base_pct + overlap_bonus + object_bonus)

    ghost_cameras: List[Dict[str, Any]] = []
    surface_labels = {
        "north_wall": "North Wall",
        "east_wall": "East Wall",
        "south_wall": "South Wall",
        "west_wall": "West Wall",
        "floor": "Floor & Furniture Layout",
        "overview": "Corner 45° Room Overview",
    }

    for surf in core_surfaces:
        cnt = surface_counts.get(surf, 0)
        if cnt == 0:
            base_pose = DEFAULT_SURFACE_CAMERA_POSES[surf]
            # Scale camera offset proportionally to room size
            pose = {
                "x": round(base_pose["x"] * (w / 4.6), 2),
                "y": base_pose["y"],
                "z": round(base_pose["z"] * (l / 4.2), 2),
                "yaw_deg": base_pose["yaw_deg"],
                "pitch_deg": base_pose["pitch_deg"],
            }
            ghost_cameras.append(
                {
                    "id": f"nbv_{surf}",
                    "surface": surf,
                    "label": f"Capture {surface_labels[surf]}",
                    "priority": "high" if surf.endswith("_wall") else "medium",
                    "pose": pose,
                    "reason": f"No photo covering {surface_labels[surf]} yet — stand ~{max(1.2, round(min(w, l) * 0.35, 1))}m back facing straight on.",
                }
            )

    if not ghost_cameras:
        # Suggest close-up for any un-converted object
        pending_objs = [o for o in objects if not o.get("mesh_file_id")]
        if pending_objs:
            top = pending_objs[0]
            op = top.get("pose") or {}
            ghost_cameras.append(
                {
                    "id": f"nbv_obj_{top.get('id')}",
                    "surface": "object_closeup",
                    "label": f"Convert '{top.get('name')}' to 3D",
                    "priority": "medium",
                    "pose": {
                        "x": round(float(op.get("x") or 0.0) * 0.5, 2),
                        "y": round(float(op.get("y") or 1.1), 2),
                        "z": round(float(op.get("z") or 0.0) * 0.5, 2),
                        "yaw_deg": 0.0,
                        "pitch_deg": -8.0,
                    },
                    "reason": f"Room walls are covered! Select '{top.get('name')}' in the Objects tab and click Generate 3D (.glb) for full-360° fidelity.",
                }
            )

    next_instruction = (
        ghost_cameras[0]["reason"]
        if ghost_cameras
        else "High-resolution coverage complete! Export your furnished 3D Room Digital Twin (.glb) or refine object poses."
    )

    return {
        "coverage_pct": coverage_pct,
        "photo_count": len(photos),
        "object_count": len(objects),
        "converted_3d_count": mesh_count,
        "surface_counts": surface_counts,
        "ghost_cameras": ghost_cameras,
        "next_instruction": next_instruction,
    }
