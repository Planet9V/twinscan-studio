"""Automatic Fleet & Live USB/Serial Peripheral Sync into Lab Architect Inventory.

Probes registered Raspberry Pi / robot fleet nodes over SSH for live hardware
model, RAM, and attached USB/CSI/serial peripherals (e.g. BBC micro:bit v2 on
``/dev/ttyACM0``, 4K USB webcams, LD19 LiDAR, Arduinos, ESP32s, Pi Picos) and
idempotently upserts them with full capability metadata into ``robot_ai_store``
inventory so ``/architect`` always designs with your real lab hardware.
"""

from __future__ import annotations

import asyncio
import os
import pty
import re
import select
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

USB_PERIPHERAL_CATALOG: List[Dict[str, Any]] = [
    {
        "vid_pid_prefix": "0d28:0204",
        "name": "BBC micro:bit v2 (Arm CMSIS-DAP)",
        "profile_id": "microbit_v2",
        "category": "microcontroller",
        "manufacturer": "BBC / Arm",
        "model": "micro:bit v2",
        "voltage_v": 3.3,
        "current_ma": 150,
        "interfaces": ["usb_serial", "ble_5_0", "radio_2_4ghz", "i2c", "gpio_edge"],
        "capabilities": [
            "accelerometer_3axis",
            "magnetometer_compass",
            "temperature_sensor",
            "mems_mic_speaker",
            "led_matrix_5x5",
            "ble_radio_2_4ghz",
            "remote_hex_flash",
        ],
    },
    {
        "vid_pid_prefix": "0bda:3035",
        "name": "4K USB Overwatch Webcam",
        "profile_id": "lan_camera_array",
        "category": "vision",
        "manufacturer": "Realtek UVC",
        "model": "4K USB Webcam (0bda:3035)",
        "voltage_v": 5.0,
        "current_ma": 450,
        "interfaces": ["usb_uvc"],
        "capabilities": ["video_1080p_qhd", "overwatch_triangulation", "yolo_face_apriltag"],
    },
    {
        "vid_pid_prefix": "10c4:ea60",
        "name": "LD19 360° LiDAR / CP210x Serial Sensor",
        "profile_id": "generic_sensor_module",
        "category": "sensor",
        "manufacturer": "Silicon Labs / LDRobot",
        "model": "CP210x / LD19 LiDAR",
        "voltage_v": 5.0,
        "current_ma": 300,
        "interfaces": ["uart_usb"],
        "capabilities": ["lidar_360_scan", "serial_uart"],
    },
    {
        "vid_pid_prefix": "2341:",
        "name": "Arduino Microcontroller Board",
        "profile_id": "generic_sensor_module",
        "category": "microcontroller",
        "manufacturer": "Arduino",
        "model": "Arduino USB Board",
        "voltage_v": 5.0,
        "current_ma": 200,
        "interfaces": ["usb_serial", "gpio", "pwm", "adc", "i2c", "spi"],
        "capabilities": ["gpio_pwm", "adc_analog", "serial_uart", "arduino_cli_flash"],
    },
    {
        "vid_pid_prefix": "303a:",
        "name": "ESP32 / ESP32-S3 Wireless MCU",
        "profile_id": "generic_sensor_module",
        "category": "microcontroller",
        "manufacturer": "Espressif",
        "model": "ESP32 Series",
        "voltage_v": 3.3,
        "current_ma": 250,
        "interfaces": ["usb_serial", "wifi", "ble", "gpio", "i2c", "spi"],
        "capabilities": ["wifi_ble", "gpio_pwm", "esptool_flash", "edge_sensor_node"],
    },
    {
        "vid_pid_prefix": "2e8a:",
        "name": "Raspberry Pi Pico (RP2040/RP2350)",
        "profile_id": "generic_sensor_module",
        "category": "microcontroller",
        "manufacturer": "Raspberry Pi",
        "model": "Pi Pico",
        "voltage_v": 3.3,
        "current_ma": 150,
        "interfaces": ["usb_serial", "gpio", "pio", "i2c", "spi"],
        "capabilities": ["pio_realtime", "uf2_flash", "gpio_pwm"],
    },
]

_USB_LINE_RE = re.compile(r"ID\s+([0-9a-fA-F]{4}:[0-9a-fA-F]{4})\s*(.*)")


