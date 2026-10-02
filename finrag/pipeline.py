"""
FinRAG pipeline: the orchestrator that ties every control together.

Ingestion
---------
    upload -> validate & parse (loaders) -> Art.9 scan + lawful basis check
           -> pseudonymise (PII -> tokens, vault) -> chunk
           -> indirect-injection screen (quarantine) -> encrypted store -> audit

Question answering
------------------
    question -> authz + rate limit -> input guardrails -> pseudonymise query
             -> tenant-scoped hybrid retrieval -> context screen
             -> LLM (fenced sources, no tools) -> output guardrails
             -> confidence + human-review flag -> optional re-identification (DPO)
             -> AI label + disclaimer -> audit

Data-subject rights
-------------------
    erase_subject (Art. 17), export_subject (Art. 15/20), delete_document,
    purge_expired (Art. 5(1)(e)).

[RULE: GDPR-ART25]   Privacy by design: every path goes through these controls;
                     there is no "raw" bypass API.
[RULE: GDPR-ART5-2]  Every operation is audited.
[RULE: EUAIA-ART9]   Risk controls applied systematically in one place.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from finrag.config import Settings, get_settings
from finrag.generation.llm import AnswerGenerator, LLMUnavailableError, build_generator
from finrag.generation.prompts import SYSTEM_CANARY, PromptSource
from finrag.governance import gdpr, transparency
from finrag.ingestion.chunker import chunk_sections
from finrag.ingestion.loaders import UnsupportedDocumentError, load_document
from finrag.security import guardrails
from finrag.security.access import AccessDenied, Permission, Principal, RateLimiter
from finrag.security.audit import AuditLog
from finrag.security.crypto import DecryptionError, Encryptor, KeyRing
from finrag.security.pii import PIIDetector, Pseudonymiser, PseudonymVault, redact
from finrag.retrieval.store import ChunkRecord, DocumentRecord, TenantStore

logger = logging.getLogger(__name__)


class RateLimitExceeded(RuntimeError):
    """Raised when a principal exceeds the configured request rate."""


@dataclass
class IngestReport:
    """Summary returned after ingesting a document (contains no PII)."""

    doc_id: str
    filename: str
    file_type: str
    chunks: int
    quarantined_chunks: int
    pii_redacted: dict[str, int]
    expires_at: str
    duplicate: bool = False


@dataclass
class Citation:
    """A source reference attached to an answer."""

    label: str
    doc_id: str
    filename: str
    location: str
    score: float
    excerpt: str


@dataclass
class Answer:
    """Final, guardrailed answer returned to callers."""

    answer: str
    citations: list[Citation] = field(default_factory=list)
    confidence: float = 0.0
    requires_human_review: bool = True
    review_reasons: list[str] = field(default_factory=list)
    blocked: bool = False
    blocked_reasons: list[str] = field(default_factory=list)
    ai_disclosure: str = transparency.AI_DISCLOSURE
    disclaimer: str = transparency.FINANCIAL_DISCLAIMER
    label: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable representation."""
        return asdict(self)


@dataclass
class _TenantContext:
    """Per-tenant crypto material, store, vault and pseudonymiser."""

    store: TenantStore
    vault: PseudonymVault
    pseudonymiser: Pseudonymiser


def _tenant_key(key: bytes, tenant: str) -> bytes:
    """Derive a tenant-specific key so tenants are cryptographically isolated.

    [RULE: OWASP-LLM08] [RULE: SEC-CRYPTO] The same e-mail in two tenants gets
    different tokens and is encrypted under different keys.
    """
    return hmac.new(key, f"tenant:{tenant}".encode(), hashlib.sha256).digest()


