# Code Style: FinRAG

How code in this repository is written. These conventions describe what the existing
code does; where a rule is only a goal, it says so. Run the checks in §10 before every
commit.

Related: [Architecture](Architecture.md) · [Security](Security.md) · [Testing](Testing.md) · [Agents](Agents.md)

---

## 1. Language and tooling

| Item | Standard |
|---|---|
| Python | 3.10 or newer (`requires-python = ">=3.10"`); CI uses 3.11, the Docker image 3.12 |
| Linter | `ruff` with its default rules, `line-length = 100`, `target-version = "py310"` (see `pyproject.toml`) |
| Formatter | None enforced. Follow the layout of surrounding code; wrap at 100 columns |
| Tests | `pytest` (see [Testing](Testing.md)) |
| Type checking | Annotations are required (§4). A type checker is **not** run in CI yet (Proposed: `mypy` or `pyright`) |

## 2. File layout

Every module starts with:

1. A **module docstring** explaining what the module does, why it is designed that way,
   and any `[RULE: ID]` tags for the controls it implements.
2. `from __future__ import annotations`.
3. Imports in three groups, separated by blank lines: standard library, third-party,
   first-party (`finrag.*`). Use absolute imports (`from finrag.security.pii import …`),
   never relative ones.
4. Constants, then helpers, then classes, then public functions, with public API first
   when it aids reading. Private names start with `_`.

Each package has an `__init__.py` with a one-line docstring.

## 3. Naming

| Kind | Convention | Example |
|---|---|---|
| Modules, functions, variables | `snake_case` | `load_document`, `top_k` |
| Classes, exceptions, enums | `PascalCase` | `PseudonymVault`, `UnsupportedDocumentError` |
| Constants | `UPPER_SNAKE_CASE` | `SYSTEM_PROMPT`, `_HASH_DIM` |
| Private helpers | leading underscore | `_split_table` |
| Exceptions | end in `Error`, derive from the closest builtin | `class ComplianceError(ValueError)` |
| Tests | `test_<behaviour>` | `test_tenant_isolation` |
| Settings / env vars | field `snake_case`, env `FINRAG_<FIELD>` | `rate_limit_per_minute` → `FINRAG_RATE_LIMIT_PER_MINUTE` |
| Rule IDs | `FAMILY-NAME`, uppercase | `GDPR-ART17`, `OWASP-LLM01` |

Use British spelling in prose, comments and user-facing text (`pseudonymise`,
`authorise`, `minimisation`). Identifiers that mirror external APIs keep their spelling.

## 4. Types

- Annotate every function parameter and return value, and class attributes.
- Use modern syntax (`list[str]`, `dict[str, int]`, `X | None`); no `typing.List` or
  `Optional`.
- Prefer `@dataclass` (use `frozen=True` for value objects such as `Principal`, `Rule`)
  for data holders. Use `pydantic` models only at boundaries (settings in `config.py`,
  request bodies in `api.py`).
- Use `Protocol` for interfaces (`AnswerGenerator`), not abstract base classes.
- Avoid `Any`. Where unavoidable, keep it local and comment why. A `# type: ignore[code]`
  needs the specific code and, if not obvious, a reason.

## 5. Comments and docstrings

This project is read by reviewers and auditors as well as developers, so comments carry
more weight than usual.

- **Docstrings:** every module, class and public function. First line is a summary in the
  imperative or descriptive mood and fits on one line. Add detail only when behaviour is
  not obvious.
- **Why over what.** Comment the reason, the threat or the rule, not the syntax.
- **Rule tags.** Mark each control with `[RULE: ID]` in a comment on or just above the
  code that implements it. Several tags may share a comment. Example:

  ```python
  # [RULE: SEC-AUTHZ] Deny by default.
  if permission not in self.permissions:
      raise AccessDenied(...)
  ```

  Rules for tags:
  - The ID must exist in `finrag/compliance/rules.py`. Add the rule there first if new.
  - Tag only code that really implements the control. Do not tag to make coverage look
    better; a tag is a claim.
  - After adding or moving tags, run `python scripts/compliance_report.py` and commit the
    regenerated `docs/COMPLIANCE_MATRIX.md`.
- No commented-out code. No unexplained `TODO`; if you leave one, say what and why.
- Never put secrets, real personal data or real customer examples in comments, docstrings
  or fixtures. Use synthetic values (`jane.doe@example.com`, `GB82 WEST 1234 5698 7654 32`).

## 6. Error handling

| Situation | Convention |
|---|---|
| Invalid user input or file | Raise a specific exception (`UnsupportedDocumentError`, `ComplianceError`, `ValueError`) with a message written by us that does not echo user data |
| Permission failure | `AccessDenied`; audit it as `outcome="denied"` |
| Provider failure | Catch the SDK's typed errors, most specific first, and raise `LLMUnavailableError` |
| Integrity failure | `DecryptionError`; audit it, then re-raise (fail closed) |
| Unexpected error | Let it propagate; the API handler logs only `type(exc).__name__` and returns a generic 500 |

