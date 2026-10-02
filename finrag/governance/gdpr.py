"""
GDPR governance helpers: lawful basis, purposes, retention, RoPA and exports.

The pipeline calls these helpers; they hold no state of their own.

[RULE: GDPR-ART6]    Allowed lawful bases (Art. 6(1)(a)-(f)) - ingestion fails
                     without one.
[RULE: GDPR-ART7]    Consent-based ingestion must reference a consent record.
[RULE: GDPR-ART9]    Special-category data needs an Art. 9(2) condition.
[RULE: GDPR-ART5-1B] Purposes come from an allow-list (purpose limitation).
[RULE: GDPR-ART30]   Machine-readable record of processing activities.
[RULE: GDPR-ART13]   Privacy notice content served by the API.
[RULE: GDPR-ART20]   Exports in JSON (structured, machine-readable).
[RULE: SEC-CSV-INJECTION] CSV exports neutralise spreadsheet formulas.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from finrag.config import Settings


class LawfulBasis(str, Enum):
    """GDPR Art. 6(1) lawful bases."""

    CONSENT = "consent"  # 6(1)(a)
    CONTRACT = "contract"  # 6(1)(b)
    LEGAL_OBLIGATION = "legal_obligation"  # 6(1)(c)
    VITAL_INTERESTS = "vital_interests"  # 6(1)(d)
    PUBLIC_TASK = "public_task"  # 6(1)(e)
    LEGITIMATE_INTERESTS = "legitimate_interests"  # 6(1)(f)


class Purpose(str, Enum):
    """Allow-listed processing purposes for this system."""

    FINANCIAL_ANALYSIS = "financial_analysis"
    FINANCIAL_REPORTING = "financial_reporting"
    AUDIT_SUPPORT = "audit_support"
    REGULATORY_COMPLIANCE = "regulatory_compliance"


class Art9Condition(str, Enum):
    """GDPR Art. 9(2) conditions permitting special-category processing."""

    EXPLICIT_CONSENT = "explicit_consent"  # 9(2)(a)
    EMPLOYMENT_LAW = "employment_social_security_law"  # 9(2)(b)
    LEGAL_CLAIMS = "legal_claims"  # 9(2)(f)
    SUBSTANTIAL_PUBLIC_INTEREST = "substantial_public_interest"  # 9(2)(g)


class ComplianceError(ValueError):
    """Raised when a request would violate a data-protection rule."""


def validate_processing(
    lawful_basis: str,
    purpose: str,
    consent_reference: str | None,
    special_categories: list[str],
    special_category_condition: str | None,
) -> tuple[LawfulBasis, Purpose, Art9Condition | None]:
    """Check lawful basis, purpose and special-category conditions."""
    try:
        basis = LawfulBasis(lawful_basis)
    except ValueError as exc:
        # [RULE: GDPR-ART6] No valid basis -> no processing.
        raise ComplianceError(f"invalid lawful basis '{lawful_basis}'") from exc
    try:
        purp = Purpose(purpose)
    except ValueError as exc:
        # [RULE: GDPR-ART5-1B] Purpose limitation.
        raise ComplianceError(f"purpose '{purpose}' is not an approved purpose") from exc
    if basis is LawfulBasis.CONSENT and not consent_reference:
        # [RULE: GDPR-ART7] Consent must be demonstrable.
        raise ComplianceError("consent-based processing requires a consent_reference")
    condition: Art9Condition | None = None
    if special_categories:
        if not special_category_condition:
            # [RULE: GDPR-ART9] Prohibited by default.
            raise ComplianceError(
                "document appears to contain special-category data "
                f"({', '.join(special_categories)}); an Art. 9(2) condition is required")
        try:
            condition = Art9Condition(special_category_condition)
        except ValueError as exc:
            raise ComplianceError("invalid Art. 9(2) condition") from exc
    return basis, purp, condition


def retention_deadline(settings: Settings, retention_days: int | None) -> datetime:
    """Compute ``expires_at``; requested retention may not exceed policy max.

    [RULE: GDPR-ART5-1E] Storage limitation - every document expires.
    """
    days = retention_days or settings.default_retention_days
    if days <= 0 or days > 3650:
        raise ComplianceError("retention_days must be between 1 and 3650")
    return datetime.now(timezone.utc) + timedelta(days=days)


def records_of_processing(settings: Settings) -> dict[str, Any]:
    """Return the Art. 30 record of processing activities for this system."""
    # [RULE: GDPR-ART30] [RULE: GDPR-ART5-2]
    external = settings.llm_provider.value == "anthropic"
    return {
        "name": "FinRAG - question answering over financial documents",
        "purposes": [p.value for p in Purpose],
        "lawful_bases_supported": [b.value for b in LawfulBasis],
        "categories_of_data_subjects": [
            "employees, customers, suppliers or counterparties named in uploaded documents"],
        "categories_of_personal_data": [
            "contact details (email, phone)", "financial identifiers (IBAN, card, account no.)",
            "government identifiers (NINO, SSN, passport, tax id)", "names", "IP addresses"],
        "special_categories": "blocked unless an Art. 9(2) condition is recorded",
        "recipients": (["Anthropic PBC (LLM inference processor) - pseudonymised excerpts only"]
                       if external else ["none - processing is fully local"]),
        "international_transfers": (
            "Pseudonymised excerpts to LLM processor under the controller's DPA / SCCs"
            if external else "none"),
        "retention": {
            "documents_default_days": settings.default_retention_days,
            "audit_log_days": max(settings.audit_retention_days, 183),
        },
        "security_measures": [
            "keyed pseudonymisation before storage", "AES/Fernet encryption at rest with "
            "HKDF-separated keys", "RBAC with hashed API keys", "tamper-evident audit log",
            "prompt-injection and output guardrails", "rate limiting", "TLS in transit "
            "(terminated at the reverse proxy)"],
    }


def privacy_notice(settings: Settings) -> dict[str, Any]:
    """Information for data subjects / users (Art. 13) in machine-readable form."""
    # [RULE: GDPR-ART13] [RULE: GDPR-ART5-1A]
    ropa = records_of_processing(settings)
    return {
        "controller": "The organisation operating this FinRAG deployment",
        "purposes": ropa["purposes"],
        "recipients": ropa["recipients"],
        "retention": ropa["retention"],
        "rights": ["access (Art. 15)", "rectification (Art. 16)", "erasure (Art. 17)",
                   "restriction (Art. 18)", "portability (Art. 20)", "objection (Art. 21)",
                   "not to be subject to solely automated decisions (Art. 22)",
                   "complain to a supervisory authority (Art. 77)"],
        "automated_decision_making": "none - outputs are informational and reviewed by humans",
    }


def neutralise_csv_cell(value: Any) -> str:
    """Prefix values that a spreadsheet would interpret as formulas.

    [RULE: SEC-CSV-INJECTION] Cells starting with = + - @ TAB or CR are
    prefixed with a single quote so Excel/LibreOffice treat them as text.
    """
    text = "" if value is None else str(value)
    return f"'{text}" if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def export_records(records: list[dict[str, Any]], fmt: str = "json") -> str:
    """Serialise records for an Art. 15 / Art. 20 response."""
    if fmt == "json":
        # [RULE: GDPR-ART20] Structured, commonly used, machine-readable.
        return json.dumps(records, indent=2, sort_keys=True, default=str)
    if fmt == "csv":
        buffer = io.StringIO()
        fields = sorted({k for r in records for k in r})
        writer = csv.DictWriter(buffer, fieldnames=fields)
        writer.writeheader()
        for record in records:
            writer.writerow({k: neutralise_csv_cell(record.get(k)) for k in fields})
        return buffer.getvalue()
    raise ComplianceError("export format must be 'json' or 'csv'")
