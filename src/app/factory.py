"""FastAPI application factory for Eigenia TwinScan (modular entrypoint, zero main.py)."""

from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio
import os
import sys
from typing import Any, AsyncIterator, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes_admin import router as admin_router
from src.api.routes_agent import router as agent_router
from src.api.routes_ai_vision import router as ai_vision_router
from src.api.routes_devices import router as devices_router
from src.api.routes_enrichment import router as enrichment_router
from src.api.routes_lidar import router as lidar_router
from src.api.routes_overwatch import router as overwatch_router
from src.api.routes_flasher import router as flasher_router
from src.api.routes_room_studio import router as room_studio_router
from src.api.routes_slam import router as slam_router
from src.api.routes_robots import router as robots_router
from src.api.routes_twin import router as twin_router
from src.api.routes_vision import router as vision_router
from src.api.routes_voice import router as voice_router
from src.api.routes_wiki import router as wiki_router
from src.api.state import TwinScanRuntimeState
from src.app.config import Settings, get_settings
from src.db.repository import TwinRepositoryProtocol
from src.db.robot_ai_store import (
    InMemoryRobotAiStore,
    PostgresRobotAiStore,
    RobotAiStoreProtocol,
)
from src.db.robot_store import InMemoryRobotStore, PostgresRobotStore, RobotStoreProtocol
from src.robot.conversation_engine import RobotConversationManager
from src.robot.explorer_engine import AutonomousExplorerManager
from src.robot.patrol_engine import RobotPatrolManager
from src.robot.ros_profiles import normalize_ros_mode
from src.robot.sentry_manager import RobotSentryManager
from src.robot.voice_manager import WonderEchoWakeManager
from src.vision.overwatch_triangulator import OverwatchCameraManager
from src.vision.robot_ai_vision import RobotAiVisionEngine, ensure_onnx_models


def _init_robot_store(settings: Settings) -> RobotStoreProtocol:
    """Initialize PostgresRobotStore when DATABASE_URL is reachable, else InMemoryRobotStore."""
    if settings.database_url:
        try:
            pg_store = PostgresRobotStore(
                database_url=settings.database_url,
                encryption_key=settings.twinscan_encryption_key,
            )
            pg_store.initialize()
            return pg_store
        except Exception as exc:
            sys.stderr.write(f"[robot_store] PostgreSQL unavailable, falling back to InMemoryRobotStore: {exc}\n")
    mem_store = InMemoryRobotStore(encryption_key=settings.twinscan_encryption_key)
    mem_store.initialize()
    return mem_store


def _init_robot_ai_store(settings: Settings) -> RobotAiStoreProtocol:
    """Initialize PostgresRobotAiStore when DATABASE_URL is reachable, else InMemoryRobotAiStore."""
    if settings.database_url:
        try:
            pg_store = PostgresRobotAiStore(database_url=settings.database_url)
            pg_store.initialize()
            return pg_store
        except Exception as exc:
            sys.stderr.write(f"[robot_ai_store] PostgreSQL unavailable, falling back to InMemoryRobotAiStore: {exc}\n")
    mem_store = InMemoryRobotAiStore()
    mem_store.initialize()
    return mem_store


async def _probe_tcp_port(ip: str, port: int, timeout_s: float = 1.5) -> bool:
    """Probe whether a TCP ``(ip, port)`` endpoint is reachable within ``timeout_s``."""
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout=timeout_s)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return True
    except Exception:
        return False


