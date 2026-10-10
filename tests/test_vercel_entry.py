"""The Vercel entry point must start with good settings and explain bad ones.

[RULE: SEC-ERROR-HANDLING] A misconfigured deployment fails closed with a clear message.
Runs in subprocesses so module state never leaks between scenarios.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOOD_KEY = "XATwBG07UEbG4hltgkOhX43jNMtfKVBWhc5rAQPhsEk="

SCRIPT = """
import importlib.util, json
from fastapi.testclient import TestClient
spec = importlib.util.spec_from_file_location("index", r"{path}")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
client = TestClient(module.app)
response = client.get("/healthz")
print(json.dumps({{"status": response.status_code, "body": response.text}}))
"""


def _run(env: dict[str, str]) -> tuple[int, str]:
    base = {"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": "/tmp"}
    result = subprocess.run(
        [sys.executable, "-c", SCRIPT.format(path=ROOT / "api" / "index.py")],
        env={**base, **env}, capture_output=True, text=True, check=False, cwd="/tmp")
    import json
    last = [line for line in result.stdout.splitlines() if line.startswith("{")][-1]
    data = json.loads(last)
    return data["status"], data["body"]


def test_starts_with_demo_settings(tmp_path):
    status, body = _run({"FINRAG_ENVIRONMENT": "production", "FINRAG_DEMO_MODE": "true",
                         "FINRAG_MASTER_KEY": GOOD_KEY, "FINRAG_DATA_DIR": str(tmp_path)})
    assert status == 200 and '"ok"' in body


def test_missing_master_key_gives_clear_503_without_leaking(tmp_path):
    status, body = _run({"FINRAG_ENVIRONMENT": "production", "FINRAG_DEMO_MODE": "true",
                         "FINRAG_DATA_DIR": str(tmp_path)})
    assert status == 503
    assert "FINRAG_MASTER_KEY must be set" in body and "docs/DEPLOY_VERCEL.md" in body


def test_vercel_defaults_data_dir_to_tmp():
    # With VERCEL set and no FINRAG_DATA_DIR the app must start (it uses /tmp/finrag).
    status, _ = _run({"VERCEL": "1", "FINRAG_ENVIRONMENT": "production",
                      "FINRAG_DEMO_MODE": "true", "FINRAG_MASTER_KEY": GOOD_KEY})
    assert status == 200
