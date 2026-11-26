"""Admin Configuration (Fernet-encrypted PostgreSQL app_settings), diagnostics, and PostgreSQL File Storage routes."""

from __future__ import annotations

import asyncio
import io
import sys
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, File, Form, Header, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.api.state import TwinScanRuntimeState
from src.vision.openrouter_catalog import fetch_openrouter_model_catalog, test_openrouter_api_key
from src.vision.schemas import EquipmentVisionResult

router = APIRouter(tags=["admin-and-files"])

ALLOWED_MIME_PREFIXES = (
    "image/",
    "application/pdf",
    "application/json",
    "application/vnd.cyclonedx+json",
    "application/dxf",
    "model/gltf",
    "text/",
    "application/octet-stream",
)


class SettingsUpdateRequest(BaseModel):
    """Map of managed setting keys to updated string values."""

    settings: Dict[str, str]


class ConfigImportRequest(BaseModel):
    """Portable non-secret configuration JSON import payload."""

    settings: Dict[str, str]


class OpenRouterTestKeyRequest(BaseModel):
    """Optional draft OpenRouter API key and base URL to verify before saving."""

    api_key: Optional[str] = None
    base_url: Optional[str] = None


def _state(request: Request) -> TwinScanRuntimeState:
    return request.app.state.runtime


def _verify_admin_guard(request: Request, x_admin_token: Optional[str]) -> None:
    """Enforce optional X-Admin-Token header when TWINSCAN_ADMIN_TOKEN is configured."""
    expected = _state(request).settings.twinscan_admin_token.strip()
    if expected and (x_admin_token or "").strip() != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Admin-Token header.")


@router.get("/api/admin/settings")
async def get_admin_settings(request: Request) -> dict[str, Any]:
    """Return masked configuration settings, audit log, storage stats, and embedding drift info."""
    rt = _state(request)
    items = rt.repo.list_settings_masked(rt.default_settings_map())
    active_emb_model = rt.effective_config.get("openrouter_embedding_model", "")
    all_eq = rt.repo.list_equipment()
    drifted = sum(1 for e in all_eq if (e.get("embedding_model") or "") not in {active_emb_model, "fallback"})
    return {
        "settings": items,
        "admin_token_required": bool(rt.settings.twinscan_admin_token.strip()),
        "storage": rt.repo.storage_stats(),
        "embedding_drift": {"active_model": active_emb_model, "drifted_asset_count": drifted, "total_assets": len(all_eq)},
    }


@router.put("/api/admin/settings")
async def put_admin_settings(
    body: SettingsUpdateRequest,
    request: Request,
    x_admin_token: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    """Persist settings into PostgreSQL 18 (Fernet-encrypted secrets) and hot-reload runtime clients."""
    _verify_admin_guard(request, x_admin_token)
    rt = _state(request)
    source_ip = request.client.host if request.client else "local"
    changed = rt.repo.upsert_settings(body.settings, source_ip=source_ip)
    rt.apply_runtime_settings()
    return {
        "updated_count": len(changed),
        "audit_entries": changed,
        "openrouter_configured": rt.openrouter_configured,
        "settings": rt.repo.list_settings_masked(rt.default_settings_map()),
    }


@router.get("/api/admin/audit")
async def get_settings_audit(request: Request, limit: int = 30) -> dict[str, Any]:
    """Return immutable configuration change audit entries."""
    return {"entries": _state(request).repo.list_settings_audit(limit=limit)}


@router.get("/api/admin/usage")
async def get_vision_usage(request: Request, limit: int = 30) -> dict[str, Any]:
    """Return vision & research inference latency/confidence telemetry ledger."""
    entries = _state(request).repo.list_vision_usage(limit=limit)
    return {"entries": entries}


@router.post("/api/admin/test-connections")
async def test_all_connections(request: Request) -> dict[str, Any]:
    """Run live diagnostics across PostgreSQL 18 + pgvector, Neo4j 5, and OpenRouter API."""
    rt = _state(request)
    pg_health = rt.repo.check_health()
    neo4j_health = rt.neo4j.check_health()

    or_status: dict[str, Any] = {"status": "unconfigured"}
    api_key = rt.effective_config.get("openrouter_api_key", "").strip()
    base_url = rt.effective_config.get("openrouter_base_url", "https://openrouter.ai/api/v1").rstrip("/")
    if api_key and api_key != "your_openrouter_api_key_here":
        last_err = ""
        for attempt in range(1, 4):
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        f"{base_url}/auth/key",
                        headers={"Authorization": f"Bearer {api_key}"},
                    )
                    resp.raise_for_status()
                    data = resp.json().get("data") or {}
                    or_status = {
                        "status": "connected",
                        "label": data.get("label") or "OpenRouter Key Active",
                        "usage": data.get("usage"),
                        "limit": data.get("limit"),
                    }
                    break
            except Exception as exc:
                last_err = str(exc)
                sys.stderr.write(f"[admin.openrouter_check] Attempt {attempt}/3 failed: {exc}\n")
                if attempt < 3:
                    await asyncio.sleep(1.0)
        else:
            or_status = {"status": "error", "error": last_err}

    return {"postgres": pg_health, "neo4j": neo4j_health, "openrouter": or_status}


