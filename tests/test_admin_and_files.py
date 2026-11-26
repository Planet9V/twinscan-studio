"""Unit & API tests for Fernet secret encryption, Admin config hot-reload, and PG file storage."""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.app.config import Settings
from src.app.factory import create_app
from src.db.crypto import SecretCipher, mask_secret_value
from src.db.repository import InMemoryTwinRepository


def test_fernet_cipher_encrypt_decrypt_and_masking() -> None:
    """SecretCipher round-trips secrets cleanly and mask_secret_value hides sensitive core."""
    cipher = SecretCipher("eigenia-unit-test-passphrase")
    enc = cipher.encrypt("sk-or-v1-supersecret9988")
    assert enc.startswith("enc:v1:")
    assert "supersecret" not in enc
    assert cipher.decrypt(enc) == "sk-or-v1-supersecret9988"
    masked = mask_secret_value("sk-or-v1-supersecret9988")
    assert masked.startswith("sk-or-") and masked.endswith("9988") and "••••" in masked


def test_admin_settings_hot_reload_audit_guard_and_file_dedup(tmp_path) -> None:
    """Admin endpoints enforce token guard, encrypt/mask keys, hot-reload runtime, and dedup files."""
    cfg = Settings(
        openrouter_api_key="",
        database_url="",
        neo4j_uri="",
        twinscan_encryption_key="test-key",
        twinscan_admin_token="secret-admin-tok",
        twinscan_storage_dir=str(tmp_path),
    )
    app = create_app(settings=cfg, repository=InMemoryTwinRepository(encryption_key="test-key"))

    with TestClient(app) as client:
        # 1. Token guard blocks unauthenticated PUT
        denied = client.put("/api/admin/settings", json={"settings": {"facility_name": "Plant X"}})
        assert denied.status_code == 401

        # 2. Authorized PUT saves encrypted secret, hot-reloads OpenRouter status, and logs audit
        headers = {"X-Admin-Token": "secret-admin-tok"}
        upd = client.put(
            "/api/admin/settings",
            headers=headers,
            json={
                "settings": {
                    "openrouter_api_key": "sk-or-v1-livekey123456",
                    "facility_name": "Eigenia Water Plant",
                    "near_proximity_m": "4.5",
                }
            },
        )
        assert upd.status_code == 200
        assert upd.json()["openrouter_configured"] is True
        key_row = next(s for s in upd.json()["settings"] if s["key"] == "openrouter_api_key")
        assert key_row["is_set"] is True
        assert "livekey" not in key_row["value"]

        # Re-submitting masked placeholder preserves existing secret untouched
        preserve = client.put(
            "/api/admin/settings",
            headers=headers,
            json={"settings": {"openrouter_api_key": key_row["value"]}},
        )
        assert preserve.status_code == 200
        assert preserve.json()["updated_count"] == 0

        audit = client.get("/api/admin/audit").json()["entries"]
        assert len(audit) >= 3

        # 3. Content-addressed file storage deduplicates identical uploads + supports ETag 304
        payload = b"PDF-MANUAL-SIEMENS-S7-1500-CONTENT"
        up1 = client.post(
            "/api/files",
            files={"file": ("manual.pdf", payload, "application/pdf")},
            data={"category": "manual_upload"},
        )
        assert up1.status_code == 200
        f1 = up1.json()["file"]
        assert f1["deduplicated"] is False

        up2 = client.post(
            "/api/files",
            files={"file": ("manual-copy.pdf", payload, "application/pdf")},
            data={"category": "manual_upload"},
        )
        assert up2.status_code == 200
        assert up2.json()["file"]["deduplicated"] is True
        assert up2.json()["stats"]["dedup_savings_bytes"] == len(payload)

        dl = client.get(f1["url"])
        assert dl.status_code == 200
        assert dl.content == payload
        etag = dl.headers["etag"]
        assert client.get(f1["url"], headers={"If-None-Match": etag}).status_code == 304

        # 4. Storage integrity scrub & non-secret config export
        scrub = client.post("/api/admin/storage-scrub", headers=headers)
        assert scrub.status_code == 200
        assert scrub.json()["corrupted_blobs"] == 0

        exported = client.get("/api/admin/config-export").json()
        assert "openrouter_api_key" not in exported["settings"]
        assert exported["settings"]["facility_name"] == "Eigenia Water Plant"
