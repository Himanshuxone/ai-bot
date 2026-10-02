"""
Key management and encryption at rest.

A single *master key* (from the environment) is expanded with HKDF into
independent sub-keys, one per purpose. Compromise or rotation of one purpose
does not expose the others.

[RULE: SEC-CRYPTO]     Fernet = AES-128-CBC + HMAC-SHA256 (authenticated
                       encryption); HKDF-SHA256 for key separation.
[RULE: GDPR-ART32]     Encryption of personal data at rest.
[RULE: GDPR-ART5-1F]   Integrity: Fernet tokens are authenticated, so any
                       tampering with stored data is detected on decrypt.
[RULE: SEC-SECRETS]    Keys are never written to disk or logs by this module.
"""

from __future__ import annotations

import base64
import logging
import os
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from finrag.config import Settings

logger = logging.getLogger(__name__)


class KeyConfigurationError(RuntimeError):
    """Raised when the master key is missing or malformed in a strict context."""


class DecryptionError(RuntimeError):
    """Raised when ciphertext fails authentication (tampering or wrong key)."""


def generate_master_key() -> str:
    """Create a new random 256-bit master key, urlsafe-base64 encoded."""
    # os.urandom uses the OS CSPRNG.
    return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")


def _derive(master: bytes, purpose: str) -> bytes:
    """Derive a 32-byte purpose-bound sub-key from the master key with HKDF."""
    # [RULE: SEC-CRYPTO] ``info`` binds the derived key to its purpose, giving
    # cryptographic key separation between store / vault / pseudonymiser / audit.
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"finrag-v1",
        info=purpose.encode("utf-8"),
    ).derive(master)


@dataclass(frozen=True)
class KeyRing:
    """Holds purpose-specific keys derived from the master key."""

    store_key: bytes  # encrypts the vector store (document chunks)
    vault_key: bytes  # encrypts the pseudonym -> original-value vault
    pseudonym_key: bytes  # HMAC key for deterministic PII tokens
    audit_key: bytes  # HMAC key for the tamper-evident audit chain

    @classmethod
    def from_settings(cls, settings: Settings) -> "KeyRing":
        """Build the key ring, failing closed in production if no key is set."""
        secret = settings.master_key.get_secret_value() if settings.master_key else None
        if not secret:
            if settings.is_production:
                # [RULE: SEC-ERROR-HANDLING] Fail closed: never run production
                # with an ephemeral or default key.
                raise KeyConfigurationError("FINRAG_MASTER_KEY must be set in production")
            # Development convenience only: an ephemeral key means data written in
            # this process cannot be read after restart. We warn loudly.
            logger.warning(
                "FINRAG_MASTER_KEY not set - using an EPHEMERAL key (development only)."
            )
            secret = generate_master_key()
        try:
            master = base64.urlsafe_b64decode(secret.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise KeyConfigurationError("FINRAG_MASTER_KEY is not valid base64") from exc
        if len(master) < 32:
            # [RULE: SEC-CRYPTO] Require at least 256 bits of key material.
            raise KeyConfigurationError("FINRAG_MASTER_KEY must decode to >= 32 bytes")
        return cls(
            store_key=_derive(master, "store"),
            vault_key=_derive(master, "vault"),
            pseudonym_key=_derive(master, "pseudonym"),
            audit_key=_derive(master, "audit"),
        )


class Encryptor:
    """Thin wrapper around Fernet for authenticated encryption of byte blobs."""

    def __init__(self, raw_key: bytes) -> None:
        # Fernet expects a urlsafe-base64 32-byte key.
        self._fernet = Fernet(base64.urlsafe_b64encode(raw_key))

    def encrypt(self, plaintext: bytes) -> bytes:
        """Encrypt and authenticate ``plaintext``."""
        return self._fernet.encrypt(plaintext)

    def decrypt(self, token: bytes) -> bytes:
        """Decrypt ``token``; raises ``DecryptionError`` if it was tampered with."""
        try:
            return self._fernet.decrypt(token)
        except InvalidToken as exc:
            # [RULE: GDPR-ART33] An authentication failure may indicate tampering;
            # surface it as a distinct error so callers can log a security event.
            raise DecryptionError("ciphertext failed authentication") from exc


def atomic_write(path: "os.PathLike[str] | str", data: bytes) -> None:
    """Write ``data`` atomically with owner-only permissions (0600)."""
    # [RULE: GDPR-ART5-1F] Atomic replace avoids half-written (corrupted) files;
    # 0600 restricts read access to the service account (least privilege).
    tmp = f"{os.fspath(path)}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
