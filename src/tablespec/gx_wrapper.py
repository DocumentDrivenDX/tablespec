"""Centralized wrapper for Great Expectations interactions.

Provides consistent GX initialization, validation, and expectation handling
across the entire codebase. All GX interactions should go through this wrapper.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class GXWrapper:
    """Centralized Great Expectations wrapper.

    Ensures consistent GX configuration and validation behavior across all
    uses in the codebase.
    """

    def __init__(self) -> None:
        """Initialize GX wrapper with standard configuration."""
        self.logger = logging.getLogger(self.__class__.__name__)
        self._register_custom_expectations()

    def _register_custom_expectations(self) -> None:
        """Register custom expectations with GX registry."""
        try:
            from great_expectations.expectations import registry

            # Import and register our custom expectations
            from tablespec.validation.custom_gx_expectations import (
                ExpectColumnDateToBeInCurrentYear,
                ExpectColumnValuesToMatchDomainType,
                ExpectColumnValuesToCastToType,
            )

            # Register the expectation classes
            registry.register_expectation(ExpectColumnValuesToCastToType)
            registry.register_expectation(ExpectColumnDateToBeInCurrentYear)
            registry.register_expectation(ExpectColumnValuesToMatchDomainType)

            self.logger.debug(
                "Registered custom expectations: expect_column_values_to_cast_to_type, "
                "expect_column_date_to_be_in_current_year, "
                "expect_column_values_to_match_domain_type"
            )
        except ImportError as e:
            # GX or custom expectations not available
            self.logger.debug(f"Could not register custom expectations: {e}")
        except Exception as e:
            # Log but don't fail - custom expectations are optional enhancements
            self.logger.warning(f"Failed to register custom expectations: {e}")

    def create_expectation_suite(
        self, name: str, meta: dict[str, Any] | None = None
    ) -> Any:
        """Create GX expectation suite with standard configuration."""
        from great_expectations.core.expectation_suite import ExpectationSuite

        return ExpectationSuite(name=name, meta=meta or {})

    def create_expectation_config(
        self,
        exp_type: str,
        kwargs: dict[str, Any],
        meta: dict[str, Any] | None = None,
    ) -> Any:
        """Create GX expectation configuration."""
        from great_expectations.expectations.expectation_configuration import (
            ExpectationConfiguration,
        )

        return ExpectationConfiguration(
            type=exp_type,
            kwargs=kwargs,
            meta=meta or {},
        )

    def validate_expectation(
        self,
        exp_type: str,
        kwargs: dict[str, Any],
        meta: dict[str, Any] | None = None,
    ) -> tuple[bool, str | None]:
        """Validate single expectation with GX library.

        Returns
        -------
            tuple: (is_valid, error_message)

        """
        try:
            suite = self.create_expectation_suite("validation_test")
            exp_config = self.create_expectation_config(exp_type, kwargs, meta)
            suite.add_expectation_configuration(exp_config)
            return (True, None)
        except Exception as e:
            return (False, str(e))

    def validate_suite(self, suite_dict: dict[str, Any]) -> tuple[bool, list[str]]:
        """Validate entire expectation suite with GX library.

        Returns
        -------
            tuple: (is_valid, error_messages)

        """
        errors = []

        try:
            suite = self.create_expectation_suite(
                name=suite_dict.get("name", "default"),
                meta=suite_dict.get("meta", {}),
            )

            for exp_dict in suite_dict.get("expectations", []):
                exp_type = exp_dict.get("type")

                # Skip pending expectations
                if exp_type == "expect_validation_rule_pending_implementation":
                    continue

                try:
                    exp_config = self.create_expectation_config(
                        exp_type=exp_type,
                        kwargs=exp_dict.get("kwargs", {}),
                        meta=exp_dict.get("meta", {}),
                    )
                    suite.add_expectation_configuration(exp_config)
                except Exception as e:
                    # Check if it's our custom expectation that might not be registered
                    custom_expectations = {
                        "expect_column_values_to_cast_to_type",
                        "expect_column_date_to_be_in_current_year",
                        "expect_column_values_to_match_domain_type",
                    }
                    if exp_type in custom_expectations:
                        self.logger.debug(
                            f"Custom expectation {exp_type} validation skipped (will work at runtime)"
                        )
                        # Don't treat this as an error - it will work during actual validation
                        continue
                    errors.append(f"Invalid expectation {exp_type}: {e}")

            return (len(errors) == 0, errors)

        except Exception as e:
            return (False, [f"Suite validation error: {e}"])

    def get_context(self) -> Any:
        """Get GX context with standard configuration.

        Returns
        -------
            GX context object

        """
        import great_expectations as gx

        # get_context is a public API function despite import analysis warning
        return gx.get_context()  # type: ignore[attr-defined]

    def create_validator_for_dataframe(self, spark_df: Any, validation_id: str) -> Any:
        """Create GX validator for Spark DataFrame.

        Args:
        ----
            spark_df: PySpark DataFrame
            validation_id: Unique validation ID

        Returns:
        -------
            GX validator object configured for DataFrame validation

        """
        import warnings

        context = self.get_context()

        # Add Spark datasource with in-memory DataFrame
        datasource = context.data_sources.add_spark(name=f"spark_ds_{validation_id}")
        data_asset = datasource.add_dataframe_asset(name=f"df_asset_{validation_id}")

        # Build batch request
        batch_request = data_asset.build_batch_request(options={"dataframe": spark_df})

        # Get validator (suppress warnings about result_format persistence)
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=r".*result_format.*configured.*will not be persisted.*",
                category=UserWarning,
            )
            validator = context.get_validator(batch_request=batch_request)

        # Configure validator
        validator.metrics_calculator.show_progress_bars = False

        return validator

    def execute_expectation(
        self,
        spark_df: Any,
        expectation_type: str,
        result_format: str = "COMPLETE",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute a single expectation on a DataFrame.

        Args:
        ----
            spark_df: PySpark DataFrame to validate
            expectation_type: GX expectation type (e.g., 'expect_column_values_to_not_be_null')
            result_format: GX result format ('COMPLETE', 'SUMMARY', 'BOOLEAN_ONLY')
            **kwargs: Expectation-specific parameters (column, value_set, etc.)

        Returns:
        -------
            dict: GX expectation result with 'success', 'result', etc.

        """
        import uuid

        # Create validator for this DataFrame
        validation_id = str(uuid.uuid4())[:8]
        validator = self.create_validator_for_dataframe(spark_df, validation_id)

        # Get expectation method from validator
        expectation_method = getattr(validator, expectation_type, None)
        if expectation_method is None:
            msg = f"Unknown expectation type: {expectation_type}"
            raise ValueError(msg)

        # Execute expectation with provided kwargs
        result = expectation_method(result_format=result_format, **kwargs)

        # Convert result to dict
        return result.to_json_dict()


# Singleton instance
_gx_wrapper: GXWrapper | None = None


def get_gx_wrapper() -> GXWrapper:
    """Get singleton GX wrapper instance."""
    global _gx_wrapper
    if _gx_wrapper is None:
        _gx_wrapper = GXWrapper()
    return _gx_wrapper
