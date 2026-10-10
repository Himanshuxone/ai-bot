"""
FastAPI HTTP server for FinRAG.

Run (development)::

    uvicorn finrag.api:app --host 127.0.0.1 --port 8000

Deploy behind a TLS-terminating reverse proxy; the app itself never serves
plain HTTP to the internet.

[RULE: SEC-AUTHN]           API key (X-API-Key header) required on every
                            endpoint except /healthz and public transparency info.
[RULE: SEC-AUTHZ]           Permissions enforced inside the pipeline.
[RULE: SEC-HEADERS]         Security headers on every response.
[RULE: SEC-ERROR-HANDLING]  Generic error bodies; no stack traces.
[RULE: OWASP-LLM10]         Request-body size cap + per-principal rate limit.
[RULE: EUAIA-ART50]         AI disclosure header and fields on every answer.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from finrag import demo
from finrag.config import get_settings
from finrag.generation.llm import LLMUnavailableError
from finrag.governance import gdpr, transparency
from finrag.ingestion.loaders import UnsupportedDocumentError
from finrag.pipeline import FinRAGPipeline, RateLimitExceeded
from finrag.security.access import (
    AccessDenied,
    APIKeyAuthenticator,
    Permission,
    Principal,
    RateLimiter,
)

logger = logging.getLogger("finrag.api")
settings = get_settings()

# [RULE: SEC-ERROR-HANDLING] Interactive docs are disabled in production to
# reduce the attack surface.
app = FastAPI(
    title="FinRAG",
    version="1.0.0",
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None,
    openapi_url=None if settings.is_production else "/openapi.json",
)

pipeline = FinRAGPipeline(settings)

if settings.api_keys_file:
    authenticator = APIKeyAuthenticator.from_file(settings.api_keys_file)
elif settings.is_production and not settings.demo_mode:
    # [RULE: SEC-AUTHN] Fail closed: production without credentials config.
    raise RuntimeError("FINRAG_API_KEYS_FILE must be configured in production")
else:
    authenticator = APIKeyAuthenticator([])  # dev: every request is rejected
    logger.warning("No API keys configured; all authenticated endpoints will return 401.")

# Public demo mode: per-visitor temporary workspaces (see finrag/demo.py).
demo_auth = (demo.DemoAuthenticator(pipeline.keys.demo_key, settings.demo_session_minutes)
             if settings.demo_mode else None)
# [RULE: OWASP-LLM10] Limit how fast new demo workspaces can be created.
_demo_session_limiter = RateLimiter(20)
_seeded_workspaces: set[str] = set()  # workspaces already seeded by this instance


# ----------------------------------------------------------------- middleware
@app.middleware("http")
async def security_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
    """Reject oversized bodies early and add security headers."""
    # [RULE: OWASP-LLM10] [RULE: SEC-FILE-UPLOAD] Content-Length cap (+64 KiB
    # for multipart overhead). Streaming bodies are capped again on read.
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > settings.max_upload_bytes + 65536:
        return JSONResponse({"detail": "request too large"}, status_code=413)
    response = await call_next(request)
    # [RULE: SEC-HEADERS]
    response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    # The JSON API gets the strictest policy. The browser UI (static files under
    # /ui) may load only same-origin scripts, styles and images: no inline code,
    # no third-party hosts, no framing (also limits XSS impact on the API key).
    if request.url.path.startswith("/ui"):
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; font-src 'self'; manifest-src 'self'; base-uri 'none'; "
            "form-action 'none'; frame-ancestors 'none'")
    else:
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    # [RULE: EUAIA-ART50] Machine-readable disclosure that responses are AI-assisted.
    response.headers["X-AI-Generated"] = "true"
    return response


# ------------------------------------------------------------ error handling
@app.exception_handler(AccessDenied)
async def _denied(_: Request, __: AccessDenied) -> JSONResponse:
    return JSONResponse({"detail": "forbidden"}, status_code=403)


@app.exception_handler(RateLimitExceeded)
async def _rate(_: Request, __: RateLimitExceeded) -> JSONResponse:
    return JSONResponse({"detail": "rate limit exceeded"}, status_code=429,
                        headers={"Retry-After": "60"})


@app.exception_handler(UnsupportedDocumentError)
async def _bad_doc(_: Request, exc: UnsupportedDocumentError) -> JSONResponse:
    # Messages are authored by us (no user data echoed back).
    return JSONResponse({"detail": str(exc)}, status_code=422)


@app.exception_handler(gdpr.ComplianceError)
async def _compliance(_: Request, exc: gdpr.ComplianceError) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=422)


@app.exception_handler(LLMUnavailableError)
async def _llm(_: Request, __: LLMUnavailableError) -> JSONResponse:
    return JSONResponse({"detail": "answer service temporarily unavailable"}, status_code=503)


@app.exception_handler(Exception)
async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
    # [RULE: SEC-ERROR-HANDLING] Log type only (message could contain data).
    logger.error("unhandled error: %s", type(exc).__name__)
    return JSONResponse({"detail": "internal error"}, status_code=500)


# ------------------------------------------------------------- dependencies
def get_principal(x_api_key: Annotated[str | None, Header()] = None) -> Principal:
    """Authenticate the caller from the ``X-API-Key`` header."""
    principal = authenticator.authenticate(x_api_key)
    if principal is None and demo_auth is not None:
        principal = demo_auth.authenticate(x_api_key)
        if principal is not None and principal.tenant not in _seeded_workspaces:
            # Serverless instances come and go: restore the samples if this instance has
            # never seen the workspace (or its temporary disk was recycled).
            if not pipeline._ctx(principal.tenant).store.documents:
                demo.seed_samples(pipeline, principal)
            _seeded_workspaces.add(principal.tenant)
    if principal is None:
        raise HTTPException(status_code=401, detail="unauthorised")
    return principal


PrincipalDep = Annotated[Principal, Depends(get_principal)]


# ------------------------------------------------------------------- models
class QueryRequest(BaseModel):
    """Body for POST /v1/query."""

    # [RULE: SEC-INPUT-VALIDATION] Length bounds enforced by pydantic as well.
    question: str = Field(min_length=1, max_length=settings.max_query_chars)
    reidentify: bool = False


class SubjectRequest(BaseModel):
    """Body for GDPR data-subject requests."""

    identifier: str = Field(min_length=3, max_length=256)
    format: str = Field(default="json", pattern="^(json|csv)$")


# --------------------------------------------------------------- endpoints
@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness probe (no auth, no data)."""
    return {"status": "ok"}


