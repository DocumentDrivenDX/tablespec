"""Focused JSONL conformance tier.

Exercises the typed-raw JSON path end to end: a temporary JSONL batch carries a
nested payload, the UMF declares flat projection metadata, and the Spark oracle
plus dbt-on-DuckDB engine must both materialize the same canonical rows.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from tablespec.ingestion import get_reader
from tablespec.models.umf import JsonSource
from tests.conformance.corpus.registry import Case
from tests.conformance.engines import DbtDuckDBEngine, SparkDirectEngine
from tests.ingest_parity.canonical import to_json

pytestmark = [
    pytest.mark.slow,
    pytest.mark.spark_only,
    pytest.mark.filterwarnings("ignore::ResourceWarning"),
    pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning"),
]


def _json_umf(batch_path: Path) -> dict:
    return {
        "version": "1.0",
        "table_name": "json_events",
        "source": {
            "kind": "json",
            "path": str(batch_path),
            "multi_line": False,
            "projection": [
                {"column": "member_id", "path": "member_id"},
                {"column": "status", "path": "payload.status"},
                {"column": "amount", "path": "payload.amount"},
                {"column": "flag", "path": "payload.flag"},
            ],
        },
        "ingestion": {"mode": "snapshot"},
        "columns": [
            {"name": "member_id", "data_type": "INTEGER"},
            {"name": "status", "data_type": "VARCHAR"},
            {"name": "amount", "data_type": "DOUBLE"},
            {"name": "flag", "data_type": "BOOLEAN"},
        ],
    }


def _write_jsonl_batch(path: Path) -> list[dict[str, object]]:
    rows = [
        {
            "member_id": 1,
            "payload": {"status": "active", "amount": 12.5, "flag": True},
        },
        {
            "member_id": 2,
            "payload": {"status": "pending", "amount": 0.25, "flag": False},
        },
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    return [
        {
            "member_id": 1,
            "status": "active",
            "amount": 12.5,
            "flag": True,
        },
        {
            "member_id": 2,
            "status": "pending",
            "amount": 0.25,
            "flag": False,
        },
    ]


def test_jsonl_typed_raw_projection_matches_across_engines(
    tmp_path, spark_session
) -> None:  # noqa: ANN001
    jsonl_dir = tmp_path / "json_events"
    jsonl_dir.mkdir()
    batch = jsonl_dir / "json_events.jsonl"
    rows = _write_jsonl_batch(batch)
    umf_path = tmp_path / "json_events.umf.yaml"
    umf_path.write_text(yaml.safe_dump(_json_umf(batch), sort_keys=False))

    case = Case(
        id="json_events",
        kind="ingest",
        tags=("json", "snapshot"),
        ts_precision=3,
        umf=umf_path,
        batches=(batch,),
        golden=None,
    )

    spark_engine = SparkDirectEngine()
    spark_expected = to_json(
        rows,
        ["member_id", "status", "amount", "flag"],
        {},
        ts_precision=3,
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


def test_jsonl_missing_projection_path_fails_before_nulling(
    tmp_path, spark_session
) -> None:  # noqa: ANN001
    batch = tmp_path / "json_events.jsonl"
    _write_jsonl_batch(batch)
    spec = JsonSource(
        kind="json",
        path=str(batch),
        projection=[
            {"column": "member_id", "path": "member_id"},
            {"column": "status", "path": "payload.missing_status"},
        ],
    )

    with pytest.raises(ValueError, match="projection path.*not found"):
        get_reader(spec).read(spec, spark_session)
