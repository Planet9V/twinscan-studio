"""Unit tests for remote Pi / IP Overwatch HTTP MJPEG camera puller and routes."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes_overwatch import router as overwatch_router
from src.vision.overwatch_triangulator import OverwatchCameraManager
from src.vision.remote_camera_puller import (
    REMOTE_SOURCES_SETTING_KEY,
    RemoteOverwatchPullerManager,
    extract_mjpeg_frames,
    validate_stream_url,
)


class _InMemorySettingsRepo:
    def __init__(self) -> None:
        self._data: Dict[str, str] = {}

    def get_raw_settings(self) -> Dict[str, str]:
        return dict(self._data)

    def upsert_settings(self, updates: Dict[str, Any], source_ip: str = "") -> None:
        for k, v in updates.items():
            self._data[str(k)] = str(v)


def test_extract_mjpeg_frames_handles_multiple_and_partial() -> None:
    """Extracts multiple complete JPEG frames while retaining incomplete trailing bytes."""
    f1 = b"\xff\xd8\x01\x02\xff\xd9"
    f2 = b"\xff\xd8\xaa\xbb\xcc\xff\xd9"
    partial = b"\xff\xd8\x11\x22"
    buf = bytearray(b"junk-header" + f1 + b"--frame\r\n" + f2 + partial)

    frames = extract_mjpeg_frames(buf)
    assert frames == [f1, f2]
    assert bytes(buf) == partial


def test_validate_stream_url_rejects_non_http() -> None:
    """Only http:// and https:// stream URLs with a host are accepted."""
    assert validate_stream_url("http://192.168.1.140:8090/stream.mjpg") == "http://192.168.1.140:8090/stream.mjpg"
    with pytest.raises(ValueError):
        validate_stream_url("file:///etc/passwd")
    with pytest.raises(ValueError):
        validate_stream_url("rtsp://192.168.1.140/live")


def test_remote_puller_persists_and_reloads_from_repo() -> None:
    """Upserted remote sources persist to settings JSON and reload cleanly."""
    repo = _InMemorySettingsRepo()
    mgr = RemoteOverwatchPullerManager()
    mgr.attach_repository(repo)

    res = asyncio.run(
        mgr.upsert_source(
            camera_id="usb_4k",
            stream_url="http://192.168.1.140:8090/stream.mjpg",
            camera_name="Pi5 4K Webcam (192.168.1.140)",
            fps=15.0,
            enabled=False,
        )
    )
    assert res["camera_id"] == "usb_4k"
    assert REMOTE_SOURCES_SETTING_KEY in repo._data
    saved = json.loads(repo._data[REMOTE_SOURCES_SETTING_KEY])
    assert saved["usb_4k"]["stream_url"] == "http://192.168.1.140:8090/stream.mjpg"

    mgr2 = RemoteOverwatchPullerManager()
    assert mgr2.attach_repository(repo) == 1
    listed = mgr2.list_sources()
    assert len(listed) == 1
    assert listed[0]["camera_name"] == "Pi5 4K Webcam (192.168.1.140)"

    removed = asyncio.run(mgr2.remove_source("usb_4k"))
    assert removed is True
    assert mgr2.list_sources() == []


def test_remote_sources_api_routes() -> None:
    """GET/POST/DELETE /api/overwatch/remote-sources manage remote camera registrations."""
    app = FastAPI()
    app.include_router(overwatch_router)
    app.state.overwatch_manager = OverwatchCameraManager()
    puller = RemoteOverwatchPullerManager()
    puller.attach_repository(_InMemorySettingsRepo())
    app.state.remote_overwatch_puller = puller

    client = TestClient(app)

    r_list = client.get("/api/overwatch/remote-sources")
    assert r_list.status_code == 200
    assert r_list.json()["count"] == 0

    r_bad = client.post(
        "/api/overwatch/remote-sources",
        json={"camera_id": "usb_4k", "stream_url": "file:///dev/video0", "enabled": False},
    )
    assert r_bad.status_code == 400

    r_add = client.post(
        "/api/overwatch/remote-sources",
        json={
            "camera_id": "usb_4k",
            "stream_url": "http://192.168.1.140:8090/stream.mjpg",
            "camera_name": "Pi5 4K Webcam (192.168.1.140)",
            "fps": 15.0,
            "enabled": False,
        },
    )
    assert r_add.status_code == 200
    assert r_add.json()["ok"] is True
    assert r_add.json()["source"]["camera_id"] == "usb_4k"

    r_del = client.delete("/api/overwatch/remote-sources/usb_4k")
    assert r_del.status_code == 200
    assert r_del.json()["removed"] is True
