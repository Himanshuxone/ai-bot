"""Public demo mode: isolated temporary workspaces with sample documents.

[RULE: OWASP-LLM08]  Visitors never see each other's data.
[RULE: SEC-AUTHN]    Demo tokens are signed and expire.
[RULE: GDPR-ART44]   Demo mode refuses to run with an external AI provider.
"""

from __future__ import annotations

import importlib
import shutil

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from finrag.config import Settings
from finrag.demo import DemoAuthenticator
from finrag.security.crypto import generate_master_key


def _client(tmp_path, monkeypatch, demo: bool = True, **env):
    monkeypatch.setenv("FINRAG_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("FINRAG_MASTER_KEY", generate_master_key())
    monkeypatch.setenv("FINRAG_ENVIRONMENT", "production")  # as deployed: fail closed
    monkeypatch.delenv("FINRAG_API_KEYS_FILE", raising=False)
    monkeypatch.setenv("FINRAG_DEMO_MODE", "true" if demo else "false")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    from finrag import config
    config.get_settings.cache_clear()
    import finrag.api as api
    importlib.reload(api)
    return TestClient(api.app), api, config


@pytest.fixture()
def demo_client(tmp_path, monkeypatch):
    client, api, config = _client(tmp_path, monkeypatch)
    yield client, api
    config.get_settings.cache_clear()


def _session(client) -> str:
    response = client.post("/v1/demo/session")
    assert response.status_code == 200, response.text
    return response.json()["api_key"]


def _h(token: str) -> dict[str, str]:
    return {"X-API-Key": token}


# ------------------------------------------------------------------ tokens
def test_token_roundtrip_and_tamper_checks():
    auth = DemoAuthenticator(b"k" * 32, 60)
    token = auth.issue()
    principal = auth.authenticate(token)
    assert principal and principal.tenant.startswith("demo-") and principal.roles == {"analyst"}
    prefix, tenant, expiry, sig = token.split(".")
    assert auth.authenticate(f"{prefix}.demo-000000000000.{expiry}.{sig}") is None  # other tenant
    assert auth.authenticate(f"{prefix}.{tenant}.{int(expiry) + 999}.{sig}") is None  # new expiry
    assert DemoAuthenticator(b"x" * 32, 60).authenticate(token) is None  # wrong key
    for junk in (None, "", "abc", "fd1.a.b", "fd1.../etc.1.2", "x" * 500):
        assert auth.authenticate(junk) is None


def test_expired_token_rejected():
    auth = DemoAuthenticator(b"k" * 32, -1)
    assert auth.authenticate(auth.issue()) is None


def test_demo_mode_requires_offline_provider():
    with pytest.raises(ValidationError):
        Settings(demo_mode=True, llm_provider="anthropic")
    assert Settings(demo_mode=True).llm_provider.value == "offline"


# --------------------------------------------------------------------- API
def test_demo_session_gives_private_workspace_with_samples(demo_client):
    client, _ = demo_client
    assert client.get("/v1/demo").json()["enabled"] is True
    token = _session(client)
    me = client.get("/v1/me", headers=_h(token)).json()
    assert me["demo"] is True and me["tenant"].startswith("demo-") and me["provider"] == "offline"
    docs = client.get("/v1/documents", headers=_h(token)).json()
    assert {d["filename"] for d in docs} == {
        "sample_financials.csv", "board_notes.md", "quarterly_budget.xlsx"}
    answer = client.post("/v1/query", json={"question": "What was net income in FY2024?"},
                         headers=_h(token)).json()
    assert "198,000" in answer["answer"] and answer["citations"]
    # personal data in the Excel/Markdown samples is masked, not stored
    excel = next(d for d in docs if d["filename"] == "quarterly_budget.xlsx")
    assert excel["pii_counts"].get("EMAIL") == 2


def test_visitors_are_isolated(demo_client):
    client, _ = demo_client
    a, b = _session(client), _session(client)
    files = {"file": ("secret.txt", b"Project Falcon revenue was 777,000", "text/plain")}
    data = {"lawful_basis": "legitimate_interests", "purpose": "financial_analysis"}
    assert client.post("/v1/documents", files=files, data=data, headers=_h(a)).status_code == 201
    names_a = {d["filename"] for d in client.get("/v1/documents", headers=_h(a)).json()}
    names_b = {d["filename"] for d in client.get("/v1/documents", headers=_h(b)).json()}
    assert "secret.txt" in names_a and "secret.txt" not in names_b
    answer = client.post("/v1/query", json={"question": "Project Falcon revenue"},
                         headers=_h(b)).json()
    assert "777" not in answer["answer"]


def test_restores_samples_after_instance_recycle(demo_client):
    client, api = demo_client
    token = _session(client)
    tenant = client.get("/v1/me", headers=_h(token)).json()["tenant"]
    # simulate a new serverless instance with an empty temporary disk
    api.pipeline._tenants.pop(tenant, None)
    shutil.rmtree(api.pipeline.data_dir / "tenants" / tenant)
    api._seeded_workspaces.clear()
    assert len(client.get("/v1/documents", headers=_h(token)).json()) == 3


def test_old_workspaces_are_pruned(tmp_path, monkeypatch):
    client, api, config = _client(tmp_path, monkeypatch, FINRAG_DEMO_MAX_WORKSPACES="2")
    try:
        for _ in range(5):
            _session(client)
        left = [p for p in (api.pipeline.data_dir / "tenants").iterdir()]
        assert len(left) <= 3  # newest workspace is added after pruning
    finally:
        config.get_settings.cache_clear()


def test_demo_endpoints_inert_when_disabled(tmp_path, monkeypatch):
    client, api, config = _client(tmp_path, monkeypatch, demo=False,
                                  FINRAG_ENVIRONMENT="development")
    try:
        assert client.get("/v1/demo").json()["enabled"] is False
        assert client.post("/v1/demo/session").status_code == 404
        assert client.get("/v1/me", headers=_h("fd1.demo-000000000000.9999999999.x")).status_code == 401
    finally:
        config.get_settings.cache_clear()


def test_demo_mode_runs_in_production_without_keys_file(demo_client):
    client, _ = demo_client
    assert client.get("/healthz").status_code == 200
    assert client.get("/v1/me").status_code == 401  # no key, no access
    assert client.get("/docs").status_code == 404  # interactive docs off in production
