"""Neo4j 5 Knowledge Graph store implementing Eigenia's DEXPI/CycloneDX G_CPDT ontology.

Synchronizes physical spaces, equipment assets, OEM/Model/Tag/Cyber nodes, spatial
NEAR edges, VulnerabilityPosture, EnrichmentSource citations, delete sync, and full
PostgreSQL -> Neo4j reconciliation with try/except, stderr logging, and 3x retry.
"""

from __future__ import annotations

import math
import sys
import time
from typing import Any, List, Optional, Sequence

from neo4j import GraphDatabase

from src.twin.completeness import score_equipment_completeness


def compute_proximity_edges(
    equipment: Sequence[dict[str, Any]],
    max_distance_m: float = 3.0,
) -> List[dict[str, Any]]:
    """Compute pairwise spatial ``NEAR`` relationships between placed equipment assets."""
    edges: List[dict[str, Any]] = []
    items = list(equipment)
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a, b = items[i], items[j]
            dist = math.hypot(float(a["x"]) - float(b["x"]), float(a["y"]) - float(b["y"]))
            if dist <= max_distance_m:
                edges.append({"source": a["id"], "target": b["id"], "distance_m": round(dist, 3)})
    return edges


def build_graph_payload(
    space: dict[str, Any],
    equipment: Sequence[dict[str, Any]],
    anomalies: Sequence[dict[str, Any]] = (),
    dark_zones: Sequence[dict[str, Any]] = (),
    max_near_m: float = 3.0,
) -> dict[str, Any]:
    """Build an enriched Eigenia G_CPDT graph payload (with completeness, risk & dark zones)."""
    nodes: List[dict[str, Any]] = []
    edges: List[dict[str, Any]] = []
    seen_nodes: set[str] = set()

    def add_node(node_id: str, label: str, node_type: str, meta: dict[str, Any]) -> None:
        if node_id in seen_nodes:
            return
        seen_nodes.add(node_id)
        nodes.append({"id": node_id, "label": label, "node_type": node_type, "meta": meta})

    fac_id = f"facility:{space.get('facility', 'Eigenia Facility')}"
    space_id = f"space:{space['id']}"
    add_node(fac_id, space.get("facility", "Eigenia Facility"), "Facility", {})
    add_node(space_id, space["name"], "Space", {"metrics": space.get("metrics", {})})
    edges.append({"id": f"e:{fac_id}->{space_id}", "source": fac_id, "target": space_id, "label": "CONTAINS"})

    for eq in equipment:
        comp = score_equipment_completeness(eq)
        enrichment = eq.get("enrichment") or {}
        posture = enrichment.get("cyber_posture") or {}
        eq_node_id = f"equipment:{eq['id']}"
        add_node(
            eq_node_id,
            eq["name"],
            "Equipment",
            {
                "equipment_id": eq["id"],
                "equipment_type": eq.get("equipment_type"),
                "dexpi_class": eq.get("dexpi_class"),
                "manufacturer": eq.get("manufacturer"),
                "model_number": eq.get("model_number"),
                "serial_number": eq.get("serial_number"),
                "x": eq.get("x"),
                "y": eq.get("y"),
                "cpe_23": eq.get("inferred_cpe_23"),
                "completeness_pct": comp["completeness_pct"],
                "status": comp["status"],
                "missing_fields": comp["missing_fields"],
                "cve_count": posture.get("cve_count", 0),
                "max_epss": posture.get("max_epss", 0.0),
                "enriched": bool(enrichment.get("enriched_at")),
            },
        )
        edges.append(
            {
                "id": f"e:{eq_node_id}->{space_id}",
                "source": eq_node_id,
                "target": space_id,
                "label": f"LOCATED_IN ({eq['x']:.1f}m, {eq['y']:.1f}m)",
            }
        )

        mfg = (eq.get("manufacturer") or "Unknown").strip()
        if mfg and mfg not in {"Unknown", "Pending OpenRouter Key"}:
            mfg_id = f"mfg:{mfg.lower()}"
            add_node(mfg_id, mfg, "Manufacturer", {})
            edges.append({"id": f"e:{eq_node_id}->{mfg_id}", "source": eq_node_id, "target": mfg_id, "label": "MADE_BY"})

        model = (eq.get("model_number") or "Unknown").strip()
        if model and model not in {"Unknown", "Pending OpenRouter Key"}:
            mod_id = f"model:{mfg.lower()}:{model.lower()}"
            add_node(
                mod_id,
                model,
                "ProductModel",
                {"cpe_23": eq.get("inferred_cpe_23"), "dexpi_class": eq.get("dexpi_class")},
            )
            edges.append({"id": f"e:{eq_node_id}->{mod_id}", "source": eq_node_id, "target": mod_id, "label": "IS_MODEL"})

        for tag in eq.get("asset_tags") or []:
            tag_id = f"tag:{tag}"
            add_node(tag_id, tag, "IndustrialTag", {"tag": tag})
            edges.append({"id": f"e:{eq_node_id}->{tag_id}", "source": eq_node_id, "target": tag_id, "label": "HAS_TAG"})

        for cyb in list(eq.get("mac_addresses") or []) + list(eq.get("ip_or_hostname_labels") or []):
            cyb_id = f"cyber:{cyb}"
            add_node(cyb_id, cyb, "CyberIdentifier", {"identifier": cyb})
            edges.append({"id": f"e:{eq_node_id}->{cyb_id}", "source": eq_node_id, "target": cyb_id, "label": "HAS_CYBER_ID"})

        if posture.get("cve_count", 0) > 0:
            risk_id = f"risk:{eq['id']}"
            add_node(
                risk_id,
                f"{posture['cve_count']} CVEs (EPSS {posture.get('max_epss', 0):.2f})",
                "VulnerabilityPosture",
                posture,
            )
            edges.append({"id": f"e:{eq_node_id}->{risk_id}", "source": eq_node_id, "target": risk_id, "label": "EXPOSES"})

    for near in compute_proximity_edges(equipment, max_distance_m=max_near_m):
        edges.append(
            {
                "id": f"e:near:{near['source']}:{near['target']}",
                "source": f"equipment:{near['source']}",
                "target": f"equipment:{near['target']}",
                "label": f"NEAR ({near['distance_m']}m)",
            }
        )

    for dz in list(dark_zones)[:6]:
        dz_id = f"darkzone:{dz['id']}"
        add_node(
            dz_id,
            dz["label"],
            "DarkZone",
            {
                "dark_zone_id": dz["id"],
                "priority_score": dz["priority_score"],
                "x": dz["centroid_x"],
                "y": dz["centroid_y"],
                "nbv_x": dz["nbv_x"],
                "nbv_y": dz["nbv_y"],
                "recommended_action": dz["recommended_action"],
            },
        )
        edges.append({"id": f"e:{dz_id}->{space_id}", "source": dz_id, "target": space_id, "label": f"BLIND_SPOT (P{dz['priority_score']})"})

    for anom in list(anomalies)[:6]:
        an_id = f"anomaly:{anom['id']}"
        add_node(
            an_id,
            f"Change ({anom['severity']})",
            "ChangeAnomaly",
            {"x": anom.get("centroid_x"), "y": anom.get("centroid_y"), "area_m2": anom.get("area_m2")},
        )
        edges.append({"id": f"e:{an_id}->{space_id}", "source": an_id, "target": space_id, "label": "DETECTED_IN"})

    return {
        "nodes": nodes,
        "edges": edges,
        "stats": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "equipment_count": len(equipment),
            "dark_zone_count": len(dark_zones),
            "anomaly_count": len(anomalies),
        },
    }


