"""Pytest suite for Spatial Memory Pro, Universal Devices, Lab Inventory, and Co-Design Architect API."""

from __future__ import annotations

import base64
from typing import Any, Dict

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from src.app.config import Settings
from src.app.factory import create_app
from src.db.repository import InMemoryTwinRepository
from src.db.robot_ai_store import InMemoryRobotAiStore
from src.db.robot_store import InMemoryRobotStore


def _make_sample_jpeg() -> bytes:
    """Create a valid 160x120 synthetic JPEG image for local camera ingest tests."""
    img = np.zeros((120, 160, 3), dtype=np.uint8)
    img[:, :] = (35, 65, 95)
    cv2.rectangle(img, (20, 20), (140, 100), (220, 140, 40), 2)
    cv2.putText(img, "EIGENIA LAB", (24, 66), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (240, 240, 240), 1)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


@pytest.fixture()
def client() -> TestClient:
    """Create an isolated FastAPI TestClient backed by in-memory stores."""
    settings = Settings(
        database_url="",
        openrouter_api_key="",
        neo4j_uri="",
    )
    app = create_app(
        settings=settings,
        repository=InMemoryTwinRepository(),
        robot_store=InMemoryRobotStore(),
        robot_ai_store=InMemoryRobotAiStore(),
    )
    with TestClient(app) as test_client:
        yield test_client


def test_spatial_memory_pro_filters_patch_bulk_and_delete(client: TestClient) -> None:
    """Verify active/archived/all filtering, PATCH edit, bulk archive/retrieve/delete, and counts."""
    ai_store = client.app.state.robot_ai_store
    s1 = ai_store.record_spatial_sighting(
        "robot-1",
        {
            "space_id": "space-a",
            "label": "Golden Retriever",
            "kind": "animal",
            "x_m": 1.2,
            "y_m": -0.4,
            "confidence": 0.91,
            "notes": "Near couch",
            "camera_source": "puppypi_fpv",
            "tags": ["pet", "living-room"],
        },
    )
    s2 = ai_store.record_spatial_sighting(
        "robot-1",
        {
            "space_id": "space-a",
            "label": "Jim",
            "kind": "face",
            "x_m": 0.5,
            "y_m": 0.8,
            "confidence": 0.87,
            "notes": "At desk",
            "camera_source": "local_cam:Entry",
            "tags": ["operator"],
        },
    )
    s3 = ai_store.record_spatial_sighting(
        "robot-1",
        {
            "space_id": "space-b",
            "label": "Red Backpack",
            "kind": "object",
            "x_m": 2.1,
            "y_m": 0.3,
            "confidence": 0.78,
            "notes": "By door",
            "camera_source": "puppypi_fpv",
            "tags": ["gear"],
        },
    )

    # Default status=active returns all 3 and accurate counts
    r = client.get("/api/spatial-memory")
    assert r.status_code == 200
    data = r.json()
    assert len(data["sightings"]) == 3
    assert data["counts"] == {"active": 3, "archived": 0, "total": 3}

    # Filter by kind & space_id & query (including tag/camera_source search)
    r_kind = client.get("/api/spatial-memory", params={"kind": "face", "space_id": "space-a"})
    assert r_kind.status_code == 200
    assert [s["id"] for s in r_kind.json()["sightings"]] == [s2["id"]]

    r_tag = client.get("/api/spatial-memory", params={"query": "living-room"})
    assert r_tag.status_code == 200
    assert [s["id"] for s in r_tag.json()["sightings"]] == [s1["id"]]

    # PATCH label, notes, tags, and archive flag
    r_patch = client.patch(
        f"/api/spatial-memory/{s1['id']}",
        json={
            "label": "Buddy the Dog",
            "notes": "Sleeping by sofa",
            "tags": ["pet", "verified"],
            "archived": True,
        },
    )
    assert r_patch.status_code == 200
    patched = r_patch.json()["sighting"]
    assert patched["label"] == "Buddy the Dog"
    assert patched["notes"] == "Sleeping by sofa"
    assert patched["tags"] == ["pet", "verified"]
    assert patched["archived"] is True
    assert patched["archived_at"] is not None

    # Active vs Archived vs All
    r_active = client.get("/api/spatial-memory", params={"status": "active"})
    assert r_active.json()["counts"] == {"active": 2, "archived": 1, "total": 3}
    assert len(r_active.json()["sightings"]) == 2

    r_arch = client.get("/api/spatial-memory", params={"status": "archived"})
    assert [s["id"] for s in r_arch.json()["sightings"]] == [s1["id"]]

    r_all = client.get("/api/spatial-memory", params={"status": "all"})
    assert len(r_all.json()["sightings"]) == 3

    # Bulk archive, retrieve, and delete
    r_bulk_arch = client.post(
        "/api/spatial-memory/bulk",
        json={"action": "archive", "ids": [s2["id"], s3["id"]]},
    )
    assert r_bulk_arch.status_code == 200
    assert r_bulk_arch.json() == {"ok": True, "affected": 2}
    assert client.get("/api/spatial-memory").json()["counts"] == {"active": 0, "archived": 3, "total": 3}

    r_bulk_ret = client.post(
        "/api/spatial-memory/bulk",
        json={"action": "retrieve", "ids": [s1["id"], s2["id"]]},
    )
    assert r_bulk_ret.status_code == 200
    assert r_bulk_ret.json() == {"ok": True, "affected": 2}
    assert client.get("/api/spatial-memory").json()["counts"] == {"active": 2, "archived": 1, "total": 3}

    r_bulk_del = client.post(
        "/api/spatial-memory/bulk",
        json={"action": "delete", "ids": [s3["id"]]},
    )
    assert r_bulk_del.status_code == 200
    assert r_bulk_del.json() == {"ok": True, "affected": 1}

    # Single DELETE and 404 checks
    r_del = client.delete(f"/api/spatial-memory/{s2['id']}")
    assert r_del.status_code == 200
    assert r_del.json() == {"deleted": True}
    assert client.patch("/api/spatial-memory/nonexistent", json={"label": "X"}).status_code == 404


