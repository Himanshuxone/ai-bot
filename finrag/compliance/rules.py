"""
Compliance rule registry.

Every security / privacy / AI-governance control in this code base is tagged
in a comment with ``[RULE: <ID>]``. This module is the single source of truth
for what each ID means, so that:

* a reviewer can read any tagged line and look the rule up here;
* ``scripts/compliance_report.py`` can scan the code and generate
  ``docs/COMPLIANCE_MATRIX.md`` (rule -> file:line where it is implemented);
* ``tests/test_compliance_tags.py`` fails the build if code references a rule
  that is not registered here (prevents typos and "made-up" compliance claims).

Rule families
-------------
GDPR-*    Regulation (EU) 2016/679 (General Data Protection Regulation)
EUAIA-*   Regulation (EU) 2024/1689 (Artificial Intelligence Act)
OWASP-*   OWASP Top 10 for LLM Applications (2025 edition)
SEC-*     General application-security controls (OWASP ASVS-aligned)
PII-*     Internal PII-handling standard implemented by this project
FIN-*     Financial-domain safeguards

[RULE: GDPR-ART5-2]  Accountability - being able to *demonstrate* compliance.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    """A single compliance requirement that code can reference."""

    rule_id: str
    framework: str
    title: str
    summary: str


# The registry. Keep IDs stable: they are referenced from code comments and docs.
_RULES: tuple[Rule, ...] = (
    # ------------------------------------------------------------------ GDPR
    Rule("GDPR-ART4-5", "GDPR", "Pseudonymisation",
         "Personal data processed so it can no longer be attributed to a data subject "
         "without additional information kept separately and secured."),
    Rule("GDPR-ART5-1A", "GDPR", "Lawfulness, fairness and transparency",
         "Personal data processed lawfully, fairly and transparently."),
    Rule("GDPR-ART5-1B", "GDPR", "Purpose limitation",
         "Collected for specified, explicit and legitimate purposes; not further processed "
         "incompatibly with those purposes."),
    Rule("GDPR-ART5-1C", "GDPR", "Data minimisation",
         "Adequate, relevant and limited to what is necessary for the purpose."),
    Rule("GDPR-ART5-1D", "GDPR", "Accuracy",
         "Accurate and, where necessary, kept up to date."),
    Rule("GDPR-ART5-1E", "GDPR", "Storage limitation",
         "Kept no longer than necessary for the purposes of processing."),
    Rule("GDPR-ART5-1F", "GDPR", "Integrity and confidentiality",
         "Appropriate security incl. protection against unauthorised processing, loss, "
         "destruction or damage."),
    Rule("GDPR-ART5-2", "GDPR", "Accountability",
         "Controller is responsible for, and able to demonstrate, compliance."),
    Rule("GDPR-ART6", "GDPR", "Lawful basis",
         "Processing only lawful if at least one Art. 6(1) basis applies."),
    Rule("GDPR-ART7", "GDPR", "Conditions for consent",
         "Where consent is the basis, it must be demonstrable and withdrawable."),
    Rule("GDPR-ART9", "GDPR", "Special categories of personal data",
         "Health, biometric, religious, political, sexual-orientation etc. data are "
         "prohibited by default."),
    Rule("GDPR-ART13", "GDPR", "Information to be provided",
         "Data subjects must be told purposes, retention, rights, recipients."),
    Rule("GDPR-ART15", "GDPR", "Right of access",
         "Data subject may obtain confirmation and a copy of their personal data."),
    Rule("GDPR-ART17", "GDPR", "Right to erasure",
         "Data subject may obtain erasure of their personal data without undue delay."),
    Rule("GDPR-ART20", "GDPR", "Right to data portability",
         "Data provided in a structured, commonly used, machine-readable format."),
    Rule("GDPR-ART22", "GDPR", "Automated individual decision-making",
         "No decisions with legal/similarly significant effect based solely on "
         "automated processing."),
    Rule("GDPR-ART25", "GDPR", "Data protection by design and by default",
         "Privacy-protective technical measures and defaults built in."),
    Rule("GDPR-ART30", "GDPR", "Records of processing activities",
         "Maintain a record of processing activities (RoPA)."),
    Rule("GDPR-ART32", "GDPR", "Security of processing",
         "Encryption, pseudonymisation, confidentiality, resilience, regular testing."),
    Rule("GDPR-ART33", "GDPR", "Breach notification",
         "Detect and record personal-data breaches so the controller can notify within 72h."),
    Rule("GDPR-ART44", "GDPR", "International transfers",
         "Transfers to third countries / processors only under Chapter V safeguards; "
         "minimise what is transferred."),
    # -------------------------------------------------------- EU AI Act
    Rule("EUAIA-ART4", "EU AI Act", "AI literacy",
         "Deployers ensure staff have sufficient AI literacy (documentation, guidance)."),
    Rule("EUAIA-ART5", "EU AI Act", "Prohibited AI practices",
         "No manipulative techniques, social scoring, exploitation of vulnerabilities, "
         "emotion recognition at work, etc."),
    Rule("EUAIA-ART6", "EU AI Act", "High-risk classification (Annex III)",
         "Creditworthiness/credit scoring of natural persons is high-risk (Annex III 5(b)); "
         "system must stay within its non-high-risk intended purpose."),
    Rule("EUAIA-ART9", "EU AI Act", "Risk management",
         "Identify, analyse and mitigate foreseeable risks throughout the lifecycle."),
    Rule("EUAIA-ART10", "EU AI Act", "Data and data governance",
         "Input data relevant, representative, examined for errors and bias; provenance kept."),
    Rule("EUAIA-ART12", "EU AI Act", "Record-keeping",
         "Automatic logging of events over the system lifetime for traceability."),
    Rule("EUAIA-ART13", "EU AI Act", "Transparency and provision of information",
         "Instructions for use: intended purpose, accuracy, limitations, human oversight."),
    Rule("EUAIA-ART14", "EU AI Act", "Human oversight",
         "Humans can understand, monitor, override and intervene; outputs flagged when "
         "uncertain."),
    Rule("EUAIA-ART15", "EU AI Act", "Accuracy, robustness and cybersecurity",
         "Appropriate accuracy, resilience to errors and to attacks (e.g. prompt injection, "
         "data poisoning)."),
    Rule("EUAIA-ART26", "EU AI Act", "Obligations of deployers",
         "Use per instructions, monitor operation, keep logs (>= 6 months), inform users."),
    Rule("EUAIA-ART50", "EU AI Act", "Transparency obligations",
         "Users informed they interact with AI; AI-generated content marked in a "
         "machine-readable way."),
    # ------------------------------------------------- OWASP LLM Top 10 2025
    Rule("OWASP-LLM01", "OWASP LLM Top 10", "Prompt injection",
         "Direct and indirect (document-borne) prompt injection."),
    Rule("OWASP-LLM02", "OWASP LLM Top 10", "Sensitive information disclosure",
         "Leakage of PII, secrets or confidential data via prompts or outputs."),
    Rule("OWASP-LLM04", "OWASP LLM Top 10", "Data and model poisoning",
         "Malicious or malformed documents corrupting the knowledge base."),
    Rule("OWASP-LLM05", "OWASP LLM Top 10", "Improper output handling",
         "LLM output must be validated/sanitised before being used downstream."),
    Rule("OWASP-LLM06", "OWASP LLM Top 10", "Excessive agency",
         "LLM is given no tools/permissions beyond answering from supplied context."),
    Rule("OWASP-LLM07", "OWASP LLM Top 10", "System prompt leakage",
         "System prompt contains no secrets and leakage is detected."),
    Rule("OWASP-LLM08", "OWASP LLM Top 10", "Vector and embedding weaknesses",
         "Tenant isolation and access control in the vector store; no cross-tenant retrieval."),
    Rule("OWASP-LLM09", "OWASP LLM Top 10", "Misinformation",
         "Grounding, citations and verification of factual (numeric) claims."),
    Rule("OWASP-LLM10", "OWASP LLM Top 10", "Unbounded consumption",
         "Rate limits, size limits and token caps against DoS / cost abuse."),
    # ------------------------------------------------------- AppSec
    Rule("SEC-AUTHN", "AppSec", "Authentication",
         "Every request is authenticated; credentials stored only as hashes; constant-time "
         "comparison."),
    Rule("SEC-AUTHZ", "AppSec", "Authorisation (RBAC, least privilege)",
         "Each operation requires an explicit permission; deny by default."),
    Rule("SEC-INPUT-VALIDATION", "AppSec", "Input validation",
         "Validate type, size, structure and encoding of all untrusted input."),
    Rule("SEC-FILE-UPLOAD", "AppSec", "Safe file handling",
         "Magic-byte checks, size caps, decompression-bomb and path-traversal protection."),
    Rule("SEC-CSV-INJECTION", "AppSec", "Formula / CSV injection",
         "Neutralise spreadsheet formulas in exported data."),
    Rule("SEC-CRYPTO", "AppSec", "Cryptography",
         "Authenticated encryption (AES-128-CBC+HMAC via Fernet), HKDF key separation, "
         "keys from environment/secret manager only."),
    Rule("SEC-SECRETS", "AppSec", "Secrets management",
         "No secrets in code or logs; loaded from environment / secret manager."),
    Rule("SEC-LOGGING", "AppSec", "Secure logging",
         "Logs are tamper-evident and contain no raw PII or secrets."),
    Rule("SEC-ERROR-HANDLING", "AppSec", "Error handling",
         "Fail closed; never leak stack traces or internals to clients."),
    Rule("SEC-HEADERS", "AppSec", "HTTP security headers",
         "HSTS, nosniff, frame-deny, no-store, restrictive CSP."),
    # ------------------------------------------------------- PII standard
    Rule("PII-DETECT", "PII Standard", "PII detection",
         "Detect direct identifiers (email, phone, IBAN, card, national IDs, tax IDs, IP)."),
    Rule("PII-REDACT", "PII Standard", "PII redaction",
         "Replace detected PII before storage, logging or transfer to third parties."),
    Rule("PII-PSEUDONYMISE", "PII Standard", "Keyed pseudonymisation",
         "Deterministic HMAC tokens; re-identification only via encrypted vault + privilege."),
    Rule("PII-LOG-SCRUB", "PII Standard", "Log scrubbing",
         "PII is never written to logs or audit trail in clear text."),
    # ------------------------------------------------------- Financial
    Rule("FIN-NO-ADVICE", "Financial", "No personalised investment advice",
         "Outputs are informational analysis of supplied documents, not regulated advice."),
    Rule("FIN-NUMERIC-INTEGRITY", "Financial", "Numeric integrity",
         "Figures in answers must be traceable to source documents; unverified figures are "
         "flagged for human review."),
)

#: Public lookup table ``rule_id -> Rule``.
RULES: dict[str, Rule] = {r.rule_id: r for r in _RULES}


def get_rule(rule_id: str) -> Rule:
    """Return a registered rule or raise ``KeyError`` (used by tests and the report)."""
    return RULES[rule_id]
