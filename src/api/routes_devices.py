"""FastAPI routes for Universal Hardware Envelope, Lab Inventory, Local Bridges, and Co-Design Architect."""

from __future__ import annotations

import asyncio
import sys
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from src.ai.lab_architect import (
    evaluate_design_idea,
    generate_inventory_ideas,
    refine_blueprint,
)
from src.devices.envelope import (
    build_starter_lab_inventory,
    list_device_profiles,
)
from src.devices.local_camera_bridge import (
    generate_pi_zero_gadget_setup_script,
    ingest_local_media_to_spatial_memory,
)
from src.devices.microbit_bridge import (
    probe_microbit_usb,
    send_microbit_serial_command,
)

router = APIRouter(prefix="/api", tags=["devices-inventory-architect"])


class CreateManagedDeviceRequest(BaseModel):
    """Payload for registering a non-robot IoT/camera/microcontroller device."""

    name: str = Field(..., min_length=1, max_length=120)
    profile_id: str = Field(default="generic_sensor_module", max_length=64)
    space_id: Optional[str] = Field(default=None, max_length=120)
    transport: str = Field(default="usb", max_length=64)
    endpoint: str = Field(default="", max_length=512)
    status: str = Field(default="offline", max_length=32)
    config: Dict[str, Any] = Field(default_factory=dict)


class UpdateManagedDeviceRequest(BaseModel):
    """Payload for updating an existing managed device."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    profile_id: Optional[str] = Field(default=None, max_length=64)
    space_id: Optional[str] = Field(default=None, max_length=120)
    transport: Optional[str] = Field(default=None, max_length=64)
    endpoint: Optional[str] = Field(default=None, max_length=512)
    status: Optional[str] = Field(default=None, max_length=32)
    config: Optional[Dict[str, Any]] = None
    last_seen_at: Optional[str] = None


class MicrobitCommandRequest(BaseModel):
    """Payload for dispatching a command to a USB-connected BBC micro:bit v2.21."""

    port: Optional[str] = Field(default=None, max_length=256)
    action: str = Field(..., min_length=1, max_length=64)
    payload: Any = None


class CreateInventoryItemRequest(BaseModel):
    """Payload for creating a lab hardware inventory item."""

    name: str = Field(..., min_length=1, max_length=160)
    profile_id: Optional[str] = Field(default=None, max_length=64)
    category: str = Field(default="accessory", max_length=32)
    manufacturer: str = Field(default="", max_length=120)
    model: str = Field(default="", max_length=120)
    quantity: int = Field(default=1, ge=0, le=9999)
    status: str = Field(default="available", max_length=32)
    location: str = Field(default="", max_length=160)
    interfaces: List[str] = Field(default_factory=list)
    voltage_v: Optional[float] = Field(default=None, ge=0.0, le=240.0)
    current_ma: Optional[int] = Field(default=None, ge=0, le=100000)
    capabilities: List[str] = Field(default_factory=list)
    notes: str = Field(default="", max_length=2000)
    est_cost_usd: Optional[float] = Field(default=None, ge=0.0, le=1000000.0)


class UpdateInventoryItemRequest(BaseModel):
    """Payload for updating a lab hardware inventory item."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=160)
    profile_id: Optional[str] = Field(default=None, max_length=64)
    category: Optional[str] = Field(default=None, max_length=32)
    manufacturer: Optional[str] = Field(default=None, max_length=120)
    model: Optional[str] = Field(default=None, max_length=120)
    quantity: Optional[int] = Field(default=None, ge=0, le=9999)
    status: Optional[str] = Field(default=None, max_length=32)
    location: Optional[str] = Field(default=None, max_length=160)
    interfaces: Optional[List[str]] = None
    voltage_v: Optional[float] = Field(default=None, ge=0.0, le=240.0)
    current_ma: Optional[int] = Field(default=None, ge=0, le=100000)
    capabilities: Optional[List[str]] = None
    notes: Optional[str] = Field(default=None, max_length=2000)
    est_cost_usd: Optional[float] = Field(default=None, ge=0.0, le=1000000.0)


