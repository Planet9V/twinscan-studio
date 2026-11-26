"""Unit tests for CycloneDX 1.6 HBOM, DEXPI G_CPDT, Cypher, DXF, glTF, and PLY exporters."""

from __future__ import annotations

from src.lidar.ld19_parser import LidarPoint
from src.twin.exporters import (
    export_cyclonedx_hbom,
    export_cypher_script,
    export_dexpi_graph_json,
    export_dxf_floorplan,
    export_gltf_scene,
    export_ply_point_cloud,
)


def _sample_data():
    space = {"id": "sp-12345678", "name": "Substation Bay A", "facility": "Eigenia Energy", "metrics": {"area_m2": 36.0}}
    walls = [{"x1": -3.0, "y1": -2.5, "x2": 3.0, "y2": -2.5, "length_m": 6.0, "inlier_count": 40}]
    equipment = [
        {
            "id": "eq-1",
            "name": "ABB Relay",
            "manufacturer": "ABB",
            "model_number": "REF615",
            "serial_number": "SN-88219",
            "dexpi_class": "ProtectionRelay",
            "inferred_cpe_23": "cpe:2.3:h:abb:ref615:*:*:*:*:*:*:*:*",
            "asset_tags": ["SUB-A-01"],
            "mac_addresses": ["AA:BB:CC:DD:EE:FF"],
            "x": 1.2,
            "y": 0.8,
            "z": 0.0,
            "yaw_deg": 90.0,
            "width_m": 0.6,
            "depth_m": 0.5,
            "height_m": 1.4,
        }
    ]
    return space, walls, equipment


def test_export_cyclonedx_dexpi_and_cypher() -> None:
    """Standards JSON and Cypher exporters emit valid CycloneDX 1.6 and G_CPDT structures."""
    space, _, equipment = _sample_data()
    hbom = export_cyclonedx_hbom(space, equipment)
    assert hbom["bomFormat"] == "CycloneDX"
    assert hbom["specVersion"] == "1.6"
    assert hbom["components"][0]["cpe"].startswith("cpe:2.3:h:abb")

    dexpi = export_dexpi_graph_json(space, equipment)
    assert dexpi["schema"] == "eigenia.G_CPDT.v1"
    assert len(dexpi["equipment"]) == 1

    cypher = export_cypher_script(space, equipment)
    assert "MERGE (f:Facility" in cypher
    assert "LOCATED_IN" in cypher


def test_export_dxf_gltf_and_ply() -> None:
    """CAD DXF, binary glTF, and ASCII PLY exporters produce non-empty valid payloads."""
    _, walls, equipment = _sample_data()
    dxf = export_dxf_floorplan(walls, equipment, zones=[{"polygon": [[0, 0], [1, 0], [1, 1]]}])
    assert b"SECTION" in dxf and b"WALLS" in dxf

    glb = export_gltf_scene(walls, equipment)
    assert glb[:4] == b"glTF"

    ply = export_ply_point_cloud([LidarPoint(0.0, 2.0, 220, 2.0, 0.0)])
    assert ply.startswith("ply\nformat ascii 1.0")
    assert "element vertex 1" in ply
