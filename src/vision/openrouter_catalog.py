"""OpenRouter API key verification and live model catalog normalizer with pricing, types, and 5-minute TTL cache.

Provides:
- ``test_openrouter_api_key``: Verifies draft or saved OpenRouter keys via ``GET /auth/key``
  (fast-fail on 401/403, 3x retry on transient network/5xx) and enriches credits via ``GET /credits``.
- ``normalize_openrouter_model``: Normalizes OpenRouter ``/models`` and ``/embeddings/models`` entries
  with per-1M USD pricing, cost tiers, modality/capability categories, and concise ``model_type``.
- ``fetch_openrouter_model_catalog``: Concurrently fetches live models + embedding models with a
  5-minute in-memory TTL cache and a rich curated fallback catalog.
"""

from __future__ import annotations

import asyncio
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

import httpx

CATALOG_CACHE_TTL_S = 300.0
_CATALOG_CACHE: Dict[str, Any] = {}

RECOMMENDED_VISION_IDS = (
    "google/gemini-2.5-flash",
    "google/gemini-2.5-pro",
    "anthropic/claude-sonnet-4",
    "openai/gpt-4o",
    "qwen/qwen2.5-vl-72b-instruct",
    "meta-llama/llama-4-maverick",
)
RECOMMENDED_RESEARCH_IDS = (
    "perplexity/sonar-pro",
    "perplexity/sonar",
    "google/gemini-2.5-flash:online",
    "google/gemini-2.5-pro:online",
)
RECOMMENDED_EMBEDDING_IDS = (
    "openai/text-embedding-3-small",
    "openai/text-embedding-3-large",
    "google/gemini-embedding-001",
)
POPULAR_MODEL_ORDER = list(
    dict.fromkeys(RECOMMENDED_VISION_IDS + RECOMMENDED_RESEARCH_IDS + RECOMMENDED_EMBEDDING_IDS)
)
_POPULAR_RANK = {mid: idx for idx, mid in enumerate(POPULAR_MODEL_ORDER)}

ALL_CATEGORIES = (
    "vision",
    "web_research",
    "reasoning",
    "embedding",
    "text",
    "audio_video",
    "free",
)


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        if val is None or val == "":
            return default
        f = float(val)
        return f if f >= 0.0 else default
    except (TypeError, ValueError):
        return default


def _optional_float(val: Any) -> Optional[float]:
    try:
        if val is None or val == "":
            return None
        return round(float(val), 6)
    except (TypeError, ValueError):
        return None


def _extract_error_message(resp: httpx.Response) -> str:
    """Extract a concise human-readable error message from an OpenRouter HTTP error response."""
    try:
        payload = resp.json()
        err = payload.get("error")
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])
        if isinstance(err, str) and err.strip():
            return err.strip()
        if payload.get("message"):
            return str(payload["message"])
    except Exception:
        pass
    text = (resp.text or "").strip()
    return text[:240] if text else f"HTTP {resp.status_code}"


