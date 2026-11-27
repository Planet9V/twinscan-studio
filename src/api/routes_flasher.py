"""FastAPI router for the Universal Multi-Platform Hardware Flasher (/api/flasher/*)."""

from __future__ import annotations

from datetime import datetime, timezone
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from src.flasher.board_catalog import PLATFORM_BY_ID, SUPPORTED_PLATFORMS, fetch_rpi_os_catalog
from src.flasher.provisioner import build_pi_headless_bundle, validate_removable_target

router = APIRouter(prefix="/api/flasher", tags=["flasher"])


class FlasherState:
    """Thread-safe in-memory coordinator for host removable devices & flash jobs."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._host_info: Dict[str, Any] = {}
        self._devices: List[Dict[str, Any]] = []
        self._last_report_mono: float = 0.0
        self._jobs: Dict[str, Dict[str, Any]] = {}

    def report_host_devices(self, host_os: str, tools: Dict[str, bool], devices: List[Dict[str, Any]]) -> Dict[str, Any]:
        with self._lock:
            self._host_info = {"os": host_os, "tools": dict(tools)}
            # Strictly filter out any device marked internal
            self._devices = [d for d in devices if d.get("is_internal") is not True]
            self._last_report_mono = time.monotonic()
            pending = [j for j in self._jobs.values() if j["status"] == "queued"]
            return {"ok": True, "accepted_devices": len(self._devices), "pending_jobs": pending}

    def list_devices(self) -> Dict[str, Any]:
        with self._lock:
            age = round(time.monotonic() - self._last_report_mono, 1) if self._last_report_mono > 0 else None
            online = bool(age is not None and age <= 15.0)
            return {
                "host_bridge_online": online,
                "age_sec": age,
                "host": dict(self._host_info) if online else None,
                "devices": list(self._devices) if online else [],
            }

    def create_job(self, job: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            self._jobs[job["job_id"]] = job
            return dict(job)

    def update_job(self, job_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        with self._lock:
            if job_id not in self._jobs:
                return None
            self._jobs[job_id].update(updates)
            self._jobs[job_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
            return dict(self._jobs[job_id])

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            j = self._jobs.get(job_id)
            return dict(j) if j else None

    def list_jobs(self) -> List[Dict[str, Any]]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: j["created_at"], reverse=True)[:20]


def _get_flasher_state(request: Request) -> FlasherState:
    st = getattr(request.app.state, "flasher_state", None)
    if st is None:
        st = FlasherState()
        request.app.state.flasher_state = st
    return st


class HostReportPayload(BaseModel):
    host_os: str = Field(default="unknown", max_length=64)
    tools: Dict[str, bool] = Field(default_factory=dict)
    devices: List[Dict[str, Any]] = Field(default_factory=list)


class ProvisionPreviewPayload(BaseModel):
    hostname: str = Field(default="eigenia-pi5", max_length=32)
    username: str = Field(default="pi", max_length=32)
    ssh_pubkey: Optional[str] = Field(default=None, max_length=1024)
    wifi_ssid: Optional[str] = Field(default=None, max_length=64)
    wifi_password: Optional[str] = Field(default=None, max_length=128)
    country_code: str = Field(default="US", max_length=4)
    twinscan_url: Optional[str] = Field(default=None, max_length=128)
    role: str = Field(default="minimal_ssh", max_length=32)


class CreateFlashJobPayload(BaseModel):
    board_id: str = Field(..., max_length=32)
    image_url: str = Field(..., max_length=512)
    image_name: str = Field(default="OS Image", max_length=128)
    device_id: str = Field(..., max_length=64)
    confirmation_token: str = Field(..., max_length=64)
    provision: Optional[ProvisionPreviewPayload] = None


class JobProgressPayload(BaseModel):
    status: str = Field(..., pattern="^(queued|downloading|flashing|verifying|complete|error)$")
    progress_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    message: str = Field(default="", max_length=512)


@router.get("/platforms")
async def list_supported_platforms() -> Dict[str, Any]:
    """Return all supported SBC & microcontroller board profiles and storage guidance."""
    return {"platforms": SUPPORTED_PLATFORMS}


@router.get("/os-catalog")
async def get_board_os_catalog(board: str = Query(default="pi5", max_length=32)) -> Dict[str, Any]:
    """Return official Raspberry Pi OS / Ubuntu images filtered for ``board``."""
    return await fetch_rpi_os_catalog(board_id=board)


@router.get("/devices")
async def list_removable_devices(request: Request) -> Dict[str, Any]:
    """Return verified removable SD cards, UF2/HEX drives, and USB serial boards from the host bridge."""
    return _get_flasher_state(request).list_devices()


@router.post("/host/report")
async def report_host_flash_devices(request: Request, payload: HostReportPayload) -> Dict[str, Any]:
    """Receive removable device inventory from ``src.bridge.host_flash_bridge`` and return queued jobs."""
    return _get_flasher_state(request).report_host_devices(
        host_os=payload.host_os,
        tools=payload.tools,
        devices=payload.devices,
    )


@router.post("/provision-preview")
async def preview_headless_provision(payload: ProvisionPreviewPayload) -> Dict[str, Any]:
    """Preview the validated headless Raspberry Pi first-boot script (Wi-Fi password redacted)."""
    try:
        return build_pi_headless_bundle(
            hostname=payload.hostname,
            username=payload.username,
            ssh_pubkey=payload.ssh_pubkey,
            wifi_ssid=payload.wifi_ssid,
            wifi_password=payload.wifi_password,
            country_code=payload.country_code,
            twinscan_url=payload.twinscan_url,
            role=payload.role,
            redact_secrets=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/jobs")
async def create_flash_job(request: Request, payload: CreateFlashJobPayload) -> Dict[str, Any]:
    """Validate removable target with strict Poka-Yoke safety and queue a flash job."""
    if payload.board_id not in PLATFORM_BY_ID:
        raise HTTPException(status_code=400, detail=f"Unsupported board_id {payload.board_id!r}.")

    st = _get_flasher_state(request)
    inv = st.list_devices()
    target = next((d for d in inv["devices"] if str(d.get("device_id")) == payload.device_id), None)
    if target is None:
        raise HTTPException(
            status_code=400,
            detail=f"Removable device '{payload.device_id}' not found. Ensure the host flash bridge is running and media is inserted.",
        )

    try:
        safe_target = validate_removable_target(target, payload.confirmation_token)
        prov_bundle = None
        if payload.provision is not None:
            prov_bundle = build_pi_headless_bundle(
                hostname=payload.provision.hostname,
                username=payload.provision.username,
                ssh_pubkey=payload.provision.ssh_pubkey,
                wifi_ssid=payload.provision.wifi_ssid,
                wifi_password=payload.provision.wifi_password,
                country_code=payload.provision.country_code,
                twinscan_url=payload.provision.twinscan_url,
                role=payload.provision.role,
                redact_secrets=False,
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    now_iso = datetime.now(timezone.utc).isoformat()
    job_id = str(uuid.uuid4())
    job = {
        "job_id": job_id,
        "board_id": payload.board_id,
        "image_name": payload.image_name,
        "image_url": payload.image_url,
        "target": safe_target,
        "provision": {"hostname": prov_bundle["hostname"], "role": prov_bundle["role"]} if prov_bundle else None,
        "firstrun_sh": prov_bundle["firstrun_sh"] if prov_bundle else None,
        "status": "queued",
        "progress_pct": 0.0,
        "message": "Queued for host flash bridge execution.",
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    return st.create_job(job)


@router.get("/jobs")
async def list_flash_jobs(request: Request) -> Dict[str, Any]:
    """List recent device flash jobs."""
    return {"jobs": _get_flasher_state(request).list_jobs()}


@router.get("/jobs/{job_id}")
async def get_flash_job(request: Request, job_id: str) -> Dict[str, Any]:
    """Get live progress for a specific flash job."""
    job = _get_flasher_state(request).get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Flash job {job_id} not found.")
    return job


@router.post("/jobs/{job_id}/progress")
async def update_flash_job_progress(request: Request, job_id: str, payload: JobProgressPayload) -> Dict[str, Any]:
    """Update flash job status & percentage from the host flash bridge."""
    updated = _get_flasher_state(request).update_job(
        job_id,
        {"status": payload.status, "progress_pct": payload.progress_pct, "message": payload.message},
    )
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Flash job {job_id} not found.")
    return updated
