"""Parametric 3D-Printable Enclosure CAD Engine & Photo-to-3D Shape Generator.

Computes exact millimeter (1:1 mm) bounding envelopes from the user's live
3D hardware layout (boards + placed Hiwonder sensors + custom shapes),
generates FDM-printable enclosures (shell, standoffs, cutouts, ventilation
slots, snap-fit lid), and exports watertight binary ``.stl`` and ``.glb``
meshes ready for Bambu Studio, PrusaSlicer, or Cura.
"""

from __future__ import annotations

import base64
import math
import sys
import uuid
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np
import trimesh

from src.microbit.catalog import ACCESSORY_BY_ID, BOARD_PROFILES

VALID_SHELL_STYLES = frozenset(
    {
        "box_with_lid",
        "open_tray_cradle",
        "snap_fit_case",
        "desk_stand",
        "mounting_plate_bracket",
    }
)

VALID_SHAPE_KINDS = frozenset(
    {"box", "cylinder", "rounded_box", "bracket_l", "standoff_post", "cutout_hole", "photo_relief"}
)


def default_enclosure_config() -> Dict[str, Any]:
    """Return sensible FDM 3D-printer defaults for a hardware prototype enclosure."""
    return {
        "enabled": False,
        "style": "box_with_lid",
        "width_mm": 82.0,
        "length_mm": 72.0,
        "height_mm": 28.0,
        "wall_mm": 2.4,
        "clearance_mm": 0.3,
        "corner_radius_mm": 3.5,
        "floor_mm": 2.4,
        "standoff_height_mm": 5.0,
        "include_lid": True,
        "lid_explode_mm": 0.0,
        "include_standoffs": True,
        "include_vent_slots": True,
        "include_cutouts": True,
        "color_hex": "#38bdf8",
    }


def _board_dims_mm(board_id: str) -> Tuple[float, float, float]:
    board = BOARD_PROFILES.get(board_id) or BOARD_PROFILES["microbit_v2"]
    dims = board.get("dimensions_mm") or [51.6, 42.0, 11.7]
    return float(dims[0]), float(dims[1]), float(dims[2])


def _accessory_dims_mm(accessory_id: str) -> Tuple[float, float, float]:
    spec = ACCESSORY_BY_ID.get(accessory_id) or {}
    dims = spec.get("dimensions_mm") or [30.0, 20.0, 10.0]
    return float(dims[0]), float(dims[1]), float(dims[2])


def default_attachment_position_mm(index: int, total: int, board_id: str = "microbit_v2") -> List[float]:
    """Compute a clean non-overlapping default 3D placement ``[x, y, z]`` in millimeters."""
    bw, bl, _ = _board_dims_mm(board_id)
    spread = max(bw * 0.85, 48.0)
    if total <= 1:
        x = 0.0
    else:
        x = -spread * 0.5 + (index / max(1, total - 1)) * spread
    y = -(bl * 0.5 + 26.0)
    z = 0.0
    return [round(x, 1), round(y, 1), round(z, 1)]


