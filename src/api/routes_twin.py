"""Spatial Digital Twin CRUD, pgvector semantic search, Neo4j Knowledge Graph, and standards export routes."""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any, List, Literal, Optional

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from src.api.state import TwinScanRuntimeState
from src.db.robot_ai_store import RobotAiStoreProtocol
from src.db.robot_store import RobotStoreProtocol
from src.graph.neo4j_store import build_graph_payload
from src.lidar.composite_enhancer import resolve_enhance_preset
from src.lidar.scene_reconstructor import (
    capture_live_camera_frame,
    export_combined_room_glb,
    reconstruct_enhanced_wall_panel,
    reconstruct_wall_panel,
)
from src.robot.rosbridge_proxy import publish_velocity
from src.twin.completeness import score_equipment_completeness
from src.twin.exporters import (
    export_cyclonedx_hbom,
    export_cypher_script,
    export_dexpi_graph_json,
    export_dxf_floorplan,
    export_gltf_scene,
    export_ply_point_cloud,
)
from src.vision.schemas import EquipmentVisionResult

router = APIRouter(prefix="/api", tags=["twin"])


class CreateSpaceRequest(BaseModel):
    """Payload to create a new physical space."""

    name: str = Field(..., min_length=1, max_length=120)
    facility: str = Field(default="Eigenia Facility", max_length=120)
    description: str = Field(default="", max_length=500)


