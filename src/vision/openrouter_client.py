"""OpenRouter multi-model Vision & Embeddings client with 3x retry and stderr logging."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import sys
from typing import Any, List, Optional

import httpx
import numpy as np

from src.vision.preprocessor import decode_industrial_barcodes, preprocess_industrial_image
from src.vision.schemas import BarcodeMatch, EquipmentVisionResult, VisionFieldBox

SUPPORTED_OPENROUTER_VISION_MODELS: List[dict[str, str]] = [
    {
        "id": "google/gemini-2.5-flash",
        "label": "Gemini 2.5 Flash (Fast Spatial Grounding)",
        "tier": "fast-grounding",
    },
    {
        "id": "google/gemini-2.5-pro",
        "label": "Gemini 2.5 Pro (Precision Multi-Label + Grounding)",
        "tier": "frontier-grounding",
    },
    {
        "id": "qwen/qwen2.5-vl-72b-instruct",
        "label": "Qwen 2.5 VL 72B (Open-Weight Industrial OCR)",
        "tier": "open-weight-ocr",
    },
    {
        "id": "anthropic/claude-sonnet-4",
        "label": "Claude Sonnet 4 (Dense Plate & Electrical Table OCR)",
        "tier": "frontier-ocr",
    },
    {
        "id": "openai/gpt-4o",
        "label": "GPT-4o (General Multimodal Verification)",
        "tier": "general",
    },
]

_EXTRACTION_SYSTEM_PROMPT = """You are an industrial OT/IT cyber-physical asset inspector for Eigenia TwinScan.
Inspect the provided equipment/nameplate image and return ONLY a valid JSON object matching this exact schema:
{
  "name": "short descriptive asset name e.g. Siemens S7-1500 PLC",
  "equipment_type": "Server Rack | PLC | Network Switch | Firewall | Router | PDU | HVAC | Pump | Valve | Motor | Sensor | Panel | Robot | Workstation | Industrial Equipment",
  "dexpi_class": "DEXPI 2.0 / ISO 15926-4 class e.g. ProgrammableLogicController, CentrifugalPump, Switchgear, ServerRack, HeatExchanger, Sensor",
  "manufacturer": "Make / OEM name",
  "model_number": "Exact model number",
  "part_number": "Part/order number or null",
  "serial_number": "Exact serial number (prefer deterministic barcode hints when present) or null",
  "hardware_revision": "Hardware rev or null",
  "firmware_version": "Firmware version if printed or null",
  "manufacturing_date": "Date code or YYYY-MM if visible or null",
  "inferred_cpe_23": "Candidate NIST CPE 2.3 string like cpe:2.3:h:siemens:simatic_s7-1500:*:*:*:*:*:*:*:* or null",
  "voltage_rating": "e.g. 24V DC or 480V AC 3-Phase or null",
  "current_or_power": "e.g. 15A / 2.2kW or null",
  "certifications": ["UL", "CE", "FCC"],
  "asset_tags": ["any facility asset tag IDs"],
  "mac_addresses": ["any visible MAC addresses"],
  "ip_or_hostname_labels": ["any visible IP or hostname stickers"],
  "primary_bbox_norm": [ymin, xmin, ymax, xmax],
  "detected_boxes": [
    {"label": "serial_number | model_number | asset_tag | nameplate | mac_address", "value": "text", "bbox_norm": [ymin, xmin, ymax, xmax], "confidence": 0.95}
  ],
  "confidence": 0.92,
  "raw_notes": "brief inspection observations"
}
All bbox_norm values MUST be normalized to a 0-1000 scale [ymin, xmin, ymax, xmax].
Do not include markdown code fences or prose outside the JSON object."""


def _extract_json_object(content: str) -> dict[str, Any]:
    """Parse a JSON object from an LLM response, stripping optional markdown fences."""
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start : end + 1]
    return json.loads(cleaned)


def deterministic_fallback_embedding(text: str, dimensions: int = 1536) -> List[float]:
    """Generate a deterministic normalized semantic hash vector for offline/local fallback.

    Preserves token-level cosine similarity across shared make/model/type terms so
    pgvector HNSW queries behave meaningfully even before an OpenRouter key is configured.

    Args:
        text: Input equipment metadata string.
        dimensions: Target vector length (default 1536).

    Returns:
        Unit-normalized list of floats of length ``dimensions``.
    """
    vec = np.zeros(dimensions, dtype=np.float32)
    tokens = re.findall(r"[a-z0-9_.:-]+", text.lower())
    if not tokens:
        vec[0] = 1.0
        return vec.tolist()

    for tok in tokens:
        digest = hashlib.sha256(tok.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:4], "little") % dimensions
        sign = 1.0 if (digest[4] & 1) == 0 else -1.0
        vec[idx] += sign
        # Also hash character 3-grams for fuzzy model-number similarity.
        for i in range(max(0, len(tok) - 2)):
            ngram = tok[i : i + 3]
            nd = hashlib.blake2b(ngram.encode("utf-8"), digest_size=8).digest()
            n_idx = int.from_bytes(nd[:4], "little") % dimensions
            vec[n_idx] += 0.35 if (nd[4] & 1) == 0 else -0.35

    norm = float(np.linalg.norm(vec))
    if norm > 0:
        vec /= norm
    return vec.tolist()


class OpenRouterVisionClient:
    """Async OpenRouter gateway for industrial nameplate VLM extraction and embeddings."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://openrouter.ai/api/v1",
        default_model: str = "google/gemini-2.5-flash",
        secondary_model: str = "qwen/qwen2.5-vl-72b-instruct",
        embedding_model: str = "openai/text-embedding-3-small",
        embedding_dimensions: int = 1536,
        max_retries: int = 3,
        timeout_s: float = 45.0,
    ) -> None:
        """Initialize the OpenRouter client.

        Args:
            api_key: OpenRouter bearer token.
            base_url: OpenRouter OpenAI-compatible base URL.
            default_model: Default vision model slug.
            secondary_model: Secondary vision model slug for dual-model consensus.
            embedding_model: Embedding model slug for pgvector indexing.
            embedding_dimensions: Expected output embedding dimensions.
            max_retries: Maximum retry attempts on transient API failures.
            timeout_s: Per-request HTTP timeout in seconds.
        """
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.secondary_model = secondary_model
        self.embedding_model = embedding_model
        self.embedding_dimensions = embedding_dimensions
        self.max_retries = max_retries
        self.timeout_s = timeout_s

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://eigenia.nl",
            "X-Title": "Eigenia TwinScan",
        }

    async def _post_with_retry(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST JSON to OpenRouter with try/except, stderr logging, and 3x backoff retry."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        last_error: Optional[Exception] = None

        for attempt in range(1, self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                    response = await client.post(url, headers=self._headers(), json=payload)
                    response.raise_for_status()
                    return response.json()
            except Exception as exc:
                last_error = exc
                sys.stderr.write(
                    f"[openrouter] POST {endpoint} failed (attempt {attempt}/{self.max_retries}): {exc}\n"
                )
                if attempt < self.max_retries:
                    await asyncio.sleep(min(2.0 ** (attempt - 1), 4.0))

        raise RuntimeError(f"OpenRouter request to {endpoint} failed after {self.max_retries} attempts: {last_error}")

    async def _call_vision_model(
        self,
        image_b64: str,
        model: str,
        barcodes: List[BarcodeMatch],
        context_hint: str = "",
    ) -> EquipmentVisionResult:
        """Invoke a single OpenRouter vision model and parse structured asset output."""
        barcode_hint = (
            "Deterministically decoded barcodes (treat these as exact ground truth): "
            + json.dumps([b.model_dump() for b in barcodes])
            if barcodes
            else "No 1D/2D barcode detected in local Stage-1 pass."
        )
        user_text = f"Extract full equipment identity, manufacturing label fields, cyber IDs, and 0-1000 bounding boxes.\n{barcode_hint}"
        if context_hint:
            user_text += f"\nOperator context: {context_hint}"

        payload = {
            "model": model,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": _EXTRACTION_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                    ],
                },
            ],
        }
        data = await self._post_with_retry("chat/completions", payload)
        content = data["choices"][0]["message"]["content"]
        parsed = _extract_json_object(content)

        boxes = []
        for b in parsed.get("detected_boxes") or []:
            try:
                boxes.append(VisionFieldBox(**b))
            except Exception:
                continue

        return EquipmentVisionResult(
            name=parsed.get("name") or f"{parsed.get('manufacturer', 'Unknown')} {parsed.get('model_number', 'Asset')}",
            equipment_type=parsed.get("equipment_type") or "Industrial Equipment",
            dexpi_class=parsed.get("dexpi_class") or "Equipment",
            manufacturer=parsed.get("manufacturer") or "Unknown",
            model_number=parsed.get("model_number") or "Unknown",
            part_number=parsed.get("part_number"),
            serial_number=parsed.get("serial_number") or (barcodes[0].text if barcodes else None),
            hardware_revision=parsed.get("hardware_revision"),
            firmware_version=parsed.get("firmware_version"),
            manufacturing_date=parsed.get("manufacturing_date"),
            inferred_cpe_23=parsed.get("inferred_cpe_23"),
            voltage_rating=parsed.get("voltage_rating"),
            current_or_power=parsed.get("current_or_power"),
            certifications=list(parsed.get("certifications") or []),
            asset_tags=list(parsed.get("asset_tags") or []),
            mac_addresses=list(parsed.get("mac_addresses") or []),
            ip_or_hostname_labels=list(parsed.get("ip_or_hostname_labels") or []),
            barcodes=barcodes,
            primary_bbox_norm=list(parsed.get("primary_bbox_norm") or [150.0, 200.0, 850.0, 800.0]),
            detected_boxes=boxes,
            confidence=float(parsed.get("confidence", 0.85)),
            model_used=model,
            raw_notes=str(parsed.get("raw_notes") or ""),
        )

    async def analyze_equipment_image(
        self,
        image_bytes: bytes,
        model: Optional[str] = None,
        consensus: bool = False,
        secondary_model: Optional[str] = None,
        context_hint: str = "",
    ) -> EquipmentVisionResult:
        """Run dual-stage barcode/CLAHE preprocessing + OpenRouter VLM extraction.

        When ``OPENROUTER_API_KEY`` is not configured, runs deterministic Stage-1
        OpenCV/zxing-cpp decoding and returns a clearly flagged offline review record.

        Args:
            image_bytes: Uploaded image bytes.
            model: OpenRouter vision model slug (defaults to configured primary model).
            consensus: If True, cross-checks key identity fields against a second model.
            secondary_model: Optional override for the consensus model.
            context_hint: Optional operator notes about the equipment.

        Returns:
            ``EquipmentVisionResult`` populated with barcodes, fields, and bounding boxes.
        """
        barcodes = decode_industrial_barcodes(image_bytes)
        try:
            enhanced_jpeg, _ = preprocess_industrial_image(image_bytes)
        except Exception as exc:
            sys.stderr.write(f"[openrouter] Preprocess fallback to raw bytes: {exc}\n")
            enhanced_jpeg = image_bytes

        chosen_model = model or self.default_model
        if not self.api_key or self.api_key == "your_openrouter_api_key_here":
            tag_vals = [b.text for b in barcodes]
            return EquipmentVisionResult(
                name=f"Scanned Asset {tag_vals[0]}" if tag_vals else "Unverified Equipment (Set OPENROUTER_API_KEY)",
                equipment_type="Industrial Equipment",
                dexpi_class="Equipment",
                manufacturer="Pending OpenRouter Key",
                model_number="Pending OpenRouter Key",
                serial_number=tag_vals[0] if tag_vals else None,
                asset_tags=tag_vals,
                barcodes=barcodes,
                confidence=0.95 if tag_vals else 0.35,
                model_used=f"offline-stage1 ({chosen_model} inactive)",
                raw_notes=(
                    "Stage-1 OpenCV CLAHE + zxing-cpp completed locally. "
                    "Add OPENROUTER_API_KEY to .env to enable live VLM nameplate extraction."
                ),
            )

        image_b64 = base64.b64encode(enhanced_jpeg).decode("ascii")
        primary = await self._call_vision_model(image_b64, chosen_model, barcodes, context_hint=context_hint)

        if consensus:
            sec_model = secondary_model or self.secondary_model
            if sec_model and sec_model != chosen_model:
                try:
                    secondary = await self._call_vision_model(image_b64, sec_model, barcodes, context_hint=context_hint)
                    discrepancies: List[str] = []
                    for field in ("manufacturer", "model_number", "serial_number", "voltage_rating"):
                        v1 = getattr(primary, field)
                        v2 = getattr(secondary, field)
                        if v1 and v2 and str(v1).strip().lower() != str(v2).strip().lower():
                            discrepancies.append(f"{field}: {chosen_model}='{v1}' vs {sec_model}='{v2}'")
                    primary.consensus_verified = len(discrepancies) == 0
                    primary.discrepancies = discrepancies
                    primary.model_used = f"{chosen_model} + {sec_model}"
                except Exception as exc:
                    sys.stderr.write(f"[openrouter] Consensus secondary model failed: {exc}\n")

        return primary

    async def generate_embedding(self, text: str) -> List[float]:
        """Generate a normalized embedding vector via OpenRouter with deterministic fallback.

        Args:
            text: Canonical text representation of an equipment asset.

        Returns:
            Float vector matching ``self.embedding_dimensions``.
        """
        if not self.api_key or self.api_key == "your_openrouter_api_key_here":
            return deterministic_fallback_embedding(text, self.embedding_dimensions)

        try:
            payload = {"model": self.embedding_model, "input": text}
            data = await self._post_with_retry("embeddings", payload)
            emb = data["data"][0]["embedding"]
            if len(emb) == self.embedding_dimensions:
                return [float(x) for x in emb]
            arr = np.zeros(self.embedding_dimensions, dtype=np.float32)
            limit = min(len(emb), self.embedding_dimensions)
            arr[:limit] = emb[:limit]
            norm = float(np.linalg.norm(arr))
            if norm > 0:
                arr /= norm
            return arr.tolist()
        except Exception as exc:
            sys.stderr.write(f"[openrouter] Embedding fallback engaged: {exc}\n")
            return deterministic_fallback_embedding(text, self.embedding_dimensions)
