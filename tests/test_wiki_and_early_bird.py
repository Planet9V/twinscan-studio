"""Pytest suite for Documentation Wiki API and 50-Spot Early Bird Founding Maker campaign."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.app.config import Settings
from src.app.factory import create_app
from src.db.repository import InMemoryTwinRepository
from src.db.robot_ai_store import InMemoryRobotAiStore
from src.db.robot_store import InMemoryRobotStore


@pytest.fixture()
def wiki_client(tmp_path: Path) -> TestClient:
    """Create an isolated TestClient with a temporary populated docs/wiki directory."""
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    (wiki_dir / "catalogue.json").write_text(
        json.dumps(
            {
                "title": "Eigenia TwinScan Wiki",
                "sections": [{"title": "Onboarding", "pages": ["00-introduction", "01-onboarding-principal"]}],
            }
        ),
        encoding="utf-8",
    )
    (wiki_dir / "00-introduction.md").write_text(
        "---\n"
        'title: "Introduction & Maker Vision"\n'
        'description: "Flagship Hiwonder PuppyPi Pro robotics digital twin."\n'
        "---\n\n"
        "# Introduction & Maker Vision\n\n"
        "Eigenia TwinScan unifies Hiwonder PuppyPi Pro, LD19 360° LiDAR, and 3D room fusion.\n\n"
        "## Hardware Ecosystem\n\n"
        "Supports Pi 5, Pi Zero 2 W, and micro:bit v2.21.\n",
        encoding="utf-8",
    )
    (wiki_dir / "01-onboarding-principal.md").write_text(
        "---\n"
        'title: "Principal Onboarding"\n'
        'description: "Architectural overview for principal engineers."\n'
        "---\n\n"
        "# Principal Onboarding\n\n"
        "Dual Three.js and Babylon.js digital twin backed by Postgres 18 and Neo4j 5.\n",
        encoding="utf-8",
    )

    settings = Settings(database_url="", openrouter_api_key="", neo4j_uri="")
    app = create_app(
        settings=settings,
        repository=InMemoryTwinRepository(),
        robot_store=InMemoryRobotStore(),
        robot_ai_store=InMemoryRobotAiStore(),
    )
    app.state.wiki_dir = wiki_dir
    with TestClient(app) as client:
        yield client


def test_wiki_catalogue_page_fetch_and_path_traversal_protection(wiki_client: TestClient, tmp_path: Path) -> None:
    """Verify /api/wiki/catalogue, /api/wiki/pages/{slug}, prev/next links, 400 on invalid slugs, and empty fallback."""
    # 1. Populated catalogue
    r_cat = wiki_client.get("/api/wiki/catalogue")
    assert r_cat.status_code == 200
    cat = r_cat.json()
    assert "PuppyPi Pro" in cat["flagship_example"]
    assert isinstance(cat["catalogue"], dict)
    slugs = [p["slug"] for p in cat["pages"]]
    assert slugs == ["00-introduction", "01-onboarding-principal"]
    assert cat["pages"][0]["title"] == "Introduction & Maker Vision"
    assert cat["pages"][0]["read_minutes"] >= 1
    assert "Hardware Ecosystem" in cat["pages"][0]["headings"]

    # 2. Fetch page 0 with prev/next navigation
    r_p0 = wiki_client.get("/api/wiki/pages/00-introduction")
    assert r_p0.status_code == 200
    p0 = r_p0.json()
    assert p0["slug"] == "00-introduction"
    assert p0["prev_slug"] is None
    assert p0["next_slug"] == "01-onboarding-principal"
    assert "Hiwonder PuppyPi Pro" in p0["markdown"]

    # 3. Fetch page 1
    r_p1 = wiki_client.get("/api/wiki/pages/01-onboarding-principal")
    assert r_p1.status_code == 200
    assert r_p1.json()["prev_slug"] == "00-introduction"
    assert r_p1.json()["next_slug"] is None

    # 4. Path traversal & invalid slug protection -> HTTP 400
    for bad_slug in ("..etc", "UPPERCASE", "bad_underscore", "foo.md", "a..b"):
        r_bad = wiki_client.get(f"/api/wiki/pages/{bad_slug}")
        assert r_bad.status_code == 400, f"Expected 400 for {bad_slug}, got {r_bad.status_code}"

    # 5. Missing valid slug -> HTTP 404
    assert wiki_client.get("/api/wiki/pages/99-does-not-exist").status_code == 404

    # 6. Graceful fallback when wiki dir does not exist
    wiki_client.app.state.wiki_dir = tmp_path / "nonexistent-wiki"
    r_empty = wiki_client.get("/api/wiki/catalogue")
    assert r_empty.status_code == 200
    assert r_empty.json()["pages"] == []


def test_early_bird_status_claim_anonymization_duplicate_and_50_cap(wiki_client: TestClient) -> None:
    """Verify Early Bird 50-spot campaign: status, valid claim, anonymization, invalid 400, duplicate 409, and 50-cap 409."""
    # 1. Initial status
    r_st = wiki_client.get("/api/early-bird/status")
    assert r_st.status_code == 200
    st = r_st.json()
    assert st["total_spots"] == 50
    assert st["claimed_spots"] == 0
    assert st["remaining_spots"] == 50
    assert st["is_open"] is True
    assert len(st["perks"]) == 6
    assert st["recent_makers"] == []

    # 2. Invalid input -> 400
    assert wiki_client.post("/api/early-bird/claim", json={"name": "A", "email": "ada@lab.io"}).status_code == 400
    assert wiki_client.post("/api/early-bird/claim", json={"name": "Ada Lovelace", "email": "not-an-email"}).status_code == 400

    # 3. Successful claim #1
    r_c1 = wiki_client.post(
        "/api/early-bird/claim",
        json={
            "name": "Ada Lovelace",
            "email": "Ada@RoboticsLab.IO",
            "role": "Robotics Maker",
            "hardware_stack": ["PuppyPi Pro", "Raspberry Pi 5", "micro:bit v2.21"],
            "project_goal": "Autonomous multi-room 3D twin mapping",
        },
    )
    assert r_c1.status_code == 201
    c1 = r_c1.json()
    assert c1["ok"] is True
    assert c1["spot_number"] == 1
    assert c1["total_spots"] == 50
    assert c1["remaining_spots"] == 49
    assert c1["founder_code"] == "EIGENIA-MAKER-01"
    assert c1["display_name"] == "Ada L."
    assert c1["hardware_stack"] == ["PuppyPi Pro", "Raspberry Pi 5", "micro:bit v2.21"]

    # 4. Status reflects claim with email strictly redacted
    st1 = wiki_client.get("/api/early-bird/status").json()
    assert st1["claimed_spots"] == 1
    assert st1["remaining_spots"] == 49
    assert len(st1["recent_makers"]) == 1
    assert st1["recent_makers"][0]["display_name"] == "Ada L."
    assert "email" not in st1["recent_makers"][0]

    # 5. Duplicate email (case-insensitive) -> 409
    r_dup = wiki_client.post(
        "/api/early-bird/claim",
        json={"name": "Ada Duplicate", "email": "ada@roboticslab.io"},
    )
    assert r_dup.status_code == 409

    # 6. Fill remaining spots 2..50 -> all succeed
    for i in range(2, 51):
        res = wiki_client.post(
            "/api/early-bird/claim",
            json={
                "name": f"Maker {i} Builder",
                "email": f"maker{i}@eigenia.dev",
                "role": "Hardware Hacker",
                "hardware_stack": ["PuppyPi Pro"],
            },
        )
        assert res.status_code == 201
        assert res.json()["spot_number"] == i
        assert res.json()["founder_code"] == f"EIGENIA-MAKER-{i:02d}"

    st_full = wiki_client.get("/api/early-bird/status").json()
    assert st_full["claimed_spots"] == 50
    assert st_full["remaining_spots"] == 0
    assert st_full["is_open"] is False

    # 7. Spot #51 strictly rejected with 409
    r_51 = wiki_client.post(
        "/api/early-bird/claim",
        json={"name": "Late Maker", "email": "maker51@eigenia.dev"},
    )
    assert r_51.status_code == 409
