"""Suite-level GX execution with staged validation support.

Executes entire expectation suites in a single batch pass via the GX Spark
engine, replacing the per-expectation validator pattern in gx_wrapper.py.

Requires a Spark or Sail session — use ``get_session()`` from
``tablespec.session`` to obtain one.

Supports staged execution where raw (string) and ingested (typed)
expectations route to different DataFrames.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ExpectationResult:
    """Result of a single expectation evaluation."""

    expectation_type: str
    success: bool
    column: str | None = None
    observed_value: Any = None
    unexpected_count: int = 0
    unexpected_values: list[Any] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class SuiteExecutionResult:
    """Result of executing an entire expectation suite."""

    results: list[ExpectationResult]
    success: bool  # True if all expectations passed
    total: int = 0
    passed: int = 0
    failed: int = 0

    @classmethod
    def from_results(cls, results: list[ExpectationResult]) -> SuiteExecutionResult:
        passed = sum(1 for r in results if r.success)
        failed = sum(1 for r in results if not r.success)
        return cls(
            results=results,
            success=all(r.success for r in results) if results else True,
            total=len(results),
            passed=passed,
            failed=failed,
        )


@dataclass
class StagedExecutionResult:
    """Result of staged (raw + ingested) execution."""

    raw: SuiteExecutionResult
    ingested: SuiteExecutionResult
    skipped: list[dict[str, Any]]  # Redundant/unknown expectations that were skipped


class GXSuiteExecutor:
    """Execute GX expectation suites against Spark DataFrames.

    Requires a Spark or Sail session. All validation runs through the GX
    Spark execution engine.

    Supports two execution modes:
    - execute_suite(): Run all expectations against a single DataFrame
    - execute_staged(): Classify and route expectations to raw/ingested DataFrames
    """

    def __init__(self, spark: Any | None = None) -> None:
        """Initialise the executor.

        Args:
            spark: A ``SparkSession`` (from Spark or Sail).
        """
        self._spark = spark
        self._context: Any | None = None

    def _get_context(self) -> Any:
        if self._context is None:
            import great_expectations as gx

            self._context = gx.get_context()  # type: ignore[attr-defined]
        return self._context

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute_suite(
        self,
        df: Any,
        expectations: list[dict[str, Any]],
    ) -> SuiteExecutionResult:
        """Execute all expectations against a Spark DataFrame in one batch.

        Args:
            df: A PySpark DataFrame (from Spark or Sail session).
            expectations: List of expectation dicts with 'type', 'kwargs', and
                optional 'meta' keys.

        Returns:
            SuiteExecutionResult with per-expectation results and summary counts.
        """
        if not expectations:
            return SuiteExecutionResult.from_results([])

        return self._execute_spark(df, expectations)

    def validate_expectation(
        self,
        exp_type: str,
        kwargs: dict[str, Any],
        meta: dict[str, Any] | None = None,
    ) -> tuple[bool, str | None]:
        """Validate a single expectation configuration without executing it."""
        from great_expectations.core import ExpectationSuite as GXSuite
        from great_expectations.expectations.expectation_configuration import (
            ExpectationConfiguration,
        )

        try:
            suite = GXSuite(name="validation_test")
            suite.add_expectation_configuration(
                ExpectationConfiguration(type=exp_type, kwargs=kwargs, meta=meta or {})
            )
            return (True, None)
        except Exception as exc:
            return (False, str(exc))

    def execute_staged(
        self,
        raw_df: Any,
        ingested_df: Any,
        expectations: list[dict[str, Any]],
    ) -> StagedExecutionResult:
        """Classify expectations by stage and execute against appropriate DataFrame.

        Raw expectations run against raw_df (string data).
        Ingested expectations run against ingested_df (typed data).
        Redundant/unknown expectations are skipped.

        Args:
            raw_df: Spark DataFrame with string columns representing raw/bronze data.
            ingested_df: Spark DataFrame with typed columns representing ingested data.
            expectations: List of expectation dicts to classify and execute.

        Returns:
            StagedExecutionResult with separate raw/ingested results and skipped list.
        """
        from tablespec.models.umf import (
            REDUNDANT_VALIDATION_TYPES,
            classify_validation_type,
        )

        raw_exps: list[dict[str, Any]] = []
        ingested_exps: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []

        for exp in expectations:
            exp_type = exp.get("type", exp.get("expectation_type", ""))

            if exp_type in REDUNDANT_VALIDATION_TYPES:
                skipped.append({"expectation": exp, "reason": "redundant"})
                continue

            # Honor explicit stage from meta, fall back to classification
            stage: str | None = exp.get("meta", {}).get("validation_stage")
            if not stage:
                stage = classify_validation_type(exp_type)

            if stage == "raw":
                raw_exps.append(exp)
            elif stage == "ingested":
                ingested_exps.append(exp)
            else:
                skipped.append(
                    {"expectation": exp, "reason": f"unknown stage: {stage}"}
                )

        raw_result = (
            self.execute_suite(raw_df, raw_exps)
            if raw_exps
            else SuiteExecutionResult.from_results([])
        )
        ingested_result = (
            self.execute_suite(ingested_df, ingested_exps)
            if ingested_exps
            else SuiteExecutionResult.from_results([])
        )

        return StagedExecutionResult(
            raw=raw_result,
            ingested=ingested_result,
            skipped=skipped,
        )

    # ------------------------------------------------------------------
    # Internal: execution routing
    # ------------------------------------------------------------------

    @staticmethod
    def _is_connect_dataframe(df: Any) -> bool:
        """True iff *df* is a Spark Connect DataFrame.

        Connect DataFrames live under the ``pyspark.sql.connect`` package (Sail,
        Databricks serverless). The GX ``add_spark`` path is classic-Spark only —
        it relies on a JVM ``SparkContext`` that does not exist on Connect — so
        Connect DataFrames must take the native DataFrame-API path instead.
        """
        return type(df).__module__.startswith("pyspark.sql.connect")

    def _execute_spark(
        self,
        df: Any,
        expectations: list[dict[str, Any]],
    ) -> SuiteExecutionResult:
        """Execute expectations against a Spark DataFrame.

        Routing:
        - Spark CONNECT DataFrames (Sail / Databricks serverless) -> the native
          DataFrame-API path (``_execute_native``). GX's ``add_spark`` engine uses
          classic ``pyspark.sql.functions`` that assert a live JVM ``SparkContext``,
          which does not exist on Connect; without this branch every data-scanning
          expectation would silently return ``success=False``.
        - CLASSIC Spark DataFrames -> the GX ``add_spark`` engine (unchanged).
        """
        if self._is_connect_dataframe(df):
            return self._execute_native(df, expectations)
        return self._execute_via_gx_spark(df, expectations)

    def _execute_native(
        self,
        df: Any,
        expectations: list[dict[str, Any]],
    ) -> SuiteExecutionResult:
        """Connect-safe evaluation of a suite via the Spark DataFrame API.

        Each expectation is evaluated with ``_functions_for(df)``-selected column
        expressions (session-correct on classic Spark and Spark Connect alike), and
        mapped into the SAME ``ExpectationResult`` shape that
        ``_parse_validation_result`` produces, so downstream consumers (report.py,
        quality/executor.py, table_validator.py) are unaffected.

        Unknown / unsupported expectation types are surfaced as failed
        ``ExpectationResult`` entries. The native path must fail closed so a
        suite never reports enforcement for an expectation it did not execute.
        """
        from tablespec.validation import native_executor

        results: list[ExpectationResult] = []
        for exp in expectations:
            exp_type = exp.get("type", exp.get("expectation_type", ""))
            kwargs = exp.get("kwargs", {})
            column = kwargs.get("column")
            try:
                raw = native_executor.evaluate_expectation(df, exp_type, kwargs)
                if raw is None:
                    raw = self._evaluate_custom_native(df, exp_type, kwargs)
                if raw is None:
                    results.append(
                        ExpectationResult(
                            expectation_type=exp_type,
                            success=False,
                            column=column,
                            observed_value=f"unsupported on native path: {exp_type}",
                            details={
                                "error": f"unsupported native expectation: {exp_type}"
                            },
                        )
                    )
                    continue
                results.append(
                    self._native_result_to_expectation_result(exp_type, column, raw)
                )
            except Exception as exc:  # noqa: BLE001 - one bad expectation must not abort the suite
                logger.exception("Native evaluation of %s failed: %s", exp_type, exc)
                results.append(
                    ExpectationResult(
                        expectation_type=exp_type,
                        success=False,
                        column=column,
                        observed_value=f"native evaluation failed: {exc}",
                        details={"error": str(exc)},
                    )
                )
        return SuiteExecutionResult.from_results(results)

    @staticmethod
    def _evaluate_custom_native(
        df: Any, exp_type: str, kwargs: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Evaluate tablespec custom expectations natively (Connect-safe)."""
        from tablespec.validation.custom_gx_expectations import (
            validate_cast_to_type,
            validate_column_pair_date_order,
            validate_date_in_current_year,
            validate_domain_type,
        )

        if exp_type == "expect_column_values_to_cast_to_type":
            return validate_cast_to_type(
                df,
                kwargs["column"],
                kwargs["target_type"],
                format_str=kwargs.get("format"),
                fallback_formats=kwargs.get("fallback_formats"),
                mostly=kwargs.get("mostly", 1.0),
            )
        if exp_type == "expect_column_pair_values_a_to_be_greater_than_b":
            return validate_column_pair_date_order(
                df,
                kwargs["column_A"],
                kwargs["column_B"],
                or_equal=kwargs.get("or_equal", True),
                mostly=kwargs.get("mostly", 1.0),
            )
        if exp_type == "expect_column_date_to_be_in_current_year":
            return validate_date_in_current_year(
                df, kwargs["column"], mostly=kwargs.get("mostly", 1.0)
            )
        if exp_type == "expect_column_values_to_match_domain_type":
            # validate_domain_type is a pandas shim; materialize the (small) column.
            pdf = df.select(kwargs["column"]).toPandas()
            return validate_domain_type(
                pdf,
                kwargs["column"],
                kwargs["domain_type"],
                kwargs.get("mostly", 1.0),
            )
        return None

    @staticmethod
    def _native_result_to_expectation_result(
        exp_type: str, column: str | None, raw: dict[str, Any]
    ) -> ExpectationResult:
        """Map a native ``{success, result}`` dict to an ``ExpectationResult``."""
        result_obj = raw.get("result", {})
        return ExpectationResult(
            expectation_type=exp_type,
            success=bool(raw.get("success", False)),
            column=column,
            observed_value=result_obj.get("observed_value"),
            unexpected_count=result_obj.get("unexpected_count", 0),
            unexpected_values=result_obj.get("partial_unexpected_list", []),
            details=result_obj,
        )

    def _execute_via_gx_spark(
        self,
        df: Any,
        expectations: list[dict[str, Any]],
    ) -> SuiteExecutionResult:
        """Execute expectations via the GX ``add_spark`` engine (CLASSIC Spark only).

        This path uses GX's ``SparkDFExecutionEngine``, which depends on classic
        ``pyspark.sql.functions`` and a live JVM ``SparkContext``. It is NOT usable
        on Spark Connect — Connect DataFrames are routed to ``_execute_native`` by
        ``_execute_spark`` before reaching here.
        """
        from great_expectations.core import ExpectationSuite as GXSuite
        from great_expectations.core import ValidationDefinition
        from great_expectations.expectations.expectation_configuration import (
            ExpectationConfiguration,
        )

        native_types = {
            "expect_column_value_lengths_to_equal",
            "expect_embedding_dimension_multiple_of_16_advisory",
        }
        native_expectations: list[dict[str, Any]] = []
        gx_expectations: list[dict[str, Any]] = []
        for exp in expectations:
            exp_type = exp.get("type", exp.get("expectation_type", ""))
            if exp_type in native_types:
                native_expectations.append(exp)
            else:
                gx_expectations.append(exp)

        native_result = (
            self._execute_native(df, native_expectations)
            if native_expectations
            else SuiteExecutionResult.from_results([])
        )
        if not gx_expectations:
            return native_result

        context = self._get_context()
        run_id = uuid.uuid4().hex[:8]

        # Build suite
        suite = GXSuite(name=f"suite_{run_id}")
        for exp in gx_expectations:
            exp_type = exp.get("type", exp.get("expectation_type", ""))
            kwargs = exp.get("kwargs", {})
            meta = exp.get("meta", {})
            suite.add_expectation_configuration(
                ExpectationConfiguration(type=exp_type, kwargs=kwargs, meta=meta)
            )
        suite = context.suites.add(suite)

        # Set up Spark datasource and asset
        ds_name = f"spark_ds_{run_id}"
        asset_name = f"spark_asset_{run_id}"
        batch_name = f"spark_batch_{run_id}"

        ds = None
        vd_name = f"vd_{run_id}"
        try:
            ds = context.data_sources.add_spark(name=ds_name)
            asset = ds.add_dataframe_asset(name=asset_name)
            batch_def = asset.add_batch_definition_whole_dataframe(batch_name)

            vd = context.validation_definitions.add(
                ValidationDefinition(name=vd_name, suite=suite, data=batch_def)
            )

            validation_result = vd.run(batch_parameters={"dataframe": df})
            parsed = self._parse_validation_result(validation_result)
            parsed = self._reconcile_dropped(df, parsed, gx_expectations)
            if native_expectations:
                return SuiteExecutionResult.from_results(
                    native_result.results + parsed.results
                )
            return parsed
        finally:
            self._cleanup(context, suite, ds, ds_name, asset_name, vd_name)

    def _reconcile_dropped(
        self,
        df: Any,
        parsed: SuiteExecutionResult,
        expectations_fed: list[dict[str, Any]],
    ) -> SuiteExecutionResult:
        """Re-evaluate any expectation GX dropped from its results.

        GX can return FEWER results than were fed:

          * two custom expectations of the SAME type (e.g. two
            ``expect_column_values_to_cast_to_type`` over different columns) collate
            into a single result entry, dropping the others, even on clean data; and
          * an expectation whose metric resolution RAISED (e.g. a strict ANSI cast
            on uncastable dirt before the ``try_cast`` fix) is silently dropped.

        A dropped expectation must never read as a pass. Rather than blindly fail it
        (which would false-fail the benign same-type-collation case), each missing
        ``(type, column)`` is RE-EVALUATED standalone via the Connect-safe native
        validators so it gets a REAL verdict. If a missing expectation cannot be
        re-evaluated standalone, it is surfaced as FAILED (fail-closed) so dropped
        dirt can never silently pass.
        """
        present = [(r.expectation_type, r.column) for r in parsed.results]
        if len(parsed.results) >= len(expectations_fed):
            return parsed

        remaining = list(present)
        extra: list[ExpectationResult] = []
        for exp in expectations_fed:
            exp_type = exp.get("type", exp.get("expectation_type", ""))
            kwargs = exp.get("kwargs", {})
            column = kwargs.get("column")
            key = (exp_type, column)
            if key in remaining:
                remaining.remove(key)
                continue
            extra.append(self._reeval_one(df, exp_type, kwargs, column))

        if not extra:
            return parsed
        return SuiteExecutionResult.from_results(parsed.results + extra)

    def _reeval_one(
        self, df: Any, exp_type: str, kwargs: dict[str, Any], column: str | None
    ) -> ExpectationResult:
        """Re-evaluate a single dropped expectation standalone (real verdict).

        Uses the native evaluator + custom validators (the same Connect-safe helpers
        the native path uses). On any failure to re-evaluate, fails closed so a
        dropped expectation never silently passes.
        """
        from tablespec.validation import native_executor

        try:
            raw = native_executor.evaluate_expectation(df, exp_type, kwargs)
            if raw is None:
                raw = self._evaluate_custom_native(df, exp_type, kwargs)
            if raw is None:
                return ExpectationResult(
                    expectation_type=exp_type,
                    success=False,
                    column=column,
                    observed_value=(
                        "dropped by GX and not re-evaluable standalone -> failed closed"
                    ),
                    details={"error": "dropped by GX; no standalone evaluator"},
                )
            return self._native_result_to_expectation_result(exp_type, column, raw)
        except Exception as exc:  # noqa: BLE001 - fail closed on re-eval error
            logger.exception("Re-eval of dropped %s failed: %s", exp_type, exc)
            return ExpectationResult(
                expectation_type=exp_type,
                success=False,
                column=column,
                observed_value=f"re-evaluation failed: {exc}",
                details={"error": str(exc)},
            )

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_validation_result(validation_result: Any) -> SuiteExecutionResult:
        """Convert a GX ValidationResult into our SuiteExecutionResult.

        Note: GX may return FEWER results than were fed (same-type custom-expectation
        collation, or a raised metric). :meth:`_reconcile_dropped` re-evaluates any
        such dropped expectation standalone so it never silently passes.
        """
        results: list[ExpectationResult] = []
        for res in validation_result.results:
            result_dict = res.to_json_dict() if hasattr(res, "to_json_dict") else {}
            result_obj = result_dict.get("result", {})
            exp_config = result_dict.get("expectation_config", {})

            results.append(
                ExpectationResult(
                    expectation_type=exp_config.get("type", ""),
                    success=result_dict.get("success", False),
                    column=exp_config.get("kwargs", {}).get("column"),
                    observed_value=result_obj.get("observed_value"),
                    unexpected_count=result_obj.get("unexpected_count", 0),
                    unexpected_values=result_obj.get("partial_unexpected_list", []),
                    details=result_obj,
                )
            )

        return SuiteExecutionResult.from_results(results)

    @staticmethod
    def _cleanup(
        context: Any,
        suite: Any,
        ds: Any | None,
        ds_name: str,
        asset_name: str,
        vd_name: str | None = None,
    ) -> None:
        """Clean up ephemeral GX resources."""
        if vd_name is not None:
            try:
                context.validation_definitions.delete(vd_name)
            except Exception:
                pass
        try:
            context.suites.delete(suite.name)
        except Exception:
            pass
        if ds is not None:
            try:
                ds.delete_asset(asset_name)
            except Exception:
                pass
        try:
            context.data_sources.delete(ds_name)
        except Exception:
            pass