class ArchitectEvaluateRequest(BaseModel):
    """Payload for evaluating a hardware/robotics idea against lab inventory."""

    idea: str = Field(..., min_length=2, max_length=2000)
    creativity_level: int = Field(default=3, ge=1, le=5)
    persona: str = Field(default="systems_architect", max_length=64)
    locked_part_ids: List[str] = Field(default_factory=list)
    excluded_part_ids: List[str] = Field(default_factory=list)
    canvas_part_names: List[str] = Field(default_factory=list)
    model: Optional[str] = Field(default=None, max_length=120)


class ArchitectIdeateRequest(BaseModel):
    """Payload for generating inventory-grounded hardware project ideas."""

    creativity_level: int = Field(default=3, ge=1, le=5)
    focus_area: str = Field(default="all", max_length=64)
    count: int = Field(default=4, ge=1, le=8)
    locked_part_ids: List[str] = Field(default_factory=list)
    excluded_part_ids: List[str] = Field(default_factory=list)
    model: Optional[str] = Field(default=None, max_length=120)


class ArchitectRefineRequest(BaseModel):
    """Payload for iteratively refining a saved Co-Design Architect blueprint."""

    message: str = Field(default="", max_length=2000)
    selected_node_id: Optional[str] = Field(default=None, max_length=120)
    creativity_level: Optional[int] = Field(default=None, ge=1, le=5)
    persona: Optional[str] = Field(default=None, max_length=64)
    locked_part_ids: Optional[List[str]] = None
    excluded_part_ids: Optional[List[str]] = None
    accept_missing_part: Optional[str] = Field(default=None, max_length=160)
    model: Optional[str] = Field(default=None, max_length=120)


def _openrouter_settings(request: Request, requested_model: Optional[str] = None) -> tuple[str, str, str]:
    """Read decrypted OpenRouter API key, base URL, and active model from runtime effective config."""
    rt = request.app.state.runtime
    cfg = getattr(rt, "effective_config", {}) or {}
    api_key = str(cfg.get("openrouter_api_key") or "").strip()
    base_url = str(cfg.get("openrouter_base_url") or "https://openrouter.ai/api/v1").strip()
    model = (
        str(requested_model or "").strip()
        or str(cfg.get("openrouter_default_vision_model") or "").strip()
        or "google/gemini-2.5-flash"
    )
    return api_key, base_url, model


# ---------------------------------------------------------------------------
# Universal Hardware Envelope & Managed Devices
# ---------------------------------------------------------------------------


@router.get("/devices/profiles")
async def get_device_profiles() -> Dict[str, Any]:
    """List all 6 loadable Universal Hardware Envelope device profiles."""
    return {"profiles": list_device_profiles()}


