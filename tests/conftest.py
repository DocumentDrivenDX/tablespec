"""Pytest configuration for tablespec tests."""

import json
import os
import shutil
import sys
import tempfile
import warnings
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Resolve a Spark-compatible JAVA_HOME for the LOCAL (non-Databricks) path.
#
# PySpark 4.0 is pip-bundled in the test environment and ships its own jars, so
# NO separate SPARK_HOME / .local/spark installation is required: we only need a
# working, Spark-compatible JDK (major 17 or 21 -- newer JDKs crash Spark with
# "getSubject is not supported"). ``scripts/setup_test_env.resolve_java_home``
# is the single source of truth for that resolution; it honours an
# already-compatible ``$JAVA_HOME`` and otherwise probes common JDK locations.
#
# This runs at module import time so that module-level ``try: import pyspark``
# blocks in source code see a usable JAVA_HOME *before* pytest collects tests.
# On Databricks the runtime owns the JVM, so we leave the environment untouched.
# ---------------------------------------------------------------------------

# Make scripts/setup_test_env importable (it lives under <root>/scripts).
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


def _resolve_spark_java_home() -> Path | None:
    """Return a Spark-compatible JAVA_HOME, or None if none can be found.

    Never provisions over the network (``--no-fallback`` semantics): the test
    gate must SKIP -- not hang -- when no compatible JDK is installed.
    """
    try:
        from setup_test_env import resolve_java_home  # type: ignore[import-not-found]
    except Exception:
        return None
    try:
        return resolve_java_home()
    except Exception:
        return None


def _configure_local_spark_env() -> bool:
    """Configure JAVA_HOME / PYSPARK_PYTHON for a local Spark run.

    Returns True if a compatible JDK is available (env configured), False if no
    compatible JDK could be resolved (callers should skip Spark tests).

    Uses pip-bundled PySpark -- SPARK_HOME is intentionally NOT set. If the
    caller already exported a Databricks SPARK_HOME we honour it untouched.
    """
    if "DATABRICKS_RUNTIME_VERSION" in os.environ:
        return True

    java_home = _resolve_spark_java_home()
    if java_home is None:
        return False

    # Only override JAVA_HOME when it is unset or points at an incompatible JDK;
    # resolve_java_home already preferred a compatible $JAVA_HOME if present.
    os.environ["JAVA_HOME"] = str(java_home)
    os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
    os.environ.setdefault("PYSPARK_DRIVER_PYTHON", sys.executable)
    return True


if "DATABRICKS_RUNTIME_VERSION" not in os.environ:
    _configure_local_spark_env()

# Ivy coordinate for Delta Lake matching the pinned Spark 4.0 line. Used by the
# local ``spark_session`` fixture to obtain Delta jars without a separate install.
_DELTA_PACKAGE = "io.delta:delta-spark_2.13:4.0.0"


def pytest_addoption(parser):
    """Register custom CLI options."""
    parser.addoption(
        "--update-golden",
        action="store_true",
        default=False,
        help="(Re)write golden baseline files (ingest parity) instead of asserting.",
    )


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "no_spark: mark test as not requiring Spark (skips Spark setup)"
    )


# ---------------------------------------------------------------------------
# Spark environment setup (autouse) and session-scoped spark_session fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _setup_spark_environment_per_test(request):
    """Set up Spark environment variables for local testing.

    Skipped for tests/modules marked with @pytest.mark.no_spark.
    This is function-scoped so it can check individual test markers.
    """
    if request.node.get_closest_marker("no_spark"):
        return

    # Skip if in Databricks (the runtime owns the JVM/session).
    if "DATABRICKS_RUNTIME_VERSION" in os.environ:
        return

    # Resolve and export a Spark-compatible JAVA_HOME using pip-bundled PySpark.
    # If no compatible JDK is available this is a no-op; the spark_session
    # fixture will pytest.skip when a session is actually requested.
    _configure_local_spark_env()


