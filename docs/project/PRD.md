# Product Requirements Document (PRD): FinRAG

| | |
|---|---|
| **Product** | FinRAG: question answering over financial documents |
| **Version** | 1.0 (as built); sections marked *Proposed* are not implemented |
| **Status** | Implemented in PR #1; this PRD records intent, scope and open questions |
| **Related** | [Architecture](Architecture.md) · [Security](Security.md) · [Testing](Testing.md) · [Design System](Design_System.md) · [Agents](Agents.md) |

> **Reading guide.** Requirements marked **Built** are implemented and tested.
> **Proposed** means the idea is documented but no code exists. Anything stated as a
> target or metric is a proposal to be agreed with stakeholders, not a measured result.

---

## 1. Problem

Finance, audit and compliance teams keep their facts in spreadsheets, ledgers, board
notes and reports. Finding one figure ("What was EBITDA in FY2024?") means opening
several files and checking which column and which period a number belongs to.

Generic chat assistants can answer such questions, but for financial documents they
bring three problems:

1. **Personal data leaves the organisation.** Documents contain names, IBANs, e-mail
   addresses and tax IDs. Sending them to a third-party model is a GDPR transfer.
2. **Wrong numbers look convincing.** A model can state a revenue figure that is not in
   any document, with no way to check it.
3. **Regulation applies.** The EU AI Act requires transparency and human oversight, and
   forbids some uses, such as credit scoring of individuals, without extra obligations.

## 2. Vision

> Ask a question about your financial documents and get an answer you can verify,
> without personal data leaving your control and without breaking GDPR or the EU AI Act.

## 3. Target users

Roles are defined in code (`finrag/security/access.py`, `ROLE_PERMISSIONS`).

| Persona | Role | Main goals |
|---|---|---|
| **Finance analyst** | `analyst` | Upload documents, ask questions, check figures against sources |
| **Business stakeholder** | `viewer` | Ask questions over documents an analyst has uploaded; cannot upload |
| **Data protection officer (DPO)** | `dpo` | Handle access, export and erasure requests, re-identify when legally needed, review the audit log |
| **Platform admin** | `admin` | List and delete documents, run retention purges, verify the audit log |
| **Developer / integrator** | API client | Call the HTTP API or CLI from other systems |

## 4. Goals and non-goals

### Goals

- G1. Answer questions about PDF, XLSX, CSV, TXT and Markdown financial documents, with a
  citation for every statement.
- G2. Keep raw personal data out of storage, logs and LLM requests.
- G3. Make GDPR obligations (lawful basis, purpose, retention, access, erasure) part of
  the normal workflow, not a manual afterthought.
- G4. Block uses the EU AI Act prohibits or classes as high-risk, and label every answer
  as AI-generated.
- G5. Let a reviewer trace any control to its code and any request to an audit record.
- G6. Run fully offline by default; use Claude only when explicitly enabled.

### Non-goals

- NG1. **Investment, tax, legal or credit advice.** Output is informational analysis.
- NG2. **Decisions about individuals** (credit scoring, lending, hiring, insurance
  pricing). These are blocked (EU AI Act Annex III; GDPR Art. 22).
- NG3. **OCR of scanned documents.** Text must already be extractable.
- NG4. **A hosted, multi-user SaaS front end.** The built-in web UI is a single-page app served by the same process, with API-key sign-in; there is no SSO, user management or billing.
- NG5. **Very large corpora.** The built-in index is designed for thousands of chunks per
  tenant (see [Architecture](Architecture.md)).
- NG6. **Replacing a DPIA or legal review.** FinRAG supplies technical controls; the
  deploying organisation still owns the organisational ones.

## 5. User stories

| ID | As a… | I want to… | So that… | Status |
|---|---|---|---|---|
| U1 | analyst | upload a workbook with a lawful basis and purpose | processing is documented from the start | Built |
| U2 | analyst | ask "What was net income in FY2024?" | I get the figure, its source and its period | Built |
| U3 | analyst | see which answers need human review and why | I know what to double-check | Built |
| U4 | viewer | ask questions without being able to change data | I can use the tool safely | Built |
| U5 | DPO | export everything mentioning a person | I can answer an access request | Built |
| U6 | DPO | erase one person's identifiers across all documents | I can honour an erasure request | Built |
| U7 | DPO | see original values behind a pseudonym, with an audit entry | I can handle legal requests | Built |
| U8 | admin | delete expired documents automatically | retention rules are enforced | Built (run `purge` on a schedule) |
| U9 | admin | verify that the audit log was not altered | I can trust it as evidence | Built |
| U10 | developer | call the API with an API key and get JSON | I can integrate FinRAG | Built |
| U11 | analyst | upload a scanned PDF | I do not have to OCR it first | Proposed |
| U12 | viewer | use a web page instead of the API | non-technical users can self-serve | Built (web UI at `/ui/`) |
| U13 | analyst | upload several files at once and see what happened to each | I can load a document set quickly and spot rejected files | Built |
| U14 | any user | see clearly whether an answer needs checking, and open the cited source in one click | I can verify figures without hunting | Built |

## 6. Functional requirements

Each requirement lists where it is implemented and tested. Rule IDs refer to
[`COMPLIANCE_MATRIX.md`](../COMPLIANCE_MATRIX.md).

