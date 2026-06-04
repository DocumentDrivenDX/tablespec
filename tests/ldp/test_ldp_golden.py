"""Golden test of the generated LDP SQL for the multi-table fixture (PROTOTYPE).

Asserts the emitted LDP SQL is byte-stable against committed goldens under
``tests/golden/ldp/`` for a representative pipeline: a snapshot+pk table (member),
an incremental+pk table with APPLY CHANGES (claims), a keyless-incremental append
table (events), and a gold join (enriched). Regenerate with UPDATE_LDP_GOLDEN=1.

JVM-free, no Databricks execution -- this pins the generated text, not runtime
behaviour (see the package docstring for the honest scope).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from tablespec.ldp import generate_ldp_project
from tablespec.models.umf import UMF

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "ldp"
GOLDEN_DIR = Path(__file__).parent.parent / "golden" / "ldp"
_TABLES = ["member", "claims", "events", "enriched"]


def _umfs() -> list[UMF]:
    return [
        UMF(**yaml.safe_load((FIXTURE_DIR / f"{t}.umf.yaml").read_text()))
        for t in _TABLES
    ]


def test_ldp_project_matches_golden() -> None:
    files = generate_ldp_project(_umfs(), dialect="spark")

    if os.environ.get("UPDATE_LDP_GOLDEN"):
        for rel, content in files.items():
            dest = GOLDEN_DIR / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content)

    # Every generated file has a committed golden and matches it byte-for-byte.
    expected_files = sorted(
        str(p.relative_to(GOLDEN_DIR)) for p in GOLDEN_DIR.rglob("*.sql")
    )
    assert sorted(files) == expected_files, (
        "generated LDP file set drifted from the golden set:\n"
        f"  generated: {sorted(files)}\n  golden:    {expected_files}"
    )
    for rel, content in sorted(files.items()):
        golden = GOLDEN_DIR / rel
        assert golden.exists(), f"missing LDP golden: {golden}"
        assert content == golden.read_text(), (
            f"LDP golden mismatch for {rel} "
            f"(regenerate with UPDATE_LDP_GOLDEN=1 if intended)"
        )
