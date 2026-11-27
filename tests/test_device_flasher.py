"""Unit tests for the Universal Hardware Flasher (Poka-Yoke safety, provisioning & API routes)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes_flasher import router as flasher_router
from src.flasher.board_catalog import fetch_rpi_os_catalog
from src.flasher.provisioner import build_pi_headless_bundle, validate_removable_target


def test_poka_yoke_blocks_internal_system_disks_and_bad_confirmations() -> None:
    """Protected OS disks, non-removable drives, and mismatched confirmations MUST be rejected."""
    with pytest.raises(ValueError, match="SAFETY BLOCK"):
        validate_removable_target(
            {"device_id": "disk0", "device_path": "/dev/disk0", "is_removable": True, "is_internal": False},
            confirmation_token="disk0",
        )

    with pytest.raises(ValueError, match="SAFETY BLOCK"):
        validate_removable_target(
            {"device_id": "disk5", "device_path": "/dev/disk5", "is_removable": False, "is_internal": False},
            confirmation_token="disk5",
        )

    with pytest.raises(ValueError, match="Confirmation mismatch"):
        validate_removable_target(
            {"device_id": "disk5", "device_path": "/dev/disk5", "is_removable": True, "is_internal": False},
            confirmation_token="wrong",
        )

    ok = validate_removable_target(
        {"device_id": "disk5", "device_path": "/dev/disk5", "size_gb": 62.5, "is_removable": True, "is_internal": False},
        confirmation_token="disk5",
    )
    assert ok["device_id"] == "disk5"
    assert ok["size_gb"] == 62.5


def test_headless_provisioner_validates_and_redacts_secrets() -> None:
    """Headless Pi bundle validates RFC-1123 hostnames, blocks control chars, and redacts preview passwords."""
    bundle = build_pi_headless_bundle(
        hostname="eigenia-pi5",
        username="pi",
        wifi_ssid="LabNet",
        wifi_password="super-secret-password",
        twinscan_url="http://192.168.1.50:8000",
        role="overwatch_cam_node",
        redact_secrets=True,
    )
    assert bundle["ok"] is True
    assert "super-secret-password" not in bundle["firstrun_sh"]
    assert "********" in bundle["firstrun_sh"]
    assert "eigenia-pi5" in bundle["firstrun_sh"]

    with pytest.raises(ValueError, match="Invalid hostname"):
        build_pi_headless_bundle(hostname="bad host; rm -rf /")


@pytest.mark.asyncio
async def test_os_catalog_offline_fallback_and_routes() -> None:
    """Offline fallback returns valid Pi 5 images, and FastAPI routes enforce safety end-to-end."""
    cat = await fetch_rpi_os_catalog(board_id="pi5", allow_network=False)
    assert cat["board_id"] == "pi5"
    assert len(cat["images"]) >= 2

    app = FastAPI()
    app.include_router(flasher_router)
    client = TestClient(app)

    r_plat = client.get("/api/flasher/platforms")
    assert r_plat.status_code == 200
    ids = [p["id"] for p in r_plat.json()["platforms"]]
    assert {"pi5", "pi4", "pi3", "arduino", "esp32", "pico", "microbit"}.issubset(set(ids))

    # Host bridge reports one removable SD card and one internal drive (internal must be dropped!)
    r_rep = client.post(
        "/api/flasher/host/report",
        json={
            "host_os": "Darwin",
            "tools": {"rpi_imager": True},
            "devices": [
                {"device_id": "disk0", "device_path": "/dev/disk0", "is_removable": False, "is_internal": True, "size_gb": 500},
                {"device_id": "disk5", "device_path": "/dev/disk5", "is_removable": True, "is_internal": False, "size_gb": 62.5, "label": "Untitled"},
            ],
        },
    )
    assert r_rep.status_code == 200
    assert r_rep.json()["accepted_devices"] == 1

    # Queue job with wrong confirmation -> 400
    r_bad = client.post(
        "/api/flasher/jobs",
        json={
            "board_id": "pi5",
            "image_url": "https://downloads.raspberrypi.org/raspios_lite_arm64_latest",
            "image_name": "Raspberry Pi OS Lite (64-bit)",
            "device_id": "disk5",
            "confirmation_token": "nope",
        },
    )
    assert r_bad.status_code == 400

    # Queue job with exact confirmation -> 200
    r_ok = client.post(
        "/api/flasher/jobs",
        json={
            "board_id": "pi5",
            "image_url": "https://downloads.raspberrypi.org/raspios_lite_arm64_latest",
            "image_name": "Raspberry Pi OS Lite (64-bit)",
            "device_id": "disk5",
            "confirmation_token": "disk5",
            "provision": {"hostname": "eigenia-pi5", "username": "pi", "role": "minimal_ssh"},
        },
    )
    assert r_ok.status_code == 200
    job = r_ok.json()
    assert job["status"] == "queued"
    assert job["target"]["device_id"] == "disk5"
