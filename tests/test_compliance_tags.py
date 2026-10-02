"""Every ``[RULE: X]`` tag in the code must refer to a registered rule.

[RULE: GDPR-ART5-2] Prevents unverifiable or mistyped compliance claims.
"""

from __future__ import annotations

import re
from pathlib import Path

from finrag.compliance import RULES

ROOT = Path(__file__).resolve().parents[1]
TAG = re.compile(r"\[RULE:\s*([A-Z0-9-]+)\]")


def _tags() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for path in (ROOT / "finrag").rglob("*.py"):
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            for rule in TAG.findall(line):
                found.setdefault(rule, []).append(f"{path.relative_to(ROOT)}:{lineno}")
    return found


def test_all_tags_registered():
    unknown = {k: v for k, v in _tags().items() if k not in RULES}
    assert not unknown, f"unregistered rule ids: {unknown}"


def test_every_rule_implemented_somewhere():
    tags = _tags()
    missing = [r for r in RULES if r not in tags]
    assert not missing, f"rules with no implementation tag: {missing}"


def test_compliance_matrix_is_fresh():
    """docs/COMPLIANCE_MATRIX.md must match the current code tags."""
    import subprocess
    import sys

    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "compliance_report.py"),
                             "--check"], capture_output=True, text=True)
    assert result.returncode == 0, "run: python scripts/compliance_report.py"