@router.post("/api/admin/openrouter/test-key")
async def test_openrouter_key_endpoint(
    request: Request,
    body: Optional[OpenRouterTestKeyRequest] = None,
) -> dict[str, Any]:
    """Test a newly pasted draft OpenRouter API key or the saved PostgreSQL key without mutating DB."""
    rt = _state(request)
    req = body or OpenRouterTestKeyRequest()
    draft_key = (req.api_key or "").strip()
    if draft_key and "••••" not in draft_key:
        active_key = draft_key
        key_source = "draft"
    else:
        active_key = rt.effective_config.get("openrouter_api_key", "").strip()
        key_source = "saved"
    base_url = (req.base_url or rt.effective_config.get("openrouter_base_url") or "https://openrouter.ai/api/v1").strip()
    return await test_openrouter_api_key(
        api_key=active_key,
        base_url=base_url,
        key_source=key_source,
    )


@router.get("/api/admin/openrouter-models")
async def refresh_openrouter_models(
    request: Request,
    refresh: bool = Query(default=False),
) -> dict[str, Any]:
    """Fetch the full normalized OpenRouter chat & embedding model catalog with costs and categories."""
    rt = _state(request)
    base_url = rt.effective_config.get("openrouter_base_url", "https://openrouter.ai/api/v1").rstrip("/")
    api_key = rt.effective_config.get("openrouter_api_key", "").strip()
    return await fetch_openrouter_model_catalog(
        api_key=api_key,
        base_url=base_url,
        force_refresh=refresh,
    )


