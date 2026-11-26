"""Universal Hardware Envelope, Device Profiles, micro:bit USB bridge, and 100% Local Camera Bridge."""

from src.devices.envelope import (
    DEVICE_PROFILES,
    build_starter_lab_inventory,
    get_device_profile,
    list_device_profiles,
)
from src.devices.local_camera_bridge import (
    extract_frames_from_media,
    fetch_lan_camera_frame,
    generate_pi_zero_gadget_setup_script,
    ingest_local_media_to_spatial_memory,
)
from src.devices.microbit_bridge import (
    MICROBIT_TEMPLATES,
    build_led_matrix_python,
    generate_microbit_template,
    probe_microbit_usb,
    send_microbit_serial_command,
)

__all__ = [
    "DEVICE_PROFILES",
    "MICROBIT_TEMPLATES",
    "build_led_matrix_python",
    "build_starter_lab_inventory",
    "extract_frames_from_media",
    "fetch_lan_camera_frame",
    "generate_microbit_template",
    "generate_pi_zero_gadget_setup_script",
    "get_device_profile",
    "ingest_local_media_to_spatial_memory",
    "list_device_profiles",
    "probe_microbit_usb",
    "send_microbit_serial_command",
]
