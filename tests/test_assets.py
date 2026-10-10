"""Embedded copies of the web UI and demo samples (for hosts that package only Python).

[RULE: GDPR-ART25]  The demo works whatever files the host leaves out.
[RULE: SEC-FILE-UPLOAD] Embedded files are looked up by exact key (no traversal).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOOD_KEY = "XATwBG07UEbG4hltgkOhX43jNMtfKVBWhc5rAQPhsEk="

SCRIPT = """
import importlib.util
from fastapi.testclient import TestClient
spec = importlib.util.spec_from_file_location("index", "api/index.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
c = TestClient(module.app)
r = c.get("/", follow_redirects=False)
assert r.status_code in (302, 307) and r.headers["location"] == "/ui/", r.status_code
page = c.get("/ui/")
assert page.status_code == 200 and "text/html" in page.headers["content-type"], page.status_code
assert "FinRAG" in page.text
js = c.get("/ui/js/main.js")
assert js.status_code == 200 and "javascript" in js.headers["content-type"]
assert c.get("/ui/styles.css").headers["content-type"].startswith("text/css")
assert c.get("/ui/js/views/ask.js").status_code == 200
assert c.get("/ui/missing.js").status_code == 404
assert c.get("/ui/../finrag/config.py").status_code == 404
bare = c.get("/ui", follow_redirects=False)  # no redirect: hosts that drop the slash would loop
assert bare.status_code == 200 and "FinRAG" in bare.text, bare.status_code
csp = page.headers["content-security-policy"]
assert "script-src 'self'" in csp and "unsafe-inline" not in csp
token = c.post("/v1/demo/session").json()["api_key"]
docs = c.get("/v1/documents", headers={"X-API-Key": token}).json()
assert sorted(d["filename"] for d in docs) == [
    "board_notes.md", "quarterly_budget.xlsx", "sample_financials.csv"], docs
print("OK")
"""


def test_bundle_is_current():
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_assets.py"),
                             "--check"], capture_output=True, text=True, check=False)
    assert result.returncode == 0, "run: python scripts/build_assets.py"


def test_works_when_only_python_files_are_packaged(tmp_path):
    """Simulate a serverless bundle: Python modules only, no HTML/CSS/JS/sample files."""
    shutil.copytree(ROOT / "finrag", tmp_path / "finrag",
                    ignore=lambda _d, names: [n for n in names
                                              if n == "__pycache__"
                                              or (n.endswith((".html", ".css", ".js", ".svg",
                                                              ".csv", ".md", ".xlsx")))])
    (tmp_path / "api").mkdir()
    shutil.copy(ROOT / "api" / "index.py", tmp_path / "api" / "index.py")
    assert not list((tmp_path / "finrag").rglob("*.js"))
    assert not (tmp_path / "finrag" / "demo_data" / "quarterly_budget.xlsx").exists()
    result = subprocess.run(
        [sys.executable, "-c", SCRIPT],
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": "/tmp",
             "FINRAG_ENVIRONMENT": "production", "FINRAG_DEMO_MODE": "true",
             "FINRAG_MASTER_KEY": GOOD_KEY, "FINRAG_DATA_DIR": str(tmp_path / "store")},
        capture_output=True, text=True, check=False, cwd=tmp_path)
    assert result.returncode == 0, (result.stdout + result.stderr)[-1200:]
    assert "OK" in result.stdout
