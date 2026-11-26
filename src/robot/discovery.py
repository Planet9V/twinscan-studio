"""3-tier async LAN auto-discovery for Hiwonder PuppyPi and ROS robots.

Probes LAN CIDRs (default ``192.168.1.0/24``) and saved robot IPs in parallel using
``asyncio.Semaphore(64)`` across:
1. Unicast UDP ``9027`` (``LOBOT_NET_DISCOVER`` -> parses ``PUPPY_1.0:<SN>``)
2. TCP ``9090`` (``rosbridge_websocket``) and TCP ``8080`` (``web_video_server``)
3. TCP ``22`` (OpenSSH banner grab)
"""

from __future__ import annotations

import asyncio
import ipaddress
import sys
from typing import Any, List, Optional, Sequence, Tuple

DEFAULT_DISCOVERY_CIDRS: tuple[str, ...] = ("192.168.1.0/24",)
LOBOT_DISCOVER_PORT = 9027
LOBOT_DISCOVER_PAYLOAD = b"LOBOT_NET_DISCOVER"
ROSBRIDGE_PORT = 9090
VIDEO_SERVER_PORT = 8080
SSH_PORT = 22
MAX_DISCOVERY_HOSTS = 1024


def parse_lobot_udp_reply(payload: bytes | str) -> Optional[dict[str, str]]:
    """Parse a Hiwonder/Lobot UDP 9027 discovery reply frame.

    Expected wire format from PuppyPi ``find_device.py``:
    ``"PUPPY_1.0:<32-char-SN>\\n"``.

    Args:
        payload: Raw UDP datagram bytes or decoded string.

    Returns:
        Dictionary ``{"protocol": str, "serial_number": str}`` when valid, else ``None``.
    """
    text = payload.decode("utf-8", errors="ignore") if isinstance(payload, (bytes, bytearray)) else str(payload)
    cleaned = text.strip()
    if not cleaned or ":" not in cleaned:
        return None
    prefix, serial = cleaned.split(":", 1)
    prefix = prefix.strip()
    serial = serial.strip()
    if not prefix or not serial:
        return None
    upper = prefix.upper()
    if not (upper.startswith("PUPPY") or upper.startswith("LOBOT") or upper.startswith("HIWONDER")):
        return None
    return {"protocol": prefix, "serial_number": serial}


def expand_target_ips(
    cidrs: Optional[Sequence[str]] = None,
    saved_ips: Optional[Sequence[str]] = None,
    max_hosts: int = MAX_DISCOVERY_HOSTS,
) -> List[str]:
    """Expand CIDR ranges and explicit IP addresses into a deduplicated list of IPv4 targets.

    Args:
        cidrs: Optional list of CIDR strings (defaults to ``["192.168.1.0/24"]``).
        saved_ips: Optional list of previously known robot IPv4 addresses to always probe.
        max_hosts: Safety ceiling on total expanded host addresses.

    Returns:
        Deduplicated list of IPv4 address strings.
    """
    seen: set[str] = set()
    targets: List[str] = []

    def _add_ip(ip_str: str) -> None:
        if len(targets) >= max_hosts or ip_str in seen:
            return
        seen.add(ip_str)
        targets.append(ip_str)

    # Probe saved IPs first so known robots are never truncated by max_hosts.
    for raw_ip in saved_ips or ():
        s = str(raw_ip).strip()
        if not s:
            continue
        try:
            addr = ipaddress.ip_address(s)
            if isinstance(addr, ipaddress.IPv4Address):
                _add_ip(str(addr))
        except ValueError:
            sys.stderr.write(f"[discovery] Ignoring invalid saved IP: {s!r}\n")

    active_cidrs = list(cidrs) if cidrs else list(DEFAULT_DISCOVERY_CIDRS)
    for raw_cidr in active_cidrs:
        s = str(raw_cidr).strip()
        if not s:
            continue
        try:
            if "/" not in s:
                addr = ipaddress.ip_address(s)
                if isinstance(addr, ipaddress.IPv4Address):
                    _add_ip(str(addr))
                continue
            net = ipaddress.ip_network(s, strict=False)
            if not isinstance(net, ipaddress.IPv4Network):
                continue
            if net.num_addresses == 1:
                _add_ip(str(net.network_address))
            else:
                for host in net.hosts():
                    if len(targets) >= max_hosts:
                        break
                    _add_ip(str(host))
        except ValueError as exc:
            sys.stderr.write(f"[discovery] Ignoring invalid CIDR {s!r}: {exc}\n")

    return targets


