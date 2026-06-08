"""Unit tests for the shared ingest SELECT seam + the direct Databricks emitter.

These are pure-Python (no Spark, no dbt, no duckdb) and cover:

  * :func:`build_ingest_select` -- the ONE seam both emitters share: column order,
    mode/key/order metadata, the aligned cast SELECT block, the dedup-latest window,
    and the ``has_dedup`` decision per (mode, primary_key).
  * :func:`generate_ingest_sql` -- the direct committed Databricks artifact: the raw
    landing DDL (all STRING + provenance), the typed target DDL (incl. DECIMAL /
    VARCHAR(n) / NOT NULL), and every one of the four write-transform branches
    (incremental+pk MERGE, keyless-incremental blind INSERT, snapshot+pk INSERT
    OVERWRITE, snapshot no-pk blind OVERWRITE).

The dbt emitters reuse ``build_ingest_select`` verbatim, so locking its behaviour
here also pins the dbt staging-model bodies.
"""

from __future__ import annotations

import pytest

from tablespec.schemas.ingest_generator import (
    IngestSelect,
    build_ingest_select,
    generate_ingest_sql,
)

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]


def _umf(
    *,
    columns: list[dict],
    mode: str = "incremental",
    primary_key: list[str] | None = None,
    order_by: list[str] | None = None,
    table_name: str = "t",
    description: str | None = None,
) -> dict:
    data: dict = {
        "table_name": table_name,
        "columns": columns,
        "ingestion": {"mode": mode},
    }
    if primary_key is not None:
        data["primary_key"] = primary_key
    if order_by is not None:
        data["ingestion"]["order_by"] = order_by
    if description is not None:
        data["description"] = description
    return data


_COLS = [
    {"name": "id", "data_type": "INTEGER", "nullable": False},
    {"name": "name", "data_type": "VARCHAR", "nullable": True},
    {"name": "amt", "data_type": "DECIMAL", "precision": 12, "scale": 4},
]


class TestBuildIngestSelect:
    def test_columns_and_metadata(self):
        ingest = build_ingest_select(
            _umf(columns=_COLS, primary_key=["id"]), dialect="spark"
        )
        assert ingest.columns == ["id", "name", "amt"]
        assert ingest.mode == "incremental"
        assert ingest.primary_key == ["id"]
        assert ingest.order_by == ["_load_ts"]  # default provenance order
        assert ingest.dialect == "spark"

    def test_default_mode_is_incremental(self):
        """A UMF with no ingestion block defaults to incremental."""
        ingest = build_ingest_select({"table_name": "t", "columns": _COLS})
        assert ingest.mode == "incremental"
        assert ingest.order_by == ["_load_ts"]

    def test_custom_order_by_is_honoured(self):
        ingest = build_ingest_select(
            _umf(columns=_COLS, primary_key=["id"], order_by=["seq", "_load_ts"])
        )
        assert ingest.order_by == ["seq", "_load_ts"]

    def test_select_block_exact_casts_spark(self):
        block = build_ingest_select(_umf(columns=_COLS), dialect="spark").select_block
        lines = [ln.strip() for ln in block.splitlines()]
        assert len(lines) == 3
        # exact per-column cast expression (a swapped/broken cast would fail)
        assert lines[0].startswith(
            "cast(nullif(trim(regexp_replace(id, '^\\\\$', '')), '') as INT)"
        )
        assert lines[0].endswith("AS id,")
        assert lines[1].startswith("name")  # STRING passthrough, no cast
        assert lines[1].endswith("AS name,")
        assert lines[2].startswith(
            "cast(nullif(trim(regexp_replace(amt, '^\\\\$', '')), '') as DECIMAL(12,4))"
        )
        assert lines[2].endswith("AS amt")  # last column: no trailing comma

    def test_select_block_exact_casts_duckdb(self):
        block = build_ingest_select(_umf(columns=_COLS), dialect="duckdb").select_block
        lines = [ln.strip() for ln in block.splitlines()]
        assert lines[0].startswith(
            "try_cast(nullif(trim(regexp_replace(id, '^\\$', '')), '') as INT)"
        )
        assert lines[1].startswith("name")  # STRING passthrough identical to spark
        assert lines[2].startswith(
            "try_cast(nullif(trim(regexp_replace(amt, '^\\$', '')), '') "
            "as DECIMAL(12,4))"
        )

    def test_databricks_alias_uses_spark_rendering_path(self):
        spark_ingest = build_ingest_select(_umf(columns=_COLS), dialect="spark")
        dbx_ingest = build_ingest_select(_umf(columns=_COLS), dialect="databricks")
        assert dbx_ingest.dialect == "databricks"
        assert dbx_ingest.columns == spark_ingest.columns
        assert dbx_ingest.mode == spark_ingest.mode
        assert dbx_ingest.primary_key == spark_ingest.primary_key
        assert dbx_ingest.order_by == spark_ingest.order_by
        assert dbx_ingest.select_block == spark_ingest.select_block

    def test_has_dedup_only_for_incremental_with_pk(self):
        assert build_ingest_select(
            _umf(columns=_COLS, mode="incremental", primary_key=["id"])
        ).has_dedup
        assert not build_ingest_select(
            _umf(columns=_COLS, mode="incremental", primary_key=[])
        ).has_dedup
        assert not build_ingest_select(
            _umf(columns=_COLS, mode="snapshot", primary_key=["id"])
        ).has_dedup

    def test_dedup_window_partitions_by_pk_and_orders_desc(self):
        ingest = build_ingest_select(
            _umf(columns=_COLS, primary_key=["id"], order_by=["_load_ts"])
        )
        sql = ingest.dedup_window_sql("raw_t")
        assert "PARTITION BY id ORDER BY _load_ts DESC" in sql
        assert "FROM raw_t" in sql
        assert "WHERE _rn = 1" in sql

    def test_dedup_window_composite_key_and_multi_order(self):
        ingest = build_ingest_select(
            _umf(
                columns=_COLS,
                primary_key=["id", "name"],
                order_by=["seq", "_load_ts"],
            )
        )
        sql = ingest.dedup_window_sql("src")
        assert "PARTITION BY id, name ORDER BY seq DESC, _load_ts DESC" in sql

    def test_empty_columns_yields_empty_block(self):
        ingest = build_ingest_select(_umf(columns=[]))
        assert ingest.columns == []
        assert ingest.select_block == ""

    def test_is_frozen_dataclass(self):
        ingest = build_ingest_select(_umf(columns=_COLS))
        assert isinstance(ingest, IngestSelect)
        with pytest.raises((AttributeError, TypeError)):
            ingest.mode = "snapshot"  # type: ignore[misc]

    def test_unsupported_dialect_raises_with_shared_message(self):
        with pytest.raises(
            ValueError,
            match=r"Unsupported dialect: 'postgres' \(expected one of spark, databricks, duckdb\)",
        ):
            build_ingest_select(_umf(columns=[]), dialect="postgres")


