"""
Authentication, role-based access control and rate limiting.

API keys are never stored in clear text: the keys file holds SHA-256 hashes,
and incoming keys are hashed and compared in constant time.

Keys file format (JSON)::

    [
      {"key_sha256": "<hex>", "principal": "alice", "tenant": "acme",
       "roles": ["analyst"]}
    ]

[RULE: SEC-AUTHN]     Hashed credentials, constant-time comparison.
[RULE: SEC-AUTHZ]     Deny-by-default RBAC; every operation names a permission.
[RULE: OWASP-LLM08]   Each principal is bound to exactly one tenant; the tenant
                      is taken from the credential, never from the request.
[RULE: OWASP-LLM10]   Per-principal token-bucket rate limiting.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class Permission(str, Enum):
    """Fine-grained permissions checked by the pipeline and API."""

    QUERY = "query"
    INGEST = "ingest"
    DELETE_DOCUMENT = "delete_document"
    LIST_DOCUMENTS = "list_documents"
    ERASE_SUBJECT = "erase_subject"  # GDPR Art. 17
    EXPORT_SUBJECT = "export_subject"  # GDPR Art. 15 / 20
    REIDENTIFY = "reidentify"  # see original values behind pseudonyms
    VIEW_AUDIT = "view_audit"
    PURGE = "purge"  # run retention enforcement


# [RULE: SEC-AUTHZ] Least privilege: viewers can only ask questions; only the
# DPO role can re-identify pseudonymised data or act on data-subject requests.
ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    "viewer": frozenset({Permission.QUERY}),
    "analyst": frozenset({Permission.QUERY, Permission.INGEST, Permission.LIST_DOCUMENTS,
                          Permission.DELETE_DOCUMENT}),
    "dpo": frozenset({Permission.LIST_DOCUMENTS, Permission.ERASE_SUBJECT,
                      Permission.EXPORT_SUBJECT, Permission.REIDENTIFY,
                      Permission.VIEW_AUDIT, Permission.DELETE_DOCUMENT, Permission.PURGE}),
    "admin": frozenset({Permission.LIST_DOCUMENTS, Permission.VIEW_AUDIT, Permission.PURGE,
                        Permission.DELETE_DOCUMENT}),
}


class AccessDenied(PermissionError):
    """Raised when a principal lacks a required permission."""


@dataclass(frozen=True)
class Principal:
    """An authenticated caller bound to one tenant."""

    principal_id: str
    tenant: str
    roles: frozenset[str]

    @property
    def permissions(self) -> frozenset[Permission]:
        """Union of permissions over all roles (unknown roles grant nothing)."""
        perms: set[Permission] = set()
        for role in self.roles:
            perms |= ROLE_PERMISSIONS.get(role, frozenset())
        return frozenset(perms)

    def require(self, permission: Permission) -> None:
        """Raise ``AccessDenied`` unless the principal holds ``permission``."""
        # [RULE: SEC-AUTHZ] Deny by default.
        if permission not in self.permissions:
            raise AccessDenied(f"{self.principal_id} lacks permission '{permission.value}'")


def hash_api_key(api_key: str) -> str:
    """Return the SHA-256 hex digest used to store an API key."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


class APIKeyAuthenticator:
    """Resolve API keys to principals using a file of hashed keys."""

    def __init__(self, entries: list[dict[str, object]]) -> None:
        self._entries = entries

    @classmethod
    def from_file(cls, path: Path) -> "APIKeyAuthenticator":
        """Load hashed keys from a JSON file."""
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def authenticate(self, api_key: str | None) -> Principal | None:
        """Return the matching principal or ``None``. Constant-time compare."""
        if not api_key or len(api_key) > 256:
            return None
        candidate = hash_api_key(api_key)
        match: Principal | None = None
        # Iterate over every entry (no early exit) to avoid timing side channels.
        for entry in self._entries:
            if hmac.compare_digest(str(entry["key_sha256"]), candidate):
                match = Principal(
                    principal_id=str(entry["principal"]),
                    tenant=str(entry["tenant"]),
                    roles=frozenset(entry.get("roles", [])),  # type: ignore[arg-type]
                )
        return match


class RateLimiter:
    """Thread-safe token bucket, keyed by principal id."""

    def __init__(self, per_minute: int) -> None:
        self._capacity = float(per_minute)
        self._rate = per_minute / 60.0
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        """Consume one token for ``key``; return False if the bucket is empty."""
        now = time.monotonic()
        with self._lock:
            tokens, last = self._buckets.get(key, (self._capacity, now))
            tokens = min(self._capacity, tokens + (now - last) * self._rate)
            if tokens < 1.0:
                self._buckets[key] = (tokens, now)
                return False
            self._buckets[key] = (tokens - 1.0, now)
            return True
