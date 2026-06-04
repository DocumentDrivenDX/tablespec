"""Unit tests for date_formats module - supported date/datetime format definitions."""

from datetime import datetime

import pytest

pytestmark = [pytest.mark.fast, pytest.mark.no_spark]

from tablespec.date_formats import (
    SUPPORTED_DATE_FORMATS,
    DateFormat,
    FormatType,
    get_format_type,
    get_strftime_format,
    get_supported_umf_formats,
    is_supported_format,
    suggest_format_for_example,
    validate_format_for_data_type,
)


class TestSupportedDateFormats:
    """Test the supported formats registry."""

    def test_all_supported_formats_have_required_fields(self):
        """Every DateFormat must have all required fields."""
        for fmt in SUPPORTED_DATE_FORMATS:
            assert isinstance(fmt, DateFormat)
            assert fmt.umf_format, f"Missing umf_format in {fmt}"
            assert fmt.strftime_format, f"Missing strftime_format in {fmt}"
            assert fmt.format_type in FormatType, f"Invalid format_type in {fmt}"
            assert fmt.description, f"Missing description in {fmt}"

    def test_no_duplicate_umf_formats(self):
        """UMF format strings must be unique."""
        umf_formats = [fmt.umf_format for fmt in SUPPORTED_DATE_FORMATS]
        assert len(umf_formats) == len(set(umf_formats)), "Duplicate UMF formats found"

    @pytest.mark.parametrize(
        "fmt",
        SUPPORTED_DATE_FORMATS,
        ids=[f.umf_format for f in SUPPORTED_DATE_FORMATS],
    )
    def test_each_format_produces_valid_datetime(self, fmt: DateFormat):
        """Every supported format's strftime must produce valid output."""
        # Create a test datetime with all components
        test_dt = datetime(2024, 11, 5, 14, 30, 45)  # noqa: DTZ001 - Test data doesn't need timezone

        # Format should not raise an exception
        formatted = test_dt.strftime(fmt.strftime_format)

        # Result should not contain unprocessed format tokens
        assert "YYYY" not in formatted
        assert "yyyy" not in formatted
        assert "MM" not in formatted, f"Unprocessed 'MM' in: {formatted}"
        assert formatted.count("%") == 0, f"Unprocessed tokens in: {formatted}"

        # For dates, verify year is present
        if fmt.format_type in (FormatType.DATE, FormatType.DATETIME):
            assert "2024" in formatted or "24" in formatted, (
                f"Year not in formatted output: {formatted}"
            )

    @pytest.mark.parametrize(
        "fmt",
        [f for f in SUPPORTED_DATE_FORMATS if "%-" not in f.strftime_format],
        ids=[
            f.umf_format
            for f in SUPPORTED_DATE_FORMATS
            if "%-" not in f.strftime_format
        ],
    )
    def test_padded_formats_can_be_parsed(self, fmt: DateFormat):
        """Zero-padded formats can round-trip: format then parse.

        Note: Non-padded formats (with %-) are excluded because strptime
        has inconsistent behavior with them across platforms.
        """
        test_dt = datetime(2024, 11, 5, 14, 30, 45)  # noqa: DTZ001 - Test data doesn't need timezone

        formatted = test_dt.strftime(fmt.strftime_format)

        # Should be able to parse the formatted string back
        try:
            parsed = datetime.strptime(formatted, fmt.strftime_format)
            # For date-only formats, time components default to 0
            if fmt.format_type == FormatType.DATE:
                assert parsed.year == test_dt.year
                assert parsed.month == test_dt.month
                assert parsed.day == test_dt.day
            elif fmt.format_type == FormatType.DATETIME:
                # Check date and time components that are in the format
                assert parsed.year == test_dt.year
                assert parsed.month == test_dt.month
                assert parsed.day == test_dt.day
                assert parsed.hour == test_dt.hour
                assert parsed.minute == test_dt.minute
                # Seconds may not be in the format, so only check if format includes them
                if "%S" in fmt.strftime_format:
                    assert parsed.second == test_dt.second
            elif fmt.format_type == FormatType.TIME:
                assert parsed.hour == test_dt.hour
                assert parsed.minute == test_dt.minute
        except ValueError as e:
            pytest.fail(
                f"Could not parse '{formatted}' with format '{fmt.strftime_format}': {e}"
            )


