"""Loader validation tests. [RULE: SEC-FILE-UPLOAD]"""

from __future__ import annotations

import io
import zipfile

import pytest

from finrag.ingestion.chunker import chunk_sections
from finrag.ingestion.loaders import UnsupportedDocumentError, load_document, sanitize_filename


def test_sanitize_filename_blocks_traversal():
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert sanitize_filename("..\\..\\win.ini") == "win.ini"
    assert sanitize_filename("re<po>rt.pdf") == "re_po_rt.pdf"


def test_rejects_unknown_extension(settings):
    with pytest.raises(UnsupportedDocumentError):
        load_document("evil.exe", b"MZ....", settings)


def test_rejects_fake_pdf(settings):
    with pytest.raises(UnsupportedDocumentError, match="magic"):
        load_document("report.pdf", b"not a pdf at all", settings)


def test_rejects_oversize(settings):
    settings.max_upload_bytes = 10
    with pytest.raises(UnsupportedDocumentError, match="exceeds"):
        load_document("a.txt", b"x" * 11, settings)


def test_rejects_binary_text(settings):
    with pytest.raises(UnsupportedDocumentError):
        load_document("a.csv", b"a,b\x00c", settings)


def test_rejects_macro_workbook(settings):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("[Content_Types].xml", "<x/>")
        zf.writestr("xl/workbook.xml", "<x/>")
        zf.writestr("xl/vbaProject.bin", b"macro")
    with pytest.raises(UnsupportedDocumentError, match="macro"):
        load_document("book.xlsx", buffer.getvalue(), settings)


def test_rejects_zip_bomb(settings):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "<x/>")
        zf.writestr("xl/workbook.xml", "<x/>")
        zf.writestr("xl/worksheets/sheet1.xml", "0" * 5_000_000)
    with pytest.raises(UnsupportedDocumentError, match="zip bomb|compression"):
        load_document("bomb.xlsx", buffer.getvalue(), settings)


def test_xlsx_formulas_not_evaluated(settings, xlsx_bytes):
    doc = load_document("pl.xlsx", xlsx_bytes, settings)
    sheet = doc.sections[0]
    assert sheet.kind == "table" and "Line item" in sheet.header
    assert any("Net income" in r and "198,000" in r for r in sheet.rows)
    # Workbook saved by openpyxl has no cached value -> formula cell is empty,
    # and the formula text itself is never executed or emitted.
    assert not any("SUM(" in r for r in sheet.rows)


def test_table_chunks_repeat_header(settings):
    rows = "\n".join(f"Item{i},{i * 1000}" for i in range(400))
    doc = load_document("big.csv", f"Name,Amount\n{rows}".encode(), settings)
    chunks = chunk_sections(doc.sections, 500, 50)
    assert len(chunks) > 1
    assert all(c.text.startswith("Columns: Name | Amount") for c in chunks)
