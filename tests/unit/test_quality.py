"""Unit tests for quality package - models, storage, and baseline storage.

Tests pure Python components without requiring PySpark.
PySpark-dependent components are tested with skipif markers.
"""

# @covers US-016-AC1
# @covers US-016-AC2
# @covers US-016-AC3
# @covers US-016-AC4

from __future__ import annotations

import json
import sys
from datetime import datetime
from unittest.mock import MagicMock

import pytest

# Mark all tests in this module to skip Spark environment setup
pytestmark = pytest.mark.no_spark

# The quality modules import pyspark.sql.types at module level,
# so we need to mock PySpark before importing them.
HAS_PYSPARK = False
try:
    import pyspark  # noqa: F401

    HAS_PYSPARK = True
except ImportError:
    pass


def _import_baseline_storage():
    """Import baseline_storage, mocking PySpark if needed."""
    if not HAS_PYSPARK:
        # Create mock pyspark module hierarchy for import
        mock_pyspark = MagicMock()
        mock_types = MagicMock()
        # Create actual mock type classes that can be called
        mock_types.LongType = MagicMock
        mock_types.StringType = MagicMock
        mock_types.StructField = MagicMock
        mock_types.StructType = MagicMock
        mock_types.TimestampType = MagicMock

        modules = {
            "pyspark": mock_pyspark,
            "pyspark.sql": mock_pyspark.sql,
            "pyspark.sql.types": mock_types,
        }
        for mod_name, mod in modules.items():
            if mod_name not in sys.modules:
                sys.modules[mod_name] = mod

    from tablespec.quality.baseline_storage import (
        BaselineWriter,
        ColumnDistribution,
        DistributionComparison,
        NumericStats,
        RecordComparison,
        RowCountComparison,
        RunBaseline,
    )

    return {
        "BaselineWriter": BaselineWriter,
        "ColumnDistribution": ColumnDistribution,
        "DistributionComparison": DistributionComparison,
        "NumericStats": NumericStats,
        "RecordComparison": RecordComparison,
        "RowCountComparison": RowCountComparison,
        "RunBaseline": RunBaseline,
    }


def _import_storage():
    """Import storage, mocking PySpark if needed."""
    if not HAS_PYSPARK:
        mock_pyspark = MagicMock()
        mock_types = MagicMock()
        mock_types.BooleanType = MagicMock
        mock_types.DoubleType = MagicMock
        mock_types.IntegerType = MagicMock
        mock_types.LongType = MagicMock
        mock_types.StringType = MagicMock
        mock_types.StructField = MagicMock
        mock_types.StructType = MagicMock
        mock_types.TimestampType = MagicMock

        modules = {
            "pyspark": mock_pyspark,
            "pyspark.sql": mock_pyspark.sql,
            "pyspark.sql.types": mock_types,
        }
        for mod_name, mod in modules.items():
            if mod_name not in sys.modules:
                sys.modules[mod_name] = mod

    from tablespec.quality.storage import QualityResultsWriter

    return {"QualityResultsWriter": QualityResultsWriter}


# --- Baseline Storage Model Tests ---


class TestColumnDistribution:
    """Test ColumnDistribution Pydantic model."""

    def test_create_minimal(self):
        m = _import_baseline_storage()
        dist = m["ColumnDistribution"](column_name="status")
        assert dist.column_name == "status"
        assert dist.value_counts == {}
        assert dist.distinct_count == 0
        assert dist.null_count == 0
        assert dist.total_count == 0

    def test_create_with_values(self):
        m = _import_baseline_storage()
        dist = m["ColumnDistribution"](
            column_name="gender",
            value_counts={"M": 100, "F": 150},
            distinct_count=2,
            null_count=5,
            total_count=255,
        )
        assert dist.value_counts == {"M": 100, "F": 150}
        assert dist.distinct_count == 2
        assert dist.null_count == 5
        assert dist.total_count == 255

    def test_model_serialization(self):
        m = _import_baseline_storage()
        dist = m["ColumnDistribution"](
            column_name="status",
            value_counts={"A": 10, "B": 20},
            distinct_count=2,
            null_count=0,
            total_count=30,
        )
        data = dist.model_dump()
        assert data["column_name"] == "status"
        assert data["value_counts"] == {"A": 10, "B": 20}


