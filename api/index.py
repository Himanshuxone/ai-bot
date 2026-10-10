"""
Vercel entry point.

Vercel's Python runtime serves the ASGI object named ``app`` from this file. All
requests are routed here by ``vercel.json``, including the web UI under ``/ui/``.

Configure the deployment with environment variables (see docs/DEPLOY_VERCEL.md):
``FINRAG_DEMO_MODE=true`` gives every visitor a private temporary workspace with sample
documents; ``FINRAG_MASTER_KEY`` is required in production.

Two safeguards for serverless hosting:

* On Vercel only ``/tmp`` is writable, so the data folder defaults there.
* If the real app cannot start (usually a missing or mistyped environment variable) a
  tiny fallback app answers every request with HTTP 503 and says *what* is wrong, instead
  of Vercel's opaque "function failed" page. The full traceback goes to the function logs.
  The message only contains our own configuration errors, never secret values.

[RULE: GDPR-ART25]   Public deployments run the isolated, offline demo mode.
[RULE: SEC-ERROR-HANDLING] Fail closed with a clear, non-leaking message.
"""

import json
import os
import sys
import traceback
from pathlib import Path

# Make the repository root importable (this file lives in api/).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if os.environ.get("VERCEL"):
    os.environ.setdefault("FINRAG_DATA_DIR", "/tmp/finrag")

try:
    from finrag.api import app
except Exception as exc:  # startup failure: report it clearly instead of crashing
    traceback.print_exc()  # full details go to Vercel's function logs
    _reason = f"{type(exc).__name__}: {str(exc).splitlines()[0][:200] if str(exc) else ''}"

    async def app(scope, receive, send):  # type: ignore[no-redef]
        """Fallback ASGI app: explain that startup failed (HTTP 503)."""
        if scope["type"] == "lifespan":
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        elif scope["type"] == "http":
            body = json.dumps({
                "detail": "FinRAG failed to start",
                "reason": _reason,
                "fix": ("Check the FINRAG_* environment variables for the Production "
                        "environment (see docs/DEPLOY_VERCEL.md) and redeploy."),
            }).encode()
            await send({"type": "http.response.start", "status": 503,
                        "headers": [(b"content-type", b"application/json"),
                                    (b"cache-control", b"no-store")]})
            await send({"type": "http.response.body", "body": body})
