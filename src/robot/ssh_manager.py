"""Async stdlib PTY SSH runner, PuppyPi Hardware BOM + Software SBOM collector, and Remote Configurator.

Uses ONLY Python 3.12 standard library (``asyncio``, ``pty``, ``os``, ``select``,
``subprocess``, ``base64``, ``json``) with the system ``ssh`` binary. Zero shell
interpolation of user-supplied values: every remote operation sends a fixed base64
Python payload over SSH and validates all parameters strictly before execution.
"""

from __future__ import annotations

import asyncio
import base64
import fcntl
import json
import os
import pty
import re
import select
import shlex
import subprocess
import sys
import termios
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

SSH_BEGIN_MARKER = "===EIGENIA_SSH_BEGIN==="
SSH_END_MARKER = "===EIGENIA_SSH_END==="

SAFE_USER_RE = re.compile(r"^[a-zA-Z0-9_.\-]{1,32}$")
SAFE_HOST_RE = re.compile(r"^[a-zA-Z0-9.\-:]{1,128}$")
COUNTRY_CODE_RE = re.compile(r"^[A-Z]{2}$")

VALID_PASSWORD_USERS = frozenset({"pi", "root"})
VALID_ASR_LANGUAGES = frozenset({"English", "Chinese"})
VALID_POWER_ACTIONS = frozenset({"restart_ros", "reboot", "shutdown"})
VALID_RMW_IMPLEMENTATIONS = frozenset({"rmw_cyclonedds_cpp", "rmw_fastrtps_cpp"})


class SSHCommandError(RuntimeError):
    """Raised when an SSH execution fails after retries or due to authentication error."""


class SSHAuthError(SSHCommandError):
    """Raised when the remote SSH host rejects the username or password."""


def validate_ssh_target(ip: str, user: str) -> Tuple[str, str]:
    """Validate SSH host and username against strict allow-lists.

    Args:
        ip: Remote IPv4/hostname string.
        user: Remote SSH username.

    Returns:
        Normalized ``(ip, user)`` tuple.

    Raises:
        ValueError: When host or username contains invalid characters.
    """
    clean_ip = str(ip or "").strip()
    clean_user = str(user or "").strip()
    if not clean_ip or not SAFE_HOST_RE.match(clean_ip):
        raise ValueError(f"Invalid SSH target host: {ip!r}")
    if not clean_user or not SAFE_USER_RE.match(clean_user):
        raise ValueError(f"Invalid SSH username: {user!r}")
    return clean_ip, clean_user


def validate_wifi_params(
    mode: int,
    ssid: str,
    wifi_password: str,
    country_code: str = "US",
) -> Dict[str, Any]:
    """Validate Wi-Fi configuration inputs before remote generation.

    Args:
        mode: PuppyPi Wi-Fi mode (``1`` = AP, ``2`` = STA).
        ssid: Wireless network SSID.
        wifi_password: WPA/WPA2 passphrase (may be empty for open networks).
        country_code: ISO 3166-1 alpha-2 regulatory country code (e.g. ``"US"``).

    Returns:
        Validated parameter dictionary.

    Raises:
        ValueError: On invalid mode, country code, SSID, or control characters.
    """
    mode_int = int(mode)
    if mode_int not in (1, 2):
        raise ValueError(f"Wi-Fi mode must be 1 (AP) or 2 (STA), got {mode!r}")
    clean_ssid = str(ssid or "").strip()
    if not clean_ssid or len(clean_ssid) > 64 or any(ord(c) < 32 for c in clean_ssid):
        raise ValueError("SSID must be 1-64 printable characters with no control characters")
    clean_pw = str(wifi_password or "")
    if len(clean_pw) > 128 or any(ord(c) < 32 for c in clean_pw):
        raise ValueError("Wi-Fi password must be <=128 printable characters with no control characters")
    clean_cc = str(country_code or "US").strip().upper()
    if not COUNTRY_CODE_RE.match(clean_cc):
        raise ValueError(f"country_code must be a 2-letter ISO code like 'US', got {country_code!r}")
    return {
        "mode": mode_int,
        "ssid": clean_ssid,
        "wifi_password": clean_pw,
        "country_code": clean_cc,
    }


def render_wifi_conf_py(
    mode: int,
    ssid: str,
    wifi_password: str,
    ap_ssid: str = "HW-PUPPYPI",
    ap_password: str = "hiwonder",
) -> str:
    """Render a syntax-safe ``wifi_conf.py`` using straight ASCII double quotes.

    Args:
        mode: ``1`` (AP) or ``2`` (STA).
        ssid: Target STA SSID (or AP SSID if mode == 1).
        wifi_password: Target password string.
        ap_ssid: Fallback AP SSID.
        ap_password: Fallback AP password.

    Returns:
        Valid Python source code string for ``wifi_conf.py``.
    """
    validated = validate_wifi_params(mode=mode, ssid=ssid, wifi_password=wifi_password)
    if validated["mode"] == 1:
        ap_ssid = validated["ssid"]
        ap_password = validated["wifi_password"] or ap_password
    lines = [
        "# Managed by Eigenia TwinScan Remote Configurator",
        f"WIFI_MODE = {validated['mode']}",
        f"WIFI_AP_SSID = {json.dumps(ap_ssid)}",
        f"WIFI_AP_PASSWORD = {json.dumps(ap_password)}",
        f"WIFI_STA_SSID = {json.dumps(validated['ssid'])}",
        f"WIFI_STA_PASSWORD = {json.dumps(validated['wifi_password'])}",
        "",
    ]
    return "\n".join(lines)


def validate_password_change_params(target_user: str, new_password: str) -> Tuple[str, str]:
    """Validate target account and new password for ``chpasswd``.

    Args:
        target_user: Must be ``"pi"`` or ``"root"``.
        new_password: New password string (no newlines, colons, or null bytes).

    Returns:
        Validated ``(target_user, new_password)`` tuple.

    Raises:
        ValueError: When validation fails.
    """
    user = str(target_user or "").strip()
    if user not in VALID_PASSWORD_USERS:
        raise ValueError(f"target_user must be one of {sorted(VALID_PASSWORD_USERS)}, got {target_user!r}")
    pw = str(new_password or "")
    if len(pw) < 4 or len(pw) > 128:
        raise ValueError("new_password must be between 4 and 128 characters")
    if any(ch in pw for ch in ("\n", "\r", ":", "\x00")):
        raise ValueError("new_password must not contain newlines, colons, or null bytes")
    return user, pw


