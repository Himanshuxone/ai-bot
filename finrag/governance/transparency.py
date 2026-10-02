"""
EU AI Act transparency, human oversight and AI-output labelling.

Risk classification (deployer's assessment, see docs/COMPLIANCE.md):
FinRAG answers questions about an organisation's own financial documents. It
is **not** used to evaluate the creditworthiness of natural persons, to
price life/health insurance, or for employment decisions (Annex III), and
such requests are blocked by the guardrails. It is therefore treated as a
limited-risk system subject to Art. 50 transparency obligations, while
voluntarily applying several high-risk controls (logging, human oversight,
accuracy monitoring) as good practice.

[RULE: EUAIA-ART50]  Users are told they interact with AI; every answer carries
                     a machine-readable "AI-generated" label.
[RULE: EUAIA-ART13]  Model card / instructions for use (purpose, limits).
[RULE: EUAIA-ART14]  Human-oversight flag and reasons on every answer.
[RULE: EUAIA-ART6]   Documented intended purpose and excluded high-risk uses.
[RULE: EUAIA-ART4]   Guidance for staff (AI literacy) exposed via the API/docs.
[RULE: FIN-NO-ADVICE] Standard financial disclaimer.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

AI_DISCLOSURE = (
    "You are interacting with an AI system. Answers are generated automatically from "
    "your organisation's documents and may contain errors. Verify important figures "
    "against the cited sources."
)

FINANCIAL_DISCLAIMER = (
    "This is informational analysis of the supplied documents, not investment, tax, "
    "legal or credit advice, and it must not be used as the sole basis for decisions "
    "about individuals."
)

INTENDED_PURPOSE = (
    "Question answering, summarisation and figure look-up over financial documents "
    "(statements, ledgers, budgets, reports) uploaded by authorised staff."
)

EXCLUDED_USES = [
    "Creditworthiness assessment or credit scoring of natural persons (Annex III 5(b))",
    "Risk assessment and pricing for life or health insurance (Annex III 5(c))",
    "Recruitment, promotion, termination or task allocation decisions (Annex III 4)",
    "Social scoring, manipulation, or exploitation of vulnerabilities (Art. 5)",
    "Fully automated decisions with legal or similarly significant effects (GDPR Art. 22)",
]


def model_card(model_name: str, provider: str) -> dict[str, Any]:
    """Instructions for use / model card served at ``/v1/transparency``."""
    # [RULE: EUAIA-ART13] [RULE: EUAIA-ART4]
    return {
        "system": "FinRAG",
        "intended_purpose": INTENDED_PURPOSE,
        "excluded_uses": EXCLUDED_USES,
        "risk_classification": "limited risk (Art. 50) - high-risk uses blocked by design",
        "model": {"name": model_name, "provider": provider},
        "how_it_works": "Retrieval-augmented generation: relevant pseudonymised excerpts are "
                        "retrieved locally and the model answers only from them, with "
                        "citations.",
        "known_limitations": [
            "Text is extracted from PDFs without OCR; scanned images are not read.",
            "Complex multi-page tables may be split across chunks.",
            "Calculations by the model can be wrong; unverified figures are flagged.",
            "PII detection is pattern-based and may miss unusual identifiers.",
        ],
        "accuracy_measures": ["citation validation", "numeric cross-check against sources",
                              "confidence score with human-review threshold"],
        "human_oversight": "Answers with low confidence, unverified figures, invalid "
                           "citations or advice-seeking questions are flagged "
                           "requires_human_review=true. Reviewers can consult the cited "
                           "sources and the audit trail.",
        "user_guidance": [
            "Always check cited sources for figures used in reports or decisions.",
            "Do not upload documents outside the approved purposes.",
            "Report suspected errors or misuse to the system owner.",
        ],
        "ai_disclosure": AI_DISCLOSURE,
    }


def label_output(model_name: str, requires_review: bool) -> dict[str, Any]:
    """Machine-readable provenance label attached to every answer.

    [RULE: EUAIA-ART50] Outputs are marked as AI-generated.
    """
    return {
        "ai_generated": True,
        "generator": "FinRAG",
        "model": model_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "requires_human_review": requires_review,
    }
