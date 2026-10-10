"""
Start FinRAG with the web UI for local use, with ready-made demo users.

    python scripts/demo.py                  # http://127.0.0.1:8000
    python scripts/demo.py --port 9000
    FINRAG_LLM_PROVIDER=anthropic ANTHROPIC_API_KEY=... python scripts/demo.py

On first run this creates, under ``data/demo/``:

* ``master.key``  - the encryption master key, so stored data survives restarts;
* ``keys.json``   - SHA-256 hashes of three demo API keys (analyst, viewer, dpo);
* ``credentials.txt`` - the three plaintext demo keys, for you to copy into the UI.

Everything lives under ``data/`` which is git-ignored. This is a development
convenience: do NOT use these keys or this launcher in production.

[RULE: SEC-SECRETS]  Keys are generated randomly, written with mode 0600, never
                     committed, and only hashes go in ``keys.json``.
[RULE: SEC-AUTHN]    Demo keys are 256-bit random values, not guessable passwords.
[RULE: GDPR-ART25]   Binds to localhost by default; offline LLM unless you opt in.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from finrag.security.access import hash_api_key  # noqa: E402
from finrag.security.crypto import generate_master_key  # noqa: E402

DEMO_USERS = [
    ("analyst", "alice-analyst", ["analyst"]),
    ("viewer", "victor-viewer", ["viewer"]),
    # A DPO who must see original values also needs permission to ask questions, so the
    # demo DPO holds "dpo" + "viewer". The roles stay separate: no ingest rights.
    ("dpo", "dora-dpo", ["dpo", "viewer"]),
]


def write_private(path: Path, content: str) -> None:
    """Write a file readable only by the current user."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(content)


def prepare(data_dir: Path) -> dict[str, str]:
    """Create master key and demo users if missing; return role -> plaintext key."""
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    master = data_dir / "master.key"
    keys_file = data_dir / "keys.json"
    creds = data_dir / "credentials.txt"
    if not master.exists():
        write_private(master, generate_master_key())
    if not (keys_file.exists() and creds.exists()):
        plain: dict[str, str] = {}
        entries = []
        for role, principal, roles in DEMO_USERS:
            plain[role] = secrets.token_urlsafe(32)
            entries.append({"key_sha256": hash_api_key(plain[role]), "principal": principal,
                            "tenant": "demo", "roles": roles})
        write_private(keys_file, json.dumps(entries, indent=2))
        write_private(creds, "\n".join(f"{role}: {key}" for role, key in plain.items()) + "\n")
    return dict(line.split(": ", 1) for line in creds.read_text().splitlines() if ": " in line)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    data_dir = ROOT / "data" / "demo"
    keys = prepare(data_dir)

    # Settings are read when the app module is imported, so set them first.
    os.environ.setdefault("FINRAG_DATA_DIR", str(data_dir))
    os.environ.setdefault("FINRAG_MASTER_KEY", (data_dir / "master.key").read_text().strip())
    os.environ.setdefault("FINRAG_API_KEYS_FILE", str(data_dir / "keys.json"))

    provider = os.environ.get("FINRAG_LLM_PROVIDER", "offline")
    print("\nFinRAG demo")
    print(f"  Open:      http://{args.host}:{args.port}/")
    print(f"  AI mode:   {provider}"
          + ("  (answers are quoted from documents; set FINRAG_LLM_PROVIDER=anthropic and "
             "ANTHROPIC_API_KEY for written answers)" if provider == "offline" else ""))
    print("  Sign in with one of these API keys (also saved in data/demo/credentials.txt):")
    for role, key in keys.items():
        print(f"    {role:8} {key}")
    print("  Sample files to upload: samples/sample_financials.csv, samples/board_notes.md\n")

    import uvicorn

    uvicorn.run("finrag.api:app", host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
