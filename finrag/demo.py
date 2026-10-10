"""
Public demo mode: private, temporary workspaces pre-loaded with sample documents.

Why this exists
---------------
A public showcase (for example on a serverless host) must not give every visitor the
same workspace, or one visitor could read what another uploaded. In demo mode each
visitor gets:

* their **own tenant** (``demo-<random>``), so stores, vault and keys are isolated;
* a **stateless signed token** as API key, so any server instance can verify it
  without shared storage (``fd1.<tenant>.<expiry>.<signature>``);
* three **synthetic sample documents** (CSV, Markdown, Excel) already loaded;
* an expiry (default 2 hours) after which the token stops working and the oldest
  workspaces are deleted.

Demo mode also forces the offline answer generator (see ``config.py``), so no visitor
content ever leaves the host.

Limits to be aware of: serverless instances have temporary disks, so a workspace can
disappear if the visitor is routed to a different or recycled instance. The demo copes
by re-loading the samples; files the visitor uploaded would be lost.

[RULE: OWASP-LLM08]  One isolated tenant per visitor.
[RULE: SEC-AUTHN]    Tokens are HMAC-signed, expire, and are compared in constant time.
[RULE: SEC-CRYPTO]   Signing key is HKDF-derived from the master key (purpose "demo").
[RULE: GDPR-ART25]   Privacy by default: temporary, isolated, offline, synthetic data.
[RULE: GDPR-ART5-1E] Workspaces expire and are pruned.
[RULE: OWASP-LLM10]  Capped number of workspaces; session creation is rate limited by
                     the caller.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
import secrets
import time
from pathlib import Path

from finrag.pipeline import FinRAGPipeline
from finrag.security.access import Principal

logger = logging.getLogger(__name__)

DEMO_DATA = Path(__file__).parent / "demo_data"
SAMPLE_FILES = ("sample_financials.csv", "board_notes.md", "quarterly_budget.xlsx")
_TENANT_RE = re.compile(r"^demo-[0-9a-f]{12}$")
_PREFIX = "fd1"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


class DemoAuthenticator:
    """Issue and verify stateless demo session tokens."""

    def __init__(self, key: bytes, session_minutes: int) -> None:
        self._key = key
        self.ttl_seconds = session_minutes * 60

    def _sign(self, tenant: str, expiry: int) -> str:
        mac = hmac.new(self._key, f"{_PREFIX}.{tenant}.{expiry}".encode(), hashlib.sha256)
        return _b64(mac.digest())

    def issue(self) -> str:
        """Create a new workspace id and a signed token for it."""
        tenant = f"demo-{secrets.token_hex(6)}"
        expiry = int(time.time()) + self.ttl_seconds
        return f"{_PREFIX}.{tenant}.{expiry}.{self._sign(tenant, expiry)}"

    def authenticate(self, token: str | None) -> Principal | None:
        """Return the visitor principal for a valid, unexpired token, else ``None``."""
        if not token or len(token) > 200 or not token.startswith(f"{_PREFIX}."):
            return None
        parts = token.split(".")
        if len(parts) != 4:
            return None
        _, tenant, expiry_text, signature = parts
        if not _TENANT_RE.match(tenant) or not expiry_text.isdigit():
            return None
        expiry = int(expiry_text)
        # Compare first, then check expiry, so timing does not reveal which failed.
        valid = hmac.compare_digest(signature, self._sign(tenant, expiry))
        if not valid or expiry < time.time():
            return None
        return Principal(principal_id=f"visitor-{tenant[5:11]}", tenant=tenant,
                         roles=frozenset({"analyst"}))


def seed_samples(pipeline: FinRAGPipeline, principal: Principal) -> int:
    """Load the synthetic sample documents into the visitor's workspace."""
    loaded = 0
    for name in SAMPLE_FILES:
        try:
            pipeline.ingest(principal, name, (DEMO_DATA / name).read_bytes(),
                            lawful_basis="legitimate_interests", purpose="financial_analysis",
                            retention_days=1)
            loaded += 1
        except Exception as exc:
            # [RULE: SEC-LOGGING] Log only the exception type.
            logger.error("could not load demo sample %s: %s", name, type(exc).__name__)
    return loaded


def prune_workspaces(pipeline: FinRAGPipeline, keep: int) -> int:
    """Delete the oldest demo workspaces beyond ``keep``. Returns how many were removed."""
    root = pipeline.data_dir / "tenants"
    if not root.is_dir():
        return 0
    workspaces = [p for p in root.iterdir() if p.is_dir() and _TENANT_RE.match(p.name)]
    workspaces.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    stale = workspaces[max(keep, 1):]
    for path in stale:
        pipeline.purge_tenant(path.name)
    return len(stale)