def test_inventory_crud_and_idempotent_seed_lab(client: TestClient) -> None:
    """Verify /api/inventory CRUD, filtering, counts, and idempotent seed-lab."""
    # First seed creates curated starter lab hardware
    r_seed1 = client.post("/api/inventory/seed-lab")
    assert r_seed1.status_code == 200
    body1 = r_seed1.json()
    assert body1["seeded"] >= 6
    initial_total = len(body1["items"])
    assert initial_total == body1["seeded"]

    # Second seed is 100% idempotent (0 duplicates added)
    r_seed2 = client.post("/api/inventory/seed-lab")
    assert r_seed2.status_code == 200
    assert r_seed2.json()["seeded"] == 0
    assert len(r_seed2.json()["items"]) == initial_total

    # Create custom wishlist part
    r_create = client.post(
        "/api/inventory",
        json={
            "name": "Hailo-8L M.2 AI Kit",
            "category": "compute",
            "manufacturer": "Raspberry Pi",
            "model": "AI HAT+",
            "quantity": 1,
            "status": "wishlist",
            "interfaces": ["PCIe 2.0"],
            "voltage_v": 3.3,
            "current_ma": 900,
            "capabilities": ["13 TOPS NPU"],
            "est_cost_usd": 70.0,
        },
    )
    assert r_create.status_code == 200
    item_id = r_create.json()["item"]["id"]

    # Filter & summary counts
    r_list = client.get("/api/inventory", params={"status": "wishlist", "query": "hailo"})
    assert r_list.status_code == 200
    listed = r_list.json()
    assert len(listed["items"]) == 1
    assert listed["items"][0]["id"] == item_id
    assert listed["counts"]["wishlist"] >= 1
    assert listed["counts"]["owned"] >= 1
    assert listed["counts"]["total"] == initial_total + 1

    # PATCH status to available & update quantity
    r_upd = client.patch(f"/api/inventory/{item_id}", json={"status": "available", "quantity": 2})
    assert r_upd.status_code == 200
    assert r_upd.json()["item"]["status"] == "available"
    assert r_upd.json()["item"]["quantity"] == 2

    # DELETE
    r_del = client.delete(f"/api/inventory/{item_id}")
    assert r_del.status_code == 200
    assert r_del.json() == {"deleted": True}
    assert client.delete(f"/api/inventory/{item_id}").status_code == 404


