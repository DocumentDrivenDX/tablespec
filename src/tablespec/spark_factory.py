"""Generic Spark session factory for Delta Lake support.

This module provides a centralized way to create Spark sessions with Delta Lake
support that works across different environments (local, Databricks, etc.).

This is a generic factory suitable for library use. For project-specific
configuration (e.g., pulseflow local Spark paths), wrap this factory.
"""

from __future__ import annotations

# ruff: noqa: E402
import logging
import os
from pathlib import Path
import sys
from typing import TYPE_CHECKING
import warnings

# Disable tqdm progress bars and suppress warnings BEFORE importing PySpark
os.environ["TQDM_DISABLE"] = "1"
warnings.filterwarnings("ignore", category=DeprecationWarning)

if TYPE_CHECKING:
    from pyspark.sql import SparkSession

logger = logging.getLogger(__name__)


def _import_spark_session() -> type:
    """Import and return the SparkSession class, raising ImportError if unavailable."""
    try:
        from pyspark.sql import SparkSession as _SparkSession

        return _SparkSession
    except ImportError:
        msg = (
            "PySpark is required for SparkSessionFactory. "
            "Install it with: pip install tablespec[spark]"
        )
        raise ImportError(msg) from None


class ThreadMonitorFilter(logging.Filter):
    """Filter out py4j ThreadMonitor debug messages.

    ThreadMonitor is a py4j Java class that monitors gateway connections and logs
    thread stack frames at DEBUG level. These messages appear as noise in notebook
    output and look like errors even though they're just debug information.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Return False to block ThreadMonitor messages, True to allow others."""
        # Block any log message containing ThreadMonitor
        try:
            message = record.getMessage()
            if "ThreadMonitor" in message:
                return False
        except Exception:
            pass
        # Block if logger name contains ThreadMonitor
        return "ThreadMonitor" not in record.name


