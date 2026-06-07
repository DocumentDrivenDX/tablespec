"""Spark Connect (Sail) lane for native GX suite execution and TableValidator.

GX 1.x's ``add_spark`` engine is classic-Spark only: it uses classic
``pyspark.sql.functions`` that assert a live JVM ``SparkContext``, which does not
exist on Spark Connect. On Connect that path silently returns ``success=False`` /
``result={}`` for every data-scanning expectation. ``GXSuiteExecutor`` therefore
routes Connect DataFrames to a native DataFrame-API path
(``_execute_native`` -> ``native_executor``).

This lane proves that native path is CORRECT — not just non-crashing — by running
every supported expectation type against BOTH a clean dataset (expect
``success=True``) and a dirty dataset (expect ``success=False`` with the exact
``unexpected_count``). It uses pysail's Rust Spark Connect server, so no JVM /
JAVA_HOME is required. The same operations run on real Databricks serverless.
"""

from __future__ import annotations

import warnings

# @covers US-022-AC1
# @covers US-022-AC2
# @covers US-022-AC3
# @covers US-022-AC4

import pytest

try:
    from pysail.spark import SparkConnectServer

    # Use the Spark CONNECT builder directly: the top-level remote().getOrCreate()
    # raises SESSION_ALREADY_EXIST when a classic JVM session is active in the
    # process (as during the full make test run). The connect builder has no such
    # guard and leaves any classic session untouched.
    from pyspark.sql.connect.session import SparkSession as RemoteSparkSession

    _HAS_SAIL = True
except ImportError:
    _HAS_SAIL = False

pytestmark = [
    pytest.mark.no_spark,  # Sail needs no JVM/JAVA_HOME; skip classic-Spark setup.
    pytest.mark.skipif(not _HAS_SAIL, reason="pysail not available"),
]


@pytest.fixture(scope="module")
def sail_spark():
    """Start a Sail Spark Connect server and yield a Connect SparkSession."""
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=ResourceWarning)
        server = SparkConnectServer()
        server.start()
        host, port = server.listening_address
        session = (
            RemoteSparkSession.builder.remote(f"sc://{host}:{port}")
            .appName("tablespec-validation-connect-sail")
            .create()
        )
        yield session
        session.stop()
        server.stop()


def _run(spark, expectations, data, schema):
    from tablespec.validation.gx_executor import GXSuiteExecutor

    df = spark.createDataFrame(data, schema)
    executor = GXSuiteExecutor(spark=spark)
    return executor.execute_suite(df, expectations)


def _by_type(result):
    return {r.expectation_type: r for r in result.results}


# ─────────────────────────────────────────────────────────────────────
# Routing: a Connect DataFrame must take the native path, not add_spark.
# ─────────────────────────────────────────────────────────────────────


def test_connect_dataframe_is_detected(sail_spark):
    from tablespec.validation.gx_executor import GXSuiteExecutor

    df = sail_spark.createDataFrame([(1,)], "x int")
    assert GXSuiteExecutor._is_connect_dataframe(df) is True


# ─────────────────────────────────────────────────────────────────────
# Per-expectation: clean -> success, dirty -> failure w/ correct count.
# ─────────────────────────────────────────────────────────────────────


def test_row_count_between(sail_spark):
    exp = [
        {
            "type": "expect_table_row_count_to_be_between",
            "kwargs": {"min_value": 2, "max_value": 5},
        }
    ]
    schema = "id int"
    clean = _by_type(_run(sail_spark, exp, [(1,), (2,), (3,)], schema))
    assert clean["expect_table_row_count_to_be_between"].success is True
    assert clean["expect_table_row_count_to_be_between"].observed_value == 3

    dirty = _by_type(_run(sail_spark, exp, [(1,)], schema))
    assert dirty["expect_table_row_count_to_be_between"].success is False
    assert dirty["expect_table_row_count_to_be_between"].observed_value == 1


def test_column_count_to_equal(sail_spark):
    schema = "a int, b int"
    clean = _by_type(
        _run(
            sail_spark,
            [{"type": "expect_table_column_count_to_equal", "kwargs": {"value": 2}}],
            [(1, 2)],
            schema,
        )
    )
    assert clean["expect_table_column_count_to_equal"].success is True

    dirty = _by_type(
        _run(
            sail_spark,
            [{"type": "expect_table_column_count_to_equal", "kwargs": {"value": 3}}],
            [(1, 2)],
            schema,
        )
    )
    assert dirty["expect_table_column_count_to_equal"].success is False
    assert dirty["expect_table_column_count_to_equal"].observed_value == 2


