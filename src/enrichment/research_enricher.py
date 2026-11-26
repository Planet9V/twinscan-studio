"""Pass-3 Direct Research & Cyber-Physical Enrichment Engine.

Queries OpenRouter web-search-enabled research models for OEM datasheets, physical
dimensions (auto-refining 3D twins), industrial protocols, and lifecycle status,
combined with live NIST NVD CVE and FIRST.org EPSS risk telemetry.
All external calls use try/except, stderr logging, and 3x exponential retry.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from typing import Any, List, Optional

import httpx


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    s, e = cleaned.find("{"), cleaned.rfind("}")
    if s != -1 and e != -1 and e > s:
        cleaned = cleaned[s : e + 1]
    return json.loads(cleaned)


class DirectResearchEnricher:
    """Enriches equipment assets via OpenRouter web-grounded research, NVD CVE, and FIRST EPSS."""

    def __init__(
        self,
        openrouter_api_key: str = "",
        openrouter_base_url: str = "https://openrouter.ai/api/v1",
        research_model: str = "perplexity/sonar-pro",
        max_retries: int = 3,
        timeout_s: float = 35.0,
    ) -> None:
        """Configure the direct research enrichment engine."""
        self.openrouter_api_key = openrouter_api_key.strip()
        self.openrouter_base_url = openrouter_base_url.rstrip("/")
        self.research_model = research_model
        self.max_retries = max_retries
        self.timeout_s = timeout_s

    async def _request_json_with_retry(
        self,
        method: str,
        url: str,
        headers: Optional[dict[str, str]] = None,
        json_body: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Execute an external HTTP request with try/except, stderr logging, and 3x retry."""
        last_err: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                    resp = await client.request(
                        method,
                        url,
                        headers=headers,
                        json=json_body,
                        params=params,
                    )
                    resp.raise_for_status()
                    return resp.json()
            except Exception as exc:
                last_err = exc
                sys.stderr.write(
                    f"[enrichment] {method} {url} failed (attempt {attempt}/{self.max_retries}): {exc}\n"
                )
                if attempt < self.max_retries:
                    await asyncio.sleep(min(1.5 ** attempt, 4.0))
        raise RuntimeError(f"External lookup {url} failed after {self.max_retries} attempts: {last_err}")

    async def lookup_nvd_and_epss(self, cpe_23: Optional[str], keyword: str = "") -> dict[str, Any]:
        """Query NIST NVD CVE API and FIRST.org EPSS API for cyber risk posture.

        Args:
            cpe_23: Candidate NIST CPE 2.3 string.
            keyword: Fallback OEM + Model keyword when CPE is absent.

        Returns:
            Dictionary with ``cve_count``, ``max_cvss``, ``max_epss``, and ``top_cves``.
        """
        params: dict[str, Any] = {"resultsPerPage": 8}
        if cpe_23 and cpe_23.startswith("cpe:2.3:"):
            params["cpeName"] = cpe_23
        elif keyword.strip():
            params["keywordSearch"] = keyword.strip()
        else:
            return {"cve_count": 0, "max_cvss": 0.0, "max_epss": 0.0, "top_cves": [], "source": "none"}

        try:
            nvd_data = await self._request_json_with_retry(
                "GET",
                "https://services.nvd.nist.gov/rest/json/cves/2.0",
                params=params,
            )
        except Exception as exc:
            sys.stderr.write(f"[enrichment.nvd] Skipping NVD lookup: {exc}\n")
            return {"cve_count": 0, "max_cvss": 0.0, "max_epss": 0.0, "top_cves": [], "source": "unavailable"}

        vulns = nvd_data.get("vulnerabilities") or []
        cve_ids: List[str] = []
        top_cves: List[dict[str, Any]] = []
        max_cvss = 0.0

        for entry in vulns[:8]:
            cve = entry.get("cve") or {}
            cid = cve.get("id")
            if not cid:
                continue
            cve_ids.append(cid)
            metrics = cve.get("metrics") or {}
            cvss = 0.0
            for key in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
                arr = metrics.get(key) or []
                if arr:
                    cvss = float((arr[0].get("cvssData") or {}).get("baseScore") or 0.0)
                    break
            max_cvss = max(max_cvss, cvss)
            descs = cve.get("descriptions") or []
            summary = next((d.get("value", "") for d in descs if d.get("lang") == "en"), "")
            top_cves.append({"cve_id": cid, "cvss": cvss, "epss": 0.0, "summary": summary[:220]})

        max_epss = 0.0
        if cve_ids:
            try:
                epss_data = await self._request_json_with_retry(
                    "GET",
                    "https://api.first.org/data/v1/epss",
                    params={"cve": ",".join(cve_ids)},
                )
                epss_map = {
                    row["cve"]: float(row.get("epss", 0.0))
                    for row in (epss_data.get("data") or [])
                    if "cve" in row
                }
                for item in top_cves:
                    score = epss_map.get(item["cve_id"], 0.0)
                    item["epss"] = round(score, 4)
                    max_epss = max(max_epss, score)
            except Exception as exc:
                sys.stderr.write(f"[enrichment.epss] Skipping FIRST EPSS lookup: {exc}\n")

        return {
            "cve_count": int(nvd_data.get("totalResults", len(top_cves))),
            "max_cvss": round(max_cvss, 1),
            "max_epss": round(max_epss, 4),
            "top_cves": top_cves,
            "source": "nvd+first_epss",
        }

    async def enrich_asset(
        self,
        asset: dict[str, Any],
        research_model: Optional[str] = None,
        include_nvd: bool = True,
    ) -> dict[str, Any]:
        """Run Pass-3 direct online research + NVD/EPSS cyber posture enrichment on an asset.

        Args:
            asset: Existing equipment asset record.
            research_model: Optional OpenRouter research model override.
            include_nvd: Whether to execute live NVD CVE & FIRST EPSS lookups.

        Returns:
            Structured enrichment dossier containing datasheet specs, updated dimensions,
            lifecycle status, protocols, follow-up inspection guidance, citations, and CVE/EPSS risk.
        """
        mfg = asset.get("manufacturer", "Unknown")
        model = asset.get("model_number", "Unknown")
        part = asset.get("part_number") or ""
        chosen_model = research_model or self.research_model

        specs: dict[str, Any] = {
            "official_name": asset.get("name"),
            "dexpi_class": asset.get("dexpi_class", "Equipment"),
            "inferred_cpe_23": asset.get("inferred_cpe_23"),
            "dimensions_m": {
                "width_m": float(asset.get("width_m") or 0.75),
                "depth_m": float(asset.get("depth_m") or 0.75),
                "height_m": float(asset.get("height_m") or 1.6),
            },
            "voltage_rating": asset.get("voltage_rating"),
            "power_watts": None,
            "protocols": [],
            "lifecycle_status": "Unknown",
            "datasheet_summary": "",
            "recommended_field_checks": [],
            "citations": [],
            "research_model_used": chosen_model,
        }

        if self.openrouter_api_key and self.openrouter_api_key != "your_openrouter_api_key_here":
            prompt = (
                f"Research official technical specifications for industrial/IT hardware: "
                f"Manufacturer='{mfg}', Model='{model}', Part='{part}', Type='{asset.get('equipment_type', '')}'. "
                f"Return ONLY valid JSON with keys: official_name, dexpi_class, inferred_cpe_23, "
                f"dimensions_m ({{width_m, depth_m, height_m}} in meters), voltage_rating, power_watts, "
                f"protocols (list of OT/IT protocols e.g. PROFINET, Modbus TCP, SNMP), "
                f"lifecycle_status (Active | End-of-Sale | End-of-Life | Unknown), "
                f"datasheet_summary (2 concise sentences), recommended_field_checks (list of 3 physical checks), "
                f"citations (list of authoritative URLs)."
            )
            try:
                data = await self._request_json_with_retry(
                    "POST",
                    f"{self.openrouter_base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.openrouter_api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://eigenia.nl",
                        "X-Title": "Eigenia TwinScan Direct Research",
                    },
                    json_body={
                        "model": chosen_model,
                        "temperature": 0.1,
                        "response_format": {"type": "json_object"},
                        "messages": [
                            {"role": "system", "content": "You are an OT/IT cyber-physical hardware research analyst. Output strict JSON."},
                            {"role": "user", "content": prompt},
                        ],
                    },
                )
                content = data["choices"][0]["message"]["content"]
                parsed = _extract_json(content)
                specs.update({k: v for k, v in parsed.items() if v is not None})
                if isinstance(data.get("citations"), list):
                    specs["citations"] = list(set(list(specs.get("citations") or []) + data["citations"]))
            except Exception as exc:
                sys.stderr.write(f"[enrichment.openrouter] Research call failed: {exc}\n")
                specs["datasheet_summary"] = f"OpenRouter research unavailable: {exc}"
        else:
            specs["datasheet_summary"] = (
                f"Offline heuristic enrichment for {mfg} {model}. Add OPENROUTER_API_KEY in Admin "
                f"to pull live OEM datasheets, physical dimensions, EoL lifecycle, and citations."
            )
            specs["recommended_field_checks"] = [
                "Verify physical nameplate serial & hardware revision on rear panel.",
                "Record active Ethernet/Fieldbus port connections for Neo4j topology.",
                "Confirm firmware version via local HMI or OT passive tap.",
            ]

        cyber_posture = (
            await self.lookup_nvd_and_epss(
                cpe_23=specs.get("inferred_cpe_23") or asset.get("inferred_cpe_23"),
                keyword=f"{mfg} {model}" if mfg != "Unknown" else "",
            )
            if include_nvd
            else {"cve_count": 0, "max_cvss": 0.0, "max_epss": 0.0, "top_cves": [], "source": "skipped"}
        )

        return {
            **specs,
            "cyber_posture": cyber_posture,
            "enriched_at": datetime.now(timezone.utc).isoformat(),
        }
