"""Standards-native Cyber-Physical Digital Twin exporters.

Generates OWASP CycloneDX 1.6 Hardware BOM (HBOM), Eigenia Schema G_CPDT /
DEXPI 2.0 topological JSON, Neo4j Cypher scripts, AutoCAD DXF floorplans via
``ezdxf``, 3D glTF/GLB scenes via ``trimesh``, and ASCII PLY point clouds.
"""

from __future__ import annotations

import io
import uuid
from datetime import datetime, timezone
from typing import Any, Sequence

import ezdxf

from src.lidar.ld19_parser import LidarPoint
from src.lidar.mapping import WallSegment
from src.lidar.spatial_3d import build_room_3d_scene


def export_cyclonedx_hbom(
    space: dict[str, Any],
    equipment: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """Export discovered physical assets as an OWASP CycloneDX 1.6 Hardware BOM.

    Args:
        space: Space metadata dictionary.
        equipment: Placed equipment asset dictionaries.

    Returns:
        CycloneDX 1.6 compliant JSON dictionary.
    """
    components = []
    for eq in equipment:
        props = [
            {"name": "eigenia:space_id", "value": str(space["id"])},
            {"name": "eigenia:dexpi_class", "value": str(eq.get("dexpi_class", "Equipment"))},
            {"name": "eigenia:pose_xyz_m", "value": f"{eq['x']:.3f},{eq['y']:.3f},{eq.get('z', 0.0):.3f}"},
            {"name": "eigenia:yaw_deg", "value": f"{eq.get('yaw_deg', 0.0):.1f}"},
        ]
        if eq.get("serial_number"):
            props.append({"name": "eigenia:serial_number", "value": str(eq["serial_number"])})
        if eq.get("voltage_rating"):
            props.append({"name": "eigenia:voltage_rating", "value": str(eq["voltage_rating"])})
        for mac in eq.get("mac_addresses") or []:
            props.append({"name": "eigenia:mac_address", "value": str(mac)})
        for tag in eq.get("asset_tags") or []:
            props.append({"name": "eigenia:asset_tag", "value": str(tag)})

        comp: dict[str, Any] = {
            "bom-ref": f"asset-{eq['id']}",
            "type": "device",
            "name": eq["name"],
            "version": eq.get("model_number") or "unknown",
            "manufacturer": {"name": eq.get("manufacturer") or "Unknown"},
            "properties": props,
        }
        if eq.get("inferred_cpe_23"):
            comp["cpe"] = eq["inferred_cpe_23"]
        components.append(comp)

    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{uuid.uuid4()}",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tools": {"components": [{"type": "application", "name": "Eigenia TwinScan", "version": "1.0.0"}]},
            "component": {
                "bom-ref": f"space-{space['id']}",
                "type": "platform",
                "name": space["name"],
                "group": space.get("facility", "Eigenia Facility"),
            },
        },
        "components": components,
    }


