"""UMF Validation Module

Provides validation for Universal Metadata Format (UMF) files using JSON Schema.
Ensures UMF files conform to the expected structure and constraints.
"""

import json
import logging
from pathlib import Path
from typing import Any

import jsonschema
import yaml
from jsonschema import ValidationError


class UMFValidationError(Exception):
    """Custom exception for UMF validation errors."""

    def __init__(self, message: str, errors: list[str] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or []


class UMFValidator:
    """Validates UMF files against the JSON Schema."""

    def __init__(self, schema_path: Path | None = None) -> None:
        """Initialize validator with schema.

        Args:
        ----
            schema_path: Path to UMF JSON Schema file. If None, uses
                Pydantic-generated schema from the UMF model.

        """
        self.logger = logging.getLogger(self.__class__.__name__)

        # Load schema
        if schema_path is not None:
            if not schema_path.exists():
                msg = f"UMF schema file not found: {schema_path}"
                raise FileNotFoundError(msg)

            with schema_path.open(encoding="utf-8") as f:
                self.schema = json.load(f)

            self.logger.info(f"UMF validator initialized with schema: {schema_path}")
        else:
            from tablespec.models.umf import UMF

            self.schema = UMF.model_json_schema()
            self.logger.info("UMF validator initialized with Pydantic-generated schema")

        # Create validator
        self.validator = jsonschema.Draft7Validator(self.schema)

    def validate_file(self, umf_file_path: Path, raise_on_error: bool = True) -> bool:
        """Validate a UMF file.

        Args:
        ----
            umf_file_path: Path to UMF YAML file
            raise_on_error: Whether to raise exception on validation errors

        Returns:
        -------
            True if valid, False if invalid (when raise_on_error=False)

        Raises:
        ------
            UMFValidationError: If validation fails and raise_on_error=True
            FileNotFoundError: If file doesn't exist

        """
        if not umf_file_path.exists():
            msg = f"UMF file not found: {umf_file_path}"
            raise FileNotFoundError(msg)

        try:
            with umf_file_path.open(encoding="utf-8") as f:
                umf_data = yaml.safe_load(f)

            return self.validate_data(umf_data, raise_on_error, str(umf_file_path))

        except yaml.YAMLError as e:
            error_msg = f"Invalid YAML in {umf_file_path}: {e}"
            if raise_on_error:
                raise UMFValidationError(error_msg) from e
            self.logger.exception(error_msg)
            return False

    def validate_data(
        self,
        umf_data: dict[str, Any],
        raise_on_error: bool = True,
        source_name: str = "UMF data",
    ) -> bool:
        """Validate UMF data dictionary.

        Args:
        ----
            umf_data: UMF data as dictionary
            raise_on_error: Whether to raise exception on validation errors
            source_name: Name/path for error messages

        Returns:
        -------
            True if valid, False if invalid (when raise_on_error=False)

        Raises:
        ------
            UMFValidationError: If validation fails and raise_on_error=True

        """
        try:
            # Validate against schema
            self.validator.validate(umf_data)

            # Additional business logic validation
            self._validate_business_rules(umf_data)

            self.logger.debug(f"UMF validation passed for {source_name}")
            return True

        except ValidationError as e:
            error_msg = f"Schema validation failed for {source_name}: {e.message}"
            if e.absolute_path:
                error_msg += f" at path: {'.'.join(str(p) for p in e.absolute_path)}"

            if raise_on_error:
                raise UMFValidationError(error_msg, [error_msg]) from e
            self.logger.exception(error_msg)
            return False

        except Exception as e:
            error_msg = f"Validation error for {source_name}: {e}"
            if raise_on_error:
                raise UMFValidationError(error_msg) from e
            self.logger.exception(error_msg)
            return False

    def validate_directory(
        self,
        directory_path: Path,
        pattern: str = "*.umf.yaml",
        raise_on_error: bool = False,
    ) -> dict[str, bool]:
        """Validate all UMF files in a directory.

        Args:
        ----
            directory_path: Directory containing UMF files
            pattern: File pattern to match (default: *.umf.yaml)
            raise_on_error: Whether to raise exception on any validation errors

        Returns:
        -------
            Dictionary mapping file paths to validation results

        Raises:
        ------
            UMFValidationError: If any validation fails and raise_on_error=True

        """
        if not directory_path.exists() or not directory_path.is_dir():
            msg = f"Directory not found: {directory_path}"
            raise ValueError(msg)

        umf_files = list(directory_path.glob(pattern))
        if not umf_files:
            self.logger.warning(
                f"No UMF files found in {directory_path} with pattern {pattern}"
            )
            return {}

        results = {}
        errors = []

        for umf_file in umf_files:
            try:
                is_valid = self.validate_file(umf_file, raise_on_error=False)
                results[str(umf_file)] = is_valid
                if not is_valid:
                    errors.append(f"Validation failed for {umf_file}")
            except Exception as e:
                results[str(umf_file)] = False
                errors.append(f"Error validating {umf_file}: {e}")

        if errors and raise_on_error:
            msg = f"UMF validation errors in {directory_path}"
            raise UMFValidationError(msg, errors)

        valid_count = sum(1 for v in results.values() if v)
        total_count = len(results)

        self.logger.info(
            f"UMF validation results: {valid_count}/{total_count} files valid in {directory_path}"
        )

        return results

    def apply_default_specifications(self, umf_data: dict[str, Any]) -> dict[str, Any]:
        """Apply default specifications to columns missing them.

        Args:
        ----
            umf_data: UMF data as dictionary

        Returns:
        -------
            Modified UMF data with defaults applied

        """
        # Default values
        default_varchar_length = 255
        default_decimal_precision = 18
        default_decimal_scale = 2

        # Apply defaults to columns
        for column in umf_data.get("columns", []):
            data_type = column.get("data_type")

            # Apply VARCHAR defaults
            if data_type == "VARCHAR" and "length" not in column:
                column["length"] = default_varchar_length
                self.logger.debug(
                    f"Applied default length {default_varchar_length} to VARCHAR column '{column.get('name')}'"
                )

            # Apply DECIMAL defaults
            if data_type == "DECIMAL":
                if "precision" not in column:
                    column["precision"] = default_decimal_precision
                    self.logger.debug(
                        f"Applied default precision {default_decimal_precision} to DECIMAL column '{column.get('name')}'"
                    )
                if "scale" not in column:
                    column["scale"] = default_decimal_scale
                    self.logger.debug(
                        f"Applied default scale {default_decimal_scale} to DECIMAL column '{column.get('name')}'"
                    )

        return umf_data

    def fix_duplicate_column_names(self, umf_data: dict[str, Any]) -> dict[str, Any]:
        """Fix duplicate column names by appending suffixes.

        Args:
        ----
            umf_data: UMF data as dictionary

        Returns:
        -------
            Modified UMF data with unique column names

        """
        if "columns" not in umf_data:
            return umf_data

        seen_names = {}
        for column in umf_data["columns"]:
            original_name = column.get("name", "")
            if original_name in seen_names:
                # Increment counter for this name
                seen_names[original_name] += 1
                # Append suffix to make unique
                new_name = f"{original_name}_{seen_names[original_name]}"
                column["name"] = new_name
                # Store original name if not already present
                if "original_name" not in column:
                    column["original_name"] = original_name
                self.logger.debug(
                    f"Renamed duplicate column '{original_name}' to '{new_name}'"
                )
            else:
                seen_names[original_name] = 1

        return umf_data

    def get_validation_errors(self, umf_data: dict[str, Any]) -> list[str]:
        """Get list of validation errors without raising exceptions.

        Args:
        ----
            umf_data: UMF data as dictionary

        Returns:
        -------
            List of error messages (empty if valid)

        """
        errors = []

        # Schema validation errors
        for error in self.validator.iter_errors(umf_data):
            error_msg = f"Schema error: {error.message}"
            if error.absolute_path:
                error_msg += (
                    f" at path: {'.'.join(str(p) for p in error.absolute_path)}"
                )
            errors.append(error_msg)

        # Business rule validation errors
        try:
            self._validate_business_rules(umf_data)
        except Exception as e:
            errors.append(f"Business rule error: {e}")

        # Expectation type validation
        errors.extend(self._validate_expectation_types(umf_data))

        return errors

    def _validate_expectation_types(self, umf_data: dict[str, Any]) -> list[str]:
        """Check that expectation types in validation_rules are recognized.

        Args:
        ----
            umf_data: UMF data as dictionary

        Returns:
        -------
            List of error messages for unknown expectation types

        """
        from tablespec.models.umf import (
            INGESTED_QUALITY_CHECK_TYPES,
            RAW_VALIDATION_TYPES,
            REDUNDANT_VALIDATION_TYPES,
        )
        from tablespec.expectation_migration import ensure_expectation_suite_data

        known_types = (
            RAW_VALIDATION_TYPES
            | INGESTED_QUALITY_CHECK_TYPES
            | REDUNDANT_VALIDATION_TYPES
        )
        errors = []

        suite_data = ensure_expectation_suite_data(umf_data)
        for exp in suite_data.get("expectations", []):
            exp_type = exp.get("type", exp.get("expectation_type", ""))
            if exp_type and exp_type not in known_types:
                errors.append(f"Unknown expectation type '{exp_type}' in expectations.")

        for exp in suite_data.get("pending", []):
            exp_type = exp.get("type", exp.get("expectation_type", ""))
            if exp_type and exp_type not in known_types:
                errors.append(
                    f"Unknown expectation type '{exp_type}' in expectations.pending."
                )
        return errors

    def _validate_business_rules(self, umf_data: dict[str, Any]) -> None:
        """Validate business-specific rules not covered by JSON Schema.

        Args:
        ----
            umf_data: UMF data as dictionary

        Raises:
        ------
            ValueError: If business rules are violated

        """
        # Validate column names are unique
        if "columns" in umf_data:
            column_names = [col.get("name") for col in umf_data["columns"]]
            if len(column_names) != len(set(column_names)):
                msg = "Column names must be unique"
                raise ValueError(msg)

        # Validate data type constraints
        for column in umf_data.get("columns", []):
            data_type = column.get("data_type")

            # VARCHAR columns should have length
            if data_type == "VARCHAR" and "length" not in column:
                self.logger.warning(
                    f"VARCHAR column '{column.get('name')}' missing length specification"
                )

            # DECIMAL columns should have precision/scale
            if data_type == "DECIMAL" and "precision" not in column:
                self.logger.warning(
                    f"DECIMAL column '{column.get('name')}' missing precision specification"
                )

        # Validate version format
        version = umf_data.get("version", "")
        if version and not version.replace(".", "").isdigit():
            msg = f"Invalid version format: {version}"
            raise ValueError(msg)


def validate_umf_file(file_path: str | Path, schema_path: Path | None = None) -> bool:
    """Validate a single UMF file.

    Args:
    ----
        file_path: Path to UMF file
        schema_path: Optional path to schema file

    Returns:
    -------
        True if valid, False otherwise

    """
    validator = UMFValidator(schema_path)
    return validator.validate_file(Path(file_path), raise_on_error=False)


def validate_umf_directory(
    directory_path: str | Path, schema_path: Path | None = None
) -> dict[str, bool]:
    """Validate all UMF files in a directory.

    Args:
    ----
        directory_path: Path to directory containing UMF files
        schema_path: Optional path to schema file

    Returns:
    -------
        Dictionary mapping file paths to validation results

    """
    validator = UMFValidator(schema_path)
    return validator.validate_directory(Path(directory_path))