class UpdateSpaceRequest(BaseModel):
    """Payload to rename or update metadata on an existing physical space."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    facility: Optional[str] = Field(default=None, max_length=120)
    description: Optional[str] = Field(default=None, max_length=500)


class CloneSpaceRequest(BaseModel):
    """Payload to duplicate a room (walls, zones, 3D scene panels, and equipment) into a new checkpoint."""

    name: str = Field(..., min_length=1, max_length=120)
    facility: Optional[str] = Field(default=None, max_length=120)
    description: Optional[str] = Field(default=None, max_length=500)


class ZoneItem(BaseModel):
    """Safety or clearance polygon zone definition."""

    id: str
    name: str
    polygon: List[List[float]]
    threshold: int = 3


class SaveZonesRequest(BaseModel):
    """Payload to replace zones for a space."""

    zones: List[ZoneItem]


class CreateEquipmentRequest(BaseModel):
    """Payload to pin an identified equipment asset onto a space."""

    name: str
    equipment_type: str = "Industrial Equipment"
    dexpi_class: str = "Equipment"
    manufacturer: str = "Unknown"
    model_number: str = "Unknown"
    part_number: Optional[str] = None
    serial_number: Optional[str] = None
    inferred_cpe_23: Optional[str] = None
    voltage_rating: Optional[str] = None
    current_or_power: Optional[str] = None
    certifications: List[str] = Field(default_factory=list)
    asset_tags: List[str] = Field(default_factory=list)
    mac_addresses: List[str] = Field(default_factory=list)
    ip_or_hostname_labels: List[str] = Field(default_factory=list)
    barcodes: List[dict[str, Any]] = Field(default_factory=list)
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    yaw_deg: float = 0.0
    width_m: float = 0.75
    depth_m: float = 0.75
    height_m: float = 1.6
    confidence: float = 0.9
    model_used: str = "manual"
    image_file_id: Optional[str] = None
    image_url: Optional[str] = None
    raw_notes: str = ""


class SemanticSearchRequest(BaseModel):
    """Payload for PostgreSQL 18 pgvector semantic asset search."""

    query: str = Field(..., min_length=1)
    limit: int = Field(default=8, ge=1, le=50)
    space_id: Optional[str] = None
    manufacturer: Optional[str] = None


def _state(request: Request) -> TwinScanRuntimeState:
    return request.app.state.runtime


def _attach_completeness(items: List[dict[str, Any]]) -> List[dict[str, Any]]:
    return [{**eq, "completeness": score_equipment_completeness(eq)} for eq in items]


def _enrich_space_summary(request: Request, space: dict[str, Any]) -> dict[str, Any]:
    """Attach panel_count, equipment_count, wall_count, and latest thumbnail_url to a space record."""
    rt = _state(request)
    ai_store = getattr(request.app.state, "robot_ai_store", None)
    panels = ai_store.list_scene_panels(space["id"]) if ai_store is not None else []
    equipment = rt.repo.list_equipment(space["id"])
    walls = space.get("walls") or []
    latest_thumb = next(
        (p.get("texture_url") for p in reversed(panels) if p.get("texture_url")),
        None,
    )
    return {
        **space,
        "panel_count": len(panels),
        "equipment_count": len(equipment),
        "wall_count": len(walls),
        "thumbnail_url": latest_thumb,
    }


@router.get("/spaces")
async def list_spaces(request: Request) -> dict[str, Any]:
    """List all physical spaces with enriched summary counts and latest scene panel thumbnail."""
    rt = _state(request)
    spaces = [_enrich_space_summary(request, sp) for sp in rt.repo.list_spaces()]
    return {"active_space_id": rt.active_space_id, "spaces": spaces}


@router.post("/spaces")
async def create_space(body: CreateSpaceRequest, request: Request) -> dict[str, Any]:
    """Create a new scanned physical space and set it active."""
    rt = _state(request)
    space = rt.repo.create_space(name=body.name, facility=body.facility, description=body.description)
    rt.active_space_id = space["id"]
    return _enrich_space_summary(request, space)


@router.patch("/spaces/{space_id}")
async def update_space(space_id: str, body: UpdateSpaceRequest, request: Request) -> dict[str, Any]:
    """Rename or update facility/description metadata on an existing physical space."""
    rt = _state(request)
    updated = rt.repo.update_space(
        space_id,
        name=body.name,
        facility=body.facility,
        description=body.description,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Space not found")
    return _enrich_space_summary(request, updated)


@router.post("/spaces/{space_id}/clone")
async def clone_space(space_id: str, body: CloneSpaceRequest, request: Request) -> dict[str, Any]:
    """Clone an existing space (walls, zones, 3D scene panels, and equipment) into a new active checkpoint."""
    rt = _state(request)
    source = rt.repo.get_space(space_id)
    if not source:
        raise HTTPException(status_code=404, detail="Space not found")

    new_space = rt.repo.create_space(
        name=body.name.strip(),
        facility=body.facility.strip() if body.facility is not None else str(source.get("facility") or "Eigenia Facility"),
        description=body.description.strip() if body.description is not None else str(source.get("description") or ""),
    )
    new_id = new_space["id"]

    src_walls = list(source.get("walls") or [])
    src_metrics = dict(source.get("metrics") or {})
    if src_walls or src_metrics:
        rt.repo.save_walls(new_id, src_walls, src_metrics)

    src_zones = list(source.get("zones") or [])
    if src_zones:
        rt.repo.save_zones(new_id, src_zones)

    ai_store = getattr(request.app.state, "robot_ai_store", None)
    cloned_panels = 0
    if ai_store is not None:
        for panel in ai_store.list_scene_panels(space_id):
            panel_copy = dict(panel)
            panel_copy.pop("id", None)
            panel_copy.pop("created_at", None)
            panel_copy["space_id"] = new_id
            ai_store.save_scene_panel(panel_copy)
            cloned_panels += 1

    cloned_equipment = 0
    for eq in rt.repo.list_equipment(space_id):
        eq_copy = {
            k: v
            for k, v in eq.items()
            if k not in {"id", "space_id", "created_at", "updated_at", "completeness", "similarity"}
        }
        rt.repo.create_equipment(
            new_id,
            eq_copy,
            embedding=None,
            embedding_model=str(eq.get("embedding_model") or "fallback"),
        )
        cloned_equipment += 1

    rt.active_space_id = new_id
    final_space = rt.repo.get_space(new_id) or new_space
    return {
        "space": _enrich_space_summary(request, final_space),
        "cloned_panels": cloned_panels,
        "cloned_equipment": cloned_equipment,
    }


@router.delete("/spaces/{space_id}")
async def delete_space(space_id: str, request: Request) -> dict[str, Any]:
    """Delete a space and clear its reconstructed 3D scene panels (preventing deletion of the last space)."""
    rt = _state(request)
    spaces = rt.repo.list_spaces()
    if len(spaces) <= 1:
        raise HTTPException(status_code=400, detail="Cannot delete the only remaining space.")
    if not rt.repo.delete_space(space_id):
        raise HTTPException(status_code=404, detail="Space not found")
    ai_store = getattr(request.app.state, "robot_ai_store", None)
    if ai_store is not None:
        try:
            ai_store.clear_scene_panels(space_id)
        except Exception as exc:
            sys.stderr.write(f"[spaces.delete] Failed to clear scene panels for {space_id}: {exc}\n")
    remaining = rt.repo.list_spaces()
    if rt.active_space_id == space_id and remaining:
        rt.active_space_id = remaining[0]["id"]
    return {"deleted": True, "active_space_id": rt.active_space_id}


@router.get("/spaces/{space_id}")
async def get_space_detail(space_id: str, request: Request) -> dict[str, Any]:
    """Return space geometry, completeness-scored equipment, and anomalies."""
    rt = _state(request)
    space = rt.repo.get_space(space_id)
    if not space:
        raise HTTPException(status_code=404, detail="Space not found")
    rt.active_space_id = space_id
    return {
        "space": space,
        "equipment": _attach_completeness(rt.repo.list_equipment(space_id)),
        "anomalies": rt.repo.list_anomalies(space_id),
    }


@router.put("/spaces/{space_id}/zones")
async def save_space_zones(space_id: str, body: SaveZonesRequest, request: Request) -> dict[str, Any]:
    """Save polygon clearance/safety zones."""
    rt = _state(request)
    if not rt.repo.get_space(space_id):
        raise HTTPException(status_code=404, detail="Space not found")
    zones = rt.repo.save_zones(space_id, [z.model_dump() for z in body.zones])
    return {"space_id": space_id, "zones": zones}


@router.get("/spaces/{space_id}/equipment")
async def list_space_equipment(space_id: str, request: Request) -> dict[str, Any]:
    """List placed equipment assets within a space with completeness scores."""
    rt = _state(request)
    return {"space_id": space_id, "equipment": _attach_completeness(rt.repo.list_equipment(space_id))}


@router.post("/spaces/{space_id}/equipment")
async def pin_equipment_to_space(
    space_id: str,
    body: CreateEquipmentRequest,
    request: Request,
) -> dict[str, Any]:
    """Persist equipment in PostgreSQL 18 (with pgvector embedding) and sync to Neo4j."""
    rt = _state(request)
    space = rt.repo.get_space(space_id)
    if not space:
        raise HTTPException(status_code=404, detail="Space not found")

    summary_model = EquipmentVisionResult(
        name=body.name,
        equipment_type=body.equipment_type,
        dexpi_class=body.dexpi_class,
        manufacturer=body.manufacturer,
        model_number=body.model_number,
        part_number=body.part_number,
        serial_number=body.serial_number,
        inferred_cpe_23=body.inferred_cpe_23,
        voltage_rating=body.voltage_rating,
        asset_tags=body.asset_tags,
        mac_addresses=body.mac_addresses,
    )
    emb_model = rt.effective_config.get("openrouter_embedding_model", "fallback")
    embedding = await rt.vision.generate_embedding(summary_model.to_embedding_text())
    created = rt.repo.create_equipment(
        space_id,
        body.model_dump(),
        embedding=embedding,
        embedding_model=emb_model if rt.openrouter_configured else "fallback",
    )

    all_eq = rt.repo.list_equipment(space_id)
    neo4j_synced = rt.neo4j.sync_space_and_equipment(
        space=space,
        equipment=all_eq,
        max_near_m=rt.near_proximity_m,
    )
    return {
        "equipment": {**created, "completeness": score_equipment_completeness(created)},
        "neo4j_synced": neo4j_synced,
    }


@router.delete("/equipment/{equipment_id}")
async def delete_equipment_asset(equipment_id: str, request: Request) -> dict[str, Any]:
    """Delete an equipment asset from PostgreSQL 18 AND sync DETACH DELETE to Neo4j."""
    rt = _state(request)
    if not rt.repo.delete_equipment(equipment_id):
        raise HTTPException(status_code=404, detail="Equipment not found")
    neo4j_deleted = rt.neo4j.delete_equipment_node(equipment_id)
    return {"deleted": True, "equipment_id": equipment_id, "neo4j_deleted": neo4j_deleted}


@router.post("/equipment/search")
async def search_equipment_semantic(body: SemanticSearchRequest, request: Request) -> dict[str, Any]:
    """Execute PostgreSQL 18 pgvector halfvec iterative HNSW semantic search."""
    rt = _state(request)
    q_emb = await rt.vision.generate_embedding(body.query)
    matches = rt.repo.search_equipment_semantic(
        query_embedding=q_emb,
        limit=body.limit,
        space_id=body.space_id,
        manufacturer=body.manufacturer,
    )
    return {"query": body.query, "count": len(matches), "results": _attach_completeness(matches)}


@router.get("/spaces/{space_id}/graph")
async def get_space_knowledge_graph(space_id: str, request: Request) -> dict[str, Any]:
    """Return the Eigenia Schema G_CPDT Knowledge Graph topology (including Dark Zones & Risk)."""
    rt = _state(request)
    space = rt.repo.get_space(space_id)
    if not space:
        raise HTTPException(status_code=404, detail="Space not found")
    equipment = rt.repo.list_equipment(space_id)
    anomalies = rt.repo.list_anomalies(space_id)
    payload = build_graph_payload(
        space=space,
        equipment=equipment,
        anomalies=anomalies,
        dark_zones=[d.to_dict() for d in rt.latest_dark_zones],
        max_near_m=rt.near_proximity_m,
    )
    payload["neo4j"] = rt.neo4j.check_health()
    return payload


@router.get("/spaces/{space_id}/export/{fmt}")
async def export_space_artifact(space_id: str, fmt: str, request: Request) -> Response:
    """Export CycloneDX 1.6 HBOM, DEXPI JSON, Cypher, AutoCAD DXF, 3D glTF, or PLY."""
    rt = _state(request)
    space = rt.repo.get_space(space_id)
    if not space:
        raise HTTPException(status_code=404, detail="Space not found")
    equipment = rt.repo.list_equipment(space_id)
    walls = space.get("walls") or [w.to_dict() for w in rt.latest_walls]
    zones = space.get("zones") or []

    fmt_lower = fmt.lower()
    if fmt_lower == "cyclonedx":
        data = json.dumps(export_cyclonedx_hbom(space, equipment), indent=2).encode("utf-8")
        return Response(
            content=data,
            media_type="application/vnd.cyclonedx+json",
            headers={"Content-Disposition": f'attachment; filename="twinscan-{space_id[:8]}-hbom.cdx.json"'},
        )
    if fmt_lower == "dexpi":
        data = json.dumps(export_dexpi_graph_json({**space, "walls": walls}, equipment), indent=2).encode("utf-8")
        return Response(
            content=data,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="twinscan-{space_id[:8]}-gcpdt.json"'},
        )
    if fmt_lower == "cypher":
        cypher = export_cypher_script(space, equipment).encode("utf-8")
        return Response(
            content=cypher,
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="twinscan-{space_id[:8]}.cypher"'},
        )
    if fmt_lower == "dxf":
        dxf_bytes = export_dxf_floorplan(walls, equipment, zones)
        return Response(
            content=dxf_bytes,
            media_type="application/dxf",
            headers={"Content-Disposition": f'attachment; filename="twinscan-{space_id[:8]}.dxf"'},
        )
    if fmt_lower == "gltf":
        glb_bytes = export_gltf_scene(walls, equipment, wall_height_m=rt.default_wall_height_m)
        return Response(
            content=glb_bytes,
            media_type="model/gltf-binary",
            headers={"Content-Disposition": f'attachment; filename="twinscan-{space_id[:8]}.glb"'},
        )
    if fmt_lower == "ply":
        ply_text = export_ply_point_cloud(rt.latest_points).encode("utf-8")
        return Response(
            content=ply_text,
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="twinscan-{space_id[:8]}.ply"'},
        )

    raise HTTPException(
        status_code=400,
        detail="Unsupported export format. Choose from: cyclonedx, dexpi, cypher, dxf, gltf, ply.",
    )


# --- 3D Real-Room Fusion (Stage 1 Single-Wall, Stage 2 360° Turn Capture & 5-Pass Enhancement) ---


class SceneEnhanceOptionsModel(BaseModel):
    """Optional 5-pass composite enhancement preset and per-pass overrides."""

    quality_preset: Literal["fast", "balanced", "studio_ultra"] = "balanced"
    burst_frames: Optional[int] = Field(default=None, ge=1, le=5)
    clahe_sharpen: Optional[bool] = None
    upscale_2x: Optional[bool] = None
    flip_tta: Optional[bool] = None
    guided_depth: Optional[bool] = None
    normal_map: Optional[bool] = None
    taubin_smooth: Optional[bool] = None

    def to_enhance_dict(self) -> dict[str, Any]:
        """Serialize preset and non-None pass overrides for ``resolve_enhance_preset``."""
        return {
            "quality_preset": self.quality_preset,
            "burst_frames": self.burst_frames,
            "clahe_sharpen": self.clahe_sharpen,
            "upscale_2x": self.upscale_2x,
            "flip_tta": self.flip_tta,
            "guided_depth": self.guided_depth,
            "normal_map": self.normal_map,
            "taubin_smooth": self.taubin_smooth,
        }


class CaptureWallRequest(SceneEnhanceOptionsModel):
    """Payload to capture a single textured 3D relief wall panel without moving the robot."""

    robot_id: Optional[str] = None
    label: Optional[str] = None
    yaw_deg: float = 0.0
    pitch_deg: float = 0.0
    roll_deg: float = 0.0
    x: float = 0.0
    y: float = 0.0
    z: float = 0.22
    fallback_distance_m: float = Field(default=1.8, ge=0.4, le=6.0)
    resolution: Literal["low", "medium", "high"] = "medium"
    depth_relief_scale: float = Field(default=1.0, ge=0.1, le=3.0)
    hfov_deg: float = Field(default=65.0, ge=25.0, le=130.0)
    vfov_deg: float = Field(default=50.0, ge=20.0, le=110.0)


class Capture360Request(SceneEnhanceOptionsModel):
    """Payload to perform a stepped 360-degree in-place turn capture around PuppyPi."""

    robot_id: str
    steps: int = Field(default=8, ge=4, le=12)
    fallback_distance_m: float = Field(default=1.8, ge=0.4, le=6.0)
    resolution: Literal["low", "medium", "high"] = "low"
    depth_relief_scale: float = Field(default=1.0, ge=0.1, le=3.0)
    turn_duration_s: float = Field(default=0.9, ge=0.1, le=4.0)
    settle_s: float = Field(default=0.7, ge=0.0, le=3.0)
    yaw_rate_rad_s: float = Field(default=0.85, ge=0.1, le=0.89)
    hfov_deg: float = Field(default=65.0, ge=25.0, le=130.0)
    vfov_deg: float = Field(default=50.0, ge=20.0, le=110.0)


class EnhancePanelRequest(SceneEnhanceOptionsModel):
    """Payload to re-enhance an already-captured scene panel without moving the robot."""

    resolution: Optional[Literal["low", "medium", "high"]] = None
    depth_relief_scale: float = Field(default=1.0, ge=0.1, le=3.0)
    fallback_distance_m: Optional[float] = Field(default=None, ge=0.4, le=6.0)


def _robot_store(request: Request) -> RobotStoreProtocol:
    return request.app.state.robot_store


def _ai_store(request: Request) -> RobotAiStoreProtocol:
    return request.app.state.robot_ai_store


def _resolve_target_robot(request: Request, robot_id: Optional[str]) -> dict[str, Any]:
    """Resolve an explicit robot ID or pick the first online/registered robot."""
    store = _robot_store(request)
    if robot_id:
        robot = store.get_robot(robot_id)
        if not robot:
            raise HTTPException(status_code=404, detail=f"Robot {robot_id!r} not found.")
        return robot
    robots = store.list_robots()
    if not robots:
        raise HTTPException(
            status_code=400,
            detail="No PuppyPi robot registered. Discover or register a robot first.",
        )
    online = [r for r in robots if r.get("status") == "online"]
    return online[0] if online else robots[0]


def _extract_live_lidar_xy(rt: TwinScanRuntimeState) -> Optional[List[tuple[float, float]]]:
    """Return real physical 2D LiDAR points only when live hardware/ROS2 `/scan` is active."""
    if rt.source_mode == "robot_ros2" and rt.robot_scan_connected and rt.latest_points:
        return [(float(p.x), float(p.y)) for p in rt.latest_points]
    if rt.source_mode == "hardware" and rt.latest_points:
        return [(float(p.x), float(p.y)) for p in rt.latest_points]
    return None


def _infer_resolution_from_mesh(mesh: dict[str, Any]) -> str:
    """Infer ``low`` / ``medium`` / ``high`` preset from an existing panel mesh grid width."""
    gw = int(mesh.get("grid_w") or 80)
    if gw <= 52:
        return "low"
    if gw >= 100:
        return "high"
    return "medium"


async def _capture_and_store_panel(
    rt: TwinScanRuntimeState,
    ai_store: RobotAiStoreProtocol,
    space_id: str,
    robot: dict[str, Any],
    *,
    label: str,
    stage: str,
    pose: dict[str, float],
    fallback_distance_m: float,
    resolution: str,
    depth_relief_scale: float,
    hfov_deg: float,
    vfov_deg: float,
    enhance_options: Optional[dict[str, Any]] = None,
) -> tuple[dict[str, Any], str]:
    """Capture live camera burst, fuse with live LiDAR sweeps + 5-pass enhancement, store assets, and persist panel."""
    ip = str(robot["ip_address"])
    video_port = int(robot.get("video_port") or 8080)
    ros_version = str(robot.get("ros_version") or "ros2")
    resolved_cfg = resolve_enhance_preset(
        quality_preset=str((enhance_options or {}).get("quality_preset") or "balanced"),
        overrides=enhance_options,
    )
    burst_count = int(resolved_cfg["burst_frames"])
    sweep_count = int(resolved_cfg["lidar_sweeps"])

    jpeg_frames: List[bytes] = []
    lidar_sweeps: List[List[tuple[float, float]]] = []
    topic_used = "/image_raw"

    for idx in range(max(1, burst_count)):
        try:
            frame_bytes, topic_used = await capture_live_camera_frame(
                ip=ip,
                video_port=video_port,
                ros_version=ros_version,
            )
            jpeg_frames.append(frame_bytes)
        except Exception as exc:
            if not jpeg_frames:
                sys.stderr.write(f"[reconstruct] Camera capture failed for {ip}:{video_port}: {exc}\n")
                raise HTTPException(
                    status_code=502,
                    detail=f"Unable to capture live frame from robot camera ({ip}:{video_port}): {exc}",
                ) from exc
            sys.stderr.write(f"[reconstruct] Burst frame {idx + 1}/{burst_count} skipped: {exc}\n")
            break
        if len(lidar_sweeps) < sweep_count:
            pts = _extract_live_lidar_xy(rt)
            if pts:
                lidar_sweeps.append(pts)
        if idx < burst_count - 1:
            await asyncio.sleep(0.05)

    # Collect any remaining live LiDAR sweeps if requested.
    while len(lidar_sweeps) < sweep_count:
        pts = _extract_live_lidar_xy(rt)
        if not pts:
            break
        lidar_sweeps.append(pts)
        if len(lidar_sweeps) < sweep_count:
            await asyncio.sleep(0.05)

    try:
        reconstructed, enhanced_jpeg, normal_jpeg, glb_bytes = await asyncio.to_thread(
            reconstruct_enhanced_wall_panel,
            jpeg_frames=jpeg_frames,
            lidar_sweeps_xy=lidar_sweeps or None,
            pose=pose,
            resolution=resolution,
            fallback_distance_m=fallback_distance_m,
            depth_relief_scale=depth_relief_scale,
            hfov_deg=hfov_deg,
            vfov_deg=vfov_deg,
            enhance_options=resolved_cfg,
        )
    except Exception as exc:
        sys.stderr.write(f"[reconstruct] Mesh reconstruction failed: {exc}\n")
        raise HTTPException(status_code=500, detail=f"3D wall reconstruction failed: {exc}") from exc

    safe_slug = "".join(ch if ch.isalnum() else "_" for ch in label.lower()).strip("_")[:32] or "wall"
    tex_rec = rt.repo.store_file(
        filename=f"scene-{safe_slug}.jpg",
        content_type="image/jpeg",
        data=enhanced_jpeg,
        category="scene_texture",
        space_id=space_id,
        metadata={"robot_id": robot["id"], "topic": topic_used, "stage": stage, "preset": resolved_cfg["quality_preset"]},
    )
    norm_rec = None
    if normal_jpeg:
        norm_rec = rt.repo.store_file(
            filename=f"scene-{safe_slug}-normal.jpg",
            content_type="image/jpeg",
            data=normal_jpeg,
            category="scene_normal",
            space_id=space_id,
            metadata={"robot_id": robot["id"], "stage": stage},
        )
    glb_rec = rt.repo.store_file(
        filename=f"scene-{safe_slug}.glb",
        content_type="model/gltf-binary",
        data=glb_bytes,
        category="scene_glb",
        space_id=space_id,
        metadata={"robot_id": robot["id"], "stage": stage},
    )

    saved = ai_store.save_scene_panel(
        {
            "space_id": space_id,
            "robot_id": robot["id"],
            "label": label,
            "stage": stage,
            "pose": reconstructed["pose"],
            "lidar_calibrated": reconstructed["lidar_calibrated"],
            "lidar_ray_count": reconstructed["lidar_ray_count"],
            "depth_source": reconstructed["depth_source"],
            "mean_distance_m": reconstructed["mean_distance_m"],
            "min_distance_m": reconstructed["min_distance_m"],
            "max_distance_m": reconstructed["max_distance_m"],
            "vertex_count": reconstructed["vertex_count"],
            "triangle_count": reconstructed["triangle_count"],
            "texture_file_id": tex_rec["id"],
            "normal_map_file_id": norm_rec["id"] if norm_rec else None,
            "normal_map_url": f"/api/files/{norm_rec['id']}" if norm_rec else None,
            "glb_file_id": glb_rec["id"],
            "quality_metrics": reconstructed.get("quality_metrics"),
            "mesh": reconstructed["mesh"],
        }
    )

    qm = saved.get("quality_metrics") or {}
    preset_tag = qm.get("preset", resolved_cfg["quality_preset"])
    if saved["lidar_calibrated"]:
        note = f"[{preset_tag}] LD19 metric calibrated with {saved['lidar_ray_count']} live rays ({saved['depth_source']}, {topic_used})."
    else:
        note = f"[{preset_tag}] Captured with {saved['depth_source']} around {fallback_distance_m:.2f}m (LD19 LiDAR offline; {topic_used})."
    return saved, note


@router.get("/spaces/{space_id}/reconstruct/panels")
async def list_scene_panels(space_id: str, request: Request) -> dict[str, Any]:
    """List all reconstructed 3D real-room scene panels for ``space_id``."""
    rt = _state(request)
    if not rt.repo.get_space(space_id):
        raise HTTPException(status_code=404, detail="Space not found")
    panels = _ai_store(request).list_scene_panels(space_id)
    return {"space_id": space_id, "panels": panels}


@router.post("/spaces/{space_id}/reconstruct/capture-wall")
async def capture_single_wall_panel(
    space_id: str,
    body: CaptureWallRequest,
    request: Request,
) -> dict[str, Any]:
    """Capture a single textured 3D relief wall panel from PuppyPi's live camera (zero movement)."""
    rt = _state(request)
    if not rt.repo.get_space(space_id):
        raise HTTPException(status_code=404, detail="Space not found")

    robot = _resolve_target_robot(request, body.robot_id)
    ai_store = _ai_store(request)
    existing_count = len(ai_store.list_scene_panels(space_id))
    label = (body.label or "").strip() or f"Wall View #{existing_count + 1}"

    pose = {
        "x": float(body.x),
        "y": float(body.y),
        "z": float(body.z),
        "yaw_deg": float(body.yaw_deg),
        "pitch_deg": float(body.pitch_deg),
        "roll_deg": float(body.roll_deg),
    }
    panel, note = await _capture_and_store_panel(
        rt,
        ai_store,
        space_id,
        robot,
        label=label,
        stage="single_wall",
        pose=pose,
        fallback_distance_m=body.fallback_distance_m,
        resolution=body.resolution,
        depth_relief_scale=body.depth_relief_scale,
        hfov_deg=body.hfov_deg,
        vfov_deg=body.vfov_deg,
        enhance_options=body.to_enhance_dict(),
    )
    return {"ok": True, "panel": panel, "note": note}