async def _auto_attach_live_robot_lidar(app: FastAPI) -> bool:
    """Auto-attach live ``robot_ros2`` LiDAR bridge on startup if a configured robot's ROSBridge is reachable."""
    rt: TwinScanRuntimeState = app.state.runtime
    if rt.source_mode != "simulator":
        return False
    store: RobotStoreProtocol = app.state.robot_store
    try:
        robots = store.list_robots()
    except Exception as exc:
        sys.stderr.write(f"[robots.auto_attach] Failed listing robots: {exc}\n")
        return False

    for rob in robots:
        ip = str(rob.get("ip_address") or "").strip()
        distro = str(rob.get("active_ros_distro") or "").strip()
        if not ip or not distro:
            continue
        ros_port = int(rob.get("rosbridge_port") or 9090)
        if await _probe_tcp_port(ip, ros_port, timeout_s=1.5):
            rt.source_mode = "robot_ros2"
            rt.active_lidar_robot_id = rob["id"]
            if not rt._rotation_user_overridden and rt.filter_config.rotation_offset_deg == 0.0:
                rt.filter_config.rotation_offset_deg = 90.0
            await rt.start_robot_ros2_bridge(
                robot_id=rob["id"],
                ip=ip,
                rosbridge_port=ros_port,
                ros_version=normalize_ros_mode(distro),
            )
            # Default Dark Mode: turn PuppyPi RGB LEDs off on startup unless explicitly disabled in /config
            try:
                raw_cfg = rt.repo.get_settings_raw() if rt.repo is not None else {}
                dark_mode = str(raw_cfg.get("robot_led_dark_mode") or "true").strip().lower() != "false"
                if dark_mode:
                    from src.robot.rosbridge_proxy import set_rgb

                    await set_rgb(
                        ip=ip,
                        port=ros_port,
                        data=[{"id": 1, "r": 0, "g": 0, "b": 0}, {"id": 2, "r": 0, "g": 0, "b": 0}],
                        ros_version=normalize_ros_mode(distro),
                    )
            except Exception as exc:
                sys.stderr.write(f"[robots.auto_attach] Default dark-mode RGB off skipped: {exc}\n")
            return True
    return False


