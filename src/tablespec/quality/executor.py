"""Quality check executor for post-ingestion data quality assessment.

This module provides quality check execution using Great Expectations,
focusing on business rules and data fitness rather than structural validation.

Supports run-over-run comparison expectations that compare current data against
previous baselines to detect significant changes (row count, distribution, records).
"""

from __future__ import annotations

from datetime import datetime
import logging
from typing import TYPE_CHECKING, Any
import uuid

try:
    from tablespec.models.quality import (
        QualityCheckResult,
        QualityCheckRun,
        QualityScore,
        QualityThreshold,
    )
except ImportError:
    QualityCheckResult = None  # type: ignore[assignment, misc]
    QualityCheckRun = None  # type: ignore[assignment, misc]
    QualityScore = None  # type: ignore[assignment, misc]
    QualityThreshold = None  # type: ignore[assignment, misc]

try:
    from tablespec.pipeline_discovery import PipelineDiscovery
except ImportError:
    PipelineDiscovery = None  # type: ignore[assignment, misc]

from tablespec.expectation_migration import migrate_to_expectation_suite
from tablespec.umf_loader import UMFLoader

try:
    from tablespec.validation.run_comparison import (
        is_run_comparison_expectation,
    )
except ImportError:

    def is_run_comparison_expectation(expectation_type: str) -> bool:  # type: ignore[misc]
        """Fallback when run_comparison module is not available."""
        return expectation_type in {
            "expect_row_count_change_within_percent",
            "expect_column_distribution_stable",
            "expect_record_changes_within_limits",
        }


if TYPE_CHECKING:
    from pathlib import Path

    from pyspark.sql import DataFrame, SparkSession

    from tablespec.models.umf import QualityCheck
    from tablespec.quality.baseline_storage import RunBaseline

# GX-specific exceptions for targeted error handling
try:
    from great_expectations.exceptions import GreatExpectationsError
except ImportError:
    # Fallback if GX not installed - will be caught at runtime
    GreatExpectationsError = Exception  # type: ignore[misc, assignment]

logger = logging.getLogger(__name__)

# Default quality checks applied to all tables unless overridden
DEFAULT_ROW_COUNT_CHECK: dict[str, Any] = {
    "expectation": {
        "type": "expect_row_count_change_within_percent",
        "kwargs": {
            "direction": "both",
            "max_change_percent": 20.0,
        },
        "meta": {
            "description": "Alert if row count changes by more than 20% compared to previous run",
            "severity": "warning",
        },
    },
    "severity": "warning",
    "blocking": False,
    "description": "Alert if row count changes by more than 20% compared to previous run",
    "tags": ["run_comparison", "default"],
}


