"""
Tamper-evident audit log.

Each event is one JSON line containing an HMAC over (previous MAC + event).
Altering, deleting or re-ordering any line breaks the chain, which
``AuditLog.verify()`` detects.

What is logged: who (principal id), what (action), when (UTC), which
resource (document id / tenant), outcome, guardrail flags, model used.
What is NOT logged: raw PII, document content, secrets. Free text passed in
``details`` is redacted before writing.

[RULE: EUAIA-ART12]   Automatic event logging for traceability.
[RULE: EUAIA-ART26]   Logs retained for >= 6 months (``audit_retention_days``).
[RULE: GDPR-ART5-2]   Accountability: evidence of every processing operation.
[RULE: GDPR-ART30]    Supports the record of processing activities.
[RULE: GDPR-ART33]    Security events (guardrail blocks, decryption failures)
                      are recorded so breaches can be detected and reported.
[RULE: SEC-LOGGING]   HMAC chain makes the log tamper-evident.
[RULE: PII-LOG-SCRUB] All free-text fields are passed through ``redact()``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from finrag.security.pii import PIIDetector, redact

_GENESIS = "0" * 64


def _scrub(value: Any, detector: PIIDetector) -> Any:
    """Recursively redact PII from strings inside ``value``."""
    if isinstance(value, str):
        return redact(value, detector)
    if isinstance(value, dict):
        return {k: _scrub(v, detector) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_scrub(v, detector) for v in value]
    return value


class AuditLog:
    """Append-only, HMAC-chained JSONL audit log."""

    def __init__(self, path: Path, key: bytes) -> None:
        self._path = path
        self._key = key
        self._lock = threading.Lock()
        self._detector = PIIDetector()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._last_mac = self._read_last_mac()

    def _read_last_mac(self) -> str:
        if not self._path.exists():
            return _GENESIS
        last = _GENESIS
        with self._path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    last = json.loads(line)["mac"]
        return last

    def _mac(self, prev: str, body: str) -> str:
        return hmac.new(self._key, f"{prev}|{body}".encode(), hashlib.sha256).hexdigest()

    def record(self, action: str, principal: str, tenant: str, outcome: str = "success",
               **details: Any) -> None:
        """Append one event. ``details`` is PII-scrubbed before writing."""
        event = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "principal": principal,
            "tenant": tenant,
            "outcome": outcome,
            "details": _scrub(details, self._detector),
        }
        body = json.dumps(event, sort_keys=True, separators=(",", ":"))
        with self._lock:
            mac = self._mac(self._last_mac, body)
            line = json.dumps({"event": event, "prev": self._last_mac, "mac": mac},
                              sort_keys=True, separators=(",", ":"))
            # O_APPEND with 0600: append-only semantics, owner-only access.
            fd = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            self._last_mac = mac

    def verify(self) -> tuple[bool, int, str | None]:
        """Verify the full chain. Returns ``(ok, events_checked, error)``."""
        if not self._path.exists():
            return True, 0, None
        prev = _GENESIS
        count = 0
        with self._path.open("r", encoding="utf-8") as handle:
            for lineno, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                record = json.loads(line)
                body = json.dumps(record["event"], sort_keys=True, separators=(",", ":"))
                if record["prev"] != prev:
                    return False, count, f"chain break at line {lineno}"
                if not hmac.compare_digest(record["mac"], self._mac(prev, body)):
                    return False, count, f"MAC mismatch at line {lineno}"
                prev = record["mac"]
                count += 1
        return True, count, None

    def events(self, tenant: str | None = None) -> list[dict[str, Any]]:
        """Return events (optionally for one tenant) for review/export."""
        if not self._path.exists():
            return []
        out = []
        with self._path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    event = json.loads(line)["event"]
                    if tenant is None or event["tenant"] == tenant:
                        out.append(event)
        return out

    def expired_before(self, retention_days: int) -> datetime:
        """Cut-off timestamp for log archival under the retention policy.

        [RULE: EUAIA-ART26] Retention must be at least 183 days (6 months); the
        caller archives (rather than deletes) older segments to WORM storage.
        """
        return datetime.now(timezone.utc) - timedelta(days=max(retention_days, 183))
