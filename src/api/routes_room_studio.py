"""FastAPI router for the standalone High-Fidelity Room Twin Studio (/room-studio)."""

from __future__ import annotations

import asyncio
import sys
import time
import uuid
from typing import Any, Dict, List, Optional

import cv2
import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from src.room_studio.models import (
    DEFAULT_SURFACE_CAMERA_POSES,
    RoomStudioStore,
    VALID_SUPPORT_TYPES,
    VALID_SURFACES,
)
from src.room_studio.object_to_glb import (
    ALLOWED_3D_ENGINES,
    crop_object_from_photo,
    generate_fal_3d_glb,
    generate_local_depth_glb,
    stitch_surface_photos,
)
from src.room_studio.vision_scene_graph import (
    compute_next_best_view,
    compute_physics_placement,
    parse_room_photo_objects,
)

router = APIRouter(prefix="/api/room-studio", tags=["room-studio"])


def _get_store(request: Request) -> RoomStudioStore:
    store = getattr(request.app.state, "room_studio_store", None)
    if store is None:
        store = RoomStudioStore()
        runtime = getattr(request.app.state, "runtime", None)
        repo = getattr(request.app.state, "twin_repo", None) or getattr(runtime, "repo", None)
        if repo is not None:
            store.attach_repository(repo)
        request.app.state.room_studio_store = store
    return store


def _get_repo(request: Request) -> Any:
    runtime = getattr(request.app.state, "runtime", None)
    return getattr(request.app.state, "twin_repo", None) or getattr(runtime, "repo", None)


class CreateProjectRequest(BaseModel):
    """Create a new standalone Room Twin Studio project."""

    name: str = Field(default="My Studio Room", min_length=1, max_length=96)
    width_m: float = Field(default=4.6, ge=1.5, le=30.0)
    length_m: float = Field(default=4.2, ge=1.5, le=30.0)
    height_m: float = Field(default=2.6, ge=1.8, le=10.0)


class UpdateProjectRequest(BaseModel):
    """Update room shell dimensions or name."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=96)
    width_m: Optional[float] = Field(default=None, ge=1.5, le=30.0)
    length_m: Optional[float] = Field(default=None, ge=1.5, le=30.0)
    height_m: Optional[float] = Field(default=None, ge=1.8, le=10.0)


class CreateObjectRequest(BaseModel):
    """Manually tag/box an object on a room photo (e.g., guitar on wall)."""

    source_photo_id: Optional[str] = Field(default=None, max_length=64)
    name: str = Field(..., min_length=1, max_length=80)
    category: str = Field(default="prop", max_length=32)
    support_type: str = Field(default="WALL_MOUNTED", max_length=24)
    support_surface: str = Field(default="north_wall", max_length=32)
    bbox_norm: List[float] = Field(default_factory=lambda: [0.25, 0.25, 0.75, 0.75])
    dimensions_m: List[float] = Field(default_factory=lambda: [0.4, 0.9, 0.15])
    color_hex: str = Field(default="#38bdf8", max_length=16)
    notes: str = Field(default="", max_length=200)


class UpdateObjectRequest(BaseModel):
    """Update an object's name, 6-DoF Three.js pose, dimensions, or support surface."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    support_type: Optional[str] = Field(default=None, max_length=24)
    support_surface: Optional[str] = Field(default=None, max_length=32)
    dimensions_m: Optional[List[float]] = Field(default=None)
    pose: Optional[Dict[str, float]] = Field(default=None)
    color_hex: Optional[str] = Field(default=None, max_length=16)
    notes: Optional[str] = Field(default=None, max_length=200)


class Generate3DRequest(BaseModel):
    """Request conversion of a tagged photo object into a Three.js PBR ``.glb`` mesh."""

    engine: str = Field(default="local_depth3d", max_length=64)