def infer_host_board_profile(
    robot_name: str,
    model_text: str,
    ram_gb: Optional[float],
    ip_address: str,
) -> Dict[str, Any]:
    """Build a structured Lab Architect inventory entry for a registered fleet SBC/robot."""
    low = f"{robot_name} {model_text}".lower()
    ram_label = f"{round(ram_gb):.0f}GB" if (ram_gb is not None and ram_gb >= 1.0) else ""

    if "puppy" in low:
        return {
            "name": f"{robot_name} (Live Fleet Robot)",
            "profile_id": "puppypi_pro",
            "category": "robot",
            "manufacturer": "Hiwonder",
            "model": model_text or "PuppyPi Pro (Pi 5)",
            "quantity": 1,
            "status": "in_use",
            "location": f"LAN {ip_address}",
            "interfaces": ["wifi", "ros2_humble", "lidar_ld19", "usb_camera", "audio_wonderecho", "i2c_servos"],
            "voltage_v": 7.4,
            "current_ma": 2500,
            "capabilities": [
                "quadruped_locomotion",
                "lidar_360_mapping",
                "mobile_fpv_camera",
                "voice_assistant_ox",
                "autonomous_patrol_explore",
                "2dof_arm_servos",
            ],
            "notes": f"[fleet_sync:{ip_address}] Auto-synced live PuppyPi Pro quadruped robot.",
        }

    if "pi 5" in low or "pi5" in low or "rasp5" in low:
        return {
            "name": f"Raspberry Pi 5 {ram_label or '16GB'} ({ip_address})".replace("  ", " "),
            "profile_id": "raspberry_pi_5",
            "category": "compute",
            "manufacturer": "Raspberry Pi",
            "model": model_text or f"Raspberry Pi 5 {ram_label}".strip(),
            "quantity": 1,
            "status": "available",
            "location": f"LAN {ip_address}",
            "interfaces": ["ethernet_gbe", "wifi_5ghz", "bluetooth", "pcie_gen3", "dual_csi", "usb3", "gpio_40pin", "i2c", "spi"],
            "voltage_v": 5.1,
            "current_ma": 3000,
            "capabilities": [
                "edge_ai_compute",
                "local_llm_ollama_ready",
                "yolo_depth_offload",
                "dual_4k_camera_host",
                "usb_mcu_host",
                "docker_edge_server",
                "ros2_node_ready",
            ],
            "notes": f"[fleet_sync:{ip_address}] Auto-synced live Raspberry Pi 5 ({ram_label or 'RAM verified'}).",
        }

    if "pi 4" in low or "pi4" in low or "rasp4" in low:
        return {
            "name": f"Raspberry Pi 4 {ram_label or '8GB'} ({ip_address})".replace("  ", " "),
            "profile_id": "raspberry_pi_5",
            "category": "compute",
            "manufacturer": "Raspberry Pi",
            "model": model_text or f"Raspberry Pi 4 {ram_label}".strip(),
            "quantity": 1,
            "status": "available",
            "location": f"LAN {ip_address} (Wi-Fi)",
            "interfaces": ["wifi_5ghz", "ethernet_gbe", "bluetooth", "csi_camera", "usb3", "gpio_40pin", "i2c", "spi"],
            "voltage_v": 5.0,
            "current_ma": 2000,
            "capabilities": [
                "wireless_overwatch_cam_node",
                "sensor_telemetry_relay",
                "ros2_mqtt_bridge",
                "usb_mcu_host",
                "docker_edge_node",
            ],
            "notes": f"[fleet_sync:{ip_address}] Auto-synced live Raspberry Pi 4 ({ram_label or 'RAM verified'}).",
        }

    return {
        "name": f"{robot_name} ({ip_address})",
        "profile_id": "generic_sensor_module",
        "category": "compute",
        "manufacturer": "Generic",
        "model": model_text or robot_name,
        "quantity": 1,
        "status": "available",
        "location": f"LAN {ip_address}",
        "interfaces": ["network_ssh"],
        "voltage_v": 5.0,
        "current_ma": 1000,
        "capabilities": ["network_compute_node"],
        "notes": f"[fleet_sync:{ip_address}] Auto-synced fleet device.",
    }