@app.get("/v1/me")
def me(principal: PrincipalDep) -> dict[str, object]:
    """Who am I and what may I do? Used by the web UI to show only allowed actions.

    [RULE: SEC-AUTHN] Doubles as the API-key check at sign-in.
    [RULE: SEC-AUTHZ] The UI hides actions the role lacks; the server still enforces
                      every permission, so hiding is convenience, not security.
    """
    return {
        "principal": principal.principal_id,
        "tenant": principal.tenant,
        "roles": sorted(principal.roles),
        "permissions": sorted(p.value for p in principal.permissions),
        "provider": settings.llm_provider.value,
        "model": pipeline.generator.model_name,
        "demo": demo_auth is not None and principal.tenant.startswith("demo-"),
        "options": {
            "lawful_bases": [b.value for b in gdpr.LawfulBasis],
            "purposes": [p.value for p in gdpr.Purpose],
            "art9_conditions": [c.value for c in gdpr.Art9Condition],
            "extensions": [".pdf", ".xlsx", ".csv", ".txt", ".md"],
            "max_upload_bytes": settings.max_upload_bytes,
            "max_query_chars": settings.max_query_chars,
            "default_retention_days": settings.default_retention_days,
        },
    }


@app.get("/v1/demo")
def demo_info() -> dict[str, object]:
    """Tell the web UI whether the public demo is available. Public by design."""
    return {"enabled": demo_auth is not None,
            "session_minutes": settings.demo_session_minutes}


@app.post("/v1/demo/session")
def demo_session() -> dict[str, object]:
    """Start a private demo workspace with sample documents and return its session key.

    [RULE: OWASP-LLM08] Each call creates a new isolated workspace.
    [RULE: OWASP-LLM10] Rate limited; old workspaces are pruned.
    """
    if demo_auth is None:
        raise HTTPException(status_code=404, detail="not found")
    if not _demo_session_limiter.allow("sessions"):
        raise RateLimitExceeded("too many demo sessions")
    token = demo_auth.issue()
    principal = demo_auth.authenticate(token)
    assert principal is not None
    demo.prune_workspaces(pipeline, settings.demo_max_workspaces)
    demo.seed_samples(pipeline, principal)
    _seeded_workspaces.add(principal.tenant)
    return {"api_key": token, "expires_in": demo_auth.ttl_seconds}


