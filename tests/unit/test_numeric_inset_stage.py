"""Numeric value-sets must validate on the typed (ingested) stage, not raw strings.

A profiled low-cardinality NUMERIC column yields an
``expect_column_values_to_be_in_set`` whose value_set holds numbers (1.5, 2.0). On
the RAW all-string stage those never match the string representation ("1.50"), so
the expectation must carry ``meta.validation_stage == "ingested"``. String
value-sets keep the default raw routing. Covers both producers: the profiler
(``ProfileToGxMapper``) and the baseline generator (``gx_baseline``).
"""

from __future__ import annotations

import pytest

from tablespec.type_mappings import is_numeric_data_type


def _in_set(expectations, column):
    for e in expectations:
        if (
            e["type"] == "expect_column_values_to_be_in_set"
            and e["kwargs"]["column"] == column
        ):
            return e
    return None


@pytest.mark.parametrize(
    ("data_type", "expected"),
    [
        ("DecimalType", True),
        ("DECIMAL(10,2)", True),
        ("DoubleType", True),
        ("INTEGER", True),
        ("double", True),
        ("StringType", False),
        ("DATE", False),
        ("VARCHAR", False),
        (None, False),
    ],
)
def test_is_numeric_data_type(data_type, expected):
    assert is_numeric_data_type(data_type) is expected


def test_profiler_numeric_value_set_routes_to_ingested():
    from tablespec.profiling.gx_expectation_builder import ProfileToGxMapper
    from tablespec.profiling.types import ColumnProfile, DataFrameProfile

    profile = DataFrameProfile(
        num_records=4,
        columns={
            "amount": ColumnProfile(
                column_name="amount",
                completeness=1.0,
                data_type="DecimalType",
                distinct_values=[1.5, 2.0, 3.5],
            ),
            "status": ColumnProfile(
                column_name="status",
                completeness=1.0,
                data_type="StringType",
                distinct_values=["A", "B"],
            ),
        },
    )
    exps = ProfileToGxMapper().build_expectations(profile)

    numeric = _in_set(exps, "amount")
    assert numeric is not None, "numeric column should get an in_set expectation"
    assert numeric["meta"].get("validation_stage") == "ingested"

    string = _in_set(exps, "status")
    assert string is not None
    assert string["meta"].get("validation_stage") != "ingested"  # default -> raw


def test_baseline_numeric_value_set_routes_to_ingested():
    from tablespec.gx_baseline import BaselineExpectationGenerator

    umf = {
        "table_name": "t",
        "columns": [
            {
                "name": "amount",
                "data_type": "DECIMAL",
                "profiling": {"distinct_values": [1.5, 2.0]},
            },
            {
                "name": "status",
                "data_type": "STRING",
                "profiling": {"distinct_values": ["A", "B"]},
            },
        ],
    }
    exps = BaselineExpectationGenerator().generate_baseline_expectations(umf)

    numeric = _in_set(exps, "amount")
    assert numeric is not None
    assert numeric["meta"].get("validation_stage") == "ingested"

    string = _in_set(exps, "status")
    assert string is not None
    assert string["meta"].get("validation_stage") != "ingested"
