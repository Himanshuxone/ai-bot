"""PII detection, redaction and pseudonymisation tests. [RULE: PII-DETECT]"""

from __future__ import annotations

from finrag.security.crypto import Encryptor
from finrag.security.pii import PIIDetector, Pseudonymiser, PseudonymVault, redact


def _types(text: str) -> set[str]:
    return {s.pii_type for s in PIIDetector().detect(text)}


def test_detects_common_identifiers():
    assert "EMAIL" in _types("mail me at john.smith@example.co.uk")
    assert "IBAN" in _types("Pay to GB82 WEST 1234 5698 7654 32 today")
    assert "CREDIT_CARD" in _types("card 4111 1111 1111 1111 exp 01/30")
    assert "UK_NINO" in _types("NI number AB 12 34 56 C")
    assert "US_SSN" in _types("SSN 123-45-6789")
    assert "PHONE" in _types("call +44 20 7946 0958")
    assert "IP_ADDRESS" in _types("login from 192.168.10.24")
    assert "ACCOUNT_NUMBER" in _types("Account no: 12345678")
    assert "PERSON" in _types("Approved by Mr John Smith yesterday")


def test_financial_figures_are_not_pii():
    # Large numbers, invalid checksums and dates must survive untouched.
    text = "Revenue 1,452,000 vs 1,180,000; EBITDA 310000; date 12-03-2024; ratio 0.44"
    assert PIIDetector().detect(text) == []
    # A 16-digit number failing Luhn is not a card.
    assert "CREDIT_CARD" not in _types("ref 1234 5678 9012 3456")
    # Invalid IBAN checksum.
    assert "IBAN" not in _types("GB00 WEST 1234 5698 7654 32")


def test_redact_is_irreversible():
    out = redact("Contact jane@example.com")
    assert "jane@example.com" not in out
    assert "[REDACTED:EMAIL]" in out


def test_pseudonymise_deterministic_and_reversible(tmp_path):
    vault = PseudonymVault(tmp_path / "v.enc", Encryptor(b"k" * 32))
    pseudo = Pseudonymiser(b"p" * 32, vault)
    a, counts = pseudo.pseudonymise("Email JANE@example.com now", "doc1")
    b, _ = pseudo.pseudonymise("again jane@example.com", "doc2")
    token = pseudo.token_for("EMAIL", "jane@example.com")
    assert token in a and token in b  # case-insensitive, deterministic
    assert counts == {"EMAIL": 1}
    assert "jane@example.com" in pseudo.reidentify(a).lower()
    # Query mode (doc_id=None) must not write to the vault.
    pseudo.pseudonymise("bob@example.com", None)
    assert vault.lookup(pseudo.token_for("EMAIL", "bob@example.com")) is None


def test_vault_release_and_forget(tmp_path):
    vault = PseudonymVault(tmp_path / "v.enc", Encryptor(b"k" * 32))
    vault.put("<EMAIL_aaaaaaaaaa>", "EMAIL", "x@y.com", "d1")
    vault.put("<EMAIL_aaaaaaaaaa>", "EMAIL", "x@y.com", "d2")
    assert vault.release_doc("d1") == 0  # still referenced by d2
    assert vault.release_doc("d2") == 1  # now destroyed
    assert vault.lookup("<EMAIL_aaaaaaaaaa>") is None


def test_vault_is_encrypted_on_disk(tmp_path):
    path = tmp_path / "v.enc"
    vault = PseudonymVault(path, Encryptor(b"k" * 32))
    vault.put("<EMAIL_bbbbbbbbbb>", "EMAIL", "secret@example.com", "d1")
    vault.save()
    assert b"secret@example.com" not in path.read_bytes()


def test_special_category_detection():
    assert PIIDetector.special_categories("Employee diagnosed with cancer") == [
        "cancer", "diagnosed"]
    assert PIIDetector.special_categories("The company's financial health is good") == []


def test_labels_do_not_capture_ordinary_words():
    # Only the label is case-insensitive; lower-case words are not names/IDs.
    assert _types("Customer: the company pays monthly") == set()
    assert _types("Passport details pending") == set()
    assert _types("Tax reference: outstanding") == set()
    assert "PERSON" in _types("customer: Jane Doe")
    assert "PASSPORT" in _types("passport no: X1234567")
