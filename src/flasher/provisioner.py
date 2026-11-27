"""Poka-Yoke Removable-Disk Safety Guards & Headless Pi Provisioning Generator.

Ensures internal OS drives can NEVER be flashed and generates clean, injection-safe
headless Raspberry Pi boot provisioning scripts (SSH + Wi-Fi + TwinScan role).
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

_HOSTNAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9-]{0,30}[a-zA-Z0-9]?$")
_USERNAME_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,30}$")
_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
_SAFE_URL_RE = re.compile(r"^https?://[a-zA-Z0-9._:/-]{3,128}$")

FORBIDDEN_SYSTEM_DEVICES = frozenset(
    {
        "/dev/disk0",
        "/dev/disk1",
        "/dev/rdisk0",
        "/dev/rdisk1",
        "/dev/sda",
        "/dev/nvme0n1",
        "disk0",
        "disk1",
        "physicaldrive0",
        "c:",
    }
)


def validate_removable_target(
    device_info: Dict[str, Any],
    confirmation_token: str,
) -> Dict[str, Any]:
    """Strictly validate that a flash target is removable USB media and explicitly confirmed.

    Args:
        device_info: Device dictionary reported by the host flash bridge.
        confirmation_token: Exact device identifier typed by the operator to confirm flashing.

    Returns:
        Normalized safe device descriptor.

    Raises:
        ValueError: If the target is an internal OS drive, read-only, non-removable, or unconfirmed.
    """
    dev_id = str(device_info.get("device_id") or "").strip()
    dev_path = str(device_info.get("device_path") or dev_id).strip()
    if not dev_id or not dev_path:
        raise ValueError("Missing target device_id or device_path.")

    low_id = dev_id.lower()
    low_path = dev_path.lower()
    if low_id in FORBIDDEN_SYSTEM_DEVICES or low_path in FORBIDDEN_SYSTEM_DEVICES:
        raise ValueError(f"SAFETY BLOCK: '{dev_path}' is a protected internal system disk and cannot be flashed.")

    if device_info.get("is_internal") is True:
        raise ValueError(f"SAFETY BLOCK: '{dev_path}' is flagged as internal storage.")

    if device_info.get("is_removable") is not True:
        raise ValueError(f"SAFETY BLOCK: '{dev_path}' is not verified as removable USB/SD media.")

    if device_info.get("read_only") is True:
        raise ValueError(f"Target '{dev_path}' is write-protected / read-only.")

    if str(confirmation_token or "").strip().lower() != low_id:
        raise ValueError(
            f"Confirmation mismatch: type exact device ID '{dev_id}' to confirm flashing removable media."
        )

    return {
        "device_id": dev_id,
        "device_path": dev_path,
        "kind": str(device_info.get("kind") or "sd_card"),
        "size_gb": float(device_info.get("size_gb") or 0.0),
        "label": str(device_info.get("label") or dev_id),
    }


def _sanitize_shell_single_quoted(value: str) -> str:
    """Reject control characters and escape single quotes safely for POSIX sh."""
    if any(ord(ch) < 32 for ch in value):
        raise ValueError("Provisioning fields must not contain newline or control characters.")
    return "'" + value.replace("'", "'\"'\"'") + "'"


def build_pi_headless_bundle(
    hostname: str = "eigenia-pi5",
    username: str = "pi",
    ssh_pubkey: Optional[str] = None,
    wifi_ssid: Optional[str] = None,
    wifi_password: Optional[str] = None,
    country_code: str = "US",
    twinscan_url: Optional[str] = None,
    role: str = "minimal_ssh",
    redact_secrets: bool = False,
) -> Dict[str, Any]:
    """Generate validated headless Raspberry Pi first-boot provisioning metadata & script.

    Args:
        hostname: RFC-1123 hostname (e.g. ``eigenia-pi5``).
        username: Linux login user (default ``pi``).
        ssh_pubkey: Optional SSH public key line (``ssh-ed25519 ...``).
        wifi_ssid: Optional Wi-Fi network SSID.
        wifi_password: Optional Wi-Fi WPA2/WPA3 passphrase.
        country_code: 2-letter ISO country code (default ``US``).
        twinscan_url: Optional TwinScan backend URL for auto-enrolling camera/sensor nodes.
        role: One of ``minimal_ssh``, ``overwatch_cam_node``, ``ros2_sensor_node``.
        redact_secrets: If ``True``, mask ``wifi_password`` for safe UI preview.

    Returns:
        Dictionary with ``hostname``, ``username``, ``role``, ``firstrun_sh``, and ``rpi_imager_cli_flags``.

    Raises:
        ValueError: If hostname, username, country code, or URL fails validation.
    """
    clean_host = (hostname or "eigenia-pi5").strip()
    if not _HOSTNAME_RE.match(clean_host):
        raise ValueError(f"Invalid hostname {clean_host!r}: use letters, digits, and hyphens only.")

    clean_user = (username or "pi").strip().lower()
    if not _USERNAME_RE.match(clean_user):
        raise ValueError(f"Invalid username {clean_user!r}: use lowercase letters, digits, '_' or '-'.")

    clean_cc = (country_code or "US").strip().upper()
    if not _COUNTRY_RE.match(clean_cc):
        raise ValueError(f"Invalid country_code {clean_cc!r}: expected 2 uppercase letters (e.g. US).")

    clean_role = (role or "minimal_ssh").strip().lower()
    if clean_role not in ("minimal_ssh", "overwatch_cam_node", "ros2_sensor_node"):
        raise ValueError(f"Unsupported role {clean_role!r}.")

    clean_url = (twinscan_url or "").strip()
    if clean_url and not _SAFE_URL_RE.match(clean_url):
        raise ValueError("Invalid twinscan_url: expected http(s)://host:port.")

    lines = [
        "#!/bin/sh",
        "# Generated by Eigenia // TwinScan Studio Universal Device Flasher",
        "set -e",
        f"hostnamectl set-hostname {_sanitize_shell_single_quoted(clean_host)} || true",
        "systemctl enable ssh || true",
        "systemctl start ssh || true",
    ]

    if ssh_pubkey and ssh_pubkey.strip():
        pub = ssh_pubkey.strip()
        if "\n" in pub or "\r" in pub:
            raise ValueError("ssh_pubkey must be a single line.")
        lines.extend(
            [
                f"mkdir -p /home/{clean_user}/.ssh",
                f"echo {_sanitize_shell_single_quoted(pub)} >> /home/{clean_user}/.ssh/authorized_keys",
                f"chmod 700 /home/{clean_user}/.ssh && chmod 600 /home/{clean_user}/.ssh/authorized_keys",
                f"chown -R {clean_user}:{clean_user} /home/{clean_user}/.ssh",
            ]
        )

    if wifi_ssid and wifi_ssid.strip():
        ssid_q = _sanitize_shell_single_quoted(wifi_ssid.strip())
        pw_raw = "********" if (redact_secrets and wifi_password) else (wifi_password or "")
        pw_q = _sanitize_shell_single_quoted(pw_raw)
        lines.extend(
            [
                f"raspi-config nonint do_wifi_country {clean_cc} || true",
                f"nmcli device wifi connect {ssid_q} password {pw_q} || true",
            ]
        )

    if clean_role == "overwatch_cam_node" and clean_url:
        lines.append(f"# TwinScan Overwatch Camera Node target: {clean_url}/api/overwatch/ingest")
        lines.append(f"echo TWINSCAN_API_URL={_sanitize_shell_single_quoted(clean_url)} > /etc/eigenia-node.env")
    elif clean_role == "ros2_sensor_node" and clean_url:
        lines.append(f"# TwinScan ROS 2 Sensor Node target: {clean_url}")
        lines.append(f"echo TWINSCAN_API_URL={_sanitize_shell_single_quoted(clean_url)} > /etc/eigenia-node.env")

    return {
        "ok": True,
        "hostname": clean_host,
        "username": clean_user,
        "country_code": clean_cc,
        "role": clean_role,
        "ssh_enabled": True,
        "wifi_configured": bool(wifi_ssid and wifi_ssid.strip()),
        "firstrun_sh": "\n".join(lines) + "\n",
    }
