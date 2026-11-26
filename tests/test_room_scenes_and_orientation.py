"""Unit and FastAPI integration tests for Room/Scene Management, LD19 Orientation, and ROS 2 LD19 Launch."""

from __future__ import annotations

import inspect
import math
from typing import Any, List

from fastapi.testclient import TestClient

from src.api.state import compute_cardinal_distances_m
from src.app.config import Settings
from src.app.factory import create_app
from src.db.repository import InMemoryTwinRepository
from src.db.robot_ai_store import InMemoryRobotAiStore
from src.db.robot_store import InMemoryRobotStore
from src.lidar.ld19_parser import LidarPoint, polar_to_cartesian
from src.robot import ssh_manager


def _build_client() -> TestClient:
    """Create an isolated in-memory FastAPI TestClient."""
    settings = Settings(database_url="", neo4j_uri="", openrouter_api_key="")
    app = create_app(
        settings=settings,
        repository=InMemoryTwinRepository(),
        robot_store=InMemoryRobotStore(),
        robot_ai_store=InMemoryRobotAiStore(),
    )
    return TestClient(app)


def test_spaces_enriched_summary_rename_clone_and_delete() -> None:
    """Verify GET /spaces enrichment, PATCH /spaces/{id}, POST /spaces/{id}/clone, and DELETE panel cleanup."""
    with _build_client() as client:
        rt = client.app.state.runtime
        ai_store = client.app.state.robot_ai_store
        orig_id = rt.active_space_id

        # Populate original space with walls, zones, equipment, and 2 scene panels.
        rt.repo.save_walls(orig_id, [{"x1": -2.0, "y1": 2.0, "x2": 2.0, "y2": 2.0, "length_m": 4.0}], {"area_m2": 12.0})
        rt.repo.save_zones(orig_id, [{"id": "z1", "name": "Keepout", "polygon": [[0, 0], [1, 0], [1, 1]], "threshold": 3}])
        rt.repo.create_equipment(orig_id, {"name": "PLC Cabinet A", "x": 1.0, "y": 1.5})
        ai_store.save_scene_panel(
            {"space_id": orig_id, "label": "Wall 1", "texture_file_id": "tex-old", "glb_file_id": "glb-old"}
        )
        ai_store.save_scene_panel(
            {
                "space_id": orig_id,
                "label": "Wall 2",
                "texture_file_id": "tex-latest",
                "normal_map_file_id": "norm-latest",
                "glb_file_id": "glb-latest",
            }
        )

        # 1. GET /api/spaces returns enriched summary counts and latest panel thumbnail.
        list_resp = client.get("/api/spaces")
        assert list_resp.status_code == 200
        spaces = list_resp.json()["spaces"]
        orig_summary = next(s for s in spaces if s["id"] == orig_id)
        assert orig_summary["panel_count"] == 2
        assert orig_summary["equipment_count"] == 1
        assert orig_summary["wall_count"] == 1
        assert orig_summary["thumbnail_url"] == "/api/files/tex-latest"

        # 2. PATCH /api/spaces/{id} renames and updates metadata cleanly.
        patch_resp = client.patch(
            f"/api/spaces/{orig_id}",
            json={"name": "East Office", "facility": "HQ Floor 2", "description": "Primary office scan"},
        )
        assert patch_resp.status_code == 200
        patched = patch_resp.json()
        assert patched["name"] == "East Office"
        assert patched["facility"] == "HQ Floor 2"
        assert patched["description"] == "Primary office scan"
        assert patched["panel_count"] == 2
        assert patched["thumbnail_url"] == "/api/files/tex-latest"

        assert client.patch("/api/spaces/does-not-exist", json={"name": "Nope"}).status_code == 404

        # 3. POST /api/spaces/{id}/clone copies walls, zones, scene_panels (zero-copy files), and equipment.
        clone_resp = client.post(
            f"/api/spaces/{orig_id}/clone",
            json={"name": "East Office Checkpoint 1"},
        )
        assert clone_resp.status_code == 200, clone_resp.text
        clone_data = clone_resp.json()
        cloned_space = clone_data["space"]
        cloned_id = cloned_space["id"]
        assert cloned_id != orig_id
        assert clone_data["cloned_panels"] == 2
        assert clone_data["cloned_equipment"] == 1
        assert cloned_space["panel_count"] == 2
        assert cloned_space["equipment_count"] == 1
        assert cloned_space["wall_count"] == 1
        assert cloned_space["thumbnail_url"] == "/api/files/tex-latest"
        assert rt.active_space_id == cloned_id

        # Verify cloned panels got new IDs while reusing stored file IDs zero-copy.
        orig_panel_ids = {p["id"] for p in ai_store.list_scene_panels(orig_id)}
        cloned_panels = ai_store.list_scene_panels(cloned_id)
        assert len(cloned_panels) == 2
        assert {p["id"] for p in cloned_panels}.isdisjoint(orig_panel_ids)
        assert {p["texture_file_id"] for p in cloned_panels} == {"tex-old", "tex-latest"}

        # 4. DELETE /api/spaces/{id} clears that space's scene_panels without harming the other space.
        del_resp = client.delete(f"/api/spaces/{cloned_id}")
        assert del_resp.status_code == 200
        assert del_resp.json()["deleted"] is True
        assert ai_store.list_scene_panels(cloned_id) == []
        assert len(ai_store.list_scene_panels(orig_id)) == 2


