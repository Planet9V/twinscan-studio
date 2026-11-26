"""Unit tests for twin repository semantic search and Neo4j G_CPDT Knowledge Graph store."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.db.repository import InMemoryTwinRepository
from src.graph.neo4j_store import Neo4jKnowledgeGraphStore, build_graph_payload, compute_proximity_edges
from src.vision.openrouter_client import deterministic_fallback_embedding


def test_in_memory_repository_crud_and_semantic_search() -> None:
    """Repository persists spaces/equipment and ranks semantic queries accurately."""
    repo = InMemoryTwinRepository()
    repo.initialize()
    space = repo.list_spaces()[0]

    eq1 = repo.create_equipment(
        space["id"],
        {
            "name": "Cisco Catalyst 9300 Switch",
            "manufacturer": "Cisco",
            "model_number": "C9300-48P",
            "equipment_type": "Network Switch",
            "x": 1.0,
            "y": 1.0,
        },
        embedding=deterministic_fallback_embedding("Cisco Catalyst 9300 Network Switch PoE"),
    )
    repo.create_equipment(
        space["id"],
        {
            "name": "Grundfos Chilled Water Pump",
            "manufacturer": "Grundfos",
            "model_number": "CR32-4",
            "equipment_type": "Pump",
            "x": 3.0,
            "y": 1.0,
        },
        embedding=deterministic_fallback_embedding("Grundfos CR32 Centrifugal Water Pump 480V"),
    )

    q_vec = deterministic_fallback_embedding("Cisco 9300 ethernet switch")
    results = repo.search_equipment_semantic(q_vec, limit=5, space_id=space["id"])
    assert len(results) == 2
    assert results[0]["id"] == eq1["id"]
    assert results[0]["similarity"] > results[1]["similarity"]

    filtered = repo.search_equipment_semantic(q_vec, manufacturer="Grundfos")
    assert len(filtered) == 1
    assert filtered[0]["manufacturer"] == "Grundfos"


def test_graph_payload_and_proximity_edges() -> None:
    """Knowledge graph builder emits Eigenia G_CPDT nodes and spatial NEAR edges."""
    space = {"id": "sp-1", "name": "Pump Room", "facility": "Eigenia Water Plant", "metrics": {"area_m2": 42.0}}
    equipment = [
        {
            "id": "e1",
            "name": "PLC-01",
            "manufacturer": "Siemens",
            "model_number": "S7-1500",
            "asset_tags": ["TAG-100"],
            "mac_addresses": ["00:1B:1B:01:02:03"],
            "x": 1.0,
            "y": 1.0,
        },
        {
            "id": "e2",
            "name": "Pump-01",
            "manufacturer": "Grundfos",
            "model_number": "CR32",
            "asset_tags": [],
            "mac_addresses": [],
            "x": 2.2,
            "y": 1.5,
        },
    ]
    near = compute_proximity_edges(equipment, max_distance_m=2.5)
    assert len(near) == 1
    assert near[0]["distance_m"] < 1.5

    graph = build_graph_payload(space, equipment, max_near_m=2.5)
    node_types = {n["node_type"] for n in graph["nodes"]}
    assert {"Facility", "Space", "Equipment", "Manufacturer", "ProductModel", "IndustrialTag", "CyberIdentifier"} <= node_types
    assert any("NEAR" in e["label"] for e in graph["edges"])


def test_neo4j_store_retries_three_times_and_logs_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    """Neo4j write failures log to stderr and retry 3 times gracefully."""
    store = Neo4jKnowledgeGraphStore(uri="bolt://127.0.0.1:7687", max_retries=3)
    fake_driver = MagicMock()
    fake_driver.session.side_effect = RuntimeError("bolt unreachable")
    with patch.object(store, "_get_driver", return_value=fake_driver), patch("src.graph.neo4j_store.time.sleep"):
        ok = store._run_write_with_retry("RETURN 1", {})
    assert ok is False
    err = capsys.readouterr().err
    assert "attempt 1/3" in err
    assert "attempt 3/3" in err
