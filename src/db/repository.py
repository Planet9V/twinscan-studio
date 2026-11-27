"""PostgreSQL 18 + pgvector pooled twin repository with Fernet app_settings and content-addressed file storage.

Implements ``PostgresTwinRepository`` (backed by ``psycopg_pool.ConnectionPool``,
``halfvec(1536)`` HNSW iterative scans, Fernet-encrypted ``app_settings``, immutable
``settings_audit_log``, SHA-256 deduplicated ``file_blobs`` + ``stored_files``, and
``vision_usage_log``) plus ``InMemoryTwinRepository`` for isolated pytest runs.
"""

from __future__ import annotations

import hashlib
import json
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional, Protocol, Tuple

import numpy as np
import psycopg
from pgvector import HalfVector
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from src.db.crypto import SecretCipher, mask_secret_value

MANAGED_SETTING_SPECS: List[dict[str, Any]] = [
    {"key": "openrouter_api_key", "is_secret": True, "category": "vision", "description": "OpenRouter API key for Vision, Research & Embeddings"},
    {"key": "openrouter_base_url", "is_secret": False, "category": "vision", "description": "OpenRouter OpenAI-compatible base URL"},
    {"key": "openrouter_default_vision_model", "is_secret": False, "category": "vision", "description": "Primary Vision VLM for nameplate & tag extraction"},
    {"key": "openrouter_secondary_vision_model", "is_secret": False, "category": "vision", "description": "Secondary Vision VLM for Dual-Model Consensus"},
    {"key": "openrouter_research_model", "is_secret": False, "category": "vision", "description": "Web-grounded OpenRouter model for Pass-3 direct equipment research"},
    {"key": "openrouter_embedding_model", "is_secret": False, "category": "vision", "description": "Embedding model for PostgreSQL 18 pgvector halfvec index"},
    {"key": "fal_api_key", "is_secret": True, "category": "vision", "description": "Optional Fernet-encrypted fal.ai API key for Overwatch ROI super-resolution"},
    {"key": "fal_upscale_model", "is_secret": False, "category": "vision", "description": "fal.ai ROI upscale model (fal-ai/esrgan or fal-ai/clarity-upscaler)"},
    {"key": "neo4j_uri", "is_secret": False, "category": "neo4j", "description": "Local Neo4j 5 Bolt URI (e.g. bolt://neo4j:7687)"},
    {"key": "neo4j_user", "is_secret": False, "category": "neo4j", "description": "Neo4j username"},
    {"key": "neo4j_password", "is_secret": True, "category": "neo4j", "description": "Neo4j password"},
    {"key": "facility_name", "is_secret": False, "category": "spatial", "description": "Default Eigenia facility name"},
    {"key": "near_proximity_m", "is_secret": False, "category": "spatial", "description": "Max distance (m) for automatic Neo4j NEAR edges"},
    {"key": "default_camera_fov_deg", "is_secret": False, "category": "spatial", "description": "Camera horizontal FOV (deg) for LiDAR raycast auto-placement"},
    {"key": "default_camera_yaw_offset_deg", "is_secret": False, "category": "spatial", "description": "Camera-to-LiDAR boresight yaw offset (deg)"},
    {"key": "default_wall_height_m", "is_secret": False, "category": "spatial", "description": "3D extruded wall height (m) in Three.js & Babylon.js"},
    {"key": "overwatch_calibrations_json", "is_secret": False, "category": "spatial", "description": "Persisted JSON map of Overwatch camera extrinsics & 4-point homographies"},
    {"key": "max_upload_mb", "is_secret": False, "category": "storage", "description": "Maximum single file upload size (MB) into PostgreSQL"},
    {"key": "openclaw_gateway_url", "is_secret": False, "category": "openclaw", "description": "Portable OpenClaw Gateway URL (e.g. http://openclaw-gateway:18789)"},
    {"key": "openclaw_gateway_token", "is_secret": True, "category": "openclaw", "description": "Fernet-encrypted OpenClaw Gateway authentication token"},
    {"key": "openclaw_mcp_bearer_token", "is_secret": True, "category": "openclaw", "description": "Optional Fernet-encrypted Bearer token protecting /api/agent/mcp and /api/agent/execute"},
    {"key": "openclaw_telegram_bot_token", "is_secret": True, "category": "openclaw", "description": "Optional Fernet-encrypted Telegram bot token for OpenClaw remote messaging"},
    {"key": "openclaw_discord_bot_token", "is_secret": True, "category": "openclaw", "description": "Optional Fernet-encrypted Discord bot token for OpenClaw remote messaging"},
]

MANAGED_SPEC_BY_KEY: dict[str, dict[str, Any]] = {s["key"]: s for s in MANAGED_SETTING_SPECS}


