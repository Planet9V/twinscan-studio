"""Data models and PostgreSQL/in-memory persistence for Room Twin Studio."""

from __future__ import annotations

import json
import sys
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

ROOM_STUDIO_SETTING_KEY = "room_studio_projects_json"

VALID_SURFACES = frozenset(
    {
        "north_wall",
        "east_wall",
        "south_wall",
        "west_wall",
        "floor",
        "ceiling",
        "object_closeup",
        "overview",
    }
)

VALID_SUPPORT_TYPES = frozenset({"WALL_MOUNTED", "ON_FLOOR", "ON_SURFACE", "CEILING"})

DEFAULT_SURFACE_CAMERA_POSES: Dict[str, Dict[str, float]] = {
    "north_wall": {"x": 0.0, "y": 1.35, "z": 1.4, "yaw_deg": 0.0, "pitch_deg": -5.0},
    "south_wall": {"x": 0.0, "y": 1.35, "z": -1.4, "yaw_deg": 180.0, "pitch_deg": -5.0},
    "east_wall": {"x": -1.4, "y": 1.35, "z": 0.0, "yaw_deg": 90.0, "pitch_deg": -5.0},
    "west_wall": {"x": 1.4, "y": 1.35, "z": 0.0, "yaw_deg": -90.0, "pitch_deg": -5.0},
    "floor": {"x": 0.0, "y": 1.75, "z": 1.2, "yaw_deg": 0.0, "pitch_deg": -55.0},
    "ceiling": {"x": 0.0, "y": 1.0, "z": 0.0, "yaw_deg": 0.0, "pitch_deg": 65.0},
    "object_closeup": {"x": 0.0, "y": 1.2, "z": 0.9, "yaw_deg": 0.0, "pitch_deg": -10.0},
    "overview": {"x": 1.8, "y": 1.65, "z": 1.8, "yaw_deg": -45.0, "pitch_deg": -20.0},
}


def make_default_project(
    name: str = "My Studio Room",
    width_m: float = 4.6,
    length_m: float = 4.2,
    height_m: float = 2.6,
) -> Dict[str, Any]:
    """Create a fresh Room Studio project record with metric dimensions."""
    now = time.time()
    return {
        "id": f"room_{uuid.uuid4().hex[:10]}",
        "name": str(name).strip() or "My Studio Room",
        "width_m": max(1.5, min(30.0, float(width_m))),
        "length_m": max(1.5, min(30.0, float(length_m))),
        "height_m": max(1.8, min(10.0, float(height_m))),
        "splat_file_id": None,
        "splat_filename": None,
        "splat_format": None,
        "wall_textures": {},
        "photos": [],
        "objects": [],
        "created_at": now,
        "updated_at": now,
    }


class RoomStudioStore:
    """Thread-safe repository storing Room Studio projects in PostgreSQL ``app_settings``."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._repo: Any = None
        self._projects: Dict[str, Dict[str, Any]] = {}

    def attach_repository(self, repo: Any) -> int:
        """Attach the TwinScan repository and hydrate saved Room Studio projects.

        Args:
            repo: Repository implementing ``get_settings_raw`` and ``upsert_settings``.

        Returns:
            Number of loaded Room Studio projects.
        """
        self._repo = repo
        if repo is None:
            return 0
        getter = getattr(repo, "get_settings_raw", None) or getattr(repo, "get_raw_settings", None)
        if getter is None:
            return 0
        try:
            raw = getter() or {}
            blob = str(raw.get(ROOM_STUDIO_SETTING_KEY) or "").strip()
            if not blob:
                return 0
            parsed = json.loads(blob)
            if not isinstance(parsed, dict):
                return 0
            with self._lock:
                self._projects = {str(k): dict(v) for k, v in parsed.items() if isinstance(v, dict)}
                return len(self._projects)
        except Exception as exc:
            sys.stderr.write(f"[room_studio.store] Failed loading projects: {exc}\n")
            return 0

    def _persist(self) -> None:
        if self._repo is None or not hasattr(self._repo, "upsert_settings"):
            return
        try:
            with self._lock:
                payload = json.dumps(self._projects)
            self._repo.upsert_settings({ROOM_STUDIO_SETTING_KEY: payload}, source_ip="room_studio")
        except Exception as exc:
            sys.stderr.write(f"[room_studio.store] Failed persisting projects: {exc}\n")

    def list_projects(self) -> List[Dict[str, Any]]:
        """Return all Room Studio projects sorted by most recently updated."""
        with self._lock:
            items = [dict(p) for p in self._projects.values()]
        items.sort(key=lambda p: float(p.get("updated_at") or 0.0), reverse=True)
        return items

    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single Room Studio project by ID."""
        with self._lock:
            proj = self._projects.get(project_id)
            return dict(proj) if proj is not None else None

    def create_project(
        self,
        *,
        name: str,
        width_m: float = 4.6,
        length_m: float = 4.2,
        height_m: float = 2.6,
    ) -> Dict[str, Any]:
        """Create and persist a new Room Studio project."""
        proj = make_default_project(name=name, width_m=width_m, length_m=length_m, height_m=height_m)
        with self._lock:
            self._projects[proj["id"]] = proj
        self._persist()
        return dict(proj)

    def save_project(self, project: Dict[str, Any]) -> Dict[str, Any]:
        """Save an updated Room Studio project record."""
        project["updated_at"] = time.time()
        with self._lock:
            self._projects[str(project["id"])] = dict(project)
        self._persist()
        return dict(project)

    def delete_project(self, project_id: str) -> bool:
        """Delete a Room Studio project by ID."""
        with self._lock:
            existed = project_id in self._projects
            self._projects.pop(project_id, None)
        if existed:
            self._persist()
        return existed