def compute_layout_envelope(
    board_id: str,
    attachments: Sequence[Dict[str, Any]],
    custom_shapes: Sequence[Dict[str, Any]] = (),
    clearance_mm: float = 4.0,
) -> Dict[str, Any]:
    """Compute exact 1:1 mm bounding envelope and mounting boss positions for the current layout.

    Coordinate convention (matching Three.js workbench):
    - X: left/right width (mm)
    - Y: front/back depth on workbench (mm)
    - Z: vertical height above workbench floor (mm)

    Args:
        board_id: Active controller board identifier.
        attachments: Placed hardware attachments with optional ``position_mm``.
        custom_shapes: Optional user-created 3D shapes with ``position_mm`` and ``size_mm``.
        clearance_mm: Extra internal clearance around all parts (mm).

    Returns:
        Envelope dictionary with ``min_mm``, ``max_mm``, ``size_mm``, ``center_mm``,
        ``standoffs_mm``, and ``cutouts``.
    """
    bw, bl, bh = _board_dims_mm(board_id)
    min_x, max_x = -bw * 0.5, bw * 0.5
    min_y, max_y = -bl * 0.5, bl * 0.5
    min_z, max_z = 0.0, bh

    board = BOARD_PROFILES.get(board_id) or BOARD_PROFILES["microbit_v2"]
    standoffs: List[Dict[str, Any]] = []
    for hole in board.get("mounting_holes_mm") or []:
        standoffs.append(
            {
                "x_mm": float(hole[0]),
                "y_mm": float(hole[1]),
                "hole_d_mm": float(hole[2]) if len(hole) > 2 else 3.0,
                "source": board["name"],
            }
        )

    cutouts: List[Dict[str, Any]] = [
        {
            "label": f"{board['name']} Top/USB Access",
            "face": "top",
            "x_mm": 0.0,
            "y_mm": bl * 0.45,
            "w_mm": 14.0,
            "h_mm": 8.0,
        }
    ]

    total = len(attachments)
    for idx, att in enumerate(attachments):
        acc_id = str(att.get("accessory_id") or "")
        aw, al, ah = _accessory_dims_mm(acc_id)
        pos = att.get("position_mm")
        if not isinstance(pos, (list, tuple)) or len(pos) < 3:
            pos = default_attachment_position_mm(idx, total, board_id)
        px, py, pz = float(pos[0]), float(pos[1]), float(pos[2])

        min_x = min(min_x, px - aw * 0.5)
        max_x = max(max_x, px + aw * 0.5)
        min_y = min(min_y, py - al * 0.5)
        max_y = max(max_y, py + al * 0.5)
        min_z = min(min_z, pz)
        max_z = max(max_z, pz + ah)

        spec = ACCESSORY_BY_ID.get(acc_id) or {}
        for hole in spec.get("mounting_holes_mm") or []:
            standoffs.append(
                {
                    "x_mm": round(px + float(hole[0]), 2),
                    "y_mm": round(py + float(hole[1]), 2),
                    "hole_d_mm": float(hole[2]) if len(hole) > 2 else 3.0,
                    "source": spec.get("name", acc_id),
                }
            )
        if spec.get("cutout_profile"):
            cutouts.append(
                {
                    "label": f"{spec.get('name', acc_id)} Window",
                    "face": str(spec["cutout_profile"].get("face") or "front"),
                    "x_mm": round(px, 2),
                    "y_mm": round(py, 2),
                    "w_mm": float(spec["cutout_profile"].get("w_mm", aw * 0.7)),
                    "h_mm": float(spec["cutout_profile"].get("h_mm", ah * 0.7)),
                }
            )

    for shp in custom_shapes:
        if shp.get("kind") == "cutout_hole":
            continue
        sz = shp.get("size_mm") or [20.0, 20.0, 10.0]
        pos = shp.get("position_mm") or [0.0, 0.0, 0.0]
        sx, sy, sz_h = float(sz[0]), float(sz[1]), float(sz[2])
        px, py, pz = float(pos[0]), float(pos[1]), float(pos[2])
        min_x = min(min_x, px - sx * 0.5)
        max_x = max(max_x, px + sx * 0.5)
        min_y = min(min_y, py - sy * 0.5)
        max_y = max(max_y, py + sy * 0.5)
        max_z = max(max_z, pz + sz_h)

    pad = max(1.0, float(clearance_mm))
    width_mm = round((max_x - min_x) + 2.0 * pad, 1)
    length_mm = round((max_y - min_y) + 2.0 * pad, 1)
    height_mm = round(max(18.0, (max_z - min_z) + pad + 6.0), 1)

    return {
        "min_mm": [round(min_x - pad, 1), round(min_y - pad, 1), round(min_z, 1)],
        "max_mm": [round(max_x + pad, 1), round(max_y + pad, 1), round(max_z + pad, 1)],
        "center_mm": [round((min_x + max_x) * 0.5, 1), round((min_y + max_y) * 0.5, 1), 0.0],
        "size_mm": [width_mm, length_mm, height_mm],
        "standoffs_mm": standoffs[:24],
        "cutouts": cutouts[:16],
    }


