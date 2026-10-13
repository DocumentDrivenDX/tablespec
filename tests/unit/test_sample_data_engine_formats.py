"""Unit tests for SampleDataGenerator format handling changes."""

# @covers US-013-AC1
# @covers US-013-AC2
# @covers US-013-AC3
# @covers US-013-AC4

from pathlib import Path
from unittest.mock import patch

import pytest

from tablespec.sample_data.config import GenerationConfig

# Mark all tests in this module as not requiring Spark
pytestmark = [pytest.mark.no_spark, pytest.mark.fast]


@pytest.fixture
def sample_generator():
    """Create a SampleDataGenerator instance with mocked dependencies.

    Uses patching to avoid initializing heavy dependencies like GX extractors.
    """
    with (
        patch("tablespec.sample_data.engine.GXConstraintExtractor"),
        patch("tablespec.sample_data.engine.DomainTypeRegistry"),
        patch("tablespec.sample_data.engine.KeyRegistry"),
        patch("tablespec.sample_data.engine.HealthcareDataGenerators"),
        patch("tablespec.sample_data.engine.ValidationRuleProcessor"),
        patch("tablespec.sample_data.engine.RelationshipGraph"),
    ):
        from tablespec.sample_data.engine import SampleDataGenerator

        return SampleDataGenerator(
            input_dir=Path("/tmp/test_input"),
            output_dir=Path("/tmp/test_output"),
            config=GenerationConfig(num_members=10),
        )


