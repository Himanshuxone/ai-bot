# Go-to-Market: how to sell FinRAG

| | |
|---|---|
| **Product** | FinRAG: secure question answering over financial documents |
| **Status** | Strategy and plan. Everything here is a **hypothesis to test**, not a result |
| **Related** | [PRD](PRD.md) · [Security](Security.md) · [Architecture](Architecture.md) · [Deploy on Vercel](../DEPLOY_VERCEL.md) |

> **Honesty note.** No market sizes, prices, conversion rates or customer names appear
> here as facts, because none have been measured. Numbers are *starting assumptions* to
> validate in the first 90 days. The product claims below only use what the repository
> implements and tests.

---

## 1. What we are selling

**One sentence:** answers you can verify from your own financial documents, with personal
data masked before any AI sees it and an audit trail that stands up to a GDPR or EU AI Act
question.

The product is not "chat with a PDF". Many tools do that. The difference is the part
buyers in finance cannot easily build or accept without it:

| Buyer worry | What FinRAG does (built and tested) |
|---|---|
| "Our data goes to an AI vendor" | Offline by default; with Claude enabled only masked text is sent; demo mode never calls an external model |
| "The model invented a number" | Every answer carries `[S1]` citations; figures not found in sources are flagged and routed to human review |
| "Auditors will ask what happened" | Hash-chained audit log, record of processing (GDPR Art. 30), exportable subject data |
| "Who can see what?" | Roles (analyst, viewer, DPO, admin), strict tenant isolation, encrypted stores |
| "Is this allowed under the EU AI Act?" | AI disclosure on every answer, human-oversight flag, prohibited uses (for example credit scoring of individuals) blocked |

## 2. Positioning

**For** finance, audit and compliance teams in regulated European organisations **who**
need quick answers from spreadsheets and reports, **FinRAG is** a document Q&A tool
**that** keeps personal data under their control and makes every answer checkable.
**Unlike** general chat assistants, it is built around GDPR and EU AI Act obligations and
shows its sources.

**Tagline candidates (test with 5 prospects each):**

1. "Ask your financials. Check every answer."
2. "Document Q&A your DPO will sign off."
3. "The answer, and the line it came from."

**Do not claim:** certified, compliant by itself, accurate to a percentage, or "replaces
analysts". The product aids compliance; the deployer still owes a DPIA, a DPA and
training (see [COMPLIANCE](../COMPLIANCE.md) §6). Say so up front; it builds trust with
exactly the buyers we want.

## 3. Who buys (ideal customer profile)

Start narrow. A focused first segment beats a generic pitch.

| Priority | Segment | Why they care | Typical champion | Typical blocker |
|---|---|---|---|---|
| 1 | **Small audit and accounting firms** (EU/UK) handling client ledgers | Many client files, personal data inside, time pressure at close | Partner or head of audit | Fear of client data in public AI tools |
| 2 | **Finance teams in mid-size companies** (50–500 staff) | Board packs, budgets, month-end questions | FP&A lead or finance director | IT/DPO approval |
| 3 | **Fintechs and lenders** needing internal document search | Regulated, privacy-conscious, no big IT team | Head of compliance | EU AI Act scope worries |
| 4 | **Consultancies** doing due diligence | Many documents, tight deadlines, NDAs | Engagement manager | Client confidentiality |

Buying roles in a deal: **champion** (finance/audit lead), **economic buyer** (finance
director or partner), **gatekeepers** (DPO, IT security). The DPO is both the biggest
blocker and the best ally: the product's documentation is written for them.

**Avoid at first:** banks with long procurement cycles, consumer use, and any use that
decides on individuals (credit scoring, hiring): those are high-risk or prohibited under
the EU AI Act and are blocked in the product.

## 4. Packaging and pricing hypotheses

Pricing is a hypothesis; test it in discovery calls by asking "what would you pay to
remove this problem?" before showing numbers.

| Offer | For | Model | Notes |
|---|---|---|---|
| **Free live demo** | Everyone | Free, synthetic data, 2-hour sessions | Already deployable (see [Deploy](../DEPLOY_VERCEL.md)); the main lead magnet |
| **Pilot** | First 3–5 design partners | Fixed fee for 4–6 weeks, or free in exchange for a case study and weekly feedback | Their own (non-sensitive first) documents, one team, success criteria agreed up front |
| **Self-hosted licence** | Security-sensitive firms | Annual licence per team/organisation + support | Runs in their cloud/on-prem (`Dockerfile`); data never leaves |
| **Managed (single-tenant)** | Teams without IT capacity | Monthly subscription per seat band | Requires work not yet built: persistent encrypted storage, backups, SSO (see PRD "Next") |
| **Implementation services** | Larger accounts | Day-rate or fixed fee | DPIA support, integration, training, custom PII rules |

