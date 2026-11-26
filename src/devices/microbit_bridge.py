"""Pure-stdlib BBC micro:bit v2.21 USB DAPLink probe, MicroPython templates, and CDC serial bridge.

Uses ZERO external packages (only Python stdlib ``glob``, ``os``, ``select``, ``termios``,
``time``, ``json``) to detect connected micro:bit boards, build 5x5 LED matrix MicroPython
snippets, and send interactive REPL commands with 3x retry and ``sys.stderr`` logging.
"""

from __future__ import annotations

import glob
import json
import os
import re
import select
import sys
import termios
import time
from copy import deepcopy
from typing import Any, Dict, List, Optional, Sequence

MICROBIT_TEMPLATES: List[Dict[str, str]] = [
    {
        "id": "serial_sensor_hub",
        "name": "USB Serial Sensor Hub (JSON @ 115200)",
        "description": "Streams accelerometer, compass, temperature, light level, sound level, and button states as JSON lines over USB CDC.",
        "language": "python",
        "code": (
            "from microbit import *\n"
            "import json\n"
            "uart.init(baudrate=115200)\n"
            "display.show(Image.HAPPY)\n"
            "while True:\n"
            "    payload = {\n"
            "        'ax': accelerometer.get_x(),\n"
            "        'ay': accelerometer.get_y(),\n"
            "        'az': accelerometer.get_z(),\n"
            "        'temp_c': temperature(),\n"
            "        'light': display.read_light_level(),\n"
            "        'sound': microphone.sound_level(),\n"
            "        'btn_a': button_a.is_pressed(),\n"
            "        'btn_b': button_b.is_pressed(),\n"
            "    }\n"
            "    print(json.dumps(payload))\n"
            "    sleep(500)\n"
        ),
    },
    {
        "id": "led_status_companion",
        "name": "Eigenia Lab Status Badge & Alert Chime",
        "description": "Displays live TwinScan alerts on the 5x5 LED matrix and plays an audible chime when triggered over USB serial.",
        "language": "python",
        "code": (
            "from microbit import *\n"
            "import music\n"
            "display.scroll('OX OK', wait=False, loop=False)\n"
            "while True:\n"
            "    if uart.any():\n"
            "        line = str(uart.readline(), 'utf-8').strip()\n"
            "        if line.startswith('ALERT:'):\n"
            "            display.show(Image.NO)\n"
            "            music.pitch(880, 180)\n"
            "            display.scroll(line[6:], wait=True)\n"
            "        elif line:\n"
            "            display.scroll(line, wait=True)\n"
            "    sleep(100)\n"
        ),
    },
    {
        "id": "ble_room_beacon",
        "name": "2.4 GHz Radio Door / Motion Beacon",
        "description": "Battery-powered micro:bit v2 vibration & magnetic reed beacon broadcasting lightweight room events on channel 7.",
        "language": "python",
        "code": (
            "from microbit import *\n"
            "import radio\n"
            "radio.on()\n"
            "radio.config(channel=7, power=6)\n"
            "display.show(Image.TARGET)\n"
            "while True:\n"
            "    if accelerometer.was_gesture('shake') or button_a.was_pressed():\n"
            "        radio.send('MOTION:DOOR_1')\n"
            "        display.show(Image.SURPRISED)\n"
            "        sleep(800)\n"
            "        display.show(Image.TARGET)\n"
            "    sleep(150)\n"
        ),
    },
]

_SAFE_ICONS = frozenset(
    {
        "HEART",
        "HAPPY",
        "SAD",
        "YES",
        "NO",
        "SURPRISED",
        "TARGET",
        "DIAMOND",
        "SQUARE",
        "TRIANGLE",
        "PACMAN",
        "GHOST",
        "SKULL",
        "ARROW_N",
        "ARROW_E",
        "ARROW_S",
        "ARROW_W",
    }
)


