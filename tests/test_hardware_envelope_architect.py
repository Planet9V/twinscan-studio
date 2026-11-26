"""Unit tests for Universal Hardware Envelope, micro:bit bridge, Local Camera Bridge, and Lab Architect."""

from __future__ import annotations

import os
import tempfile
from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest

from src.ai.lab_architect import (
    CREATIVITY_TIERS,
    PERSONA_PROMPTS,
    evaluate_design_idea,
    generate_inventory_ideas,
    refine_blueprint,
)
from src.db.repository import InMemoryTwinRepository
from src.db.robot_ai_store import InMemoryRobotAiStore
from src.devices.envelope import (
    build_starter_lab_inventory,
    get_device_profile,
    list_device_profiles,
)
from src.devices.local_camera_bridge import (
    extract_frames_from_media,
    generate_pi_zero_gadget_setup_script,
    ingest_local_media_to_spatial_memory,
)
from src.devices.microbit_bridge import (
    build_led_matrix_python,
    generate_microbit_template,
    probe_microbit_usb,
    send_microbit_serial_command,
)


def _sample_inventory() -> list[dict]:
    items = build_starter_lab_inventory()
    for idx, item in enumerate(items, start=1):
        item["id"] = f"inv-{idx}"
    return items


def test_device_profiles_and_starter_inventory() -> None:
    """Verify all 6 universal hardware device profiles and starter lab inventory fields."""
    profiles = list_device_profiles()
    ids = {p["profile_id"] for p in profiles}
    assert ids == {
        "puppypi_pi5_ros2",
        "raspberry_pi_5_node",
        "raspberry_pi_zero_2w",
        "microbit_v2_21",
        "local_camera_array",
        "generic_sensor_module",
    }
    mb = get_device_profile("microbit_v2_21")
    assert mb is not None
    assert mb["max_gpio_v"] == 3.3
    assert len(mb["firmware_templates"]) == 3
    assert get_device_profile("nonexistent") is None

    starter = build_starter_lab_inventory()
    assert len(starter) >= 8
    assert any("PuppyPi" in i["name"] for i in starter)
    assert any("micro:bit" in i["name"] for i in starter)
    assert any("Pi Zero 2 W" in i["name"] for i in starter)


def test_microbit_bridge_matrix_templates_and_offline_preview() -> None:
    """Verify micro:bit probe, 5x5 LED matrix codegen, templates, and safe offline command preview."""
    probe = probe_microbit_usb()
    assert "ports" in probe and "volumes" in probe and isinstance(probe["detected"], bool)

    tpl = generate_microbit_template("serial_sensor_hub")
    assert tpl["id"] == "serial_sensor_hub"
    assert "accelerometer" in tpl["code"]

    with pytest.raises(ValueError):
        generate_microbit_template("unknown_tpl")

    grid = [[9, 0, 0, 0, 9]] * 5
    code = build_led_matrix_python(grid)
    assert "Image('90009:90009:90009:90009:90009')" in code

    res = send_microbit_serial_command(port="/dev/nonexistent_microbit_port", action="show_text", payload={"text": "HEY OX"})
    assert res["ok"] is False
    assert "HEY OX" in res["preview_code"]

    res_matrix = send_microbit_serial_command(port="/dev/nonexistent_microbit_port", action="set_matrix", payload={"grid": grid})
    assert "90009:90009" in res_matrix["preview_code"]


def test_local_camera_bridge_gadget_script_and_frame_extraction() -> None:
    """Verify Pi Zero g_mass_storage script generation and JPEG + MP4 frame extraction."""
    gadget = generate_pi_zero_gadget_setup_script(docker_host="192.168.1.89:8000", device_id="blink-sync-01")
    assert gadget["filename"] == "setup_blink-sync-01_gadget.sh"
    assert "g_mass_storage" in gadget["script"]
    assert 'TWINSCAN_HOST="192.168.1.89:8000"' in gadget["script"]
    assert "/api/devices/cameras/ingest-media" in gadget["script"]
    assert "mount -o loop,ro" in gadget["script"]
    assert len(gadget["instructions"]) >= 3

    # JPEG extraction
    img = np.full((120, 160, 3), 180, dtype=np.uint8)
    cv2.rectangle(img, (20, 20), (140, 100), (20, 90, 224), 3)
    ok, jpg = cv2.imencode(".jpg", img)
    assert ok
    frames = extract_frames_from_media(jpg.tobytes(), "test.jpg", max_frames=3)
    assert len(frames) == 1
    assert frames[0].shape == (120, 160, 3)

    # Synthetic MP4 clip extraction
    tmp_mp4 = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tf:
            tmp_mp4 = tf.name
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(tmp_mp4, fourcc, 10.0, (160, 120))
        for i in range(12):
            frame = np.full((120, 160, 3), 40 + i * 10, dtype=np.uint8)
            cv2.circle(frame, (30 + i * 8, 60), 18, (255, 255, 255), 2)
            writer.write(frame)
        writer.release()
        mp4_bytes = open(tmp_mp4, "rb").read()
        mp4_frames = extract_frames_from_media(mp4_bytes, "clip.mp4", max_frames=3)
        assert 1 <= len(mp4_frames) <= 3
    finally:
        if tmp_mp4 and os.path.exists(tmp_mp4):
            os.unlink(tmp_mp4)


