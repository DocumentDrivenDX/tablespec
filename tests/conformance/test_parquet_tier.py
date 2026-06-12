"""Focused parquet conformance tier.

Exercises the typed-raw parquet path end to end without relying on committed
parquet fixtures: a temporary parquet batch is written with typed columns, then
the Spark oracle and dbt/DuckDB engine adapters ingest it through the source-kind
dispatch and must produce identical canonical output.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from tests.conformance.corpus.registry import Case
from tests.conformance.engines import DbtDuckDBEngine, SparkDirectEngine
from tests.ingest_parity.canonical import to_json

pytestmark = [
    pytest.mark.spark_only,
    pytest.mark.filterwarnings("ignore::ResourceWarning"),
    pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning"),
]


def _parquet_umf(batch_path: Path) -> dict:
    return {
        "version": "1.0",
        "table_name": "parquet_events",
        "source": {
            "kind": "parquet",
            "path": str(batch_path),
        },
        "ingestion": {"mode": "snapshot"},
        "columns": [
            {"name": "event_id", "data_type": "INTEGER"},
            {"name": "event_date", "data_type": "DATE"},
            {
                "name": "amount",
                "data_type": "DECIMAL",
                "precision": 10,
                "scale": 2,
            },
        ],
    }


def _write_parquet_batch(spark, path: Path) -> list[dict[str, object]]:
    rows = [
        {"event_id": 1, "event_date": date(2026, 6, 3), "amount": Decimal("12.34")},
        {"event_id": 2, "event_date": date(2026, 6, 4), "amount": Decimal("0.10")},
    ]
    schema = "event_id int, event_date date, amount decimal(10,2)"
    spark.createDataFrame(
        [(r["event_id"], r["event_date"], r["amount"]) for r in rows], schema
    ).write.mode("overwrite").parquet(str(path))
    return rows


def test_parquet_tier_matches_across_engines(tmp_path, spark_session) -> None:  # noqa: ANN001
    parquet_dir = tmp_path / "parquet_events"
    rows = _write_parquet_batch(spark_session, parquet_dir)
    umf_path = tmp_path / "parquet_events.umf.yaml"
    umf_path.write_text(yaml.safe_dump(_parquet_umf(parquet_dir), sort_keys=False))

    case = Case(
        id="parquet_events",
        kind="ingest",
        tags=("parquet", "snapshot"),
        ts_precision=0,
        umf=umf_path,
        batches=(parquet_dir,),
        golden=None,
    )

    spark_engine = SparkDirectEngine()
    spark_expected = to_json(
        rows,
        ["event_id", "event_date", "amount"],
        {"amount": 2},
        ts_precision=0,
    )
    spark_actual = spark_engine.run(case)
    assert spark_actual == spark_expected

    duck_engine = DbtDuckDBEngine()
    reason = duck_engine.availability(case)
    if reason is not None:
        pytest.skip(reason)

    duck_actual = duck_engine.run(case)
    assert duck_actual == spark_expected
    assert duck_actual == spark_actual