class SparkSessionFactory:
    """Factory for creating Spark sessions with consistent Delta Lake configuration."""

    @staticmethod
    def is_databricks_environment() -> bool:
        """Detect if running in Databricks environment.

        Returns
        -------
            True if running in Databricks, False otherwise

        """
        return "DATABRICKS_RUNTIME_VERSION" in os.environ or (
            "SPARK_HOME" in os.environ
            and "databricks" in os.environ.get("SPARK_HOME", "").lower()
        )

    @staticmethod
    def _configure_logging() -> None:
        """Configure logging to suppress py4j debug output."""
        # Disable py4j debug logging completely
        py4j_loggers = [
            "py4j",
            "py4j.java_gateway",
            "py4j.clientserver",
            "py4j.reflection",
            "py4j.protocol",
            "py4j.commands",
            "py4j.java_collections",
        ]
        for logger_name in py4j_loggers:
            logger = logging.getLogger(logger_name)
            logger.setLevel(logging.CRITICAL)
            logger.disabled = True
            logger.propagate = False

        # Add ThreadMonitor filter to root logger handlers
        thread_monitor_filter = ThreadMonitorFilter()
        root_logger = logging.getLogger()
        for handler in root_logger.handlers:
            handler.addFilter(thread_monitor_filter)

    @staticmethod
    def is_delta_available() -> bool:
        """Check if Delta Lake libraries are already available.

        Returns
        -------
            True if Delta Lake is available, False otherwise

        """
        try:
            import delta  # noqa: F401  # type: ignore[reportUnusedImport]

            return True
        except ImportError:
            return False

    @staticmethod
    def _raise_delta_config_error() -> None:
        """Raise a RuntimeError for missing Delta Lake configuration."""
        msg = "Delta Lake extensions not found in Spark configuration"
        raise RuntimeError(msg)

    @classmethod
    def create_session(
        cls: type[SparkSessionFactory],
        app_name: str,
        custom_config: dict[str, str] | None = None,
        local_mode: bool = True,  # noqa: ARG003
    ) -> SparkSession:
        """Create a Spark session with Delta Lake support required.

        Args:
        ----
            app_name: Name of the Spark application
            custom_config: Optional custom Spark configuration
            local_mode: Whether to use local mode (ignored in Databricks)

        Returns:
        -------
            Configured SparkSession with Delta Lake support

        Notes:
        -----
            For local Spark installations, set SPARK_HOME and JAVA_HOME
            environment variables before calling this function.

        """
        SparkSession = _import_spark_session()  # noqa: N806

        # Configure logging BEFORE creating Spark session to suppress py4j debug output
        cls._configure_logging()

        # Get logger reference after configuring
        session_logger = logging.getLogger(__name__)
        session_logger.info(f"Creating Spark session: {app_name}")

        # Check environment
        is_databricks = SparkSessionFactory.is_databricks_environment()
        delta_available = SparkSessionFactory.is_delta_available()

        session_logger.debug(
            f"Environment: Databricks={is_databricks}, Delta available={delta_available}"
        )

        # Start with base configuration
        config = custom_config.copy() if custom_config else {}

        # Set app name
        config["spark.app.name"] = app_name

        # Set up local Spark installation if not on Databricks
        if not is_databricks:
            # Read SPARK_HOME and JAVA_HOME from environment
            spark_home_str = os.environ.get("SPARK_HOME")
            java_home_str = os.environ.get("JAVA_HOME")

            if spark_home_str:
                spark_home = Path(spark_home_str)
                if not spark_home.exists():
                    msg = f"SPARK_HOME path does not exist: {spark_home}"
                    raise RuntimeError(msg)
                session_logger.info(
                    f"Using Spark installation from SPARK_HOME: {spark_home}"
                )

            if java_home_str:
                java_home = Path(java_home_str)
                if not java_home.exists():
                    msg = f"JAVA_HOME path does not exist: {java_home}"
                    raise RuntimeError(msg)
                session_logger.info(f"Using Java from JAVA_HOME: {java_home}")

            # Set PYSPARK_PYTHON to ensure correct Python interpreter
            if "PYSPARK_PYTHON" not in os.environ:
                os.environ["PYSPARK_PYTHON"] = sys.executable
            if "PYSPARK_DRIVER_PYTHON" not in os.environ:
                os.environ["PYSPARK_DRIVER_PYTHON"] = sys.executable

        if is_databricks:
            # In Databricks, always reuse the runtime's pre-existing session.
            # Never create a new session — the runtime manages the connection.
            session_logger.info(
                "Detected Databricks environment - using runtime session"
            )

            # 1. Try the active session (works when running in-process, e.g. pytest.main())
            try:
                existing_session = SparkSession.getActiveSession()
                if existing_session is not None:
                    session_logger.info("Using active Databricks Spark session")
                    return existing_session
            except Exception:
                pass

            # 2. Try getOrCreate() — on Databricks runtimes this is patched to
            #    return the cluster's session. Also works if SPARK_REMOTE is set.
            try:
                spark_remote = os.environ.get("SPARK_REMOTE")
                builder = SparkSession.builder  # type: ignore[attr-defined]
                if spark_remote:
                    session_logger.info(f"Using SPARK_REMOTE: {spark_remote}")
                    builder = builder.remote(spark_remote)  # type: ignore[attr-defined]
                spark = builder.getOrCreate()  # type: ignore[attr-defined]
                session_logger.info("Databricks Spark session acquired via getOrCreate")
                return spark
            except Exception as e:
                msg = (
                    f"Failed to acquire Databricks Spark session: {e}. "
                    "If running in a subprocess, use pytest.main() in-process "
                    "or set the SPARK_REMOTE environment variable."
                )
                raise RuntimeError(msg) from e

        else:
            # Local/standalone environment - need full configuration
            session_logger.info("Configuring for local/standalone environment")

            # Check for existing active session first (same pattern as Databricks)
            try:
                existing_session = SparkSession.getActiveSession()
                if existing_session is not None:
                    session_logger.info("Reusing existing active Spark session")
                    return existing_session
            except Exception:
                pass

            # Base local configuration
            local_config = {
                "spark.master": "local[*]",
                "spark.executor.memory": "4g",
                "spark.driver.memory": "4g",  # Increased from 2g to prevent memory pressure during complex joins
                # Increase JVM stack size for deep query plan analysis (default 1MB)
                "spark.driver.extraJavaOptions": "-Xss4m",
                "spark.executor.cores": "2",
                "spark.sql.adaptive.enabled": "true",
                "spark.sql.adaptive.coalescePartitions.enabled": "true",
                "spark.sql.adaptive.coalescePartitions.minPartitionSize": "1MB",
                "spark.serializer": "org.apache.spark.serializer.KryoSerializer",
                "spark.sql.execution.arrow.pyspark.enabled": "true",
                "spark.sql.execution.pyspark.udf.simplifiedTraceback.enabled": "false",
                # Reduce excessive logging
                "spark.ui.showConsoleProgress": "false",
                "spark.sql.adaptive.advisory.enabled": "false",
                "spark.sql.execution.pyspark.python.profile.enabled": "false",
                # Disable py4j client/server debug logging
                "spark.sql.streaming.ui.enabled": "false",
                "spark.ui.enabled": "false",
                "spark.eventLog.enabled": "false",
                # Prevent plan truncation warnings
                "spark.sql.debug.maxToStringFields": "1000",
                # Code generation settings for wide schemas (80+ columns)
                # Increase field limit from default 100 to handle wide tables
                "spark.sql.codegen.maxFields": "300",
                # Increase bytecode size limit from default 8000 to 20000 bytes
                "spark.sql.codegen.hugeMethodLimit": "20000",
                # Split large generated methods to avoid 64KB JVM method size limit
                "spark.sql.codegen.splitConsumeFuncByOperator": "true",
                # Fallback to interpreted mode if codegen exceeds 64KB limit
                "spark.sql.codegen.fallback": "true",
                # Performance optimizations for parallel file loading
                # Increase parallelism for better multi-file throughput
                "spark.default.parallelism": "200",
                "spark.sql.shuffle.partitions": "200",
                # Optimize file reading for many small files
                # Smaller partitions allow Spark to read more files in parallel
                "spark.sql.files.maxPartitionBytes": "67108864",  # 64MB (default 128MB)
                # Enable file coalescing to group small files for better throughput
                "spark.sql.files.openCostInBytes": "4194304",  # 4MB (helps coalesce small files)
                # Increase max concurrent tasks for better parallel file loading
                # Increased from 4 to 16 to utilize all cores on 16-core cluster
                "spark.sql.files.maxConcurrentReads": "16",
            }

            # Delta Lake should be pre-installed (via setup script or cluster config)
            # Add only essential Delta configuration (JARs should already be available)
            delta_config = {
                "spark.sql.extensions": "io.delta.sql.DeltaSparkSessionExtension",
                "spark.sql.catalog.spark_catalog": "org.apache.spark.sql.delta.catalog.DeltaCatalog",
                "spark.databricks.delta.retentionDurationCheck.enabled": "false",
                "spark.databricks.delta.schema.autoMerge.enabled": "true",
                "spark.databricks.delta.optimizeWrite.enabled": "true",
                "spark.databricks.delta.autoCompact.enabled": "true",
            }
            local_config.update(delta_config)

            # Merge configurations (custom overrides local defaults)
            final_config = {**local_config, **config}

            # Create builder with configuration
            builder = SparkSession.builder  # type: ignore[attr-defined]
            for key, value in final_config.items():
                builder = builder.config(key, value)  # type: ignore[attr-defined]

        # Create session - getOrCreate() will reuse existing session if compatible
        try:
            spark = builder.getOrCreate()  # type: ignore[attr-defined]
            spark.sparkContext.setLogLevel("ERROR")

            # Aggressively suppress py4j and Spark DEBUG logging
            # Disable py4j debug logging completely
            py4j_loggers = [
                "py4j",
                "py4j.java_gateway",
                "py4j.clientserver",
                "py4j.reflection",
                "py4j.protocol",
                "py4j.commands",
                "py4j.java_collections",
            ]
            for logger_name in py4j_loggers:
                logger = logging.getLogger(logger_name)
                logger.setLevel(logging.CRITICAL)
                logger.disabled = True
                logger.propagate = False

            # Also disable root py4j handler if it exists and add ThreadMonitor filter
            root_logger = logging.getLogger()
            thread_monitor_filter = ThreadMonitorFilter()
            for handler in root_logger.handlers[:]:
                if hasattr(handler, "name") and "py4j" in str(handler.name).lower():
                    root_logger.removeHandler(handler)
                else:
                    # Add ThreadMonitor filter to remaining handlers
                    handler.addFilter(thread_monitor_filter)

            # Set all Spark-related loggers to ERROR only
            spark_loggers = [
                "org.apache.spark",
                "org.spark_project",
                "org.apache.hadoop",
                "io.delta",
                "org.eclipse.jetty",
            ]
            for logger_name in spark_loggers:
                logging.getLogger(logger_name).setLevel(logging.ERROR)

            # Basic verification - Delta Lake setup verification is handled by setup script
            try:
                # Test basic Spark functionality
                spark.range(1).collect()

                # Verify Delta Lake extensions are configured
                extensions = spark.conf.get("spark.sql.extensions", "") or ""
                if "DeltaSparkSessionExtension" not in extensions:
                    cls._raise_delta_config_error()

                session_logger.info(
                    "Spark session with Delta Lake configuration verified"
                )

            except Exception as spark_e:
                session_logger.exception(
                    f"Spark session verification failed: {spark_e}"
                )
                try:
                    spark.stop()
                except Exception as stop_e:
                    session_logger.warning(
                        f"Error stopping failed Spark session: {stop_e}"
                    )

                msg = f"Spark session initialization failed: {spark_e}"
                raise RuntimeError(msg) from spark_e

            session_logger.info(f"Spark session created successfully: {app_name}")
            return spark

        except Exception as e:
            session_logger.exception(f"Failed to create Spark session: {e}")
            raise


def create_delta_spark_session(
    app_name: str, custom_config: dict[str, str] | None = None
) -> SparkSession:
    """Create a Spark session with Delta Lake support.

    Convenience function for creating Spark sessions with Delta Lake
    configuration.

    Args:
    ----
        app_name: Name of the Spark application
        custom_config: Optional custom Spark configuration

    Returns:
    -------
        Configured SparkSession with Delta Lake support

    Examples:
    --------
        >>> from tablespec import create_delta_spark_session
        >>> spark = create_delta_spark_session("MyDataValidation")

    """
    return SparkSessionFactory.create_session(app_name, custom_config)


__all__ = [
    "SparkSessionFactory",
    "create_delta_spark_session",
]