def validate_mechanics_params(
    with_arm: Optional[int] = None,
    x_shift: Optional[float] = None,
    servo_deviations: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """Validate mechanical calibration parameters for ``puppy.py`` and ``servo_deviation.json``.

    Args:
        with_arm: Optional robotic arm flag (``0`` or ``1``).
        x_shift: Optional standing center-of-gravity offset in ``[-10.0, 10.0]``.
        servo_deviations: Optional map of servo IDs (``1..11``) to trim integers in ``[-200, 200]``.

    Returns:
        Sanitized parameter dictionary.

    Raises:
        ValueError: When any parameter falls outside safe bounds.
    """
    out: Dict[str, Any] = {}
    if with_arm is not None:
        arm_int = int(with_arm)
        if arm_int not in (0, 1):
            raise ValueError(f"with_arm must be 0 or 1, got {with_arm!r}")
        out["with_arm"] = arm_int
    if x_shift is not None:
        xs = float(x_shift)
        if xs < -10.0 or xs > 10.0:
            raise ValueError(f"x_shift must be within [-10.0, 10.0], got {xs}")
        out["x_shift"] = round(xs, 3)
    if servo_deviations is not None:
        clean_dev: Dict[str, int] = {}
        for k, v in servo_deviations.items():
            sid = int(k)
            if sid < 1 or sid > 16:
                raise ValueError(f"Servo ID must be in 1..16, got {k!r}")
            trim = int(v)
            if trim < -200 or trim > 200:
                raise ValueError(f"Servo {sid} deviation must be in [-200, 200], got {trim}")
            clean_dev[str(sid)] = trim
        out["servo_deviations"] = clean_dev
    if not out:
        raise ValueError("At least one of with_arm, x_shift, or servo_deviations must be provided")
    return out


def parse_network_interfaces(
    ip_json_text: str,
    nmcli_text: str = "",
    iw_link_text: str = "",
    mac_map: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Parse ``ip -j -br addr`` (or ``ip -j addr``), ``nmcli dev status``, and ``iw dev wlan0 link``.

    Handles ``ip -j -br addr`` omitting ``"family"`` by detecting IPv4 via ``"." in local``.

    Args:
        ip_json_text: JSON stdout from ``ip -j -br addr`` or ``ip -j addr``.
        nmcli_text: Output from ``nmcli -t -f DEVICE,TYPE,STATE,CONNECTION dev status``.
        iw_link_text: Output from ``iw dev wlan0 link`` (and/or ``iw dev wlan0 info``).
        mac_map: Optional mapping of interface name to hardware MAC address.

    Returns:
        Structured dictionary with ``wifi``, ``ethernet``, and ``interfaces`` keys.
    """
    nm_by_dev: Dict[str, Dict[str, str]] = {}
    for ln in (nmcli_text or "").splitlines():
        parts = ln.split(":", 3)
        if len(parts) >= 4:
            dev, dev_type, state, conn = parts[0].strip(), parts[1].strip(), parts[2].strip(), parts[3].strip()
            if dev:
                nm_by_dev[dev] = {"type": dev_type, "state": state, "connection": conn}

    iw_ssid: Optional[str] = None
    iw_freq: Optional[int] = None
    iw_signal_pct: Optional[int] = None
    iw_mode: Optional[str] = None
    if iw_link_text:
        m_ssid = re.search(r"SSID:\s*(.+)$", iw_link_text, re.MULTILINE)
        if m_ssid:
            iw_ssid = m_ssid.group(1).strip()
        m_freq = re.search(r"freq:\s*(\d+)", iw_link_text)
        if m_freq:
            iw_freq = int(m_freq.group(1))
        m_sig = re.search(r"signal:\s*(-?\d+)\s*dBm", iw_link_text)
        if m_sig:
            dbm = int(m_sig.group(1))
            iw_signal_pct = int(max(0, min(100, (dbm + 100) * 2)))
        if re.search(r"type\s+AP", iw_link_text, re.IGNORECASE):
            iw_mode = "ap"
        elif iw_ssid:
            iw_mode = "sta"

    raw_ifaces: List[Dict[str, Any]] = []
    try:
        parsed = json.loads(ip_json_text or "[]")
        if isinstance(parsed, list):
            raw_ifaces = [x for x in parsed if isinstance(x, dict)]
    except json.JSONDecodeError:
        raw_ifaces = []

    interfaces: List[Dict[str, Any]] = []
    ethernet: List[Dict[str, Any]] = []
    wifi_info: Dict[str, Any] = {
        "ifname": "wlan0",
        "enabled": False,
        "state": "DOWN",
        "mode": "disconnected",
        "ssid": iw_ssid,
        "ipv4": None,
        "mac": (mac_map or {}).get("wlan0"),
        "freq_mhz": iw_freq,
        "signal_pct": iw_signal_pct,
        "connection": None,
    }

    for entry in raw_ifaces:
        ifname = str(entry.get("ifname") or "").strip()
        if not ifname or ifname == "lo" or ifname.startswith(("docker", "br-", "veth")):
            continue
        operstate = str(entry.get("operstate") or "UNKNOWN").upper()
        mac = entry.get("address") or (mac_map or {}).get(ifname)
        ipv4_list: List[str] = []
        for a in entry.get("addr_info") or []:
            local = str(a.get("local") or "")
            if "." in local and ":" not in local:
                ipv4_list.append(local)
        ipv4 = ipv4_list[0] if ipv4_list else None
        nm = nm_by_dev.get(ifname, {})
        conn_name = nm.get("connection") or None
        nm_state = (nm.get("state") or "").lower()
        enabled = bool(operstate == "UP" or (ipv4 is not None) or nm_state == "connected")

        iface_rec: Dict[str, Any] = {
            "ifname": ifname,
            "enabled": enabled,
            "state": operstate,
            "ipv4": ipv4,
            "mac": mac,
            "connection": conn_name,
        }

        if ifname.startswith("wlan") or nm.get("type") == "wifi":
            mode = iw_mode
            if not mode:
                if conn_name and conn_name.startswith("HW-"):
                    mode = "ap"
                elif enabled and (iw_ssid or conn_name):
                    mode = "sta"
                else:
                    mode = "disconnected"
            wifi_info = {
                **iface_rec,
                "mode": mode,
                "ssid": iw_ssid or conn_name,
                "freq_mhz": iw_freq,
                "signal_pct": iw_signal_pct,
            }
            interfaces.append({**wifi_info, "type": "wifi"})
        elif ifname.startswith(("eth", "enp", "enx")) or nm.get("type") == "ethernet":
            kind = "onboard" if ifname == "eth0" else "usb"
            eth_rec = {**iface_rec, "kind": kind}
            ethernet.append(eth_rec)
            interfaces.append({**eth_rec, "type": "ethernet"})
        else:
            interfaces.append({**iface_rec, "type": nm.get("type") or "other"})

    # Ensure any ethernet interfaces present only in nmcli still appear
    seen_eth = {e["ifname"] for e in ethernet}
    for dev, nm in nm_by_dev.items():
        if nm.get("type") == "ethernet" and dev not in seen_eth:
            eth_rec = {
                "ifname": dev,
                "enabled": nm.get("state") == "connected",
                "state": "UP" if nm.get("state") == "connected" else "DOWN",
                "ipv4": None,
                "mac": (mac_map or {}).get(dev),
                "connection": nm.get("connection") or None,
                "kind": "onboard" if dev == "eth0" else "usb",
            }
            ethernet.append(eth_rec)
            interfaces.append({**eth_rec, "type": "ethernet"})

    ethernet.sort(key=lambda e: (0 if e["enabled"] else 1, e["ifname"]))
    return {"wifi": wifi_info, "ethernet": ethernet, "interfaces": interfaces}


_NETWORK_REMOTE_SCRIPT = r"""
import glob, json, os, subprocess

sudo_pw = os.environ.get("SUDO_PW", "")

def run(cmd, timeout=8):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ""

def run_docker(args, timeout=10):
    try:
        r = subprocess.run(["docker"] + args, capture_output=True, text=True, timeout=timeout)
        if r.returncode == 0:
            return r.returncode, r.stdout.strip(), r.stderr.strip()
    except Exception:
        pass
    if sudo_pw:
        try:
            r = subprocess.run(
                ["sudo", "-S", "-p", "", "docker"] + args,
                input=sudo_pw + "\n",
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return r.returncode, r.stdout.strip(), r.stderr.strip()
        except Exception as exc:
            return -1, "", str(exc)
    return -1, "", "docker unavailable"

macs = {}
for p in glob.glob("/sys/class/net/*/address"):
    iface = os.path.basename(os.path.dirname(p))
    try:
        with open(p, "r", encoding="utf-8") as f:
            macs[iface] = f.read().strip()
    except Exception:
        pass

ip_br = run(["ip", "-j", "-br", "addr"])
nmcli_out = run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "dev", "status"])
iw_link = run(["iw", "dev", "wlan0", "link"])
iw_info = run(["iw", "dev", "wlan0", "info"])

ros_containers = []
active_ros_distro = None
rc_dk, dk_out, _ = run_docker(["ps", "-a", "--format", "{{.Names}}\t{{.State}}\t{{.Status}}"])
if rc_dk == 0 and dk_out:
    for ln in dk_out.splitlines():
        parts = ln.split("\t")
        if len(parts) >= 2:
            cname = parts[0].strip()
            cstate = parts[1].strip()
            cstatus = parts[2].strip() if len(parts) > 2 else ""
            distro = "ROS1 Noetic" if cname == "puppypi" else ("ROS2 Humble" if cname == "puppypi_ros2" else "unknown")
            ros_containers.append({
                "name": cname,
                "state": cstate,
                "status": cstatus,
                "ros_distro": distro,
            })
            if cstate.lower() == "running":
                if cname == "puppypi":
                    active_ros_distro = "ROS1 Noetic"
                elif cname == "puppypi_ros2":
                    active_ros_distro = "ROS2 Humble"

print(json.dumps({
    "ip_br_json": ip_br,
    "nmcli_status": nmcli_out,
    "iw_link": (iw_link + "\n" + iw_info).strip(),
    "mac_map": macs,
    "active_ros_distro": active_ros_distro,
    "ros_containers": ros_containers,
}))
"""


async def collect_network_interfaces(
    ip: str,
    user: str,
    password: str,
) -> Dict[str, Any]:
    """Query live Wi-Fi, Ethernet, and active ROS Docker container status on the robot over SSH.

    Args:
        ip: Robot IPv4 address.
        user: SSH username.
        password: SSH password.

    Returns:
        Structured dictionary with ``wifi``, ``ethernet``, ``interfaces``,
        ``active_ros_distro``, and ``ros_containers``.
    """
    raw = await run_remote_python(
        ip=ip,
        user=user,
        password=password,
        python_source=_NETWORK_REMOTE_SCRIPT,
        payload={},
        timeout=20.0,
        retries=3,
        env_vars={"SUDO_PW": password},
    )
    parsed = parse_network_interfaces(
        ip_json_text=str(raw.get("ip_br_json") or "[]"),
        nmcli_text=str(raw.get("nmcli_status") or ""),
        iw_link_text=str(raw.get("iw_link") or ""),
        mac_map=raw.get("mac_map") or {},
    )
    parsed["active_ros_distro"] = raw.get("active_ros_distro")
    parsed["ros_containers"] = raw.get("ros_containers") or []
    return parsed


def validate_ros_ai_params(
    target_ros: Optional[str] = None,
    asr_language: Optional[str] = None,
    ros_domain_id: Optional[int] = None,
    rmw_implementation: Optional[str] = None,
    persist_boot: bool = True,
) -> Dict[str, Any]:
    """Validate ROS distro switch target, DDS parameters, ASR language, and boot persistence.

    Args:
        target_ros: Optional ``"ros1"``/``"noetic"`` or ``"ros2"``/``"humble"``.
        asr_language: Optional ``"English"`` or ``"Chinese"``.
        ros_domain_id: Optional ROS 2 DDS domain ID in ``0..232``.
        rmw_implementation: Optional RMW middleware (``rmw_cyclonedds_cpp`` or ``rmw_fastrtps_cpp``).
        persist_boot: Whether switching ``target_ros`` also updates systemd and Docker restart
            policies so the chosen ROS distro boots automatically after power-cycling.

    Returns:
        Normalized configuration dictionary.
    """
    norm_ros: Optional[str] = None
    if target_ros is not None and str(target_ros).strip():
        raw = str(target_ros).strip().lower()
        if raw in ("ros1", "noetic", "puppypi"):
            norm_ros = "ros1"
        elif raw in ("ros2", "humble", "puppypi_ros2"):
            norm_ros = "ros2"
        else:
            raise ValueError(f"target_ros must be 'ros1' or 'ros2', got {target_ros!r}")

    norm_lang: Optional[str] = None
    if asr_language is not None and str(asr_language).strip():
        raw_lang = str(asr_language).strip()
        if raw_lang not in VALID_ASR_LANGUAGES:
            raise ValueError(f"asr_language must be 'English' or 'Chinese', got {asr_language!r}")
        norm_lang = raw_lang

    norm_domain: Optional[int] = None
    if ros_domain_id is not None:
        dom = int(ros_domain_id)
        if dom < 0 or dom > 232:
            raise ValueError(f"ros_domain_id must be between 0 and 232, got {dom}")
        norm_domain = dom

    norm_rmw: Optional[str] = None
    if rmw_implementation is not None and str(rmw_implementation).strip():
        rmw = str(rmw_implementation).strip()
        if rmw not in VALID_RMW_IMPLEMENTATIONS:
            raise ValueError(f"rmw_implementation must be one of {sorted(VALID_RMW_IMPLEMENTATIONS)}, got {rmw!r}")
        norm_rmw = rmw

    if norm_ros is None and norm_lang is None and norm_domain is None and norm_rmw is None:
        raise ValueError("Provide target_ros, asr_language, ros_domain_id, or rmw_implementation")
    return {
        "target_ros": norm_ros,
        "asr_language": norm_lang,
        "ros_domain_id": norm_domain,
        "rmw_implementation": norm_rmw,
        "persist_boot": bool(persist_boot),
    }


def render_ros2_boot_script(
    ros_domain_id: int = 0,
    rmw_implementation: str = "rmw_cyclonedds_cpp",
) -> str:
    """Render ``/home/pi/puppypi/start_node_ros2.sh`` for unattended ROS 2 Humble boot.

    Validates DDS parameters before rendering and emits a bash script that:
    - Stops any ROS 1 ``puppypi`` container and starts ``puppypi_ros2``
    - Grants camera/LiDAR device permissions (``/dev/video0``, ``/dev/video1``, ``/dev/ldlidar``)
    - Launches the full ROS 2 Humble bringup stack as ``ubuntu``
    - Launches a single deduplicated ``ldlidar_stl_ros2_node`` when ``/dev/ldlidar`` is present

    Args:
        ros_domain_id: Validated ROS 2 DDS domain ID in ``0..232``.
        rmw_implementation: Validated RMW middleware string.

    Returns:
        Executable bash script content with trailing newline.
    """
    validated = validate_ros_ai_params(
        target_ros="ros2",
        ros_domain_id=ros_domain_id,
        rmw_implementation=rmw_implementation,
    )
    dom = int(validated["ros_domain_id"] if validated["ros_domain_id"] is not None else 0)
    rmw = str(validated["rmw_implementation"] or "rmw_cyclonedds_cpp")
    return (
        "#!/bin/bash\n"
        "# Managed by Eigenia TwinScan — Automatic ROS 2 Humble Boot Bringup\n"
        "set +e\n\n"
        "for _ in $(seq 1 20); do\n"
        "    docker info >/dev/null 2>&1 && break\n"
        "    sleep 1\n"
        "done\n\n"
        "docker stop puppypi >/dev/null 2>&1 || true\n"
        "docker start puppypi_ros2 >/dev/null 2>&1 || true\n"
        "sleep 2\n\n"
        "for dev in /dev/video0 /dev/video1 /dev/ldlidar; do\n"
        "    [ -e \"$dev\" ] && chmod 666 \"$dev\" 2>/dev/null || true\n"
        "done\n\n"
        "docker exec puppypi_ros2 rm -f /tmp/ros2_rrc.log /tmp/ros2_puppy.log /tmp/ros2_cam.log /tmp/ros2_video.log /tmp/ros2_bridge.log /tmp/ldlidar_ros2.log >/dev/null 2>&1 || true\n\n"
        "docker exec -u ubuntu puppypi_ros2 bash -lc '"
        "pids=$(ps -eww -o pid,ppid,args | awk -v self=\"$$\" "
        "\"\\$1 != self && \\$2 != self && !/awk/ && "
        "(/ros2 launch/|/rosbridge_websocket/|/web_video_server/|/puppy_control/|/ros_robot_controller/|/usb_cam_node/) {print \\$1}\"); "
        "[ -n \"$pids\" ] && kill -9 $pids 2>/dev/null || true; sleep 0.5'\n\n"
        "ROS2_ENV=\"source /opt/ros/humble/setup.bash 2>/dev/null || true; "
        "source /home/ubuntu/ros2_ws/.robotrc 2>/dev/null || true; "
        "source /home/ubuntu/ros2_ws/.typerc 2>/dev/null || true; "
        "source /home/ubuntu/third_party_ros2/third_party_ws/install/setup.bash 2>/dev/null || true; "
        "source /home/ubuntu/ros2_ws/install/setup.bash 2>/dev/null || true; "
        f"export RMW_IMPLEMENTATION={rmw} ROS_LOCALHOST_ONLY=0 ROS_DOMAIN_ID={dom}\"\n\n"
        "docker exec -d -u ubuntu puppypi_ros2 bash -lc \"$ROS2_ENV; exec ros2 launch ros_robot_controller ros_robot_controller.launch.py >/tmp/ros2_rrc.log 2>&1\"\n"
        "docker exec -d -u ubuntu puppypi_ros2 bash -lc \"$ROS2_ENV; exec ros2 launch puppy_control puppy_control.launch.py >/tmp/ros2_puppy.log 2>&1\"\n"
        "docker exec -d -u ubuntu puppypi_ros2 bash -lc \"$ROS2_ENV; exec ros2 launch peripherals usb_cam.launch.py >/tmp/ros2_cam.log 2>&1\"\n"
        "docker exec -d -u ubuntu puppypi_ros2 bash -lc \"$ROS2_ENV; exec ros2 launch peripherals web_video_server.launch.py >/tmp/ros2_video.log 2>&1\"\n"
        "docker exec -d -u ubuntu puppypi_ros2 bash -lc \"$ROS2_ENV; exec ros2 launch rosbridge_server rosbridge_websocket_launch.xml >/tmp/ros2_bridge.log 2>&1\"\n\n"
        "if [ -e /dev/ldlidar ]; then\n"
        "    docker exec -u ubuntu puppypi_ros2 bash -lc '"
        "pids=$(ps -eww -o pid,ppid,args | awk -v self=\"$$\" "
        "\"\\$1 != self && \\$2 != self && !/awk/ && /ldlidar_stl_ros2/ {print \\$1}\"); "
        "[ -n \"$pids\" ] && kill -9 $pids 2>/dev/null || true; sleep 0.3'\n"
        "    docker exec -d -u ubuntu puppypi_ros2 bash -lc \"$ROS2_ENV; "
        "exec /home/ubuntu/third_party_ros2/third_party_ws/install/ldlidar_stl_ros2/lib/ldlidar_stl_ros2/ldlidar_stl_ros2_node --ros-args "
        "-p product_name:=LDLiDAR_LD19 -p topic_name:=scan -p frame_id:=lidar_frame "
        "-p port_name:=/dev/ldlidar -p port_baudrate:=230400 -p laser_scan_dir:=true "
        "-p enable_angle_crop_func:=false > /tmp/ldlidar_ros2.log 2>&1\"\n"
        "fi\n"
    )


def render_ros2_systemd_unit() -> str:
    """Render ``/etc/systemd/system/start_node_ros2.service`` for automatic ROS 2 Humble boot.

    Returns:
        Systemd unit file text with trailing newline.
    """
    return (
        "[Unit]\n"
        "Description=Eigenia PuppyPi ROS 2 Humble Automatic Bringup\n"
        "Requires=docker.service\n"
        "After=docker.service network-online.target\n\n"
        "[Service]\n"
        "Type=oneshot\n"
        "RemainAfterExit=yes\n"
        "User=root\n"
        "ExecStart=/bin/bash /home/pi/puppypi/start_node_ros2.sh\n\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )


def _extract_marked_output(raw_text: str) -> str:
    """Extract clean stdout enclosed between ``SSH_BEGIN_MARKER`` and ``SSH_END_MARKER``."""
    normalized = raw_text.replace("\r\n", "\n")
    start_idx = normalized.rfind(SSH_BEGIN_MARKER)
    if start_idx == -1:
        return normalized.strip()
    after_start = normalized[start_idx + len(SSH_BEGIN_MARKER) :]
    end_idx = after_start.find(SSH_END_MARKER)
    if end_idx == -1:
        return after_start.strip()
    return after_start[:end_idx].strip()


def _run_ssh_pty_sync(
    ip: str,
    user: str,
    password: str,
    remote_cmd: str,
    timeout: float = 30.0,
) -> Tuple[int, str]:
    """Execute a command over OpenSSH using stdlib ``pty`` to supply password interactively."""
    clean_ip, clean_user = validate_ssh_target(ip, user)
    wrapped = f"printf '{SSH_BEGIN_MARKER}\\n'; {remote_cmd}; rc=$?; printf '\\n{SSH_END_MARKER}\\n'; exit $rc"
    ssh_argv = [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "ConnectTimeout=8",
        "-o", "NumberOfPasswordPrompts=1",
        "-o", "PubkeyAuthentication=no",
        "-o", "PreferredAuthentications=password,keyboard-interactive",
        "-o", "LogLevel=ERROR",
        f"{clean_user}@{clean_ip}",
        wrapped,
    ]

    master_fd, slave_fd = pty.openpty()
    proc: Optional[subprocess.Popen[bytes]] = None
    buf = bytearray()
    pw_sent = False
    deadline = time.monotonic() + timeout

    def _attach_controlling_tty() -> None:
        os.setsid()
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)

    try:
        proc = subprocess.Popen(
            ssh_argv,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            preexec_fn=_attach_controlling_tty,
            close_fds=True,
        )
        os.close(slave_fd)
        slave_fd = -1

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                proc.kill()
                raise TimeoutError(f"SSH command to {clean_user}@{clean_ip} timed out after {timeout}s")

            rlist, _, _ = select.select([master_fd], [], [], min(0.2, remaining))
            if rlist:
                try:
                    chunk = os.read(master_fd, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                buf.extend(chunk)
                tail = bytes(buf[-256:]).decode("utf-8", errors="ignore").lower()
                if not pw_sent and ("password:" in tail or "passphrase" in tail):
                    os.write(master_fd, (password + "\n").encode("utf-8"))
                    pw_sent = True
                if "permission denied" in tail or "authentication failed" in tail:
                    proc.kill()
                    raise SSHAuthError(f"SSH authentication failed for {clean_user}@{clean_ip}")
            elif proc.poll() is not None:
                # Drain any remaining buffered bytes after child exits.
                while True:
                    r2, _, _ = select.select([master_fd], [], [], 0.05)
                    if not r2:
                        break
                    try:
                        more = os.read(master_fd, 4096)
                    except OSError:
                        break
                    if not more:
                        break
                    buf.extend(more)
                break

        returncode = proc.wait(timeout=2.0)
        decoded = buf.decode("utf-8", errors="replace")
        if "permission denied" in decoded.lower() and SSH_BEGIN_MARKER not in decoded:
            raise SSHAuthError(f"SSH authentication failed for {clean_user}@{clean_ip}")
        return returncode, _extract_marked_output(decoded)
    finally:
        if slave_fd >= 0:
            try:
                os.close(slave_fd)
            except OSError:
                pass
        try:
            os.close(master_fd)
        except OSError:
            pass
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
                proc.wait(timeout=1.0)
            except Exception:
                pass


async def run_ssh_command(
    ip: str,
    user: str,
    password: str,
    remote_cmd: str,
    timeout: float = 30.0,
    retries: int = 3,
) -> Tuple[int, str]:
    """Run an SSH command asynchronously via stdlib ``pty`` with 3x retry on transient errors.

    Args:
        ip: Target robot IPv4 address.
        user: SSH username.
        password: SSH password.
        remote_cmd: Fixed shell command (must NOT interpolate untrusted user input).
        timeout: Per-attempt execution timeout in seconds.
        retries: Maximum retry attempts on transient network errors.

    Returns:
        Tuple ``(exit_code, cleaned_stdout)``.

    Raises:
        SSHAuthError: Immediately on bad credentials (no pointless retry).
        SSHCommandError: When all attempts fail.
    """
    last_exc: Optional[Exception] = None
    for attempt in range(1, max(1, retries) + 1):
        try:
            return await asyncio.to_thread(_run_ssh_pty_sync, ip, user, password, remote_cmd, timeout)
        except SSHAuthError:
            raise
        except Exception as exc:
            last_exc = exc
            sys.stderr.write(
                f"[ssh] Command to {user}@{ip} failed (attempt {attempt}/{retries}): {exc}\n"
            )
            if attempt < retries:
                await asyncio.sleep(min(0.6 * attempt, 2.0))
    raise SSHCommandError(f"SSH command to {user}@{ip} failed after {retries} attempts: {last_exc}")


async def run_remote_python(
    ip: str,
    user: str,
    password: str,
    python_source: str,
    payload: Optional[Dict[str, Any]] = None,
    timeout: float = 45.0,
    retries: int = 3,
    env_vars: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Execute a base64-encoded Python 3 script on the remote robot with JSON input & output.

    Zero shell injection: both ``python_source`` and ``payload`` are base64-encoded so
    only ``[A-Za-z0-9+/=]`` characters ever cross the SSH command line. Optional
    ``env_vars`` (such as ``SUDO_PW``) are safely shell-quoted as inline environment
    assignments and never passed as command-line arguments to child binaries.

    Args:
        ip: Target robot IPv4 address.
        user: SSH username.
        password: SSH password.
        python_source: Self-contained Python 3 script reading ``PAYLOAD`` dict and printing JSON.
        payload: Optional JSON-serializable input dictionary exposed as ``PAYLOAD``.
        timeout: Execution timeout in seconds.
        retries: Maximum retry attempts on transient errors.
        env_vars: Optional dictionary of environment variables for the remote python process.

    Returns:
        Parsed JSON dictionary printed by the remote script.

    Raises:
        SSHCommandError: If execution returns non-zero or invalid JSON output.
    """
    src_b64 = base64.b64encode(python_source.encode("utf-8")).decode("ascii")
    pay_b64 = base64.b64encode(json.dumps(payload or {}).encode("utf-8")).decode("ascii")
    env_prefix = ""
    if env_vars:
        parts = []
        for k, v in env_vars.items():
            if not re.match(r"^[A-Z_][A-Z0-9_]*$", k):
                raise ValueError(f"Invalid env var name: {k!r}")
            parts.append(f"{k}={shlex.quote(str(v))}")
        env_prefix = " ".join(parts) + " "
    remote_cmd = (
        f"{env_prefix}python3 -c \"import base64,json;"
        f"PAYLOAD=json.loads(base64.b64decode('{pay_b64}').decode());"
        f"exec(compile(base64.b64decode('{src_b64}').decode(), '<eigenia>', 'exec'))\""
    )
    rc, output = await run_ssh_command(
        ip=ip,
        user=user,
        password=password,
        remote_cmd=remote_cmd,
        timeout=timeout,
        retries=retries,
    )
    if rc != 0:
        raise SSHCommandError(f"Remote Python helper exited with code {rc}: {output[:400]}")
    lines = [ln.strip() for ln in output.splitlines() if ln.strip()]
    for candidate in reversed(lines):
        if candidate.startswith("{") and candidate.endswith("}"):
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise SSHCommandError(f"Invalid JSON from remote Python helper: {exc} | raw={output[:300]}") from exc


def build_robot_cyclonedx_hbom_sbom(
    robot_meta: Dict[str, Any],
    devices: Sequence[Dict[str, Any]],
    sbom_packages: Sequence[Dict[str, Any]],
    containers: Sequence[Dict[str, Any]] = (),
    live_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Generate an OWASP CycloneDX 1.6 combined Robot Hardware BOM + Software SBOM JSON.

    Args:
        robot_meta: Robot identity metadata (name, model, serial_number, ip_address, etc.).
        devices: Catalogued hardware BOM device dictionaries.
        sbom_packages: Catalogued software SBOM package dictionaries.
        containers: Catalogued Docker/ROS container metadata dictionaries.
        live_config: Redacted live robot configuration summary.

    Returns:
        CycloneDX 1.6 compliant JSON dictionary.
    """
    components: List[Dict[str, Any]] = []

    for idx, dev in enumerate(devices):
        props = [
            {"name": "eigenia:subsystem", "value": str(dev.get("subsystem") or "hardware")},
            {"name": "eigenia:bus_type", "value": str(dev.get("bus_type") or "unknown")},
            {"name": "eigenia:status", "value": str(dev.get("status") or "online")},
        ]
        if dev.get("device_path"):
            props.append({"name": "eigenia:device_path", "value": str(dev["device_path"])})
        if dev.get("usb_id"):
            props.append({"name": "eigenia:usb_id", "value": str(dev["usb_id"])})
        components.append(
            {
                "bom-ref": f"hw-{idx + 1}-{dev.get('subsystem', 'dev')}",
                "type": "device",
                "name": f"{dev.get('make', 'Unknown')} {dev.get('model', 'Device')}".strip(),
                "manufacturer": {"name": str(dev.get("make") or "Unknown")},
                "version": str((dev.get("metadata") or {}).get("revision") or "1.0"),
                "properties": props,
            }
        )

    for c_idx, ctr in enumerate(containers):
        c_name = str(ctr.get("name") or f"container-{c_idx + 1}")
        components.append(
            {
                "bom-ref": f"container-{c_name}",
                "type": "container",
                "name": c_name,
                "version": str(ctr.get("image") or "unknown"),
                "properties": [
                    {"name": "eigenia:ros_distro", "value": str(ctr.get("ros_distro") or "unknown")},
                    {"name": "eigenia:container_state", "value": str(ctr.get("state") or "unknown")},
                    {"name": "eigenia:container_status", "value": str(ctr.get("status") or "")},
                ],
            }
        )

    for p_idx, pkg in enumerate(sbom_packages):
        comp: Dict[str, Any] = {
            "bom-ref": f"pkg-{pkg.get('layer', 'host')}-{p_idx + 1}",
            "type": "library",
            "name": str(pkg.get("name") or ""),
            "version": str(pkg.get("version") or ""),
            "properties": [
                {"name": "eigenia:sbom_layer", "value": str(pkg.get("layer") or "host_dpkg")},
            ],
        }
        if pkg.get("purl"):
            comp["purl"] = str(pkg["purl"])
        components.append(comp)

    meta_props = [
        {"name": "eigenia:ip_address", "value": str(robot_meta.get("ip_address") or "")},
    ]
    if robot_meta.get("mac_address"):
        meta_props.append({"name": "eigenia:mac_address", "value": str(robot_meta["mac_address"])})
    if robot_meta.get("serial_number"):
        meta_props.append({"name": "eigenia:serial_number", "value": str(robot_meta["serial_number"])})
    if robot_meta.get("active_ros_distro"):
        meta_props.append({"name": "eigenia:active_ros_distro", "value": str(robot_meta["active_ros_distro"])})
    if live_config:
        if live_config.get("asr_language"):
            meta_props.append({"name": "eigenia:asr_language", "value": str(live_config["asr_language"])})
        if live_config.get("with_arm") is not None:
            meta_props.append({"name": "eigenia:with_arm", "value": str(live_config["with_arm"])})

    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{uuid.uuid4()}",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tools": {
                "components": [
                    {"type": "application", "name": "Eigenia TwinScan Robot Cataloguer", "version": "2.0.0"}
                ]
            },
            "component": {
                "bom-ref": f"robot-{robot_meta.get('id') or robot_meta.get('ip_address') or 'puppypi'}",
                "type": "device",
                "name": str(robot_meta.get("name") or "Hiwonder PuppyPi Pro"),
                "version": str(robot_meta.get("model") or "PuppyPi Pro"),
                "properties": meta_props,
            },
        },
        "components": components,
    }


_CATALOGUE_REMOTE_SCRIPT = r"""
import glob, json, os, re, subprocess

sudo_pw = os.environ.get("SUDO_PW", "")

def run(cmd, timeout=12):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except Exception as e:
        return -1, "", str(e)

def run_docker(args, timeout=15):
    try:
        r = subprocess.run(["docker"] + args, capture_output=True, text=True, timeout=timeout)
        if r.returncode == 0:
            return r.returncode, r.stdout.strip(), r.stderr.strip()
    except Exception:
        pass
    if sudo_pw:
        try:
            r = subprocess.run(
                ["sudo", "-S", "-p", "", "docker"] + args,
                input=sudo_pw + "\n",
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return r.returncode, r.stdout.strip(), r.stderr.strip()
        except Exception as e:
            return -1, "", str(e)
    return -1, "", "docker permission denied"

def read_file(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read().replace("\x00", "").strip()
    except Exception:
        return ""

board = {}
board["model"] = read_file("/proc/device-tree/model") or "Raspberry Pi"
cpuinfo = read_file("/proc/cpuinfo")
for key, field in (("Revision", "revision"), ("Serial", "serial"), ("Hardware", "hardware")):
    m = re.search(rf"^{key}\s*:\s*(.+)$", cpuinfo, re.MULTILINE)
    if m:
        board[field] = m.group(1).strip()
temp_raw = read_file("/sys/class/thermal/thermal_zone0/temp")
if temp_raw.isdigit():
    board["cpu_temp_c"] = round(int(temp_raw) / 1000.0, 1)
meminfo = read_file("/proc/meminfo")
m_tot = re.search(r"MemTotal:\s+(\d+)\s+kB", meminfo)
m_avail = re.search(r"MemAvailable:\s+(\d+)\s+kB", meminfo)
if m_tot:
    board["ram_total_mb"] = round(int(m_tot.group(1)) / 1024.0, 1)
if m_avail:
    board["ram_available_mb"] = round(int(m_avail.group(1)) / 1024.0, 1)
_, df_out, _ = run(["df", "-B1", "/"])
df_lines = df_out.splitlines()
if len(df_lines) >= 2:
    parts = df_lines[1].split()
    if len(parts) >= 5:
        board["disk_total_gb"] = round(int(parts[1]) / (1024**3), 2)
        board["disk_used_gb"] = round(int(parts[2]) / (1024**3), 2)
        board["disk_use_pct"] = parts[4]
os_rel = read_file("/etc/os-release")
m_os = re.search(r'PRETTY_NAME="([^"]+)"', os_rel)
board["os_pretty"] = m_os.group(1) if m_os else ""
_, uname_out, _ = run(["uname", "-r"])
board["kernel"] = uname_out

# Network interfaces (full + brief + nmcli + iw for Wi-Fi/Ethernet telemetry)
net_ifaces = []
mac_map = {}
for mp in glob.glob("/sys/class/net/*/address"):
    iname = os.path.basename(os.path.dirname(mp))
    mac_map[iname] = read_file(mp)
rc_ip, ip_out, _ = run(["ip", "-j", "addr"])
if rc_ip == 0 and ip_out:
    try:
        for iface in json.loads(ip_out):
            name = iface.get("ifname", "")
            if name == "lo":
                continue
            addrs = [a.get("local") for a in iface.get("addr_info", []) if a.get("family") == "inet"]
            net_ifaces.append({
                "name": name,
                "mac": iface.get("address") or mac_map.get(name),
                "state": iface.get("operstate", "UNKNOWN"),
                "ipv4": addrs,
            })
    except Exception:
        pass
_, ip_br_out, _ = run(["ip", "-j", "-br", "addr"])
_, nmcli_out, _ = run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "dev", "status"])
_, iw_link_out, _ = run(["iw", "dev", "wlan0", "link"])
_, iw_info_out, _ = run(["iw", "dev", "wlan0", "info"])

# USB devices
usb_devices = []
rc_usb, usb_out, _ = run(["lsusb"])
if rc_usb == 0:
    for ln in usb_out.splitlines():
        m = re.match(r"Bus\s+(\d+)\s+Device\s+(\d+):\s+ID\s+([0-9a-fA-F:]+)\s*(.*)", ln)
        if m:
            usb_devices.append({
                "bus": m.group(1),
                "device": m.group(2),
                "usb_id": m.group(3),
                "description": m.group(4).strip(),
            })

# Serial ports
serial_ports = sorted(
    glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyAMA*") + glob.glob("/dev/serial/by-id/*")
)

# Video & Audio & I2C
video_devices = sorted(glob.glob("/dev/video*"))
_, aplay_out, _ = run(["aplay", "-l"])
_, arecord_out, _ = run(["arecord", "-l"])
i2c_buses = sorted(glob.glob("/dev/i2c-*"))
i2c_addrs = []
if "/dev/i2c-1" in i2c_buses:
    rc_i2c, i2c_out, _ = run(["i2cdetect", "-y", "1"])
    if rc_i2c == 0:
        for ln in i2c_out.splitlines()[1:]:
            parts = ln.split(":", 1)
            if len(parts) == 2:
                for tok in parts[1].split():
                    if re.match(r"^[0-9a-fA-F]{2}$", tok):
                        i2c_addrs.append(f"0x{tok.lower()}")

# Docker containers (uses run_docker with automatic sudo -S fallback for pi user)
containers = []
rc_dk, dk_out, _ = run_docker(["ps", "-a", "--format", "{{json .}}"])
if rc_dk == 0 and dk_out:
    for ln in dk_out.splitlines():
        try:
            c = json.loads(ln)
            cname = c.get("Names", "")
            distro = "ROS1 Noetic" if cname == "puppypi" else ("ROS2 Humble" if cname == "puppypi_ros2" else "unknown")
            containers.append({
                "name": cname,
                "image": c.get("Image", ""),
                "state": c.get("State", ""),
                "status": c.get("Status", ""),
                "ros_distro": distro,
            })
        except Exception:
            pass

# Live config (strictly redact Wi-Fi passwords)
live_config = {"with_arm": None, "x_shift": None, "asr_language": None, "servo_deviations": {}, "wifi": {}}
servo_raw = read_file("/home/pi/puppypi/servo_deviation.json")
if servo_raw:
    try:
        live_config["servo_deviations"] = json.loads(servo_raw)
    except Exception:
        pass

for wpath in ("/etc/wifi/wifi_conf.py", os.path.expanduser("~/hiwonder-toolbox/wifi_conf.py")):
    wtxt = read_file(wpath)
    if wtxt:
        m_mode = re.search(r"WIFI_MODE\s*=\s*(\d+)", wtxt)
        m_sta = re.search(r"WIFI_STA_SSID\s*=\s*['\"]([^'\"]*)['\"]", wtxt)
        m_ap = re.search(r"WIFI_AP_SSID\s*=\s*['\"]([^'\"]*)['\"]", wtxt)
        m_pw = re.search(r"WIFI_STA_PASSWORD\s*=\s*['\"]([^'\"]*)['\"]", wtxt)
        live_config["wifi"] = {
            "source": wpath,
            "mode": int(m_mode.group(1)) if m_mode else None,
            "sta_ssid": m_sta.group(1) if m_sta else "",
            "ap_ssid": m_ap.group(1) if m_ap else "",
            "password_set": bool(m_pw and m_pw.group(1)),
        }

running_names = {c["name"] for c in containers if c.get("state") == "running"}
if "puppypi" in running_names:
    rc_p, p_out, _ = run_docker(["exec", "puppypi", "sh", "-c", "cat /home/ubuntu/puppypi/src/puppy_control/scripts/puppy.py 2>/dev/null || cat /home/ubuntu/ros_ws/src/puppy_control/scripts/puppy.py 2>/dev/null"])
    if rc_p == 0 and p_out:
        m_arm = re.search(r"^\s*with_arm\s*=\s*(\d+)", p_out, re.MULTILINE)
        m_xs = re.search(r"['\"]x_shift['\"]\s*:\s*(-?\d+(?:\.\d+)?)", p_out)
        if m_arm:
            live_config["with_arm"] = int(m_arm.group(1))
        if m_xs:
            live_config["x_shift"] = float(m_xs.group(1))
    rc_rc, rc_out, _ = run_docker(["exec", "puppypi", "cat", "/home/ubuntu/puppypi/.robotrc"])
    if rc_rc == 0 and rc_out:
        m_asr = re.search(r"ASR_LANGUAGE\s*=\s*['\"]?([A-Za-z]+)", rc_out)
        if m_asr:
            live_config["asr_language"] = m_asr.group(1)
elif "puppypi_ros2" in running_names:
    rc_p, p_out, _ = run_docker(["exec", "puppypi_ros2", "cat", "/home/ubuntu/ros2_ws/src/driver/puppy_control/puppy_control/puppy.py"])
    if rc_p == 0 and p_out:
        m_arm = re.search(r"^\s*with_arm\s*=\s*(\d+)", p_out, re.MULTILINE)
        m_xs = re.search(r"['\"]x_shift['\"]\s*:\s*(-?\d+(?:\.\d+)?)", p_out)
        if m_arm:
            live_config["with_arm"] = int(m_arm.group(1))
        if m_xs:
            live_config["x_shift"] = float(m_xs.group(1))
    rc_rc, rc_out, _ = run_docker(["exec", "puppypi_ros2", "cat", "/home/ubuntu/ros2_ws/.typerc"])
    if rc_rc == 0 and rc_out:
        m_asr = re.search(r"ASR_LANGUAGE\s*=\s*['\"]?([A-Za-z]+)", rc_out)
        if m_asr:
            live_config["asr_language"] = m_asr.group(1)

# SBOM 6 layers
def parse_dpkg(text):
    pkgs = []
    for ln in text.splitlines():
        if "\t" in ln:
            n, v = ln.split("\t", 1)
            if n.strip():
                pkgs.append({"name": n.strip(), "version": v.strip()})
    return pkgs

def parse_pip(text):
    try:
        items = json.loads(text)
        return [{"name": p.get("name", ""), "version": p.get("version", "")} for p in items if p.get("name")]
    except Exception:
        return []

sbom = {"host_dpkg": [], "host_pip": [], "ros1_dpkg": [], "ros1_pip": [], "ros2_dpkg": [], "ros2_pip": []}
rc, out, _ = run(["dpkg-query", "-W", "-f=${Package}\t${Version}\n"], timeout=15)
if rc == 0:
    sbom["host_dpkg"] = parse_dpkg(out)
rc, out, _ = run(["python3", "-m", "pip", "list", "--format=json"], timeout=15)
if rc == 0:
    sbom["host_pip"] = parse_pip(out)

if "puppypi" in running_names:
    rc, out, _ = run_docker(["exec", "puppypi", "dpkg-query", "-W", "-f=${Package}\t${Version}\n"], timeout=20)
    if rc == 0:
        sbom["ros1_dpkg"] = parse_dpkg(out)
    rc, out, _ = run_docker(["exec", "puppypi", "python3", "-m", "pip", "list", "--format=json"], timeout=20)
    if rc == 0:
        sbom["ros1_pip"] = parse_pip(out)

if "puppypi_ros2" in running_names:
    rc, out, _ = run_docker(["exec", "puppypi_ros2", "dpkg-query", "-W", "-f=${Package}\t${Version}\n"], timeout=20)
    if rc == 0:
        sbom["ros2_dpkg"] = parse_dpkg(out)
    rc, out, _ = run_docker(["exec", "puppypi_ros2", "python3", "-m", "pip", "list", "--format=json"], timeout=20)
    if rc == 0:
        sbom["ros2_pip"] = parse_pip(out)

print(json.dumps({
    "board": board,
    "network_interfaces": net_ifaces,
    "network_raw": {
        "ip_br_json": ip_br_out,
        "nmcli_status": nmcli_out,
        "iw_link": (iw_link_out + "\n" + iw_info_out).strip(),
        "mac_map": mac_map,
    },
    "usb_devices": usb_devices,
    "serial_ports": serial_ports,
    "video_devices": video_devices,
    "audio_playback": aplay_out,
    "audio_capture": arecord_out,
    "i2c_buses": i2c_buses,
    "i2c_addresses": i2c_addrs,
    "containers": containers,
    "live_config": live_config,
    "sbom": sbom,
}))
"""


def normalize_catalogue_payload(
    raw: Dict[str, Any],
    robot_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Normalize raw SSH diagnostic JSON into structured devices, SBOM packages, and CycloneDX 1.6.

    Args:
        raw: JSON output produced by the remote catalogue diagnostic script.
        robot_meta: Existing robot record metadata (for CycloneDX header fields).

    Returns:
        Dictionary with ``devices``, ``sbom_packages``, ``containers``, ``live_config``,
        ``robot_updates``, and ``hbom_sbom`` (CycloneDX 1.6 JSON).
    """
    board = raw.get("board") or {}
    net_ifaces = raw.get("network_interfaces") or []
    usb_devices = raw.get("usb_devices") or []
    serial_ports = raw.get("serial_ports") or []
    video_devices = raw.get("video_devices") or []
    i2c_addrs = raw.get("i2c_addresses") or []
    containers = raw.get("containers") or []
    live_config = raw.get("live_config") or {}
    raw_sbom = raw.get("sbom") or {}

    devices: List[Dict[str, Any]] = []

    # 1. Host Compute SBC
    devices.append(
        {
            "subsystem": "compute",
            "make": "Raspberry Pi",
            "model": str(board.get("model") or "Raspberry Pi 5"),
            "bus_type": "soc",
            "device_path": "/proc/device-tree/model",
            "usb_id": None,
            "status": "online",
            "metadata": {
                "revision": board.get("revision"),
                "serial": board.get("serial"),
                "cpu_temp_c": board.get("cpu_temp_c"),
                "ram_total_mb": board.get("ram_total_mb"),
                "disk_total_gb": board.get("disk_total_gb"),
                "os_pretty": board.get("os_pretty"),
                "kernel": board.get("kernel"),
            },
        }
    )

    # 2. USB peripherals
    has_cp210x_lidar = False
    has_usb_cam = False
    has_wonderecho = False
    for u in usb_devices:
        uid = str(u.get("usb_id") or "")
        desc = str(u.get("description") or "USB Device")
        low = desc.lower()
        if "10c4:ea60" in uid.lower() or "cp210" in low or "lidar" in low:
            has_cp210x_lidar = True
            subsystem = "lidar"
        elif "camera" in low or "uvc" in low or "webcam" in low or "video" in low:
            has_usb_cam = True
            subsystem = "camera"
        elif "audio" in low or "echo" in low or "mic" in low or "1a86:7523" in uid.lower():
            has_wonderecho = True
            subsystem = "audio"
        elif "root hub" in low or "hub" in low:
            subsystem = "usb_hub"
        else:
            subsystem = "usb"
        parts = desc.split(" ", 1)
        make = parts[0] if parts and parts[0] else "USB"
        model = parts[1] if len(parts) > 1 else desc
        devices.append(
            {
                "subsystem": subsystem,
                "make": make,
                "model": model,
                "bus_type": "usb",
                "device_path": f"/dev/bus/usb/{u.get('bus', '001')}/{u.get('device', '001')}",
                "usb_id": uid or None,
                "status": "online",
                "metadata": {"description": desc},
            }
        )

    # 3. Serial ports
    for sp in serial_ports:
        devices.append(
            {
                "subsystem": "serial",
                "make": "UART/Serial",
                "model": os.path.basename(str(sp)),
                "bus_type": "uart",
                "device_path": str(sp),
                "usb_id": None,
                "status": "online",
                "metadata": {},
            }
        )

    # 4. V4L2 Camera devices
    if video_devices:
        has_usb_cam = True
        devices.append(
            {
                "subsystem": "camera",
                "make": "V4L2",
                "model": f"Camera ({video_devices[0]})",
                "bus_type": "v4l2",
                "device_path": str(video_devices[0]),
                "usb_id": None,
                "status": "online",
                "metadata": {"all_video_nodes": video_devices},
            }
        )

    # 5. I2C bus & detected devices
    for addr in i2c_addrs:
        devices.append(
            {
                "subsystem": "i2c_sensor",
                "make": "I2C Device",
                "model": f"I2C Bus 1 @ {addr}",
                "bus_type": "i2c",
                "device_path": "/dev/i2c-1",
                "usb_id": None,
                "status": "online",
                "metadata": {"i2c_address": addr},
            }
        )

    # 6. Network interfaces
    primary_mac: Optional[str] = None
    for iface in net_ifaces:
        if not primary_mac and iface.get("mac") and iface.get("state") == "UP":
            primary_mac = str(iface["mac"])
        devices.append(
            {
                "subsystem": "network",
                "make": "Linux Net",
                "model": str(iface.get("name") or "eth"),
                "bus_type": "network",
                "device_path": f"/sys/class/net/{iface.get('name', 'eth')}",
                "usb_id": None,
                "status": "online" if str(iface.get("state", "")).upper() == "UP" else "down",
                "metadata": {"mac": iface.get("mac"), "ipv4": iface.get("ipv4") or []},
            }
        )
    if not primary_mac and net_ifaces:
        primary_mac = net_ifaces[0].get("mac")

    # 7. Expected PuppyPi Pro peripherals audit (highlight unattached/displaced sensors!)
    if not has_cp210x_lidar and not any("ttyUSB" in str(s) for s in serial_ports):
        devices.append(
            {
                "subsystem": "lidar",
                "make": "LDROBOT",
                "model": "LD19 360° DTOF LiDAR (CP2102)",
                "bus_type": "usb-uart",
                "device_path": "/dev/ttyUSB0",
                "usb_id": "10c4:ea60",
                "status": "unattached",
                "metadata": {"note": "Expected PuppyPi LiDAR not detected on USB/UART (may be connected to workstation)"},
            }
        )
    if not has_wonderecho and "card" not in str(raw.get("audio_capture") or "").lower():
        devices.append(
            {
                "subsystem": "audio",
                "make": "Hiwonder",
                "model": "WonderEcho Voice Module",
                "bus_type": "usb-audio",
                "device_path": None,
                "usb_id": None,
                "status": "unattached",
                "metadata": {"note": "Expected WonderEcho voice/audio peripheral not detected"},
            }
        )

    # Normalize SBOM packages across all 6 layers with valid Package URLs (PURLs).
    sbom_packages: List[Dict[str, Any]] = []
    for layer in ("host_dpkg", "host_pip", "ros1_dpkg", "ros1_pip", "ros2_dpkg", "ros2_pip"):
        entries = raw_sbom.get(layer) or []
        is_pip = layer.endswith("_pip")
        for pkg in entries:
            pname = str(pkg.get("name") or "").strip()
            pver = str(pkg.get("version") or "").strip()
            if not pname:
                continue
            if is_pip:
                purl = f"pkg:pypi/{pname.lower()}@{pver}" if pver else f"pkg:pypi/{pname.lower()}"
            else:
                distro_ns = "ubuntu" if layer.startswith("ros") else "debian"
                purl = f"pkg:deb/{distro_ns}/{pname}@{pver}" if pver else f"pkg:deb/{distro_ns}/{pname}"
            sbom_packages.append(
                {
                    "layer": layer,
                    "name": pname,
                    "version": pver,
                    "purl": purl,
                }
            )

    active_ros_distro: Optional[str] = None
    for c in containers:
        if str(c.get("state", "")).lower() == "running":
            if c.get("name") == "puppypi":
                active_ros_distro = "noetic"
                break
            if c.get("name") == "puppypi_ros2":
                active_ros_distro = "humble"
                break

    net_raw = raw.get("network_raw") or {}
    network_telemetry = parse_network_interfaces(
        ip_json_text=str(net_raw.get("ip_br_json") or "[]"),
        nmcli_text=str(net_raw.get("nmcli_status") or ""),
        iw_link_text=str(net_raw.get("iw_link") or ""),
        mac_map=net_raw.get("mac_map") or {},
    ) if net_raw else None

    robot_updates = {
        "model": str(board.get("model") or "Hiwonder PuppyPi Pro"),
        "serial_number": board.get("serial") or (robot_meta or {}).get("serial_number"),
        "mac_address": primary_mac or (robot_meta or {}).get("mac_address"),
        "active_ros_distro": active_ros_distro,
        "cpu_temp_c": board.get("cpu_temp_c"),
        "status": "online",
        "capabilities": {
            "board": board,
            "containers": containers,
            "live_config": live_config,
            **({"network": network_telemetry} if network_telemetry else {}),
            "has_camera": has_usb_cam,
            "has_lidar_onboard": has_cp210x_lidar,
            "sbom_counts": {layer: len(raw_sbom.get(layer) or []) for layer in ("host_dpkg", "host_pip", "ros1_dpkg", "ros1_pip", "ros2_dpkg", "ros2_pip")},
        },
    }

    merged_meta = {**(robot_meta or {}), **robot_updates}
    hbom_sbom = build_robot_cyclonedx_hbom_sbom(
        robot_meta=merged_meta,
        devices=devices,
        sbom_packages=sbom_packages,
        containers=containers,
        live_config=live_config,
    )

    return {
        "board": board,
        "devices": devices,
        "sbom_packages": sbom_packages,
        "containers": containers,
        "live_config": live_config,
        "network": network_telemetry,
        "robot_updates": robot_updates,
        "hbom_sbom": hbom_sbom,
    }


async def collect_robot_catalogue(
    ip: str,
    user: str,
    password: str,
    robot_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Collect full hardware BOM, Docker/ROS state, live config, and 6-layer SBOM over SSH.

    Args:
        ip: Robot IPv4 address.
        user: SSH username (typically ``"pi"``).
        password: SSH password.
        robot_meta: Optional existing robot metadata merged into CycloneDX header.

    Returns:
        Normalized catalogue dictionary including ``hbom_sbom`` (CycloneDX 1.6 JSON).
    """
    raw = await run_remote_python(
        ip=ip,
        user=user,
        password=password,
        python_source=_CATALOGUE_REMOTE_SCRIPT,
        payload={},
        timeout=55.0,
        retries=3,
        env_vars={"SUDO_PW": password},
    )
    return normalize_catalogue_payload(raw=raw, robot_meta=robot_meta)


_WIFI_REMOTE_SCRIPT = r"""
import json, os, py_compile, subprocess, tempfile, time

content = PAYLOAD["wifi_conf_content"]
mode = int(PAYLOAD.get("mode", 2))
ssid = str(PAYLOAD.get("ssid") or "")
wifi_pw = str(PAYLOAD.get("wifi_password") or "")
country = PAYLOAD["country_code"]
sudo_pw = PAYLOAD["sudo_password"]
restart_svc = bool(PAYLOAD.get("restart_service", True))

def sudo_run(args, stdin_bytes=None, timeout=25):
    cmd = ["sudo", "-S", "-p", ""] + args
    inp = (sudo_pw + "\n").encode("utf-8") + (stdin_bytes or b"")
    return subprocess.run(cmd, input=inp, capture_output=True, timeout=timeout)

def get_wlan0_ipv4():
    try:
        r = subprocess.run(["ip", "-j", "-4", "addr", "show", "dev", "wlan0"], capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            data = json.loads(r.stdout)
            for iface in data:
                for addr in iface.get("addr_info", []):
                    if addr.get("family") == "inet" and addr.get("local"):
                        return str(addr["local"])
    except Exception:
        pass
    return None

# 1. Compile-check rendered Python before touching any live config file!
with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as tf:
    tf.write(content)
    tmp_path = tf.name

try:
    py_compile.compile(tmp_path, doraise=True)
    user_target = os.path.expanduser("~/hiwonder-toolbox/wifi_conf.py")
    os.makedirs(os.path.dirname(user_target), exist_ok=True)
    user_tmp = user_target + ".tmp"
    with open(user_tmp, "w", encoding="utf-8") as uf:
        uf.write(content)
    py_compile.compile(user_tmp, doraise=True)
    os.replace(user_tmp, user_target)

    etc_dir = "/etc/wifi"
    sudo_run(["mkdir", "-p", etc_dir])
    r_cp = sudo_run(["cp", tmp_path, "/etc/wifi/wifi_conf.py.tmp"])
    if r_cp.returncode != 0:
        raise RuntimeError(f"Failed writing /etc/wifi/wifi_conf.py.tmp: {r_cp.stderr.decode(errors='ignore')}")
    r_chk = sudo_run(["python3", "-m", "py_compile", "/etc/wifi/wifi_conf.py.tmp"])
    if r_chk.returncode != 0:
        raise RuntimeError("py_compile failed for /etc/wifi/wifi_conf.py.tmp")
    r_mv = sudo_run(["mv", "/etc/wifi/wifi_conf.py.tmp", "/etc/wifi/wifi_conf.py"])
    if r_mv.returncode != 0:
        raise RuntimeError(f"Failed replacing /etc/wifi/wifi_conf.py: {r_mv.stderr.decode(errors='ignore')}")

    cc_res = sudo_run(["raspi-config", "nonint", "do_wifi_country", country])
    if cc_res.returncode != 0:
        sudo_run(["iw", "reg", "set", country])

    restarted = False
    nm_connected = False
    nm_error = ""
    if restart_svc:
        if mode == 2 and ssid:
            # Stop AND disable Hiwonder wifi.service so its disconnect() never wipes NM profiles on reboot.
            sudo_run(["systemctl", "stop", "wifi.service"])
            sudo_run(["systemctl", "disable", "wifi.service"])
            # Tear down any active HW-* AP or existing wlan0 connection.
            r_act = subprocess.run(
                ["nmcli", "-t", "-f", "NAME,DEVICE", "con", "show", "--active"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if r_act.returncode == 0:
                for ln in r_act.stdout.splitlines():
                    if ":" not in ln:
                        continue
                    cname, dev = ln.split(":", 1)
                    if dev.strip() == "wlan0" or cname.startswith("HW-"):
                        sudo_run(["nmcli", "con", "down", cname])
                    if cname.startswith("HW-"):
                        sudo_run(["nmcli", "con", "modify", cname, "connection.autoconnect", "no"])

            # Force fresh Wi-Fi scan after AP teardown so 5GHz/STA SSIDs populate NM's cache.
            sudo_run(["nmcli", "dev", "wifi", "rescan", "ifname", "wlan0"])
            time.sleep(4.0)

            # Create or replace persistent NetworkManager STA profile cleanly (argv list, zero shell).
            sudo_run(["nmcli", "con", "delete", ssid])
            add_args = [
                "nmcli", "con", "add",
                "type", "wifi",
                "ifname", "wlan0",
                "con-name", ssid,
                "ssid", ssid,
                "autoconnect", "yes",
                "connection.autoconnect-priority", "10",
                "802-11-wireless.powersave", "2",
            ]
            if wifi_pw:
                add_args.extend(["wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", wifi_pw])
            r_add = sudo_run(add_args, timeout=25)
            if r_add.returncode != 0:
                nm_error = r_add.stderr.decode(errors="ignore").strip()
            else:
                r_up = sudo_run(["nmcli", "con", "up", ssid], timeout=35)
                if r_up.returncode != 0:
                    sudo_run(["nmcli", "dev", "wifi", "rescan", "ifname", "wlan0"])
                    time.sleep(3.0)
                    r_up = sudo_run(["nmcli", "con", "up", ssid], timeout=35)
                nm_connected = (r_up.returncode == 0)
                if not nm_connected:
                    nm_error = r_up.stderr.decode(errors="ignore").strip()
        else:
            sudo_run(["systemctl", "enable", "wifi.service"])
            r_svc = sudo_run(["systemctl", "restart", "wifi.service"])
            restarted = (r_svc.returncode == 0)

    wlan0_ip = get_wlan0_ipv4()
    print(json.dumps({
        "updated": True,
        "mode": mode,
        "ssid": ssid,
        "paths": ["/etc/wifi/wifi_conf.py", user_target],
        "country_code": country,
        "wifi_service_restarted": restarted,
        "nm_connected": nm_connected,
        "wlan0_ip": wlan0_ip,
        "nm_error": nm_error,
    }))
finally:
    try:
        os.unlink(tmp_path)
    except OSError:
        pass
"""


async def configure_wifi(
    ip: str,
    user: str,
    password: str,
    mode: int,
    ssid: str,
    wifi_password: str,
    country_code: str = "US",
    restart_service: bool = True,
) -> Dict[str, Any]:
    """Atomically update PuppyPi Wi-Fi config and connect ``wlan0`` via NetworkManager in STA mode.

    Writes both ``/etc/wifi/wifi_conf.py`` and ``~/hiwonder-toolbox/wifi_conf.py`` after
    ``py_compile`` verification, sets regulatory country code, and for STA mode (``mode == 2``)
    tears down any active ``HW-*`` AP, runs ``nmcli dev wifi rescan ifname wlan0`` + 4s settle,
    creates a persistent NetworkManager profile, brings it up, and returns the ``wlan0`` IPv4.

    Args:
        ip: Robot IPv4 address.
        user: SSH username.
        password: SSH / sudo password.
        mode: ``1`` (AP) or ``2`` (STA).
        ssid: Target Wi-Fi SSID.
        wifi_password: Target Wi-Fi passphrase.
        country_code: Two-letter ISO country code (default ``"US"``).
        restart_service: Whether to apply/activate the new Wi-Fi configuration immediately.

    Returns:
        Result dictionary confirming updated paths, country code, connection status, and ``wlan0_ip``.
    """
    validated = validate_wifi_params(
        mode=mode, ssid=ssid, wifi_password=wifi_password, country_code=country_code
    )
    rendered = render_wifi_conf_py(
        mode=validated["mode"],
        ssid=validated["ssid"],
        wifi_password=validated["wifi_password"],
    )
    return await run_remote_python(
        ip=ip,
        user=user,
        password=password,
        python_source=_WIFI_REMOTE_SCRIPT,
        payload={
            "wifi_conf_content": rendered,
            "mode": validated["mode"],
            "ssid": validated["ssid"],
            "wifi_password": validated["wifi_password"],
            "country_code": validated["country_code"],
            "sudo_password": password,
            "restart_service": bool(restart_service),
        },
        timeout=65.0,
        retries=3,
    )


_CHPASSWD_REMOTE_SCRIPT = r"""
import json, subprocess

target_user = PAYLOAD["target_user"]
new_pw = PAYLOAD["new_password"]
sudo_pw = PAYLOAD["sudo_password"]

if target_user not in ("pi", "root"):
    raise ValueError("Invalid target_user")
if any(c in new_pw for c in ("\n", "\r", ":", "\x00")):
    raise ValueError("Invalid characters in password")

# Authenticate sudo timestamp first, then pipe target_user:new_password cleanly to chpasswd stdin.
auth = subprocess.run(
    ["sudo", "-S", "-v"],
    input=(sudo_pw + "\n").encode("utf-8"),
    capture_output=True,
    timeout=15,
)
if auth.returncode != 0:
    raise RuntimeError("sudo authentication failed")

res = subprocess.run(
    ["sudo", "-n", "chpasswd"],
    input=f"{target_user}:{new_pw}\n".encode("utf-8"),
    capture_output=True,
    timeout=15,
)
if res.returncode != 0:
    raise RuntimeError(f"chpasswd failed: {res.stderr.decode(errors='ignore')}")

print(json.dumps({"updated": True, "target_user": target_user}))
"""


async def change_password(
    ip: str,
    user: str,
    password: str,
    target_user: str,
    new_password: str,
) -> Dict[str, Any]:
    """Change Linux password for ``pi`` or ``root`` on PuppyPi via ``sudo chpasswd`` over stdin.

    Args:
        ip: Robot IPv4 address.
        user: Current SSH username.
        password: Current SSH / sudo password.
        target_user: Target Linux account (strictly ``"pi"`` or ``"root"``).
        new_password: New password string (no newlines or colons).

    Returns:
        Dictionary confirming ``{"updated": True, "target_user": ...}``.
    """
    valid_user, valid_pw = validate_password_change_params(target_user, new_password)
    return await run_remote_python(
        ip=ip,
        user=user,
        password=password,
        python_source=_CHPASSWD_REMOTE_SCRIPT,
        payload={
            "target_user": valid_user,
            "new_password": valid_pw,
            "sudo_password": password,
        },
        timeout=25.0,
        retries=3,
    )


_MECHANICS_REMOTE_SCRIPT = r"""
import json, os, re, subprocess, tempfile

sudo_pw = os.environ.get("SUDO_PW", "")

def run_docker(args, timeout=15):
    try:
        r = subprocess.run(["docker"] + args, capture_output=True, text=True, timeout=timeout)
        if r.returncode == 0:
            return r
    except Exception:
        pass
    return subprocess.run(
        ["sudo", "-S", "-p", "", "docker"] + args,
        input=sudo_pw + "\n",
        capture_output=True,
        text=True,
        timeout=timeout,
    )

with_arm = PAYLOAD.get("with_arm")
x_shift = PAYLOAD.get("x_shift")
servo_devs = PAYLOAD.get("servo_deviations")
ros_version = PAYLOAD.get("ros_version")
updated = {"puppy_py_updated": False, "servo_deviation_updated": False}

if servo_devs is not None:
    s_path = "/home/pi/puppypi/servo_deviation.json"
    os.makedirs(os.path.dirname(s_path), exist_ok=True)
    existing = {}
    if os.path.exists(s_path):
        try:
            with open(s_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            existing = {}
    existing.update({str(k): int(v) for k, v in servo_devs.items()})
    tmp_s = s_path + ".tmp"
    with open(tmp_s, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2)
    os.replace(tmp_s, s_path)
    updated["servo_deviation_updated"] = True
    updated["servo_deviations"] = existing

if with_arm is not None or x_shift is not None:
    if not ros_version:
        r_ps = run_docker(["ps", "--format", "{{.Names}}"], timeout=10)
        running = set(r_ps.stdout.splitlines()) if r_ps.returncode == 0 else set()
        ros_version = "ros2" if "puppypi_ros2" in running and "puppypi" not in running else "ros1"

    container = "puppypi_ros2" if ros_version == "ros2" else "puppypi"
    candidates = (
        ["/home/ubuntu/ros2_ws/src/driver/puppy_control/puppy_control/puppy.py"]
        if ros_version == "ros2"
        else [
            "/home/ubuntu/puppypi/src/puppy_control/scripts/puppy.py",
            "/home/ubuntu/ros_ws/src/puppy_control/scripts/puppy.py",
        ]
    )
    found_path = None
    content = ""
    for p in candidates:
        r = run_docker(["exec", container, "cat", p], timeout=15)
        if r.returncode == 0 and r.stdout:
            found_path = p
            content = r.stdout
            break
    if not found_path:
        raise RuntimeError(f"Could not locate puppy.py inside {container} container")

    new_content = content
    if with_arm is not None:
        new_content = re.sub(
            r"(^\s*with_arm\s*=\s*)\d+",
            rf"\g<1>{int(with_arm)}",
            new_content,
            count=1,
            flags=re.MULTILINE,
        )
    if x_shift is not None:
        new_content = re.sub(
            r"(['\"]x_shift['\"]\s*:\s*)-?\d+(?:\.\d+)?",
            rf"\g<1>{float(x_shift)}",
            new_content,
            count=1,
        )

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as tf:
        tf.write(new_content)
        tmp_py = tf.name
    try:
        chk = subprocess.run(["python3", "-m", "py_compile", tmp_py], capture_output=True, text=True, timeout=10)
        if chk.returncode != 0:
            raise RuntimeError(f"py_compile failed: {chk.stderr}")
        cp = run_docker(["cp", tmp_py, f"{container}:{found_path}.tmp"], timeout=15)
        if cp.returncode != 0:
            raise RuntimeError(f"docker cp failed: {cp.stderr}")
        c_chk = run_docker(["exec", container, "python3", "-m", "py_compile", f"{found_path}.tmp"], timeout=15)
        if c_chk.returncode != 0:
            raise RuntimeError(f"Container py_compile failed: {c_chk.stderr}")
        mv = run_docker(["exec", container, "mv", f"{found_path}.tmp", found_path], timeout=15)
        if mv.returncode != 0:
            raise RuntimeError(f"Container mv failed: {mv.stderr}")
        updated["puppy_py_updated"] = True
        updated["puppy_py_path"] = found_path
        updated["container"] = container
        updated["ros_version"] = ros_version
    finally:
        try:
            os.unlink(tmp_py)
        except OSError:
            pass

print(json.dumps(updated))
"""


async def configure_mechanics(
    ip: str,
    user: str,
    password: str,
    with_arm: Optional[int] = None,
    x_shift: Optional[float] = None,
    servo_deviations: Optional[Dict[str, int]] = None,
    ros_version: Optional[str] = None,
) -> Dict[str, Any]:
    """Safely update ``puppy.py`` (``with_arm``/``x_shift``) in ``puppypi`` or ``puppypi_ros2`` and ``servo_deviation.json``.

    Validates ``puppy.py`` syntax with ``python3 -m py_compile`` before atomic replacement.

    Args:
        ip: Robot IPv4 address.
        user: SSH username.
        password: SSH password.
        with_arm: Optional robotic arm flag (``0`` or ``1``).
        x_shift: Optional standing X center-of-gravity shift in ``[-10.0, 10.0]``.
        servo_deviations: Optional mapping of servo IDs to trim offsets in ``[-200, 200]``.
        ros_version: Optional ``"ros1"`` or ``"ros2"`` (auto-detected on host if omitted).

    Returns:
        Dictionary detailing which configuration files were updated.
    """
    validated = validate_mechanics_params(
        with_arm=with_arm, x_shift=x_shift, servo_deviations=servo_deviations
    )
    if ros_version is not None:
        validated["ros_version"] = "ros2" if str(ros_version).lower() in ("ros2", "humble") else "ros1"
    return await run_remote_python(
        ip=ip,
        user=user,
        password=password,
        python_source=_MECHANICS_REMOTE_SCRIPT,
        payload=validated,
        timeout=35.0,
        retries=3,
        env_vars={"SUDO_PW": password},
    )


_ROS_AI_REMOTE_SCRIPT = r"""
import json, os, re, subprocess

target_ros = PAYLOAD.get("target_ros")
asr_lang = PAYLOAD.get("asr_language")
ros_domain_id = PAYLOAD.get("ros_domain_id")
rmw_impl = PAYLOAD.get("rmw_implementation")
persist_boot = bool(PAYLOAD.get("persist_boot", True))
ros2_boot_script = PAYLOAD.get("ros2_boot_script") or ""
ros2_systemd_unit = PAYLOAD.get("ros2_systemd_unit") or ""
sudo_pw = os.environ.get("SUDO_PW") or PAYLOAD.get("sudo_password") or ""
actions = []

def sudo_run(args, timeout=40, stdin_extra=None):
    data = sudo_pw + "\n"
    if stdin_extra:
        data += stdin_extra
    return subprocess.run(
        ["sudo", "-S", "-p", ""] + args,
        input=data.encode("utf-8"),
        capture_output=True,
        timeout=timeout,
    )

def run_docker(args, timeout=30, stdin_text=None):
    try:
        r = subprocess.run(["docker"] + args, input=stdin_text, capture_output=True, text=True, timeout=timeout)
        if r.returncode == 0:
            return r
    except Exception:
        pass
    inp = (sudo_pw + "\n") + (stdin_text or "")
    return subprocess.run(
        ["sudo", "-S", "-p", "", "docker"] + args,
        input=inp,
        capture_output=True,
        text=True,
        timeout=timeout,
    )

def update_env_var(container, path, key, value):
    r = run_docker(["exec", container, "cat", path], timeout=15)
    if r.returncode != 0:
        return False
    txt = r.stdout
    pat = rf"({re.escape(key)}\s*=\s*['\"]?)[^\s'\"#]+(['\"]?)"
    if re.search(pat, txt):
        new_txt = re.sub(pat, rf"\g<1>{value}\g<2>", txt)
    else:
        new_txt = txt.rstrip("\n") + f"\nexport {key}={value}\n"
    w = run_docker(
        ["exec", "-i", container, "sh", "-c", f"cat > '{path}.tmp' && mv '{path}.tmp' '{path}'"],
        timeout=15,
        stdin_text=new_txt,
    )
    return w.returncode == 0

def launch_ros2_stack(domain_id, rmw):
    dom = int(domain_id if domain_id is not None else 0)
    rmw_val = rmw or "rmw_cyclonedds_cpp"
    bringup = (
        "set +e; "
        "source /opt/ros/humble/setup.bash 2>/dev/null || true; "
        "source /home/ubuntu/ros2_ws/.robotrc 2>/dev/null || true; "
        "source /home/ubuntu/ros2_ws/.typerc 2>/dev/null || true; "
        "source /home/ubuntu/third_party_ros2/third_party_ws/install/setup.bash 2>/dev/null || true; "
        "source /home/ubuntu/ros2_ws/install/setup.bash 2>/dev/null || true; "
        f"export RMW_IMPLEMENTATION={rmw_val} ROS_LOCALHOST_ONLY=0 ROS_DOMAIN_ID={dom}; "
        "pkill -f 'ros2 launch|rosbridge_websocket|web_video_server|puppy_control|ros_robot_controller' 2>/dev/null || true; "
        "sleep 1; "
        "nohup ros2 launch ros_robot_controller ros_robot_controller.launch.py >/tmp/ros2_rrc.log 2>&1 & "
        "nohup ros2 launch puppy_control puppy_control.launch.py >/tmp/ros2_puppy.log 2>&1 & "
        "nohup ros2 launch peripherals usb_cam.launch.py >/tmp/ros2_cam.log 2>&1 & "
        "nohup ros2 launch peripherals web_video_server.launch.py >/tmp/ros2_video.log 2>&1 & "
        "nohup ros2 launch rosbridge_server rosbridge_websocket_launch.xml >/tmp/ros2_bridge.log 2>&1 & "
    )
    r = run_docker(["exec", "-d", "-u", "ubuntu", "puppypi_ros2", "bash", "-lc", bringup], timeout=20)
    if os.path.exists("/dev/ldlidar"):
        kill_lidar_cmd = (
            "pids=$(ps -eww -o pid,ppid,args | awk -v self=\"$$\" '$1 != self && $2 != self && !/awk/ && /ldlidar_stl_ros2/ {print $1}'); "
            "[ -n \"$pids\" ] && kill -9 $pids 2>/dev/null || true; sleep 0.3"
        )
        run_docker(["exec", "-u", "ubuntu", "puppypi_ros2", "bash", "-lc", kill_lidar_cmd], timeout=10)
        lidar_exec = (
            "source /opt/ros/humble/setup.bash 2>/dev/null || true; "
            "source /home/ubuntu/third_party_ros2/third_party_ws/install/setup.bash 2>/dev/null || true; "
            "source /home/ubuntu/ros2_ws/install/setup.bash 2>/dev/null || true; "
            f"export RMW_IMPLEMENTATION={rmw_val} ROS_LOCALHOST_ONLY=0 ROS_DOMAIN_ID={dom}; "
            "pids=$(ps -eww -o pid,ppid,args | awk -v self=\"$$\" '$1 != self && $2 != self && !/awk/ && /ldlidar_stl_ros2/ {print $1}'); "
            "[ -n \"$pids\" ] && kill -9 $pids 2>/dev/null || true; sleep 0.2; "
            "exec /home/ubuntu/third_party_ros2/third_party_ws/install/ldlidar_stl_ros2/lib/ldlidar_stl_ros2/ldlidar_stl_ros2_node --ros-args "
            "-p product_name:=LDLiDAR_LD19 -p topic_name:=scan -p frame_id:=lidar_frame "
            "-p port_name:=/dev/ldlidar -p port_baudrate:=230400 -p laser_scan_dir:=true "
            "-p enable_angle_crop_func:=false > /tmp/ldlidar_ros2.log 2>&1"
        )
        run_docker(["exec", "-d", "-u", "ubuntu", "puppypi_ros2", "bash", "-lc", lidar_exec], timeout=20)
    return r.returncode == 0

if target_ros == "ros1":
    sudo_run(["systemctl", "stop", "start_node_ros2.service"])
    run_docker(["stop", "puppypi_ros2"], timeout=30)
    r_start = run_docker(["start", "puppypi"], timeout=30)
    if r_start.returncode != 0:
        raise RuntimeError(f"docker start puppypi failed: {r_start.stderr}")
    if asr_lang:
        if update_env_var("puppypi", "/home/ubuntu/puppypi/.robotrc", "ASR_LANGUAGE", asr_lang):
            actions.append(f"set_asr_language:{asr_lang}:puppypi")
    if persist_boot:
        run_docker(["update", "--restart=no", "puppypi_ros2"], timeout=15)
        run_docker(["update", "--restart=always", "puppypi"], timeout=15)
        sudo_run(["systemctl", "disable", "start_node_ros2.service"])
        sudo_run(["systemctl", "enable", "start_node.service"])
        actions.append("persisted_ros1_boot_default")
    sudo_run(["systemctl", "restart", "start_node.service"])
    actions.append("switched_to_ros1_noetic")
elif target_ros == "ros2":
    sudo_run(["systemctl", "stop", "start_node.service"])
    run_docker(["stop", "puppypi"], timeout=30)
    stop_script = os.path.expanduser("~/puppypi/.stop_ros1.sh")
    if os.path.isfile(stop_script):
        subprocess.run(["bash", stop_script], capture_output=True, timeout=20)
    r_start = run_docker(["start", "puppypi_ros2"], timeout=30)
    if r_start.returncode != 0:
        raise RuntimeError(f"docker start puppypi_ros2 failed: {r_start.stderr}")
    if asr_lang:
        if update_env_var("puppypi_ros2", "/home/ubuntu/ros2_ws/.typerc", "ASR_LANGUAGE", asr_lang):
            actions.append(f"set_asr_language:{asr_lang}:puppypi_ros2")
    if ros_domain_id is not None:
        update_env_var("puppypi_ros2", "/home/ubuntu/ros2_ws/.typerc", "ROS_DOMAIN_ID", str(ros_domain_id))
        actions.append(f"set_ros_domain_id:{ros_domain_id}")
    if rmw_impl:
        update_env_var("puppypi_ros2", "/home/ubuntu/ros2_ws/.typerc", "RMW_IMPLEMENTATION", rmw_impl)
        actions.append(f"set_rmw_implementation:{rmw_impl}")
    installed_boot_unit = False
    if ros2_boot_script and ros2_systemd_unit:
        boot_script_path = os.path.expanduser("~/puppypi/start_node_ros2.sh")
        os.makedirs(os.path.dirname(boot_script_path), exist_ok=True)
        with open(boot_script_path + ".tmp", "w", encoding="utf-8") as fh:
            fh.write(ros2_boot_script)
        os.chmod(boot_script_path + ".tmp", 0o755)
        os.replace(boot_script_path + ".tmp", boot_script_path)
        tmp_unit_path = "/tmp/eigenia_start_node_ros2.service.tmp"
        with open(tmp_unit_path, "w", encoding="utf-8") as ufh:
            ufh.write(ros2_systemd_unit)
        w_unit = sudo_run(
            ["install", "-m", "0644", tmp_unit_path, "/etc/systemd/system/start_node_ros2.service"],
            timeout=15,
        )
        try:
            os.remove(tmp_unit_path)
        except OSError:
            pass
        if w_unit.returncode == 0:
            sudo_run(["systemctl", "daemon-reload"], timeout=20)
            installed_boot_unit = True
            actions.append("installed_start_node_ros2_service")
    if persist_boot and installed_boot_unit:
        run_docker(["update", "--restart=no", "puppypi"], timeout=15)
        run_docker(["update", "--restart=always", "puppypi_ros2"], timeout=15)
        sudo_run(["systemctl", "disable", "start_node.service"], timeout=20)
        sudo_run(["systemctl", "enable", "start_node_ros2.service"], timeout=20)
        actions.append("persisted_ros2_boot_default")
    if installed_boot_unit:
        r_svc = sudo_run(["systemctl", "restart", "start_node_ros2.service"], timeout=45)
        if r_svc.returncode == 0:
            actions.append("launched_ros2_bringup_stack")
        elif launch_ros2_stack(ros_domain_id, rmw_impl):
            actions.append("launched_ros2_bringup_stack")
    elif launch_ros2_stack(ros_domain_id, rmw_impl):
        actions.append("launched_ros2_bringup_stack")
    actions.append("switched_to_ros2_humble")
else:
    if asr_lang:
        if update_env_var("puppypi", "/home/ubuntu/puppypi/.robotrc", "ASR_LANGUAGE", asr_lang):
            actions.append(f"set_asr_language:{asr_lang}:puppypi")
        if update_env_var("puppypi_ros2", "/home/ubuntu/ros2_ws/.typerc", "ASR_LANGUAGE", asr_lang):
            actions.append(f"set_asr_language:{asr_lang}:puppypi_ros2")
    if ros_domain_id is not None:
        if update_env_var("puppypi_ros2", "/home/ubuntu/ros2_ws/.typerc", "ROS_DOMAIN_ID", str(ros_domain_id)):
            actions.append(f"set_ros_domain_id:{ros_domain_id}")
    if rmw_impl:
        if update_env_var("puppypi_ros2", "/home/ubuntu/ros2_ws/.typerc", "RMW_IMPLEMENTATION", rmw_impl):
            actions.append(f"set_rmw_implementation:{rmw_impl}")

active_distro = "noetic" if target_ros == "ros1" else ("humble" if target_ros == "ros2" else None)
boot_default = (target_ros if persist_boot and target_ros in ("ros1", "ros2") else None)
print(json.dumps({
    "updated": True,
    "active_ros_distro": active_distro,
    "boot_default": boot_default,
    "persist_boot": persist_boot,
    "asr_language": asr_lang,
    "ros_domain_id": ros_domain_id,
    "rmw_implementation": rmw_impl,
    "actions": actions,
}))
"""


async def configure_ros_and_ai(
    ip: str,
    user: str,
    password: str,
    target_ros: Optional[str] = None,
    asr_language: Optional[str] = None,
    ros_domain_id: int = 0,
    rmw_implementation: str = "rmw_cyclonedds_cpp",
    persist_boot: bool = True,
) -> Dict[str, Any]:
    """Switch PuppyPi between ROS 1 Noetic (``puppypi``) and ROS 2 Humble (``puppypi_ros2``), persist boot default, and update ``ASR_LANGUAGE``.

    Args:
        ip: Robot IPv4 address.
        user: SSH username.
        password: SSH / sudo password.
        target_ros: Optional ``"ros1"`` or ``"ros2"``.
        asr_language: Optional ``"English"`` or ``"Chinese"``.
        ros_domain_id: DDS domain ID for ROS 2 (default ``0``).
        rmw_implementation: ROS 2 middleware (default ``"rmw_cyclonedds_cpp"``).
        persist_boot: Whether to persist the chosen ROS distro across power-cycles via systemd
            and Docker restart policies (default ``True``).

    Returns:
        Dictionary summarizing the actions applied, ``active_ros_distro``, and ``boot_default``.
    """
    validated = validate_ros_ai_params(
        target_ros=target_ros,
        asr_language=asr_language,
        ros_domain_id=ros_domain_id,
        rmw_implementation=rmw_implementation,
        persist_boot=persist_boot,
    )
    payload = dict(validated)
    if validated.get("target_ros") == "ros2":
        payload["ros2_boot_script"] = render_ros2_boot_script(
            ros_domain_id=int(validated["ros_domain_id"] if validated["ros_domain_id"] is not None else 0),
            rmw_implementation=str(validated["rmw_implementation"] or "rmw_cyclonedds_cpp"),
        )
        payload["ros2_systemd_unit"] = render_ros2_systemd_unit()
    return await run_remote_python(
        ip=ip,
        user=user,
        password=password,
        python_source=_ROS_AI_REMOTE_SCRIPT,
        payload=payload,
        timeout=80.0,
        retries=3,
        env_vars={"SUDO_PW": password},
    )


_POWER_REMOTE_SCRIPT = r"""
import json, subprocess

action = PAYLOAD["action"]
sudo_pw = PAYLOAD["sudo_password"]

def sudo_run(args):
    return subprocess.run(
        ["sudo", "-S", "-p", ""] + args,
        input=(sudo_pw + "\n").encode("utf-8"),
        capture_output=True,
        timeout=45,
    )

if action == "restart_ros":
    chk = subprocess.run(
        ["systemctl", "is-enabled", "start_node_ros2.service"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    svc = "start_node_ros2.service" if chk.returncode == 0 and chk.stdout.strip() == "enabled" else "start_node.service"
    r = sudo_run(["systemctl", "restart", svc])
    if r.returncode != 0:
        raise RuntimeError(f"Failed restarting {svc}: {r.stderr.decode(errors='ignore')}")
elif action == "reboot":
    sudo_run(["sh", "-c", "nohup sh -c 'sleep 1 && reboot' >/dev/null 2>&1 &"])
elif action == "shutdown":
    sudo_run(["sh", "-c", "nohup sh -c 'sleep 1 && shutdown -h now' >/dev/null 2>&1 &"])
else:
    raise ValueError(f"Unsupported power action: {action}")

print(json.dumps({"executed": True, "action": action}))
"""


async def power_action(
    ip: str,
    user: str,
    password: str,
    action: str,
) -> Dict[str, Any]:
    """Execute a validated power/service control action on the PuppyPi host.

    Args:
        ip: Robot IPv4 address.
        user: SSH username.
        password: SSH / sudo password.
        action: One of ``"restart_ros"``, ``"reboot"``, or ``"shutdown"``.

    Returns:
        Confirmation dictionary ``{"executed": True, "action": action}``.

    Raises:
        ValueError: If ``action`` is not in the allow-list.
    """
    clean_action = str(action or "").strip().lower()
    if clean_action not in VALID_POWER_ACTIONS:
        raise ValueError(f"action must be one of {sorted(VALID_POWER_ACTIONS)}, got {action!r}")
    return await run_remote_python(
        ip=ip,
        user=user,
        password=password,
        python_source=_POWER_REMOTE_SCRIPT,
        payload={"action": clean_action, "sudo_password": password},
        timeout=35.0,
        retries=3,
    )


_UDEV_RULES_CONTENT = (
    "# Persistent USB serial symlinks for PuppyPi Pro (managed by Eigenia TwinScan)\n"
    "# Stage 1: Tag WonderEcho Pro internal USB hub (1a86:8091) so its child CH340 maps to /dev/wonderecho\n"
    'SUBSYSTEM=="tty", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="8091", ENV{PUPPYPI_WONDERECHO_HUB}="1"\n'
    'SUBSYSTEM=="tty", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="7523", ENV{PUPPYPI_WONDERECHO_HUB}=="1", MODE="0666", GROUP="dialout", SYMLINK+="wonderecho"\n'
    "# Stage 2: Any direct-port CP2102 or CH340 NOT behind 1a86:8091 maps to /dev/ldlidar\n"
    'SUBSYSTEM=="tty", ATTRS{idVendor}=="10c4", ATTRS{idProduct}=="ea60", MODE="0666", GROUP="dialout", SYMLINK+="ldlidar"\n'
    'SUBSYSTEM=="tty", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="7523", ENV{PUPPYPI_WONDERECHO_HUB}!="1", MODE="0666", GROUP="dialout", SYMLINK+="ldlidar"\n'
)

_INSTALL_UDEV_SCRIPT = r"""
import json, os, subprocess, tempfile

rules = PAYLOAD["rules"]
sudo_pw = os.environ.get("SUDO_PW", "")

def sudo_run(args, timeout=20):
    return subprocess.run(
        ["sudo", "-S", "-p", ""] + args,
        input=(sudo_pw + "\n").encode("utf-8"),
        capture_output=True,
        timeout=timeout,
    )

with tempfile.NamedTemporaryFile("w", suffix=".rules", delete=False, encoding="utf-8") as tf:
    tf.write(rules)
    tmp_path = tf.name

try:
    r_cp = sudo_run(["cp", tmp_path, "/etc/udev/rules.d/99-puppypi-serial.rules"])
    if r_cp.returncode != 0:
        raise RuntimeError(f"Failed writing udev rules: {r_cp.stderr.decode(errors='ignore')}")
    sudo_run(["chmod", "644", "/etc/udev/rules.d/99-puppypi-serial.rules"])
    sudo_run(["udevadm", "control", "--reload-rules"])
    sudo_run(["udevadm", "trigger"])
    we_present = os.path.exists("/dev/wonderecho")
    ld_present = os.path.exists("/dev/ldlidar")
    print(json.dumps({
        "ok": True,
        "wonderecho_present": we_present,
        "ldlidar_present": ld_present,
        "detail": f"Installed /etc/udev/rules.d/99-puppypi-serial.rules (wonderecho={we_present}, ldlidar={ld_present})",
    }))
finally:
    try:
        os.unlink(tmp_path)
    except OSError:
        pass
"""


async def install_puppypi_udev_rules(
    ip: str,
    user: str,
    password: str,
) -> Dict[str, Any]:
    """Install persistent ``/etc/udev/rules.d/99-puppypi-serial.rules`` for WonderEcho Pro and LD19 LiDAR.

    Creates ``/dev/wonderecho`` for the WonderEcho CH340 behind hub ``1a86:8091`` and
    ``/dev/ldlidar`` for direct-attached CP2102/CH340 LD19 LiDAR adapters.

    Args:
        ip: Robot IPv4 address.
        user: SSH username.
        password: SSH / sudo password.

    Returns:
        Dictionary ``{ok, wonderecho_present, ldlidar_present, detail}``.
    """
    return await run_remote_python(
        ip=ip,
        user=user,
        password=password,
        python_source=_INSTALL_UDEV_SCRIPT,
        payload={"rules": _UDEV_RULES_CONTENT},
        timeout=30.0,
        retries=3,
        env_vars={"SUDO_PW": password},
    )


_START_LIDAR_SCRIPT = r"""
import json, os, subprocess

ros_ver = str(PAYLOAD.get("ros_version") or "ros2").lower()
sudo_pw = os.environ.get("SUDO_PW", "")

def run_docker(args, timeout=20):
    try:
        r = subprocess.run(["docker"] + args, capture_output=True, text=True, timeout=timeout)
        if r.returncode == 0:
            return r
    except Exception:
        pass
    return subprocess.run(
        ["sudo", "-S", "-p", "", "docker"] + args,
        input=sudo_pw + "\n",
        capture_output=True,
        text=True,
        timeout=timeout,
    )

if not os.path.exists("/dev/ldlidar"):
    print(json.dumps({
        "ok": False,
        "device_present": False,
        "ros_version": ros_ver,
        "detail": "LD19 LiDAR not detected on USB (/dev/ldlidar absent). Re-seat the LiDAR USB data cable and check battery charge.",
    }))
    raise SystemExit(0)

if ros_ver == "ros2":
    kill_lidar_cmd = (
        "pids=$(ps -eww -o pid,ppid,args | awk -v self=\"$$\" '$1 != self && $2 != self && !/awk/ && /ldlidar_stl_ros2/ {print $1}'); "
        "[ -n \"$pids\" ] && kill -9 $pids 2>/dev/null || true; sleep 0.3"
    )
    run_docker(["exec", "-u", "ubuntu", "puppypi_ros2", "bash", "-lc", kill_lidar_cmd], timeout=10)
    cmd = (
        "source /opt/ros/humble/setup.bash 2>/dev/null || true; "
        "source /home/ubuntu/third_party_ros2/third_party_ws/install/setup.bash 2>/dev/null || true; "
        "source /home/ubuntu/ros2_ws/install/setup.bash 2>/dev/null || true; "
        "export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp ROS_LOCALHOST_ONLY=0 ROS_DOMAIN_ID=0; "
        "pids=$(ps -eww -o pid,ppid,args | awk -v self=\"$$\" '$1 != self && $2 != self && !/awk/ && /ldlidar_stl_ros2/ {print $1}'); "
        "[ -n \"$pids\" ] && kill -9 $pids 2>/dev/null || true; sleep 0.2; "
        "exec /home/ubuntu/third_party_ros2/third_party_ws/install/ldlidar_stl_ros2/lib/ldlidar_stl_ros2/ldlidar_stl_ros2_node --ros-args "
        "-p product_name:=LDLiDAR_LD19 -p topic_name:=scan -p frame_id:=lidar_frame "
        "-p port_name:=/dev/ldlidar -p port_baudrate:=230400 -p laser_scan_dir:=true "
        "-p enable_angle_crop_func:=false > /tmp/ldlidar_ros2.log 2>&1"
    )
    r = run_docker(["exec", "-d", "-u", "ubuntu", "puppypi_ros2", "bash", "-lc", cmd], timeout=20)
else:
    cmd = (
        "source /opt/ros/noetic/setup.bash 2>/dev/null || true; "
        "source /home/ubuntu/puppypi/devel/setup.bash 2>/dev/null || true; "
        "nohup roslaunch ldlidar LD19.launch port_name:=/dev/ldlidar >/tmp/ros1_lidar.log 2>&1 &"
    )
    r = run_docker(["exec", "-d", "puppypi", "bash", "-lc", cmd], timeout=20)

if r.returncode != 0:
    print(json.dumps({
        "ok": False,
        "device_present": True,
        "ros_version": ros_ver,
        "detail": f"Failed launching LiDAR node in container: {r.stderr.strip()}",
    }))
else:
    print(json.dumps({
        "ok": True,
        "device_present": True,
        "ros_version": ros_ver,
        "detail": f"Started LD19 LiDAR node on /dev/ldlidar ({ros_ver.upper()}, publishing /scan).",
    }))
"""


async def start_robot_lidar_node(
    ip: str,
    user: str,
    password: str,
    ros_version: str = "ros2",
) -> Dict[str, Any]:
    """Probe ``/dev/ldlidar`` and launch the verified ROS 2/1 LD19 LiDAR node publishing ``/scan``.

    Args:
        ip: Robot IPv4 address.
        user: SSH username.
        password: SSH / sudo password.
        ros_version: Active ROS mode (``"ros2"`` or ``"ros1"``).

    Returns:
        Dictionary ``{ok, device_present, ros_version, detail}``.
    """
    return await run_remote_python(
        ip=ip,
        user=user,
        password=password,
        python_source=_START_LIDAR_SCRIPT,
        payload={"ros_version": "ros2" if str(ros_version).lower() in ("ros2", "humble") else "ros1"},
        timeout=25.0,
        retries=2,
        env_vars={"SUDO_PW": password},
    )


_CLEAN_STALE_LOGS_SCRIPT = r"""
import glob, json, os, subprocess, time

sudo_pw = os.environ.get("SUDO_PW", "")
now = time.time()
cutoff = now - 86400.0  # Strictly older than 24 hours (-mtime +0)
files_removed = 0
bytes_reclaimed = 0


def run_docker(args, timeout=15):
    r = subprocess.run(["docker"] + args, capture_output=True, text=True, timeout=timeout)
    if r.returncode == 0 or not sudo_pw:
        return r
    return subprocess.run(
        ["sudo", "-S", "-p", "", "docker"] + args,
        input=sudo_pw + "\n",
        capture_output=True,
        text=True,
        timeout=timeout,
    )


# 1. Clean ONLY stale *.log files (>24h) inside running ROS containers under /home/ubuntu/.ros/log and /tmp/*lidar*.log
container_cleaner = (
    "python3 -c \""
    "import glob, json, os, time; "
    "cut = time.time() - 86400.0; rem = 0; freed = 0; "
    "roots = ['/home/ubuntu/.ros/log']; "
    "for root in roots: "
    "  if os.path.isdir(root): "
    "    for dp, _, fns in os.walk(root): "
    "      for fn in fns: "
    "        if not fn.endswith('.log'): continue; "
    "        fp = os.path.join(dp, fn); "
    "        try: "
    "          st = os.stat(fp); "
    "          if st.st_mtime < cut: "
    "            os.remove(fp); rem += 1; freed += st.st_size; "
    "        except OSError: pass; "
    "for fp in glob.glob('/tmp/*lidar*.log'): "
    "  try: "
    "    st = os.stat(fp); "
    "    if st.st_mtime < cut: "
    "      os.remove(fp); rem += 1; freed += st.st_size; "
    "  except OSError: pass; "
    "print(json.dumps({'rem': rem, 'freed': freed}))"
    "\""
)

for cname in ("puppypi_ros2", "puppypi"):
    chk = run_docker(["inspect", "-f", "{{.State.Running}}", cname], timeout=8)
    if chk.returncode == 0 and chk.stdout.strip().lower() == "true":
        res = run_docker(["exec", cname, "bash", "-lc", container_cleaner], timeout=12)
        if res.returncode == 0 and res.stdout.strip():
            try:
                line = res.stdout.strip().splitlines()[-1]
                data = json.loads(line)
                files_removed += int(data.get("rem", 0))
                bytes_reclaimed += int(data.get("freed", 0))
            except Exception:
                pass

# 2. Clean host /tmp/*lidar*.log older than 24h (never code or config!)
for fp in glob.glob("/tmp/*lidar*.log"):
    try:
        st = os.stat(fp)
        if st.st_mtime < cutoff:
            os.remove(fp)
            files_removed += 1
            bytes_reclaimed += int(st.st_size)
    except OSError:
        pass

disk_use_pct = "unknown"
try:
    df = subprocess.run(["df", "-h", "/"], capture_output=True, text=True, timeout=5)
    lines = [ln.strip() for ln in df.stdout.splitlines() if ln.strip()]
    if len(lines) >= 2:
        parts = lines[1].split()
        if len(parts) >= 5:
            disk_use_pct = parts[4]
except Exception:
    pass

reclaimed_mb = round(bytes_reclaimed / (1024.0 * 1024.0), 2)
print(json.dumps({
    "ok": True,
    "files_removed": files_removed,
    "reclaimed_mb": reclaimed_mb,
    "disk_use_pct": disk_use_pct,
    "detail": f"Removed {files_removed} stale ROS/LiDAR log(s) (>24h), reclaimed {reclaimed_mb:.2f} MB (disk {disk_use_pct}).",
}))
"""


async def clean_robot_stale_logs(
    ip: str,
    user: str,
    password: str,
    timeout: float = 15.0,
) -> Dict[str, Any]:
    """Safely prune rotated ``*.log`` files older than 24h under ``~/.ros/log`` and ``/tmp/*lidar*.log``.

    Never modifies or deletes any code, packages, or configuration files.

    Args:
        ip: Robot IPv4 address.
        user: SSH username.
        password: SSH / sudo password.
        timeout: SSH command timeout in seconds (default ``15.0``).

    Returns:
        Dictionary ``{ok, files_removed, reclaimed_mb, disk_use_pct, detail}``.
    """
    return await run_remote_python(
        ip=ip,
        user=user,
        password=password,
        python_source=_CLEAN_STALE_LOGS_SCRIPT,
        payload={},
        timeout=timeout,
        retries=2,
        env_vars={"SUDO_PW": password},
    )
