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
    assert (
        ct.strategy,
        ct.operation_column,
        ct.delete_values,
        ct.baseline_values,
        ct.key_columns,
        ct.version_column,
        ct.delivery_column,
    ) == ("merge", "SYS_CHANGE_OPERATION", ["D"], None, None, None, None)
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
    assert (
        "WHEN MATCHED AND coalesce(src._ct_operation IN ('D'), false) THEN DELETE"
        in sql
    )
    # a NULL operation (baseline row) must still insert
    assert "WHEN NOT MATCHED AND NOT coalesce(src._ct_operation IN ('D'), false)" in sql


# Three deliveries (delivery order = _load_ts): 1 is a full baseline (no
# operation), 2 has increments -- key 2 updated twice (version 9, then 10),
# key 3 inserted (v8) and deleted (v11, key only in CT_ID) -- and 3 re-baselines
# without key 1. Assertions are aggregates: (row count, sum of keys, sum of
# amounts).
_DELIVERIES = [
    [
        "('1', '10', NULL, NULL, NULL, 'b1', TIMESTAMP'2026-11-01 00:00:00')",
        "('2', '20', NULL, NULL, NULL, 'b1', TIMESTAMP'2026-11-01 00:00:00')",
    ],
    [
        "('2', '21', '2', 'U', '9', 'i2', TIMESTAMP'2026-11-02 00:00:00')",
        "('2', '22', '2', 'U', '10', 'i2', TIMESTAMP'2026-11-02 00:00:00')",
        "(NULL, NULL, '3', 'D', '11', 'i2', TIMESTAMP'2026-11-02 00:00:00')",
        "('3', '30', '3', 'I', '8', 'i2', TIMESTAMP'2026-11-02 00:00:00')",
    ],
    [
        "('2', '22', NULL, NULL, NULL, 'b3', TIMESTAMP'2026-11-03 00:00:00')",
        "('3', '31', NULL, NULL, NULL, 'b3', TIMESTAMP'2026-11-03 00:00:00')",
    ],
]


def _spark_totals(spark_session, strategy: str, deliveries: int) -> tuple:
    umf = UMF.model_validate(
        _ct_umf(
            strategy=strategy,
            key_columns=["CT_ID"],
            version_column="SYS_CHANGE_VERSION",
        )
    ).model_dump(exclude_none=True)
    suffix = uuid.uuid4().hex[:8]
    raw, ingested = f"raw_ct_{suffix}", f"ingested_ct_{suffix}"
    sql = generate_ingest_sql(umf, raw_table=raw, ingested_table=ingested)
    ddl, transform = sql.split("-- 3. Raw -> ingested transform")
    try:
        for stmt in ddl.split(";"):
            if "CREATE TABLE" in stmt:
                spark_session.sql(stmt[stmt.index("CREATE") :])
        for rows in _DELIVERIES[:deliveries]:
            if strategy == "merge":  # merge applies one batch at a time
                spark_session.sql(f"DELETE FROM {raw}")
            spark_session.sql(
                f"INSERT INTO {raw} (ID, amount, CT_ID, SYS_CHANGE_OPERATION, "
                f"SYS_CHANGE_VERSION, _source_file, _load_ts) VALUES {', '.join(rows)}"
            )
            spark_session.sql(transform.strip())
        got = spark_session.sql(
            f"SELECT count(*) AS n, sum(ID) AS k, sum(amount) AS a FROM {ingested}"
        ).collect()[0]
        return (got["n"], got["k"], float(got["a"]))
    finally:
        spark_session.sql(f"DROP TABLE IF EXISTS {raw}")
        spark_session.sql(f"DROP TABLE IF EXISTS {ingested}")


@pytest.mark.parametrize("strategy", ["merge", "rebuild"])
def test_change_tracking_applies_baseline_then_increments(spark_session, strategy):
    # baseline rows (NULL operation) insert; key 2's latest version wins within
    # its delivery; key 3's in-delivery delete wins over its insert
    assert _spark_totals(spark_session, strategy, 2) == (2, 3, 32.0)


def test_change_tracking_rebuild_rebaseline_supersedes(spark_session):
    # the delivery-3 baseline drops key 1 and resurrects key 3
    assert _spark_totals(spark_session, "rebuild", 3) == (2, 5, 53.0)


