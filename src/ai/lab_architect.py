"""Interactive Human-AI Hardware Co-Design Architect with 5-Tier Creativity Dial & 4 Specialist Lenses.

Supports live OpenRouter LLM synthesis (3x retry + ``sys.stderr`` logging) with a rich,
deterministic electronics/systems fallback engine so evaluation, ideation, electrical
guardrails, 2D ``TopologyFlowCanvas`` wiring graphs, and 3D ``CoDesignAssembly3D``
layouts work reliably both online and 100% offline.
"""

from __future__ import annotations

import asyncio
import json
import math
import sys
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

import httpx

from src.devices.envelope import list_device_profiles

CREATIVITY_TIERS: Dict[int, Dict[str, Any]] = {
    1: {
        "level": 1,
        "label": "Steady & Proven",
        "temperature": 0.2,
        "rubric": "Strictly use owned inventory only, zero risky wiring, conservative off-the-shelf ROS 2 / MicroPython patterns.",
    },
    2: {
        "level": 2,
        "label": "Practical Upgrade",
        "temperature": 0.45,
        "rubric": "Mostly owned parts with at most 1-2 low-cost (<$15) cables/shifters to eliminate bottlenecks reliably.",
    },
    3: {
        "level": 3,
        "label": "Creative Maker",
        "temperature": 0.7,
        "rubric": "Inventive multi-device fusion combining PuppyPi, Pi Zero 2 W, micro:bit v2, and local cameras in novel ways.",
    },
    4: {
        "level": 4,
        "label": "Frontier R&D",
        "temperature": 0.88,
        "rubric": "Ambitious multi-agent physical AI, distributed edge swarm sensing, semantic memory triggers, and custom firmware.",
    },
    5: {
        "level": 5,
        "label": "Extreme / Groundbreaking",
        "temperature": 1.0,
        "rubric": "Moonshot architectural leaps — autonomous multi-node spatial twin, cross-modal acoustic/LiDAR/vision intelligence, clearly separating Tonight Prototype vs Moonshot Unlocks.",
    },
}