def test_columns_to_match_ordered_list(sail_spark):
    schema = "a int, b int"
    clean = _by_type(
        _run(
            sail_spark,
            [
                {
                    "type": "expect_table_columns_to_match_ordered_list",
                    "kwargs": {"column_list": ["a", "b"]},
                }
            ],
            [(1, 2)],
            schema,
        )
    )
    assert clean["expect_table_columns_to_match_ordered_list"].success is True

    dirty = _by_type(
        _run(
            sail_spark,
            [
                {
                    "type": "expect_table_columns_to_match_ordered_list",
                    "kwargs": {"column_list": ["b", "a"]},
                }
            ],
            [(1, 2)],
            schema,
        )
    )
    assert dirty["expect_table_columns_to_match_ordered_list"].success is False


def test_column_values_to_be_of_type(sail_spark):
    schema = "id int, name string"
    clean = _by_type(
        _run(
            sail_spark,
            [
                {
                    "type": "expect_column_values_to_be_of_type",
                    "kwargs": {"column": "name", "type_": "StringType"},
                }
            ],
            [(1, "a")],
            schema,
        )
    )
    assert clean["expect_column_values_to_be_of_type"].success is True

    dirty = _by_type(
        _run(
            sail_spark,
            [
                {
                    "type": "expect_column_values_to_be_of_type",
                    "kwargs": {"column": "name", "type_": "IntegerType"},
                }
            ],
            [(1, "a")],
            schema,
        )
    )
    assert dirty["expect_column_values_to_be_of_type"].success is False


def test_values_to_not_be_null(sail_spark):
    exp = [
        {
            "type": "expect_column_values_to_not_be_null",
            "kwargs": {"column": "v"},
        }
    ]
    schema = "v string"
    clean = _by_type(_run(sail_spark, exp, [("a",), ("b",)], schema))
    assert clean["expect_column_values_to_not_be_null"].success is True

    dirty = _by_type(_run(sail_spark, exp, [("a",), (None,), (None,)], schema))
    r = dirty["expect_column_values_to_not_be_null"]
    assert r.success is False
    assert r.unexpected_count == 2


def test_values_to_not_be_null_with_row_condition(sail_spark):
    """Per-context not-null: only rows matching row_condition are scoped."""
    exp = [
        {
            "type": "expect_column_values_to_not_be_null",
            "kwargs": {
                "column": "v",
                "row_condition": "lob='MD'",
                "condition_parser": "spark",
            },
        }
    ]
    schema = "lob string, v string"
    # MP rows have nulls but are out of scope; MD rows are all non-null -> success.
    clean = _by_type(
        _run(sail_spark, exp, [("MD", "x"), ("MP", None), ("MD", "y")], schema)
    )
    assert clean["expect_column_values_to_not_be_null"].success is True

    dirty = _by_type(
        _run(sail_spark, exp, [("MD", None), ("MP", "ok"), ("MD", "y")], schema)
    )
    r = dirty["expect_column_values_to_not_be_null"]
    assert r.success is False
    assert r.unexpected_count == 1


def test_values_to_be_in_set(sail_spark):
    exp = [
        {
            "type": "expect_column_values_to_be_in_set",
            "kwargs": {"column": "flag", "value_set": ["Y", "N"]},
        }
    ]
    schema = "flag string"
    clean = _by_type(_run(sail_spark, exp, [("Y",), ("N",), (None,)], schema))
    assert clean["expect_column_values_to_be_in_set"].success is True

    dirty = _by_type(_run(sail_spark, exp, [("Y",), ("X",), ("Z",)], schema))
    r = dirty["expect_column_values_to_be_in_set"]
    assert r.success is False
    assert r.unexpected_count == 2
    assert set(r.unexpected_values) == {"X", "Z"}


def test_values_to_be_between(sail_spark):
    exp = [
        {
            "type": "expect_column_values_to_be_between",
            "kwargs": {"column": "age", "min_value": 0, "max_value": 120},
        }
    ]
    schema = "age int"
    clean = _by_type(_run(sail_spark, exp, [(1,), (50,), (120,), (None,)], schema))
    assert clean["expect_column_values_to_be_between"].success is True

    dirty = _by_type(_run(sail_spark, exp, [(1,), (-5,), (200,)], schema))
    r = dirty["expect_column_values_to_be_between"]
    assert r.success is False
    assert r.unexpected_count == 2