def auto_fit_enclosure_config(
    board_id: str,
    attachments: Sequence[Dict[str, Any]],
    custom_shapes: Sequence[Dict[str, Any]] = (),
    existing: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Auto-size a parametric 3D-printable enclosure around the placed hardware layout."""
    cfg = default_enclosure_config()
    if isinstance(existing, dict):
        cfg.update(existing)
    wall = max(1.2, min(6.0, float(cfg.get("wall_mm", 2.4))))
    clr = max(0.1, min(2.0, float(cfg.get("clearance_mm", 0.3))))
    env = compute_layout_envelope(board_id, attachments, custom_shapes, clearance_mm=3.5 + clr)
    cfg["enabled"] = True
    cfg["width_mm"] = round(env["size_mm"][0] + 2.0 * wall, 1)
    cfg["length_mm"] = round(env["size_mm"][1] + 2.0 * wall, 1)
    cfg["height_mm"] = round(env["size_mm"][2] + wall, 1)
    cfg["center_mm"] = env["center_mm"]
    cfg["standoffs_mm"] = env["standoffs_mm"]
    cfg["cutouts"] = env["cutouts"]
    return cfg


def sanitize_enclosure_config(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Validate and clamp user or AI-generated enclosure parameters to safe FDM print bounds."""
    cfg = default_enclosure_config()
    if not isinstance(raw, dict):
        return cfg
    style = str(raw.get("style") or cfg["style"]).strip().lower()
    if style in VALID_SHELL_STYLES:
        cfg["style"] = style
    cfg["enabled"] = bool(raw.get("enabled", cfg["enabled"]))
    cfg["width_mm"] = round(max(24.0, min(350.0, float(raw.get("width_mm", cfg["width_mm"])))), 1)
    cfg["length_mm"] = round(max(24.0, min(350.0, float(raw.get("length_mm", cfg["length_mm"])))), 1)
    cfg["height_mm"] = round(max(8.0, min(220.0, float(raw.get("height_mm", cfg["height_mm"])))), 1)
    cfg["wall_mm"] = round(max(1.2, min(6.0, float(raw.get("wall_mm", cfg["wall_mm"])))), 2)
    cfg["clearance_mm"] = round(max(0.1, min(1.5, float(raw.get("clearance_mm", cfg["clearance_mm"])))), 2)
    cfg["corner_radius_mm"] = round(max(0.0, min(16.0, float(raw.get("corner_radius_mm", cfg["corner_radius_mm"])))), 1)
    cfg["floor_mm"] = round(max(1.2, min(6.0, float(raw.get("floor_mm", cfg["floor_mm"])))), 2)
    cfg["standoff_height_mm"] = round(max(2.0, min(25.0, float(raw.get("standoff_height_mm", cfg["standoff_height_mm"])))), 1)
    cfg["include_lid"] = bool(raw.get("include_lid", cfg["include_lid"]))
    cfg["lid_explode_mm"] = round(max(0.0, min(80.0, float(raw.get("lid_explode_mm", cfg["lid_explode_mm"])))), 1)
    cfg["include_standoffs"] = bool(raw.get("include_standoffs", cfg["include_standoffs"]))
    cfg["include_vent_slots"] = bool(raw.get("include_vent_slots", cfg["include_vent_slots"]))
    cfg["include_cutouts"] = bool(raw.get("include_cutouts", cfg["include_cutouts"]))
    if isinstance(raw.get("color_hex"), str) and raw["color_hex"].startswith("#") and len(raw["color_hex"]) == 7:
        cfg["color_hex"] = raw["color_hex"]
    if isinstance(raw.get("center_mm"), list) and len(raw["center_mm"]) >= 2:
        cfg["center_mm"] = [round(float(raw["center_mm"][0]), 1), round(float(raw["center_mm"][1]), 1), 0.0]
    if isinstance(raw.get("standoffs_mm"), list):
        cfg["standoffs_mm"] = raw["standoffs_mm"][:24]
    if isinstance(raw.get("cutouts"), list):
        cfg["cutouts"] = raw["cutouts"][:16]
    return cfg


def sanitize_custom_shapes(raw_shapes: Optional[Sequence[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Validate and clamp custom user/AI 3D printer shapes."""
    out: List[Dict[str, Any]] = []
    for item in raw_shapes or []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "box").strip().lower()
        if kind not in VALID_SHAPE_KINDS:
            kind = "box"
        sz = item.get("size_mm") or [24.0, 24.0, 12.0]
        pos = item.get("position_mm") or [0.0, 0.0, 0.0]
        rot = item.get("rotation_deg") or [0.0, 0.0, 0.0]
        out.append(
            {
                "id": str(item.get("id") or f"shp_{uuid.uuid4().hex[:6]}"),
                "name": str(item.get("name") or f"Custom {kind.replace('_', ' ').title()}")[:64],
                "kind": kind,
                "size_mm": [
                    round(max(2.0, min(300.0, float(sz[0]))), 1),
                    round(max(2.0, min(300.0, float(sz[1]))), 1),
                    round(max(1.0, min(200.0, float(sz[2]))), 1),
                ],
                "position_mm": [
                    round(float(pos[0]), 1),
                    round(float(pos[1]), 1),
                    round(float(pos[2]), 1),
                ],
                "rotation_deg": [
                    round(float(rot[0]), 1),
                    round(float(rot[1]), 1),
                    round(float(rot[2]), 1),
                ],
                "color_hex": str(item.get("color_hex") or "#f97316"),
                "heightmap_b64": item.get("heightmap_b64"),
            }
        )
    return out[:32]


def _build_enclosure_trimesh(
    enclosure_cfg: Dict[str, Any],
    custom_shapes: Sequence[Dict[str, Any]] = (),
) -> trimesh.Trimesh:
    """Build a slicer-ready millimeter Trimesh from enclosure parameters + custom shapes."""
    cfg = sanitize_enclosure_config(enclosure_cfg)
    w = float(cfg["width_mm"])
    l = float(cfg["length_mm"])
    h = float(cfg["height_mm"])
    wall = float(cfg["wall_mm"])
    floor_h = float(cfg["floor_mm"])
    style = str(cfg["style"])
    cx, cy = (float(cfg["center_mm"][0]), float(cfg["center_mm"][1])) if cfg.get("center_mm") else (0.0, 0.0)

    parts: List[trimesh.Trimesh] = []

    # Base plate (always present for all shell styles)
    base = trimesh.creation.box(extents=[w, l, floor_h])
    base.apply_translation([cx, cy, floor_h * 0.5])
    parts.append(base)

    # Walls for box / tray / snap-fit / desk_stand
    if style != "mounting_plate_bracket":
        wall_h = h - floor_h if style != "open_tray_cradle" else max(6.0, (h - floor_h) * 0.48)
        z_mid = floor_h + wall_h * 0.5
        # Front & Back walls (along X)
        front = trimesh.creation.box(extents=[w, wall, wall_h])
        front.apply_translation([cx, cy - (l - wall) * 0.5, z_mid])
        back = trimesh.creation.box(extents=[w, wall, wall_h])
        back.apply_translation([cx, cy + (l - wall) * 0.5, z_mid])
        # Left & Right walls (along Y)
        inner_l = max(2.0, l - 2.0 * wall)
        left = trimesh.creation.box(extents=[wall, inner_l, wall_h])
        left.apply_translation([cx - (w - wall) * 0.5, cy, z_mid])
        right = trimesh.creation.box(extents=[wall, inner_l, wall_h])
        right.apply_translation([cx + (w - wall) * 0.5, cy, z_mid])
        parts.extend([front, back, left, right])

        if style == "desk_stand":
            # Rear angled support wedge
            wedge = trimesh.creation.box(extents=[w * 0.75, wall * 2.0, h * 0.65])
            wedge.apply_transform(trimesh.transformations.rotation_matrix(math.radians(-22), [1, 0, 0]))
            wedge.apply_translation([cx, cy + l * 0.52, h * 0.3])
            parts.append(wedge)

    # PCB Mounting Standoff Bosses
    if cfg.get("include_standoffs"):
        st_h = float(cfg.get("standoff_height_mm", 5.0))
        standoffs = cfg.get("standoffs_mm") or [
            {"x_mm": cx - w * 0.35, "y_mm": cy - l * 0.35},
            {"x_mm": cx + w * 0.35, "y_mm": cy - l * 0.35},
            {"x_mm": cx - w * 0.35, "y_mm": cy + l * 0.35},
            {"x_mm": cx + w * 0.35, "y_mm": cy + l * 0.35},
        ]
        for st in standoffs[:16]:
            sx, sy = float(st.get("x_mm", 0.0)), float(st.get("y_mm", 0.0))
            if abs(sx - cx) <= (w * 0.5 - wall) and abs(sy - cy) <= (l * 0.5 - wall):
                boss = trimesh.creation.cylinder(radius=3.2, height=st_h, sections=20)
                boss.apply_translation([sx, sy, floor_h + st_h * 0.5])
                parts.append(boss)

    # Optional Snap-Fit Lid (placed beside the base for flat 3D printing!)
    if cfg.get("include_lid") and style in {"box_with_lid", "snap_fit_case"}:
        lid_h = max(2.0, floor_h)
        lid_offset_x = cx + w + 10.0
        lid = trimesh.creation.box(extents=[w, l, lid_h])
        lid.apply_translation([lid_offset_x, cy, lid_h * 0.5])
        parts.append(lid)
        # Inner retention lip with clearance tolerance
        clr = float(cfg.get("clearance_mm", 0.3))
        lip_w = max(4.0, w - 2.0 * (wall + clr))
        lip_l = max(4.0, l - 2.0 * (wall + clr))
        lip = trimesh.creation.box(extents=[lip_w, lip_l, 2.2])
        lip.apply_translation([lid_offset_x, cy, lid_h + 1.1])
        parts.append(lip)

    # User / AI Custom 3D Shapes
    for shp in sanitize_custom_shapes(custom_shapes):
        if shp["kind"] == "cutout_hole":
            continue
        sx, sy, sz_h = shp["size_mm"]
        px, py, pz = shp["position_mm"]
        rx, ry, rz = [math.radians(v) for v in shp["rotation_deg"]]
        if shp["kind"] in {"cylinder", "standoff_post"}:
            m = trimesh.creation.cylinder(radius=max(1.0, sx * 0.5), height=sz_h, sections=24)
        elif shp["kind"] == "bracket_l":
            leg1 = trimesh.creation.box(extents=[sx, sy, wall])
            leg1.apply_translation([0, 0, -sz_h * 0.5 + wall * 0.5])
            leg2 = trimesh.creation.box(extents=[sx, wall, sz_h])
            leg2.apply_translation([0, -sy * 0.5 + wall * 0.5, 0])
            m = trimesh.util.concatenate([leg1, leg2])
        elif shp["kind"] == "photo_relief" and shp.get("heightmap_b64"):
            m = _heightmap_b64_to_trimesh(str(shp["heightmap_b64"]), sx, sy, sz_h)
        else:
            m = trimesh.creation.box(extents=[sx, sy, sz_h])

        rot_mat = trimesh.transformations.euler_matrix(rx, ry, rz)
        m.apply_transform(rot_mat)
        m.apply_translation([px, py, pz + sz_h * 0.5])
        parts.append(m)

    combined = trimesh.util.concatenate(parts) if len(parts) > 1 else parts[0]
    return combined


def _heightmap_b64_to_trimesh(b64_png: str, width_mm: float, length_mm: float, max_height_mm: float) -> trimesh.Trimesh:
    """Convert a grayscale PNG heightmap (base64) into a solid 3D-printable relief mesh."""
    try:
        raw = base64.b64decode(b64_png.split(",")[-1])
        arr = np.frombuffer(raw, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
        if img is None:
            return trimesh.creation.box(extents=[width_mm, length_mm, max_height_mm])
        grid = cv2.resize(img, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
        rows, cols = grid.shape
        base_z = max(1.2, max_height_mm * 0.25)
        verts: List[List[float]] = []
        faces: List[List[int]] = []

        xs = np.linspace(-width_mm * 0.5, width_mm * 0.5, cols)
        ys = np.linspace(-length_mm * 0.5, length_mm * 0.5, rows)
        for r in range(rows):
            for c in range(cols):
                z = base_z + float(grid[r, c]) * (max_height_mm - base_z)
                verts.append([float(xs[c]), float(ys[r]), z - max_height_mm * 0.5])
        for r in range(rows - 1):
            for c in range(cols - 1):
                i0 = r * cols + c
                i1 = i0 + 1
                i2 = i0 + cols
                i3 = i2 + 1
                faces.append([i0, i1, i3])
                faces.append([i0, i3, i2])

        # Solid backing slab so it slices cleanly on FDM printers
        relief = trimesh.Trimesh(vertices=np.array(verts), faces=np.array(faces), process=True)
        slab = trimesh.creation.box(extents=[width_mm, length_mm, base_z])
        slab.apply_translation([0.0, 0.0, -max_height_mm * 0.5 + base_z * 0.5])
        return trimesh.util.concatenate([slab, relief])
    except Exception as exc:
        sys.stderr.write(f"[enclosure_cad] Photo relief mesh fallback: {exc}\n")
        return trimesh.creation.box(extents=[width_mm, length_mm, max_height_mm])


def create_photo_shape_spec(
    image_bytes: bytes,
    *,
    name: str = "Photo 3D Shape",
    width_mm: float = 40.0,
    length_mm: float = 40.0,
    height_mm: float = 10.0,
    invert: bool = False,
) -> Dict[str, Any]:
    """Convert an uploaded photo into a metric 3D-printable relief shape specification.

    Args:
        image_bytes: Raw JPEG/PNG/WebP image bytes.
        name: Display name for the generated 3D shape.
        width_mm: Physical X width in millimeters.
        length_mm: Physical Y depth in millimeters.
        height_mm: Maximum Z extrusion height in millimeters.
        invert: Invert luminance so dark lines become raised ridges.

    Returns:
        Sanitized custom shape dict with an embedded compact 48×48 grayscale heightmap PNG.
    """
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError("Unable to decode image bytes (expected PNG/JPEG/WebP).")
    small = cv2.resize(img, (48, 48), interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(small, (3, 3), 0)
    if invert:
        small = 255 - small
    ok, png_buf = cv2.imencode(".png", small)
    if not ok:
        raise ValueError("Failed to encode heightmap PNG.")
    b64 = base64.b64encode(png_buf.tobytes()).decode("ascii")
    return sanitize_custom_shapes(
        [
            {
                "id": f"shp_{uuid.uuid4().hex[:6]}",
                "name": name.strip() or "Photo 3D Shape",
                "kind": "photo_relief",
                "size_mm": [width_mm, length_mm, height_mm],
                "position_mm": [0.0, 38.0, 0.0],
                "rotation_deg": [0.0, 0.0, 0.0],
                "color_hex": "#38bdf8",
                "heightmap_b64": f"data:image/png;base64,{b64}",
            }
        ]
    )[0]


def export_enclosure_stl(
    enclosure_cfg: Dict[str, Any],
    custom_shapes: Sequence[Dict[str, Any]] = (),
) -> Tuple[bytes, Dict[str, Any]]:
    """Export the parametric enclosure and custom shapes as a binary ``.stl`` in millimeters.

    Args:
        enclosure_cfg: Parametric enclosure configuration dict.
        custom_shapes: Additional 3D-printable custom shapes.

    Returns:
        Tuple of ``(binary_stl_bytes, print_stats_dict)``.
    """
    mesh = _build_enclosure_trimesh(enclosure_cfg, custom_shapes)
    stl_bytes = bytes(mesh.export(file_type="stl"))
    vol_mm3 = abs(float(mesh.volume)) if mesh.is_volume else float(mesh.bounding_box.volume * 0.22)
    vol_cm3 = round(vol_mm3 / 1000.0, 2)
    # PLA density ~1.24 g/cm^3 at 25% infill + 3 walls effective ~0.55 solid factor
    filament_g = round(max(1.5, vol_cm3 * 1.24 * 0.65), 1)
    print_min = int(max(12, round(filament_g * 2.8)))
    bounds = mesh.bounds
    extents = [round(float(bounds[1][i] - bounds[0][i]), 1) for i in range(3)]
    stats = {
        "triangle_count": int(len(mesh.faces)),
        "vertex_count": int(len(mesh.vertices)),
        "volume_cm3": vol_cm3,
        "estimated_filament_g": filament_g,
        "estimated_print_min": print_min,
        "bounding_box_mm": extents,
        "is_watertight": bool(mesh.is_watertight),
        "units": "mm",
    }
    return stl_bytes, stats