class TestGenerateIngestSqlStructure:
    def test_emits_three_sections_and_header(self):
        sql = generate_ingest_sql(_umf(columns=_COLS, primary_key=["id"]))
        assert "-- 1. Raw landing table" in sql
        assert "-- 2. Typed target table" in sql
        assert "-- 3. Raw -> ingested transform" in sql
        assert "Ingest plan: raw_t -> ingested_t" in sql

    def test_raw_table_is_all_string_plus_provenance(self):
        sql = generate_ingest_sql(_umf(columns=_COLS, primary_key=["id"]))
        raw_section = sql.split("-- 2.")[0]
        # EVERY business column is STRING in the raw landing table -- assert the
        # exact per-column declaration so an INT/DECIMAL leak would fail.
        import re

        for col in ("id", "name", "amt"):
            assert re.search(rf"\b{col}\s+STRING\b", raw_section), (
                f"raw column {col} is not declared STRING:\n{raw_section}"
            )
        # the numeric column is NOT carried as its typed form in the raw landing zone
        assert "DECIMAL" not in raw_section
        assert " INT" not in raw_section
        # provenance columns appended (with their fixed types)
        assert re.search(r"\b_source_file\s+STRING\b", raw_section)
        assert re.search(r"\b_load_ts\s+TIMESTAMP\b", raw_section)
        assert "USING DELTA" in raw_section

    def test_table_name_overrides(self):
        sql = generate_ingest_sql(
            _umf(columns=_COLS, primary_key=["id"]),
            raw_table="bronze.raw_x",
            ingested_table="silver.x",
        )
        assert "bronze.raw_x" in sql
        assert "silver.x" in sql
        assert "Ingest plan: bronze.raw_x -> silver.x" in sql

    def test_typed_decimal_precision_scale(self):
        sql = generate_ingest_sql(_umf(columns=_COLS, primary_key=["id"]))
        assert "DECIMAL(12,4)" in sql

    def test_typed_decimal_defaults(self):
        cols = [{"name": "amt", "data_type": "DECIMAL"}]
        sql = generate_ingest_sql(_umf(columns=cols, primary_key=[]))
        assert "DECIMAL(10,2)" in sql

    def test_typed_varchar_max_length(self):
        cols = [
            {"name": "id", "data_type": "INTEGER", "nullable": False},
            {"name": "code", "data_type": "VARCHAR", "max_length": 5, "nullable": True},
        ]
        sql = generate_ingest_sql(_umf(columns=cols, primary_key=["id"]))
        assert "VARCHAR(5)" in sql

    def test_typed_not_null_marker(self):
        import re

        sql = generate_ingest_sql(_umf(columns=_COLS, primary_key=["id"]))
        ing_section = sql.split("-- 2.")[1].split("-- 3.")[0]
        # id is non-nullable -> NOT NULL on THAT column; name is nullable -> no marker
        assert re.search(r"\bid\s+INT NOT NULL\b", ing_section), ing_section
        name_line = next(
            ln for ln in ing_section.splitlines() if re.search(r"\bname\b", ln)
        )
        assert "NOT NULL" not in name_line  # nullable column has no marker
        amt_line = next(
            ln for ln in ing_section.splitlines() if re.search(r"\bamt\b", ln)
        )
        assert "NOT NULL" not in amt_line  # amt has no nullable=False -> nullable

    def test_typed_datetime_maps_to_timestamp(self):
        cols = [
            {"name": "id", "data_type": "INTEGER", "nullable": False},
            {"name": "ts", "data_type": "DATETIME", "nullable": True},
        ]
        sql = generate_ingest_sql(_umf(columns=cols, primary_key=["id"]))
        ing_section = sql.split("-- 2.")[1].split("-- 3.")[0]
        assert "TIMESTAMP" in ing_section
        assert "DATETIME" not in ing_section  # never emit literal DATETIME

    def test_description_becomes_typed_comment(self):
        sql = generate_ingest_sql(
            _umf(columns=_COLS, primary_key=["id"], description="My table")
        )
        assert "COMMENT 'My table'" in sql

    def test_description_single_quotes_escaped(self):
        sql = generate_ingest_sql(
            _umf(columns=_COLS, primary_key=["id"], description="it's mine")
        )
        assert "it''s mine" in sql