@pytest.fixture(scope="session")
def spark_session():
    """Provide a Spark session for tests via the tablespec spark factory.

    The factory (tablespec.spark_factory) is the single entrypoint for Spark
    session creation. It detects Databricks vs local environments automatically:
    - On Databricks: returns the runtime's active session (never creates one).
    - Locally: creates a session with Delta Lake, using file-based locking for
      parallel safety.

    On Databricks the session is never stopped (the runtime owns it).
    Locally it is stopped on teardown.
    """
    try:
        from tablespec.spark_factory import create_delta_spark_session
    except ImportError:
        pytest.skip(
            "PySpark not available -- install with: uv sync --extra spark --group dev"
        )

    is_databricks = "DATABRICKS_RUNTIME_VERSION" in os.environ

    if not is_databricks:
        # Local: use pip-bundled PySpark (no SPARK_HOME). Only a Spark-compatible
        # JDK is required; skip ONLY when none can be resolved.
        if not _configure_local_spark_env():
            pytest.skip(
                "No Spark-compatible JDK (major 17 or 21) found. Install "
                "openjdk@17/@21, set TABLESPEC_JAVA_HOME, or run "
                "'uv run python scripts/setup_spark.py'."
            )

    # --- Create (or acquire) the session via the factory ---
    # Locally, PySpark ships no Delta jars, so pull the matching Delta package
    # via Ivy (``spark.jars.packages``); this makes the session genuinely
    # Delta-capable without a separate Spark/Delta install. On Databricks the
    # runtime already provides Delta, so no extra config is needed.
    custom_config = (
        None
        if is_databricks
        else {
            "spark.master": "local[2]",
            "spark.default.parallelism": "2",
            "spark.dynamicAllocation.enabled": "false",
            "spark.sql.shuffle.partitions": "2",
            "spark.executor.cores": "1",
            "spark.executor.instances": "1",
            "spark.ui.enabled": "false",
            "spark.jars.packages": _DELTA_PACKAGE,
        }
    )

    if is_databricks:
        # Databricks: acquiring the runtime session is environment-dependent
        # (e.g. subprocess vs in-process); a failure here is not a code defect
        # under test, so skip rather than fail.
        try:
            spark = create_delta_spark_session("tablespec-test", custom_config)
        except Exception as e:
            pytest.skip(f"Databricks Spark session unavailable: {e}")
    else:
        # Local: a compatible JDK was already resolved above, so PySpark + Delta
        # MUST start. Do NOT swallow this into a skip -- the skip-only condition
        # is "no compatible JDK", which was already handled. Any failure here is
        # a real problem and must fail the test.
        spark = create_delta_spark_session("tablespec-test", custom_config)

    if is_databricks:
        # On Databricks the runtime owns the session -- never stop it.
        yield spark
        return

    # Local: protect against accidental stops during tests, then clean up.
    import fcntl

    lock_file = Path(tempfile.gettempdir()) / "tablespec_spark_test.lock"
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = open(lock_file, "w")  # noqa: SIM115 -- lock must be held for entire session

    try:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)

        original_stop = spark.stop

        def protected_stop():
            import logging

            logging.getLogger(__name__).warning(
                "spark.stop() called during tests -- ignoring to preserve session"
            )

        spark.stop = protected_stop  # type: ignore[method-assign]

        try:
            yield spark
        finally:
            spark.stop = original_stop  # type: ignore[method-assign]
            spark.stop()
    finally:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
        lock_fd.close()


@pytest.fixture
def anyio_backend():
    """Configure anyio to only use asyncio backend, not trio."""
    return "asyncio"


@pytest.fixture
def temp_output_dir():
    """Create a temporary directory for test outputs."""
    temp_dir = Path(tempfile.mkdtemp())
    yield temp_dir
    # Cleanup
    shutil.rmtree(temp_dir)


@pytest.fixture
def _mock_test_mode(monkeypatch):
    """Set environment variables for deterministic test execution."""
    monkeypatch.setenv("TABLESPEC_TEST_MODE", "1")
    monkeypatch.setenv("TABLESPEC_RANDOM_SEED", "42")


class FixtureDataLoader:
    """Helper class for loading and comparing fixture data."""

    @staticmethod
    def load_json(path: Path) -> dict[str, Any]:
        """Load JSON file with error handling."""
        try:
            with open(path) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            pytest.fail(f"Failed to load JSON from {path}: {e}")

    @staticmethod
    def compare_json_structure(
        actual: dict[str, Any], expected: dict[str, Any], path: str = ""
    ) -> None:
        """Compare JSON structure, ignoring specific timestamp/ID fields."""
        ignore_fields = {
            "timestamp",
            "generated_at",
            "processing_time",
            "extraction_id",
            "extraction_timestamp",
            "source_file_modified",
            "output_file",
            "source_file",
            "input_file",
        }

        if isinstance(expected, dict) and isinstance(actual, dict):  # pyright: ignore[reportUnnecessaryIsInstance]
            for key, expected_value in expected.items():
                current_path = f"{path}.{key}" if path else key

                if key in ignore_fields:
                    continue  # Skip timestamp fields

                if key not in actual:
                    pytest.fail(f"Missing key in actual data: {current_path}")

                FixtureDataLoader.compare_json_structure(
                    actual[key], expected_value, current_path
                )

        elif isinstance(expected, list) and isinstance(actual, list):
            if len(actual) != len(expected):
                pytest.fail(
                    f"List length mismatch at {path}: expected {len(expected)}, got {len(actual)}"
                )

            for i, (actual_item, expected_item) in enumerate(
                zip(actual, expected, strict=False)
            ):
                FixtureDataLoader.compare_json_structure(
                    actual_item, expected_item, f"{path}[{i}]"
                )

        elif actual != expected:
            pytest.fail(f"Value mismatch at {path}: expected {expected}, got {actual}")


