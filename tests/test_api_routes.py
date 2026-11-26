"""End-to-end FastAPI route tests for LiDAR, OpenRouter Vision, pgvector search, Graph, and Exports."""

from __future__ import annotations

import cv2
import numpy as np
from fastapi.testclient import TestClient

from src.app.config import Settings
from src.app.factory import create_app
from src.db.repository import InMemoryTwinRepository


def _build_test_client(tmp_path) -> TestClient:
    cfg = Settings(
        openrouter_api_key="",
        database_url="",
        neo4j_uri="",
        twinscan_storage_dir=str(tmp_path),
    )
    app = create_app(settings=cfg, repository=InMemoryTwinRepository())
    return TestClient(app)


def test_full_api_workflow(tmp_path) -> None:
    """Verify health, LiDAR controls, vision scan, asset placement, semantic search, graph, and exports."""
    with _build_test_client(tmp_path) as client:
        # 1. Health & Spaces
        h = client.get("/health")
        assert h.status_code == 200
        assert h.json()["status"] == "ok"
        space_id = h.json()["active_space_id"]
        assert space_id

        # 2. LiDAR status, filter update, baseline capture, rogue injection, wall extraction
        assert client.get("/api/lidar/status").status_code == 200
        assert client.post("/api/lidar/filters", json={"min_range_m": 0.1, "max_range_m": 10.0}).status_code == 200
        assert client.post("/api/lidar/baseline").json()["baseline_active"] is True
        mode_res = client.post("/api/lidar/mode", json={"inject_rogue_object": True})
        assert mode_res.status_code == 200
        assert mode_res.json()["rogue_injected"] is True

        walls_res = client.post(f"/api/lidar/extract-walls?space_id={space_id}")
        assert walls_res.status_code == 200
        assert len(walls_res.json()["walls"]) >= 4

        # 3. Vision nameplate analysis (Stage-1 offline + LiDAR raycast auto-placement)
        img = np.full((100, 160, 3), 200, dtype=np.uint8)
        ok, jpg = cv2.imencode(".jpg", img)
        assert ok
        vis_res = client.post(
            "/api/vision/analyze",
            files={"file": ("plate.jpg", jpg.tobytes(), "image/jpeg")},
            data={"camera_fov_deg": "68.0", "camera_yaw_deg": "0.0"},
        )
        assert vis_res.status_code == 200
        assert "suggested_pose" in vis_res.json()
        assert vis_res.json()["image_url"].startswith("/api/files/")

        # 4. Pin equipment asset + semantic search + Focus Queue + Enrich + Archive + Graph
        pin_res = client.post(
            f"/api/spaces/{space_id}/equipment",
            json={
                "name": "Siemens S7-1500 PLC",
                "equipment_type": "PLC",
                "dexpi_class": "ProgrammableLogicController",
                "manufacturer": "Siemens",
                "model_number": "6ES7515",
                "serial_number": "SN-44102",
                "inferred_cpe_23": "cpe:2.3:h:siemens:simatic_s7-1500:*:*:*:*:*:*:*:*",
                "asset_tags": ["OT-PLC-01"],
                "mac_addresses": ["00:1B:1B:AA:BB:CC"],
                "image_file_id": vis_res.json()["image_file_id"],
                "image_url": vis_res.json()["image_url"],
                "x": -2.3,
                "y": 1.4,
            },
        )
        assert pin_res.status_code == 200
        eq_id = pin_res.json()["equipment"]["id"]

        fq_res = client.get(f"/api/spaces/{space_id}/focus-queue")
        assert fq_res.status_code == 200
        assert fq_res.json()["queue_count"] >= 1

        enr_res = client.post(f"/api/equipment/{eq_id}/enrich", json={"include_nvd": False})
        assert enr_res.status_code == 200
        assert enr_res.json()["equipment"]["completeness"]["completeness_pct"] >= 80

        arch_res = client.post(f"/api/spaces/{space_id}/archive-snapshot")
        assert arch_res.status_code == 200
        assert len(arch_res.json()["archived_files"]) == 5

        search_res = client.post("/api/equipment/search", json={"query": "Siemens PLC S7-1500", "space_id": space_id})
        assert search_res.status_code == 200
        assert search_res.json()["count"] == 1
        assert search_res.json()["results"][0]["id"] == eq_id

        graph_res = client.get(f"/api/spaces/{space_id}/graph")
        assert graph_res.status_code == 200
        assert graph_res.json()["stats"]["equipment_count"] == 1

        # 5. Standards exports
        for fmt in ("cyclonedx", "dexpi", "cypher", "dxf", "gltf", "ply"):
            exp = client.get(f"/api/spaces/{space_id}/export/{fmt}")
            assert exp.status_code == 200, f"Export {fmt} failed"
            assert len(exp.content) > 20
