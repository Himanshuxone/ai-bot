# Compliance Guide: PII, Security, GDPR and the EU AI Act

This guide explains **which rules FinRAG applies, why, and where**. Every control in the
code is tagged with a comment like:

```python
# [RULE: GDPR-ART17] When a document is erased, the identifiers that only
# it referenced are destroyed too, so its pseudonyms become irreversible.
```

* Rule definitions: [`finrag/compliance/rules.py`](../finrag/compliance/rules.py)
* Generated rule → `file:line` table: [`COMPLIANCE_MATRIX.md`](COMPLIANCE_MATRIX.md)
* CI fails if a tag is not registered, a registered rule has no implementation, or the
  matrix is out of date (`tests/test_compliance_tags.py`).

To find every place a rule is implemented:

```bash
grep -rn "RULE: GDPR-ART17" finrag/
```

> **Disclaimer.** FinRAG gives you technical controls. Compliance also depends on
> organisational measures (DPIA, contracts, staff training, incident response) that only
> the deploying organisation can put in place. Section 6 lists them. This document is not
> legal advice.

---

## 1. GDPR (Regulation (EU) 2016/679)

| Article | Requirement | FinRAG implementation | Main code |
|---|---|---|---|
| Art. 4(5) | Pseudonymisation | HMAC-SHA256 tokens (`<EMAIL_9f2c1a7b3e>`); mapping kept in a separately encrypted vault | `security/pii.py` (`Pseudonymiser`, `PseudonymVault`) |
| Art. 5(1)(a) | Lawful, fair, transparent | Privacy notice endpoint, AI disclosure on every answer | `governance/gdpr.py::privacy_notice`, `api.py` `/v1/transparency` |
| Art. 5(1)(b) | Purpose limitation | Purpose allow-list required at ingestion and stored per document | `governance/gdpr.py::Purpose`, `validate_processing` |
| Art. 5(1)(c) | Data minimisation | PII replaced before storage; raw files discarded; duplicate uploads not re-stored; LLM not called when no context; only top-k excerpts sent | `pipeline.py::ingest/ask`, `retrieval/store.py` |
| Art. 5(1)(d) | Accuracy | Header-repeating table chunks; figure verification against sources | `ingestion/chunker.py`, `security/guardrails.py::check_answer` |
| Art. 5(1)(e) | Storage limitation | Mandatory `expires_at` per document (default 90 days, max 10 years); `purge` command / endpoint | `governance/gdpr.py::retention_deadline`, `pipeline.py::purge_expired` |
| Art. 5(1)(f) | Integrity & confidentiality | Authenticated encryption, atomic owner-only writes | `security/crypto.py` |
| Art. 5(2) | Accountability | Tamper-evident audit log, compliance tags, generated matrix | `security/audit.py`, `scripts/compliance_report.py` |
| Art. 6 | Lawful basis | Ingestion fails without a valid Art. 6(1) basis; stored per document | `governance/gdpr.py::LawfulBasis` |
| Art. 7 | Consent | `consent` basis requires a `consent_reference` | `governance/gdpr.py::validate_processing` |
| Art. 9 | Special categories | Keyword detection on raw text; ingestion blocked without an Art. 9(2) condition | `security/pii.py::special_categories`, `governance/gdpr.py::Art9Condition` |
| Art. 13 | Information to data subjects | Machine-readable privacy notice | `governance/gdpr.py::privacy_notice` |
| Art. 15 | Right of access | Export of every excerpt mentioning an identifier, with purpose, basis and retention | `pipeline.py::export_subject` |
| Art. 17 | Right to erasure | Identifier-level erasure (vault entry destroyed, tokens overwritten with `[ERASED]`); document-level hard delete with orphan vault clean-up | `pipeline.py::erase_subject/delete_document`, `security/pii.py::release_doc` |
| Art. 20 | Portability | JSON (and formula-safe CSV) exports | `governance/gdpr.py::export_records` |
| Art. 22 | Automated decisions | Decision-type requests about individuals blocked; prompt forbids decisions; human-review flag | `security/guardrails.py::_HIGH_RISK_RE`, `generation/prompts.py` |
| Art. 25 | Data protection by design & default | Offline LLM default, local index, redaction by default, finite retention | `config.py`, `retrieval/index.py` |
| Art. 30 | Records of processing | `/v1/gdpr/ropa` returns the RoPA, reflecting the configured provider | `governance/gdpr.py::records_of_processing` |
| Art. 32 | Security of processing | Encryption, pseudonymisation, RBAC, testing (CI) | `security/*` |
| Art. 33 | Breach detection | Security events (access denied, blocked queries, rejected uploads, decrypt failures) are audited | `pipeline.py::_authorise`, `security/crypto.py::DecryptionError` |
| Art. 44 | International transfers | Nothing leaves the host in offline mode; with Claude only pseudonymised excerpts are sent; local embeddings | `generation/llm.py`, `retrieval/index.py` |

### What PII is detected