class TestNumericStats:
    """Test NumericStats Pydantic model."""

    def test_create_minimal(self):
        m = _import_baseline_storage()
        stats = m["NumericStats"](column_name="amount")
        assert stats.column_name == "amount"
        assert stats.min_value is None
        assert stats.max_value is None
        assert stats.mean_value is None
        assert stats.stddev_value is None

    def test_create_with_values(self):
        m = _import_baseline_storage()
        stats = m["NumericStats"](
            column_name="price",
            min_value=1.0,
            max_value=999.99,
            mean_value=50.5,
            stddev_value=15.3,
        )
        assert stats.min_value == 1.0
        assert stats.max_value == 999.99
        assert stats.mean_value == 50.5
        assert stats.stddev_value == 15.3


class TestRunBaseline:
    """Test RunBaseline Pydantic model."""

    def test_create_minimal(self):
        m = _import_baseline_storage()
        baseline = m["RunBaseline"](
            run_id="run-001",
            run_timestamp=datetime(2025, 1, 15, 10, 0, 0),
            pipeline_name="test_pipeline",
            table_name="test_table",
            row_count=1000,
        )
        assert baseline.run_id == "run-001"
        assert baseline.pipeline_name == "test_pipeline"
        assert baseline.table_name == "test_table"
        assert baseline.row_count == 1000
        assert baseline.column_distributions == {}
        assert baseline.numeric_stats == {}
        assert baseline.record_checksums is None
        assert baseline.primary_key_columns is None

    def test_create_with_distributions(self):
        m = _import_baseline_storage()
        dist = m["ColumnDistribution"](
            column_name="status",
            value_counts={"A": 500, "B": 500},
            distinct_count=2,
            total_count=1000,
        )
        baseline = m["RunBaseline"](
            run_id="run-002",
            run_timestamp=datetime(2025, 1, 15, 10, 0, 0),
            pipeline_name="pipeline",
            table_name="table",
            row_count=1000,
            column_distributions={"status": dist},
        )
        assert "status" in baseline.column_distributions
        assert baseline.column_distributions["status"].distinct_count == 2

    def test_create_with_numeric_stats(self):
        m = _import_baseline_storage()
        stats = m["NumericStats"](
            column_name="amount",
            min_value=0.0,
            max_value=100.0,
            mean_value=50.0,
            stddev_value=10.0,
        )
        baseline = m["RunBaseline"](
            run_id="run-003",
            run_timestamp=datetime(2025, 1, 15, 10, 0, 0),
            pipeline_name="pipeline",
            table_name="table",
            row_count=500,
            numeric_stats={"amount": stats},
        )
        assert "amount" in baseline.numeric_stats
        assert baseline.numeric_stats["amount"].mean_value == 50.0

    def test_create_with_record_checksums(self):
        m = _import_baseline_storage()
        baseline = m["RunBaseline"](
            run_id="run-004",
            run_timestamp=datetime(2025, 1, 15, 10, 0, 0),
            pipeline_name="pipeline",
            table_name="table",
            row_count=100,
            record_checksums={"pk1": "hash1", "pk2": "hash2"},
            primary_key_columns=["id"],
        )
        assert baseline.record_checksums == {"pk1": "hash1", "pk2": "hash2"}
        assert baseline.primary_key_columns == ["id"]


