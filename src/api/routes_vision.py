"""OpenRouter Vision nameplate analysis (storing photos in PostgreSQL) and LiDAR raycast auto-placement."""

from __future__ import annotations

import time
from typing import Any, Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from src.api.state import TwinScanRuntimeState
from src.lidar.spatial_3d import raycast_camera_to_lidar
from src.vision.openrouter_catalog import build_curated_fallback_catalog, get_cached_catalog_models
from src.vision.preprocessor import preprocess_industrial_image

router = APIRouter(prefix="/api/vision", tags=["vision"])


def _state(request: Request) -> TwinScanRuntimeState:
    return request.app.state.runtime


@router.get("/models")
async def list_vision_models(request: Request) -> dict[str, Any]:
    """List rich OpenRouter models (live cache or curated fallback) and active model configuration."""
    rt = _state(request)
    models = get_cached_catalog_models() or build_curated_fallback_catalog()
    return {
        "openrouter_configured": rt.openrouter_configured,
        "default_model": rt.effective_config.get("openrouter_default_vision_model", rt.settings.openrouter_default_vision_model),
        "secondary_model": rt.effective_config.get("openrouter_secondary_vision_model", rt.settings.openrouter_secondary_vision_model),
        "research_model": rt.effective_config.get("openrouter_research_model", rt.settings.openrouter_research_model),
        "embedding_model": rt.effective_config.get("openrouter_embedding_model", rt.settings.openrouter_embedding_model),
        "models": models,
    }


@router.post("/analyze")
async def analyze_equipment_photo(
    request: Request,
    file: UploadFile = File(...),
    model: Optional[str] = Form(default=None),
    consensus: bool = Form(default=False),
    context_hint: str = Form(default=""),
    camera_fov_deg: Optional[float] = Form(default=None),
    camera_yaw_deg: float = Form(default=0.0),
) -> dict[str, Any]:
    """Run Stage-1 CLAHE/zxing-cpp + Stage-2 OpenRouter VLM, store photos in Postgres, and raycast pose."""
    rt = _state(request)
    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Uploaded image file is empty.")
    if len(image_bytes) > rt.max_upload_bytes:
        raise HTTPException(status_code=413, detail="Uploaded image exceeds maximum size limit.")

    fname = file.filename or "capture.jpg"
    ctype = file.content_type or "image/jpeg"

    # Store original evidence photo directly in PostgreSQL content-addressed file storage.
    stored_orig = rt.repo.store_file(
        filename=fname,
        content_type=ctype,
        data=image_bytes,
        category="equipment_photo",
        space_id=rt.active_space_id or None,
        metadata={"variant": "original"},
    )

    # Also store CLAHE + unsharp enhanced inspection image in PostgreSQL when valid.
    enhanced_file_id: Optional[str] = None
    try:
        enhanced_bytes, _ = preprocess_industrial_image(image_bytes)
        stored_enh = rt.repo.store_file(
            filename=f"enhanced-{fname}",
            content_type="image/jpeg",
            data=enhanced_bytes,
            category="equipment_photo_enhanced",
            space_id=rt.active_space_id or None,
            metadata={"variant": "clahe_unsharp", "parent_file_id": stored_orig["id"]},
        )
        enhanced_file_id = stored_enh["id"]
    except Exception:
        pass

    t0 = time.perf_counter()
    result = await rt.vision.analyze_equipment_image(
        image_bytes=image_bytes,
        model=model,
        consensus=consensus,
        context_hint=context_hint,
    )
    latency_ms = int((time.perf_counter() - t0) * 1000)

    rt.repo.log_vision_usage(
        {
            "operation": "vision_consensus" if consensus else "vision_extract",
            "model": result.model_used,
            "latency_ms": latency_ms,
            "confidence": result.confidence,
            "consensus_verified": result.consensus_verified,
            "status": "ok",
        }
    )

    fov = camera_fov_deg if camera_fov_deg is not None else rt.default_camera_fov_deg
    suggested_pose = raycast_camera_to_lidar(
        bbox_norm=result.primary_bbox_norm,
        lidar_points=rt.latest_points,
        camera_fov_deg=fov,
        camera_yaw_deg=camera_yaw_deg,
    )

    return {
        "extraction": result.model_dump(),
        "image_file_id": stored_orig["id"],
        "enhanced_file_id": enhanced_file_id,
        "image_url": stored_orig["url"],
        "enhanced_url": f"/api/files/{enhanced_file_id}" if enhanced_file_id else None,
        "suggested_pose": suggested_pose,
        "latency_ms": latency_ms,
    }
