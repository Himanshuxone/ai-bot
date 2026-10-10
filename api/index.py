"""
Vercel entry point.

Vercel's Python runtime looks for a top-level ``app = FastAPI(...)`` in this file (it
checks the source statically, so the assignment must be visible at module level). That
``app`` is a thin wrapper: the real application from ``finrag.api`` is mounted inside it.
All requests are routed here by ``vercel.json``, including the web UI under ``/ui/``.

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
from fastapi.responses import JSONResponse

# Make the repository root importable (this file lives in api/).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if os.environ.get("VERCEL"):
    os.environ.setdefault("FINRAG_DATA_DIR", "/tmp/finrag")

# Top-level FastAPI instance: required by Vercel's static entrypoint detection.
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

try:
    from finrag.api import app as _finrag_app
except Exception as exc:  # startup failure: report it clearly instead of crashing
    traceback.print_exc()  # full details go to Vercel's function logs
    _first_line = str(exc).splitlines()[0][:200] if str(exc) else ""
    _reason = f"{type(exc).__name__}: {_first_line}"

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