class TestRowCountComparison:
    """Test RowCountComparison Pydantic model."""

    def test_increase(self):
        m = _import_baseline_storage()
        comp = m["RowCountComparison"](
            previous_count=100,
            current_count=120,
            absolute_change=20,
            percent_change=20.0,
            direction="increase",
        )
        assert comp.direction == "increase"
        assert comp.absolute_change == 20
        assert comp.percent_change == 20.0

    def test_decrease(self):
        m = _import_baseline_storage()
        comp = m["RowCountComparison"](
            previous_count=100,
            current_count=80,
            absolute_change=-20,
            percent_change=-20.0,
            direction="decrease",
        )
        assert comp.direction == "decrease"
        assert comp.absolute_change == -20

    def test_unchanged(self):
        m = _import_baseline_storage()
        comp = m["RowCountComparison"](
            previous_count=100,
            current_count=100,
            absolute_change=0,
            percent_change=0.0,
            direction="unchanged",
        )
        assert comp.direction == "unchanged"
        assert comp.absolute_change == 0


class TestDistributionComparison:
    """Test DistributionComparison Pydantic model."""

    def test_create(self):
        m = _import_baseline_storage()
        comp = m["DistributionComparison"](
            column_name="status",
            js_divergence=0.15,
            previous_distinct=3,
            current_distinct=4,
            new_values=["D"],
            removed_values=[],
        )
        assert comp.column_name == "status"
        assert comp.js_divergence == 0.15
        assert comp.new_values == ["D"]
        assert comp.removed_values == []

    def test_defaults(self):
        m = _import_baseline_storage()
        comp = m["DistributionComparison"](
            column_name="col",
            js_divergence=0.0,
            previous_distinct=5,
            current_distinct=5,
        )
        assert comp.new_values == []
        assert comp.removed_values == []


class TestRecordComparison:
    """Test RecordComparison Pydantic model."""

    def test_create(self):
        m = _import_baseline_storage()
        comp = m["RecordComparison"](
            added_count=10,
            removed_count=5,
            modified_count=3,
            unchanged_count=82,
            added_percent=10.0,
            removed_percent=5.0,
            modified_percent=3.0,
        )
        assert comp.added_count == 10
        assert comp.removed_count == 5
        assert comp.modified_count == 3
        assert comp.unchanged_count == 82


# --- BaselineWriter Tests ---