@router.post("/spaces/{space_id}/reconstruct/panels/{panel_id}/enhance")
async def enhance_existing_scene_panel(
    space_id: str,
    panel_id: str,
    body: EnhancePanelRequest,
    request: Request,
) -> dict[str, Any]:
    """Re-run Passes 2 + 4 enhancement on an existing captured panel (zero robot movement)."""
    rt = _state(request)
    if not rt.repo.get_space(space_id):
        raise HTTPException(status_code=404, detail="Space not found")

    ai_store = _ai_store(request)
    existing = ai_store.get_scene_panel(panel_id)
    if not existing or existing.get("space_id") != space_id:
        raise HTTPException(status_code=404, detail="Scene panel not found")

    tex_id = existing.get("texture_file_id")
    if not tex_id:
        raise HTTPException(status_code=400, detail="Panel has no stored texture image to enhance.")
    found = rt.repo.get_file_with_bytes(tex_id)
    if not found:
        raise HTTPException(status_code=404, detail="Stored texture blob not found.")
    _, orig_jpeg = found

    existing_mesh = existing.get("mesh") or {}
    resolution = body.resolution or _infer_resolution_from_mesh(existing_mesh)
    fallback_dist = float(body.fallback_distance_m if body.fallback_distance_m is not None else (existing.get("mean_distance_m") or 1.8))
    hfov_deg = float(existing_mesh.get("hfov_deg") or 65.0)
    vfov_deg = float(existing_mesh.get("vfov_deg") or 50.0)
    pose = dict(existing.get("pose") or {"x": 0.0, "y": 0.0, "z": 0.22, "yaw_deg": 0.0, "pitch_deg": 0.0, "roll_deg": 0.0})

    opts = body.to_enhance_dict()
    opts["burst_frames"] = 1  # Single-image re-enhancement (Passes 2 + 4)
    resolved_cfg = resolve_enhance_preset(quality_preset=body.quality_preset, overrides=opts)
    lidar_pts = _extract_live_lidar_xy(rt)

    try:
        reconstructed, enhanced_jpeg, normal_jpeg, glb_bytes = await asyncio.to_thread(
            reconstruct_enhanced_wall_panel,
            jpeg_frames=[orig_jpeg],
            lidar_sweeps_xy=[lidar_pts] if lidar_pts else None,
            pose=pose,
            resolution=resolution,
            fallback_distance_m=fallback_dist,
            depth_relief_scale=body.depth_relief_scale,
            hfov_deg=hfov_deg,
            vfov_deg=vfov_deg,
            enhance_options=resolved_cfg,
        )
    except Exception as exc:
        sys.stderr.write(f"[reconstruct.enhance] Panel {panel_id} enhancement failed: {exc}\n")
        raise HTTPException(status_code=500, detail=f"Panel enhancement failed: {exc}") from exc

    label = str(existing.get("label") or "Wall View")
    safe_slug = "".join(ch if ch.isalnum() else "_" for ch in label.lower()).strip("_")[:32] or "wall"
    new_tex = rt.repo.store_file(
        filename=f"scene-{safe_slug}-enh.jpg",
        content_type="image/jpeg",
        data=enhanced_jpeg,
        category="scene_texture",
        space_id=space_id,
        metadata={"panel_id": panel_id, "preset": resolved_cfg["quality_preset"], "enhanced": True},
    )
    new_norm = None
    if normal_jpeg:
        new_norm = rt.repo.store_file(
            filename=f"scene-{safe_slug}-normal.jpg",
            content_type="image/jpeg",
            data=normal_jpeg,
            category="scene_normal",
            space_id=space_id,
            metadata={"panel_id": panel_id},
        )
    new_glb = rt.repo.store_file(
        filename=f"scene-{safe_slug}-enh.glb",
        content_type="model/gltf-binary",
        data=glb_bytes,
        category="scene_glb",
        space_id=space_id,
        metadata={"panel_id": panel_id, "enhanced": True},
    )

    updated = ai_store.save_scene_panel(
        {
            **existing,
            "id": panel_id,
            "pose": reconstructed["pose"],
            "lidar_calibrated": reconstructed["lidar_calibrated"],
            "lidar_ray_count": reconstructed["lidar_ray_count"],
            "depth_source": reconstructed["depth_source"],
            "mean_distance_m": reconstructed["mean_distance_m"],
            "min_distance_m": reconstructed["min_distance_m"],
            "max_distance_m": reconstructed["max_distance_m"],
            "vertex_count": reconstructed["vertex_count"],
            "triangle_count": reconstructed["triangle_count"],
            "texture_file_id": new_tex["id"],
            "normal_map_file_id": new_norm["id"] if new_norm else None,
            "normal_map_url": f"/api/files/{new_norm['id']}" if new_norm else None,
            "glb_file_id": new_glb["id"],
            "quality_metrics": reconstructed.get("quality_metrics"),
            "mesh": reconstructed["mesh"],
        }
    )
    qm = updated.get("quality_metrics") or {}
    note = (
        f"Enhanced with preset '{qm.get('preset', body.quality_preset)}' "
        f"({qm.get('texture_width')}x{qm.get('texture_height')}, "
        f"sharpness {qm.get('sharpness_gain_pct', 0.0):+.1f}%, "
        f"normal_map={'yes' if qm.get('has_normal_map') else 'no'})."
    )
    return {"ok": True, "panel": updated, "note": note}