def parse_lsusb_and_devs(
    lsusb_output: str,
    dev_listing: str,
    host_name: str,
    host_ip: str,
) -> List[Dict[str, Any]]:
    """Parse ``lsusb`` and ``/dev/*`` output into Lab Architect inventory items for attached peripherals.

    Args:
        lsusb_output: Raw stdout from ``lsusb``.
        dev_listing: Raw stdout from listing ``/dev/ttyACM* /dev/ttyUSB* /dev/video*``.
        host_name: Human-readable name of the host Pi/robot.
        host_ip: IPv4 address of the host Pi/robot.

    Returns:
        List of structured inventory item dictionaries for all recognized attached peripherals.
    """
    has_acm = "/dev/ttyACM" in dev_listing
    has_usb_serial = "/dev/ttyUSB" in dev_listing
    port_hint = "/dev/ttyACM0" if has_acm else "/dev/ttyUSB0" if has_usb_serial else "USB"

    found: List[Dict[str, Any]] = []
    seen_keys: set[str] = set()

    for line in (lsusb_output or "").splitlines():
        m = _USB_LINE_RE.search(line)
        if not m:
            continue
        vid_pid = m.group(1).lower()
        raw_desc = m.group(2).strip()
        for spec in USB_PERIPHERAL_CATALOG:
            if vid_pid.startswith(spec["vid_pid_prefix"]):
                dedup = f"{host_ip}:{spec['vid_pid_prefix']}"
                if dedup in seen_keys:
                    continue
                seen_keys.add(dedup)
                found.append(
                    {
                        "name": f"{spec['name']} (on {host_name})",
                        "profile_id": spec["profile_id"],
                        "category": spec["category"],
                        "manufacturer": spec["manufacturer"],
                        "model": spec["model"],
                        "quantity": 1,
                        "status": "available",
                        "location": f"{host_name} ({host_ip}) · {port_hint}",
                        "interfaces": list(spec["interfaces"]),
                        "voltage_v": spec["voltage_v"],
                        "current_ma": spec["current_ma"],
                        "capabilities": list(spec["capabilities"]),
                        "notes": f"[fleet_usb:{dedup}] Live USB peripheral ({vid_pid} {raw_desc}) attached to {host_name} ({host_ip}) via {port_hint}.",
                    }
                )
                break
    return found


def _ssh_probe_sync(ip: str, user: str, password: str, port: int = 22, timeout_sec: float = 6.0) -> Tuple[str, Optional[float], str, str]:
    """Run a single read-only SSH hardware & USB probe with up to 3x retry."""
    cmd = (
        'echo "MODEL:$(tr -d \\0 < /proc/device-tree/model 2>/dev/null || hostname)" && '
        'echo "RAM_MB:$(free -m | awk \'/^Mem:/{print $2}\')" && '
        'echo "===LSUSB===" && lsusb 2>/dev/null || true; '
        'echo "===DEVS===" && ls /dev/ttyACM* /dev/ttyUSB* /dev/video* 2>/dev/null || true'
    )
    last_err = ""
    for attempt in range(1, 4):
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
                        "UserKnownHostsFile=/dev/null",
                        "-o",
                        "ConnectTimeout=4",
                        "-p",
                        str(int(port)),
                        f"{user}@{ip}",
                        cmd,
                    ],
                )
            buf = b""
            sent_pw = False
            t0 = time.monotonic()
            while time.monotonic() - t0 < timeout_sec:
                r, _, _ = select.select([fd], [], [], 0.35)
                if fd in r:
                    try:
                        chunk = os.read(fd, 4096)
                        if not chunk:
                            break
                        buf += chunk
                        if not sent_pw and b"password:" in buf.lower():
                            os.write(fd, f"{password}\n".encode("utf-8"))
                            sent_pw = True
                    except OSError:
                        break
            try:
                os.waitpid(pid, os.WNOHANG)
            except Exception:
                pass
            try:
                os.close(fd)
            except Exception:
                pass

            text = buf.decode("utf-8", errors="ignore")
            if "===LSUSB===" in text:
                model_m = re.search(r"MODEL:([^\r\n]+)", text)
                ram_m = re.search(r"RAM_MB:(\d+)", text)
                model_str = model_m.group(1).strip() if model_m else ""
                ram_gb = round(int(ram_m.group(1)) / 1024.0, 1) if ram_m else None
                after_lsusb = text.split("===LSUSB===", 1)[1]
                lsusb_part, _, devs_part = after_lsusb.partition("===DEVS===")
                return model_str, ram_gb, lsusb_part, devs_part
            last_err = "Probe marker missing in SSH output."
        except Exception as exc:
            last_err = str(exc)
            sys.stderr.write(f"[fleet_sync] SSH probe attempt {attempt}/3 failed for {ip}: {exc}\n")
        if attempt < 3:
            time.sleep(0.35 * attempt)
    raise RuntimeError(f"SSH hardware probe failed on {ip}: {last_err}")


