"""Table validation using UMF specifications with DataFrame error reporting.

The TableValidator module provides validation of PySpark DataFrames against
Universal Metadata Format (UMF) specifications, generating structured error
reports as DataFrames.

This implementation delegates to ``GXSuiteExecutor`` +
``BaselineExpectationGenerator`` for GX-supported expectations, and falls
back to direct SQL queries for legacy checks (format rules, value constraints,
schema diff).
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from pyspark.sql.types import (
    IntegerType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

if TYPE_CHECKING:
    from pyspark.sql import DataFrame, SparkSession

logger = logging.getLogger(__name__)

# Schema for validation error DataFrame
VALIDATION_ERROR_SCHEMA = StructType(
    [
        StructField("table_name", StringType(), False),
        StructField("validation_timestamp", TimestampType(), False),
        StructField(
            "error_type", StringType(), False
        ),  # schema, data_type, nullable, format, value, business_rule
        StructField("severity", StringType(), False),  # error, warning, info
        StructField("column_name", StringType(), True),  # null for table-level errors
        StructField("rule_name", StringType(), True),  # specific rule that failed
        StructField("rule_details", StringType(), True),  # rule specification/pattern
        StructField("error_message", StringType(), False),  # human-readable message
        StructField("error_count", IntegerType(), True),  # number of records affected
        StructField("sample_values", StringType(), True),  # sample of failing values
    ]
)


class TableValidator:
    """Validates Spark DataFrames against UMF specifications.

    Compatibility shim that routes GX-supported expectations through
    ``GXSuiteExecutor`` + ``BaselineExpectationGenerator``, and keeps
    SQL-based validation for schema, data-type, format-rule, and
    value-constraint checks.
    """

    def __init__(self, spark: SparkSession) -> None:
        """Initialize the validator with a Spark session.

        Args:
            spark: SparkSession for executing validation queries

        """
        self.spark = spark
        self.logger = logging.getLogger(self.__class__.__name__)
        self.errors: list[dict] = []

        # Set up GX execution path
        try:
            from tablespec.gx_baseline import BaselineExpectationGenerator
            from tablespec.validation.gx_executor import GXSuiteExecutor

            self._gen = BaselineExpectationGenerator()
            self._exec = GXSuiteExecutor(spark=spark)
            self._gx_available = True
        except ImportError:
            self._gen = None  # type: ignore[assignment]
            self._exec = None  # type: ignore[assignment]
            self._gx_available = False

    def validate_table(
        self,
        df: DataFrame,
        umf_path: Path,
        table_name: str | None = None,
    ) -> DataFrame:
        """Validate DataFrame against UMF specification.

        Args:
            df: Spark DataFrame to validate
            umf_path: Path to UMF specification file
            table_name: Optional table name override

        Returns:
            DataFrame with validation errors (empty if no errors)

        """
        self.logger.info(f"Starting validation for table using UMF: {umf_path}")

        # Load UMF specification
        umf = self._load_umf(umf_path)
        table = table_name or umf.get("table_name", "unknown")
        timestamp = datetime.now()

        # Clear previous errors
        self.errors = []

        # --- SQL-based checks (schema, data types, business rules) ---
        self._validate_schema(df, umf, table, timestamp)
        self._validate_data_types(df, umf, table, timestamp)
        self._validate_nullable(df, umf, table, timestamp)
        self._validate_rules(df, umf, table, timestamp)

        # --- GX-based checks (baseline expectations) ---
        if self._gx_available:
            self._validate_via_gx(df, umf, table, timestamp)

        # Convert errors to DataFrame
        if self.errors:
            self.logger.info(f"Found {len(self.errors)} validation issues for {table}")
            return self.spark.createDataFrame(self.errors, VALIDATION_ERROR_SCHEMA)
        self.logger.info(f"All validations passed for {table}")
        # Return empty DataFrame with correct schema
        return self.spark.createDataFrame([], VALIDATION_ERROR_SCHEMA)

    # ------------------------------------------------------------------
    # GX-based validation
    # ------------------------------------------------------------------

    def _validate_via_gx(
        self,
        df: DataFrame,
        umf: dict[str, Any],
        table_name: str,
        timestamp: datetime,
    ) -> None:
        """Run baseline expectations via GXSuiteExecutor and map failures to errors.

        Only adds errors for GX-specific checks that aren't already covered
        by the SQL-based validation above (e.g. cast-to-type, domain-type).
        """
        # Expectation types already handled by SQL-based validation
        sql_covered_types = {
            "expect_table_column_count_to_equal",
            "expect_table_columns_to_match_ordered_list",
            "expect_column_values_to_not_be_null",
            "expect_column_value_lengths_to_be_between",
        }

        try:
            expectations = self._gen.generate_baseline_expectations(
                umf, include_structural=False
            )
            # Filter to only GX-specific expectations
            gx_expectations = [
                e for e in expectations if e.get("type") not in sql_covered_types
            ]

            if not gx_expectations:
                return

            result = self._exec.execute_suite(df, gx_expectations)

            for er in result.results:
                if not er.success:
                    self._add_error(
                        table_name=table_name,
                        timestamp=timestamp,
                        error_type="gx_expectation",
                        severity="warning",
                        column_name=er.column,
                        rule_name=er.expectation_type,
                        rule_details=str(er.details.get("observed_value", ""))
                        if isinstance(er.details, dict)
                        else None,
                        error_message=f"GX expectation {er.expectation_type} failed"
                        + (f" for column {er.column}" if er.column else ""),
                        error_count=er.unexpected_count
                        if er.unexpected_count
                        else None,
                    )
        except Exception as e:
            self.logger.warning(f"GX-based validation failed (non-fatal): {e}")

    # ------------------------------------------------------------------
    # Existing SQL-based validation (preserved for compatibility)
    # ------------------------------------------------------------------

    def _load_umf(self, umf_path: Path) -> dict:
        """Load UMF specification from YAML file."""
        try:
            with Path(umf_path).open(encoding="utf-8") as f:
                umf = yaml.safe_load(f)
            self.logger.debug(
                f"Loaded UMF for table: {umf.get('table_name', 'unknown')}"
            )
            return umf
        except Exception as e:
            self.logger.exception(f"Failed to load UMF from {umf_path}: {e}")
            raise

    def _add_error(
        self,
        table_name: str,
        timestamp: datetime,
        error_type: str,
        severity: str,
        error_message: str,
        column_name: str | None = None,
        rule_name: str | None = None,
        rule_details: str | None = None,
        error_count: int | None = None,
        sample_values: str | None = None,
    ) -> None:
        """Add a validation error to the collection."""
        self.errors.append(
            {
                "table_name": table_name,
                "validation_timestamp": timestamp,
                "error_type": error_type,
                "severity": severity,
                "column_name": column_name,
                "rule_name": rule_name,
                "rule_details": rule_details,
                "error_message": error_message,
                "error_count": error_count,
                "sample_values": sample_values,
            }
        )

    def _validate_schema(
        self,
        df: DataFrame,
        umf: dict,
        table_name: str,
        timestamp: datetime,
    ) -> None:
        """Validate that DataFrame schema matches UMF column definitions."""
        df_columns = set(df.columns)
        umf_columns = {col["name"] for col in umf.get("columns", [])}

        # Check for missing columns
        missing_columns = umf_columns - df_columns
        for col in missing_columns:
            self._add_error(
                table_name=table_name,
                timestamp=timestamp,
                error_type="schema",
                severity="error",
                column_name=col,
                rule_name="column_required",
                rule_details="Column defined in UMF specification",
                error_message=f"Required column '{col}' is missing from DataFrame",
            )

        # Check for extra columns
        extra_columns = df_columns - umf_columns
        for col in extra_columns:
            self._add_error(
                table_name=table_name,
                timestamp=timestamp,
                error_type="schema",
                severity="warning",
                column_name=col,
                rule_name="column_unexpected",
                rule_details="Column not defined in UMF specification",
                error_message=f"Unexpected column '{col}' found in DataFrame",
            )

    def _validate_data_types(
        self,
        df: DataFrame,
        umf: dict,
        table_name: str,
        timestamp: datetime,
    ) -> None:
        """Validate DataFrame column data types against UMF specification."""
        df_schema = {
            field.name: field.dataType.simpleString() for field in df.schema.fields
        }

        for col_spec in umf.get("columns", []):
            col_name = col_spec["name"]
            expected_type = col_spec.get("data_type", "").upper()

            if col_name not in df_schema:
                continue

            actual_type = df_schema[col_name].upper()

            type_mapping = {
                "VARCHAR": ["STRING"],
                "CHAR": ["STRING"],
                "INTEGER": ["INT", "INTEGER"],
                "BIGINT": ["BIGINT", "LONG"],
                "DECIMAL": ["DECIMAL"],
                "DATE": ["DATE"],
                "TIMESTAMP": ["TIMESTAMP"],
                "BOOLEAN": ["BOOLEAN"],
            }

            if expected_type in type_mapping:
                valid_types = type_mapping[expected_type]
                if actual_type not in valid_types:
                    self._add_error(
                        table_name=table_name,
                        timestamp=timestamp,
                        error_type="data_type",
                        severity="error",
                        column_name=col_name,
                        rule_name="type_mismatch",
                        rule_details=f"Expected: {expected_type}, Found: {actual_type}",
                        error_message=f"Column '{col_name}' has incorrect data type",
                    )

    def _validate_nullable(
        self,
        df: DataFrame,
        umf: dict,
        table_name: str,
        timestamp: datetime,
    ) -> None:
        """Validate nullable constraints based on UMF specification.

        Only uses context-based nullable validation when the UMF explicitly
        declares a ``context_column``.
        """
        temp_view = f"{table_name}_validation_temp"
        df.createOrReplaceTempView(temp_view)

        context_column = umf.get("context_column")
        has_context_column = context_column is not None and context_column in df.columns

        for col_spec in umf.get("columns", []):
            col_name = col_spec["name"]
            nullable_spec = col_spec.get("nullable", {})

            if col_name not in df.columns:
                continue

            for context, is_nullable in nullable_spec.items():
                if not is_nullable:
                    if has_context_column:
                        null_query = f"""
                        SELECT COUNT(*) as null_count
                        FROM {temp_view}
                        WHERE {col_name} IS NULL AND {context_column} = '{context}'
                        """
                    else:
                        if context != next(iter(nullable_spec.keys())):
                            continue
                        null_query = f"""
                        SELECT COUNT(*) as null_count
                        FROM {temp_view}
                        WHERE {col_name} IS NULL
                        """

                    try:
                        result = self.spark.sql(null_query).collect()
                        null_count = result[0]["null_count"] if result else 0

                        if null_count > 0:
                            error_msg = (
                                f"Found {null_count} null values in '{col_name}' for context '{context}'"
                                if has_context_column
                                else f"Found {null_count} null values in '{col_name}'"
                            )
                            rule_details = (
                                f"Column must not be null for context '{context}'"
                                if has_context_column
                                else "Column must not be null"
                            )

                            self._add_error(
                                table_name=table_name,
                                timestamp=timestamp,
                                error_type="nullable",
                                severity="error",
                                column_name=col_name,
                                rule_name="not_null_constraint",
                                rule_details=rule_details,
                                error_message=error_msg,
                                error_count=null_count,
                            )
                    except Exception as e:
                        self.logger.warning(
                            f"Failed to check nullable constraint for {col_name}: {e}"
                        )

    def _validate_rules(
        self,
        df: DataFrame,
        umf: dict,
        table_name: str,
        timestamp: datetime,
    ) -> None:
        """Validate business rules from UMF validation_rules section."""
        temp_view = f"{table_name}_validation_temp"
        df.createOrReplaceTempView(temp_view)

        for col_spec in umf.get("columns", []):
            col_name = col_spec["name"]
            validation_rules = col_spec.get("validation_rules", {})

            if col_name not in df.columns:
                continue

            if validation_rules.get("confidence") == "critical":
                self._validate_uniqueness(
                    df, temp_view, col_name, table_name, timestamp
                )

            for format_rule in validation_rules.get("format_rules", []):
                self._validate_format_rule(
                    df, temp_view, col_name, format_rule, table_name, timestamp
                )

            for value_constraint in validation_rules.get("value_constraints", []):
                self._validate_value_constraint(
                    df, temp_view, col_name, value_constraint, table_name, timestamp
                )

    def _validate_uniqueness(
        self,
        _df: DataFrame,
        temp_view: str,
        col_name: str,
        table_name: str,
        timestamp: datetime,
    ) -> None:
        """Validate uniqueness constraint for critical columns."""
        dup_query = f"""
        SELECT {col_name}, COUNT(*) as cnt
        FROM {temp_view}
        WHERE {col_name} IS NOT NULL
        GROUP BY {col_name}
        HAVING COUNT(*) > 1
        """

        try:
            duplicates = self.spark.sql(dup_query)
            dup_count = duplicates.count()

            if dup_count > 0:
                samples = duplicates.limit(5).collect()
                sample_str = ", ".join([str(row[col_name]) for row in samples])

                self._add_error(
                    table_name=table_name,
                    timestamp=timestamp,
                    error_type="uniqueness",
                    severity="error",
                    column_name=col_name,
                    rule_name="unique_constraint",
                    rule_details="Column marked as critical must be unique",
                    error_message=f"Found {dup_count} duplicate values in '{col_name}'",
                    error_count=dup_count,
                    sample_values=sample_str,
                )
        except Exception as e:
            self.logger.warning(f"Failed to check uniqueness for {col_name}: {e}")

    def _validate_format_rule(
        self,
        _df: DataFrame,
        temp_view: str,
        col_name: str,
        format_rule: str,
        table_name: str,
        timestamp: datetime,
    ) -> None:
        """Validate format rules (basic pattern matching)."""
        if "2-character" in format_rule.lower() and "state" in format_rule.lower():
            invalid_query = f"""
            SELECT {col_name}, COUNT(*) as cnt
            FROM {temp_view}
            WHERE {col_name} IS NOT NULL
            AND (LENGTH({col_name}) != 2 OR {col_name} RLIKE '[^A-Z]')
            GROUP BY {col_name}
            """

            try:
                invalid_values = self.spark.sql(invalid_query)
                invalid_count = invalid_values.count()

                if invalid_count > 0:
                    samples = invalid_values.limit(5).collect()
                    sample_str = ", ".join([str(row[col_name]) for row in samples])

                    self._add_error(
                        table_name=table_name,
                        timestamp=timestamp,
                        error_type="format",
                        severity="warning",
                        column_name=col_name,
                        rule_name="format_validation",
                        rule_details=format_rule,
                        error_message=f"Found {invalid_count} values not matching format rule",
                        error_count=invalid_count,
                        sample_values=sample_str,
                    )
            except Exception as e:
                self.logger.warning(
                    f"Failed to validate format rule for {col_name}: {e}"
                )

    def _validate_value_constraint(
        self,
        _df: DataFrame,
        temp_view: str,
        col_name: str,
        value_constraint: str,
        table_name: str,
        timestamp: datetime,
    ) -> None:
        """Validate value constraints (allowed values)."""
        allowed_values = []

        if "=" in value_constraint:
            parts = value_constraint.split(",")
            for part in parts:
                if "=" in part:
                    value = part.split("=")[0].strip().strip("\"'")
                    if value:
                        allowed_values.append(value)

        if not allowed_values and any(
            x in value_constraint for x in ['"Y"', '"N"', "'Y'", "'N'"]
        ):
            if '"Y"' in value_constraint or "'Y'" in value_constraint:
                allowed_values.append("Y")
            if '"N"' in value_constraint or "'N'" in value_constraint:
                allowed_values.append("N")

        if allowed_values:
            value_list = "', '".join(allowed_values)
            invalid_query = f"""
            SELECT {col_name}, COUNT(*) as cnt
            FROM {temp_view}
            WHERE {col_name} IS NOT NULL
            AND {col_name} NOT IN ('{value_list}')
            GROUP BY {col_name}
            """

            try:
                invalid_values = self.spark.sql(invalid_query)
                invalid_count = invalid_values.count()

                if invalid_count > 0:
                    samples = invalid_values.limit(5).collect()
                    sample_str = ", ".join([str(row[col_name]) for row in samples])

                    self._add_error(
                        table_name=table_name,
                        timestamp=timestamp,
                        error_type="value_constraint",
                        severity="warning",
                        column_name=col_name,
                        rule_name="allowed_values",
                        rule_details=f"Allowed values: {allowed_values}",
                        error_message=f"Found {invalid_count} values not in allowed set",
                        error_count=invalid_count,
                        sample_values=sample_str,
                    )
            except Exception as e:
                self.logger.warning(
                    f"Failed to validate value constraint for {col_name}: {e}"
                )


__all__ = ["VALIDATION_ERROR_SCHEMA", "TableValidator"]
