"""Unit tests for domain type compatibility validation.

Tests that domain types are only applied when compatible with the column's data_type,
preventing CAST_INVALID_INPUT errors from generating incompatible values.
"""

from __future__ import annotations

from pydantic import ValidationError
import pytest

from tablespec.inference.domain_types import DomainTypeRegistry
from tablespec.models.umf import UMFColumn

pytestmark = pytest.mark.fast


class TestDomainTypeRegistryExpectedType:
    """Test DomainTypeRegistry.get_expected_base_type()."""

    @pytest.fixture
    def registry(self) -> DomainTypeRegistry:
        """Create a domain type registry."""
        return DomainTypeRegistry()

    def test_birth_date_expects_date(self, registry: DomainTypeRegistry):
        """birth_date domain type should expect DATE base type."""
        expected = registry.get_expected_base_type("birth_date")
        assert expected == "DATE"

    def test_service_date_expects_date(self, registry: DomainTypeRegistry):
        """service_date domain type should expect DATE base type."""
        expected = registry.get_expected_base_type("service_date")
        assert expected == "DATE"

    def test_calendar_year_expects_integer(self, registry: DomainTypeRegistry):
        """calendar_year domain type should expect INTEGER base type."""
        expected = registry.get_expected_base_type("calendar_year")
        assert expected == "INTEGER"

    def test_timestamp_expects_timestamp(self, registry: DomainTypeRegistry):
        """Timestamp domain type should expect TIMESTAMP base type."""
        expected = registry.get_expected_base_type("timestamp")
        assert expected == "TIMESTAMP"

    def test_email_has_no_explicit_type(self, registry: DomainTypeRegistry):
        """Email domain type has no explicit type constraint (validated by regex)."""
        expected = registry.get_expected_base_type("email")
        # email is validated by regex, not by type
        assert expected is None

    def test_unknown_domain_type_returns_none(self, registry: DomainTypeRegistry):
        """Unknown domain types should return None."""
        expected = registry.get_expected_base_type("unknown_domain_type")
        assert expected is None


