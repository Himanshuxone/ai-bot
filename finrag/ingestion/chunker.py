"""
Structure-aware chunking.

* Text sections are split on paragraph boundaries into ~``chunk_size`` chunks
  with a small character overlap so sentences straddling a boundary survive.
* Table sections are split by rows, and **every chunk repeats the column
  header**, so a retrieved chunk such as "Row 14 | Line item: EBITDA | FY2024:
  310.00" is always interpretable on its own. This matters a lot for financial
  sheets where the meaning of a number depends on its column.

[RULE: EUAIA-ART10]  Each chunk carries provenance (source file + location)
                     used for citations and audit.
[RULE: GDPR-ART5-1D] Header repetition prevents mis-attributing figures to the
                     wrong period/column (accuracy of derived information).
"""

from __future__ import annotations

from dataclasses import dataclass

from finrag.ingestion.loaders import Section


@dataclass
class Chunk:
    """A retrievable unit of text with provenance."""

    text: str
    location: str


def _split_text(text: str, size: int, overlap: int) -> list[str]:
    """Greedy paragraph packing with overlap; hard-splits oversized paragraphs."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    pieces: list[str] = []
    for para in paragraphs:
        # Hard-split paragraphs longer than the chunk size.
        while len(para) > size:
            cut = para.rfind(" ", 0, size)
            cut = cut if cut > size // 2 else size
            pieces.append(para[:cut])
            para = para[cut:].lstrip()
        if para:
            pieces.append(para)

    chunks: list[str] = []
    current = ""
    for piece in pieces:
        if current and len(current) + len(piece) + 2 > size:
            chunks.append(current)
            # Carry the tail of the previous chunk forward as overlap.
            tail = current[-overlap:] if overlap else ""
            current = f"{tail}\n\n{piece}" if tail else piece
        else:
            current = f"{current}\n\n{piece}" if current else piece
    if current:
        chunks.append(current)
    return chunks


def _split_table(section: Section, size: int) -> list[str]:
    """Group table rows into chunks, prefixing each with the column header."""
    prefix = f"Columns: {section.header}\n"
    chunks: list[str] = []
    current: list[str] = []
    length = len(prefix)
    for row in section.rows:
        if current and length + len(row) + 1 > size:
            chunks.append(prefix + "\n".join(current))
            current, length = [], len(prefix)
        current.append(row)
        length += len(row) + 1
    if current:
        chunks.append(prefix + "\n".join(current))
    return chunks


def chunk_sections(sections: list[Section], size: int, overlap: int) -> list[Chunk]:
    """Convert loader sections into retrievable chunks."""
    out: list[Chunk] = []
    for section in sections:
        if section.kind == "table":
            for text in _split_table(section, size):
                out.append(Chunk(text=text, location=section.location))
        else:
            for text in _split_text(section.text, size, overlap):
                out.append(Chunk(text=text, location=section.location))
    return out