def probe_microbit_usb() -> Dict[str, Any]:
    """Scan local host serial devices and mounted volumes for BBC micro:bit v2 DAPLink.

    Returns:
        Dictionary ``{"ports": [...], "volumes": [...], "detected": bool}``.
    """
    port_patterns = (
        "/dev/cu.usbmodem*",
        "/dev/tty.usbmodem*",
        "/dev/ttyACM*",
        "/dev/serial/by-id/*MICROBIT*",
        "/dev/serial/by-id/*mbed*",
        "/dev/serial/by-id/*DAPLink*",
    )
    volume_patterns = (
        "/Volumes/MICROBIT*",
        "/media/*/MICROBIT*",
        "/mnt/*/MICROBIT*",
    )
    ports: List[str] = []
    seen_ports = set()
    for pat in port_patterns:
        for match in sorted(glob.glob(pat)):
            if match not in seen_ports:
                seen_ports.add(match)
                ports.append(match)

    volumes: List[str] = []
    seen_vols = set()
    for pat in volume_patterns:
        for match in sorted(glob.glob(pat)):
            if os.path.isdir(match) and match not in seen_vols:
                seen_vols.add(match)
                volumes.append(match)

    return {
        "ports": ports,
        "volumes": volumes,
        "detected": bool(ports or volumes),
    }


def generate_microbit_template(template_id: str) -> Dict[str, Any]:
    """Retrieve a downloadable MicroPython firmware template for BBC micro:bit v2.21.

    Args:
        template_id: One of ``serial_sensor_hub``, ``led_status_companion``, or ``ble_room_beacon``.

    Returns:
        Template dictionary ``{id, name, description, language, code}``.

    Raises:
        ValueError: If ``template_id`` is not recognized.
    """
    tid = str(template_id or "").strip()
    for tpl in MICROBIT_TEMPLATES:
        if tpl["id"] == tid:
            return deepcopy(tpl)
    raise ValueError(f"Unknown micro:bit template_id: {template_id!r}")


def build_led_matrix_python(grid_5x5: Sequence[Sequence[int]]) -> str:
    """Convert a 5x5 LED brightness grid (0..9) into runnable MicroPython code.

    Args:
        grid_5x5: 5 rows of 5 integer brightness values (0 = off, 1..9 = on).

    Returns:
        MicroPython snippet displaying the exact 5x5 matrix on BBC micro:bit v2.21.
    """
    rows: List[str] = []
    for r in range(5):
        row_src = grid_5x5[r] if r < len(grid_5x5) else []
        digits: List[str] = []
        for c in range(5):
            raw_val = row_src[c] if c < len(row_src) else 0
            try:
                v = int(raw_val)
            except (TypeError, ValueError):
                v = 0
            v = max(0, min(9, v))
            digits.append(str(v))
        rows.append("".join(digits))
    pattern = ":".join(rows)
    return f"from microbit import *; display.show(Image('{pattern}'))"


def _build_command_python(action: str, payload: Any) -> str:
    act = str(action or "").strip().lower()
    if act == "show_text":
        text = str(payload.get("text", "OX") if isinstance(payload, dict) else (payload or "OX"))
        clean = re.sub(r"[^A-Za-z0-9 .,!?:/_-]", "", text)[:48] or "OX"
        return f"from microbit import *; display.scroll({json.dumps(clean)}, wait=False)"
    if act == "show_icon":
        icon = str(payload.get("icon", "HEART") if isinstance(payload, dict) else (payload or "HEART")).upper()
        if icon not in _SAFE_ICONS:
            icon = "HEART"
        return f"from microbit import *; display.show(Image.{icon})"
    if act == "play_tone":
        freq = 880
        dur = 250
        if isinstance(payload, dict):
            freq = max(100, min(4000, int(payload.get("freq", 880))))
            dur = max(50, min(2000, int(payload.get("duration_ms", 250))))
        return f"import music; music.pitch({freq}, {dur})"
    if act == "set_matrix":
        grid = payload.get("grid") if isinstance(payload, dict) else payload
        if not isinstance(grid, (list, tuple)):
            grid = [[9 if (r == c or r + c == 4) else 0 for c in range(5)] for r in range(5)]
        return build_led_matrix_python(grid)
    if act == "read_sensors":
        return (
            "from microbit import *; import json; "
            "print(json.dumps({'temp_c': temperature(), 'light': display.read_light_level(), "
            "'ax': accelerometer.get_x(), 'ay': accelerometer.get_y(), 'az': accelerometer.get_z()}))"
        )
    raise ValueError(f"Unsupported micro:bit action: {action!r}")