async def probe_tcp_port(
    ip: str,
    port: int,
    timeout: float = 0.45,
    read_banner: bool = False,
) -> Tuple[bool, str]:
    """Probe a single TCP port and optionally read a service banner (e.g. OpenSSH).

    Args:
        ip: Target IPv4 address.
        port: TCP port number.
        timeout: Connection timeout in seconds.
        read_banner: When ``True``, attempt a brief banner read after connecting.

    Returns:
        Tuple ``(is_open, banner_text)``.
    """
    writer: Optional[asyncio.StreamWriter] = None
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout=timeout)
        banner = ""
        if read_banner:
            try:
                raw = await asyncio.wait_for(reader.read(128), timeout=min(0.35, timeout))
                banner = raw.decode("utf-8", errors="ignore").strip().splitlines()[0] if raw else ""
            except Exception:
                banner = ""
        return True, banner
    except Exception:
        return False, ""
    finally:
        if writer is not None:
            try:
                writer.close()
                await asyncio.wait_for(writer.wait_closed(), timeout=0.15)
            except Exception:
                pass


class _LobotUdpClientProtocol(asyncio.DatagramProtocol):
    """Minimal asyncio UDP protocol for single-shot Lobot discovery replies."""

    def __init__(self, future: asyncio.Future[bytes]) -> None:
        self._future = future

    def datagram_received(self, data: bytes, addr: Tuple[str, int]) -> None:
        if not self._future.done():
            self._future.set_result(data)

    def error_received(self, exc: Exception) -> None:
        if not self._future.done():
            self._future.set_exception(exc)


async def probe_udp_lobot(
    ip: str,
    port: int = LOBOT_DISCOVER_PORT,
    timeout: float = 0.5,
) -> Optional[dict[str, str]]:
    """Send unicast ``LOBOT_NET_DISCOVER`` UDP packet to ``ip:9027`` and parse reply.

    Args:
        ip: Target IPv4 address.
        port: UDP port (default ``9027``).
        timeout: Seconds to wait for a datagram reply.

    Returns:
        Parsed ``{"protocol", "serial_number"}`` dictionary or ``None``.
    """
    loop = asyncio.get_running_loop()
    fut: asyncio.Future[bytes] = loop.create_future()
    transport: Optional[asyncio.DatagramTransport] = None
    try:
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _LobotUdpClientProtocol(fut),
            remote_addr=(ip, port),
        )
        transport.sendto(LOBOT_DISCOVER_PAYLOAD)
        data = await asyncio.wait_for(fut, timeout=timeout)
        return parse_lobot_udp_reply(data)
    except Exception:
        return None
    finally:
        if transport is not None:
            try:
                transport.close()
            except Exception:
                pass


