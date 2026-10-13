"""Unit tests for completeness_validator module."""

from tablespec.completeness_validator import (
    REQUIRED_BASELINE_TYPES,
    REQUIRED_PROVENANCE_COLUMNS,
    validate_baseline_expectations,
    validate_domain_types,
    validate_provenance_columns,
)
from tablespec.models import UMF, UMFColumn, ValidationRule, ValidationRules


class TestValidateProvenanceColumns:
    """Tests for validate_provenance_columns function."""

    def _create_umf_with_columns(self, column_names: list[str]) -> UMF:
        """Helper to create UMF with given column names."""
        columns = [UMFColumn(name=name, data_type="VARCHAR") for name in column_names]
        return UMF(
            table_name="test_table",
            canonical_name="test_table",
            description="Test table",
            version="1.0",
            columns=columns,
        )

    def test_all_provenance_columns_present(self):
        """Test validation passes when all 8 provenance columns are present."""
        columns = [*list(REQUIRED_PROVENANCE_COLUMNS), "business_col"]
        umf = self._create_umf_with_columns(columns)

        errors = validate_provenance_columns(umf)

        assert errors == []

    def test_one_provenance_column_missing(self):
        """Test validation fails when one provenance column is missing."""
        columns = list(REQUIRED_PROVENANCE_COLUMNS)
        columns.remove("meta_source_name")
        columns.append("business_col")
        umf = self._create_umf_with_columns(columns)

        errors = validate_provenance_columns(umf)

        assert len(errors) == 1
        assert errors[0][0] == "meta_source_name"
        assert "Missing required provenance column" in errors[0][1]

    def test_all_provenance_columns_missing(self):
        """Test validation fails when all provenance columns are missing."""
        umf = self._create_umf_with_columns(["business_col_1", "business_col_2"])

        errors = validate_provenance_columns(umf)

        assert len(errors) == 8
        missing_cols = {err[0] for err in errors}
        assert missing_cols == REQUIRED_PROVENANCE_COLUMNS

    def test_only_one_business_column(self):
        """Test validation fails when only business column exists (no provenance)."""
        umf = self._create_umf_with_columns(["business_col"])

        errors = validate_provenance_columns(umf)

        assert len(errors) == 8


class TestValidateDomainTypes:
    """Tests for validate_domain_types function."""

    def _create_umf_with_domain_types(
        self, columns: list[tuple[str, str | None]]
    ) -> UMF:
        """Helper to create UMF with columns and domain types.

        Args:
            columns: List of (column_name, domain_type) tuples

        """
        umf_columns = []
        for col_name, domain_type in columns:
            col = UMFColumn(name=col_name, data_type="VARCHAR")
            if domain_type:
                col.domain_type = domain_type
            umf_columns.append(col)

        return UMF(
            table_name="test_table",
            canonical_name="test_table",
            description="Test table",
            version="1.0",
            columns=umf_columns,
        )

    def test_valid_domain_types(self):
        """Test validation passes for valid domain types."""
        umf = self._create_umf_with_domain_types(
            [
                ("state_code", "us_state_code"),
                ("email_address", "email"),
                ("member_id", "member_id"),
            ]
        )

        errors = validate_domain_types(umf)

        assert errors == []

    def test_invalid_domain_type(self):
        """Test validation fails for invalid domain type."""
        umf = self._create_umf_with_domain_types(
            [
                ("state_code", "us_state_code"),
                ("bad_col", "nonexistent_domain_type"),
            ]
        )

        errors = validate_domain_types(umf)

        assert len(errors) == 1
        assert errors[0][0] == "bad_col"
        assert "nonexistent_domain_type" in errors[0][1]

    def test_column_without_domain_type(self):
        """Test validation passes for columns without domain_type (optional field)."""
        umf = self._create_umf_with_domain_types(
            [
                ("col_with_domain", "us_state_code"),
                ("col_without_domain", None),
            ]
        )

        errors = validate_domain_types(umf)

        assert errors == []

    def test_multiple_invalid_domain_types(self):
        """Test validation reports all invalid domain types."""
        umf = self._create_umf_with_domain_types(
            [
                ("col1", "invalid_type_1"),
                ("col2", "invalid_type_2"),
                ("col3", "us_state_code"),  # Valid
            ]
        )

        errors = validate_domain_types(umf)

        assert len(errors) == 2
        error_cols = {err[0] for err in errors}
        assert error_cols == {"col1", "col2"}