def _write_repl_termios(port: str, python_code: str, read_response: bool = False) -> str:
    """Send a one-line MicroPython REPL command over ``port`` using stdlib ``os.open`` + ``termios``."""
    fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        attrs = termios.tcgetattr(fd)
        attrs[0] = 0
        attrs[1] = 0
        attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
        attrs[3] = 0
        attrs[4] = termios.B115200
        attrs[5] = termios.B115200
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        # Interrupt running loop (Ctrl-C) and enter normal REPL line
        os.write(fd, b"\x03\r\n")
        time.sleep(0.12)
        os.write(fd, (python_code + "\r\n").encode("utf-8"))
        if not read_response:
            time.sleep(0.15)
            return ""
        buf = bytearray()
        deadline = time.monotonic() + 1.2
        while time.monotonic() < deadline:
            r, _, _ = select.select([fd], [], [], 0.15)
            if not r:
                if b"}" in buf:
                    break
                continue
            try:
                chunk = os.read(fd, 1024)
                if chunk:
                    buf.extend(chunk)
            except BlockingIOError:
                continue
        return buf.decode("utf-8", errors="ignore")
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


def send_microbit_serial_command(
    port: Optional[str],
    action: str,
    payload: Any = None,
) -> Dict[str, Any]:
    """Send a MicroPython command to a USB-connected BBC micro:bit v2.21 (or return preview if absent).

    Retries transient serial I/O errors up to 3 times and logs failures to ``sys.stderr``.
    Never crashes when running inside Docker without USB passthrough — returns a clear
    preview payload with the exact runnable MicroPython code.

    Args:
        port: Optional explicit serial path (e.g. ``"/dev/cu.usbmodem14102"``). Auto-probes when omitted.
        action: One of ``show_text``, ``show_icon``, ``play_tone``, ``read_sensors``, ``set_matrix``.
        payload: Action-specific arguments (text, icon name, freq/duration, or 5x5 grid).

    Returns:
        Dictionary ``{"ok": bool, "detail": str, "preview_code": str, "sensor_data"?: dict}``.
    """
    preview_code = _build_command_python(action, payload)
    target_port = str(port or "").strip()
    if not target_port:
        probed = probe_microbit_usb()
        if probed["ports"]:
            target_port = probed["ports"][0]

    if not target_port or not os.path.exists(target_port):
        return {
            "ok": False,
            "detail": (
                "No micro:bit USB CDC serial port detected on this host/container. "
                "Plug BBC micro:bit v2.21 into USB (or pass --device=/dev/ttyACM0 to Docker) "
                "or flash the MicroPython code preview below."
            ),
            "preview_code": preview_code,
        }

    last_err: Optional[Exception] = None
    want_sensors = str(action).strip().lower() == "read_sensors"
    for attempt in range(1, 4):
        try:
            raw_out = _write_repl_termios(target_port, preview_code, read_response=want_sensors)
            result: Dict[str, Any] = {
                "ok": True,
                "detail": f"Sent '{action}' to BBC micro:bit on {target_port} (115200 8N1).",
                "preview_code": preview_code,
            }
            if want_sensors:
                m = re.search(r"\{[^{}]+\}", raw_out)
                if m:
                    try:
                        result["sensor_data"] = json.loads(m.group(0))
                    except json.JSONDecodeError:
                        result["sensor_data"] = {"raw": raw_out.strip()[:200]}
                else:
                    result["sensor_data"] = {"raw": raw_out.strip()[:200]}
            return result
        except Exception as exc:
            last_err = exc
            sys.stderr.write(
                f"[microbit_bridge] Serial write on {target_port} failed (attempt {attempt}/3): {exc}\n"
            )
            if attempt < 3:
                time.sleep(0.25 * attempt)

    return {
        "ok": False,
        "detail": f"Failed communicating with micro:bit on {target_port} after 3 attempts: {last_err}",
        "preview_code": preview_code,
    }
