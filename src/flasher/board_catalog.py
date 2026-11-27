"""Supported Hardware Platforms & Official Raspberry Pi OS Catalog Client.

Provides board metadata (Pi 5, Pi 4, Pi 3 / Zero 2 W, Arduino, ESP32, Pi Pico,
BBC micro:bit) and fetches/caches the official Raspberry Pi Imager v4 OS JSON
catalog with 3x retry, stderr logging, and curated offline fallback.
"""

from __future__ import annotations

import asyncio
import sys
import time
from typing import Any, Dict, List, Optional

import httpx

RPI_OS_CATALOG_URL = "https://downloads.raspberrypi.org/os_list_imagingutility_v4.json"
_CATALOG_CACHE_TTL_SEC = 3600.0
_CATALOG_CACHE: Dict[str, Any] = {"ts": 0.0, "raw": None}

SUPPORTED_PLATFORMS: List[Dict[str, Any]] = [
    {
        "id": "pi5",
        "name": "Raspberry Pi 5",
        "family": "raspberry_pi",
        "flash_method": "sd_image",
        "min_storage_gb": 16,
        "recommended_storage_gb": "32–64 GB (A2/U3)",
        "rpi_tag": "pi5-64bit",
        "supports_headless_provision": True,
        "description": "Flagship 64-bit SBC for PuppyPi Pro, ROS 2 Humble/Jazzy, and high-res camera/AI nodes.",
    },
    {
        "id": "pi4",
        "name": "Raspberry Pi 4 / 400",
        "family": "raspberry_pi",
        "flash_method": "sd_image",
        "min_storage_gb": 16,
        "recommended_storage_gb": "32 GB (A2/U3)",
        "rpi_tag": "pi4-64bit",
        "supports_headless_provision": True,
        "description": "Quad-core 64-bit SBC ideal for Overwatch LAN camera nodes, LiDAR relays, and Docker edge services.",
    },
    {
        "id": "pi3",
        "name": "Raspberry Pi 3 / Zero 2 W",
        "family": "raspberry_pi",
        "flash_method": "sd_image",
        "min_storage_gb": 8,
        "recommended_storage_gb": "16–32 GB",
        "rpi_tag": "pi3-64bit",
        "supports_headless_provision": True,
        "description": "Compact low-power Pi for headless Lite OS sensor nodes, camera relays, and MQTT bridges.",
    },
    {
        "id": "arduino",
        "name": "Arduino (Uno / Nano / Mega / R4)",
        "family": "microcontroller",
        "flash_method": "arduino_cli",
        "min_storage_gb": 0,
        "recommended_storage_gb": "USB Serial (no SD)",
        "rpi_tag": None,
        "supports_headless_provision": False,
        "description": "Flash .ino / .hex firmware over USB serial via arduino-cli for motor drivers, servos, and sensors.",
    },
    {
        "id": "esp32",
        "name": "ESP32 / ESP32-S3",
        "family": "microcontroller",
        "flash_method": "esptool",
        "min_storage_gb": 0,
        "recommended_storage_gb": "USB Serial (no SD)",
        "rpi_tag": None,
        "supports_headless_provision": False,
        "description": "Flash MicroPython or Wi-Fi/BLE sensor firmware over USB serial via esptool.",
    },
    {
        "id": "pico",
        "name": "Raspberry Pi Pico / Pico W",
        "family": "uf2_drive",
        "flash_method": "uf2_copy",
        "min_storage_gb": 0,
        "recommended_storage_gb": "RPI-RP2 USB Drive",
        "rpi_tag": None,
        "supports_headless_provision": False,
        "description": "Zero-sudo drag-and-drop .uf2 bootloader flashing for RP2040/RP2350 controllers.",
    },
    {
        "id": "microbit",
        "name": "BBC micro:bit v2",
        "family": "hex_drive",
        "flash_method": "hex_copy",
        "min_storage_gb": 0,
        "recommended_storage_gb": "MICROBIT USB Drive",
        "rpi_tag": None,
        "supports_headless_provision": False,
        "description": "Zero-sudo .hex flashing onto the mounted MICROBIT USB drive for classroom & sensor builds.",
    },
]

PLATFORM_BY_ID: Dict[str, Dict[str, Any]] = {p["id"]: p for p in SUPPORTED_PLATFORMS}

