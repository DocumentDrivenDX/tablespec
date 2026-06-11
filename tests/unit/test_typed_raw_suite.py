"""Raw-suite typing for typed sources (FEAT-031 SUITE-01..03).

Suite COMPOSITION branches on the UMF's declared ``source.kind``: sources
that land NATIVE-TYPED raw (jdbc/parquet, SRC-04/ADR-015) never receive
raw-stage string-shape checks (length/regex/strftime/castability) -- they
keep schema-type + nullability conformance and every ingested-stage check.
Delimited and legacy (no ``source:`` block) UMFs are byte-for-byte
unaffected (zero regression). Stage ROUTING stays data-driven via the
existing classification (SUITE-03); the seam lives in
``tablespec.gx_baseline``, not the executor.
"""

from __future__ import annotations

from typing import Any

import pytest

from tablespec.gx_baseline import (
    STRING_SHAPE_EXPECTATION_TYPES,
    BaselineExpectationGenerator,
    drop_string_shape_raw_expectations,
    raw_stage_is_typed,
)
from tablespec.models.umf import TYPED_RAW_SOURCE_KINDS, classify_validation_type

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]


def _umf_data(source: dict[str, Any] | None = None) -> dict[str, Any]:
    """A UMF dict that provokes every string-shape baseline category.

    ``code`` (length + regex pattern), ``event_date`` (DATE: cast +
    strftime), ``recorded_at`` (TIMESTAMP: cast), ``qty`` (INTEGER: cast),
    ``amount`` (DECIMAL: cast + profiling min/max -> ingested between).
    """
    data: dict[str, Any] = {
        "version": "1.0",
        "table_name": "events",
        "columns": [
            {
                "name": "code",
                "data_type": "VARCHAR",
                "length": 8,
                "nullable": {"default": False},
                "profiling": {"patterns": ["^[A-Z]{2}\\d{6}$"]},
            },
            {
                "name": "event_date",
                "data_type": "DATE",
                "format": "YYYY-MM-DD",
            },
            {
                "name": "recorded_at",
                "data_type": "TIMESTAMP",
            },
            {
                "name": "qty",
                "data_type": "INTEGER",
            },
            {
                "name": "amount",
                "data_type": "DECIMAL",
                "precision": 10,
                "scale": 2,
                "profiling": {"statistics": {"min": 0, "max": 100}},
            },
        ],
    }
    if source is not None:
        data["source"] = source
    return data


JDBC_SOURCE = {
    "kind": "jdbc",
    "url": "jdbc:sqlserver://example:1433;databaseName=Northwind",
    "dbtable": "[dbo].[Events]",
}
PARQUET_SOURCE = {"kind": "parquet", "path": "/data/events"}
DELIMITED_SOURCE = {"kind": "delimited", "delimiter": "|"}


@pytest.fixture
def generator() -> BaselineExpectationGenerator:
    return BaselineExpectationGenerator()


class TestRawStageIsTyped:
    def test_typed_kinds(self):
        assert TYPED_RAW_SOURCE_KINDS == frozenset({"jdbc", "parquet"})
        assert raw_stage_is_typed(_umf_data(JDBC_SOURCE))
        assert raw_stage_is_typed(_umf_data(PARQUET_SOURCE))

    def test_delimited_and_legacy_are_string_raw(self):
        assert not raw_stage_is_typed(_umf_data(DELIMITED_SOURCE))
        assert not raw_stage_is_typed(_umf_data())  # legacy: no source block

    def test_string_shape_types_all_classify_raw(self):
        """The withheld categories are raw-stage by classification (SUITE-03)."""
        for exp_type in STRING_SHAPE_EXPECTATION_TYPES:
            assert classify_validation_type(exp_type) in ("raw", "unknown")


class TestTypedRawComposition:
    """SUITE-01/02: typed raw composes no string-shape raw checks."""

    @pytest.mark.parametrize("source", [JDBC_SOURCE, PARQUET_SOURCE])
    def test_no_string_shape_checks_for_typed_source(self, generator, source):
        expectations = generator.generate_baseline_expectations(_umf_data(source))
        composed = {exp["type"] for exp in expectations}
        assert not (composed & STRING_SHAPE_EXPECTATION_TYPES), sorted(
            composed & STRING_SHAPE_EXPECTATION_TYPES
        )

    @pytest.mark.parametrize("source", [JDBC_SOURCE, PARQUET_SOURCE])
    def test_typed_source_keeps_schema_and_nullability_checks(self, generator, source):
        """SUITE-02: schema conformance + not-null survive for typed raw."""
        expectations = generator.generate_baseline_expectations(_umf_data(source))
        composed = {exp["type"] for exp in expectations}
        assert "expect_table_column_count_to_equal" in composed
        assert "expect_table_columns_to_match_ordered_list" in composed
        not_null = [
            exp
            for exp in expectations
            if exp["type"] == "expect_column_values_to_not_be_null"
        ]
        assert [exp["kwargs"]["column"] for exp in not_null] == ["code"]

    @pytest.mark.parametrize("source", [JDBC_SOURCE, PARQUET_SOURCE])
    def test_typed_source_keeps_ingested_stage_checks(self, generator, source):
        """Ingested-stage checks (typed-data semantics) still run."""
        expectations = generator.generate_baseline_expectations(_umf_data(source))
        between = [
            exp
            for exp in expectations
            if exp["type"] == "expect_column_values_to_be_between"
        ]
        assert len(between) == 1
        assert between[0]["kwargs"]["column"] == "amount"
        assert classify_validation_type(between[0]["type"]) == "ingested"


class TestDelimitedRegression:
    """SUITE-01 scoping: all-STRING raw keeps its string checks, unchanged."""

    @pytest.mark.parametrize("source", [DELIMITED_SOURCE, None])
    def test_string_checks_still_composed(self, generator, source):
        expectations = generator.generate_baseline_expectations(_umf_data(source))
        composed = {exp["type"] for exp in expectations}
        assert "expect_column_value_lengths_to_be_between" in composed
        assert "expect_column_values_to_match_strftime_format" in composed
        assert "expect_column_values_to_cast_to_type" in composed
        assert "expect_column_values_to_match_regex" in composed

    def test_delimited_output_identical_to_legacy(self, generator):
        """Declaring kind=delimited changes nothing vs. no source block."""
        legacy = generator.generate_baseline_expectations(_umf_data())
        delimited = generator.generate_baseline_expectations(
            _umf_data(DELIMITED_SOURCE)
        )
        assert delimited == legacy


class TestDropStringShapeRawExpectations:
    """The filter helper honors explicit stage metadata (SUITE-03)."""

    def test_raw_string_shape_dropped(self):
        exps = [
            {
                "type": "expect_column_values_to_cast_to_type",
                "kwargs": {"column": "d", "target_type": "DATE"},
                "meta": {},
            }
        ]
        assert drop_string_shape_raw_expectations(exps) == []

    def test_explicit_ingested_stage_survives(self):
        exps = [
            {
                "type": "expect_column_values_to_match_regex",
                "kwargs": {"column": "c", "regex": "^x$"},
                "meta": {"validation_stage": "ingested"},
            }
        ]
        assert drop_string_shape_raw_expectations(exps) == exps

    def test_non_string_shape_untouched(self):
        exps = [
            {
                "type": "expect_column_values_to_not_be_null",
                "kwargs": {"column": "c"},
                "meta": {},
            },
            {
                "type": "expect_column_values_to_be_between",
                "kwargs": {"column": "c", "min_value": 0, "max_value": 1},
                "meta": {},
            },
        ]
        assert drop_string_shape_raw_expectations(exps) == exps