def test_lidar_rotation_offset_partial_update_and_cardinal_distances() -> None:
    """Verify rotation_offset_deg transforms rays, preserves other filters, and populates cardinal_m."""
    # Synthetic raw scan with distinct distances at 0 deg (+X), 90 deg (+Y), 180 deg (-X), 270 deg (-Y).
    raw_specs = [
        (0.0, 1.25),   # LD19 forward arrow (0 deg)
        (2.0, 1.25),
        (358.0, 1.25),
        (90.0, 2.50),
        (180.0, 3.75),
        (270.0, 4.50),
    ]
    raw_pts: List[LidarPoint] = []
    for ang, dist in raw_specs:
        x, y = polar_to_cartesian(ang, dist)
        raw_pts.append(LidarPoint(angle_deg=ang, distance_m=dist, intensity=200, x=x, y=y))

    # Direct cardinal calculation at 0 deg offset.
    card0 = compute_cardinal_distances_m(raw_pts)
    assert card0["right"] == 1.25
    assert card0["front"] == 2.5
    assert card0["left"] == 3.75
    assert card0["back"] == 4.5

    with _build_client() as client:
        rt = client.app.state.runtime
        rt.filter_config.max_range_m = 7.5
        rt.process_scan(raw_pts, run_analytics=True)

        snap0 = client.get("/api/lidar/snapshot").json()
        assert snap0["rotation_offset_deg"] == 0.0
        assert snap0["cardinal_m"]["right"] == 1.25
        assert snap0["cardinal_m"]["front"] == 2.5

        # Partial update: send ONLY rotation_offset_deg=90 -> must preserve max_range_m=7.5!
        # Rotating +90 deg moves raw 0 deg (1.25m) to 90 deg (+Y = FRONT)!
        f_resp = client.post("/api/lidar/filters", json={"rotation_offset_deg": 90})
        assert f_resp.status_code == 200
        f_data = f_resp.json()
        assert f_data["rotation_offset_deg"] == 90.0
        assert f_data["filters"]["max_range_m"] == 7.5

        snap90 = client.get("/api/lidar/snapshot").json()
        assert snap90["rotation_offset_deg"] == 90.0
        assert snap90["cardinal_m"]["front"] == 1.25
        assert snap90["cardinal_m"]["left"] == 2.5
        assert snap90["cardinal_m"]["back"] == 3.75
        assert snap90["cardinal_m"]["right"] == 4.5

        # Negative rotation angle normalizes cleanly mod 360.
        f_neg = client.post("/api/lidar/filters", json={"rotation_offset_deg": -90})
        assert f_neg.status_code == 200
        assert f_neg.json()["rotation_offset_deg"] == 270.0


def test_robot_ros2_defaults_rotation_offset_to_90_unless_overridden() -> None:
    """Verify switching to robot_ros2 defaults rotation_offset_deg to 90 deg while respecting user choice."""
    with _build_client() as client:
        rt = client.app.state.runtime
        assert rt.filter_config.rotation_offset_deg == 0.0

        resp = client.post("/api/lidar/settings", json={"source_mode": "robot_ros2"})
        assert resp.status_code == 200
        assert rt.filter_config.rotation_offset_deg == 90.0

        # Explicit user override to 0 deg must be preserved on subsequent settings updates.
        client.post("/api/lidar/filters", json={"rotation_offset_deg": 0})
        client.post("/api/lidar/settings", json={"source_mode": "robot_ros2"})
        assert rt.filter_config.rotation_offset_deg == 0.0


def test_ssh_manager_ros2_ld19_launch_scripts_hardened() -> None:
    """Verify both ROS 2 LD19 launch scripts in ssh_manager use ps -eww + awk ($1!=self && $2!=self), -u ubuntu, CycloneDDS, and direct exec."""
    src = inspect.getsource(ssh_manager)
    assert "pkill -f ldlidar_stl_ros2_node" not in src
    assert "pkill -x ldlidar_stl_ros2_node" not in src
    assert "!/bash/" not in src
    assert src.count("$1 != self && $2 != self && !/awk/ && /ldlidar_stl_ros2/") >= 4
    assert src.count('"-u", "ubuntu", "puppypi_ros2"') >= 4
    assert "ROS_LOCALHOST_ONLY=0" in src
    assert "rmw_cyclonedds_cpp" in src
    assert src.count("exec /home/ubuntu/third_party_ros2/third_party_ws/install/ldlidar_stl_ros2/lib/ldlidar_stl_ros2/ldlidar_stl_ros2_node --ros-args") >= 2
    assert src.count("-p frame_id:=lidar_frame") >= 2
    assert src.count("-p laser_scan_dir:=true") >= 2
    assert src.count("-p enable_angle_crop_func:=false") >= 2
    assert src.count("> /tmp/ldlidar_ros2.log 2>&1") >= 2
