# Security: FinRAG

Security requirements, controls and operating procedures. The root
[`SECURITY.md`](../../SECURITY.md) is the short public policy (how to report a
vulnerability and a hardening checklist); this document is the detailed reference. The
article-by-article compliance explanation is in [`../COMPLIANCE.md`](../COMPLIANCE.md) and
the rule-to-code map in [`../COMPLIANCE_MATRIX.md`](../COMPLIANCE_MATRIX.md).

Related: [PRD](PRD.md) · [Architecture](Architecture.md) · [Testing](Testing.md) · [Agents](Agents.md)

> **Honest limits.** PII detection and prompt-injection detection are pattern-based and
> can miss things. FinRAG has not had an independent penetration test. Technical controls
> do not replace a DPIA, contracts or staff training (see §9).

---

## 1. Assets and trust boundaries

| Asset | Why it matters | Where it lives |
|---|---|---|
| Financial documents | Confidential business data | Pseudonymised chunks in `store.enc` |
| Personal data (names, IBAN, e-mail, tax IDs) | GDPR-protected | Originals only in `vault.enc` |
| Master key | Decrypts everything | Environment / secret manager |
| API keys | Grant access | Only SHA-256 hashes on disk |
| Audit log | Evidence | `audit/audit.log` |
| LLM provider key | Cost and data path | `ANTHROPIC_API_KEY` (read by the SDK) |

| Boundary | Untrusted input | Main controls |
|---|---|---|
| Client → API | Headers, JSON, multipart files | API key, RBAC, size caps, validation, rate limit |
| File → parser | File bytes | Allow-list, magic bytes, caps, zip/macro checks |
| Document text → prompt | Chunk content | Quarantine, fenced sources, "data not instructions" |
| Host → LLM provider | Excerpts | Pseudonymised only, no tools, offline by default |
| LLM → user | Model output | Canary, PII redaction, citation and figure checks |
| Process → disk | Everything persisted | Fernet encryption, atomic 0600 writes |
| Browser page → API | Any script running in the page, model output shown on screen | Same-origin CSP (no inline code, no third-party hosts, no `eval`), text-only rendering, key in `sessionStorage` |

## 2. Threat model (STRIDE)

| Threat | Example | Control | Tests |
|---|---|---|---|
| **S**poofing | Guessed or stolen API key | Hashed keys, constant-time compare, key shown once | `test_security_core.py::test_api_key_auth` |
| **T**ampering | Edited `store.enc` or audit line | Fernet authentication; HMAC chain; decrypt failures audited | `test_pipeline.py::test_tampered_store_*`, `test_audit_chain_and_scrubbing` |
| **R**epudiation | "I never deleted that" | Every action audited with principal and tenant | `test_pipeline.py` |
| **I**nformation disclosure | PII in logs, answers or prompts; cross-tenant read | Pseudonymisation, redaction, tenant isolation | `test_no_raw_pii_on_disk`, `test_tenant_isolation` |
| **D**enial of service | Huge upload, zip bomb, query flood | Size/page/row caps, zip-ratio check, rate limit, `max_tokens` | `test_loaders.py`, `test_security_core.py::test_rate_limiter` |
| **E**levation of privilege | Viewer ingests; analyst re-identifies | Deny-by-default RBAC | `test_pipeline.py::test_rbac`, `test_api.py` |
| **XSS via model or document text** | A malicious document makes the model emit `<script>` or an HTML payload that the page then runs | DOM built with `textContent`, no HTML-parsing sinks, strict CSP, answer markup stripped server-side | `test_web.py::test_no_unsafe_patterns_in_js`, `test_ui_csp_is_strict_and_api_csp_unchanged` |

LLM-specific threats follow the OWASP Top 10 for LLM Applications (2025); see §4.

## 3. Security requirements

| ID | Requirement | Rule IDs | Implemented in |
|---|---|---|---|
| SR1 | Every request is authenticated; credentials are stored only as hashes | `SEC-AUTHN` | `security/access.py`, `api.py` |
| SR2 | Each operation requires an explicit permission; unknown roles grant nothing | `SEC-AUTHZ` | `security/access.py` |
| SR3 | The tenant is taken from the credential and validated | `OWASP-LLM08` | `retrieval/store.py::validate_tenant` |
| SR4 | Uploads are allow-listed, size-capped, type-checked and inspected | `SEC-FILE-UPLOAD` | `ingestion/loaders.py` |
| SR5 | Spreadsheet formulas are never evaluated; exported CSV cells are neutralised | `SEC-CSV-INJECTION` | `loaders.py` (`data_only=True`), `governance/gdpr.py` |
| SR6 | Stored data uses authenticated encryption with purpose-separated keys | `SEC-CRYPTO`, `GDPR-ART32` | `security/crypto.py` |
| SR7 | No raw PII at rest, in logs, or in LLM input | `PII-*`, `GDPR-ART5-1C` | `security/pii.py`, `pipeline.py` |
| SR8 | Prompt injection is detected in questions and documents | `OWASP-LLM01` | `security/guardrails.py` |
| SR9 | The model has no tools and no secrets in its prompt | `OWASP-LLM06`, `OWASP-LLM07` | `generation/` |
| SR10 | Answers are validated before release | `OWASP-LLM05`, `OWASP-LLM09` | `guardrails.check_answer` |
| SR11 | Operations are logged tamper-evidently without raw PII | `SEC-LOGGING`, `EUAIA-ART12` | `security/audit.py` |
| SR12 | Errors fail closed and reveal nothing internal | `SEC-ERROR-HANDLING` | `api.py`, `crypto.py` |
| SR13 | Responses carry security headers | `SEC-HEADERS` | `api.py` |
| SR14 | Production refuses to start without keys | `SEC-CRYPTO`, `SEC-AUTHN` | `crypto.py`, `api.py` |
| SR15 | The web UI never renders untrusted text as HTML, and runs under a same-origin CSP with no inline code | `OWASP-LLM05`, `SEC-HEADERS` | `finrag/web/js/dom.js`, `api.py` middleware |
| SR16 | The UI keeps the API key only in `sessionStorage`, never in URLs, cookies or `localStorage`, and clears conversations on sign-out | `SEC-SECRETS`, `GDPR-ART5-1E` | `finrag/web/js/api.js`, `views/ask.js` |

