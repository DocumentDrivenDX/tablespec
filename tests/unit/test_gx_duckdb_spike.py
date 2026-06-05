"""Spike test: verify Great Expectations 1.6+ works with DuckDB.

This spike intentionally uses pandas via DuckDB export -- not part of the
Spark/Sail validation pipeline.

This is a proof-of-concept to validate that GX can query data stored in
DuckDB.  Two approaches are tested:

1. **SqlAlchemy datasource** (`duckdb-engine`) -- the ideal path.
2. **Pandas datasource** fed from `duckdb.sql().df()` -- the fallback.

Findings are documented in the test docstrings.
"""

from __future__ import annotations

import pytest

try:
    import duckdb
    import sqlalchemy  # noqa: F401

    HAS_DUCKDB = True
except ImportError:
    HAS_DUCKDB = False

pytestmark = [
    pytest.mark.fast,
    pytest.mark.no_spark,
    pytest.mark.skipif(not HAS_DUCKDB, reason="duckdb/duckdb-engine not installed"),
    pytest.mark.filterwarnings("ignore::ResourceWarning"),
    pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning"),
]


# ---------------------------------------------------------------------------
# Approach 1: SqlAlchemy datasource (ideal, but currently broken)
# ---------------------------------------------------------------------------


class TestGxDuckdbSqlAlchemy:
    """Attempt to use GX's SqlAlchemy execution engine with DuckDB.

    FINDING: GX 1.15.1 hits an ``IndexError: list index out of range`` in
    ``SqlAlchemyExecutionEngine.resolve_metric_bundle`` (sqlalchemy_execution_engine.py:1022)
    when DuckDB is the backend.  The bundled SQL query returns an empty
    result set, so ``res[0]`` fails and is re-raised as a
    ``MetricResolutionError``.  GX captures that exception in the validation
    result rather than propagating it, so ``validate(...).success`` is
    ``False`` with ``exception_info`` recording ``"list index out of range"``.
    This is a dialect-compatibility gap inside Great Expectations (not a
    duckdb-engine bug) and is out of scope for this project to patch.

    Rather than a perpetual ``strict=True`` xfail placeholder, the test below
    pins the gap with a positive assertion: ``success is False`` plus the
    captured exception substring.  It stays green while the gap exists and
    will fail intentionally (flagging that this documentation is stale) if a
    future GX/duckdb-engine upgrade closes the gap.

    Verified reproducing on: great_expectations 1.15.1, duckdb 1.5.0,
    sqlalchemy 2.0.48.
    """

    @pytest.fixture()
    def gx_sqla_batch(self, tmp_path):
        import great_expectations as gx

        db_path = tmp_path / "spike.duckdb"
        connection_string = f"duckdb:///{db_path}"

        engine = sqlalchemy.create_engine(connection_string)
        with engine.connect() as conn:
            conn.execute(
                sqlalchemy.text(
                    """
                    CREATE TABLE sample_data (
                        id INTEGER,
                        state_code VARCHAR,
                        full_name VARCHAR,
                        age INTEGER
                    )
                    """
                )
            )
            conn.execute(
                sqlalchemy.text(
                    """
                    INSERT INTO sample_data VALUES
                        (1, 'CA', 'Alice Smith', 30),
                        (2, 'TX', 'Bob Jones', NULL),
                        (3, 'NY', 'Charlie Brown', 25),
                        (4, 'CA', NULL, 40),
                        (5, 'FL', 'Eve Davis', 35)
                    """
                )
            )
            conn.commit()
        engine.dispose()

        context = gx.get_context()
        datasource = context.data_sources.add_sql(
            name="duckdb_spike_sqla",
            connection_string=connection_string,
            create_temp_table=False,
        )
        asset = datasource.add_table_asset(name="sample_data", table_name="sample_data")
        batch_def = asset.add_batch_definition_whole_table("full_table")
        return batch_def.get_batch()

    def test_sqla_duckdb_dialect_gap_is_pinned(self, gx_sqla_batch):
        """Pin the documented GX-SqlAlchemy/DuckDB dialect gap.

        GX's ``SqlAlchemyExecutionEngine.resolve_metric_bundle`` raises
        ``IndexError: list index out of range`` for the DuckDB dialect, which
        GX captures (rather than propagating).  The validation therefore
        reports ``success is False`` with the exception recorded in
        ``exception_info``.

        This is a pinned-failure test: it documents an upstream GX limitation
        that is out of scope to fix here.  If a future GX upgrade closes the
        gap, ``success`` becomes ``True`` / the exception disappears and this
        test fails -- a signal to remove this pin and re-enable the SqlAlchemy
        path (see the working Pandas fallback below).
        """
        import great_expectations as gx

        result = gx_sqla_batch.validate(
            gx.expectations.ExpectColumnValuesToNotBeNull(column="id")
        )

        # The metric resolution fails for the DuckDB dialect, so the
        # expectation cannot succeed.
        assert result.success is False

        # GX captures the underlying IndexError in exception_info.
        exception_messages = [
            info.get("exception_message", "")
            for info in (result.exception_info or {}).values()
            if isinstance(info, dict)
        ]
        assert any("index out of range" in message for message in exception_messages), (
            "Expected the GX-DuckDB 'list index out of range' dialect gap, "
            f"but got exception_info={result.exception_info!r}. If GX/duckdb-engine "
            "fixed this, remove this pin and re-enable the SqlAlchemy datasource path."
        )