class Neo4jKnowledgeGraphStore:
    """Neo4j 5 Bolt driver client with retry policy, delete sync, and full PG18 reconciler."""

    def __init__(
        self,
        uri: str,
        user: str = "neo4j",
        password: str = "twinscan_graph_secret",
        max_retries: int = 3,
    ) -> None:
        """Configure the Neo4j store."""
        self.uri = uri.strip()
        self.user = user
        self.password = password
        self.max_retries = max_retries
        self._driver: Optional[Any] = None

    @property
    def enabled(self) -> bool:
        """Return True when a Neo4j Bolt URI is configured."""
        return bool(self.uri)

    def _get_driver(self) -> Any:
        if self._driver is None:
            self._driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
        return self._driver

    def close(self) -> None:
        """Close the Neo4j driver cleanly."""
        if self._driver is not None:
            self._driver.close()
            self._driver = None

    def _run_write_with_retry(self, cypher: str, params: dict[str, Any]) -> bool:
        """Execute a Cypher write statement with try/except, stderr logging, and 3x retry."""
        if not self.enabled:
            return False
        for attempt in range(1, self.max_retries + 1):
            try:
                driver = self._get_driver()
                with driver.session() as session:
                    session.run(cypher, **params)
                return True
            except Exception as exc:
                sys.stderr.write(f"[neo4j] Cypher write failed (attempt {attempt}/{self.max_retries}): {exc}\n")
                if attempt < self.max_retries:
                    time.sleep(min(1.5 ** attempt, 4.0))
        return False

    def delete_equipment_node(self, equipment_id: str) -> bool:
        """Remove a deleted Equipment node and its incident edges from Neo4j."""
        return self._run_write_with_retry(
            "MATCH (e:Equipment {id: $equipment_id}) DETACH DELETE e",
            {"equipment_id": equipment_id},
        )

    def sync_space_and_equipment(
        self,
        space: dict[str, Any],
        equipment: Sequence[dict[str, Any]],
        max_near_m: float = 3.0,
    ) -> bool:
        """Upsert space, equipment, OEM/Model/Tag/Cyber/Vulnerability nodes, and NEAR edges."""
        if not self.enabled:
            return False
        near_edges = compute_proximity_edges(equipment, max_distance_m=max_near_m)
        enriched_eq = []
        for eq in equipment:
            enr = eq.get("enrichment") or {}
            posture = enr.get("cyber_posture") or {}
            enriched_eq.append(
                {
                    **eq,
                    "cve_count": int(posture.get("cve_count", 0)),
                    "max_epss": float(posture.get("max_epss", 0.0)),
                    "citations": list(enr.get("citations") or [])[:5],
                }
            )
        cypher = """
        MERGE (f:Facility {name: $facility})
        MERGE (s:Space {id: $space_id})
        SET s.name = $space_name, s.area_m2 = $area_m2
        MERGE (f)-[:CONTAINS]->(s)
        WITH s
        UNWIND $equipment AS eq
        MERGE (e:Equipment {id: eq.id})
        SET e.name = eq.name,
            e.equipment_type = eq.equipment_type,
            e.dexpi_class = eq.dexpi_class,
            e.serial_number = eq.serial_number,
            e.x = eq.x, e.y = eq.y, e.z = eq.z, e.yaw_deg = eq.yaw_deg,
            e.cpe_23 = eq.inferred_cpe_23,
            e.cve_count = eq.cve_count,
            e.max_epss = eq.max_epss
        MERGE (e)-[loc:LOCATED_IN]->(s)
        SET loc.x = eq.x, loc.y = eq.y, loc.z = eq.z, loc.yaw_deg = eq.yaw_deg
        FOREACH (_ IN CASE WHEN eq.manufacturer <> 'Unknown' THEN [1] ELSE [] END |
            MERGE (m:Manufacturer {name: eq.manufacturer})
            MERGE (e)-[:MADE_BY]->(m)
        )
        FOREACH (_ IN CASE WHEN eq.model_number <> 'Unknown' THEN [1] ELSE [] END |
            MERGE (pm:ProductModel {key: eq.manufacturer + ':' + eq.model_number})
            SET pm.model_number = eq.model_number, pm.cpe_23 = eq.inferred_cpe_23, pm.dexpi_class = eq.dexpi_class
            MERGE (e)-[:IS_MODEL]->(pm)
        )
        FOREACH (tag IN eq.asset_tags |
            MERGE (t:IndustrialTag {value: tag})
            MERGE (e)-[:HAS_TAG]->(t)
        )
        FOREACH (mac IN eq.mac_addresses |
            MERGE (c:CyberIdentifier {value: mac})
            SET c.kind = 'MAC'
            MERGE (e)-[:HAS_CYBER_ID]->(c)
        )
        FOREACH (url IN eq.citations |
            MERGE (src:EnrichmentSource {url: url})
            MERGE (e)-[:ENRICHED_BY]->(src)
        )
        WITH count(*) AS _done
        UNWIND $near_edges AS ne
        MATCH (a:Equipment {id: ne.source}), (b:Equipment {id: ne.target})
        MERGE (a)-[r:NEAR]-(b)
        SET r.distance_m = ne.distance_m
        """
        return self._run_write_with_retry(
            cypher,
            {
                "facility": space.get("facility", "Eigenia Facility"),
                "space_id": space["id"],
                "space_name": space["name"],
                "area_m2": float((space.get("metrics") or {}).get("area_m2", 0.0)),
                "equipment": enriched_eq,
                "near_edges": near_edges,
            },
        )

    def reconcile_all(
        self,
        spaces: Sequence[dict[str, Any]],
        equipment_by_space: dict[str, List[dict[str, Any]]],
        max_near_m: float = 3.0,
    ) -> dict[str, Any]:
        """Rebuild Neo4j parity from PostgreSQL 18 as single source of truth."""
        if not self.enabled:
            return {"synced_spaces": 0, "synced_equipment": 0, "status": "disabled"}
        synced_spaces = 0
        synced_equipment = 0
        for sp in spaces:
            eqs = equipment_by_space.get(sp["id"], [])
            if self.sync_space_and_equipment(sp, eqs, max_near_m=max_near_m):
                synced_spaces += 1
                synced_equipment += len(eqs)
        return {
            "synced_spaces": synced_spaces,
            "synced_equipment": synced_equipment,
            "status": "reconciled",
        }

    def check_health(self) -> dict[str, Any]:
        """Verify live Neo4j connectivity."""
        if not self.enabled:
            return {"status": "disabled", "uri": ""}
        try:
            driver = self._get_driver()
            driver.verify_connectivity()
            return {"status": "connected", "uri": self.uri}
        except Exception as exc:
            sys.stderr.write(f"[neo4j] Health check failed: {exc}\n")
            return {"status": "unavailable", "uri": self.uri, "error": str(exc)}