def test_values_to_match_regex(sail_spark):
    exp = [
        {
            "type": "expect_column_values_to_match_regex",
            "kwargs": {"column": "code", "regex": r"^[A-Z]{2}$"},
        }
    ]
    schema = "code string"
    clean = _by_type(_run(sail_spark, exp, [("AB",), ("CD",), (None,)], schema))
    assert clean["expect_column_values_to_match_regex"].success is True

    dirty = _by_type(_run(sail_spark, exp, [("AB",), ("a",), ("123",)], schema))
    r = dirty["expect_column_values_to_match_regex"]
    assert r.success is False
    assert r.unexpected_count == 2


def test_value_lengths_to_be_between(sail_spark):
    exp = [
        {
            "type": "expect_column_value_lengths_to_be_between",
            "kwargs": {"column": "s", "max_value": 3},
        }
    ]
    schema = "s string"
    clean = _by_type(_run(sail_spark, exp, [("ab",), ("abc",), (None,)], schema))
    assert clean["expect_column_value_lengths_to_be_between"].success is True

    dirty = _by_type(_run(sail_spark, exp, [("ab",), ("abcd",), ("abcde",)], schema))
    r = dirty["expect_column_value_lengths_to_be_between"]
    assert r.success is False
    assert r.unexpected_count == 2


def test_values_to_be_unique(sail_spark):
    exp = [
        {
            "type": "expect_column_values_to_be_unique",
            "kwargs": {"column": "id"},
        }
    ]
    schema = "id int"
    clean = _by_type(_run(sail_spark, exp, [(1,), (2,), (3,)], schema))
    assert clean["expect_column_values_to_be_unique"].success is True

    # 1 appears 3x -> all 3 rows counted as unexpected.
    dirty = _by_type(_run(sail_spark, exp, [(1,), (1,), (1,), (2,)], schema))
    r = dirty["expect_column_values_to_be_unique"]
    assert r.success is False
    assert r.unexpected_count == 3
    assert r.unexpected_values == [1]


def test_values_to_match_strftime_format(sail_spark):
    exp = [
        {
            "type": "expect_column_values_to_match_strftime_format",
            "kwargs": {"column": "d", "strftime_format": "%Y-%m-%d"},
        }
    ]
    schema = "d string"
    clean = _by_type(
        _run(sail_spark, exp, [("2023-01-15",), ("2024-12-31",), (None,)], schema)
    )
    assert clean["expect_column_values_to_match_strftime_format"].success is True

    # "2023-02-30" is impossible; "01/15/2023" wrong shape -> 2 unexpected.
    dirty = _by_type(
        _run(
            sail_spark,
            exp,
            [("2023-01-15",), ("2023-02-30",), ("01/15/2023",)],
            schema,
        )
    )
    r = dirty["expect_column_values_to_match_strftime_format"]
    assert r.success is False
    assert r.unexpected_count == 2


def test_cast_to_type_date(sail_spark):
    """The custom cast expectation reports correctly on Connect (no false positive)."""
    exp = [
        {
            "type": "expect_column_values_to_cast_to_type",
            "kwargs": {
                "column": "d",
                "target_type": "DATE",
                "format": "YYYY-MM-DD",
                "mostly": 1.0,
            },
        }
    ]
    schema = "d string"
    clean = _by_type(
        _run(sail_spark, exp, [("2023-01-15",), ("2024-12-31",), (None,)], schema)
    )
    assert clean["expect_column_values_to_cast_to_type"].success is True

    dirty = _by_type(
        _run(
            sail_spark,
            exp,
            [("2023-01-15",), ("2023-02-30",), ("notadate",)],
            schema,
        )
    )
    r = dirty["expect_column_values_to_cast_to_type"]
    assert r.success is False
    assert r.unexpected_count == 2


def test_cast_to_type_integer(sail_spark):
    exp = [
        {
            "type": "expect_column_values_to_cast_to_type",
            "kwargs": {"column": "n", "target_type": "INTEGER", "mostly": 1.0},
        }
    ]
    schema = "n string"
    clean = _by_type(_run(sail_spark, exp, [("5",), ("10",), (None,)], schema))
    assert clean["expect_column_values_to_cast_to_type"].success is True

    dirty = _by_type(_run(sail_spark, exp, [("5",), ("x",), ("3.5",)], schema))
    r = dirty["expect_column_values_to_cast_to_type"]
    assert r.success is False
    assert r.unexpected_count == 2


