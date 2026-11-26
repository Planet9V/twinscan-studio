"""PostgreSQL 18 + pgvector and in-memory store for Known People, Face Embeddings, Patrol Routes, and Voice Logs.

Implements ``RobotAiStoreProtocol``, ``InMemoryRobotAiStore``, and ``PostgresRobotAiStore``
managing four normalized tables:
- ``known_people``
- ``face_embeddings`` (128-D SFace cosine similarity via ``pgvector`` ``vector(128)``)
- ``patrol_routes``
- ``voice_interaction_logs``
"""

from __future__ import annotations

import json
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Protocol, Sequence

import numpy as np
import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


class RobotAiStoreProtocol(Protocol):
    """Unified storage interface for Face Recognition Registry, Patrol Routes, and Voice Logs."""

    def initialize(self) -> None:
        """Create required database tables and extensions."""
        ...

    def close(self) -> None:
        """Release underlying connection pools."""
        ...

    def create_person(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Register a new known person for face recognition."""
        ...

    def list_people(self) -> List[Dict[str, Any]]:
        """List all known people with their stored embedding counts."""
        ...

    def get_person(self, person_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single known person by ID."""
        ...

    def update_person(self, person_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update profile fields on a known person."""
        ...

    def delete_person(self, person_id: str) -> bool:
        """Delete a known person and cascade-remove all stored face embeddings."""
        ...

    def touch_person_seen(self, person_id: str) -> None:
        """Update ``last_seen_at`` timestamp for a recognized person."""
        ...

    def add_face_embedding(
        self,
        person_id: str,
        embedding: Sequence[float],
        source_file_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Store a normalized 128-D face embedding linked to ``person_id``."""
        ...

    def match_face_embedding(
        self,
        embedding: Sequence[float],
        threshold: float = 0.363,
    ) -> Optional[Dict[str, Any]]:
        """Find the closest enrolled person above cosine similarity ``threshold``."""
        ...

    def create_patrol_route(self, robot_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Save a named multi-waypoint patrol route for a robot."""
        ...

    def list_patrol_routes(self, robot_id: str) -> List[Dict[str, Any]]:
        """List saved patrol routes for ``robot_id``."""
        ...

    def get_patrol_route(self, route_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a single patrol route by ID."""
        ...

    def delete_patrol_route(self, route_id: str) -> bool:
        """Delete a patrol route by ID."""
        ...

    def record_voice_log(
        self,
        robot_id: str,
        direction: str,
        transcript: str,
        action_taken: str = "",
        reply_text: str = "",
    ) -> Dict[str, Any]:
        """Record a voice command, TTS utterance, or wake-word event."""
        ...

    def list_voice_logs(self, robot_id: str, limit: int = 30) -> List[Dict[str, Any]]:
        """Return recent voice interaction logs for ``robot_id`` ordered newest first."""
        ...

    def get_voice_config(self, robot_id: str) -> Dict[str, Any]:
        """Return per-robot conversational voice assistant config (with defaults)."""
        ...

    def upsert_voice_config(self, robot_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Create or update per-robot conversational voice assistant config."""
        ...

    def list_personalities(self) -> List[Dict[str, Any]]:
        """List all built-in and custom voice assistant personalities."""
        ...

    def get_personality(self, personality_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single personality by ID."""
        ...

    def create_personality(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new custom voice assistant personality."""
        ...

    def update_personality(self, personality_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update an existing personality."""
        ...

    def delete_personality(self, personality_id: str) -> bool:
        """Delete a custom personality (refuses deleting built-in personalities)."""
        ...

    def record_conversation_turn(self, robot_id: str, turn: Dict[str, Any]) -> Dict[str, Any]:
        """Record a user or assistant conversation turn for ``robot_id``."""
        ...

    def list_conversation_turns(self, robot_id: str, limit: int = 30) -> List[Dict[str, Any]]:
        """Return recent conversation turns for ``robot_id`` ordered oldest-first."""
        ...

    def clear_conversation_turns(self, robot_id: str) -> int:
        """Delete all conversation history turns for ``robot_id`` and return count removed."""
        ...

    def record_spatial_sighting(self, robot_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Record a semantic spatial sighting (object, animal, or person) with coordinates and snapshot."""
        ...

    def list_spatial_sightings(
        self,
        query: Optional[str] = None,
        limit: int = 200,
        robot_id: Optional[str] = None,
        status: str = "active",
        kind: Optional[str] = None,
        space_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List recent spatial sightings optionally filtered by query, lifecycle status, kind, and space."""
        ...

    def get_spatial_sighting(self, sighting_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single spatial sighting by ID."""
        ...

    def update_spatial_sighting(self, sighting_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update mutable fields (label, kind, notes, tags, archived, space_id) on a spatial sighting."""
        ...

    def bulk_update_spatial_sightings(self, action: str, ids: Sequence[str]) -> int:
        """Apply bulk ``archive``, ``retrieve``, or ``delete`` across spatial sighting IDs."""
        ...

    def count_spatial_sightings(
        self,
        space_id: Optional[str] = None,
        kind: Optional[str] = None,
        query: Optional[str] = None,
    ) -> Dict[str, int]:
        """Return ``{active, archived, total}`` counts for spatial sightings."""
        ...

    def delete_spatial_sighting(self, sighting_id: str) -> bool:
        """Delete a stored spatial sighting by ID."""
        ...

    def record_sentry_event(self, robot_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Record an autonomous sentry security alert event."""
        ...

    def list_sentry_events(self, robot_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """List recent sentry alert events for ``robot_id`` ordered newest first."""
        ...

    def clear_sentry_events(self, robot_id: str) -> int:
        """Clear all sentry alert events for ``robot_id`` and return count removed."""
        ...

    def save_scene_panel(self, panel: Dict[str, Any]) -> Dict[str, Any]:
        """Persist a reconstructed 3D real-room scene panel record."""
        ...

    def list_scene_panels(self, space_id: str) -> List[Dict[str, Any]]:
        """List all reconstructed 3D scene panels belonging to ``space_id`` ordered oldest first."""
        ...

    def get_scene_panel(self, panel_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single reconstructed 3D scene panel by ID."""
        ...

    def delete_scene_panel(self, panel_id: str) -> bool:
        """Delete a reconstructed 3D scene panel by ID."""
        ...

    def clear_scene_panels(self, space_id: str) -> int:
        """Delete all reconstructed 3D scene panels for ``space_id`` and return count removed."""
        ...

    def list_inventory_items(
        self,
        status: Optional[str] = None,
        category: Optional[str] = None,
        query: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List lab hardware inventory items with optional status, category, and search filters."""
        ...

    def get_inventory_item(self, item_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single lab hardware inventory item by ID."""
        ...

    def create_inventory_item(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create and persist a new lab hardware inventory item."""
        ...

    def update_inventory_item(self, item_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update mutable fields on a lab hardware inventory item."""
        ...

    def delete_inventory_item(self, item_id: str) -> bool:
        """Delete a lab hardware inventory item by ID."""
        ...

    def count_inventory_items(self) -> Dict[str, int]:
        """Return ``{owned, wishlist, deployed, total}`` summary counts for inventory."""
        ...

    def list_managed_devices(
        self,
        profile_id: Optional[str] = None,
        space_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List registered non-robot IoT/camera/microcontroller devices."""
        ...

    def get_managed_device(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single managed device by ID."""
        ...

    def create_managed_device(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Register a new managed device."""
        ...

    def update_managed_device(self, device_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update fields on an existing managed device."""
        ...

    def delete_managed_device(self, device_id: str) -> bool:
        """Delete a managed device by ID."""
        ...

    def save_design_blueprint(self, blueprint: Dict[str, Any]) -> Dict[str, Any]:
        """Insert or update a Co-Design Architect blueprint record."""
        ...

    def list_design_blueprints(self, limit: int = 50) -> List[Dict[str, Any]]:
        """List saved Co-Design Architect blueprints ordered newest updated first."""
        ...

    def get_design_blueprint(self, blueprint_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single Co-Design Architect blueprint by ID."""
        ...

    def delete_design_blueprint(self, blueprint_id: str) -> bool:
        """Delete a Co-Design Architect blueprint by ID."""
        ...

    def list_early_bird_signups(self, limit: int = 50) -> List[Dict[str, Any]]:
        """List anonymized Early Bird Maker signups ordered newest spot first."""
        ...

    def claim_early_bird_spot(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Claim a sequential Early Bird Maker spot (capped at 50, unique email)."""
        ...

    def get_early_bird_status(self) -> Dict[str, Any]:
        """Return Early Bird campaign status, remaining spots, perks, and anonymized recent makers."""
        ...


EARLY_BIRD_MAX_SPOTS = 50

EARLY_BIRD_PERKS: List[str] = [
    "Lifetime Founding Maker badge (EIGENIA-MAKER-01..50) & priority community spotlight",
    "Direct 1-on-1 PuppyPi Pro / Pi 5 / LD19 setup office hours with core engineers",
    "Early access to multi-robot swarm telemetry & new Universal Hardware Envelopes",
    "Priority custom 3D hardware profile requests (ESP32, Jetson, OAK-D, micro:bit add-ons)",
    "Free Founding Maker access to upcoming offline vision model packs & 3D export plugins",
    "Direct vote on the Eigenia TwinScan hardware & ROS 2 feature roadmap",
]


def _anonymize_maker_name(name: str) -> str:
    """Convert a full name into a privacy-safe display label (e.g. ``'Alex Mercer'`` -> ``'Alex M.'``)."""
    parts = [p for p in str(name or "").strip().split() if p]
    if not parts:
        return "Maker"
    if len(parts) == 1:
        return parts[0][:24]
    return f"{parts[0][:24]} {parts[-1][0].upper()}."


def _normalize_hardware_stack(raw: Any) -> List[str]:
    if isinstance(raw, str):
        items = [x.strip() for x in raw.split(",") if x.strip()]
    elif isinstance(raw, list):
        items = [str(x).strip() for x in raw if str(x).strip()]
    else:
        items = []
    return items[:12]


def _default_voice_config(robot_id: str) -> Dict[str, Any]:
    """Build default per-robot conversational assistant configuration."""
    return {
        "robot_id": robot_id,
        "assistant_name": "OX",
        "wake_word": "Hey OX",
        "wake_aliases": ["hey ox", "hey aux", "hey o x", "hey box", "hey fox"],
        "wake_mode": "custom_software",
        "default_engine": "piper_tts",
        "default_voice": "en_US-lessac-medium",
        "default_speed": 155,
        "anti_clip": True,
        "followup_window_sec": 12,
        "personality_id": "dog",
        "llm_model": "google/gemini-2.5-flash",
        "attach_camera_on_visual": True,
        "allow_body_actions": True,
        "updated_at": None,
    }


def _builtin_personalities_seed() -> List[Dict[str, Any]]:
    from src.robot.conversation_engine import BUILTIN_PERSONALITIES

    return [dict(p) for p in BUILTIN_PERSONALITIES]


def _normalize_vec128(embedding: Sequence[float]) -> np.ndarray:
    """Pad/truncate and L2-normalize a 128-D face embedding vector."""
    arr = np.asarray(list(embedding), dtype=np.float32).flatten()
    if arr.size < 128:
        arr = np.pad(arr, (0, 128 - arr.size))
    elif arr.size > 128:
        arr = arr[:128]
    norm = float(np.linalg.norm(arr))
    if norm > 1e-8:
        arr = arr / norm
    return arr


def _format_person(row: Dict[str, Any], embedding_count: int = 0) -> Dict[str, Any]:
    out = dict(row)
    for k in ("last_seen_at", "created_at", "updated_at"):
        if isinstance(out.get(k), datetime):
            out[k] = out[k].isoformat()
    avatar_id = out.get("avatar_file_id")
    out["avatar_url"] = f"/api/files/{avatar_id}" if avatar_id else None
    out["embedding_count"] = int(out.get("embedding_count", embedding_count))
    return out


class InMemoryRobotAiStore:
    """In-memory Robot AI store matching PostgreSQL 18 + pgvector semantics for pytest."""

    def __init__(self) -> None:
        """Initialize empty in-memory tables and seed built-in personalities."""
        self._people: Dict[str, Dict[str, Any]] = {}
        self._embeddings: List[Dict[str, Any]] = []
        self._routes: Dict[str, Dict[str, Any]] = {}
        self._voice_logs: Dict[str, List[Dict[str, Any]]] = {}
        self._voice_configs: Dict[str, Dict[str, Any]] = {}
        self._personalities: Dict[str, Dict[str, Any]] = {}
        self._conversation_turns: Dict[str, List[Dict[str, Any]]] = {}
        self._spatial_sightings: Dict[str, Dict[str, Any]] = {}
        self._sentry_events: Dict[str, List[Dict[str, Any]]] = {}
        self._scene_panels: Dict[str, Dict[str, Any]] = {}
        self._inventory_items: Dict[str, Dict[str, Any]] = {}
        self._managed_devices: Dict[str, Dict[str, Any]] = {}
        self._design_blueprints: Dict[str, Dict[str, Any]] = {}
        self._early_bird_signups: List[Dict[str, Any]] = []
        self._seed_builtins()

    def _seed_builtins(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        for p in _builtin_personalities_seed():
            if p["id"] not in self._personalities:
                self._personalities[p["id"]] = {**p, "created_at": now, "updated_at": now}

    def initialize(self) -> None:
        """Ensure built-in personalities are seeded."""
        self._seed_builtins()
        return None

    def close(self) -> None:
        """No-op close for in-memory store."""
        return None

    def create_person(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Register a new known person."""
        now = datetime.now(timezone.utc).isoformat()
        pid = str(data.get("id") or uuid.uuid4())
        name = str(data.get("name") or "").strip()
        if not name:
            raise ValueError("Person name is required")
        rec = {
            "id": pid,
            "name": name,
            "role": str(data.get("role") or "Operator"),
            "greeting_phrase": str(data.get("greeting_phrase") or f"Hello {name}!"),
            "greet_action": str(data.get("greet_action") or "none"),
            "auto_speak": bool(data.get("auto_speak", True)),
            "avatar_file_id": data.get("avatar_file_id"),
            "notes": str(data.get("notes") or ""),
            "last_seen_at": None,
            "created_at": now,
            "updated_at": now,
        }
        self._people[pid] = rec
        return _format_person(rec, embedding_count=0)

    def _count_embeddings(self, person_id: str) -> int:
        return sum(1 for e in self._embeddings if e["person_id"] == person_id)

    def list_people(self) -> List[Dict[str, Any]]:
        """List all enrolled people sorted by name."""
        rows = sorted(self._people.values(), key=lambda p: p["name"].lower())
        return [_format_person(r, embedding_count=self._count_embeddings(r["id"])) for r in rows]

    def get_person(self, person_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a known person by ID."""
        rec = self._people.get(person_id)
        return _format_person(rec, embedding_count=self._count_embeddings(person_id)) if rec else None

    def update_person(self, person_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update editable profile fields on a known person."""
        rec = self._people.get(person_id)
        if not rec:
            return None
        for key in ("name", "role", "greeting_phrase", "greet_action", "auto_speak", "avatar_file_id", "notes"):
            if key in updates and updates[key] is not None:
                rec[key] = updates[key]
        rec["updated_at"] = datetime.now(timezone.utc).isoformat()
        return _format_person(rec, embedding_count=self._count_embeddings(person_id))

    def delete_person(self, person_id: str) -> bool:
        """Delete a known person and all of their face embeddings."""
        removed = self._people.pop(person_id, None)
        if not removed:
            return False
        self._embeddings = [e for e in self._embeddings if e["person_id"] != person_id]
        return True

    def touch_person_seen(self, person_id: str) -> None:
        """Update ``last_seen_at`` for a recognized person."""
        rec = self._people.get(person_id)
        if rec:
            rec["last_seen_at"] = datetime.now(timezone.utc).isoformat()

    def add_face_embedding(
        self,
        person_id: str,
        embedding: Sequence[float],
        source_file_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Store a normalized 128-D face embedding for ``person_id``."""
        if person_id not in self._people:
            raise KeyError(f"Person {person_id} not found")
        vec = _normalize_vec128(embedding)
        eid = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        rec = {
            "id": eid,
            "person_id": person_id,
            "embedding": vec,
            "source_file_id": source_file_id,
            "created_at": now,
        }
        self._embeddings.append(rec)
        return {"id": eid, "person_id": person_id, "source_file_id": source_file_id, "created_at": now}

    def match_face_embedding(
        self,
        embedding: Sequence[float],
        threshold: float = 0.363,
    ) -> Optional[Dict[str, Any]]:
        """Find best cosine-similarity match across all enrolled face embeddings."""
        if not self._embeddings:
            return None
        q = _normalize_vec128(embedding)
        best_sim = -1.0
        best_pid: Optional[str] = None
        for entry in self._embeddings:
            sim = float(np.dot(q, entry["embedding"]))
            if sim > best_sim:
                best_sim = sim
                best_pid = entry["person_id"]
        if best_pid is None or best_sim < threshold:
            return None
        person = self.get_person(best_pid)
        if not person:
            return None
        return {"person": person, "similarity": round(best_sim, 4)}

    def create_patrol_route(self, robot_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Save a named patrol route."""
        now = datetime.now(timezone.utc).isoformat()
        rid = str(data.get("id") or uuid.uuid4())
        name = str(data.get("name") or "").strip() or f"Route {rid[:6]}"
        rec = {
            "id": rid,
            "robot_id": robot_id,
            "space_id": data.get("space_id"),
            "name": name,
            "waypoints": list(data.get("waypoints") or []),
            "loop_enabled": bool(data.get("loop_enabled", True)),
            "max_speed_cms": float(data.get("max_speed_cms", 12.0)),
            "obstacle_clearance_m": float(data.get("obstacle_clearance_m", 0.45)),
            "created_at": now,
            "updated_at": now,
        }
        self._routes[rid] = rec
        return dict(rec)

    def list_patrol_routes(self, robot_id: str) -> List[Dict[str, Any]]:
        """List saved patrol routes for a robot."""
        items = [dict(r) for r in self._routes.values() if r["robot_id"] == robot_id]
        items.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
        return items

    def get_patrol_route(self, route_id: str) -> Optional[Dict[str, Any]]:
        """Return one patrol route by ID."""
        rec = self._routes.get(route_id)
        return dict(rec) if rec else None

    def delete_patrol_route(self, route_id: str) -> bool:
        """Delete a patrol route by ID."""
        return self._routes.pop(route_id, None) is not None

    def record_voice_log(
        self,
        robot_id: str,
        direction: str,
        transcript: str,
        action_taken: str = "",
        reply_text: str = "",
    ) -> Dict[str, Any]:
        """Append a voice interaction log entry."""
        rec = {
            "id": str(uuid.uuid4()),
            "robot_id": robot_id,
            "direction": str(direction or "in"),
            "transcript": str(transcript or ""),
            "action_taken": str(action_taken or ""),
            "reply_text": str(reply_text or ""),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._voice_logs.setdefault(robot_id, []).insert(0, rec)
        return dict(rec)

    def list_voice_logs(self, robot_id: str, limit: int = 30) -> List[Dict[str, Any]]:
        """Return recent voice interaction logs for ``robot_id``."""
        return [dict(v) for v in self._voice_logs.get(robot_id, [])[: max(1, int(limit))]]

    def get_voice_config(self, robot_id: str) -> Dict[str, Any]:
        """Return per-robot conversational voice config (falling back to defaults)."""
        cur = self._voice_configs.get(robot_id)
        if not cur:
            return _default_voice_config(robot_id)
        return {**cur, "wake_aliases": list(cur.get("wake_aliases") or [])}

    def upsert_voice_config(self, robot_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Merge updates into per-robot conversational voice config."""
        cfg = self.get_voice_config(robot_id)
        for key in (
            "assistant_name",
            "wake_word",
            "wake_mode",
            "default_engine",
            "default_voice",
            "llm_model",
            "personality_id",
        ):
            if key in updates and updates[key] is not None:
                cfg[key] = str(updates[key]).strip() or cfg[key]
        if "wake_aliases" in updates and updates["wake_aliases"] is not None:
            cfg["wake_aliases"] = [str(a).strip() for a in updates["wake_aliases"] if str(a).strip()]
        if "default_speed" in updates and updates["default_speed"] is not None:
            cfg["default_speed"] = max(80, min(320, int(updates["default_speed"])))
        if "followup_window_sec" in updates and updates["followup_window_sec"] is not None:
            cfg["followup_window_sec"] = max(0, min(60, int(updates["followup_window_sec"])))
        for bkey in ("anti_clip", "attach_camera_on_visual", "allow_body_actions"):
            if bkey in updates and updates[bkey] is not None:
                cfg[bkey] = bool(updates[bkey])
        cfg["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._voice_configs[robot_id] = cfg
        return self.get_voice_config(robot_id)

    def list_personalities(self) -> List[Dict[str, Any]]:
        """List all built-in and custom voice personalities."""
        self._seed_builtins()
        items = [dict(p) for p in self._personalities.values()]
        items.sort(key=lambda p: (not bool(p.get("is_builtin")), str(p.get("name") or "").lower()))
        return items

    def get_personality(self, personality_id: str) -> Optional[Dict[str, Any]]:
        """Return a single personality by ID."""
        self._seed_builtins()
        rec = self._personalities.get(personality_id)
        return dict(rec) if rec else None

    def create_personality(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new custom personality."""
        name = str(data.get("name") or "").strip()
        prompt = str(data.get("system_prompt") or "").strip()
        if not name:
            raise ValueError("Personality name is required")
        if not prompt:
            raise ValueError("Personality system_prompt is required")
        now = datetime.now(timezone.utc).isoformat()
        pid = str(data.get("id") or f"custom-{uuid.uuid4().hex[:8]}")
        rec = {
            "id": pid,
            "name": name,
            "badge": str(data.get("badge") or "CUSTOM").strip()[:16].upper(),
            "description": str(data.get("description") or "").strip(),
            "system_prompt": prompt,
            "default_voice": str(data.get("default_voice") or "en_US-lessac-medium").strip(),
            "allow_body_actions": bool(data.get("allow_body_actions", True)),
            "is_builtin": False,
            "created_at": now,
            "updated_at": now,
        }
        self._personalities[pid] = rec
        return dict(rec)

    def update_personality(self, personality_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update editable fields on an existing personality."""
        rec = self._personalities.get(personality_id)
        if not rec:
            return None
        for key in ("name", "badge", "description", "system_prompt", "default_voice"):
            if key in data and data[key] is not None:
                val = str(data[key]).strip()
                if val or key == "description":
                    rec[key] = val.upper()[:16] if key == "badge" else val
        if "allow_body_actions" in data and data["allow_body_actions"] is not None:
            rec["allow_body_actions"] = bool(data["allow_body_actions"])
        rec["updated_at"] = datetime.now(timezone.utc).isoformat()
        return dict(rec)

    def delete_personality(self, personality_id: str) -> bool:
        """Delete a custom personality; raises ``ValueError`` for built-in personalities."""
        rec = self._personalities.get(personality_id)
        if not rec:
            return False
        if rec.get("is_builtin"):
            raise ValueError(f"Built-in personality {personality_id!r} cannot be deleted.")
        del self._personalities[personality_id]
        return True

    def record_conversation_turn(self, robot_id: str, turn: Dict[str, Any]) -> Dict[str, Any]:
        """Append a conversation turn for ``robot_id``."""
        rec = {
            "id": str(turn.get("id") or uuid.uuid4()),
            "robot_id": robot_id,
            "role": str(turn.get("role") or "user"),
            "content": str(turn.get("content") or ""),
            "personality_id": turn.get("personality_id"),
            "action_taken": turn.get("action_taken"),
            "rgb_applied": list(turn["rgb_applied"]) if turn.get("rgb_applied") else None,
            "camera_attached": bool(turn.get("camera_attached", False)),
            "engine_used": turn.get("engine_used"),
            "latency_ms": int(turn["latency_ms"]) if turn.get("latency_ms") is not None else None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._conversation_turns.setdefault(robot_id, []).append(rec)
        return dict(rec)

    def list_conversation_turns(self, robot_id: str, limit: int = 30) -> List[Dict[str, Any]]:
        """Return recent conversation turns for ``robot_id`` ordered oldest-first."""
        turns = self._conversation_turns.get(robot_id, [])
        n = max(1, int(limit))
        return [dict(t) for t in turns[-n:]]

    def clear_conversation_turns(self, robot_id: str) -> int:
        """Clear all stored conversation turns for ``robot_id``."""
        removed = len(self._conversation_turns.get(robot_id, []))
        self._conversation_turns[robot_id] = []
        return removed

    def record_spatial_sighting(self, robot_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Store a semantic spatial sighting in memory."""
        sid = str(data.get("id") or uuid.uuid4())
        snap_id = data.get("snapshot_file_id")
        archived = bool(data.get("archived", False))
        archived_at = data.get("archived_at") or (datetime.now(timezone.utc).isoformat() if archived else None)
        raw_tags = data.get("tags") or []
        tags = [str(t).strip() for t in raw_tags if str(t).strip()] if isinstance(raw_tags, list) else []
        rec = {
            "id": sid,
            "robot_id": robot_id,
            "space_id": data.get("space_id"),
            "label": str(data.get("label") or "object").strip(),
            "kind": str(data.get("kind") or "object").strip(),
            "x_m": round(float(data.get("x_m", 0.0)), 3),
            "y_m": round(float(data.get("y_m", 0.0)), 3),
            "confidence": round(float(data.get("confidence", 0.5)), 3),
            "snapshot_file_id": snap_id,
            "snapshot_url": f"/api/files/{snap_id}" if snap_id else None,
            "notes": str(data.get("notes") or ""),
            "seen_at": str(data.get("seen_at") or datetime.now(timezone.utc).isoformat()),
            "archived": archived,
            "archived_at": archived_at,
            "camera_source": str(data.get("camera_source") or "puppypi_fpv").strip() or "puppypi_fpv",
            "tags": tags,
        }
        self._spatial_sightings[sid] = rec
        return dict(rec)

    @staticmethod
    def _matches_sighting_filters(
        s: Dict[str, Any],
        *,
        q: str,
        robot_id: Optional[str],
        kind: Optional[str],
        space_id: Optional[str],
    ) -> bool:
        if robot_id and s["robot_id"] != robot_id:
            return False
        if space_id and s.get("space_id") != space_id:
            return False
        if kind and kind.strip().lower() not in {"all", ""}:
            if str(s.get("kind") or "").lower() != kind.strip().lower():
                return False
        if q:
            tags_text = " ".join(str(t).lower() for t in (s.get("tags") or []))
            if not (
                q in str(s.get("label") or "").lower()
                or q in str(s.get("kind") or "").lower()
                or q in str(s.get("notes") or "").lower()
                or q in str(s.get("camera_source") or "").lower()
                or q in tags_text
            ):
                return False
        return True

    def list_spatial_sightings(
        self,
        query: Optional[str] = None,
        limit: int = 200,
        robot_id: Optional[str] = None,
        status: str = "active",
        kind: Optional[str] = None,
        space_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List recent spatial sightings optionally filtered by keyword, lifecycle status, kind, and space."""
        q = (query or "").strip().lower()
        st = (status or "active").strip().lower()
        items = [
            s
            for s in self._spatial_sightings.values()
            if self._matches_sighting_filters(s, q=q, robot_id=robot_id, kind=kind, space_id=space_id)
            and (
                st == "all"
                or (st == "archived" and bool(s.get("archived", False)))
                or (st != "archived" and not bool(s.get("archived", False)))
            )
        ]
        items.sort(key=lambda s: str(s.get("seen_at") or ""), reverse=True)
        return [dict(s) for s in items[: max(1, int(limit))]]

    def get_spatial_sighting(self, sighting_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single spatial sighting by ID from memory."""
        found = self._spatial_sightings.get(sighting_id)
        return dict(found) if found else None

    def update_spatial_sighting(self, sighting_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update mutable fields on a spatial sighting in memory."""
        rec = self._spatial_sightings.get(sighting_id)
        if not rec:
            return None
        if "label" in updates and updates["label"] is not None:
            cleaned = str(updates["label"]).strip()
            if cleaned:
                rec["label"] = cleaned
        if "kind" in updates and updates["kind"] is not None:
            cleaned_k = str(updates["kind"]).strip().lower()
            if cleaned_k:
                rec["kind"] = cleaned_k
        if "notes" in updates and updates["notes"] is not None:
            rec["notes"] = str(updates["notes"])
        if "tags" in updates and updates["tags"] is not None:
            raw_tags = updates["tags"]
            rec["tags"] = [str(t).strip() for t in raw_tags if str(t).strip()] if isinstance(raw_tags, list) else []
        if "space_id" in updates:
            rec["space_id"] = updates["space_id"]
        if "camera_source" in updates and updates["camera_source"] is not None:
            rec["camera_source"] = str(updates["camera_source"]).strip() or "puppypi_fpv"
        if "archived" in updates and updates["archived"] is not None:
            next_arch = bool(updates["archived"])
            rec["archived"] = next_arch
            rec["archived_at"] = datetime.now(timezone.utc).isoformat() if next_arch else None
        return dict(rec)

    def bulk_update_spatial_sightings(self, action: str, ids: Sequence[str]) -> int:
        """Apply bulk ``archive``, ``retrieve``, or ``delete`` across spatial sighting IDs in memory."""
        act = str(action or "").strip().lower()
        affected = 0
        now = datetime.now(timezone.utc).isoformat()
        for sid in ids:
            if act == "delete":
                if self._spatial_sightings.pop(sid, None) is not None:
                    affected += 1
            elif act == "archive":
                rec = self._spatial_sightings.get(sid)
                if rec is not None:
                    rec["archived"] = True
                    rec["archived_at"] = rec.get("archived_at") or now
                    affected += 1
            elif act == "retrieve":
                rec = self._spatial_sightings.get(sid)
                if rec is not None:
                    rec["archived"] = False
                    rec["archived_at"] = None
                    affected += 1
        return affected

    def count_spatial_sightings(
        self,
        space_id: Optional[str] = None,
        kind: Optional[str] = None,
        query: Optional[str] = None,
    ) -> Dict[str, int]:
        """Return ``{active, archived, total}`` counts for spatial sightings in memory."""
        q = (query or "").strip().lower()
        active = 0
        archived = 0
        for s in self._spatial_sightings.values():
            if not self._matches_sighting_filters(s, q=q, robot_id=None, kind=kind, space_id=space_id):
                continue
            if bool(s.get("archived", False)):
                archived += 1
            else:
                active += 1
        return {"active": active, "archived": archived, "total": active + archived}

    def delete_spatial_sighting(self, sighting_id: str) -> bool:
        """Delete a spatial sighting by ID."""
        return self._spatial_sightings.pop(sighting_id, None) is not None

    def record_sentry_event(self, robot_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Store a sentry alert event in memory."""
        snap_id = data.get("snapshot_file_id")
        rec = {
            "id": str(data.get("id") or uuid.uuid4()),
            "robot_id": robot_id,
            "trigger_type": str(data.get("trigger_type") or "lidar_motion"),
            "label": str(data.get("label") or "Alert"),
            "severity": str(data.get("severity") or "medium"),
            "detail": str(data.get("detail") or ""),
            "snapshot_file_id": snap_id,
            "snapshot_url": f"/api/files/{snap_id}" if snap_id else None,
            "spoken_alert": data.get("spoken_alert"),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._sentry_events.setdefault(robot_id, []).insert(0, rec)
        return dict(rec)

    def list_sentry_events(self, robot_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Return recent sentry alert events for ``robot_id`` ordered newest first."""
        return [dict(e) for e in self._sentry_events.get(robot_id, [])[: max(1, int(limit))]]

    def clear_sentry_events(self, robot_id: str) -> int:
        """Clear all sentry alert events for ``robot_id``."""
        removed = len(self._sentry_events.get(robot_id, []))
        self._sentry_events[robot_id] = []
        return removed

    @staticmethod
    def _format_scene_panel(panel: Dict[str, Any]) -> Dict[str, Any]:
        tex_id = panel.get("texture_file_id")
        norm_id = panel.get("normal_map_file_id")
        glb_id = panel.get("glb_file_id")
        created = panel.get("created_at")
        q_metrics = panel.get("quality_metrics")
        return {
            "id": str(panel["id"]),
            "space_id": str(panel["space_id"]),
            "robot_id": str(panel["robot_id"]) if panel.get("robot_id") is not None else None,
            "label": str(panel.get("label") or "Front Wall"),
            "stage": str(panel.get("stage") or "single_wall"),
            "pose": dict(panel.get("pose") or {}),
            "lidar_calibrated": bool(panel.get("lidar_calibrated", False)),
            "lidar_ray_count": int(panel.get("lidar_ray_count", 0)),
            "depth_source": str(panel.get("depth_source") or "geometric_relief"),
            "mean_distance_m": round(float(panel.get("mean_distance_m", 1.8)), 3),
            "min_distance_m": round(float(panel.get("min_distance_m", 1.0)), 3),
            "max_distance_m": round(float(panel.get("max_distance_m", 2.5)), 3),
            "vertex_count": int(panel.get("vertex_count", 0)),
            "triangle_count": int(panel.get("triangle_count", 0)),
            "texture_file_id": str(tex_id) if tex_id else None,
            "texture_url": f"/api/files/{tex_id}" if tex_id else None,
            "normal_map_file_id": str(norm_id) if norm_id else None,
            "normal_map_url": (
                str(panel.get("normal_map_url"))
                if panel.get("normal_map_url")
                else (f"/api/files/{norm_id}" if norm_id else None)
            ),
            "glb_file_id": str(glb_id) if glb_id else None,
            "glb_url": f"/api/files/{glb_id}" if glb_id else None,
            "quality_metrics": dict(q_metrics) if isinstance(q_metrics, dict) else None,
            "mesh": dict(panel.get("mesh") or {}),
            "created_at": created.isoformat() if isinstance(created, datetime) else str(created or ""),
        }

    def save_scene_panel(self, panel: Dict[str, Any]) -> Dict[str, Any]:
        """Insert or update a reconstructed 3D scene panel record in memory."""
        pid = str(panel.get("id") or uuid.uuid4())
        existing = self._scene_panels.get(pid)
        created_at = panel.get("created_at") or (existing.get("created_at") if existing else None) or datetime.now(timezone.utc).isoformat()
        rec = self._format_scene_panel({**panel, "id": pid, "created_at": created_at})
        self._scene_panels[pid] = rec
        return dict(rec)

    def list_scene_panels(self, space_id: str) -> List[Dict[str, Any]]:
        """List all reconstructed 3D scene panels for ``space_id`` ordered oldest first."""
        items = [dict(p) for p in self._scene_panels.values() if p["space_id"] == space_id]
        items.sort(key=lambda p: p.get("created_at", ""))
        return items

    def get_scene_panel(self, panel_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single reconstructed 3D scene panel by ID from memory."""
        found = self._scene_panels.get(panel_id)
        return dict(found) if found else None

    def delete_scene_panel(self, panel_id: str) -> bool:
        """Delete a reconstructed 3D scene panel by ID from memory."""
        return self._scene_panels.pop(panel_id, None) is not None

    def clear_scene_panels(self, space_id: str) -> int:
        """Delete all reconstructed 3D scene panels for ``space_id`` from memory."""
        to_delete = [pid for pid, p in self._scene_panels.items() if p["space_id"] == space_id]
        for pid in to_delete:
            self._scene_panels.pop(pid, None)
        return len(to_delete)

    @staticmethod
    def _format_inventory_item(item: Dict[str, Any]) -> Dict[str, Any]:
        created = item.get("created_at")
        updated = item.get("updated_at")
        raw_ifaces = item.get("interfaces")
        raw_caps = item.get("capabilities")
        return {
            "id": str(item["id"]),
            "name": str(item.get("name") or "").strip(),
            "profile_id": str(item["profile_id"]) if item.get("profile_id") else None,
            "category": str(item.get("category") or "accessory").strip().lower(),
            "manufacturer": str(item.get("manufacturer") or ""),
            "model": str(item.get("model") or ""),
            "quantity": max(0, int(item.get("quantity", 1))),
            "status": str(item.get("status") or "available").strip().lower(),
            "location": str(item.get("location") or ""),
            "interfaces": [str(x).strip() for x in raw_ifaces if str(x).strip()] if isinstance(raw_ifaces, list) else [],
            "voltage_v": float(item["voltage_v"]) if item.get("voltage_v") is not None else None,
            "current_ma": int(item["current_ma"]) if item.get("current_ma") is not None else None,
            "capabilities": [str(x).strip() for x in raw_caps if str(x).strip()] if isinstance(raw_caps, list) else [],
            "notes": str(item.get("notes") or ""),
            "est_cost_usd": float(item["est_cost_usd"]) if item.get("est_cost_usd") is not None else None,
            "created_at": created.isoformat() if isinstance(created, datetime) else str(created or ""),
            "updated_at": updated.isoformat() if isinstance(updated, datetime) else str(updated or ""),
        }

    def list_inventory_items(
        self,
        status: Optional[str] = None,
        category: Optional[str] = None,
        query: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List lab hardware inventory items from memory with optional filters."""
        st = (status or "").strip().lower()
        cat = (category or "").strip().lower()
        q = (query or "").strip().lower()
        items: List[Dict[str, Any]] = []
        for it in self._inventory_items.values():
            if st and st != "all":
                if st == "owned":
                    if it.get("status") not in ("available", "deployed"):
                        continue
                elif str(it.get("status") or "").lower() != st:
                    continue
            if cat and cat != "all" and str(it.get("category") or "").lower() != cat:
                continue
            if q:
                hay = " ".join(
                    [
                        str(it.get("name") or ""),
                        str(it.get("manufacturer") or ""),
                        str(it.get("model") or ""),
                        str(it.get("location") or ""),
                        str(it.get("notes") or ""),
                        str(it.get("profile_id") or ""),
                        " ".join(it.get("interfaces") or []),
                        " ".join(it.get("capabilities") or []),
                    ]
                ).lower()
                if q not in hay:
                    continue
            items.append(dict(it))
        items.sort(key=lambda x: (str(x.get("category") or ""), str(x.get("name") or "").lower()))
        return items

    def get_inventory_item(self, item_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single lab hardware inventory item by ID from memory."""
        found = self._inventory_items.get(item_id)
        return dict(found) if found else None

    def create_inventory_item(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create and store a new lab hardware inventory item in memory."""
        name = str(data.get("name") or "").strip()
        if not name:
            raise ValueError("Inventory item name is required")
        iid = str(data.get("id") or uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        rec = self._format_inventory_item(
            {
                **data,
                "id": iid,
                "name": name,
                "created_at": data.get("created_at") or now,
                "updated_at": data.get("updated_at") or now,
            }
        )
        self._inventory_items[iid] = rec
        return dict(rec)

    def update_inventory_item(self, item_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update mutable fields on a lab hardware inventory item in memory."""
        existing = self._inventory_items.get(item_id)
        if not existing:
            return None
        merged = dict(existing)
        for key in (
            "name",
            "profile_id",
            "category",
            "manufacturer",
            "model",
            "quantity",
            "status",
            "location",
            "interfaces",
            "voltage_v",
            "current_ma",
            "capabilities",
            "notes",
            "est_cost_usd",
        ):
            if key in updates and updates[key] is not None:
                merged[key] = updates[key]
            elif key in ("profile_id", "voltage_v", "current_ma", "est_cost_usd") and key in updates and updates[key] is None:
                merged[key] = None
        if not str(merged.get("name") or "").strip():
            merged["name"] = existing["name"]
        merged["updated_at"] = datetime.now(timezone.utc).isoformat()
        rec = self._format_inventory_item(merged)
        self._inventory_items[item_id] = rec
        return dict(rec)

    def delete_inventory_item(self, item_id: str) -> bool:
        """Delete a lab hardware inventory item by ID from memory."""
        return self._inventory_items.pop(item_id, None) is not None

    def count_inventory_items(self) -> Dict[str, int]:
        """Return ``{owned, wishlist, deployed, total}`` summary counts from memory."""
        owned = 0
        wishlist = 0
        deployed = 0
        for it in self._inventory_items.values():
            st = str(it.get("status") or "").lower()
            if st in ("available", "deployed"):
                owned += 1
            if st == "deployed":
                deployed += 1
            if st == "wishlist":
                wishlist += 1
        return {
            "owned": owned,
            "wishlist": wishlist,
            "deployed": deployed,
            "total": len(self._inventory_items),
        }

    @staticmethod
    def _format_managed_device(dev: Dict[str, Any]) -> Dict[str, Any]:
        created = dev.get("created_at")
        last_seen = dev.get("last_seen_at")
        cfg = dev.get("config")
        return {
            "id": str(dev["id"]),
            "name": str(dev.get("name") or "").strip(),
            "profile_id": str(dev.get("profile_id") or "custom"),
            "space_id": str(dev["space_id"]) if dev.get("space_id") else None,
            "transport": str(dev.get("transport") or "usb").strip().lower(),
            "endpoint": str(dev.get("endpoint") or ""),
            "status": str(dev.get("status") or "offline").strip().lower(),
            "config": dict(cfg) if isinstance(cfg, dict) else {},
            "last_seen_at": last_seen.isoformat() if isinstance(last_seen, datetime) else last_seen,
            "created_at": created.isoformat() if isinstance(created, datetime) else str(created or ""),
        }

    def list_managed_devices(
        self,
        profile_id: Optional[str] = None,
        space_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List registered non-robot managed devices from memory."""
        items = [
            dict(d)
            for d in self._managed_devices.values()
            if (not profile_id or d.get("profile_id") == profile_id)
            and (not space_id or d.get("space_id") == space_id)
        ]
        items.sort(key=lambda d: str(d.get("created_at") or ""), reverse=True)
        return items

    def get_managed_device(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single managed device by ID from memory."""
        found = self._managed_devices.get(device_id)
        return dict(found) if found else None

    def create_managed_device(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Register a new managed device in memory."""
        name = str(data.get("name") or "").strip()
        if not name:
            raise ValueError("Managed device name is required")
        did = str(data.get("id") or uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        rec = self._format_managed_device(
            {
                **data,
                "id": did,
                "name": name,
                "created_at": data.get("created_at") or now,
            }
        )
        self._managed_devices[did] = rec
        return dict(rec)

    def update_managed_device(self, device_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update fields on an existing managed device in memory."""
        existing = self._managed_devices.get(device_id)
        if not existing:
            return None
        merged = dict(existing)
        for key in ("name", "profile_id", "space_id", "transport", "endpoint", "status", "config", "last_seen_at"):
            if key in updates and updates[key] is not None:
                merged[key] = updates[key]
            elif key in ("space_id", "last_seen_at") and key in updates and updates[key] is None:
                merged[key] = None
        if not str(merged.get("name") or "").strip():
            merged["name"] = existing["name"]
        rec = self._format_managed_device(merged)
        self._managed_devices[device_id] = rec
        return dict(rec)

    def delete_managed_device(self, device_id: str) -> bool:
        """Delete a managed device by ID from memory."""
        return self._managed_devices.pop(device_id, None) is not None

    def save_design_blueprint(self, blueprint: Dict[str, Any]) -> Dict[str, Any]:
        """Insert or update a Co-Design Architect blueprint in memory."""
        bid = str(blueprint.get("id") or uuid.uuid4())
        existing = self._design_blueprints.get(bid)
        now = datetime.now(timezone.utc).isoformat()
        created_at = blueprint.get("created_at") or (existing.get("created_at") if existing else None) or now
        verdict = str(blueprint.get("verdict") or blueprint.get("feasibility") or "buildable_now")
        score = int(
            blueprint.get("feasibility_score")
            if blueprint.get("feasibility_score") is not None
            else blueprint.get("score", 80)
        )
        rec = {
            **blueprint,
            "id": bid,
            "title": str(blueprint.get("title") or blueprint.get("idea") or "Untitled Blueprint")[:160],
            "idea": str(blueprint.get("idea") or ""),
            "verdict": verdict,
            "feasibility_score": score,
            "creativity_level": int(blueprint.get("creativity_level", 3)),
            "persona": str(blueprint.get("persona") or "systems_architect"),
            "model_used": str(blueprint.get("model_used") or ""),
            "created_at": str(created_at),
            "updated_at": now,
        }
        self._design_blueprints[bid] = rec
        return dict(rec)

    def list_design_blueprints(self, limit: int = 50) -> List[Dict[str, Any]]:
        """List saved Co-Design Architect blueprints ordered newest updated first."""
        items = [dict(b) for b in self._design_blueprints.values()]
        items.sort(key=lambda b: str(b.get("updated_at") or b.get("created_at") or ""), reverse=True)
        return items[: max(1, int(limit))]

    def get_design_blueprint(self, blueprint_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single Co-Design Architect blueprint by ID from memory."""
        found = self._design_blueprints.get(blueprint_id)
        return dict(found) if found else None

    def delete_design_blueprint(self, blueprint_id: str) -> bool:
        """Delete a Co-Design Architect blueprint by ID from memory."""
        return self._design_blueprints.pop(blueprint_id, None) is not None

    def list_early_bird_signups(self, limit: int = 50) -> List[Dict[str, Any]]:
        """List anonymized Early Bird Maker signups from memory ordered newest spot first."""
        ordered = sorted(self._early_bird_signups, key=lambda r: int(r["spot_number"]), reverse=True)
        return [
            {
                "spot_number": int(r["spot_number"]),
                "founder_code": str(r["founder_code"]),
                "display_name": str(r["display_name"]),
                "role": str(r["role"]),
                "hardware_stack": list(r.get("hardware_stack") or []),
                "created_at": str(r["created_at"]),
            }
            for r in ordered[: max(1, int(limit))]
        ]

    def claim_early_bird_spot(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Claim a sequential Early Bird Maker spot in memory (strictly capped at 50, unique email)."""
        name = str(data.get("name") or "").strip()
        email = str(data.get("email") or "").strip().lower()
        if len(name) < 2 or not email:
            raise ValueError("invalid_early_bird_input")
        if any(str(r.get("email") or "").lower() == email for r in self._early_bird_signups):
            raise ValueError("email_already_claimed")
        if len(self._early_bird_signups) >= EARLY_BIRD_MAX_SPOTS:
            raise ValueError("early_bird_full")

        spot_number = len(self._early_bird_signups) + 1
        founder_code = f"EIGENIA-MAKER-{spot_number:02d}"
        display_name = _anonymize_maker_name(name)
        role = str(data.get("role") or "Maker").strip()[:64] or "Maker"
        hw_stack = _normalize_hardware_stack(data.get("hardware_stack"))
        goal = str(data.get("project_goal") or "").strip()[:500]
        now = datetime.now(timezone.utc).isoformat()
        rec = {
            "id": str(uuid.uuid4()),
            "spot_number": spot_number,
            "founder_code": founder_code,
            "name": name,
            "display_name": display_name,
            "email": email,
            "role": role,
            "hardware_stack": hw_stack,
            "project_goal": goal,
            "created_at": now,
        }
        self._early_bird_signups.append(rec)
        return {
            "ok": True,
            "spot_number": spot_number,
            "total_spots": EARLY_BIRD_MAX_SPOTS,
            "remaining_spots": max(0, EARLY_BIRD_MAX_SPOTS - spot_number),
            "founder_code": founder_code,
            "display_name": display_name,
            "role": role,
            "hardware_stack": list(hw_stack),
            "claimed_at": now,
        }

    def get_early_bird_status(self) -> Dict[str, Any]:
        """Return Early Bird 50-Maker campaign status and anonymized recent signups from memory."""
        claimed = len(self._early_bird_signups)
        return {
            "campaign": "Eigenia TwinScan Founding 50 Makers",
            "total_spots": EARLY_BIRD_MAX_SPOTS,
            "claimed_spots": claimed,
            "remaining_spots": max(0, EARLY_BIRD_MAX_SPOTS - claimed),
            "is_open": claimed < EARLY_BIRD_MAX_SPOTS,
            "perks": list(EARLY_BIRD_PERKS),
            "recent_makers": self.list_early_bird_signups(limit=12),
        }


class PostgresRobotAiStore:
    """Pooled PostgreSQL 18 + pgvector store for People/Faces, Patrol Routes, and Voice Logs."""

    def __init__(self, database_url: str, max_retries: int = 3) -> None:
        """Configure the PostgreSQL Robot AI store."""
        self.database_url = database_url
        self.max_retries = max_retries
        self._pool: Optional[ConnectionPool] = None

    def _ensure_pool(self) -> ConnectionPool:
        if self._pool is None:
            def _configure_conn(conn: psycopg.Connection[Any]) -> None:
                register_vector(conn)

            self._pool = ConnectionPool(
                conninfo=self.database_url,
                min_size=1,
                max_size=8,
                kwargs={"row_factory": dict_row},
                configure=_configure_conn,
                open=True,
            )
        return self._pool

    def _with_retry(self, fn: Any) -> Any:
        last_exc: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                return fn()
            except Exception as exc:
                last_exc = exc
                sys.stderr.write(
                    f"[robot_ai_store] PostgreSQL op failed (attempt {attempt}/{self.max_retries}): {exc}\n"
                )
                if attempt < self.max_retries:
                    time.sleep(min(0.4 * attempt, 2.0))
        assert last_exc is not None
        raise last_exc

    def initialize(self) -> None:
        """Create ``known_people``, ``face_embeddings``, ``patrol_routes``, and ``voice_interaction_logs``."""
        ddl = """
        CREATE EXTENSION IF NOT EXISTS vector;

        CREATE TABLE IF NOT EXISTS known_people (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'Operator',
            greeting_phrase TEXT NOT NULL DEFAULT '',
            greet_action TEXT NOT NULL DEFAULT 'none',
            auto_speak BOOLEAN NOT NULL DEFAULT TRUE,
            avatar_file_id TEXT,
            notes TEXT NOT NULL DEFAULT '',
            last_seen_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS face_embeddings (
            id TEXT PRIMARY KEY,
            person_id TEXT NOT NULL REFERENCES known_people(id) ON DELETE CASCADE,
            embedding vector(128) NOT NULL,
            source_file_id TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_face_embeddings_person ON face_embeddings(person_id);

        CREATE TABLE IF NOT EXISTS patrol_routes (
            id TEXT PRIMARY KEY,
            robot_id TEXT NOT NULL,
            space_id TEXT,
            name TEXT NOT NULL,
            waypoints_json JSONB NOT NULL DEFAULT '[]'::jsonb,
            loop_enabled BOOLEAN NOT NULL DEFAULT TRUE,
            max_speed_cms DOUBLE PRECISION NOT NULL DEFAULT 12.0,
            obstacle_clearance_m DOUBLE PRECISION NOT NULL DEFAULT 0.45,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_patrol_routes_robot ON patrol_routes(robot_id);

        CREATE TABLE IF NOT EXISTS voice_interaction_logs (
            id TEXT PRIMARY KEY,
            robot_id TEXT NOT NULL,
            direction TEXT NOT NULL DEFAULT 'in',
            transcript TEXT NOT NULL DEFAULT '',
            action_taken TEXT NOT NULL DEFAULT '',
            reply_text TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_voice_logs_robot ON voice_interaction_logs(robot_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS voice_assistant_config (
            robot_id TEXT PRIMARY KEY,
            assistant_name TEXT NOT NULL DEFAULT 'OX',
            wake_word TEXT NOT NULL DEFAULT 'Hey OX',
            wake_aliases_json JSONB NOT NULL DEFAULT '["hey ox","hey aux","hey o x","hey box","hey fox"]'::jsonb,
            wake_mode TEXT NOT NULL DEFAULT 'custom_software',
            default_engine TEXT NOT NULL DEFAULT 'piper_tts',
            default_voice TEXT NOT NULL DEFAULT 'en_US-lessac-medium',
            default_speed INTEGER NOT NULL DEFAULT 155,
            anti_clip BOOLEAN NOT NULL DEFAULT TRUE,
            followup_window_sec INTEGER NOT NULL DEFAULT 12,
            personality_id TEXT NOT NULL DEFAULT 'dog',
            llm_model TEXT NOT NULL DEFAULT 'google/gemini-2.5-flash',
            attach_camera_on_visual BOOLEAN NOT NULL DEFAULT TRUE,
            allow_body_actions BOOLEAN NOT NULL DEFAULT TRUE,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS voice_personalities (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            badge TEXT NOT NULL DEFAULT 'CUSTOM',
            description TEXT NOT NULL DEFAULT '',
            system_prompt TEXT NOT NULL,
            default_voice TEXT NOT NULL DEFAULT 'en_US-lessac-medium',
            allow_body_actions BOOLEAN NOT NULL DEFAULT TRUE,
            is_builtin BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS voice_conversation_turns (
            id TEXT PRIMARY KEY,
            robot_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            personality_id TEXT,
            action_taken TEXT,
            rgb_applied_json JSONB,
            camera_attached BOOLEAN NOT NULL DEFAULT FALSE,
            engine_used TEXT,
            latency_ms INTEGER,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_voice_turns_robot ON voice_conversation_turns(robot_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS spatial_sightings (
            id TEXT PRIMARY KEY,
            robot_id TEXT NOT NULL,
            space_id TEXT,
            label TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'object',
            x_m DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            y_m DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5,
            snapshot_file_id TEXT,
            notes TEXT NOT NULL DEFAULT '',
            seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            archived BOOLEAN NOT NULL DEFAULT FALSE,
            archived_at TIMESTAMPTZ,
            camera_source TEXT NOT NULL DEFAULT 'puppypi_fpv',
            tags_json JSONB NOT NULL DEFAULT '[]'::jsonb
        );
        ALTER TABLE spatial_sightings ADD COLUMN IF NOT EXISTS archived BOOLEAN NOT NULL DEFAULT FALSE;
        ALTER TABLE spatial_sightings ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;
        ALTER TABLE spatial_sightings ADD COLUMN IF NOT EXISTS camera_source TEXT NOT NULL DEFAULT 'puppypi_fpv';
        ALTER TABLE spatial_sightings ADD COLUMN IF NOT EXISTS tags_json JSONB NOT NULL DEFAULT '[]'::jsonb;
        CREATE INDEX IF NOT EXISTS idx_spatial_sightings_seen ON spatial_sightings(seen_at DESC);
        CREATE INDEX IF NOT EXISTS idx_spatial_sightings_label ON spatial_sightings(LOWER(label));
        CREATE INDEX IF NOT EXISTS idx_spatial_sightings_archived ON spatial_sightings(archived, seen_at DESC);

        CREATE TABLE IF NOT EXISTS sentry_events (
            id TEXT PRIMARY KEY,
            robot_id TEXT NOT NULL,
            trigger_type TEXT NOT NULL DEFAULT 'lidar_motion',
            label TEXT NOT NULL DEFAULT 'Alert',
            severity TEXT NOT NULL DEFAULT 'medium',
            detail TEXT NOT NULL DEFAULT '',
            snapshot_file_id TEXT,
            spoken_alert TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_sentry_events_robot ON sentry_events(robot_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS scene_panels (
            id TEXT PRIMARY KEY,
            space_id TEXT NOT NULL,
            robot_id TEXT,
            label TEXT NOT NULL DEFAULT 'Front Wall',
            stage TEXT NOT NULL DEFAULT 'single_wall',
            pose_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            lidar_calibrated BOOLEAN NOT NULL DEFAULT FALSE,
            lidar_ray_count INTEGER NOT NULL DEFAULT 0,
            depth_source TEXT NOT NULL DEFAULT 'geometric_relief',
            mean_distance_m DOUBLE PRECISION NOT NULL DEFAULT 1.8,
            min_distance_m DOUBLE PRECISION NOT NULL DEFAULT 1.0,
            max_distance_m DOUBLE PRECISION NOT NULL DEFAULT 2.5,
            vertex_count INTEGER NOT NULL DEFAULT 0,
            triangle_count INTEGER NOT NULL DEFAULT 0,
            texture_file_id TEXT,
            normal_map_file_id TEXT,
            normal_map_url TEXT,
            glb_file_id TEXT,
            quality_metrics_json JSONB,
            mesh_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        ALTER TABLE scene_panels ADD COLUMN IF NOT EXISTS normal_map_file_id TEXT;
        ALTER TABLE scene_panels ADD COLUMN IF NOT EXISTS normal_map_url TEXT;
        ALTER TABLE scene_panels ADD COLUMN IF NOT EXISTS quality_metrics_json JSONB;
        CREATE INDEX IF NOT EXISTS idx_scene_panels_space ON scene_panels(space_id, created_at ASC);

        CREATE TABLE IF NOT EXISTS inventory_items (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            profile_id TEXT,
            category TEXT NOT NULL DEFAULT 'accessory',
            manufacturer TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            quantity INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'available',
            location TEXT NOT NULL DEFAULT '',
            interfaces_json JSONB NOT NULL DEFAULT '[]'::jsonb,
            voltage_v DOUBLE PRECISION,
            current_ma INTEGER,
            capabilities_json JSONB NOT NULL DEFAULT '[]'::jsonb,
            notes TEXT NOT NULL DEFAULT '',
            est_cost_usd DOUBLE PRECISION,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_inventory_items_status ON inventory_items(status, category);

        CREATE TABLE IF NOT EXISTS managed_devices (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            profile_id TEXT NOT NULL DEFAULT 'custom',
            space_id TEXT,
            transport TEXT NOT NULL DEFAULT 'usb',
            endpoint TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'offline',
            config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            last_seen_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_managed_devices_profile ON managed_devices(profile_id, space_id);

        CREATE TABLE IF NOT EXISTS design_blueprints (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT '',
            idea TEXT NOT NULL DEFAULT '',
            feasibility TEXT NOT NULL DEFAULT 'plausible',
            score INTEGER NOT NULL DEFAULT 50,
            creativity_level INTEGER NOT NULL DEFAULT 3,
            persona TEXT NOT NULL DEFAULT 'systems_architect',
            model_used TEXT NOT NULL DEFAULT '',
            blueprint_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_design_blueprints_updated ON design_blueprints(updated_at DESC);

        CREATE TABLE IF NOT EXISTS early_bird_signups (
            id TEXT PRIMARY KEY,
            spot_number INTEGER NOT NULL UNIQUE,
            founder_code TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            display_name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            role TEXT NOT NULL DEFAULT 'Maker',
            hardware_stack JSONB NOT NULL DEFAULT '[]'::jsonb,
            project_goal TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_early_bird_spot ON early_bird_signups(spot_number ASC);
        """

        def _init() -> None:
            with psycopg.connect(self.database_url) as conn:
                conn.execute(ddl)
                for p in _builtin_personalities_seed():
                    conn.execute(
                        """
                        INSERT INTO voice_personalities (
                            id, name, badge, description, system_prompt,
                            default_voice, allow_body_actions, is_builtin
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE)
                        ON CONFLICT (id) DO NOTHING
                        """,
                        (
                            p["id"],
                            p["name"],
                            p["badge"],
                            p["description"],
                            p["system_prompt"],
                            p["default_voice"],
                            bool(p["allow_body_actions"]),
                        ),
                    )
                conn.commit()
            self._ensure_pool()

        self._with_retry(_init)

    def close(self) -> None:
        """Close the PostgreSQL connection pool cleanly."""
        if self._pool is not None:
            self._pool.close()
            self._pool = None

    def create_person(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Insert a new known person row."""
        pid = str(data.get("id") or uuid.uuid4())
        name = str(data.get("name") or "").strip()
        if not name:
            raise ValueError("Person name is required")

        def _op() -> Dict[str, Any]:
            with self._ensure_pool().connection() as conn:
                row = conn.execute(
                    """
                    INSERT INTO known_people (
                        id, name, role, greeting_phrase, greet_action, auto_speak, avatar_file_id, notes
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        pid,
                        name,
                        str(data.get("role") or "Operator"),
                        str(data.get("greeting_phrase") or f"Hello {name}!"),
                        str(data.get("greet_action") or "none"),
                        bool(data.get("auto_speak", True)),
                        data.get("avatar_file_id"),
                        str(data.get("notes") or ""),
                    ),
                ).fetchone()
                conn.commit()
                return _format_person(row, embedding_count=0)

        return self._with_retry(_op)

    def list_people(self) -> List[Dict[str, Any]]:
        """List all known people with their stored face embedding counts."""
        def _op() -> List[Dict[str, Any]]:
            with self._ensure_pool().connection() as conn:
                rows = conn.execute(
                    """
                    SELECT p.*, COUNT(e.id) AS embedding_count
                    FROM known_people p
                    LEFT JOIN face_embeddings e ON e.person_id = p.id
                    GROUP BY p.id
                    ORDER BY LOWER(p.name) ASC
                    """
                ).fetchall()
                return [_format_person(r) for r in rows]

        return self._with_retry(_op)

    def get_person(self, person_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single known person with embedding count."""
        def _op() -> Optional[Dict[str, Any]]:
            with self._ensure_pool().connection() as conn:
                row = conn.execute(
                    """
                    SELECT p.*, COUNT(e.id) AS embedding_count
                    FROM known_people p
                    LEFT JOIN face_embeddings e ON e.person_id = p.id
                    WHERE p.id = %s
                    GROUP BY p.id
                    """,
                    (person_id,),
                ).fetchone()
                return _format_person(row) if row else None

        return self._with_retry(_op)

    def update_person(self, person_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update profile fields on a known person."""
        def _op() -> Optional[Dict[str, Any]]:
            with self._ensure_pool().connection() as conn:
                existing = conn.execute("SELECT * FROM known_people WHERE id = %s", (person_id,)).fetchone()
                if not existing:
                    return None
                conn.execute(
                    """
                    UPDATE known_people SET
                        name = %s,
                        role = %s,
                        greeting_phrase = %s,
                        greet_action = %s,
                        auto_speak = %s,
                        avatar_file_id = %s,
                        notes = %s,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (
                        updates.get("name") or existing["name"],
                        updates.get("role") if updates.get("role") is not None else existing["role"],
                        updates.get("greeting_phrase") if updates.get("greeting_phrase") is not None else existing["greeting_phrase"],
                        updates.get("greet_action") if updates.get("greet_action") is not None else existing["greet_action"],
                        bool(updates["auto_speak"]) if "auto_speak" in updates and updates["auto_speak"] is not None else existing["auto_speak"],
                        updates.get("avatar_file_id") if "avatar_file_id" in updates else existing["avatar_file_id"],
                        updates.get("notes") if updates.get("notes") is not None else existing["notes"],
                        person_id,
                    ),
                )
                conn.commit()
            return self.get_person(person_id)

        return self._with_retry(_op)

    def delete_person(self, person_id: str) -> bool:
        """Delete a known person and cascade-remove face embeddings."""
        def _op() -> bool:
            with self._ensure_pool().connection() as conn:
                cur = conn.execute("DELETE FROM known_people WHERE id = %s", (person_id,))
                conn.commit()
                return cur.rowcount > 0

        return self._with_retry(_op)

    def touch_person_seen(self, person_id: str) -> None:
        """Update ``last_seen_at`` to NOW() for a recognized person."""
        def _op() -> None:
            with self._ensure_pool().connection() as conn:
                conn.execute("UPDATE known_people SET last_seen_at = NOW() WHERE id = %s", (person_id,))
                conn.commit()

        self._with_retry(_op)

    def add_face_embedding(
        self,
        person_id: str,
        embedding: Sequence[float],
        source_file_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Insert a normalized 128-D face embedding vector into PostgreSQL pgvector."""
        vec = _normalize_vec128(embedding).tolist()
        eid = str(uuid.uuid4())

        def _op() -> Dict[str, Any]:
            with self._ensure_pool().connection() as conn:
                row = conn.execute(
                    """
                    INSERT INTO face_embeddings (id, person_id, embedding, source_file_id)
                    VALUES (%s, %s, %s::vector, %s)
                    RETURNING id, person_id, source_file_id, created_at
                    """,
                    (eid, person_id, vec, source_file_id),
                ).fetchone()
                conn.commit()
                out = dict(row)
                if isinstance(out.get("created_at"), datetime):
                    out["created_at"] = out["created_at"].isoformat()
                return out

        return self._with_retry(_op)

    def match_face_embedding(
        self,
        embedding: Sequence[float],
        threshold: float = 0.363,
    ) -> Optional[Dict[str, Any]]:
        """Query pgvector cosine similarity to find the closest enrolled person."""
        vec = _normalize_vec128(embedding).tolist()

        def _op() -> Optional[Dict[str, Any]]:
            with self._ensure_pool().connection() as conn:
                row = conn.execute(
                    """
                    SELECT person_id, (1.0 - (embedding <=> %s::vector)) AS similarity
                    FROM face_embeddings
                    ORDER BY embedding <=> %s::vector ASC
                    LIMIT 1
                    """,
                    (vec, vec),
                ).fetchone()
                if not row:
                    return None
                sim = float(row["similarity"] or 0.0)
                if sim < threshold:
                    return None
                person = self.get_person(str(row["person_id"]))
                if not person:
                    return None
                return {"person": person, "similarity": round(sim, 4)}

        return self._with_retry(_op)

    @staticmethod
    def _serialize_route(row: Dict[str, Any]) -> Dict[str, Any]:
        created = row.get("created_at")
        updated = row.get("updated_at")
        return {
            "id": str(row["id"]),
            "robot_id": str(row["robot_id"]),
            "space_id": row.get("space_id"),
            "name": str(row["name"]),
            "waypoints": list(row.get("waypoints_json") or []),
            "loop_enabled": bool(row.get("loop_enabled", True)),
            "max_speed_cms": float(row.get("max_speed_cms", 12.0)),
            "obstacle_clearance_m": float(row.get("obstacle_clearance_m", 0.45)),
            "created_at": created.isoformat() if isinstance(created, datetime) else str(created or ""),
            "updated_at": updated.isoformat() if isinstance(updated, datetime) else str(updated or ""),
        }

    def create_patrol_route(self, robot_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Insert a named patrol route into PostgreSQL."""
        rid = str(data.get("id") or uuid.uuid4())
        name = str(data.get("name") or "").strip() or f"Route {rid[:6]}"

        def _op() -> Dict[str, Any]:
            with self._ensure_pool().connection() as conn:
                row = conn.execute(
                    """
                    INSERT INTO patrol_routes (
                        id, robot_id, space_id, name, waypoints_json,
                        loop_enabled, max_speed_cms, obstacle_clearance_m
                    ) VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        rid,
                        robot_id,
                        data.get("space_id"),
                        name,
                        json.dumps(list(data.get("waypoints") or [])),
                        bool(data.get("loop_enabled", True)),
                        float(data.get("max_speed_cms", 12.0)),
                        float(data.get("obstacle_clearance_m", 0.45)),
                    ),
                ).fetchone()
                conn.commit()
                return self._serialize_route(row)

        return self._with_retry(_op)

    def list_patrol_routes(self, robot_id: str) -> List[Dict[str, Any]]:
        """List saved patrol routes for ``robot_id``."""
        def _op() -> List[Dict[str, Any]]:
            with self._ensure_pool().connection() as conn:
                rows = conn.execute(
                    "SELECT * FROM patrol_routes WHERE robot_id = %s ORDER BY created_at DESC",
                    (robot_id,),
                ).fetchall()
                return [self._serialize_route(r) for r in rows]

        return self._with_retry(_op)

    def get_patrol_route(self, route_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single patrol route by ID."""
        def _op() -> Optional[Dict[str, Any]]:
            with self._ensure_pool().connection() as conn:
                row = conn.execute("SELECT * FROM patrol_routes WHERE id = %s", (route_id,)).fetchone()
                return self._serialize_route(row) if row else None

        return self._with_retry(_op)

    def delete_patrol_route(self, route_id: str) -> bool:
        """Delete a patrol route by ID."""
        def _op() -> bool:
            with self._ensure_pool().connection() as conn:
                cur = conn.execute("DELETE FROM patrol_routes WHERE id = %s", (route_id,))
                conn.commit()
                return cur.rowcount > 0

        return self._with_retry(_op)

    def record_voice_log(
        self,
        robot_id: str,
        direction: str,
        transcript: str,
        action_taken: str = "",
        reply_text: str = "",
    ) -> Dict[str, Any]:
        """Insert a voice interaction log row into PostgreSQL."""
        vid = str(uuid.uuid4())

        def _op() -> Dict[str, Any]:
            with self._ensure_pool().connection() as conn:
                row = conn.execute(
                    """
                    INSERT INTO voice_interaction_logs (
                        id, robot_id, direction, transcript, action_taken, reply_text
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (vid, robot_id, str(direction or "in"), str(transcript or ""), str(action_taken or ""), str(reply_text or "")),
                ).fetchone()
                conn.commit()
                out = dict(row)
                if isinstance(out.get("created_at"), datetime):
                    out["created_at"] = out["created_at"].isoformat()
                return out

        return self._with_retry(_op)

    def list_voice_logs(self, robot_id: str, limit: int = 30) -> List[Dict[str, Any]]:
        """List recent voice interaction logs for ``robot_id``."""
        def _op() -> List[Dict[str, Any]]:
            with self._ensure_pool().connection() as conn:
                rows = conn.execute(
                    """
                    SELECT * FROM voice_interaction_logs
                    WHERE robot_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (robot_id, max(1, int(limit))),
                ).fetchall()
                out = []
                for r in rows:
                    item = dict(r)
                    if isinstance(item.get("created_at"), datetime):
                        item["created_at"] = item["created_at"].isoformat()
                    out.append(item)
                return out

        return self._with_retry(_op)

    @staticmethod
    def _serialize_voice_config(row: Dict[str, Any]) -> Dict[str, Any]:
        aliases = row.get("wake_aliases_json")
        if isinstance(aliases, str):
            try:
                aliases = json.loads(aliases)
            except Exception:
                aliases = []
        upd = row.get("updated_at")
        return {
            "robot_id": str(row["robot_id"]),
            "assistant_name": str(row.get("assistant_name") or "OX"),
            "wake_word": str(row.get("wake_word") or "Hey OX"),
            "wake_aliases": list(aliases or []),
            "wake_mode": str(row.get("wake_mode") or "custom_software"),
            "default_engine": str(row.get("default_engine") or "piper_tts"),
            "default_voice": str(row.get("default_voice") or "en_US-lessac-medium"),
            "default_speed": int(row.get("default_speed", 155)),
            "anti_clip": bool(row.get("anti_clip", True)),
            "followup_window_sec": int(row.get("followup_window_sec", 12)),
            "personality_id": str(row.get("personality_id") or "dog"),
            "llm_model": str(row.get("llm_model") or "google/gemini-2.5-flash"),
            "attach_camera_on_visual": bool(row.get("attach_camera_on_visual", True)),
            "allow_body_actions": bool(row.get("allow_body_actions", True)),
            "updated_at": upd.isoformat() if isinstance(upd, datetime) else upd,
        }

    def get_voice_config(self, robot_id: str) -> Dict[str, Any]:
        """Fetch per-robot conversational voice config from PostgreSQL (or defaults)."""
        def _op() -> Dict[str, Any]:
            with self._ensure_pool().connection() as conn:
                row = conn.execute(
                    "SELECT * FROM voice_assistant_config WHERE robot_id = %s", (robot_id,)
                ).fetchone()
                return self._serialize_voice_config(row) if row else _default_voice_config(robot_id)

        return self._with_retry(_op)

    def upsert_voice_config(self, robot_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Insert or update per-robot conversational voice config in PostgreSQL."""
        cur = self.get_voice_config(robot_id)
        for key in (
            "assistant_name",
            "wake_word",
            "wake_mode",
            "default_engine",
            "default_voice",
            "llm_model",
            "personality_id",
        ):
            if key in updates and updates[key] is not None:
                cur[key] = str(updates[key]).strip() or cur[key]
        if "wake_aliases" in updates and updates["wake_aliases"] is not None:
            cur["wake_aliases"] = [str(a).strip() for a in updates["wake_aliases"] if str(a).strip()]
        if "default_speed" in updates and updates["default_speed"] is not None:
            cur["default_speed"] = max(80, min(320, int(updates["default_speed"])))
        if "followup_window_sec" in updates and updates["followup_window_sec"] is not None:
            cur["followup_window_sec"] = max(0, min(60, int(updates["followup_window_sec"])))
        for bkey in ("anti_clip", "attach_camera_on_visual", "allow_body_actions"):
            if bkey in updates and updates[bkey] is not None:
                cur[bkey] = bool(updates[bkey])

        def _op() -> Dict[str, Any]:
            with self._ensure_pool().connection() as conn:
                row = conn.execute(
                    """
                    INSERT INTO voice_assistant_config (
                        robot_id, assistant_name, wake_word, wake_aliases_json, wake_mode,
                        default_engine, default_voice, default_speed, anti_clip,
                        followup_window_sec, personality_id, llm_model,
                        attach_camera_on_visual, allow_body_actions, updated_at
                    ) VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (robot_id) DO UPDATE SET
                        assistant_name = EXCLUDED.assistant_name,
                        wake_word = EXCLUDED.wake_word,
                        wake_aliases_json = EXCLUDED.wake_aliases_json,
                        wake_mode = EXCLUDED.wake_mode,
                        default_engine = EXCLUDED.default_engine,
                        default_voice = EXCLUDED.default_voice,
                        default_speed = EXCLUDED.default_speed,
                        anti_clip = EXCLUDED.anti_clip,
                        followup_window_sec = EXCLUDED.followup_window_sec,
                        personality_id = EXCLUDED.personality_id,
                        llm_model = EXCLUDED.llm_model,
                        attach_camera_on_visual = EXCLUDED.attach_camera_on_visual,
                        allow_body_actions = EXCLUDED.allow_body_actions,
                        updated_at = NOW()
                    RETURNING *
                    """,
                    (
                        robot_id,
                        cur["assistant_name"],
                        cur["wake_word"],
                        json.dumps(cur["wake_aliases"]),
                        cur["wake_mode"],
                        cur["default_engine"],
                        cur["default_voice"],
                        cur["default_speed"],
                        cur["anti_clip"],
                        cur["followup_window_sec"],
                        cur["personality_id"],
                        cur["llm_model"],
                        cur["attach_camera_on_visual"],
                        cur["allow_body_actions"],
                    ),
                ).fetchone()
                conn.commit()
                return self._serialize_voice_config(row)

        return self._with_retry(_op)

    @staticmethod
    def _serialize_personality(row: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(row)
        for k in ("created_at", "updated_at"):
            if isinstance(out.get(k), datetime):
                out[k] = out[k].isoformat()
        out["allow_body_actions"] = bool(out.get("allow_body_actions", True))
        out["is_builtin"] = bool(out.get("is_builtin", False))
        return out

    def list_personalities(self) -> List[Dict[str, Any]]:
        """List all built-in and custom personalities from PostgreSQL."""
        def _op() -> List[Dict[str, Any]]:
            with self._ensure_pool().connection() as conn:
                rows = conn.execute(
                    "SELECT * FROM voice_personalities ORDER BY is_builtin DESC, LOWER(name) ASC"
                ).fetchall()
                return [self._serialize_personality(r) for r in rows]

        return self._with_retry(_op)

    def get_personality(self, personality_id: str) -> Optional[Dict[str, Any]]:
        """Fetch one personality by ID from PostgreSQL."""
        def _op() -> Optional[Dict[str, Any]]:
            with self._ensure_pool().connection() as conn:
                row = conn.execute(
                    "SELECT * FROM voice_personalities WHERE id = %s", (personality_id,)
                ).fetchone()
                return self._serialize_personality(row) if row else None

        return self._with_retry(_op)

    def create_personality(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Insert a new custom voice personality into PostgreSQL."""
        name = str(data.get("name") or "").strip()
        prompt = str(data.get("system_prompt") or "").strip()
        if not name:
            raise ValueError("Personality name is required")
        if not prompt:
            raise ValueError("Personality system_prompt is required")
        pid = str(data.get("id") or f"custom-{uuid.uuid4().hex[:8]}")

        def _op() -> Dict[str, Any]:
            with self._ensure_pool().connection() as conn:
                row = conn.execute(
                    """
                    INSERT INTO voice_personalities (
                        id, name, badge, description, system_prompt,
                        default_voice, allow_body_actions, is_builtin
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, FALSE)
                    RETURNING *
                    """,
                    (
                        pid,
                        name,
                        str(data.get("badge") or "CUSTOM").strip()[:16].upper(),
                        str(data.get("description") or "").strip(),
                        prompt,
                        str(data.get("default_voice") or "en_US-lessac-medium").strip(),
                        bool(data.get("allow_body_actions", True)),
                    ),
                ).fetchone()
                conn.commit()
                return self._serialize_personality(row)

        return self._with_retry(_op)

    def update_personality(self, personality_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update editable fields on an existing voice personality."""
        allowed = {
            k: v
            for k, v in data.items()
            if k in ("name", "badge", "description", "system_prompt", "default_voice", "allow_body_actions")
            and v is not None
        }
        if not allowed:
            return self.get_personality(personality_id)

        def _op() -> Optional[Dict[str, Any]]:
            sets = [f"{k} = %s" for k in allowed] + ["updated_at = NOW()"]
            vals = [
                str(v).strip().upper()[:16] if k == "badge" else (bool(v) if k == "allow_body_actions" else str(v).strip())
                for k, v in allowed.items()
            ] + [personality_id]
            with self._ensure_pool().connection() as conn:
                row = conn.execute(
                    f"UPDATE voice_personalities SET {', '.join(sets)} WHERE id = %s RETURNING *",
                    vals,
                ).fetchone()
                conn.commit()
                return self._serialize_personality(row) if row else None

        return self._with_retry(_op)

    def delete_personality(self, personality_id: str) -> bool:
        """Delete a custom personality from PostgreSQL (refuses built-in personalities)."""
        existing = self.get_personality(personality_id)
        if not existing:
            return False
        if existing.get("is_builtin"):
            raise ValueError(f"Built-in personality {personality_id!r} cannot be deleted.")

        def _op() -> bool:
            with self._ensure_pool().connection() as conn:
                cur = conn.execute(
                    "DELETE FROM voice_personalities WHERE id = %s AND is_builtin = FALSE",
                    (personality_id,),
                )
                conn.commit()
                return cur.rowcount > 0

        return self._with_retry(_op)

    @staticmethod
    def _serialize_turn(row: Dict[str, Any]) -> Dict[str, Any]:
        rgb = row.get("rgb_applied_json")
        if isinstance(rgb, str):
            try:
                rgb = json.loads(rgb)
            except Exception:
                rgb = None
        created = row.get("created_at")
        return {
            "id": str(row["id"]),
            "robot_id": str(row["robot_id"]),
            "role": str(row["role"]),
            "content": str(row["content"]),
            "personality_id": row.get("personality_id"),
            "action_taken": row.get("action_taken"),
            "rgb_applied": list(rgb) if isinstance(rgb, list) else None,
            "camera_attached": bool(row.get("camera_attached", False)),
            "engine_used": row.get("engine_used"),
            "latency_ms": int(row["latency_ms"]) if row.get("latency_ms") is not None else None,
            "created_at": created.isoformat() if isinstance(created, datetime) else str(created or ""),
        }

    def record_conversation_turn(self, robot_id: str, turn: Dict[str, Any]) -> Dict[str, Any]:
        """Insert a user or assistant conversation turn into PostgreSQL."""
        tid = str(turn.get("id") or uuid.uuid4())
        rgb_json = json.dumps(list(turn["rgb_applied"])) if turn.get("rgb_applied") else None

        def _op() -> Dict[str, Any]:
            with self._ensure_pool().connection() as conn:
                row = conn.execute(
                    """
                    INSERT INTO voice_conversation_turns (
                        id, robot_id, role, content, personality_id, action_taken,
                        rgb_applied_json, camera_attached, engine_used, latency_ms
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        tid,
                        robot_id,
                        str(turn.get("role") or "user"),
                        str(turn.get("content") or ""),
                        turn.get("personality_id"),
                        turn.get("action_taken"),
                        rgb_json,
                        bool(turn.get("camera_attached", False)),
                        turn.get("engine_used"),
                        int(turn["latency_ms"]) if turn.get("latency_ms") is not None else None,
                    ),
                ).fetchone()
                conn.commit()
                return self._serialize_turn(row)

        return self._with_retry(_op)

    def list_conversation_turns(self, robot_id: str, limit: int = 30) -> List[Dict[str, Any]]:
        """List recent conversation turns for ``robot_id`` ordered oldest-first."""
        def _op() -> List[Dict[str, Any]]:
            with self._ensure_pool().connection() as conn:
                rows = conn.execute(
                    """
                    SELECT * FROM (
                        SELECT * FROM voice_conversation_turns
                        WHERE robot_id = %s
                        ORDER BY created_at DESC
                        LIMIT %s
                    ) sub
                    ORDER BY created_at ASC
                    """,
                    (robot_id, max(1, int(limit))),
                ).fetchall()
                return [self._serialize_turn(r) for r in rows]

        return self._with_retry(_op)

    def clear_conversation_turns(self, robot_id: str) -> int:
        """Delete all stored conversation turns for ``robot_id`` from PostgreSQL."""
        def _op() -> int:
            with self._ensure_pool().connection() as conn:
                cur = conn.execute(
                    "DELETE FROM voice_conversation_turns WHERE robot_id = %s",
                    (robot_id,),
                )
                conn.commit()
                return int(cur.rowcount)

        return self._with_retry(_op)

    @staticmethod
    def _serialize_sighting(row: Dict[str, Any]) -> Dict[str, Any]:
        snap_id = row.get("snapshot_file_id")
        seen = row.get("seen_at")
        arch_at = row.get("archived_at")
        raw_tags = row.get("tags_json")
        if isinstance(raw_tags, str):
            try:
                raw_tags = json.loads(raw_tags)
            except Exception:
                raw_tags = []
        return {
            "id": str(row["id"]),
            "robot_id": str(row["robot_id"]),
            "space_id": row.get("space_id"),
            "label": str(row.get("label") or "object"),
            "kind": str(row.get("kind") or "object"),
            "x_m": round(float(row.get("x_m", 0.0)), 3),
            "y_m": round(float(row.get("y_m", 0.0)), 3),
            "confidence": round(float(row.get("confidence", 0.5)), 3),
            "snapshot_file_id": snap_id,
            "snapshot_url": f"/api/files/{snap_id}" if snap_id else None,
            "notes": str(row.get("notes") or ""),
            "seen_at": seen.isoformat() if isinstance(seen, datetime) else str(seen or ""),
            "archived": bool(row.get("archived", False)),
            "archived_at": arch_at.isoformat() if isinstance(arch_at, datetime) else arch_at,
            "camera_source": str(row.get("camera_source") or "puppypi_fpv"),
            "tags": [str(t).strip() for t in raw_tags if str(t).strip()] if isinstance(raw_tags, list) else [],
        }

    def record_spatial_sighting(self, robot_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Insert a semantic spatial sighting row into PostgreSQL."""
        sid = str(data.get("id") or uuid.uuid4())
        archived = bool(data.get("archived", False))
        raw_tags = data.get("tags")
        tags = [str(t).strip() for t in raw_tags if str(t).strip()] if isinstance(raw_tags, list) else []

        def _op() -> Dict[str, Any]:
            with self._ensure_pool().connection() as conn:
                row = conn.execute(
                    """
                    INSERT INTO spatial_sightings (
                        id, robot_id, space_id, label, kind, x_m, y_m, confidence,
                        snapshot_file_id, notes, archived, archived_at, camera_source, tags_json
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, CASE WHEN %s THEN NOW() ELSE NULL END, %s, %s::jsonb
                    )
                    RETURNING *
                    """,
                    (
                        sid,
                        robot_id,
                        data.get("space_id"),
                        str(data.get("label") or "object").strip(),
                        str(data.get("kind") or "object").strip(),
                        float(data.get("x_m", 0.0)),
                        float(data.get("y_m", 0.0)),
                        float(data.get("confidence", 0.5)),
                        data.get("snapshot_file_id"),
                        str(data.get("notes") or ""),
                        archived,
                        archived,
                        str(data.get("camera_source") or "puppypi_fpv").strip() or "puppypi_fpv",
                        json.dumps(tags),
                    ),
                ).fetchone()
                conn.commit()
                return self._serialize_sighting(row)

        return self._with_retry(_op)

    def list_spatial_sightings(
        self,
        query: Optional[str] = None,
        limit: int = 200,
        robot_id: Optional[str] = None,
        status: str = "active",
        kind: Optional[str] = None,
        space_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Query recent semantic spatial sightings from PostgreSQL with archive/kind/space filters."""
        q = (query or "").strip()
        st = (status or "active").strip().lower()
        k = (kind or "").strip().lower()

        def _op() -> List[Dict[str, Any]]:
            clauses: List[str] = []
            params: List[Any] = []
            if st == "active":
                clauses.append("archived = FALSE")
            elif st == "archived":
                clauses.append("archived = TRUE")
            if robot_id:
                clauses.append("robot_id = %s")
                params.append(robot_id)
            if k and k != "all":
                clauses.append("LOWER(kind) = %s")
                params.append(k)
            if space_id:
                clauses.append("space_id = %s")
                params.append(space_id)
            if q:
                clauses.append(
                    "(label ILIKE %s OR kind ILIKE %s OR notes ILIKE %s OR camera_source ILIKE %s OR tags_json::text ILIKE %s)"
                )
                like = f"%{q}%"
                params.extend([like, like, like, like, like])
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            params.append(max(1, int(limit)))
            with self._ensure_pool().connection() as conn:
                rows = conn.execute(
                    f"SELECT * FROM spatial_sightings {where} ORDER BY seen_at DESC LIMIT %s",
                    params,
                ).fetchall()
                return [self._serialize_sighting(r) for r in rows]

        return self._with_retry(_op)

    def get_spatial_sighting(self, sighting_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single spatial sighting by ID from PostgreSQL."""
        def _op() -> Optional[Dict[str, Any]]:
            with self._ensure_pool().connection() as conn:
                row = conn.execute(
                    "SELECT * FROM spatial_sightings WHERE id = %s",
                    (sighting_id,),
                ).fetchone()
                return self._serialize_sighting(row) if row else None

        return self._with_retry(_op)

    def update_spatial_sighting(self, sighting_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update mutable fields on a spatial sighting row in PostgreSQL."""
        def _op() -> Optional[Dict[str, Any]]:
            sets: List[str] = []
            params: List[Any] = []
            if "label" in updates and updates["label"] is not None:
                cleaned = str(updates["label"]).strip()
                if cleaned:
                    sets.append("label = %s")
                    params.append(cleaned)
            if "kind" in updates and updates["kind"] is not None:
                cleaned_k = str(updates["kind"]).strip().lower()
                if cleaned_k:
                    sets.append("kind = %s")
                    params.append(cleaned_k)
            if "notes" in updates and updates["notes"] is not None:
                sets.append("notes = %s")
                params.append(str(updates["notes"]))
            if "tags" in updates and updates["tags"] is not None:
                raw_tags = updates["tags"]
                tags = [str(t).strip() for t in raw_tags if str(t).strip()] if isinstance(raw_tags, list) else []
                sets.append("tags_json = %s::jsonb")
                params.append(json.dumps(tags))
            if "space_id" in updates:
                sets.append("space_id = %s")
                params.append(updates["space_id"])
            if "camera_source" in updates and updates["camera_source"] is not None:
                sets.append("camera_source = %s")
                params.append(str(updates["camera_source"]).strip() or "puppypi_fpv")
            if "archived" in updates and updates["archived"] is not None:
                next_arch = bool(updates["archived"])
                sets.append("archived = %s")
                params.append(next_arch)
                if next_arch:
                    sets.append("archived_at = COALESCE(archived_at, NOW())")
                else:
                    sets.append("archived_at = NULL")
            if not sets:
                return self.get_spatial_sighting(sighting_id)
            params.append(sighting_id)
            with self._ensure_pool().connection() as conn:
                row = conn.execute(
                    f"UPDATE spatial_sightings SET {', '.join(sets)} WHERE id = %s RETURNING *",
                    params,
                ).fetchone()
                conn.commit()
                return self._serialize_sighting(row) if row else None

        return self._with_retry(_op)

    def bulk_update_spatial_sightings(self, action: str, ids: Sequence[str]) -> int:
        """Apply bulk ``archive``, ``retrieve``, or ``delete`` across spatial sighting IDs in PostgreSQL."""
        id_list = [str(i) for i in ids if str(i).strip()]
        if not id_list:
            return 0
        act = str(action or "").strip().lower()

        def _op() -> int:
            with self._ensure_pool().connection() as conn:
                if act == "delete":
                    cur = conn.execute("DELETE FROM spatial_sightings WHERE id = ANY(%s)", (id_list,))
                elif act == "archive":
                    cur = conn.execute(
                        "UPDATE spatial_sightings SET archived = TRUE, archived_at = COALESCE(archived_at, NOW()) WHERE id = ANY(%s)",
                        (id_list,),
                    )
                elif act == "retrieve":
                    cur = conn.execute(
                        "UPDATE spatial_sightings SET archived = FALSE, archived_at = NULL WHERE id = ANY(%s)",
                        (id_list,),
                    )
                else:
                    return 0
                conn.commit()
                return int(cur.rowcount)

        return self._with_retry(_op)

    def count_spatial_sightings(
        self,
        space_id: Optional[str] = None,
        kind: Optional[str] = None,
        query: Optional[str] = None,
    ) -> Dict[str, int]:
        """Return ``{active, archived, total}`` counts for spatial sightings in PostgreSQL."""
        q = (query or "").strip()
        k = (kind or "").strip().lower()

        def _op() -> Dict[str, int]:
            clauses: List[str] = []
            params: List[Any] = []
            if k and k != "all":
                clauses.append("LOWER(kind) = %s")
                params.append(k)
            if space_id:
                clauses.append("space_id = %s")
                params.append(space_id)
            if q:
                clauses.append(
                    "(label ILIKE %s OR kind ILIKE %s OR notes ILIKE %s OR camera_source ILIKE %s OR tags_json::text ILIKE %s)"
                )
                like = f"%{q}%"
                params.extend([like, like, like, like, like])
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            with self._ensure_pool().connection() as conn:
                row = conn.execute(
                    f"""
                    SELECT
                        COUNT(*) FILTER (WHERE archived = FALSE) AS active_count,
                        COUNT(*) FILTER (WHERE archived = TRUE) AS archived_count,
                        COUNT(*) AS total_count
                    FROM spatial_sightings {where}
                    """,
                    params,
                ).fetchone()
                return {
                    "active": int(row["active_count"] or 0),
                    "archived": int(row["archived_count"] or 0),
                    "total": int(row["total_count"] or 0),
                }

        return self._with_retry(_op)

    def delete_spatial_sighting(self, sighting_id: str) -> bool:
        """Delete a spatial sighting row from PostgreSQL."""
        def _op() -> bool:
            with self._ensure_pool().connection() as conn:
                cur = conn.execute("DELETE FROM spatial_sightings WHERE id = %s", (sighting_id,))
                conn.commit()
                return cur.rowcount > 0

        return self._with_retry(_op)

    @staticmethod
    def _serialize_sentry_event(row: Dict[str, Any]) -> Dict[str, Any]:
        snap_id = row.get("snapshot_file_id")
        created = row.get("created_at")
        return {
            "id": str(row["id"]),
            "robot_id": str(row["robot_id"]),
            "trigger_type": str(row.get("trigger_type") or "lidar_motion"),
            "label": str(row.get("label") or "Alert"),
            "severity": str(row.get("severity") or "medium"),
            "detail": str(row.get("detail") or ""),
            "snapshot_file_id": snap_id,
            "snapshot_url": f"/api/files/{snap_id}" if snap_id else None,
            "spoken_alert": row.get("spoken_alert"),
            "created_at": created.isoformat() if isinstance(created, datetime) else str(created or ""),
        }

    def record_sentry_event(self, robot_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Insert a sentry alert event row into PostgreSQL."""
        eid = str(data.get("id") or uuid.uuid4())

        def _op() -> Dict[str, Any]:
            with self._ensure_pool().connection() as conn:
                row = conn.execute(
                    """
                    INSERT INTO sentry_events (
                        id, robot_id, trigger_type, label, severity, detail, snapshot_file_id, spoken_alert
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        eid,
                        robot_id,
                        str(data.get("trigger_type") or "lidar_motion"),
                        str(data.get("label") or "Alert"),
                        str(data.get("severity") or "medium"),
                        str(data.get("detail") or ""),
                        data.get("snapshot_file_id"),
                        data.get("spoken_alert"),
                    ),
                ).fetchone()
                conn.commit()
                return self._serialize_sentry_event(row)

        return self._with_retry(_op)

    def list_sentry_events(self, robot_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """List recent sentry alert events for ``robot_id`` from PostgreSQL."""
        def _op() -> List[Dict[str, Any]]:
            with self._ensure_pool().connection() as conn:
                rows = conn.execute(
                    "SELECT * FROM sentry_events WHERE robot_id = %s ORDER BY created_at DESC LIMIT %s",
                    (robot_id, max(1, int(limit))),
                ).fetchall()
                return [self._serialize_sentry_event(r) for r in rows]

        return self._with_retry(_op)

    def clear_sentry_events(self, robot_id: str) -> int:
        """Delete all sentry alert events for ``robot_id`` from PostgreSQL."""
        def _op() -> int:
            with self._ensure_pool().connection() as conn:
                cur = conn.execute("DELETE FROM sentry_events WHERE robot_id = %s", (robot_id,))
                conn.commit()
                return int(cur.rowcount)

        return self._with_retry(_op)

    @staticmethod
    def _serialize_scene_panel(row: Dict[str, Any]) -> Dict[str, Any]:
        pose = row.get("pose_json")
        if isinstance(pose, str):
            try:
                pose = json.loads(pose)
            except Exception:
                pose = {}
        mesh = row.get("mesh_json")
        if isinstance(mesh, str):
            try:
                mesh = json.loads(mesh)
            except Exception:
                mesh = {}
        q_metrics = row.get("quality_metrics_json")
        if isinstance(q_metrics, str):
            try:
                q_metrics = json.loads(q_metrics)
            except Exception:
                q_metrics = None
        tex_id = row.get("texture_file_id")
        norm_id = row.get("normal_map_file_id")
        norm_url = row.get("normal_map_url") or (f"/api/files/{norm_id}" if norm_id else None)
        glb_id = row.get("glb_file_id")
        created = row.get("created_at")
        return {
            "id": str(row["id"]),
            "space_id": str(row["space_id"]),
            "robot_id": str(row["robot_id"]) if row.get("robot_id") is not None else None,
            "label": str(row.get("label") or "Front Wall"),
            "stage": str(row.get("stage") or "single_wall"),
            "pose": dict(pose or {}),
            "lidar_calibrated": bool(row.get("lidar_calibrated", False)),
            "lidar_ray_count": int(row.get("lidar_ray_count", 0)),
            "depth_source": str(row.get("depth_source") or "geometric_relief"),
            "mean_distance_m": round(float(row.get("mean_distance_m", 1.8)), 3),
            "min_distance_m": round(float(row.get("min_distance_m", 1.0)), 3),
            "max_distance_m": round(float(row.get("max_distance_m", 2.5)), 3),
            "vertex_count": int(row.get("vertex_count", 0)),
            "triangle_count": int(row.get("triangle_count", 0)),
            "texture_file_id": str(tex_id) if tex_id else None,
            "texture_url": f"/api/files/{tex_id}" if tex_id else None,
            "normal_map_file_id": str(norm_id) if norm_id else None,
            "normal_map_url": str(norm_url) if norm_url else None,
            "glb_file_id": str(glb_id) if glb_id else None,
            "glb_url": f"/api/files/{glb_id}" if glb_id else None,
            "quality_metrics": dict(q_metrics) if isinstance(q_metrics, dict) else None,
            "mesh": dict(mesh or {}),
            "created_at": created.isoformat() if isinstance(created, datetime) else str(created or ""),
        }

    def save_scene_panel(self, panel: Dict[str, Any]) -> Dict[str, Any]:
        """Insert or upsert a reconstructed 3D scene panel row in PostgreSQL."""
        pid = str(panel.get("id") or uuid.uuid4())
        pose_json = json.dumps(panel.get("pose") or {})
        mesh_json = json.dumps(panel.get("mesh") or {})
        q_metrics = panel.get("quality_metrics")
        q_metrics_json = json.dumps(q_metrics) if isinstance(q_metrics, dict) else None
        norm_id = panel.get("normal_map_file_id")
        norm_url = panel.get("normal_map_url") or (f"/api/files/{norm_id}" if norm_id else None)

        def _op() -> Dict[str, Any]:
            with self._ensure_pool().connection() as conn:
                row = conn.execute(
                    """
                    INSERT INTO scene_panels (
                        id, space_id, robot_id, label, stage, pose_json,
                        lidar_calibrated, lidar_ray_count, depth_source,
                        mean_distance_m, min_distance_m, max_distance_m,
                        vertex_count, triangle_count, texture_file_id,
                        normal_map_file_id, normal_map_url, glb_file_id,
                        quality_metrics_json, mesh_json
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s::jsonb,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s::jsonb, %s::jsonb
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        label = EXCLUDED.label,
                        stage = EXCLUDED.stage,
                        pose_json = EXCLUDED.pose_json,
                        lidar_calibrated = EXCLUDED.lidar_calibrated,
                        lidar_ray_count = EXCLUDED.lidar_ray_count,
                        depth_source = EXCLUDED.depth_source,
                        mean_distance_m = EXCLUDED.mean_distance_m,
                        min_distance_m = EXCLUDED.min_distance_m,
                        max_distance_m = EXCLUDED.max_distance_m,
                        vertex_count = EXCLUDED.vertex_count,
                        triangle_count = EXCLUDED.triangle_count,
                        texture_file_id = EXCLUDED.texture_file_id,
                        normal_map_file_id = EXCLUDED.normal_map_file_id,
                        normal_map_url = EXCLUDED.normal_map_url,
                        glb_file_id = EXCLUDED.glb_file_id,
                        quality_metrics_json = EXCLUDED.quality_metrics_json,
                        mesh_json = EXCLUDED.mesh_json
                    RETURNING *
                    """,
                    (
                        pid,
                        str(panel["space_id"]),
                        panel.get("robot_id"),
                        str(panel.get("label") or "Front Wall"),
                        str(panel.get("stage") or "single_wall"),
                        pose_json,
                        bool(panel.get("lidar_calibrated", False)),
                        int(panel.get("lidar_ray_count", 0)),
                        str(panel.get("depth_source") or "geometric_relief"),
                        float(panel.get("mean_distance_m", 1.8)),
                        float(panel.get("min_distance_m", 1.0)),
                        float(panel.get("max_distance_m", 2.5)),
                        int(panel.get("vertex_count", 0)),
                        int(panel.get("triangle_count", 0)),
                        panel.get("texture_file_id"),
                        norm_id,
                        norm_url,
                        panel.get("glb_file_id"),
                        q_metrics_json,
                        mesh_json,
                    ),
                ).fetchone()
                conn.commit()
                return self._serialize_scene_panel(row)

        return self._with_retry(_op)

    def list_scene_panels(self, space_id: str) -> List[Dict[str, Any]]:
        """List all reconstructed 3D scene panels for ``space_id`` from PostgreSQL."""
        def _op() -> List[Dict[str, Any]]:
            with self._ensure_pool().connection() as conn:
                rows = conn.execute(
                    "SELECT * FROM scene_panels WHERE space_id = %s ORDER BY created_at ASC",
                    (space_id,),
                ).fetchall()
                return [self._serialize_scene_panel(r) for r in rows]

        return self._with_retry(_op)

    def get_scene_panel(self, panel_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single reconstructed 3D scene panel by ID from PostgreSQL."""
        def _op() -> Optional[Dict[str, Any]]:
            with self._ensure_pool().connection() as conn:
                row = conn.execute(
                    "SELECT * FROM scene_panels WHERE id = %s",
                    (panel_id,),
                ).fetchone()
                return self._serialize_scene_panel(row) if row else None

        return self._with_retry(_op)

    def delete_scene_panel(self, panel_id: str) -> bool:
        """Delete a reconstructed 3D scene panel by ID from PostgreSQL."""
        def _op() -> bool:
            with self._ensure_pool().connection() as conn:
                cur = conn.execute("DELETE FROM scene_panels WHERE id = %s", (panel_id,))
                conn.commit()
                return cur.rowcount > 0

        return self._with_retry(_op)

    def clear_scene_panels(self, space_id: str) -> int:
        """Delete all reconstructed 3D scene panels for ``space_id`` from PostgreSQL."""
        def _op() -> int:
            with self._ensure_pool().connection() as conn:
                cur = conn.execute("DELETE FROM scene_panels WHERE space_id = %s", (space_id,))
                conn.commit()
                return int(cur.rowcount)

        return self._with_retry(_op)

    @staticmethod
    def _serialize_inventory_item(row: Dict[str, Any]) -> Dict[str, Any]:
        ifaces = row.get("interfaces_json")
        if isinstance(ifaces, str):
            try:
                ifaces = json.loads(ifaces)
            except Exception:
                ifaces = []
        caps = row.get("capabilities_json")
        if isinstance(caps, str):
            try:
                caps = json.loads(caps)
            except Exception:
                caps = []
        created = row.get("created_at")
        updated = row.get("updated_at")
        return {
            "id": str(row["id"]),
            "name": str(row.get("name") or ""),
            "profile_id": row.get("profile_id"),
            "category": str(row.get("category") or "accessory"),
            "manufacturer": str(row.get("manufacturer") or ""),
            "model": str(row.get("model") or ""),
            "quantity": int(row.get("quantity", 1)),
            "status": str(row.get("status") or "available"),
            "location": str(row.get("location") or ""),
            "interfaces": [str(x) for x in ifaces] if isinstance(ifaces, list) else [],
            "voltage_v": float(row["voltage_v"]) if row.get("voltage_v") is not None else None,
            "current_ma": int(row["current_ma"]) if row.get("current_ma") is not None else None,
            "capabilities": [str(x) for x in caps] if isinstance(caps, list) else [],
            "notes": str(row.get("notes") or ""),
            "est_cost_usd": float(row["est_cost_usd"]) if row.get("est_cost_usd") is not None else None,
            "created_at": created.isoformat() if isinstance(created, datetime) else str(created or ""),
            "updated_at": updated.isoformat() if isinstance(updated, datetime) else str(updated or ""),
        }

    def list_inventory_items(
        self,
        status: Optional[str] = None,
        category: Optional[str] = None,
        query: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List lab hardware inventory items from PostgreSQL with optional filters."""
        st = (status or "").strip().lower()
        cat = (category or "").strip().lower()
        q = (query or "").strip()

        def _op() -> List[Dict[str, Any]]:
            clauses: List[str] = []
            params: List[Any] = []
            if st and st != "all":
                if st == "owned":
                    clauses.append("status IN ('available', 'deployed')")
                else:
                    clauses.append("LOWER(status) = %s")
                    params.append(st)
            if cat and cat != "all":
                clauses.append("LOWER(category) = %s")
                params.append(cat)
            if q:
                clauses.append(
                    "(name ILIKE %s OR manufacturer ILIKE %s OR model ILIKE %s OR location ILIKE %s OR notes ILIKE %s OR COALESCE(profile_id, '') ILIKE %s OR interfaces_json::text ILIKE %s OR capabilities_json::text ILIKE %s)"
                )
                like = f"%{q}%"
                params.extend([like] * 8)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            with self._ensure_pool().connection() as conn:
                rows = conn.execute(
                    f"SELECT * FROM inventory_items {where} ORDER BY category ASC, LOWER(name) ASC",
                    params,
                ).fetchall()
                return [self._serialize_inventory_item(r) for r in rows]

        return self._with_retry(_op)

    def get_inventory_item(self, item_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single lab hardware inventory item by ID from PostgreSQL."""
        def _op() -> Optional[Dict[str, Any]]:
            with self._ensure_pool().connection() as conn:
                row = conn.execute("SELECT * FROM inventory_items WHERE id = %s", (item_id,)).fetchone()
                return self._serialize_inventory_item(row) if row else None

        return self._with_retry(_op)

    def create_inventory_item(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Insert a new lab hardware inventory item into PostgreSQL."""
        name = str(data.get("name") or "").strip()
        if not name:
            raise ValueError("Inventory item name is required")
        iid = str(data.get("id") or uuid.uuid4())
        ifaces = [str(x).strip() for x in (data.get("interfaces") or []) if str(x).strip()]
        caps = [str(x).strip() for x in (data.get("capabilities") or []) if str(x).strip()]

        def _op() -> Dict[str, Any]:
            with self._ensure_pool().connection() as conn:
                row = conn.execute(
                    """
                    INSERT INTO inventory_items (
                        id, name, profile_id, category, manufacturer, model, quantity,
                        status, location, interfaces_json, voltage_v, current_ma,
                        capabilities_json, notes, est_cost_usd
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s::jsonb, %s, %s)
                    RETURNING *
                    """,
                    (
                        iid,
                        name,
                        data.get("profile_id"),
                        str(data.get("category") or "accessory").strip().lower(),
                        str(data.get("manufacturer") or ""),
                        str(data.get("model") or ""),
                        max(0, int(data.get("quantity", 1))),
                        str(data.get("status") or "available").strip().lower(),
                        str(data.get("location") or ""),
                        json.dumps(ifaces),
                        float(data["voltage_v"]) if data.get("voltage_v") is not None else None,
                        int(data["current_ma"]) if data.get("current_ma") is not None else None,
                        json.dumps(caps),
                        str(data.get("notes") or ""),
                        float(data["est_cost_usd"]) if data.get("est_cost_usd") is not None else None,
                    ),
                ).fetchone()
                conn.commit()
                return self._serialize_inventory_item(row)

        return self._with_retry(_op)

    def update_inventory_item(self, item_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update mutable fields on a lab hardware inventory item in PostgreSQL."""
        def _op() -> Optional[Dict[str, Any]]:
            sets: List[str] = []
            params: List[Any] = []
            if "name" in updates and updates["name"] is not None:
                cleaned = str(updates["name"]).strip()
                if cleaned:
                    sets.append("name = %s")
                    params.append(cleaned)
            if "profile_id" in updates:
                sets.append("profile_id = %s")
                params.append(updates["profile_id"])
            if "category" in updates and updates["category"] is not None:
                sets.append("category = %s")
                params.append(str(updates["category"]).strip().lower())
            if "manufacturer" in updates and updates["manufacturer"] is not None:
                sets.append("manufacturer = %s")
                params.append(str(updates["manufacturer"]))
            if "model" in updates and updates["model"] is not None:
                sets.append("model = %s")
                params.append(str(updates["model"]))
            if "quantity" in updates and updates["quantity"] is not None:
                sets.append("quantity = %s")
                params.append(max(0, int(updates["quantity"])))
            if "status" in updates and updates["status"] is not None:
                sets.append("status = %s")
                params.append(str(updates["status"]).strip().lower())
            if "location" in updates and updates["location"] is not None:
                sets.append("location = %s")
                params.append(str(updates["location"]))
            if "interfaces" in updates and updates["interfaces"] is not None:
                ifaces = [str(x).strip() for x in updates["interfaces"] if str(x).strip()]
                sets.append("interfaces_json = %s::jsonb")
                params.append(json.dumps(ifaces))
            if "voltage_v" in updates:
                sets.append("voltage_v = %s")
                params.append(float(updates["voltage_v"]) if updates["voltage_v"] is not None else None)
            if "current_ma" in updates:
                sets.append("current_ma = %s")
                params.append(int(updates["current_ma"]) if updates["current_ma"] is not None else None)
            if "capabilities" in updates and updates["capabilities"] is not None:
                caps = [str(x).strip() for x in updates["capabilities"] if str(x).strip()]
                sets.append("capabilities_json = %s::jsonb")
                params.append(json.dumps(caps))
            if "notes" in updates and updates["notes"] is not None:
                sets.append("notes = %s")
                params.append(str(updates["notes"]))
            if "est_cost_usd" in updates:
                sets.append("est_cost_usd = %s")
                params.append(float(updates["est_cost_usd"]) if updates["est_cost_usd"] is not None else None)
            if not sets:
                return self.get_inventory_item(item_id)
            sets.append("updated_at = NOW()")
            params.append(item_id)
            with self._ensure_pool().connection() as conn:
                row = conn.execute(
                    f"UPDATE inventory_items SET {', '.join(sets)} WHERE id = %s RETURNING *",
                    params,
                ).fetchone()
                conn.commit()
                return self._serialize_inventory_item(row) if row else None

        return self._with_retry(_op)

    def delete_inventory_item(self, item_id: str) -> bool:
        """Delete a lab hardware inventory item by ID from PostgreSQL."""
        def _op() -> bool:
            with self._ensure_pool().connection() as conn:
                cur = conn.execute("DELETE FROM inventory_items WHERE id = %s", (item_id,))
                conn.commit()
                return cur.rowcount > 0

        return self._with_retry(_op)

    def count_inventory_items(self) -> Dict[str, int]:
        """Return ``{owned, wishlist, deployed, total}`` summary counts from PostgreSQL."""
        def _op() -> Dict[str, int]:
            with self._ensure_pool().connection() as conn:
                row = conn.execute(
                    """
                    SELECT
                        COUNT(*) FILTER (WHERE status IN ('available', 'deployed')) AS owned_count,
                        COUNT(*) FILTER (WHERE status = 'wishlist') AS wishlist_count,
                        COUNT(*) FILTER (WHERE status = 'deployed') AS deployed_count,
                        COUNT(*) AS total_count
                    FROM inventory_items
                    """
                ).fetchone()
                return {
                    "owned": int(row["owned_count"] or 0),
                    "wishlist": int(row["wishlist_count"] or 0),
                    "deployed": int(row["deployed_count"] or 0),
                    "total": int(row["total_count"] or 0),
                }

        return self._with_retry(_op)

    @staticmethod
    def _serialize_managed_device(row: Dict[str, Any]) -> Dict[str, Any]:
        cfg = row.get("config_json")
        if isinstance(cfg, str):
            try:
                cfg = json.loads(cfg)
            except Exception:
                cfg = {}
        created = row.get("created_at")
        last_seen = row.get("last_seen_at")
        return {
            "id": str(row["id"]),
            "name": str(row.get("name") or ""),
            "profile_id": str(row.get("profile_id") or "custom"),
            "space_id": row.get("space_id"),
            "transport": str(row.get("transport") or "usb"),
            "endpoint": str(row.get("endpoint") or ""),
            "status": str(row.get("status") or "offline"),
            "config": dict(cfg) if isinstance(cfg, dict) else {},
            "last_seen_at": last_seen.isoformat() if isinstance(last_seen, datetime) else last_seen,
            "created_at": created.isoformat() if isinstance(created, datetime) else str(created or ""),
        }

    def list_managed_devices(
        self,
        profile_id: Optional[str] = None,
        space_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List registered non-robot managed devices from PostgreSQL."""
        def _op() -> List[Dict[str, Any]]:
            clauses: List[str] = []
            params: List[Any] = []
            if profile_id:
                clauses.append("profile_id = %s")
                params.append(profile_id)
            if space_id:
                clauses.append("space_id = %s")
                params.append(space_id)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            with self._ensure_pool().connection() as conn:
                rows = conn.execute(
                    f"SELECT * FROM managed_devices {where} ORDER BY created_at DESC",
                    params,
                ).fetchall()
                return [self._serialize_managed_device(r) for r in rows]

        return self._with_retry(_op)

    def get_managed_device(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single managed device by ID from PostgreSQL."""
        def _op() -> Optional[Dict[str, Any]]:
            with self._ensure_pool().connection() as conn:
                row = conn.execute("SELECT * FROM managed_devices WHERE id = %s", (device_id,)).fetchone()
                return self._serialize_managed_device(row) if row else None

        return self._with_retry(_op)

    def create_managed_device(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Insert a new managed device row into PostgreSQL."""
        name = str(data.get("name") or "").strip()
        if not name:
            raise ValueError("Managed device name is required")
        did = str(data.get("id") or uuid.uuid4())
        cfg = data.get("config") if isinstance(data.get("config"), dict) else {}

        def _op() -> Dict[str, Any]:
            with self._ensure_pool().connection() as conn:
                row = conn.execute(
                    """
                    INSERT INTO managed_devices (
                        id, name, profile_id, space_id, transport, endpoint, status, config_json, last_seen_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                    RETURNING *
                    """,
                    (
                        did,
                        name,
                        str(data.get("profile_id") or "custom"),
                        data.get("space_id"),
                        str(data.get("transport") or "usb").strip().lower(),
                        str(data.get("endpoint") or ""),
                        str(data.get("status") or "offline").strip().lower(),
                        json.dumps(cfg),
                        data.get("last_seen_at"),
                    ),
                ).fetchone()
                conn.commit()
                return self._serialize_managed_device(row)

        return self._with_retry(_op)

    def update_managed_device(self, device_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update mutable fields on a managed device row in PostgreSQL."""
        def _op() -> Optional[Dict[str, Any]]:
            sets: List[str] = []
            params: List[Any] = []
            for col in ("name", "profile_id", "transport", "endpoint", "status"):
                if col in updates and updates[col] is not None:
                    val = str(updates[col]).strip()
                    if col in ("transport", "status"):
                        val = val.lower()
                    if col != "name" or val:
                        sets.append(f"{col} = %s")
                        params.append(val)
            if "space_id" in updates:
                sets.append("space_id = %s")
                params.append(updates["space_id"])
            if "last_seen_at" in updates:
                sets.append("last_seen_at = %s")
                params.append(updates["last_seen_at"])
            if "config" in updates and isinstance(updates["config"], dict):
                sets.append("config_json = %s::jsonb")
                params.append(json.dumps(updates["config"]))
            if not sets:
                return self.get_managed_device(device_id)
            params.append(device_id)
            with self._ensure_pool().connection() as conn:
                row = conn.execute(
                    f"UPDATE managed_devices SET {', '.join(sets)} WHERE id = %s RETURNING *",
                    params,
                ).fetchone()
                conn.commit()
                return self._serialize_managed_device(row) if row else None

        return self._with_retry(_op)

    def delete_managed_device(self, device_id: str) -> bool:
        """Delete a managed device by ID from PostgreSQL."""
        def _op() -> bool:
            with self._ensure_pool().connection() as conn:
                cur = conn.execute("DELETE FROM managed_devices WHERE id = %s", (device_id,))
                conn.commit()
                return cur.rowcount > 0

        return self._with_retry(_op)

    @staticmethod
    def _serialize_design_blueprint(row: Dict[str, Any]) -> Dict[str, Any]:
        bp = row.get("blueprint_json")
        if isinstance(bp, str):
            try:
                bp = json.loads(bp)
            except Exception:
                bp = {}
        out = dict(bp) if isinstance(bp, dict) else {}
        created = row.get("created_at")
        updated = row.get("updated_at")
        out["id"] = str(row["id"])
        out["title"] = str(row.get("title") or out.get("title") or "Untitled Blueprint")
        out["idea"] = str(row.get("idea") or out.get("idea") or "")
        out["verdict"] = str(out.get("verdict") or row.get("feasibility") or "buildable_now")
        out["feasibility_score"] = int(
            out["feasibility_score"]
            if out.get("feasibility_score") is not None
            else row.get("score", 80)
        )
        out["creativity_level"] = int(row.get("creativity_level", out.get("creativity_level", 3)))
        out["persona"] = str(row.get("persona") or out.get("persona") or "systems_architect")
        out["model_used"] = str(row.get("model_used") or out.get("model_used") or "")
        out["created_at"] = created.isoformat() if isinstance(created, datetime) else str(created or "")
        out["updated_at"] = updated.isoformat() if isinstance(updated, datetime) else str(updated or "")
        return out

    def save_design_blueprint(self, blueprint: Dict[str, Any]) -> Dict[str, Any]:
        """Insert or update a Co-Design Architect blueprint in PostgreSQL."""
        bid = str(blueprint.get("id") or uuid.uuid4())
        title = str(blueprint.get("title") or blueprint.get("idea") or "Untitled Blueprint")[:160]
        idea = str(blueprint.get("idea") or "")
        verdict = str(blueprint.get("verdict") or blueprint.get("feasibility") or "buildable_now")
        score = int(
            blueprint.get("feasibility_score")
            if blueprint.get("feasibility_score") is not None
            else blueprint.get("score", 80)
        )
        creativity_level = int(blueprint.get("creativity_level", 3))
        persona = str(blueprint.get("persona") or "systems_architect")
        model_used = str(blueprint.get("model_used") or "")
        payload = {**blueprint, "id": bid, "verdict": verdict, "feasibility_score": score}

        def _op() -> Dict[str, Any]:
            with self._ensure_pool().connection() as conn:
                row = conn.execute(
                    """
                    INSERT INTO design_blueprints (
                        id, title, idea, feasibility, score, creativity_level, persona, model_used, blueprint_json
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT (id) DO UPDATE SET
                        title = EXCLUDED.title,
                        idea = EXCLUDED.idea,
                        feasibility = EXCLUDED.feasibility,
                        score = EXCLUDED.score,
                        creativity_level = EXCLUDED.creativity_level,
                        persona = EXCLUDED.persona,
                        model_used = EXCLUDED.model_used,
                        blueprint_json = EXCLUDED.blueprint_json,
                        updated_at = NOW()
                    RETURNING *
                    """,
                    (
                        bid,
                        title,
                        idea,
                        verdict,
                        score,
                        creativity_level,
                        persona,
                        model_used,
                        json.dumps(payload),
                    ),
                ).fetchone()
                conn.commit()
                return self._serialize_design_blueprint(row)

        return self._with_retry(_op)

    def list_design_blueprints(self, limit: int = 50) -> List[Dict[str, Any]]:
        """List saved Co-Design Architect blueprints from PostgreSQL ordered newest updated first."""
        def _op() -> List[Dict[str, Any]]:
            with self._ensure_pool().connection() as conn:
                rows = conn.execute(
                    "SELECT * FROM design_blueprints ORDER BY updated_at DESC LIMIT %s",
                    (max(1, int(limit)),),
                ).fetchall()
                return [self._serialize_design_blueprint(r) for r in rows]

        return self._with_retry(_op)

    def get_design_blueprint(self, blueprint_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single Co-Design Architect blueprint by ID from PostgreSQL."""
        def _op() -> Optional[Dict[str, Any]]:
            with self._ensure_pool().connection() as conn:
                row = conn.execute("SELECT * FROM design_blueprints WHERE id = %s", (blueprint_id,)).fetchone()
                return self._serialize_design_blueprint(row) if row else None

        return self._with_retry(_op)

    def delete_design_blueprint(self, blueprint_id: str) -> bool:
        """Delete a Co-Design Architect blueprint by ID from PostgreSQL."""
        def _op() -> bool:
            with self._ensure_pool().connection() as conn:
                cur = conn.execute("DELETE FROM design_blueprints WHERE id = %s", (blueprint_id,))
                conn.commit()
                return cur.rowcount > 0

        return self._with_retry(_op)

    @staticmethod
    def _serialize_early_bird_public(row: Dict[str, Any]) -> Dict[str, Any]:
        hw = row.get("hardware_stack")
        if isinstance(hw, str):
            try:
                hw = json.loads(hw)
            except Exception:
                hw = []
        created = row.get("created_at")
        return {
            "spot_number": int(row["spot_number"]),
            "founder_code": str(row["founder_code"]),
            "display_name": str(row["display_name"]),
            "role": str(row.get("role") or "Maker"),
            "hardware_stack": [str(x) for x in hw] if isinstance(hw, list) else [],
            "created_at": created.isoformat() if isinstance(created, datetime) else str(created or ""),
        }

    def list_early_bird_signups(self, limit: int = 50) -> List[Dict[str, Any]]:
        """List anonymized Early Bird Maker signups from PostgreSQL ordered newest spot first."""
        def _op() -> List[Dict[str, Any]]:
            with self._ensure_pool().connection() as conn:
                rows = conn.execute(
                    """
                    SELECT spot_number, founder_code, display_name, role, hardware_stack, created_at
                    FROM early_bird_signups
                    ORDER BY spot_number DESC
                    LIMIT %s
                    """,
                    (max(1, int(limit)),),
                ).fetchall()
                return [self._serialize_early_bird_public(r) for r in rows]

        return self._with_retry(_op)

    def claim_early_bird_spot(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Atomically claim a sequential Early Bird Maker spot in PostgreSQL (strictly capped at 50)."""
        name = str(data.get("name") or "").strip()
        email = str(data.get("email") or "").strip().lower()
        if len(name) < 2 or not email:
            raise ValueError("invalid_early_bird_input")
        display_name = _anonymize_maker_name(name)
        role = str(data.get("role") or "Maker").strip()[:64] or "Maker"
        hw_stack = _normalize_hardware_stack(data.get("hardware_stack"))
        goal = str(data.get("project_goal") or "").strip()[:500]
        sid = str(uuid.uuid4())

        def _op() -> Dict[str, Any]:
            with self._ensure_pool().connection() as conn:
                conn.execute("LOCK TABLE early_bird_signups IN EXCLUSIVE MODE")
                dup = conn.execute(
                    "SELECT 1 FROM early_bird_signups WHERE LOWER(email) = %s",
                    (email,),
                ).fetchone()
                if dup:
                    conn.rollback()
                    raise ValueError("email_already_claimed")
                cnt_row = conn.execute("SELECT COUNT(*) AS c FROM early_bird_signups").fetchone()
                claimed = int(cnt_row["c"] or 0)
                if claimed >= EARLY_BIRD_MAX_SPOTS:
                    conn.rollback()
                    raise ValueError("early_bird_full")
                spot_number = claimed + 1
                founder_code = f"EIGENIA-MAKER-{spot_number:02d}"
                row = conn.execute(
                    """
                    INSERT INTO early_bird_signups (
                        id, spot_number, founder_code, name, display_name, email, role, hardware_stack, project_goal
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                    RETURNING spot_number, founder_code, display_name, role, hardware_stack, created_at
                    """,
                    (sid, spot_number, founder_code, name, display_name, email, role, json.dumps(hw_stack), goal),
                ).fetchone()
                conn.commit()
                pub = self._serialize_early_bird_public(row)
                return {
                    "ok": True,
                    "spot_number": pub["spot_number"],
                    "total_spots": EARLY_BIRD_MAX_SPOTS,
                    "remaining_spots": max(0, EARLY_BIRD_MAX_SPOTS - pub["spot_number"]),
                    "founder_code": pub["founder_code"],
                    "display_name": pub["display_name"],
                    "role": pub["role"],
                    "hardware_stack": pub["hardware_stack"],
                    "claimed_at": pub["created_at"],
                }

        return self._with_retry(_op)

    def get_early_bird_status(self) -> Dict[str, Any]:
        """Return Early Bird 50-Maker campaign status and anonymized recent makers from PostgreSQL."""
        def _op() -> Dict[str, Any]:
            with self._ensure_pool().connection() as conn:
                cnt_row = conn.execute("SELECT COUNT(*) AS c FROM early_bird_signups").fetchone()
                claimed = int(cnt_row["c"] or 0)
                rows = conn.execute(
                    """
                    SELECT spot_number, founder_code, display_name, role, hardware_stack, created_at
                    FROM early_bird_signups
                    ORDER BY spot_number DESC
                    LIMIT 12
                    """
                ).fetchall()
                recent = [self._serialize_early_bird_public(r) for r in rows]
                return {
                    "campaign": "Eigenia TwinScan Founding 50 Makers",
                    "total_spots": EARLY_BIRD_MAX_SPOTS,
                    "claimed_spots": claimed,
                    "remaining_spots": max(0, EARLY_BIRD_MAX_SPOTS - claimed),
                    "is_open": claimed < EARLY_BIRD_MAX_SPOTS,
                    "perks": list(EARLY_BIRD_PERKS),
                    "recent_makers": recent,
                }

        return self._with_retry(_op)



