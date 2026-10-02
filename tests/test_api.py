"""HTTP API tests (auth, headers, upload, query)."""

from __future__ import annotations

import importlib
import json

import pytest
from fastapi.testclient import TestClient

from finrag.security.access import hash_api_key
from finrag.security.crypto import generate_master_key


@pytest.fixture()
def client(tmp_path, monkeypatch):
    keys = [
        {"key_sha256": hash_api_key("analyst-key"), "principal": "alice", "tenant": "acme",
         "roles": ["analyst"]},
        {"key_sha256": hash_api_key("viewer-key"), "principal": "vic", "tenant": "acme",
         "roles": ["viewer"]},
    ]
    keys_file = tmp_path / "keys.json"
    keys_file.write_text(json.dumps(keys))
    monkeypatch.setenv("FINRAG_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("FINRAG_MASTER_KEY", generate_master_key())
    monkeypatch.setenv("FINRAG_API_KEYS_FILE", str(keys_file))
    from finrag import config
    config.get_settings.cache_clear()
    import finrag.api as api
    importlib.reload(api)
    yield TestClient(api.app)
    config.get_settings.cache_clear()


def test_requires_auth(client):
    assert client.post("/v1/query", json={"question": "hi"}).status_code == 401
    assert client.post("/v1/query", json={"question": "hi"},
                       headers={"X-API-Key": "wrong"}).status_code == 401


def test_security_headers(client):
    response = client.get("/healthz")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-AI-Generated"] == "true"


def test_transparency_public(client):
    body = client.get("/v1/transparency").json()
    assert "intended_purpose" in body["model_card"]
    assert "rights" in body["privacy_notice"]


def test_upload_and_query(client):
    files = {"file": ("fin.csv", b"Item,FY2024\nRevenue,1452000\nNet income,198000\n",
                      "text/csv")}
    data = {"lawful_basis": "legitimate_interests", "purpose": "financial_analysis"}
    up = client.post("/v1/documents", files=files, data=data,
                     headers={"X-API-Key": "analyst-key"})
    assert up.status_code == 201, up.text
    answer = client.post("/v1/query", json={"question": "What was net income?"},
                         headers={"X-API-Key": "analyst-key"}).json()
    assert "198000" in answer["answer"] and answer["label"]["ai_generated"]


def test_viewer_cannot_upload(client):
    files = {"file": ("fin.csv", b"a,b\n1,2\n", "text/csv")}
    data = {"lawful_basis": "legitimate_interests", "purpose": "financial_analysis"}
    response = client.post("/v1/documents", files=files, data=data,
                           headers={"X-API-Key": "viewer-key"})
    assert response.status_code == 403


def test_bad_file_rejected(client):
    files = {"file": ("x.pdf", b"not a pdf", "application/pdf")}
    data = {"lawful_basis": "legitimate_interests", "purpose": "financial_analysis"}
    response = client.post("/v1/documents", files=files, data=data,
                           headers={"X-API-Key": "analyst-key"})
    assert response.status_code == 422