@router.post("/spaces/{space_id}/reconstruct/capture-360")
async def capture_360_room_panels(
    space_id: str,
    body: Capture360Request,
    request: Request,
) -> dict[str, Any]:
    """Rotate PuppyPi in place through 360 degrees in discrete steps and capture textured 3D panels."""
    rt = _state(request)
    if not rt.repo.get_space(space_id):
        raise HTTPException(status_code=404, detail="Space not found")

    robot = _resolve_target_robot(request, body.robot_id)
    ai_store = _ai_store(request)
    ip = str(robot["ip_address"])
    ros_port = int(robot.get("rosbridge_port") or 9090)
    ros_version = str(robot.get("ros_version") or "ros2")
    robot_id = str(robot["id"])

    panels: List[dict[str, Any]] = []
    aborted = False
    note = ""
    start_imu_yaw: Optional[float] = (
        float(rt.robot_pose["yaw_deg"])
        if (rt.robot_pose or {}).get("live") and (rt.robot_pose or {}).get("yaw_deg") is not None
        else None
    )
    prev_imu_yaw: Optional[float] = start_imu_yaw

    def _is_estopped() -> bool:
        estop_set = getattr(request.app.state, "estop_active_robots", None)
        return bool(estop_set and robot_id in estop_set)

    try:
        for step_idx in range(body.steps):
            if _is_estopped() or await request.is_disconnected():
                aborted = True
                note = f"360° capture aborted safely before step {step_idx + 1}/{body.steps}."
                break

            nominal_yaw = round(step_idx * (360.0 / body.steps), 2)
            yaw_deg = nominal_yaw
            if step_idx > 0 and start_imu_yaw is not None and (rt.robot_pose or {}).get("live") and (rt.robot_pose or {}).get("yaw_deg") is not None:
                cur_imu = float(rt.robot_pose["yaw_deg"])
                step_delta = abs(((cur_imu - (prev_imu_yaw if prev_imu_yaw is not None else start_imu_yaw) + 180.0) % 360.0) - 180.0)
                if step_delta >= 5.0:
                    yaw_deg = round((cur_imu - start_imu_yaw) % 360.0, 2)
                    prev_imu_yaw = cur_imu
            label = f"360° View {step_idx + 1}/{body.steps} ({int(round(yaw_deg))}°)"
            pose = {
                "x": 0.0,
                "y": 0.0,
                "z": 0.22,
                "yaw_deg": yaw_deg,
                "pitch_deg": 0.0,
                "roll_deg": 0.0,
            }
            panel, _ = await _capture_and_store_panel(
                rt,
                ai_store,
                space_id,
                robot,
                label=label,
                stage="pano_360",
                pose=pose,
                fallback_distance_m=body.fallback_distance_m,
                resolution=body.resolution,
                depth_relief_scale=body.depth_relief_scale,
                hfov_deg=body.hfov_deg,
                vfov_deg=body.vfov_deg,
                enhance_options=body.to_enhance_dict(),
            )
            panels.append(panel)

            if step_idx < body.steps - 1:
                if _is_estopped() or await request.is_disconnected():
                    aborted = True
                    note = f"360° capture aborted safely after step {step_idx + 1}/{body.steps}."
                    break
                try:
                    await publish_velocity(
                        ip=ip,
                        port=ros_port,
                        x=0.0,
                        y=0.0,
                        yaw_rate=body.yaw_rate_rad_s,
                        ros_version=ros_version,
                        use_autogait=True,
                        robot_id=robot_id,
                    )
                    await asyncio.sleep(body.turn_duration_s)
                    await publish_velocity(
                        ip=ip,
                        port=ros_port,
                        x=0.0,
                        y=0.0,
                        yaw_rate=0.0,
                        ros_version=ros_version,
                        use_autogait=True,
                        robot_id=robot_id,
                    )
                    if body.settle_s > 0:
                        await asyncio.sleep(body.settle_s)
                except Exception as exc:
                    aborted = True
                    note = f"Rotation interrupted on step {step_idx + 1}/{body.steps}: {exc}"
                    sys.stderr.write(f"[reconstruct.360] Turn error on {ip}: {exc}\n")
                    break
    finally:
        try:
            await publish_velocity(
                ip=ip,
                port=ros_port,
                x=0.0,
                y=0.0,
                yaw_rate=0.0,
                ros_version=ros_version,
                use_autogait=True,
                robot_id=robot_id,
            )
        except Exception as exc:
            sys.stderr.write(f"[reconstruct.360] Zero-velocity stop in finally failed on {ip}: {exc}\n")

    if not note:
        note = f"Captured {len(panels)}/{body.steps} textured 360° room views."
    return {
        "ok": True,
        "panels": panels,
        "aborted": aborted,
        "completed_steps": len(panels),
        "total_steps": body.steps,
        "note": note,
    }