@router.get("/projects")
async def list_room_projects(request: Request) -> Dict[str, Any]:
    """List all standalone Room Twin Studio projects (auto-creates one if empty)."""
    store = _get_store(request)
    projects = store.list_projects()
    if not projects:
        first = store.create_project(name="Main Studio Room")
        projects = [first]
    return {"ok": True, "projects": projects, "count": len(projects)}


@router.post("/projects")
async def create_room_project(request: Request, payload: CreateProjectRequest) -> Dict[str, Any]:
    """Create a new Room Twin Studio project."""
    store = _get_store(request)
    proj = store.create_project(
        name=payload.name,
        width_m=payload.width_m,
        length_m=payload.length_m,
        height_m=payload.height_m,
    )
    return {"ok": True, "project": proj, "coach": compute_next_best_view(proj)}


@router.get("/projects/{project_id}")
async def get_room_project(request: Request, project_id: str) -> Dict[str, Any]:
    """Fetch a Room Studio project along with live Next-Best-View AI Capture Coach data."""
    store = _get_store(request)
    proj = store.get_project(project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail="Room Studio project not found.")
    return {"ok": True, "project": proj, "coach": compute_next_best_view(proj)}


@router.patch("/projects/{project_id}")
async def update_room_project(
    request: Request,
    project_id: str,
    payload: UpdateProjectRequest,
) -> Dict[str, Any]:
    """Update room shell dimensions or name."""
    store = _get_store(request)
    proj = store.get_project(project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail="Room Studio project not found.")
    if payload.name is not None:
        proj["name"] = payload.name.strip()
    if payload.width_m is not None:
        proj["width_m"] = float(payload.width_m)
    if payload.length_m is not None:
        proj["length_m"] = float(payload.length_m)
    if payload.height_m is not None:
        proj["height_m"] = float(payload.height_m)
    saved = store.save_project(proj)
    return {"ok": True, "project": saved, "coach": compute_next_best_view(saved)}


@router.delete("/projects/{project_id}")
async def delete_room_project(request: Request, project_id: str) -> Dict[str, Any]:
    """Delete a Room Studio project."""
    store = _get_store(request)
    removed = store.delete_project(project_id)
    return {"ok": True, "removed": removed}


@router.post("/projects/{project_id}/photos")
async def upload_room_photo(
    request: Request,
    project_id: str,
    file: UploadFile = File(...),
    name: str = Form(default=""),
    surface: str = Form(default="north_wall"),
    tags: str = Form(default=""),
) -> Dict[str, Any]:
    """Upload a high-res photo tagged to a wall/surface and store it in PostgreSQL 18."""
    store = _get_store(request)
    repo = _get_repo(request)
    proj = store.get_project(project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail="Room Studio project not found.")
    if repo is None:
        raise HTTPException(status_code=503, detail="Storage repository unavailable.")

    clean_surface = surface.strip().lower()
    if clean_surface not in VALID_SURFACES:
        clean_surface = "overview"

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Uploaded photo is empty.")

    arr = np.frombuffer(raw, dtype=np.uint8)
    decoded = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if decoded is None:
        raise HTTPException(status_code=400, detail="Uploaded file is not a valid JPEG/PNG image.")
    h, w = decoded.shape[:2]

    stored = repo.store_file(
        filename=file.filename or f"{clean_surface}_{uuid.uuid4().hex[:6]}.jpg",
        content_type=file.content_type or "image/jpeg",
        data=raw,
        category="room_studio_photo",
        metadata={"project_id": project_id, "surface": clean_surface},
    )

    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    photo_rec = {
        "id": f"photo_{uuid.uuid4().hex[:8]}",
        "file_id": stored["id"],
        "url": f"/api/files/{stored['id']}/download",
        "name": name.strip() or (file.filename or f"{clean_surface.replace('_', ' ').title()}"),
        "surface": clean_surface,
        "tags": tag_list,
        "camera_pose": dict(DEFAULT_SURFACE_CAMERA_POSES.get(clean_surface, DEFAULT_SURFACE_CAMERA_POSES["overview"])),
        "width": int(w),
        "height": int(h),
        "analyzed": False,
        "detected_count": 0,
        "uploaded_at": time.time(),
    }

    proj.setdefault("photos", []).append(photo_rec)
    # Automatically assign as wall texture if this surface has none yet
    if clean_surface in {"north_wall", "east_wall", "south_wall", "west_wall", "floor"}:
        wall_tex = proj.setdefault("wall_textures", {})
        if clean_surface not in wall_tex:
            wall_tex[clean_surface] = {
                "file_id": stored["id"],
                "url": f"/api/files/{stored['id']}/download",
                "method": "direct_photo",
                "photo_count": 1,
            }

    saved = store.save_project(proj)
    return {"ok": True, "photo": photo_rec, "project": saved, "coach": compute_next_best_view(saved)}


