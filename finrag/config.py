"""
Central configuration.

All settings come from environment variables (prefix ``FINRAG_``) or a local
``.env`` file, never from hard-coded values.

[RULE: SEC-SECRETS]  Secrets (master key, API keys) are read from the
                     environment / secret manager only and are wrapped in
                     ``SecretStr`` so they are masked in ``repr()`` and logs.
[RULE: GDPR-ART25]   Defaults are privacy-protective: the offline LLM provider
                     is the default, retention is finite, PII redaction is on.
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    """Deployment environment. Production enables stricter fail-closed checks."""

    DEVELOPMENT = "development"
    PRODUCTION = "production"


class LLMProvider(str, Enum):
    """Which answer generator to use."""

    # Local, extractive answerer: no data leaves the machine.
    OFFLINE = "offline"
    # Anthropic Claude via the official SDK (only redacted text is sent).
    ANTHROPIC = "anthropic"


class Settings(BaseSettings):
    """Typed application settings loaded from ``FINRAG_*`` environment variables."""

    model_config = SettingsConfigDict(env_prefix="FINRAG_", env_file=".env", extra="ignore")

    # ----------------------------------------------------------------- runtime
    environment: Environment = Environment.DEVELOPMENT
    data_dir: Path = Path("./data")

    # [RULE: SEC-CRYPTO] [RULE: GDPR-ART32] Root key from which all encryption /
    # pseudonymisation sub-keys are derived with HKDF. Must be a urlsafe-base64
    # 32-byte value (generate with ``python -m finrag.cli keygen``).
    master_key: SecretStr | None = None

    # ------------------------------------------------------------------- LLM
    # [RULE: GDPR-ART25] [RULE: GDPR-ART44] Offline by default so no document
    # content is transferred to a third-party processor unless explicitly enabled.
    llm_provider: LLMProvider = LLMProvider.OFFLINE
    anthropic_model: str = "claude-opus-5-5"
    # Effort controls thinking depth / cost on Claude; "medium" is a sensible
    # balance for document Q&A.
    anthropic_effort: str = "medium"
    # [RULE: OWASP-LLM10] Hard cap on generated tokens per answer.
    max_output_tokens: int = 4000

    # ------------------------------------------------------------- ingestion
    # [RULE: SEC-FILE-UPLOAD] [RULE: OWASP-LLM10] Resource limits for uploads.
    max_upload_bytes: int = 25 * 1024 * 1024  # 25 MiB
    max_pdf_pages: int = 500
    max_sheet_rows: int = 50_000
    max_xlsx_uncompressed_bytes: int = 200 * 1024 * 1024  # zip-bomb guard
    max_xlsx_compression_ratio: float = 100.0
    chunk_size_chars: int = 1200
    chunk_overlap_chars: int = 150

    # ------------------------------------------------------------- retrieval
    top_k: int = 6
    min_relevance: float = 0.05

    # ----------------------------------------------------------------- query
    # [RULE: OWASP-LLM10] [RULE: SEC-INPUT-VALIDATION]
    max_query_chars: int = 2000
    rate_limit_per_minute: int = 30

    # --------------------------------------------------------------- privacy
    # [RULE: GDPR-ART5-1E] Default retention for uploaded documents.
    default_retention_days: int = 90
    # [RULE: EUAIA-ART26] Deployers must keep logs for at least six months.
    audit_retention_days: int = 365

    # ------------------------------------------------------- human oversight
    # [RULE: EUAIA-ART14] Answers below this confidence are flagged for review.
    review_confidence_threshold: float = 0.55

    # -------------------------------------------------------------- API auth
    # [RULE: SEC-AUTHN] Path to a JSON file of hashed API keys (see README).
    api_keys_file: Path | None = None

    @field_validator("anthropic_effort")
    @classmethod
    def _valid_effort(cls, value: str) -> str:
        # [RULE: SEC-INPUT-VALIDATION] Reject unknown effort levels early.
        allowed = {"low", "medium", "high", "xhigh", "max"}
        if value not in allowed:
            raise ValueError(f"anthropic_effort must be one of {sorted(allowed)}")
        return value

    @property
    def is_production(self) -> bool:
        """True when running with production (fail-closed) semantics."""
        return self.environment is Environment.PRODUCTION


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton (cached)."""
    return Settings()


__all__ = ["Environment", "LLMProvider", "Settings", "get_settings"]
