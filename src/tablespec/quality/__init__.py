# SPDX-License-Identifier: MIT OR Apache-2.0
"""Quality check execution and management for post-ingestion data quality assessment."""

from tablespec.quality.baseline_service import BaselineService
from tablespec.quality.baseline_storage import (
    BaselineWriter,
    ColumnDistribution,
    DistributionComparison,
    NumericStats,
    RecordComparison,
    RowCountComparison,
    RunBaseline,
)
from tablespec.quality.storage import QUALITY_CHECK_RESULT_SCHEMA, QualityResultsWriter

__all__ = [
    "QUALITY_CHECK_RESULT_SCHEMA",
    "BaselineService",
    "BaselineWriter",
    "ColumnDistribution",
    "DistributionComparison",
    "NumericStats",
    "QualityResultsWriter",
    "RecordComparison",
    "RowCountComparison",
    "RunBaseline",
]

try:
    from tablespec.quality.executor import QualityCheckExecutor

    __all__ += ["QualityCheckExecutor"]
except ImportError:
    pass
