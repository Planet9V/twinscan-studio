"""Dark-Zone Focus Priority Queue, Pass-3 Direct Research Enrichment, and PostgreSQL Snapshot Archival routes."""

from __future__ import annotations

import json
import time
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src.api.state import TwinScanRuntimeState
from src.lidar.dark_zones import detect_spatial_dark_zones
from src.twin.completeness import build_priority_focus_queue, score_equipment_completeness
from src.twin.exporters import (
    export_cyclonedx_hbom,
    export_dexpi_graph_json,
    export_dxf_floorplan,
    export_gltf_scene,
    export_ply_point_cloud,
)
from src.vision.schemas import EquipmentVisionResult

router = APIRouter(prefix="/api", tags=["enrichment-and-focus"])


class EnrichAssetRequest(BaseModel):
    """Parameters for triggering Pass-3 direct online research & NVD/EPSS enrichment."""

    research_model: Optional[str] = None
    include_nvd: bool = True


def _state(request: Request) -> TwinScanRuntimeState:
    return request.app.state.runtime


@router.get("/spaces/{space_id}/focus-queue")
async def get_priority_focus_queue(space_id: str, request: Request) -> dict[str, Any]:
    """Return prioritized Spatial Dark Zones, Unidentified Clusters, and Dark/Incomplete Assets."""
    rt = _state(request)
    space = rt.repo.get_space(space_id)
    if not space:
        raise HTTPException(status_code=404, detail="Space not found.")
    equipment = rt.repo.list_equipment(space_id)
    dark_zones = detect_spatial_dark_zones(rt.latest_points, rt.latest_clusters, equipment)
    rt.latest_dark_zones = dark_zones
    queue = build_priority_focus_queue(dark_zones, equipment)
    return {
        "space_id": space_id,
        "dark_zone_count": len(dark_zones),
        "queue_count": len(queue),
        "dark_zones": [d.to_dict() for d in dark_zones],
        "focus_queue": queue,
    }


@router.post("/equipment/{equipment_id}/enrich")
async def enrich_equipment_direct_research(
    equipment_id: str,
    body: EnrichAssetRequest,
    request: Request,
) -> dict[str, Any]:
    """Run Pass-3 Direct Research (OpenRouter web-search + NVD CPE/CVE + FIRST EPSS) on an asset."""
    rt = _state(request)
    asset = rt.repo.get_equipment(equipment_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Equipment asset not found.")

    t0 = time.perf_counter()
    dossier = await rt.enricher.enrich_asset(
        asset=asset,
        research_model=body.research_model,
        include_nvd=body.include_nvd,
    )
    latency_ms = int((time.perf_counter() - t0) * 1000)

    dims = dossier.get("dimensions_m") or {}
    updates: dict[str, Any] = {}
    if dossier.get("dexpi_class"):
        updates["dexpi_class"] = dossier["dexpi_class"]
    if dossier.get("inferred_cpe_23"):
        updates["inferred_cpe_23"] = dossier["inferred_cpe_23"]
    if dossier.get("voltage_rating"):
        updates["voltage_rating"] = dossier["voltage_rating"]
    for key in ("width_m", "depth_m", "height_m"):
        val = dims.get(key)
        if isinstance(val, (int, float)) and 0.05 <= float(val) <= 10.0:
            updates[key] = float(val)

    merged_preview = {**asset, **updates, "enrichment": dossier}
    emb_model = rt.effective_config.get("openrouter_embedding_model", "fallback")
    summary = EquipmentVisionResult(
        name=merged_preview["name"],
        equipment_type=merged_preview.get("equipment_type", "Industrial Equipment"),
        dexpi_class=merged_preview.get("dexpi_class", "Equipment"),
        manufacturer=merged_preview.get("manufacturer", "Unknown"),
        model_number=merged_preview.get("model_number", "Unknown"),
        serial_number=merged_preview.get("serial_number"),
        inferred_cpe_23=merged_preview.get("inferred_cpe_23"),
        voltage_rating=merged_preview.get("voltage_rating"),
        asset_tags=merged_preview.get("asset_tags") or [],
        mac_addresses=merged_preview.get("mac_addresses") or [],
    )
    emb_text = summary.to_embedding_text() + f" | Specs: {dossier.get('datasheet_summary', '')}"
    embedding = await rt.vision.generate_embedding(emb_text)

    updated = rt.repo.update_equipment_enrichment(
        equipment_id=equipment_id,
        enrichment=dossier,
        updates=updates,
        embedding=embedding,
        embedding_model=emb_model if rt.openrouter_configured else "fallback",
    )
    rt.repo.log_vision_usage(
        {
            "operation": "direct_research",
            "model": dossier.get("research_model_used", "research"),
            "latency_ms": latency_ms,
            "confidence": 0.92,
            "consensus_verified": False,
            "status": "ok",
        }
    )

    space = rt.repo.get_space(asset["space_id"])
    if space:
        rt.neo4j.sync_space_and_equipment(
            space=space,
            equipment=rt.repo.list_equipment(space["id"]),
            max_near_m=rt.near_proximity_m,
        )

    completeness = score_equipment_completeness(updated or merged_preview)
    return {
        "equipment": {**(updated or merged_preview), "completeness": completeness},
        "enrichment": dossier,
        "latency_ms": latency_ms,
    }


@router.post("/spaces/{space_id}/archive-snapshot")
async def archive_twin_snapshot_to_postgres(space_id: str, request: Request) -> dict[str, Any]:
    """Generate and persist versioned CycloneDX, DEXPI, DXF, glTF, and PLY artifacts in PostgreSQL."""
    rt = _state(request)
    space = rt.repo.get_space(space_id)
    if not space:
        raise HTTPException(status_code=404, detail="Space not found.")
    equipment = rt.repo.list_equipment(space_id)
    walls = space.get("walls") or [w.to_dict() for w in rt.latest_walls]
    zones = space.get("zones") or []

    artifacts = [
        (
            f"snapshot-{space_id[:8]}-hbom.cdx.json",
            "application/vnd.cyclonedx+json",
            json.dumps(export_cyclonedx_hbom(space, equipment), indent=2).encode("utf-8"),
        ),
        (
            f"snapshot-{space_id[:8]}-gcpdt.json",
            "application/json",
            json.dumps(export_dexpi_graph_json({**space, "walls": walls}, equipment), indent=2).encode("utf-8"),
        ),
        (
            f"snapshot-{space_id[:8]}.dxf",
            "application/dxf",
            export_dxf_floorplan(walls, equipment, zones),
        ),
        (
            f"snapshot-{space_id[:8]}.glb",
            "model/gltf-binary",
            export_gltf_scene(walls, equipment, wall_height_m=rt.default_wall_height_m),
        ),
        (
            f"snapshot-{space_id[:8]}.ply",
            "text/plain",
            export_ply_point_cloud(rt.latest_points).encode("utf-8"),
        ),
    ]

    archived = [
        rt.repo.store_file(
            filename=fname,
            content_type=ctype,
            data=raw,
            category="export_artifact",
            space_id=space_id,
            metadata={"space_name": space["name"], "equipment_count": len(equipment)},
        )
        for fname, ctype, raw in artifacts
    ]
    return {"space_id": space_id, "archived_files": archived, "storage": rt.repo.storage_stats()}
