"""Universal Hardware Envelope: Loadable Device Profiles and Starter Lab Inventory Builder.

Defines 6 canonical hardware profiles (``puppypi_pi5_ros2``, ``raspberry_pi_5_node``,
``raspberry_pi_zero_2w``, ``microbit_v2_21``, ``local_camera_array``, and
``generic_sensor_module``) with exact electrical envelopes, physical millimeter dimensions,
hard safety limits, and downloadable firmware/setup templates.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional

from src.devices.microbit_bridge import MICROBIT_TEMPLATES

_PI_ZERO_TELEMETRY_TEMPLATE = """#!/usr/bin/env python3
\"\"\"Lightweight Raspberry Pi Zero 2 W local LAN telemetry & clip beacon.\"\"\"
import json, socket, time, urllib.request

HOST = "http://192.168.1.89:8000"
DEVICE_ID = "pizero-node-1"

while True:
    payload = {
        "device_id": DEVICE_ID,
        "hostname": socket.gethostname(),
        "ts": time.time(),
    }
    print(json.dumps(payload), flush=True)
    time.sleep(15)
"""

_PI5_ROS2_CHECK_TEMPLATE = """#!/usr/bin/env bash
# Quick read-only Raspberry Pi 5 ROS 2 Humble health & USB check
vcgencmd pmic_read_adc | grep -E "EXT5V_V|VDD_CORE"
vcgencmd get_throttled
vcgencmd measure_temp
lsusb -t
ls -la /dev/ldlidar /dev/wonderecho /dev/video0 2>/dev/null || true
"""

_LOCAL_CAM_SNAP_TEMPLATE = """#!/usr/bin/env bash
# Push a single local LAN camera snapshot directly into Eigenia TwinScan Spatial Memory (Zero Cloud)
TWINSCAN_HOST="${1:-192.168.1.89:8000}"
CAM_URL="${2:-http://192.168.1.120/snap.jpg}"
CAM_NAME="${3:-Garage LAN Cam}"
curl -sS -X POST "http://${TWINSCAN_HOST}/api/devices/cameras/ingest-media" \\
  -H "Content-Type: application/json" \\
  -d "{\\"stream_url\\":\\"${CAM_URL}\\",\\"camera_name\\":\\"${CAM_NAME}\\"}"
