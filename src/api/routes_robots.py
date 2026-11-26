"""FastAPI endpoints for PuppyPi Auto-Discovery, ROS 1/2 Dual-Mode Control, Network Telemetry, Update Checks, BOM/SBOM, FPV Video, and Remote Config."""

from __future__ import annotations

import ipaddress
import json
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, HTTPException, Query, Request, Response, WebSocket
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.api.state import TwinScanRuntimeState
from src.db.robot_store import RobotStoreProtocol
from src.lidar.spatial_3d import raycast_camera_to_lidar
from src.robot.discovery import discover_robots_on_lan
from src.robot.pi5_diagnostics import collect_pi5_hardware_diagnostics
from src.robot.ros_profiles import get_ros_comparison_payload, get_ros_profile, normalize_ros_mode
from src.robot.rosbridge_proxy import (
    call_go_home,
    fetch_robot_snapshot,
    proxy_rosbridge_websocket,
    publish_gait,
    publish_pose,
    publish_velocity,
    run_action,
    set_buzzer,
    set_mark_time,
    set_oled,
    set_rgb,
    set_servo,
    set_vision_mode,
    stream_robot_video,
    trigger_estop,
    validate_video_topic,
)
from src.robot.ssh_manager import (
    SSHAuthError,
    SSHCommandError,
    build_robot_cyclonedx_hbom_sbom,
    change_password,
    clean_robot_stale_logs,
    collect_network_interfaces,
    collect_robot_catalogue,
    configure_mechanics,
    configure_ros_and_ai,
    configure_wifi,
    power_action,
)
from src.robot.update_checker import run_robot_update_and_feature_check
from src.robot.update_executor import (
    apply_apt_updates,
    apply_pip_updates,
    download_apt_updates,
    download_pip_updates,
    list_container_snapshots,
    preview_apt_updates,
    preview_pip_updates,
    rollback_container_snapshot,
    run_post_update_smoke_tests,
)
from src.vision.preprocessor import preprocess_industrial_image

router = APIRouter(prefix="/api/robots", tags=["robots"])


# --- Request Models ---


class DiscoverRequest(BaseModel):
    """LAN discovery scan parameters."""

    cidrs: Optional[List[str]] = None
    auto_register: bool = True


class RegisterRobotRequest(BaseModel):
    """Manual robot registration payload."""

    ip_address: str
    name: Optional[str] = None
    model: str = "Hiwonder PuppyPi Pro"
    serial_number: Optional[str] = None
    mac_address: Optional[str] = None
    ssh_user: str = "pi"
    ssh_password: Optional[str] = "raspberrypi"
    rosbridge_port: int = 9090
    video_port: int = 8080


class ActiveIpRequest(BaseModel):
    """Switch active control IPv4 address for a robot (e.g. Ethernet <-> Wi-Fi)."""

    ip_address: str


class VelocityCommandRequest(BaseModel):
    """PuppyPi velocity command payload."""

    x: float = 0.0
    y: float = 0.0
    yaw_rate: float = 0.0
    use_autogait: bool = True


class MarkTimeCommandRequest(BaseModel):
    """Toggle march-in-place mode via ``/puppy_control/set_mark_time``."""

    enabled: bool = True


class PoseCommandRequest(BaseModel):
    """PuppyPi body pose or preset payload."""

    preset: Optional[str] = None
    roll: float = 0.0
    pitch: float = 0.0
    yaw: float = 0.0
    height: float = -10.0
    x_shift: float = -0.5
    stance_x: float = 0.0
    stance_y: float = 0.0
    run_time: int = 500


class GaitCommandRequest(BaseModel):
    """PuppyPi gait timing or preset payload."""

    preset: Optional[str] = None
    overlap_time: float = 0.2
    swing_time: float = 0.2
    clearance_time: float = 0.0
    z_clearance: float = 4.0


class ActionCommandRequest(BaseModel):
    """PuppyPi action group trigger payload."""

    name: str
    wait: bool = False


class ServoCommandRequest(BaseModel):
    """Direct servo PWM pulse payload."""

    id: int = Field(ge=1, le=16)
    pulse: int
    time: int = 500


class BuzzerCommandRequest(BaseModel):
    """STM32 expansion board buzzer payload."""

    freq: int = 1900
    on_time: float = 0.1
    off_time: float = 0.1
    repeat: int = 1


class RgbPixel(BaseModel):
    """Single addressable RGB LED state."""

    id: int = Field(ge=1, le=16)
    r: int = 0
    g: int = 0
    b: int = 0


class RgbCommandRequest(BaseModel):
    """STM32 expansion board RGB LED array payload."""

    data: List[RgbPixel]


class OledCommandRequest(BaseModel):
    """STM32 OLED line display payload."""

    index: int = Field(default=1, ge=1, le=4)
    text: str = ""


class VisionModeRequest(BaseModel):
    """Activate or deactivate a Hiwonder CV vision node with automatic heartbeat."""

    mode: str = "raw"


class SnapToVisionRequest(BaseModel):
    """Live PuppyPi FPV camera snap-to-vision analysis parameters."""

    topic: Optional[str] = None
    model: Optional[str] = None
    consensus: bool = False
    context_hint: str = ""
    camera_fov_deg: Optional[float] = None
    camera_yaw_deg: float = 0.0


class WifiConfigRequest(BaseModel):
    """Remote PuppyPi Wi-Fi configuration payload."""

    mode: int = 2
    ssid: str
    wifi_password: Optional[str] = None
    password: Optional[str] = None
    country_code: str = "US"
    restart_service: bool = True


class PasswordConfigRequest(BaseModel):
    """Remote Linux account password change payload."""

    target_user: str = "pi"
    new_password: str


class MechanicsConfigRequest(BaseModel):
    """Remote PuppyPi mechanics and servo calibration payload."""

    with_arm: Optional[Union[int, bool]] = None
    x_shift: Optional[float] = None
    servo_deviations: Optional[Dict[str, int]] = None


class RosAiConfigRequest(BaseModel):
    """Remote ROS1/ROS2 distro switch, DDS config, ASR language, and boot persistence payload."""

    target_ros: Optional[str] = None
    asr_language: Optional[str] = None
    ros_domain_id: int = 0
    rmw_implementation: str = "rmw_cyclonedds_cpp"
    persist_boot: bool = True


class PowerActionRequest(BaseModel):
    """Remote PuppyPi service/power control payload."""

    action: str


class UpdateTrackRequest(BaseModel):
    """Robot software update dry-run or pre-download request."""

    track: str = "ros_pip"
    packages: Optional[List[str]] = None


class UpdateApplyRequest(BaseModel):
    """Robot software update apply request with safety gates."""

    track: str = "ros_pip"
    packages: Optional[List[str]] = None
    allow_abi_sensitive: bool = False
    run_tests: bool = True


class UpdateTestRequest(BaseModel):
    """Standalone 6-point post-update smoke test request."""

    packages: Optional[List[str]] = None


class UpdateRollbackRequest(BaseModel):
    """Docker container rollback snapshot request."""

    rollback_tag: str
    container: Optional[str] = None


# --- Helpers ---


