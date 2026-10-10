"""
Locate the web UI and demo sample files, on disk or embedded.

The files in ``finrag/web`` and ``finrag/demo_data`` are the source of truth. Some hosts
(notably serverless platforms) package only Python modules, so ``finrag/_assets.py``
holds a compressed copy (regenerate with ``python scripts/build_assets.py``). Disk is
preferred; the embedded copy is used only when the files are absent.

``FINRAG_WEB_DIR`` can point at another UI folder (or a missing one, to test the
embedded path).

[RULE: SEC-FILE-UPLOAD]  Embedded files are looked up by exact key: no path traversal.
[RULE: GDPR-ART25]       The offline demo keeps working whatever the host packages.
"""

from __future__ import annotations

import base64
import mimetypes
import os
import zlib
from pathlib import Path

from finrag import _assets

WEB_DIR = Path(os.environ.get("FINRAG_WEB_DIR") or Path(__file__).parent / "web")
DEMO_DIR = Path(__file__).parent / "demo_data"

_MEDIA_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
}


def _decode(blob: str) -> bytes:
    return zlib.decompress(base64.b64decode(blob))


def media_type(name: str) -> str:
    """Content type for a UI file."""
    suffix = Path(name).suffix.lower()
    return (_MEDIA_TYPES.get(suffix) or mimetypes.guess_type(name)[0]
            or "application/octet-stream")


def web_dir() -> Path | None:
    """The UI folder if a real UI is on disk (it must contain index.html), else ``None``.

    An empty or partial folder (which a stripped-down deployment bundle can leave behind)
    does not count, so the embedded copy is used instead.
    """
    return WEB_DIR if (WEB_DIR / "index.html").is_file() else None


def embedded_web_available() -> bool:
    """True when a bundled copy of the UI exists."""
    return "index.html" in _assets.WEB


def embedded_web_file(rel: str) -> bytes | None:
    """Bytes of an embedded UI file, or ``None``. ``rel`` must match a bundled key exactly."""
    blob = _assets.WEB.get(rel)
    return _decode(blob) if blob is not None else None


def demo_sample(name: str) -> bytes:
    """Bytes of a demo sample document (disk first, then the embedded copy)."""
    path = DEMO_DIR / name
    if path.is_file():
        return path.read_bytes()
    blob = _assets.DEMO.get(name)
    if blob is None:
        raise FileNotFoundError(name)
    return _decode(blob)