def test_devices_profiles_crud_microbit_pizero_and_camera_ingest(client: TestClient) -> None:
    """Verify device profiles, managed devices CRUD, micro:bit probe/cmd, Pi Zero script, and camera ingest."""
    # Profiles
    r_prof = client.get("/api/devices/profiles")
    assert r_prof.status_code == 200
    profiles = r_prof.json()["profiles"]
    assert len(profiles) == 6
    profile_ids = {p["profile_id"] for p in profiles}
    assert {"puppypi_pi5_ros2", "raspberry_pi_zero_2w", "microbit_v2_21", "local_camera_array"} <= profile_ids

    # Managed Devices CRUD
    r_dev = client.post(
        "/api/devices",
        json={
            "name": "Entryway Pi Zero Bridge",
            "profile_id": "raspberry_pi_zero_2w",
            "space_id": "space-entry",
            "transport": "usb_otg_gadget",
            "endpoint": "192.168.1.140",
            "status": "online",
            "config": {"sync_module": "Blink Sync 2"},
        },
    )
    assert r_dev.status_code == 200
    dev_id = r_dev.json()["device"]["id"]

    r_devs = client.get("/api/devices", params={"profile_id": "raspberry_pi_zero_2w"})
    assert r_devs.status_code == 200
    assert [d["id"] for d in r_devs.json()["devices"]] == [dev_id]

    r_patch = client.patch(f"/api/devices/{dev_id}", json={"status": "offline"})
    assert r_patch.status_code == 200
    assert r_patch.json()["device"]["status"] == "offline"

    assert client.delete(f"/api/devices/{dev_id}").json() == {"deleted": True}

    # micro:bit probe & command preview (safe without physical hardware)
    r_probe = client.get("/api/devices/microbit/probe")
    assert r_probe.status_code == 200
    assert {"ports", "volumes", "detected"} <= set(r_probe.json().keys())

    r_cmd = client.post(
        "/api/devices/microbit/command",
        json={"port": "/dev/nonexistent-microbit-test", "action": "show_icon", "payload": {"icon": "HEART"}},
    )
    assert r_cmd.status_code == 200
    cmd_data = r_cmd.json()
    assert cmd_data["ok"] is False
    assert "Image.HEART" in cmd_data["preview_code"]

    # Pi Zero 2 W gadget setup script
    r_script = client.get(
        "/api/devices/pizero/gadget-script",
        params={"docker_host": "192.168.1.89:8000", "device_id": "garage-sync"},
    )
    assert r_script.status_code == 200
    script_body = r_script.json()
    assert script_body["filename"] == "setup_garage-sync_gadget.sh"
    assert "g_mass_storage" in script_body["script"]
    assert "192.168.1.89:8000" in script_body["script"]
    assert len(script_body["instructions"]) >= 3

    # Local camera ingest via multipart JPEG upload
    jpeg_bytes = _make_sample_jpeg()
    r_multi = client.post(
        "/api/devices/cameras/ingest-media",
        files={"file": ("clip_frame.jpg", jpeg_bytes, "image/jpeg")},
        data={"camera_name": "Garage Door", "space_id": "space-garage"},
    )
    assert r_multi.status_code == 200
    multi_data = r_multi.json()
    assert multi_data["ok"] is True
    assert multi_data["camera_source"] == "local_cam:Garage Door"
    assert multi_data["frames_analyzed"] == 1
    assert multi_data["recorded_count"] >= 1
    assert multi_data["sightings"][0]["camera_source"] == "local_cam:Garage Door"

    # Local camera ingest via JSON base64
    b64_str = base64.b64encode(jpeg_bytes).decode("ascii")
    r_json = client.post(
        "/api/devices/cameras/ingest-media",
        json={"image_base64": b64_str, "camera_name": "Front Porch", "space_id": "space-porch"},
    )
    assert r_json.status_code == 200
    json_data = r_json.json()
    assert json_data["ok"] is True
    assert json_data["camera_source"] == "local_cam:Front Porch"
    assert json_data["recorded_count"] >= 1


