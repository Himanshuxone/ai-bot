"""
Encrypted, tenant-isolated document store.

Layout on disk (one directory per tenant)::

    data/tenants/<tenant>/store.enc   <- Fernet-encrypted JSON (docs + chunks)
    data/tenants/<tenant>/vault.enc   <- pseudonym vault (separate key)

Only **pseudonymised** chunk text is stored here; the raw upload is never
persisted.

[RULE: GDPR-ART32]    Encrypted at rest with a dedicated sub-key.
[RULE: GDPR-ART5-1C]  Raw files are discarded after parsing; only the
                      pseudonymised text needed for retrieval is kept.
[RULE: GDPR-ART5-1E]  Every document carries an ``expires_at``; ``purge_expired``
                      deletes overdue documents (storage limitation).
[RULE: GDPR-ART17]    Hard deletion of documents and their chunks.
[RULE: OWASP-LLM08]   Tenant directories are derived from the authenticated
                      principal and validated against a strict pattern.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from finrag.retrieval.index import HybridIndex, SearchHit
from finrag.security.crypto import Encryptor, atomic_write

_TENANT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")


def validate_tenant(tenant: str) -> str:
    """Ensure a tenant id is safe to use as a directory name.

    [RULE: SEC-FILE-UPLOAD] [RULE: OWASP-LLM08] Blocks path traversal such as
    ``../other-tenant`` which would break tenant isolation.
    """
    if not _TENANT_RE.match(tenant):
        raise ValueError("invalid tenant id")
    return tenant


@dataclass
class DocumentRecord:
    """Metadata kept for each ingested document (no raw content)."""

    doc_id: str
    filename: str
    file_type: str
    sha256: str
    uploaded_by: str
    uploaded_at: str
    expires_at: str
    # [RULE: GDPR-ART6] [RULE: GDPR-ART5-1B] Lawful basis and purpose are
    # mandatory metadata recorded at ingestion.
    lawful_basis: str
    purpose: str
    pii_counts: dict[str, int] = field(default_factory=dict)
    special_categories: list[str] = field(default_factory=list)
    special_category_condition: str | None = None
    quarantined_chunks: int = 0
    data_subject_tokens: list[str] = field(default_factory=list)


@dataclass
class ChunkRecord:
    """A stored, pseudonymised chunk."""

    chunk_id: str
    doc_id: str
    text: str
    location: str
    quarantined: bool = False  # True if indirect prompt injection was detected


class TenantStore:
    """All documents and chunks for one tenant, encrypted at rest."""

    def __init__(self, root: Path, tenant: str, encryptor: Encryptor) -> None:
        self.tenant = validate_tenant(tenant)
        self.dir = root / "tenants" / self.tenant
        self.dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._path = self.dir / "store.enc"
        self._enc = encryptor
        self._lock = threading.RLock()
        self.documents: dict[str, DocumentRecord] = {}
        self.chunks: list[ChunkRecord] = []
        self._index: HybridIndex | None = None
        self._load()

    # ------------------------------------------------------------ persistence
    def _load(self) -> None:
        if not self._path.exists():
            return
        payload = json.loads(self._enc.decrypt(self._path.read_bytes()))
        self.documents = {k: DocumentRecord(**v) for k, v in payload["documents"].items()}
        self.chunks = [ChunkRecord(**c) for c in payload["chunks"]]

    def _save(self) -> None:
        payload = {
            "documents": {k: asdict(v) for k, v in self.documents.items()},
            "chunks": [asdict(c) for c in self.chunks],
        }
        atomic_write(self._path, self._enc.encrypt(json.dumps(payload).encode()))
        self._index = None  # invalidate the in-memory index

    # ---------------------------------------------------------------- writes
    def add_document(self, record: DocumentRecord, chunks: list[ChunkRecord]) -> None:
        """Persist a document and its chunks atomically."""
        with self._lock:
            self.documents[record.doc_id] = record
            self.chunks.extend(chunks)
            self._save()

    def delete_document(self, doc_id: str) -> bool:
        """Hard-delete a document and all of its chunks."""
        with self._lock:
            if doc_id not in self.documents:
                return False
            del self.documents[doc_id]
            self.chunks = [c for c in self.chunks if c.doc_id != doc_id]
            self._save()
            return True

    def replace_token(self, token: str, replacement: str) -> int:
        """Overwrite a pseudonym token in all chunks (used for erasure)."""
        changed = 0
        with self._lock:
            for chunk in self.chunks:
                if token in chunk.text:
                    chunk.text = chunk.text.replace(token, replacement)
                    changed += 1
            for doc in self.documents.values():
                if token in doc.data_subject_tokens:
                    doc.data_subject_tokens.remove(token)
            if changed:
                self._save()
        return changed

    def expired_documents(self, now: datetime | None = None) -> list[str]:
        """Return ids of documents past their retention deadline."""
        now = now or datetime.now(timezone.utc)
        return [d.doc_id for d in self.documents.values()
                if datetime.fromisoformat(d.expires_at) <= now]

    # ----------------------------------------------------------------- reads
    def find_by_hash(self, sha256: str) -> DocumentRecord | None:
        """Detect duplicate uploads (avoids storing the same data twice)."""
        return next((d for d in self.documents.values() if d.sha256 == sha256), None)

    def search(self, query: str, top_k: int) -> list[tuple[ChunkRecord, float]]:
        """Hybrid search over this tenant's non-quarantined chunks only."""
        with self._lock:
            if self._index is None:
                self._index = HybridIndex([c.text for c in self.chunks])
            excluded = {i for i, c in enumerate(self.chunks) if c.quarantined}
            hits: list[SearchHit] = self._index.search(query, top_k, exclude=excluded)
            return [(self.chunks[h.position], h.score) for h in hits]
