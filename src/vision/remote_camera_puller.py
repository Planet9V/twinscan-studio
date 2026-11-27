"""Background HTTP MJPEG & snapshot puller for remote Raspberry Pi / IP Overwatch cameras.

Allows the TwinScan Docker backend to pull live JPEG frames directly from
remote edge camera nodes (e.g. Raspberry Pi 5 running ``eigenia-pi5-cam.service``
on ``http://192.168.1.140:8090/stream.mjpg``) without requiring inbound firewall
ports on the host machine. Sources are persisted in PostgreSQL ``app_settings``
under ``overwatch_remote_sources_json`` so they reconnect automatically across
container restarts.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx

from src.vision.overwatch_triangulator import (
    OverwatchCameraManager,
    sanitize_camera_id,
)

REMOTE_SOURCES_SETTING_KEY = "overwatch_remote_sources_json"
MAX_MJPEG_BUFFER_BYTES = 4 * 1024 * 1024
MAX_CONNECT_RETRIES = 3


def validate_stream_url(url: str) -> str:
    """Validate and normalize a remote HTTP(S) camera stream or snapshot URL.

    Args:
        url: Candidate camera stream URL.

    Returns:
        Stripped valid HTTP(S) URL.

    Raises:
        ValueError: If the URL does not use ``http`` or ``https`` or lacks a host.
    """
    cleaned = str(url or "").strip()
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("stream_url must be a valid http:// or https:// URL with a host.")
    return cleaned


def extract_mjpeg_frames(buf: bytearray) -> List[bytes]:
    """Extract all complete JPEG frames (SOI ``0xFFD8`` .. EOI ``0xFFD9``) from a byte buffer.

    Mutates ``buf`` in place, leaving any incomplete trailing frame intact for the
    next chunk. Protects memory by clearing buffers that exceed
    ``MAX_MJPEG_BUFFER_BYTES`` without a valid EOI marker.

    Args:
        buf: Mutable byte buffer accumulating streamed HTTP bytes.

    Returns:
        List of complete raw JPEG frame byte payloads.
    """
    frames: List[bytes] = []
    while True:
        soi = buf.find(b"\xff\xd8")
        if soi < 0:
            if len(buf) > 2:
                del buf[:-2]
            break
        if soi > 0:
            del buf[:soi]
        eoi = buf.find(b"\xff\xd9", 2)
        if eoi < 0:
            if len(buf) > MAX_MJPEG_BUFFER_BYTES:
                buf.clear()
            break
        frames.append(bytes(buf[: eoi + 2]))
        del buf[: eoi + 2]
    return frames


@dataclass
class RemoteCameraSource:
    """Configuration for a single remote HTTP Overwatch camera source."""

    camera_id: str
    stream_url: str
    camera_name: str
    fps: float = 15.0
    enabled: bool = True


class RemoteOverwatchPullerManager:
    """Manages persistent background HTTP pull tasks feeding ``OverwatchCameraManager``."""

    def __init__(self) -> None:
        self._sources: Dict[str, RemoteCameraSource] = {}
        self._tasks: Dict[str, asyncio.Task[None]] = {}
        self._stats: Dict[str, Dict[str, Any]] = {}
        self._repo: Any = None
        self._overwatch_manager: Optional[OverwatchCameraManager] = None
        self._ai_vision_engine: Any = None
        self._ai_store: Any = None
        self._runtime: Any = None
        self._running: bool = False

    def attach_repository(self, repo: Any) -> int:
        """Attach the settings repository and load persisted remote camera sources.

        Args:
            repo: Repository exposing ``get_raw_settings`` and ``upsert_settings``.

        Returns:
            Number of remote camera sources loaded from storage.
        """
        self._repo = repo
        if repo is None or not hasattr(repo, "get_raw_settings"):
            return 0
        try:
            raw = repo.get_raw_settings()
            blob = str(raw.get(REMOTE_SOURCES_SETTING_KEY) or "").strip()
            if not blob:
                return 0
            data = json.loads(blob)
            if not isinstance(data, dict):
                return 0
            loaded = 0
            for cid, entry in data.items():
                if not isinstance(entry, dict):
                    continue
                try:
                    clean_cid = sanitize_camera_id(cid)
                    url = validate_stream_url(str(entry.get("stream_url") or ""))
                    name = str(entry.get("camera_name") or clean_cid).strip() or clean_cid
                    fps = max(0.5, min(60.0, float(entry.get("fps") or 15.0)))
                    enabled = bool(entry.get("enabled", True))
                    self._sources[clean_cid] = RemoteCameraSource(
                        camera_id=clean_cid,
                        stream_url=url,
                        camera_name=name,
                        fps=fps,
                        enabled=enabled,
                    )
                    self._stats.setdefault(clean_cid, self._default_stat())
                    loaded += 1
                except Exception as exc:
                    sys.stderr.write(f"[overwatch.remote] Skipping invalid saved source {cid!r}: {exc}\n")
            return loaded
        except Exception as exc:
            sys.stderr.write(f"[overwatch.remote] Failed loading persisted sources: {exc}\n")
            return 0

    def _persist_sources(self) -> None:
        if self._repo is None or not hasattr(self._repo, "upsert_settings"):
            return
        try:
            payload = {cid: asdict(src) for cid, src in self._sources.items()}
            self._repo.upsert_settings(
                {REMOTE_SOURCES_SETTING_KEY: json.dumps(payload)},
                source_ip="overwatch_remote",
            )
        except Exception as exc:
            sys.stderr.write(f"[overwatch.remote] Failed persisting remote sources: {exc}\n")

    @staticmethod
    def _default_stat() -> Dict[str, Any]:
        return {
            "connected": False,
            "frames_ingested": 0,
            "last_frame_ts": 0.0,
            "last_error": None,
            "reconnect_count": 0,
        }

    def bind_runtime(
        self,
        *,
        overwatch_manager: OverwatchCameraManager,
        ai_vision_engine: Any = None,
        ai_store: Any = None,
        runtime: Any = None,
    ) -> None:
        """Bind runtime dependencies used when ingesting pulled frames.

        Args:
            overwatch_manager: Active ``OverwatchCameraManager`` instance.
            ai_vision_engine: Optional ``RobotAIVisionEngine`` for YOLO/face/AprilTag.
            ai_store: Optional ``RobotAiStore`` for face matching.
            runtime: Optional ``TwinScanRuntime`` for live LiDAR context.
        """
        self._overwatch_manager = overwatch_manager
        self._ai_vision_engine = ai_vision_engine
        self._ai_store = ai_store
        self._runtime = runtime

    async def start_all(
        self,
        *,
        overwatch_manager: Optional[OverwatchCameraManager] = None,
        ai_vision_engine: Any = None,
        ai_store: Any = None,
        runtime: Any = None,
    ) -> int:
        """Start background pull tasks for all enabled remote camera sources.

        Args:
            overwatch_manager: Optional manager to bind before starting.
            ai_vision_engine: Optional vision engine to bind.
            ai_store: Optional AI store to bind.
            runtime: Optional TwinScan runtime to bind.

        Returns:
            Number of puller tasks started.
        """
        if overwatch_manager is not None:
            self.bind_runtime(
                overwatch_manager=overwatch_manager,
                ai_vision_engine=ai_vision_engine,
                ai_store=ai_store,
                runtime=runtime,
            )
        self._running = True
        started = 0
        for cid, src in list(self._sources.items()):
            if src.enabled:
                self._ensure_task(cid)
                started += 1
        return started

    async def stop_all(self) -> None:
        """Cancel and await all active background camera puller tasks."""
        self._running = False
        tasks = list(self._tasks.values())
        self._tasks.clear()
        for task in tasks:
            if not task.done():
                task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                sys.stderr.write(f"[overwatch.remote] Error awaiting cancelled puller: {exc}\n")

    async def upsert_source(
        self,
        *,
        camera_id: str,
        stream_url: str,
        camera_name: Optional[str] = None,
        fps: float = 15.0,
        enabled: bool = True,
    ) -> Dict[str, Any]:
        """Register or update a remote HTTP Overwatch camera source and start pulling.

        Args:
            camera_id: Target Overwatch camera slot (e.g. ``usb_4k``).
            stream_url: Remote HTTP(S) MJPEG stream or JPEG snapshot URL.
            camera_name: Human-readable display label.
            fps: Target ingest frame rate.
            enabled: Whether the background puller should run immediately.

        Returns:
            Serialized source descriptor with current live puller status.
        """
        clean_cid = sanitize_camera_id(camera_id)
        clean_url = validate_stream_url(stream_url)
        clean_name = str(camera_name or clean_cid).strip() or clean_cid
        clean_fps = max(0.5, min(60.0, float(fps)))

        await self._cancel_task(clean_cid)
        self._sources[clean_cid] = RemoteCameraSource(
            camera_id=clean_cid,
            stream_url=clean_url,
            camera_name=clean_name,
            fps=clean_fps,
            enabled=bool(enabled),
        )
        self._stats[clean_cid] = self._default_stat()
        self._persist_sources()

        if enabled and self._running and self._overwatch_manager is not None:
            self._ensure_task(clean_cid)
        return self._format_source(clean_cid)

    async def remove_source(self, camera_id: str) -> bool:
        """Stop pulling and remove a remote camera source from memory and PostgreSQL.

        Args:
            camera_id: Overwatch camera slot to remove.

        Returns:
            True if the source existed and was removed, False otherwise.
        """
        clean_cid = sanitize_camera_id(camera_id)
        await self._cancel_task(clean_cid)
        existed = clean_cid in self._sources
        self._sources.pop(clean_cid, None)
        self._stats.pop(clean_cid, None)
        if existed:
            self._persist_sources()
        return existed

    def list_sources(self) -> List[Dict[str, Any]]:
        """Return all configured remote camera sources with live telemetry."""
        return [self._format_source(cid) for cid in sorted(self._sources.keys())]

    def _format_source(self, cid: str) -> Dict[str, Any]:
        src = self._sources[cid]
        stat = self._stats.get(cid) or self._default_stat()
        last_ts = float(stat.get("last_frame_ts") or 0.0)
        age_s = round(time.time() - last_ts, 2) if last_ts > 0 else None
        return {
            **asdict(src),
            "connected": bool(stat.get("connected", False)),
            "frames_ingested": int(stat.get("frames_ingested", 0)),
            "last_frame_age_s": age_s,
            "last_error": stat.get("last_error"),
            "reconnect_count": int(stat.get("reconnect_count", 0)),
        }

    def _ensure_task(self, cid: str) -> None:
        existing = self._tasks.get(cid)
        if existing is not None and not existing.done():
            return
        self._tasks[cid] = asyncio.create_task(self._pull_loop(cid))

    async def _cancel_task(self, cid: str) -> None:
        task = self._tasks.pop(cid, None)
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                sys.stderr.write(f"[overwatch.remote] Cancel error for {cid}: {exc}\n")

    async def _ingest_one_frame(self, src: RemoteCameraSource, jpeg_bytes: bytes) -> None:
        if self._overwatch_manager is None or not jpeg_bytes:
            return
        await asyncio.to_thread(
            self._overwatch_manager.ingest_frame,
            jpeg_bytes=jpeg_bytes,
            camera_name=src.camera_name,
            fps=src.fps,
            ai_vision_engine=self._ai_vision_engine,
            ai_store=self._ai_store,
            runtime=self._runtime,
            camera_id=src.camera_id,
        )
        stat = self._stats.setdefault(src.camera_id, self._default_stat())
        stat["connected"] = True
        stat["frames_ingested"] = int(stat.get("frames_ingested", 0)) + 1
        stat["last_frame_ts"] = time.time()
        stat["last_error"] = None

    async def _pull_loop(self, cid: str) -> None:
        """Continuously stream frames from the remote HTTP camera with retry/backoff."""
        min_interval = 0.05
        while self._running:
            src = self._sources.get(cid)
            if src is None or not src.enabled:
                return
            stat = self._stats.setdefault(cid, self._default_stat())
            min_interval = max(1.0 / max(src.fps, 0.5), 0.04)
            connected_this_round = False

            for attempt in range(1, MAX_CONNECT_RETRIES + 1):
                if not self._running or cid not in self._sources:
                    return
                try:
                    timeout = httpx.Timeout(connect=6.0, read=12.0, write=6.0, pool=6.0)
                    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                        async with client.stream("GET", src.stream_url) as resp:
                            resp.raise_for_status()
                            ctype = (resp.headers.get("content-type") or "").lower()
                            if "multipart" in ctype or src.stream_url.lower().endswith(".mjpg"):
                                buf = bytearray()
                                last_ingest = 0.0
                                async for chunk in resp.aiter_bytes(chunk_size=32768):
                                    if not self._running or cid not in self._sources:
                                        return
                                    if not chunk:
                                        continue
                                    buf.extend(chunk)
                                    frames = extract_mjpeg_frames(buf)
                                    if frames:
                                        connected_this_round = True
                                        now = time.monotonic()
                                        if now - last_ingest >= min_interval:
                                            await self._ingest_one_frame(src, frames[-1])
                                            last_ingest = now
                            else:
                                # Single JPEG snapshot endpoint polling mode.
                                data = await resp.aread()
                                if data and data[:2] == b"\xff\xd8":
                                    connected_this_round = True
                                    await self._ingest_one_frame(src, data)
                                await asyncio.sleep(min_interval)
                                break
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    stat["connected"] = False
                    stat["last_error"] = str(exc)
                    sys.stderr.write(
                        f"[overwatch.remote] Pull error for {cid} ({src.stream_url}) "
                        f"attempt {attempt}/{MAX_CONNECT_RETRIES}: {exc}\n"
                    )
                    if attempt < MAX_CONNECT_RETRIES:
                        await asyncio.sleep(min(2.0 * attempt, 6.0))
                if connected_this_round:
                    break

            if not connected_this_round:
                stat["connected"] = False
                stat["reconnect_count"] = int(stat.get("reconnect_count", 0)) + 1
                await asyncio.sleep(4.0)