def create_app(
    settings: Optional[Settings] = None,
    repository: Optional[TwinRepositoryProtocol] = None,
    robot_store: Optional[RobotStoreProtocol] = None,
    robot_ai_store: Optional[RobotAiStoreProtocol] = None,
) -> FastAPI:
    """Create and configure the Eigenia TwinScan FastAPI application."""
    cfg = settings or get_settings()
    runtime = TwinScanRuntimeState(settings=cfg, repository=repository)
    active_robot_store = robot_store or _init_robot_store(cfg)
    if robot_store is not None:
        active_robot_store.initialize()
    active_ai_store = robot_ai_store or _init_robot_ai_store(cfg)
    if robot_ai_store is not None:
        active_ai_store.initialize()

    models_dir = os.environ.get("TWINSCAN_MODELS_DIR", "./data/models")
    ai_vision_engine = RobotAiVisionEngine(ai_store=active_ai_store, models_dir=models_dir)
    overwatch_manager = OverwatchCameraManager()
    patrol_manager = RobotPatrolManager()
    explorer_manager = AutonomousExplorerManager()
    wake_manager = WonderEchoWakeManager()
    conversation_manager = RobotConversationManager()
    sentry_manager = RobotSentryManager()

    async def _robot_liveness_loop() -> None:
        """Background 15s TCP liveness probe updating registered robots' online/offline status."""
        while True:
            try:
                await asyncio.sleep(15.0)
                for rob in active_robot_store.list_robots():
                    ip = str(rob.get("ip_address") or "").strip()
                    if not ip:
                        continue
                    ros_port = int(rob.get("rosbridge_port") or 9090)
                    alive = await _probe_tcp_port(ip, ros_port, 1.2) or await _probe_tcp_port(ip, 22, 1.2)
                    new_status = "online" if alive else "offline"
                    if rob.get("status") != new_status:
                        active_robot_store.upsert_robot({"id": rob["id"], "ip_address": ip, "status": new_status})
            except asyncio.CancelledError:
                return
            except Exception as exc:
                sys.stderr.write(f"[robots.liveness] Probe error: {exc}\n")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.runtime.start_background_tasks()
        model_dl_task: Optional[asyncio.Task[Any]] = None
        liveness_task: Optional[asyncio.Task[None]] = None
        auto_attach_task: Optional[asyncio.Task[Any]] = None
        if os.environ.get("TWINSCAN_AUTO_DOWNLOAD_MODELS") == "1" or models_dir.startswith("/app"):
            async def _warm_models() -> None:
                res = await ensure_onnx_models(models_dir)
                ai_vision_engine._models_ready.update(res)

            model_dl_task = asyncio.create_task(_warm_models())
        if cfg.database_url:
            liveness_task = asyncio.create_task(_robot_liveness_loop())
            auto_attach_task = asyncio.create_task(_auto_attach_live_robot_lidar(app))

            async def _startup_fleet_sync() -> None:
                try:
                    from src.devices.fleet_hardware_sync import sync_fleet_to_architect

                    await sync_fleet_to_architect(
                        robot_store=app.state.robot_store,
                        ai_store=app.state.robot_ai_store,
                        probe_live=True,
                    )
                except Exception as exc:
                    sys.stderr.write(f"[fleet_sync.startup] Background sync warning: {exc}\n")

            asyncio.create_task(_startup_fleet_sync())
        await app.state.remote_overwatch_puller.start_all(
            overwatch_manager=app.state.overwatch_manager,
            ai_vision_engine=app.state.ai_vision_engine,
            ai_store=app.state.robot_ai_store,
            runtime=app.state.runtime,
        )
        try:
            yield
        finally:
            for bg in (model_dl_task, liveness_task, auto_attach_task):
                if bg is not None and not bg.done():
                    bg.cancel()
                    try:
                        await bg
                    except asyncio.CancelledError:
                        pass
            await app.state.remote_overwatch_puller.stop_all()
            await app.state.sentry_manager.stop_all()
            await app.state.conversation_manager.stop_all()
            await app.state.explorer_manager.stop_all()
            await app.state.patrol_manager.stop_all()
            await app.state.wake_manager.stop_all()
            await app.state.runtime.shutdown()
            app.state.robot_store.close()
            app.state.robot_ai_store.close()

    app = FastAPI(
        title="Eigenia TwinScan API",
        version="2.0.0",
        description="Exemplar LD19 LiDAR, OpenRouter Vision & Direct Research, PostgreSQL 18 pgvector/Storage & Neo4j G_CPDT Studio",
        lifespan=lifespan,
    )
    app.state.runtime = runtime
    app.state.robot_store = active_robot_store
    app.state.robot_ai_store = active_ai_store
    app.state.ai_vision_engine = ai_vision_engine
    overwatch_manager.attach_repository(runtime.repo)
    app.state.overwatch_manager = overwatch_manager
    from src.vision.remote_camera_puller import RemoteOverwatchPullerManager

    remote_overwatch_puller = RemoteOverwatchPullerManager()
    remote_overwatch_puller.attach_repository(runtime.repo)
    app.state.remote_overwatch_puller = remote_overwatch_puller
    app.state.patrol_manager = patrol_manager
    app.state.explorer_manager = explorer_manager
    app.state.wake_manager = wake_manager
    app.state.conversation_manager = conversation_manager
    app.state.sentry_manager = sentry_manager

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(lidar_router)
    app.include_router(vision_router)
    app.include_router(twin_router)
    app.include_router(enrichment_router)
    app.include_router(admin_router)
    app.include_router(robots_router)
    app.include_router(voice_router)
    app.include_router(ai_vision_router)
    app.include_router(devices_router)
    app.include_router(wiki_router)
    app.include_router(agent_router)
    app.include_router(overwatch_router)
    app.include_router(flasher_router)
    app.include_router(room_studio_router)
    app.include_router(slam_router)

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, Any]:
        """Return system health across PostgreSQL 18, Neo4j 5, OpenRouter, and LiDAR."""
        rt: TwinScanRuntimeState = app.state.runtime
        return {
            "status": "ok",
            "service": "eigenia-twinscan",
            "database": rt.repo.check_health(),
            "database_backend": type(rt.repo).__name__,
            "neo4j": rt.neo4j.check_health(),
            "openrouter_configured": rt.openrouter_configured,
            "lidar_source_mode": rt.source_mode,
            "active_space_id": rt.active_space_id,
            "storage": rt.repo.storage_stats(),
        }

    return app