class TestGenerateIngestSqlWriteBranches:
    """Each of the four write strategies emits the documented transform."""

    def test_incremental_with_pk_emits_merge(self):
        sql = generate_ingest_sql(
            _umf(columns=_COLS, mode="incremental", primary_key=["id"])
        )
        transform = sql.split("-- 3.")[1]
        assert "MERGE INTO ingested_t AS tgt" in transform
        assert "ON tgt.id = src.id" in transform
        assert "WHEN MATCHED THEN UPDATE SET *" in transform
        assert "WHEN NOT MATCHED THEN INSERT *" in transform
        # dedup window runs inside the USING subquery
        assert "row_number() OVER (PARTITION BY id" in transform

    def test_incremental_composite_pk_merge_on_clause(self):
        sql = generate_ingest_sql(
            _umf(columns=_COLS, mode="incremental", primary_key=["id", "name"])
        )
        transform = sql.split("-- 3.")[1]
        assert "ON tgt.id = src.id AND tgt.name = src.name" in transform

    def test_keyless_incremental_emits_blind_insert(self):
        sql = generate_ingest_sql(
            _umf(columns=_COLS, mode="incremental", primary_key=[])
        )
        transform = sql.split("-- 3.")[1]
        assert "INSERT INTO ingested_t" in transform
        assert "MERGE" not in transform
        assert "WARNING" in transform  # documents duplicate-accumulation risk
        assert "row_number()" not in transform  # no dedup without a key

    def test_snapshot_with_pk_emits_insert_overwrite(self):
        sql = generate_ingest_sql(
            _umf(columns=_COLS, mode="snapshot", primary_key=["id"])
        )
        transform = sql.split("-- 3.")[1]
        assert "INSERT OVERWRITE ingested_t" in transform
        assert "snapshot mode: full drop/reload" in transform
        assert "MERGE" not in transform

    def test_snapshot_no_pk_emits_blind_overwrite_with_warning(self):
        sql = generate_ingest_sql(_umf(columns=_COLS, mode="snapshot", primary_key=[]))
        transform = sql.split("-- 3.")[1]
        assert "INSERT OVERWRITE ingested_t" in transform
        assert "blind drop/reload" in transform
        assert "no key-level reconciliation" in transform