Do not use bare `except:` or `except Exception:` to hide problems. Catch the narrowest type
and use `raise … from exc` so the cause is kept. Messages shown to clients are generic;
details go to the audit log (redacted).

## 7. Logging and audit

- Use `logging.getLogger(__name__)`. Never `print` in library code (the CLI is the only
  place that prints).
- **Never log** raw PII, document text, questions, prompts, keys or request bodies.
  Log identifiers, counts, status codes and exception *types*.
- Security-relevant events go to `AuditLog.record(...)`, not the application log. Free
  text passed to it is redacted automatically, but pass redacted values anyway.

## 8. Design rules

1. **One entry point.** The API and CLI call `FinRAGPipeline`; they must not reach into
   stores or the vault directly.
2. **Dependencies point down** (see [Architecture](Architecture.md) §3). Domain modules
   never import `pipeline`, `api` or `cli`.
3. **No global mutable state** beyond the cached `get_settings()` and the process-wide
   `SYSTEM_CANARY`.
4. **Configuration through `Settings`.** No new `os.environ` reads scattered in code;
   add a typed field with a safe default and document it in `.env.example` and the README.
5. **Safe defaults.** A new setting must default to the more private, more restrictive
   option.
6. **Small functions.** Prefer functions that fit on a screen. Extract helpers rather than
   nesting deeply; `pipeline.ingest` and `ask` are long, so do not make them longer without
   extracting.
7. **Validate at the boundary**, trust inside. Check types, sizes and encodings where
   untrusted data enters.
8. **No new dependency without a reason.** Prefer the standard library. Each new
   dependency needs a justification in the PR and passes `pip-audit`.
9. **Deterministic tests and code paths.** No wall-clock sleeps, no network.

## 9. Security-sensitive code

Apply extra care and expect a security review when changing `finrag/security/`,
`finrag/ingestion/loaders.py`, `finrag/generation/` or `finrag/api.py`.

- Compare secrets with `hmac.compare_digest`, never `==`.
- Use `secrets` / `os.urandom` for randomness, never `random`.
- Never pass tools to the model; never add secrets to prompts.
- Never evaluate spreadsheet formulas, `eval`, `exec`, `pickle` or `subprocess` on
  untrusted data. Parse with strict, bounded readers.
- Write files with `atomic_write` (mode `0600`).
- Treat every string from a document, a question or a model as untrusted.

## 10. Checks before committing

```bash
ruff check finrag tests scripts
pytest -q
python scripts/compliance_report.py        # then commit docs/COMPLIANCE_MATRIX.md if it changed
python scripts/compliance_report.py --check
```

All must pass; CI runs the same commands plus `pip-audit`.

## 11. JavaScript and CSS (web UI)

| Topic | Rule |
|---|---|
| Language | Plain ES modules, no build step, no framework, no TypeScript; browsers must run the files as written |
| Style | 2-space indent, double quotes, semicolons, `const` by default, `async`/`await`, small functions |
| DOM | Create nodes with `h(tag, attrs, ...children)` from `js/dom.js`. Untrusted text goes in as `textContent` or text nodes only |
| Forbidden | `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`, `eval`, `new Function`, string `setTimeout`, inline `style=` and `on*=` attributes, third-party scripts, styles or fonts (enforced by `tests/test_web.py`) |
| Storage | `sessionStorage` for the API key only; `localStorage` for the theme only; never store questions, answers or document text |
| Comments | A header comment per module saying what the screen does and which `[RULE: ID]` tags it implements; why-comments for non-obvious choices |
| Accessibility | Every control has a visible or accessible name; status uses colour plus an icon plus text; focus is visible and managed on route change; touch targets at least 44 px |
| CSS | Tokens in `:root` (and the dark overrides); components reference tokens only; mobile-first with `min-width` breakpoints at 768 and 1024 px; no `!important` except the reduced-motion rule |
| Naming | `kebab-case` CSS classes, `camelCase` JS, `snake_case` only for API field names |
| Errors | Show a message that says what happened and what to do, next to the thing that failed; never show raw server errors or stack traces |

## 12. Git and pull requests

- Small, focused commits with an imperative summary line ("Add retention purge"), a blank
  line, then the why.
- One concern per pull request. Describe what changed, how it was tested, and any
  limitation. Link the rule IDs affected.
- Do not commit `.env`, `keys.json`, `data/`, `*.enc` or `audit.log` (they are
  git-ignored).
- Documentation changes that describe behaviour must be updated in the same PR as the
  behaviour.

## 13. Documentation style

- Markdown, ATX headings (`#`), tables for structured comparisons, fenced code blocks
  with a language tag.
- Mermaid for diagrams, validated by rendering before commit (see
  [Design System](Design_System.md) §4).
- State limitations plainly. Mark unbuilt ideas **Proposed**; never describe a goal as a
  feature.
