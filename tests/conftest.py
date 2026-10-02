"""Shared pytest fixtures: isolated settings, pipeline and principals."""

from __future__ import annotations

import io

import pytest

from finrag.config import Settings
from finrag.pipeline import FinRAGPipeline
from finrag.security.access import Principal
from finrag.security.crypto import generate_master_key


@pytest.fixture()
def settings(tmp_path) -> Settings:
    """Settings pointing at a temp data dir with a fresh master key."""
    return Settings(data_dir=tmp_path / "data", master_key=generate_master_key(),
                    rate_limit_per_minute=1000)


@pytest.fixture()
def pipeline(settings) -> FinRAGPipeline:
    """Pipeline using the offline (local) generator."""
    return FinRAGPipeline(settings)


@pytest.fixture()
def analyst() -> Principal:
    return Principal("alice", "acme", frozenset({"analyst"}))


@pytest.fixture()
def dpo() -> Principal:
    return Principal("dora", "acme", frozenset({"dpo", "analyst"}))


@pytest.fixture()
def viewer() -> Principal:
    return Principal("victor", "acme", frozenset({"viewer"}))


@pytest.fixture()
def xlsx_bytes() -> bytes:
    """A small synthetic P&L workbook."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "P&L"
    ws.append(["Line item", "FY2023", "FY2024"])
    ws.append(["Revenue", 1180000, 1452000])
    ws.append(["Operating expenses", 276000, 330000])
    ws.append(["Net income", 131000, 198000])
    ws.append(["Formula row", "=SUM(B2:B3)", None])
    contacts = wb.create_sheet("Contacts")
    contacts.append(["Role", "Email"])
    contacts.append(["CFO", "cfo.person@example.com"])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


INGEST_KW = {"lawful_basis": "legitimate_interests", "purpose": "financial_analysis"}