CURATED_FALLBACK_IMAGES: List[Dict[str, Any]] = [
    {
        "id": "raspios-bookworm-arm64-lite",
        "name": "Raspberry Pi OS Lite (64-bit)",
        "description": "Fastest headless Debian Bookworm 64-bit image (~2.5 GB installed; ideal for 32 GB SD cards).",
        "url": "https://downloads.raspberrypi.org/raspios_lite_arm64_latest",
        "download_mb": 460,
        "extract_mb": 2600,
        "devices": ["pi5-64bit", "pi4-64bit", "pi3-64bit"],
        "recommended": True,
    },
    {
        "id": "raspios-bookworm-arm64",
        "name": "Raspberry Pi OS with Desktop (64-bit)",
        "description": "Full Raspberry Pi Desktop 64-bit (~5.5 GB installed; great on 32 GB or 64 GB SD cards).",
        "url": "https://downloads.raspberrypi.org/raspios_arm64_latest",
        "download_mb": 1180,
        "extract_mb": 5600,
        "devices": ["pi5-64bit", "pi4-64bit", "pi3-64bit"],
        "recommended": False,
    },
    {
        "id": "ubuntu-24-04-server-arm64",
        "name": "Ubuntu Server 24.04 LTS (64-bit)",
        "description": "Native ROS 2 Jazzy & Docker LTS server image for Raspberry Pi 4 & Pi 5 (~8–10 GB with ROS 2).",
        "url": "https://cdimage.ubuntu.com/releases/24.04/release/ubuntu-24.04.1-preinstalled-server-arm64+raspi.img.xz",
        "download_mb": 1320,
        "extract_mb": 4200,
        "devices": ["pi5-64bit", "pi4-64bit"],
        "recommended": False,
    },
]


def _flatten_rpi_entries(entries: List[Dict[str, Any]], tag: Optional[str]) -> List[Dict[str, Any]]:
    """Recursively flatten official Raspberry Pi Imager JSON OS tree."""
    out: List[Dict[str, Any]] = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        if isinstance(item.get("subitems"), list):
            out.extend(_flatten_rpi_entries(item["subitems"], tag))
            continue
        url = str(item.get("url") or "").strip()
        name = str(item.get("name") or "").strip()
        if not url or not name:
            continue
        devices = [str(d) for d in (item.get("devices") or [])]
        if tag and devices and tag not in devices:
            continue
        dl_bytes = int(item.get("image_download_size") or 0)
        ex_bytes = int(item.get("extract_size") or 0)
        out.append(
            {
                "id": str(item.get("extract_sha256") or name.lower().replace(" ", "-"))[:40],
                "name": name,
                "description": str(item.get("description") or "").strip(),
                "url": url,
                "sha256": str(item.get("extract_sha256") or "") or None,
                "release_date": str(item.get("release_date") or "") or None,
                "download_mb": round(dl_bytes / (1024 * 1024), 1) if dl_bytes > 0 else None,
                "extract_mb": round(ex_bytes / (1024 * 1024), 1) if ex_bytes > 0 else None,
                "devices": devices,
                "recommended": "lite (64-bit)" in name.lower(),
            }
        )
    return out


async def fetch_rpi_os_catalog(board_id: str = "pi5", allow_network: bool = True) -> Dict[str, Any]:
    """Fetch official Raspberry Pi Imager OS images compatible with ``board_id``.

    Args:
        board_id: One of ``pi5``, ``pi4``, ``pi3``, or other supported board IDs.
        allow_network: Set ``False`` in offline unit tests to return curated fallback immediately.

    Returns:
        Dictionary with ``board_id``, ``source`` (``official_rpi_json`` or ``curated_fallback``),
        and ``images`` list.
    """
    plat = PLATFORM_BY_ID.get(board_id, PLATFORM_BY_ID["pi5"])
    tag = plat.get("rpi_tag")

    if plat["family"] != "raspberry_pi":
        return {
            "board_id": plat["id"],
            "source": "microcontroller_firmware",
            "images": [
                {
                    "id": f"{plat['id']}-custom-firmware",
                    "name": f"Custom {plat['name']} Firmware Upload",
                    "description": plat["description"],
                    "url": "",
                    "download_mb": None,
                    "extract_mb": None,
                    "devices": [plat["id"]],
                    "recommended": True,
                }
            ],
        }

    now = time.monotonic()
    raw_json = _CATALOG_CACHE.get("raw")
    if allow_network and (raw_json is None or (now - float(_CATALOG_CACHE.get("ts") or 0.0)) > _CATALOG_CACHE_TTL_SEC):
        for attempt in range(1, 4):
            try:
                async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                    resp = await client.get(RPI_OS_CATALOG_URL)
                    resp.raise_for_status()
                    raw_json = resp.json()
                    _CATALOG_CACHE["raw"] = raw_json
                    _CATALOG_CACHE["ts"] = now
                    break
            except Exception as exc:
                sys.stderr.write(f"[flasher.catalog] Attempt {attempt}/3 failed: {exc}\n")
                if attempt < 3:
                    await asyncio.sleep(0.3 * attempt)

    if isinstance(raw_json, dict) and isinstance(raw_json.get("os_list"), list):
        flat = _flatten_rpi_entries(raw_json["os_list"], tag)
        if flat:
            # Keep top 24 most relevant images (prioritizing 64-bit / Lite / Desktop / Ubuntu)
            flat.sort(
                key=lambda x: (
                    0 if "raspberry pi os" in x["name"].lower() else 1 if "ubuntu" in x["name"].lower() else 2,
                    0 if "64-bit" in x["name"].lower() else 1,
                )
            )
            return {
                "board_id": plat["id"],
                "source": "official_rpi_json",
                "images": flat[:24],
            }

    fallback = [img for img in CURATED_FALLBACK_IMAGES if not tag or tag in img["devices"]]
    return {
        "board_id": plat["id"],
        "source": "curated_fallback",
        "images": fallback,
    }