@router.delete("/projects/{project_id}/photos/{photo_id}")
async def delete_room_photo(request: Request, project_id: str, photo_id: str) -> Dict[str, Any]:
    """Remove a photo from a Room Studio project."""
    store = _get_store(request)
    proj = store.get_project(project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail="Room Studio project not found.")
    proj["photos"] = [p for p in proj.get("photos", []) if p.get("id") != photo_id]
    saved = store.save_project(proj)
    return {"ok": True, "project": saved, "coach": compute_next_best_view(saved)}


@router.post("/projects/{project_id}/photos/{photo_id}/analyze")
async def analyze_room_photo(request: Request, project_id: str, photo_id: str) -> Dict[str, Any]:
    """Run CAST-style Vision Scene Graph extraction on a room photo and place detected objects."""
    store = _get_store(request)
    repo = _get_repo(request)
    proj = store.get_project(project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail="Room Studio project not found.")
    photo = next((p for p in proj.get("photos", []) if p.get("id") == photo_id), None)
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found in project.")
    if repo is None:
        raise HTTPException(status_code=503, detail="Storage repository unavailable.")

    loaded = repo.get_file_with_bytes(str(photo["file_id"]))
    if not loaded:
        raise HTTPException(status_code=404, detail="Stored photo binary not found.")
    _, img_bytes = loaded

    raw_settings = (repo.get_settings_raw() if hasattr(repo, "get_settings_raw") else {}) or {}
    or_key = str(raw_settings.get("openrouter_api_key") or "").strip() or None
    or_model = str(raw_settings.get("openrouter_model") or "google/gemini-2.5-flash").strip()

    try:
        analysis = await parse_room_photo_objects(
            image_bytes=img_bytes,
            surface=str(photo.get("surface") or "north_wall"),
            notes=", ".join(photo.get("tags") or []) or str(photo.get("name") or ""),
            openrouter_api_key=or_key,
            openrouter_model=or_model,
        )
    except Exception as exc:
        sys.stderr.write(f"[room_studio.analyze] Vision analysis error: {exc}\n")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    created_objects: List[Dict[str, Any]] = []
    for item in analysis.get("objects") or []:
        bb = item["bbox_norm"]
        crop_b64 = None
        try:
            _, crop_b64, _ = crop_object_from_photo(img_bytes, bb)
        except Exception:
            crop_b64 = None
        pose = compute_physics_placement(
            room_width_m=float(proj["width_m"]),
            room_length_m=float(proj["length_m"]),
            room_height_m=float(proj["height_m"]),
            support_type=item["support_type"],
            support_surface=item["support_surface"],
            bbox_norm=bb,
            dimensions_m=item["dimensions_m"],
        )
        obj_rec = {
            "id": f"obj_{uuid.uuid4().hex[:8]}",
            "source_photo_id": photo_id,
            "name": item["name"],
            "category": item["category"],
            "support_type": item["support_type"],
            "support_surface": item["support_surface"],
            "bbox_norm": bb,
            "dimensions_m": item["dimensions_m"],
            "pose": pose,
            "color_hex": item["color_hex"],
            "confidence": item["confidence"],
            "mesh_file_id": None,
            "mesh_url": None,
            "mesh_engine": "none",
            "crop_b64": crop_b64,
            "notes": item.get("notes") or "",
        }
        proj.setdefault("objects", []).append(obj_rec)
        created_objects.append(obj_rec)

    photo["analyzed"] = True
    photo["detected_count"] = len(created_objects)
    saved = store.save_project(proj)
    return {
        "ok": True,
        "summary": analysis.get("summary"),
        "provider": analysis.get("provider"),
        "created_objects": created_objects,
        "project": saved,
        "coach": compute_next_best_view(saved),
    }


