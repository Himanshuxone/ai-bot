# Agents Guide: FinRAG

Instructions for AI coding agents (and humans who want the short version) working in this
repository. Read this first, then the document linked for the area you are changing.

| If you are changing… | Read |
|---|---|
| Anything | this file, [Code Style](CODE_STYLE.md), [Testing](Testing.md) |
| Security, PII, guardrails, API | [Security](Security.md) |
| Structure, retrieval, storage | [Architecture](Architecture.md), [`../RAG_FLOW.md`](../RAG_FLOW.md) |
| Behaviour users see | [Design System](Design_System.md), [PRD](PRD.md) |
| Compliance claims | [`../COMPLIANCE.md`](../COMPLIANCE.md), [`../COMPLIANCE_MATRIX.md`](../COMPLIANCE_MATRIX.md) |

> **Note on this file's name.** Some agent tools look for `AGENTS.md` (or `CLAUDE.md`) in
> the repository root. If your tool needs that, add a root file that points here rather
> than duplicating the content.

---

## 1. What this project is

FinRAG is a Python retrieval-augmented generation (RAG) service that answers questions
about financial documents (PDF, XLSX, CSV, TXT, MD). It is built around **PII
protection, security guardrails, GDPR and EU AI Act compliance**. These are the product,
not extras: a change that weakens them is a regression even if every test passes.

Shape of the code:

```
finrag/
  pipeline.py      # the single entry point (ingest, ask, erase, export, purge)
  api.py  cli.py   # interfaces; call only the pipeline
  web/             # browser UI (index.html, styles.css, js/); a client of the HTTP API
  config.py        # typed settings (FINRAG_* env vars)
  security/        # crypto, pii, guardrails, access, audit
  ingestion/       # loaders (safe parsing), chunker
  retrieval/       # encrypted tenant store, local hybrid index
  generation/      # prompts, Claude + offline generators
  governance/      # gdpr, transparency
  compliance/      # rule registry
tests/  docs/  scripts/  samples/
```

## 2. Setup and commands

```bash
pip install -r requirements-dev.txt

pytest -q                                       # run tests (97; offline; browser tests skip without Chromium)
ruff check finrag tests scripts                 # lint
python scripts/compliance_report.py             # regenerate docs/COMPLIANCE_MATRIX.md
python scripts/compliance_report.py --check     # verify it is current (CI does this)

python scripts/demo.py                           # run the web UI locally with demo users (dev only)
python -m finrag.cli keygen                     # new master key
python -m finrag.cli --help                     # CLI
uvicorn finrag.api:app --reload                 # dev API (needs FINRAG_API_KEYS_FILE to authenticate)
```

For a local run without a key, set `FINRAG_DATA_DIR` to a temp directory; development mode
uses an ephemeral key. Never run production settings locally with real data.

## 3. Hard rules (do not break)

These protect users and the compliance claims. If a task seems to require breaking one,
stop and ask.

1. **No raw PII or document text in logs, errors, audit events, fixtures or comments.**
   Use synthetic data (`jane.doe@example.com`, `GB82 WEST 1234 5698 7654 32`).
2. **Never give the LLM tools, and never put secrets in prompts.** The model produces
   text from fenced sources only.
3. **Never send raw files or unmasked PII to the LLM or any external service.**
   Pseudonymisation happens before chunking, storage and generation.
4. **Never bypass `FinRAGPipeline`.** The API and CLI must not read stores, the vault or
   keys directly.
5. **Never widen permissions silently.** Changing `ROLE_PERMISSIONS` needs updated docs
   ([Security](Security.md) §5) and tests.
6. **Never weaken defaults.** Offline LLM by default, finite retention, fail closed in
   production.
7. **Never evaluate spreadsheet formulas, or use `eval`/`exec`/`pickle`/`subprocess` on
   untrusted data.**
8. **Do not add `[RULE: …]` tags to code that does not implement the rule.** A tag is a
   compliance claim. Do not delete tests, skip them, or loosen assertions to get green.
9. **Do not commit secrets or data**: `.env`, `keys.json`, `data/`, `*.enc`, `audit.log`.
10. **Do not state unbuilt features as built.** Mark ideas **Proposed** in documentation.
11. **UI code: no HTML-parsing sinks, no inline code, no third-party hosts.** Build DOM with `h()` and `textContent` from `js/dom.js`; never `innerHTML`, `eval`, inline `style=` or `on*=` attributes, CDN scripts or web fonts. `tests/test_web.py` enforces this.

## 4. Workflow for a change

1. **Understand first.** Read the module, its tests and the matching document above.
   Find existing helpers before writing new ones.
2. **Plan small.** One concern per change. For anything touching security or compliance,
   write down the threat or rule you are addressing.
3. **Write the test first or alongside** (see [Testing](Testing.md) §6). For a security
   control, add both a positive test (attack stopped) and a negative test (legitimate use
   still works).
4. **Implement** following [Code Style](CODE_STYLE.md): module docstring, type hints,
   `[RULE: ID]` comments on controls, British spelling, no new dependency without a
   reason.
5. **Verify**: run the four commands in §2. All must pass.
6. **Update docs** that describe the changed behaviour in the same change: README,
   [Architecture](Architecture.md), [Security](Security.md), `docs/RAG_FLOW.md` and the
   regenerated `docs/COMPLIANCE_MATRIX.md` as relevant.