## 4. OWASP Top 10 for LLM Applications (2025)

| Risk | Status | Control |
|---|---|---|
| LLM01 Prompt injection | Mitigated (heuristic + structural) | Query checks, chunk quarantine, fenced `<source>`, tag neutralisation, static system prompt |
| LLM02 Sensitive information disclosure | Mitigated | Pseudonymisation, output PII redaction, re-identification only for `dpo` and audited |
| LLM03 Supply chain | Partly | `pip-audit` in CI; dependencies not yet hash-pinned |
| LLM04 Data and model poisoning | Mitigated | Strict loaders, quarantine of instruction-like content |
| LLM05 Improper output handling | Mitigated | Plain text only, script/iframe tags stripped, citations validated |
| LLM06 Excessive agency | Mitigated | No tools passed to the model |
| LLM07 System prompt leakage | Mitigated | No secrets in prompt; random canary; leaking answers withheld |
| LLM08 Vector and embedding weaknesses | Mitigated | Per-tenant store, index and keys; no shared index |
| LLM09 Misinformation | Reduced | Grounding, citations, figure verification, review flag |
| LLM10 Unbounded consumption | Mitigated | Caps, rate limits, `max_tokens`, SDK timeouts |

## 5. Authentication and authorisation

**Authentication.** `X-API-Key` header. The server hashes the presented key (SHA-256) and
compares it in constant time against each entry, with no early exit. Keys over 256
characters are rejected. Create keys with `python -m finrag.cli hash-key`; store only the
hash.

**Authorisation.** Roles map to permissions in `ROLE_PERMISSIONS`. Roles can be combined,
but keep `dpo` separate from `analyst` where possible (segregation of duties).

| Permission | viewer | analyst | dpo | admin |
|---|:-:|:-:|:-:|:-:|
| query | ✔ | ✔ | | |
| ingest | | ✔ | | |
| list documents | | ✔ | ✔ | ✔ |
| delete document | | ✔ | ✔ | ✔ |
| export / erase data subject | | | ✔ | |
| re-identify | | | ✔ | |
| view audit / RoPA | | | ✔ | ✔ |
| purge expired | | | ✔ | ✔ |

Denied attempts are written to the audit log as `outcome: denied`.

**Web UI session.** There are no cookies, so cross-site request forgery does not apply: the browser never attaches the key on its own. The key sits in `sessionStorage`, which any script in the page could read; the CSP and the ban on HTML sinks are what prevent such a script from running. Sign-out clears the key and the in-memory conversation.

**Known gap.** The API-key file is read once at start-up. Revoking a key requires a
restart. There is no key expiry, per-key rate-limit state across processes, or SSO.

## 6. Cryptography and key management

| Item | Choice |
|---|---|
| Master key | 32 random bytes, urlsafe base64, from `FINRAG_MASTER_KEY` |
| Key derivation | HKDF-SHA256 with purpose `info` (`store`, `vault`, `pseudonym`, `audit`), then per-tenant HMAC |
| Encryption | Fernet (AES-128-CBC with HMAC-SHA256, authenticated) |
| Pseudonym tokens | `HMAC-SHA256(tenant key, "TYPE\|normalised value")`, first 10 hex chars |
| Audit chain | `HMAC-SHA256(audit key, previous MAC \| event)` |
| Randomness | `os.urandom`, `secrets` |
| File writes | Temp file, `fsync`, atomic replace, mode `0600`; data and tenant directories `0700` |

Rules:

- Development without a key uses an **ephemeral** key and logs a warning. Production
  fails to start.
- Never log, print or commit keys. `Settings.master_key` is a `SecretStr`.
- **Rotation** is an offline job: decrypt with the old key ring, re-encrypt with the new
  one. Pseudonym tokens change when the pseudonym key changes, so rotate it only with a
  full re-ingest. A tooling script for this does not exist yet.
