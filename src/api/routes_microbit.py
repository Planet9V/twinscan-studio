"""FastAPI router for the dedicated BBC micro:bit v2.2 3D Project Lab (/microbit)."""

from __future__ import annotations

import asyncio
import sys
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.microbit.bridge import (
    deploy_micropython_code,
    probe_microbit_hardware,
    read_microbit_live_sensors,
    resolve_microbit_host,
)
from src.microbit.catalog import (
    ACCESSORY_BY_ID,
    BOARD_PROFILES,
    MICROBIT_ACCESSORIES,
    MICROBIT_V2_PINS,
    STARTER_TEMPLATES,
    generate_prototype_code,
)
from src.microbit.project_store import MicrobitProjectStore

router = APIRouter(prefix="/api/microbit", tags=["microbit"])


def _get_store(request: Request) -> MicrobitProjectStore:
    store = getattr(request.app.state, "microbit_store", None)
    if store is None:
        store = MicrobitProjectStore()
        runtime = getattr(request.app.state, "runtime", None)
        repo = getattr(request.app.state, "twin_repo", None) or getattr(runtime, "repo", None)
        if repo is not None:
            store.attach_repository(repo)
        request.app.state.microbit_store = store
    return store


class CreateMicrobitProjectRequest(BaseModel):
    """Create a new multi-board hardware prototype project."""

    name: str = Field(..., min_length=1, max_length=96)
    description: str = Field(default="", max_length=240)
    board_id: str = Field(default="microbit_v2", max_length=32)


class AttachmentItem(BaseModel):
    """Accessory attached to specific board pins."""

    id: Optional[str] = Field(default=None, max_length=32)
    accessory_id: str = Field(..., max_length=48)
    label: Optional[str] = Field(default=None, max_length=80)
    pin: str = Field(default="P0", max_length=16)
    secondary_pin: Optional[str] = Field(default=None, max_length=16)


class UpdateMicrobitProjectRequest(BaseModel):
    """Update a hardware project's board, metadata, attached accessories, sim_rules, or code."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=96)
    board_id: Optional[str] = Field(default=None, max_length=32)
    description: Optional[str] = Field(default=None, max_length=240)
    attachments: Optional[List[AttachmentItem]] = Field(default=None)
    sim_rules: Optional[List[Dict[str, Any]]] = Field(default=None)
    code: Optional[str] = Field(default=None, max_length=20000)


class CopilotChatRequest(BaseModel):
    """Natural-language instruction for the micro:bit AI Hardware & Code Co-Pilot."""

    message: str = Field(..., min_length=1, max_length=1500)


class DeployCodeRequest(BaseModel):
    """Deploy MicroPython code to the live micro:bit v2.2."""

    code: str = Field(..., min_length=1, max_length=20000)
    host_robot_id: Optional[str] = Field(default=None, max_length=64)


@router.get("/catalog")
async def get_microbit_catalog() -> Dict[str, Any]:
    """Return multi-board pinout schematics, Hiwonder + prototyping library, and templates."""
    return {
        "ok": True,
        "board": BOARD_PROFILES["microbit_v2"],
        "boards": BOARD_PROFILES,
        "pins": MICROBIT_V2_PINS,
        "accessories": MICROBIT_ACCESSORIES,
        "templates": STARTER_TEMPLATES,
    }


@router.get("/projects")
async def list_microbit_projects(request: Request) -> Dict[str, Any]:
    """List all saved hardware prototype projects."""
    projects = _get_store(request).list_projects()
    return {"ok": True, "projects": projects, "count": len(projects)}


@router.post("/projects")
async def create_microbit_project(request: Request, payload: CreateMicrobitProjectRequest) -> Dict[str, Any]:
    """Create a new hardware prototype project for micro:bit v2.2, Raspberry Pi 5, or PuppyPi Pro."""
    proj = _get_store(request).create_project(
        name=payload.name,
        description=payload.description,
        board_id=payload.board_id,
    )
    return {"ok": True, "project": proj}


@router.patch("/projects/{project_id}")
async def update_microbit_project(
    request: Request,
    project_id: str,
    payload: UpdateMicrobitProjectRequest,
) -> Dict[str, Any]:
    """Update a hardware project's target board, attached accessories, pins, or code."""
    store = _get_store(request)
    proj = store.get_project(project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail="micro:bit project not found.")
    if payload.name is not None:
        proj["name"] = payload.name.strip()
    if payload.board_id is not None and payload.board_id in BOARD_PROFILES:
        proj["board_id"] = payload.board_id
    if payload.description is not None:
        proj["description"] = payload.description.strip()
    if payload.attachments is not None:
        cleaned = []
        for item in payload.attachments:
            spec = ACCESSORY_BY_ID.get(item.accessory_id)
            if not spec:
                continue
            cleaned.append(
                {
                    "id": item.id or f"att_{uuid.uuid4().hex[:6]}",
                    "accessory_id": item.accessory_id,
                    "label": (item.label or spec["name"]).strip(),
                    "pin": item.pin.upper(),
                    "secondary_pin": item.secondary_pin.upper() if item.secondary_pin else spec.get("secondary_pin"),
                }
            )
        proj["attachments"] = cleaned
    if payload.code is not None:
        proj["code"] = payload.code
    if payload.sim_rules is not None:
        proj["sim_rules"] = payload.sim_rules
    saved = store.save_project(proj)
    return {"ok": True, "project": saved}