7. **Report honestly.** State what you ran, what passed, what you did not test, and any
   limitation. Do not claim a control works unless a test or run showed it.

## 5. Recipes

### Add a new file type

1. Add `_load_<type>(data, settings) -> list[Section]` in `finrag/ingestion/loaders.py`.
   Validate the format first (magic bytes or structure), enforce size, page and row
   limits, and reject anything unsafe.
2. Register the extension in `_LOADERS`.
3. Tests in `tests/test_loaders.py`: one valid file, plus rejection cases (wrong content
   for the extension, oversized, malicious).
4. Update README "Features" and `PRD.md` FR1.

### Add a PII type

1. Add a pattern to `_PATTERNS` in `finrag/security/pii.py`. Prefer a checksum validator
   or a context label to avoid false positives on financial figures.
2. Tests in `tests/test_pii.py`: positive, and a negative showing ordinary financial
   numbers or words are not matched.
3. Update the PII table in `docs/COMPLIANCE.md`.

### Add or change a guardrail

1. Edit `finrag/security/guardrails.py`; tag with the right `[RULE: …]`.
2. Tests in `tests/test_guardrails.py` (blocked case and allowed case).
3. If it adds a new `reasons` value, handle it in `FinRAGPipeline._block_message` or
   `_assess` and in the Design System message tables.

### Add a setting

1. Add a typed field to `Settings` in `finrag/config.py` with a safe default.
2. Document it in `.env.example` and the README configuration table.
3. Test the default and an invalid value if validated.

### Add a new rule ID

1. Add `Rule(...)` to `finrag/compliance/rules.py`.
2. Tag the implementing code with `[RULE: ID]`.
3. `python scripts/compliance_report.py` and commit the matrix. CI fails if a registered
   rule has no implementing tag.

### Change the web UI

1. Work in `finrag/web/`. Colours, spacing and type come from the tokens at the top of
   `styles.css`; add a token rather than a raw value, and recheck contrast for both themes.
2. Build elements with `h()` and `icon()`; show untrusted text only via `textContent`.
3. A new screen is a module in `js/views/` with `render(root, ctx)`, registered in `ROUTES`
   in `js/main.js` with an `allowed` check. The server must enforce the same permission.
4. Handle loading, empty, error and disabled states; pair colour with an icon and text; keep
   touch targets at least 44 px; test at 375 px width and in dark mode.
5. Run `pytest tests/test_web.py`, then `python scripts/demo.py` and try it in a browser. If
   Chromium is available also run `tests/test_ui_e2e.py`.
6. Update [Design System](Design_System.md) if you change a token, pattern or component.

### After editing the UI or the demo sample files

`finrag/_assets.py` is a generated, compressed copy of `finrag/web/**` and
`finrag/demo_data/*` that serverless hosts fall back to when they package only Python
modules. After changing any of those files run:

```bash
python scripts/build_assets.py          # regenerate; commit finrag/_assets.py
```

CI (`build_assets.py --check`) and `tests/test_assets.py` fail if it is stale. Never edit
`_assets.py` by hand.

### Swap the retrieval backend

Keep the `TenantStore.search(query, top_k)` contract. Embed only pseudonymised text, keep
per-tenant isolation, encrypt at rest, and delete vectors on `delete_document`,
`erase_subject` and `purge_expired`. See [Architecture](Architecture.md) §9.

### Change the Claude call

Edit `AnthropicLLM.generate` in `finrag/generation/llm.py` only. Keep: no `tools`, the
`max_tokens` cap, handling of `stop_reason == "refusal"`, the typed-exception chain, and
`thinking`/effort settings from `Settings`. Update `tests/test_llm.py`. Do not call the
real API in tests.

## 6. Pitfalls specific to this codebase

- The pseudonymiser is called with `doc_id=None` for **questions** so nothing is stored;
  passing a document id would write the question's PII to the vault.
- Table chunks must repeat the column header; changing the chunker without keeping this
  causes figures to lose their period.
- `TenantStore._save` invalidates the in-memory index; if you add a code path that changes
  chunks, make sure the index is invalidated too.
- The compliance test `test_compliance_matrix_is_fresh` fails after moving code that
  carries `[RULE: …]` tags until you regenerate the matrix.
- Pattern detectors (PII, injection) are heuristic. Do not describe them in documentation
  as complete or guaranteed.
- State lives in local files with in-process locks: assume one instance per data
  directory.
- The UI page's CSP forbids `eval`, so browser-automation helpers that evaluate strings
  (for example Playwright `wait_for_function`) fail; wait on selectors instead.
- `GET /v1/me` is the UI's source of truth for permissions and option lists; when you add a
  permission or an enum value, expose it there so the UI does not hard-code it.
- Case-insensitive file systems: `docs/ARCHITECTURE.md` and `docs/project/Architecture.md`
  live in different directories on purpose. Do not move them into the same directory.

## 7. When to stop and ask

- The task needs a change to a hard rule in §3.
- You need to send data to a new external service.
- A requirement conflicts with GDPR or EU AI Act behaviour described in the docs.
- You cannot make a failing test pass without weakening it.
- The change affects stored data formats (existing encrypted files would stop loading).

## 8. Pull requests

- Only open a pull request when asked.
- Describe what changed, why, how it was tested (commands and results) and known
  limitations. List affected rule IDs.
- Keep the PR to one concern. Do not mix refactors with behaviour changes.
- Respond to review comments by pushing fixes or explaining why not; never rewrite
  history on a shared branch.