@pytest.mark.no_spark
def test_change_tracking_versions_sort_numerically_on_string_raw():
    umf = UMF.model_validate(_ct_umf(version_column="V")).model_dump(exclude_none=True)
    assert build_ingest_select(umf).order_terms == ["_load_ts", "try_cast(V as BIGINT)"]
    umf["source"] = {"kind": "parquet"}
    assert build_ingest_select(umf).order_terms == ["_load_ts", "V"]


@pytest.mark.no_spark
@pytest.mark.parametrize(
    ("ct", "error"),
    [
        ({"delivery_column": "d"}, "requires strategy 'rebuild'"),
        ({"delete_values": ["D"], "baseline_values": [" d "]}, "overlap"),
    ],
)
def test_change_tracking_config_validation(ct, error):
    with pytest.raises(ValidationError, match=error):
        UMF.model_validate(_ct_umf(**ct))


@pytest.mark.no_spark
def test_change_tracking_custom_baseline_and_delivery_columns():
    umf = UMF.model_validate(
        _ct_umf(
            strategy="rebuild",
            baseline_values=["S"],
            delete_values=["del"],
            delivery_column="extract_ts",
        )
    ).model_dump(exclude_none=True)
    sql = generate_ingest_sql(umf)
    assert "max(extract_ts) AS _ct_baseline" in sql
    assert "coalesce(c._ct_operation IN ('S'), false)" in sql
    assert "NOT coalesce(_ct_operation IN ('DEL'), false)" in sql


# --- dbt / LDP -----------------------------------------------------------


@pytest.mark.no_spark
def test_dbt_maps_append_to_keyless_incremental():
    assert dbt_ingest_mode("append", ["e"]) == ("incremental", [])
    mat = MaterializationPolicy().for_ingested(mode="append", primary_key=["e"])
    assert (mat.strategy, mat.incremental_strategy) == ("incremental", "append")


@pytest.mark.no_spark
def test_dbt_change_tracking_materializations():
    policy = MaterializationPolicy()
    rebuild = policy.for_ingested(
        mode="change_tracking", primary_key=["ID"], change_strategy="rebuild"
    )
    merge = policy.for_ingested(mode="change_tracking", primary_key=["ID"])
    assert rebuild.strategy == "table"
    assert (merge.strategy, merge.incremental_strategy, merge.unique_key) == (
        "incremental",
        "merge",
        ("ID",),
    )


@pytest.mark.no_spark
def test_dbt_merge_model_has_delete_hook():
    from tablespec.dbt.single_table import generate_dbt_project

    umf = UMF.model_validate(_ct_umf(key_columns=["CT_ID"])).model_dump(
        exclude_none=True
    )
    model = generate_dbt_project(umf, dialect="duckdb")["models/claim_header.sql"]
    assert "incremental_strategy='merge'" in model
    assert 'post_hook="DELETE FROM {{ this }} WHERE ID IN (' in model
    assert "WHERE NOT coalesce(src_raw._ct_operation IN ('D'), false)" in model


@pytest.mark.no_spark
@pytest.mark.parametrize("strategy", ["merge", "rebuild"])
def test_ldp_renders_change_tracking(strategy):
    from tablespec.ldp.project import generate_ldp_project

    umf = UMF.model_validate(
        _ct_umf(strategy=strategy, version_column="SYS_CHANGE_VERSION")
    )
    files = generate_ldp_project([umf], dialect="spark")
    sql = files["ingested/ingested_claim_header.sql"]
    if strategy == "merge":
        assert "APPLY CHANGES INTO ingested_claim_header" in sql
        assert "APPLY AS DELETE WHEN coalesce(_ct_operation IN ('D'), false)" in sql
        assert (
            "STRUCT(_load_ts, try_cast(SYS_CHANGE_VERSION as BIGINT)) AS _ct_sequence"
            in sql
        )
        assert "COLUMNS * EXCEPT (_ct_operation, _ct_sequence)" in sql
        assert "STORED AS SCD TYPE 1;" in sql
    else:
        assert "CREATE OR REFRESH MATERIALIZED VIEW ingested_claim_header" in sql
        assert "_ct_baseline" in sql and "STREAM" not in sql


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