@app.get("/v1/transparency")
def transparency_info() -> dict[str, object]:
    """Model card, AI disclosure, privacy notice. Public by design.

    [RULE: EUAIA-ART13] [RULE: EUAIA-ART50] [RULE: GDPR-ART13]
    """
    return {
        "model_card": transparency.model_card(pipeline.generator.model_name,
                                              settings.llm_provider.value),
        "privacy_notice": gdpr.privacy_notice(settings),
    }


@app.post("/v1/documents", status_code=201)
async def upload_document(
    principal: PrincipalDep,
    file: Annotated[UploadFile, File()],
    lawful_basis: Annotated[str, Form()],
    purpose: Annotated[str, Form()],
    retention_days: Annotated[int | None, Form()] = None,
    consent_reference: Annotated[str | None, Form(max_length=128)] = None,
    special_category_condition: Annotated[str | None, Form()] = None,
) -> dict[str, object]:
    """Upload a financial document (PDF, XLSX, CSV, TXT, MD)."""
    # Read at most max+1 bytes so an oversized stream is detected without
    # buffering it entirely in memory.
    data = await file.read(settings.max_upload_bytes + 1)
    report = pipeline.ingest(
        principal, file.filename or "document", data,
        lawful_basis=lawful_basis, purpose=purpose, retention_days=retention_days,
        consent_reference=consent_reference,
        special_category_condition=special_category_condition,
    )
    return report.__dict__


@app.get("/v1/documents")
def list_documents(principal: PrincipalDep) -> list[dict[str, object]]:
    """List document metadata in the caller's tenant."""
    return pipeline.list_documents(principal)


@app.delete("/v1/documents/{doc_id}")
def delete_document(principal: PrincipalDep, doc_id: str) -> dict[str, object]:
    """Hard-delete a document (Art. 17 at document level)."""
    if not doc_id.isalnum() or len(doc_id) > 64:
        raise HTTPException(status_code=422, detail="invalid document id")
    if not pipeline.delete_document(principal, doc_id):
        raise HTTPException(status_code=404, detail="not found")
    return {"deleted": doc_id}


@app.post("/v1/query")
def query(principal: PrincipalDep, body: QueryRequest) -> dict[str, object]:
    """Ask a question; returns a guardrailed, cited, AI-labelled answer."""
    return pipeline.ask(principal, body.question, reidentify=body.reidentify).to_dict()


@app.post("/v1/gdpr/erasure")
def gdpr_erasure(principal: PrincipalDep, body: SubjectRequest) -> dict[str, object]:
    """Art. 17 erasure of one identifier across the tenant."""
    return pipeline.erase_subject(principal, body.identifier)


@app.post("/v1/gdpr/export")
def gdpr_export(principal: PrincipalDep, body: SubjectRequest) -> PlainTextResponse:
    """Art. 15 / 20 export of excerpts that mention an identifier."""
    content = pipeline.export_subject(principal, body.identifier, body.format)
    media = "application/json" if body.format == "json" else "text/csv"
    return PlainTextResponse(content, media_type=media)


@app.post("/v1/admin/purge")
def purge(principal: PrincipalDep) -> dict[str, object]:
    """Enforce retention: delete expired documents (Art. 5(1)(e))."""
    return {"purged": pipeline.purge_expired(principal)}


@app.get("/v1/audit/verify")
def audit_verify(principal: PrincipalDep) -> dict[str, object]:
    """Verify the tamper-evident audit chain."""
    return pipeline.verify_audit(principal)


@app.get("/v1/gdpr/ropa")
def ropa(principal: PrincipalDep) -> dict[str, object]:
    """Record of processing activities (Art. 30)."""
    principal.require(Permission.VIEW_AUDIT)
    return gdpr.records_of_processing(settings)


# ------------------------------------------------------------------- web UI
WEB_DIR = Path(__file__).parent / "web"

if settings.web_ui and WEB_DIR.is_dir():
    # [RULE: SEC-HEADERS] Served with the UI-specific CSP set in the middleware.
    app.mount("/ui", StaticFiles(directory=WEB_DIR, html=True), name="ui")

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        """Send browsers to the web app."""
        return RedirectResponse("/ui/")
