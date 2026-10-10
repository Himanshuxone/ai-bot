"""
Bundle the web UI and demo sample files into ``finrag/_assets.py``.

Why: serverless hosts such as Vercel reliably package Python modules but may leave out
other files (HTML, CSS, JavaScript, sample documents). FinRAG therefore ships a copy of
those files *inside* Python code and uses it whenever the files are not on disk. The
normal files stay the source of truth: edit them, then regenerate this module.

    python scripts/build_assets.py           # regenerate finrag/_assets.py
    python scripts/build_assets.py --check   # exit 1 if the bundle is out of date (CI)

[RULE: GDPR-ART25]  The demo keeps working (isolated, offline) whatever the host packages.
"""

from __future__ import annotations

import argparse
import base64
import importlib.util
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "finrag"
OUT = PKG / "_assets.py"
SOURCES = {"WEB": PKG / "web", "DEMO": PKG / "demo_data"}

HEADER = '''"""
GENERATED FILE - do not edit. Run ``python scripts/build_assets.py`` to regenerate.

Compressed copies of finrag/web/** (``WEB``) and finrag/demo_data/* (``DEMO``), keyed by
path relative to those folders. Used only when the files are missing from disk (see
finrag/assets.py). Values are zlib-compressed, base64-encoded bytes.
"""

'''


def collect() -> dict[str, dict[str, bytes]]:
    """Read every source file, keyed by posix path relative to its folder."""
    found: dict[str, dict[str, bytes]] = {}
    for name, folder in SOURCES.items():
        found[name] = {p.relative_to(folder).as_posix(): p.read_bytes()
                       for p in sorted(folder.rglob("*")) if p.is_file()}
    return found


def render(found: dict[str, dict[str, bytes]]) -> str:
    """Render the module source."""
    parts = [HEADER]
    for name, files in found.items():
        parts.append(f"{name} = {{\n")
        for rel, data in files.items():
            blob = base64.b64encode(zlib.compress(data, 9)).decode("ascii")
            parts.append(f'    "{rel}": (\n')
            for i in range(0, len(blob), 96):
                parts.append(f'        "{blob[i:i + 96]}"\n')
            parts.append("    ),\n")
        parts.append("}\n\n")
    return "".join(parts).rstrip("\n") + "\n"


def decode(blob: str) -> bytes:
    """Inverse of the encoding used by ``render``."""
    return zlib.decompress(base64.b64decode(blob))


def is_current() -> bool:
    """True when the committed bundle decodes to exactly the files on disk."""
    if not OUT.exists():
        return False
    spec = importlib.util.spec_from_file_location("_assets_check", OUT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name, files in collect().items():
        bundled = {rel: decode(blob) for rel, blob in getattr(module, name).items()}
        if bundled != files:
            return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail if the bundle is stale")
    args = parser.parse_args()
    if args.check:
        if is_current():
            return 0
        print("finrag/_assets.py is stale; run: python scripts/build_assets.py", file=sys.stderr)
        return 1
    OUT.write_text(render(collect()), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KiB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