class TestBaselineWriter:
    """Test BaselineWriter initialization and helper methods."""

    def test_init_without_spark(self):
        m = _import_baseline_storage()
        backend = MagicMock()
        writer = m["BaselineWriter"](backend=backend)
        assert writer.backend is backend
        assert writer.table_ref == "run_baselines"
        assert writer.stage == "validation"
        assert writer.spark is None

    def test_init_with_custom_params(self):
        m = _import_baseline_storage()
        backend = MagicMock()
        writer = m["BaselineWriter"](
            backend=backend,
            table_ref="custom_baselines",
            stage="gold",
        )
        assert writer.table_ref == "custom_baselines"
        assert writer.stage == "gold"

    def test_write_baseline_without_spark_raises(self):
        m = _import_baseline_storage()
        backend = MagicMock()
        writer = m["BaselineWriter"](backend=backend, spark=None)
        baseline = m["RunBaseline"](
            run_id="r1",
            run_timestamp=datetime(2025, 1, 1),
            pipeline_name="p1",
            table_name="t1",
            row_count=100,
        )
        with pytest.raises(ValueError, match="SparkSession required"):
            writer.write_baseline(baseline)

    def test_read_latest_baseline_without_spark_raises(self):
        m = _import_baseline_storage()
        backend = MagicMock()
        writer = m["BaselineWriter"](backend=backend, spark=None)
        with pytest.raises(ValueError, match="SparkSession required"):
            writer.read_latest_baseline("table", "pipeline")

    def test_baseline_to_row_minimal(self):
        m = _import_baseline_storage()
        backend = MagicMock()
        writer = m["BaselineWriter"](backend=backend)
        baseline = m["RunBaseline"](
            run_id="r1",
            run_timestamp=datetime(2025, 3, 15, 10, 30, 0),
            pipeline_name="pipeline",
            table_name="table",
            row_count=500,
        )
        row = writer._baseline_to_row(baseline)
        assert row["run_id"] == "r1"
        assert row["run_date"] == "2025-03-15"
        assert row["pipeline_name"] == "pipeline"
        assert row["table_name"] == "table"
        assert row["row_count"] == 500
        assert row["column_distributions"] is None
        assert row["distinct_counts"] is None
        assert row["null_counts"] is None
        assert row["record_checksums"] is None
        assert row["primary_key_columns"] is None
        assert row["numeric_stats"] is None

    def test_baseline_to_row_with_distributions(self):
        m = _import_baseline_storage()
        backend = MagicMock()
        writer = m["BaselineWriter"](backend=backend)
        dist = m["ColumnDistribution"](
            column_name="status",
            value_counts={"A": 10, "B": 20},
            distinct_count=2,
            null_count=1,
            total_count=31,
        )
        baseline = m["RunBaseline"](
            run_id="r2",
            run_timestamp=datetime(2025, 3, 15, 10, 30, 0),
            pipeline_name="p",
            table_name="t",
            row_count=31,
            column_distributions={"status": dist},
        )
        row = writer._baseline_to_row(baseline)
        # Verify JSON serialization
        distributions = json.loads(row["column_distributions"])
        assert distributions == {"status": {"A": 10, "B": 20}}
        distinct = json.loads(row["distinct_counts"])
        assert distinct == {"status": 2}
        nulls = json.loads(row["null_counts"])
        assert nulls == {"status": 1}

    def test_baseline_to_row_with_numeric_stats(self):
        m = _import_baseline_storage()
        backend = MagicMock()
        writer = m["BaselineWriter"](backend=backend)
        stats = m["NumericStats"](
            column_name="amount",
            min_value=1.0,
            max_value=100.0,
            mean_value=50.0,
            stddev_value=10.0,
        )
        baseline = m["RunBaseline"](
            run_id="r3",
            run_timestamp=datetime(2025, 3, 15, 10, 30, 0),
            pipeline_name="p",
            table_name="t",
            row_count=100,
            numeric_stats={"amount": stats},
        )
        row = writer._baseline_to_row(baseline)
        numeric = json.loads(row["numeric_stats"])
        assert numeric["amount"]["min"] == 1.0
        assert numeric["amount"]["max"] == 100.0
        assert numeric["amount"]["mean"] == 50.0
        assert numeric["amount"]["stddev"] == 10.0

    def test_baseline_to_row_with_checksums(self):
        m = _import_baseline_storage()
        backend = MagicMock()
        writer = m["BaselineWriter"](backend=backend)
        baseline = m["RunBaseline"](
            run_id="r4",
            run_timestamp=datetime(2025, 3, 15, 10, 30, 0),
            pipeline_name="p",
            table_name="t",
            row_count=100,
            record_checksums={"pk1": "hash1"},
            primary_key_columns=["id", "name"],
        )
        row = writer._baseline_to_row(baseline)
        checksums = json.loads(row["record_checksums"])
        assert checksums == {"pk1": "hash1"}
        pk_cols = json.loads(row["primary_key_columns"])
        assert pk_cols == ["id", "name"]


# --- QualityResultsWriter Tests ---


