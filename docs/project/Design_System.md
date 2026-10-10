# Design System: FinRAG

> **Scope note.** FinRAG has a **web UI** (`finrag/web/`, served at `/ui/`) in addition to
> the CLI and HTTP API. This document defines what the product says and how it looks:
> voice, the answer contract, accessibility rules, the design tokens and the components that
> are implemented in `finrag/web/styles.css` and `finrag/web/js/`. Sections 6 and 7 describe
> **built** tokens and components; anything still planned is marked **Proposed**.

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

## 6. Design tokens (Built)

Defined once in `finrag/web/styles.css` as CSS custom properties. Components use only these
tokens, never raw colours. Light and dark themes are designed together and follow the
operating-system setting unless the user picks one with the header toggle (remembered in
`localStorage`; the only thing the UI stores there).

| Token group | Values |
|---|---|
| Surfaces | `--bg`, `--surface`, `--surface-2`, `--scrim` |
| Text | `--text`, `--muted`, `--on-primary` |
| Borders | `--border` (decorative), `--border-strong` (input and control boundaries, 3:1) |
| Brand / links | `--primary`, `--primary-weak` |
| Status | `--success`, `--warning`, `--danger`, each with a `-bg` pair; plus `--primary` for info |
| Type | system font stack (no downloaded fonts); scale 12 / 14 / 16 / 18 / 24 / 32 px; body 16 px, line height 1.5; tabular numerals for figures |
| Space | 4, 8, 12, 16, 24, 32, 48 px |
| Shape and depth | radius 6 and 10 px; two shadow levels |
| Motion | 180 ms, `cubic-bezier(0.2, 0.8, 0.2, 1)`; everything disabled under `prefers-reduced-motion` |
| Layers | nav 20, top bar 30, toast 100 |

**Contrast was measured, not estimated.** Every text pair meets WCAG AA (4.5:1) and every
control boundary 3:1 in both themes, checked with a script when the tokens were chosen.
When you change a colour, recheck the pairs it touches.

Design dials used: variance 3 (centred, conventional), motion 3 (small feedback only),
density 6 (data-friendly but readable).

## 7. Layout and navigation (Built)

| Aspect | Rule |
|---|---|
| Structure | Top bar (brand, mode badge, user, theme, sign out) plus primary navigation plus one content area, max width 860 px (1040 px for Documents) |
| Desktop (1024 px and up) | Left sidebar navigation |
| Phone and tablet | Bottom navigation, at most 4 items, each with icon and text label; safe-area padding |
| Items | Ask, Documents, Privacy, About; each shown only if the role permits it (viewers see Ask and About) |
| Deep links | URL hashes `#/ask`, `#/documents`, `#/privacy`, `#/about`; Back works as expected; opening a screen the role cannot use falls back to the first allowed one |
| Focus | After each route change focus moves to the page heading; a skip link is the first tab stop |
| Primary action | One per screen: **Ask** on the Ask screen, **Upload** on Documents; secondary actions are outlined |
| Destructive actions | Always behind a confirmation dialog with Cancel focused by default; Esc cancels |

## 8. Components (Built)

| Component | Behaviour |
|---|---|
| **Question box** | Visible label (screen-reader), auto-growing, character counter against the server limit, Enter sends, Shift+Enter adds a line, inline error, loading state on the button |
| **Example questions** | Chips shown on an empty conversation; they fill the box and do not send |
| **Answer card** | Status banner, answer text with citation buttons and privacy placeholders as code chips, collapsible sources, Copy answer (adds the AI label to the copied text), AI-generated badge, disclosure and disclaimer always visible |
| **Status banners** | Each pairs colour with an icon and text: success "Looks consistent", warning "Check this answer before using it" with plain-language reasons, danger "Request not processed" |
| **Citation chip** | `[S1]` becomes a button that opens Sources, scrolls to and highlights the excerpt; unknown labels show a warning style and are not clickable |
| **Upload form** | Drop zone that is also a real file input (keyboard accessible); multi-file queue with per-file status; required lawful basis and purpose with helper text; optional retention days; consent reference shown only for consent; special-category condition inside a disclosure that opens automatically when the server asks for it; errors under the field and the first invalid field focused |
| **Document library** | Table on wide screens, stacked cards on phones; per-document privacy summary and warnings; Delete with confirmation; empty, loading and error states |
| **Privacy tools** | Export (view and download), erase with confirmation, retention purge, audit verification, processing record |
| **Toasts** | Polite live region, dismissible, auto-dismiss after 5 s, never steal focus |
| **Mode badge** | "Offline mode" (nothing leaves the server) or "AI: model name"; the tooltip explains the data flow |

States every component handles: loading (skeleton, no blocking spinner over 1 s),
empty (with a next action), error (with a retry), and disabled (reduced opacity and a
not-allowed cursor).

Plain-language labels for review reasons (shown in the warning banner):

| `review_reasons` value | Shown as |
|---|---|
| `low_confidence` | "The match with your documents is weak." |
| `no_citations` | "The answer does not cite any document." |
| `invalid_citations` | "The answer refers to a source that was not provided." |
| `unverified_figures` | "Some numbers could not be found in the cited documents." |
| `advice_requested` | "This looks like a request for advice. FinRAG gives information only." |
| `answer_truncated` | "The answer was cut short." |

## 9. Security rules for UI code

Design and security meet here, so these are part of the system:

1. Build the DOM with `createElement` and `textContent` (see `js/dom.js`). Never use
   `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`, `eval`, or
   `new Function`. A test (`tests/test_web.py`) fails the build if they appear.
2. No inline scripts, inline `style` attributes, inline event handlers, or third-party
   hosts or fonts. The Content-Security-Policy for `/ui` allows only same-origin files.
3. The API key lives in `sessionStorage` only (cleared when the tab closes), is sent in the
   `X-API-Key` header, and never appears in a URL. Conversations are kept in memory only and
   cleared on sign-out.
4. The UI hides actions a role cannot use, but the server is the authority.

## 10. Still Proposed

- Automated accessibility audit (for example axe) and visual regression tests.
- Streaming answers; per-document question scope.
- Localisation beyond British English.
- A tablet-specific layout (tablets currently use the phone or desktop layout by width).