def test_cross_column_date_order(sail_spark):
    exp = [
        {
            "type": "expect_column_pair_values_a_to_be_greater_than_b",
            "kwargs": {
                "column_A": "end_date",
                "column_B": "start_date",
                "or_equal": True,
            },
        }
    ]
    schema = "start_date date, end_date date"
    import datetime

    clean = _by_type(
        _run(
            sail_spark,
            exp,
            [(datetime.date(2023, 1, 1), datetime.date(2023, 6, 1))],
            schema,
        )
    )
    assert clean["expect_column_pair_values_a_to_be_greater_than_b"].success is True

    dirty = _by_type(
        _run(
            sail_spark,
            exp,
            [(datetime.date(2023, 6, 1), datetime.date(2023, 1, 1))],
            schema,
        )
    )
    r = dirty["expect_column_pair_values_a_to_be_greater_than_b"]
    assert r.success is False
    assert r.unexpected_count == 1


# ─────────────────────────────────────────────────────────────────────
# Whole-suite parity: a clean dataset passes ALL baseline expectations.
# ─────────────────────────────────────────────────────────────────────


def test_full_suite_clean_passes(sail_spark):
    exp = [
        {"type": "expect_table_column_count_to_equal", "kwargs": {"value": 2}},
        {
            "type": "expect_table_columns_to_match_ordered_list",
            "kwargs": {"column_list": ["id", "flag"]},
        },
        {"type": "expect_column_values_to_not_be_null", "kwargs": {"column": "id"}},
        {
            "type": "expect_column_values_to_be_unique",
            "kwargs": {"column": "id"},
        },
        {
            "type": "expect_column_values_to_be_in_set",
            "kwargs": {"column": "flag", "value_set": ["Y", "N"]},
        },
    ]
    schema = "id int, flag string"
    result = _run(sail_spark, exp, [(1, "Y"), (2, "N"), (3, "Y")], schema)
    assert result.success is True
    assert result.total == 5
    assert result.passed == 5


# ─────────────────────────────────────────────────────────────────────
# TableValidator end-to-end on a Connect session.
# ─────────────────────────────────────────────────────────────────────


_UMF_YAML = """
table_name: members
version: "1.0"
columns:
  - name: member_id
    data_type: VARCHAR
    nullable:
      MD: false
  - name: signup_date
    data_type: DATE
    format: YYYY-MM-DD
  - name: state
    data_type: VARCHAR
"""


@pytest.fixture
def umf_path(tmp_path):
    p = tmp_path / "members.umf.yaml"
    p.write_text(_UMF_YAML)
    return p


def test_table_validator_clean_connect(sail_spark, umf_path):
    from tablespec.validation.table_validator import TableValidator

    schema = "member_id string, signup_date string, state string"
    df = sail_spark.createDataFrame(
        [
            ("m1", "2023-01-15", "CA"),
            ("m2", "2024-06-30", "NY"),
        ],
        schema,
    )
    validator = TableValidator(sail_spark)
    errors = validator.validate_table(df, umf_path)
    rows = [r.asDict() for r in errors.collect()]
    rule_names = {r["rule_name"] for r in rows}
    # The cast-to-type GX check must NOT report a false positive on Connect:
    # before the native path, add_spark silently failed every cast on Connect.
    assert "expect_column_values_to_cast_to_type" not in rule_names, (
        f"cast check false-positived on clean data: {rows}"
    )
    # No nullability / strftime failures on clean data either.
    assert "not_null_constraint" not in rule_names
    assert "expect_column_values_to_match_strftime_format" not in rule_names
    # The only error tolerated here is the data_type mismatch inherent to
    # validating RAW string columns against a typed (DATE) UMF schema.
    assert rule_names <= {"type_mismatch"}, f"unexpected errors: {rows}"


def test_table_validator_dirty_connect(sail_spark, umf_path):
    from tablespec.validation.table_validator import TableValidator

    schema = "member_id string, signup_date string, state string"
    df = sail_spark.createDataFrame(
        [
            ("m1", "2023-01-15", "CA"),
            ("m2", "2023-02-30", "NY"),  # impossible date -> cast failure
            (None, "2024-06-30", "TX"),  # null required member_id
        ],
        schema,
    )
    validator = TableValidator(sail_spark)
    errors = validator.validate_table(df, umf_path)
    rows = [r.asDict() for r in errors.collect()]
    rule_names = {r["rule_name"] for r in rows}
    # The cast-to-type GX check must fire on the impossible date.
    assert "expect_column_values_to_cast_to_type" in rule_names
    # The not-null SQL check must fire on the null member_id.
    assert "not_null_constraint" in rule_names