@router.get("/devices")
async def list_managed_devices(
    request: Request,
    profile_id: Optional[str] = Query(default=None),
    space_id: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    """List registered non-robot managed devices with optional profile/space filters."""
    ai_store = request.app.state.robot_ai_store
    devices = ai_store.list_managed_devices(profile_id=profile_id, space_id=space_id)
    return {"devices": devices}


@router.post("/devices")
async def create_managed_device(body: CreateManagedDeviceRequest, request: Request) -> Dict[str, Any]:
    """Register a new non-robot managed device (Pi Zero 2 W, micro:bit, local camera, sensor)."""
    ai_store = request.app.state.robot_ai_store
    try:
        device = ai_store.create_managed_device(body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "device": device}


@router.patch("/devices/{device_id}")
async def update_managed_device(
    device_id: str,
    body: UpdateManagedDeviceRequest,
    request: Request,
) -> Dict[str, Any]:
    """Update fields on an existing managed device."""
    ai_store = request.app.state.robot_ai_store
    updates = body.model_dump(exclude_unset=True)
    updated = ai_store.update_managed_device(device_id, updates)
    if not updated:
        raise HTTPException(status_code=404, detail="Managed device not found.")
    return {"ok": True, "device": updated}


@router.delete("/devices/{device_id}")
async def delete_managed_device(device_id: str, request: Request) -> Dict[str, Any]:
    """Delete a managed device by ID."""
    ai_store = request.app.state.robot_ai_store
    deleted = ai_store.delete_managed_device(device_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Managed device not found.")
    return {"deleted": True}


# ---------------------------------------------------------------------------
# BBC micro:bit v2.21 Bridge & Pi Zero 2 W / Local Camera Bridges
# ---------------------------------------------------------------------------


@router.get("/devices/microbit/probe")
async def probe_microbit() -> Dict[str, Any]:
    """Probe local host USB CDC serial ports and DAPLink volumes for BBC micro:bit v2.21."""
    return await asyncio.to_thread(probe_microbit_usb)


@router.post("/devices/microbit/command")
async def run_microbit_command(body: MicrobitCommandRequest) -> Dict[str, Any]:
    """Send a MicroPython command to a USB-connected BBC micro:bit v2.21 (or return preview code)."""
    try:
        return await asyncio.to_thread(
            send_microbit_serial_command,
            body.port,
            body.action,
            body.payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/devices/pizero/gadget-script")
async def get_pizero_gadget_script(
    docker_host: str = Query(default="192.168.1.89:8000"),
    device_id: str = Query(default="pizero-sync-bridge"),
) -> Dict[str, Any]:
    """Generate a cloud-free Raspberry Pi Zero 2 W USB Mass Storage clip harvester setup script."""
    return generate_pi_zero_gadget_setup_script(docker_host=docker_host, device_id=device_id)


@router.post("/devices/cameras/ingest-media")
async def ingest_camera_media(request: Request) -> Dict[str, Any]:
    """Ingest a local camera image, .mp4 clip, base64 image, or LAN stream URL into Spatial Memory.

    Accepts both ``multipart/form-data`` (fields ``file``, ``camera_name``, ``space_id``, ``robot_id``)
    and ``application/json`` (``image_base64``, ``stream_url``, ``camera_name``, ``space_id``, ``robot_id``).
    """
    ai_vision_engine = request.app.state.ai_vision_engine
    ai_store = request.app.state.robot_ai_store
    rt = request.app.state.runtime
    repo = rt.repo

    content_type = str(request.headers.get("content-type") or "").lower()
    media_bytes: Optional[bytes] = None
    filename = "frame.jpg"
    image_base64: Optional[str] = None
    stream_url: Optional[str] = None
    camera_name = "Local Cam"
    space_id: Optional[str] = getattr(rt, "active_space_id", None)
    robot_id = "local-camera"
    max_frames = 3

    try:
        if "multipart/form-data" in content_type:
            form = await request.form()
            upload = form.get("file")
            if upload is not None and hasattr(upload, "read"):
                media_bytes = await upload.read()
                filename = str(getattr(upload, "filename", None) or "frame.jpg")
            if form.get("camera_name"):
                camera_name = str(form.get("camera_name"))
            if form.get("space_id"):
                space_id = str(form.get("space_id"))
            if form.get("robot_id"):
                robot_id = str(form.get("robot_id"))
            if form.get("image_base64"):
                image_base64 = str(form.get("image_base64"))
            if form.get("stream_url"):
                stream_url = str(form.get("stream_url"))
            if form.get("max_frames"):
                max_frames = int(str(form.get("max_frames")))
        else:
            body = await request.json()
            if not isinstance(body, dict):
                raise HTTPException(status_code=400, detail="JSON body must be an object.")
            camera_name = str(body.get("camera_name") or camera_name)
            if body.get("space_id") is not None:
                space_id = str(body.get("space_id")) if body.get("space_id") else None
            if body.get("robot_id"):
                robot_id = str(body.get("robot_id"))
            if body.get("image_base64"):
                image_base64 = str(body.get("image_base64"))
            if body.get("stream_url"):
                stream_url = str(body.get("stream_url"))
            if body.get("filename"):
                filename = str(body.get("filename"))
            if body.get("max_frames") is not None:
                max_frames = int(body.get("max_frames"))
    except HTTPException:
        raise
    except Exception as exc:
        sys.stderr.write(f"[routes_devices] Failed to parse ingest-media request: {exc}\n")
        raise HTTPException(status_code=400, detail=f"Invalid ingest payload: {exc}") from exc

    try:
        return await ingest_local_media_to_spatial_memory(
            ai_vision_engine=ai_vision_engine,
            ai_store=ai_store,
            repo=repo,
            camera_name=camera_name,
            space_id=space_id,
            robot_id=robot_id,
            media_bytes=media_bytes,
            filename=filename,
            image_base64=image_base64,
            stream_url=stream_url,
            max_frames=max_frames,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ConnectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Lab Hardware Inventory
# ---------------------------------------------------------------------------


@router.get("/inventory")
async def list_inventory(
    request: Request,
    status: Optional[str] = Query(default=None),
    category: Optional[str] = Query(default=None),
    query: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    """List lab hardware inventory items with optional status/category/search filters and summary counts."""
    ai_store = request.app.state.robot_ai_store
    items = ai_store.list_inventory_items(status=status, category=category, query=query)
    counts = ai_store.count_inventory_items()
    return {"items": items, "counts": counts}


@router.post("/inventory")
async def create_inventory_item(body: CreateInventoryItemRequest, request: Request) -> Dict[str, Any]:
    """Create a new lab hardware inventory item."""
    ai_store = request.app.state.robot_ai_store
    try:
        item = ai_store.create_inventory_item(body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "item": item}


@router.patch("/inventory/{item_id}")
async def update_inventory_item(
    item_id: str,
    body: UpdateInventoryItemRequest,
    request: Request,
) -> Dict[str, Any]:
    """Update mutable fields on a lab hardware inventory item."""
    ai_store = request.app.state.robot_ai_store
    updates = body.model_dump(exclude_unset=True)
    updated = ai_store.update_inventory_item(item_id, updates)
    if not updated:
        raise HTTPException(status_code=404, detail="Inventory item not found.")
    return {"ok": True, "item": updated}


@router.delete("/inventory/{item_id}")
async def delete_inventory_item(item_id: str, request: Request) -> Dict[str, Any]:
    """Delete a lab hardware inventory item by ID."""
    ai_store = request.app.state.robot_ai_store
    deleted = ai_store.delete_inventory_item(item_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Inventory item not found.")
    return {"deleted": True}


@router.post("/inventory/seed-lab")
async def seed_starter_lab_inventory(request: Request) -> Dict[str, Any]:
    """Idempotently seed the user's curated starter lab hardware inventory (skipping existing names)."""
    ai_store = request.app.state.robot_ai_store
    existing = ai_store.list_inventory_items()
    existing_names = {str(it.get("name") or "").strip().lower() for it in existing}
    seeded = 0
    for starter in build_starter_lab_inventory():
        key = str(starter.get("name") or "").strip().lower()
        if key and key not in existing_names:
            ai_store.create_inventory_item(starter)
            existing_names.add(key)
            seeded += 1
    items = ai_store.list_inventory_items()
    return {"seeded": seeded, "items": items}


@router.post("/inventory/sync-fleet")
async def sync_fleet_hardware_to_inventory(
    request: Request,
    probe_live: bool = Query(default=True),
) -> Dict[str, Any]:
    """Probe all registered fleet Pis/robots for live USB/serial peripherals and sync into Lab Architect."""
    from src.devices.fleet_hardware_sync import sync_fleet_to_architect

    robot_store = getattr(request.app.state, "robot_store", None)
    ai_store = request.app.state.robot_ai_store
    return await sync_fleet_to_architect(robot_store=robot_store, ai_store=ai_store, probe_live=probe_live)


# ---------------------------------------------------------------------------
# Human-AI Co-Design Lab Architect
# ---------------------------------------------------------------------------


@router.post("/architect/evaluate")
async def architect_evaluate(body: ArchitectEvaluateRequest, request: Request) -> Dict[str, Any]:
    """Evaluate a hardware/robotics project idea against owned lab inventory and persist the blueprint."""
    ai_store = request.app.state.robot_ai_store
    inventory = ai_store.list_inventory_items()
    profiles = list_device_profiles()
    api_key, base_url, model = _openrouter_settings(request, body.model)

    blueprint = await evaluate_design_idea(
        idea=body.idea,
        inventory_items=inventory,
        profiles=profiles,
        creativity_level=body.creativity_level,
        persona=body.persona,
        locked_part_ids=body.locked_part_ids,
        excluded_part_ids=body.excluded_part_ids,
        canvas_part_names=body.canvas_part_names,
        openrouter_api_key=api_key,
        base_url=base_url,
        model=model,
    )
    saved = ai_store.save_design_blueprint(blueprint)
    return {"ok": True, "blueprint": saved}


@router.post("/architect/ideate")
async def architect_ideate(body: ArchitectIdeateRequest, request: Request) -> Dict[str, Any]:
    """Generate tailored robotics & IoT project ideas calibrated to lab inventory and creativity tier."""
    ai_store = request.app.state.robot_ai_store
    inventory = ai_store.list_inventory_items()
    profiles = list_device_profiles()
    api_key, base_url, model = _openrouter_settings(request, body.model)

    ideas, model_used = await generate_inventory_ideas(
        inventory_items=inventory,
        profiles=profiles,
        creativity_level=body.creativity_level,
        focus_area=body.focus_area,
        count=body.count,
        locked_part_ids=body.locked_part_ids,
        excluded_part_ids=body.excluded_part_ids,
        openrouter_api_key=api_key,
        base_url=base_url,
        model=model,
    )
    return {"ok": True, "ideas": ideas, "model_used": model_used}


@router.post("/architect/blueprints/{blueprint_id}/refine")
async def architect_refine_blueprint(
    blueprint_id: str,
    body: ArchitectRefineRequest,
    request: Request,
) -> Dict[str, Any]:
    """Iteratively refine a saved Co-Design blueprint via walkthrough chat, point-and-ask, or part promotion."""
    ai_store = request.app.state.robot_ai_store
    existing = ai_store.get_design_blueprint(blueprint_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Design blueprint not found.")

    inventory = ai_store.list_inventory_items()
    profiles = list_device_profiles()
    api_key, base_url, model = _openrouter_settings(request, body.model)

    refined = await refine_blueprint(
        blueprint=existing,
        message=body.message,
        inventory_items=inventory,
        profiles=profiles,
        selected_node_id=body.selected_node_id,
        creativity_level=body.creativity_level,
        persona=body.persona,
        locked_part_ids=body.locked_part_ids,
        excluded_part_ids=body.excluded_part_ids,
        accept_missing_part=body.accept_missing_part,
        openrouter_api_key=api_key,
        base_url=base_url,
        model=model,
    )
    saved = ai_store.save_design_blueprint(refined)
    return {"ok": True, "blueprint": saved}


@router.get("/architect/blueprints")
async def list_architect_blueprints(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
) -> Dict[str, Any]:
    """List saved Co-Design Architect blueprints ordered newest updated first."""
    ai_store = request.app.state.robot_ai_store
    return {"blueprints": ai_store.list_design_blueprints(limit=limit)}


@router.delete("/architect/blueprints/{blueprint_id}")
async def delete_architect_blueprint(blueprint_id: str, request: Request) -> Dict[str, Any]:
    """Delete a saved Co-Design Architect blueprint by ID."""
    ai_store = request.app.state.robot_ai_store
    deleted = ai_store.delete_design_blueprint(blueprint_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Design blueprint not found.")
    return {"deleted": True}
