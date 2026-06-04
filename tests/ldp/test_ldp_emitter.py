"""Structural + functional tests for the PROTOTYPE LDP emitter.

LDP runs only on Databricks; there is no Databricks here, so these are JVM-free,
no-execution tests of the GENERATED SQL: materialization matches ingestion.mode,
APPLY CHANGES carries the right KEYS / SEQUENCE BY, EXPECTATIONS carry the correct
ON VIOLATION semantics, gold refs resolve to the right upstream datasets, and the
emitter fails closed on a cycle / unknown relation. Real-Databricks e2e is
explicitly out of scope (see the package docstring).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tablespec.ldp import (
    LdpProjectError,
    OnViolation,
    UnknownDatasetError,
    derive_expectations,
    generate_ldp_project,
)
from tablespec.ldp.renderer import LdpRefRenderer
from tablespec.models.umf import UMF

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "ldp"
_TABLES = ["member", "claims", "events", "enriched"]

_NN = {"default": False}
_NL = {"default": True}


def _load(table: str) -> UMF:
    return UMF(**yaml.safe_load((FIXTURE_DIR / f"{table}.umf.yaml").read_text()))


def _umfs() -> list[UMF]:
    return [_load(t) for t in _TABLES]


def _project() -> dict[str, str]:
    return generate_ldp_project(_umfs(), dialect="spark")


# ---------------------------------------------------------------------------
# materialization matches ingestion.mode
# ---------------------------------------------------------------------------


def test_raw_landing_is_streaming_table_with_read_files() -> None:
    files = _project()
    raw = files["raw/raw_claims.sql"]
    assert raw.startswith("CREATE OR REFRESH STREAMING TABLE raw_claims")
    assert "FROM STREAM read_files(" in raw
    assert "format => 'csv'" in raw


def test_incremental_pk_uses_streaming_table_and_apply_changes() -> None:
    """incremental + primary_key -> STREAMING TABLE shell + APPLY CHANGES."""
    body = _project()["ingested/ingested_claims.sql"]
    assert "CREATE OR REFRESH STREAMING TABLE ingested_claims" in body
    assert "APPLY CHANGES INTO ingested_claims" in body
    # APPLY CHANGES replaces the hand-written dedup window + MERGE.
    assert "row_number()" not in body.lower()
    assert "MERGE INTO" not in body


def test_apply_changes_keys_equal_primary_key_and_sequence_by_order_by() -> None:
    body = _project()["ingested/ingested_claims.sql"]
    assert "KEYS (claim_id)" in body
    assert "SEQUENCE BY _load_ts" in body
    # Reads from the raw STREAM (autoloader), not a static relation.
    assert "FROM STREAM raw_claims" in body


def test_snapshot_uses_materialized_view_no_apply_changes() -> None:
    body = _project()["ingested/ingested_member.sql"]
    assert "CREATE OR REFRESH MATERIALIZED VIEW ingested_member" in body
    assert "APPLY CHANGES" not in body
    assert "STREAM" not in body  # snapshot is a full reload, not a stream


def test_keyless_incremental_is_streaming_append_no_keys() -> None:
    body = _project()["ingested/ingested_events.sql"]
    assert "CREATE OR REFRESH STREAMING TABLE ingested_events" in body
    assert "FROM STREAM raw_events" in body
    # No primary key -> no APPLY CHANGES / KEYS (blind append).
    assert "APPLY CHANGES" not in body
    assert "KEYS (" not in body


def test_gold_is_materialized_view() -> None:
    body = _project()["gold/gold_enriched.sql"]
    assert "CREATE OR REFRESH MATERIALIZED VIEW gold_enriched" in body


# ---------------------------------------------------------------------------
# EXPECTATIONS + ON VIOLATION semantics
# ---------------------------------------------------------------------------


def test_not_null_pk_expectation_fails_update() -> None:
    body = _project()["ingested/ingested_claims.sql"]
    assert (
        "CONSTRAINT not_null_claim_id EXPECT (claim_id IS NOT NULL) "
        "ON VIOLATION FAIL UPDATE" in body
    )


def test_blocking_accepted_values_fails_update() -> None:
    """A blocking/error in-set expectation -> ON VIOLATION FAIL UPDATE."""
    body = _project()["ingested/ingested_claims.sql"]
    assert (
        "CONSTRAINT accepted_values_status EXPECT "
        "(status IS NULL OR status IN ('PAID', 'DENIED', 'PENDING')) "
        "ON VIOLATION FAIL UPDATE" in body
    )


def test_non_blocking_accepted_values_drops_row() -> None:
    """A non-blocking/warning in-set expectation -> ON VIOLATION DROP ROW."""
    body = _project()["ingested/ingested_events.sql"]
    assert (
        "CONSTRAINT accepted_values_severity EXPECT "
        "(severity IS NULL OR severity IN ('LOW', 'HIGH')) "
        "ON VIOLATION DROP ROW" in body
    )


def test_warn_severity_omits_on_violation_clause() -> None:
    """A bare WARN expectation renders WITHOUT an ON VIOLATION clause (LDP default)."""
    from tablespec.ldp.expectations import LdpExpectation

    e = LdpExpectation("c", "x IS NOT NULL", OnViolation.WARN)
    rendered = e.render()
    assert rendered == "CONSTRAINT c EXPECT (x IS NOT NULL)"
    assert "ON VIOLATION" not in rendered


def test_uniqueness_and_fk_are_comments_not_constraints() -> None:
    """Uniqueness + FK are not row-local; they are honest comments, not EXPECTs."""
    body = _project()["ingested/ingested_claims.sql"]
    assert "-- uniqueness intent: PRIMARY KEY (claim_id)" in body
    assert "-- relationship intent: member_id -> ingested_member.member_id" in body
    # They must NOT masquerade as a CONSTRAINT.
    assert "CONSTRAINT unique" not in body
    assert "CONSTRAINT relationship" not in body


def test_snapshot_pk_comment_states_uniqueness_not_enforced() -> None:
    """A snapshot PK note must NOT claim APPLY CHANGES enforcement (it has none)."""
    body = _project()["ingested/ingested_member.sql"]
    assert "is NOT enforced by LDP" in body
    assert "APPLY CHANGES ... KEYS (latest-per-key" not in body


def test_derive_expectations_blocking_maps_to_fail_update() -> None:
    claims = _load("claims").model_dump(exclude_none=True)
    exps = {e.name: e for e in derive_expectations(claims)}
    assert exps["accepted_values_status"].on_violation is OnViolation.FAIL_UPDATE
    assert exps["not_null_claim_id"].on_violation is OnViolation.FAIL_UPDATE


def _claims_with_status_meta(meta: dict) -> dict:
    """A claims UMF-dump whose status in-set expectation carries *meta*."""
    return UMF(
        version="1.0",
        table_name="t",
        primary_key=["id"],
        columns=[
            {"name": "id", "data_type": "INTEGER", "nullable": _NN},
            {"name": "status", "data_type": "VARCHAR", "nullable": _NL},
        ],
        expectations={
            "expectations": [
                {
                    "type": "expect_column_values_to_be_in_set",
                    "kwargs": {"column": "status", "value_set": ["A", "B"]},
                    "meta": meta,
                }
            ]
        },
    ).model_dump(exclude_none=True)


def test_non_blocking_error_severity_drops_row_does_not_abort() -> None:
    """A non-blocking error-severity check quarantines, it does NOT FAIL UPDATE."""
    data = _claims_with_status_meta({"severity": "error", "blocking": False})
    exps = {e.name: e for e in derive_expectations(data)}
    assert exps["accepted_values_status"].on_violation is OnViolation.DROP_ROW


def test_info_severity_is_warn_keeps_row() -> None:
    """An info-severity, non-blocking check is a WARN (no ON VIOLATION, row kept)."""
    data = _claims_with_status_meta({"severity": "info"})
    exps = {e.name: e for e in derive_expectations(data)}
    e = exps["accepted_values_status"]
    assert e.on_violation is OnViolation.WARN
    assert "ON VIOLATION" not in e.render()


def test_blocking_true_overrides_to_fail_update() -> None:
    data = _claims_with_status_meta({"severity": "info", "blocking": True})
    exps = {e.name: e for e in derive_expectations(data)}
    assert exps["accepted_values_status"].on_violation is OnViolation.FAIL_UPDATE


def test_multi_column_sequence_by_uses_struct() -> None:
    """APPLY CHANGES with a multi-column order_by wraps it in STRUCT(...)."""
    multi = UMF(
        version="1.0",
        table_name="multi",
        primary_key=["id"],
        ingestion={"mode": "incremental", "order_by": ["seq", "_load_ts"]},
        columns=[
            {"name": "id", "data_type": "INTEGER", "nullable": _NN},
            {"name": "seq", "data_type": "INTEGER", "nullable": _NL},
        ],
    )
    files = generate_ldp_project([multi], dialect="spark")
    body = files["ingested/ingested_multi.sql"]
    assert "SEQUENCE BY STRUCT(seq, _load_ts)" in body


# ---------------------------------------------------------------------------
# gold dataset refs resolve to the right upstream datasets
# ---------------------------------------------------------------------------


def test_gold_refs_resolve_to_ingested_datasets() -> None:
    body = _project()["gold/gold_enriched.sql"]
    # Bare LDP dataset references (NOT dbt {{ ref() }}).
    assert "FROM ingested_claims" in body
    assert "ingested_member" in body
    assert "{{ ref(" not in body
    assert "{{ source(" not in body


def test_gold_to_gold_ref_resolves_to_upstream_gold() -> None:
    """A gold dataset deriving from another gold references gold_<upstream>."""
    member = _load("member")
    claims = _load("claims")
    enriched = _load("enriched")
    summary = UMF(
        version="1.0",
        table_name="summary",
        primary_key=["claim_id"],
        metadata={"base_table": "enriched"},
        columns=[
            {
                "name": "claim_id",
                "data_type": "INTEGER",
                "nullable": _NN,
                "derivation": {"strategy": "primary_key"},
            },
            {
                "name": "who",
                "data_type": "VARCHAR",
                "nullable": _NL,
                "derivation": {
                    "strategy": "survivorship",
                    "candidates": [
                        {"table": "enriched", "column": "member_name", "priority": 1}
                    ],
                },
            },
        ],
    )
    files = generate_ldp_project([member, claims, enriched, summary], dialect="spark")
    body = files["gold/gold_summary.sql"]
    assert "FROM gold_enriched" in body  # model->model edge, not ingested_enriched
    assert "ingested_enriched" not in body


# ---------------------------------------------------------------------------
# fail closed
# ---------------------------------------------------------------------------


def test_renderer_fails_closed_on_unknown_relation() -> None:
    member = _load("member")
    reg = _Reg([member])
    renderer = LdpRefRenderer(reg)
    with pytest.raises(UnknownDatasetError):
        renderer.render("does_not_exist")


def test_unknown_relation_in_gold_fails_project() -> None:
    """A gold dataset referencing an unknown, non-external relation fails closed."""
    phantom = UMF(
        version="1.0",
        table_name="phantom_gold",
        primary_key=["id"],
        columns=[
            {
                "name": "id",
                "data_type": "INTEGER",
                "nullable": _NN,
                "derivation": {"strategy": "primary_key"},
            },
            {
                "name": "x",
                "data_type": "VARCHAR",
                "nullable": _NL,
                "derivation": {
                    "strategy": "survivorship",
                    "candidates": [
                        {"table": "ghost_table", "column": "x", "priority": 1}
                    ],
                },
            },
        ],
    )
    with pytest.raises(LdpProjectError, match="fail closed"):
        generate_ldp_project([phantom], dialect="spark")


def test_cycle_fails_project() -> None:
    a = UMF(
        version="1.0",
        table_name="a",
        primary_key=["id"],
        metadata={"base_table": "b"},
        columns=[
            {
                "name": "id",
                "data_type": "INTEGER",
                "nullable": _NN,
                "derivation": {"strategy": "primary_key"},
            },
            {
                "name": "v",
                "data_type": "VARCHAR",
                "nullable": _NL,
                "derivation": {
                    "strategy": "survivorship",
                    "candidates": [{"table": "b", "column": "v", "priority": 1}],
                },
            },
        ],
    )
    b = UMF(
        version="1.0",
        table_name="b",
        primary_key=["id"],
        metadata={"base_table": "a"},
        columns=[
            {
                "name": "id",
                "data_type": "INTEGER",
                "nullable": _NN,
                "derivation": {"strategy": "primary_key"},
            },
            {
                "name": "v",
                "data_type": "VARCHAR",
                "nullable": _NL,
                "derivation": {
                    "strategy": "survivorship",
                    "candidates": [{"table": "a", "column": "v", "priority": 1}],
                },
            },
        ],
    )
    with pytest.raises(LdpProjectError, match="cycle"):
        generate_ldp_project([a, b], dialect="spark")


class _Reg:
    """Minimal NodeRegistry wrapper for the renderer unit tests."""

    def __init__(self, umfs: list[UMF]) -> None:
        from tablespec.core.registry import NodeRegistry

        self._reg = NodeRegistry(umfs)

    def resolve(self, name: str):
        return self._reg.resolve(name)