@router.delete("/spaces/{space_id}/reconstruct/panels/{panel_id}")
async def delete_scene_panel(space_id: str, panel_id: str, request: Request) -> dict[str, Any]:
    """Delete a single reconstructed 3D scene panel and prune its stored texture/normal/GLB blobs."""
    rt = _state(request)
    ai_store = _ai_store(request)
    existing = ai_store.get_scene_panel(panel_id)
    if not existing or existing.get("space_id") != space_id:
        raise HTTPException(status_code=404, detail="Scene panel not found")
    ai_store.delete_scene_panel(panel_id)
    for key in ("texture_file_id", "normal_map_file_id", "glb_file_id"):
        fid = existing.get(key)
        if fid:
            try:
                rt.repo.delete_file(fid)
            except Exception as exc:
                sys.stderr.write(f"[reconstruct] Failed to prune file {fid}: {exc}\n")
    return {"deleted": True, "panel_id": panel_id}


@router.delete("/spaces/{space_id}/reconstruct/panels")
async def clear_space_scene_panels(space_id: str, request: Request) -> dict[str, Any]:
    """Delete all reconstructed 3D scene panels for ``space_id``."""
    rt = _state(request)
    if not rt.repo.get_space(space_id):
        raise HTTPException(status_code=404, detail="Space not found")
    ai_store = _ai_store(request)
    existing = ai_store.list_scene_panels(space_id)
    deleted_count = ai_store.clear_scene_panels(space_id)
    for panel in existing:
        for key in ("texture_file_id", "normal_map_file_id", "glb_file_id"):
            fid = panel.get(key)
            if fid:
                try:
                    rt.repo.delete_file(fid)
                except Exception as exc:
                    sys.stderr.write(f"[reconstruct] Failed to prune file {fid}: {exc}\n")
    return {"deleted_count": deleted_count}


