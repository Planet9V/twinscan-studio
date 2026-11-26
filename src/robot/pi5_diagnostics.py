"""Live Raspberry Pi 5 PMIC power, USB budget, and 22-component 3D Hardware Twin diagnostics.

Collects read-only telemetry over SSH (using ``src.robot.ssh_manager.run_remote_python``
with 3x retry and ``sys.stderr`` error logging) and exposes pure, unit-testable parsers
for DA9091 PMIC ADC rails, ``vcgencmd get_throttled`` bitmasks, physical USB-A port
power/flap accounting, LD19 LiDAR USB-UART converter detection, and all 22 canonical
3D BOM component states.
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from src.robot.ssh_manager import SSHAuthError, SSHCommandError, run_remote_python

CANONICAL_PI5_COMPONENT_IDS: Tuple[str, ...] = (
    "bcm2712_soc",
    "ram_lpddr4x",
    "rp1_southbridge",
    "da9091_pmic",
    "wifi_bt_module",
    "usbc_pwr",
    "micro_hdmi_0",
    "micro_hdmi_1",
    "pcie_ffc",
    "csi_dsi_0",
    "csi_dsi_1",
    "gpio_40pin",
    "microsd_slot",
    "eth_rj45",
    "usb2_port_1_1",
    "usb2_port_1_2",
    "usb3_port_3_1",
    "usb3_port_3_2",
    "rrc_hat_stm32",
    "ld19_lidar_module",
    "camera_icspring",
    "wonderecho_pro",
)

THROTTLED_FLAG_BITS: Tuple[Tuple[int, str], ...] = (
    (0x1, "under_voltage_now"),
    (0x2, "arm_freq_capped_now"),
    (0x4, "throttled_now"),
    (0x8, "soft_temp_limit_now"),
    (0x10000, "under_voltage_occurred"),
    (0x20000, "arm_freq_capped_occurred"),
    (0x40000, "throttled_occurred"),
    (0x80000, "soft_temp_limit_occurred"),
)

USB_PORT_SPECS: Tuple[Tuple[str, str, str], ...] = (
    ("1-1", "USB 2.0 Top", "usb2_port_1_1"),
    ("1-2", "USB 2.0 Bottom", "usb2_port_1_2"),
    ("3-1", "USB 3.0 Top", "usb3_port_3_1"),
    ("3-2", "USB 3.0 Bottom", "usb3_port_3_2"),
)

_PMIC_LINE_RE = re.compile(
    r"^\s*([A-Za-z0-9_]+)\s+(volt|current)\(\d+\)=([0-9.eE+-]+)\s*[VA]?\s*$"
)

_PI5_DIAG_REMOTE_SCRIPT = r"""
import glob, json, os, struct, subprocess

sudo_pw = os.environ.get("SUDO_PW", "")

def run(cmd, timeout=6):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (r.stdout or "").strip()
    except Exception:
        return ""

def run_docker(args, timeout=8):
    try:
        r = subprocess.run(["docker"] + args, capture_output=True, text=True, timeout=timeout)
        if r.returncode == 0:
            return (r.stdout or "").strip()
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
            if r.returncode == 0:
                return (r.stdout or "").strip()
        except Exception:
            pass
    return ""

sections = {}
sections["pmic"] = run(["vcgencmd", "pmic_read_adc"])
sections["throttled"] = run(["vcgencmd", "get_throttled"])
sections["temp"] = run(["vcgencmd", "measure_temp"])
sections["arm_freq"] = run(["vcgencmd", "measure_clock", "arm"])

chosen_lines = []
for f in sorted(glob.glob("/proc/device-tree/chosen/power/*")):
    name = os.path.basename(f)
    try:
        raw = open(f, "rb").read()
        if len(raw) == 4:
            val = struct.unpack(">I", raw)[0]
            chosen_lines.append(f"{name}={val}")
        else:
            txt = raw.replace(b"\x00", b"").decode("utf-8", errors="ignore").strip()
            if txt and name == "name":
                chosen_lines.append(f"{name}={txt}")
    except Exception:
        pass
sections["chosen_power"] = "\n".join(chosen_lines)

usb_lines = []
for d in sorted(glob.glob("/sys/bus/usb/devices/*")):
    if not os.path.isfile(os.path.join(d, "idVendor")):
        continue
    def rd(fn):
        try:
            return open(os.path.join(d, fn), "r", encoding="utf-8", errors="ignore").read().strip()
        except Exception:
            return ""
    name = os.path.basename(d)
    vid = rd("idVendor")
    pid = rd("idProduct")
    if vid == "1d6b":
        continue
    spd = rd("speed")
    maxp = rd("bMaxPower")
    prod = rd("product")
    mfg = rd("manufacturer")
    drv = ""
    for ifdir in sorted(glob.glob(os.path.join(d, f"{name}:*"))):
        drv_link = os.path.join(ifdir, "driver")
        if os.path.islink(drv_link):
            drv = os.path.basename(os.readlink(drv_link))
            break
    usb_lines.append(f"{name}|{vid}:{pid}|{spd}|{maxp}|{drv}|{mfg}|{prod}")
sections["usb_devices"] = "\n".join(usb_lines)

dmesg_out = run(["dmesg"], timeout=6)
if not dmesg_out:
    dmesg_out = run(["journalctl", "-k", "-b", "0", "--no-pager", "-n", "400"], timeout=6)
dmesg_usb = []
for ln in dmesg_out.splitlines():
    low = ln.lower()
    if "cannot submit urb" in low:
        continue
    if any(k in low for k in ("usb ", "disconnect", "over-current", "under-voltage", "ch341", "cp210", "ttyusb", "unable to enumerate")):
        dmesg_usb.append(ln)
sections["dmesg_usb"] = "\n".join(dmesg_usb[-120:])

try:
    sections["model"] = open("/proc/device-tree/model", "rb").read().replace(b"\x00", b"").decode("utf-8", errors="ignore").strip()
except Exception:
    sections["model"] = ""

sections["cpu"] = run(["lscpu"])
sections["mem"] = run(["free", "-m"])
sections["disk"] = run(["df", "-BG", "/"])
sections["uptime"] = run(["uptime"])
sections["pcie"] = run(["lspci"])

