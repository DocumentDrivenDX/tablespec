# SPDX-License-Identifier: MIT OR Apache-2.0
"""``ingestion.mode: append`` and ``change_tracking``, plus ``optional`` columns."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from tablespec.dbt.materialization import (
    MaterializationPolicy,
    dbt_ingest_mode,
)
from tablespec.gx_baseline import BaselineExpectationGenerator
from tablespec.models.umf import UMF
from tablespec.schemas.ingest_generator import build_ingest_select, generate_ingest_sql

pytestmark = [
    pytest.mark.filterwarnings("ignore::ResourceWarning"),
    pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning"),
]


def _ct_umf(**ct) -> dict:
    return {
        "version": "1.0",
        "table_name": "claim_header",
        "columns": [
            {"name": "ID", "data_type": "BIGINT"},
            {"name": "amount", "data_type": "DECIMAL", "precision": 12, "scale": 2},
            {"name": "note", "data_type": "VARCHAR", "length": 20, "optional": True},
        ],
        "primary_key": ["ID"],
        "ingestion": {
            "mode": "change_tracking",
            "order_by": ["_load_ts"],
            "change_tracking": ct,
        },
    }


# --- model ---------------------------------------------------------------


@pytest.mark.no_spark
def test_change_tracking_defaults():
    umf = UMF.model_validate(_ct_umf())
    ct = umf.ingestion.change_tracking
    assert (ct.operation_column, ct.delete_values, ct.key_columns) == (
        "SYS_CHANGE_OPERATION",
        ["D"],
        None,
    )
    assert umf.columns[2].optional is True


@pytest.mark.no_spark
def test_change_tracking_requires_primary_key():
    data = _ct_umf()
    data.pop("primary_key")
    with pytest.raises(ValidationError, match="requires a primary_key"):
        UMF.model_validate(data)


@pytest.mark.no_spark
def test_change_tracking_key_columns_align_with_primary_key():
    with pytest.raises(ValidationError, match="align"):
        UMF.model_validate(_ct_umf(key_columns=["CT_ID", "CT_OTHER"]))


@pytest.mark.no_spark
def test_change_tracking_block_needs_change_tracking_mode():
    data = _ct_umf()
    data["ingestion"]["mode"] = "incremental"
    with pytest.raises(ValidationError, match="only valid with mode"):
        UMF.model_validate(data)


# --- generated SQL -------------------------------------------------------


@pytest.mark.no_spark
def test_append_inserts_every_row():
    sql = generate_ingest_sql(
        {
            "table_name": "events",
            "columns": [{"name": "e", "data_type": "VARCHAR"}],
            "primary_key": ["e"],
            "ingestion": {"mode": "append"},
        }
    )
    transform = sql.split("-- 3. Raw -> ingested transform")[1]
    assert "INSERT INTO ingested_events" in transform
    assert "MERGE" not in transform and "row_number" not in transform


@pytest.mark.no_spark
def test_change_tracking_sql_keys_on_coalesced_key_column():
    umf = UMF.model_validate(_ct_umf(key_columns=["CT_ID"])).model_dump(
        exclude_none=True
    )
    ingest = build_ingest_select(umf)
    assert ingest.key_exprs == ("coalesce(CT_ID, ID)",)
    sql = generate_ingest_sql(umf)
    assert "CT_ID                STRING" in sql
    assert "SYS_CHANGE_OPERATION STRING" in sql
    assert "PARTITION BY coalesce(CT_ID, ID)" in sql
    assert "WHEN MATCHED AND src._ct_operation IN ('D') THEN DELETE" in sql


def test_change_tracking_merge_applies_inserts_updates_deletes(spark_session):
    umf = UMF.model_validate(_ct_umf(key_columns=["CT_ID"])).model_dump(
        exclude_none=True
    )
    suffix = uuid.uuid4().hex[:8]
    raw, ingested = f"raw_ct_{suffix}", f"ingested_ct_{suffix}"
    sql = generate_ingest_sql(umf, raw_table=raw, ingested_table=ingested)
    ddl, transform = sql.split("-- 3. Raw -> ingested transform")
    statements = [s for s in ddl.split(";") if "CREATE TABLE" in s]
    try:
        for stmt in statements:
            spark_session.sql(stmt[stmt.index("CREATE") :])

        def deliver(rows):
            spark_session.sql(f"DELETE FROM {raw}")
            values = ", ".join(rows)
            spark_session.sql(
                f"INSERT INTO {raw} (ID, amount, note, CT_ID, SYS_CHANGE_OPERATION, "
                f"_source_file, _load_ts) VALUES {values}"
            )
            spark_session.sql(transform.strip())

        # delivery 1: two inserts; key 2 updated later in the same file
        deliver(
            [
                "('1', '10.00', 'a', '1', 'I', 'f1', TIMESTAMP'2026-11-01 00:00:00')",
                "('2', '20.00', NULL, '2', 'I', 'f1', TIMESTAMP'2026-11-01 00:00:00')",
                "('2', '25.00', 'b', '2', 'U', 'f1', TIMESTAMP'2026-11-01 00:00:01')",
            ]
        )
        # delivery 2: delete key 1 (key only in CT_ID), insert 3000000000
        deliver(
            [
                "(NULL, NULL, NULL, '1', 'D', 'f2', TIMESTAMP'2026-11-02 00:00:00')",
                "('3000000000', '1.50', NULL, '3000000000', 'I', 'f2', "
                "TIMESTAMP'2026-11-02 00:00:00')",
            ]
        )
        rows = sorted(
            (r["ID"], str(r["amount"]), r["note"])
            for r in spark_session.table(ingested).collect()
        )
        assert rows == [(2, "25.00", "b"), (3000000000, "1.50", None)]
    finally:
        spark_session.sql(f"DROP TABLE IF EXISTS {raw}")
        spark_session.sql(f"DROP TABLE IF EXISTS {ingested}")


# --- emitters that do not render every mode ------------------------------


@pytest.mark.no_spark
def test_dbt_maps_append_to_keyless_incremental():
    assert dbt_ingest_mode("append", ["e"]) == ("incremental", [])
    mat = MaterializationPolicy().for_ingested(mode="append", primary_key=["e"])
    assert (mat.strategy, mat.incremental_strategy) == ("incremental", "append")


@pytest.mark.no_spark
def test_dbt_refuses_change_tracking():
    with pytest.raises(NotImplementedError, match="change_tracking"):
        MaterializationPolicy().for_ingested(mode="change_tracking", primary_key=["ID"])


# --- optional columns ----------------------------------------------------


@pytest.mark.no_spark
def test_baseline_requires_only_non_optional_columns():
    umf = UMF.model_validate(_ct_umf()).model_dump(exclude_none=True)
    structural = [
        e
        for e in BaselineExpectationGenerator().generate_baseline_expectations(umf)
        if e["type"].startswith("expect_table_column")
    ]
    assert structural == [
        {
            "type": "expect_table_columns_to_match_set",
            "kwargs": {"column_set": ["ID", "amount"], "exact_match": False},
            "meta": {
                "description": "Table must contain every non-optional column",
                "severity": "critical",
                "generated_from": "baseline",
            },
        }
    ]


@pytest.mark.no_spark
def test_baseline_unchanged_without_optional_columns():
    umf = UMF.model_validate(_ct_umf()).model_dump(exclude_none=True)
    umf["columns"][2].pop("optional", None)
    types = {
        e["type"]
        for e in BaselineExpectationGenerator().generate_baseline_expectations(umf)
    }
    assert "expect_table_column_count_to_equal" in types
    assert "expect_table_columns_to_match_ordered_list" in types