@router.get("/spaces/{space_id}/reconstruct/export-room.glb")
async def export_combined_room_glb_route(space_id: str, request: Request) -> Response:
    """Export all reconstructed 3D panels in ``space_id`` as a single binary glTF 2.0 ``.glb`` room model."""
    rt = _state(request)
    space = rt.repo.get_space(space_id)
    if not space:
        raise HTTPException(status_code=404, detail="Space not found")
    panels = _ai_store(request).list_scene_panels(space_id)
    if not panels:
        raise HTTPException(status_code=404, detail="No reconstructed 3D scene panels exist in this space.")

    entries: List[dict[str, Any]] = []
    for panel in panels:
        tex_id = panel.get("texture_file_id")
        if not tex_id:
            continue
        tex_found = rt.repo.get_file_with_bytes(tex_id)
        if not tex_found:
            continue
        _, tex_bytes = tex_found
        norm_bytes: Optional[bytes] = None
        norm_id = panel.get("normal_map_file_id")
        if norm_id:
            norm_found = rt.repo.get_file_with_bytes(norm_id)
            if norm_found:
                _, norm_bytes = norm_found
        entries.append(
            {
                "label": panel.get("label") or "WallPanel",
                "mesh": panel.get("mesh") or {},
                "jpeg_bytes": tex_bytes,
                "normal_jpeg_bytes": norm_bytes,
            }
        )

    if not entries:
        raise HTTPException(status_code=404, detail="No stored panel textures available to build room .glb.")

    try:
        glb_bytes = await asyncio.to_thread(export_combined_room_glb, entries)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    raw_name = str(space.get("name") or space_id[:8])
    safe_name = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in raw_name.lower()).strip("_")[:48] or "twinscan"
    return Response(
        content=glb_bytes,
        media_type="model/gltf-binary",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}-room.glb"'},
    )