serial_lines = []
for pattern in ("/dev/ttyUSB*", "/dev/ttyACM*", "/dev/ttyAMA*", "/dev/rrc", "/dev/ldlidar", "/dev/wonderecho"):
    for p in sorted(glob.glob(pattern)):
        if os.path.islink(p):
            serial_lines.append(f"{p} -> {os.readlink(p)}")
        else:
            serial_lines.append(p)
sections["serial"] = "\n".join(serial_lines)
sections["i2c"] = "\n".join(sorted(glob.glob("/dev/i2c-*")))
sections["spi"] = "\n".join(sorted(glob.glob("/dev/spidev*")))
sections["video"] = run(["v4l2-ctl", "--list-devices"]) or "\n".join(sorted(glob.glob("/dev/video*")))
sections["audio"] = "\n".join(filter(None, [run(["aplay", "-l"]), run(["arecord", "-l"])]))
sections["pinctrl"] = run(["pinctrl", "get", "0-27"])
sections["network"] = run(["ip", "-br", "a"])
sections["docker"] = run_docker(["ps", "-a", "--format", "{{.Names}}\t{{.Status}}"])

print(json.dumps({"ok": True, "sections": sections}))
"""


def parse_pmic_adc_output(
    raw: str,
) -> Tuple[List[Dict[str, Any]], Optional[float], Optional[float]]:
    """Parse ``vcgencmd pmic_read_adc`` output into rails, EXT5V voltage, and total Watts.

    Pairs matching ``<RAIL>_V`` and ``<RAIL>_A`` channels to compute per-rail power
    (``volts * amps``) and summed board PMIC power following the standard Raspberry Pi 5
    DA9091 ADC formula.

    Args:
        raw: Raw stdout string from ``vcgencmd pmic_read_adc``.

    Returns:
        Tuple ``(pmic_rails, ext5v_volts, total_pmic_watts)`` where each rail dict has
        ``{"name", "volts", "amps", "watts"}``.
    """
    rail_order: List[str] = []
    rail_map: Dict[str, Dict[str, Optional[float]]] = {}

    for line in (raw or "").splitlines():
        m = _PMIC_LINE_RE.match(line)
        if not m:
            continue
        channel_name, kind, val_str = m.group(1), m.group(2), m.group(3)
        try:
            value = float(val_str)
        except ValueError:
            continue

        base_name = channel_name
        if kind == "volt" and base_name.endswith("_V"):
            base_name = base_name[:-2]
        elif kind == "current" and base_name.endswith("_A"):
            base_name = base_name[:-2]

        if base_name not in rail_map:
            rail_order.append(base_name)
            rail_map[base_name] = {"volts": None, "amps": None}

        if kind == "volt":
            rail_map[base_name]["volts"] = round(value, 4)
        else:
            rail_map[base_name]["amps"] = round(value, 4)

    rails: List[Dict[str, Any]] = []
    total_w = 0.0
    has_power = False
    for name in rail_order:
        volts = rail_map[name]["volts"]
        amps = rail_map[name]["amps"]
        watts: Optional[float] = None
        if volts is not None and amps is not None:
            watts = round(volts * amps, 4)
            total_w += volts * amps
            has_power = True
        rails.append({"name": name, "volts": volts, "amps": amps, "watts": watts})

    ext5v_volts: Optional[float] = None
    if "EXT5V" in rail_map and rail_map["EXT5V"]["volts"] is not None:
        ext5v_volts = rail_map["EXT5V"]["volts"]

    total_pmic_watts = round(total_w, 3) if has_power else None
    return rails, ext5v_volts, total_pmic_watts


def decode_throttled_mask(hex_str: str) -> List[str]:
    """Decode Raspberry Pi ``vcgencmd get_throttled`` bitmask into human-readable flags.

    Args:
        hex_str: Raw string such as ``"throttled=0x0"`` or ``"0x50005"``.

    Returns:
        Ordered list of active throttle/voltage flag strings (empty list when ``0x0``).
    """
    m = re.search(r"0x([0-9a-fA-F]+)", str(hex_str or ""))
    if m:
        mask = int(m.group(1), 16)
    else:
        cleaned = str(hex_str or "").strip()
        if not cleaned:
            return []
        try:
            mask = int(cleaned, 16)
        except ValueError:
            return []
    return [label for bit, label in THROTTLED_FLAG_BITS if (mask & bit) != 0]


def _extract_throttled_hex(raw: str) -> str:
    m = re.search(r"0x[0-9a-fA-F]+", str(raw or ""))
    return m.group(0).lower() if m else "0x0"


def _parse_temp_c(raw: str) -> Optional[float]:
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*'?C", str(raw or ""), re.IGNORECASE)
    if m:
        return round(float(m.group(1)), 1)
    m2 = re.search(r"([0-9]+(?:\.[0-9]+)?)", str(raw or ""))
    return round(float(m2.group(1)), 1) if m2 else None


def _parse_arm_freq_mhz(raw: str) -> Optional[float]:
    m = re.search(r"=\s*([0-9]+)", str(raw or ""))
    if not m:
        return None
    hz = int(m.group(1))
    return round(hz / 1_000_000.0, 1)


def _parse_uptime_and_load(raw: str) -> Tuple[str, List[float]]:
    text = str(raw or "").strip()
    loads: List[float] = []
    m_load = re.search(
        r"load average:\s*([0-9.]+)[,\s]+([0-9.]+)[,\s]+([0-9.]+)",
        text,
        re.IGNORECASE,
    )
    if m_load:
        loads = [round(float(m_load.group(i)), 2) for i in (1, 2, 3)]
    m_up = re.search(r"up\s+([^,]+(?:,\s*[^,]+)?),\s+\d+\s+user", text)
    uptime_txt = m_up.group(1).strip() if m_up else text
    return uptime_txt, loads


def _parse_cpu_model(raw: str) -> str:
    for line in str(raw or "").splitlines():
        if line.lower().startswith("model name:"):
            return line.split(":", 1)[1].strip()
    return "Cortex-A76"


def _parse_mem_mb(raw: str) -> Tuple[Optional[float], Optional[float]]:
    for line in str(raw or "").splitlines():
        if line.lower().startswith("mem:"):
            parts = line.split()
            if len(parts) >= 3:
                try:
                    total = float(parts[1].rstrip("MiGi"))
                    used = float(parts[2].rstrip("MiGi"))
                    return round(used, 1), round(total, 1)
                except ValueError:
                    pass
    return None, None


def _parse_disk_gb(raw: str) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    for line in str(raw or "").splitlines():
        parts = line.split()
        if len(parts) >= 6 and (parts[-1] == "/" or parts[0].startswith("/dev/")):
            try:
                total = float(re.sub(r"[^0-9.]", "", parts[1]))
                used = float(re.sub(r"[^0-9.]", "", parts[2]))
                pct = float(re.sub(r"[^0-9.]", "", parts[4]))
                return round(used, 2), round(total, 2), round(pct, 1)
            except ValueError:
                continue
    return None, None, None


def _parse_chosen_power(raw: str) -> Tuple[bool, int, bool]:
    kv: Dict[str, str] = {}
    for line in str(raw or "").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            kv[k.strip()] = v.strip()
    usb_max_en = kv.get("usb_max_current_enable", "0").split()[0] == "1"
    over_cur = kv.get("usb_over_current_detected", "0").split()[0] == "1"
    budget_ma = 1600 if usb_max_en else 600
    return usb_max_en, budget_ma, over_cur


def _parse_usb_devices(raw: str) -> List[Dict[str, Any]]:
    devices: List[Dict[str, Any]] = []
    for line in str(raw or "").splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 4:
            continue
        path = parts[0]
        vid_pid = parts[1].lower()
        speed_raw = parts[2]
        maxp_raw = parts[3]
        driver = parts[4] if len(parts) > 4 else ""
        mfg = parts[5] if len(parts) > 5 else ""
        prod = parts[6] if len(parts) > 6 else ""

        try:
            speed_mbps: Optional[float] = float(re.sub(r"[^0-9.]", "", speed_raw)) if speed_raw else None
        except ValueError:
            speed_mbps = None
        m_ma = re.search(r"(\d+)", maxp_raw)
        max_power_ma = int(m_ma.group(1)) if m_ma else 0

        root_port = path.split(".", 1)[0]
        # Map USB 3.0 companion root buses (2-1 -> 1-1, 4-1 -> 3-1) onto their physical USB-A receptacle
        if root_port == "2-1":
            root_port = "1-1"
        elif root_port == "4-1":
            root_port = "3-1"

        devices.append(
            {
                "path": path,
                "root_port": root_port,
                "vid_pid": vid_pid,
                "speed_mbps": speed_mbps,
                "max_power_ma": max_power_ma,
                "driver": driver or None,
                "manufacturer": mfg or None,
                "product": prod or None,
            }
        )
    return devices


def _count_port_flaps(dmesg_usb: str) -> Dict[str, int]:
    flaps: Dict[str, int] = {port: 0 for port, _, _ in USB_PORT_SPECS}
    for line in str(dmesg_usb or "").splitlines():
        m = re.search(r"usb\s+(\d+-\d+)(?:\.\d+)?:\s+USB disconnect", line, re.IGNORECASE)
        if not m:
            continue
        root = m.group(1)
        if root == "2-1":
            root = "1-1"
        elif root == "4-1":
            root = "3-1"
        if root in flaps:
            # Count root-level disconnects (avoid double-counting child hub disconnects on same event)
            if re.search(rf"usb\s+{re.escape(m.group(1))}:\s+USB disconnect", line, re.IGNORECASE):
                flaps[root] += 1
    return flaps


def _parse_serial_section(raw: str) -> Tuple[List[str], Dict[str, str]]:
    uarts: List[str] = []
    symlinks: Dict[str, str] = {}
    for line in str(raw or "").splitlines():
        s = line.strip()
        if not s:
            continue
        uarts.append(s)
        if "->" in s:
            left, right = [x.strip() for x in s.split("->", 1)]
            symlinks[left] = right
    return uarts, symlinks


def _parse_audio_cards(raw: str) -> List[str]:
    cards: List[str] = []
    seen = set()
    for line in str(raw or "").splitlines():
        m = re.match(r"^card\s+(\d+):\s+([^\[]+\[[^\]]+\])", line.strip())
        if m:
            label = f"card {m.group(1)}: {m.group(2).strip()}"
            if label not in seen:
                seen.add(label)
                cards.append(label)
    return cards


def _parse_video_devices(raw: str) -> List[str]:
    out: List[str] = []
    for line in str(raw or "").splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("/dev/video") or s.endswith(":"):
            out.append(s)
    return out[:24]


def _parse_pinctrl_active(raw: str) -> List[str]:
    active: List[str] = []
    for line in str(raw or "").splitlines():
        s = line.strip()
        if not s:
            continue
        if any(tag in s for tag in ("a0", "a1", "a2", "a3", "a4", "a5", "op ", "UART", "I2C", "SPI")):
            active.append(s)
    return active[:20]


def _parse_network_interfaces(raw: str) -> Tuple[List[str], Dict[str, Dict[str, str]]]:
    lines: List[str] = []
    by_name: Dict[str, Dict[str, str]] = {}
    for line in str(raw or "").splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        iface = parts[0]
        state = parts[1].upper()
        addrs = " ".join(parts[2:]) if len(parts) > 2 else ""
        lines.append(f"{iface} {state} {addrs}".strip())
        by_name[iface] = {"state": state, "addrs": addrs}
    return lines, by_name


def _parse_docker_containers(raw: str) -> List[str]:
    out: List[str] = []
    for line in str(raw or "").splitlines():
        s = line.strip()
        if not s:
            continue
        out.append(s.replace("\t", ": "))
    return out


def build_pi5_diagnostics_payload(
    robot: Dict[str, Any],
    raw_sections: Dict[str, str],
) -> Dict[str, Any]:
    """Assemble the complete ``Pi5HardwareDiagnostics`` payload from raw Pi 5 telemetry sections.

    Args:
        robot: Stored robot record dict (must include ``id``, ``name``, ``ip_address``).
        raw_sections: Dictionary of command outputs keyed by section name
            (``pmic``, ``throttled``, ``temp``, ``arm_freq``, ``chosen_power``,
            ``usb_devices``, ``dmesg_usb``, ``model``, ``cpu``, ``mem``, ``disk``,
            ``uptime``, ``pcie``, ``serial``, ``i2c``, ``spi``, ``video``, ``audio``,
            ``pinctrl``, ``network``, ``docker``).

    Returns:
        Dictionary conforming strictly to the ``Pi5HardwareDiagnostics`` TypeScript contract
        with all 22 canonical 3D BOM component states.
    """
    sec = raw_sections or {}
    pmic_rails, ext5v_volts, total_pmic_watts = parse_pmic_adc_output(sec.get("pmic", ""))
    throttled_hex = _extract_throttled_hex(sec.get("throttled", "0x0"))
    throttled_flags = decode_throttled_mask(throttled_hex)
    cpu_temp_c = _parse_temp_c(sec.get("temp", ""))
    arm_freq_mhz = _parse_arm_freq_mhz(sec.get("arm_freq", ""))
    uptime_text, load_avg = _parse_uptime_and_load(sec.get("uptime", ""))
    board_model = (sec.get("model") or robot.get("model") or "Raspberry Pi 5 Model B Rev 1.1").strip()
    cpu_model = _parse_cpu_model(sec.get("cpu", ""))
    ram_used_mb, ram_total_mb = _parse_mem_mb(sec.get("mem", ""))
    disk_used_gb, disk_total_gb, disk_used_pct = _parse_disk_gb(sec.get("disk", ""))
    usb_max_en, usb_budget_ma, usb_over_cur = _parse_chosen_power(sec.get("chosen_power", ""))

    usb_entries = _parse_usb_devices(sec.get("usb_devices", ""))
    flap_counts = _count_port_flaps(sec.get("dmesg_usb", ""))
    uarts, serial_symlinks = _parse_serial_section(sec.get("serial", ""))
    audio_cards = _parse_audio_cards(sec.get("audio", ""))
    video_devices = _parse_video_devices(sec.get("video", ""))
    i2c_buses = [ln.strip() for ln in str(sec.get("i2c", "")).splitlines() if ln.strip()]
    spi_devices = [ln.strip() for ln in str(sec.get("spi", "")).splitlines() if ln.strip()]
    pcie_lines = [ln.strip() for ln in str(sec.get("pcie", "")).splitlines() if ln.strip()]
    pinctrl_active = _parse_pinctrl_active(sec.get("pinctrl", ""))
    network_lines, net_by_name = _parse_network_interfaces(sec.get("network", ""))
    docker_containers = _parse_docker_containers(sec.get("docker", ""))

    # Identify WonderEcho hub port(s) so child CH340 isn't misclassified as LD19
    wonderecho_hub_ports = {d["root_port"] for d in usb_entries if d["vid_pid"] == "1a86:8091"}
    wonderecho_audio = next((d for d in usb_entries if d["vid_pid"] == "0c76:161f"), None)
    wonderecho_ch340 = next(
        (d for d in usb_entries if d["vid_pid"] == "1a86:7523" and d["root_port"] in wonderecho_hub_ports),
        None,
    )
    camera_dev = next((d for d in usb_entries if d["vid_pid"] == "32e6:9005"), None)
    ld19_usb_dev = next(
        (
            d
            for d in usb_entries
            if d["vid_pid"] == "10c4:ea60"
            or d["vid_pid"].startswith("0403:")
            or (d["vid_pid"] == "1a86:7523" and d["root_port"] not in wonderecho_hub_ports)
        ),
        None,
    )

    # Build 4 physical Pi 5 USB-A port records
    usb_ports: List[Dict[str, Any]] = []
    usb_total_draw_ma = 0
    port_by_path: Dict[str, Dict[str, Any]] = {}

    for port_path, bus_label, _comp_id in USB_PORT_SPECS:
        attached = [d for d in usb_entries if d["root_port"] == port_path]
        port_ma = sum(d["max_power_ma"] for d in attached)
        usb_total_draw_ma += port_ma
        flaps = flap_counts.get(port_path, 0)

        if not attached:
            port_info: Dict[str, Any] = {
                "port_path": port_path,
                "bus_label": bus_label,
                "speed_mbps": None,
                "max_power_ma": 0,
                "vid_pid": None,
                "product": None,
                "driver": None,
                "device_nodes": [],
                "flap_count": flaps,
                "status": "empty",
            }
        else:
            primary = attached[0]
            # Prefer a named leaf product over generic "USB HUB" when hub is attached
            if port_path in wonderecho_hub_ports:
                product_label = "WonderEcho Pro (1a86:8091 Hub + CH340 + USB Audio)"
                vid_pid_label = "1a86:8091"
            else:
                names = [d["product"] for d in attached if d["product"]]
                product_label = " + ".join(names) if names else primary["vid_pid"]
                vid_pid_label = primary["vid_pid"]

            drivers = sorted({d["driver"] for d in attached if d["driver"]})
            nodes: List[str] = []
            if camera_dev and camera_dev["root_port"] == port_path:
                nodes.extend([v for v in video_devices if v in ("/dev/video0", "/dev/video1")] or ["/dev/video0"])
            if port_path in wonderecho_hub_ports:
                if "/dev/wonderecho" in serial_symlinks:
                    nodes.append(f"/dev/wonderecho -> {serial_symlinks['/dev/wonderecho']}")
                for ac in audio_cards:
                    if "usb" in ac.lower():
                        nodes.append(ac)
            if ld19_usb_dev and ld19_usb_dev["root_port"] == port_path:
                if "/dev/ldlidar" in serial_symlinks:
                    nodes.append(f"/dev/ldlidar -> {serial_symlinks['/dev/ldlidar']}")
                else:
                    nodes.append("/dev/ttyUSB*")

            if usb_over_cur:
                p_status = "fault"
            elif flaps >= 2:
                p_status = "warning"
            else:
                p_status = "ok"

            port_info = {
                "port_path": port_path,
                "bus_label": bus_label,
                "speed_mbps": primary["speed_mbps"],
                "max_power_ma": port_ma,
                "vid_pid": vid_pid_label,
                "product": product_label,
                "driver": ", ".join(drivers) if drivers else None,
                "device_nodes": nodes,
                "flap_count": flaps,
                "status": p_status,
            }
        usb_ports.append(port_info)
        port_by_path[port_path] = port_info

    # LD19 LiDAR verdict
    ld19_symlink = "/dev/ldlidar" if "/dev/ldlidar" in serial_symlinks else None
    ld19_detected = bool(ld19_symlink or ld19_usb_dev is not None)
    ld19_device_path = (
        f"/dev/ldlidar -> {serial_symlinks['/dev/ldlidar']}"
        if ld19_symlink
        else (f"USB {ld19_usb_dev['path']} ({ld19_usb_dev['vid_pid']})" if ld19_usb_dev else None)
    )
    headroom_ma = max(0, usb_budget_ma - usb_total_draw_ma)
    if ld19_detected:
        ld19_verdict = {
            "detected": True,
            "device_path": ld19_device_path,
            "summary": f"LD19 LiDAR USB-to-UART converter detected ({ld19_device_path}); ready for 230400-baud ROS 2 /scan.",
            "likely_causes": [],
        }
    else:
        ld19_verdict = {
            "detected": False,
            "device_path": None,
            "summary": (
                f"No LD19 USB-to-UART converter (CP2102 10c4:ea60 / CH340) enumerated on any Pi 5 USB-A port. "
                f"Pi 5 USB power is healthy ({usb_total_draw_ma}/{usb_budget_ma} mA, {headroom_ma} mA headroom, "
                f"EXT5V={ext5v_volts if ext5v_volts is not None else 'n/a'}V), so a spinning LiDAR is receiving 5V power only without USB D+/D- data."
            ),
            "likely_causes": [
                "Charge-only (2-wire power-only, missing D+/D-) USB cable between the LD19 converter PCB and Pi 5",
                "Plugged into a 5V power-only port on the PuppyPi expansion board instead of a Raspberry Pi 5 USB-A port",
                "Faulty or unseated CP2102/CH340 USB-to-UART converter PCB or loose USB connector",
            ],
        }

    # Lookup helpers for PMIC rails
    rail_lookup = {r["name"]: r for r in pmic_rails}
    vdd_core = rail_lookup.get("VDD_CORE", {})
    sys_3v3 = rail_lookup.get("3V3_SYS", {})
    sys_1v8 = rail_lookup.get("1V8_SYS", {})
    ddr_vdd2 = rail_lookup.get("DDR_VDD2", {})
    wl_3v7 = rail_lookup.get("3V7_WL_SW", {})
    hdmi_rail = rail_lookup.get("HDMI", {})

    # Compute component statuses
    soc_status = "ok"
    soc_trouble: Optional[str] = None
    if any(f in throttled_flags for f in ("throttled_now", "soft_temp_limit_now")) or (
        cpu_temp_c is not None and cpu_temp_c >= 80.0
    ):
        soc_status = "fault"
        soc_trouble = "CPU thermal throttling active; verify heatsink/fan airflow and reduce load."
    elif (cpu_temp_c is not None and cpu_temp_c >= 70.0) or (load_avg and load_avg[0] >= 3.0):
        soc_status = "warning"
        soc_trouble = "Elevated SoC temperature or load average; check active ROS nodes."

    ram_pct = round((ram_used_mb / ram_total_mb) * 100.0, 1) if (ram_used_mb is not None and ram_total_mb) else None
    ram_status = "warning" if (ram_pct is not None and ram_pct >= 85.0) else "ok"

    rp1_present = any("rp1" in ln.lower() for ln in pcie_lines)
    rp1_status = "ok" if (rp1_present or usb_entries or uarts) else "warning"

    pmic_under_now = "under_voltage_now" in throttled_flags or (ext5v_volts is not None and ext5v_volts < 4.75)
    pmic_under_hist = "under_voltage_occurred" in throttled_flags or (ext5v_volts is not None and ext5v_volts < 4.88)
    pmic_status = "fault" if (pmic_under_now or usb_over_cur) else ("warning" if pmic_under_hist else "ok")
    pmic_trouble = (
        "Under-voltage or USB over-current flagged by DA9091 PMIC; inspect 5V buck/PSU rail."
        if pmic_status != "ok"
        else None
    )

    usbc_status = "fault" if pmic_under_now else ("warning" if not usb_max_en else "ok")
    usbc_trouble = (
        "USB-A current budget is capped at 600 mA (usb_max_current_enable=0); add PSU_MAX_CURRENT=5000 or usb_max_current_enable=1."
        if not usb_max_en
        else pmic_trouble
    )

    wlan = net_by_name.get("wlan0", {})
    wlan_up = wlan.get("state") == "UP"
    eth = net_by_name.get("eth0", {})
    eth_up = eth.get("state") == "UP"

    disk_status = "ok"
    disk_trouble: Optional[str] = None
    if disk_used_pct is not None:
        if disk_used_pct >= 92.0:
            disk_status = "fault"
            disk_trouble = "MicroSD rootfs is critically full (>=92%); prune old Docker images or ROS logs."
        elif disk_used_pct >= 85.0:
            disk_status = "warning"
            disk_trouble = "MicroSD rootfs is >=85% full; consider pruning unused ROS logs or Docker caches."

    rrc_present = any("/dev/rrc" in u or "/dev/ttyAMA0" in u for u in uarts)
    rrc_status = "ok" if rrc_present else "fault"

    we_port = next(iter(wonderecho_hub_ports), None)
    we_flaps = flap_counts.get(we_port, 0) if we_port else 0
    we_present = bool(wonderecho_audio or wonderecho_ch340 or we_port)
    if not we_present:
        we_status = "fault"
        we_trouble: Optional[str] = "WonderEcho Pro USB audio/serial not detected; re-seat into a black USB 2.0 port."
    elif we_flaps >= 2:
        we_status = "warning"
        we_trouble = (
            f"WonderEcho Pro disconnected {we_flaps}x on port {we_port}; move plug to a black USB 2.0 port and reseat firmly."
        )
    else:
        we_status = "ok"
        we_trouble = None

    cam_present = bool(camera_dev or any("/dev/video0" in v for v in video_devices))
    cam_status = "ok" if cam_present else "fault"

    # Assemble all 22 canonical 3D BOM hardware components in deterministic order
    components: List[Dict[str, Any]] = [
        {
            "component_id": "bcm2712_soc",
            "name": "Broadcom BCM2712 SoC (Quad Cortex-A76)",
            "category": "soc",
            "status": soc_status,
            "summary": f"{cpu_model} @ {arm_freq_mhz or 0:.0f} MHz · {cpu_temp_c if cpu_temp_c is not None else 'n/a'}°C · load {load_avg[0] if load_avg else 0:.2f}",
            "metrics": {
                "cpu_model": cpu_model,
                "temp_c": cpu_temp_c,
                "arm_freq_mhz": arm_freq_mhz,
                "vdd_core_v": vdd_core.get("volts"),
                "vdd_core_a": vdd_core.get("amps"),
                "load_1m": load_avg[0] if load_avg else None,
            },
            "bom_match_keywords": ["bcm2712", "raspberry pi 5", "cortex-a76", "soc", "cpu"],
            "troubleshooting": soc_trouble,
        },
        {
            "component_id": "ram_lpddr4x",
            "name": "LPDDR4X-4267 System RAM",
            "category": "soc",
            "status": ram_status,
            "summary": (
                f"{ram_used_mb:.0f} / {ram_total_mb:.0f} MB ({ram_pct:.1f}%)"
                if (ram_used_mb is not None and ram_total_mb is not None and ram_pct is not None)
                else "RAM telemetry unavailable"
            ),
            "metrics": {
                "ram_used_mb": ram_used_mb,
                "ram_total_mb": ram_total_mb,
                "ram_used_pct": ram_pct,
                "ddr_vdd2_v": ddr_vdd2.get("volts"),
                "ddr_vdd2_a": ddr_vdd2.get("amps"),
            },
            "bom_match_keywords": ["ram", "lpddr4x", "memory", "8gb", "raspberry pi 5"],
            "troubleshooting": "High RAM utilization; check Docker containers." if ram_status != "ok" else None,
        },
        {
            "component_id": "rp1_southbridge",
            "name": "Raspberry Pi RP1 I/O Southbridge",
            "category": "soc",
            "status": rp1_status,
            "summary": f"PCIe Gen2 Southbridge active ({len(usb_entries)} USB funcs, {len(i2c_buses)} I2C, {len(spi_devices)} SPI)",
            "metrics": {
                "pcie_detected": rp1_present,
                "usb_device_count": len(usb_entries),
                "i2c_bus_count": len(i2c_buses),
                "spi_device_count": len(spi_devices),
            },
            "bom_match_keywords": ["rp1", "southbridge", "i/o controller", "pcie"],
            "troubleshooting": None,
        },
        {
            "component_id": "da9091_pmic",
            "name": "Dialog DA9091 Power Management IC",
            "category": "power",
            "status": pmic_status,
            "summary": (
                f"EXT5V {ext5v_volts:.3f}V · {total_pmic_watts:.2f}W total · throttled {throttled_hex}"
                if (ext5v_volts is not None and total_pmic_watts is not None)
                else f"PMIC throttled={throttled_hex}"
            ),
            "metrics": {
                "ext5v_v": ext5v_volts,
                "total_pmic_w": total_pmic_watts,
                "3v3_sys_v": sys_3v3.get("volts"),
                "1v8_sys_v": sys_1v8.get("volts"),
                "vdd_core_v": vdd_core.get("volts"),
                "throttled_hex": throttled_hex,
            },
            "bom_match_keywords": ["pmic", "da9091", "power", "voltage", "regulator"],
            "troubleshooting": pmic_trouble,
        },
        {
            "component_id": "wifi_bt_module",
            "name": "Dual-Band Wi-Fi 5 & Bluetooth 5.0 Radio",
            "category": "network",
            "status": "ok" if wlan_up else "warning",
            "summary": f"wlan0 {wlan.get('state', 'UNKNOWN')} ({wlan.get('addrs') or robot.get('ip_address', '')})",
            "metrics": {
                "state": wlan.get("state", "UNKNOWN"),
                "ip": robot.get("ip_address"),
                "wl_3v7_v": wl_3v7.get("volts"),
                "wl_3v7_a": wl_3v7.get("amps"),
            },
            "bom_match_keywords": ["wifi", "wlan0", "bluetooth", "wireless", "cypress"],
            "troubleshooting": None if wlan_up else "wlan0 interface is not UP; verify NetworkManager profile.",
        },
        {
            "component_id": "usbc_pwr",
            "name": "USB-C 5V/5A Power Input & USB Budget",
            "category": "power",
            "status": usbc_status,
            "summary": f"5V Rail {ext5v_volts if ext5v_volts is not None else 'n/a'}V · USB Budget {usb_total_draw_ma}/{usb_budget_ma} mA",
            "metrics": {
                "ext5v_v": ext5v_volts,
                "usb_max_current_enable": usb_max_en,
                "usb_budget_ma": usb_budget_ma,
                "usb_total_draw_ma": usb_total_draw_ma,
                "usb_over_current": usb_over_cur,
            },
            "bom_match_keywords": ["usb-c", "power supply", "5v", "psu", "buck"],
            "troubleshooting": usbc_trouble,
        },
        {
            "component_id": "micro_hdmi_0",
            "name": "Micro-HDMI 0 (vc4hdmi0)",
            "category": "interface",
            "status": "empty",
            "summary": f"Headless · HDMI 5V rail {hdmi_rail.get('volts') if hdmi_rail.get('volts') is not None else 'n/a'}V",
            "metrics": {
                "hdmi_5v": hdmi_rail.get("volts"),
                "hdmi_a": hdmi_rail.get("amps"),
                "audio_card": any("vc4hdmi0" in c for c in audio_cards),
            },
            "bom_match_keywords": ["hdmi0", "micro-hdmi", "display"],
            "troubleshooting": None,
        },
        {
            "component_id": "micro_hdmi_1",
            "name": "Micro-HDMI 1 (vc4hdmi1)",
            "category": "interface",
            "status": "empty",
            "summary": "Headless (secondary Micro-HDMI unused)",
            "metrics": {
                "audio_card": any("vc4hdmi1" in c for c in audio_cards),
            },
            "bom_match_keywords": ["hdmi1", "micro-hdmi", "display"],
            "troubleshooting": None,
        },
        {
            "component_id": "pcie_ffc",
            "name": "PCIe 2.0 x1 FFC Connector",
            "category": "interface",
            "status": "empty",
            "summary": "No external NVMe/PCIe HAT attached (RP1 internal bus active)",
            "metrics": {"pcie_devices": len(pcie_lines)},
            "bom_match_keywords": ["pcie", "nvme", "ffc", "m.2"],
            "troubleshooting": None,
        },
        {
            "component_id": "csi_dsi_0",
            "name": "MIPI CSI/DSI Connector 0",
            "category": "interface",
            "status": "empty",
            "summary": "Unused (PuppyPi uses USB UVC camera on Port 1-1)",
            "metrics": {"csi_attached": False},
            "bom_match_keywords": ["csi0", "dsi0", "mipi", "ribbon"],
            "troubleshooting": None,
        },
        {
            "component_id": "csi_dsi_1",
            "name": "MIPI CSI/DSI Connector 1",
            "category": "interface",
            "status": "empty",
            "summary": "Unused (secondary MIPI CSI/DSI port)",
            "metrics": {"csi_attached": False},
            "bom_match_keywords": ["csi1", "dsi1", "mipi", "ribbon"],
            "troubleshooting": None,
        },
        {
            "component_id": "gpio_40pin",
            "name": "40-Pin GPIO Header (UART0 / I2C1 / SPI)",
            "category": "interface",
            "status": "ok" if rrc_present else "warning",
            "summary": f"UART0->RRC ({'OK' if rrc_present else 'MISSING'}) · {len(i2c_buses)} I2C · {len(spi_devices)} SPI",
            "metrics": {
                "uart0_rrc": rrc_present,
                "i2c_buses": len(i2c_buses),
                "spi_devices": len(spi_devices),
                "active_alt_pins": len(pinctrl_active),
            },
            "bom_match_keywords": ["gpio", "40-pin", "header", "uart", "i2c", "spi"],
            "troubleshooting": None if rrc_present else "Verify /dev/ttyAMA0 (uart0=on) and RRC HAT seating.",
        },
        {
            "component_id": "microsd_slot",
            "name": "MicroSD Root Storage Slot",
            "category": "storage",
            "status": disk_status,
            "summary": (
                f"{disk_used_gb:.1f} / {disk_total_gb:.1f} GB ({disk_used_pct:.0f}% used)"
                if (disk_used_gb is not None and disk_total_gb is not None and disk_used_pct is not None)
                else "MicroSD telemetry unavailable"
            ),
            "metrics": {
                "disk_used_gb": disk_used_gb,
                "disk_total_gb": disk_total_gb,
                "disk_used_pct": disk_used_pct,
            },
            "bom_match_keywords": ["microsd", "sd card", "mmcblk0", "storage", "disk"],
            "troubleshooting": disk_trouble,
        },
        {
            "component_id": "eth_rj45",
            "name": "Gigabit Ethernet RJ45 (eth0)",
            "category": "network",
            "status": "ok" if eth_up else "empty",
            "summary": f"eth0 {eth.get('state', 'DOWN')} ({eth.get('addrs') or 'unplugged'})",
            "metrics": {
                "state": eth.get("state", "DOWN"),
                "addrs": eth.get("addrs") or None,
            },
            "bom_match_keywords": ["ethernet", "rj45", "eth0", "lan"],
            "troubleshooting": None,
        },
    ]

    # Add the 4 USB-A physical port components
    for port_path, bus_label, comp_id in USB_PORT_SPECS:
        pinfo = port_by_path[port_path]
        if pinfo["status"] == "empty":
            p_summary = f"{bus_label} ({port_path}) — Empty at USB data layer"
            p_trouble: Optional[str] = (
                "If LD19 LiDAR is plugged here and spinning, the USB cable is likely charge-only (missing D+/D-) or converter PCB is unseated."
                if (port_path == "1-2" and not ld19_detected)
                else None
            )
        else:
            p_summary = f"{bus_label} ({port_path}): {pinfo['product']} ({pinfo['max_power_ma']} mA)"
            p_trouble = (
                f"Detected {pinfo['flap_count']} USB disconnect/re-enumeration cycles on {port_path}; reseat or move to a black USB 2.0 port."
                if pinfo["flap_count"] >= 2
                else None
            )
        components.append(
            {
                "component_id": comp_id,
                "name": f"{bus_label} Receptacle ({port_path})",
                "category": "usb",
                "status": pinfo["status"],
                "summary": p_summary,
                "metrics": {
                    "port_path": port_path,
                    "vid_pid": pinfo["vid_pid"],
                    "speed_mbps": pinfo["speed_mbps"],
                    "max_power_ma": pinfo["max_power_ma"],
                    "flap_count": pinfo["flap_count"],
                },
                "bom_match_keywords": [port_path, bus_label.lower(), "usb", pinfo["vid_pid"] or ""],
                "troubleshooting": p_trouble,
            }
        )

    # Add the 4 PuppyPi stack peripheral components
    components.extend(
        [
            {
                "component_id": "rrc_hat_stm32",
                "name": "Hiwonder RRC STM32 Expansion HAT",
                "category": "peripheral",
                "status": rrc_status,
                "summary": "Connected on /dev/rrc -> /dev/ttyAMA0 (8 leg + 3 arm servos, IMU, buzzer)"
                if rrc_present
                else "/dev/rrc (/dev/ttyAMA0) missing",
                "metrics": {
                    "serial_link": "/dev/rrc -> /dev/ttyAMA0" if rrc_present else None,
                    "battery_mv": robot.get("battery_mv"),
                },
                "bom_match_keywords": ["rrc", "stm32", "expansion", "servo", "imu", "buzzer", "hat"],
                "troubleshooting": None
                if rrc_present
                else "Verify Hiwonder RRC expansion board 40-pin seating and dtparam=uart0=on.",
            },
            {
                "component_id": "ld19_lidar_module",
                "name": "LDROBOT LD19 360° ToF LiDAR + USB-UART Converter",
                "category": "peripheral",
                "status": "ok" if ld19_detected else "fault",
                "summary": (
                    f"Enumerated at {ld19_device_path} (230400 baud)"
                    if ld19_detected
                    else "Not enumerated on USB (0 CP2102/CH340 adapters) — check data USB cable"
                ),
                "metrics": {
                    "detected": ld19_detected,
                    "device_path": ld19_device_path,
                    "usb_headroom_ma": headroom_ma,
                    "baud_rate": 230400,
                },
                "bom_match_keywords": ["ld19", "ld06", "lidar", "ldlidar", "cp2102", "tof", "laser"],
                "troubleshooting": None
                if ld19_detected
                else "Swap the LD19 converter's USB cable for a known data-transfer cable (not charge-only) and plug directly into any Pi 5 USB-A port.",
            },
            {
                "component_id": "camera_icspring",
                "name": "icSpring 640×480 UVC USB Camera",
                "category": "peripheral",
                "status": cam_status,
                "summary": (
                    f"Enumerated on Port {camera_dev['root_port']} ({camera_dev['vid_pid']}, {camera_dev['max_power_ma']} mA) -> /dev/video0"
                    if camera_dev
                    else ("/dev/video0 present" if cam_present else "USB camera not detected")
                ),
                "metrics": {
                    "vid_pid": camera_dev["vid_pid"] if camera_dev else None,
                    "port_path": camera_dev["root_port"] if camera_dev else None,
                    "max_power_ma": camera_dev["max_power_ma"] if camera_dev else 0,
                },
                "bom_match_keywords": ["icspring", "camera", "uvc", "video0", "32e6:9005", "webcam"],
                "troubleshooting": None if cam_present else "Re-seat the icSpring USB camera cable on Pi 5 USB-A.",
            },
            {
                "component_id": "wonderecho_pro",
                "name": "Hiwonder WonderEcho Pro Voice & Speaker Module",
                "category": "peripheral",
                "status": we_status,
                "summary": (
                    f"Port {we_port} · CH340 + USB PnP Audio (flaps={we_flaps})"
                    if we_present
                    else "WonderEcho Pro USB audio & CH340 serial disconnected"
                ),
                "metrics": {
                    "port_path": we_port,
                    "audio_detected": bool(wonderecho_audio),
                    "serial_detected": bool(wonderecho_ch340 or "/dev/wonderecho" in serial_symlinks),
                    "flap_count": we_flaps,
                    "max_power_ma": port_by_path[we_port]["max_power_ma"] if we_port in port_by_path else 0,
                },
                "bom_match_keywords": ["wonderecho", "audio", "microphone", "speaker", "0c76:161f", "1a86:8091", "voice"],
                "troubleshooting": we_trouble,
            },
        ]
    )

    return {
        "robot_id": str(robot.get("id") or ""),
        "robot_name": str(robot.get("name") or "PuppyPi"),
        "ip_address": str(robot.get("ip_address") or ""),
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "board_model": board_model,
        "cpu_model": cpu_model,
        "cpu_temp_c": cpu_temp_c,
        "arm_freq_mhz": arm_freq_mhz,
        "load_avg": load_avg,
        "uptime_text": uptime_text,
        "ram_used_mb": ram_used_mb,
        "ram_total_mb": ram_total_mb,
        "disk_used_gb": disk_used_gb,
        "disk_total_gb": disk_total_gb,
        "disk_used_pct": disk_used_pct,
        "throttled_hex": throttled_hex,
        "throttled_flags": throttled_flags,
        "ext5v_volts": ext5v_volts,
        "total_pmic_watts": total_pmic_watts,
        "pmic_rails": pmic_rails,
        "usb_max_current_enable": usb_max_en,
        "usb_budget_ma": usb_budget_ma,
        "usb_total_draw_ma": usb_total_draw_ma,
        "usb_over_current": usb_over_cur,
        "usb_ports": usb_ports,
        "ld19_verdict": ld19_verdict,
        "interfaces": {
            "pcie": pcie_lines,
            "uarts": uarts,
            "i2c_buses": i2c_buses,
            "spi_devices": spi_devices,
            "video_devices": video_devices,
            "audio_cards": audio_cards,
            "pinctrl_active": pinctrl_active,
            "network": network_lines,
            "docker_containers": docker_containers,
        },
        "components": components,
    }


async def collect_pi5_hardware_diagnostics(
    robot: Dict[str, Any],
    password: str,
    timeout: float = 12.0,
) -> Dict[str, Any]:
    """Run a single read-only SSH probe on Raspberry Pi 5 and return structured diagnostics.

    Uses ``run_remote_python`` with up to 3 automatic retries and logs transient errors
    to ``sys.stderr``.

    Args:
        robot: Robot record containing ``id``, ``name``, ``ip_address``, and ``ssh_user``.
        password: SSH password for the robot host.
        timeout: Per-attempt SSH timeout in seconds.

    Returns:
        Structured ``Pi5HardwareDiagnostics`` dictionary with live PMIC, USB, interface,
        LD19 verdict, and 22 canonical 3D BOM component states.

    Raises:
        SSHAuthError: When SSH credentials are rejected.
        SSHCommandError: When collection fails after retries.
    """
    ip = str(robot.get("ip_address") or "").strip()
    user = str(robot.get("ssh_user") or "pi").strip()
    try:
        res = await run_remote_python(
            ip=ip,
            user=user,
            password=password,
            python_source=_PI5_DIAG_REMOTE_SCRIPT,
            payload={},
            timeout=timeout,
            retries=3,
            env_vars={"SUDO_PW": password} if password else None,
        )
    except SSHAuthError:
        raise
    except Exception as exc:
        sys.stderr.write(f"[pi5_diagnostics] Failed collecting Pi 5 telemetry from {user}@{ip}: {exc}\n")
        raise SSHCommandError(f"Pi 5 hardware diagnostics failed for {user}@{ip}: {exc}") from exc

    sections = res.get("sections") if isinstance(res, dict) else {}
    if not isinstance(sections, dict):
        sections = {}
    return build_pi5_diagnostics_payload(robot=robot, raw_sections=sections)
