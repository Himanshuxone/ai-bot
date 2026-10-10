"""The Vercel entry point must start with good settings and explain bad ones.

[RULE: SEC-ERROR-HANDLING] A misconfigured deployment fails closed with a clear message.
Runs in subprocesses so module state never leaks between scenarios.
"""

from __future__ import annotations

import re
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


def test_invalid_setting_names_the_variable_but_not_its_value(tmp_path):
    status, body = _run({"FINRAG_ENVIRONMENT": "production", "FINRAG_DEMO_MODE": "true",
                         "FINRAG_MASTER_KEY": GOOD_KEY, "FINRAG_DATA_DIR": str(tmp_path),
                         "FINRAG_MAX_UPLOAD_BYTES": "not-a-number-xyz"})
    assert status == 503
    assert "FINRAG_MAX_UPLOAD_BYTES" in body and "not-a-number-xyz" not in body


def test_tolerates_stray_whitespace_quotes_and_capitals(tmp_path):
    status, _ = _run({"FINRAG_ENVIRONMENT": '"Production"\r', "FINRAG_DEMO_MODE": "True ",
                      "FINRAG_MASTER_KEY": GOOD_KEY + "\r\n", "FINRAG_DATA_DIR": str(tmp_path),
                      "FINRAG_MAX_UPLOAD_BYTES": " 2097152\r"})
    assert status == 200


def test_top_level_fastapi_app_is_visible_to_vercel():
    """Vercel checks api/index.py statically for a top-level ``app = FastAPI(...)``."""
    source = (ROOT / "api" / "index.py").read_text(encoding="utf-8")
    assert re.search(r"^app\s*=\s*FastAPI\(", source, re.MULTILINE)
    assert re.search(r"^from fastapi import FastAPI", source, re.MULTILINE)


def test_ui_api_and_demo_work_through_the_wrapper(tmp_path):
    script = SCRIPT.replace(
        'response = client.get("/healthz")',
        'redirect = client.get("/", follow_redirects=False)\n'
        'assert redirect.status_code in (302, 307) and redirect.headers["location"] == "/ui/"\n'
        'assert client.get("/ui/").status_code == 200\n'
        'assert client.get("/ui/js/main.js").status_code == 200\n'
        'token = client.post("/v1/demo/session").json()["api_key"]\n'
        'docs = client.get("/v1/documents", headers={{"X-API-Key": token}}).json()\n'
        'assert len(docs) == 3, docs\n'
        'assert "script-src" in client.get("/ui/").headers["content-security-policy"]\n'
        'response = client.get("/healthz")')
    result = subprocess.run(
        [sys.executable, "-c", script.format(path=ROOT / "api" / "index.py")],
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": "/tmp",
             "FINRAG_ENVIRONMENT": "production", "FINRAG_DEMO_MODE": "true",
             "FINRAG_MASTER_KEY": GOOD_KEY, "FINRAG_DATA_DIR": str(tmp_path)},
        capture_output=True, text=True, check=False, cwd="/tmp")
    assert result.returncode == 0, result.stderr[-800:]
    assert '"status": 200' in result.stdout


def test_vercel_defaults_data_dir_to_tmp():
    # With VERCEL set and no FINRAG_DATA_DIR the app must start (it uses /tmp/finrag).
    status, _ = _run({"VERCEL": "1", "FINRAG_ENVIRONMENT": "production",
                      "FINRAG_DEMO_MODE": "true", "FINRAG_MASTER_KEY": GOOD_KEY})
    assert status == 200