# ---------------------------------------------------------------------------
# Approach 2: Pandas datasource (working fallback)
# ---------------------------------------------------------------------------


class TestGxDuckdbPandas:
    """Use DuckDB to query data, then hand a DataFrame to GX's Pandas engine.

    This is the recommended approach until GX adds first-class DuckDB
    dialect support in its SqlAlchemy engine.
    """

    @pytest.fixture()
    def gx_pandas_batch(self):
        import great_expectations as gx

        # Build sample data in DuckDB, export as pandas DataFrame
        con = duckdb.connect(":memory:")
        con.execute(
            """
            CREATE TABLE sample_data (
                id INTEGER,
                state_code VARCHAR,
                full_name VARCHAR,
                age INTEGER
            )
            """
        )
        con.execute(
            """
            INSERT INTO sample_data VALUES
                (1, 'CA', 'Alice Smith', 30),
                (2, 'TX', 'Bob Jones', NULL),
                (3, 'NY', 'Charlie Brown', 25),
                (4, 'CA', NULL, 40),
                (5, 'FL', 'Eve Davis', 35)
            """
        )
        df = con.execute("SELECT * FROM sample_data").df()
        con.close()

        context = gx.get_context()
        datasource = context.data_sources.add_pandas(name="duckdb_pandas_spike")
        asset = datasource.add_dataframe_asset(name="sample_data")
        batch_def = asset.add_batch_definition_whole_dataframe("full_table")
        batch = batch_def.get_batch(batch_parameters={"dataframe": df})
        return batch

    # -- expect_column_values_to_not_be_null --------------------------------

    def test_not_null_passes(self, gx_pandas_batch):
        """Column 'id' has no nulls -- expectation should pass."""
        import great_expectations as gx

        result = gx_pandas_batch.validate(
            gx.expectations.ExpectColumnValuesToNotBeNull(column="id")
        )
        assert result.success is True

    def test_not_null_fails(self, gx_pandas_batch):
        """Column 'full_name' has one null -- expectation should fail."""
        import great_expectations as gx

        result = gx_pandas_batch.validate(
            gx.expectations.ExpectColumnValuesToNotBeNull(column="full_name")
        )
        assert result.success is False

    # -- expect_column_values_to_be_in_set ----------------------------------

    def test_in_set_passes(self, gx_pandas_batch):
        """All state_code values are in the allowed set."""
        import great_expectations as gx

        result = gx_pandas_batch.validate(
            gx.expectations.ExpectColumnValuesToBeInSet(
                column="state_code",
                value_set=["CA", "TX", "NY", "FL", "WA"],
            )
        )
        assert result.success is True

    def test_in_set_fails(self, gx_pandas_batch):
        """state_code='FL' is not in the restricted set -- should fail."""
        import great_expectations as gx

        result = gx_pandas_batch.validate(
            gx.expectations.ExpectColumnValuesToBeInSet(
                column="state_code",
                value_set=["CA", "TX", "NY"],
            )
        )
        assert result.success is False

    # -- expect_column_value_lengths_to_be_between --------------------------

    def test_lengths_between_passes(self, gx_pandas_batch):
        """state_code is always 2 chars."""
        import great_expectations as gx

        result = gx_pandas_batch.validate(
            gx.expectations.ExpectColumnValueLengthsToBeBetween(
                column="state_code",
                min_value=2,
                max_value=2,
            )
        )
        assert result.success is True

    def test_lengths_between_fails(self, gx_pandas_batch):
        """full_name lengths vary and exceed max_value=5 -- should fail."""
        import great_expectations as gx

        result = gx_pandas_batch.validate(
            gx.expectations.ExpectColumnValueLengthsToBeBetween(
                column="full_name",
                min_value=1,
                max_value=5,
            )
        )
        assert result.success is False
