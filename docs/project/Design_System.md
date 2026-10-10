# Design System: FinRAG

> **Scope note.** FinRAG 1.0 has **no graphical user interface**. Its user-facing
> surfaces are the **CLI**, the **HTTP API responses** and the **diagrams and documents**.
> This design system therefore defines (1) what the product says and how it says it,
> (2) the contract any UI must honour when it renders an answer, and (3) *Proposed*
> design tokens for a future web UI. Sections 1 to 5 describe what exists; sections 6 and
> 7 are proposals.

Related: [PRD](PRD.md) · [Architecture](Architecture.md) · [Security](Security.md)

---

## 1. Design principles

| Principle | Meaning | Example in the product |
|---|---|---|
| **Verifiable over fluent** | Every claim points to a source the reader can open | `[S1]` citations; excerpts returned with each answer |
| **Honest about uncertainty** | Say when the documents do not contain the answer, and when a human should check | "The documents available to you do not contain enough information…"; `requires_human_review` |
| **Disclose the machine** | Users always know they are talking to AI | `ai_disclosure` text, `label.ai_generated`, `X-AI-Generated` header |
| **Privacy is visible, not hidden** | Masked data looks masked, never silently altered | Tokens such as `<EMAIL_9f2c1a7b3e>`; `[REDACTED:IBAN]`; `[ERASED]` |
| **Explain refusals without leaking internals** | Say what is not allowed and what to do instead; never reveal rules or stack traces | "Please involve a qualified human decision-maker." |
| **Calm and neutral** | No urgency, hype or persuasion (EU AI Act Art. 5) | Plain statements, no emotional framing |

## 2. Voice and tone

- **Plain, precise, short.** Quote figures exactly as in the source, with unit, currency
  and period.
- **No personalised advice.** Use "the documents show…", never "you should buy/sell…".
- **Refusals** state the category (security policy, prohibited practice, out-of-scope
  decision) and the next step. They never name the pattern that matched.
- **Errors** are generic to the client and specific in the audit log
  (`SEC-ERROR-HANDLING`).
- **Spelling:** British English in documentation and messages (for example "pseudonymise",
  "authorise").

## 3. Content patterns (implemented)

### 3.1 Answer object

Every answer, whether from the API or the CLI, has the same shape
(`finrag/pipeline.py`, `Answer`):

| Field | Purpose | Display rule for any UI |
|---|---|---|
| `answer` | Text with `[S#]` citations | Render as plain text. Never as HTML |
| `citations[]` | `label`, `filename`, `location`, `score`, `excerpt` | Make each `[S#]` in the text link to its citation |
| `confidence` | 0 to 1 heuristic | Show as a coarse level, not a percentage (see 5.2) |
| `requires_human_review` + `review_reasons[]` | Oversight flag and why | Show prominently before the answer is used |
| `blocked` + `blocked_reasons[]` | Request refused | Show the explanatory message in `answer`; do not show reasons to end users |
| `ai_disclosure` | AI notice | Always visible with the answer |
| `disclaimer` | Not-advice notice | Always visible with the answer |
| `label` | Machine-readable AI-output label | Preserve when copying or exporting the answer |

### 3.2 Privacy placeholders

| Placeholder | Meaning | Where it appears |
|---|---|---|
| `<TYPE_xxxxxxxxxx>` (for example `<EMAIL_9f2c1a7b3e>`) | Pseudonym token for stored/answered text | Answers, citations, stored chunks |
| `[REDACTED:TYPE]` | Irreversible removal | Audit log, answers where unexpected PII appeared |
| `[ERASED]` | Identifier erased on request (GDPR Art. 17) | Stored chunks after erasure |

A UI must show these literally. It must not try to guess the underlying value.

### 3.3 Status and messages

| Situation | HTTP | User-facing text (source) |
|---|---|---|
| Missing/invalid API key | 401 | `unauthorised` (`finrag/api.py`) |
| Missing permission | 403 | `forbidden` |
| Rate limit | 429 + `Retry-After: 60` | `rate limit exceeded` |
| Bad file or non-compliant upload | 422 | Specific reason, for example `macro-enabled workbooks are not accepted` |
| Question blocked | 200 with `blocked: true` | Explanation from `FinRAGPipeline._block_message` |
| LLM unavailable | 503 | `answer service temporarily unavailable` |
| Anything unexpected | 500 | `internal error` |

### 3.4 CLI output

Order: answer, `Sources:` list, one `Confidence … Human review required …` line, then the
AI disclosure and disclaimer. Errors print `error: <message>` to stderr and exit with
code `2`.