**Why not a cheap per-seat SaaS first:** the managed product's missing parts (persistent
storage, SSO, backups, evaluation set) cost real effort. Selling pilots and self-hosted
licences first funds and shapes that work.

## 5. Go-to-market motion

### Phase 0: Prepare (weeks 0–2)

- Stable public demo URL and a custom domain; a 2-minute screen recording of the demo
  flow (upload → ask → open citation → flagged figure).
- A one-page PDF: problem, how it works, controls table (section 1), limits, contact.
- A "trust pack" folder: [Security](Security.md), [COMPLIANCE](../COMPLIANCE.md),
  [COMPLIANCE_MATRIX](../COMPLIANCE_MATRIX.md), record of processing, DPIA template.
- Answers to the 10 questions in section 8.

### Phase 1: Design partners (weeks 2–8)

Goal: **3 organisations running a pilot on real documents.**

1. Build a list of 100 target firms in the first segment (audit/accounting practices,
   mid-size finance teams) using public directories and LinkedIn.
2. Warm routes first: your own network, former colleagues, local accountancy bodies and
   meet-ups. Cold outreach second.
3. Offer a 30-minute demo plus a 4-week pilot with clear success criteria (for example
   "time to find a figure", "number of answers with correct citation").
4. Review weekly. Capture exact quotes, objections and missing features.

### Phase 2: Repeatable sales (weeks 8–20)

- Turn the best pilot into a **case study** (with permission) and a reference call.
- Publish content aimed at the DPO and finance lead (section 6).
- Add a partner channel: accounting software resellers, GDPR/DPO consultants, audit
  firms who recommend tools to clients (revenue share).
- Introduce the managed offer once at least two pilots ask for it.

### Phase 3: Scale (after week 20)

- Self-serve sign-up with persistent storage, SSO, usage-based limits.
- Integrations: shared drives, accounting exports, e-mail attachments.
- Marketplace listings and events where finance technology buyers gather.

## 6. Marketing plan

**Message pillars**

1. *Verifiable* - "every answer shows its source line".
2. *Private* - "names, IBANs and e-mails are masked before any AI sees them".
3. *Accountable* - "audit trail, human review, EU AI Act transparency built in".

**Channels and content (low budget, high trust)**

| Channel | What to publish | Goal |
|---|---|---|
| Website with live demo | Hero with the demo button, controls table, security page | Convert visitors to demo sessions |
| LinkedIn (founder-led) | Weekly posts: "How we mask IBANs without breaking financial figures", demo clips, lessons from pilots | Reach finance/compliance leaders |
| Long-form articles | "Using AI on client ledgers without breaking GDPR", "What the EU AI Act means for document Q&A", "Why citations beat confidence scores" | Search traffic and credibility with DPOs |
| Webinars with a DPO or auditor guest | Live demo plus Q&A on controls | Qualified leads |
| Open-source posture | Keep the rule-tagged code readable; publish the compliance matrix | Technical trust; inbound from security reviewers |
| Communities | Accounting forums, finance Slack/Discord groups, local meet-ups | Peer recommendation |
| Paid search (later) | Only after messaging is proven; exact-match terms around "GDPR" + "document AI" | Predictable lead flow |

**Content rules:** show real limits (no OCR yet, heuristic PII detection). Buyers in
this segment distrust perfect claims.

## 7. Sales process

| Stage | Exit criterion | Typical asset |
|---|---|---|
| 1. Lead | Visited demo or replied | Demo link |
| 2. Discovery call (30 min) | Pain, volume of documents, who must approve | Discovery questions below |
| 3. Demo on their kind of document | Champion says "I want this for my team" | Synthetic file shaped like theirs |
| 4. Security/DPO review | DPO has the trust pack and no unresolved blocker | Trust pack, DPA/DPIA templates |
| 5. Pilot | Success criteria met | Weekly report |
| 6. Contract | Signed order form | Licence/subscription terms |

**Discovery questions:** Which documents do you search most often? How long does it take
to find a figure today? Do these contain personal data? Who must approve new tools that
touch it? Has anyone already tried a public AI tool, and what happened? What would make
this a clear yes or no after four weeks?