"""

DEVICE_PROFILES: Dict[str, Dict[str, Any]] = {
    "puppypi_pi5_ros2": {
        "profile_id": "puppypi_pi5_ros2",
        "display_name": "Hiwonder PuppyPi Pro (Pi 5 + ROS 2 Humble)",
        "category": "compute",
        "tagline": "12-DOF quadruped robot with Raspberry Pi 5, STM32 RRC HAT, UVC FPV camera, WonderEcho Pro, and LD19 LiDAR mount.",
        "transports": ["wifi_sta", "rosbridge_ws", "http_mjpeg", "ssh_pty", "uart_rrc"],
        "voltage_rail_v": 7.4,
        "max_gpio_v": 3.3,
        "power_budget_ma": 5000,
        "dimensions_mm": [226, 149, 190],
        "color_hex": "#E05A10",
        "interfaces": [
            "USB 2.0 (x2)",
            "USB 3.0 (x2)",
            "UART0 /dev/rrc (STM32)",
            "I2C-1",
            "Wi-Fi 5 5GHz",
            "Gigabit Ethernet",
            "40-pin GPIO (3.3V)",
        ],
        "capabilities": [
            "ROS 2 Humble quadruped gait & pose control",
            "Live 640x480 UVC FPV streaming (:8080)",
            "WonderEcho Pro USB voice I/O (ALSA Card 2)",
            "LD19 360-deg ToF LiDAR (/scan @ 230400 baud)",
            "Autonomous patrol, sentry guard & 3D room fusion",
        ],
        "hard_limits": [
            "Pi 5 GPIO logic is strictly 3.3V (5V input damages RP1 silicon)",
            "Combined USB-A draw capped at 1600 mA (with usb_max_current_enable=1) or 600 mA default",
            "2S LiPo battery sag below 6.8V risks servo brownout; keep >= 7.2V for walking",
            "LD19 requires a full 4-wire data USB cable (charge-only cables spin motor with zero enumeration)",
        ],
        "firmware_templates": [
            {
                "id": "pi5_ros2_health",
                "name": "Pi 5 PMIC & ROS 2 Health Check",
                "description": "Read-only bash probe verifying DA9091 PMIC voltage, USB tree, and serial symlinks.",
                "language": "bash",
                "code": _PI5_ROS2_CHECK_TEMPLATE,
            }
        ],
    },
    "raspberry_pi_5_node": {
        "profile_id": "raspberry_pi_5_node",
        "display_name": "Raspberry Pi 5 Model B (8 GB Compute Node)",
        "category": "compute",
        "tagline": "Quad-core Cortex-A76 2.4 GHz edge compute hub with RP1 southbridge, PCIe 2.0 x1, and DA9091 PMIC.",
        "transports": ["wifi_sta", "ethernet", "ssh_pty", "http_rest", "uart", "i2c", "spi"],
        "voltage_rail_v": 5.0,
        "max_gpio_v": 3.3,
        "power_budget_ma": 5000,
        "dimensions_mm": [85, 56, 17],
        "color_hex": "#38BDF8",
        "interfaces": [
            "USB-C 5V/5A PD",
            "USB 3.0 (x2)",
            "USB 2.0 (x2)",
            "PCIe 2.0 x1 FFC",
            "MIPI CSI/DSI (x2)",
            "Micro-HDMI (x2)",
            "40-pin GPIO (3.3V)",
            "Gigabit Ethernet",
        ],
        "capabilities": [
            "Local ONNX CV inference (YuNet, SFace, YOLO11n)",
            "Multi-sensor USB/I2C/UART aggregation",
            "Docker & ROS 2 Humble container host",
            "Real-time DA9091 per-rail PMIC telemetry",
        ],
        "hard_limits": [
            "USB-A ports share a 1600 mA rail only when PSU_MAX_CURRENT=5000 / 5V 5A PD is present (else 600 mA)",
            "GPIO pins are 3.3V-only, max 16 mA per pin / 50 mA total across header",
            "Active cooling recommended above 70C sustained load (thermal throttle at 80-85C)",
        ],
        "firmware_templates": [
            {
                "id": "pi5_pmic_probe",
                "name": "Pi 5 PMIC & Thermal Probe",
                "description": "Quick shell snippet to inspect Pi 5 voltages, frequency, and throttling.",
                "language": "bash",
                "code": _PI5_ROS2_CHECK_TEMPLATE,
            }
        ],
    },
    "raspberry_pi_zero_2w": {
        "profile_id": "raspberry_pi_zero_2w",
        "display_name": "Raspberry Pi Zero 2 W (Edge / USB-OTG Bridge)",
        "category": "compute",
        "tagline": "Ultra-compact quad-core ARM64 Linux SBC with native USB-OTG gadget mode (g_mass_storage / g_ether).",
        "transports": ["wifi_sta", "usb_otg_gadget", "ssh_pty", "http_rest", "ble"],
        "voltage_rail_v": 5.0,
        "max_gpio_v": 3.3,
        "power_budget_ma": 1200,
        "dimensions_mm": [65, 30, 5],
        "color_hex": "#10B981",
        "interfaces": [
            "Micro-USB OTG Data/Gadget",
            "Micro-USB 5V Power",
            "Mini-HDMI",
            "CSI-2 Camera",
            "40-pin GPIO (3.3V)",
            "Wi-Fi 2.4 GHz + BLE 4.2",
        ],
        "capabilities": [
            "USB Mass Storage Gadget (g_mass_storage) for cloud-free Blink Sync Module 2 clip harvesting",
            "Low-power Wi-Fi sensor & serial-to-HTTP bridge",
            "Portable CSI camera or I2C environmental node",
        ],
        "hard_limits": [
            "512 MB RAM ceiling — offload heavy YOLO/Whisper/Depth models to Docker host or Pi 5",
            "2.4 GHz Wi-Fi only (no 5 GHz band)",
            "Never mount g_mass_storage backing image read-write on host while gadget is active (use read-only loop mount snapshots)",
            "GPIO strictly 3.3V logic",
        ],
        "firmware_templates": [
            {
                "id": "pizero_beacon",
                "name": "Pi Zero 2 W LAN Telemetry Beacon",
                "description": "Minimal stdlib Python heartbeat script for Pi Zero 2 W edge nodes.",
                "language": "python",
                "code": _PI_ZERO_TELEMETRY_TEMPLATE,
            }
        ],
    },
    "microbit_v2_21": {
        "profile_id": "microbit_v2_21",
        "display_name": "BBC micro:bit v2.21 (nRF52833 MCU)",
        "category": "microcontroller",
        "tagline": "Pocket 3.3V ARM Cortex-M4F microcontroller with 5x5 red LED matrix, MEMS mic/speaker, IMU, compass, and BLE 5.0.",
        "transports": ["usb_cdc_serial", "usb_daplink_mass_storage", "ble_radio", "i2c_3v3"],
        "voltage_rail_v": 3.3,
        "max_gpio_v": 3.3,
        "power_budget_ma": 200,
        "dimensions_mm": [52, 42, 12],
        "color_hex": "#F59E0B",
        "interfaces": [
            "Micro-USB DAPLink + CDC Serial (115200 8N1)",
            "5x5 Red LED Matrix",
            "Buttons A/B + Capacitive Logo",
            "MEMS Microphone + Onboard Speaker",
            "3-Axis Accelerometer & Magnetometer (LSM303AGR)",
            "2.4 GHz Radio & BLE 5.0",
            "Edge Connector (3.3V GPIO / I2C / SPI / PWM)",
        ],
        "capabilities": [
            "Tactile room status badge & alert chime display",
            "Low-power tilt/shake/compass/sound-level telemetry over USB serial or 2.4 GHz radio",
            "Drag-and-drop .hex / MicroPython REPL over USB CDC",
        ],
        "hard_limits": [
            "STRICT 3.3V GPIO maximum — NEVER connect directly to 5V rails or 5V UART without a logic-level shifter",
            "Max ~200 mA regulated 3.3V output across edge connector — drive servos/motors from an external 5V-6V PSU with shared GND",
            "No Wi-Fi or camera DMA; bridge to Docker/Pi over USB CDC serial or BLE/2.4GHz gateway",
        ],
        "firmware_templates": deepcopy(MICROBIT_TEMPLATES),
    },
    "local_camera_array": {
        "profile_id": "local_camera_array",
        "display_name": "100% Local LAN / RTSP / Sync-USB Camera Array",
        "category": "camera",
        "tagline": "Cloud-free local IP cameras (RTSP/MJPEG/HTTP) and Pi Zero USB clip harvesters feeding offline Spatial Memory.",
        "transports": ["rtsp_lan", "http_snapshot", "usb_uvc", "pizero_clip_push"],
        "voltage_rail_v": 5.0,
        "max_gpio_v": 3.3,
        "power_budget_ma": 500,
        "dimensions_mm": [70, 70, 42],
        "color_hex": "#8B5CF6",
        "interfaces": [
            "LAN RTSP / MJPEG / HTTP JPEG",
            "Local .mp4 / .jpg Clip Ingest API",
            "USB Mass Storage Clip Bridge (Blink Sync Module 2 via Pi Zero)",
        ],
        "capabilities": [
            "Zero-cloud local frame extraction & sharpness selection",
            "Offline YOLO11n + YuNet/SFace face & animal recognition into Spatial Memory",
            "Supports RTSP/ONVIF IP cams, UVC cams, and local USB clip uploads",
        ],
        "hard_limits": [
            "Blink Outdoor/Mini cameras do NOT expose native RTSP streams — use Pi Zero 2 W g_mass_storage on Sync Module 2 for 100% local cloud-free clip ingest",
            "Keep camera streams on local LAN subnet (192.168.1.0/24) to avoid cloud latency and subscription dependencies",
            "Decode H.264/MP4 clips on Docker host (OpenCV) rather than low-RAM microcontrollers",
        ],
        "firmware_templates": [
            {
                "id": "local_cam_push",
                "name": "Local LAN Snapshot Ingest Hook",
                "description": "Curl snippet to push any local HTTP camera snapshot into Spatial Memory.",
                "language": "bash",
                "code": _LOCAL_CAM_SNAP_TEMPLATE,
            }
        ],
    },
    "generic_sensor_module": {
        "profile_id": "generic_sensor_module",
        "display_name": "Modular Sensor / Actuator Breakout (I2C / UART / USB)",
        "category": "sensor",
        "tagline": "Pluggable LiDAR, ultrasonic, thermal, IMU, servo, or voice peripheral attached to any host node.",
        "transports": ["uart_serial", "i2c", "spi", "usb_serial", "pwm"],
        "voltage_rail_v": 5.0,
        "max_gpio_v": 3.3,
        "power_budget_ma": 350,
        "dimensions_mm": [45, 38, 25],
        "color_hex": "#14B8A6",
        "interfaces": ["UART (3.3V TTL)", "I2C (3.3V)", "USB-Serial (CP2102/CH340)", "5V Power + GND"],
        "capabilities": [
            "Drop-in peripheral expansion for PuppyPi, Pi 5, Pi Zero 2 W, or micro:bit",
            "Plug-and-play udev symlink binding on Linux hosts",
        ],
        "hard_limits": [
            "Verify logic level compatibility (3.3V vs 5V) before wiring UART/I2C directly to Pi or micro:bit GPIO",
            "Account for stall/spin-up surge current (e.g. LD19 ~300 mA, micro servos 400-800 mA each)",
            "Always tie common GND across separate power supplies",
        ],
        "firmware_templates": [],
    },
}


def list_device_profiles() -> List[Dict[str, Any]]:
    """Return all 6 loadable universal hardware device profiles in canonical order.

    Returns:
        List of deep-copied ``DeviceProfile`` dictionaries.
    """
    return [deepcopy(profile) for profile in DEVICE_PROFILES.values()]


def get_device_profile(profile_id: str) -> Optional[Dict[str, Any]]:
    """Look up a single universal hardware profile by ``profile_id``.

    Args:
        profile_id: Canonical profile identifier (e.g. ``"microbit_v2_21"``).

    Returns:
        Deep-copied ``DeviceProfile`` dictionary, or ``None`` if unknown.
    """
    prof = DEVICE_PROFILES.get(str(profile_id or "").strip())
    return deepcopy(prof) if prof is not None else None


def build_starter_lab_inventory() -> List[Dict[str, Any]]:
    """Build the curated default Starter Lab Inventory for one-click idempotent seeding.

    Reflects the user's real robotics & edge lab hardware (PuppyPi Pro Pi 5, LD19 LiDAR,
    WonderEcho Pro, icSpring camera, Pi Zero 2 W, BBC micro:bit v2.21, local Blink Sync
    clip harvester setup, and core bench accessories).

    Returns:
        List of inventory creation dictionaries ready for ``ai_store.create_inventory_item``.
    """
    return [
        {
            "name": "Hiwonder PuppyPi Pro (Raspberry Pi 5 8GB)",
            "profile_id": "puppypi_pi5_ros2",
            "category": "compute",
            "manufacturer": "Hiwonder / Raspberry Pi",
            "model": "PuppyPi Pro + Pi 5 Rev 1.1",
            "quantity": 1,
            "status": "deployed",
            "location": "Lab Floor (192.168.1.119)",
            "interfaces": ["Wi-Fi 5", "USB 3.0 x2", "USB 2.0 x2", "UART0 /dev/rrc", "40-pin GPIO"],
            "voltage_v": 7.4,
            "current_ma": 2500,
            "capabilities": ["ROS 2 Humble", "Quadruped Locomotion", "FPV Camera", "AI Vision"],
            "notes": "Primary quadruped platform running ROS 2 Humble with DA9091 PMIC (1600 mA USB unlocked).",
            "est_cost_usd": 499.0,
        },
        {
            "name": "LDROBOT LD19 360-deg ToF LiDAR",
            "profile_id": "generic_sensor_module",
            "category": "sensor",
            "manufacturer": "LDROBOT",
            "model": "LD19 + CP2102 USB-UART",
            "quantity": 1,
            "status": "needs_part",
            "location": "Mounted on PuppyPi Top Deck",
            "interfaces": ["USB-Serial (230400 baud)", "4-pin JST-ZH UART"],
            "voltage_v": 5.0,
            "current_ma": 250,
            "capabilities": ["360-deg 2D Laser Scan", "12m Range", "10 Hz Scan"],
            "notes": "Motor spins on 5V; needs verified 4-wire data USB cable or replacement CP2102 converter PCB.",
            "est_cost_usd": 89.0,
        },
        {
            "name": "Hiwonder WonderEcho Pro Voice Module",
            "profile_id": "generic_sensor_module",
            "category": "sensor",
            "manufacturer": "Hiwonder",
            "model": "WonderEcho Pro (1a86:8091)",
            "quantity": 1,
            "status": "deployed",
            "location": "PuppyPi USB 2.0 Port 1-2",
            "interfaces": ["USB 2.0 Hub", "CH340 Serial (/dev/wonderecho)", "USB PnP Audio (ALSA Card 2)"],
            "voltage_v": 5.0,
            "current_ma": 302,
            "capabilities": ["Wake Word Mic", "Piper TTS Speaker", "Offline Voice Commands"],
            "notes": "Rock-solid with 0 flaps on Pi 5 black USB 2.0 Port 1-2.",
            "est_cost_usd": 39.0,
        },
        {
            "name": "icSpring 640x480 UVC FPV Camera",
            "profile_id": "local_camera_array",
            "category": "camera",
            "manufacturer": "icSpring",
            "model": "UVC 32e6:9005",
            "quantity": 1,
            "status": "deployed",
            "location": "PuppyPi USB 2.0 Port 1-1",
            "interfaces": ["USB 2.0 UVC (/dev/video0)"],
            "voltage_v": 5.0,
            "current_ma": 100,
            "capabilities": ["640x480 30fps YUYV", "ROS 2 /image_raw", "3D Room Fusion"],
            "notes": "Primary front FPV camera for AI Vision Studio and 3D room wall capture.",
            "est_cost_usd": 24.0,
        },
        {
            "name": "Raspberry Pi Zero 2 W",
            "profile_id": "raspberry_pi_zero_2w",
            "category": "compute",
            "manufacturer": "Raspberry Pi",
            "model": "Pi Zero 2 W (512 MB)",
            "quantity": 1,
            "status": "available",
            "location": "Workbench Drawer A",
            "interfaces": ["Micro-USB OTG", "Wi-Fi 2.4 GHz", "BLE 4.2", "CSI-2", "40-pin GPIO"],
            "voltage_v": 5.0,
            "current_ma": 350,
            "capabilities": ["USB g_mass_storage Gadget", "Blink Sync Clip Harvester", "Edge Sensor Bridge"],
            "notes": "Ideal zero-cloud USB gadget bridge for Blink Sync Module 2 local clip forwarding.",
            "est_cost_usd": 15.0,
        },
        {
            "name": "BBC micro:bit v2.21",
            "profile_id": "microbit_v2_21",
            "category": "microcontroller",
            "manufacturer": "Micro:bit Educational Foundation",
            "model": "v2.21 (nRF52833)",
            "quantity": 1,
            "status": "available",
            "location": "Workbench Drawer A",
            "interfaces": ["Micro-USB DAPLink/CDC", "5x5 LED Matrix", "BLE 5.0", "2.4 GHz Radio", "3.3V Edge GPIO"],
            "voltage_v": 3.3,
            "current_ma": 120,
            "capabilities": ["5x5 LED Alert Display", "IMU/Compass/Temp", "MEMS Mic & Buzzer", "Radio Beacon"],
            "notes": "Strict 3.3V logic; great as a tactile status badge, door/vibration beacon, or handheld PuppyPi remote.",
            "est_cost_usd": 20.0,
        },
        {
            "name": "Blink Outdoor 4 + Sync Module 2 (Local USB)",
            "profile_id": "local_camera_array",
            "category": "camera",
            "manufacturer": "Blink",
            "model": "Sync Module 2 + Outdoor 4",
            "quantity": 1,
            "status": "available",
            "location": "Entryway / Local Sync Hub",
            "interfaces": ["USB-A Local Clip Storage (Sync Module 2)", "Wi-Fi"],
            "voltage_v": 5.0,
            "current_ma": 500,
            "capabilities": ["Motion-Triggered Local .mp4 Clips", "Battery-Powered Outdoor/Indoor Coverage"],
            "notes": "No native RTSP; pair Sync Module 2 USB port with Pi Zero 2 W g_mass_storage for 100% cloud-free ingest.",
            "est_cost_usd": 99.0,
        },
        {
            "name": "ShanWan 2.4GHz Wireless Gamepad",
            "profile_id": "generic_sensor_module",
            "category": "accessory",
            "manufacturer": "ShanWan",
            "model": "ZD-V+ Wireless (2563:0575)",
            "quantity": 1,
            "status": "deployed",
            "location": "PuppyPi USB 3.0 Port 3-2",
            "interfaces": ["USB HID (/dev/input/js0)"],
            "voltage_v": 5.0,
            "current_ma": 350,
            "capabilities": ["Manual Teleop", "Emergency Stop Override"],
            "notes": "Dongle draws 350 mA declared USB budget on Port 3-2.",
            "est_cost_usd": 25.0,
        },
        {
            "name": "4-Channel Bidirectional 3.3V/5V Logic Level Shifter",
            "profile_id": "generic_sensor_module",
            "category": "accessory",
            "manufacturer": "Generic",
            "model": "BSS138 4-Ch I2C/UART Shifter",
            "quantity": 2,
            "status": "wishlist",
            "location": "Wishlist",
            "interfaces": ["3.3V LV", "5V HV", "I2C/UART"],
            "voltage_v": 3.3,
            "current_ma": 10,
            "capabilities": ["Safe 3.3V <-> 5V Signal Shifting"],
            "notes": "Recommended whenever interfacing 5V sensors/servos with micro:bit v2 or Pi 5 GPIO.",
            "est_cost_usd": 4.0,
        },
        {
            "name": "USB-C to USB-A 4-Wire High-Speed Data Cable (Short 30cm)",
            "profile_id": "generic_sensor_module",
            "category": "accessory",
            "manufacturer": "Anker / Cable Matters",
            "model": "USB 3.0 30cm Data Cable",
            "quantity": 1,
            "status": "wishlist",
            "location": "Wishlist",
            "interfaces": ["USB-A", "USB-C (Full D+/D- Data + 5V)"],
            "voltage_v": 5.0,
            "current_ma": 3000,
            "capabilities": ["Reliable CP2102/CH340 Serial Data Link"],
            "notes": "Replaces suspected charge-only cable on LD19 LiDAR USB-UART converter board.",
            "est_cost_usd": 8.0,
        },
    ]