| ID | Requirement | Where | Tests |
|---|---|---|---|
| FR1 | Accept PDF, XLSX, CSV, TXT, MD up to 25 MiB (configurable); reject other types, fake extensions, macros, zip bombs, encrypted PDFs | `finrag/ingestion/loaders.py` | `test_loaders.py` |
| FR2 | Keep spreadsheet meaning: each row stored with its column names, header repeated in every chunk | `finrag/ingestion/chunker.py` | `test_loaders.py::test_table_chunks_repeat_header` |
| FR3 | Replace PII with keyed tokens before storage; never store the raw file | `finrag/security/pii.py`, `finrag/pipeline.py` | `test_pii.py`, `test_pipeline.py::test_no_raw_pii_on_disk` |
| FR4 | Require lawful basis, approved purpose and expiry on every upload; block special-category data without an Art. 9(2) condition | `finrag/governance/gdpr.py` | `test_pipeline.py` |
| FR5 | Retrieve the most relevant chunks with a local hybrid (BM25 + hashed TF-IDF) index, per tenant | `finrag/retrieval/` | `test_pipeline.py` |
| FR6 | Generate answers with Claude (`claude-opus-5-5`) or the offline extractive generator; the model gets no tools | `finrag/generation/llm.py` | `test_llm.py` |
| FR7 | Cite sources as `[S#]`; verify numbers against sources; flag unverified figures for review | `finrag/security/guardrails.py`, `finrag/pipeline.py` | `test_guardrails.py`, `test_pipeline.py` |
| FR8 | Block prompt injection, prohibited practices and high-risk decisions; quarantine instruction-like document content | `finrag/security/guardrails.py` | `test_guardrails.py`, `test_pipeline.py` |
| FR9 | Label every answer as AI-generated and attach a disclosure and disclaimer; publish a model card | `finrag/governance/transparency.py`, `finrag/api.py` | `test_api.py` |
| FR10 | Provide export, erasure, document deletion and retention purge | `finrag/pipeline.py` | `test_pipeline.py` |
| FR11 | Log every operation to a tamper-evident audit log without raw PII | `finrag/security/audit.py` | `test_pipeline.py::test_audit_chain_and_scrubbing` |
| FR12 | Authenticate by API key, authorise by role, rate-limit per principal | `finrag/security/access.py`, `finrag/api.py` | `test_security_core.py`, `test_api.py` |
| FR13 | Provide a browser UI to upload files, ask questions, open citations and run role-permitted privacy tasks; render model output as text only; strict CSP | `finrag/web/`, `finrag/api.py` (`/ui`, `/v1/me`) | `test_web.py`, `test_ui_e2e.py` |

## 7. Non-functional requirements

| Area | Requirement | Status |
|---|---|---|
| **Privacy** | No raw PII at rest, in logs, or in LLM requests | Built |
| **Security** | Encryption at rest; deny-by-default access; fail closed in production | Built |
| **Compliance** | Every control tagged with a rule ID; CI fails on unknown tags or a stale matrix | Built |
| **Portability** | Runs offline on Python 3.10+; Docker image runs as non-root | Built |
| **Reliability** | Atomic writes; authenticated encryption detects tampering | Built |
| **Performance** | Exact search over all of a tenant's chunks | Built for thousands of chunks; no measured benchmark yet |
| **Observability** | Audit log only; no metrics or tracing | Proposed |
| **Scalability** | Multi-process / multi-node deployment | Proposed (stores are local files) |

## 8. Success metrics (Proposed)

These are targets to agree with stakeholders. They are **not** measured today.

| Metric | Proposed target | How to measure |
|---|---|---|
| Answers with at least one valid citation | ≥ 95 % | audit log: `citations` flag |
| Answers flagged `unverified_figures` | trend down over time | audit log: `unverified_numbers` |
| Seeded PII found in stored data after ingestion | 0 | scan `data/` in CI against a labelled test set |
| Time to complete an erasure request | under one working day | DPO runbook |
| Blocked prompt-injection attempts that reached the model | 0 | red-team suite (see Open questions) |

## 9. Release scope

| Release | Scope |
|---|---|
| **1.0 (this PR)** | Everything marked **Built** above |
| **1.1** | Web UI (this change): sign-in, upload, ask, citations, document library, privacy tools, About page; `scripts/demo.py` launcher |
| **Next (Proposed)** | NER-based PII detector plug-in; OCR for scanned PDFs; evaluation set for answer quality; structured metrics; streaming answers; SSO |
| **Later (Proposed)** | Self-hosted embedding model and vector database (see [Architecture](Architecture.md)); multi-node deployment; SSO |

## 10. Risks

| Risk | Impact | Mitigation | Residual |
|---|---|---|---|
| PII not detected (for example an unlabelled name in free text) | Personal data stored or sent to the LLM | Pattern detection with checksums; plug-in point for an NER model | Real: documented as a limitation |
| Prompt-injection detectors are heuristic | A crafted document or question may slip through | Structural defences too: fenced sources, no tools, canary, output checks | Real |
| Model invents a figure | Wrong number reaches a report | Citation and figure verification, human-review flag | Reduced, not removed |
| Users treat output as advice | Regulatory exposure | Disclaimer on every answer; advice-seeking questions flagged | Reduced |
| Master key lost | All stored data unreadable | Key held in a secret manager with backup (deployer's duty) | Operational |
| Misuse for individual decisions | EU AI Act high-risk obligations | Blocked in code and documented as excluded use | Reduced |

## 11. Open questions

1. Which organisation is the data controller, and who signs the DPA with the LLM provider?
2. Is `legitimate_interests` an acceptable default lawful basis, or should the choice be
   restricted by tenant policy?
3. What retention period fits each document type (default is 90 days)?
4. Is the built-in web UI enough for the first deployment, or is SSO or a separate front end needed?
5. What accuracy bar must answers meet, and who owns the evaluation set?
6. Do we need SSO instead of API keys?
