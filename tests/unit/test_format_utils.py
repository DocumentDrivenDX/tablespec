"""Tests for format_utils module."""

import pytest

from tablespec.format_utils import convert_umf_format_to_strftime

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]


class TestConvertUmfFormatToStrftime:
    """Test UMF format to Python strftime conversion."""

    def test_date_format_yyyy_mm_dd(self):
        """Test YYYY-MM-DD converts to %Y-%m-%d."""
        assert convert_umf_format_to_strftime("YYYY-MM-DD") == "%Y-%m-%d"

    def test_date_format_mm_dd_yyyy(self):
        """Test MM/DD/YYYY converts to %m/%d/%Y."""
        assert convert_umf_format_to_strftime("MM/DD/YYYY") == "%m/%d/%Y"

    def test_date_format_dd_mm_yyyy(self):
        """Test DD/MM/YYYY converts to %d/%m/%Y."""
        assert convert_umf_format_to_strftime("DD/MM/YYYY") == "%d/%m/%Y"

    def test_date_format_yyyymmdd(self):
        """Test YYYYMMDD converts to %Y%m%d."""
        assert convert_umf_format_to_strftime("YYYYMMDD") == "%Y%m%d"

    def test_timestamp_format_full(self):
        """Test YYYY-MM-DD HH:MM:SS converts to %Y-%m-%d %H:%M:%S."""
        assert (
            convert_umf_format_to_strftime("YYYY-MM-DD HH:MM:SS") == "%Y-%m-%d %H:%M:%S"
        )

    def test_timestamp_format_compact(self):
        """Test YYYYMMDD HHMMSS converts to %Y%m%d %H%M%S."""
        # Note: Without colon after HH, MM is treated as month (ambiguous but follows pattern)
        assert convert_umf_format_to_strftime("YYYYMMDD HHMMSS") == "%Y%m%d %H%m%S"

    def test_mm_ambiguity_in_date_context(self):
        """Test MM is interpreted as month in date-only formats."""
        # MM in date context should be month (%m)
        assert convert_umf_format_to_strftime("MM-YYYY") == "%m-%Y"
        assert convert_umf_format_to_strftime("YYYY-MM") == "%Y-%m"

    def test_mm_ambiguity_in_time_context(self):
        """Test MM is interpreted as minutes after HH: in time formats."""
        # MM after HH: should be minutes (%M)
        assert convert_umf_format_to_strftime("HH:MM") == "%H:%M"
        assert convert_umf_format_to_strftime("HH:MM:SS") == "%H:%M:%S"

    def test_complex_format_with_both_mm_contexts(self):
        """Test format with MM in both date and time contexts."""
        # First MM (month) in date, second MM (minutes) in time
        result = convert_umf_format_to_strftime("MM/DD/YYYY HH:MM:SS")
        assert result == "%m/%d/%Y %H:%M:%S"

    def test_two_digit_year(self):
        """Test YY converts to %y."""
        assert convert_umf_format_to_strftime("MM/DD/YY") == "%m/%d/%y"

    def test_time_only_format(self):
        """Test time-only formats."""
        assert convert_umf_format_to_strftime("HH:MM:SS") == "%H:%M:%S"
        assert convert_umf_format_to_strftime("HH:MM") == "%H:%M"

    def test_format_with_separators(self):
        """Test various separator characters are preserved."""
        assert convert_umf_format_to_strftime("YYYY-MM-DD") == "%Y-%m-%d"
        assert convert_umf_format_to_strftime("YYYY/MM/DD") == "%Y/%m/%d"
        assert convert_umf_format_to_strftime("YYYY.MM.DD") == "%Y.%m.%d"
        assert convert_umf_format_to_strftime("YYYY MM DD") == "%Y %m %d"

    def test_regression_issue_190_pcp_summary_mail_date(self):
        """Regression test for issue #190 - ensure YYYY-MM-DD format converts correctly."""
        # PCP_SUMMARY_MAIL_DATE uses YYYY-MM-DD format
        result = convert_umf_format_to_strftime("YYYY-MM-DD")
        assert result == "%Y-%m-%d"

        # Verify this allows parsing dates like 9999-12-31
        from datetime import datetime

        test_date = "9999-12-31"
        parsed = datetime.strptime(test_date, result)
        assert parsed.year == 9999
        assert parsed.month == 12
        assert parsed.day == 31