@router.post("/api/admin/reconcile-neo4j")
async def reconcile_neo4j(
    request: Request,
    x_admin_token: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    """Rebuild Neo4j Knowledge Graph parity from PostgreSQL 18 spaces and equipment."""
    _verify_admin_guard(request, x_admin_token)
    rt = _state(request)
    spaces = rt.repo.list_spaces()
    eq_by_space = {s["id"]: rt.repo.list_equipment(s["id"]) for s in spaces}
    return rt.neo4j.reconcile_all(spaces, eq_by_space, max_near_m=rt.near_proximity_m)


@router.post("/api/admin/reindex-embeddings")
async def reindex_pgvector_embeddings(
    request: Request,
    x_admin_token: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    """Re-compute halfvec(1536) embeddings for all equipment assets using the active embedding model."""
    _verify_admin_guard(request, x_admin_token)
    rt = _state(request)
    active_model = rt.effective_config.get("openrouter_embedding_model", "fallback")
    assets = rt.repo.list_equipment()
    reindexed = 0
    for eq in assets:
        summary = EquipmentVisionResult(
            name=eq["name"],
            equipment_type=eq.get("equipment_type", "Industrial Equipment"),
            dexpi_class=eq.get("dexpi_class", "Equipment"),
            manufacturer=eq.get("manufacturer", "Unknown"),
            model_number=eq.get("model_number", "Unknown"),
            part_number=eq.get("part_number"),
            serial_number=eq.get("serial_number"),
            inferred_cpe_23=eq.get("inferred_cpe_23"),
            voltage_rating=eq.get("voltage_rating"),
            asset_tags=eq.get("asset_tags") or [],
            mac_addresses=eq.get("mac_addresses") or [],
        )
        enr = eq.get("enrichment") or {}
        text = summary.to_embedding_text()
        if enr.get("datasheet_summary"):
            text += f" | Specs: {enr['datasheet_summary']}"
        vec = await rt.vision.generate_embedding(text)
        if rt.repo.update_equipment_embedding(eq["id"], vec, active_model if rt.openrouter_configured else "fallback"):
            reindexed += 1
    return {"reindexed_count": reindexed, "embedding_model": active_model}


@router.get("/api/admin/config-export")
async def export_non_secret_config(request: Request) -> dict[str, Any]:
    """Export portable non-secret configuration JSON for sovereign backup/restore."""
    rt = _state(request)
    items = rt.repo.list_settings_masked(rt.default_settings_map())
    safe = {item["key"]: item["value"] for item in items if not item["is_secret"]}
    return {"schema": "eigenia.twinscan.config.v1", "settings": safe}


@router.post("/api/admin/config-import")
async def import_non_secret_config(
    body: ConfigImportRequest,
    request: Request,
    x_admin_token: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    """Import portable non-secret configuration JSON into PostgreSQL 18."""
    _verify_admin_guard(request, x_admin_token)
    rt = _state(request)
    source_ip = request.client.host if request.client else "local"
    changed = rt.repo.upsert_settings(body.settings, source_ip=source_ip)
    rt.apply_runtime_settings()
    return {"imported_count": len(changed)}


@router.post("/api/admin/storage-scrub")
async def scrub_postgres_storage(
    request: Request,
    x_admin_token: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    """Verify SHA-256 integrity of every PostgreSQL blob and garbage-collect unreferenced orphans."""
    _verify_admin_guard(request, x_admin_token)
    rt = _state(request)
    result = rt.repo.verify_and_scrub_storage()
    return {**result, "stats": rt.repo.storage_stats()}


# --- PostgreSQL Content-Addressed File Storage Endpoints ---


@router.get("/api/files")
async def list_stored_files(
    request: Request,
    category: Optional[str] = None,
    space_id: Optional[str] = None,
    equipment_id: Optional[str] = None,
) -> dict[str, Any]:
    """List files stored inside PostgreSQL 18 ``stored_files``."""
    rt = _state(request)
    files = rt.repo.list_files(category=category, space_id=space_id, equipment_id=equipment_id)
    return {"files": files, "stats": rt.repo.storage_stats()}


@router.post("/api/files")
async def upload_file_to_postgres(
    request: Request,
    file: UploadFile = File(...),
    category: str = Form(default="manual_upload"),
    space_id: Optional[str] = Form(default=None),
    equipment_id: Optional[str] = Form(default=None),
) -> dict[str, Any]:
    """Upload and SHA-256 deduplicate any allowed file directly into PostgreSQL 18 ``file_blobs``."""
    rt = _state(request)
    ctype = file.content_type or "application/octet-stream"
    if not any(ctype.startswith(prefix) for prefix in ALLOWED_MIME_PREFIXES):
        raise HTTPException(status_code=415, detail=f"Unsupported file MIME type: {ctype}")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(data) > rt.max_upload_bytes:
        raise HTTPException(status_code=413, detail=f"File exceeds {rt.max_upload_bytes // (1024 * 1024)} MB limit.")

    record = rt.repo.store_file(
        filename=file.filename or "upload.bin",
        content_type=ctype,
        data=data,
        category=category,
        space_id=space_id or rt.active_space_id or None,
        equipment_id=equipment_id,
    )
    return {"file": record, "stats": rt.repo.storage_stats()}


@router.get("/api/files/{file_id}")
async def download_file_from_postgres(
    file_id: str,
    request: Request,
    if_none_match: Optional[str] = Header(default=None),
) -> Response:
    """Stream binary file bytes directly from PostgreSQL 18 with HTTP ETag caching."""
    rt = _state(request)
    meta = rt.repo.get_file_meta(file_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Stored file not found.")
    etag = f'"{meta["sha256"]}"'
    if if_none_match and if_none_match.strip() == etag:
        return Response(status_code=304, headers={"ETag": etag})

    found = rt.repo.get_file_with_bytes(file_id)
    if not found:
        raise HTTPException(status_code=404, detail="Stored file blob missing.")
    _, raw_bytes = found
    return StreamingResponse(
        io.BytesIO(raw_bytes),
        media_type=meta["content_type"],
        headers={
            "ETag": etag,
            "Cache-Control": "public, max-age=3600",
            "Content-Disposition": f'inline; filename="{meta["filename"]}"',
            "Content-Length": str(len(raw_bytes)),
        },
    )


@router.delete("/api/files/{file_id}")
async def delete_stored_file(
    file_id: str,
    request: Request,
    x_admin_token: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    """Delete a file record from PostgreSQL 18 (and prune blob if unreferenced)."""
    _verify_admin_guard(request, x_admin_token)
    rt = _state(request)
    if not rt.repo.delete_file(file_id):
        raise HTTPException(status_code=404, detail="Stored file not found.")
    return {"deleted": True, "file_id": file_id, "stats": rt.repo.storage_stats()}