@pytest.mark.asyncio
async def test_ingest_local_media_to_spatial_memory_offline() -> None:
    """Verify cloud-free local JPEG ingest stores file and records object + face sightings."""
    repo = InMemoryTwinRepository()
    ai_store = InMemoryRobotAiStore()

    fake_vision = MagicMock()
    fake_vision.detect_faces_and_embeddings.return_value = [
        {"bbox_norm": [0.1, 0.1, 0.4, 0.5], "confidence": 0.91, "embedding": [0.1] * 128}
    ]
    fake_vision.detect_objects_and_animals.return_value = [
        {"label": "dog", "confidence": 0.87, "is_animal": True, "bbox_norm": [0.2, 0.2, 0.8, 0.8]}
    ]

    img = np.full((120, 160, 3), 200, dtype=np.uint8)
    _, jpg = cv2.imencode(".jpg", img)

    result = await ingest_local_media_to_spatial_memory(
        ai_vision_engine=fake_vision,
        ai_store=ai_store,
        repo=repo,
        camera_name="Porch Blink Sync",
        space_id="space-1",
        robot_id="local-cam-1",
        media_bytes=jpg.tobytes(),
        filename="porch.jpg",
    )
    assert result["ok"] is True
    assert result["camera_source"] == "local_cam:Porch Blink Sync"
    assert result["frames_analyzed"] == 1
    assert result["recorded_count"] == 2
    labels = {s["label"] for s in result["sightings"]}
    assert "dog" in labels and "Unknown Person" in labels


@pytest.mark.asyncio
async def test_lab_architect_evaluate_ideate_and_refine() -> None:
    """Verify 5-tier creativity evaluation, electrical guardrails, ideation, and iterative refinement."""
    assert set(CREATIVITY_TIERS.keys()) == {1, 2, 3, 4, 5}
    assert set(PERSONA_PROMPTS.keys()) == {"systems_architect", "electronics_ee", "robotics_cv", "red_team"}

    inv = _sample_inventory()
    puppypi_id = inv[0]["id"]
    gamepad_id = inv[7]["id"]

    # Tier 1: Strictly owned parts only
    bp_t1 = await evaluate_design_idea(
        idea="Build a local PuppyPi room patrol with micro:bit desk badge and Blink camera clip alert",
        inventory_items=inv,
        creativity_level=1,
        persona="electronics_ee",
        locked_part_ids=[puppypi_id],
        excluded_part_ids=[gamepad_id],
    )
    assert bp_t1["creativity_level"] == 1
    assert bp_t1["missing_parts"] == []
    assert bp_t1["verdict"] == "buildable_now"
    assert all(p.get("inventory_id") != gamepad_id for p in bp_t1["parts_used"])
    assert any(p.get("inventory_id") == puppypi_id for p in bp_t1["parts_used"])
    assert len(bp_t1["wiring_graph"]["nodes"]) == len(bp_t1["assembly_3d"]["parts"])
    topics = " ".join(c["topic"].lower() for c in bp_t1["electrical_checks"])
    assert "3.3v" in topics or "usb" in topics

    # Tier 5: Moonshot upgrades proposed
    bp_t5 = await evaluate_design_idea(
        idea="Autonomous multi-room spatial intelligence with PuppyPi, LD19 LiDAR, micro:bit, and Blink cameras",
        inventory_items=inv,
        creativity_level=5,
        persona="red_team",
    )
    assert bp_t5["creativity_level"] == 5
    assert len(bp_t5["missing_parts"]) >= 2
    assert len(bp_t5["build_tonight_vs_moonshot"]["tonight"]) >= 1
    assert len(bp_t5["build_tonight_vs_moonshot"]["moonshot"]) >= 1

    # Iterative refinement: promote first missing part + point-and-ask on hub node
    first_missing = bp_t5["missing_parts"][0]["name"]
    first_node_id = bp_t5["assembly_3d"]["parts"][0]["id"]
    bp_v2 = await refine_blueprint(
        blueprint=bp_t5,
        message="Audit power margin and accept the recommended upgrade.",
        inventory_items=inv,
        selected_node_id=first_node_id,
        persona="electronics_ee",
        accept_missing_part=first_missing,
    )
    assert len(bp_v2["versions"]) == 2
    assert len(bp_v2["chat_history"]) == 4
    assert any(p["name"] == first_missing for p in bp_v2["parts_used"])

    # Ideation generator
    ideas, model_used = await generate_inventory_ideas(
        inventory_items=inv,
        creativity_level=4,
        focus_area="security",
        count=4,
    )
    assert len(ideas) == 4
    assert model_used == "deterministic-local-architect"
    assert all(i["creativity_level"] == 4 for i in ideas)
