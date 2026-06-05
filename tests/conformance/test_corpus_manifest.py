"""Corpus-manifest validation (Phase 2).

Proves the unified conformance corpus (tests/conformance/corpus/cases.yaml +
registry.py) is well-formed and fully materialized at the Phase-2 boundary:

  * every case has a known kind + tags drawn from the published taxonomy;
  * every INGEST case's UMF, ordered batches, and committed golden exist, and the
    golden parses as deterministic canonical JSON;
  * every GOLD case's source UMFs + CSVs exist, and the non-FK gold cases COMPILE
    through ``generate_sql_plan`` (so the generator path the manifest pins is
    actually exercised), while the FK case is well-formed for the dbt
    relationships schema-test tier;
  * gold cases are declared ``pending`` (their executed goldens are produced by
    the later SQLPlanGeneratorGold phase) -- this test asserts they are declared,
    not silently missing.

These checks run in the JVM-free lane (no Spark, no dbt CLI). They guard the
corpus contract that the executed engine legs depend on.
"""

from __future__ import annotations

import json

import pytest
import yaml

from tablespec.models.umf import UMF
from tablespec.schemas.sql_generator import generate_sql_plan
from tests.conformance.corpus.registry import (
    Case,
    gold_cases,
    ingest_cases,
    load_cases,
)

pytestmark = [pytest.mark.no_spark]

# The published tag taxonomy (acceptance doc Section 4.2). Every tag on a case
# MUST be one of these (a typo'd tag would silently break tag-based selection).
_KNOWN_TAGS = {
    "types",
    "decimal",
    "datetime",
    "tz",
    "incremental",
    "snapshot",
    "pk",
    "nopk",
    "multibatch",
    "gold",
}

# Generator path -> a substring its emitted SQL MUST contain. Proves the manifest
# pins a path the source UMFs actually drive (not a mislabeled case).
_GOLD_GENERATOR_MARKER = {
    "_generate_join_step": "JOIN",
    "_generate_pivot_join": "PIVOT",
    "_generate_unpivot_base_view": "UNPIVOT",
    "_generate_pre_aggregation_views": "_AGG",
    "_generate_member_universe_view": "UNION",
    "_generate_first_record_join": "ROW_NUMBER",
}

_INGEST_CASES = ingest_cases()
_GOLD_CASES = gold_cases()


def test_corpus_loads_and_is_nonempty() -> None:
    cases = load_cases()
    assert cases, "the conformance corpus is empty"
    # ids are unique (the registry also guards this, assert it visibly here).
    ids = [c.id for c in cases]
    assert len(ids) == len(set(ids)), f"duplicate case ids: {ids}"


@pytest.mark.parametrize("case", load_cases(), ids=[c.id for c in load_cases()])
def test_case_tags_in_taxonomy(case: Case) -> None:
    unknown = set(case.tags) - _KNOWN_TAGS
    assert not unknown, f"case {case.id!r} has tags outside the taxonomy: {unknown}"
    assert case.kind in ("ingest", "gold")
    assert case.ts_precision in (0, 6), (
        f"case {case.id!r} pins an unsupported ts_precision {case.ts_precision}"
    )


@pytest.mark.parametrize("case", _INGEST_CASES, ids=[c.id for c in _INGEST_CASES])
def test_ingest_case_inputs_and_golden_present(case: Case) -> None:
    assert case.umf is not None and case.umf.exists(), f"missing UMF for {case.id}"
    # Ingest fixtures use the simplified scalar-``nullable`` ingest dialect that
    # the Spark baseline / dbt-duckdb path consume as a raw dict via yaml (NOT the
    # full UMF pydantic model); validate them the same way the runners do.
    umf = yaml.safe_load(case.umf.read_text())
    assert umf.get("table_name"), f"ingest UMF for {case.id} has no table_name"
    columns = [c["name"] for c in umf["columns"]]
    assert case.batches, f"ingest case {case.id} has no batches"
    for b in case.batches:
        assert b.exists(), f"missing batch for {case.id}: {b}"
    assert case.golden is not None and case.golden.exists(), (
        f"missing committed golden for {case.id}: {case.golden} "
        f"(regenerate via the Spark baseline under --update-golden)"
    )
    # The golden is deterministic canonical JSON with the expected shape.
    payload = json.loads(case.golden.read_text())
    assert set(payload) == {"columns", "rows"}
    assert payload["columns"] == columns


