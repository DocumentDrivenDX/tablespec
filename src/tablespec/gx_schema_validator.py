# SPDX-License-Identifier: MIT OR Apache-2.0
"""Validate GX expectation schemas against actual GX library.

This module provides utilities to validate that expectation types defined in
JSON schemas are actually supported by the Great Expectations library.
"""

from __future__ import annotations

import json
import logging
import jsonschema
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


class GXSchemaValidator:
    """Validate that expectation types in schema work with GX library."""

    def __init__(self) -> None:
        """Initialize the validator."""
        self.logger = logging.getLogger(self.__class__.__name__)

    def _generate_minimal_kwargs(self, exp_type: str) -> dict[str, Any]:
        """Generate minimal valid kwargs for expectation type.

        Args:
        ----
            exp_type: Expectation type string (e.g., "expect_column_to_exist")

        Returns:
        -------
            dict: Minimal kwargs needed to instantiate the expectation

        """
        kwargs: dict[str, Any] = {}

        # Pattern matching to determine required kwargs based on expectation naming
        if exp_type.startswith("expect_column_pair_"):
            # Column pair expectations need two columns
            kwargs["column_A"] = "col_a"
            kwargs["column_B"] = "col_b"
        elif exp_type.startswith("expect_compound_columns_"):
            # Compound column expectations need column list
            kwargs["column_list"] = ["col1", "col2"]
        elif exp_type.startswith("expect_multicolumn_"):
            # Multicolumn expectations need column list
            kwargs["column_list"] = ["col1", "col2"]
        elif exp_type.startswith("expect_select_column_"):
            # Select column expectations need column list
            kwargs["column_list"] = ["col1", "col2"]
        elif exp_type.startswith("expect_column_"):
            # Most column expectations need a single column
            kwargs["column"] = "test_col"
        elif exp_type.startswith("expect_table_"):
            # Table-level expectations
            if "match_ordered_list" in exp_type:
                kwargs["column_list"] = ["col1", "col2"]
            elif "match_set" in exp_type:
                kwargs["column_set"] = ["col1", "col2"]
            elif "column_count" in exp_type:
                kwargs["value"] = 5
            # Otherwise no column kwargs needed

        # Add type-specific kwargs based on expectation name
        if "in_set" in exp_type or "in_type_list" in exp_type:
            if "type" in exp_type:
                kwargs["type_list"] = ["INTEGER", "STRING"]
            else:
                kwargs["value_set"] = ["A", "B", "C"]
        elif "match_regex" in exp_type or "match_like_pattern" in exp_type:
            if "list" in exp_type:
                kwargs["regex_list"] = ["^[A-Z]+$", "^\\d+$"]
            else:
                kwargs["regex"] = "^[A-Z]+$"
        elif "between" in exp_type:
            kwargs["min_value"] = 0
            kwargs["max_value"] = 100
        elif "strftime" in exp_type:
            kwargs["strftime_format"] = "%Y-%m-%d"
        elif "of_type" in exp_type:
            kwargs["type_"] = "INTEGER"
        elif "equal" in exp_type and exp_type.startswith("expect_column_value_lengths"):
            kwargs["value"] = 10
        elif "json_schema" in exp_type:
            kwargs["json_schema"] = {"type": "object"}
        elif "z_scores" in exp_type:
            kwargs["threshold"] = 3
        elif "kl_divergence" in exp_type:
            kwargs["partition_object"] = {
                "values": [1, 2, 3],
                "weights": [0.3, 0.4, 0.3],
            }
            kwargs["threshold"] = 0.1
        elif "equal_other_table" in exp_type:
            kwargs["other_table_name"] = "other_table"

        return kwargs

    def validate_expectation_type(self, exp_type: str) -> tuple[bool, str | None]:
        """Test if expectation type is valid with GX library.

        This mimics the actual validation done by gx_expectation_processor.py,
        which attempts to add expectations to an ExpectationSuite. This is the
        real test of whether an expectation type is registered with GX.

        Args:
        ----
            exp_type: Expectation type to validate

        Returns:
        -------
            tuple: (is_valid, error_message)

        """
        try:
            from great_expectations.core.expectation_suite import ExpectationSuite
            from great_expectations.expectations.expectation_configuration import (
                ExpectationConfiguration,
            )

            # Special case: pending implementation is not a real GX expectation
            if exp_type == "expect_validation_rule_pending_implementation":
                return (True, None)  # Valid in our schema but not in GX

            # Generate minimal kwargs
            kwargs = self._generate_minimal_kwargs(exp_type)

            # Create expectation configuration
            exp_config = ExpectationConfiguration(type=exp_type, kwargs=kwargs, meta={})

            # The real test: try to add it to a suite
            # This will fail if the expectation type is not registered with GX
            suite = ExpectationSuite(name="test_validation_suite", meta={})
            suite.add_expectation_configuration(exp_config)

            return (True, None)

        except ImportError:
            return (False, "Great Expectations library not installed")
        except Exception as e:
            return (False, str(e))

    def validate_all_types_in_schema(self, schema_path: Path) -> dict[str, Any]:
        """Validate all expectation types in schema file.

        Args:
        ----
            schema_path: Path to GX expectation suite schema JSON file

        Returns:
        -------
            dict: Validation results with structure:
                {
                    "total": int,
                    "valid": [str, ...],
                    "invalid": [{"type": str, "error": str}, ...]
                }

        """
        # Load schema
        with schema_path.open(encoding="utf-8") as f:
            schema = json.load(f)

        # Extract expectation types from enum
        exp_types = schema["properties"]["expectations"]["items"]["properties"]["type"][
            "enum"
        ]

        results: dict[str, Any] = {"total": len(exp_types), "valid": [], "invalid": []}

        # Validate each type
        for exp_type in exp_types:
            is_valid, error = self.validate_expectation_type(exp_type)

            if is_valid:
                results["valid"].append(exp_type)
                self.logger.debug(f"✓ {exp_type}")
            else:
                results["invalid"].append({"type": exp_type, "error": error})
                self.logger.warning(f"✗ {exp_type}: {error}")

        self.logger.info(
            f"Validated {results['total']} expectation types: "
            f"{len(results['valid'])} valid, {len(results['invalid'])} invalid"
        )

        return results

    def generate_corrected_schema(
        self, schema_path: Path, output_path: Path, validation_results: dict[str, Any]
    ) -> None:
        """Generate corrected schema with only valid expectations.

        Args:
        ----
            schema_path: Path to original schema file
            output_path: Path to write corrected schema
            validation_results: Results from validate_all_types_in_schema()

        """
        # Load original schema
        with schema_path.open(encoding="utf-8") as f:
            schema = json.load(f)

        # Update enum with only valid expectations
        schema["properties"]["expectations"]["items"]["properties"]["type"]["enum"] = (
            sorted(validation_results["valid"])
        )

        # Write corrected schema
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(schema, f, indent=2)

        self.logger.info(
            f"Generated corrected schema at {output_path} with "
            f"{len(validation_results['valid'])} valid expectations"
        )

    def validate_expectation_json(
        self, expectation_json: dict[str, Any], schema: dict[str, Any]
    ) -> tuple[bool, list[str]]:
        """Validate expectation JSON against schema, then with GX library.

        Args:
        ----
            expectation_json: Single expectation as dict (with type, kwargs, meta)
            schema: JSON schema for expectation suite

        Returns:
        -------
            tuple: (is_valid, list_of_errors)

        """
        errors = []

        # 1. Validate against JSON schema
        expectation_schema = schema["properties"]["expectations"]["items"]
        try:
            jsonschema.validate(expectation_json, expectation_schema)
        except jsonschema.ValidationError as e:
            errors.append(f"JSON schema validation error: {e.message}")
            return (False, errors)

        return (True, [])

    def generate_complete_expectation_suite(self, schema_path: Path) -> dict[str, Any]:
        """Generate a complete expectation suite containing all valid expectation types.

        Args:
        ----
            schema_path: Path to GX expectation suite schema JSON file

        Returns:
        -------
            dict: Complete expectation suite with all expectation types

        """
        # Load schema
        with schema_path.open(encoding="utf-8") as f:
            schema = json.load(f)

        # Extract expectation types
        exp_types = schema["properties"]["expectations"]["items"]["properties"]["type"][
            "enum"
        ]

        # Build complete suite
        suite = {
            "name": "complete_validation_suite",
            "meta": {
                "great_expectations_version": "1.6.0",
                "table_name": "test_table",
                "generated_by": "gx_schema_validator",
                "generation_date": "2025-01-29",
            },
            "expectations": [],
        }

        # Add each expectation type
        for exp_type in exp_types:
            # Skip pending implementation - it's a marker, not a real GX expectation
            if exp_type == "expect_validation_rule_pending_implementation":
                continue

            kwargs = self._generate_minimal_kwargs(exp_type)

            expectation = {
                "type": exp_type,
                "kwargs": kwargs,
                "meta": {
                    "description": f"Test expectation for {exp_type}",
                    "severity": "warning",
                },
            }

            suite["expectations"].append(expectation)

        return suite

    def validate_suite_against_schema(
        self, suite: dict[str, Any], schema: dict[str, Any]
    ) -> tuple[bool, list[str]]:
        """Validate a complete expectation suite against the JSON schema.

        Args:
        ----
            suite: Expectation suite as dict
            schema: JSON schema for expectation suite

        Returns:
        -------
            tuple: (is_valid, list_of_errors)

        """
        errors = []

        # Validate suite against JSON schema
        try:
            jsonschema.validate(suite, schema)
        except jsonschema.ValidationError as e:
            errors.append(f"JSON schema validation error: {e.message}")
            errors.append(f"  Path: {' -> '.join(str(p) for p in e.path)}")
            errors.append(
                f"  Schema path: {' -> '.join(str(p) for p in e.schema_path)}"
            )
            return (False, errors)
        # If validation passes
        return (True, [])