class TestDomainTypeRegistryCompatibility:
    """Test DomainTypeRegistry.is_domain_type_compatible_with_data_type()."""

    @pytest.fixture
    def registry(self) -> DomainTypeRegistry:
        """Create a domain type registry."""
        return DomainTypeRegistry()

    # DATE domain types
    def test_birth_date_compatible_with_date_type(self, registry: DomainTypeRegistry):
        """birth_date should be compatible with DateType."""
        assert registry.is_domain_type_compatible_with_data_type(
            "birth_date", "DateType"
        )

    def test_birth_date_compatible_with_timestamp_type(
        self, registry: DomainTypeRegistry
    ):
        """birth_date should be compatible with TimestampType (supertype of DATE)."""
        assert registry.is_domain_type_compatible_with_data_type(
            "birth_date", "TimestampType"
        )

    def test_birth_date_incompatible_with_string_type(
        self, registry: DomainTypeRegistry
    ):
        """birth_date should NOT be compatible with StringType."""
        assert not registry.is_domain_type_compatible_with_data_type(
            "birth_date", "StringType"
        )

    def test_birth_date_incompatible_with_integer_type(
        self, registry: DomainTypeRegistry
    ):
        """birth_date should NOT be compatible with IntegerType."""
        assert not registry.is_domain_type_compatible_with_data_type(
            "birth_date", "IntegerType"
        )

    # INTEGER domain types
    def test_calendar_year_compatible_with_integer_type(
        self, registry: DomainTypeRegistry
    ):
        """calendar_year should be compatible with IntegerType."""
        assert registry.is_domain_type_compatible_with_data_type(
            "calendar_year", "IntegerType"
        )

    def test_calendar_year_compatible_with_long_type(
        self, registry: DomainTypeRegistry
    ):
        """calendar_year should be compatible with LongType."""
        assert registry.is_domain_type_compatible_with_data_type(
            "calendar_year", "LongType"
        )

    def test_calendar_year_incompatible_with_string_type(
        self, registry: DomainTypeRegistry
    ):
        """calendar_year should NOT be compatible with StringType."""
        assert not registry.is_domain_type_compatible_with_data_type(
            "calendar_year", "StringType"
        )

    def test_calendar_year_incompatible_with_double_type(
        self, registry: DomainTypeRegistry
    ):
        """calendar_year should NOT be compatible with DoubleType."""
        assert not registry.is_domain_type_compatible_with_data_type(
            "calendar_year", "DoubleType"
        )

    # TIMESTAMP domain types
    def test_timestamp_compatible_with_timestamp_type(
        self, registry: DomainTypeRegistry
    ):
        """Timestamp should be compatible with TimestampType."""
        assert registry.is_domain_type_compatible_with_data_type(
            "timestamp", "TimestampType"
        )

    def test_timestamp_incompatible_with_date_type(self, registry: DomainTypeRegistry):
        """Timestamp should NOT be compatible with DateType (timestamp is more specific)."""
        assert not registry.is_domain_type_compatible_with_data_type(
            "timestamp", "DateType"
        )

    def test_timestamp_incompatible_with_string_type(
        self, registry: DomainTypeRegistry
    ):
        """Timestamp should NOT be compatible with StringType."""
        assert not registry.is_domain_type_compatible_with_data_type(
            "timestamp", "StringType"
        )

    # Domain types without explicit type constraints (email, npi, etc.)
    def test_email_compatible_with_string_type(self, registry: DomainTypeRegistry):
        """Email has no explicit type constraint, compatible with any type."""
        assert registry.is_domain_type_compatible_with_data_type("email", "StringType")

    def test_email_compatible_with_any_type(self, registry: DomainTypeRegistry):
        """Email has no explicit type constraint, compatible with any type."""
        # Since email has no expect_column_values_to_be_of_type validation,
        # it returns True for compatibility (type-agnostic, validated by regex)
        assert registry.is_domain_type_compatible_with_data_type(
            "email", "TimestampType"
        )

    def test_unknown_domain_type_compatible_with_any(
        self, registry: DomainTypeRegistry
    ):
        """Unknown domain types should be compatible with any data type (allow fallback)."""
        assert registry.is_domain_type_compatible_with_data_type(
            "unknown_domain", "StringType"
        )
        assert registry.is_domain_type_compatible_with_data_type(
            "unknown_domain", "IntegerType"
        )


