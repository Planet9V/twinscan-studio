"""Remote Raspberry Pi 5 USB Serial Bridge for BBC micro:bit v2.2.

Probes, deploys MicroPython ``main.py``, runs live hardware self-tests, and
reads real-time accelerometer / temperature / sound / button telemetry over
``/dev/ttyACM0`` on the connected Raspberry Pi host using Fernet-encrypted
fleet SSH credentials (with 3x retry and ``sys.stderr`` error logging).
"""

from __future__ import annotations

import json
import os
import pty
import select
import sys
import time
from typing import Any, Dict, Optional, Tuple

MAX_BRIDGE_RETRIES = 3


def resolve_microbit_host(robot_store: Any, host_robot_id: Optional[str] = None) -> Tuple[str, str, str, str]:
    """Find the registered Raspberry Pi node hosting the BBC micro:bit v2.2.

    Args:
        robot_store: Registered fleet store with ``list_robots`` and ``get_robot_ssh_password``.
        host_robot_id: Optional explicit robot/Pi UUID.

    Returns:
        Tuple ``(ip_address, ssh_user, ssh_password, host_name)``.

    Raises:
        ValueError: If no suitable Raspberry Pi host is registered.
    """
    if robot_store is None:
        raise ValueError("Fleet robot store unavailable.")
    robots = list(robot_store.list_robots() or [])
    target = None
    if host_robot_id:
        target = next((r for r in robots if r.get("id") == host_robot_id), None)
    if target is None:
        target = next((r for r in robots if "pi 5" in str(r.get("name", "")).lower() or "rasp5" in str(r.get("name", "")).lower()), None)
    if target is None and robots:
        target = robots[0]
    if target is None:
        raise ValueError("No Raspberry Pi host found in Fleet.")
    ip = str(target.get("ip_address") or "").strip()
    user = str(target.get("ssh_user") or "ox").strip()
    pw = ""
    if hasattr(robot_store, "get_robot_ssh_password"):
        pw = robot_store.get_robot_ssh_password(target["id"]) or ""
    return ip, user, pw, str(target.get("name") or ip)