**Demo script (7 minutes):** (1) click *Try the demo*, three sample documents appear;
(2) ask "What was net income in FY2024?"; (3) open the citation; (4) show masked personal
data in the upload summary; (5) ask a question outside the documents, show the refusal /
review flag; (6) show the audit view and the AI disclosure; (7) state limits and the
deployment options.

## 8. Objections and honest answers

| Objection | Answer |
|---|---|
| "Is this GDPR compliant?" | It implements technical controls mapped to articles in [COMPLIANCE_MATRIX](../COMPLIANCE_MATRIX.md). Compliance also needs your DPIA, DPA and training; we provide templates and support |
| "Will you train on our data?" | The product does not train models. By default nothing leaves your environment; if you enable Claude, only masked excerpts are sent under your provider agreement |
| "What if it gets a number wrong?" | Figures not found in the sources are flagged for human review, and every answer cites its sources. It reduces the risk; it does not remove it, so a person stays in the loop |
| "Does it read scanned PDFs?" | Not yet (no OCR). It is on the roadmap; pilots can use text PDFs, spreadsheets and CSV |
| "How good is the PII detection?" | Pattern-based with checksums (IBANs, cards) and context rules; it can miss unlabelled names in free text. A name-recognition plug-in point exists |
| "Why not Copilot / ChatGPT?" | They are broader tools. FinRAG is narrower: masking before the model, citations, audit trail and EU AI Act controls out of the box, and a self-hosted option |
| "Is the public demo safe to use with real files?" | No. The demo is for synthetic data only; use a pilot environment for real documents |

## 9. Competitive landscape (qualitative)

Check each point with current research before publishing; products change fast.

| Alternative | Strength | Our angle |
|---|---|---|
| General chat assistants | Familiar, powerful | Data stays under control, citations, audit trail |
| Enterprise copilots from large vendors | Integrated with existing suites | Simpler, auditable, can run self-hosted, specialised for financial documents |
| Document-AI / intelligent document processing vendors | Strong extraction and OCR | Question answering with verification rather than form extraction |
| Building in-house | Full control | Months of security and compliance work already done and documented |
| Doing nothing (manual search) | No risk or cost | Time saved; fewer transcription errors |

## 10. Metrics

| Stage | Metric | Starting target (assumption) |
|---|---|---|
| Awareness | Demo sessions per week | grow week on week |
| Activation | Demo sessions that ask at least one question | ≥ 50 % |
| Interest | Visitors who book a call | 3–5 % of demo users |
| Pilots | Active design partners | 3 by week 8 |
| Pilot success | Pilots that meet their success criteria | ≥ 2 of 3 |
| Revenue | Paid conversions from pilots | ≥ 1 by week 20 |
| Product quality | Answers with a valid citation; flagged figures resolved | see [PRD §8](PRD.md) |
| Trust | Security questionnaires answered without product change | rising |

Instrument the demo with privacy-friendly, aggregate counters only (no document content,
no personal data). That keeps the product consistent with its own message.

## 11. Budget and effort (indicative)

- **Founder time** is the main cost: about half of each week on conversations in Phase 1.
- **Cash:** domain, hosting, a design pass for the website, optional webinar tooling and a
  small outreach tool. Keep paid advertising at zero until messaging is proven.
- **Product work that sales will demand** (from [PRD "Next"](PRD.md)): OCR, NER-based PII
  detection, persistent encrypted storage and backups, SSO, an evaluation set for answer
  quality. Prioritise by what design partners ask for.

## 12. Risks

| Risk | Mitigation |
|---|---|
| Over-claiming compliance | Use "supports" and "helps", publish limits, never say "certified" |
| Long security reviews | Ship the trust pack early; involve the DPO in demos |
| Model or provider changes | Offline mode and a provider switch already exist |
| Answer errors in a pilot | Citations, review flag, weekly review, clear success criteria |
| Competitors bundle similar features | Compete on auditability, self-hosting and focus on regulated European finance |
| Founder bandwidth | Stay in one segment; say no to custom work that does not generalise |

## 13. First 30 days checklist

- [ ] Custom domain and stable demo URL; 2-minute demo video recorded
- [ ] One-page overview and trust pack assembled
- [ ] Target list of 100 firms in segment 1; 20 warm contacts identified
- [ ] 10 discovery calls booked; notes template ready
- [ ] First LinkedIn post and first article drafted
- [ ] Pilot agreement template (scope, data handling, success criteria, fee or case-study terms) reviewed by a lawyer
- [ ] Demo instrumentation (aggregate counters) decided
