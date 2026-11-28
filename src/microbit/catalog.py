"""BBC micro:bit v2.2 Hardware Pinout Schematics, Accessory Library & MicroPython Generator.

Provides authoritative electrical pinout definitions for the micro:bit v2.2
(nRF52833), an interactive prototyping accessory catalog, pin-conflict &
step-by-step wiring guide generation, and automatic MicroPython code synthesis.
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

MICROBIT_V2_PINS: List[Dict[str, Any]] = [
    {
        "id": "P0",
        "label": "P0 (Ring 0)",
        "pad_type": "ring",
        "x_mm": -17.5,
        "capabilities": ["Digital I/O", "Analog ADC (10-bit)", "PWM", "Audio Out", "Touch"],
        "voltage": "3.3V",
        "max_ma": 5,
        "notes": "Primary general-purpose ring pad. Great for servos, external speaker, NeoPixels, or analog sensors.",
    },
    {
        "id": "P1",
        "label": "P1 (Ring 1)",
        "pad_type": "ring",
        "x_mm": -8.75,
        "capabilities": ["Digital I/O", "Analog ADC (10-bit)", "PWM", "Touch"],
        "voltage": "3.3V",
        "max_ma": 5,
        "notes": "General-purpose ring pad with ADC & PWM. Ideal for sensors, ultrasonic Trig, or second servo.",
    },
    {
        "id": "P2",
        "label": "P2 (Ring 2)",
        "pad_type": "ring",
        "x_mm": 0.0,
        "capabilities": ["Digital I/O", "Analog ADC (10-bit)", "PWM", "Touch"],
        "voltage": "3.3V",
        "max_ma": 5,
        "notes": "General-purpose ring pad with ADC & PWM. Great for ultrasonic Echo, buttons, or PIR motion.",
    },
    {
        "id": "3V",
        "label": "3V Power Rail",
        "pad_type": "ring",
        "x_mm": 8.75,
        "capabilities": ["3.3V Regulated Power Out (up to 190mA total on v2.2)"],
        "voltage": "3.3V",
        "max_ma": 190,
        "notes": "Powers low-current sensors/OLEDs. For multiple servos or long NeoPixel strips, use external 5V + shared GND.",
    },
    {
        "id": "GND",
        "label": "GND (Ground)",
        "pad_type": "ring",
        "x_mm": 17.5,
        "capabilities": ["Common Ground (0V)"],
        "voltage": "0V",
        "max_ma": 500,
        "notes": "Always connect accessory GND here (and tie external battery GND here for common reference).",
    },
    {
        "id": "P8",
        "label": "P8 (Edge)",
        "pad_type": "edge",
        "x_mm": -13.0,
        "capabilities": ["Digital I/O", "PWM"],
        "voltage": "3.3V",
        "max_ma": 5,
        "notes": "Dedicated digital GPIO on edge breakout (not shared with LED matrix).",
    },
    {
        "id": "P12",
        "label": "P12 (Edge)",
        "pad_type": "edge",
        "x_mm": -4.2,
        "capabilities": ["Digital I/O", "PWM"],
        "voltage": "3.3V",
        "max_ma": 5,
        "notes": "Dedicated digital GPIO on edge breakout.",
    },
    {
        "id": "P13",
        "label": "P13 (SPI SCK)",
        "pad_type": "edge",
        "x_mm": 4.2,
        "capabilities": ["Digital I/O", "SPI Clock (SCK)"],
        "voltage": "3.3V",
        "max_ma": 5,
        "notes": "Hardware SPI Clock pin (requires edge breakout board).",
    },
    {
        "id": "P19",
        "label": "P19 (I2C SCL)",
        "pad_type": "edge",
        "x_mm": 12.8,
        "capabilities": ["I2C Clock (SCL)"],
        "voltage": "3.3V",
        "max_ma": 5,
        "notes": "Shared internal/external I2C bus clock (connect OLED displays, BME280, ToF sensors).",
    },
    {
        "id": "P20",
        "label": "P20 (I2C SDA)",
        "pad_type": "edge",
        "x_mm": 14.8,
        "capabilities": ["I2C Data (SDA)"],
        "voltage": "3.3V",
        "max_ma": 5,
        "notes": "Shared internal/external I2C bus data line (pair with P19 SCL).",
    },
]

PIN_BY_ID: Dict[str, Dict[str, Any]] = {p["id"]: p for p in MICROBIT_V2_PINS}

MICROBIT_ACCESSORIES: List[Dict[str, Any]] = [
    {
        "id": "sg90_servo",
        "name": "SG90 Micro Servo (180°)",
        "category": "actuator",
        "color_hex": "#3b82f6",
        "allowed_signal_pins": ["P0", "P1", "P2", "P8", "P12"],
        "default_pin": "P0",
        "secondary_pin": None,
        "needs_power": True,
        "power_note": "Connect Red to 3V (1 micro servo) or external 5V battery pack with shared GND.",
        "wires": [
            {"from": "Signal (Orange)", "to_role": "signal", "color": "#f97316"},
            {"from": "VCC (Red)", "to_role": "3V", "color": "#ef4444"},
            {"from": "GND (Brown)", "to_role": "GND", "color": "#334155"},
        ],
        "summary": "180° positional micro servo controlled via 50Hz PWM.",
    },
    {
        "id": "external_speaker",
        "name": "External Amplified Speaker / Piezo",
        "category": "audio",
        "color_hex": "#ec4899",
        "allowed_signal_pins": ["P0"],
        "default_pin": "P0",
        "secondary_pin": None,
        "needs_power": False,
        "power_note": "Clip + to P0 and - to GND for much louder audio & speech than the onboard piezo.",
        "wires": [
            {"from": "Audio +", "to_role": "signal", "color": "#ec4899"},
            {"from": "Audio - (GND)", "to_role": "GND", "color": "#334155"},
        ],
        "summary": "External speaker or buzzer on P0 + GND for crisp, loud melodies and speech.",
    },
    {
        "id": "neopixel_8",
        "name": "NeoPixel RGB LED Strip (8 LEDs)",
        "category": "display",
        "color_hex": "#a855f7",
        "allowed_signal_pins": ["P0", "P1", "P2", "P8"],
        "default_pin": "P1",
        "secondary_pin": None,
        "needs_power": True,
        "power_note": "Keep brightness <= 40% when powered from micro:bit 3V rail.",
        "wires": [
            {"from": "DIN (Data In)", "to_role": "signal", "color": "#22d3ee"},
            {"from": "VCC (+3V)", "to_role": "3V", "color": "#ef4444"},
            {"from": "GND", "to_role": "GND", "color": "#334155"},
        ],
        "summary": "Addressable WS2812B RGB LED strip driven natively by MicroPython neopixel.",
    },
    {
        "id": "oled_ssd1306",
        "name": "SSD1306 128×64 I2C OLED Display",
        "category": "display",
        "color_hex": "#06b6d4",
        "allowed_signal_pins": ["P19"],
        "default_pin": "P19",
        "secondary_pin": "P20",
        "needs_power": True,
        "power_note": "Uses hardware I2C (SCL=P19, SDA=P20, address 0x3C).",
        "wires": [
            {"from": "SCL", "to_role": "signal", "color": "#facc15"},
            {"from": "SDA", "to_role": "secondary", "color": "#22d3ee"},
            {"from": "VCC (3.3V)", "to_role": "3V", "color": "#ef4444"},
            {"from": "GND", "to_role": "GND", "color": "#334155"},
        ],
        "summary": "Crisp monochrome I2C OLED display for live sensor readouts & graphics.",
    },
    {
        "id": "hcsr04_ultrasonic",
        "name": "HC-SR04 Ultrasonic Distance Sensor",
        "category": "sensor",
        "color_hex": "#10b981",
        "allowed_signal_pins": ["P1", "P0", "P8"],
        "default_pin": "P1",
        "secondary_pin": "P2",
        "needs_power": True,
        "power_note": "Use 3.3V-compatible HC-SR04P (or voltage divider on Echo for 5V HC-SR04).",
        "wires": [
            {"from": "TRIG", "to_role": "signal", "color": "#10b981"},
            {"from": "ECHO", "to_role": "secondary", "color": "#38bdf8"},
            {"from": "VCC", "to_role": "3V", "color": "#ef4444"},
            {"from": "GND", "to_role": "GND", "color": "#334155"},
        ],
        "summary": "Measures obstacle distance from 2 cm to 400 cm via pulse timing.",
    },
    {
        "id": "pir_motion",
        "name": "PIR Motion Sensor (HC-SR501 / AM312)",
        "category": "sensor",
        "color_hex": "#f59e0b",
        "allowed_signal_pins": ["P2", "P1", "P0", "P8"],
        "default_pin": "P2",
        "secondary_pin": None,
        "needs_power": True,
        "power_note": "AM312 mini PIR runs directly on 3.3V from the micro:bit.",
        "wires": [
            {"from": "OUT (Digital)", "to_role": "signal", "color": "#f59e0b"},
            {"from": "VCC (3.3V)", "to_role": "3V", "color": "#ef4444"},
            {"from": "GND", "to_role": "GND", "color": "#334155"},
        ],
        "summary": "Triggers HIGH when warm motion is detected in the room.",
    },
    {
        "id": "analog_sensor",
        "name": "Analog Sensor (Moisture / Knob / Light)",
        "category": "sensor",
        "color_hex": "#84cc16",
        "allowed_signal_pins": ["P0", "P1", "P2"],
        "default_pin": "P2",
        "secondary_pin": None,
        "needs_power": True,
        "power_note": "Outputs 0..3.3V read as 0..1023 via pinX.read_analog().",
        "wires": [
            {"from": "SIG (Analog)", "to_role": "signal", "color": "#84cc16"},
            {"from": "VCC (3.3V)", "to_role": "3V", "color": "#ef4444"},
            {"from": "GND", "to_role": "GND", "color": "#334155"},
        ],
        "summary": "Reads continuous analog values (0–1023) for soil moisture, dials, or light.",
    },
]

ACCESSORY_BY_ID: Dict[str, Dict[str, Any]] = {a["id"]: a for a in MICROBIT_ACCESSORIES}

STARTER_TEMPLATES: List[Dict[str, str]] = [
    {
        "id": "interactive_reactions",
        "name": "Interactive Lift, Shake & Button Demo",
        "code": (
            "from microbit import *\n"
            "import audio\n"
            "import math\n\n"
            "speaker.on()\n"
            "set_volume(255)\n"
            "display.show(Image.HAPPY)\n"
            "audio.play(Sound.HAPPY, wait=True)\n\n"
            "last_z = accelerometer.get_z()\n"
            "last_ms = running_time()\n\n"
            "while True:\n"
            "    now = running_time()\n"
            "    x, y, z = accelerometer.get_x(), accelerometer.get_y(), accelerometer.get_z()\n"
            "    mag = math.sqrt(x*x + y*y + z*z)\n"
            "    dz = z - last_z\n"
            "    last_z = last_z * 0.8 + z * 0.2\n"
            "    if (now - last_ms > 1200) and (abs(dz) > 380 or mag > 1500 or mag < 520):\n"
            "        display.show(Image.SURPRISED)\n"
            "        audio.play(Sound.SLIDE, wait=True)\n"
            "        display.show(Image.HAPPY)\n"
            "        last_ms = running_time()\n"
            "    elif button_a.was_pressed():\n"
            "        display.show(Image.HEART)\n"
            "        audio.play(Sound.GIGGLE, wait=True)\n"
            "        display.show(Image.HAPPY)\n"
            "    elif button_b.was_pressed():\n"
            "        t_f = int(round(temperature() * 9 / 5 + 32))\n"
            "        display.scroll(str(t_f) + 'F', delay=65)\n"
            "    sleep(35)\n"
        ),
    },
    {
        "id": "tilt_telemetry",
        "name": "Live 3D Tilt & Sensor Serial Streamer",
        "code": (
            "from microbit import *\n"
            "import json\n\n"
            "display.show(Image.TARGET)\n"
            "while True:\n"
            "    pkt = {\n"
            "        'ax': accelerometer.get_x(),\n"
            "        'ay': accelerometer.get_y(),\n"
            "        'az': accelerometer.get_z(),\n"
            "        'temp_c': temperature(),\n"
            "        'light': display.read_light_level(),\n"
            "        'sound': microphone.sound_level(),\n"
            "        'btn_a': button_a.is_pressed(),\n"
            "        'btn_b': button_b.is_pressed(),\n"
            "        'logo': pin_logo.is_touched(),\n"
            "    }\n"
            "    print(json.dumps(pkt))\n"
            "    sleep(150)\n"
        ),
    },
]


def validate_project_wiring(attachments: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Validate pin assignments across attached accessories and build a physical wiring guide.

    Args:
        attachments: Sequence of attachment dicts with ``accessory_id``, ``pin``,
            and optional ``secondary_pin`` and ``label``.

    Returns:
        Dictionary with ``ok``, ``conflicts``, ``warnings``, ``used_pins``,
        and ordered ``wiring_steps``.
    """
    pin_owners: Dict[str, List[str]] = {}
    conflicts: List[str] = []
    warnings: List[str] = []
    wiring_steps: List[Dict[str, str]] = []

    step_num = 1
    for att in attachments:
        acc_id = str(att.get("accessory_id") or "")
        spec = ACCESSORY_BY_ID.get(acc_id)
        if not spec:
            continue
        label = str(att.get("label") or spec["name"])
        sig_pin = str(att.get("pin") or spec["default_pin"]).upper()
        sec_pin = att.get("secondary_pin") or spec.get("secondary_pin")
        if sec_pin:
            sec_pin = str(sec_pin).upper()

        # I2C pins (P19/P20) can be shared across multiple I2C devices
        if sig_pin not in {"3V", "GND", "P19", "P20"}:
            pin_owners.setdefault(sig_pin, []).append(label)
        if sec_pin and sec_pin not in {"3V", "GND", "P19", "P20"}:
            pin_owners.setdefault(sec_pin, []).append(label)

        if sig_pin not in spec["allowed_signal_pins"]:
            warnings.append(f"{label}: {sig_pin} is non-standard (recommended: {', '.join(spec['allowed_signal_pins'])}).")

        for wire in spec.get("wires", []):
            role = wire["to_role"]
            target_pin = sig_pin if role == "signal" else (sec_pin if role == "secondary" else role)
            if not target_pin:
                continue
            wiring_steps.append(
                {
                    "step": str(step_num),
                    "accessory": label,
                    "from_pin": wire["from"],
                    "to_pin": target_pin,
                    "color": wire["color"],
                    "instruction": f"Connect {wire['from']} on {label} → micro:bit {target_pin}",
                }
            )
            step_num += 1

    for pin_id, owners in pin_owners.items():
        if len(owners) > 1:
            conflicts.append(f"Pin conflict on {pin_id}: shared by {' and '.join(owners)}. Reassign one to a free pin.")

    if sum(1 for a in attachments if a.get("accessory_id") == "sg90_servo") >= 2:
        warnings.append("2+ servos detected: power servos from an external 5V battery pack and tie GND to micro:bit GND.")

    return {
        "ok": len(conflicts) == 0,
        "conflicts": conflicts,
        "warnings": warnings,
        "used_pins": sorted(pin_owners.keys()),
        "wiring_steps": wiring_steps,
    }