| Type | Method | False-positive guard |
|---|---|---|
| E-mail | regex | — |
| IBAN | regex | ISO 7064 mod-97 checksum |
| Payment card | regex | Luhn checksum, 13–19 digits |
| UK National Insurance no. | regex with valid prefix letters | — |
| US SSN | `AAA-GG-SSSS` with invalid ranges excluded | requires dashes |
| Phone | `+` international prefix, or after "tel/phone/mobile" | plain numbers never match |
| IPv4 | regex | octet range check |
| Account no., sort code, passport, tax ID, date of birth | only after a label ("Account no:", "Sort code", "DOB", …) | context required |
| Person name | after honorific (Mr/Ms/Dr…) or label (Name:, Customer:, Prepared by:) | context required |

Financial figures such as `1,452,000`, dates like `12-03-2024` or ratios are deliberately
**not** treated as PII (see `tests/test_pii.py::test_financial_figures_are_not_pii`).

Pattern-based detection cannot catch everything (for example a bare name in free text).
For higher recall, plug in an NER detector via `PIIDetector(extra_detectors=[...])`.

### Data-subject request runbook

| Request | CLI | API |
|---|---|---|
| Access (Art. 15) / portability (Art. 20) | `finrag --roles dpo export jane@example.com --format json` | `POST /v1/gdpr/export` |
| Erasure (Art. 17), one identifier | `finrag --roles dpo erase jane@example.com` | `POST /v1/gdpr/erasure` |
| Erasure, whole document | `finrag delete <doc_id>` | `DELETE /v1/documents/{id}` |
| Retention enforcement | `finrag --roles dpo purge` (schedule daily) | `POST /v1/admin/purge` |
| Record of processing | — | `GET /v1/gdpr/ropa` |

All of these are audited, and the identifier itself is redacted in the audit log.

---

## 2. EU AI Act (Regulation (EU) 2024/1689)

### Risk classification

FinRAG's **intended purpose** is question answering and figure look-up over an
organisation's own financial documents. Under the deployer's assessment:

* It is **not** a prohibited practice (Art. 5): social scoring, manipulation,
  exploitation of vulnerabilities and emotion inference requests are refused
  (`prohibited_ai_practice`).
* It is **not** used for Annex III high-risk purposes. In particular, assessing the
  creditworthiness of natural persons (Annex III 5(b)), life/health insurance pricing
  (5(c)) and employment decisions (4) are **out of scope and blocked**
  (`high_risk_use_out_of_scope`). If an organisation wants to use it for such purposes it
  must first carry out the full high-risk conformity process.
* It interacts with people and generates text, so the **Art. 50 transparency
  obligations** apply.

FinRAG voluntarily applies several high-risk-style controls (logging, human oversight,
accuracy measures, robustness) as good practice.

| Article | Requirement | FinRAG implementation | Main code |
|---|---|---|---|
| Art. 4 | AI literacy | Model card with user guidance; this documentation | `governance/transparency.py::model_card` |
| Art. 5 | Prohibited practices | Prohibited requests blocked with explanation | `security/guardrails.py::_PROHIBITED_RE` |
| Art. 6 / Annex III | High-risk classification | Intended purpose and excluded uses documented; high-risk requests blocked | `governance/transparency.py`, `security/guardrails.py::_HIGH_RISK_RE` |
| Art. 9 | Risk management | Identified risks (injection, poisoning, leakage, hallucinated figures, misuse) each have a control, applied centrally in the pipeline | `pipeline.py`, `security/guardrails.py` |
| Art. 10 | Data governance | Input validation, provenance (file/page/sheet/row) on every chunk, quarantine of suspicious content | `ingestion/*` |
| Art. 12 | Record-keeping | Automatic event logging of every ingest, query, re-identification, deletion | `security/audit.py` |
| Art. 13 | Transparency to deployers | Model card: purpose, limitations, accuracy measures, oversight | `/v1/transparency` |
| Art. 14 | Human oversight | `requires_human_review` + `review_reasons` on every answer; citations to check sources | `pipeline.py::_assess` |
| Art. 15 | Accuracy, robustness, cybersecurity | Citation and figure checks, injection defences, refusal handling, fail-closed errors, dependency audit in CI | `security/guardrails.py`, `generation/llm.py`, `.github/workflows/ci.yml` |
| Art. 26 | Deployer obligations | Audit retention ≥ 6 months enforced in code (`max(setting, 183)`) | `security/audit.py::expired_before` |
| Art. 50 | Transparency obligations | AI disclosure text, `X-AI-Generated` header, machine-readable `label.ai_generated=true` on every answer | `governance/transparency.py::label_output`, `api.py` |

---

## 3. PII handling standard

| Rule | Meaning | Where |
|---|---|---|
| `PII-DETECT` | Detect direct identifiers with validated patterns | `security/pii.py::PIIDetector` |
| `PII-PSEUDONYMISE` | Replace with deterministic keyed tokens before storage; re-identification only for the `reidentify` permission, always audited | `security/pii.py::Pseudonymiser`, `pipeline.py::ask` |
| `PII-REDACT` | Irreversible `[REDACTED:TYPE]` for logs and leaked output | `security/pii.py::redact`, `security/guardrails.py::check_answer` |
| `PII-LOG-SCRUB` | Nothing written to the audit log without redaction (tokens too) | `security/audit.py::_scrub` |

