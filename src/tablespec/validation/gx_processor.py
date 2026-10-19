# SPDX-License-Identifier: MIT OR Apache-2.0
"""Great Expectations Suite Processor for Phase 4.

Processes AI-generated GX expectation suites from Phase 3,
validates them against schema, converts to YAML, validates
with GX library, and stores alongside UMF files.
"""

import json
import logging
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from tablespec.gx_baseline import BaselineExpectationGenerator


class GXExpectationProcessor:
    """Process and validate Great Expectations suites from Phase 3."""

    def __init__(self, umf_dir: Path | None = None) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self.umf_dir = umf_dir
        self.baseline_generator = BaselineExpectationGenerator()

        # Load GX expectation suite schema from tablespec package
        try:
            import importlib.resources

            with (
                importlib.resources.files("tablespec.schemas")
                .joinpath("gx_expectation_suite.schema.json")
                .open() as f
            ):
                self.gx_schema = json.load(f)
        except (ImportError, FileNotFoundError, AttributeError):
            # Fallback for development environment
            try:
                from pathlib import Path

                schema_path = (
                    Path(__file__).parent.parent.parent.parent.parent.parent
                    / "tablespec"
                    / "src"
                    / "tablespec"
                    / "schemas"
                    / "gx_expectation_suite.schema.json"
                )
                if schema_path.exists():
                    with schema_path.open() as f:
                        self.gx_schema = json.load(f)
                else:
                    raise FileNotFoundError
            except (FileNotFoundError, OSError):
                self.logger.warning("GX schema not found, validation will be skipped")
                self.gx_schema = None

    def process_expectation_suite(
        self, json_file: Path, output_dir: Path
    ) -> dict[str, Any]:
        """Process a single GX expectation suite from JSON.

        Args:
        ----
            json_file: Path to JSON file containing GX expectation suite
            output_dir: Directory to save processed YAML file

        Returns:
        -------
            dict: Processing result with status and file paths

        """
        try:
            # Extract table name from filename
            # Expected format: TableName_validation_rules.json or TableName_expectations.json
            table_name = json_file.stem.replace("_validation_rules", "").replace(
                "_expectations", ""
            )

            # Load JSON
            with json_file.open(encoding="utf-8") as f:
                suite_data = json.load(f)

            # Merge with baseline expectations if UMF directory provided
            if self.umf_dir:
                suite_data = self._merge_baseline_expectations(table_name, suite_data)

            # Validate format is GX 1.6+ (reject legacy format)
            format_errors = self._validate_gx_format(suite_data)
            if format_errors:
                self.logger.error(
                    f"File {json_file} uses legacy GX format. Please update to GX 1.6+:\n  "
                    + "\n  ".join(format_errors)
                )
                return {
                    "status": "failed",
                    "reason": "invalid_gx_format",
                    "errors": format_errors,
                    "file": str(json_file),
                }

            # Validate against schema if available
            if self.gx_schema:
                try:
                    jsonschema.validate(suite_data, self.gx_schema)
                    self.logger.debug(f"Validation passed for {table_name}")
                except jsonschema.ValidationError as e:
                    self.logger.exception(
                        f"Schema validation failed for {table_name}: {e}"
                    )
                    return {
                        "status": "failed",
                        "reason": "schema_validation_failed",
                        "error": str(e),
                        "file": str(json_file),
                    }

            # Ensure expectation suite name matches table (GX 1.6+ uses 'name')
            if "name" not in suite_data:
                suite_data["name"] = f"{table_name}_suite"

            # Save as YAML alongside UMF
            yaml_path = output_dir / "tables" / f"{table_name}.expectations.yaml"
            yaml_path.parent.mkdir(parents=True, exist_ok=True)

            with yaml_path.open("w", encoding="utf-8") as f:
                yaml.dump(suite_data, f, default_flow_style=False, sort_keys=False)

            self.logger.info(f"Processed GX suite for {table_name} → {yaml_path.name}")

            return {
                "status": "success",
                "table_name": table_name,
                "json_file": str(json_file),
                "yaml_file": str(yaml_path),
                "num_expectations": len(suite_data.get("expectations", [])),
            }

        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
            self.logger.exception(f"Failed to process {json_file}: {e}")
            return {
                "status": "failed",
                "reason": "processing_error",
                "error": str(e),
                "file": str(json_file),
            }

    def _validate_gx_format(self, data: dict) -> list[str]:
        """Validate that data is in Great Expectations 1.6+ format.

        Args:
        ----
            data: Dictionary to check

        Returns:
        -------
            list[str]: List of format errors (empty if valid)

        """
        errors = []

        # Check for required top-level fields (GX 1.6+)
        if "name" not in data:
            if "expectation_suite_name" in data:
                errors.append(
                    "Legacy format: rename 'expectation_suite_name' to 'name'"
                )
            else:
                errors.append("Missing required field 'name' (suite name)")

        # Reject legacy field if present
        if "data_asset_type" in data:
            errors.append("Legacy field 'data_asset_type' not supported (remove it)")

        # Check expectations array
        if "expectations" not in data:
            errors.append("Missing required field 'expectations'")
        elif not isinstance(data["expectations"], list):
            errors.append("Field 'expectations' must be an array")
        elif data["expectations"]:
            # Check first expectation structure
            first_exp = data["expectations"][0]
            if not isinstance(first_exp, dict):
                errors.append("Expectations must be objects")
            else:
                # Check for required expectation fields (GX 1.6+)
                if "type" not in first_exp:
                    if "expectation_type" in first_exp:
                        errors.append(
                            "Legacy format: rename 'expectation_type' to 'type' in expectations"
                        )
                    else:
                        errors.append("Expectation missing required field 'type'")

                if "kwargs" not in first_exp:
                    errors.append("Expectation missing required field 'kwargs'")

                # Check for invalid severity values
                if "meta" in first_exp and "severity" in first_exp["meta"]:
                    severity = first_exp["meta"]["severity"]
                    if severity not in ["critical", "warning", "info"]:
                        errors.append(
                            f"Invalid severity '{severity}' (use: critical, warning, or info)"
                        )

        return errors

    def _merge_baseline_expectations(
        self, table_name: str, ai_suite_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Merge baseline structural expectations with AI-generated expectations.

        Args:
        ----
            table_name: Name of the table
            ai_suite_data: AI-generated expectation suite data

        Returns:
        -------
            dict: Merged suite data with baseline + AI expectations

        """
        try:
            # Check if umf_dir is configured
            if self.umf_dir is None:
                self.logger.warning(
                    f"UMF directory not configured, skipping baseline generation for {table_name}"
                )
                return ai_suite_data

            # Find UMF file for this table
            umf_file = self.umf_dir / f"{table_name}.specs.umf.yaml"
            if not umf_file.exists():
                # Try alternative naming patterns
                umf_file = self.umf_dir / f"{table_name}.umf.yaml"
                if not umf_file.exists():
                    self.logger.warning(
                        f"UMF file not found for {table_name}, skipping baseline generation"
                    )
                    return ai_suite_data

            # Load UMF data
            with umf_file.open(encoding="utf-8") as f:
                umf_data = yaml.safe_load(f)

            # Generate baseline expectations
            baseline_expectations = (
                self.baseline_generator.generate_baseline_expectations(
                    umf_data, include_structural=True
                )
            )

            if not baseline_expectations:
                self.logger.debug(
                    f"No baseline expectations generated for {table_name}"
                )
                return ai_suite_data

            # Get AI expectations
            ai_expectations = ai_suite_data.get("expectations", [])

            # Create a set of AI expectation signatures to avoid duplicates
            ai_signatures = set()
            for exp in ai_expectations:
                # Create signature from type + column (if present)
                exp_type = exp.get("type", "")
                column = exp.get("kwargs", {}).get("column")
                if column:
                    ai_signatures.add(f"{exp_type}:{column}")
                else:
                    # For multi-column or table-level expectations, use full kwargs
                    kwargs_str = json.dumps(exp.get("kwargs", {}), sort_keys=True)
                    ai_signatures.add(f"{exp_type}:{kwargs_str}")

            # Filter baseline expectations to avoid duplicates
            unique_baseline = []
            for exp in baseline_expectations:
                exp_type = exp.get("type", "")
                column = exp.get("kwargs", {}).get("column")
                if column:
                    signature = f"{exp_type}:{column}"
                else:
                    kwargs_str = json.dumps(exp.get("kwargs", {}), sort_keys=True)
                    signature = f"{exp_type}:{kwargs_str}"

                if signature not in ai_signatures:
                    unique_baseline.append(exp)

            # Merge: baseline first, then AI expectations
            merged_expectations = unique_baseline + ai_expectations

            self.logger.info(
                f"{table_name}: Merged {len(unique_baseline)} baseline + "
                f"{len(ai_expectations)} AI = {len(merged_expectations)} total expectations"
            )

            # Update suite data
            ai_suite_data["expectations"] = merged_expectations
            return ai_suite_data

        except Exception as e:
            self.logger.exception(
                f"Failed to merge baseline expectations for {table_name}: {e}"
            )
            return ai_suite_data

    def process_all_suites(self, input_dir: Path, output_dir: Path) -> dict[str, Any]:
        """Process all GX expectation suites in a directory.

        Args:
        ----
            input_dir: Directory containing JSON expectation suites
            output_dir: Directory to save processed YAML files

        Returns:
        -------
            dict: Summary of processing results

        """
        results = {
            "total_files": 0,
            "successful": 0,
            "failed": 0,
            "skipped": 0,
            "files": [],
        }

        # Look for expectation JSON files
        patterns = [
            "*_validation_rules.json",
            "*_expectations.json",
            "*.expectations.json",
        ]
        json_files = []
        for pattern in patterns:
            json_files.extend(input_dir.glob(pattern))

        results["total_files"] = len(json_files)

        if not json_files:
            self.logger.warning(f"No expectation files found in {input_dir}")
            return results

        for json_file in json_files:
            result = self.process_expectation_suite(json_file, output_dir)
            results["files"].append(result)

            if result["status"] == "success":
                results["successful"] += 1
            elif result["status"] == "failed":
                results["failed"] += 1
            else:
                results["skipped"] += 1

        self.logger.info(
            f"Processed {results['successful']}/{results['total_files']} GX suites successfully"
        )

        return results

    def update_umf_with_expectations(
        self, umf_file: Path, expectations_file: Path
    ) -> bool:
        """Update UMF file with reference to expectations file.

        Args:
        ----
            umf_file: Path to UMF YAML file
            expectations_file: Path to expectations YAML file

        Returns:
        -------
            bool: True if update successful

        """
        try:
            # Load UMF
            with umf_file.open(encoding="utf-8") as f:
                umf_data = yaml.safe_load(f)

            # Add validation section if not present
            if "validation" not in umf_data:
                umf_data["validation"] = {}

            # Update expectations reference
            umf_data["validation"]["expectation_suite"] = expectations_file.name

            # Save updated UMF
            with umf_file.open("w", encoding="utf-8") as f:
                yaml.dump(umf_data, f, default_flow_style=False, sort_keys=False)

            self.logger.debug(f"Updated {umf_file.name} with expectations reference")
            return True

        except Exception as e:
            self.logger.exception(f"Failed to update UMF {umf_file}: {e}")
            return False

    def validate_gx_suite(self, suite_file: Path) -> tuple[bool, list[str]]:
        """Validate a GX expectation suite file.

        Args:
        ----
            suite_file: Path to YAML file containing GX expectation suite

        Returns:
        -------
            tuple: (success: bool, errors: list[str])

        """
        errors = []

        try:
            # Load YAML
            with suite_file.open(encoding="utf-8") as f:
                suite_dict = yaml.safe_load(f)

            # Schema validation if available
            if self.gx_schema:
                try:
                    jsonschema.validate(suite_dict, self.gx_schema)
                except jsonschema.ValidationError as e:
                    errors.append(f"Schema validation error: {e.message}")

            # Try to load with actual GX library
            try:
                from great_expectations.core.expectation_suite import ExpectationSuite
                from great_expectations.expectations.expectation_configuration import (
                    ExpectationConfiguration,
                )

                # Create ExpectationSuite object (GX 1.6+ API)
                suite = ExpectationSuite(
                    name=suite_dict.get("name", "default"),
                    meta=suite_dict.get("meta", {}),
                )

                # Add expectations (GX 1.6+ API)
                # Skip pending implementation expectations as they're not real GX expectations
                for exp_dict in suite_dict.get("expectations", []):
                    exp_type = exp_dict.get("type")

                    # Special handling for pending implementation expectations
                    if exp_type == "expect_validation_rule_pending_implementation":
                        # Validate structure without adding to GX suite
                        # These are markers for future human implementation, so just require description
                        if "meta" not in exp_dict:
                            errors.append(
                                "Pending expectation missing required 'meta' field"
                            )
                        elif "description" not in exp_dict["meta"]:
                            errors.append(
                                "Pending expectation missing required meta.description field"
                            )
                        continue  # Don't add to GX suite

                    # Normal GX expectations
                    try:
                        exp_config = ExpectationConfiguration(
                            type=exp_type,
                            kwargs=exp_dict.get("kwargs", {}),
                            meta=exp_dict.get("meta", {}),
                        )
                        suite.add_expectation_configuration(exp_config)
                    except Exception as e:
                        errors.append(
                            f"Invalid expectation: {exp_type or 'unknown'} - {e}"
                        )

            except ImportError:
                self.logger.warning(
                    "Great Expectations library not available, skipping GX validation"
                )
            except Exception as e:
                errors.append(f"Failed to load with GX library: {e}")

            return (len(errors) == 0, errors)

        except (OSError, UnicodeDecodeError, yaml.YAMLError) as e:
            return (False, [f"Failed to load suite file: {e}"])

    def validate_all_suites(self, directory: Path) -> dict[str, Any]:
        """Validate all GX expectation suites in a directory.

        Args:
        ----
            directory: Directory containing expectation YAML files

        Returns:
        -------
            dict: Validation results summary

        """
        results = {"total_files": 0, "valid": 0, "invalid": 0, "validation_errors": {}}

        # Find all expectation YAML files
        yaml_files = list(directory.glob("*.expectations.yaml"))
        results["total_files"] = len(yaml_files)

        for yaml_file in yaml_files:
            success, errors = self.validate_gx_suite(yaml_file)

            if success:
                results["valid"] += 1
                self.logger.info(f"✓ Validated {yaml_file.name}")
            else:
                results["invalid"] += 1
                results["validation_errors"][yaml_file.name] = errors
                self.logger.error(f"✗ Validation failed for {yaml_file.name}:")
                for error in errors:
                    self.logger.error(f"  - {error}")

        return results