def test_architect_evaluate_ideate_refine_and_persistence(client: TestClient) -> None:
    """Verify offline Co-Design Architect evaluate, ideate, refine walkthrough, list, and delete."""
    # Seed lab inventory first
    seed_resp = client.post("/api/inventory/seed-lab")
    assert seed_resp.status_code == 200
    items = seed_resp.json()["items"]
    locked_id = items[0]["id"]

    # Evaluate idea at creativity tier 4 with electronics_ee persona
    r_eval = client.post(
        "/api/architect/evaluate",
        json={
            "idea": "Connect BBC micro:bit v2.21 desk alert badge with PuppyPi Pro and local Blink Sync Module 2 clip harvester",
            "creativity_level": 4,
            "persona": "electronics_ee",
            "locked_part_ids": [locked_id],
        },
    )
    assert r_eval.status_code == 200
    eval_data = r_eval.json()
    assert eval_data["ok"] is True
    bp: Dict[str, Any] = eval_data["blueprint"]
    bp_id = bp["id"]
    assert bp["creativity_level"] == 4
    assert bp["persona"] == "electronics_ee"
    assert bp["verdict"] in ("buildable_now", "needs_minor_parts", "hardware_limit")
    assert 1 <= bp["feasibility_score"] <= 100
    assert len(bp["wiring_graph"]["nodes"]) >= 1
    assert len(bp["assembly_3d"]["parts"]) >= 1
    assert len(bp["electrical_checks"]) >= 1

    # Ideate from inventory
    r_ideate = client.post(
        "/api/architect/ideate",
        json={"creativity_level": 5, "focus_area": "security", "count": 3},
    )
    assert r_ideate.status_code == 200
    ideate_data = r_ideate.json()
    assert ideate_data["ok"] is True
    assert len(ideate_data["ideas"]) == 3
    assert ideate_data["model_used"]

    # Refine saved blueprint with point-and-ask and persona switch
    first_node_id = bp["assembly_3d"]["parts"][0]["id"]
    r_refine = client.post(
        f"/api/architect/blueprints/{bp_id}/refine",
        json={
            "message": "Audit single points of failure on this node",
            "selected_node_id": first_node_id,
            "persona": "red_team",
            "creativity_level": 3,
        },
    )
    assert r_refine.status_code == 200
    refined = r_refine.json()["blueprint"]
    assert refined["id"] == bp_id
    assert refined["persona"] == "red_team"
    assert len(refined["versions"]) >= 2
    assert len(refined["chat_history"]) >= 4

    # List & delete saved blueprints
    r_list = client.get("/api/architect/blueprints")
    assert r_list.status_code == 200
    assert any(b["id"] == bp_id for b in r_list.json()["blueprints"])

    r_del = client.delete(f"/api/architect/blueprints/{bp_id}")
    assert r_del.status_code == 200
    assert r_del.json() == {"deleted": True}
    assert client.post(f"/api/architect/blueprints/{bp_id}/refine", json={"message": "hi"}).status_code == 404
