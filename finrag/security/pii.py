"""
PII detection, redaction and keyed pseudonymisation.

Pipeline position
-----------------
Every piece of untrusted text passes through this module **before** it is
stored, logged, embedded or sent to an LLM provider:

    raw text --detect--> spans --pseudonymise--> "<EMAIL_9f2c1a7b3e>" (stored)
                                 \--redact-----> "[REDACTED:EMAIL]"   (logs)

Design notes
------------
* Detection is regex + checksum based (Luhn for cards, ISO 7064 mod-97 for
  IBANs, octet validation for IPs) to keep false positives low on financial
  documents, which are full of long numbers that must NOT be redacted.
* Context-sensitive identifiers (account numbers, sort codes, names, DOB) are
  only matched after a label such as "Account no:" or "Mr".
* Tokens are deterministic per tenant (HMAC-SHA256 with a tenant-scoped key),
  so the same e-mail always maps to the same token, which keeps retrieval and
  aggregation working on pseudonymised data.
* The token -> original mapping lives in an encrypted ``PseudonymVault``,
  separate from the document store. Without the vault key the stored corpus is
  pseudonymous; deleting a vault entry makes the token irreversible.

The detector is intentionally pluggable: production deployments can add an
NER model (e.g. Microsoft Presidio / spaCy) via ``PIIDetector.extra_detectors``.

[RULE: PII-DETECT]        Detection of direct identifiers.
[RULE: PII-REDACT]        Irreversible redaction for logs.
[RULE: PII-PSEUDONYMISE]  Reversible-under-control HMAC tokens.
[RULE: GDPR-ART4-5]       Pseudonymisation with separately-kept additional info.
[RULE: GDPR-ART5-1C]      Data minimisation: identifiers are not needed to
                          answer financial questions, so they are removed.
[RULE: GDPR-ART9]         Special-category data is detected and flagged.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from finrag.security.crypto import Encryptor, atomic_write


@dataclass(frozen=True)
class PIISpan:
    """A detected PII occurrence inside a string."""

    start: int
    end: int
    pii_type: str
    value: str


# --------------------------------------------------------------------------
# Checksum validators (reduce false positives on financial figures)
# --------------------------------------------------------------------------
def _luhn_ok(number: str) -> bool:
    """Return True if ``number`` (digits only) passes the Luhn checksum."""
    digits = [int(d) for d in number]
    checksum = 0
    for idx, digit in enumerate(reversed(digits)):
        if idx % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


def _iban_ok(iban: str) -> bool:
    """Validate an IBAN using the ISO 7064 mod-97-10 algorithm."""
    compact = iban.replace(" ", "").upper()
    if not 15 <= len(compact) <= 34:
        return False
    rearranged = compact[4:] + compact[:4]
    numeric = "".join(str(int(ch, 36)) for ch in rearranged)
    return int(numeric) % 97 == 1


def _ipv4_ok(ip: str) -> bool:
    """Return True for a syntactically valid dotted-quad IPv4 address."""
    parts = ip.split(".")
    return len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)


# --------------------------------------------------------------------------
# Pattern table: (type, compiled regex, capture group, optional validator)
# --------------------------------------------------------------------------
_Validator = Callable[[str], bool]

_PATTERNS: list[tuple[str, re.Pattern[str], int, _Validator | None]] = [
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), 0, None),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){2,7}(?:\s?[A-Z0-9]{1,4})?\b"), 0,
     _iban_ok),
    ("CREDIT_CARD", re.compile(r"\b(?:\d[ -]?){12,18}\d\b"), 0,
     lambda v: _luhn_ok(re.sub(r"\D", "", v)) and 13 <= len(re.sub(r"\D", "", v)) <= 19),
    ("UK_NINO", re.compile(r"\b[A-CEGHJ-PR-TW-Z]{2}\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-D]\b"), 0, None),
    ("US_SSN", re.compile(r"\b(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b"), 0, None),
    ("IP_ADDRESS", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), 0, _ipv4_ok),
    # International phone numbers must start with "+" so plain financial
    # figures such as 1 234 567 890 are never mistaken for phones.
    ("PHONE", re.compile(r"(?<!\w)\+\d{1,3}[\s.-]?(?:\(?\d{1,4}\)?[\s.-]?){2,5}\d{2,4}\b"), 0,
     None),
    # Context-labelled identifiers: only the value (group 1) is treated as PII.
    ("PHONE", re.compile(r"(?i)\b(?:tel|phone|mobile|fax)\b[.:#\s]*((?:\(?\d[\d\s().-]{6,18}\d))"),
     1, None),
    ("ACCOUNT_NUMBER", re.compile(
        r"(?i)\b(?:account|acct|a/c)\s*(?:no\.?|number|num|#)?\s*[:#]?\s*(\d{6,12})\b"), 1, None),
    ("SORT_CODE", re.compile(r"(?i)\bsort\s*code\s*[:#]?\s*(\d{2}[- ]?\d{2}[- ]?\d{2})\b"), 1,
     None),
    # Scoped (?i:...) flags make only the *label* case-insensitive; the value
    # must still look like an identifier (upper-case + at least one digit).
    ("PASSPORT", re.compile(
        r"\b(?i:passport)\s*(?i:no\.?|number|#)?\s*[:#]?\s*((?=[A-Z0-9]*\d)[A-Z0-9]{6,9})\b"),
     1, None),
    ("DATE_OF_BIRTH", re.compile(
        r"(?i)\b(?:dob|d\.o\.b\.|date\s+of\s+birth|born(?:\s+on)?)\s*[:#]?\s*"
        r"(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|\d{4}-\d{2}-\d{2})"), 1, None),
    ("TAX_ID", re.compile(
        r"\b(?i:tax\s*(?:id|identification\s+number|reference)|tin|utr|ssn)\s*[:#]?\s*"
        r"((?=[A-Z0-9-]*\d)[A-Z0-9-]{8,15})\b"), 1, None),
    # Person names: honorific + capitalised words, or a "Name:"-style label.
    ("PERSON", re.compile(r"\b(?:Mr|Mrs|Ms|Miss|Dr|Prof)\.?\s+((?:[A-Z][a-z'-]+\s?){1,3})"), 1,
     None),
    ("PERSON", re.compile(
        r"(?m)\b(?i:name|customer|client|account\s+holder|employee|beneficiary|"
        r"signed\s+by|prepared\s+by)\s*[:]\s*((?:[A-Z][a-z'-]+[ \t]?){2,3})"), 1, None),
]

# [RULE: GDPR-ART9] Indicators of special-category data. Deliberately specific
# to avoid false positives like "financial health".
_SPECIAL_CATEGORY_TERMS = re.compile(
    r"(?i)\b(medical\s+condition|diagnos(?:is|ed)|hiv|cancer|pregnan\w*|disabilit\w+|"
    r"mental\s+health|religio(?:n|us\s+belief)|ethnic(?:ity|\s+origin)|racial\s+origin|"
    r"sexual\s+orientation|trade\s+union\s+member\w*|political\s+(?:opinion|affiliation)|"
    r"biometric|genetic\s+data)\b"
)

# Pseudonym token format, e.g. <EMAIL_9f2c1a7b3e>
TOKEN_RE = re.compile(r"<([A-Z_]+)_([0-9a-f]{10})>")


@dataclass
class PIIDetector:
    """Find PII spans in text using validated patterns plus optional plug-ins."""

    # Hook for extra detectors (e.g. an NER model). Each returns spans.
    extra_detectors: list[Callable[[str], Iterable[PIISpan]]] = field(default_factory=list)

    def detect(self, text: str) -> list[PIISpan]:
        """Return non-overlapping PII spans, preferring the longest match."""
        found: list[PIISpan] = []
        for pii_type, pattern, group, validator in _PATTERNS:
            for match in pattern.finditer(text):
                value = match.group(group)
                if not value:
                    continue
                value_stripped = value.rstrip()
                if validator and not validator(value_stripped):
                    continue
                start = match.start(group)
                found.append(PIISpan(start, start + len(value_stripped), pii_type, value_stripped))
        for detector in self.extra_detectors:
            found.extend(detector(text))
        # Resolve overlaps: sort by start, then longest first; keep first winner.
        found.sort(key=lambda s: (s.start, -(s.end - s.start)))
        result: list[PIISpan] = []
        cursor = -1
        for span in found:
            if span.start >= cursor:
                result.append(span)
                cursor = span.end
        return result

    @staticmethod
    def special_categories(text: str) -> list[str]:
        """Return distinct special-category indicator terms found in ``text``."""
        # [RULE: GDPR-ART9]
        return sorted({m.group(1).lower() for m in _SPECIAL_CATEGORY_TERMS.finditer(text)})


def redact(text: str, detector: PIIDetector | None = None) -> str:
    """Irreversibly replace PII with ``[REDACTED:<TYPE>]`` (for logs/audit)."""
    # [RULE: PII-REDACT] [RULE: PII-LOG-SCRUB]
    detector = detector or PIIDetector()
    spans = detector.detect(text)
    out: list[str] = []
    last = 0
    for span in spans:
        out.append(text[last:span.start])
        out.append(f"[REDACTED:{span.pii_type}]")
        last = span.end
    out.append(text[last:])
    # Pseudonym tokens are also scrubbed so logs reveal nothing linkable.
    return TOKEN_RE.sub(lambda m: f"[REDACTED:{m.group(1)}]", "".join(out))


class PseudonymVault:
    """Encrypted, file-backed mapping of pseudonym token -> original value.

    Stored separately from document chunks and encrypted with its own key.
    [RULE: GDPR-ART4-5] "additional information ... kept separately".
    [RULE: GDPR-ART32]  Encrypted at rest; access gated by RBAC in callers.
    """

    def __init__(self, path: Path, encryptor: Encryptor) -> None:
        self._path = path
        self._enc = encryptor
        self._lock = threading.RLock()
        self._entries: dict[str, dict[str, object]] = self._load()

    def _load(self) -> dict[str, dict[str, object]]:
        if not self._path.exists():
            return {}
        return json.loads(self._enc.decrypt(self._path.read_bytes()))

    def _flush(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(self._path, self._enc.encrypt(json.dumps(self._entries).encode()))

    def put(self, token: str, pii_type: str, value: str, doc_id: str) -> None:
        """Record that ``token`` stands for ``value`` within ``doc_id``."""
        with self._lock:
            entry = self._entries.setdefault(token, {"type": pii_type, "value": value, "docs": []})
            docs = entry["docs"]
            assert isinstance(docs, list)
            if doc_id not in docs:
                docs.append(doc_id)

    def save(self) -> None:
        """Persist pending changes to disk."""
        with self._lock:
            self._flush()

    def lookup(self, token: str) -> str | None:
        """Return the original value for ``token`` (caller must be authorised)."""
        entry = self._entries.get(token)
        return str(entry["value"]) if entry else None

    def tokens_for_doc(self, doc_id: str) -> list[str]:
        """List tokens referenced by a document (used for Art. 15 exports)."""
        return [t for t, e in self._entries.items() if doc_id in e["docs"]]  # type: ignore[operator]

    def release_doc(self, doc_id: str) -> int:
        """Detach a deleted document; drop entries no longer referenced.

        [RULE: GDPR-ART17] When a document is erased, the identifiers that only
        it referenced are destroyed too, so its pseudonyms become irreversible.
        """
        removed = 0
        with self._lock:
            for token in list(self._entries):
                docs = self._entries[token]["docs"]
                assert isinstance(docs, list)
                if doc_id in docs:
                    docs.remove(doc_id)
                    if not docs:
                        del self._entries[token]
                        removed += 1
            self._flush()
        return removed

    def forget_token(self, token: str) -> bool:
        """Delete one mapping (data-subject erasure). Returns True if it existed."""
        with self._lock:
            existed = self._entries.pop(token, None) is not None
            self._flush()
        return existed


class Pseudonymiser:
    """Replace PII with deterministic, keyed tokens and record them in the vault."""

    def __init__(self, key: bytes, vault: PseudonymVault, detector: PIIDetector | None = None):
        self._key = key
        self._vault = vault
        self.detector = detector or PIIDetector()

    def token_for(self, pii_type: str, value: str) -> str:
        """Compute the HMAC-based token for a value (stable for a given key)."""
        # [RULE: PII-PSEUDONYMISE] Normalise so "John@X.com" == "john@x.com".
        normalised = re.sub(r"\s+", "", value).lower()
        digest = hmac.new(self._key, f"{pii_type}|{normalised}".encode(), hashlib.sha256)
        return f"<{pii_type}_{digest.hexdigest()[:10]}>"

    def pseudonymise(self, text: str, doc_id: str | None) -> tuple[str, dict[str, int]]:
        """Return ``(pseudonymised_text, counts_by_type)``.

        With a ``doc_id`` the token mapping is recorded in the vault (document
        ingestion). With ``doc_id=None`` nothing is stored: this is used for user
        questions, so "what did jane@x.com pay?" is turned into the same token
        that the stored chunks contain - retrieval works without the question's
        PII ever being stored or sent to the LLM. [RULE: GDPR-ART5-1C]
        """
        spans = self.detector.detect(text)
        counts: dict[str, int] = {}
        out: list[str] = []
        last = 0
        for span in spans:
            token = self.token_for(span.pii_type, span.value)
            if doc_id is not None:
                self._vault.put(token, span.pii_type, span.value, doc_id)
            counts[span.pii_type] = counts.get(span.pii_type, 0) + 1
            out.append(text[last:span.start])
            out.append(token)
            last = span.end
        out.append(text[last:])
        return "".join(out), counts

    def reidentify(self, text: str) -> str:
        """Replace tokens with original values. Callers MUST check permissions.

        [RULE: SEC-AUTHZ] Only invoked by the pipeline for principals holding
        the ``reidentify`` permission (e.g. a DPO handling an Art. 15 request).
        """
        def _swap(match: re.Match[str]) -> str:
            original = self._vault.lookup(match.group(0))
            return original if original is not None else match.group(0)

        return TOKEN_RE.sub(_swap, text)
