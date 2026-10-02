"""
Input, context and output guardrails.

Three checkpoints wrap the LLM call:

1. ``check_query``    - user question (direct prompt injection, prohibited /
                        out-of-scope uses, size limits, PII in the question).
2. ``screen_context`` - retrieved document chunks (indirect prompt injection
                        hidden inside uploaded documents).
3. ``check_answer``   - model output (PII leakage, system-prompt leakage,
                        invalid citations, unverified figures).

Heuristic detectors are used so the module has no external dependencies; they
are a *defence-in-depth* layer on top of the structural defences in
``generation/prompts.py`` (context is fenced and declared as untrusted data,
and the model is given no tools).

[RULE: OWASP-LLM01]  Prompt-injection detection (direct + indirect).
[RULE: EUAIA-ART15]  Robustness against attempts to manipulate the system.
[RULE: EUAIA-ART9]   Risk management: known misuse risks have controls.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from finrag.security.pii import TOKEN_RE, PIIDetector

# --------------------------------------------------------------------------
# Patterns
# --------------------------------------------------------------------------
# [RULE: OWASP-LLM01] Common jailbreak / injection phrasings.
_INJECTION_PATTERNS = [
    r"ignore\s+(?:all\s+|any\s+)?(?:the\s+)?(?:previous|prior|above|earlier)\s+"
    r"(?:instructions?|prompts?|rules?|context)",
    r"disregard\s+(?:all\s+|the\s+)?(?:previous|prior|above|system)\s+\w+",
    r"forget\s+(?:everything|all|your)\s+(?:instructions?|rules?|above)?",
    r"(?:reveal|show|print|repeat|output|leak)\s+(?:me\s+)?(?:your|the)\s+"
    r"(?:system\s+prompt|instructions|hidden\s+prompt|initial\s+prompt)",
    r"you\s+are\s+now\s+(?:a|an|in)\b",
    r"\b(?:developer|god|dan|jailbreak)\s+mode\b",
    r"act\s+as\s+(?:if\s+you\s+(?:are|were)\s+)?(?:an?\s+)?(?:unrestricted|unfiltered)",
    r"pretend\s+(?:that\s+)?(?:you|there)\s+(?:are|is)\s+no\s+(?:rules|restrictions)",
    r"</?\s*(?:system|assistant|instructions?)\s*>",
    r"\bnew\s+instructions?\s*:",
    r"override\s+(?:your|the)\s+(?:safety|guardrails?|rules|policy)",
    r"(?:print|list|dump|reveal)\s+(?:all\s+)?(?:the\s+)?(?:api\s+keys?|secrets?|passwords?|"
    r"credentials|environment\s+variables)",
]
_INJECTION_RE = re.compile("|".join(f"(?:{p})" for p in _INJECTION_PATTERNS), re.IGNORECASE)

# [RULE: EUAIA-ART5] Prohibited AI practices relevant to a finance assistant.
_PROHIBITED_RE = re.compile(
    r"(?i)\b(social\s+scor\w*|"
    r"(?:infer|detect|recogni[sz]e)\s+(?:the\s+)?emotions?|"
    r"exploit\s+(?:their|the)\s+(?:vulnerabilit\w+|age|disabilit\w+)|"
    r"manipulat\w+\s+(?:customers?|users?|people|them)\s+into|"
    r"predict\s+(?:whether|if)\s+\w+\s+will\s+commit\s+(?:a\s+)?(?:crime|fraud))\b"
)

# [RULE: EUAIA-ART6] [RULE: GDPR-ART22] High-risk Annex III use cases that are
# outside this system's intended purpose: automated creditworthiness / credit
# scoring of natural persons and automated individual decisions.
_HIGH_RISK_RE = re.compile(
    r"(?i)\b((?:credit\s*(?:score|scoring|worthiness)|creditworthiness)\s+(?:of|for)\s+"
    r"(?:this|the|a|an)?\s*(?:person|individual|applicant|customer|employee|him|her|them)|"
    r"(?:should|can)\s+(?:we|i)\s+(?:approve|reject|deny|decline)\s+(?:this|the|his|her|their)?"
    r"\s*(?:loan|credit|mortgage|application|applicant)|"
    r"(?:decide|determine)\s+(?:whether\s+)?(?:to\s+)?(?:hire|fire|dismiss|promote)\b|"
    r"(?:life|health)\s+insurance\s+(?:pricing|risk)\s+(?:of|for)\s+(?:this|the)\s+person)"
)

# [RULE: FIN-NO-ADVICE] Requests for personalised investment advice.
_ADVICE_RE = re.compile(
    r"(?i)\b(should\s+i\s+(?:buy|sell|invest|short|hold)|"
    r"(?:what|which)\s+(?:stocks?|shares?|funds?|crypto\w*)\s+should\s+i|"
    r"guarantee(?:d)?\s+(?:returns?|profit))\b"
)

# Zero-width and bidi control characters used to smuggle hidden instructions.
_INVISIBLE_RE = re.compile("[​-‏‪-‮⁠-⁤﻿]")

# Long base64-looking blobs can carry encoded instructions.
_BASE64_BLOB_RE = re.compile(r"[A-Za-z0-9+/]{120,}={0,2}")

# Citation markers produced by the model, e.g. [S1] or [S1, S3].
_CITATION_RE = re.compile(r"\[S(\d+)(?:\s*,\s*S?(\d+))*\]")

# Numbers in answers: 1,234.56 / 12.5% / (3,400) / £2.1m / €40bn ...
_NUMBER_RE = re.compile(r"(?<![\w.])\(?-?\d[\d,]*(?:\.\d+)?\)?(?:\s?%|\s?(?:k|m|bn|mn|million|"
                        r"billion|thousand))?", re.IGNORECASE)


@dataclass
class GuardrailResult:
    """Outcome of a guardrail check."""

    allowed: bool
    reasons: list[str] = field(default_factory=list)
    sanitized: str = ""
    flags: dict[str, object] = field(default_factory=dict)


def normalise_text(text: str) -> str:
    """NFKC-normalise and strip invisible / control characters.

    [RULE: SEC-INPUT-VALIDATION] Defeats homoglyph and zero-width obfuscation
    of injection payloads before pattern matching.
    """
    text = unicodedata.normalize("NFKC", text)
    text = _INVISIBLE_RE.sub("", text)
    # Drop C0 control characters except tab/newline/carriage return.
    return "".join(ch for ch in text if ch in "\t\n\r" or unicodedata.category(ch) != "Cc")


def check_query(query: str, max_chars: int, detector: PIIDetector | None = None) -> GuardrailResult:
    """Validate a user question before retrieval and generation."""
    reasons: list[str] = []
    text = normalise_text(query).strip()

    # [RULE: SEC-INPUT-VALIDATION] [RULE: OWASP-LLM10] Bound the input size.
    if not text:
        return GuardrailResult(False, ["empty_query"])
    if len(text) > max_chars:
        return GuardrailResult(False, [f"query_too_long>{max_chars}"])

    # [RULE: OWASP-LLM01] Direct prompt injection.
    if _INJECTION_RE.search(text):
        reasons.append("prompt_injection_detected")
    if _BASE64_BLOB_RE.search(text):
        reasons.append("encoded_payload_detected")

    # [RULE: EUAIA-ART5] Prohibited practices are refused outright.
    if _PROHIBITED_RE.search(text):
        reasons.append("prohibited_ai_practice")

    # [RULE: EUAIA-ART6] [RULE: GDPR-ART22] Out-of-scope high-risk decisions.
    if _HIGH_RISK_RE.search(text):
        reasons.append("high_risk_use_out_of_scope")

    flags: dict[str, object] = {}
    # [RULE: FIN-NO-ADVICE] Not blocked, but the answer will be framed as
    # informational and the disclaimer is emphasised.
    if _ADVICE_RE.search(text):
        flags["advice_requested"] = True

    # [RULE: GDPR-ART5-1C] [RULE: PII-REDACT] PII in the question is not needed
    # for retrieval over pseudonymised data; record that it was present.
    detector = detector or PIIDetector()
    pii_spans = detector.detect(text)
    if pii_spans:
        flags["query_pii_types"] = sorted({s.pii_type for s in pii_spans})

    return GuardrailResult(not reasons, reasons, text, flags)


def screen_context(chunk_text: str) -> list[str]:
    """Return indirect-injection indicators found in a retrieved chunk.

    [RULE: OWASP-LLM01] Documents are attacker-controllable input; chunks with
    instruction-like content are dropped from the prompt (quarantined).
    [RULE: OWASP-LLM04] Same check runs at ingestion to flag poisoned files.
    """
    text = normalise_text(chunk_text)
    findings: list[str] = []
    if _INJECTION_RE.search(text):
        findings.append("instruction_like_content")
    if _INVISIBLE_RE.search(chunk_text):
        findings.append("hidden_characters")
    if _BASE64_BLOB_RE.search(text):
        findings.append("encoded_payload")
    return findings


def _normalise_number(raw: str) -> str | None:
    """Canonicalise a numeric string so '1,234.50' and '1234.5' compare equal."""
    core = re.sub(r"[^\d.\-]", "", raw.replace("(", "-").replace(")", ""))
    if not core or core in {"-", ".", "-."}:
        return None
    try:
        value = float(core)
    except ValueError:
        return None
    return f"{abs(value):.4f}".rstrip("0").rstrip(".")


def extract_numbers(text: str) -> set[str]:
    """Return canonicalised numbers in ``text`` (ignoring citation indices)."""
    stripped = _CITATION_RE.sub(" ", TOKEN_RE.sub(" ", text))
    numbers = set()
    for match in _NUMBER_RE.finditer(stripped):
        canon = _normalise_number(match.group(0))
        # Ignore trivial integers (list numbering, "Q1", single digits).
        if canon is not None and (len(canon.replace(".", "")) >= 2 or "." in canon):
            numbers.add(canon)
    return numbers


def check_answer(
    answer: str,
    context_by_label: dict[str, str],
    system_canary: str,
    detector: PIIDetector | None = None,
) -> GuardrailResult:
    """Validate model output before returning it to the user.

    ``context_by_label`` maps source labels like ``"S1"`` to the chunk text that
    was shown to the model.
    """
    detector = detector or PIIDetector()
    reasons: list[str] = []
    flags: dict[str, object] = {}
    text = normalise_text(answer)

    # [RULE: OWASP-LLM07] The system prompt carries a random canary; if it shows
    # up in the output the model has been coerced into leaking its prompt.
    if system_canary and system_canary in text:
        return GuardrailResult(False, ["system_prompt_leak"], "", flags)

    # [RULE: OWASP-LLM02] [RULE: PII-REDACT] Any raw PII that slipped through
    # (e.g. hallucinated or reconstructed) is redacted from the output.
    spans = detector.detect(text)
    if spans:
        flags["output_pii_redacted"] = sorted({s.pii_type for s in spans})
        pieces, last = [], 0
        for span in spans:
            pieces.append(text[last:span.start])
            pieces.append(f"[REDACTED:{span.pii_type}]")
            last = span.end
        pieces.append(text[last:])
        text = "".join(pieces)

    # [RULE: OWASP-LLM09] Citations must reference sources that were provided.
    cited: set[str] = set()
    for match in _CITATION_RE.finditer(text):
        for grp in match.groups():
            if grp:
                cited.add(f"S{grp}")
    invalid = sorted(c for c in cited if c not in context_by_label)
    if invalid:
        reasons.append("invalid_citations")
        flags["invalid_citations"] = invalid
    flags["citations"] = sorted(cited)

    # [RULE: FIN-NUMERIC-INTEGRITY] [RULE: OWASP-LLM09] Every figure in the
    # answer should appear in the supplied context. Unverified figures do not
    # block the answer but force human review.
    context_numbers: set[str] = set()
    for chunk in context_by_label.values():
        context_numbers |= extract_numbers(chunk)
    unverified = sorted(n for n in extract_numbers(text) if n not in context_numbers)
    flags["unverified_numbers"] = unverified

    # [RULE: OWASP-LLM05] Output is treated as plain text: strip anything that
    # looks like markup/script so downstream UIs cannot be attacked via HTML.
    text = re.sub(r"<\s*/?\s*(script|iframe|object|embed|style)[^>]*>", "", text, flags=re.I)

    return GuardrailResult(not reasons, reasons, text, flags)
