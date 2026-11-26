"""Unit tests for Asset Completeness scoring, Priority Focus Queue, and Direct Research Enrichment."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from src.enrichment.research_enricher import DirectResearchEnricher
from src.lidar.dark_zones import SpatialDarkZone
from src.twin.completeness import build_priority_focus_queue, score_equipment_completeness


def test_completeness_scorer_distinguishes_dark_incomplete_and_verified() -> None:
    """Completeness rubric accurately scores DARK, INCOMPLETE, and VERIFIED equipment assets."""
    dark_asset = {"name": "Box 1", "manufacturer": "Unknown", "model_number": "Unknown", "width_m": 0.6, "depth_m": 0.6}
    c_dark = score_equipment_completeness(dark_asset)
    assert c_dark["status"] == "DARK"
    assert "manufacturer" in c_dark["missing_fields"]
    assert "serial_number" in c_dark["missing_fields"]

    verified_asset = {
        "name": "Siemens S7-1500",
        "manufacturer": "Siemens",
        "model_number": "6ES7515",
        "serial_number": "SN-9910",
        "barcodes": [{"format": "DataMatrix", "text": "SN-9910"}],
        "dexpi_class": "ProgrammableLogicController",
        "voltage_rating": "24V DC",
        "mac_addresses": ["00:1B:1B:11:22:33"],
        "inferred_cpe_23": "cpe:2.3:h:siemens:simatic_s7-1500:*:*:*:*:*:*:*:*",
        "enrichment": {"enriched_at": "2026-11-24T00:00:00Z"},
        "width_m": 0.35,
        "depth_m": 0.25,
    }
    c_ver = score_equipment_completeness(verified_asset)
    assert c_ver["status"] == "VERIFIED"
    assert c_ver["completeness_pct"] == 100


def test_priority_focus_queue_orders_highest_priority_first() -> None:
    """Focus queue merges spatial dark zones and incomplete assets sorted by priority."""
    dz = SpatialDarkZone(
        id="dark-shadow-0",
        kind="occlusion_shadow",
        label="Shadow #1",
        centroid_x=2.5,
        centroid_y=1.2,
        area_m2=1.4,
        priority_score=88,
        nbv_x=1.5,
        nbv_y=0.8,
        nbv_yaw_deg=35.0,
        polygon=[[2, 1], [3, 1], [3, 2]],
        recommended_action="Move right to scan behind rack.",
    )
    eq = {"id": "eq-1", "name": "Unknown Cabinet", "manufacturer": "Unknown", "model_number": "Unknown", "x": 1.0, "y": 1.0, "width_m": 0.8, "depth_m": 0.8}
    queue = build_priority_focus_queue([dz], [eq])
    assert len(queue) == 2
    assert queue[0]["priority_score"] >= queue[1]["priority_score"]


@pytest.mark.asyncio
async def test_direct_research_enricher_openrouter_nvd_and_epss() -> None:
    """Pass-3 enricher fuses OpenRouter web research with NVD CVE and FIRST EPSS scores."""
    enricher = DirectResearchEnricher(openrouter_api_key="sk-or-test")
    or_response = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "official_name": "Siemens SIMATIC S7-1500 CPU 1515-2 PN",
                            "dexpi_class": "ProgrammableLogicController",
                            "inferred_cpe_23": "cpe:2.3:h:siemens:simatic_s7-1500:*:*:*:*:*:*:*:*",
                            "dimensions_m": {"width_m": 0.175, "depth_m": 0.147, "height_m": 0.129},
                            "voltage_rating": "24V DC",
                            "protocols": ["PROFINET", "OPC-UA", "Modbus TCP"],
                            "lifecycle_status": "Active",
                            "datasheet_summary": "Modular industrial controller with dual PROFINET interfaces.",
                            "recommended_field_checks": ["Check firmware on display"],
                            "citations": ["https://mall.industry.siemens.com/"],
                        }
                    )
                }
            }
        ]
    }
    nvd_response = {
        "totalResults": 1,
        "vulnerabilities": [
            {
                "cve": {
                    "id": "CVE-2023-28489",
                    "metrics": {"cvssMetricV31": [{"cvssData": {"baseScore": 8.8}}]},
                    "descriptions": [{"lang": "en", "value": "Sample industrial controller vulnerability."}],
                }
            }
        ],
    }
    epss_response = {"data": [{"cve": "CVE-2023-28489", "epss": "0.4125"}]}

    with patch.object(
        enricher,
        "_request_json_with_retry",
        new=AsyncMock(side_effect=[or_response, nvd_response, epss_response]),
    ):
        dossier = await enricher.enrich_asset(
            {"name": "S7-1500", "manufacturer": "Siemens", "model_number": "6ES7515"},
            include_nvd=True,
        )

    assert dossier["lifecycle_status"] == "Active"
    assert dossier["dimensions_m"]["width_m"] == 0.175
    assert dossier["cyber_posture"]["cve_count"] == 1
    assert dossier["cyber_posture"]["max_cvss"] == 8.8
    assert dossier["cyber_posture"]["max_epss"] == 0.4125