class TestDateFormatConversion:
    """Tests for _convert_umf_format_to_strftime() method."""

    def test_convert_ambiguous_timestamp_yyyy_mm_dd_hh_mm_ss(self, sample_generator):
        """Test converting ambiguous YYYY-MM-DD HH:MM:SS format.

        This format is ambiguous because MM appears twice:
        - MM in date part = month
        - MM in time part = minutes
        """
        result = sample_generator._convert_umf_format_to_strftime("YYYY-MM-DD HH:MM:SS")

        # Should convert correctly: month in date, minutes in time
        assert "%Y" in result  # Year
        assert "%m" in result  # Month (date part)
        assert "%d" in result  # Day
        assert "%H" in result  # Hour
        assert "%M" in result  # Minutes (time part)
        assert "%S" in result  # Seconds

        # The full result should be valid strftime
        assert result == "%Y-%m-%d %H:%M:%S"

    def test_convert_date_only_format_yyyy_mm_dd(self, sample_generator):
        """Test converting date-only YYYY-MM-DD format."""
        result = sample_generator._convert_umf_format_to_strftime("YYYY-MM-DD")

        assert result == "%Y-%m-%d"

    def test_convert_date_only_format_mm_dd_yyyy(self, sample_generator):
        """Test converting MM/DD/YYYY format."""
        result = sample_generator._convert_umf_format_to_strftime("MM/DD/YYYY")

        assert result == "%m/%d/%Y"

    def test_convert_time_only_format_hh_mm_ss(self, sample_generator):
        """Test converting time-only HH:MM:SS format."""
        result = sample_generator._convert_umf_format_to_strftime("HH:MM:SS")

        assert result == "%H:%M:%S"

    def test_convert_time_only_format_hh_mm(self, sample_generator):
        """Test converting time-only HH:MM format."""
        result = sample_generator._convert_umf_format_to_strftime("HH:MM")

        assert result == "%H:%M"

    def test_convert_lowercase_time_format(self, sample_generator):
        """Test converting lowercase time format hh:mm:ss.

        Note: hh (lowercase) is 12-hour format, HH (uppercase) is 24-hour format.
        This follows standard date format conventions used in Java SimpleDateFormat.
        """
        result = sample_generator._convert_umf_format_to_strftime("YYYY-MM-DD hh:mm:ss")

        # hh:mm:ss -> %I:%M:%S (12-hour format)
        assert "%I" in result  # 12-hour format
        assert "%M" in result
        assert "%S" in result

    def test_convert_empty_format_returns_none(self, sample_generator):
        """Test that empty format returns None."""
        result = sample_generator._convert_umf_format_to_strftime("")

        assert result is None

    def test_convert_none_format_returns_none(self, sample_generator):
        """Test that None format returns None."""
        result = sample_generator._convert_umf_format_to_strftime(None)

        assert result is None

    def test_convert_full_month_name(self, sample_generator):
        """Test converting MMMM (full month name) format."""
        result = sample_generator._convert_umf_format_to_strftime("MMMM DD, YYYY")

        assert "%B" in result  # Full month name

    def test_convert_abbreviated_month_name(self, sample_generator):
        """Test converting MMM (abbreviated month name) format."""
        result = sample_generator._convert_umf_format_to_strftime("DD-MMM-YYYY")

        assert "%b" in result  # Abbreviated month name

    def test_convert_two_digit_year(self, sample_generator):
        """Test converting YY (2-digit year) format."""
        result = sample_generator._convert_umf_format_to_strftime("MM/DD/YY")

        assert "%y" in result  # 2-digit year

    def test_convert_12_hour_format_with_ampm(self, sample_generator):
        """Test converting 12-hour format with AM/PM marker."""
        result = sample_generator._convert_umf_format_to_strftime("MM/DD/YYYY hh:mm A")

        assert "%I" in result  # 12-hour format
        assert "%M" in result  # Minutes
        assert "%p" in result  # AM/PM marker
        assert result == "%m/%d/%Y %I:%M %p"

    def test_convert_single_digit_month_day(self, sample_generator):
        """Test converting single-digit month/day format (M/D)."""
        result = sample_generator._convert_umf_format_to_strftime("M/D/YYYY")

        assert "%-m" in result  # Single-digit month
        assert "%-d" in result  # Single-digit day
        assert result == "%-m/%-d/%Y"

    def test_convert_single_digit_hour_with_ampm(self, sample_generator):
        """Test converting single-digit 12-hour format with AM/PM."""
        result = sample_generator._convert_umf_format_to_strftime("M/D/YYYY h:mm A")

        assert "%-m" in result  # Single-digit month
        assert "%-d" in result  # Single-digit day
        assert "%-I" in result  # Single-digit 12-hour
        assert "%M" in result  # Minutes
        assert "%p" in result  # AM/PM marker
        assert result == "%-m/%-d/%Y %-I:%M %p"

    def test_convert_timestamp_with_seconds_and_ampm(self, sample_generator):
        """Test converting timestamp with seconds and AM/PM."""
        result = sample_generator._convert_umf_format_to_strftime("M/D/YYYY h:mm:ss A")

        assert "%-I" in result  # Single-digit 12-hour
        assert "%M" in result  # Minutes
        assert "%S" in result  # Seconds
        assert "%p" in result  # AM/PM marker
        assert result == "%-m/%-d/%Y %-I:%M:%S %p"


class TestGenerationConfigDefaults:
    """Tests for GenerationConfig defaults and initialization."""

    def test_config_default_values(self):
        """Test that GenerationConfig has expected defaults."""
        config = GenerationConfig()

        assert config.num_members == 10000
        assert config.relationship_density == 0.7
        assert config.temporal_range_days == 365
        assert config.random_seed == 42
        assert config.key_pool_size == 500
        assert config.key_distribution_80_20 is True
        assert config.high_frequency_key_ratio == 0.8

    def test_config_custom_values(self):
        """Test GenerationConfig with custom values."""
        config = GenerationConfig(
            num_members=100,
            relationship_density=0.5,
            random_seed=None,
        )

        assert config.num_members == 100
        assert config.relationship_density == 0.5
        assert config.random_seed is None

    def test_config_null_percentage_default_empty_dict(self):
        """Test that null_percentage defaults to empty dict."""
        config = GenerationConfig()

        assert config.null_percentage == {}
        assert isinstance(config.null_percentage, dict)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
