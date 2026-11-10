# SPDX-License-Identifier: MIT OR Apache-2.0
"""BIGINT is a first-class UMF data type: 64-bit keys survive ingest instead
of overflowing a 32-bit INTEGER cast to NULL."""

from __future__ import annotations

import pytest

from tablespec.casting_utils import cast_column_sql
from tablespec.gx_baseline import BaselineExpectationGenerator
from tablespec.models.umf import UMF, UMFColumn
from tablespec.profiling.spark_mapper import SPARK_TO_UMF_TYPE
from tablespec.profiling.sql_reflect import SQL_TO_UMF_TYPE
from tablespec.schemas.ingest_generator import generate_ingest_sql
from tablespec.type_lattice import SAFE_WIDENINGS

pytestmark = [
    pytest.mark.filterwarnings("ignore::ResourceWarning"),
    pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning"),
]

BIG = "3000000000"  # > 2**31 - 1


@pytest.mark.no_spark
def test_umf_accepts_bigint():
    umf = UMF(
        version="1.0",
        table_name="t",
        columns=[UMFColumn(name="ID", data_type="BIGINT")],
        primary_key=["ID"],
    )
    assert umf.columns[0].data_type == "BIGINT"


@pytest.mark.no_spark
def test_ingest_types_bigint_end_to_end():
    sql = generate_ingest_sql(
        {"table_name": "t", "columns": [{"name": "ID", "data_type": "BIGINT"}]}
    )
    assert "ID BIGINT" in sql
    assert "as BIGINT) AS ID" in sql


@pytest.mark.no_spark
def test_reflection_maps_64_bit_types_to_bigint():
    assert SPARK_TO_UMF_TYPE["LongType"] == "BIGINT"
    assert SQL_TO_UMF_TYPE["BIGINT"] == "BIGINT"
    assert SQL_TO_UMF_TYPE["LONG"] == "BIGINT"
    assert SQL_TO_UMF_TYPE["INT"] == "INTEGER"


@pytest.mark.no_spark
def test_integer_to_bigint_is_a_safe_widening():
    assert ("INTEGER", "BIGINT") in SAFE_WIDENINGS


@pytest.mark.no_spark
def test_baseline_casts_bigint_columns_to_bigint():
    exps = BaselineExpectationGenerator().generate_baseline_expectations(
        {
            "table_name": "t",
            "columns": [{"name": "ID", "data_type": "BIGINT"}],
        }
    )
    casts = [e for e in exps if e["type"] == "expect_column_values_to_cast_to_type"]
    assert [c["kwargs"]["target_type"] for c in casts] == ["BIGINT"]


def test_spark_bigint_cast_keeps_values_above_int_range(spark_session):
    expr_big = cast_column_sql("v", "BIGINT", dialect="spark")
    expr_int = cast_column_sql("v", "INTEGER", dialect="spark")
    row = spark_session.sql(
        f"SELECT {expr_big} AS big, {expr_int} AS small FROM VALUES ('{BIG}') AS t(v)"
    ).collect()[0]
    assert row["big"] == int(BIG)
    assert row["small"] is None  # what INTEGER did to these keys


def test_runtime_caster_handles_bigint(spark_session):
    from pyspark.sql import functions as F

    from tablespec.casting_utils import cast_column_with_format

    df = spark_session.createDataFrame([(BIG,)], "v string")
    out = df.select(cast_column_with_format(F.col("v"), "BIGINT").alias("o")).collect()
    assert out[0]["o"] == int(BIG)