Questions are pseudonymised with the same tenant key **without** storing anything, so
"What do we owe jane@example.com?" retrieves the right chunks while the e-mail is never
stored or sent to the LLM.

---

## 4. Security guardrails

### OWASP Top 10 for LLM Applications (2025)

| Risk | Control |
|---|---|
| LLM01 Prompt injection | Pattern + obfuscation detection on questions; indirect-injection screening of chunks (quarantine at ingest and query time); fenced `<source>` blocks with tag neutralisation; system rule that sources are data |
| LLM02 Sensitive info disclosure | Pseudonymisation before the LLM; output PII redaction; RBAC on re-identification |
| LLM04 Data / model poisoning | Strict file validation; quarantine of instruction-like content |
| LLM05 Improper output handling | Output treated as plain text, script/iframe tags stripped, citations validated |
| LLM06 Excessive agency | No tools or function calling given to the model |
| LLM07 System prompt leakage | No secrets in the prompt; random canary; leaking answers withheld |
| LLM08 Vector & embedding weaknesses | Per-tenant stores, indexes and keys; tenant taken from the credential, validated against a strict pattern |
| LLM09 Misinformation | Grounding, mandatory citations, figure cross-check, confidence score, human-review flag |
| LLM10 Unbounded consumption | Upload/page/row/query caps, zip-bomb guard, rate limiting, `max_tokens`, SDK timeouts |

### Application security

| Rule | Control |
|---|---|
| `SEC-AUTHN` | SHA-256-hashed API keys, constant-time comparison, no early exit |
| `SEC-AUTHZ` | Deny-by-default RBAC (`viewer`, `analyst`, `dpo`, `admin`) |
| `SEC-INPUT-VALIDATION` | NFKC normalisation, invisible/control characters stripped, pydantic bounds |
| `SEC-FILE-UPLOAD` | Allow-list, magic bytes, size caps, macro/external-link/zip-bomb rejection, filename sanitising |
| `SEC-CSV-INJECTION` | Formula prefixes neutralised in CSV exports |
| `SEC-CRYPTO` | Fernet (AES-CBC + HMAC), HKDF key separation, ≥ 256-bit master key |
| `SEC-SECRETS` | Env / secret manager only, `SecretStr`, `.gitignore`, never baked into the image |
| `SEC-LOGGING` | HMAC-chained audit log with `verify` command |
| `SEC-ERROR-HANDLING` | Fail closed; generic error bodies; production refuses to start without keys |
| `SEC-HEADERS` | HSTS, nosniff, DENY framing, no-store, CSP `default-src 'none'` |

### Roles and permissions

| Permission | viewer | analyst | dpo | admin |
|---|:-:|:-:|:-:|:-:|
| query | ✔ | ✔ | | |
| ingest | | ✔ | | |
| list / delete documents | | ✔ | ✔ | ✔ |
| erase / export data subject | | | ✔ | |
| re-identify pseudonyms | | | ✔ | |
| view / verify audit, RoPA | | | ✔ | ✔ |
| purge expired | | | ✔ | ✔ |

Roles combine (e.g. `["analyst", "dpo"]`), but keeping them separate is recommended
(segregation of duties).

---

## 5. Financial-domain safeguards

| Rule | Control |
|---|---|
| `FIN-NO-ADVICE` | Prompt forbids personalised investment/tax/legal advice; advice-seeking questions flagged for review; disclaimer on every answer |
| `FIN-NUMERIC-INTEGRITY` | Every number in the answer is normalised (`1,452,000` = `1452000.00`, `(3,400)` = `-3400`) and checked against the cited sources; unverified figures force human review |

---

## 6. Organisational measures the deployer must add

FinRAG cannot do these for you:

1. **DPIA** (GDPR Art. 35) before processing documents with personal data at scale.
2. **Data Processing Agreement / SCCs** with Anthropic (or any LLM provider) before
   setting `FINRAG_LLM_PROVIDER=anthropic`, and check the provider's data-retention terms.
3. **Key management:** store `FINRAG_MASTER_KEY` in a KMS / secret manager, restrict access,
   back it up securely (losing it makes all data unreadable, which is equivalent to erasure).
4. **TLS** at the reverse proxy; network policies so only the proxy reaches the app.
5. **Retention schedule:** run `purge` daily (cron / Kubernetes CronJob); archive audit logs
   older than the retention period to WORM storage.
6. **Incident response:** monitor the audit log for `denied`, `blocked`, `rejected` and
   decryption failures; notify the supervisory authority within 72 h of a personal-data
   breach (Art. 33).
7. **AI literacy:** train users on the model card's limitations and on reviewing flagged
   answers (EU AI Act Art. 4).
8. **Periodic testing:** penetration tests and red-teaming of prompt-injection defences;
   keep `pip-audit` in CI.
