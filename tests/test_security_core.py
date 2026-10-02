"""Crypto, auth, rate limiting and store tests. [RULE: SEC-CRYPTO] [RULE: SEC-AUTHN]"""

from __future__ import annotations

import pytest

from finrag.config import Environment, Settings
from finrag.retrieval.store import validate_tenant
from finrag.security.access import APIKeyAuthenticator, RateLimiter, hash_api_key
from finrag.security.crypto import DecryptionError, Encryptor, KeyConfigurationError, KeyRing


def test_production_requires_master_key(tmp_path):
    with pytest.raises(KeyConfigurationError):
        KeyRing.from_settings(Settings(environment=Environment.PRODUCTION, master_key=None,
                                       data_dir=tmp_path))


def test_short_master_key_rejected(tmp_path):
    with pytest.raises(KeyConfigurationError):
        KeyRing.from_settings(Settings(master_key="c2hvcnQ=", data_dir=tmp_path))


def test_tamper_detected():
    enc = Encryptor(b"x" * 32)
    token = bytearray(enc.encrypt(b"secret"))
    token[20] ^= 1
    with pytest.raises(DecryptionError):
        enc.decrypt(bytes(token))


def test_api_key_auth():
    auth = APIKeyAuthenticator([{"key_sha256": hash_api_key("good"), "principal": "a",
                                 "tenant": "t", "roles": ["viewer"]}])
    assert auth.authenticate("good").tenant == "t"
    assert auth.authenticate("bad") is None
    assert auth.authenticate(None) is None


def test_rate_limiter():
    limiter = RateLimiter(per_minute=2)
    assert limiter.allow("u") and limiter.allow("u")
    assert not limiter.allow("u")
    assert limiter.allow("other")


@pytest.mark.parametrize("tenant", ["../etc", "A", "", "a/b", "x" * 80])
def test_tenant_validation(tenant):
    with pytest.raises(ValueError):
        validate_tenant(tenant)