class FinRAGPipeline:
    """High-level, compliance-enforcing API used by the CLI and HTTP server."""

    def __init__(self, settings: Settings | None = None,
                 generator: AnswerGenerator | None = None) -> None:
        self.settings = settings or get_settings()
        self.keys = KeyRing.from_settings(self.settings)
        self.data_dir = Path(self.settings.data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.audit = AuditLog(self.data_dir / "audit" / "audit.log", self.keys.audit_key)
        self.generator = generator or build_generator(self.settings)
        self.detector = PIIDetector()
        self.rate_limiter = RateLimiter(self.settings.rate_limit_per_minute)
        self._tenants: dict[str, _TenantContext] = {}

    # ------------------------------------------------------------- helpers
    def _ctx(self, tenant: str) -> _TenantContext:
        """Lazily open the encrypted store/vault for a tenant."""
        if tenant not in self._tenants:
            try:
                store = TenantStore(self.data_dir, tenant,
                                    Encryptor(_tenant_key(self.keys.store_key, tenant)))
                vault = PseudonymVault(store.dir / "vault.enc",
                                       Encryptor(_tenant_key(self.keys.vault_key, tenant)))
            except DecryptionError:
                # [RULE: GDPR-ART33] Tampered data or wrong key: record a security
                # event so a possible breach can be investigated, then fail closed.
                self.audit.record("open_tenant_store", "system", tenant,
                                  outcome="decryption_failed")
                raise
            pseudo = Pseudonymiser(_tenant_key(self.keys.pseudonym_key, tenant), vault,
                                   self.detector)
            self._tenants[tenant] = _TenantContext(store, vault, pseudo)
        return self._tenants[tenant]

    def _authorise(self, principal: Principal, permission: Permission, action: str) -> None:
        """Check a permission and audit denials as security events."""
        try:
            principal.require(permission)
        except AccessDenied:
            # [RULE: GDPR-ART33] [RULE: SEC-AUTHZ] Denied access is logged.
            self.audit.record(action, principal.principal_id, principal.tenant,
                              outcome="denied", permission=permission.value)
            raise

    # ----------------------------------------------------------- ingestion
    def ingest(
        self,
        principal: Principal,
        filename: str,
        data: bytes,
        *,
        lawful_basis: str,
        purpose: str,
        retention_days: int | None = None,
        consent_reference: str | None = None,
        special_category_condition: str | None = None,
    ) -> IngestReport:
        """Validate, pseudonymise, chunk and store a financial document."""
        self._authorise(principal, Permission.INGEST, "ingest")
        ctx = self._ctx(principal.tenant)
        try:
            loaded = load_document(filename, data, self.settings)
        except UnsupportedDocumentError as exc:
            # [RULE: OWASP-LLM04] Rejected uploads are recorded, never stored.
            self.audit.record("ingest", principal.principal_id, principal.tenant,
                              outcome="rejected", reason=str(exc))
            raise

        digest = hashlib.sha256(data).hexdigest()
        existing = ctx.store.find_by_hash(digest)
        if existing:
            # [RULE: GDPR-ART5-1C] Do not store a second copy of the same data.
            return IngestReport(existing.doc_id, existing.filename, existing.file_type,
                                sum(1 for c in ctx.store.chunks if c.doc_id == existing.doc_id),
                                existing.quarantined_chunks, existing.pii_counts,
                                existing.expires_at, duplicate=True)

        # [RULE: GDPR-ART9] Scan raw text for special-category indicators.
        raw_text = "\n".join(s.text or (s.header + "\n" + "\n".join(s.rows))
                             for s in loaded.sections)
        special = self.detector.special_categories(raw_text)
        try:
            basis, purp, condition = gdpr.validate_processing(
                lawful_basis, purpose, consent_reference, special, special_category_condition)
            expires_at = gdpr.retention_deadline(self.settings, retention_days)
        except gdpr.ComplianceError as exc:
            self.audit.record("ingest", principal.principal_id, principal.tenant,
                              outcome="rejected", reason=str(exc), filename=loaded.filename)
            raise

        doc_id = uuid.uuid4().hex
        # [RULE: PII-PSEUDONYMISE] [RULE: GDPR-ART5-1C] Replace identifiers
        # BEFORE chunking/storage, so no raw PII ever reaches disk or the LLM.
        totals: dict[str, int] = {}

        def _pseudo(text: str) -> str:
            out, counts = ctx.pseudonymiser.pseudonymise(text, doc_id)
            for key, value in counts.items():
                totals[key] = totals.get(key, 0) + value
            return out

        for section in loaded.sections:
            section.text = _pseudo(section.text) if section.text else section.text
            section.header = _pseudo(section.header) if section.header else section.header
            section.rows = [_pseudo(r) for r in section.rows]

        chunks = chunk_sections(loaded.sections, self.settings.chunk_size_chars,
                                self.settings.chunk_overlap_chars)
        records: list[ChunkRecord] = []
        quarantined = 0
        for i, chunk in enumerate(chunks):
            # [RULE: OWASP-LLM01] [RULE: OWASP-LLM04] Quarantine instruction-like
            # chunks: stored for audit, but never retrieved into a prompt.
            findings = guardrails.screen_context(chunk.text)
            if findings:
                quarantined += 1
            records.append(ChunkRecord(chunk_id=f"{doc_id}:{i}", doc_id=doc_id,
                                       text=chunk.text, location=chunk.location,
                                       quarantined=bool(findings)))

        record = DocumentRecord(
            doc_id=doc_id, filename=loaded.filename, file_type=loaded.file_type,
            sha256=digest, uploaded_by=principal.principal_id,
            uploaded_at=datetime.now(timezone.utc).isoformat(),
            expires_at=expires_at.isoformat(), lawful_basis=basis.value, purpose=purp.value,
            pii_counts=totals, special_categories=special,
            special_category_condition=condition.value if condition else None,
            quarantined_chunks=quarantined,
            data_subject_tokens=ctx.vault.tokens_for_doc(doc_id),
        )
        ctx.store.add_document(record, records)
        ctx.vault.save()
        # The raw ``data`` bytes go out of scope here and are never persisted.

        self.audit.record("ingest", principal.principal_id, principal.tenant,
                          doc_id=doc_id, filename=loaded.filename, file_type=loaded.file_type,
                          chunks=len(records), quarantined=quarantined, pii_counts=totals,
                          lawful_basis=basis.value, purpose=purp.value,
                          expires_at=record.expires_at)
        return IngestReport(doc_id, loaded.filename, loaded.file_type, len(records),
                            quarantined, totals, record.expires_at)

    # ---------------------------------------------------- question answering
    def ask(self, principal: Principal, question: str, *, reidentify: bool = False) -> Answer:
        """Answer a question from the tenant's documents with full guardrails."""
        self._authorise(principal, Permission.QUERY, "query")
        # [RULE: OWASP-LLM10] Per-principal rate limit.
        if not self.rate_limiter.allow(principal.principal_id):
            self.audit.record("query", principal.principal_id, principal.tenant,
                              outcome="rate_limited")
            raise RateLimitExceeded("rate limit exceeded")
        ctx = self._ctx(principal.tenant)

        # 1) Input guardrails ------------------------------------------------
        check = guardrails.check_query(question, self.settings.max_query_chars, self.detector)
        if not check.allowed:
            # [RULE: EUAIA-ART5] [RULE: OWASP-LLM01] [RULE: GDPR-ART33]
            self.audit.record("query", principal.principal_id, principal.tenant,
                              outcome="blocked", reasons=check.reasons,
                              question=redact(question[:500], self.detector))
            return Answer(answer=self._block_message(check.reasons), blocked=True,
                          blocked_reasons=check.reasons, requires_human_review=False,
                          label=transparency.label_output(self.generator.model_name, False))

        # 2) Pseudonymise the question (nothing stored) ----------------------
        safe_question, _ = ctx.pseudonymiser.pseudonymise(check.sanitized, None)

        # 3) Tenant-scoped retrieval -----------------------------------------
        # [RULE: OWASP-LLM08] Only this tenant's store is searched.
        hits = [(c, s) for c, s in ctx.store.search(safe_question, self.settings.top_k)
                if s >= self.settings.min_relevance]
        sources: list[PromptSource] = []
        citations: list[Citation] = []
        for chunk, score in hits:
            # Defence in depth: re-screen at query time.
            if guardrails.screen_context(chunk.text):
                continue
            label = f"S{len(sources) + 1}"
            doc = ctx.store.documents.get(chunk.doc_id)
            filename = doc.filename if doc else "unknown"
            sources.append(PromptSource(label, filename, chunk.location, chunk.text))
            citations.append(Citation(label, chunk.doc_id, filename, chunk.location,
                                      round(score, 4), chunk.text[:300]))

        # [RULE: GDPR-ART5-1C] No relevant context -> do not call the LLM at all.
        if not sources:
            answer = Answer(
                answer="The documents available to you do not contain enough information "
                       "to answer this question.",
                confidence=0.0, requires_human_review=False,
                label=transparency.label_output(self.generator.model_name, False))
            self.audit.record("query", principal.principal_id, principal.tenant,
                              outcome="no_context", question=redact(safe_question))
            return answer

        # 4) Generation --------------------------------------------------------
        try:
            result = self.generator.generate(safe_question, sources)
        except LLMUnavailableError as exc:
            # [RULE: SEC-ERROR-HANDLING] Fail closed with a generic message.
            self.audit.record("query", principal.principal_id, principal.tenant,
                              outcome="llm_error", error=str(exc))
            raise

        if result.refused:
            self.audit.record("query", principal.principal_id, principal.tenant,
                              outcome="model_refused", model=result.model)
            return Answer(answer="The request was declined by the model's safety policy.",
                          blocked=True, blocked_reasons=["model_refusal"],
                          requires_human_review=False,
                          label=transparency.label_output(result.model, False))

        # 5) Output guardrails -------------------------------------------------
        context_by_label = {s.label: s.text for s in sources}
        out = guardrails.check_answer(result.text, context_by_label, SYSTEM_CANARY,
                                      self.detector)
        if "system_prompt_leak" in out.reasons:
            # [RULE: OWASP-LLM07] Withhold the whole answer.
            self.audit.record("query", principal.principal_id, principal.tenant,
                              outcome="blocked_output", reasons=out.reasons)
            return Answer(answer="The answer was withheld by an output safety check.",
                          blocked=True, blocked_reasons=out.reasons,
                          requires_human_review=True,
                          label=transparency.label_output(result.model, True))

        # 6) Confidence & human oversight -------------------------------------
        confidence, review_reasons = self._assess(hits, out, check.flags, result.truncated)
        requires_review = bool(review_reasons)

        text = out.sanitized
        # 7) Optional re-identification (privileged) --------------------------
        if reidentify:
            # [RULE: SEC-AUTHZ] [RULE: GDPR-ART4-5] Only DPO-type roles may see
            # original values; every use is audited.
            self._authorise(principal, Permission.REIDENTIFY, "reidentify")
            text = ctx.pseudonymiser.reidentify(text)
            for citation in citations:
                citation.excerpt = ctx.pseudonymiser.reidentify(citation.excerpt)
            self.audit.record("reidentify", principal.principal_id, principal.tenant,
                              docs=sorted({c.doc_id for c in citations}))

        answer = Answer(
            answer=text,
            citations=[c for c in citations if c.label in out.flags.get("citations", [])]
            or citations,
            confidence=confidence,
            requires_human_review=requires_review,
            review_reasons=review_reasons,
            label=transparency.label_output(result.model, requires_review),
        )
        # [RULE: EUAIA-ART12] [RULE: PII-LOG-SCRUB] Trace record (no raw PII).
        self.audit.record("query", principal.principal_id, principal.tenant,
                          question=redact(safe_question), model=result.model,
                          docs=sorted({c.doc_id for c in answer.citations}),
                          confidence=confidence, review_reasons=review_reasons,
                          guardrail_flags={k: v for k, v in out.flags.items()
                                           if k != "citations"},
                          usage=result.usage)
        return answer

    def _assess(self, hits: list[tuple[ChunkRecord, float]], out: guardrails.GuardrailResult,
                query_flags: dict[str, object], truncated: bool) -> tuple[float, list[str]]:
        """Heuristic confidence score and reasons for human review.

        confidence = 0.4 * top retrieval score
                   + 0.3 * (answer has valid citations)
                   + 0.3 * (share of figures verified against sources)

        [RULE: EUAIA-ART14] [RULE: FIN-NUMERIC-INTEGRITY] [RULE: OWASP-LLM09]
        """
        reasons: list[str] = []
        retrieval = min(1.0, hits[0][1]) if hits else 0.0
        cited = out.flags.get("citations") or []
        citation_score = 1.0 if cited and "invalid_citations" not in out.reasons else 0.0
        unverified = out.flags.get("unverified_numbers") or []
        total_numbers = len(guardrails.extract_numbers(out.sanitized)) or 1
        numeric_score = 1.0 - min(1.0, len(unverified) / total_numbers)  # type: ignore[arg-type]
        confidence = round(0.4 * retrieval + 0.3 * citation_score + 0.3 * numeric_score, 3)

        if confidence < self.settings.review_confidence_threshold:
            reasons.append("low_confidence")
        if not cited:
            reasons.append("no_citations")
        if "invalid_citations" in out.reasons:
            reasons.append("invalid_citations")
        if unverified:
            reasons.append("unverified_figures")
        if query_flags.get("advice_requested"):
            reasons.append("advice_requested")  # [RULE: FIN-NO-ADVICE]
        if truncated:
            reasons.append("answer_truncated")
        return confidence, reasons

    @staticmethod
    def _block_message(reasons: list[str]) -> str:
        """User-facing explanation for a blocked query (no internals leaked)."""
        if "prohibited_ai_practice" in reasons:
            return ("This request falls under practices prohibited by the EU AI Act "
                    "(Art. 5) and cannot be processed.")
        if "high_risk_use_out_of_scope" in reasons:
            return ("This system is not designed to make or support decisions about "
                    "individuals such as credit scoring, lending, hiring or insurance. "
                    "Please involve a qualified human decision-maker.")
        if any(r.startswith("query_too_long") for r in reasons) or "empty_query" in reasons:
            return "The question is empty or too long."
        return "The request was blocked by a security policy."

    # ------------------------------------------------------ document admin
    def list_documents(self, principal: Principal) -> list[dict[str, Any]]:
        """List document metadata for the caller's tenant (no content)."""
        self._authorise(principal, Permission.LIST_DOCUMENTS, "list_documents")
        docs = self._ctx(principal.tenant).store.documents.values()
        return [{k: v for k, v in asdict(d).items() if k != "data_subject_tokens"} for d in docs]

    def delete_document(self, principal: Principal, doc_id: str) -> bool:
        """Hard-delete a document, its chunks and orphaned vault entries."""
        self._authorise(principal, Permission.DELETE_DOCUMENT, "delete_document")
        ctx = self._ctx(principal.tenant)
        deleted = ctx.store.delete_document(doc_id)
        released = ctx.vault.release_doc(doc_id) if deleted else 0
        self.audit.record("delete_document", principal.principal_id, principal.tenant,
                          outcome="success" if deleted else "not_found", doc_id=doc_id,
                          vault_entries_destroyed=released)
        return deleted

    def purge_expired(self, principal: Principal) -> list[str]:
        """Delete every document past its retention deadline.

        [RULE: GDPR-ART5-1E] Run on a schedule (cron / k8s CronJob).
        """
        self._authorise(principal, Permission.PURGE, "purge")
        ctx = self._ctx(principal.tenant)
        purged = []
        for doc_id in ctx.store.expired_documents():
            if ctx.store.delete_document(doc_id):
                ctx.vault.release_doc(doc_id)
                purged.append(doc_id)
        self.audit.record("purge_expired", principal.principal_id, principal.tenant,
                          purged=purged)
        return purged

    # ------------------------------------------------- data-subject rights
    def _subject_tokens(self, ctx: _TenantContext, identifier: str) -> list[str]:
        """Tokens that the given identifier would have been pseudonymised to."""
        spans = self.detector.detect(identifier)
        types = {s.pii_type for s in spans} or {"PERSON", "EMAIL", "PHONE", "ACCOUNT_NUMBER"}
        value = spans[0].value if len(spans) == 1 else identifier.strip()
        return [ctx.pseudonymiser.token_for(t, value) for t in sorted(types)]

    def erase_subject(self, principal: Principal, identifier: str) -> dict[str, Any]:
        """Right to erasure for one identifier (e-mail, IBAN, name...).

        The vault mapping is destroyed and every occurrence of the token in
        stored chunks is overwritten with ``[ERASED]``. Documents themselves
        (company financials) remain available without the personal data.

        [RULE: GDPR-ART17]
        """
        self._authorise(principal, Permission.ERASE_SUBJECT, "erase_subject")
        ctx = self._ctx(principal.tenant)
        chunks_changed = 0
        mappings = 0
        for token in self._subject_tokens(ctx, identifier):
            chunks_changed += ctx.store.replace_token(token, "[ERASED]")
            mappings += int(ctx.vault.forget_token(token))
        report = {"chunks_updated": chunks_changed, "vault_entries_destroyed": mappings}
        # Identifier itself is redacted in the audit log.
        self.audit.record("erase_subject", principal.principal_id, principal.tenant,
                          subject=redact(identifier, self.detector), **report)
        return report

    def export_subject(self, principal: Principal, identifier: str,
                       fmt: str = "json") -> str:
        """Right of access / portability: excerpts mentioning the identifier.

        [RULE: GDPR-ART15] [RULE: GDPR-ART20]
        """
        self._authorise(principal, Permission.EXPORT_SUBJECT, "export_subject")
        ctx = self._ctx(principal.tenant)
        tokens = self._subject_tokens(ctx, identifier)
        records = []
        for chunk in ctx.store.chunks:
            if any(t in chunk.text for t in tokens):
                doc = ctx.store.documents.get(chunk.doc_id)
                records.append({
                    "document": doc.filename if doc else chunk.doc_id,
                    "location": chunk.location,
                    "purpose": doc.purpose if doc else "",
                    "lawful_basis": doc.lawful_basis if doc else "",
                    "retained_until": doc.expires_at if doc else "",
                    "excerpt": ctx.pseudonymiser.reidentify(chunk.text),
                })
        self.audit.record("export_subject", principal.principal_id, principal.tenant,
                          subject=redact(identifier, self.detector), records=len(records))
        return gdpr.export_records(records, fmt)

    # ------------------------------------------------------------- audit
    def verify_audit(self, principal: Principal) -> dict[str, Any]:
        """Verify the HMAC chain of the audit log. [RULE: SEC-LOGGING]"""
        self._authorise(principal, Permission.VIEW_AUDIT, "verify_audit")
        ok, count, error = self.audit.verify()
        return {"valid": ok, "events": count, "error": error}
