"""Pytest suite for OpenRouter API key testing, rich model catalog normalization, and Admin/Vision routes."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.app.config import Settings
from src.app.factory import create_app
from src.db.repository import InMemoryTwinRepository
from src.db.robot_store import InMemoryRobotStore
from src.vision.openrouter_catalog import (
    clear_catalog_cache,
    fetch_openrouter_model_catalog,
    normalize_openrouter_model,
    test_openrouter_api_key as verify_openrouter_api_key,
)


class _MockResponse:
    def __init__(self, status_code: int, payload: Any = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _build_client(tmp_path) -> TestClient:
    cfg = Settings(
        openrouter_api_key="",
        database_url="",
        neo4j_uri="",
        twinscan_storage_dir=str(tmp_path),
        twinscan_encryption_key="or-catalog-test-key",
    )
    app = create_app(
        settings=cfg,
        repository=InMemoryTwinRepository(encryption_key=cfg.twinscan_encryption_key),
        robot_store=InMemoryRobotStore(encryption_key=cfg.twinscan_encryption_key),
    )
    return TestClient(app)


# --- 1. test_openrouter_api_key Unit Tests ---


@pytest.mark.asyncio
async def test_openrouter_key_unconfigured() -> None:
    """Empty or placeholder API keys immediately return unconfigured without network I/O."""
    res = await verify_openrouter_api_key("", key_source="saved")
    assert res["ok"] is False
    assert res["status"] == "unconfigured"
    assert res["key_source"] == "saved"

    res2 = await verify_openrouter_api_key("your_openrouter_api_key_here", key_source="draft")
    assert res2["ok"] is False
    assert res2["status"] == "unconfigured"


@pytest.mark.asyncio
async def test_openrouter_key_valid_with_credits() -> None:
    """Valid key returns 200 connected with usage, limit, remaining, and total credits."""
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url: str, **kwargs):
            if url.endswith("/auth/key"):
                return _MockResponse(
                    200,
                    {"data": {"label": "Eigenia Prod Key", "is_free_tier": False, "usage": 1.25, "limit": 20.0}},
                )
            if url.endswith("/credits"):
                return _MockResponse(200, {"data": {"total_credits": 25.0, "total_usage": 1.25}})
            return _MockResponse(404)

    with patch("src.vision.openrouter_catalog.httpx.AsyncClient", FakeClient):
        res = await verify_openrouter_api_key("sk-or-v1-valid-test-key", key_source="draft")

    assert res["ok"] is True
    assert res["status"] == "connected"
    assert res["http_status"] == 200
    assert res["key_source"] == "draft"
    assert res["label"] == "Eigenia Prod Key"
    assert res["is_free_tier"] is False
    assert res["usage_usd"] == 1.25
    assert res["limit_usd"] == 20.0
    assert res["limit_remaining_usd"] == 18.75
    assert res["total_credits_usd"] == 25.0
    assert "sk-or-v1-valid-test-key" not in str(res)


@pytest.mark.asyncio
async def test_openrouter_key_401_fast_fails_without_retry() -> None:
    """HTTP 401/403 must fast-fail on the first attempt without retrying."""
    calls = 0

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url: str, **kwargs):
            nonlocal calls
            calls += 1
            return _MockResponse(401, {"error": {"message": "User not found."}})

    with patch("src.vision.openrouter_catalog.httpx.AsyncClient", FakeClient):
        res = await verify_openrouter_api_key("sk-or-v1-bad-key", key_source="draft", retries=3)

    assert calls == 1
    assert res["ok"] is False
    assert res["status"] == "invalid_key"
    assert res["http_status"] == 401
    assert res["error"] == "User not found."


@pytest.mark.asyncio
async def test_openrouter_key_503_retries_and_recovers(capsys) -> None:
    """Transient HTTP 503 retries up to 3 times and recovers when upstream responds 200."""
    attempts = 0

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url: str, **kwargs):
            nonlocal attempts
            if url.endswith("/auth/key"):
                attempts += 1
                if attempts < 3:
                    return _MockResponse(503, {"error": {"message": "Temporarily unavailable"}})
                return _MockResponse(200, {"data": {"label": "Recovered Key", "is_free_tier": True, "usage": 0.0}})
            return _MockResponse(404)

    with patch("src.vision.openrouter_catalog.httpx.AsyncClient", FakeClient), patch("asyncio.sleep", new=AsyncMock()):
        res = await verify_openrouter_api_key("sk-or-v1-retry-key", key_source="saved", retries=3)

    assert attempts == 3
    assert res["ok"] is True
    assert res["label"] == "Recovered Key"
    assert "[openrouter.test_key]" in capsys.readouterr().err


# --- 2. Model Normalizer & Catalog Tests ---


def test_normalize_openrouter_model_pricing_and_categories() -> None:
    """Verify per-1M pricing conversion, FREE tier, and vision/reasoning/web_research/embedding categories."""
    vision_reason = normalize_openrouter_model(
        {
            "id": "google/gemini-2.5-flash",
            "name": "Google: Gemini 2.5 Flash",
            "context_length": 1_048_576,
            "architecture": {"input_modalities": ["text", "image", "audio"], "output_modalities": ["text"]},
            "supported_parameters": ["reasoning"],
            "pricing": {"prompt": "0.0000003", "completion": "0.0000025", "image": "0.0001"},
        }
    )
    assert vision_reason["provider"] == "google"
    assert vision_reason["model_type"] == "Reasoning + Vision"
    assert set(["vision", "reasoning", "audio_video", "text"]).issubset(set(vision_reason["categories"]))
    assert vision_reason["pricing"]["prompt_per_1m_usd"] == 0.3
    assert vision_reason["pricing"]["completion_per_1m_usd"] == 2.5
    assert vision_reason["pricing"]["image_per_1k_usd"] == 0.1
    assert vision_reason["pricing"]["blended_per_1m_usd"] == 1.95
    assert vision_reason["pricing"]["cost_tier"] == "Standard ($$)"
    assert vision_reason["pricing"]["is_free"] is False

    web_model = normalize_openrouter_model(
        {
            "id": "perplexity/sonar-pro",
            "name": "Perplexity: Sonar Pro",
            "context_length": 200_000,
            "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
            "pricing": {"prompt": "0.000003", "completion": "0.000015", "web_search": "0.005"},
        }
    )
    assert web_model["model_type"] == "Web Research"
    assert "web_research" in web_model["categories"]
    assert web_model["pricing"]["cost_tier"] == "Frontier ($$$)"

    emb_model = normalize_openrouter_model(
        {
            "id": "openai/text-embedding-3-small",
            "name": "OpenAI: Text Embedding 3 Small",
            "context_length": 8192,
            "pricing": {"prompt": "0.00000002", "completion": "0"},
        },
        is_embedding=True,
    )
    assert emb_model["model_type"] == "Embedding"
    assert "embedding" in emb_model["categories"]
    assert emb_model["pricing"]["cost_tier"] == "Budget ($)"

    free_model = normalize_openrouter_model(
        {
            "id": "meta-llama/llama-4-maverick:free",
            "name": "Meta: Llama 4 Maverick (Free)",
            "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]},
            "pricing": {"prompt": "0", "completion": "0"},
        }
    )
    assert free_model["pricing"]["is_free"] is True
    assert free_model["pricing"]["cost_tier"] == "Free"
    assert "free" in free_model["categories"]


@pytest.mark.asyncio
async def test_fetch_openrouter_model_catalog_live_cache_and_fallback() -> None:
    """Verify full catalog fetch merges chat + embeddings, caches 5m, and falls back gracefully."""
    clear_catalog_cache()

    class LiveClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url: str, **kwargs):
            if url.endswith("/embeddings/models"):
                return _MockResponse(
                    200,
                    {"data": [{"id": "openai/text-embedding-3-small", "name": "Embedding Small", "pricing": {"prompt": "0.00000002", "completion": "0"}}]},
                )
            return _MockResponse(
                200,
                {
                    "data": [
                        {
                            "id": "google/gemini-2.5-flash",
                            "name": "Gemini 2.5 Flash",
                            "context_length": 1_000_000,
                            "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]},
                            "pricing": {"prompt": "0.0000003", "completion": "0.0000025"},
                        },
                        {
                            "id": "perplexity/sonar-pro",
                            "name": "Sonar Pro",
                            "context_length": 200_000,
                            "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
                            "pricing": {"prompt": "0.000003", "completion": "0.000015"},
                        },
                    ]
                },
            )

    with patch("src.vision.openrouter_catalog.httpx.AsyncClient", LiveClient):
        cat = await fetch_openrouter_model_catalog(api_key="", force_refresh=True)
    assert cat["source"] == "openrouter-live"
    assert cat["count"] == 3
    assert cat["category_counts"]["vision"] == 1
    assert cat["category_counts"]["web_research"] == 1
    assert cat["category_counts"]["embedding"] == 1

    # Fallback when OpenRouter is unreachable
    clear_catalog_cache()

    class DeadClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url: str, **kwargs):
            raise RuntimeError("offline")

    with patch("src.vision.openrouter_catalog.httpx.AsyncClient", DeadClient), patch("asyncio.sleep", new=AsyncMock()):
        fb = await fetch_openrouter_model_catalog(api_key="", force_refresh=True)
    assert fb["source"] == "curated-fallback"
    assert fb["count"] >= 8
    assert fb["category_counts"]["embedding"] >= 2


# --- 3. FastAPI Endpoints Integration Tests ---


def test_admin_test_key_and_catalog_and_vision_models_routes(tmp_path) -> None:
    """Verify POST /api/admin/openrouter/test-key (draft & saved), GET /api/admin/openrouter-models, and GET /api/vision/models."""
    clear_catalog_cache()
    with _build_client(tmp_path) as client:
        # 1. Unconfigured saved key test
        r0 = client.post("/api/admin/openrouter/test-key", json={})
        assert r0.status_code == 200
        assert r0.json()["status"] == "unconfigured"
        assert r0.json()["key_source"] == "saved"

        # 2. Draft key test (must NOT persist to DB)
        mock_test = AsyncMock(
            return_value={
                "ok": True,
                "status": "connected",
                "http_status": 200,
                "latency_ms": 88,
                "key_source": "draft",
                "label": "Draft Key",
                "is_free_tier": False,
                "usage_usd": 0.5,
                "limit_usd": 10.0,
                "limit_remaining_usd": 9.5,
                "total_credits_usd": 10.0,
                "error": None,
            }
        )
        with patch("src.api.routes_admin.test_openrouter_api_key", new=mock_test):
            r_draft = client.post(
                "/api/admin/openrouter/test-key",
                json={"api_key": "sk-or-v1-unsaved-draft"},
            )
        assert r_draft.status_code == 200
        assert r_draft.json()["ok"] is True
        assert mock_test.call_args.kwargs["key_source"] == "draft"
        assert mock_test.call_args.kwargs["api_key"] == "sk-or-v1-unsaved-draft"
        # Ensure DB was NOT mutated by testing a draft key
        assert client.app.state.runtime.openrouter_configured is False

        # 3. Masked placeholder falls back to saved key
        client.put("/api/admin/settings", json={"settings": {"openrouter_api_key": "sk-or-v1-saved-real-key"}})
        with patch("src.api.routes_admin.test_openrouter_api_key", new=mock_test):
            r_masked = client.post(
                "/api/admin/openrouter/test-key",
                json={"api_key": "sk-or-••••••-key"},
            )
        assert r_masked.status_code == 200
        assert mock_test.call_args.kwargs["key_source"] == "saved"
        assert mock_test.call_args.kwargs["api_key"] == "sk-or-v1-saved-real-key"

        # 4. GET /api/admin/openrouter-models?refresh=true
        fake_cat = {
            "source": "openrouter-live",
            "count": 1,
            "fetched_at": "2026-11-25T00:00:00+00:00",
            "category_counts": {"all": 1, "vision": 1},
            "models": [{"id": "google/gemini-2.5-flash", "label": "Gemini 2.5 Flash", "tier": "openrouter-live"}],
        }
        mock_cat = AsyncMock(return_value=fake_cat)
        with patch("src.api.routes_admin.fetch_openrouter_model_catalog", new=mock_cat):
            r_cat = client.get("/api/admin/openrouter-models?refresh=true")
        assert r_cat.status_code == 200
        assert r_cat.json()["source"] == "openrouter-live"
        assert mock_cat.call_args.kwargs["force_refresh"] is True

        # 5. GET /api/vision/models includes embedding_model & rich pricing/model_type
        r_vis = client.get("/api/vision/models")
        assert r_vis.status_code == 200
        body = r_vis.json()
        assert "embedding_model" in body
        assert len(body["models"]) >= 8
        assert "pricing" in body["models"][0]
        assert "model_type" in body["models"][0]
