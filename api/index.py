"""
Vercel entry point.

Vercel's Python runtime looks for a top-level ``app = FastAPI(...)`` in this file (it
checks the source statically, so the assignment must be visible at module level). That
``app`` is a thin wrapper: the real application from ``finrag.api`` is mounted inside it.
``vercel.json`` sets ``"framework": "fastapi"``, so Vercel sends every request here and keeps
the original path. Do not add a ``rewrites`` entry: a rewrite to ``/api/index`` replaces the
path, and every route then answers 404.

Configure the deployment with environment variables (see docs/DEPLOY_VERCEL.md):
``FINRAG_DEMO_MODE=true`` gives every visitor a private temporary workspace with sample
documents; ``FINRAG_MASTER_KEY`` is required in production.

Two safeguards for serverless hosting:

* On Vercel only ``/tmp`` is writable, so the data folder defaults there.
* If the real app cannot start (usually a missing or mistyped environment variable) every
  request gets HTTP 503 with a message saying *what* is wrong, instead of Vercel's opaque
  "function failed" page. The full traceback goes to the function logs. The message only
  contains our own configuration errors, never secret values.

[RULE: GDPR-ART25]   Public deployments run the isolated, offline demo mode.
[RULE: SEC-ERROR-HANDLING] Fail closed with a clear, non-leaking message.
"""

import os
import sys
import traceback
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse, RedirectResponse

# Make the repository root importable (this file lives in api/).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if os.environ.get("VERCEL"):
    os.environ.setdefault("FINRAG_DATA_DIR", "/tmp/finrag")

# Top-level FastAPI instance: required by Vercel's static entrypoint detection.
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/api/index", include_in_schema=False)
@app.get("/api", include_in_schema=False)
async def entry_alias() -> RedirectResponse:
    """The function's own address: send people who open it to the web app."""
    return RedirectResponse("/ui/")


class PathGuard:
    """Normalise the request path and report what the platform actually sent.

    Some hosts hand a rewritten function the *function's* address instead of the browser's
    address. Every route would then miss and the app would answer 404 for everything. This
    removes a leading ``/api/index`` prefix, and adds ``X-Finrag-Path`` (the path as the app
    saw it, before and after) so a mismatch can be diagnosed with a plain ``curl -I``.
    The values are only the request path; nothing secret.
    """

    PREFIX = "/api/index"

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.inner(scope, receive, send)
            return
        seen = scope.get("path", "")
        path = seen
        if path.startswith(self.PREFIX + "/"):
            path = path[len(self.PREFIX):]
            scope = dict(scope, path=path, raw_path=path.encode())
        note = f"seen={seen!r} used={path!r} root={scope.get('root_path', '')!r}"

        async def tagged(message):
            if message["type"] == "http.response.start":
                message = dict(message)
                message["headers"] = [*message.get("headers", []),
                                      (b"x-finrag-path", note.encode("ascii", "replace"))]
            await send(message)

        await self.inner(scope, receive, tagged)


app.add_middleware(PathGuard)


def _describe(exc: Exception) -> str:
    """Short, safe description of a startup failure: names variables, never values."""
    errors = getattr(exc, "errors", None)
    if callable(errors):  # pydantic ValidationError from the settings
        try:
            parts = []
            for item in errors():
                location = ".".join(str(p) for p in item.get("loc", ()))
                name = f"FINRAG_{location.upper()}" if location else "settings"
                # Only the rule that failed ("msg"), never the offending input value.
                parts.append(f"{name}: {item.get('msg', 'invalid')}")
            return ("Invalid settings: " + "; ".join(parts))[:400]
        except Exception:  # fall back to the generic description below
            pass
    first_line = str(exc).splitlines()[0][:200] if str(exc) else ""
    return f"{type(exc).__name__}: {first_line}"


try:
    from finrag.api import app as _finrag_app
except Exception as exc:  # startup failure: report it clearly instead of crashing
    traceback.print_exc()  # full details go to Vercel's function logs
    _reason = _describe(exc)

    @app.api_route("/{path:path}",
                   methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
    async def startup_failed(path: str) -> JSONResponse:
        """Explain that the application could not start (HTTP 503)."""
        return JSONResponse(
            {"detail": "FinRAG failed to start",
             "reason": _reason,
             "fix": ("Check the FINRAG_* environment variables for the Production "
                     "environment (see docs/DEPLOY_VERCEL.md) and redeploy.")},
            status_code=503, headers={"Cache-Control": "no-store"})
else:
    app.mount("/", _finrag_app)