async def test_openrouter_api_key(
    api_key: str,
    base_url: str = "https://openrouter.ai/api/v1",
    key_source: str = "saved",
    timeout: float = 10.0,
    retries: int = 3,
) -> Dict[str, Any]:
    """Validate an OpenRouter API key against ``GET /auth/key`` and enrich via ``GET /credits``.

    Fast-fails immediately on HTTP 401/403 without retries; retries up to ``retries`` times on
    transient network or 5xx errors while logging errors to ``sys.stderr``.

    Args:
        api_key: Plaintext OpenRouter API key (never returned in the result).
        base_url: OpenRouter API base URL (default ``https://openrouter.ai/api/v1``).
        key_source: Origin label (``"draft"`` or ``"saved"``).
        timeout: Timeout in seconds for ``/auth/key``.
        retries: Max attempts for transient network/5xx errors.

    Returns:
        Structured key verification result dictionary.
    """
    clean_key = (api_key or "").strip()
    if not clean_key or clean_key == "your_openrouter_api_key_here":
        return {
            "ok": False,
            "status": "unconfigured",
            "http_status": None,
            "latency_ms": 0,
            "key_source": key_source,
            "label": None,
            "is_free_tier": False,
            "usage_usd": None,
            "limit_usd": None,
            "limit_remaining_usd": None,
            "total_credits_usd": None,
            "error": "No OpenRouter API key provided or saved.",
        }

    root = (base_url or "https://openrouter.ai/api/v1").rstrip("/")
    headers = {"Authorization": f"Bearer {clean_key}"}
    t0 = time.perf_counter()
    last_error = "OpenRouter request failed."
    last_status: Optional[int] = None

    for attempt in range(1, max(1, retries) + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(f"{root}/auth/key", headers=headers)
                latency_ms = int((time.perf_counter() - t0) * 1000)
                last_status = resp.status_code

                if resp.status_code in (401, 403):
                    msg = _extract_error_message(resp)
                    return {
                        "ok": False,
                        "status": "invalid_key",
                        "http_status": resp.status_code,
                        "latency_ms": latency_ms,
                        "key_source": key_source,
                        "label": None,
                        "is_free_tier": False,
                        "usage_usd": None,
                        "limit_usd": None,
                        "limit_remaining_usd": None,
                        "total_credits_usd": None,
                        "error": msg,
                    }

                if resp.status_code >= 500:
                    last_error = _extract_error_message(resp)
                    sys.stderr.write(
                        f"[openrouter.test_key] Attempt {attempt}/{retries} got HTTP {resp.status_code}: {last_error}\n"
                    )
                    if attempt < retries:
                        await asyncio.sleep(min(0.4 * attempt, 1.5))
                        continue
                    break

                if resp.status_code >= 400:
                    return {
                        "ok": False,
                        "status": "error",
                        "http_status": resp.status_code,
                        "latency_ms": latency_ms,
                        "key_source": key_source,
                        "label": None,
                        "is_free_tier": False,
                        "usage_usd": None,
                        "limit_usd": None,
                        "limit_remaining_usd": None,
                        "total_credits_usd": None,
                        "error": _extract_error_message(resp),
                    }

                payload = resp.json()
                data = payload.get("data") if isinstance(payload, dict) else {}
                if not isinstance(data, dict):
                    data = {}

                usage_usd = _optional_float(data.get("usage"))
                limit_usd = _optional_float(data.get("limit"))
                limit_remaining_usd = _optional_float(data.get("limit_remaining"))
                if limit_remaining_usd is None and limit_usd is not None and usage_usd is not None:
                    limit_remaining_usd = round(max(0.0, limit_usd - usage_usd), 6)

                total_credits_usd: Optional[float] = None
                # Best-effort account credits lookup
                try:
                    c_resp = await client.get(f"{root}/credits", headers=headers, timeout=5.0)
                    if c_resp.status_code == 200:
                        c_data = (c_resp.json() or {}).get("data") or {}
                        if isinstance(c_data, dict):
                            total_credits_usd = _optional_float(c_data.get("total_credits"))
                            total_usage = _optional_float(c_data.get("total_usage"))
                            if usage_usd is None and total_usage is not None:
                                usage_usd = total_usage
                            if (
                                limit_remaining_usd is None
                                and total_credits_usd is not None
                                and total_usage is not None
                            ):
                                limit_remaining_usd = round(max(0.0, total_credits_usd - total_usage), 6)
                except Exception as c_exc:
                    sys.stderr.write(f"[openrouter.credits] Best-effort /credits skipped: {c_exc}\n")

                return {
                    "ok": True,
                    "status": "connected",
                    "http_status": 200,
                    "latency_ms": latency_ms,
                    "key_source": key_source,
                    "label": data.get("label") or "OpenRouter Key Active",
                    "is_free_tier": bool(data.get("is_free_tier", False)),
                    "usage_usd": usage_usd,
                    "limit_usd": limit_usd,
                    "limit_remaining_usd": limit_remaining_usd,
                    "total_credits_usd": total_credits_usd,
                    "error": None,
                }
        except Exception as exc:
            last_error = str(exc)
            sys.stderr.write(f"[openrouter.test_key] Attempt {attempt}/{retries} failed: {exc}\n")
            if attempt < retries:
                await asyncio.sleep(min(0.4 * attempt, 1.5))

    return {
        "ok": False,
        "status": "error",
        "http_status": last_status,
        "latency_ms": int((time.perf_counter() - t0) * 1000),
        "key_source": key_source,
        "label": None,
        "is_free_tier": False,
        "usage_usd": None,
        "limit_usd": None,
        "limit_remaining_usd": None,
        "total_credits_usd": None,
        "error": last_error,
    }


setattr(test_openrouter_api_key, "__test__", False)


def normalize_openrouter_model(
    raw: Dict[str, Any],
    is_embedding: bool = False,
    tier: str = "openrouter-live",
) -> Dict[str, Any]:
    """Normalize a raw OpenRouter model payload into rich pricing, modality, and category metadata.

    Args:
        raw: Raw dictionary from OpenRouter ``/models`` or ``/embeddings/models``.
        is_embedding: Explicit flag marking entries fetched from ``/embeddings/models``.
        tier: Source tier tag (default ``"openrouter-live"``).

    Returns:
        Normalized ``OpenRouterModelInfo`` dictionary.
    """
    model_id = str(raw.get("id") or "").strip()
    name = str(raw.get("name") or model_id).strip()
    provider = model_id.split("/", 1)[0] if "/" in model_id else "openrouter"
    description = str(raw.get("description") or "").strip()
    context_length = int(raw.get("context_length") or 0)

    arch = raw.get("architecture") if isinstance(raw.get("architecture"), dict) else {}
    input_modalities = [str(m).lower() for m in (arch.get("input_modalities") or raw.get("input_modalities") or [])]
    output_modalities = [str(m).lower() for m in (arch.get("output_modalities") or raw.get("output_modalities") or [])]
    if not input_modalities:
        input_modalities = ["text"]
    if not output_modalities:
        output_modalities = ["embeddings"] if is_embedding else ["text"]

    supported_params = {str(p).lower() for p in (raw.get("supported_parameters") or [])}
    pricing_raw = raw.get("pricing") if isinstance(raw.get("pricing"), dict) else {}

    prompt_1m = round(_safe_float(pricing_raw.get("prompt")) * 1_000_000.0, 4)
    completion_1m = round(_safe_float(pricing_raw.get("completion")) * 1_000_000.0, 4)
    image_raw = _safe_float(pricing_raw.get("image"))
    image_per_1k = round(image_raw * 1_000.0, 4) if image_raw > 0 else None
    web_search_cost = _safe_float(pricing_raw.get("web_search"))

    blended_1m = round((prompt_1m + 3.0 * completion_1m) / 4.0, 4)
    low_id = model_id.lower()
    is_free = (prompt_1m == 0.0 and completion_1m == 0.0) or ":free" in low_id

    if is_free:
        cost_tier = "Free"
    elif blended_1m <= 1.0:
        cost_tier = "Budget ($)"
    elif blended_1m <= 8.0:
        cost_tier = "Standard ($$)"
    else:
        cost_tier = "Frontier ($$$)"

    has_embedding = is_embedding or ("embeddings" in output_modalities) or ("embedding" in low_id)
    has_vision = "image" in input_modalities
    has_web_research = (
        (":online" in low_id)
        or (provider == "perplexity")
        or ("sonar" in low_id)
        or (web_search_cost > 0.0)
    )
    has_reasoning = (
        ("reasoning" in supported_params)
        or ("include_reasoning" in supported_params)
        or any(tok in low_id for tok in ("thinking", "reasoner", "/o1", "/o3", "/o4", "-r1"))
    )
    has_audio_video = ("audio" in input_modalities) or ("video" in input_modalities)
    has_text = ("text" in input_modalities) and not has_embedding

    categories: List[str] = []
    if has_vision:
        categories.append("vision")
    if has_embedding:
        categories.append("embedding")
    if has_web_research:
        categories.append("web_research")
    if has_reasoning:
        categories.append("reasoning")
    if has_audio_video:
        categories.append("audio_video")
    if has_text:
        categories.append("text")
    if is_free:
        categories.append("free")

    if has_embedding:
        model_type = "Embedding"
    elif has_web_research:
        model_type = "Web Research"
    elif has_reasoning and has_vision:
        model_type = "Reasoning + Vision"
    elif has_vision:
        model_type = "Vision + Text"
    elif has_reasoning:
        model_type = "Reasoning"
    elif has_audio_video:
        model_type = "Audio / Video"
    else:
        model_type = "Text / Chat"

    recommended_for: List[str] = []
    if model_id in RECOMMENDED_VISION_IDS or (has_vision and provider in {"google", "anthropic", "openai", "qwen"} and not has_embedding):
        if model_id in RECOMMENDED_VISION_IDS:
            recommended_for.extend(["vision", "secondary_vision"])
    if model_id in RECOMMENDED_RESEARCH_IDS or has_web_research or model_id in ("google/gemini-2.5-flash", "google/gemini-2.5-pro"):
        if "research" not in recommended_for:
            recommended_for.append("research")
    if has_embedding:
        recommended_for.append("embedding")

    return {
        "id": model_id,
        "name": name,
        "label": name,
        "provider": provider,
        "tier": tier,
        "description": description[:280],
        "context_length": context_length,
        "input_modalities": input_modalities,
        "output_modalities": output_modalities,
        "categories": categories,
        "model_type": model_type,
        "pricing": {
            "prompt_per_1m_usd": prompt_1m,
            "completion_per_1m_usd": completion_1m,
            "image_per_1k_usd": image_per_1k,
            "blended_per_1m_usd": blended_1m,
            "is_free": is_free,
            "cost_tier": cost_tier,
        },
        "recommended_for": recommended_for,
    }


def build_curated_fallback_catalog() -> List[Dict[str, Any]]:
    """Return a rich curated fallback OpenRouter catalog with realistic costs, types, and modalities."""
    curated_raw: List[tuple[Dict[str, Any], bool, str]] = [
        (
            {
                "id": "google/gemini-2.5-flash",
                "name": "Google: Gemini 2.5 Flash",
                "description": "Fast multimodal vision & reasoning model with 1M context window.",
                "context_length": 1_048_576,
                "architecture": {"input_modalities": ["text", "image", "audio", "video"], "output_modalities": ["text"]},
                "supported_parameters": ["reasoning"],
                "pricing": {"prompt": "0.0000003", "completion": "0.0000025"},
            },
            False,
            "fast-recommended",
        ),
        (
            {
                "id": "google/gemini-2.5-pro",
                "name": "Google: Gemini 2.5 Pro",
                "description": "Frontier multimodal reasoning and industrial nameplate inspection model.",
                "context_length": 1_048_576,
                "architecture": {"input_modalities": ["text", "image", "audio", "video"], "output_modalities": ["text"]},
                "supported_parameters": ["reasoning"],
                "pricing": {"prompt": "0.00000125", "completion": "0.00001"},
            },
            False,
            "frontier-vision",
        ),
        (
            {
                "id": "anthropic/claude-sonnet-4",
                "name": "Anthropic: Claude Sonnet 4",
                "description": "High-accuracy multimodal vision & technical documentation analysis.",
                "context_length": 200_000,
                "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]},
                "supported_parameters": ["reasoning"],
                "pricing": {"prompt": "0.000003", "completion": "0.000015"},
            },
            False,
            "frontier-vision",
        ),
        (
            {
                "id": "openai/gpt-4o",
                "name": "OpenAI: GPT-4o",
                "description": "Flagship multimodal vision + structured JSON extraction model.",
                "context_length": 128_000,
                "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]},
                "pricing": {"prompt": "0.0000025", "completion": "0.00001"},
            },
            False,
            "frontier-vision",
        ),
        (
            {
                "id": "qwen/qwen2.5-vl-72b-instruct",
                "name": "Qwen: Qwen2.5-VL 72B Instruct",
                "description": "Strong open-weights OCR & industrial nameplate vision model.",
                "context_length": 128_000,
                "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]},
                "pricing": {"prompt": "0.0000004", "completion": "0.0000004"},
            },
            False,
            "ocr-specialist",
        ),
        (
            {
                "id": "perplexity/sonar-pro",
                "name": "Perplexity: Sonar Pro",
                "description": "Web-grounded research model with live datasheet & CVE citations.",
                "context_length": 200_000,
                "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
                "pricing": {"prompt": "0.000003", "completion": "0.000015", "web_search": "0.005"},
            },
            False,
            "web-research",
        ),
        (
            {
                "id": "google/gemini-2.5-flash:online",
                "name": "Google: Gemini 2.5 Flash (Online Web Search)",
                "description": "Gemini 2.5 Flash with live OpenRouter web search grounding.",
                "context_length": 1_048_576,
                "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]},
                "pricing": {"prompt": "0.0000003", "completion": "0.0000025", "web_search": "0.004"},
            },
            False,
            "web-research",
        ),
        (
            {
                "id": "openai/text-embedding-3-small",
                "name": "OpenAI: Text Embedding 3 Small",
                "description": "1536-dim fast semantic vector embeddings for PostgreSQL pgvector.",
                "context_length": 8_192,
                "architecture": {"input_modalities": ["text"], "output_modalities": ["embeddings"]},
                "pricing": {"prompt": "0.00000002", "completion": "0"},
            },
            True,
            "embedding-default",
        ),
        (
            {
                "id": "openai/text-embedding-3-large",
                "name": "OpenAI: Text Embedding 3 Large",
                "description": "High-precision vector embeddings for industrial spec retrieval.",
                "context_length": 8_192,
                "architecture": {"input_modalities": ["text"], "output_modalities": ["embeddings"]},
                "pricing": {"prompt": "0.00000013", "completion": "0"},
            },
            True,
            "embedding",
        ),
        (
            {
                "id": "meta-llama/llama-4-maverick:free",
                "name": "Meta: Llama 4 Maverick (Free)",
                "description": "Zero-cost multimodal vision & chat tier on OpenRouter.",
                "context_length": 128_000,
                "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]},
                "pricing": {"prompt": "0", "completion": "0"},
            },
            False,
            "free-vision",
        ),
    ]
    return [normalize_openrouter_model(raw, is_embedding=is_emb, tier=tier) for raw, is_emb, tier in curated_raw]


def _compute_category_counts(models: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {"all": len(models)}
    for cat in ALL_CATEGORIES:
        counts[cat] = sum(1 for m in models if cat in (m.get("categories") or []))
    return counts


def _sort_catalog_models(models: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def _sort_key(m: Dict[str, Any]) -> tuple[int, int, str]:
        mid = m["id"]
        if mid in _POPULAR_RANK:
            return (0, _POPULAR_RANK[mid], mid)
        rec = 0 if m.get("recommended_for") else 1
        return (1, rec, m["name"].lower())

    return sorted(models, key=_sort_key)


def get_cached_catalog_models() -> Optional[List[Dict[str, Any]]]:
    """Return cached live OpenRouter models if still within the 5-minute TTL, else ``None``."""
    entry = _CATALOG_CACHE.get("default")
    if not entry:
        return None
    if (time.monotonic() - entry["ts"]) > CATALOG_CACHE_TTL_S:
        return None
    return list(entry["payload"]["models"])


def clear_catalog_cache() -> None:
    """Clear the in-memory OpenRouter catalog TTL cache (useful in tests)."""
    _CATALOG_CACHE.clear()


async def _fetch_json_with_retry(
    client: httpx.AsyncClient,
    url: str,
    headers: Dict[str, str],
    retries: int = 3,
) -> Optional[List[Dict[str, Any]]]:
    """Fetch ``data`` list from an OpenRouter catalog endpoint with 3x retry."""
    for attempt in range(1, max(1, retries) + 1):
        try:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = (resp.json() or {}).get("data")
            return data if isinstance(data, list) else []
        except Exception as exc:
            sys.stderr.write(f"[openrouter.catalog] Fetch {url} failed (attempt {attempt}/{retries}): {exc}\n")
            if attempt < retries:
                await asyncio.sleep(min(0.4 * attempt, 1.5))
    return None


async def fetch_openrouter_model_catalog(
    api_key: str = "",
    base_url: str = "https://openrouter.ai/api/v1",
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """Fetch and normalize the full OpenRouter chat + embedding model catalog with 5-minute TTL cache.

    Args:
        api_key: Optional OpenRouter API key for authenticated rate limits.
        base_url: OpenRouter API base URL.
        force_refresh: When ``True``, bypass the 5-minute TTL cache.

    Returns:
        ``OpenRouterCatalogResponse`` dictionary containing ``source``, ``count``, ``fetched_at``,
        ``category_counts``, and all normalized ``models``.
    """
    root = (base_url or "https://openrouter.ai/api/v1").rstrip("/")
    cache_key = "default"
    cached = _CATALOG_CACHE.get(cache_key)
    if not force_refresh and cached and (time.monotonic() - cached["ts"]) <= CATALOG_CACHE_TTL_S:
        return cached["payload"]

    clean_key = (api_key or "").strip()
    headers = (
        {"Authorization": f"Bearer {clean_key}"}
        if clean_key and clean_key != "your_openrouter_api_key_here"
        else {}
    )

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            main_raw, emb_raw = await asyncio.gather(
                _fetch_json_with_retry(client, f"{root}/models", headers, retries=3),
                _fetch_json_with_retry(client, f"{root}/embeddings/models", headers, retries=2),
            )
    except Exception as exc:
        sys.stderr.write(f"[openrouter.catalog] Client setup failed: {exc}\n")
        main_raw, emb_raw = None, None

    by_id: Dict[str, Dict[str, Any]] = {}
    if main_raw:
        for item in main_raw:
            if isinstance(item, dict) and item.get("id"):
                norm = normalize_openrouter_model(item, is_embedding=False, tier="openrouter-live")
                by_id[norm["id"]] = norm
    if emb_raw:
        for item in emb_raw:
            if isinstance(item, dict) and item.get("id"):
                norm = normalize_openrouter_model(item, is_embedding=True, tier="openrouter-live")
                by_id[norm["id"]] = norm

    if by_id:
        models = _sort_catalog_models(list(by_id.values()))
        payload = {
            "source": "openrouter-live",
            "count": len(models),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "category_counts": _compute_category_counts(models),
            "models": models,
        }
        _CATALOG_CACHE[cache_key] = {"ts": time.monotonic(), "payload": payload}
        return payload

    fallback = _sort_catalog_models(build_curated_fallback_catalog())
    return {
        "source": "curated-fallback",
        "count": len(fallback),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "category_counts": _compute_category_counts(fallback),
        "models": fallback,
    }