## 4. Diagram conventions

Used in `docs/ARCHITECTURE.md` and `docs/RAG_FLOW.md` (Mermaid).

| Element | Convention |
|---|---|
| Tool | Mermaid in Markdown so diagrams render on GitHub and stay in version control |
| Flowchart nodes | Action in plain text; the function and file in *italics* on a new line, for example `pipeline.py · ask` |
| Decisions | Diamond with a yes/no (or named) label on every branch |
| Terminals | Circles for start and end; parallelograms for user-visible output |
| Data stores | Cylinders (`store.enc`, `vault.enc`) |
| Sequence diagrams | One participant per file/class, labelled `file.py` then `Class.function` |
| Validation | Render each diagram (for example with `mermaid-cli`) before committing |

## 5. Accessibility and inclusion (requirements for any UI)

1. **Do not rely on colour alone** for status. Pair colour with an icon and text.
2. **Contrast:** at least 4.5:1 for body text, 3:1 for large text and UI components
   (WCAG 2.2 AA).
3. **Keyboard:** every action reachable without a mouse; visible focus ring.
4. **Screen readers:** citations are real links with accessible names such as
   "Source 1: sample_financials.csv, table"; the review banner uses a live region.
5. **Numbers:** keep the formatting from the source (for example `1,452,000`); never
   round for display.
6. **Plain language:** target a reading level suitable for non-specialists, with
   finance terms explained once.

### Showing confidence

`confidence` is a routing heuristic, not a probability (see
[Architecture](Architecture.md)). Show three levels:

| Level | Rule | Treatment |
|---|---|---|
| Needs review | `requires_human_review` is true | Warning banner above the answer with `review_reasons` in plain words |
| Looks consistent | not flagged, `confidence` ≥ threshold | Neutral note "Figures matched your documents" |
| No answer | no citations | Message only, no styling of success |

## 6. Design tokens (Proposed, for a future web UI)

Not implemented. Values are starting points to be validated for contrast.

```css
:root {
  /* Colour: semantic, not decorative */
  --color-bg: #ffffff;
  --color-surface: #f6f7f9;
  --color-text: #1b1f24;
  --color-text-muted: #4b5563;
  --color-border: #d0d5dd;
  --color-link: #0b5cad;
  --color-info: #0b5cad;     /* AI disclosure */
  --color-warning: #8a4b00;  /* needs human review */
  --color-danger: #b42318;   /* blocked / error */
  --color-success: #05603a;  /* figures matched */

  /* Typography */
  --font-sans: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --font-mono: ui-monospace, "SF Mono", Menlo, Consolas, monospace; /* tokens, numbers */
  --text-sm: 0.875rem; --text-md: 1rem; --text-lg: 1.25rem;

  /* Space and shape (4 px base) */
  --space-1: 4px; --space-2: 8px; --space-3: 12px; --space-4: 16px; --space-6: 24px;
  --radius-md: 8px;
}
@media (prefers-color-scheme: dark) {
  :root {
    --color-bg: #0f1216; --color-surface: #181c22; --color-text: #e8eaed;
    --color-text-muted: #aab1bb; --color-border: #2f3640; --color-link: #6cb2ff;
    --color-warning: #ffb454; --color-danger: #ff8a80; --color-success: #5fd39a;
  }
}
```

## 7. Components (Proposed)

| Component | Content | States |
|---|---|---|
| **Question box** | Multiline input, character counter (limit `max_query_chars`, default 2000) | empty, typing, too long, sending |
| **Answer card** | Answer text, citation chips, confidence level, disclosure, disclaimer | loading, answered, flagged for review, blocked, no answer, error |
| **Citation chip / panel** | `[S1]` chip opens the excerpt with file and location | collapsed, expanded |
| **Review banner** | Why a human should check, in plain words | hidden, shown |
| **Upload form** | File picker, lawful-basis select, purpose select, retention days, optional consent reference | idle, validating, rejected (with reason), accepted |
| **Document list** | Filename, type, expiry date, PII counts, quarantined chunks | empty, populated, deleting |
| **DPO console** | Export, erase, purge, audit verify | idle, running, done, failed |

Plain-language labels for review reasons:

| `review_reasons` value | Show as |
|---|---|
| `low_confidence` | "The match with your documents is weak." |
| `no_citations` | "The answer does not cite any document." |
| `invalid_citations` | "The answer refers to a source that was not provided." |
| `unverified_figures` | "Some numbers could not be found in the cited documents." |
| `advice_requested` | "This looks like a request for advice. FinRAG gives information only." |
| `answer_truncated` | "The answer was cut short." |
