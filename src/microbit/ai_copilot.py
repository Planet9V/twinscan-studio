"""Conversational AI Hardware & MicroPython Co-Pilot for BBC micro:bit v2.2.

Translates plain-English user instructions (e.g., "on lift say 'Weeee!', on left
button play a sound and sweep the servo to 180°") into:
1. Updated 3D hardware attachments & conflict-free pin assignments
2. Structured interactive simulator rules (``sim_rules``) executed live in the
   Three.js 3D Digital Twin canvas
3. Synchronized, runnable MicroPython ``main.py`` ready for 1-click deploy to
   the physical micro:bit v2.2.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import uuid
from typing import Any, Dict, List, Optional, Sequence

import httpx

from src.microbit.catalog import ACCESSORY_BY_ID, MICROBIT_ACCESSORIES, MICROBIT_V2_PINS
from src.microbit.enclosure_cad import (
    auto_fit_enclosure_config,
    sanitize_custom_shapes,
    sanitize_enclosure_config,
)

MAX_LLM_RETRIES = 3

VALID_TRIGGERS = frozenset(
    {
        "lift",
        "tilt_left",
        "tilt_right",
        "shake",
        "button_a",
        "button_b",
        "logo_touch",
        "pir_motion",
        "touch_pad",
        "ultrasonic_near",
        "temp_high",
    }
)
VALID_LED_ICONS = frozenset(
    {"HAPPY", "HEART", "SURPRISED", "SAD", "CONFUSED", "ARROW_N", "ARROW_E", "ARROW_W", "YES", "NO"}
)
VALID_SOUNDS = frozenset({"none", "slide", "chime", "giggle", "spring", "sad"})


def compile_rules_to_micropython(
    attachments: Sequence[Dict[str, Any]],
    sim_rules: Sequence[Dict[str, Any]],
    project_name: str = "micro:bit Prototype",
) -> str:
    """Compile attached accessories and interactive simulator rules into runnable MicroPython.

    Args:
        attachments: List of attached accessory dicts with ``accessory_id`` and ``pin``.
        sim_rules: List of structured trigger->action simulator rules.
        project_name: Project display name for script header.

    Returns:
        Complete MicroPython ``main.py`` source code.
    """
    imports = ["from microbit import *", "import audio", "import music", "import speech", "import math"]
    has_neopixel = any(a.get("accessory_id") == "neopixel_8" for a in attachments)
    if has_neopixel:
        imports.append("import neopixel")

    servo_pin_var: Optional[str] = None
    neopixel_pin_var: Optional[str] = None
    pir_pin_var: Optional[str] = None
    ext_speaker_pin_var: Optional[str] = None

    for att in attachments:
        acc_id = str(att.get("accessory_id") or "")
        pin_raw = str(att.get("pin") or "P0").lower()
        pvar = f"pin{pin_raw[1:]}" if pin_raw.startswith("p") and pin_raw[1:].isdigit() else "pin0"
        if acc_id == "sg90_servo" and servo_pin_var is None:
            servo_pin_var = pvar
        elif acc_id == "neopixel_8" and neopixel_pin_var is None:
            neopixel_pin_var = pvar
        elif acc_id == "pir_motion" and pir_pin_var is None:
            pir_pin_var = pvar
        elif acc_id == "external_speaker" and ext_speaker_pin_var is None:
            ext_speaker_pin_var = pvar

    setup = [
        f"# AI Co-Pilot Prototype: {project_name}",
        "speaker.on()",
        "set_volume(255)",
        "display.show(Image.HAPPY)",
        "last_z = accelerometer.get_z()",
        "last_ms = running_time()",
    ]
    if servo_pin_var:
        setup.append(f"{servo_pin_var}.set_analog_period(20)  # 50Hz SG90 Servo")
    if neopixel_pin_var:
        setup.append(f"np = neopixel.NeoPixel({neopixel_pin_var}, 8)")

    def _hex_to_rgb_tuple(hx: str) -> str:
        s = str(hx or "#22d3ee").lstrip("#")
        if len(s) != 6:
            return "(0, 45, 55)"
        try:
            r = max(0, min(60, int(s[0:2], 16) // 4))
            g = max(0, min(60, int(s[2:4], 16) // 4))
            b = max(0, min(60, int(s[4:6], 16) // 4))
            return f"({r}, {g}, {b})"
        except ValueError:
            return "(0, 45, 55)"

    def _action_block(rule: Dict[str, Any]) -> List[str]:
        lines: List[str] = []
        icon = str(rule.get("led_icon") or "HAPPY").upper()
        if icon not in VALID_LED_ICONS:
            icon = "HAPPY"
        lines.append(f"        display.show(Image.{icon})")

        angle = rule.get("servo_angle")
        if servo_pin_var and angle is not None:
            ang = max(0, min(180, int(angle)))
            duty = int(round(26 + (ang / 180.0) * 102))
            lines.append(f"        {servo_pin_var}.write_analog({duty})  # {ang} deg")

        np_hex = rule.get("neopixel_hex")
        if neopixel_pin_var and np_hex:
            rgb = _hex_to_rgb_tuple(str(np_hex))
            lines.append(f"        for i in range(8): np[i] = {rgb}")
            lines.append("        np.show()")

        snd = str(rule.get("sound_effect") or "none").lower()
        pin_arg = f", pin={ext_speaker_pin_var}" if ext_speaker_pin_var else ""
        if snd == "chime":
            lines.append(f"        music.play(['C5:2', 'E5:2', 'G5:3']{pin_arg})")
        elif snd == "slide":
            lines.append("        audio.play(Sound.SLIDE, wait=True)")
        elif snd == "giggle":
            lines.append("        audio.play(Sound.GIGGLE, wait=True)")
        elif snd == "spring":
            lines.append("        audio.play(Sound.SPRING, wait=True)")
        elif snd == "sad":
            lines.append("        audio.play(Sound.SAD, wait=True)")

        speak = str(rule.get("speak_text") or "").strip()
        if speak:
            safe_txt = speak.replace('"', "").replace("'", "")[:64]
            if safe_txt.lower().startswith("wee"):
                lines.append("        speech.pronounce('WIY5IY4IY3', speed=90, pitch=55)")
            else:
                lines.append(f'        speech.say("{safe_txt}", speed=88, pitch=64)')

        lines.append("        last_ms = running_time()")
        return lines

    trigger_conds = {
        "lift": "(now - last_ms > 1200) and (abs(dz) > 380 or mag > 1500 or mag < 520)",
        "tilt_left": "(now - last_ms > 1000) and (x < -450)",
        "tilt_right": "(now - last_ms > 1000) and (x > 450)",
        "shake": "(now - last_ms > 1200) and accelerometer.was_gesture('shake')",
        "button_a": "button_a.was_pressed()",
        "button_b": "button_b.was_pressed()",
        "logo_touch": "(now - last_ms > 1000) and pin_logo.is_touched()",
        "pir_motion": f"(now - last_ms > 1200) and ({pir_pin_var or 'pin2'}.read_digital() == 1)",
    }

    branches: List[str] = []
    for idx, rule in enumerate(sim_rules):
        trig = str(rule.get("trigger") or "").lower()
        cond = trigger_conds.get(trig)
        if not cond:
            continue
        kw = "if" if idx == 0 else "elif"
        branches.append(f"    {kw} {cond}:")
        branches.extend(_action_block(rule))

    if not branches:
        branches = [
            "    if button_a.was_pressed():",
            "        display.show(Image.HEART)",
            "        audio.play(Sound.HAPPY, wait=True)",
        ]

    loop = [
        "while True:",
        "    now = running_time()",
        "    x, y, z = accelerometer.get_x(), accelerometer.get_y(), accelerometer.get_z()",
        "    mag = math.sqrt(x*x + y*y + z*z)",
        "    dz = z - last_z",
        "    last_z = last_z * 0.8 + z * 0.2",
        *branches,
        "    sleep(35)",
    ]

    return "\n".join(imports) + "\n\n" + "\n".join(setup) + "\n\n" + "\n".join(loop) + "\n"


def _sanitize_sim_rules(raw_rules: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cleaned: List[Dict[str, Any]] = []
    seen_triggers = set()
    for r in raw_rules:
        if not isinstance(r, dict):
            continue
        trig = str(r.get("trigger") or "").strip().lower()
        if trig not in VALID_TRIGGERS or trig in seen_triggers:
            continue
        seen_triggers.add(trig)
        icon = str(r.get("led_icon") or "HAPPY").strip().upper()
        if icon not in VALID_LED_ICONS:
            icon = "HAPPY"
        snd = str(r.get("sound_effect") or "none").strip().lower()
        if snd not in VALID_SOUNDS:
            snd = "none"
        servo_ang = r.get("servo_angle")
        if servo_ang is not None:
            try:
                servo_ang = max(0, min(180, int(float(servo_ang))))
            except (TypeError, ValueError):
                servo_ang = None
        np_hex = r.get("neopixel_hex")
        if np_hex is not None:
            np_str = str(np_hex).strip()
            np_hex = np_str if re.match(r"^#[0-9a-fA-F]{6}$", np_str) else None
        cleaned.append(
            {
                "trigger": trig,
                "led_icon": icon,
                "speak_text": str(r.get("speak_text") or "").strip()[:80],
                "sound_effect": snd,
                "servo_angle": servo_ang,
                "neopixel_hex": np_hex,
            }
        )
    return cleaned


def apply_deterministic_copilot_fallback(project: Dict[str, Any], user_message: str) -> Dict[str, Any]:
    """Deterministic local parser for common natural-language micro:bit instructions."""
    msg = user_message.strip()
    low = msg.lower()
    attachments = [dict(a) for a in (project.get("attachments") or [])]
    rules = [dict(r) for r in (project.get("sim_rules") or [])]
    changes: List[str] = []

    def _upsert_rule(trig: str, updates: Dict[str, Any]) -> None:
        existing = next((r for r in rules if r.get("trigger") == trig), None)
        if existing is None:
            existing = {
                "trigger": trig,
                "led_icon": "HAPPY",
                "speak_text": "",
                "sound_effect": "none",
                "servo_angle": None,
                "neopixel_hex": None,
            }
            rules.append(existing)
        existing.update({k: v for k, v in updates.items() if v is not None})

    def _ensure_part(acc_id: str) -> None:
        if any(a.get("accessory_id") == acc_id for a in attachments):
            return
        spec = ACCESSORY_BY_ID.get(acc_id)
        if not spec:
            return
        used = {a.get("pin") for a in attachments}
        pin = next((p for p in spec["allowed_signal_pins"] if p not in used), spec["default_pin"])
        attachments.append(
            {
                "id": f"att_{uuid.uuid4().hex[:6]}",
                "accessory_id": acc_id,
                "label": spec["name"],
                "pin": pin,
                "secondary_pin": spec.get("secondary_pin"),
            }
        )
        changes.append(f"attached {spec['name']} on {pin}")

    # Detect part attachment requests (including all 4 Hiwonder PuppyPi Kit modules!)
    if "temp" in low or "humid" in low or "aht10" in low:
        _ensure_part("hiwonder_temp_hum_v11")
    if "touch" in low and ("sensor" in low or "board" in low or "pad" in low or "hiwonder" in low):
        _ensure_part("hiwonder_touch_sensor")
    if "ultrasonic" in low or "distance" in low or "v5.6" in low:
        _ensure_part("hiwonder_ultrasonic_v56")
    if "matrix" in low or "8x16" in low or "tm1640" in low:
        _ensure_part("hiwonder_led_matrix_8x16")
    if "lidar" in low or "ld19" in low:
        _ensure_part("ld19_lidar")
    if "wonderecho" in low or "ai box" in low:
        _ensure_part("wonderecho_ai_box")
    if "servo" in low:
        _ensure_part("sg90_servo")
    if "neopixel" in low or "rgb" in low or "led strip" in low:
        _ensure_part("neopixel_8")
    if "speaker" in low or "buzzer" in low:
        _ensure_part("external_speaker")
    if "oled" in low or "screen" in low:
        _ensure_part("oled_ssd1306")

    # Extract quoted phrase if present (e.g. say "Weeee!")
    quoted = re.search(r'["\']([^"\']{1,60})["\']', msg)
    spoken = quoted.group(1) if quoted else ("Weeee!" if "wee" in low else "")

    # Detect color hint
    color_map = {
        "cyan": "#22d3ee",
        "blue": "#3b82f6",
        "purple": "#a855f7",
        "pink": "#ec4899",
        "red": "#ef4444",
        "green": "#22c55e",
        "yellow": "#facc15",
        "orange": "#f97316",
    }
    picked_color = next((hx for cname, hx in color_map.items() if cname in low), None)

    # Detect angle hint (e.g. 180 deg)
    ang_match = re.search(r"(\d{1,3})\s*(?:deg|degree|°)", low)
    picked_angle = int(ang_match.group(1)) if ang_match else None

    if any(w in low for w in ("lift", "tilt", "drop", "fly")):
        trig = "tilt_left" if "tilt left" in low else ("tilt_right" if "tilt right" in low else "lift")
        _upsert_rule(
            trig,
            {
                "led_icon": "SURPRISED",
                "speak_text": spoken or "Weeee!",
                "sound_effect": "slide",
                "neopixel_hex": picked_color,
                "servo_angle": picked_angle,
            },
        )
        changes.append(f"wired '{trig}' to say '{spoken or 'Weeee!'}' with slide sound")

    if any(w in low for w in ("left button", "button a", "btn a")):
        _upsert_rule(
            "button_a",
            {
                "led_icon": "HEART" if "heart" in low else "ARROW_W",
                "speak_text": spoken if ("lift" not in low and "tilt" not in low) else "",
                "sound_effect": "chime" if any(w in low for w in ("sound", "chime", "play", "melody", "beep")) else "giggle",
                "servo_angle": picked_angle if picked_angle is not None else (180 if "servo" in low else None),
                "neopixel_hex": picked_color,
            },
        )
        changes.append("configured Button A (left) behavior")

    if any(w in low for w in ("right button", "button b", "btn b")):
        _upsert_rule(
            "button_b",
            {
                "led_icon": "HAPPY",
                "speak_text": spoken if ("lift" not in low and "tilt" not in low and "left" not in low) else "",
                "sound_effect": "giggle",
                "servo_angle": picked_angle if picked_angle is not None else (0 if "servo" in low else None),
                "neopixel_hex": picked_color,
            },
        )
        changes.append("configured Button B (right) behavior")

    if "shake" in low:
        _upsert_rule(
            "shake",
            {
                "led_icon": "CONFUSED",
                "speak_text": spoken or "Whoa! Stop shaking me!",
                "sound_effect": "spring",
            },
        )
        changes.append("configured Shake reaction")

    if "logo" in low or "touch" in low:
        _upsert_rule(
            "logo_touch",
            {
                "led_icon": "HEART",
                "speak_text": spoken or "That tickles!",
                "sound_effect": "giggle",
                "neopixel_hex": picked_color,
            },
        )
        changes.append("configured Touch Logo reaction")

    enclosure_cfg = sanitize_enclosure_config(project.get("enclosure_config"))
    custom_shapes = sanitize_custom_shapes(project.get("custom_shapes"))

    # Detect 3D-printable enclosure / mechanical CAD requests
    if any(w in low for w in ("enclosure", "case", "shell", "housing", "3d print", "stl", "stand", "tray", "cradle", "box")):
        enclosure_cfg = auto_fit_enclosure_config(
            str(project.get("board_id") or "microbit_v2"),
            attachments,
            custom_shapes,
            existing=enclosure_cfg,
        )
        if "snap" in low:
            enclosure_cfg["style"] = "snap_fit_case"
        elif "stand" in low or "desk" in low:
            enclosure_cfg["style"] = "desk_stand"
        elif "tray" in low or "cradle" in low or "open" in low:
            enclosure_cfg["style"] = "open_tray_cradle"
        elif "plate" in low or "mount" in low:
            enclosure_cfg["style"] = "mounting_plate_bracket"
        else:
            enclosure_cfg["style"] = "box_with_lid"
        wall_m = re.search(r"(\d+(?:\.\d+)?)\s*mm\s*(?:wall|thick)", low)
        if wall_m:
            enclosure_cfg["wall_mm"] = round(max(1.2, min(6.0, float(wall_m.group(1)))), 2)
        if "vent" in low or "slot" in low:
            enclosure_cfg["include_vent_slots"] = True
        if "no lid" in low or "without lid" in low:
            enclosure_cfg["include_lid"] = False
        changes.append(
            f"auto-fitted {enclosure_cfg['style'].replace('_', ' ')} enclosure ({enclosure_cfg['width_mm']}×{enclosure_cfg['length_mm']}×{enclosure_cfg['height_mm']} mm, {enclosure_cfg['wall_mm']} mm wall)"
        )

    if any(w in low for w in ("bracket", "standoff", "pillar", "cylinder")) and "enclosure" not in low:
        kind = "bracket_l" if "bracket" in low else ("standoff_post" if "standoff" in low else "cylinder")
        dim_m = re.search(r"(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)(?:\s*[x×]\s*(\d+(?:\.\d+)?))?", low)
        sz = (
            [float(dim_m.group(1)), float(dim_m.group(2)), float(dim_m.group(3) or 12.0)]
            if dim_m
            else [24.0, 20.0, 12.0]
        )
        custom_shapes = sanitize_custom_shapes(
            [
                *custom_shapes,
                {
                    "name": f"AI {kind.replace('_', ' ').title()}",
                    "kind": kind,
                    "size_mm": sz,
                    "position_mm": [0.0, 36.0, 0.0],
                    "color_hex": picked_color or "#f97316",
                },
            ]
        )
        changes.append(f"added 3D-printable {kind} ({sz[0]}×{sz[1]}×{sz[2]} mm)")

    clean_rules = _sanitize_sim_rules(rules)
    code = compile_rules_to_micropython(attachments, clean_rules, project_name=str(project.get("name") or "Prototype"))
    reply = (
        "Updated your 3D twin & CAD model: " + "; ".join(changes) + ". Inspect it in Physical, Schematic, or Structure view!"
        if changes
        else "I've refreshed your 3D simulator rules and MicroPython code. Try clicking Button A, Button B, or asking me to build a 3D-printable enclosure!"
    )
    return {
        "assistant_reply": reply,
        "attachments": attachments,
        "sim_rules": clean_rules,
        "enclosure_config": enclosure_cfg,
        "custom_shapes": custom_shapes,
        "code": code,
        "provider": "local_copilot",
    }


def _extract_json_obj(text: str) -> Dict[str, Any]:
    s = text.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    i0 = s.find("{")
    i1 = s.rfind("}")
    if i0 >= 0 and i1 > i0:
        s = s[i0 : i1 + 1]
    parsed = json.loads(s)
    return parsed if isinstance(parsed, dict) else {}


async def run_microbit_copilot_turn(
    *,
    project: Dict[str, Any],
    user_message: str,
    openrouter_api_key: Optional[str] = None,
    openrouter_model: str = "google/gemini-2.5-flash",
) -> Dict[str, Any]:
    """Run one conversational AI Co-Pilot turn updating 3D parts, sim_rules, and MicroPython."""
    if not openrouter_api_key:
        return apply_deterministic_copilot_fallback(project, user_message)

    acc_summary = [
        {"id": a["id"], "name": a["name"], "allowed_pins": a["allowed_signal_pins"], "default_pin": a["default_pin"]}
        for a in MICROBIT_ACCESSORIES
    ]
    system_prompt = (
        "You are an expert BBC micro:bit v2.2 Hardware & MicroPython Co-Pilot embedded in a live 3D Digital Twin simulator.\n"
        "You MUST return ONLY raw JSON (no markdown fences) with keys:\n"
        "- assistant_reply (string, concise friendly explanation of what changed and how to test it in 3D)\n"
        "- attachments (array of {accessory_id, label, pin, secondary_pin} using ONLY valid catalog IDs and conflict-free pins)\n"
        "- sim_rules (array of {trigger, led_icon, speak_text, sound_effect, servo_angle, neopixel_hex})\n"
        f"Valid triggers: {sorted(VALID_TRIGGERS)}\n"
        f"Valid led_icons: {sorted(VALID_LED_ICONS)}\n"
        f"Valid sound_effects: {sorted(VALID_SOUNDS)}\n"
        f"Valid accessories catalog: {json.dumps(acc_summary)}\n"
        f"Valid pins: {[p['id'] for p in MICROBIT_V2_PINS]}\n"
        "Preserve existing attachments and sim_rules unless the user asks to modify or remove them."
    )

    state_msg = (
        f"Current project '{project.get('name')}':\n"
        f"attachments={json.dumps(project.get('attachments') or [])}\n"
        f"sim_rules={json.dumps(project.get('sim_rules') or [])}\n\n"
        f"User request: {user_message}"
    )

    payload = {
        "model": openrouter_model or "google/gemini-2.5-flash",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": state_msg},
        ],
        "temperature": 0.2,
        "max_tokens": 1600,
    }
    headers = {
        "Authorization": f"Bearer {openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://twinscan.eigenia.local",
        "X-Title": "Eigenia micro:bit v2.2 AI Co-Pilot",
    }

    for attempt in range(1, MAX_LLM_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=35.0) as client:
                resp = await client.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload)
                resp.raise_for_status()
                body = resp.json()
            raw_text = str(body["choices"][0]["message"]["content"] or "")
            parsed = _extract_json_obj(raw_text)

            raw_att = parsed.get("attachments")
            attachments: List[Dict[str, Any]] = []
            if isinstance(raw_att, list):
                for item in raw_att:
                    if not isinstance(item, dict):
                        continue
                    aid = str(item.get("accessory_id") or "")
                    spec = ACCESSORY_BY_ID.get(aid)
                    if not spec:
                        continue
                    attachments.append(
                        {
                            "id": str(item.get("id") or f"att_{uuid.uuid4().hex[:6]}"),
                            "accessory_id": aid,
                            "label": str(item.get("label") or spec["name"])[:80],
                            "pin": str(item.get("pin") or spec["default_pin"]).upper(),
                            "secondary_pin": item.get("secondary_pin") or spec.get("secondary_pin"),
                        }
                    )
            else:
                attachments = list(project.get("attachments") or [])

            sim_rules = _sanitize_sim_rules(parsed.get("sim_rules") or project.get("sim_rules") or [])
            enclosure_cfg = (
                sanitize_enclosure_config(parsed.get("enclosure_config"))
                if isinstance(parsed.get("enclosure_config"), dict)
                else sanitize_enclosure_config(project.get("enclosure_config"))
            )
            custom_shapes = (
                sanitize_custom_shapes(parsed.get("custom_shapes"))
                if isinstance(parsed.get("custom_shapes"), list)
                else sanitize_custom_shapes(project.get("custom_shapes"))
            )
            code = compile_rules_to_micropython(
                attachments,
                sim_rules,
                project_name=str(project.get("name") or "Prototype"),
            )
            return {
                "assistant_reply": str(parsed.get("assistant_reply") or "Updated your 3D twin, CAD model, and code!"),
                "attachments": attachments,
                "sim_rules": sim_rules,
                "enclosure_config": enclosure_cfg,
                "custom_shapes": custom_shapes,
                "code": code,
                "provider": openrouter_model,
            }
        except Exception as exc:
            sys.stderr.write(f"[microbit.copilot] OpenRouter error attempt {attempt}/{MAX_LLM_RETRIES}: {exc}\n")
            if attempt < MAX_LLM_RETRIES:
                await asyncio.sleep(1.0 * attempt)

    # Graceful fallback if OpenRouter fails
    return apply_deterministic_copilot_fallback(project, user_message)