class TestIsSupportedFormat:
    """Test is_supported_format function."""

    @pytest.mark.parametrize(
        "umf_format",
        [
            "YYYY-MM-DD",
            "MM/DD/YYYY",
            "M/D/YYYY",
            "YYYY-MM-DD HH:MM:SS",
            "M/d/yyyy, h:mm a",
        ],
    )
    def test_known_formats_are_supported(self, umf_format):
        """Known formats should be recognized as supported."""
        assert is_supported_format(umf_format) is True

    @pytest.mark.parametrize(
        "umf_format",
        [
            "INVALID",
            "YY-M-D-Z",
            "not a format",
            "2024-01-01",  # This is a value, not a format
            "",
            None,
        ],
    )
    def test_invalid_formats_are_not_supported(self, umf_format):
        """Unknown formats should not be recognized."""
        assert is_supported_format(umf_format) is False


class TestGetStrftimeFormat:
    """Test get_strftime_format function."""

    @pytest.mark.parametrize(
        ("umf_format", "expected"),
        [
            ("YYYY-MM-DD", "%Y-%m-%d"),
            ("MM/DD/YYYY", "%m/%d/%Y"),
            ("M/D/YYYY", "%-m/%-d/%Y"),
            ("YYYY-MM-DD HH:MM:SS", "%Y-%m-%d %H:%M:%S"),
            ("M/d/yyyy, h:mm a", "%-m/%-d/%Y, %-I:%M %p"),
        ],
    )
    def test_returns_correct_strftime(self, umf_format, expected):
        """Verify correct strftime format is returned."""
        assert get_strftime_format(umf_format) == expected

    def test_returns_none_for_unknown_format(self):
        """Unknown formats should return None."""
        assert get_strftime_format("INVALID") is None
        assert get_strftime_format("not a format") is None


class TestGetFormatType:
    """Test get_format_type function."""

    @pytest.mark.parametrize(
        ("umf_format", "expected"),
        [
            ("YYYY-MM-DD", FormatType.DATE),
            ("MM/DD/YYYY", FormatType.DATE),
            ("YYYY-MM-DD HH:MM:SS", FormatType.DATETIME),
            ("M/D/YYYY h:mm A", FormatType.DATETIME),
            ("HH:MM:SS", FormatType.TIME),
            ("h:mm a", FormatType.TIME),
        ],
    )
    def test_returns_correct_format_type(self, umf_format, expected):
        """Verify correct format type is returned."""
        assert get_format_type(umf_format) == expected

    def test_returns_none_for_unknown_format(self):
        """Unknown formats should return None."""
        assert get_format_type("INVALID") is None


class TestValidateFormatForDataType:
    """Test validate_format_for_data_type function."""

    @pytest.mark.parametrize(
        ("umf_format", "data_type"),
        [
            ("YYYY-MM-DD", "DateType"),
            ("MM/DD/YYYY", "DateType"),
            ("YYYY-MM-DD HH:MM:SS", "TimestampType"),
            ("M/D/YYYY h:mm A", "TimestampType"),
            ("YYYY-MM-DD", "TimestampType"),  # Date format is OK for timestamp
        ],
    )
    def test_valid_format_data_type_combinations(self, umf_format, data_type):
        """Valid format/data_type combinations should return None (no error)."""
        assert validate_format_for_data_type(umf_format, data_type) is None

    def test_unsupported_format_returns_error(self):
        """Unsupported format should return error message."""
        error = validate_format_for_data_type("INVALID_FORMAT", "DateType")
        assert error is not None
        assert "Unsupported date/datetime format" in error
        assert "INVALID_FORMAT" in error

    def test_datetime_format_for_date_type_returns_error(self):
        """Using datetime format for DateType should return error."""
        error = validate_format_for_data_type("YYYY-MM-DD HH:MM:SS", "DateType")
        assert error is not None
        assert "datetime format" in error

    def test_time_format_for_date_type_returns_error(self):
        """Using time format for DateType should return error."""
        error = validate_format_for_data_type("HH:MM:SS", "DateType")
        assert error is not None
        assert "time format" in error

    def test_none_format_is_valid(self):
        """No format specified should be valid."""
        assert validate_format_for_data_type(None, "DateType") is None
        assert validate_format_for_data_type("", "DateType") is None


