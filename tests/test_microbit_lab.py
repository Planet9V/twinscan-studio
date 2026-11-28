"""Unit and API tests for the dedicated BBC micro:bit v2.2 3D Prototyping Lab."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes_microbit import router as microbit_router
from src.db.repository import InMemoryTwinRepository
from src.microbit.catalog import generate_prototype_code, validate_project_wiring
from src.microbit.project_store import MicrobitProjectStore


def test_pin_conflict_validation_and_code_generation() -> None:
    """Detects pin conflicts cleanly and generates runnable MicroPython for attached parts."""
    good = [
        {"accessory_id": "sg90_servo", "label": "Arm Servo", "pin": "P0"},
        {"accessory_id": "neopixel_8", "label": "LED Strip", "pin": "P1"},
    ]
    res_ok = validate_project_wiring(good)
    assert res_ok["ok"] is True
    assert len(res_ok["conflicts"]) == 0
    assert len(res_ok["wiring_steps"]) == 6

    bad = [
        {"accessory_id": "sg90_servo", "label": "Servo 1", "pin": "P0"},
        {"accessory_id": "pir_motion", "label": "Motion", "pin": "P0"},
    ]
    res_bad = validate_project_wiring(bad)
    assert res_bad["ok"] is False
    assert any("P0" in c for c in res_bad["conflicts"])

    code = generate_prototype_code(good, project_name="Robot Arm Test")
    assert "neopixel" in code
    assert "pin0.set_analog_period(20)" in code


def test_microbit_lab_api_projects_and_catalog() -> None:
    """Catalog, project creation, attachment update, and code generation routes work end-to-end."""
    app = FastAPI()
    repo = InMemoryTwinRepository()
    store = MicrobitProjectStore()
    store.attach_repository(repo)
    app.state.twin_repo = repo
    app.state.microbit_store = store
    app.include_router(microbit_router)
    client = TestClient(app)

    r_cat = client.get("/api/microbit/catalog")
    assert r_cat.status_code == 200
    assert len(r_cat.json()["pins"]) >= 8
    assert len(r_cat.json()["accessories"]) >= 6

    r_create = client.post("/api/microbit/projects", json={"name": "Smart Lamp Controller"})
    assert r_create.status_code == 200
    pid = r_create.json()["project"]["id"]

    r_upd = client.patch(
        f"/api/microbit/projects/{pid}",
        json={
            "attachments": [
                {"accessory_id": "pir_motion", "label": "Desk PIR", "pin": "P2"},
                {"accessory_id": "external_speaker", "label": "Loud Speaker", "pin": "P0"},
            ]
        },
    )
    assert r_upd.status_code == 200
    assert r_upd.json()["project"]["wiring"]["ok"] is True

    r_gen = client.post(f"/api/microbit/projects/{pid}/generate-code")
    assert r_gen.status_code == 200
    assert "MOTION_DETECTED" in r_gen.json()["code"]
    assert "music.play" in r_gen.json()["code"]

    r_chat = client.post(
        f"/api/microbit/projects/{pid}/chat",
        json={"message": "Attach a servo and on lift say 'Weeee!' and on left button play a chime"},
    )
    assert r_chat.status_code == 200
    body = r_chat.json()
    assert body["ok"] is True
    proj = body["project"]
    assert any(a["accessory_id"] == "sg90_servo" for a in proj["attachments"])
    triggers = {r["trigger"]: r for r in proj["sim_rules"]}
    assert "lift" in triggers and "Wee" in triggers["lift"]["speak_text"]
    assert "button_a" in triggers and triggers["button_a"]["sound_effect"] == "chime"
    assert "speech.pronounce" in proj["code"]
    assert len(proj["chat_history"]) == 2