class TestUMFColumnDomainTypeValidation:
    """Test UMFColumn model_validator for domain_type compatibility."""

    def test_column_with_no_domain_type_passes(self):
        """Column without domain_type should always pass validation."""
        col = UMFColumn(
            name="my_column",
            data_type="VARCHAR",
            domain_type=None,
        )
        assert col.name == "my_column"

    def test_birth_date_with_date_type_passes(self):
        """birth_date domain_type with DATE should pass."""
        col = UMFColumn(
            name="patient_dob",
            data_type="DATE",
            domain_type="birth_date",
        )
        assert col.domain_type == "birth_date"

    def test_birth_date_with_datetime_type_passes(self):
        """birth_date domain_type with DATETIME should pass."""
        col = UMFColumn(
            name="patient_dob",
            data_type="DATETIME",
            domain_type="birth_date",
        )
        assert col.domain_type == "birth_date"

    def test_birth_date_with_varchar_type_fails(self):
        """birth_date domain_type with VARCHAR should fail validation."""
        with pytest.raises(ValidationError) as exc_info:
            UMFColumn(
                name="patient_dob",
                data_type="VARCHAR",
                domain_type="birth_date",
            )
        assert "incompatible domain_type" in str(exc_info.value).lower()

    def test_calendar_year_with_integer_type_passes(self):
        """calendar_year domain_type with INTEGER should pass."""
        col = UMFColumn(
            name="year",
            data_type="INTEGER",
            domain_type="calendar_year",
        )
        assert col.domain_type == "calendar_year"

    def test_calendar_year_with_varchar_type_fails(self):
        """calendar_year domain_type with VARCHAR should fail validation."""
        with pytest.raises(ValidationError) as exc_info:
            UMFColumn(
                name="year_label",
                data_type="VARCHAR",
                domain_type="calendar_year",
            )
        assert "incompatible domain_type" in str(exc_info.value).lower()

    def test_timestamp_with_datetime_type_passes(self):
        """Timestamp domain_type with DATETIME should pass."""
        col = UMFColumn(
            name="created_at",
            data_type="DATETIME",
            domain_type="timestamp",
        )
        assert col.domain_type == "timestamp"

    def test_timestamp_with_varchar_type_fails(self):
        """Timestamp domain_type with VARCHAR should fail validation."""
        with pytest.raises(ValidationError) as exc_info:
            UMFColumn(
                name="created_at",
                data_type="VARCHAR",
                domain_type="timestamp",
            )
        assert "incompatible domain_type" in str(exc_info.value).lower()

    def test_unknown_domain_type_passes(self):
        """Unknown domain types should pass validation (allow future extensions)."""
        col = UMFColumn(
            name="custom_field",
            data_type="VARCHAR",
            domain_type="custom_domain_type",
        )
        assert col.domain_type == "custom_domain_type"

    def test_unmapped_domain_type_with_any_data_type_passes(self):
        """Unmapped domain type should be compatible with any data_type (placeholder)."""
        col1 = UMFColumn(
            name="unmatched_field",
            data_type="VARCHAR",
            domain_type="unmapped",
        )
        assert col1.domain_type == "unmapped"

        col2 = UMFColumn(
            name="unmatched_int",
            data_type="INTEGER",
            domain_type="unmapped",
        )
        assert col2.domain_type == "unmapped"

        col3 = UMFColumn(
            name="unmatched_decimal",
            data_type="DECIMAL",
            domain_type="unmapped",
        )
        assert col3.domain_type == "unmapped"

    def test_service_date_with_varchar_and_format_passes(self):
        """service_date with VARCHAR and format should pass (Bronze layer pattern)."""
        col = UMFColumn(
            name="service_date",
            data_type="VARCHAR",
            domain_type="service_date",
            format="YYYYMMDD",
        )
        assert col.domain_type == "service_date"
        assert col.format == "YYYYMMDD"

    def test_birth_date_with_varchar_and_format_passes(self):
        """birth_date with VARCHAR and format should pass (Bronze layer pattern)."""
        col = UMFColumn(
            name="patient_dob",
            data_type="VARCHAR",
            domain_type="birth_date",
            format="YYYY-MM-DD",
        )
        assert col.domain_type == "birth_date"
        assert col.format == "YYYY-MM-DD"

    def test_timestamp_with_varchar_and_format_passes(self):
        """Timestamp with VARCHAR and format should pass (Bronze layer pattern)."""
        col = UMFColumn(
            name="created_at",
            data_type="VARCHAR",
            domain_type="timestamp",
            format="YYYY-MM-DD HH:mm:ss",
        )
        assert col.domain_type == "timestamp"
        assert col.format == "YYYY-MM-DD HH:mm:ss"

    def test_service_date_with_varchar_no_format_fails(self):
        """service_date with VARCHAR and NO format should fail validation."""
        with pytest.raises(ValidationError) as exc_info:
            UMFColumn(
                name="service_date",
                data_type="VARCHAR",
                domain_type="service_date",
            )
        assert "incompatible domain_type" in str(exc_info.value).lower()


class TestDomainTypeRegistryPlaceholders:
    """Test DomainTypeRegistry handling of placeholder types."""

    @pytest.fixture
    def registry(self) -> DomainTypeRegistry:
        """Create a domain type registry."""
        return DomainTypeRegistry()

    def test_unmapped_domain_type_returns_none(self, registry: DomainTypeRegistry):
        """Unmapped domain type uses __COLUMN_TYPE__ placeholder, should return None."""
        expected = registry.get_expected_base_type("unmapped")
        assert expected is None

    def test_unmapped_compatible_with_any_type(self, registry: DomainTypeRegistry):
        """Unmapped domain type should be compatible with any data type."""
        assert registry.is_domain_type_compatible_with_data_type(
            "unmapped", "StringType"
        )
        assert registry.is_domain_type_compatible_with_data_type(
            "unmapped", "IntegerType"
        )
        assert registry.is_domain_type_compatible_with_data_type("unmapped", "DateType")
        assert registry.is_domain_type_compatible_with_data_type(
            "unmapped", "DecimalType"
        )