@router.post("/projects/{project_id}/stitch/{surface}")
async def stitch_wall_surface(request: Request, project_id: str, surface: str) -> Dict[str, Any]:
    """Stitch all photos tagged to a wall/floor surface into a single high-resolution texture."""
    store = _get_store(request)
    repo = _get_repo(request)
    proj = store.get_project(project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail="Room Studio project not found.")
    if repo is None:
        raise HTTPException(status_code=503, detail="Storage repository unavailable.")

    clean_surface = surface.strip().lower()
    matching = [p for p in proj.get("photos", []) if p.get("surface") == clean_surface]
    if not matching:
        raise HTTPException(status_code=400, detail=f"No photos tagged to '{clean_surface}'.")

    blobs: List[bytes] = []
    for p in matching:
        loaded = repo.get_file_with_bytes(str(p["file_id"]))
        if loaded:
            blobs.append(loaded[1])
    if not blobs:
        raise HTTPException(status_code=404, detail="Could not load source photo binaries.")

    stitched_jpg, method = await asyncio.to_thread(stitch_surface_photos, blobs)
    stored = repo.store_file(
        filename=f"stitched_{clean_surface}_{uuid.uuid4().hex[:6]}.jpg",
        content_type="image/jpeg",
        data=stitched_jpg,
        category="room_studio_texture",
        metadata={"project_id": project_id, "surface": clean_surface, "method": method},
    )
    proj.setdefault("wall_textures", {})[clean_surface] = {
        "file_id": stored["id"],
        "url": f"/api/files/{stored['id']}/download",
        "method": method,
        "photo_count": len(blobs),
    }
    saved = store.save_project(proj)
    return {
        "ok": True,
        "surface": clean_surface,
        "method": method,
        "texture": proj["wall_textures"][clean_surface],
        "project": saved,
    }


@router.post("/projects/{project_id}/splat")
async def upload_room_splat(
    request: Request,
    project_id: str,
    file: UploadFile = File(...),
) -> Dict[str, Any]:
    """Upload a 3D Gaussian Splat (.spz / .ply / .splat / .ksplat) room backdrop."""
    store = _get_store(request)
    repo = _get_repo(request)
    proj = store.get_project(project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail="Room Studio project not found.")
    if repo is None:
        raise HTTPException(status_code=503, detail="Storage repository unavailable.")

    fname = (file.filename or "room.spz").strip()
    ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else "spz"
    if ext not in {"spz", "ply", "splat", "ksplat", "glb"}:
        raise HTTPException(status_code=400, detail="Unsupported 3D backdrop format; use .spz, .ply, .splat, .ksplat, or .glb.")
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Uploaded 3D file is empty.")

    stored = repo.store_file(
        filename=fname,
        content_type="application/octet-stream",
        data=raw,
        category="room_studio_splat",
        metadata={"project_id": project_id, "format": ext},
    )
    proj["splat_file_id"] = stored["id"]
    proj["splat_url"] = f"/api/files/{stored['id']}/download"
    proj["splat_filename"] = fname
    proj["splat_format"] = ext
    saved = store.save_project(proj)
    return {"ok": True, "project": saved}


