"""Unit tests for the compiled-artifact parser (compile/runtime separation).

The runtime backbone must derive its raw-load schema, projection order, table
names, and decimal scales from the COMPILED ``ingest.sql`` artifact -- never the
source UMF snapshot. These tests pin that the parser recovers exactly that
information from the generated ingest SQL, including the DECIMAL scale map and the
all-STRING raw column order (metadata columns excluded).
"""

from __future__ import annotations

import pytest

from tablespec.e2e.compiled import parse_ingest_sql
from tablespec.schemas.ingest_generator import generate_ingest_sql

_UMF = {
    "table_name": "claims",
    "description": "Claims table",
    "primary_key": ["claim_id"],
    "ingestion": {"mode": "incremental", "order_by": ["_load_ts"]},
    "columns": [
        {"name": "claim_id", "data_type": "INTEGER", "nullable": False},
        {"name": "svc_date", "data_type": "DATE", "format": "YYYY-MM-DD"},
        {"name": "status", "data_type": "VARCHAR", "max_length": 10},
        {"name": "amount", "data_type": "DECIMAL", "precision": 12, "scale": 4},
    ],
}


def test_parse_recovers_table_names_and_business_columns() -> None:
    schema = parse_ingest_sql(generate_ingest_sql(_UMF), "claims")
    assert schema.raw_table == "raw_claims"
    assert schema.ingested_table == "ingested_claims"
    # Business columns only, in UMF order -- metadata columns are excluded.
    assert schema.columns == ["claim_id", "svc_date", "status", "amount"]
    assert "_source_file" not in schema.columns
    assert "_load_ts" not in schema.columns


def test_parse_recovers_decimal_scales_from_typed_ddl() -> None:
    schema = parse_ingest_sql(generate_ingest_sql(_UMF), "claims")
    assert schema.decimal_scales == {"amount": 4}


def test_parse_defaults_decimal_scale_to_two() -> None:
    umf = {
        "table_name": "t",
        "primary_key": ["k"],
        "ingestion": {"mode": "incremental", "order_by": ["_load_ts"]},
        "columns": [
            {"name": "k", "data_type": "INTEGER", "nullable": False},
            {
                "name": "amt",
                "data_type": "DECIMAL",
            },  # no precision/scale -> DECIMAL(10,2)
        ],
    }
    schema = parse_ingest_sql(generate_ingest_sql(umf), "t")
    assert schema.decimal_scales == {"amt": 2}


def test_parse_handles_table_with_no_decimals() -> None:
    umf = {
        "table_name": "member",
        "primary_key": ["member_id"],
        "ingestion": {"mode": "incremental", "order_by": ["_load_ts"]},
        "columns": [
            {"name": "member_id", "data_type": "INTEGER", "nullable": False},
            {"name": "name", "data_type": "VARCHAR", "max_length": 50},
        ],
    }
    schema = parse_ingest_sql(generate_ingest_sql(umf), "member")
    assert schema.columns == ["member_id", "name"]
    assert schema.decimal_scales == {}


def test_parse_missing_table_raises() -> None:
    with pytest.raises(ValueError, match="no CREATE TABLE"):
        parse_ingest_sql("-- no tables here", "nope")