class TestQualityResultsWriter:
    """Test QualityResultsWriter initialization and error handling."""

    def test_init_without_spark(self):
        m = _import_storage()
        backend = MagicMock()
        writer = m["QualityResultsWriter"](backend=backend)
        assert writer.backend is backend
        assert writer.table_ref == "quality_check_results"
        assert writer.stage == "validation"
        assert writer.spark is None

    def test_init_with_custom_params(self):
        m = _import_storage()
        backend = MagicMock()
        writer = m["QualityResultsWriter"](
            backend=backend,
            table_ref="custom_results",
            stage="silver",
        )
        assert writer.table_ref == "custom_results"
        assert writer.stage == "silver"

    def test_write_without_spark_raises(self):
        m = _import_storage()
        backend = MagicMock()
        writer = m["QualityResultsWriter"](backend=backend, spark=None)
        mock_run = MagicMock()
        with pytest.raises(ValueError, match="SparkSession required"):
            writer.write_quality_check_run(mock_run)

    def test_read_history_without_spark_raises(self):
        m = _import_storage()
        backend = MagicMock()
        writer = m["QualityResultsWriter"](backend=backend, spark=None)
        with pytest.raises(ValueError, match="SparkSession required"):
            writer.read_quality_check_history("table")

    def test_get_last_validation_timestamp_without_spark_returns_none(self):
        m = _import_storage()
        backend = MagicMock()
        writer = m["QualityResultsWriter"](backend=backend, spark=None)
        result = writer.get_last_validation_timestamp("pipeline", "table")
        assert result is None


# --- Quality __init__ Tests ---


class TestQualityPackageInit:
    """Test that quality package exports are available."""

    def test_baseline_models_importable(self):
        m = _import_baseline_storage()
        # All models should be importable
        assert m["ColumnDistribution"] is not None
        assert m["NumericStats"] is not None
        assert m["RunBaseline"] is not None
        assert m["RowCountComparison"] is not None
        assert m["DistributionComparison"] is not None
        assert m["RecordComparison"] is not None
        assert m["BaselineWriter"] is not None

    def test_storage_importable(self):
        m = _import_storage()
        assert m["QualityResultsWriter"] is not None


# --- BaselineService Jensen-Shannon Divergence Tests ---


class TestJensenShannonDivergence:
    """Test the _jensen_shannon_divergence helper function.

    This is a pure Python function that doesn't need PySpark.
    """

    def _import_jsd(self):
        """Import the JSD function, mocking PySpark if needed."""
        if not HAS_PYSPARK:
            mock_pyspark = MagicMock()
            mock_sql = MagicMock()
            mock_types = MagicMock()
            mock_types.LongType = MagicMock
            mock_types.StringType = MagicMock
            mock_types.StructField = MagicMock
            mock_types.StructType = MagicMock
            mock_types.TimestampType = MagicMock

            modules = {
                "pyspark": mock_pyspark,
                "pyspark.sql": mock_sql,
                "pyspark.sql.types": mock_types,
                "pyspark.sql.functions": MagicMock(),
            }
            for mod_name, mod in modules.items():
                if mod_name not in sys.modules:
                    sys.modules[mod_name] = mod

        from tablespec.quality.baseline_service import _jensen_shannon_divergence

        return _jensen_shannon_divergence

    def test_identical_distributions(self):
        jsd = self._import_jsd()
        p = {"a": 0.5, "b": 0.5}
        q = {"a": 0.5, "b": 0.5}
        result = jsd(p, q)
        assert result == pytest.approx(0.0, abs=1e-6)

    def test_completely_different_distributions(self):
        jsd = self._import_jsd()
        p = {"a": 1.0}
        q = {"b": 1.0}
        result = jsd(p, q)
        # Should be close to 1.0 (maximum divergence)
        assert result > 0.9

    def test_empty_distributions(self):
        jsd = self._import_jsd()
        result = jsd({}, {})
        assert result == 0.0

    def test_partial_overlap(self):
        jsd = self._import_jsd()
        p = {"a": 0.7, "b": 0.3}
        q = {"a": 0.3, "b": 0.7}
        result = jsd(p, q)
        assert 0.0 < result < 1.0

    def test_one_sided_missing_values(self):
        jsd = self._import_jsd()
        p = {"a": 0.5, "b": 0.5}
        q = {"a": 0.5, "b": 0.25, "c": 0.25}
        result = jsd(p, q)
        assert 0.0 < result < 1.0
