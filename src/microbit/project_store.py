"""PostgreSQL 18 / In-Memory persistence for micro:bit v2.2 Prototype Projects."""

from __future__ import annotations

import json
import sys
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from src.microbit.catalog import STARTER_TEMPLATES, validate_project_wiring
from src.microbit.enclosure_cad import (
    compute_layout_envelope,
    default_attachment_position_mm,
    default_enclosure_config,
    sanitize_custom_shapes,
    sanitize_enclosure_config,
)

MICROBIT_PROJECTS_SETTING_KEY = "microbit_projects_json"


def _default_project(name: str = "micro:bit v2.2 Interactive Prototype") -> Dict[str, Any]:
    now = time.time()
    attachments = [
        {
            "id": f"att_{uuid.uuid4().hex[:6]}",
            "accessory_id": "sg90_servo",
            "label": "SG90 Micro Servo",
            "pin": "P0",
            "secondary_pin": None,
        },
        {
            "id": f"att_{uuid.uuid4().hex[:6]}",
            "accessory_id": "neopixel_8",
            "label": "NeoPixel RGB Strip",
            "pin": "P1",
            "secondary_pin": None,
        },
    ]
    sim_rules = [
        {
            "trigger": "lift",
            "led_icon": "SURPRISED",
            "speak_text": "Weeee!",
            "sound_effect": "slide",
            "servo_angle": 90,
            "neopixel_hex": "#22d3ee",
        },
        {
            "trigger": "button_a",
            "led_icon": "HEART",
            "speak_text": "",
            "sound_effect": "chime",
            "servo_angle": 180,
            "neopixel_hex": "#a855f7",
        },
        {
            "trigger": "button_b",
            "led_icon": "HAPPY",
            "speak_text": "",
            "sound_effect": "giggle",
            "servo_angle": 0,
            "neopixel_hex": "#22c55e",
        },
    ]
    return {
        "id": f"mb_{uuid.uuid4().hex[:8]}",
        "name": name,
        "board_id": "microbit_v2",
        "description": "Interactive 3D pinout prototype with AI Co-Pilot simulator, schematic view & 3D-printable enclosure CAD.",
        "attachments": attachments,
        "sim_rules": sim_rules,
        "enclosure_config": default_enclosure_config(),
        "custom_shapes": [],
        "chat_history": [],
        "code": STARTER_TEMPLATES[0]["code"],
        "created_at": now,
        "updated_at": now,
    }


class MicrobitProjectStore:
    """Thread-safe repository storing micro:bit v2.2 prototype projects in ``app_settings``."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._repo: Any = None
        self._projects: Dict[str, Dict[str, Any]] = {}

    def attach_repository(self, repo: Any) -> int:
        """Attach settings repository and hydrate persisted micro:bit projects."""
        self._repo = repo
        if repo is None:
            return 0
        getter = getattr(repo, "get_settings_raw", None) or getattr(repo, "get_raw_settings", None)
        if getter is None:
            return 0
        try:
            raw = getter() or {}
            blob = str(raw.get(MICROBIT_PROJECTS_SETTING_KEY) or "").strip()
            if not blob:
                return 0
            parsed = json.loads(blob)
            if not isinstance(parsed, dict):
                return 0
            with self._lock:
                self._projects = {str(k): dict(v) for k, v in parsed.items() if isinstance(v, dict)}
                return len(self._projects)
        except Exception as exc:
            sys.stderr.write(f"[microbit.store] Load error: {exc}\n")
            return 0

    def _persist(self) -> None:
        if self._repo is None or not hasattr(self._repo, "upsert_settings"):
            return
        try:
            with self._lock:
                payload = json.dumps(self._projects)
            self._repo.upsert_settings({MICROBIT_PROJECTS_SETTING_KEY: payload}, source_ip="microbit_lab")
        except Exception as exc:
            sys.stderr.write(f"[microbit.store] Persist error: {exc}\n")

    def _enrich(self, proj: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(proj)
        board_id = str(out.get("board_id") or "microbit_v2")
        out["board_id"] = board_id
        raw_atts = list(out.get("attachments") or [])
        norm_atts: List[Dict[str, Any]] = []
        for idx, att in enumerate(raw_atts):
            item = dict(att)
            if not isinstance(item.get("position_mm"), list) or len(item["position_mm"]) < 3:
                item["position_mm"] = default_attachment_position_mm(idx, len(raw_atts), board_id)
            if not isinstance(item.get("rotation_deg"), list) or len(item["rotation_deg"]) < 3:
                item["rotation_deg"] = [0.0, 0.0, 0.0]
            norm_atts.append(item)
        out["attachments"] = norm_atts
        out["enclosure_config"] = sanitize_enclosure_config(out.get("enclosure_config"))
        out["custom_shapes"] = sanitize_custom_shapes(out.get("custom_shapes"))
        out["envelope"] = compute_layout_envelope(board_id, norm_atts, out["custom_shapes"])
        out["wiring"] = validate_project_wiring(norm_atts, board_id=board_id)
        return out

    def list_projects(self) -> List[Dict[str, Any]]:
        """List all saved micro:bit projects (auto-seeds a starter project if empty)."""
        with self._lock:
            if not self._projects:
                first = _default_project()
                self._projects[first["id"]] = first
                should_persist = True
            else:
                should_persist = False
            items = [self._enrich(p) for p in self._projects.values()]
        if should_persist:
            self._persist()
        items.sort(key=lambda p: float(p.get("updated_at") or 0.0), reverse=True)
        return items

    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single micro:bit project by ID."""
        with self._lock:
            proj = self._projects.get(project_id)
            return self._enrich(proj) if proj is not None else None

    def create_project(self, *, name: str, description: str = "", board_id: str = "microbit_v2") -> Dict[str, Any]:
        """Create and persist a new blank multi-board prototype project."""
        now = time.time()
        proj = {
            "id": f"mb_{uuid.uuid4().hex[:8]}",
            "name": name.strip() or "New Hardware Prototype",
            "board_id": board_id if board_id in {"microbit_v2", "rpi5_16gb", "puppypi_pro"} else "microbit_v2",
            "description": description.strip(),
            "attachments": [],
            "sim_rules": [],
            "enclosure_config": default_enclosure_config(),
            "custom_shapes": [],
            "chat_history": [],
            "code": STARTER_TEMPLATES[0]["code"],
            "created_at": now,
            "updated_at": now,
        }
        with self._lock:
            self._projects[proj["id"]] = proj
        self._persist()
        return self._enrich(proj)

    def save_project(self, project: Dict[str, Any]) -> Dict[str, Any]:
        """Persist updates to an existing micro:bit project."""
        clean = {k: v for k, v in project.items() if k not in {"wiring", "envelope"}}
        clean["updated_at"] = time.time()
        with self._lock:
            self._projects[str(clean["id"])] = clean
        self._persist()
        return self._enrich(clean)

    def delete_project(self, project_id: str) -> bool:
        """Delete a micro:bit project by ID."""
        with self._lock:
            existed = project_id in self._projects
            self._projects.pop(project_id, None)
        if existed:
            self._persist()
        return existed