@router.post("/projects/{project_id}/chat")
async def chat_with_microbit_copilot(
    request: Request,
    project_id: str,
    payload: CopilotChatRequest,
) -> Dict[str, Any]:
    """Chat with the AI Hardware Co-Pilot to wire 3D parts, update simulator rules, and write MicroPython."""
    from src.microbit.ai_copilot import run_microbit_copilot_turn

    store = _get_store(request)
    proj = store.get_project(project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail="micro:bit project not found.")

    runtime = getattr(request.app.state, "runtime", None)
    repo = getattr(request.app.state, "twin_repo", None) or getattr(runtime, "repo", None)
    raw_settings = (repo.get_settings_raw() if (repo is not None and hasattr(repo, "get_settings_raw")) else {}) or {}
    or_key = str(raw_settings.get("openrouter_api_key") or "").strip() or None
    or_model = str(raw_settings.get("openrouter_model") or "google/gemini-2.5-flash").strip()

    res = await run_microbit_copilot_turn(
        project=proj,
        user_message=payload.message,
        openrouter_api_key=or_key,
        openrouter_model=or_model,
    )
    proj["attachments"] = res["attachments"]
    proj["sim_rules"] = res["sim_rules"]
    proj["code"] = res["code"]
    history = list(proj.get("chat_history") or [])
    history.append({"role": "user", "text": payload.message})
    history.append({"role": "assistant", "text": res["assistant_reply"]})
    proj["chat_history"] = history[-30:]

    saved = store.save_project(proj)
    return {
        "ok": True,
        "assistant_reply": res["assistant_reply"],
        "provider": res.get("provider"),
        "project": saved,
    }


@router.delete("/projects/{project_id}")
async def delete_microbit_project(request: Request, project_id: str) -> Dict[str, Any]:
    """Delete a micro:bit prototype project."""
    removed = _get_store(request).delete_project(project_id)
    return {"ok": True, "removed": removed}


@router.post("/projects/{project_id}/generate-code")
async def generate_project_code(request: Request, project_id: str) -> Dict[str, Any]:
    """Auto-generate MicroPython code for all accessories attached to this project."""
    store = _get_store(request)
    proj = store.get_project(project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail="micro:bit project not found.")
    code = generate_prototype_code(
        proj.get("attachments") or [],
        project_name=proj.get("name") or "Prototype",
        board_id=str(proj.get("board_id") or "microbit_v2"),
    )
    proj["code"] = code
    saved = store.save_project(proj)
    return {"ok": True, "code": code, "project": saved}


@router.get("/hardware/status")
async def get_microbit_hardware_status(request: Request) -> Dict[str, Any]:
    """Probe the connected Raspberry Pi 5 for the live BBC micro:bit v2.2."""
    robot_store = getattr(request.app.state, "robot_store", None)
    try:
        ip, user, pw, host_name = resolve_microbit_host(robot_store)
        res = await asyncio.to_thread(probe_microbit_hardware, ip, user, pw, host_name)
        return {"ok": True, **res}
    except Exception as exc:
        sys.stderr.write(f"[api.microbit.status] Warning: {exc}\n")
        return {"ok": False, "connected": False, "error": str(exc)}


@router.post("/hardware/deploy")
async def deploy_to_microbit(request: Request, payload: DeployCodeRequest) -> Dict[str, Any]:
    """Upload and run MicroPython code live on the connected micro:bit v2.2."""
    robot_store = getattr(request.app.state, "robot_store", None)
    try:
        ip, user, pw, host_name = resolve_microbit_host(robot_store, payload.host_robot_id)
        res = await asyncio.to_thread(deploy_micropython_code, ip, user, pw, payload.code)
        return {"ok": bool(res.get("ok")), "host_name": host_name, **res}
    except Exception as exc:
        sys.stderr.write(f"[api.microbit.deploy] Error: {exc}\n")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/hardware/sensors")
async def read_microbit_sensors(request: Request) -> Dict[str, Any]:
    """Read live accelerometer, temperature, light, sound, and button state from micro:bit v2.2."""
    robot_store = getattr(request.app.state, "robot_store", None)
    try:
        ip, user, pw, _ = resolve_microbit_host(robot_store)
        return await asyncio.to_thread(read_microbit_live_sensors, ip, user, pw, False)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/hardware/self-test")
async def run_microbit_self_test(request: Request) -> Dict[str, Any]:
    """Trigger a live LED + chime hardware self-test and return sensor telemetry."""
    robot_store = getattr(request.app.state, "robot_store", None)
    try:
        ip, user, pw, _ = resolve_microbit_host(robot_store)
        return await asyncio.to_thread(read_microbit_live_sensors, ip, user, pw, True)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