def _runtime(request: Request) -> TwinScanRuntimeState:
    return request.app.state.runtime


def _robot_store(request: Request) -> RobotStoreProtocol:
    return request.app.state.robot_store


def _require_robot(store: RobotStoreProtocol, robot_id: str) -> Dict[str, Any]:
    robot = store.get_robot(robot_id)
    if not robot:
        raise HTTPException(status_code=404, detail=f"Robot {robot_id} not found.")
    return robot


def _robot_ros_mode(robot: Dict[str, Any]) -> str:
    return normalize_ros_mode(robot.get("active_ros_distro"))


def _resolve_camera_topic(robot: Dict[str, Any], requested_topic: Optional[str]) -> str:
    """Resolve the active raw camera topic for ROS 1 (``/usb_cam/image_raw``) or ROS 2 (``/image_raw``)."""
    ros_mode = _robot_ros_mode(robot)
    default_topic = str(get_ros_profile(ros_mode)["camera_topic"])
    raw = (requested_topic or "").strip()
    if not raw:
        return default_topic
    if ros_mode == "ros2" and raw == "/usb_cam/image_raw":
        return default_topic
    return validate_video_topic(raw)


async def _fetch_snapshot_with_fallback(
    robot: Dict[str, Any],
    requested_topic: Optional[str],
    timeout: float = 5.0,
    retries: int = 2,
) -> tuple[bytes, str]:
    """Fetch a live JPEG from PuppyPi with automatic raw-topic fallback (``/image_raw`` <-> ``/usb_cam/image_raw``)."""
    primary = _resolve_camera_topic(robot, requested_topic)
    ip = robot["ip_address"]
    port = int(robot.get("video_port") or 8080)
    try:
        data = await fetch_robot_snapshot(ip=ip, port=port, topic=primary, timeout=timeout, retries=retries)
        return data, primary
    except ConnectionError:
        if primary in ("/image_raw", "/usb_cam/image_raw"):
            alternate = "/usb_cam/image_raw" if primary == "/image_raw" else "/image_raw"
            data = await fetch_robot_snapshot(ip=ip, port=port, topic=alternate, timeout=timeout, retries=1)
            return data, alternate
        raise


def _sync_robot_to_neo4j(
    rt: TwinScanRuntimeState,
    robot: Dict[str, Any],
    devices: List[Dict[str, Any]],
    containers: List[Dict[str, Any]],
) -> bool:
    """Sync Robot, HardwareDevice, and Container nodes into Neo4j 5 if enabled."""
    if not rt.neo4j.enabled:
        return False
    cypher = """
    MERGE (f:Facility {name: $facility})
    MERGE (r:Robot {id: $robot_id})
    SET r.name = $name,
        r.model = $model,
        r.ip_address = $ip_address,
        r.mac_address = $mac_address,
        r.serial_number = $serial_number,
        r.active_ros_distro = $active_ros_distro,
        r.status = $status
    MERGE (f)-[:OPERATES]->(r)
    WITH r
    OPTIONAL MATCH (r)-[:HAS_HARDWARE]->(old_hd:HardwareDevice)
    DETACH DELETE old_hd
    WITH r
    OPTIONAL MATCH (r)-[:RUNS_CONTAINER]->(old_c:Container)
    DETACH DELETE old_c
    WITH r
    FOREACH (dev IN $devices |
        MERGE (d:HardwareDevice {id: dev.id})
        SET d.subsystem = dev.subsystem,
            d.make = dev.make,
            d.model = dev.model,
            d.bus_type = dev.bus_type,
            d.device_path = dev.device_path,
            d.usb_id = dev.usb_id,
            d.status = dev.status
        MERGE (r)-[:HAS_HARDWARE]->(d)
    )
    FOREACH (ctr IN $containers |
        MERGE (c:Container {key: $robot_id + ':' + ctr.name})
        SET c.name = ctr.name,
            c.image = ctr.image,
            c.state = ctr.state,
            c.ros_distro = ctr.ros_distro
        MERGE (r)-[:RUNS_CONTAINER]->(c)
    )
    """
    try:
        return rt.neo4j._run_write_with_retry(
            cypher,
            {
                "facility": rt.effective_config.get("facility_name", rt.settings.facility_name),
                "robot_id": robot["id"],
                "name": robot["name"],
                "model": robot["model"],
                "ip_address": robot["ip_address"],
                "mac_address": robot.get("mac_address") or "",
                "serial_number": robot.get("serial_number") or "",
                "active_ros_distro": robot.get("active_ros_distro") or "",
                "status": robot.get("status") or "online",
                "devices": [
                    {
                        "id": str(d.get("id") or f"{robot['id']}:{i}"),
                        "subsystem": str(d.get("subsystem") or "hardware"),
                        "make": str(d.get("make") or "Unknown"),
                        "model": str(d.get("model") or "Unknown"),
                        "bus_type": str(d.get("bus_type") or "unknown"),
                        "device_path": str(d.get("device_path") or ""),
                        "usb_id": str(d.get("usb_id") or ""),
                        "status": str(d.get("status") or "online"),
                    }
                    for i, d in enumerate(devices)
                ],
                "containers": [
                    {
                        "name": str(c.get("name") or "container"),
                        "image": str(c.get("image") or ""),
                        "state": str(c.get("state") or ""),
                        "ros_distro": str(c.get("ros_distro") or ""),
                    }
                    for c in containers
                ],
            },
        )
    except Exception as exc:
        sys.stderr.write(f"[robots.neo4j] Failed syncing robot {robot['id']} to Neo4j: {exc}\n")
        return False


# --- Fleet Discovery, ROS Comparison & CRUD ---


@router.get("")
async def list_robots(request: Request) -> Dict[str, Any]:
    """List all registered robots from the robot store."""
    robots = _robot_store(request).list_robots()
    return {"robots": robots, "count": len(robots)}


@router.get("/ros-comparison")
async def get_ros_comparison() -> Dict[str, Any]:
    """Return authoritative ROS 1 Noetic vs. ROS 2 Humble comparison matrix and profiles."""
    return get_ros_comparison_payload()


@router.post("/discover")
async def discover_robots(
    request: Request,
    body: Optional[DiscoverRequest] = None,
) -> Dict[str, Any]:
    """Run 3-tier LAN auto-discovery and optionally auto-register discovered PuppyPi robots."""
    store = _robot_store(request)
    req = body or DiscoverRequest()
    saved_ips = [r["ip_address"] for r in store.list_robots() if r.get("ip_address")]
    candidates = await discover_robots_on_lan(cidrs=req.cidrs, saved_ips=saved_ips)

    registered: List[Dict[str, Any]] = []
    if req.auto_register:
        for cand in candidates:
            existing = store.get_robot_by_ip(cand["ip"])
            default_pw = None if existing is not None else "raspberrypi"
            rec = store.upsert_robot(
                {
                    "ip_address": cand["ip"],
                    "name": (existing or {}).get("name") or f"PuppyPi ({cand['ip']})",
                    "model": cand.get("model_guess") or "Hiwonder PuppyPi Pro",
                    "serial_number": cand.get("serial_number"),
                    "ssh_user": (existing or {}).get("ssh_user") or "pi",
                    "rosbridge_port": 9090,
                    "video_port": 8080,
                    "status": "online" if cand.get("rosbridge_open") else "discovered",
                    "capabilities": {
                        "rosbridge_open": bool(cand.get("rosbridge_open")),
                        "video_open": bool(cand.get("video_open")),
                        "ssh_open": bool(cand.get("ssh_open")),
                        "ssh_banner": cand.get("ssh_banner") or "",
                    },
                },
                ssh_password=default_pw,
            )
            registered.append(rec)

    return {
        "discovered": candidates,
        "robots": registered if req.auto_register else store.list_robots(),
        "count": len(candidates),
    }