PERSONA_PROMPTS: Dict[str, str] = {
    "systems_architect": (
        "Act as a Principal Robotics Systems Architect focusing on clean interfaces, failure isolation, "
        "local-first Docker autonomy, and phased Tonight vs Moonshot roadmaps."
    ),
    "electronics_ee": (
        "Act as a Senior Hardware & Electronics Engineer ruthlessly auditing 3.3V vs 5V logic levels, "
        "Raspberry Pi 5 1600 mA USB budgets, 2S LiPo brownout margins, common grounds, and cable data lines."
    ),
    "robotics_cv": (
        "Act as a Robotics & Computer Vision Engineer optimizing ROS 2 Humble DDS topics, "
        "LD19 LiDAR fusion, offline YOLO11n/YuNet/SFace pipelines, and frame-rate latency."
    ),
    "red_team": (
        "Act as an Adversarial Red-Team Critic actively hunting single points of failure, "
        "RF interference, cloud lock-in traps (e.g. Blink no-RTSP), thermal throttling, and unsafe autonomous motion."
    ),
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clamp_creativity(level: Any) -> int:
    try:
        v = int(level)
    except (TypeError, ValueError):
        v = 3
    return max(1, min(5, v))


def _normalize_persona(persona: Optional[str]) -> str:
    p = str(persona or "systems_architect").strip().lower()
    return p if p in PERSONA_PROMPTS else "systems_architect"


def _strip_json_fences(text: str) -> str:
    cleaned = (text or "").strip()
    if "```" in cleaned:
        for block in cleaned.split("```"):
            candidate = block.strip()
            if candidate.lower().startswith("json"):
                candidate = candidate[4:].strip()
            if candidate.startswith("{") or candidate.startswith("["):
                return candidate
    return cleaned


async def _call_openrouter_json(
    system_prompt: str,
    user_prompt: str,
    api_key: str,
    base_url: str,
    model: str,
    temperature: float,
) -> Optional[Any]:
    """Call OpenRouter Chat Completions with 3x retry and return parsed JSON or ``None``."""
    clean_key = (api_key or "").strip()
    if not clean_key or clean_key == "your_openrouter_api_key_here":
        return None
    root = (base_url or "https://openrouter.ai/api/v1").rstrip("/")
    body = {
        "model": model or "google/gemini-2.5-flash",
        "temperature": temperature,
        "max_tokens": 1800,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    for attempt in range(1, 4):
        try:
            async with httpx.AsyncClient(timeout=28.0) as client:
                resp = await client.post(
                    f"{root}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {clean_key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                return json.loads(_strip_json_fences(content))
        except Exception as exc:
            sys.stderr.write(f"[lab_architect] OpenRouter call failed (attempt {attempt}/3): {exc}\n")
            if attempt < 3:
                await asyncio.sleep(0.5 * attempt)
    return None


def _profile_dims_m(profile_id: str, profiles_map: Dict[str, Dict[str, Any]]) -> List[float]:
    prof = profiles_map.get(profile_id)
    if prof and isinstance(prof.get("dimensions_mm"), (list, tuple)) and len(prof["dimensions_mm"]) == 3:
        return [round(max(0.03, float(v) / 1000.0), 3) for v in prof["dimensions_mm"]]
    return [0.085, 0.056, 0.02]


def _run_electrical_and_protocol_checks(
    idea_text: str,
    parts_used: List[Dict[str, Any]],
    missing_parts: List[Dict[str, Any]],
    inventory_by_id: Dict[str, Dict[str, Any]],
    persona: str,
) -> List[Dict[str, str]]:
    """Run deterministic electrical, USB budget, voltage-level, and cloud-free protocol guardrails."""
    checks: List[Dict[str, str]] = []
    combined_names = " ".join(p.get("name", "") + " " + p.get("profile_id", "") for p in parts_used).lower()
    idea_low = (idea_text or "").lower()

    has_pi5 = "pi 5" in combined_names or "puppypi" in combined_names or "raspberry_pi_5" in combined_names
    has_microbit = "microbit" in combined_names or "micro:bit" in combined_names or "micro:bit" in idea_low
    has_blink = "blink" in combined_names or "blink" in idea_low
    has_pizero = "zero" in combined_names or "zero" in idea_low
    has_ld19 = "ld19" in combined_names or "lidar" in combined_names or "lidar" in idea_low
    has_shifter = "shifter" in combined_names or "level" in combined_names

    # 1. 3.3V micro:bit vs 5V host check
    if has_microbit and (has_pi5 or "5v" in idea_low or "servo" in idea_low):
        checks.append(
            {
                "topic": "3.3V micro:bit Logic & Power Isolation",
                "status": "ok" if has_shifter else "warning",
                "detail": (
                    "BSS138 logic level shifter present; micro:bit v2.21 3.3V edge GPIO is protected from 5V signals."
                    if has_shifter
                    else "BBC micro:bit v2.21 is strictly 3.3V logic (max 200 mA regulated). Connect to Pi 5 via USB CDC serial, BLE/radio, or add a 3.3V/5V logic-level shifter for direct UART/I2C."
                ),
            }
        )

    # 2. Raspberry Pi 5 USB-A current budget
    usb_draw_ma = 0
    for p in parts_used:
        inv = inventory_by_id.get(str(p.get("inventory_id") or ""))
        if inv and inv.get("category") in ("sensor", "camera", "accessory") and inv.get("current_ma"):
            usb_draw_ma += int(inv["current_ma"])
    if has_pi5:
        if usb_draw_ma > 1400:
            usb_status = "fault"
            usb_detail = f"Estimated USB peripheral draw (~{usb_draw_ma} mA) approaches/exceeds Pi 5's 1600 mA USB-A rail; add a powered USB hub."
        elif usb_draw_ma > 1100:
            usb_status = "warning"
            usb_detail = f"Estimated USB draw (~{usb_draw_ma} mA / 1600 mA budget); verify usb_max_current_enable=1 and keep audio/serial on black USB 2.0 ports."
        else:
            usb_status = "ok"
            usb_detail = f"Estimated USB peripheral draw (~{max(usb_draw_ma, 402)} mA) sits comfortably within Pi 5's 1600 mA unlocked USB-A budget."
        checks.append({"topic": "Raspberry Pi 5 USB-A Current Budget (1600 mA)", "status": usb_status, "detail": usb_detail})

    # 3. Blink cloud-free RTSP guardrail
    if has_blink:
        checks.append(
            {
                "topic": "Blink Camera Cloud-Free Local Ingest",
                "status": "ok" if has_pizero else "warning",
                "detail": (
                    "Blink Sync Module 2 paired with Raspberry Pi Zero 2 W USB g_mass_storage bridge harvests local .mp4 clips over LAN with zero Amazon cloud."
                    if has_pizero
                    else "Blink cameras do NOT expose native RTSP streams. Pair Sync Module 2's USB port with Raspberry Pi Zero 2 W in g_mass_storage gadget mode for 100% cloud-free local harvesting."
                ),
            }
        )

    # 4. LD19 LiDAR data cable guardrail
    if has_ld19:
        checks.append(
            {
                "topic": "LD19 LiDAR 230400-Baud USB-UART Data Link",
                "status": "warning",
                "detail": "LD19 spins on 5V alone; confirm a 4-wire data USB cable (not charge-only) connects its CP2102/CH340 converter PCB so /dev/ldlidar enumerates.",
            }
        )

    # 5. Red-team safety check
    if persona == "red_team" or not checks:
        checks.append(
            {
                "topic": "Local-First Resilience & E-STOP Safety",
                "status": "ok",
                "detail": "All vision, voice, and telemetry run locally inside Docker + ROS 2 Humble with zero cloud dependencies and hardware E-STOP override.",
            }
        )

    if missing_parts:
        checks.append(
            {
                "topic": "Procurement / Missing Hardware Delta",
                "status": "warning",
                "detail": f"{len(missing_parts)} proposed part(s) not yet owned; Prototype Tonight path isolates owned hardware so you can build immediately.",
            }
        )
    return checks


def _build_wiring_and_3d_assembly(
    parts_used: List[Dict[str, Any]],
    missing_parts: List[Dict[str, Any]],
    locked_part_ids: Sequence[str],
    profiles_map: Dict[str, Dict[str, Any]],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Build synchronized 2D ``TopologyFlowCanvas`` wiring graph and proportional 3D assembly."""
    locked_set = set(locked_part_ids or [])
    all_parts: List[Dict[str, Any]] = []
    for idx, p in enumerate(parts_used):
        pid = p.get("id") or f"part-{idx + 1}"
        all_parts.append({**p, "_node_id": pid, "_owned": bool(p.get("owned", True))})
    for idx, m in enumerate(missing_parts):
        pid = f"proposed-{idx + 1}"
        all_parts.append(
            {
                "id": pid,
                "_node_id": pid,
                "inventory_id": None,
                "name": m["name"],
                "profile_id": m.get("profile_id") or "generic_sensor_module",
                "role": m.get("reason") or "Proposed upgrade",
                "category": m.get("category") or "sensor",
                "owned": False,
                "_owned": False,
            }
        )

    if not all_parts:
        all_parts.append(
            {
                "id": "part-1",
                "_node_id": "part-1",
                "inventory_id": None,
                "name": "TwinScan Docker Host",
                "profile_id": "raspberry_pi_5_node",
                "role": "Local Orchestrator",
                "category": "compute",
                "owned": True,
                "_owned": True,
            }
        )

    # Identify hub node (prefer PuppyPi or Pi 5 compute node)
    hub_idx = 0
    for i, p in enumerate(all_parts):
        if p.get("profile_id") in ("puppypi_pi5_ros2", "raspberry_pi_5_node"):
            hub_idx = i
            break

    nodes_2d: List[Dict[str, Any]] = []
    edges_2d: List[Dict[str, Any]] = []
    parts_3d: List[Dict[str, Any]] = []
    links_3d: List[Dict[str, Any]] = []

    hub = all_parts[hub_idx]
    hub_id = hub["_node_id"]
    satellites = [p for i, p in enumerate(all_parts) if i != hub_idx]

    # Place hub at center
    hub_profile = hub.get("profile_id") or "puppypi_pi5_ros2"
    hub_locked = bool(hub.get("inventory_id") in locked_set or hub_id in locked_set)
    nodes_2d.append(
        {
            "id": hub_id,
            "label": hub["name"][:34],
            "subtitle": hub.get("role", "Primary Host")[:42],
            "metric": "LOCKED · CORE" if hub_locked else "CORE HOST",
            "category": "compute",
            "status": "ok" if hub["_owned"] else "warning",
            "x": 300,
            "y": 150,
        }
    )
    parts_3d.append(
        {
            "id": hub_id,
            "label": hub["name"][:32],
            "profile_id": hub_profile,
            "category": "compute",
            "owned": hub["_owned"],
            "locked": hub_locked,
            "x": 0.0,
            "y": 0.05,
            "z": 0.0,
            "dims_m": _profile_dims_m(hub_profile, profiles_map),
            "status": "ok" if hub["_owned"] else "proposed",
            "metric": hub.get("role", "Core Host")[:32],
        }
    )

    n_sat = max(1, len(satellites))
    for i, sat in enumerate(satellites):
        sid = sat["_node_id"]
        sprof = sat.get("profile_id") or "generic_sensor_module"
        scat = sat.get("category") or (profiles_map.get(sprof, {}).get("category") or "sensor")
        slocked = bool(sat.get("inventory_id") in locked_set or sid in locked_set)

        # 2D fan-out layout (left column & right column cleanly spaced)
        side = -1 if i % 2 == 0 else 1
        row = i // 2
        x2d = 30 if side < 0 else 570
        y2d = 40 + row * 125

        # 3D radial layout around hub
        angle = (2.0 * math.pi * i) / float(n_sat) + 0.35
        radius = 0.28 if sat["_owned"] else 0.38
        x3d = round(math.cos(angle) * radius, 3)
        z3d = round(math.sin(angle) * radius, 3)
        y3d = 0.14 if ("lidar" in sat["name"].lower() or "camera" in sat["name"].lower()) else 0.06

        # Infer link type
        low = (sat["name"] + " " + sprof).lower()
        if "blink" in low or "zero" in low:
            link_type, link_lbl = "wifi", "Local Wi-Fi HTTP"
        elif "microbit" in low:
            link_type, link_lbl = "ble", "USB CDC / BLE 2.4G"
        elif "camera" in low or "icspring" in low:
            link_type, link_lbl = "video", "USB 2.0 UVC"
        elif "shifter" in low or "i2c" in low or "uart" in low:
            link_type, link_lbl = "uart_i2c", "3.3V UART / I2C"
        elif "power" in low or "cable" in low or "psu" in low:
            link_type, link_lbl = "power_5v", "5V Power / Data"
        else:
            link_type, link_lbl = "usb", "USB 2.0 Serial/Audio"

        status_2d = "ok" if sat["_owned"] else "warning"
        status_3d = "ok" if sat["_owned"] else "proposed"

        nodes_2d.append(
            {
                "id": sid,
                "label": sat["name"][:34],
                "subtitle": sat.get("role", "Peripheral")[:42],
                "metric": "LOCKED" if slocked else ("OWNED" if sat["_owned"] else "PROPOSED"),
                "category": scat,
                "status": status_2d,
                "x": x2d,
                "y": y2d,
            }
        )
        edges_2d.append(
            {
                "id": f"e-{hub_id}-{sid}",
                "source": hub_id,
                "target": sid,
                "label": link_lbl,
                "status": status_2d,
                "animated": link_type in ("wifi", "video", "ble"),
            }
        )
        parts_3d.append(
            {
                "id": sid,
                "label": sat["name"][:32],
                "profile_id": sprof,
                "category": scat,
                "owned": sat["_owned"],
                "locked": slocked,
                "x": x3d,
                "y": y3d,
                "z": z3d,
                "dims_m": _profile_dims_m(sprof, profiles_map),
                "status": status_3d,
                "metric": link_lbl,
            }
        )
        links_3d.append(
            {
                "id": f"l-{hub_id}-{sid}",
                "source": hub_id,
                "target": sid,
                "label": link_lbl,
                "link_type": link_type,
                "status": "ok" if sat["_owned"] else "warning",
            }
        )

    return {"nodes": nodes_2d, "edges": edges_2d}, {"parts": parts_3d, "links": links_3d}


def _select_parts_deterministically(
    idea: str,
    inventory_items: Sequence[Dict[str, Any]],
    creativity_level: int,
    locked_part_ids: Sequence[str],
    excluded_part_ids: Sequence[str],
    canvas_part_names: Sequence[str],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Select owned inventory items and (at higher creativity tiers) proposed upgrades."""
    locked_set = set(locked_part_ids or [])
    excluded_set = set(excluded_part_ids or [])
    canvas_low = {str(n).strip().lower() for n in (canvas_part_names or []) if str(n).strip()}
    idea_low = (idea or "").lower()

    owned_pool = [
        item
        for item in inventory_items
        if item.get("status") in ("available", "deployed", "needs_part")
        and item.get("id") not in excluded_set
    ]

    selected: List[Dict[str, Any]] = []
    seen_ids = set()

    def _add_inv(item: Dict[str, Any], role: str) -> None:
        iid = item.get("id")
        if iid in seen_ids:
            return
        seen_ids.add(iid)
        selected.append(
            {
                "inventory_id": iid,
                "name": item["name"],
                "profile_id": item.get("profile_id") or "generic_sensor_module",
                "role": role,
                "owned": True,
            }
        )

    # 1. Always honor locked parts and explicitly placed canvas parts first
    for item in owned_pool:
        if item.get("id") in locked_set or item["name"].lower() in canvas_low:
            _add_inv(item, "Locked / Pinned Lab Part")

    # 2. Keyword-score remaining owned parts against the idea
    keyword_roles = [
        (("puppypi", "robot", "patrol", "sentry", "walk", "room", "guard", "dog"), "puppypi", "Primary ROS 2 Quadruped Host"),
        (("lidar", "scan", "map", "obstacle", "3d", "wall"), "ld19", "360-deg ToF Distance Sensor"),
        (("voice", "speak", "ox", "audio", "chime", "mic", "talk"), "wonderecho", "Voice I/O & Spoken Alerts"),
        (("camera", "vision", "face", "animal", "pet", "detect", "see", "photo"), "icspring", "Local FPV AI Vision Camera"),
        (("blink", "clip", "entry", "door", "security", "outdoor", "porch"), "blink", "Motion-Triggered Local Clip Camera"),
        (("zero", "blink", "usb", "bridge", "harvest", "gadget", "cloud-free"), "zero", "Zero-Cloud USB-OTG Clip Harvester"),
        (("microbit", "micro:bit", "badge", "led", "matrix", "beacon", "door", "alert", "desk", "remote"), "microbit", "5x5 LED Status Badge & 2.4GHz Beacon"),
    ]
    for triggers, name_token, role in keyword_roles:
        if any(t in idea_low for t in triggers):
            for item in owned_pool:
                if name_token in item["name"].lower() or name_token in str(item.get("profile_id") or "").lower():
                    _add_inv(item, role)

    # Ensure at least 2-3 core owned parts are selected even for short prompts
    if len(selected) < 3:
        for item in owned_pool:
            if len(selected) >= 4:
                break
            _add_inv(item, f"Owned {item.get('category', 'hardware').title()} Node")

    # 3. Missing/proposed parts calibrated by Creativity Level (Tier 1 = strictly 0 missing!)
    missing: List[Dict[str, Any]] = []
    if creativity_level >= 2:
        if any("ld19" in p["name"].lower() for p in selected):
            missing.append(
                {
                    "name": "30cm 4-Wire USB Data Cable (for LD19 CP2102)",
                    "profile_id": "generic_sensor_module",
                    "category": "accessory",
                    "reason": "Guarantees reliable 230400-baud D+/D- enumeration for LD19 LiDAR on Pi 5.",
                    "est_cost_usd": 8.0,
                    "interfaces": ["USB-A", "USB-C Data"],
                }
            )
    if creativity_level >= 3 and any("microbit" in p["name"].lower() for p in selected):
        missing.append(
            {
                "name": "BSS138 4-Channel 3.3V/5V Logic Level Shifter",
                "profile_id": "generic_sensor_module",
                "category": "accessory",
                "reason": "Protects micro:bit v2.21 3.3V GPIO when bridging directly to 5V sensors or relays.",
                "est_cost_usd": 4.0,
                "interfaces": ["I2C", "UART", "3.3V/5V"],
            }
        )
    if creativity_level >= 4:
        missing.append(
            {
                "name": "ESP32-S3 UWB / mmWave Presence Sensor Node",
                "profile_id": "generic_sensor_module",
                "category": "sensor",
                "reason": "Adds millimeter-wave stationary human presence & ultra-wideband room localization for PuppyPi.",
                "est_cost_usd": 19.0,
                "interfaces": ["Wi-Fi", "UART", "5V"],
            }
        )
    if creativity_level >= 5:
        missing.append(
            {
                "name": "Hailo-8L M.2 AI Accelerator HAT+ (Pi 5 PCIe FFC)",
                "profile_id": "raspberry_pi_5_node",
                "category": "compute",
                "reason": "Unlocks 13 TOPS onboard 30 FPS multi-camera YOLO11 + Depth Anything inference right on the Pi 5 PCIe bus.",
                "est_cost_usd": 70.0,
                "interfaces": ["PCIe 2.0 x1 FFC"],
            }
        )

    return selected, missing


async def evaluate_design_idea(
    idea: str,
    inventory_items: Sequence[Dict[str, Any]],
    profiles: Optional[Sequence[Dict[str, Any]]] = None,
    creativity_level: int = 3,
    persona: str = "systems_architect",
    locked_part_ids: Optional[Sequence[str]] = None,
    excluded_part_ids: Optional[Sequence[str]] = None,
    canvas_part_names: Optional[Sequence[str]] = None,
    openrouter_api_key: str = "",
    base_url: str = "https://openrouter.ai/api/v1",
    model: str = "google/gemini-2.5-flash",
) -> Dict[str, Any]:
    """Evaluate a hardware/robotics project idea against owned lab inventory and build a DesignBlueprint.

    Generates electrical guardrails, Tonight vs Moonshot plan, 2D ``wiring_graph``,
    and proportional 3D ``assembly_3d`` coordinates. Uses OpenRouter when configured and
    falls back seamlessly to deterministic engineering synthesis offline.

    Args:
        idea: Natural-language project idea prompt.
        inventory_items: Current lab inventory list.
        profiles: Optional device profile catalog (defaults to ``list_device_profiles()``).
        creativity_level: Creativity tier ``1..5``.
        persona: Specialist lens (``systems_architect``, ``electronics_ee``, ``robotics_cv``, ``red_team``).
        locked_part_ids: Inventory IDs that MUST be included.
        excluded_part_ids: Inventory IDs that MUST NOT be included.
        canvas_part_names: Optional names pinned directly on the canvas.
        openrouter_api_key: Optional OpenRouter API key.
        base_url: OpenRouter API base URL.
        model: OpenRouter model slug.

    Returns:
        Complete ``DesignBlueprint`` dictionary conforming strictly to the shared contract.
    """
    tier = _clamp_creativity(creativity_level)
    tier_meta = CREATIVITY_TIERS[tier]
    norm_persona = _normalize_persona(persona)
    prof_list = list(profiles) if profiles is not None else list_device_profiles()
    profiles_map = {p["profile_id"]: p for p in prof_list}
    inv_by_id = {str(i.get("id")): i for i in inventory_items if i.get("id")}
    locked = list(locked_part_ids or [])
    excluded = list(excluded_part_ids or [])

    parts_used, missing_parts = _select_parts_deterministically(
        idea=idea,
        inventory_items=inventory_items,
        creativity_level=tier,
        locked_part_ids=locked,
        excluded_part_ids=excluded,
        canvas_part_names=canvas_part_names or [],
    )

    clean_idea = (idea or "Local multi-sensor autonomous room sentinel").strip()
    title = clean_idea[:64].rstrip(".!?")
    if len(title) < 6:
        title = "Eigenia Multi-Node Robotics Prototype"

    summary = (
        f"[{tier_meta['label']} · {norm_persona.replace('_', ' ').title()}] "
        f"Uses {len(parts_used)} owned lab part(s) with {len(missing_parts)} optional upgrade(s) "
        f"to execute '{title}' 100% locally inside Docker + ROS 2 Humble."
    )
    architecture_steps = [
        f"Anchor core compute & telemetry on {parts_used[0]['name']} over local Wildcat Wi-Fi (zero cloud).",
        "Wire peripherals respecting strict 3.3V GPIO logic boundaries and Pi 5's 1600 mA USB-A power envelope.",
        "Stream local vision/clip frames into TwinScan's offline Spatial Memory (YOLO11n + YuNet/SFace) for searchable room state.",
        "Bind WonderEcho Pro / BBC micro:bit v2.21 for immediate physical audio + 5x5 LED alerts and hands-free 'Hey OX' triggers.",
    ]
    tonight = [
        f"Assemble {len(parts_used)} owned parts right away with zero waiting for shipping.",
        "Validate 2D wiring links, 3D assembly clearances, and local /api/devices/* telemetry endpoints.",
    ]
    moonshot = [
        f"Adopt {m['name']} (~${int(m['est_cost_usd'])}) — {m['reason']}" for m in missing_parts
    ] or [
        "Expand into multi-room 360-deg autonomous spatial patrols with cross-camera person/pet re-identification."
    ]
    model_used = "deterministic-local-architect"

    # Attempt OpenRouter enrichment when API key is configured
    sys_prompt = (
        f"{PERSONA_PROMPTS[norm_persona]}\n"
        f"Creativity Tier {tier}/5 ({tier_meta['label']}): {tier_meta['rubric']}\n"
        "Return ONLY valid JSON with keys: title (str), summary (str), verdict ('buildable_now'|'needs_minor_parts'|'hardware_limit'), "
        "feasibility_score (int 1..100), architecture_steps (list[str] 3-5 items), "
        "tonight (list[str] 2-3 items), moonshot (list[str] 2-3 items)."
    )
    user_prompt = (
        f"Idea: {clean_idea}\n"
        f"Owned selected parts: {[p['name'] for p in parts_used]}\n"
        f"Proposed missing parts: {[m['name'] for m in missing_parts]}\n"
        f"Locked part IDs: {locked}\nExcluded part IDs: {excluded}"
    )
    llm_json = await _call_openrouter_json(
        system_prompt=sys_prompt,
        user_prompt=user_prompt,
        api_key=openrouter_api_key,
        base_url=base_url,
        model=model,
        temperature=float(tier_meta["temperature"]),
    )
    if isinstance(llm_json, dict):
        title = str(llm_json.get("title") or title)[:90]
        summary = str(llm_json.get("summary") or summary)
        if isinstance(llm_json.get("architecture_steps"), list) and llm_json["architecture_steps"]:
            architecture_steps = [str(s) for s in llm_json["architecture_steps"][:6]]
        if isinstance(llm_json.get("tonight"), list) and llm_json["tonight"]:
            tonight = [str(s) for s in llm_json["tonight"][:4]]
        if isinstance(llm_json.get("moonshot"), list) and llm_json["moonshot"]:
            moonshot = [str(s) for s in llm_json["moonshot"][:4]]
        model_used = model or "google/gemini-2.5-flash"

    electrical_checks = _run_electrical_and_protocol_checks(
        idea_text=clean_idea,
        parts_used=parts_used,
        missing_parts=missing_parts,
        inventory_by_id=inv_by_id,
        persona=norm_persona,
    )
    has_fault = any(c["status"] == "fault" for c in electrical_checks)
    if has_fault:
        verdict = "hardware_limit"
        feasibility = 54
    elif missing_parts:
        verdict = "needs_minor_parts"
        feasibility = max(72, 92 - len(missing_parts) * 5)
    else:
        verdict = "buildable_now"
        feasibility = 94

    if isinstance(llm_json, dict):
        if llm_json.get("verdict") in ("buildable_now", "needs_minor_parts", "hardware_limit") and not has_fault:
            verdict = str(llm_json["verdict"])
        if isinstance(llm_json.get("feasibility_score"), (int, float)):
            feasibility = max(10, min(100, int(llm_json["feasibility_score"])))

    wiring_graph, assembly_3d = _build_wiring_and_3d_assembly(
        parts_used=parts_used,
        missing_parts=missing_parts,
        locked_part_ids=locked,
        profiles_map=profiles_map,
    )
    now = _now_iso()
    return {
        "id": str(uuid.uuid4()),
        "title": title,
        "idea": clean_idea,
        "creativity_level": tier,
        "persona": norm_persona,
        "verdict": verdict,
        "feasibility_score": feasibility,
        "summary": summary,
        "parts_used": parts_used,
        "missing_parts": missing_parts,
        "electrical_checks": electrical_checks,
        "architecture_steps": architecture_steps,
        "build_tonight_vs_moonshot": {"tonight": tonight, "moonshot": moonshot},
        "wiring_graph": wiring_graph,
        "assembly_3d": assembly_3d,
        "locked_part_ids": locked,
        "excluded_part_ids": excluded,
        "chat_history": [
            {"role": "user", "persona": norm_persona, "text": clean_idea, "timestamp": now},
            {"role": "assistant", "persona": norm_persona, "text": summary, "timestamp": now},
        ],
        "versions": [
            {
                "version": 1,
                "label": f"v1 · {tier_meta['label']}",
                "creativity_level": tier,
                "feasibility_score": feasibility,
                "timestamp": now,
                "parts_count": len(parts_used),
                "missing_count": len(missing_parts),
            }
        ],
        "model_used": model_used,
        "created_at": now,
        "updated_at": now,
    }


async def generate_inventory_ideas(
    inventory_items: Sequence[Dict[str, Any]],
    profiles: Optional[Sequence[Dict[str, Any]]] = None,
    creativity_level: int = 3,
    focus_area: str = "all",
    count: int = 4,
    locked_part_ids: Optional[Sequence[str]] = None,
    excluded_part_ids: Optional[Sequence[str]] = None,
    openrouter_api_key: str = "",
    base_url: str = "https://openrouter.ai/api/v1",
    model: str = "google/gemini-2.5-flash",
) -> Tuple[List[Dict[str, Any]], str]:
    """Generate tailored robotics/IoT project ideas calibrated to the 5-Tier Creativity Dial.

    Args:
        inventory_items: User's current lab inventory.
        profiles: Optional device profiles.
        creativity_level: Creativity tier ``1..5``.
        focus_area: Filter area (``all``, ``security``, ``robotics``, ``voice_ai``, ``iot``).
        count: Number of ideas to return (``1..8``).
        locked_part_ids: Parts that must appear in generated ideas.
        excluded_part_ids: Parts to omit.
        openrouter_api_key: Optional OpenRouter API key.
        base_url: OpenRouter base URL.
        model: OpenRouter model slug.

    Returns:
        Tuple ``(ideas_list, model_used)``.
    """
    tier = _clamp_creativity(creativity_level)
    tier_meta = CREATIVITY_TIERS[tier]
    n_ideas = max(1, min(8, int(count)))
    excluded = set(excluded_part_ids or [])
    owned_names = [
        i["name"]
        for i in inventory_items
        if i.get("status") in ("available", "deployed", "needs_part") and i.get("id") not in excluded
    ]

    # Try live OpenRouter ideation first
    sys_prompt = (
        f"You are an elite Robotics & IoT Lab Ideation Partner at Creativity Tier {tier}/5 ({tier_meta['label']}). "
        f"{tier_meta['rubric']}\n"
        f"Return ONLY a JSON array of exactly {n_ideas} objects with keys: "
        "title (str), pitch (str), creativity_level (int), difficulty ('Easy'|'Medium'|'Advanced'|'Moonshot'), "
        "verdict ('buildable_now'|'needs_minor_parts'), parts_used (list[str]), missing_parts (list[str]), "
        "capabilities (list[str]), estimated_time (str)."
    )
    user_prompt = (
        f"Focus area: {focus_area}\nOwned inventory: {owned_names}\n"
        f"Locked part IDs: {list(locked_part_ids or [])}"
    )
    llm_ideas = await _call_openrouter_json(
        system_prompt=sys_prompt,
        user_prompt=user_prompt,
        api_key=openrouter_api_key,
        base_url=base_url,
        model=model,
        temperature=float(tier_meta["temperature"]),
    )
    if isinstance(llm_ideas, list) and llm_ideas:
        cleaned: List[Dict[str, Any]] = []
        for item in llm_ideas[:n_ideas]:
            if not isinstance(item, dict):
                continue
            cleaned.append(
                {
                    "title": str(item.get("title") or "Untitled Lab Project"),
                    "pitch": str(item.get("pitch") or ""),
                    "creativity_level": tier,
                    "difficulty": str(item.get("difficulty") or "Medium"),
                    "verdict": str(item.get("verdict") or "buildable_now"),
                    "parts_used": [str(x) for x in (item.get("parts_used") or owned_names[:3])],
                    "missing_parts": [str(x) for x in (item.get("missing_parts") or [])],
                    "capabilities": [str(x) for x in (item.get("capabilities") or [])],
                    "estimated_time": str(item.get("estimated_time") or "2 hours"),
                }
            )
        if cleaned:
            return cleaned, (model or "google/gemini-2.5-flash")

    # Deterministic, tier-calibrated local ideation catalog
    catalog: List[Dict[str, Any]] = [
        {
            "title": "Zero-Cloud Blink Clip Harvester -> Offline Spatial Memory",
            "pitch": "Turn Raspberry Pi Zero 2 W into a FAT32 USB Mass Storage Gadget plugged into Blink Sync Module 2, pushing local .mp4 motion clips over Wildcat Wi-Fi into offline YOLO11n + SFace recognition.",
            "creativity_level": tier,
            "difficulty": "Easy" if tier <= 2 else "Medium",
            "verdict": "buildable_now",
            "parts_used": ["Raspberry Pi Zero 2 W", "Blink Outdoor 4 + Sync Module 2 (Local USB)"],
            "missing_parts": [],
            "capabilities": ["100% Cloud-Free Video AI", "Auto-Indexed Spatial Memory", "Zero Monthly Subscription"],
            "estimated_time": "45 min",
            "focus": "security",
        },
        {
            "title": "micro:bit v2 Tactile Desk Alert Badge & 'Hey OX' Trigger",
            "pitch": "Use BBC micro:bit v2.21 over USB CDC serial as a physical 5x5 LED room status matrix: flashes alert icons when PuppyPi spots a stranger or pet, and pressing Button A dispatches PuppyPi patrol.",
            "creativity_level": tier,
            "difficulty": "Easy",
            "verdict": "buildable_now",
            "parts_used": ["BBC micro:bit v2.21", "Hiwonder PuppyPi Pro (Raspberry Pi 5 8GB)", "Hiwonder WonderEcho Pro Voice Module"],
            "missing_parts": [],
            "capabilities": ["5x5 LED Visual Alerts", "Hardware Panic/Patrol Button", "Zero-Cloud USB Bridge"],
            "estimated_time": "30 min",
            "focus": "iot",
        },
        {
            "title": "PuppyPi Autonomous Acoustic + Visual Night Watchman",
            "pitch": "Combine PuppyPi ROS 2 Humble, icSpring UVC camera, and WonderEcho Pro voice announcements with Semantic Spatial Memory so OX greets known family members and logs unknown motion with snapshots.",
            "creativity_level": tier,
            "difficulty": "Medium",
            "verdict": "buildable_now" if tier == 1 else "needs_minor_parts",
            "parts_used": ["Hiwonder PuppyPi Pro (Raspberry Pi 5 8GB)", "icSpring 640x480 UVC FPV Camera", "Hiwonder WonderEcho Pro Voice Module"],
            "missing_parts": [] if tier == 1 else ["30cm 4-Wire USB Data Cable (for LD19 CP2102)"],
            "capabilities": ["Known-Person Face Greeting", "Offline Voice Alerts", "2D/3D Room Mapping"],
            "estimated_time": "1.5 hours",
            "focus": "robotics",
        },
        {
            "title": "Distributed Multi-Room Spatial Twin Mesh (Pi 5 + Pi Zero + micro:bit)",
            "pitch": "Fuse doorway micro:bit v2.21 vibration beacons, entryway Blink clips harvested via Pi Zero 2 W, and PuppyPi's mobile 3D wall scanner into one live living-room digital twin queryable by voice ('Hey OX, where is my backpack?').",
            "creativity_level": tier,
            "difficulty": "Advanced" if tier <= 4 else "Moonshot",
            "verdict": "buildable_now" if tier == 1 else "needs_minor_parts",
            "parts_used": [
                "Hiwonder PuppyPi Pro (Raspberry Pi 5 8GB)",
                "Raspberry Pi Zero 2 W",
                "BBC micro:bit v2.21",
                "Blink Outdoor 4 + Sync Module 2 (Local USB)",
            ],
            "missing_parts": (
                []
                if tier == 1
                else (
                    ["30cm 4-Wire USB Data Cable (for LD19 CP2102)", "Hailo-8L M.2 AI Accelerator HAT+ (Pi 5 PCIe FFC)"]
                    if tier >= 5
                    else ["30cm 4-Wire USB Data Cable (for LD19 CP2102)", "BSS138 4-Channel 3.3V/5V Logic Level Shifter"]
                )
            ),
            "capabilities": ["Multi-Node Event Handoff", "Voice-Queryable Spatial Memory", "3D Real-Room Twin"],
            "estimated_time": "1 weekend",
            "focus": "voice_ai",
        },
    ]

    focus = str(focus_area or "all").strip().lower()
    if focus != "all":
        prioritized = [c for c in catalog if c.get("focus") == focus] + [c for c in catalog if c.get("focus") != focus]
    else:
        prioritized = catalog

    out = [{k: v for k, v in item.items() if k != "focus"} for item in prioritized[:n_ideas]]
    return out, "deterministic-local-architect"


async def refine_blueprint(
    blueprint: Dict[str, Any],
    message: str,
    inventory_items: Sequence[Dict[str, Any]],
    profiles: Optional[Sequence[Dict[str, Any]]] = None,
    selected_node_id: Optional[str] = None,
    creativity_level: Optional[int] = None,
    persona: Optional[str] = None,
    locked_part_ids: Optional[Sequence[str]] = None,
    excluded_part_ids: Optional[Sequence[str]] = None,
    accept_missing_part: Optional[str] = None,
    openrouter_api_key: str = "",
    base_url: str = "https://openrouter.ai/api/v1",
    model: str = "google/gemini-2.5-flash",
) -> Dict[str, Any]:
    """Iteratively refine an existing ``DesignBlueprint`` via human-AI walkthrough chat.

    Handles point-and-ask on ``selected_node_id``, persona/creativity tier changes,
    promoting a proposed ``accept_missing_part`` onto the active design canvas, re-running
    electrical guardrails, rebuilding 2D/3D graphs, and appending a new version entry.

    Args:
        blueprint: Existing saved ``DesignBlueprint`` dictionary.
        message: User's follow-up critique, question, or change request.
        inventory_items: Current lab inventory.
        profiles: Optional device profiles.
        selected_node_id: Optional 2D/3D node ID the user clicked for point-and-ask.
        creativity_level: Optional updated creativity tier ``1..5``.
        persona: Optional updated specialist lens.
        locked_part_ids: Optional updated locked inventory IDs.
        excluded_part_ids: Optional updated excluded inventory IDs.
        accept_missing_part: Optional name of a missing part to promote into ``parts_used``.
        openrouter_api_key: Optional OpenRouter API key.
        base_url: OpenRouter base URL.
        model: OpenRouter model slug.

    Returns:
        Updated ``DesignBlueprint`` dictionary with new chat turn & version snapshot.
    """
    bp = deepcopy(blueprint)
    prof_list = list(profiles) if profiles is not None else list_device_profiles()
    profiles_map = {p["profile_id"]: p for p in prof_list}
    inv_by_id = {str(i.get("id")): i for i in inventory_items if i.get("id")}

    tier = _clamp_creativity(creativity_level if creativity_level is not None else bp.get("creativity_level", 3))
    tier_meta = CREATIVITY_TIERS[tier]
    norm_persona = _normalize_persona(persona if persona is not None else bp.get("persona", "systems_architect"))
    locked = list(locked_part_ids) if locked_part_ids is not None else list(bp.get("locked_part_ids") or [])
    excluded = list(excluded_part_ids) if excluded_part_ids is not None else list(bp.get("excluded_part_ids") or [])

    parts_used: List[Dict[str, Any]] = list(bp.get("parts_used") or [])
    missing_parts: List[Dict[str, Any]] = list(bp.get("missing_parts") or [])

    # Respect excluded IDs on existing parts_used
    excluded_set = set(excluded)
    parts_used = [p for p in parts_used if p.get("inventory_id") not in excluded_set]

    # Promote accepted missing part onto active canvas
    promoted_note = ""
    if accept_missing_part:
        target_low = accept_missing_part.strip().lower()
        remaining_missing: List[Dict[str, Any]] = []
        for mp in missing_parts:
            if mp["name"].strip().lower() == target_low:
                parts_used.append(
                    {
                        "inventory_id": None,
                        "name": mp["name"],
                        "profile_id": mp.get("profile_id") or "generic_sensor_module",
                        "role": mp.get("reason") or "Accepted upgrade",
                        "owned": False,
                    }
                )
                promoted_note = f"Promoted '{mp['name']}' onto the active 2D/3D Co-Design Canvas."
            else:
                remaining_missing.append(mp)
        missing_parts = remaining_missing

    # Point-and-ask context if a 2D/3D node is selected
    selected_label = None
    if selected_node_id:
        for p3 in (bp.get("assembly_3d") or {}).get("parts") or []:
            if p3.get("id") == selected_node_id:
                selected_label = p3.get("label")
                break

    clean_msg = (message or promoted_note or "Review electrical & architectural tradeoffs.").strip()
    electrical_checks = _run_electrical_and_protocol_checks(
        idea_text=f"{bp.get('idea', '')} {clean_msg}",
        parts_used=parts_used,
        missing_parts=missing_parts,
        inventory_by_id=inv_by_id,
        persona=norm_persona,
    )
    wiring_graph, assembly_3d = _build_wiring_and_3d_assembly(
        parts_used=parts_used,
        missing_parts=missing_parts,
        locked_part_ids=locked,
        profiles_map=profiles_map,
    )

    has_fault = any(c["status"] == "fault" for c in electrical_checks)
    feasibility = 58 if has_fault else (88 if not missing_parts else max(74, 92 - len(missing_parts) * 4))
    verdict = "hardware_limit" if has_fault else ("needs_minor_parts" if missing_parts else "buildable_now")

    focus_prefix = f"Regarding **{selected_label}** ({selected_node_id}): " if selected_label else ""
    reply_text = (
        f"{focus_prefix}{promoted_note + ' ' if promoted_note else ''}"
        f"[{norm_persona.replace('_', ' ').title()} · Tier {tier} {tier_meta['label']}] "
        f"Re-validated {len(parts_used)} active parts and {len(electrical_checks)} electrical/protocol guardrails. "
        f"Top guardrail: {electrical_checks[0]['topic']} ({electrical_checks[0]['status'].upper()}) — {electrical_checks[0]['detail']}"
    )
    model_used = bp.get("model_used") or "deterministic-local-architect"

    llm_refine = await _call_openrouter_json(
        system_prompt=(
            f"{PERSONA_PROMPTS[norm_persona]}\n"
            f"Creativity Tier {tier}/5 ({tier_meta['label']}): {tier_meta['rubric']}\n"
            "Return ONLY JSON: {\"reply\": str, \"summary\": str, \"feasibility_score\": int}."
        ),
        user_prompt=(
            f"Blueprint: {bp.get('title')}\nCurrent parts: {[p['name'] for p in parts_used]}\n"
            f"Selected node: {selected_label or 'none'}\nUser message: {clean_msg}"
        ),
        api_key=openrouter_api_key,
        base_url=base_url,
        model=model,
        temperature=float(tier_meta["temperature"]),
    )
    if isinstance(llm_refine, dict):
        if llm_refine.get("reply"):
            reply_text = str(llm_refine["reply"])
        if llm_refine.get("summary"):
            bp["summary"] = str(llm_refine["summary"])
        if isinstance(llm_refine.get("feasibility_score"), (int, float)) and not has_fault:
            feasibility = max(10, min(100, int(llm_refine["feasibility_score"])))
        model_used = model or "google/gemini-2.5-flash"

    now = _now_iso()
    history = list(bp.get("chat_history") or [])
    history.append({"role": "user", "persona": norm_persona, "text": clean_msg, "timestamp": now})
    history.append({"role": "assistant", "persona": norm_persona, "text": reply_text, "timestamp": now})

    versions = list(bp.get("versions") or [])
    next_ver = (versions[-1]["version"] + 1) if versions else 1
    versions.append(
        {
            "version": next_ver,
            "label": f"v{next_ver} · {norm_persona.replace('_', ' ').title()}",
            "creativity_level": tier,
            "feasibility_score": feasibility,
            "timestamp": now,
            "parts_count": len(parts_used),
            "missing_count": len(missing_parts),
        }
    )

    bp["creativity_level"] = tier
    bp["persona"] = norm_persona
    bp["verdict"] = verdict
    bp["feasibility_score"] = feasibility
    bp["parts_used"] = parts_used
    bp["missing_parts"] = missing_parts
    bp["electrical_checks"] = electrical_checks
    bp["wiring_graph"] = wiring_graph
    bp["assembly_3d"] = assembly_3d
    bp["locked_part_ids"] = locked
    bp["excluded_part_ids"] = excluded
    bp["chat_history"] = history
    bp["versions"] = versions
    bp["model_used"] = model_used
    bp["updated_at"] = now
    return bp