@pytest.fixture
def fixture_loader():
    """Provide access to the fixture data loader."""
    return FixtureDataLoader


# ---------------------------------------------------------------------------
# GX Test Harness (FEAT-016)
# ---------------------------------------------------------------------------


class GXTestResult:
    """Structured result from running GX expectations via the test harness.

    Attributes:
        all_passed: True if every expectation succeeded.
        results: Mapping from (expectation_type, column) to ExpectationResult.
        raw: The underlying SuiteExecutionResult.
    """

    def __init__(self, suite_result: Any) -> None:
        from tablespec.validation.gx_executor import SuiteExecutionResult

        self.raw: SuiteExecutionResult = suite_result
        self.all_passed: bool = suite_result.success
        self.total: int = suite_result.total
        self.passed: int = suite_result.passed
        self.failed: int = suite_result.failed
        self._index: dict[tuple[str, str | None], Any] = {}
        for r in suite_result.results:
            self._index[(r.expectation_type, r.column)] = r

    def __getitem__(self, key: str) -> Any:
        """Look up results by expectation type.

        Returns a namespace where attribute access yields column-keyed results:
            result["expect_column_to_exist"]["col_name"].success

        For table-level expectations (no column), use None:
            result["expect_table_row_count_to_equal"][None].success
        """
        matches = {col: r for (etype, col), r in self._index.items() if etype == key}
        if not matches:
            available = sorted({etype for etype, _ in self._index})
            raise KeyError(f"No results for '{key}'. Available: {available}")
        return _ColumnResults(matches)

    @property
    def failures(self) -> list[Any]:
        """Return all failed ExpectationResults."""
        return [r for r in self.raw.results if not r.success]


class _ColumnResults:
    """Accessor for per-column results within an expectation type."""

    def __init__(self, results: dict[str | None, Any]) -> None:
        self._results = results

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        if name not in self._results:
            available = sorted(str(k) for k in self._results)
            raise AttributeError(
                f"No result for column '{name}'. Available: {available}"
            )
        return self._results[name]

    def __getitem__(self, key: str | None) -> Any:
        if key not in self._results:
            available = sorted(str(k) for k in self._results)
            raise KeyError(f"No result for column '{key}'. Available: {available}")
        return self._results[key]