class TwinRepositoryProtocol(Protocol):
    """Unified interface for PostgreSQL 18 and in-memory TwinScan storage."""

    def initialize(self) -> None: ...
    def close(self) -> None: ...
    def check_health(self) -> dict[str, Any]: ...
    def list_spaces(self) -> List[dict[str, Any]]: ...
    def get_space(self, space_id: str) -> Optional[dict[str, Any]]: ...
    def create_space(self, name: str, facility: str = "Eigenia Facility", description: str = "") -> dict[str, Any]: ...
    def update_space(
        self,
        space_id: str,
        name: Optional[str] = None,
        facility: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Optional[dict[str, Any]]: ...
    def delete_space(self, space_id: str) -> bool: ...
    def save_walls(self, space_id: str, walls: List[dict[str, Any]], metrics: dict[str, Any]) -> dict[str, Any]: ...
    def save_zones(self, space_id: str, zones: List[dict[str, Any]]) -> List[dict[str, Any]]: ...
    def create_equipment(
        self,
        space_id: str,
        asset: dict[str, Any],
        embedding: Optional[List[float]] = None,
        embedding_model: str = "fallback",
    ) -> dict[str, Any]: ...
    def get_equipment(self, equipment_id: str) -> Optional[dict[str, Any]]: ...
    def list_equipment(self, space_id: Optional[str] = None) -> List[dict[str, Any]]: ...
    def delete_equipment(self, equipment_id: str) -> bool: ...
    def update_equipment_enrichment(
        self,
        equipment_id: str,
        enrichment: dict[str, Any],
        updates: Optional[dict[str, Any]] = None,
        embedding: Optional[List[float]] = None,
        embedding_model: Optional[str] = None,
    ) -> Optional[dict[str, Any]]: ...
    def update_equipment_embedding(
        self,
        equipment_id: str,
        embedding: List[float],
        embedding_model: str,
    ) -> bool: ...
    def record_anomalies(self, space_id: str, anomalies: List[dict[str, Any]]) -> List[dict[str, Any]]: ...
    def list_anomalies(self, space_id: str) -> List[dict[str, Any]]: ...
    def search_equipment_semantic(
        self,
        query_embedding: List[float],
        limit: int = 8,
        space_id: Optional[str] = None,
        manufacturer: Optional[str] = None,
    ) -> List[dict[str, Any]]: ...
    # Admin settings & audit
    def get_settings_raw(self) -> dict[str, str]: ...
    def list_settings_masked(self, defaults: dict[str, str]) -> List[dict[str, Any]]: ...
    def upsert_settings(
        self,
        updates: dict[str, str],
        source_ip: str = "local",
    ) -> List[dict[str, Any]]: ...
    def list_settings_audit(self, limit: int = 30) -> List[dict[str, Any]]: ...
    # Content-addressed PostgreSQL file storage
    def store_file(
        self,
        filename: str,
        content_type: str,
        data: bytes,
        category: str = "general",
        space_id: Optional[str] = None,
        equipment_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]: ...
    def list_files(
        self,
        category: Optional[str] = None,
        space_id: Optional[str] = None,
        equipment_id: Optional[str] = None,
    ) -> List[dict[str, Any]]: ...
    def get_file_meta(self, file_id: str) -> Optional[dict[str, Any]]: ...
    def get_file_with_bytes(self, file_id: str) -> Optional[Tuple[dict[str, Any], bytes]]: ...
    def delete_file(self, file_id: str) -> bool: ...
    def storage_stats(self) -> dict[str, Any]: ...
    def verify_and_scrub_storage(self) -> dict[str, Any]: ...
    # Vision telemetry ledger
    def log_vision_usage(self, entry: dict[str, Any]) -> dict[str, Any]: ...
    def list_vision_usage(self, limit: int = 30) -> List[dict[str, Any]]: ...


class InMemoryTwinRepository:
    """In-memory implementation matching PostgreSQL 18 repository semantics for pytest."""

    def __init__(self, encryption_key: str = "") -> None:
        """Initialize in-memory tables and Fernet secret cipher."""
        self._cipher = SecretCipher(encryption_key)
        self._spaces: dict[str, dict[str, Any]] = {}
        self._equipment: dict[str, dict[str, Any]] = {}
        self._embeddings: dict[str, np.ndarray] = {}
        self._anomalies: dict[str, List[dict[str, Any]]] = {}
        self._settings: dict[str, dict[str, Any]] = {}
        self._audit_log: List[dict[str, Any]] = []
        self._blobs: dict[str, bytes] = {}
        self._files: dict[str, dict[str, Any]] = {}
        self._usage_log: List[dict[str, Any]] = []

    def initialize(self) -> None:
        """Seed a default control-room space when empty."""
        if not self._spaces:
            self.create_space(
                name="Primary OT Control Room",
                facility="Eigenia Lab",
                description="Default scanned critical-infrastructure room",
            )

    def close(self) -> None:
        """No-op close for in-memory store."""

    def check_health(self) -> dict[str, Any]:
        """Return synthetic health diagnostics for in-memory backend."""
        return {
            "status": "connected",
            "backend": "InMemoryTwinRepository",
            "postgres_version": "in-memory-test",
            "pgvector_version": "simulated-halfvec",
            "pool_size": 0,
        }

    def list_spaces(self) -> List[dict[str, Any]]:
        """List all spaces."""
        return list(self._spaces.values())

    def get_space(self, space_id: str) -> Optional[dict[str, Any]]:
        """Get one space by ID."""
        return self._spaces.get(space_id)

    def create_space(self, name: str, facility: str = "Eigenia Facility", description: str = "") -> dict[str, Any]:
        """Create a new space."""
        sid = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        space = {
            "id": sid,
            "name": name,
            "facility": facility,
            "description": description,
            "walls": [],
            "zones": [],
            "metrics": {},
            "created_at": now,
            "updated_at": now,
        }
        self._spaces[sid] = space
        self._anomalies[sid] = []
        return space

    def update_space(
        self,
        space_id: str,
        name: Optional[str] = None,
        facility: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Update mutable metadata fields on an existing space."""
        space = self._spaces.get(space_id)
        if not space:
            return None
        if name is not None:
            cleaned = str(name).strip()
            if cleaned:
                space["name"] = cleaned
        if facility is not None:
            space["facility"] = str(facility).strip()
        if description is not None:
            space["description"] = str(description).strip()
        space["updated_at"] = datetime.now(timezone.utc).isoformat()
        return space

    def delete_space(self, space_id: str) -> bool:
        """Delete a space and cascade-remove its equipment."""
        if space_id not in self._spaces:
            return False
        del self._spaces[space_id]
        self._anomalies.pop(space_id, None)
        for eid in [k for k, v in self._equipment.items() if v["space_id"] == space_id]:
            del self._equipment[eid]
            self._embeddings.pop(eid, None)
        return True

    def save_walls(self, space_id: str, walls: List[dict[str, Any]], metrics: dict[str, Any]) -> dict[str, Any]:
        """Save RANSAC wall vectors and room metrics."""
        space = self._spaces.get(space_id)
        if not space:
            raise KeyError(f"Space {space_id} not found")
        space["walls"] = walls
        space["metrics"] = metrics
        space["updated_at"] = datetime.now(timezone.utc).isoformat()
        return space

    def save_zones(self, space_id: str, zones: List[dict[str, Any]]) -> List[dict[str, Any]]:
        """Save polygon zones for a space."""
        space = self._spaces.get(space_id)
        if not space:
            raise KeyError(f"Space {space_id} not found")
        space["zones"] = zones
        space["updated_at"] = datetime.now(timezone.utc).isoformat()
        return zones

    def create_equipment(
        self,
        space_id: str,
        asset: dict[str, Any],
        embedding: Optional[List[float]] = None,
        embedding_model: str = "fallback",
    ) -> dict[str, Any]:
        """Insert a placed equipment twin with optional vector embedding."""
        if space_id not in self._spaces:
            raise KeyError(f"Space {space_id} not found")
        eid = asset.get("id") or str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        record = {
            "id": eid,
            "space_id": space_id,
            "name": asset.get("name", "Unnamed Equipment"),
            "equipment_type": asset.get("equipment_type", "Industrial Equipment"),
            "dexpi_class": asset.get("dexpi_class", "Equipment"),
            "manufacturer": asset.get("manufacturer", "Unknown"),
            "model_number": asset.get("model_number", "Unknown"),
            "part_number": asset.get("part_number"),
            "serial_number": asset.get("serial_number"),
            "inferred_cpe_23": asset.get("inferred_cpe_23"),
            "voltage_rating": asset.get("voltage_rating"),
            "current_or_power": asset.get("current_or_power"),
            "certifications": list(asset.get("certifications") or []),
            "asset_tags": list(asset.get("asset_tags") or []),
            "mac_addresses": list(asset.get("mac_addresses") or []),
            "ip_or_hostname_labels": list(asset.get("ip_or_hostname_labels") or []),
            "barcodes": list(asset.get("barcodes") or []),
            "x": float(asset.get("x", 0.0)),
            "y": float(asset.get("y", 0.0)),
            "z": float(asset.get("z", 0.0)),
            "yaw_deg": float(asset.get("yaw_deg", 0.0)),
            "width_m": float(asset.get("width_m", 0.7)),
            "depth_m": float(asset.get("depth_m", 0.7)),
            "height_m": float(asset.get("height_m", 1.5)),
            "confidence": float(asset.get("confidence", 0.85)),
            "model_used": asset.get("model_used", "manual"),
            "image_file_id": asset.get("image_file_id"),
            "image_url": asset.get("image_url"),
            "embedding_model": embedding_model,
            "enrichment": dict(asset.get("enrichment") or {}),
            "raw_notes": asset.get("raw_notes", ""),
            "created_at": now,
        }
        self._equipment[eid] = record
        if embedding:
            vec = np.asarray(embedding, dtype=np.float32)
            norm = float(np.linalg.norm(vec))
            if norm > 0:
                vec /= norm
            self._embeddings[eid] = vec
        return record

    def get_equipment(self, equipment_id: str) -> Optional[dict[str, Any]]:
        """Return one equipment asset by ID."""
        return self._equipment.get(equipment_id)

    def list_equipment(self, space_id: Optional[str] = None) -> List[dict[str, Any]]:
        """List equipment assets optionally scoped to a space."""
        items = list(self._equipment.values())
        return [e for e in items if e["space_id"] == space_id] if space_id else items

    def delete_equipment(self, equipment_id: str) -> bool:
        """Delete an equipment record."""
        removed = self._equipment.pop(equipment_id, None)
        self._embeddings.pop(equipment_id, None)
        return removed is not None

    def update_equipment_enrichment(
        self,
        equipment_id: str,
        enrichment: dict[str, Any],
        updates: Optional[dict[str, Any]] = None,
        embedding: Optional[List[float]] = None,
        embedding_model: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Merge Pass-3 direct research enrichment dossier and optional dimension/CPE updates."""
        rec = self._equipment.get(equipment_id)
        if not rec:
            return None
        rec["enrichment"] = enrichment
        for k, v in (updates or {}).items():
            if v is not None and k in rec:
                rec[k] = v
        if embedding:
            vec = np.asarray(embedding, dtype=np.float32)
            norm = float(np.linalg.norm(vec))
            if norm > 0:
                vec /= norm
            self._embeddings[equipment_id] = vec
        if embedding_model:
            rec["embedding_model"] = embedding_model
        return rec

    def update_equipment_embedding(
        self,
        equipment_id: str,
        embedding: List[float],
        embedding_model: str,
    ) -> bool:
        """Replace an asset's vector embedding after an embedding model change."""
        rec = self._equipment.get(equipment_id)
        if not rec:
            return False
        vec = np.asarray(embedding, dtype=np.float32)
        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec /= norm
        self._embeddings[equipment_id] = vec
        rec["embedding_model"] = embedding_model
        return True

    def record_anomalies(self, space_id: str, anomalies: List[dict[str, Any]]) -> List[dict[str, Any]]:
        """Record physical change anomalies."""
        now = datetime.now(timezone.utc).isoformat()
        stored = [{**a, "id": str(uuid.uuid4()), "space_id": space_id, "detected_at": now} for a in anomalies]
        self._anomalies.setdefault(space_id, []).extend(stored)
        return stored

    def list_anomalies(self, space_id: str) -> List[dict[str, Any]]:
        """List anomalies for a space."""
        return list(self._anomalies.get(space_id, []))

    def search_equipment_semantic(
        self,
        query_embedding: List[float],
        limit: int = 8,
        space_id: Optional[str] = None,
        manufacturer: Optional[str] = None,
    ) -> List[dict[str, Any]]:
        """Cosine similarity search over equipment embeddings."""
        q = np.asarray(query_embedding, dtype=np.float32)
        q_norm = float(np.linalg.norm(q))
        if q_norm > 0:
            q /= q_norm
        scored: List[tuple[float, dict[str, Any]]] = []
        for eid, item in self._equipment.items():
            if space_id and item["space_id"] != space_id:
                continue
            if manufacturer and item["manufacturer"].lower() != manufacturer.lower():
                continue
            vec = self._embeddings.get(eid)
            score = float(np.dot(q, vec)) if vec is not None and len(vec) == len(q) else 0.0
            scored.append((score, {**item, "similarity": round(score, 4)}))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _, item in scored[:limit]]

    # --- Admin Settings & Audit ---
    def get_settings_raw(self) -> dict[str, str]:
        """Return decrypted key-value settings persisted in the store."""
        out: dict[str, str] = {}
        for k, row in self._settings.items():
            out[k] = self._cipher.decrypt(row["value"]) if row["is_secret"] else row["value"]
        return out

    def list_settings_masked(self, defaults: dict[str, str]) -> List[dict[str, Any]]:
        """Return all managed settings with secret values masked."""
        raw = self.get_settings_raw()
        items: List[dict[str, Any]] = []
        for spec in MANAGED_SETTING_SPECS:
            key = spec["key"]
            is_secret = bool(spec["is_secret"])
            persisted = key in self._settings
            val = raw.get(key) if persisted else defaults.get(key, "")
            is_set = bool(val and val != "your_openrouter_api_key_here")
            items.append(
                {
                    "key": key,
                    "value": mask_secret_value(val) if is_secret else (val or ""),
                    "is_secret": is_secret,
                    "is_set": is_set,
                    "persisted": persisted,
                    "category": spec["category"],
                    "description": spec["description"],
                    "updated_at": self._settings[key]["updated_at"] if persisted else None,
                }
            )
        return items

    def upsert_settings(self, updates: dict[str, str], source_ip: str = "local") -> List[dict[str, Any]]:
        """Upsert settings, encrypting secrets with Fernet and logging audit entries."""
        now = datetime.now(timezone.utc).isoformat()
        changed: List[dict[str, Any]] = []
        for key, new_val in updates.items():
            spec = MANAGED_SPEC_BY_KEY.get(key, {"is_secret": "key" in key or "password" in key, "category": "custom", "description": ""})
            is_secret = bool(spec["is_secret"])
            # Ignore unchanged masked placeholders sent back by the UI.
            if is_secret and "••••" in new_val:
                continue
            old_raw = self.get_settings_raw().get(key, "")
            stored_val = self._cipher.encrypt(new_val) if is_secret else new_val
            self._settings[key] = {
                "key": key,
                "value": stored_val,
                "is_secret": is_secret,
                "category": spec["category"],
                "description": spec["description"],
                "updated_at": now,
            }
            audit = {
                "id": str(uuid.uuid4()),
                "key": key,
                "old_preview": mask_secret_value(old_raw) if is_secret else old_raw,
                "new_preview": mask_secret_value(new_val) if is_secret else new_val,
                "source_ip": source_ip,
                "changed_at": now,
            }
            self._audit_log.insert(0, audit)
            changed.append(audit)
        return changed

    def list_settings_audit(self, limit: int = 30) -> List[dict[str, Any]]:
        """Return most recent configuration audit log rows."""
        return self._audit_log[:limit]

    # --- Content-Addressed File Storage ---
    def store_file(
        self,
        filename: str,
        content_type: str,
        data: bytes,
        category: str = "general",
        space_id: Optional[str] = None,
        equipment_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Store file bytes deduplicated by SHA-256."""
        sha = hashlib.sha256(data).hexdigest()
        deduplicated = sha in self._blobs
        if not deduplicated:
            self._blobs[sha] = data
        fid = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        rec = {
            "id": fid,
            "filename": filename,
            "content_type": content_type,
            "size_bytes": len(data),
            "sha256": sha,
            "deduplicated": deduplicated,
            "category": category,
            "space_id": space_id,
            "equipment_id": equipment_id,
            "metadata": dict(metadata or {}),
            "url": f"/api/files/{fid}",
            "created_at": now,
        }
        self._files[fid] = rec
        return rec

    def list_files(
        self,
        category: Optional[str] = None,
        space_id: Optional[str] = None,
        equipment_id: Optional[str] = None,
    ) -> List[dict[str, Any]]:
        """List stored files without transferring binary payloads."""
        items = list(self._files.values())
        if category:
            items = [f for f in items if f["category"] == category]
        if space_id:
            items = [f for f in items if f["space_id"] == space_id]
        if equipment_id:
            items = [f for f in items if f["equipment_id"] == equipment_id]
        items.sort(key=lambda f: f["created_at"], reverse=True)
        return items

    def get_file_meta(self, file_id: str) -> Optional[dict[str, Any]]:
        """Return metadata for a stored file."""
        return self._files.get(file_id)

    def get_file_with_bytes(self, file_id: str) -> Optional[Tuple[dict[str, Any], bytes]]:
        """Return file metadata and binary content."""
        meta = self._files.get(file_id)
        if not meta:
            return None
        blob = self._blobs.get(meta["sha256"])
        if blob is None:
            return None
        return meta, blob

    def delete_file(self, file_id: str) -> bool:
        """Delete file reference (blob cleaned on scrub or if unreferenced)."""
        removed = self._files.pop(file_id, None)
        if not removed:
            return False
        sha = removed["sha256"]
        if not any(f["sha256"] == sha for f in self._files.values()):
            self._blobs.pop(sha, None)
        return True

    def storage_stats(self) -> dict[str, Any]:
        """Compute total logical vs deduplicated physical storage metrics."""
        logical = sum(f["size_bytes"] for f in self._files.values())
        physical = sum(len(b) for b in self._blobs.values())
        return {
            "file_count": len(self._files),
            "unique_blob_count": len(self._blobs),
            "logical_bytes": logical,
            "physical_bytes": physical,
            "dedup_savings_bytes": max(0, logical - physical),
        }

    def verify_and_scrub_storage(self) -> dict[str, Any]:
        """Verify SHA-256 integrity of every blob and prune unreferenced orphans."""
        referenced = {f["sha256"] for f in self._files.values()}
        orphans = [sha for sha in list(self._blobs.keys()) if sha not in referenced]
        for sha in orphans:
            self._blobs.pop(sha, None)
        corrupted = [
            sha for sha, blob in self._blobs.items() if hashlib.sha256(blob).hexdigest() != sha
        ]
        return {
            "verified_blobs": len(self._blobs) - len(corrupted),
            "corrupted_blobs": len(corrupted),
            "pruned_orphans": len(orphans),
        }

    # --- Vision Telemetry ---
    def log_vision_usage(self, entry: dict[str, Any]) -> dict[str, Any]:
        """Append a vision/research inference usage record."""
        rec = {
            "id": str(uuid.uuid4()),
            "created_at": datetime.now(timezone.utc).isoformat(),
            **entry,
        }
        self._usage_log.insert(0, rec)
        return rec

    def list_vision_usage(self, limit: int = 30) -> List[dict[str, Any]]:
        """Return recent vision/research usage metrics."""
        return self._usage_log[:limit]


class PostgresTwinRepository:
    """Pooled PostgreSQL 18 + pgvector repository with Fernet settings & content-addressed file storage."""

    def __init__(
        self,
        database_url: str,
        embedding_dimensions: int = 1536,
        encryption_key: str = "",
    ) -> None:
        """Initialize the pooled Postgres 18 repository."""
        self.database_url = database_url
        self.embedding_dimensions = embedding_dimensions
        self._cipher = SecretCipher(encryption_key)
        self._pool: Optional[ConnectionPool] = None

    def _ensure_pool(self) -> ConnectionPool:
        if self._pool is None:
            def _configure_conn(conn: psycopg.Connection[Any]) -> None:
                register_vector(conn)

            self._pool = ConnectionPool(
                conninfo=self.database_url,
                min_size=1,
                max_size=10,
                kwargs={"row_factory": dict_row},
                configure=_configure_conn,
                open=True,
            )
        return self._pool

    def close(self) -> None:
        """Close the PostgreSQL connection pool cleanly."""
        if self._pool is not None:
            self._pool.close()
            self._pool = None

    def initialize(self) -> None:
        """Create pgvector extension, twin tables, Fernet app_settings, audit, file_blobs, and usage logs."""
        ddl = f"""
        CREATE EXTENSION IF NOT EXISTS vector;

        CREATE TABLE IF NOT EXISTS spaces (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            facility TEXT NOT NULL DEFAULT 'Eigenia Facility',
            description TEXT NOT NULL DEFAULT '',
            walls JSONB NOT NULL DEFAULT '[]'::jsonb,
            zones JSONB NOT NULL DEFAULT '[]'::jsonb,
            metrics JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS file_blobs (
            sha256 TEXT PRIMARY KEY,
            size_bytes BIGINT NOT NULL,
            data BYTEA NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS stored_files (
            id TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            content_type TEXT NOT NULL,
            size_bytes BIGINT NOT NULL,
            sha256 TEXT NOT NULL REFERENCES file_blobs(sha256),
            category TEXT NOT NULL DEFAULT 'general',
            space_id TEXT REFERENCES spaces(id) ON DELETE SET NULL,
            equipment_id TEXT,
            metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS equipment_assets (
            id TEXT PRIMARY KEY,
            space_id TEXT NOT NULL REFERENCES spaces(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            equipment_type TEXT NOT NULL DEFAULT 'Industrial Equipment',
            dexpi_class TEXT NOT NULL DEFAULT 'Equipment',
            manufacturer TEXT NOT NULL DEFAULT 'Unknown',
            model_number TEXT NOT NULL DEFAULT 'Unknown',
            part_number TEXT,
            serial_number TEXT,
            inferred_cpe_23 TEXT,
            voltage_rating TEXT,
            current_or_power TEXT,
            certifications JSONB NOT NULL DEFAULT '[]'::jsonb,
            asset_tags JSONB NOT NULL DEFAULT '[]'::jsonb,
            mac_addresses JSONB NOT NULL DEFAULT '[]'::jsonb,
            ip_or_hostname_labels JSONB NOT NULL DEFAULT '[]'::jsonb,
            barcodes JSONB NOT NULL DEFAULT '[]'::jsonb,
            x DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            y DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            z DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            yaw_deg DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            width_m DOUBLE PRECISION NOT NULL DEFAULT 0.7,
            depth_m DOUBLE PRECISION NOT NULL DEFAULT 0.7,
            height_m DOUBLE PRECISION NOT NULL DEFAULT 1.5,
            confidence DOUBLE PRECISION NOT NULL DEFAULT 0.85,
            model_used TEXT NOT NULL DEFAULT 'manual',
            image_file_id TEXT REFERENCES stored_files(id) ON DELETE SET NULL,
            image_url TEXT,
            embedding_model TEXT NOT NULL DEFAULT 'fallback',
            enrichment JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            raw_notes TEXT NOT NULL DEFAULT '',
            spec_embedding halfvec({self.embedding_dimensions}),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        ALTER TABLE equipment_assets ADD COLUMN IF NOT EXISTS image_file_id TEXT;
        ALTER TABLE equipment_assets ADD COLUMN IF NOT EXISTS embedding_model TEXT NOT NULL DEFAULT 'fallback';
        ALTER TABLE equipment_assets ADD COLUMN IF NOT EXISTS enrichment JSONB NOT NULL DEFAULT '{{}}'::jsonb;

        CREATE INDEX IF NOT EXISTS idx_equipment_spec_hnsw
            ON equipment_assets
            USING hnsw (spec_embedding halfvec_cosine_ops);

        CREATE TABLE IF NOT EXISTS change_anomalies (
            id TEXT PRIMARY KEY,
            space_id TEXT NOT NULL REFERENCES spaces(id) ON DELETE CASCADE,
            anomaly_type TEXT NOT NULL,
            centroid_x DOUBLE PRECISION NOT NULL,
            centroid_y DOUBLE PRECISION NOT NULL,
            area_m2 DOUBLE PRECISION NOT NULL,
            cell_count INTEGER NOT NULL,
            severity TEXT NOT NULL,
            detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL DEFAULT '',
            is_secret BOOLEAN NOT NULL DEFAULT FALSE,
            category TEXT NOT NULL DEFAULT 'general',
            description TEXT NOT NULL DEFAULT '',
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS settings_audit_log (
            id TEXT PRIMARY KEY,
            key TEXT NOT NULL,
            old_preview TEXT NOT NULL DEFAULT '',
            new_preview TEXT NOT NULL DEFAULT '',
            source_ip TEXT NOT NULL DEFAULT 'local',
            changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS vision_usage_log (
            id TEXT PRIMARY KEY,
            operation TEXT NOT NULL,
            model TEXT NOT NULL,
            latency_ms INTEGER NOT NULL DEFAULT 0,
            confidence DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            consensus_verified BOOLEAN NOT NULL DEFAULT FALSE,
            status TEXT NOT NULL DEFAULT 'ok',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
        with psycopg.connect(self.database_url) as conn:
            conn.execute(ddl)
            conn.commit()
        self._ensure_pool()
        if not self.list_spaces():
            self.create_space(
                name="Primary OT Control Room",
                facility="Eigenia Lab",
                description="Default scanned critical-infrastructure room",
            )

    def _serialize_row(self, row: dict[str, Any]) -> dict[str, Any]:
        out = dict(row)
        out.pop("spec_embedding", None)
        out.pop("data", None)
        for key in ("created_at", "updated_at", "detected_at", "changed_at"):
            if isinstance(out.get(key), datetime):
                out[key] = out[key].isoformat()
        return out

    def check_health(self) -> dict[str, Any]:
        """Query live PostgreSQL 18 version, pgvector extension version, and pool stats."""
        try:
            pool = self._ensure_pool()
            with pool.connection() as conn:
                vrow = conn.execute("SELECT version() AS pg_ver").fetchone()
                erow = conn.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'").fetchone()
            stats = pool.get_stats()
            return {
                "status": "connected",
                "backend": "PostgresTwinRepository",
                "postgres_version": (vrow or {}).get("pg_ver", "unknown"),
                "pgvector_version": (erow or {}).get("extversion", "missing"),
                "pool_size": stats.get("pool_size", 0),
                "pool_available": stats.get("pool_available", 0),
            }
        except Exception as exc:
            sys.stderr.write(f"[db] Health check failed: {exc}\n")
            return {"status": "unavailable", "backend": "PostgresTwinRepository", "error": str(exc)}

    def list_spaces(self) -> List[dict[str, Any]]:
        """List all spaces."""
        with self._ensure_pool().connection() as conn:
            rows = conn.execute("SELECT * FROM spaces ORDER BY created_at ASC").fetchall()
            return [self._serialize_row(r) for r in rows]

    def get_space(self, space_id: str) -> Optional[dict[str, Any]]:
        """Fetch one space by ID."""
        with self._ensure_pool().connection() as conn:
            row = conn.execute("SELECT * FROM spaces WHERE id = %s", (space_id,)).fetchone()
            return self._serialize_row(row) if row else None

    def create_space(self, name: str, facility: str = "Eigenia Facility", description: str = "") -> dict[str, Any]:
        """Insert a new space."""
        sid = str(uuid.uuid4())
        with self._ensure_pool().connection() as conn:
            row = conn.execute(
                "INSERT INTO spaces (id, name, facility, description) VALUES (%s, %s, %s, %s) RETURNING *",
                (sid, name, facility, description),
            ).fetchone()
            conn.commit()
            return self._serialize_row(row)

    def update_space(
        self,
        space_id: str,
        name: Optional[str] = None,
        facility: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Update mutable metadata fields on an existing space in PostgreSQL."""
        sets: List[str] = []
        params: List[Any] = []
        if name is not None and str(name).strip():
            sets.append("name = %s")
            params.append(str(name).strip())
        if facility is not None:
            sets.append("facility = %s")
            params.append(str(facility).strip())
        if description is not None:
            sets.append("description = %s")
            params.append(str(description).strip())
        if not sets:
            return self.get_space(space_id)
        sets.append("updated_at = NOW()")
        params.append(space_id)
        with self._ensure_pool().connection() as conn:
            row = conn.execute(
                f"UPDATE spaces SET {', '.join(sets)} WHERE id = %s RETURNING *",
                params,
            ).fetchone()
            conn.commit()
            return self._serialize_row(row) if row else None

    def delete_space(self, space_id: str) -> bool:
        """Delete a space and cascade its assets."""
        with self._ensure_pool().connection() as conn:
            cur = conn.execute("DELETE FROM spaces WHERE id = %s", (space_id,))
            conn.commit()
            return cur.rowcount > 0

    def save_walls(self, space_id: str, walls: List[dict[str, Any]], metrics: dict[str, Any]) -> dict[str, Any]:
        """Save RANSAC walls and metrics."""
        with self._ensure_pool().connection() as conn:
            row = conn.execute(
                "UPDATE spaces SET walls = %s::jsonb, metrics = %s::jsonb, updated_at = NOW() WHERE id = %s RETURNING *",
                (json.dumps(walls), json.dumps(metrics), space_id),
            ).fetchone()
            conn.commit()
            if not row:
                raise KeyError(f"Space {space_id} not found")
            return self._serialize_row(row)

    def save_zones(self, space_id: str, zones: List[dict[str, Any]]) -> List[dict[str, Any]]:
        """Save polygon zones."""
        with self._ensure_pool().connection() as conn:
            row = conn.execute(
                "UPDATE spaces SET zones = %s::jsonb, updated_at = NOW() WHERE id = %s RETURNING zones",
                (json.dumps(zones), space_id),
            ).fetchone()
            conn.commit()
            if not row:
                raise KeyError(f"Space {space_id} not found")
            return list(row["zones"])

    def create_equipment(
        self,
        space_id: str,
        asset: dict[str, Any],
        embedding: Optional[List[float]] = None,
        embedding_model: str = "fallback",
    ) -> dict[str, Any]:
        """Insert a placed equipment twin with halfvec embedding and optional file FK."""
        eid = asset.get("id") or str(uuid.uuid4())
        hv = HalfVector(embedding) if embedding else None
        with self._ensure_pool().connection() as conn:
            row = conn.execute(
                """
                INSERT INTO equipment_assets (
                    id, space_id, name, equipment_type, dexpi_class, manufacturer, model_number,
                    part_number, serial_number, inferred_cpe_23, voltage_rating, current_or_power,
                    certifications, asset_tags, mac_addresses, ip_or_hostname_labels, barcodes,
                    x, y, z, yaw_deg, width_m, depth_m, height_m, confidence, model_used,
                    image_file_id, image_url, embedding_model, enrichment, raw_notes, spec_embedding
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s::jsonb, %s, %s
                )
                RETURNING *
                """,
                (
                    eid,
                    space_id,
                    asset.get("name", "Unnamed Equipment"),
                    asset.get("equipment_type", "Industrial Equipment"),
                    asset.get("dexpi_class", "Equipment"),
                    asset.get("manufacturer", "Unknown"),
                    asset.get("model_number", "Unknown"),
                    asset.get("part_number"),
                    asset.get("serial_number"),
                    asset.get("inferred_cpe_23"),
                    asset.get("voltage_rating"),
                    asset.get("current_or_power"),
                    json.dumps(list(asset.get("certifications") or [])),
                    json.dumps(list(asset.get("asset_tags") or [])),
                    json.dumps(list(asset.get("mac_addresses") or [])),
                    json.dumps(list(asset.get("ip_or_hostname_labels") or [])),
                    json.dumps(list(asset.get("barcodes") or [])),
                    float(asset.get("x", 0.0)),
                    float(asset.get("y", 0.0)),
                    float(asset.get("z", 0.0)),
                    float(asset.get("yaw_deg", 0.0)),
                    float(asset.get("width_m", 0.7)),
                    float(asset.get("depth_m", 0.7)),
                    float(asset.get("height_m", 1.5)),
                    float(asset.get("confidence", 0.85)),
                    asset.get("model_used", "manual"),
                    asset.get("image_file_id"),
                    asset.get("image_url"),
                    embedding_model,
                    json.dumps(dict(asset.get("enrichment") or {})),
                    asset.get("raw_notes", ""),
                    hv,
                ),
            ).fetchone()
            conn.commit()
            return self._serialize_row(row)

    def get_equipment(self, equipment_id: str) -> Optional[dict[str, Any]]:
        """Fetch one equipment asset by ID."""
        with self._ensure_pool().connection() as conn:
            row = conn.execute("SELECT * FROM equipment_assets WHERE id = %s", (equipment_id,)).fetchone()
            return self._serialize_row(row) if row else None

    def list_equipment(self, space_id: Optional[str] = None) -> List[dict[str, Any]]:
        """List equipment rows."""
        with self._ensure_pool().connection() as conn:
            if space_id:
                rows = conn.execute(
                    "SELECT * FROM equipment_assets WHERE space_id = %s ORDER BY created_at DESC",
                    (space_id,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM equipment_assets ORDER BY created_at DESC").fetchall()
            return [self._serialize_row(r) for r in rows]

    def delete_equipment(self, equipment_id: str) -> bool:
        """Delete an equipment record."""
        with self._ensure_pool().connection() as conn:
            cur = conn.execute("DELETE FROM equipment_assets WHERE id = %s", (equipment_id,))
            conn.commit()
            return cur.rowcount > 0

    def update_equipment_enrichment(
        self,
        equipment_id: str,
        enrichment: dict[str, Any],
        updates: Optional[dict[str, Any]] = None,
        embedding: Optional[List[float]] = None,
        embedding_model: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Persist Pass-3 enrichment JSONB, refined 3D dimensions, CPE, and refreshed halfvec."""
        allowed = {"dexpi_class", "inferred_cpe_23", "voltage_rating", "width_m", "depth_m", "height_m"}
        set_parts = ["enrichment = %s::jsonb"]
        params: List[Any] = [json.dumps(enrichment)]
        for k, v in (updates or {}).items():
            if k in allowed and v is not None:
                set_parts.append(f"{k} = %s")
                params.append(v)
        if embedding:
            set_parts.append("spec_embedding = %s")
            params.append(HalfVector(embedding))
        if embedding_model:
            set_parts.append("embedding_model = %s")
            params.append(embedding_model)
        params.append(equipment_id)
        with self._ensure_pool().connection() as conn:
            row = conn.execute(
                f"UPDATE equipment_assets SET {', '.join(set_parts)} WHERE id = %s RETURNING *",
                tuple(params),
            ).fetchone()
            conn.commit()
            return self._serialize_row(row) if row else None

    def update_equipment_embedding(
        self,
        equipment_id: str,
        embedding: List[float],
        embedding_model: str,
    ) -> bool:
        """Re-index an asset's halfvec embedding."""
        with self._ensure_pool().connection() as conn:
            cur = conn.execute(
                "UPDATE equipment_assets SET spec_embedding = %s, embedding_model = %s WHERE id = %s",
                (HalfVector(embedding), embedding_model, equipment_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def record_anomalies(self, space_id: str, anomalies: List[dict[str, Any]]) -> List[dict[str, Any]]:
        """Persist physical change anomalies."""
        out: List[dict[str, Any]] = []
        with self._ensure_pool().connection() as conn:
            for a in anomalies:
                row = conn.execute(
                    """
                    INSERT INTO change_anomalies (
                        id, space_id, anomaly_type, centroid_x, centroid_y, area_m2, cell_count, severity
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING *
                    """,
                    (
                        str(uuid.uuid4()),
                        space_id,
                        a["anomaly_type"],
                        float(a["centroid_x"]),
                        float(a["centroid_y"]),
                        float(a["area_m2"]),
                        int(a["cell_count"]),
                        a["severity"],
                    ),
                ).fetchone()
                out.append(self._serialize_row(row))
            conn.commit()
        return out

    def list_anomalies(self, space_id: str) -> List[dict[str, Any]]:
        """List recent anomalies for a space."""
        with self._ensure_pool().connection() as conn:
            rows = conn.execute(
                "SELECT * FROM change_anomalies WHERE space_id = %s ORDER BY detected_at DESC LIMIT 50",
                (space_id,),
            ).fetchall()
            return [self._serialize_row(r) for r in rows]

    def search_equipment_semantic(
        self,
        query_embedding: List[float],
        limit: int = 8,
        space_id: Optional[str] = None,
        manufacturer: Optional[str] = None,
    ) -> List[dict[str, Any]]:
        """Execute pgvector halfvec HNSW iterative filtered semantic search."""
        hv = HalfVector(query_embedding)
        clauses = ["spec_embedding IS NOT NULL"]
        params: List[Any] = [hv]
        if space_id:
            clauses.append("space_id = %s")
            params.append(space_id)
        if manufacturer:
            clauses.append("LOWER(manufacturer) = LOWER(%s)")
            params.append(manufacturer)
        params.extend([hv, limit])

        with self._ensure_pool().connection() as conn:
            try:
                conn.execute("SET LOCAL hnsw.iterative_scan = 'relaxed_order'")
            except Exception as exc:
                sys.stderr.write(f"[pgvector] iterative_scan notice: {exc}\n")
            rows = conn.execute(
                f"""
                SELECT *, (1 - (spec_embedding <=> %s)) AS similarity
                FROM equipment_assets
                WHERE {' AND '.join(clauses)}
                ORDER BY spec_embedding <=> %s
                LIMIT %s
                """,
                tuple(params),
            ).fetchall()
            result: List[dict[str, Any]] = []
            for r in rows:
                item = self._serialize_row(r)
                item["similarity"] = round(float(item.get("similarity") or 0.0), 4)
                result.append(item)
            return result

    # --- Admin Settings & Audit ---
    def get_settings_raw(self) -> dict[str, str]:
        """Load and Fernet-decrypt persisted app_settings."""
        with self._ensure_pool().connection() as conn:
            rows = conn.execute("SELECT key, value, is_secret FROM app_settings").fetchall()
        out: dict[str, str] = {}
        for r in rows:
            out[r["key"]] = self._cipher.decrypt(r["value"]) if r["is_secret"] else r["value"]
        return out

    def list_settings_masked(self, defaults: dict[str, str]) -> List[dict[str, Any]]:
        """List all managed settings with secret values safely masked."""
        with self._ensure_pool().connection() as conn:
            rows = conn.execute("SELECT key, value, is_secret, updated_at FROM app_settings").fetchall()
        persisted_map = {r["key"]: r for r in rows}
        items: List[dict[str, Any]] = []
        for spec in MANAGED_SETTING_SPECS:
            key = spec["key"]
            is_secret = bool(spec["is_secret"])
            row = persisted_map.get(key)
            if row is not None:
                val = self._cipher.decrypt(row["value"]) if is_secret else row["value"]
                upd = row["updated_at"].isoformat() if isinstance(row["updated_at"], datetime) else row["updated_at"]
            else:
                val = defaults.get(key, "")
                upd = None
            is_set = bool(val and val != "your_openrouter_api_key_here")
            items.append(
                {
                    "key": key,
                    "value": mask_secret_value(val) if is_secret else (val or ""),
                    "is_secret": is_secret,
                    "is_set": is_set,
                    "persisted": row is not None,
                    "category": spec["category"],
                    "description": spec["description"],
                    "updated_at": upd,
                }
            )
        return items

    def upsert_settings(self, updates: dict[str, str], source_ip: str = "local") -> List[dict[str, Any]]:
        """Encrypt secrets with Fernet, upsert into app_settings, and write settings_audit_log."""
        existing = self.get_settings_raw()
        changed: List[dict[str, Any]] = []
        with self._ensure_pool().connection() as conn:
            for key, new_val in updates.items():
                spec = MANAGED_SPEC_BY_KEY.get(key, {"is_secret": "key" in key or "password" in key, "category": "custom", "description": ""})
                is_secret = bool(spec["is_secret"])
                if is_secret and "••••" in new_val:
                    continue
                old_raw = existing.get(key, "")
                stored_val = self._cipher.encrypt(new_val) if is_secret else new_val
                conn.execute(
                    """
                    INSERT INTO app_settings (key, value, is_secret, category, description, updated_at)
                    VALUES (%s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (key) DO UPDATE SET
                        value = EXCLUDED.value,
                        is_secret = EXCLUDED.is_secret,
                        category = EXCLUDED.category,
                        description = EXCLUDED.description,
                        updated_at = NOW()
                    """,
                    (key, stored_val, is_secret, spec["category"], spec["description"]),
                )
                aid = str(uuid.uuid4())
                arow = conn.execute(
                    """
                    INSERT INTO settings_audit_log (id, key, old_preview, new_preview, source_ip)
                    VALUES (%s, %s, %s, %s, %s) RETURNING *
                    """,
                    (
                        aid,
                        key,
                        mask_secret_value(old_raw) if is_secret else old_raw,
                        mask_secret_value(new_val) if is_secret else new_val,
                        source_ip,
                    ),
                ).fetchone()
                changed.append(self._serialize_row(arow))
            conn.commit()
        return changed

    def list_settings_audit(self, limit: int = 30) -> List[dict[str, Any]]:
        """Fetch recent configuration audit records."""
        with self._ensure_pool().connection() as conn:
            rows = conn.execute(
                "SELECT * FROM settings_audit_log ORDER BY changed_at DESC LIMIT %s",
                (limit,),
            ).fetchall()
            return [self._serialize_row(r) for r in rows]

    # --- Content-Addressed PostgreSQL File Storage ---
    def store_file(
        self,
        filename: str,
        content_type: str,
        data: bytes,
        category: str = "general",
        space_id: Optional[str] = None,
        equipment_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Deduplicate binary payload into file_blobs and create stored_files metadata row."""
        sha = hashlib.sha256(data).hexdigest()
        fid = str(uuid.uuid4())
        with self._ensure_pool().connection() as conn:
            exists = conn.execute("SELECT 1 FROM file_blobs WHERE sha256 = %s", (sha,)).fetchone()
            deduplicated = exists is not None
            if not deduplicated:
                conn.execute(
                    "INSERT INTO file_blobs (sha256, size_bytes, data) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                    (sha, len(data), data),
                )
            row = conn.execute(
                """
                INSERT INTO stored_files (id, filename, content_type, size_bytes, sha256, category, space_id, equipment_id, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb) RETURNING *
                """,
                (fid, filename, content_type, len(data), sha, category, space_id, equipment_id, json.dumps(metadata or {})),
            ).fetchone()
            conn.commit()
        out = self._serialize_row(row)
        out["deduplicated"] = deduplicated
        out["url"] = f"/api/files/{fid}"
        return out

    def list_files(
        self,
        category: Optional[str] = None,
        space_id: Optional[str] = None,
        equipment_id: Optional[str] = None,
    ) -> List[dict[str, Any]]:
        """List stored file metadata without loading BYTEA payloads."""
        clauses: List[str] = []
        params: List[Any] = []
        if category:
            clauses.append("category = %s")
            params.append(category)
        if space_id:
            clauses.append("space_id = %s")
            params.append(space_id)
        if equipment_id:
            clauses.append("equipment_id = %s")
            params.append(equipment_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._ensure_pool().connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM stored_files {where} ORDER BY created_at DESC LIMIT 200",
                tuple(params),
            ).fetchall()
        out = []
        for r in rows:
            item = self._serialize_row(r)
            item["url"] = f"/api/files/{item['id']}"
            out.append(item)
        return out

    def get_file_meta(self, file_id: str) -> Optional[dict[str, Any]]:
        """Fetch file metadata."""
        with self._ensure_pool().connection() as conn:
            row = conn.execute("SELECT * FROM stored_files WHERE id = %s", (file_id,)).fetchone()
        if not row:
            return None
        out = self._serialize_row(row)
        out["url"] = f"/api/files/{out['id']}"
        return out

    def get_file_with_bytes(self, file_id: str) -> Optional[Tuple[dict[str, Any], bytes]]:
        """Fetch file metadata joined with its BYTEA payload from file_blobs."""
        with self._ensure_pool().connection() as conn:
            row = conn.execute(
                """
                SELECT sf.*, fb.data
                FROM stored_files sf
                JOIN file_blobs fb ON sf.sha256 = fb.sha256
                WHERE sf.id = %s
                """,
                (file_id,),
            ).fetchone()
        if not row:
            return None
        raw_bytes = bytes(row["data"])
        meta = self._serialize_row(row)
        meta["url"] = f"/api/files/{meta['id']}"
        return meta, raw_bytes

    def delete_file(self, file_id: str) -> bool:
        """Delete a stored_files entry and prune its blob if no longer referenced."""
        with self._ensure_pool().connection() as conn:
            row = conn.execute("DELETE FROM stored_files WHERE id = %s RETURNING sha256", (file_id,)).fetchone()
            if not row:
                return False
            conn.execute(
                "DELETE FROM file_blobs WHERE sha256 = %s AND NOT EXISTS (SELECT 1 FROM stored_files WHERE sha256 = %s)",
                (row["sha256"], row["sha256"]),
            )
            conn.commit()
            return True

    def storage_stats(self) -> dict[str, Any]:
        """Compute logical vs deduplicated PostgreSQL blob storage stats."""
        with self._ensure_pool().connection() as conn:
            f_row = conn.execute("SELECT COUNT(*) AS cnt, COALESCE(SUM(size_bytes), 0) AS total FROM stored_files").fetchone()
            b_row = conn.execute("SELECT COUNT(*) AS cnt, COALESCE(SUM(size_bytes), 0) AS total FROM file_blobs").fetchone()
        logical = int((f_row or {}).get("total", 0))
        physical = int((b_row or {}).get("total", 0))
        return {
            "file_count": int((f_row or {}).get("cnt", 0)),
            "unique_blob_count": int((b_row or {}).get("cnt", 0)),
            "logical_bytes": logical,
            "physical_bytes": physical,
            "dedup_savings_bytes": max(0, logical - physical),
        }

    def verify_and_scrub_storage(self) -> dict[str, Any]:
        """Verify SHA-256 integrity of every file_blob and delete unreferenced orphans."""
        with self._ensure_pool().connection() as conn:
            cur = conn.execute(
                "DELETE FROM file_blobs fb WHERE NOT EXISTS (SELECT 1 FROM stored_files sf WHERE sf.sha256 = fb.sha256)"
            )
            pruned = cur.rowcount
            rows = conn.execute("SELECT sha256, data FROM file_blobs").fetchall()
            conn.commit()
        corrupted = sum(1 for r in rows if hashlib.sha256(bytes(r["data"])).hexdigest() != r["sha256"])
        return {
            "verified_blobs": len(rows) - corrupted,
            "corrupted_blobs": corrupted,
            "pruned_orphans": pruned,
        }

    # --- Vision Telemetry ---
    def log_vision_usage(self, entry: dict[str, Any]) -> dict[str, Any]:
        """Insert a vision/research telemetry record."""
        uid = str(uuid.uuid4())
        with self._ensure_pool().connection() as conn:
            row = conn.execute(
                """
                INSERT INTO vision_usage_log (id, operation, model, latency_ms, confidence, consensus_verified, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *
                """,
                (
                    uid,
                    str(entry.get("operation", "vision")),
                    str(entry.get("model", "unknown")),
                    int(entry.get("latency_ms", 0)),
                    float(entry.get("confidence", 0.0)),
                    bool(entry.get("consensus_verified", False)),
                    str(entry.get("status", "ok")),
                ),
            ).fetchone()
            conn.commit()
            return self._serialize_row(row)

    def list_vision_usage(self, limit: int = 30) -> List[dict[str, Any]]:
        """List recent vision/research inference metrics."""
        with self._ensure_pool().connection() as conn:
            rows = conn.execute(
                "SELECT * FROM vision_usage_log ORDER BY created_at DESC LIMIT %s",
                (limit,),
            ).fetchall()
            return [self._serialize_row(r) for r in rows]
