"""Asserted Path A e2e: existing tables -> reflect/profile -> compile -> backbone.

Drives ``scripts/bootstrap_from_tables.main``: seeds an 'existing' Spark table from
a corpus CSV, reflects (+ profiles) it into a UMF, compiles, then runs the backbone
over the persisted artifacts. Profile enrichment is the recommended default, so the
compiled suite carries data-derived expectations rather than schema-only checks.
"""

# Bootstrap Path A coverage.
# @covers US-023-AC1
# @covers US-023-AC4
# @covers US-023-AC5

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import bootstrap_from_tables

# Spark's py4j gateway leaves transient JVM-connection sockets to be GC'd lazily;
# under ``filterwarnings = error`` those surface as unraisable ResourceWarnings at an
# unrelated test boundary. They are pure session-teardown noise (the backbone itself
# closes every artifact handle), so downgrade unclosed-socket/file ResourceWarnings
# for this Spark-driving e2e module.
pytestmark = [
    pytest.mark.spark_only,
    pytest.mark.filterwarnings("ignore::ResourceWarning"),
]

FIXTURES = Path(__file__).resolve().parent / "fixtures"
MEMBER_CSV = FIXTURES / "member.raw.csv"


def test_main_profile_enriched_backbone_green(tmp_path: Path, spark_session) -> None:  # noqa: ANN001
    """Path A (profile-enriched default) compiles + runs the backbone to green.

    Requests ``spark_session`` so the backbone adopts the fixture-owned session
    (cleanly torn down at session scope; the demo never stops what it adopts).
    """
    out = tmp_path / "out"
    rc = bootstrap_from_tables.main(
        [
            "--table",
            "member",
            "--seed-from",
            f"member={MEMBER_CSV}",
            "--out",
            str(out),
            "--backend",
            "spark",
        ]
    )
    assert rc == 0, "Path A profile-enriched backbone must pass end-to-end"

    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["source"] == "tables"
    assert manifest["profile_enriched"] is True

    # Profile enrichment => the compiled suite is the profiler's expectation list
    # (carries the 'profiling' provenance), not the bare baseline.
    suite = json.loads((out / "validation" / "member.suite.json").read_text())
    provenance = {e.get("meta", {}).get("generated_from") for e in suite}
    assert "profiling" in provenance


def test_main_schema_only_backbone_green(tmp_path: Path, spark_session) -> None:  # noqa: ANN001
    """Path A with --no-profile emits the schema-only baseline suite + still runs."""
    out = tmp_path / "out"
    rc = bootstrap_from_tables.main(
        [
            "--table",
            "member",
            "--seed-from",
            f"member={MEMBER_CSV}",
            "--no-profile",
            "--out",
            str(out),
            "--backend",
            "spark",
        ]
    )
    assert rc == 0

    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["profile_enriched"] is False
    suite = json.loads((out / "validation" / "member.suite.json").read_text())
    provenance = {e.get("meta", {}).get("generated_from") for e in suite}
    assert provenance == {"baseline"}
