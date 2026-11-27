"""Fleet & Edge Camera Auto-Discovery for Eigenia Overwatch.

Probes registered Raspberry Pi / robot fleet nodes for active HTTP MJPG
camera services (e.g. ``eigenia-pi5-cam.service`` on port 8090) and ROS
video endpoints (e.g. PuppyPi Pro ``web_video_server`` on port 8080) so users
can discover and add any camera into Overwatch in one click.
"""

from __future__ import annotations

import asyncio
import re
import sys
from typing import Any, Dict, List, Optional

import httpx

from src.vision.overwatch_triangulator import OverwatchCameraManager

MAX_PROBE_RETRIES = 2


def _slugify_camera_id(raw: str, fallback: str = "cam") -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "_", (raw or "").strip().lower()).strip("_")
    return (slug[:28] or fallback)


async def _probe_http_json(url: str, timeout_s: float = 2.0) -> Optional[Dict[str, Any]]:
    for attempt in range(1, MAX_PROBE_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, dict):
                        return data
                return None
        except Exception as exc:
            if attempt == MAX_PROBE_RETRIES:
                sys.stderr.write(f"[overwatch.discover] HTTP probe {url} failed: {exc}\n")
            else:
                await asyncio.sleep(0.15)
    return None


async def _probe_http_alive(url: str, timeout_s: float = 2.0) -> bool:
    for attempt in range(1, MAX_PROBE_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                async with client.stream("GET", url) as resp:
                    if resp.status_code == 200:
                        return True
                return False
        except Exception as exc:
            if attempt == MAX_PROBE_RETRIES:
                sys.stderr.write(f"[overwatch.discover] Stream check {url} failed: {exc}\n")
            else:
                await asyncio.sleep(0.15)
    return False


async def discover_fleet_cameras(
    *,
    robot_store: Any = None,
    remote_puller: Any = None,
    overwatch_manager: Optional[OverwatchCameraManager] = None,
) -> Dict[str, Any]:
    """Discover all available fleet, remote, and active Overwatch cameras.

    Args:
        robot_store: Optional robot/node store providing registered Raspberry Pis & robots.
        remote_puller: Optional ``RemoteOverwatchPullerManager`` with configured remote URLs.
        overwatch_manager: Optional ``OverwatchCameraManager`` with active camera slots.

    Returns:
        Dictionary containing ``discovered`` candidate cameras, ``active_slots``,
        and ``remote_sources`` ready for the Overwatch Camera Manager UI.
    """
    discovered: List[Dict[str, Any]] = []
    remote_sources: List[Dict[str, Any]] = (
        remote_puller.list_sources() if remote_puller is not None and hasattr(remote_puller, "list_sources") else []
    )
    remote_by_url = {str(s.get("stream_url") or ""): s for s in remote_sources}

    active_status = overwatch_manager.get_status() if overwatch_manager is not None else {}
    active_slots: Dict[str, Any] = dict(active_status.get("cameras") or {})

    robots: List[Dict[str, Any]] = []
    if robot_store is not None and hasattr(robot_store, "list_robots"):
        try:
            robots = list(robot_store.list_robots() or [])
        except Exception as exc:
            sys.stderr.write(f"[overwatch.discover] Failed listing fleet nodes: {exc}\n")

    async def _probe_node(node: Dict[str, Any]) -> List[Dict[str, Any]]:
        ip = str(node.get("ip_address") or "").strip()
        if not ip:
            return []
        name = str(node.get("name") or ip).strip()
        node_id = str(node.get("id") or "")
        found: List[Dict[str, Any]] = []

        # 1) Check Eigenia Pi MJPG Camera Service (:8090/health)
        health_url = f"http://{ip}:8090/health"
        health = await _probe_http_json(health_url, timeout_s=1.8)
        if health is not None:
            stream_url = f"http://{ip}:8090/stream.mjpg"
            existing = remote_by_url.get(stream_url)
            res_str = str(health.get("resolution") or "1920x1080")
            fps_val = float(health.get("target_fps") or 15.0)
            suggested_id = (
                str(existing["camera_id"])
                if existing
                else ("usb_4k" if "pi 5" in name.lower() or "rasp5" in name.lower() else _slugify_camera_id(f"{name}_cam"))
            )
            found.append(
                {
                    "id": f"pi_mjpg_{ip}",
                    "kind": "pi_mjpg",
                    "node_id": node_id,
                    "node_name": name,
                    "ip_address": ip,
                    "camera_name": f"{name} Camera ({ip})",
                    "suggested_camera_id": suggested_id,
                    "stream_url": stream_url,
                    "snapshot_url": f"http://{ip}:8090/snapshot.jpg",
                    "resolution": res_str,
                    "fps": fps_val,
                    "online": bool(health.get("ok", True)),
                    "already_added": existing is not None,
                    "active_camera_id": existing["camera_id"] if existing else None,
                }
            )

        # 2) Check PuppyPi / ROS web_video_server (:8080)
        video_port = int(node.get("video_port") or 8080)
        is_robot_cam = "puppy" in name.lower() or str(node.get("robot_type") or "").lower() in {"puppypi", "puppypi_pro"}
        if is_robot_cam:
            ros_stream = f"http://{ip}:{video_port}/stream?topic=/usb_cam/image_raw"
            alive = await _probe_http_alive(f"http://{ip}:{video_port}/", timeout_s=1.5)
            found.append(
                {
                    "id": f"robot_fpv_{ip}",
                    "kind": "robot_fpv",
                    "node_id": node_id,
                    "node_name": name,
                    "ip_address": ip,
                    "camera_name": f"{name} FPV (Mobile)",
                    "suggested_camera_id": "puppypi_fpv",
                    "stream_url": ros_stream,
                    "snapshot_url": f"http://{ip}:{video_port}/snapshot?topic=/usb_cam/image_raw",
                    "resolution": "640x480",
                    "fps": 15.0,
                    "online": alive or bool(node.get("is_online")),
                    "already_added": True,
                    "active_camera_id": "puppypi_fpv",
                }
            )
        return found

    if robots:
        results = await asyncio.gather(*(_probe_node(n) for n in robots), return_exceptions=True)
        for res in results:
            if isinstance(res, list):
                discovered.extend(res)
            elif isinstance(res, Exception):
                sys.stderr.write(f"[overwatch.discover] Node probe exception: {res}\n")

    return {
        "ok": True,
        "discovered": discovered,
        "remote_sources": remote_sources,
        "active_slots": active_slots,
        "count": len(discovered),
    }
