"""Tests for Spark-free UMF reflection from INFORMATION_SCHEMA metadata.

The Databricks Apps path: a SQL warehouse supplies rows, no SparkSession
exists, and tablespec maps those rows to a UMF.
"""

from __future__ import annotations

import pytest

from tablespec.profiling.sql_reflect import (
    ColumnMeta,
    column_meta_from_row,
    normalize_sql_type,
    umf_from_information_schema,
)


class TestNormalizeSqlType:
    @pytest.mark.parametrize(
        ("declared", "expected"),
        [
            ("STRING", "VARCHAR"),
            ("string", "VARCHAR"),
            ("BIGINT", "INTEGER"),
            ("DOUBLE", "FLOAT"),
            ("TIMESTAMP_NTZ", "TIMESTAMP"),
            ("BOOLEAN", "BOOLEAN"),
        ],
    )
    def test_maps_known_types(self, declared: str, expected: str) -> None:
        assert normalize_sql_type(declared) == expected

    @pytest.mark.parametrize(
        ("declared", "expected"),
        [("decimal(10,2)", "DECIMAL"), ("varchar(50)", "VARCHAR")],
    )
    def test_strips_type_parameters(self, declared: str, expected: str) -> None:
        assert normalize_sql_type(declared) == expected

    @pytest.mark.parametrize("declared", ["nvarchar", "nchar", "ntext"])
    def test_national_variants_resolve_to_base(self, declared: str) -> None:
        assert normalize_sql_type(declared) is not None

    def test_unmapped_type_returns_none(self) -> None:
        assert normalize_sql_type("ARRAY<STRING>") is None


class TestColumnMetaFromRow:
    def test_accepts_lowercase_databricks_keys(self) -> None:
        meta = column_meta_from_row(
            {"column_name": "id", "data_type": "STRING", "is_nullable": "NO"}
        )
        assert meta.name == "id"
        assert meta.is_nullable is False

    def test_accepts_uppercase_keys(self) -> None:
        meta = column_meta_from_row(
            {"COLUMN_NAME": "id", "DATA_TYPE": "INT", "IS_NULLABLE": "YES"}
        )
        assert meta.name == "id"
        assert meta.is_nullable is True

    def test_blank_numerics_become_none(self) -> None:
        meta = column_meta_from_row(
            {"column_name": "x", "data_type": "STRING", "numeric_precision": ""}
        )
        assert meta.numeric_precision is None


class TestUmfFromInformationSchema:
    def test_builds_umf_with_types_and_nullability(self) -> None:
        umf = umf_from_information_schema(
            "encounter",
            [
                ColumnMeta("encounter_id", "STRING", is_nullable=False),
                ColumnMeta("start_date", "DATE"),
            ],
        )
        assert umf.table_name == "encounter"
        assert [c.data_type for c in umf.columns] == ["VARCHAR", "DATE"]
        assert umf.columns[0].nullable.model_dump() == {"default": False}
        assert umf.columns[1].nullable.model_dump() == {"default": True}

    def test_orders_by_ordinal_position(self) -> None:
        umf = umf_from_information_schema(
            "t",
            [
                ColumnMeta("b", "STRING", ordinal_position=2),
                ColumnMeta("a", "STRING", ordinal_position=1),
            ],
        )
        assert [c.name for c in umf.columns] == ["a", "b"]

    def test_preserves_caller_order_when_ordinals_absent(self) -> None:
        umf = umf_from_information_schema(
            "t", [ColumnMeta("b", "STRING"), ColumnMeta("a", "STRING")]
        )
        assert [c.name for c in umf.columns] == ["b", "a"]

    def test_decimal_carries_precision_and_scale(self) -> None:
        umf = umf_from_information_schema(
            "t",
            [ColumnMeta("amt", "DECIMAL", numeric_precision=10, numeric_scale=2)],
        )
        assert umf.columns[0].precision == 10
        assert umf.columns[0].scale == 2

    def test_varchar_carries_length(self) -> None:
        umf = umf_from_information_schema(
            "t", [ColumnMeta("name", "VARCHAR", character_maximum_length=50)]
        )
        assert umf.columns[0].length == 50

    def test_comment_becomes_description(self) -> None:
        umf = umf_from_information_schema(
            "t", [ColumnMeta("id", "STRING", comment="The identifier")]
        )
        assert umf.columns[0].description == "The identifier"

    def test_missing_comment_falls_back_to_generated_description(self) -> None:
        umf = umf_from_information_schema("t", [ColumnMeta("id", "STRING")])
        assert "reflected from information_schema" in (umf.columns[0].description or "")

    def test_unmapped_type_is_kept_as_varchar_not_dropped(self, caplog) -> None:
        """Dropping the column would misrepresent the table's shape."""
        umf = umf_from_information_schema(
            "t", [ColumnMeta("id", "STRING"), ColumnMeta("tags", "ARRAY<STRING>")]
        )
        assert [c.name for c in umf.columns] == ["id", "tags"]
        assert umf.columns[1].data_type == "VARCHAR"
        assert "unmapped SQL type" in caplog.text

    def test_accepts_raw_mapping_rows(self) -> None:
        umf = umf_from_information_schema(
            "t", [{"column_name": "id", "data_type": "BIGINT", "is_nullable": "NO"}]
        )
        assert umf.columns[0].data_type == "INTEGER"
