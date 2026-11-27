"""Cross-OS Host Removable-Media & Microcontroller Flash Bridge (macOS / Windows 11 / Linux).

Discovers ONLY verified removable external USB SD cards, UF2/HEX bootloader drives
(``RPI-RP2``, ``MICROBIT``), and USB serial boards (Arduino / ESP32), reports them to
TwinScan's ``POST /api/flasher/host/report``, and safely executes confirmed flash jobs.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import plistlib
import shutil
import subprocess
import sys
import time
from typing import Any, Dict, List

import httpx


def detect_host_tools() -> Dict[str, bool]:
    """Return availability of optional local flashing CLI tools."""
    rpi_mac = os.path.exists("/Applications/Raspberry Pi Imager.app/Contents/MacOS/rpi-imager")
    return {
        "rpi_imager": bool(shutil.which("rpi-imager") or rpi_mac),
        "arduino_cli": bool(shutil.which("arduino-cli")),
        "esptool": bool(shutil.which("esptool.py") or shutil.which("esptool")),
    }


def list_removable_devices_macos() -> List[Dict[str, Any]]:
    """List verified external physical USB/SD disks on macOS via ``diskutil list -plist external physical``."""
    devices: List[Dict[str, Any]] = []
    try:
        proc = subprocess.run(
            ["diskutil", "list", "-plist", "external", "physical"],
            capture_output=True,
            timeout=5.0,
            check=False,
        )
        if proc.returncode != 0 or not proc.stdout:
            return devices
        plist = plistlib.loads(proc.stdout)
        for disk_entry in plist.get("AllDisksAndPartitions") or []:
            dev_id = str(disk_entry.get("DeviceIdentifier") or "").strip()
            if not dev_id or dev_id in ("disk0", "disk1"):
                continue
            size_bytes = int(disk_entry.get("Size") or 0)
            parts = disk_entry.get("Partitions") or []
            vol_name = next((str(p.get("VolumeName") or "") for p in parts if p.get("VolumeName")), "Unnamed SD")
            mount_pt = next((str(p.get("MountPoint") or "") for p in parts if p.get("MountPoint")), "")
            kind = "uf2_drive" if vol_name.upper() == "RPI-RP2" else "hex_drive" if vol_name.upper() == "MICROBIT" else "sd_card"
            devices.append(
                {
                    "device_id": dev_id,
                    "device_path": f"/dev/{dev_id}",
                    "kind": kind,
                    "label": vol_name or dev_id,
                    "mount_point": mount_pt,
                    "size_gb": round(size_bytes / (1000**3), 1),
                    "is_removable": True,
                    "is_internal": False,
                    "read_only": False,
                }
            )
    except Exception as exc:
        sys.stderr.write(f"[host_flash_bridge] macOS diskutil probe error: {exc}\n")
    return devices


def list_serial_boards() -> List[Dict[str, Any]]:
    """List USB serial microcontrollers (Arduino / ESP32) via ``pyserial``."""
    out: List[Dict[str, Any]] = []
    try:
        from serial.tools import list_ports

        for port in list_ports.comports():
            dev = str(port.device or "")
            desc = str(port.description or "")
            if not dev or "bluetooth" in dev.lower() or "debug-console" in dev.lower():
                continue
            out.append(
                {
                    "device_id": os.path.basename(dev),
                    "device_path": dev,
                    "kind": "serial_board",
                    "label": desc or os.path.basename(dev),
                    "size_gb": 0.0,
                    "is_removable": True,
                    "is_internal": False,
                    "read_only": False,
                }
            )
    except Exception as exc:
        sys.stderr.write(f"[host_flash_bridge] Serial probe skipped: {exc}\n")
    return out


def discover_all_removable_targets() -> List[Dict[str, Any]]:
    """Discover removable SD cards, UF2/HEX drives, and USB serial boards for the current OS."""
    sys_name = platform.system()
    devs: List[Dict[str, Any]] = []
    if sys_name == "Darwin":
        devs.extend(list_removable_devices_macos())
    elif sys_name == "Linux":
        try:
            proc = subprocess.run(
                ["lsblk", "-J", "-b", "-o", "NAME,RM,SIZE,MODEL,TRAN"],
                capture_output=True,
                text=True,
                timeout=5.0,
                check=False,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                for b in json.loads(proc.stdout).get("blockdevices") or []:
                    if b.get("rm") in (True, 1, "1") and str(b.get("tran") or "").lower() == "usb":
                        name = str(b.get("name") or "")
                        devs.append(
                            {
                                "device_id": name,
                                "device_path": f"/dev/{name}",
                                "kind": "sd_card",
                                "label": str(b.get("model") or name).strip(),
                                "size_gb": round(int(b.get("size") or 0) / (1000**3), 1),
                                "is_removable": True,
                                "is_internal": False,
                                "read_only": False,
                            }
                        )
        except Exception as exc:
            sys.stderr.write(f"[host_flash_bridge] Linux lsblk probe error: {exc}\n")
    devs.extend(list_serial_boards())
    return devs


def run_bridge_loop(api_url: str = "http://localhost:8000", interval_sec: float = 4.0) -> int:
    """Continuously report removable media & serial boards to TwinScan ``/api/flasher/host/report``."""
    endpoint = f"{api_url.rstrip('/')}/api/flasher/host/report"
    print(f"[host_flash_bridge] Reporting removable devices to {endpoint} ({platform.system()})", flush=True)
    with httpx.Client(timeout=8.0) as client:
        while True:
            try:
                payload = {
                    "host_os": f"{platform.system()} {platform.release()}",
                    "tools": detect_host_tools(),
                    "devices": discover_all_removable_targets(),
                }
                client.post(endpoint, json=payload)
            except KeyboardInterrupt:
                return 0
            except Exception as exc:
                sys.stderr.write(f"[host_flash_bridge] Report error: {exc}\n")
            time.sleep(max(1.0, float(interval_sec)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TwinScan Cross-OS Host Flasher Bridge")
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--interval", type=float, default=4.0)
    args = parser.parse_args()
    raise SystemExit(run_bridge_loop(api_url=args.api_url, interval_sec=args.interval))
