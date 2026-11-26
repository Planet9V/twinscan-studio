"""Fernet AES-128-CBC + HMAC encryption-at-rest and secret masking utilities for PostgreSQL app_settings."""

from __future__ import annotations

import base64
import hashlib
import sys
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

ENCRYPTED_PREFIX = "enc:v1:"


def derive_fernet_key(raw_secret: str) -> bytes:
    """Derive a valid URL-safe 32-byte Fernet key from an arbitrary passphrase or key string.

    Args:
        raw_secret: User-supplied encryption key or passphrase.

    Returns:
        Base64 URL-safe 32-byte key suitable for ``cryptography.fernet.Fernet``.
    """
    stripped = raw_secret.strip()
    if stripped:
        try:
            Fernet(stripped.encode("utf-8"))
            return stripped.encode("utf-8")
        except Exception:
            pass
    digest = hashlib.sha256((stripped or "eigenia-twinscan-default-key").encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


class SecretCipher:
    """Symmetric Fernet cipher for encrypting secret configuration rows in PostgreSQL."""

    def __init__(self, key_material: str = "") -> None:
        """Initialize the Fernet cipher from ``key_material``."""
        self._fernet = Fernet(derive_fernet_key(key_material))

    def encrypt(self, plaintext: str) -> str:
        """Encrypt a plaintext string and prepend versioned marker ``enc:v1:``."""
        if not plaintext:
            return ""
        if plaintext.startswith(ENCRYPTED_PREFIX):
            return plaintext
        token = self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")
        return f"{ENCRYPTED_PREFIX}{token}"

    def decrypt(self, stored_value: str) -> str:
        """Decrypt an ``enc:v1:`` value, returning plaintext unchanged if unencrypted."""
        if not stored_value:
            return ""
        if not stored_value.startswith(ENCRYPTED_PREFIX):
            return stored_value
        token = stored_value[len(ENCRYPTED_PREFIX) :].encode("ascii")
        try:
            return self._fernet.decrypt(token).decode("utf-8")
        except InvalidToken as exc:
            sys.stderr.write(f"[crypto] Failed to decrypt secret (wrong encryption key?): {exc}\n")
            return ""


def mask_secret_value(value: Optional[str]) -> str:
    """Return a masked preview of a secret without exposing sensitive characters.

    Args:
        value: Plaintext secret string.

    Returns:
        Masked preview like ``sk-or-••••••9a2f`` or empty string when unset.
    """
    if not value:
        return ""
    s = value.strip()
    if len(s) <= 8:
        return "•" * len(s)
    return f"{s[:6]}••••••{s[-4:]}"
