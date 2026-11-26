"""Cyber-physical equipment completeness scoring and Dark/Incomplete Focus Priority Queue."""

from __future__ import annotations

from typing import Any, List, Sequence

from src.lidar.dark_zones import SpatialDarkZone


def score_equipment_completeness(asset: dict[str, Any]) -> dict[str, Any]:
    """Compute a weighted 0–100% completeness score and missing-field checklist for an asset.

    Rubric weights:
      - Physical pose & dimensions: 15%
      - OEM Manufacturer & Model Number: 20%
      - Serial Number or Deterministic Barcode: 20%
      - DEXPI Class & Electrical/Operating Specs: 15%
      - Cyber Identifiers (MAC / IP / Hostname): 15%
      - Direct Research Enrichment (CPE-2.3 + Datasheet/CVE Posture): 15%

    Args:
        asset: Equipment asset dictionary.

    Returns:
        Dictionary with ``completeness_pct``, ``status`` (``DARK``, ``INCOMPLETE``, ``VERIFIED``),
        ``missing_fields``, and ``next_actions``.
    """
    score = 0
    missing: List[str] = []
    actions: List[str] = []

    # 1. Physical geometry & pose (15)
    if asset.get("width_m", 0) > 0 and asset.get("depth_m", 0) > 0:
        score += 15
    else:
        missing.append("dimensions")
        actions.append("Measure or enrich physical WxDxH dimensions.")

    # 2. OEM Make & Model (20)
    mfg = str(asset.get("manufacturer") or "").strip()
    mod = str(asset.get("model_number") or "").strip()
    valid_mfg = bool(mfg and mfg.lower() not in {"unknown", "pending openrouter key"})
    valid_mod = bool(mod and mod.lower() not in {"unknown", "pending openrouter key"})
    if valid_mfg:
        score += 10
    else:
        missing.append("manufacturer")
    if valid_mod:
        score += 10
    else:
        missing.append("model_number")
    if not (valid_mfg and valid_mod):
        actions.append("Capture front-panel or nameplate photo via OpenRouter Vision to resolve Make & Model.")

    # 3. Serial number or barcode (20)
    has_serial = bool(str(asset.get("serial_number") or "").strip())
    has_barcode = bool(asset.get("barcodes"))
    if has_serial and has_barcode:
        score += 20
    elif has_serial or has_barcode:
        score += 14
        if not has_serial:
            missing.append("serial_number")
    else:
        missing.append("serial_number")
        actions.append("Scan rear/side DataMatrix barcode or serial plate.")

    # 4. DEXPI class & electrical specs (15)
    dexpi = str(asset.get("dexpi_class") or "").strip()
    if dexpi and dexpi != "Equipment":
        score += 8
    else:
        missing.append("dexpi_class")
    if asset.get("voltage_rating") or asset.get("current_or_power"):
        score += 7
    else:
        missing.append("electrical_rating")
        actions.append("Inspect UL/CE electrical rating plate or run Direct Research enrichment.")

    # 5. Cyber identifiers (15)
    has_cyber = bool(asset.get("mac_addresses") or asset.get("ip_or_hostname_labels"))
    if has_cyber:
        score += 15
    else:
        missing.append("cyber_identifiers")
        actions.append("Capture network port / MAC / hostname label to link with Cyber Digital Twin.")

    # 6. Direct research & CVE/CPE enrichment (15)
    enrichment = asset.get("enrichment") or {}
    has_cpe = bool(asset.get("inferred_cpe_23"))
    has_research = bool(enrichment.get("enriched_at"))
    if has_cpe:
        score += 7
    else:
        missing.append("cpe_23")
    if has_research:
        score += 8
    else:
        missing.append("research_enrichment")
        actions.append("Run Pass-3 Direct Research Lookup (specs, EoL, NVD CPE/CVE & EPSS).")

    if score < 45:
        status = "DARK"
    elif score < 80:
        status = "INCOMPLETE"
    else:
        status = "VERIFIED"

    return {
        "completeness_pct": score,
        "status": status,
        "missing_fields": missing,
        "next_actions": actions,
    }


def build_priority_focus_queue(
    dark_zones: Sequence[SpatialDarkZone],
    equipment: Sequence[dict[str, Any]],
) -> List[dict[str, Any]]:
    """Merge spatial dark zones, unidentified clusters, and incomplete assets into one priority queue.

    Args:
        dark_zones: Spatial occlusion shadows and unidentified LiDAR clusters.
        equipment: Placed equipment assets with optional enrichment metadata.

    Returns:
        Priority-sorted list of actionable focus items for 2D/3D/Graph camera targeting.
    """
    queue: List[dict[str, Any]] = []

    for dz in dark_zones:
        queue.append(
            {
                "id": dz.id,
                "category": dz.kind,
                "title": dz.label,
                "status": "DARK",
                "priority_score": dz.priority_score,
                "completeness_pct": 0,
                "target_x": round(dz.centroid_x, 4),
                "target_y": round(dz.centroid_y, 4),
                "nbv": {"x": round(dz.nbv_x, 3), "y": round(dz.nbv_y, 3), "yaw_deg": round(dz.nbv_yaw_deg, 1)},
                "missing_fields": ["spatial_coverage" if dz.kind == "occlusion_shadow" else "asset_identity"],
                "recommended_action": dz.recommended_action,
            }
        )

    for eq in equipment:
        comp = score_equipment_completeness(eq)
        if comp["completeness_pct"] >= 95:
            continue
        priority = int(min(96, max(20, 100 - comp["completeness_pct"])))
        queue.append(
            {
                "id": f"asset-focus:{eq['id']}",
                "equipment_id": eq["id"],
                "category": "incomplete_asset",
                "title": eq["name"],
                "status": comp["status"],
                "priority_score": priority,
                "completeness_pct": comp["completeness_pct"],
                "target_x": round(float(eq["x"]), 4),
                "target_y": round(float(eq["y"]), 4),
                "missing_fields": comp["missing_fields"],
                "recommended_action": comp["next_actions"][0] if comp["next_actions"] else "Verify specs.",
            }
        )

    queue.sort(key=lambda item: item["priority_score"], reverse=True)
    return queue