def classify_robot_candidate(
    ip: str,
    serial_number: Optional[str],
    rosbridge_open: bool,
    video_open: bool,
    ssh_open: bool,
    ssh_banner: str,
    protocol: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Classify probe signals into a discovered robot candidate or ``None``.

    Args:
        ip: Probed IPv4 address.
        serial_number: Parsed UDP 9027 serial number if received.
        rosbridge_open: Whether TCP 9090 (rosbridge) responded.
        video_open: Whether TCP 8080 (web_video_server) responded.
        ssh_open: Whether TCP 22 (SSH) responded.
        ssh_banner: SSH banner text if available.
        protocol: Optional UDP protocol prefix (e.g. ``PUPPY_1.0``).

    Returns:
        Candidate dictionary when host looks like a PuppyPi/ROS robot, else ``None``.
    """
    is_windows_ssh = "windows" in (ssh_banner or "").lower()
    if not (serial_number or rosbridge_open or (video_open and ssh_open and not is_windows_ssh)):
        return None

    if serial_number or (rosbridge_open and video_open):
        model_guess = "Hiwonder PuppyPi Pro"
    elif rosbridge_open:
        model_guess = "ROS Robot (ROSBridge)"
    else:
        model_guess = "Linux Robotics Node"

    return {
        "ip": ip,
        "serial_number": serial_number,
        "protocol": protocol,
        "rosbridge_open": rosbridge_open,
        "video_open": video_open,
        "ssh_open": ssh_open,
        "ssh_banner": ssh_banner,
        "model_guess": model_guess,
    }


async def probe_host(
    ip: str,
    semaphore: asyncio.Semaphore,
    tcp_timeout: float = 0.45,
    udp_timeout: float = 0.5,
) -> Optional[dict[str, Any]]:
    """Run all 3 discovery tiers against a single host under a concurrency semaphore.

    Args:
        ip: Target IPv4 address.
        semaphore: Concurrency limiter (typically ``asyncio.Semaphore(64)``).
        tcp_timeout: Per-port TCP connect timeout in seconds.
        udp_timeout: UDP 9027 reply timeout in seconds.

    Returns:
        Discovered robot candidate dictionary or ``None``.
    """
    async with semaphore:
        try:
            ros_res, vid_res, ssh_res, udp_res = await asyncio.gather(
                probe_tcp_port(ip, ROSBRIDGE_PORT, timeout=tcp_timeout, read_banner=False),
                probe_tcp_port(ip, VIDEO_SERVER_PORT, timeout=tcp_timeout, read_banner=False),
                probe_tcp_port(ip, SSH_PORT, timeout=tcp_timeout, read_banner=True),
                probe_udp_lobot(ip, LOBOT_DISCOVER_PORT, timeout=udp_timeout),
            )
            rosbridge_open, _ = ros_res
            video_open, _ = vid_res
            ssh_open, ssh_banner = ssh_res
            serial_number = udp_res["serial_number"] if udp_res else None
            protocol = udp_res["protocol"] if udp_res else None
            return classify_robot_candidate(
                ip=ip,
                serial_number=serial_number,
                rosbridge_open=rosbridge_open,
                video_open=video_open,
                ssh_open=ssh_open,
                ssh_banner=ssh_banner,
                protocol=protocol,
            )
        except Exception as exc:
            sys.stderr.write(f"[discovery] Probe failed for {ip}: {exc}\n")
            return None


async def discover_robots_on_lan(
    cidrs: Optional[Sequence[str]] = None,
    saved_ips: Optional[Sequence[str]] = None,
    tcp_timeout: float = 0.45,
    udp_timeout: float = 0.5,
    concurrency: int = 64,
) -> List[dict[str, Any]]:
    """Scan LAN CIDRs and saved robot IPs in parallel for PuppyPi and ROS robots.

    Args:
        cidrs: Optional CIDR subnets (defaults to ``["192.168.1.0/24"]``).
        saved_ips: Previously registered robot IPs to always include in the scan.
        tcp_timeout: TCP port probe timeout in seconds.
        udp_timeout: UDP 9027 discovery timeout in seconds.
        concurrency: Max concurrent host probes (default ``64``).

    Returns:
        List of discovered robot candidate dictionaries ranked by confidence.
    """
    ips = expand_target_ips(cidrs=cidrs, saved_ips=saved_ips)
    if not ips:
        return []
    sem = asyncio.Semaphore(max(1, concurrency))
    results = await asyncio.gather(
        *(probe_host(ip, sem, tcp_timeout=tcp_timeout, udp_timeout=udp_timeout) for ip in ips)
    )
    candidates = [r for r in results if r is not None]
    candidates.sort(
        key=lambda c: (
            1 if c.get("serial_number") else 0,
            1 if c.get("rosbridge_open") else 0,
            1 if c.get("video_open") else 0,
            1 if c.get("ssh_open") else 0,
        ),
        reverse=True,
    )
    return candidates