def generate_prototype_code(attachments: Sequence[Dict[str, Any]], project_name: str = "Prototype") -> str:
    """Auto-generate ready-to-run MicroPython code tailored to the project's attached parts.

    Args:
        attachments: Attached accessory descriptors with pin assignments.
        project_name: Display title embedded in the script header.

    Returns:
        Clean, runnable MicroPython source code string.
    """
    if not attachments:
        return STARTER_TEMPLATES[0]["code"]

    imports = ["from microbit import *"]
    setup_lines = [
        f"# Auto-generated MicroPython for: {project_name}",
        "speaker.on()",
        "set_volume(255)",
        "display.show(Image.HAPPY)",
    ]
    loop_lines: List[str] = []

    has_neopixel = any(a.get("accessory_id") == "neopixel_8" for a in attachments)
    has_speaker = any(a.get("accessory_id") == "external_speaker" for a in attachments)
    if has_neopixel:
        imports.append("import neopixel")
    if has_speaker:
        imports.append("import music")

    for idx, att in enumerate(attachments):
        acc_id = str(att.get("accessory_id") or "")
        pin_name = str(att.get("pin") or "P0").lower()
        pin_var = f"pin{pin_name[1:]}" if pin_name.startswith("p") and pin_name[1:].isdigit() else "pin0"
        sec_raw = str(att.get("secondary_pin") or "P2").lower()
        sec_var = f"pin{sec_raw[1:]}" if sec_raw.startswith("p") and sec_raw[1:].isdigit() else "pin2"

        if acc_id == "sg90_servo":
            setup_lines.append(f"{pin_var}.set_analog_period(20)  # 50Hz PWM for SG90 Servo")
            loop_lines.extend(
                [
                    "    if button_a.was_pressed():",
                    f"        {pin_var}.write_analog(26)   # ~0 deg",
                    "        display.show(Image.ARROW_W)",
                    "    elif button_b.was_pressed():",
                    f"        {pin_var}.write_analog(128)  # ~180 deg",
                    "        display.show(Image.ARROW_E)",
                ]
            )
        elif acc_id == "neopixel_8":
            np_var = f"np_{idx}"
            setup_lines.append(f"{np_var} = neopixel.NeoPixel({pin_var}, 8)")
            loop_lines.extend(
                [
                    f"    for i in range(8): {np_var}[i] = (0, 35, 55)",
                    f"    {np_var}.show()",
                ]
            )
        elif acc_id == "external_speaker":
            loop_lines.extend(
                [
                    "    if pin_logo.is_touched():",
                    f"        music.play(['C5:2', 'E5:2', 'G5:3'], pin={pin_var})",
                ]
            )
        elif acc_id == "pir_motion":
            loop_lines.extend(
                [
                    f"    if {pin_var}.read_digital() == 1:",
                    "        display.show(Image.SURPRISED)",
                    "        print('MOTION_DETECTED')",
                ]
            )
        elif acc_id == "analog_sensor":
            loop_lines.extend(
                [
                    f"    val_{idx} = {pin_var}.read_analog()",
                    f"    print('ANALOG_{pin_name.upper()}:', val_{idx})",
                ]
            )
        elif acc_id == "hcsr04_ultrasonic":
            setup_lines.append(f"# HC-SR04 Ultrasonic: TRIG={pin_var}, ECHO={sec_var}")
            loop_lines.extend(
                [
                    f"    {pin_var}.write_digital(1)",
                    "    sleep(1)",
                    f"    {pin_var}.write_digital(0)",
                ]
            )
        elif acc_id == "oled_ssd1306":
            setup_lines.append("# I2C OLED (P19 SCL / P20 SDA): scan bus on boot")
            setup_lines.append("print('I2C_DEVICES:', [hex(a) for a in i2c.scan()])")

    if not loop_lines:
        loop_lines.append("    print('TEMP_C:', temperature(), 'SOUND:', microphone.sound_level())")

    return (
        "\n".join(imports)
        + "\n\n"
        + "\n".join(setup_lines)
        + "\n\nwhile True:\n"
        + "\n".join(loop_lines)
        + "\n    sleep(150)\n"
    )