def _upsert_inventory_by_tag(ai_store: Any, item_payload: Dict[str, Any], tag: str) -> str:
    """Idempotently upsert an inventory item matched by ``tag`` in ``notes`` or exact ``name``."""
    existing = ai_store.list_inventory_items()
    low_name = str(item_payload["name"]).strip().lower()
    for row in existing:
        row_notes = str(row.get("notes") or "")
        row_name = str(row.get("name") or "").strip().lower()
        if (tag and tag in row_notes) or row_name == low_name:
            ai_store.update_inventory_item(
                row["id"],
                {
                    "name": item_payload["name"],
                    "model": item_payload["model"],
                    "location": item_payload["location"],
                    "interfaces": item_payload["interfaces"],
                    "capabilities": item_payload["capabilities"],
                    "notes": item_payload["notes"],
                },
            )
            return "updated"
    ai_store.create_inventory_item(item_payload)
    return "created"


async def sync_fleet_to_architect(
    robot_store: Any,
    ai_store: Any,
    probe_live: bool = True,
) -> Dict[str, Any]:
    """Sync all registered fleet robots/Pis and their live attached USB peripherals into Lab Architect.

    Args:
        robot_store: Active ``RobotStoreProtocol`` holding registered robots & encrypted SSH passwords.
        ai_store: Active ``RobotAiStoreProtocol`` holding Lab Architect ``owned_inventory``.
        probe_live: If ``True``, SSH-probe each host for live RAM, model, and attached USB devices.

    Returns:
        Summary dictionary with ``ok``, ``synced_hosts``, ``synced_peripherals``, and ``details``.
    """
    robots = robot_store.list_robots() if robot_store is not None else []
    synced_hosts = 0
    synced_peripherals = 0
    details: List[Dict[str, Any]] = []

    for rob in robots:
        rid = str(rob.get("id") or "")
        name = str(rob.get("name") or "Fleet Node")
        ip = str(rob.get("ip_address") or "").strip()
        model_str = str(rob.get("model") or "")
        ram_gb: Optional[float] = None
        peripherals: List[Dict[str, Any]] = []
        probe_status = "metadata_only"

        if probe_live and ip and rob.get("ssh_user"):
            pw = robot_store.get_robot_ssh_password(rid) if hasattr(robot_store, "get_robot_ssh_password") else None
            if pw:
                try:
                    p_model, p_ram, lsusb_out, devs_out = await asyncio.to_thread(
                        _ssh_probe_sync,
                        ip,
                        str(rob["ssh_user"]),
                        pw,
                        int(rob.get("ssh_port") or 22),
                    )
                    if p_model:
                        model_str = p_model
                    ram_gb = p_ram
                    peripherals = parse_lsusb_and_devs(lsusb_out, devs_out, host_name=name, host_ip=ip)
                    probe_status = "live_ssh_ok"
                except Exception as exc:
                    probe_status = f"ssh_skipped: {exc}"
                    sys.stderr.write(f"[fleet_sync] Live probe skipped for {name} ({ip}): {exc}\n")

        host_item = infer_host_board_profile(name, model_str, ram_gb, ip)
        _upsert_inventory_by_tag(ai_store, host_item, tag=f"[fleet_sync:{ip}]")
        synced_hosts += 1

        for periph in peripherals:
            m_tag = re.search(r"(\[fleet_usb:[^\]]+\])", str(periph.get("notes") or ""))
            _upsert_inventory_by_tag(ai_store, periph, tag=m_tag.group(1) if m_tag else "")
            synced_peripherals += 1

        details.append(
            {
                "robot_id": rid,
                "name": name,
                "ip": ip,
                "probe_status": probe_status,
                "model": model_str,
                "ram_gb": ram_gb,
                "peripherals_found": [p["name"] for p in peripherals],
            }
        )

    total_items = len(ai_store.list_inventory_items()) if ai_store is not None else 0
    return {
        "ok": True,
        "synced_hosts": synced_hosts,
        "synced_peripherals": synced_peripherals,
        "total_inventory_items": total_items,
        "details": details,
    }