@pytest.mark.parametrize("case", _GOLD_CASES, ids=[c.id for c in _GOLD_CASES])
def test_gold_case_sources_present(case: Case) -> None:
    assert case.gold_dir is not None and case.gold_dir.is_dir(), (
        f"missing gold dir for {case.id}: {case.gold_dir}"
    )
    umfs = sorted(case.gold_dir.glob("*.umf.yaml"))
    assert umfs, f"gold case {case.id} has no source/target UMFs"
    csvs = sorted(case.gold_dir.glob("*.csv"))
    assert csvs, f"gold case {case.id} has no source CSVs"
    # A gold case is in exactly one of two valid states:
    #   * PENDING: its executed golden has not been produced yet, so it must NOT
    #     pin a golden (the executed-gold phase writes it under --update-golden);
    #   * EXECUTED/PROMOTED: a generator fix made it run byte-stably on both
    #     backends, so it pins a committed golden that exists on disk and is no
    #     longer pending.
    # (A case may be neither pending nor golden only when it is gated by a
    # ``divergence`` reason -- a known defect that cannot yet execute.)
    if case.pending:
        assert case.golden is None, (
            f"pending gold case {case.id} should not pin a golden until executed"
        )
    elif case.divergence is None:
        assert case.golden is not None and case.golden.exists(), (
            f"executed gold case {case.id} must pin a committed golden that exists "
            f"on disk (got {case.golden}); regenerate via the SQLPlanGeneratorGold "
            f"spark oracle under --update-golden"
        )
        payload = json.loads(case.golden.read_text())
        assert set(payload) >= {"columns", "rows"}, (
            f"gold golden for {case.id} is not canonical JSON with columns/rows"
        )


def _load_gold_umfs(case: Case) -> tuple[UMF, dict[str, UMF]]:
    """Load a gold case's target + related UMFs.

    The target is the UMF carrying derivation metadata (a ``derivation`` on a
    column or a ``base_table*`` in metadata); the rest are sources.
    """
    assert case.gold_dir is not None
    by_name: dict[str, UMF] = {}
    target: UMF | None = None
    for path in sorted(case.gold_dir.glob("*.umf.yaml")):
        umf = UMF(**yaml.safe_load(path.read_text()))
        by_name[umf.table_name] = umf
        has_derivation = any(c.derivation is not None for c in umf.columns)
        has_base = umf.metadata is not None and (
            getattr(umf.metadata, "base_table", None)
            or getattr(umf.metadata, "base_table_strategy", None)
        )
        if has_derivation or has_base:
            target = umf
    assert target is not None, f"no target UMF found for gold case {case.id}"
    related = {n: u for n, u in by_name.items() if n != target.table_name}
    return target, related


@pytest.mark.parametrize(
    "case",
    [c for c in _GOLD_CASES if c.generator in _GOLD_GENERATOR_MARKER],
    ids=[c.id for c in _GOLD_CASES if c.generator in _GOLD_GENERATOR_MARKER],
)
def test_gold_case_compiles_expected_generator_path(case: Case) -> None:
    """The gold case's UMFs compile through generate_sql_plan and hit its path.

    This is a COMPILE-level proof (no execution) that the manifest's pinned
    generator path is genuinely exercised by the committed source UMFs. The
    executed-row golden is produced later by the SQLPlanGeneratorGold tier.
    """
    assert case.generator is not None
    target, related = _load_gold_umfs(case)
    sql = generate_sql_plan(target, related)
    assert sql.strip(), f"empty SQL plan for gold case {case.id}"
    marker = _GOLD_GENERATOR_MARKER[case.generator]
    assert marker in sql.upper(), (
        f"gold case {case.id} (generator {case.generator}) did not emit the "
        f"expected {marker!r} construct; the source UMFs may not drive that path"
    )


def test_fk_integrity_case_is_relationships_tier() -> None:
    """gold_fk_integrity is the dbt relationships tier (not a generate_sql_plan path)."""
    fk = next(c for c in _GOLD_CASES if c.id == "gold_fk_integrity")
    assert fk.generator == "relationships_schema_test"
    assert fk.gold_dir is not None
    # A clean + an orphan CSV are committed so the later tier can assert the
    # relationships test PASSES on clean data and FAILS on the injected orphan.
    names = {p.name for p in fk.gold_dir.glob("*.csv")}
    assert "claims.clean.csv" in names
    assert "claims.orphan.csv" in names
    # The claims UMF carries the foreign key the relationships test is built from.
    claims = UMF(**yaml.safe_load((fk.gold_dir / "claims.umf.yaml").read_text()))
    assert claims.relationships is not None
    assert claims.relationships.foreign_keys, "no FK to drive the relationships test"