@router.post("/projects/{project_id}/objects")
async def create_room_object(
    request: Request,
    project_id: str,
    payload: CreateObjectRequest,
) -> Dict[str, Any]:
    """Manually tag/box an object (e.g., guitar on wall, mug on desk) in a photo."""
    store = _get_store(request)
    repo = _get_repo(request)
    proj = store.get_project(project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail="Room Studio project not found.")

    st = payload.support_type.upper()
    if st not in VALID_SUPPORT_TYPES:
        st = "ON_FLOOR"

    crop_b64 = None
    if payload.source_photo_id and repo is not None:
        photo = next((p for p in proj.get("photos", []) if p.get("id") == payload.source_photo_id), None)
        if photo:
            loaded = repo.get_file_with_bytes(str(photo["file_id"]))
            if loaded:
                try:
                    _, crop_b64, _ = crop_object_from_photo(loaded[1], payload.bbox_norm)
                except Exception:
                    crop_b64 = None

    pose = compute_physics_placement(
        room_width_m=float(proj["width_m"]),
        room_length_m=float(proj["length_m"]),
        room_height_m=float(proj["height_m"]),
        support_type=st,
        support_surface=payload.support_surface,
        bbox_norm=payload.bbox_norm,
        dimensions_m=payload.dimensions_m,
    )
    obj_rec = {
        "id": f"obj_{uuid.uuid4().hex[:8]}",
        "source_photo_id": payload.source_photo_id,
        "name": payload.name.strip(),
        "category": payload.category.strip(),
        "support_type": st,
        "support_surface": payload.support_surface.strip().lower(),
        "bbox_norm": payload.bbox_norm,
        "dimensions_m": payload.dimensions_m,
        "pose": pose,
        "color_hex": payload.color_hex,
        "confidence": 1.0,
        "mesh_file_id": None,
        "mesh_url": None,
        "mesh_engine": "none",
        "crop_b64": crop_b64,
        "notes": payload.notes,
    }
    proj.setdefault("objects", []).append(obj_rec)
    saved = store.save_project(proj)
    return {"ok": True, "object": obj_rec, "project": saved, "coach": compute_next_best_view(saved)}


@router.patch("/projects/{project_id}/objects/{object_id}")
async def update_room_object(
    request: Request,
    project_id: str,
    object_id: str,
    payload: UpdateObjectRequest,
) -> Dict[str, Any]:
    """Update a 3D object's pose (from Three.js TransformControls), name, or support surface."""
    store = _get_store(request)
    proj = store.get_project(project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail="Room Studio project not found.")
    obj = next((o for o in proj.get("objects", []) if o.get("id") == object_id), None)
    if obj is None:
        raise HTTPException(status_code=404, detail="Object not found.")

    if payload.name is not None:
        obj["name"] = payload.name.strip()
    if payload.support_type is not None and payload.support_type.upper() in VALID_SUPPORT_TYPES:
        obj["support_type"] = payload.support_type.upper()
    if payload.support_surface is not None:
        obj["support_surface"] = payload.support_surface.strip().lower()
    if payload.dimensions_m is not None and len(payload.dimensions_m) >= 3:
        obj["dimensions_m"] = [max(0.04, float(v)) for v in payload.dimensions_m[:3]]
    if payload.color_hex is not None:
        obj["color_hex"] = payload.color_hex
    if payload.notes is not None:
        obj["notes"] = payload.notes
    if payload.pose is not None:
        cur = dict(obj.get("pose") or {})
        for k in ("x", "y", "z", "rx", "ry", "rz", "scale"):
            if k in payload.pose and payload.pose[k] is not None:
                cur[k] = round(float(payload.pose[k]), 4)
        obj["pose"] = cur

    saved = store.save_project(proj)
    return {"ok": True, "object": obj, "project": saved}


@router.delete("/projects/{project_id}/objects/{object_id}")
async def delete_room_object(request: Request, project_id: str, object_id: str) -> Dict[str, Any]:
    """Remove an object from the Room Studio scene."""
    store = _get_store(request)
    proj = store.get_project(project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail="Room Studio project not found.")
    proj["objects"] = [o for o in proj.get("objects", []) if o.get("id") != object_id]
    saved = store.save_project(proj)
    return {"ok": True, "project": saved, "coach": compute_next_best_view(saved)}


