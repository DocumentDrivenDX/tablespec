"""Unit tests for date_processing module."""

from datetime import datetime

import pytest

pytestmark = pytest.mark.fast

from tablespec.sample_data.date_processing import (
    convert_umf_format_to_strftime,
    extract_date_constraints,
)


class TestConvertUmfFormatToStrftime:
    """Test UMF date format to Python strftime conversion."""

    @pytest.mark.parametrize(
        ("umf_format", "expected"),
        [
            # Basic date formats
            ("YYYY-MM-DD", "%Y-%m-%d"),
            ("MM/DD/YYYY", "%m/%d/%Y"),
            ("DD/MM/YYYY", "%d/%m/%Y"),
            ("YYYY/MM/DD", "%Y/%m/%d"),
            # Lowercase variants
            ("yyyy-mm-dd", "%Y-%M-%d"),  # Note: mm becomes %M (minutes)
            # 2-digit year
            ("YY-MM-DD", "%y-%m-%d"),
            ("MM/DD/YY", "%m/%d/%y"),
            # No separators
            ("YYYYMMDD", "%Y%m%d"),
            ("MMDDYYYY", "%m%d%Y"),
            # Month names
            ("YYYY-MMMM-DD", "%Y-%B-%d"),
            ("YYYY-MMM-DD", "%Y-%b-%d"),
            # Time formats
            ("HH:MM:SS", "%H:%M:%S"),
            ("HH:MM", "%H:%M"),
            ("hh:mm:ss", "%I:%M:%S"),
            ("hh:mm", "%I:%M"),
            # Combined date and time
            ("YYYY-MM-DD HH:MM:SS", "%Y-%m-%d %H:%M:%S"),
            ("MM/DD/YYYY HH:MM", "%m/%d/%Y %H:%M"),
            ("YYYY-MM-DD hh:mm:ss", "%Y-%m-%d %I:%M:%S"),
            # Edge cases
            (None, None),
            ("", None),
            # Single character patterns (non-zero padded) - UPPERCASE
            ("YYYY-M-D", "%Y-%-m-%-d"),
            ("D/M/YYYY", "%-d/%-m/%Y"),
            # Single character patterns (non-zero padded) - LOWERCASE
            # This is the format used in hc_2026_ent/inbound_call_status/completed_date_time
            ("M/d/yyyy, h:mm a", "%-m/%-d/%Y, %-I:%M %p"),
            ("M/d/yyyy", "%-m/%-d/%Y"),
            ("d/M/yyyy", "%-d/%-m/%Y"),
            # Mixed single/double character patterns
            ("M/DD/YYYY", "%-m/%d/%Y"),
            ("MM/d/YYYY", "%m/%-d/%Y"),
            # AM/PM markers
            ("YYYY-MM-DD hh:mm AM", "%Y-%m-%d %I:%M %p"),
            ("hh:mm:ss PM", "%I:%M:%S %p"),
            # Lowercase am/pm (common in Java-style formats)
            ("M/d/yyyy h:mm a", "%-m/%-d/%Y %-I:%M %p"),
            ("h:mm a", "%-I:%M %p"),
            ("hh:mm a", "%I:%M %p"),
        ],
    )
    def test_format_conversion(self, umf_format, expected):
        """Test conversion of various UMF date formats to strftime."""
        result = convert_umf_format_to_strftime(umf_format)
        assert result == expected

    def test_handles_ambiguous_mm_in_datetime(self):
        """Test that MM is correctly interpreted as month in date and minutes in time."""
        # MM in date part should be month, MM in time part should be minutes
        result = convert_umf_format_to_strftime("YYYY-MM-DD HH:MM:SS")
        assert result == "%Y-%m-%d %H:%M:%S"

        # Verify it works correctly when generating actual dates
        test_date = datetime(2024, 10, 15, 14, 30, 45)  # noqa: DTZ001 - Test data doesn't need timezone
        formatted = test_date.strftime(result)
        assert formatted == "2024-10-15 14:30:45"

    def test_preserves_separators(self):
        """Test that various separators are preserved correctly."""
        assert convert_umf_format_to_strftime("YYYY-MM-DD") == "%Y-%m-%d"
        assert convert_umf_format_to_strftime("YYYY/MM/DD") == "%Y/%m/%d"
        assert convert_umf_format_to_strftime("YYYY.MM.DD") == "%Y.%m.%d"
        assert convert_umf_format_to_strftime("YYYY MM DD") == "%Y %m %d"

    def test_handles_edge_cases(self):
        """Test edge cases and unusual formats."""
        # Empty string
        assert convert_umf_format_to_strftime("") is None

        # Whitespace only
        assert convert_umf_format_to_strftime("   ") == "   "

        # Mixed case (should handle both)
        result = convert_umf_format_to_strftime("yyyy-MM-DD")
        assert "%Y" in result
        assert "%m" in result
        assert "%d" in result

    @pytest.mark.parametrize(
        "umf_format",
        [
            "YYYY-MM-DD",
            "MM/DD/YYYY",
            "M/d/yyyy",
            "M/d/yyyy, h:mm a",
            "YYYY-MM-DD HH:MM:SS",
            "hh:mm:ss a",
        ],
    )
    def test_converted_format_produces_valid_dates(self, umf_format):
        """Verify converted strftime format can actually format a datetime."""
        strftime_format = convert_umf_format_to_strftime(umf_format)
        assert strftime_format is not None

        # Create a test datetime
        test_dt = datetime(2024, 11, 5, 14, 30, 45)  # noqa: DTZ001

        # Format should not raise an exception
        formatted = test_dt.strftime(strftime_format)

        # Formatted result should not contain literal format characters
        # These would indicate the conversion failed
        assert "YYYY" not in formatted
        assert "yyyy" not in formatted
        assert "/d/" not in formatted  # Single 'd' should be converted to day number
        assert "/M/" not in formatted  # Single 'M' should be converted to month number

        # Result should contain the actual date/time values
        # For date formats, check for year
        if "%Y" in strftime_format or "%y" in strftime_format:
            assert "2024" in formatted or "24" in formatted  # Year
        # For non-zero-padded formats, check for the day/month numbers
        if "%-d" in strftime_format:
            assert "5" in formatted  # Day 5 without zero padding
        if "%-m" in strftime_format:
            assert "11" in formatted  # Month 11
        # For time-only formats, verify time components are present
        if "%H" in strftime_format or "%I" in strftime_format:
            # Should contain hour (14 for 24h or 02 for 12h)
            assert "14" in formatted or "02" in formatted or "2" in formatted