@router.post("")
async def register_robot(body: RegisterRobotRequest, request: Request) -> Dict[str, Any]:
    """Manually register or update a robot by IP address and SSH credentials."""
    store = _robot_store(request)
    try:
        robot = store.upsert_robot(
            {
                "ip_address": body.ip_address.strip(),
                "name": body.name or f"PuppyPi ({body.ip_address.strip()})",
                "model": body.model,
                "serial_number": body.serial_number,
                "mac_address": body.mac_address,
                "ssh_user": body.ssh_user,
                "rosbridge_port": body.rosbridge_port,
                "video_port": body.video_port,
                "status": "registered",
            },
            ssh_password=body.ssh_password,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"robot": robot}


@router.get("/{robot_id}")
async def get_robot_detail(
    robot_id: str,
    request: Request,
    sbom_layer: Optional[str] = Query(default=None),
    sbom_query: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    """Return a single robot's profile, hardware BOM devices, and software SBOM packages."""
    store = _robot_store(request)
    robot = _require_robot(store, robot_id)
    devices = store.list_robot_devices(robot_id)
    sbom = store.list_robot_sbom(robot_id, layer=sbom_layer, query=sbom_query)
    return {"robot": robot, "devices": devices, "sbom": sbom}


@router.delete("/{robot_id}")
async def delete_robot(robot_id: str, request: Request) -> Dict[str, Any]:
    """Delete a robot from the fleet store and detach its Neo4j node if configured."""
    store = _robot_store(request)
    if not store.delete_robot(robot_id):
        raise HTTPException(status_code=404, detail=f"Robot {robot_id} not found.")
    rt = _runtime(request)
    if rt.neo4j.enabled:
        rt.neo4j._run_write_with_retry(
            "MATCH (r:Robot {id: $robot_id}) OPTIONAL MATCH (r)-[:HAS_HARDWARE|RUNS_CONTAINER]->(n) DETACH DELETE n, r",
            {"robot_id": robot_id},
        )
    return {"deleted": True, "robot_id": robot_id}


# --- Network Interfaces, Active IP Switch & Update/Feature Readiness ---


@router.get("/{robot_id}/network")
async def get_robot_network(robot_id: str, request: Request) -> Dict[str, Any]:
    """Query live Wi-Fi, Ethernet, and active ROS Docker container state on the robot via SSH."""
    store = _robot_store(request)
    robot = _require_robot(store, robot_id)
    ssh_pw = store.get_robot_ssh_password(robot_id)
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        net = await collect_network_interfaces(
            ip=robot["ip_address"],
            user=robot["ssh_user"],
            password=ssh_pw,
        )
        upd_payload: Dict[str, Any] = {
            "id": robot_id,
            "ip_address": robot["ip_address"],
            "capabilities": {
                "network": net,
                "ros_containers": net.get("ros_containers") or [],
            },
        }
        if net.get("active_ros_distro"):
            upd_payload["active_ros_distro"] = net["active_ros_distro"]
        store.upsert_robot(upd_payload)
        return {
            "robot_id": robot_id,
            "active_ip": robot["ip_address"],
            "collected_at": now_iso,
            "source": "live",
            "error": None,
            **net,
        }
    except (SSHAuthError, SSHCommandError, ValueError) as exc:
        cached = (robot.get("capabilities") or {}).get("network")
        if isinstance(cached, dict):
            return {
                "robot_id": robot_id,
                "active_ip": robot["ip_address"],
                "collected_at": robot.get("last_seen_at"),
                "source": "cached",
                "error": str(exc),
                "wifi": cached.get("wifi"),
                "ethernet": cached.get("ethernet") or [],
                "interfaces": cached.get("interfaces") or [],
                "active_ros_distro": robot.get("active_ros_distro") or cached.get("active_ros_distro"),
                "ros_containers": (robot.get("capabilities") or {}).get("ros_containers") or cached.get("ros_containers") or [],
            }
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.put("/{robot_id}/active-ip")
async def set_robot_active_ip(
    robot_id: str,
    body: ActiveIpRequest,
    request: Request,
) -> Dict[str, Any]:
    """Switch the active control/SSH IPv4 address for a robot (e.g. Ethernet -> Wi-Fi)."""
    store = _robot_store(request)
    _require_robot(store, robot_id)
    ip_str = body.ip_address.strip()
    try:
        addr = ipaddress.ip_address(ip_str)
        if not isinstance(addr, ipaddress.IPv4Address):
            raise ValueError("Only IPv4 addresses are supported")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid IPv4 address: {ip_str!r}") from exc

    updated = store.upsert_robot({"id": robot_id, "ip_address": str(addr)})
    return {"robot": updated}


@router.post("/{robot_id}/update-check")
async def check_robot_updates(robot_id: str, request: Request) -> Dict[str, Any]:
    """Run live PyPI update checks, ROS/OS lifecycle audit, and Hardware Feature Readiness Matrix."""
    store = _robot_store(request)
    rt = _runtime(request)
    robot = _require_robot(store, robot_id)
    devices = store.list_robot_devices(robot_id)
    sbom = store.list_robot_sbom(robot_id)
    ssh_pw = store.get_robot_ssh_password(robot_id)
    return await run_robot_update_and_feature_check(
        robot=robot,
        devices=devices,
        sbom=sbom,
        openrouter_configured=rt.openrouter_configured,
        ssh_info={"ip": robot["ip_address"], "user": robot["ssh_user"], "password": ssh_pw} if ssh_pw else None,
    )


def _active_ros_container(robot: Dict[str, Any]) -> str:
    return "puppypi_ros2" if _robot_ros_mode(robot) == "ros2" else "puppypi"


@router.post("/{robot_id}/updates/dry-run")
async def robot_updates_dry_run(
    robot_id: str,
    body: UpdateTrackRequest,
    request: Request,
) -> Dict[str, Any]:
    """Preview planned Debian 12 apt or ROS container pip upgrades without modifying the robot."""
    store = _robot_store(request)
    robot = _require_robot(store, robot_id)
    ssh_pw = store.get_robot_ssh_password(robot_id)
    track = body.track.strip().lower()
    if track not in ("host_apt", "ros_pip"):
        raise HTTPException(status_code=400, detail="track must be 'host_apt' or 'ros_pip'.")
    try:
        if track == "host_apt":
            res = await preview_apt_updates(robot["ip_address"], robot["ssh_user"], ssh_pw)
        else:
            container = _active_ros_container(robot)
            res = await preview_pip_updates(
                robot["ip_address"], robot["ssh_user"], ssh_pw, container, body.packages or []
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SSHAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except (SSHCommandError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    job = store.record_update_job(
        robot_id,
        {
            "track": track,
            "action": "dry_run",
            "status": res.get("status") or ("ok" if res.get("ok") else "failed"),
            "packages": body.packages or [p["name"] for p in (res.get("packages") or [])][:30],
            "stdout_tail": res.get("stdout_tail", ""),
            "stderr_tail": res.get("stderr_tail", ""),
        },
    )
    return {**res, "job": job}


@router.post("/{robot_id}/updates/download")
async def robot_updates_download(
    robot_id: str,
    body: UpdateTrackRequest,
    request: Request,
) -> Dict[str, Any]:
    """Pre-download Debian 12 .deb packages or ROS Python wheels without installing."""
    store = _robot_store(request)
    robot = _require_robot(store, robot_id)
    ssh_pw = store.get_robot_ssh_password(robot_id)
    track = body.track.strip().lower()
    if track not in ("host_apt", "ros_pip"):
        raise HTTPException(status_code=400, detail="track must be 'host_apt' or 'ros_pip'.")
    try:
        if track == "host_apt":
            res = await download_apt_updates(robot["ip_address"], robot["ssh_user"], ssh_pw, body.packages)
        else:
            container = _active_ros_container(robot)
            res = await download_pip_updates(
                robot["ip_address"], robot["ssh_user"], ssh_pw, container, body.packages or []
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SSHAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except (SSHCommandError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    job = store.record_update_job(
        robot_id,
        {
            "track": track,
            "action": "download",
            "status": res.get("status") or ("downloaded" if res.get("ok") else "failed"),
            "packages": body.packages or [],
            "stdout_tail": res.get("stdout_tail", ""),
            "stderr_tail": res.get("stderr_tail", ""),
        },
    )
    return {**res, "job": job}


@router.post("/{robot_id}/updates/apply")
async def robot_updates_apply(
    robot_id: str,
    body: UpdateApplyRequest,
    request: Request,
) -> Dict[str, Any]:
    """Snapshot (for ros_pip), apply selected updates, run 6-point smoke tests, and refresh SBOM if green."""
    store = _robot_store(request)
    robot = _require_robot(store, robot_id)
    ssh_pw = store.get_robot_ssh_password(robot_id)
    track = body.track.strip().lower()
    if track not in ("host_apt", "ros_pip"):
        raise HTTPException(status_code=400, detail="track must be 'host_apt' or 'ros_pip'.")
    try:
        if track == "host_apt":
            res = await apply_apt_updates(robot["ip_address"], robot["ssh_user"], ssh_pw, body.packages)
        else:
            container = _active_ros_container(robot)
            res = await apply_pip_updates(
                ip=robot["ip_address"],
                user=robot["ssh_user"],
                password=ssh_pw,
                container=container,
                packages=body.packages or [],
                allow_abi_sensitive=body.allow_abi_sensitive,
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SSHAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except (SSHCommandError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    smoke_tests: Optional[Dict[str, Any]] = None
    if res.get("ok") and body.run_tests:
        smoke_tests = await run_post_update_smoke_tests(
            ip=robot["ip_address"],
            user=robot["ssh_user"],
            password=ssh_pw,
            ros_mode=_robot_ros_mode(robot),
            updated_packages=body.packages if track == "ros_pip" else None,
            rosbridge_port=int(robot.get("rosbridge_port") or 9090),
            video_port=int(robot.get("video_port") or 8080),
        )
        res["smoke_tests"] = smoke_tests
        if smoke_tests.get("passed"):
            try:
                cat = await collect_robot_catalogue(
                    ip=robot["ip_address"],
                    user=robot["ssh_user"],
                    password=ssh_pw,
                    robot_meta=robot,
                )
                store.save_robot_catalogue(
                    robot_id=robot_id,
                    devices=cat["devices"],
                    sbom_packages=cat["sbom_packages"],
                    hbom_sbom=cat["hbom_sbom"],
                    robot_updates=cat["robot_updates"],
                )
            except Exception as cat_exc:
                sys.stderr.write(f"[robots.updates.apply] Post-update SBOM re-catalogue skipped: {cat_exc}\n")

    job_status = str(res.get("status") or ("applied" if res.get("ok") else "failed"))
    if smoke_tests is not None and not smoke_tests.get("passed"):
        job_status = "applied_smoke_failed"
    job = store.record_update_job(
        robot_id,
        {
            "track": track,
            "action": "apply",
            "status": job_status,
            "packages": body.packages or [p["name"] for p in (res.get("packages") or [])][:30],
            "rollback_tag": res.get("rollback_tag"),
            "smoke_tests": smoke_tests,
            "stdout_tail": res.get("stdout_tail", ""),
            "stderr_tail": res.get("stderr_tail", ""),
        },
    )
    return {**res, "status": job_status, "job": job}


@router.post("/{robot_id}/updates/test")
async def robot_updates_test(
    robot_id: str,
    request: Request,
    body: Optional[UpdateTestRequest] = None,
) -> Dict[str, Any]:
    """Run standalone 6-point hardware & ROS smoke tests against the robot and log the result."""
    store = _robot_store(request)
    robot = _require_robot(store, robot_id)
    ssh_pw = store.get_robot_ssh_password(robot_id)
    req = body or UpdateTestRequest()
    smoke = await run_post_update_smoke_tests(
        ip=robot["ip_address"],
        user=robot["ssh_user"],
        password=ssh_pw,
        ros_mode=_robot_ros_mode(robot),
        updated_packages=req.packages,
        rosbridge_port=int(robot.get("rosbridge_port") or 9090),
        video_port=int(robot.get("video_port") or 8080),
    )
    job = store.record_update_job(
        robot_id,
        {
            "track": "smoke_test",
            "action": "test",
            "status": "passed" if smoke["passed"] else "failed",
            "packages": req.packages or [],
            "smoke_tests": smoke,
        },
    )
    return {
        "ok": smoke["passed"],
        "track": "smoke_test",
        "action": "test",
        "status": "passed" if smoke["passed"] else "failed",
        "smoke_tests": smoke,
        "job": job,
    }


@router.post("/{robot_id}/updates/rollback")
async def robot_updates_rollback(
    robot_id: str,
    body: UpdateRollbackRequest,
    request: Request,
) -> Dict[str, Any]:
    """Roll back a ROS Docker container to a ``pre-update-*`` snapshot and run 6-point smoke tests."""
    store = _robot_store(request)
    robot = _require_robot(store, robot_id)
    ssh_pw = store.get_robot_ssh_password(robot_id)
    container = body.container or (body.rollback_tag.split(":", 1)[0] if ":" in body.rollback_tag else _active_ros_container(robot))
    try:
        res = await rollback_container_snapshot(
            ip=robot["ip_address"],
            user=robot["ssh_user"],
            password=ssh_pw,
            container=container,
            rollback_tag=body.rollback_tag,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SSHAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except (SSHCommandError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    smoke_tests: Optional[Dict[str, Any]] = None
    if res.get("ok"):
        smoke_tests = await run_post_update_smoke_tests(
            ip=robot["ip_address"],
            user=robot["ssh_user"],
            password=ssh_pw,
            ros_mode="ros2" if container == "puppypi_ros2" else "ros1",
            rosbridge_port=int(robot.get("rosbridge_port") or 9090),
            video_port=int(robot.get("video_port") or 8080),
        )
        res["smoke_tests"] = smoke_tests

    job = store.record_update_job(
        robot_id,
        {
            "track": "ros_pip",
            "action": "rollback",
            "status": res.get("status") or ("rolled_back" if res.get("ok") else "failed"),
            "rollback_tag": body.rollback_tag,
            "smoke_tests": smoke_tests,
            "stdout_tail": res.get("stdout_tail", ""),
            "stderr_tail": res.get("stderr_tail", ""),
        },
    )
    return {**res, "job": job}


@router.get("/{robot_id}/updates/history")
async def robot_updates_history(robot_id: str, request: Request) -> Dict[str, Any]:
    """Return recorded update/test jobs from the DB and live ``pre-update-*`` Docker snapshots."""
    store = _robot_store(request)
    robot = _require_robot(store, robot_id)
    ssh_pw = store.get_robot_ssh_password(robot_id)
    jobs = store.list_update_jobs(robot_id, limit=25)
    snapshots = await list_container_snapshots(robot["ip_address"], robot["ssh_user"], ssh_pw) if ssh_pw else []
    return {"robot_id": robot_id, "jobs": jobs, "snapshots": snapshots}


# --- Hardware BOM + Software SBOM Cataloguing & CycloneDX 1.6 Export ---


@router.post("/{robot_id}/catalogue")
async def catalogue_robot(robot_id: str, request: Request) -> Dict[str, Any]:
    """Run SSH hardware BOM + Docker/ROS + 6-layer SBOM scan, persist to DB, and sync Neo4j."""
    store = _robot_store(request)
    robot = _require_robot(store, robot_id)
    ssh_password = store.get_robot_ssh_password(robot_id)

    try:
        cat = await collect_robot_catalogue(
            ip=robot["ip_address"],
            user=robot["ssh_user"],
            password=ssh_password,
            robot_meta=robot,
        )
    except SSHAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except (SSHCommandError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    updated_robot = store.save_robot_catalogue(
        robot_id=robot_id,
        devices=cat["devices"],
        sbom_packages=cat["sbom_packages"],
        hbom_sbom=cat["hbom_sbom"],
        robot_updates=cat["robot_updates"],
    )
    assert updated_robot is not None
    stored_devices = store.list_robot_devices(robot_id)
    stored_sbom = store.list_robot_sbom(robot_id)
    neo4j_synced = _sync_robot_to_neo4j(
        _runtime(request),
        updated_robot,
        stored_devices,
        cat.get("containers") or [],
    )
    return {
        "robot": updated_robot,
        "devices": stored_devices,
        "sbom": stored_sbom,
        "device_count": len(stored_devices),
        "sbom_count": len(stored_sbom),
        "containers": cat.get("containers") or [],
        "live_config": cat.get("live_config") or {},
        "network": cat.get("network"),
        "neo4j_synced": neo4j_synced,
    }


@router.get("/{robot_id}/export/cyclonedx")
async def export_robot_cyclonedx(robot_id: str, request: Request) -> Response:
    """Download the OWASP CycloneDX 1.6 Robot Hardware BOM + Software SBOM JSON document."""
    store = _robot_store(request)
    robot = _require_robot(store, robot_id)
    doc = robot.get("hbom_sbom")
    if not isinstance(doc, dict) or doc.get("bomFormat") != "CycloneDX":
        devices = store.list_robot_devices(robot_id)
        sbom = store.list_robot_sbom(robot_id)
        containers = (robot.get("capabilities") or {}).get("containers") or []
        live_config = (robot.get("capabilities") or {}).get("live_config") or {}
        doc = build_robot_cyclonedx_hbom_sbom(
            robot_meta=robot,
            devices=devices,
            sbom_packages=sbom,
            containers=containers,
            live_config=live_config,
        )
    content = json.dumps(doc, indent=2).encode("utf-8")
    return Response(
        content=content,
        media_type="application/vnd.cyclonedx+json",
        headers={"Content-Disposition": f'attachment; filename="robot-{robot_id}-hbom-sbom.cdx.json"'},
    )


# --- Live ROS 1 / ROS 2 Dual-Mode Control Endpoints ---


async def _preempt_autonomous_loops(
    request: Request,
    robot_id: str,
    robot: Dict[str, Any],
    always_stop: bool = False,
) -> None:
    """Stop active patrol and autonomous explorer loops before manual control or E-STOP."""
    ip = robot.get("ip_address")
    port = int(robot.get("rosbridge_port") or 9090)
    ros_ver = _robot_ros_mode(robot)

    patrol_mgr = getattr(request.app.state, "patrol_manager", None)
    if patrol_mgr is not None:
        is_active = bool(patrol_mgr.get_status(robot_id).get("active"))
        if always_stop or is_active:
            try:
                if is_active and ip:
                    await patrol_mgr.stop(robot_id, ip=ip, rosbridge_port=port, ros_version=ros_ver)
                else:
                    await patrol_mgr.stop(robot_id)
            except Exception as exc:
                sys.stderr.write(f"[robots.preempt] Stopping patrol failed for {robot_id}: {exc}\n")

    explorer_mgr = getattr(request.app.state, "explorer_manager", None)
    if explorer_mgr is not None:
        is_active = bool(explorer_mgr.get_status(robot_id).get("active"))
        if always_stop or is_active:
            try:
                if is_active and ip:
                    await explorer_mgr.stop(robot_id, ip=ip, rosbridge_port=port, ros_version=ros_ver)
                else:
                    await explorer_mgr.stop(robot_id)
            except Exception as exc:
                sys.stderr.write(f"[robots.preempt] Stopping explorer failed for {robot_id}: {exc}\n")


@router.post("/{robot_id}/estop")
async def robot_estop(robot_id: str, request: Request) -> Dict[str, Any]:
    """Trigger immediate emergency stop (zero velocity + ``/puppy_control/go_home`` + exit CV, patrol, explorer & AI follow)."""
    robot = _require_robot(_robot_store(request), robot_id)
    await _preempt_autonomous_loops(request, robot_id, robot, always_stop=True)
    ai_vision = getattr(request.app.state, "ai_vision_engine", None)
    if ai_vision is not None:
        try:
            ai_vision.stop_autonomous_motion(robot_id)
        except Exception as exc:
            sys.stderr.write(f"[robots.estop] Stopping AI vision motion failed for {robot_id}: {exc}\n")
    conv_mgr = getattr(request.app.state, "conversation_manager", None)
    if conv_mgr is not None:
        try:
            await conv_mgr.stop(robot_id)
        except Exception as exc:
            sys.stderr.write(f"[robots.estop] Stopping conversation loop failed for {robot_id}: {exc}\n")
    sentry_mgr = getattr(request.app.state, "sentry_manager", None)
    if sentry_mgr is not None:
        try:
            await sentry_mgr.disarm(robot_id)
        except Exception as exc:
            sys.stderr.write(f"[robots.estop] Disarming sentry failed for {robot_id}: {exc}\n")
    try:
        return await trigger_estop(
            robot["ip_address"],
            int(robot.get("rosbridge_port") or 9090),
            ros_version=_robot_ros_mode(robot),
            robot_id=robot_id,
        )
    except ConnectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/{robot_id}/control/go-home")
async def robot_control_go_home(robot_id: str, request: Request) -> Dict[str, Any]:
    """Stop any active autonomous loops/CV node and invoke ``/puppy_control/go_home`` (``std_srvs/Empty``)."""
    robot = _require_robot(_robot_store(request), robot_id)
    await _preempt_autonomous_loops(request, robot_id, robot, always_stop=False)
    try:
        return await call_go_home(
            ip=robot["ip_address"],
            port=int(robot.get("rosbridge_port") or 9090),
            ros_version=_robot_ros_mode(robot),
            robot_id=robot_id,
        )
    except ConnectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/{robot_id}/control/mark-time")
async def robot_control_mark_time(
    robot_id: str,
    body: MarkTimeCommandRequest,
    request: Request,
) -> Dict[str, Any]:
    """Stop any active CV node and toggle ``/puppy_control/set_mark_time``."""
    robot = _require_robot(_robot_store(request), robot_id)
    try:
        return await set_mark_time(
            ip=robot["ip_address"],
            enabled=body.enabled,
            port=int(robot.get("rosbridge_port") or 9090),
            ros_version=_robot_ros_mode(robot),
            robot_id=robot_id,
        )
    except ConnectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/{robot_id}/control/velocity")
async def robot_control_velocity(
    robot_id: str,
    body: VelocityCommandRequest,
    request: Request,
) -> Dict[str, Any]:
    """Preempt active autonomous loops and publish a safety-clamped velocity command."""
    robot = _require_robot(_robot_store(request), robot_id)
    await _preempt_autonomous_loops(request, robot_id, robot, always_stop=False)
    try:
        return await publish_velocity(
            ip=robot["ip_address"],
            port=int(robot.get("rosbridge_port") or 9090),
            x=body.x,
            y=body.y,
            yaw_rate=body.yaw_rate,
            ros_version=_robot_ros_mode(robot),
            use_autogait=body.use_autogait,
            robot_id=robot_id,
        )
    except ConnectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/{robot_id}/control/pose")
async def robot_control_pose(
    robot_id: str,
    body: PoseCommandRequest,
    request: Request,
) -> Dict[str, Any]:
    """Publish a safety-clamped pose or named preset (two-step ``run_time=0`` -> ``run_time=N``)."""
    robot = _require_robot(_robot_store(request), robot_id)
    try:
        return await publish_pose(
            ip=robot["ip_address"],
            port=int(robot.get("rosbridge_port") or 9090),
            roll=body.roll,
            pitch=body.pitch,
            yaw=body.yaw,
            height=body.height,
            x_shift=body.x_shift,
            stance_x=body.stance_x,
            stance_y=body.stance_y,
            run_time=body.run_time,
            preset=body.preset,
            ros_version=_robot_ros_mode(robot),
            robot_id=robot_id,
        )
    except ConnectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/{robot_id}/control/gait")
async def robot_control_gait(
    robot_id: str,
    body: GaitCommandRequest,
    request: Request,
) -> Dict[str, Any]:
    """Publish safety-clamped gait timing parameters or a named preset."""
    robot = _require_robot(_robot_store(request), robot_id)
    try:
        return await publish_gait(
            ip=robot["ip_address"],
            port=int(robot.get("rosbridge_port") or 9090),
            overlap_time=body.overlap_time,
            swing_time=body.swing_time,
            clearance_time=body.clearance_time,
            z_clearance=body.z_clearance,
            preset=body.preset,
            ros_version=_robot_ros_mode(robot),
            robot_id=robot_id,
        )
    except ConnectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/{robot_id}/control/action")
async def robot_control_action(
    robot_id: str,
    body: ActionCommandRequest,
    request: Request,
) -> Dict[str, Any]:
    """Preempt active autonomous loops and invoke ``/puppy_control/runActionGroup``."""
    robot = _require_robot(_robot_store(request), robot_id)
    await _preempt_autonomous_loops(request, robot_id, robot, always_stop=False)
    try:
        return await run_action(
            ip=robot["ip_address"],
            port=int(robot.get("rosbridge_port") or 9090),
            name=body.name,
            wait=body.wait,
            ros_version=_robot_ros_mode(robot),
            robot_id=robot_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ConnectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/{robot_id}/control/servo")
async def robot_control_servo(
    robot_id: str,
    body: ServoCommandRequest,
    request: Request,
) -> Dict[str, Any]:
    """Publish a safety-clamped direct servo PWM pulse (legs 1..8, 2-DOF arm 9..11)."""
    robot = _require_robot(_robot_store(request), robot_id)
    try:
        return await set_servo(
            ip=robot["ip_address"],
            port=int(robot.get("rosbridge_port") or 9090),
            servo_id=body.id,
            pulse=body.pulse,
            time_ms=body.time,
            ros_version=_robot_ros_mode(robot),
            robot_id=robot_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ConnectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/{robot_id}/control/buzzer")
async def robot_control_buzzer(
    robot_id: str,
    body: BuzzerCommandRequest,
    request: Request,
) -> Dict[str, Any]:
    """Trigger the STM32 expansion board buzzer."""
    robot = _require_robot(_robot_store(request), robot_id)
    try:
        return await set_buzzer(
            ip=robot["ip_address"],
            port=int(robot.get("rosbridge_port") or 9090),
            freq=body.freq,
            on_time=body.on_time,
            off_time=body.off_time,
            repeat=body.repeat,
            ros_version=_robot_ros_mode(robot),
        )
    except ConnectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/{robot_id}/control/rgb")
async def robot_control_rgb(
    robot_id: str,
    body: RgbCommandRequest,
    request: Request,
) -> Dict[str, Any]:
    """Set RGB LED colors on the STM32 expansion board."""
    robot = _require_robot(_robot_store(request), robot_id)
    try:
        return await set_rgb(
            ip=robot["ip_address"],
            port=int(robot.get("rosbridge_port") or 9090),
            data=[p.model_dump() for p in body.data],
            ros_version=_robot_ros_mode(robot),
        )
    except ConnectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/{robot_id}/control/oled")
async def robot_control_oled(
    robot_id: str,
    body: OledCommandRequest,
    request: Request,
) -> Dict[str, Any]:
    """Display text on the STM32 OLED status screen."""
    robot = _require_robot(_robot_store(request), robot_id)
    try:
        return await set_oled(
            ip=robot["ip_address"],
            port=int(robot.get("rosbridge_port") or 9090),
            index=body.index,
            text=body.text,
            ros_version=_robot_ros_mode(robot),
        )
    except ConnectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/{robot_id}/control/vision-mode")
async def robot_control_vision_mode(
    robot_id: str,
    body: VisionModeRequest,
    request: Request,
) -> Dict[str, Any]:
    """Activate or stop a dormant Hiwonder CV vision node with automatic 2.5s watchdog heartbeat."""
    robot = _require_robot(_robot_store(request), robot_id)
    try:
        return await set_vision_mode(
            robot_id=robot_id,
            ip=robot["ip_address"],
            mode=body.mode,
            port=int(robot.get("rosbridge_port") or 9090),
            ros_version=_robot_ros_mode(robot),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ConnectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# --- Bidirectional ROSBridge WebSocket Proxy with 0.5s Dead-Man's Switch ---


@router.websocket("/{robot_id}/rosbridge")
async def robot_rosbridge_ws(websocket: WebSocket, robot_id: str) -> None:
    """Proxy ROSBridge JSON v2 WebSocket traffic with server-side 0.5s dead-man's switch."""
    await websocket.accept()
    store: RobotStoreProtocol = websocket.app.state.robot_store
    rt: TwinScanRuntimeState = websocket.app.state.runtime
    robot = store.get_robot(robot_id)
    if not robot:
        await websocket.send_json({"op": "proxy_error", "error": f"Robot {robot_id} not found."})
        await websocket.close(code=4404)
        return

    def _update_battery(mv: int) -> None:
        try:
            store.upsert_robot({"id": robot_id, "ip_address": robot["ip_address"], "battery_mv": mv})
        except Exception:
            pass

    await proxy_rosbridge_websocket(
        client_ws=websocket,
        robot_ip=robot["ip_address"],
        robot_port=int(robot.get("rosbridge_port") or 9090),
        runtime_state=rt,
        deadman_timeout_s=0.5,
        on_battery_mv=_update_battery,
    )


# --- Live FPV MJPEG Proxy, Snapshot, and Snap-to-Vision Pipeline ---


@router.get("/{robot_id}/video/stream")
async def robot_video_stream(
    robot_id: str,
    request: Request,
    topic: Optional[str] = Query(default=None),
) -> StreamingResponse:
    """Proxy live MJPEG stream from PuppyPi ``web_video_server`` over single origin."""
    robot = _require_robot(_robot_store(request), robot_id)
    try:
        safe_topic = _resolve_camera_topic(robot, topic)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    async def _guarded_stream():
        async for chunk in stream_robot_video(
            ip=robot["ip_address"],
            port=int(robot.get("video_port") or 8080),
            topic=safe_topic,
        ):
            if await request.is_disconnected():
                return
            yield chunk

    return StreamingResponse(
        _guarded_stream(),
        media_type="multipart/x-mixed-replace; boundary=boundarydonotcross",
    )


@router.get("/{robot_id}/video/snapshot")
async def robot_video_snapshot(
    robot_id: str,
    request: Request,
    topic: Optional[str] = Query(default=None),
) -> Response:
    """Fetch and return a single live JPEG frame from PuppyPi ``web_video_server``."""
    robot = _require_robot(_robot_store(request), robot_id)
    try:
        _resolve_camera_topic(robot, topic)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        jpeg_bytes, _ = await _fetch_snapshot_with_fallback(
            robot=robot,
            requested_topic=topic,
            timeout=5.0,
            retries=2,
        )
    except ConnectionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(content=jpeg_bytes, media_type="image/jpeg")


@router.post("/{robot_id}/video/snap-to-vision")
async def robot_snap_to_vision(
    robot_id: str,
    request: Request,
    body: Optional[SnapToVisionRequest] = None,
) -> Dict[str, Any]:
    """Grab a live JPEG from PuppyPi FPV camera, run Vision + LiDAR raycast, and store in PG."""
    store = _robot_store(request)
    rt = _runtime(request)
    robot = _require_robot(store, robot_id)
    params = body or SnapToVisionRequest()

    try:
        _resolve_camera_topic(robot, params.topic)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        image_bytes, safe_topic = await _fetch_snapshot_with_fallback(
            robot=robot,
            requested_topic=params.topic,
            timeout=5.0,
            retries=2,
        )
    except ConnectionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    fname = f"puppypi-{robot_id[:8]}-{int(time.time())}.jpg"
    stored_orig = rt.repo.store_file(
        filename=fname,
        content_type="image/jpeg",
        data=image_bytes,
        category="equipment_photo",
        space_id=rt.active_space_id or None,
        metadata={"variant": "original", "source": "puppypi_fpv", "robot_id": robot_id, "topic": safe_topic},
    )

    enhanced_file_id: Optional[str] = None
    try:
        enhanced_bytes, _ = preprocess_industrial_image(image_bytes)
        stored_enh = rt.repo.store_file(
            filename=f"enhanced-{fname}",
            content_type="image/jpeg",
            data=enhanced_bytes,
            category="equipment_photo_enhanced",
            space_id=rt.active_space_id or None,
            metadata={"variant": "clahe_unsharp", "parent_file_id": stored_orig["id"], "robot_id": robot_id},
        )
        enhanced_file_id = stored_enh["id"]
    except Exception:
        pass

    t0 = time.perf_counter()
    try:
        result = await rt.vision.analyze_equipment_image(
            image_bytes=image_bytes,
            model=params.model,
            consensus=params.consensus,
            context_hint=params.context_hint,
        )
    except Exception as exc:
        sys.stderr.write(f"[robots.snap_to_vision] Vision analysis failed for robot {robot_id}: {exc}\n")
        raise HTTPException(
            status_code=502,
            detail=(
                f"PuppyPi FPV frame captured ({len(image_bytes)} B), but Vision AI analysis failed: {exc}. "
                "Add a valid OpenRouter API key in /config."
            ),
        ) from exc
    latency_ms = int((time.perf_counter() - t0) * 1000)

    rt.repo.log_vision_usage(
        {
            "operation": "robot_fpv_consensus" if params.consensus else "robot_fpv_extract",
            "model": result.model_used,
            "latency_ms": latency_ms,
            "confidence": result.confidence,
            "consensus_verified": result.consensus_verified,
            "status": "ok",
        }
    )

    fov = params.camera_fov_deg if params.camera_fov_deg is not None else rt.default_camera_fov_deg
    suggested_pose = raycast_camera_to_lidar(
        bbox_norm=result.primary_bbox_norm,
        lidar_points=rt.latest_points,
        camera_fov_deg=fov,
        camera_yaw_deg=params.camera_yaw_deg,
    )

    return {
        "extraction": result.model_dump(),
        "image_file_id": stored_orig["id"],
        "enhanced_file_id": enhanced_file_id,
        "image_url": stored_orig["url"],
        "enhanced_url": f"/api/files/{enhanced_file_id}" if enhanced_file_id else None,
        "suggested_pose": suggested_pose,
        "latency_ms": latency_ms,
        "robot_id": robot_id,
        "topic": safe_topic,
    }


# --- Remote SSH Configuration Endpoints ---


@router.put("/{robot_id}/config/wifi")
async def robot_config_wifi(
    robot_id: str,
    body: WifiConfigRequest,
    request: Request,
) -> Dict[str, Any]:
    """Update PuppyPi Wi-Fi AP/STA configuration atomically across both ``wifi_conf.py`` files."""
    store = _robot_store(request)
    robot = _require_robot(store, robot_id)
    ssh_pw = store.get_robot_ssh_password(robot_id)
    wifi_pw = body.wifi_password if body.wifi_password is not None else (body.password or "")
    try:
        res = await configure_wifi(
            ip=robot["ip_address"],
            user=robot["ssh_user"],
            password=ssh_pw,
            mode=body.mode,
            ssid=body.ssid,
            wifi_password=wifi_pw,
            country_code=body.country_code,
            restart_service=body.restart_service,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SSHAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except SSHCommandError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"robot_id": robot_id, **res}


@router.put("/{robot_id}/config/password")
async def robot_config_password(
    robot_id: str,
    body: PasswordConfigRequest,
    request: Request,
) -> Dict[str, Any]:
    """Change Linux password for ``pi`` or ``root`` and sync Fernet-encrypted store if matching ``ssh_user``."""
    store = _robot_store(request)
    robot = _require_robot(store, robot_id)
    ssh_pw = store.get_robot_ssh_password(robot_id)
    try:
        res = await change_password(
            ip=robot["ip_address"],
            user=robot["ssh_user"],
            password=ssh_pw,
            target_user=body.target_user,
            new_password=body.new_password,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SSHAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except SSHCommandError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    credential_synced = False
    if body.target_user.strip() == robot["ssh_user"]:
        store.update_robot_credentials(robot_id, ssh_password=body.new_password)
        credential_synced = True

    return {"robot_id": robot_id, "credential_synced": credential_synced, **res}


@router.put("/{robot_id}/config/mechanics")
async def robot_config_mechanics(
    robot_id: str,
    body: MechanicsConfigRequest,
    request: Request,
) -> Dict[str, Any]:
    """Update ``with_arm``/``x_shift`` inside active ROS 1/2 container's ``puppy.py`` and ``servo_deviation.json``."""
    store = _robot_store(request)
    robot = _require_robot(store, robot_id)
    ssh_pw = store.get_robot_ssh_password(robot_id)
    arm_val = int(body.with_arm) if body.with_arm is not None else None
    ros_mode = _robot_ros_mode(robot)
    try:
        res = await configure_mechanics(
            ip=robot["ip_address"],
            user=robot["ssh_user"],
            password=ssh_pw,
            with_arm=arm_val,
            x_shift=body.x_shift,
            servo_deviations=body.servo_deviations,
            ros_version=ros_mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SSHAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except SSHCommandError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    live_cfg = dict((robot.get("capabilities") or {}).get("live_config") or {})
    if arm_val is not None:
        live_cfg["with_arm"] = arm_val
    if body.x_shift is not None:
        live_cfg["x_shift"] = body.x_shift
    if "servo_deviations" in res:
        live_cfg["servo_deviations"] = res["servo_deviations"]
    store.upsert_robot(
        {"id": robot_id, "ip_address": robot["ip_address"], "capabilities": {"live_config": live_cfg}}
    )
    return {"robot_id": robot_id, **res}


@router.put("/{robot_id}/config/ros")
async def robot_config_ros(
    robot_id: str,
    body: RosAiConfigRequest,
    request: Request,
) -> Dict[str, Any]:
    """Switch PuppyPi between ROS 1 Noetic and ROS 2 Humble, launch ROS 2 stack, and persist active distro."""
    store = _robot_store(request)
    robot = _require_robot(store, robot_id)
    ssh_pw = store.get_robot_ssh_password(robot_id)
    try:
        res = await configure_ros_and_ai(
            ip=robot["ip_address"],
            user=robot["ssh_user"],
            password=ssh_pw,
            target_ros=body.target_ros,
            asr_language=body.asr_language,
            ros_domain_id=body.ros_domain_id,
            rmw_implementation=body.rmw_implementation,
            persist_boot=body.persist_boot,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SSHAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except SSHCommandError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    upd: Dict[str, Any] = {"id": robot_id, "ip_address": robot["ip_address"]}
    if res.get("active_ros_distro"):
        upd["active_ros_distro"] = res["active_ros_distro"]
    elif body.target_ros:
        upd["active_ros_distro"] = "humble" if normalize_ros_mode(body.target_ros) == "ros2" else "noetic"

    live_cfg = dict((robot.get("capabilities") or {}).get("live_config") or {})
    if res.get("asr_language"):
        live_cfg["asr_language"] = res["asr_language"]
    if res.get("boot_default"):
        live_cfg["boot_ros_distro"] = res["boot_default"]
    live_cfg["ros_domain_id"] = body.ros_domain_id
    live_cfg["rmw_implementation"] = body.rmw_implementation
    upd["capabilities"] = {"live_config": live_cfg}
    updated_robot = store.upsert_robot(upd)
    if body.target_ros:
        rt = getattr(request.app.state, "runtime", None)
        if rt is not None and hasattr(rt, "start_robot_ros2_bridge"):
            rt.source_mode = "robot_ros2"
            await rt.start_robot_ros2_bridge(
                robot_id=robot_id,
                ip=robot["ip_address"],
                rosbridge_port=int(robot.get("rosbridge_port") or 9090),
                ros_version=normalize_ros_mode(body.target_ros),
            )
    return {"robot_id": robot_id, "robot": updated_robot, **res}


@router.post("/{robot_id}/config/power")
async def robot_config_power(
    robot_id: str,
    body: PowerActionRequest,
    request: Request,
) -> Dict[str, Any]:
    """Restart the ROS stack, reboot, or shut down the PuppyPi host safely."""
    store = _robot_store(request)
    robot = _require_robot(store, robot_id)
    ssh_pw = store.get_robot_ssh_password(robot_id)
    try:
        res = await power_action(
            ip=robot["ip_address"],
            user=robot["ssh_user"],
            password=ssh_pw,
            action=body.action,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SSHAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except SSHCommandError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"robot_id": robot_id, **res}


@router.get("/{robot_id}/hardware-diagnostics")
async def robot_hardware_diagnostics(robot_id: str, request: Request) -> Dict[str, Any]:
    """Collect live Raspberry Pi 5 PMIC power rails, USB budget, and 22-component 3D BOM health."""
    store = _robot_store(request)
    robot = _require_robot(store, robot_id)
    ssh_pw = store.get_robot_ssh_password(robot_id) or ""
    try:
        return await collect_pi5_hardware_diagnostics(robot=robot, password=ssh_pw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SSHAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except SSHCommandError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/{robot_id}/maintenance/clean-logs")
async def robot_maintenance_clean_logs(robot_id: str, request: Request) -> Dict[str, Any]:
    """Safely prune stale (>24h) rotated ROS and LiDAR log files on the robot via SSH."""
    store = _robot_store(request)
    robot = _require_robot(store, robot_id)
    ssh_pw = store.get_robot_ssh_password(robot_id)
    try:
        return await clean_robot_stale_logs(
            ip=robot["ip_address"],
            user=robot["ssh_user"],
            password=ssh_pw,
        )
    except SSHAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except SSHCommandError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
