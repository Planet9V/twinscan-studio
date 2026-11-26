"""Unit tests for Stage-1 OpenCV/zxing-cpp preprocessing and OpenRouter Vision client."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import cv2
import numpy as np
import pytest

from src.vision.openrouter_client import (
    OpenRouterVisionClient,
    deterministic_fallback_embedding,
)
from src.vision.preprocessor import decode_industrial_barcodes, preprocess_industrial_image


def _make_sample_jpeg() -> bytes:
    img = np.full((120, 200, 3), 180, dtype=np.uint8)
    cv2.putText(img, "SIEMENS S7-1500", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (20, 20, 20), 2)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


def test_preprocess_industrial_image_applies_clahe() -> None:
    """CLAHE preprocessor returns valid JPEG bytes and dimensions."""
    enhanced, meta = preprocess_industrial_image(_make_sample_jpeg())
    assert len(enhanced) > 100
    assert meta["width"] == 200
    assert meta["height"] == 120
    assert meta["clahe_applied"] is True


def test_preprocess_invalid_bytes_raises() -> None:
    """Corrupt image bytes raise ValueError."""
    with pytest.raises(ValueError):
        preprocess_industrial_image(b"not-an-image")


def test_decode_industrial_barcodes_handles_clean_frame() -> None:
    """Barcode decoder cleanly returns empty list when no barcode is present."""
    assert decode_industrial_barcodes(_make_sample_jpeg()) == []


def test_deterministic_fallback_embedding_preserves_similarity() -> None:
    """Related equipment descriptions score higher cosine similarity than unrelated ones."""
    v_siemens_1 = np.array(deterministic_fallback_embedding("Siemens SIMATIC S7-1500 PLC 24V"))
    v_siemens_2 = np.array(deterministic_fallback_embedding("Siemens SIMATIC S7-1200 PLC 24V"))
    v_hvac = np.array(deterministic_fallback_embedding("Trane Chilled Water Air Handler 480V"))
    assert len(v_siemens_1) == 1536
    assert float(np.dot(v_siemens_1, v_siemens_2)) > float(np.dot(v_siemens_1, v_hvac))


@pytest.mark.asyncio
async def test_openrouter_analyze_offline_fallback() -> None:
    """Without OPENROUTER_API_KEY, client completes Stage-1 cleanly without throwing."""
    client = OpenRouterVisionClient(api_key="")
    res = await client.analyze_equipment_image(_make_sample_jpeg())
    assert "offline-stage1" in res.model_used
    assert res.confidence > 0


@pytest.mark.asyncio
async def test_openrouter_analyze_with_mocked_api_and_consensus() -> None:
    """Mocked OpenRouter response parses structured JSON and checks dual-model consensus."""
    client = OpenRouterVisionClient(api_key="sk-or-test-key")
    payload_primary = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "name": "Siemens S7-1500 PLC",
                            "equipment_type": "PLC",
                            "dexpi_class": "ProgrammableLogicController",
                            "manufacturer": "Siemens",
                            "model_number": "6ES7515-2AM02-0AB0",
                            "serial_number": "S C-N4A99120",
                            "inferred_cpe_23": "cpe:2.3:h:siemens:simatic_s7-1500:*:*:*:*:*:*:*:*",
                            "voltage_rating": "24V DC",
                            "primary_bbox_norm": [100, 200, 900, 800],
                            "confidence": 0.96,
                        }
                    )
                }
            }
        ]
    }
    payload_secondary = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "name": "Siemens S7-1500 PLC",
                            "manufacturer": "Siemens",
                            "model_number": "6ES7515-2AM02-0AB0",
                            "serial_number": "S C-N4A99120",
                            "voltage_rating": "24V DC",
                        }
                    )
                }
            }
        ]
    }
    with patch.object(client, "_post_with_retry", new=AsyncMock(side_effect=[payload_primary, payload_secondary])):
        res = await client.analyze_equipment_image(_make_sample_jpeg(), consensus=True)
        assert res.manufacturer == "Siemens"
        assert res.model_number == "6ES7515-2AM02-0AB0"
        assert res.consensus_verified is True
        assert res.discrepancies == []


@pytest.mark.asyncio
async def test_openrouter_post_retries_three_times_and_logs_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    """External API failures log to stderr and retry exactly 3 times before raising."""
    client = OpenRouterVisionClient(api_key="sk-or-test-key", max_retries=3)
    mock_http = AsyncMock()
    mock_http.__aenter__.return_value.post.side_effect = RuntimeError("network timeout")

    with patch("src.vision.openrouter_client.httpx.AsyncClient", return_value=mock_http), patch(
        "src.vision.openrouter_client.asyncio.sleep", new=AsyncMock()
    ):
        with pytest.raises(RuntimeError, match="failed after 3 attempts"):
            await client._post_with_retry("chat/completions", {"model": "test"})

    err = capsys.readouterr().err
    assert "attempt 1/3" in err
    assert "attempt 3/3" in err