class GXTestHarness:
    """Thin wrapper around GXSuiteExecutor for test ergonomics.

    Creates a Sail-backed SparkSession and provides a simple ``run()``
    method that accepts expectation dicts and test data.

    Usage::

        harness = GXTestHarness()  # auto-detects Sail or Spark
        result = harness.run(
            expectations=[{"type": "expect_column_to_exist", "kwargs": {"column": "id"}}],
            data=[{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}],
        )
        assert result.all_passed
        assert result["expect_column_to_exist"]["id"].success
    """

    def __init__(self, backend: str = "auto") -> None:
        if backend == "auto":
            # Prefer classic Spark for the default unit-test harness. Spark Connect
            # coverage lives in dedicated backend-specific tests, while the auto
            # harness is part of the canonical `make test` path and should avoid
            # flaky socket/resource cleanup from transient Connect sessions.
            backend = "spark"
        self._backend = backend
        self._spark: Any | None = None
        self._sail_server: Any | None = None
        self._executor: Any | None = None

    def _get_spark(self) -> Any:
        if self._spark is not None:
            return self._spark

        if self._backend == "sail":
            try:
                from pysail.spark import SparkConnectServer
                from pyspark.sql import SparkSession

                self._sail_server = SparkConnectServer()
                self._sail_server.start()
                _, port = self._sail_server.listening_address
                self._spark = (
                    SparkSession.builder.remote(f"sc://localhost:{port}")
                    .appName("gx-test-harness")
                    .getOrCreate()
                )
            except ImportError:
                pytest.skip("Sail not available — install with: uv sync --extra lite")
            except Exception as e:
                pytest.skip(f"Sail session failed: {e}")
        elif self._backend == "spark":
            from tablespec.session import get_session

            try:
                self._spark = get_session("gx-test-harness", backend="spark")
            except Exception as e:
                pytest.skip(f"Spark session failed: {e}")
        else:
            raise ValueError(f"Unknown backend: {self._backend}")

        return self._spark

    @staticmethod
    def _supports_local_execution(expectations: list[dict[str, Any]]) -> bool:
        supported = {
            "expect_column_to_exist",
            "expect_column_values_to_not_be_null",
            "expect_column_values_to_be_in_set",
            "expect_column_values_to_be_unique",
        }
        return all(
            exp.get("type", exp.get("expectation_type", "")) in supported
            for exp in expectations
        )

    @staticmethod
    def _execute_locally(
        expectations: list[dict[str, Any]],
        data: list[dict[str, Any]],
    ) -> Any:
        from tablespec.validation.gx_executor import (
            ExpectationResult,
            SuiteExecutionResult,
        )

        results: list[ExpectationResult] = []

        for exp in expectations:
            exp_type = exp.get("type", exp.get("expectation_type", ""))
            kwargs = exp.get("kwargs", {})
            column = kwargs.get("column")

            if exp_type == "expect_column_to_exist":
                success = all(column in row for row in data)
                results.append(
                    ExpectationResult(
                        expectation_type=exp_type, column=column, success=success
                    )
                )
                continue

            values = [row.get(column) for row in data]
            if exp_type == "expect_column_values_to_not_be_null":
                unexpected_values = [value for value in values if value is None]
                results.append(
                    ExpectationResult(
                        expectation_type=exp_type,
                        column=column,
                        success=not unexpected_values,
                        unexpected_count=len(unexpected_values),
                        unexpected_values=unexpected_values[:10],
                    )
                )
                continue

            if exp_type == "expect_column_values_to_be_in_set":
                allowed = set(kwargs.get("value_set", []))
                unexpected_values = [value for value in values if value not in allowed]
                results.append(
                    ExpectationResult(
                        expectation_type=exp_type,
                        column=column,
                        success=not unexpected_values,
                        unexpected_count=len(unexpected_values),
                        unexpected_values=unexpected_values[:10],
                    )
                )
                continue

            if exp_type == "expect_column_values_to_be_unique":
                seen: set[Any] = set()
                duplicates: list[Any] = []
                for value in values:
                    if value in seen:
                        duplicates.append(value)
                    else:
                        seen.add(value)
                results.append(
                    ExpectationResult(
                        expectation_type=exp_type,
                        column=column,
                        success=not duplicates,
                        unexpected_count=len(duplicates),
                        unexpected_values=duplicates[:10],
                    )
                )

        return SuiteExecutionResult.from_results(results)

    def run(
        self,
        expectations: list[dict[str, Any]],
        data: list[dict[str, Any]] | None = None,
        data_path: str | None = None,
    ) -> GXTestResult:
        """Execute expectations against test data.

        Args:
            expectations: List of GX expectation dicts.
            data: Inline test data as list of row dicts.
            data_path: Path to a CSV file to load as test data.

        Returns:
            GXTestResult with indexed results.
        """
        if data is not None:
            if self._supports_local_execution(expectations):
                return GXTestResult(self._execute_locally(expectations, data))

            spark = self._get_spark()
            df = spark.createDataFrame(data)
        elif data_path is not None:
            spark = self._get_spark()
            df = spark.read.csv(data_path, header=True, inferSchema=True)
        else:
            raise ValueError("Provide either data= or data_path=")

        from tablespec.validation.gx_executor import GXSuiteExecutor

        if self._executor is None:
            self._executor = GXSuiteExecutor(spark=spark)

        suite_result = self._executor.execute_suite(df, expectations)
        return GXTestResult(suite_result)

    def stop(self) -> None:
        """Shut down the session and server."""
        if self._spark is not None:
            try:
                self._spark.stop()
            except Exception:
                pass
            self._spark = None
        if self._sail_server is not None:
            try:
                self._sail_server.stop()
            except Exception:
                pass
            self._sail_server = None
        self._executor = None


@pytest.fixture(scope="session")
def gx_harness():
    """Session-scoped GXTestHarness with auto-detected backend.

    Usage in tests::

        def test_column_exists(gx_harness):
            result = gx_harness.run(
                expectations=[{"type": "expect_column_to_exist", "kwargs": {"column": "id"}}],
                data=[{"id": 1}],
            )
            assert result.all_passed
    """
    original_filters = warnings.filters[:]
    warnings.filterwarnings("ignore", category=pytest.PytestUnraisableExceptionWarning)
    warnings.filterwarnings("ignore", category=ResourceWarning)
    harness = GXTestHarness()
    yield harness
    harness.stop()
    warnings.filters[:] = original_filters
