"""
Command-line interface.

Examples::

    python -m finrag.cli keygen
    python -m finrag.cli hash-key            # create an API key + its hash
    python -m finrag.cli ingest samples/sample_financials.csv \
        --lawful-basis legitimate_interests --purpose financial_analysis
    python -m finrag.cli ask "What was revenue in FY2024?"
    python -m finrag.cli erase "jane.doe@example.com"
    python -m finrag.cli audit-verify

The CLI acts as a local operator principal. Its roles are configurable with
``--roles`` so that least privilege still applies on the command line.

[RULE: SEC-AUTHZ]     CLI calls go through the same permission checks.
[RULE: SEC-SECRETS]   ``keygen`` prints a key once; it is never stored by FinRAG.
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
from pathlib import Path
from typing import Any

from finrag.security.access import Principal, hash_api_key
from finrag.security.crypto import generate_master_key


def _principal(args: argparse.Namespace) -> Principal:
    """Build the local operator principal from CLI flags."""
    return Principal(principal_id=f"cli:{args.user}", tenant=args.tenant,
                     roles=frozenset(r.strip() for r in args.roles.split(",") if r.strip()))


def main(argv: list[str] | None = None) -> int:
    """Entry point; returns a process exit code."""
    parser = argparse.ArgumentParser(prog="finrag", description="Secure financial RAG")
    parser.add_argument("--tenant", default="default", help="tenant id (default: default)")
    parser.add_argument("--user", default="operator", help="operator name for the audit log")
    parser.add_argument("--roles", default="analyst",
                        help="comma-separated roles: viewer, analyst, dpo, admin")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("keygen", help="generate a new FINRAG_MASTER_KEY")
    sub.add_parser("hash-key", help="generate an API key and its SHA-256 hash")

    p_ing = sub.add_parser("ingest", help="ingest a document")
    p_ing.add_argument("path", type=Path)
    p_ing.add_argument("--lawful-basis", required=True)
    p_ing.add_argument("--purpose", required=True)
    p_ing.add_argument("--retention-days", type=int)
    p_ing.add_argument("--consent-reference")
    p_ing.add_argument("--special-category-condition")

    p_ask = sub.add_parser("ask", help="ask a question")
    p_ask.add_argument("question")
    p_ask.add_argument("--reidentify", action="store_true",
                       help="show original values (requires dpo role)")

    sub.add_parser("list", help="list documents")
    p_del = sub.add_parser("delete", help="delete a document")
    p_del.add_argument("doc_id")
    p_erase = sub.add_parser("erase", help="GDPR Art. 17 erasure of an identifier")
    p_erase.add_argument("identifier")
    p_exp = sub.add_parser("export", help="GDPR Art. 15/20 export for an identifier")
    p_exp.add_argument("identifier")
    p_exp.add_argument("--format", choices=["json", "csv"], default="json")
    sub.add_parser("purge", help="delete documents past retention")
    sub.add_parser("audit-verify", help="verify the audit log chain")
    sub.add_parser("transparency", help="print the model card / AI disclosure")

    args = parser.parse_args(argv)

    # Commands that need no pipeline (and therefore no master key).
    if args.command == "keygen":
        print(generate_master_key())
        return 0
    if args.command == "hash-key":
        key = secrets.token_urlsafe(32)
        print(json.dumps({"api_key (give to client, shown once)": key,
                          "key_sha256 (store in keys file)": hash_api_key(key)}, indent=2))
        return 0

    from finrag.config import get_settings
    from finrag.governance import transparency
    from finrag.pipeline import FinRAGPipeline

    from finrag.generation.llm import LLMUnavailableError
    from finrag.governance.gdpr import ComplianceError
    from finrag.ingestion.loaders import UnsupportedDocumentError
    from finrag.pipeline import RateLimitExceeded
    from finrag.security.access import AccessDenied

    pipeline = FinRAGPipeline(get_settings())
    try:
        return _run(args, pipeline, transparency)
    except (AccessDenied, ComplianceError, UnsupportedDocumentError, RateLimitExceeded,
            LLMUnavailableError) as exc:
        # [RULE: SEC-ERROR-HANDLING] Expected failures: short message, no traceback.
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _run(args: argparse.Namespace, pipeline: Any, transparency: Any) -> int:
    """Dispatch a pipeline-backed sub-command."""
    principal = _principal(args)
    if args.command == "ingest":
        report = pipeline.ingest(
            principal, args.path.name, args.path.read_bytes(),
            lawful_basis=args.lawful_basis, purpose=args.purpose,
            retention_days=args.retention_days, consent_reference=args.consent_reference,
            special_category_condition=args.special_category_condition)
        print(json.dumps(report.__dict__, indent=2))
    elif args.command == "ask":
        answer = pipeline.ask(principal, args.question, reidentify=args.reidentify)
        print(answer.answer)
        print("\nSources:")
        for c in answer.citations:
            print(f"  [{c.label}] {c.filename} ({c.location}) score={c.score}")
        print(f"\nConfidence: {answer.confidence}  Human review required: "
              f"{answer.requires_human_review} {answer.review_reasons or ''}")
        print(f"\n{answer.ai_disclosure}\n{answer.disclaimer}")
    elif args.command == "list":
        print(json.dumps(pipeline.list_documents(principal), indent=2))
    elif args.command == "delete":
        print(json.dumps({"deleted": pipeline.delete_document(principal, args.doc_id)}))
    elif args.command == "erase":
        print(json.dumps(pipeline.erase_subject(principal, args.identifier), indent=2))
    elif args.command == "export":
        print(pipeline.export_subject(principal, args.identifier, args.format))
    elif args.command == "purge":
        print(json.dumps({"purged": pipeline.purge_expired(principal)}, indent=2))
    elif args.command == "audit-verify":
        print(json.dumps(pipeline.verify_audit(principal), indent=2))
    elif args.command == "transparency":
        print(json.dumps(transparency.model_card(pipeline.generator.model_name,
                                                 pipeline.settings.llm_provider.value),
                         indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