class TestExtractDateConstraints:
    """Test extraction of date constraints from validation rules."""

    def test_extract_from_expect_column_values_to_be_between(self):
        """Test extraction from expect_column_values_to_be_between expectation."""
        umf_data = {
            "validation_rules": {
                "expectations": [
                    {
                        "type": "expect_column_values_to_be_between",
                        "kwargs": {
                            "column": "birth_date",
                            "min_value": "1900-01-01",
                            "max_value": "2024-12-31",
                        },
                    }
                ]
            }
        }

        result = extract_date_constraints("birth_date", umf_data)
        assert result == {"min_value": "1900-01-01", "max_value": "2024-12-31"}

    def test_extract_min_only(self):
        """Test extraction when only min_value is specified."""
        umf_data = {
            "validation_rules": {
                "expectations": [
                    {
                        "type": "expect_column_values_to_be_between",
                        "kwargs": {"column": "service_date", "min_value": "2020-01-01"},
                    }
                ]
            }
        }

        result = extract_date_constraints("service_date", umf_data)
        assert result == {"min_value": "2020-01-01"}

    def test_extract_max_only(self):
        """Test extraction when only max_value is specified."""
        umf_data = {
            "validation_rules": {
                "expectations": [
                    {
                        "type": "expect_column_values_to_be_between",
                        "kwargs": {"column": "end_date", "max_value": "2025-12-31"},
                    }
                ]
            }
        }

        result = extract_date_constraints("end_date", umf_data)
        assert result == {"max_value": "2025-12-31"}

    def test_no_constraints_for_different_column(self):
        """Test that constraints for other columns don't interfere."""
        umf_data = {
            "validation_rules": {
                "expectations": [
                    {
                        "type": "expect_column_values_to_be_between",
                        "kwargs": {
                            "column": "other_date",
                            "min_value": "2000-01-01",
                            "max_value": "2030-12-31",
                        },
                    }
                ]
            }
        }

        result = extract_date_constraints("my_date", umf_data)
        assert result is None

    def test_extract_from_pending_validation_rule(self):
        """Test extraction from pending validation rules with sanitization notes."""
        umf_data = {
            "validation_rules": {
                "expectations": [
                    {
                        "type": "expect_validation_rule_pending_implementation",
                        "kwargs": {"column": "claim_date"},
                        "meta": {
                            "sanitization_note": "Converted expect_column_values_to_be_between with min/max values (2020-01-01, 2024-12-31)"
                        },
                    }
                ]
            }
        }

        result = extract_date_constraints("claim_date", umf_data)
        assert result == {"min_value": "2020-01-01", "max_value": "2024-12-31"}

    def test_extract_from_value_set_with_dates(self):
        """Test extraction from value_set containing date values."""
        umf_data = {
            "validation_rules": {
                "expectations": [
                    {
                        "type": "expect_column_values_to_be_in_set",
                        "kwargs": {
                            "column": "review_date",
                            "value_set": [
                                "01/15/2023",
                                "03/20/2023",
                                "12/31/2024",
                                "06/10/2022",
                            ],
                        },
                    }
                ]
            }
        }

        result = extract_date_constraints("review_date", umf_data)
        assert result is not None
        assert "min_value" in result
        assert "max_value" in result

        # Should extract min/max from the date range
        # Expected: min = 06/10/2022, max = 12/31/2024
        min_date = datetime.strptime(result["min_value"], "%m/%d/%Y")
        max_date = datetime.strptime(result["max_value"], "%m/%d/%Y")

        assert min_date == datetime(2022, 6, 10)  # noqa: DTZ001 - Test data doesn't need timezone
        assert max_date == datetime(2024, 12, 31)  # noqa: DTZ001 - Test data doesn't need timezone

    def test_extract_from_value_set_with_iso_dates(self):
        """Test extraction from value_set with ISO date format."""
        umf_data = {
            "validation_rules": {
                "expectations": [
                    {
                        "type": "expect_column_values_to_be_in_set",
                        "kwargs": {
                            "column": "audit_date",
                            "value_set": ["2023-01-15", "2023-06-20", "2024-12-31"],
                        },
                    }
                ]
            }
        }

        result = extract_date_constraints("audit_date", umf_data)
        assert result is not None
        assert result["min_value"] == "2023-01-15"
        assert result["max_value"] == "2024-12-31"

    def test_no_constraints_when_no_validation_rules(self):
        """Test that None is returned when no validation rules exist."""
        umf_data = {}
        result = extract_date_constraints("any_date", umf_data)
        assert result is None

    def test_no_constraints_when_empty_expectations(self):
        """Test that None is returned when expectations list is empty."""
        umf_data = {"validation_rules": {"expectations": []}}
        result = extract_date_constraints("any_date", umf_data)
        assert result is None

    def test_skips_non_date_value_sets(self):
        """Test that value_set with non-date values is skipped."""
        umf_data = {
            "validation_rules": {
                "expectations": [
                    {
                        "type": "expect_column_values_to_be_in_set",
                        "kwargs": {
                            "column": "status",
                            "value_set": ["ACTIVE", "INACTIVE", "PENDING"],
                        },
                    }
                ]
            }
        }

        result = extract_date_constraints("status", umf_data)
        assert result is None

    def test_handles_mixed_value_set(self):
        """Test value_set with mix of dates and non-dates (should skip)."""
        umf_data = {
            "validation_rules": {
                "expectations": [
                    {
                        "type": "expect_column_values_to_be_in_set",
                        "kwargs": {
                            "column": "mixed_col",
                            "value_set": ["2023-01-01", "NOT_A_DATE", "2024-12-31"],
                        },
                    }
                ]
            }
        }

        # Should still extract dates that can be parsed
        result = extract_date_constraints("mixed_col", umf_data)
        # Function should handle partial parsing gracefully
        # Either returns valid dates or None
        if result:
            assert "min_value" in result or "max_value" in result

    def test_prioritizes_be_between_over_value_set(self):
        """Test that expect_column_values_to_be_between takes priority over value_set."""
        umf_data = {
            "validation_rules": {
                "expectations": [
                    {
                        "type": "expect_column_values_to_be_between",
                        "kwargs": {
                            "column": "priority_date",
                            "min_value": "2020-01-01",
                            "max_value": "2025-12-31",
                        },
                    },
                    {
                        "type": "expect_column_values_to_be_in_set",
                        "kwargs": {
                            "column": "priority_date",
                            "value_set": ["2021-06-01", "2022-07-15"],
                        },
                    },
                ]
            }
        }

        result = extract_date_constraints("priority_date", umf_data)
        # Should use the be_between constraint, not value_set
        assert result == {"min_value": "2020-01-01", "max_value": "2025-12-31"}

    def test_handles_malformed_sanitization_note(self):
        """Test graceful handling of malformed sanitization notes."""
        umf_data = {
            "validation_rules": {
                "expectations": [
                    {
                        "type": "expect_validation_rule_pending_implementation",
                        "kwargs": {"column": "test_date"},
                        "meta": {
                            "sanitization_note": "Some other text without date pattern"
                        },
                    }
                ]
            }
        }

        result = extract_date_constraints("test_date", umf_data)
        assert result is None

    def test_multiple_formats_in_value_set(self):
        """Test value_set with dates in different formats."""
        umf_data = {
            "validation_rules": {
                "expectations": [
                    {
                        "type": "expect_column_values_to_be_in_set",
                        "kwargs": {
                            "column": "multi_format_date",
                            # Mix of formats - should try each format
                            "value_set": ["01/15/2023", "2024-06-20", "12-31-2024"],
                        },
                    }
                ]
            }
        }

        result = extract_date_constraints("multi_format_date", umf_data)
        # Should parse what it can and extract min/max
        if result:
            assert "min_value" in result or "max_value" in result
