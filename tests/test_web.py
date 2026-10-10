"""Web UI serving, headers and static-safety tests (no browser needed).

[RULE: SEC-HEADERS]  The UI gets a strict same-origin CSP; the API keeps default-src 'none'.
[RULE: OWASP-LLM05]  UI code must never use HTML-parsing sinks for untrusted text.
[RULE: SEC-AUTHN]    /v1/me needs a valid key.
"""

from __future__ import annotations

import importlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from finrag.security.access import hash_api_key
from finrag.security.crypto import generate_master_key

WEB = Path(__file__).resolve().parents[1] / "finrag" / "web"


def _make_client(tmp_path, monkeypatch, **extra_env):
    keys = [
        {"key_sha256": hash_api_key("viewer-key"), "principal": "vic", "tenant": "acme",
         "roles": ["viewer"]},
        {"key_sha256": hash_api_key("dpo-key"), "principal": "dora", "tenant": "acme",
         "roles": ["dpo", "viewer"]},
    ]
    keys_file = tmp_path / "keys.json"
    keys_file.write_text(json.dumps(keys))
    monkeypatch.setenv("FINRAG_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("FINRAG_MASTER_KEY", generate_master_key())
    monkeypatch.setenv("FINRAG_API_KEYS_FILE", str(keys_file))
    for key, value in extra_env.items():
        monkeypatch.setenv(key, value)
    from finrag import config
    config.get_settings.cache_clear()
    from finrag import api
    importlib.reload(api)
    return TestClient(api.app), config


@pytest.fixture()
def client(tmp_path, monkeypatch):
    test_client, config = _make_client(tmp_path, monkeypatch)
    yield test_client
    config.get_settings.cache_clear()


def test_root_redirects_to_ui_and_files_are_served(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code in (302, 307) and response.headers["location"] == "/ui/"
    page = client.get("/ui/")
    assert page.status_code == 200 and "text/html" in page.headers["content-type"]
    assert client.get("/ui/js/main.js").status_code == 200
    assert client.get("/ui/styles.css").status_code == 200


def test_ui_csp_is_strict_and_api_csp_unchanged(client):
    csp = client.get("/ui/").headers["content-security-policy"]
    assert "script-src 'self'" in csp and "style-src 'self'" in csp
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
    assert "frame-ancestors 'none'" in csp and "connect-src 'self'" in csp
    assert client.get("/healthz").headers["content-security-policy"].startswith("default-src 'none'")


def test_me_requires_key_and_reflects_role(client):
    assert client.get("/v1/me").status_code == 401
    viewer = client.get("/v1/me", headers={"X-API-Key": "viewer-key"}).json()
    assert viewer["permissions"] == ["query"] and viewer["tenant"] == "acme"
    assert ".pdf" in viewer["options"]["extensions"]
    assert "legitimate_interests" in viewer["options"]["lawful_bases"]
    dpo = client.get("/v1/me", headers={"X-API-Key": "dpo-key"}).json()
    assert "reidentify" in dpo["permissions"] and "query" in dpo["permissions"]
    assert "ingest" not in dpo["permissions"]  # segregation of duties


def test_web_ui_can_be_disabled(tmp_path, monkeypatch):
    test_client, config = _make_client(tmp_path, monkeypatch, FINRAG_WEB_UI="false")
    try:
        assert test_client.get("/ui/").status_code == 404
        assert test_client.get("/healthz").status_code == 200
    finally:
        config.get_settings.cache_clear()


# ---------------------------------------------------------------- static scan
JS_FILES = sorted(WEB.rglob("*.js"))
FORBIDDEN_JS = [
    (r"\.innerHTML\b", "innerHTML"), (r"\.outerHTML\b", "outerHTML"),
    (r"insertAdjacentHTML", "insertAdjacentHTML"), (r"document\.write", "document.write"),
    (r"\beval\s*\(", "eval"), (r"new\s+Function\b", "new Function"),
    (r"setTimeout\s*\(\s*[\"'`]", "string setTimeout"),
    (r"localStorage\.setItem\([^)]*(key|token|answer|question)", "sensitive data in localStorage"),
]


def test_ui_javascript_exists():
    assert len(JS_FILES) >= 6


@pytest.mark.parametrize("path", JS_FILES, ids=lambda p: p.name)
def test_no_unsafe_patterns_in_js(path):
    source = path.read_text(encoding="utf-8")
    for pattern, name in FORBIDDEN_JS:
        assert not re.search(pattern, source), f"{path.name} uses forbidden pattern: {name}"


def test_index_html_has_no_inline_code_or_third_party_hosts():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"\son[a-z]+\s*=", html), "inline event handler"
    assert not re.search(r"\sstyle\s*=", html), "inline style attribute"
    assert not re.search(r"javascript:", html, re.IGNORECASE)
    for script in re.findall(r"<script\b[^>]*>", html):
        assert "src=" in script, "inline <script>"
    assert not re.search(r"""(src|href)=["']https?://""", html), "third-party resource"
    assert 'name="viewport"' in html and "user-scalable" not in html  # zoom stays enabled


def test_no_inline_styles_set_via_attribute_in_js():
    for path in JS_FILES:
        assert not re.search(r"""["']style["']\s*:""", path.read_text(encoding="utf-8")), path.name


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
@pytest.mark.parametrize("path", JS_FILES, ids=lambda p: p.name)
def test_js_syntax_is_valid(path):
    result = subprocess.run(["node", "--input-type=module", "--check"],
                            input=path.read_text(encoding="utf-8"), capture_output=True, text=True,
                            check=False)
    assert result.returncode == 0, result.stderr