- **Losing the master key makes all data unreadable.** Back it up in a secret manager.
- Token length is 40 bits; for very large tenants, accept that collisions are possible
  and consider lengthening it.

## 7. Data protection controls

| Concern | Control |
|---|---|
| Lawful basis, purpose, retention | Required on every upload; stored with the document |
| Special-category data | Detected; blocked without an Art. 9(2) condition |
| Access / portability | `export_subject` (JSON or formula-safe CSV) |
| Erasure | `erase_subject` (vault entry destroyed, tokens overwritten); `delete_document` (chunks and orphan vault entries removed) |
| Storage limitation | `expires_at` on every document; `purge_expired` |
| Minimisation | Raw files discarded; duplicates not re-stored; LLM skipped when no context |
| Transfers | Offline default; with Claude only top-k pseudonymised excerpts |

Limitation: erasure removes data from FinRAG's stores. It does not reach backups,
the LLM provider's own retention, or copies users made. The deployer must cover those.

## 8. Secure development

| Practice | How |
|---|---|
| Secrets | `.gitignore` excludes `.env`, `keys.json`, `data/`, `*.enc`, `audit.log`; use `.env.example` |
| Dependencies | `requirements.txt` ranges; `pip-audit` in CI. *Proposed:* pin with hashes (`pip-compile --generate-hashes`) |
| Static checks | `ruff` in CI |
| Tests | Security behaviours are tested (see [Testing](Testing.md)); a change to a control needs a test |
| Compliance tags | Unknown tags or an out-of-date matrix fail CI |
| Reviews | Run `/security-review` on changes that touch `security/`, `ingestion/`, `generation/` or `api.py` |
| Least privilege | CI token is `contents: read`; container runs as non-root |

Rules for contributors (and agents) when editing security code:

1. Never log or return raw PII, document text, keys or full prompts.
2. Never give the model a tool, and never put a secret in the system prompt.
3. Never widen a role's permissions silently; update the table in §5 and the tests.
4. Tag a new control with `[RULE: ID]` and register the ID if it is new.
5. Fail closed: when unsure, deny and audit.

### Public demo mode

`FINRAG_DEMO_MODE=true` (used for the Vercel demo) adds an unauthenticated
`POST /v1/demo/session` that creates a new isolated tenant and returns a signed,
expiring token. Controls: one tenant per visitor (`OWASP-LLM08`), HMAC-signed tokens with
expiry compared in constant time (`SEC-AUTHN`), signing key derived from the master key
(`SEC-CRYPTO`), forced offline generator so no content leaves the host (`GDPR-ART44`),
session creation rate limit and a cap on stored workspaces (`OWASP-LLM10`). Residual
risks: tokens are bearer secrets valid until expiry; per-instance counters mean the rate
limit is not global; the demo has no persistent store and must not be used with real data.

## 9. Operations

**Hardening checklist** (production):

- [ ] `FINRAG_ENVIRONMENT=production`
- [ ] `FINRAG_MASTER_KEY` from a secret manager; backed up
- [ ] `FINRAG_API_KEYS_FILE` set; file readable only by the service user
- [ ] TLS terminated at a reverse proxy; app on a private network
- [ ] Data volume encrypted at disk level as well
- [ ] Daily `purge` job; audit-log archival after the retention period
- [ ] DPA/SCCs signed before `FINRAG_LLM_PROVIDER=anthropic`
- [ ] One instance per data directory
- [ ] Alerting on audit outcomes: `denied`, `blocked`, `rejected`, `decryption_failed`, `rate_limited`

**Detection signals** in `audit.log`: repeated `denied` from one principal, bursts of
`blocked` (injection attempts), `decryption_failed` (tampering or wrong key), `reidentify`
events outside expected hours, and a failing `GET /v1/audit/verify`.

## 10. Incident response

| Step | Action |
|---|---|
| 1. Contain | Rotate or remove the affected API key; stop the instance if tampering is suspected |
| 2. Preserve | Copy `audit.log` and the data directory read-only; run `audit-verify` |
| 3. Assess | Which tenants, documents and identifiers were involved? Use audit `docs` and `tenant` fields |
| 4. Notify | If personal data was breached, the controller must notify the supervisory authority within **72 hours** (GDPR Art. 33), and affected individuals where risk is high (Art. 34) |
| 5. Recover | Restore from backup; rotate the master key if it may be exposed (offline re-encryption) |
| 6. Learn | Add a regression test; update this document |

## 11. Reporting a vulnerability

Do not open a public issue. Follow the contact process in the root
[`SECURITY.md`](../../SECURITY.md).

## 12. Open security work (Proposed)

- Independent penetration test and a prompt-injection red-team suite.
- Short-lived session tokens instead of keeping the long-lived API key in the browser tab; SSO.
- Subresource and header checks for the UI in CI (for example a CSP evaluator).
- NER-based PII detection for higher recall.
- Key revocation without restart; key expiry; SSO.
- Hash-pinned dependencies and SBOM generation.
- Key-rotation tooling.
- Shared rate-limit state for multi-instance deployments.
