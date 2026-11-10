# SPDX-License-Identifier: MIT OR Apache-2.0
"""Generated SQL stays valid on edge input: COMMENT literals never split an
escaped quote pair at the length cap, and the Spark-family cast renderer is
NULL-on-failure under ANSI mode (Databricks serverless / Spark 4 default)."""

from __future__ import annotations

import pytest
import sqlglot

from tablespec.casting_utils import cast_column_sql
from tablespec.schemas.generators import _sql_comment, generate_sql_ddl
from tablespec.schemas.ingest_generator import generate_ingest_sql

pytestmark = [
    pytest.mark.filterwarnings("ignore::ResourceWarning"),
    pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning"),
]


@pytest.mark.no_spark
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("plain", "plain"),
        ("it's", "it''s"),
        ("x" * 254 + "'", "x" * 254),  # cap lands inside the '' pair
        ("x" * 253 + "'", "x" * 253 + "''"),  # pair fits exactly
        ("x" * 300, "x" * 255),
    ],
)
def test_sql_comment_never_splits_a_quote_pair(text, expected):
    out = _sql_comment(text)
    assert out == expected
    assert len(out) <= 255
    trailing = len(out) - len(out.rstrip("'"))
    assert trailing % 2 == 0


@pytest.mark.no_spark
def test_ddl_with_quote_at_cap_parses():
    umf = {
        "table_name": "t",
        "description": "d" * 254 + "'s",
        "columns": [
            {"name": "a", "data_type": "VARCHAR", "description": "c" * 254 + "'s"}
        ],
    }
    ddl = generate_sql_ddl(umf)
    sqlglot.parse_one(ddl.split(";")[0], read="spark")  # raises on an open literal


@pytest.mark.no_spark
def test_ingest_ddl_comment_with_quote_at_cap_parses():
    umf = {
        "table_name": "t",
        "description": "d" * 254 + "'s",
        "columns": [{"name": "a", "data_type": "VARCHAR"}],
    }
    sql = generate_ingest_sql(umf)
    for stmt in sql.split(";"):
        if "CREATE TABLE" in stmt:
            sqlglot.parse_one(stmt[stmt.index("CREATE") :], read="spark")


@pytest.mark.no_spark
@pytest.mark.parametrize("dialect", ["spark", "databricks", "duckdb"])
@pytest.mark.parametrize(
    "target", ["INTEGER", "BIGINT", "DECIMAL", "DOUBLE", "BOOLEAN"]
)
def test_numeric_and_boolean_casts_are_try_cast(dialect, target):
    expr = cast_column_sql("v", target, dialect=dialect)
    assert expr.startswith("try_cast("), expr


@pytest.mark.no_spark
@pytest.mark.parametrize("target", ["INTEGER", "BIGINT", "BOOLEAN"])
def test_typed_raw_casts_are_try_cast(target):
    assert cast_column_sql("v", target, source_kind="parquet").startswith("try_cast(")


@pytest.mark.parametrize(
    ("target", "bad"),
    [("INTEGER", "abc"), ("BIGINT", "12x"), ("DECIMAL", "n/a"), ("BOOLEAN", "maybe")],
)
def test_spark_cast_nulls_malformed_values_with_ansi_on(spark_session, target, bad):
    previous = spark_session.conf.get("spark.sql.ansi.enabled", "false")
    spark_session.conf.set("spark.sql.ansi.enabled", "true")
    try:
        expr = cast_column_sql("v", target, dialect="spark")
        row = spark_session.sql(
            f"SELECT {expr} AS out FROM VALUES ('{bad}') AS t(v)"
        ).collect()[0]
    finally:
        spark_session.conf.set("spark.sql.ansi.enabled", previous)
    assert row["out"] is None
