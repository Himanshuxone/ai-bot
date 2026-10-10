"""
Vercel entry point.

Vercel's Python runtime serves the ASGI object named ``app`` from this file. All
requests are routed here by ``vercel.json``, including the web UI under ``/ui/``.

Configure the deployment with environment variables (see docs/DEPLOY_VERCEL.md):
``FINRAG_DEMO_MODE=true`` gives every visitor a private temporary workspace with sample
documents; ``FINRAG_DATA_DIR=/tmp/finrag`` is required because only /tmp is writable.

[RULE: GDPR-ART25] Public deployments run the isolated, offline demo mode.
"""

import sys
from pathlib import Path

# Make the repository root importable (this file lives in api/).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from finrag.api import app  # noqa: F401  (re-exported for the Vercel runtime)
