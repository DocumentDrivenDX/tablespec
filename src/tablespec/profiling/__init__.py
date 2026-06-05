"""Schema profiling and mapping utilities for tablespec.

This module provides tools for profiling DataFrames and mapping results to UMF format.

Components:
    - ``NativeSparkProfiler``: Profiles DataFrames using native SQL (serverless-compatible).
    - ``ProfileToGxMapper``: Generates GX expectations directly from profiling results.
    - ``SparkToUmfMapper``: Maps Spark DataFrame schema to UMF (requires pyspark).

Type mappings:
    - ``SPARK_TO_UMF_TYPE``: Spark DataType class name → UMF data_type string.
    - ``SQL_TO_UMF_TYPE``: SQL/warehouse type name → UMF data_type string (for dbt, etc.).

Spark-dependent components require installing tablespec[spark]:
    pip install tablespec[spark]
"""

from tablespec.profiling.gx_expectation_builder import ProfileToGxMapper
from tablespec.profiling.types import ColumnProfile, DataFrameProfile

__all__ = [
    "ColumnProfile",
    "DataFrameProfile",
    "ProfileToGxMapper",
]

# SparkToUmfMapper and type mapping dicts are available only if pyspark is installed
try:
    from tablespec.profiling.spark_mapper import (  # noqa: F401
        SPARK_TO_UMF_TYPE,
        SQL_TO_UMF_TYPE,
        SparkToUmfMapper,
    )

    __all__.extend(["SparkToUmfMapper", "SPARK_TO_UMF_TYPE", "SQL_TO_UMF_TYPE"])
except ImportError:
    # pyspark not available - SparkToUmfMapper won't be exported
    pass

# NativeSparkProfiler requires only pyspark (works on Connect/serverless)
try:
    from tablespec.profiling.native_profiler import NativeSparkProfiler  # noqa: F401

    __all__.append("NativeSparkProfiler")
except ImportError:
    # pyspark not available
    pass