class TestSuggestFormatForExample:
    """Test suggest_format_for_example function."""

    @pytest.mark.parametrize(
        ("example", "expected_format"),
        [
            ("2024-01-15", "YYYY-MM-DD"),
            ("01/15/2024", "MM/DD/YYYY"),
            ("2024-01-15 14:30:45", "YYYY-MM-DD HH:MM:SS"),
        ],
    )
    def test_suggests_correct_format(self, example, expected_format):
        """Should suggest the correct format for valid examples."""
        result = suggest_format_for_example(example)
        assert result == expected_format

    @pytest.mark.parametrize(
        "example",
        [
            "not a date",
            "2024",
            "",
            None,
            "invalid-date-format",
        ],
    )
    def test_returns_none_for_invalid_examples(self, example):
        """Should return None for values that don't match any format."""
        assert suggest_format_for_example(example) is None


class TestGetSupportedUmfFormats:
    """Test get_supported_umf_formats function."""

    def test_returns_all_format_strings(self):
        """Should return all UMF format strings."""
        formats = get_supported_umf_formats()
        assert isinstance(formats, list)
        assert len(formats) == len(SUPPORTED_DATE_FORMATS)
        assert "YYYY-MM-DD" in formats
        assert "MM/DD/YYYY" in formats

    def test_returned_formats_are_unique(self):
        """All returned formats should be unique."""
        formats = get_supported_umf_formats()
        assert len(formats) == len(set(formats))


class TestEdgeCases:
    """Test edge cases and special scenarios."""

    def test_formats_with_different_separators(self):
        """Test formats with various separators work correctly."""
        # Test with dash separator
        assert is_supported_format("YYYY-MM-DD")
        # Test with slash separator
        assert is_supported_format("MM/DD/YYYY")
        # Test with comma separator
        assert is_supported_format("M/d/yyyy, h:mm a")

    def test_formats_with_varying_padding(self):
        """Test formats with and without zero padding."""
        # Padded
        assert is_supported_format("MM/DD/YYYY")
        # Unpadded
        assert is_supported_format("M/D/YYYY")
        # Mixed
        assert is_supported_format("M/d/yyyy")

    def test_12_vs_24_hour_formats(self):
        """Test both 12-hour and 24-hour time formats."""
        # 24-hour
        assert is_supported_format("YYYY-MM-DD HH:MM:SS")
        assert get_format_type("YYYY-MM-DD HH:MM:SS") == FormatType.DATETIME

        # 12-hour with AM/PM
        assert is_supported_format("M/D/YYYY h:mm A")
        assert get_format_type("M/D/YYYY h:mm A") == FormatType.DATETIME

    def test_case_sensitivity(self):
        """Test that formats are case-sensitive."""
        # These are different formats with different meanings
        assert is_supported_format("MM/DD/YYYY")
        assert is_supported_format("M/d/yyyy")
        # But exactly matching is required
        assert not is_supported_format("mm/dd/yyyy")  # lowercase mm means minutes

    def test_compact_formats(self):
        """Test compact formats without separators."""
        assert is_supported_format("YYYYMMDD")
        assert is_supported_format("MMDDYYYY")

        # Verify they format correctly
        test_dt = datetime(2024, 11, 5)  # noqa: DTZ001 - Test data doesn't need timezone
        assert test_dt.strftime(get_strftime_format("YYYYMMDD")) == "20241105"
        assert test_dt.strftime(get_strftime_format("MMDDYYYY")) == "11052024"