def _ssh_exec(ip: str, user: str, password: str, cmd: str, timeout_s: float = 14.0) -> str:
    last_err = "unknown"
    for attempt in range(1, MAX_BRIDGE_RETRIES + 1):
        try:
            pid, fd = pty.fork()
            if pid == 0:
                os.execvp(
                    "ssh",
                    [
                        "ssh",
                        "-o",
                        "StrictHostKeyChecking=no",
                        "-o",
                        "ConnectTimeout=5",
                        f"{user}@{ip}",
                        cmd,
                    ],
                )
            out = bytearray()
            sent_pw = False
            deadline = time.time() + timeout_s
            while time.time() < deadline:
                r, _, _ = select.select([fd], [], [], 0.2)
                if not r:
                    continue
                try:
                    chunk = os.read(fd, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                out.extend(chunk)
                if not sent_pw and b"password:" in out.lower():
                    os.write(fd, (password + "\n").encode("utf-8"))
                    sent_pw = True
            try:
                os.waitpid(pid, 0)
            except Exception:
                pass
            return out.decode("utf-8", errors="replace")
        except Exception as exc:
            last_err = str(exc)
            sys.stderr.write(f"[microbit.bridge] SSH error attempt {attempt}/{MAX_BRIDGE_RETRIES}: {exc}\n")
            time.sleep(0.4 * attempt)
    raise RuntimeError(f"SSH bridge to {ip} failed: {last_err}")


def probe_microbit_hardware(ip: str, user: str, password: str, host_name: str) -> Dict[str, Any]:
    """Check whether a BBC micro:bit v2.2 (``0d28:0204``) is attached to the host Pi."""
    cmd = r'''python3 - << 'PYEOF'
import json, os, subprocess
usb = subprocess.run(["lsusb"], capture_output=True, text=True).stdout
found = "0d28:0204" in usb.lower()
tty = "/dev/ttyACM0" if os.path.exists("/dev/ttyACM0") else None
drive = os.path.exists("/dev/disk/by-label/MICROBIT")
print("MB_STATUS:" + json.dumps({"connected": found and bool(tty), "usb_detected": found, "serial_port": tty, "flash_drive": drive}))
PYEOF'''
    out = _ssh_exec(ip, user, password, cmd, timeout_s=10.0)
    for line in out.splitlines():
        if "MB_STATUS:" in line:
            data = json.loads(line.split("MB_STATUS:", 1)[1].strip())
            return {**data, "host_ip": ip, "host_name": host_name}
    return {"connected": False, "usb_detected": False, "serial_port": None, "flash_drive": False, "host_ip": ip, "host_name": host_name}


def deploy_micropython_code(ip: str, user: str, password: str, code: str) -> Dict[str, Any]:
    """Upload ``main.py`` via MicroPython raw REPL on ``/dev/ttyACM0`` and soft-reboot."""
    code_json = json.dumps(code)
    cmd = f'''python3 - << 'PYEOF'
import json, serial, time
CODE = {code_json}
s = serial.Serial("/dev/ttyACM0", 115200, timeout=0.5)
s.write(b"\\x03\\x03")
time.sleep(0.35)
s.read(4096)
s.write(b"\\x01")
time.sleep(0.3)
s.read(4096)
payload = f"f = open('main.py', 'w')\\nf.write({{CODE!r}})\\nf.close()\\nprint('DEPLOY_OK')\\n"
s.write(payload.encode("utf-8") + b"\\x04")
time.sleep(0.9)
up_resp = s.read(4096).decode("utf-8", errors="replace")
s.write(b"\\x02")
time.sleep(0.2)
s.write(b"\\x04")
time.sleep(1.2)
boot_resp = s.read(4096).decode("utf-8", errors="replace")
s.close()
print("MB_DEPLOY:" + json.dumps({{"ok": "DEPLOY_OK" in up_resp, "upload": up_resp.strip()[-120:], "boot": boot_resp.strip()[-300:]}}))
PYEOF'''
    out = _ssh_exec(ip, user, password, cmd, timeout_s=15.0)
    for line in out.splitlines():
        if "MB_DEPLOY:" in line:
            return json.loads(line.split("MB_DEPLOY:", 1)[1].strip())
    raise RuntimeError("micro:bit deploy did not return confirmation (check USB cable on Pi 5).")


def read_microbit_live_sensors(ip: str, user: str, password: str, run_chime: bool = False) -> Dict[str, Any]:
    """Read live accelerometer, temperature, light, sound level, and buttons from micro:bit v2.2."""
    chime_line = "audio.play(Sound.HAPPY, wait=True); display.show(Image.YES); " if run_chime else ""
    cmd = f'''python3 - << 'PYEOF'
import json, serial, time
s = serial.Serial("/dev/ttyACM0", 115200, timeout=0.4)
s.write(b"\\x03\\x03")
time.sleep(0.25)
s.read(4096)
s.write(b"\\x01")
time.sleep(0.2)
s.read(4096)
snippet = (
    "from microbit import *; import audio, json; "
    "{chime_line}"
    "d={{'ax':accelerometer.get_x(),'ay':accelerometer.get_y(),'az':accelerometer.get_z(),"
    "'temp_c':temperature(),'light':display.read_light_level(),'sound':microphone.sound_level(),"
    "'btn_a':button_a.is_pressed(),'btn_b':button_b.is_pressed(),'logo':pin_logo.is_touched()}}; "
    "print('SENS:' + json.dumps(d))\\n"
)
s.write(snippet.encode("utf-8") + b"\\x04")
time.sleep(1.0 if {str(run_chime)} else 0.55)
resp = s.read(4096).decode("utf-8", errors="replace")
# Soft-reboot back into user's main.py
s.write(b"\\x02")
time.sleep(0.1)
s.write(b"\\x04")
s.close()
for ln in resp.splitlines():
    if "SENS:" in ln:
        print("MB_SENS:" + ln.split("SENS:", 1)[1].strip())
        break
PYEOF'''
    out = _ssh_exec(ip, user, password, cmd, timeout_s=12.0)
    for line in out.splitlines():
        if "MB_SENS:" in line:
            data = json.loads(line.split("MB_SENS:", 1)[1].strip())
            return {"ok": True, "sensors": data}
    raise RuntimeError("Could not read live sensors from micro:bit v2.2 on /dev/ttyACM0.")