def export_dexpi_graph_json(
    space: dict[str, Any],
    equipment: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """Export an Eigenia Schema G_CPDT / DEXPI 2.0-aligned spatial-topological JSON bundle."""
    return {
        "schema": "eigenia.G_CPDT.v1",
        "standards": ["DEXPI-2.0", "ISO-15926-4", "CycloneDX-1.6"],
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "facility": space.get("facility", "Eigenia Facility"),
        "space": {
            "id": space["id"],
            "name": space["name"],
            "metrics": space.get("metrics", {}),
            "walls": space.get("walls", []),
            "zones": space.get("zones", []),
        },
        "equipment": list(equipment),
    }


def export_cypher_script(
    space: dict[str, Any],
    equipment: Sequence[dict[str, Any]],
) -> str:
    """Generate a portable Neo4j Cypher import script for a scanned space and its assets."""
    lines = [
        f"MERGE (f:Facility {{name: {space.get('facility', 'Eigenia Facility')!r}}})",
        f"MERGE (s:Space {{id: {space['id']!r}, name: {space['name']!r}}})",
        "MERGE (f)-[:CONTAINS]->(s);",
    ]
    for eq in equipment:
        lines.append(
            f"MATCH (s:Space {{id: {space['id']!r}}}) "
            f"MERGE (e:Equipment {{id: {eq['id']!r}}}) "
            f"SET e.name = {eq['name']!r}, e.manufacturer = {eq.get('manufacturer', 'Unknown')!r}, "
            f"e.model_number = {eq.get('model_number', 'Unknown')!r}, "
            f"e.serial_number = {eq.get('serial_number') or ''!r}, "
            f"e.dexpi_class = {eq.get('dexpi_class', 'Equipment')!r}, "
            f"e.cpe_23 = {eq.get('inferred_cpe_23') or ''!r} "
            f"MERGE (e)-[:LOCATED_IN {{x: {float(eq['x']):.4f}, y: {float(eq['y']):.4f}}}]->(s);"
        )
    return "\n".join(lines) + "\n"


def export_dxf_floorplan(
    walls: Sequence[dict[str, Any]],
    equipment: Sequence[dict[str, Any]],
    zones: Sequence[dict[str, Any]] = (),
) -> bytes:
    """Generate a layered AutoCAD DXF floorplan using ``ezdxf``."""
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    doc.layers.add("WALLS", color=4)
    doc.layers.add("EQUIPMENT", color=30)
    doc.layers.add("ZONES", color=1)
    doc.layers.add("LABELS", color=7)

    for w in walls:
        msp.add_line((float(w["x1"]), float(w["y1"])), (float(w["x2"]), float(w["y2"])), dxfattribs={"layer": "WALLS"})

    for eq in equipment:
        x, y = float(eq["x"]), float(eq["y"])
        hw = float(eq.get("width_m", 0.7)) / 2.0
        hd = float(eq.get("depth_m", 0.7)) / 2.0
        pts = [(x - hw, y - hd), (x + hw, y - hd), (x + hw, y + hd), (x - hw, y + hd), (x - hw, y - hd)]
        msp.add_lwpolyline(pts, dxfattribs={"layer": "EQUIPMENT"})
        msp.add_text(
            f"{eq['name']} ({eq.get('model_number', '')})",
            height=0.14,
            dxfattribs={"layer": "LABELS", "insert": (x - hw, y + hd + 0.08)},
        )

    for z in zones:
        poly = z.get("polygon") or []
        if len(poly) >= 3:
            pts = [(float(p[0]), float(p[1])) for p in poly] + [(float(poly[0][0]), float(poly[0][1]))]
            msp.add_lwpolyline(pts, dxfattribs={"layer": "ZONES"})

    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue().encode("utf-8")


def export_ply_point_cloud(points: Sequence[LidarPoint]) -> str:
    """Export filtered LiDAR points as an ASCII PLY point cloud with RGB intensity mapping."""
    header = [
        "ply",
        "format ascii 1.0",
        f"element vertex {len(points)}",
        "property float x",
        "property float y",
        "property float z",
        "property uchar red",
        "property uchar green",
        "property uchar blue",
        "end_header",
    ]
    rows = []
    for pt in points:
        # Map reflectance intensity into Eigenia Telemetry Sky -> Signal Orange gradient.
        t = max(0.0, min(1.0, pt.intensity / 255.0))
        r = int(56 + t * (224 - 56))
        g = int(189 + t * (90 - 189))
        b = int(248 + t * (16 - 248))
        rows.append(f"{pt.x:.4f} {pt.y:.4f} 0.0000 {r} {g} {b}")
    return "\n".join(header + rows) + "\n"


def export_gltf_scene(
    walls: Sequence[dict[str, Any]],
    equipment: Sequence[dict[str, Any]],
    wall_height_m: float = 2.8,
) -> bytes:
    """Export extruded room walls and placed equipment as a binary glTF (.glb) 3D asset."""
    wall_objs = [
        WallSegment(
            x1=float(w["x1"]),
            y1=float(w["y1"]),
            x2=float(w["x2"]),
            y2=float(w["y2"]),
            length_m=float(w.get("length_m", 1.0)),
            inlier_count=int(w.get("inlier_count", 10)),
        )
        for w in walls
    ]
    scene = build_room_3d_scene(wall_objs, equipment, wall_height_m=wall_height_m)
    exported = scene.export(file_type="glb")
    return exported if isinstance(exported, bytes) else bytes(exported)