class TestValidateBaselineExpectations:
    """Tests for validate_baseline_expectations function."""

    def _create_umf_with_validations(
        self,
        columns: list[str],
        column_level: dict[str, list[ValidationRule]] | None = None,
    ) -> UMF:
        """Helper to create UMF with columns and validations."""
        umf_columns = [UMFColumn(name=name, data_type="VARCHAR") for name in columns]

        validation_rules = None
        if column_level is not None:
            validation_rules = ValidationRules(column_level=column_level)

        return UMF(
            table_name="test_table",
            canonical_name="test_table",
            description="Test table",
            version="1.0",
            columns=umf_columns,
            validation_rules=validation_rules,
        )

    def _rule(self, rule_type: str) -> ValidationRule:
        """Create a ValidationRule with given type."""
        return ValidationRule(
            rule_type=rule_type, description=f"{rule_type} check", severity="error"
        )

    def test_all_baseline_validations_present(self):
        """Test validation passes when baseline validations exist.

        Note: REQUIRED_BASELINE_TYPES is now empty since expect_column_to_exist
        and expect_column_values_to_be_of_type are both redundant with schema metadata.
        """
        column_level = {
            "col1": [self._rule("expect_column_values_to_cast_to_type")],
        }
        umf = self._create_umf_with_validations(["col1"], column_level)

        errors = validate_baseline_expectations(umf)

        assert errors == []

    def test_no_required_baseline_types(self):
        """Test validation passes even without expect_column_to_exist.

        Both expect_column_to_exist and expect_column_values_to_be_of_type are
        now classified as REDUNDANT_VALIDATION_TYPES, so no baseline types are required.
        """
        column_level = {
            "col1": [self._rule("expect_column_values_to_cast_to_type")],
        }
        umf = self._create_umf_with_validations(["col1"], column_level)

        errors = validate_baseline_expectations(umf)

        assert errors == []

    def test_no_validations_passes_with_empty_required_set(self):
        """Test validation passes when no validations exist (no required types)."""
        umf = self._create_umf_with_validations(["col1"], None)

        errors = validate_baseline_expectations(umf)

        # No required baseline types, so no errors
        assert errors == []

    def test_multiple_columns_no_required_types(self):
        """Test validation passes for all columns with no required baseline types."""
        umf = self._create_umf_with_validations(["col1", "col2"], None)

        errors = validate_baseline_expectations(umf)

        # No required baseline types, so no errors
        assert errors == []

    def test_partial_validations_per_column(self):
        """Test validation passes for all columns regardless of which validations exist."""
        column_level = {
            "col1": [self._rule("expect_column_values_to_cast_to_type")],
            "col2": [self._rule("expect_column_values_to_cast_to_type")],
        }
        umf = self._create_umf_with_validations(["col1", "col2"], column_level)

        errors = validate_baseline_expectations(umf)

        assert errors == []


class TestConstants:
    """Tests for module constants."""

    def test_required_provenance_columns_count(self):
        """Test that we have exactly 8 required provenance columns."""
        assert len(REQUIRED_PROVENANCE_COLUMNS) == 8

    def test_required_provenance_columns_format(self):
        """Test that all provenance columns start with meta_."""
        for col in REQUIRED_PROVENANCE_COLUMNS:
            assert col.startswith("meta_"), f"Column {col} should start with 'meta_'"

    def test_required_baseline_types(self):
        """Test required baseline expectation types.

        Both expect_column_to_exist and expect_column_values_to_be_of_type are
        now classified as REDUNDANT_VALIDATION_TYPES, so the set is empty.
        """
        assert "expect_column_to_exist" not in REQUIRED_BASELINE_TYPES
        assert "expect_column_values_to_be_of_type" not in REQUIRED_BASELINE_TYPES
        assert len(REQUIRED_BASELINE_TYPES) == 0
