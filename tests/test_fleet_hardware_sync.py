"""Unit tests for automatic Fleet & USB Peripheral sync into Lab Architect."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes_devices import router as devices_router
from src.db.robot_ai_store import InMemoryRobotAiStore
from src.db.robot_store import InMemoryRobotStore
from src.devices.fleet_hardware_sync import parse_lsusb_and_devs, sync_fleet_to_architect


REAL_PI5_LSUSB = """
Bus 001 Device 001: ID 1d6b:0002 Linux Foundation 2.0 root hub
Bus 003 Device 002: ID 0d28:0204 NXP ARM mbed
Bus 003 Device 005: ID 0bda:3035 Realtek Semiconductor Corp. 4k Webcam
"""

REAL_PI5_DEVS = """
/dev/ttyACM0
/dev/video19
"""


def test_parse_lsusb_detects_microbit_and_4k_webcam_on_pi5() -> None:
    """Real Pi 5 lsusb output detects BBC micro:bit v2 on /dev/ttyACM0 and 4K USB Webcam."""
    found = parse_lsusb_and_devs(REAL_PI5_LSUSB, REAL_PI5_DEVS, host_name="rasp5", host_ip="192.168.1.140")
    names = [p["name"] for p in found]
    assert any("micro:bit v2" in n for n in names)
    assert any("4K USB Overwatch Webcam" in n for n in names)
    mb = next(p for p in found if "micro:bit" in p["name"])
    assert "accelerometer_3axis" in mb["capabilities"]
    assert "remote_hex_flash" in mb["capabilities"]
    assert "/dev/ttyACM0" in mb["location"]


@pytest.mark.asyncio
async def test_sync_fleet_to_architect_is_idempotent_no_duplicates() -> None:
    """Running sync_fleet_to_architect twice creates zero duplicate inventory rows."""
    r_store = InMemoryRobotStore()
    ai_store = InMemoryRobotAiStore()
    r_store.upsert_robot(
        {
            "name": "Raspberry Pi 5 16GB (rasp5)",
            "model": "Raspberry Pi 5 Model B Rev 1.1",
            "ip_address": "192.168.1.140",
            "ssh_user": "ox",
            "ssh_password": "secret",
        }
    )
    r_store.upsert_robot(
        {
            "name": "Raspberry Pi 4 8GB (Wi-Fi)",
            "model": "Raspberry Pi 4 Model B Rev 1.5",
            "ip_address": "192.168.1.142",
            "ssh_user": "ox",
            "ssh_password": "secret",
        }
    )

    res1 = await sync_fleet_to_architect(r_store, ai_store, probe_live=False)
    assert res1["ok"] is True
    assert res1["synced_hosts"] == 2
    count1 = len(ai_store.list_inventory_items())

    res2 = await sync_fleet_to_architect(r_store, ai_store, probe_live=False)
    assert res2["synced_hosts"] == 2
    assert len(ai_store.list_inventory_items()) == count1


def test_sync_fleet_endpoint_returns_synced_summary() -> None:
    """POST /api/inventory/sync-fleet syncs registered robots cleanly."""
    app = FastAPI()
    app.include_router(devices_router)
    r_store = InMemoryRobotStore()
    r_store.upsert_robot({"name": "Pi 5 Test", "model": "Raspberry Pi 5", "ip_address": "192.168.1.140"})
    app.state.robot_store = r_store
    app.state.robot_ai_store = InMemoryRobotAiStore()

    client = TestClient(app)
    r = client.post("/api/inventory/sync-fleet?probe_live=false")
    assert r.status_code == 200
    assert r.json()["synced_hosts"] == 1
    assert r.json()["total_inventory_items"] >= 1