@router.post("/projects/{project_id}/objects/{object_id}/generate-3d")
async def generate_object_3d_glb(
    request: Request,
    project_id: str,
    object_id: str,
    payload: Generate3DRequest,
) -> Dict[str, Any]:
    """Convert a tagged object crop into a Three.js PBR ``.glb`` mesh (local or fal.ai)."""
    store = _get_store(request)
    repo = _get_repo(request)
    proj = store.get_project(project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail="Room Studio project not found.")
    obj = next((o for o in proj.get("objects", []) if o.get("id") == object_id), None)
    if obj is None:
        raise HTTPException(status_code=404, detail="Object not found.")
    if repo is None:
        raise HTTPException(status_code=503, detail="Storage repository unavailable.")

    engine = payload.engine.strip()
    if engine not in ALLOWED_3D_ENGINES:
        raise HTTPException(status_code=400, detail=f"Unsupported 3D engine {engine!r}.")

    # Load source crop PNG
    crop_png: Optional[bytes] = None
    src_photo = next((p for p in proj.get("photos", []) if p.get("id") == obj.get("source_photo_id")), None)
    if src_photo is not None:
        loaded = repo.get_file_with_bytes(str(src_photo["file_id"]))
        if loaded:
            crop_png, preview_b64, _ = crop_object_from_photo(loaded[1], obj.get("bbox_norm") or [0.1, 0.1, 0.9, 0.9])
            obj["crop_b64"] = preview_b64

    if crop_png is None:
        # Synthesize a clean solid swatch PNG if object was created without a source photo
        swatch = np.full((256, 256, 3), 180, dtype=np.uint8)
        ok, enc = cv2.imencode(".png", swatch)
        crop_png = enc.tobytes() if ok else b""

    try:
        if engine == "local_depth3d":
            glb_bytes = await asyncio.to_thread(
                generate_local_depth_glb,
                crop_png,
                obj.get("dimensions_m") or [0.35, 0.45, 0.12],
            )
        else:
            raw_settings = (repo.get_settings_raw() if hasattr(repo, "get_settings_raw") else {}) or {}
            fal_key = str(raw_settings.get("fal_api_key") or "").strip()
            if not fal_key:
                raise HTTPException(
                    status_code=400,
                    detail="fal_api_key is not configured in Settings (/config). Add your fal.ai key or use Instant Local 3D.",
                )
            glb_bytes = await generate_fal_3d_glb(
                crop_png_bytes=crop_png,
                fal_api_key=fal_key,
                model_id=engine,
            )
    except HTTPException:
        raise
    except Exception as exc:
        sys.stderr.write(f"[room_studio.generate_3d] Failed generating 3D for {object_id}: {exc}\n")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    stored = repo.store_file(
        filename=f"{obj['id']}_{engine.replace('/', '_')}.glb",
        content_type="model/gltf-binary",
        data=glb_bytes,
        category="room_studio_glb",
        metadata={"project_id": project_id, "object_id": object_id, "engine": engine},
    )
    obj["mesh_file_id"] = stored["id"]
    obj["mesh_url"] = f"/api/files/{stored['id']}/download"
    obj["mesh_engine"] = engine
    obj["mesh_bytes"] = len(glb_bytes)

    saved = store.save_project(proj)
    return {
        "ok": True,
        "object": obj,
        "project": saved,
        "coach": compute_next_best_view(saved),
    }


@router.get("/projects/{project_id}/coach")
async def get_room_capture_coach(request: Request, project_id: str) -> Dict[str, Any]:
    """Return Next-Best-View 3D ghost camera frustums and room coverage score."""
    store = _get_store(request)
    proj = store.get_project(project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail="Room Studio project not found.")
    return {"ok": True, "coach": compute_next_best_view(proj)}