class QualityCheckExecutor:
    """Executes quality checks on Bronze.Ingested tables for data fitness assessment.

    Supports run-over-run comparison by optionally accepting a baseline from a
    previous run. When a baseline is provided, run comparison expectations
    (row count, distribution, record changes) will use it for comparison.
    """

    def __init__(
        self,
        spark: SparkSession,
        baseline: RunBaseline | None = None,
    ) -> None:
        """Initialize the executor with a Spark session.

        Args:
            spark: SparkSession for executing quality checks
            baseline: Optional baseline from previous run for comparison checks.
                If provided, run comparison expectations will compare against it.

        """
        self.spark = spark
        self.baseline = baseline
        self.logger = logging.getLogger(self.__class__.__name__)

        # Set up GXSuiteExecutor (batch execution) as primary engine
        try:
            from tablespec.validation.gx_executor import GXSuiteExecutor

            self.executor = GXSuiteExecutor(spark=spark)
            self.gx_available = True

            # Suppress GX internal loggers (noisy INFO messages)
            logging.getLogger("great_expectations").setLevel(logging.WARNING)
            logging.getLogger("great_expectations._docs_decorators").setLevel(
                logging.WARNING
            )
            logging.getLogger("great_expectations.expectations.expectation").setLevel(
                logging.WARNING
            )

            self.logger.info("Great Expectations available via GXSuiteExecutor")
        except ImportError as e:
            self.logger.warning(f"Great Expectations not available: {e}")
            self.gx_available = False
            self.executor = None  # type: ignore[assignment]

    def execute_quality_checks(
        self,
        spark_df: DataFrame,
        umf_path: Path,
        pipeline_name: str | None = None,
        run_id: str | None = None,
        since_timestamp: datetime | None = None,
        full_refresh: bool = False,
    ) -> QualityCheckRun:
        """Execute quality checks on a Bronze.Ingested table.

        Args:
            spark_df: Pre-loaded PySpark DataFrame (Bronze.Ingested)
            umf_path: Path to UMF YAML (contains quality_checks configuration)
            pipeline_name: Optional pipeline name (avoids path-based inference)
            run_id: Optional run identifier for tracking (generated if not provided)
            since_timestamp: Optional cutoff for incremental validation. Only records
                with meta_load_dt > since_timestamp will be validated.
            full_refresh: If True, validate all records regardless of since_timestamp.

        Returns:
            QualityCheckRun with results, scores, and non-blocking determination

        """
        # Generate run_id if not provided
        if run_id is None:
            run_id = str(uuid.uuid4())

        # Load UMF to extract quality checks (typed attribute access)
        loader = UMFLoader()
        umf = loader.load(umf_path)

        table_name = umf.table_name or umf_path.stem.replace(".umf", "")
        pipeline_name = self._resolve_pipeline_name(umf_path, pipeline_name)

        # Apply incremental filter if since_timestamp provided and not full_refresh
        total_source_records = spark_df.count()
        incremental_mode = False
        validated_records = total_source_records

        if since_timestamp and not full_refresh:
            from pyspark.sql import functions as F

            # Convert datetime to unix epoch (meta_load_dt is stored as integer)
            cutoff_epoch = int(since_timestamp.timestamp())
            spark_df = spark_df.filter(
                F.col("meta_load_dt").isNotNull()
                & (F.col("meta_load_dt") > F.lit(cutoff_epoch))
            )
            validated_records = spark_df.count()
            incremental_mode = True
            self.logger.info(
                f"Incremental validation: {validated_records} of {total_source_records} records "
                f"(since {since_timestamp.isoformat()})"
            )

            if validated_records == 0:
                self.logger.info(f"No new records to validate for {table_name}")
                return QualityCheckRun(
                    pipeline_name=pipeline_name,
                    table_name=table_name,
                    run_id=run_id,
                    run_timestamp=datetime.now(),
                    results=[],
                    should_block=False,
                    since_timestamp=since_timestamp,
                    incremental_mode=True,
                    total_source_records=total_source_records,
                    validated_records=0,
                )

        # Extract ingested-stage checks from the unified expectation suite.
        configured_checks, thresholds_dict = self._get_configured_checks(umf)

        # Add default checks (row count change) unless already configured
        checks = self._merge_with_defaults(configured_checks)

        if not checks:
            self.logger.info(f"No quality checks to execute for {table_name}")
            return QualityCheckRun(
                pipeline_name=pipeline_name,
                table_name=table_name,
                run_id=run_id,
                results=[],
                should_block=False,
                since_timestamp=since_timestamp if incremental_mode else None,
                incremental_mode=incremental_mode,
                total_source_records=total_source_records,
                validated_records=validated_records,
            )

        self.logger.info(f"Executing {len(checks)} quality checks for {table_name}")

        # If GX is unavailable, record skipped checks without blocking pipeline
        if not self.gx_available:
            self.logger.warning(
                "Great Expectations not available - recording skipped quality checks for "
                f"{table_name}"
            )
            results = [
                self._build_unavailable_result(table_name, check) for check in checks
            ]
            score = self._calculate_quality_score(results)
            thresholds = None
            if thresholds_dict:
                thresholds = QualityThreshold(**thresholds_dict)
            self._should_block_pipeline(results, score, thresholds)
            return QualityCheckRun(
                pipeline_name=pipeline_name,
                table_name=table_name,
                run_id=run_id,
                run_timestamp=datetime.now(),
                results=results,
                score=score,
                thresholds=thresholds,
                should_block=False,
                error_message="Great Expectations not available - checks skipped",
                since_timestamp=since_timestamp if incremental_mode else None,
                incremental_mode=incremental_mode,
                total_source_records=total_source_records,
                validated_records=validated_records,
            )

        # Filter checks: skip disabled and pending, enrich run-comparison kwargs
        executable_checks: list[QualityCheck] = []
        for check in checks:
            expectation = check.expectation or {}
            meta = expectation.get("meta", {})
            exp_type = expectation.get("type") or expectation.get("expectation_type")

            if meta.get("severity") == "skip":
                skip_reason = meta.get("skip_reason", "User disabled")
                self.logger.info(
                    f"Skipping disabled quality check for {table_name}: {exp_type} ({skip_reason})"
                )
                continue

            if exp_type == "expect_validation_rule_pending_implementation":
                self.logger.debug(
                    f"Skipping pending expectation for {table_name}: "
                    f"{meta.get('rule_id', 'unknown')}"
                )
                continue

            executable_checks.append(check)

        # Build expectation dicts and execute in one batch via GXSuiteExecutor
        results: list[QualityCheckResult] = []
        results = self._execute_batch(spark_df, table_name, executable_checks)

        # Calculate quality score
        score = self._calculate_quality_score(results)

        # Parse thresholds if configured
        thresholds = None
        if thresholds_dict:
            thresholds = QualityThreshold(**thresholds_dict)

        # Determine if pipeline should be blocked
        should_block = self._should_block_pipeline(results, score, thresholds)

        return QualityCheckRun(
            pipeline_name=pipeline_name,
            table_name=table_name,
            run_id=run_id,
            run_timestamp=datetime.now(),
            results=results,
            score=score,
            thresholds=thresholds,
            should_block=should_block,
            since_timestamp=since_timestamp if incremental_mode else None,
            incremental_mode=incremental_mode,
            total_source_records=total_source_records,
            validated_records=validated_records,
        )

    def _get_configured_checks(
        self,
        umf: Any,
    ) -> tuple[list[QualityCheck], dict[str, Any] | None]:
        """Return configured ingested checks and thresholds for a loaded UMF.

        Prefer the unified ExpectationSuite when it contains expectations.
        Fall back to migrating legacy quality_checks when the suite is absent or empty.
        """
        suite = umf.expectations
        if suite is None or not suite.expectations:
            suite = migrate_to_expectation_suite(umf.model_dump(exclude_none=True))

        from tablespec.models.umf import QualityCheck as QualityCheckModel

        configured_checks = [
            QualityCheckModel(
                expectation=exp.model_dump(),
                severity=exp.meta.severity,
                blocking=exp.meta.blocking,
                description=exp.meta.description,
                tags=list(exp.meta.tags),
            )
            for exp in suite.ingested
        ]
        return configured_checks, suite.thresholds

    def _execute_batch(
        self,
        spark_df: DataFrame,
        table_name: str,
        checks: list[QualityCheck],
    ) -> list[QualityCheckResult]:
        """Execute quality checks as a single batch via GXSuiteExecutor.

        Preserves check↔result correspondence by position: the i-th expectation
        result maps to the i-th check in the input list.

        Args:
            spark_df: PySpark DataFrame to validate.
            table_name: Name of the table being validated.
            checks: Filtered list of executable quality checks.

        Returns:
            List of QualityCheckResult, one per input check.
        """
        if not checks:
            return []

        # Build parallel lists: expectations (for GX) and metadata (for result mapping)
        expectations: list[dict[str, Any]] = []
        check_meta: list[
            tuple[str, str | None, str, list[str], str, bool, str | None]
        ] = []

        for check in checks:
            expectation_type, kwargs, column_name, check_id, tags = (
                self._extract_check_metadata(check)
            )

            # Enrich kwargs with baseline data for run comparison expectations
            if is_run_comparison_expectation(expectation_type):
                kwargs = self._enrich_with_baseline(
                    expectation_type, kwargs, column_name
                )

            expectation = check.expectation or {}
            meta = expectation.get("meta", {})
            expectations.append(
                {
                    "type": expectation_type,
                    "kwargs": kwargs,
                    "meta": meta,
                }
            )
            check_meta.append(
                (
                    expectation_type,
                    column_name,
                    check_id,
                    tags,
                    check.severity,
                    check.blocking,
                    check.description,
                )
            )

        try:
            suite_result = self.executor.execute_suite(spark_df, expectations)
        except Exception as e:
            self.logger.exception(f"Batch execution failed for {table_name}: {e}")
            # Return failed results for all checks
            return [
                QualityCheckResult(
                    check_id=cm[2],
                    expectation_type=cm[0],
                    column_name=cm[1],
                    success=False,
                    severity=cm[4],
                    blocking=cm[5],
                    description=cm[6],
                    details={"error": str(e), "error_type": type(e).__name__},
                    tags=cm[3],
                )
                for cm in check_meta
            ]

        # Map suite results back to QualityCheckResult by position
        results: list[QualityCheckResult] = []
        for i, (
            exp_type,
            col_name,
            check_id,
            tags,
            severity,
            blocking,
            description,
        ) in enumerate(check_meta):
            if i < len(suite_result.results):
                er = suite_result.results[i]
                results.append(
                    QualityCheckResult(
                        check_id=check_id,
                        expectation_type=exp_type,
                        column_name=col_name,
                        success=er.success,
                        severity=severity,
                        blocking=blocking,
                        description=description,
                        unexpected_count=er.unexpected_count,
                        unexpected_percent=er.details.get("unexpected_percent"),
                        observed_value=er.observed_value,
                        details=er.details,
                        tags=tags,
                    )
                )
            else:
                # Defensive: result not returned (shouldn't happen)
                results.append(
                    QualityCheckResult(
                        check_id=check_id,
                        expectation_type=exp_type,
                        column_name=col_name,
                        success=False,
                        severity=severity,
                        blocking=blocking,
                        description=description,
                        details={"error": "No result returned from GX suite execution"},
                        tags=tags,
                    )
                )

        return results

    def _extract_check_metadata(
        self, check: QualityCheck
    ) -> tuple[str, dict[str, Any], str | None, str, list[str]]:
        """Extract expectation metadata for consistent check identification."""
        expectation = check.expectation
        expectation_type = expectation.get("expectation_type") or expectation.get(
            "type", "unknown"
        )
        kwargs = expectation.get("kwargs", {})
        column_name = kwargs.get("column")
        check_id = (
            f"{expectation_type}_{column_name}" if column_name else expectation_type
        )
        tags = list(check.tags)
        return expectation_type, kwargs, column_name, check_id, tags

    def _enrich_with_baseline(
        self,
        expectation_type: str,
        kwargs: dict[str, Any],
        column_name: str | None,
    ) -> dict[str, Any]:
        """Enrich kwargs with baseline data for run comparison expectations.

        Injects the appropriate baseline data (row count, distribution, checksums)
        based on the expectation type.

        Args:
            expectation_type: The GX expectation type
            kwargs: Original kwargs from the check configuration
            column_name: Optional column name for column-specific checks

        Returns:
            Enriched kwargs with baseline data injected

        """
        # Make a copy to avoid mutating the original
        enriched = dict(kwargs)

        if self.baseline is None:
            # No baseline available - expectations will handle gracefully
            self.logger.debug(
                f"No baseline available for {expectation_type} - will pass as first run"
            )
            return enriched

        if expectation_type == "expect_row_count_change_within_percent":
            enriched["_baseline_row_count"] = self.baseline.row_count
            self.logger.debug(f"Injected baseline row count: {self.baseline.row_count}")

        elif expectation_type == "expect_column_distribution_stable":
            if column_name and column_name in self.baseline.column_distributions:
                dist = self.baseline.column_distributions[column_name]
                enriched["_baseline_distribution"] = dist.value_counts
                self.logger.debug(
                    f"Injected baseline distribution for {column_name}: "
                    f"{len(dist.value_counts)} values"
                )
            else:
                self.logger.debug(f"No baseline distribution for column {column_name}")

        elif expectation_type == "expect_record_changes_within_limits":
            if self.baseline.record_checksums:
                enriched["_baseline_checksums"] = self.baseline.record_checksums
                enriched["_baseline_pk_columns"] = self.baseline.primary_key_columns
                self.logger.debug(
                    f"Injected baseline checksums: {len(self.baseline.record_checksums)} records"
                )
            else:
                self.logger.debug(
                    "No baseline checksums available for record comparison"
                )

        return enriched

    def _build_unavailable_result(
        self, table_name: str, check: QualityCheck
    ) -> QualityCheckResult:
        """Return a non-blocking result when GX is unavailable."""
        expectation_type, _kwargs, column_name, check_id, tags = (
            self._extract_check_metadata(check)
        )
        return QualityCheckResult(
            check_id=check_id,
            expectation_type=expectation_type,
            column_name=column_name,
            success=False,
            severity=check.severity,
            blocking=check.blocking,
            description=check.description,
            details={
                "error": f"Great Expectations unavailable for {table_name}",
                "error_type": "GreatExpectationsUnavailable",
            },
            tags=tags,
        )

    def _resolve_pipeline_name(self, umf_path: Path, pipeline_name: str | None) -> str:
        """Resolve pipeline name using PipelineDiscovery when not provided.

        Args:
            umf_path: Path to UMF file or directory
            pipeline_name: Optional pipeline name provided by caller

        Returns:
            Resolved pipeline name

        """
        if pipeline_name:
            return pipeline_name

        if PipelineDiscovery is not None:
            discovery = PipelineDiscovery()
            source = discovery.get_source_from_env()
            pipelines = discovery.list_pipelines(source)

            for pipeline, _version in pipelines:
                pipeline_path = discovery.get_pipeline_path(pipeline, source)
                if umf_path.is_relative_to(pipeline_path):
                    return pipeline

        msg = f"Unable to resolve pipeline name for UMF path: {umf_path}"
        raise ValueError(msg)

    def _merge_with_defaults(
        self, configured_checks: list[QualityCheck]
    ) -> list[QualityCheck]:
        """Merge configured checks with default checks.

        Default checks (like row count change) are added automatically unless:
        - A check with the same expectation type is already configured
        - The 'skip_defaults' tag is present in any configured check

        Args:
            configured_checks: List of explicitly configured quality checks

        Returns:
            Merged list with defaults added where appropriate

        """
        from tablespec.models.umf import QualityCheck as QualityCheckModel

        # Check if defaults should be skipped
        all_tags = [tag for check in configured_checks for tag in (check.tags or [])]
        if "skip_defaults" in all_tags:
            self.logger.debug("Skipping default checks due to 'skip_defaults' tag")
            return configured_checks

        # Get expectation types already configured
        configured_types = set()
        for check in configured_checks:
            exp = check.expectation or {}
            exp_type = exp.get("type") or exp.get("expectation_type")
            if exp_type:
                configured_types.add(exp_type)

        # Build list with defaults prepended (unless already configured)
        merged_checks: list[QualityCheck] = []

        # Add row count check if not already configured
        row_count_type = DEFAULT_ROW_COUNT_CHECK["expectation"]["type"]
        if row_count_type not in configured_types:
            default_check = QualityCheckModel(**DEFAULT_ROW_COUNT_CHECK)
            merged_checks.append(default_check)
            self.logger.debug(f"Added default check: {row_count_type}")

        # Add all configured checks
        merged_checks.extend(configured_checks)

        return merged_checks

    def _calculate_quality_score(
        self, results: list[QualityCheckResult]
    ) -> QualityScore:
        """Calculate quality metrics from check results.

        Args:
            results: List of quality check results

        Returns:
            QualityScore with calculated metrics

        """
        total_checks = len(results)
        if total_checks == 0:
            return QualityScore(
                total_checks=0,
                passed_checks=0,
                failed_checks=0,
                critical_failures=0,
                warning_failures=0,
                info_failures=0,
                success_rate=0.0,
                critical_failure_rate=0.0,
                warning_failure_rate=0.0,
                blocking_failures=0,
                threshold_breached=False,  # Will be updated later
            )

        passed_checks = sum(1 for r in results if r.success)
        failed_checks = total_checks - passed_checks

        critical_failures = sum(
            1 for r in results if not r.success and r.severity in {"critical", "error"}
        )
        warning_failures = sum(
            1 for r in results if not r.success and r.severity == "warning"
        )
        info_failures = sum(
            1 for r in results if not r.success and r.severity == "info"
        )

        blocking_failures = sum(1 for r in results if not r.success and r.blocking)

        success_rate = (passed_checks / total_checks) * 100
        critical_failure_rate = (critical_failures / total_checks) * 100
        warning_failure_rate = (warning_failures / total_checks) * 100

        return QualityScore(
            total_checks=total_checks,
            passed_checks=passed_checks,
            failed_checks=failed_checks,
            critical_failures=critical_failures,
            warning_failures=warning_failures,
            info_failures=info_failures,
            success_rate=success_rate,
            critical_failure_rate=critical_failure_rate,
            warning_failure_rate=warning_failure_rate,
            blocking_failures=blocking_failures,
            threshold_breached=False,  # Will be updated by caller
        )

    def _should_block_pipeline(
        self,
        results: list[QualityCheckResult],
        score: QualityScore,
        thresholds: QualityThreshold | None,
    ) -> bool:
        """Determine if pipeline should be blocked based on check results.

        Blocks if:
        - Any check with blocking=True and severity in (critical, error) has failed
        - Failure count exceeds thresholds.max_failures (if configured)
        - Critical failure count exceeds thresholds.max_critical_failures (if configured)
        - Critical failure rate exceeds thresholds.max_critical_failure_percent
        - Warning failure rate exceeds thresholds.max_warning_failure_percent
        - Success rate falls below thresholds.min_success_rate

        Args:
            results: List of quality check results
            score: Calculated quality score
            thresholds: Optional threshold configuration

        Returns:
            True if pipeline should be blocked, False otherwise.

        """
        should_block = False

        # Check individual blocking rules: block on failed checks that are
        # marked blocking with critical or error severity
        for result in results:
            if (
                not result.success
                and result.blocking
                and result.severity in ("critical", "error")
            ):
                self.logger.warning(
                    f"Blocking check failed: {result.check_id} ({result.severity})"
                )
                should_block = True

        # Check thresholds if configured
        if thresholds:
            threshold_breached = False

            # Check aggregate failure count threshold
            if thresholds.max_failures is not None:
                failure_count = sum(1 for r in results if not r.success)
                if failure_count > thresholds.max_failures:
                    self.logger.warning(
                        f"Failure count {failure_count} exceeds threshold {thresholds.max_failures}"
                    )
                    threshold_breached = True

            # Check critical failure count threshold
            if thresholds.max_critical_failures is not None:
                critical_count = sum(
                    1 for r in results if not r.success and r.severity == "critical"
                )
                if critical_count > thresholds.max_critical_failures:
                    self.logger.warning(
                        f"Critical failure count {critical_count} exceeds threshold "
                        f"{thresholds.max_critical_failures}"
                    )
                    threshold_breached = True

            # Check critical failure rate
            if (
                thresholds.max_critical_failure_percent is not None
                and score.critical_failure_rate
                > thresholds.max_critical_failure_percent
            ):
                self.logger.warning(
                    f"Critical failure rate ({score.critical_failure_rate:.1f}%) exceeds threshold "
                    f"({thresholds.max_critical_failure_percent:.1f}%)"
                )
                threshold_breached = True

            # Check warning failure rate
            if (
                thresholds.max_warning_failure_percent is not None
                and score.warning_failure_rate > thresholds.max_warning_failure_percent
            ):
                self.logger.warning(
                    f"Warning failure rate ({score.warning_failure_rate:.1f}%) exceeds threshold "
                    f"({thresholds.max_warning_failure_percent:.1f}%)"
                )
                threshold_breached = True

            # Check minimum success rate
            if (
                thresholds.min_success_rate is not None
                and score.success_rate < thresholds.min_success_rate
            ):
                self.logger.warning(
                    f"Success rate ({score.success_rate:.1f}%) below minimum threshold "
                    f"({thresholds.min_success_rate:.1f}%)"
                )
                threshold_breached = True

            # Update score with threshold breach status
            score.threshold_breached = threshold_breached
            if threshold_breached:
                should_block = True

        return should_block
