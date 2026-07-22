"""Unit tests for filename_generator module."""

import logging

import pytest

from tablespec.sample_data.filename_generator import FilenameGenerator

pytestmark = pytest.mark.fast


class TestGetCaptureGroupPatternForColumn:
    """Test extraction of capture group patterns for specific columns."""

    @pytest.fixture
    def generator(self):
        """Create FilenameGenerator instance."""
        logger = logging.getLogger("test")
        return FilenameGenerator(logger)

    def test_extracts_simple_capture_group(self, generator):
        """Test extracting a simple capture group pattern."""
        captures = {"1": "vendor", "2": "state"}
        filename_pattern = r"^([A-Z0-9]+)_([A-Z]{2})_file\.txt$"

        # Extract pattern for vendor (capture group 1)
        pattern = generator.get_capture_group_pattern_for_column(
            "vendor", captures, filename_pattern
        )
        assert pattern == "[A-Z0-9]+"

        # Extract pattern for state (capture group 2)
        pattern = generator.get_capture_group_pattern_for_column(
            "state", captures, filename_pattern
        )
        assert pattern == "[A-Z]{2}"

    def test_extracts_digit_pattern(self, generator):
        """Test extracting numeric capture groups."""
        captures = {"1": "year", "2": "date"}
        filename_pattern = r"^file_([0-9]{4})_([0-9]{8})\.txt$"

        pattern = generator.get_capture_group_pattern_for_column(
            "year", captures, filename_pattern
        )
        assert pattern == "[0-9]{4}"

        pattern = generator.get_capture_group_pattern_for_column(
            "date", captures, filename_pattern
        )
        assert pattern == "[0-9]{8}"

    def test_returns_none_for_nonexistent_column(self, generator):
        """Test that None is returned for columns not in captures."""
        captures = {"1": "vendor"}
        filename_pattern = r"^([A-Z0-9]+)_file\.txt$"

        pattern = generator.get_capture_group_pattern_for_column(
            "nonexistent", captures, filename_pattern
        )
        assert pattern is None

    def test_handles_dict_metadata_format(self, generator):
        """Test handling capture metadata in dict format."""
        captures = {"1": {"column": "vendor", "type": "string"}, "2": {"name": "state"}}
        filename_pattern = r"^([A-Z0-9]+)_([A-Z]{2})_file\.txt$"

        # Should work with 'column' key
        pattern = generator.get_capture_group_pattern_for_column(
            "vendor", captures, filename_pattern
        )
        assert pattern == "[A-Z0-9]+"

        # Should work with 'name' key
        pattern = generator.get_capture_group_pattern_for_column(
            "state", captures, filename_pattern
        )
        assert pattern == "[A-Z]{2}"

    def test_skips_non_capturing_groups(self, generator):
        """Test that non-capturing groups (?:...) are skipped."""
        captures = {"1": "vendor", "2": "state"}
        # Pattern has non-capturing group before first capture
        filename_pattern = r"^(?:prefix_)?([A-Z0-9]+)_([A-Z]{2})_file\.txt$"

        # First capturing group should still be vendor
        pattern = generator.get_capture_group_pattern_for_column(
            "vendor", captures, filename_pattern
        )
        assert pattern == "[A-Z0-9]+"

    def test_handles_nested_groups(self, generator):
        """Test handling patterns with nested parentheses."""
        captures = {"1": "code"}
        filename_pattern = r"^((?:[A-Z]|[0-9])+)_file\.txt$"

        pattern = generator.get_capture_group_pattern_for_column(
            "code", captures, filename_pattern
        )
        assert pattern == "(?:[A-Z]|[0-9])+"

    def test_handles_alternation_in_capture(self, generator):
        """Test patterns with alternation inside capture groups."""
        captures = {"1": "mode"}
        filename_pattern = r"^file_(I|R|A|U)\.txt$"

        pattern = generator.get_capture_group_pattern_for_column(
            "mode", captures, filename_pattern
        )
        assert pattern == "I|R|A|U"

    def test_handles_optional_groups(self, generator):
        """Test patterns with optional capture groups."""
        captures = {"1": "vendor", "2": "mode"}
        filename_pattern = r"^([A-Z0-9]+)(?:_([MODE]))?\.txt$"

        pattern = generator.get_capture_group_pattern_for_column(
            "vendor", captures, filename_pattern
        )
        assert pattern == "[A-Z0-9]+"

        # Optional group is still a capturing group
        pattern = generator.get_capture_group_pattern_for_column(
            "mode", captures, filename_pattern
        )
        assert pattern == "[MODE]"


class TestGenerateFilenameFromPattern:
    """Test filename generation from UMF patterns."""

    @pytest.fixture
    def generator(self):
        """Create FilenameGenerator instance."""
        logger = logging.getLogger("test")
        return FilenameGenerator(logger)

    def test_generates_simple_filename(self, generator):
        """Test generating a simple filename from pattern."""
        umf_data = {
            "file_format": {
                "filename_pattern": {
                    "regex": r"^([A-Z0-9]+)_([A-Z]{2})_file\.txt$",
                    "captures": {"1": "vendor", "2": "state"},
                }
            },
            "columns": [],
        }
        records = [{"vendor": "ACME", "state": "IL"}]

        filename = generator.generate_filename_from_pattern(
            "test_table", umf_data, records
        )
        assert filename == "ACME_IL_file.txt"

    def test_generates_filename_with_dates(self, generator):
        """Test generating filename with date components."""
        umf_data = {
            "file_format": {
                "filename_pattern": {
                    "regex": r"^file_([0-9]{4})_([0-9]{8})\.txt$",
                    "captures": {"1": "year", "2": "date"},
                }
            },
            "columns": [],
        }
        records = [{"year": "2024", "date": "20241015"}]

        filename = generator.generate_filename_from_pattern(
            "test_table", umf_data, records
        )
        assert filename == "file_2024_20241015.txt"

    def test_fallback_to_simple_name_when_no_pattern(self, generator):
        """Test that simple table name is used when no pattern exists."""
        umf_data = {"file_format": {}, "columns": []}
        records = []

        filename = generator.generate_filename_from_pattern(
            "test_table", umf_data, records
        )
        assert filename == "test_table.txt"

    def test_fallback_when_no_records(self, generator):
        """Test fallback behavior when no records provided."""
        umf_data = {
            "file_format": {
                "filename_pattern": {
                    "regex": r"^file_([A-Z]+)\.txt$",
                    "captures": {"1": "vendor"},
                }
            },
            "columns": [],
        }
        records = []

        filename = generator.generate_filename_from_pattern(
            "test_table", umf_data, records
        )
        assert filename == "test_table.txt"

    def test_handles_flat_yaml_structure(self, generator):
        """Test handling legacy flat YAML structure."""
        umf_data = {
            "file_format": {
                "filename_pattern": r"^([A-Z0-9]+)_file\.txt$",
                "captures": {"1": "vendor"},
            },
            "columns": [],
        }
        records = [{"vendor": "ACME"}]

        filename = generator.generate_filename_from_pattern(
            "test_table", umf_data, records
        )
        assert filename == "ACME_file.txt"

    def test_handles_filename_sourced_columns(self, generator):
        """Test that filename-sourced columns use sample_values from UMF."""
        umf_data = {
            "file_format": {
                "filename_pattern": {
                    "regex": r"^([A-Z0-9]+)_([A-Z]{2})_file\.txt$",
                    "captures": {"1": "vendor", "2": "state"},
                }
            },
            "columns": [
                {"name": "vendor", "source": "filename", "sample_values": ["VENDOR1"]},
                {"name": "state", "source": "filename", "sample_values": ["CA"]},
            ],
        }
        records = [{}]  # Empty record - should use sample_values

        filename = generator.generate_filename_from_pattern(
            "test_table", umf_data, records
        )
        assert filename == "VENDOR1_CA_file.txt"

    def test_handles_optional_capture_groups(self, generator):
        """Test handling optional capture groups in pattern."""
        umf_data = {
            "file_format": {
                "filename_pattern": {
                    "regex": r"^([A-Z0-9]+)_file(?:_([MODE]))?\.txt$",
                    "captures": {"1": "vendor", "2": "mode"},
                }
            },
            "columns": [{"name": "vendor", "source": "data"}],
        }
        records = [{"vendor": "ACME"}]  # mode not provided

        filename = generator.generate_filename_from_pattern(
            "test_table", umf_data, records
        )
        # Should handle missing optional capture gracefully
        assert "ACME" in filename
        assert filename.endswith(".txt")

    def test_extracts_csv_extension(self, generator):
        """Test that CSV extension is extracted and used."""
        umf_data = {
            "file_format": {
                "filename_pattern": {
                    "regex": r"^file_([0-9]{8})\.csv$",
                    "captures": {"1": "date"},
                }
            },
            "columns": [],
        }
        records = [{"date": "20241015"}]

        filename = generator.generate_filename_from_pattern(
            "test_table", umf_data, records
        )
        assert filename == "file_20241015.csv"
        assert filename.endswith(".csv")

    def test_extracts_xlsx_extension(self, generator):
        """Test that XLSX extension is extracted and used."""
        umf_data = {
            "file_format": {
                "filename_pattern": {
                    "regex": r"^report\.xlsx$",
                    "captures": {},
                }
            },
            "columns": [],
        }
        records = [{}]

        filename = generator.generate_filename_from_pattern(
            "test_table", umf_data, records
        )
        assert filename == "report.xlsx"

    def test_handles_complex_outreach_list_pattern(self, generator):
        """Test with real OutreachList pattern from testdata pipeline."""
        umf_data = {
            "canonical_name": "OutreachList",
            "file_format": {
                "filename_pattern": {
                    "regex": r"(?i)^([A-Z0-9]+)_([A-Z]{2})_(MD|ME|MP)_OutreachList_([0-9]{4})_([0-9]{8})_(I|R|A|U)\.txt$",
                    "captures": {
                        "1": "source_vendor_prefix",
                        "2": "source_state",
                        "3": "source_lob",
                        "4": "source_project_code",
                        "5": "source_file_date",
                        "6": "source_file_mode",
                    },
                }
            },
            "columns": [
                {
                    "name": "source_vendor_prefix",
                    "source": "filename",
                    "sample_values": ["ACME"],
                },
                {"name": "source_state", "source": "filename", "sample_values": ["IL"]},
                {"name": "source_lob", "source": "filename", "sample_values": ["MD"]},
                {
                    "name": "source_project_code",
                    "source": "filename",
                    "sample_values": ["1001"],
                },
                {
                    "name": "source_file_date",
                    "source": "filename",
                    "sample_values": ["20241015"],
                },
                {
                    "name": "source_file_mode",
                    "source": "filename",
                    "sample_values": ["I"],
                },
            ],
        }
        records = [{}]

        filename = generator.generate_filename_from_pattern(
            "OutreachList", umf_data, records
        )
        assert filename == "ACME_IL_MD_OutreachList_1001_20241015_I.txt"

    def test_handles_missing_capture_values(self, generator):
        """Test handling when capture values are missing."""
        umf_data = {
            "file_format": {
                "filename_pattern": {
                    "regex": r"^([A-Z0-9]+)_([A-Z]{2})_file\.txt$",
                    "captures": {"1": "vendor", "2": "state"},
                }
            },
            "columns": [],
        }
        # Record missing 'state' value
        records = [{"vendor": "ACME"}]

        filename = generator.generate_filename_from_pattern(
            "test_table", umf_data, records
        )
        # Should use UNKNOWN for missing values
        assert "ACME" in filename
        assert "UNKNOWN" in filename or filename.endswith(".txt")

    def test_handles_none_values(self, generator):
        """Test handling None values in record."""
        umf_data = {
            "file_format": {
                "filename_pattern": {
                    "regex": r"^([A-Z0-9]+)_file\.txt$",
                    "captures": {"1": "vendor"},
                }
            },
            "columns": [],
        }
        records = [{"vendor": None}]

        filename = generator.generate_filename_from_pattern(
            "test_table", umf_data, records
        )
        # Should use UNKNOWN for None values
        assert "UNKNOWN" in filename

    def test_strips_anchors_from_pattern(self, generator):
        """Test that pattern anchors (^ and $) are properly stripped."""
        umf_data = {
            "file_format": {
                "filename_pattern": {
                    "regex": r"^file_([A-Z]+)\.txt$",
                    "captures": {"1": "vendor"},
                }
            },
            "columns": [],
        }
        records = [{"vendor": "ACME"}]

        filename = generator.generate_filename_from_pattern(
            "test_table", umf_data, records
        )
        assert filename == "file_ACME.txt"
        # Should not contain literal ^ or $
        assert "^" not in filename
        assert "$" not in filename

    def test_handles_inline_flags(self, generator):
        """Test handling inline regex flags like (?i) for case-insensitive."""
        umf_data = {
            "file_format": {
                "filename_pattern": {
                    "regex": r"(?i)^file_([A-Z]+)\.txt$",
                    "captures": {"1": "vendor"},
                }
            },
            "columns": [],
        }
        records = [{"vendor": "acme"}]

        filename = generator.generate_filename_from_pattern(
            "test_table", umf_data, records
        )
        assert "acme" in filename.lower()
        # Should not contain (?i) in output
        assert "(?i)" not in filename

    def test_logs_warning_on_pattern_mismatch(self, generator, caplog):
        """Test that warning is logged when generated filename doesn't match pattern."""
        import logging

        umf_data = {
            "file_format": {
                "filename_pattern": {
                    "regex": r"^STRICT_([A-Z]{2})_file\.txt$",  # Very strict pattern
                    "captures": {"1": "code"},
                }
            },
            "columns": [],
        }
        # Generate value that won't match strict pattern
        records = [{"code": "123"}]  # Digits won't match [A-Z]{2}

        with caplog.at_level(logging.WARNING):
            generator.generate_filename_from_pattern("test_table", umf_data, records)

        # Should log warning about mismatch (check for WARNING or ERROR level)
        assert any(
            (
                "does not match" in record.message.lower()
                or "validation failed" in record.message.lower()
            )
            for record in caplog.records
        )

    def test_handles_empty_captures(self, generator):
        """Test handling pattern with no captures."""
        umf_data = {
            "file_format": {
                "filename_pattern": {"regex": r"^static_file\.txt$", "captures": {}}
            },
            "columns": [],
        }
        records = [{}]

        filename = generator.generate_filename_from_pattern(
            "test_table", umf_data, records
        )
        assert filename == "static_file.txt"

    def test_handles_shorthand_digit_class_outside_capture(self, generator):
        r"""Test that \d{N} outside capture groups expands to representative digits."""
        umf_data = {
            "file_format": {
                "filename_pattern": {
                    "regex": r"^\d{4}_file_([0-9]{8})\.txt$",
                    "captures": {"1": "date"},
                }
            },
            "columns": [],
        }
        records = [{"date": "20241015"}]

        filename = generator.generate_filename_from_pattern(
            "test_table", umf_data, records
        )
        assert filename == "0000_file_20241015.txt"

    def test_handles_character_class_outside_capture(self, generator):
        """Test that [A-Z]{N} outside capture groups expands to representative chars."""
        umf_data = {
            "file_format": {
                "filename_pattern": {
                    "regex": r"^[A-Z]{3}_([0-9]{4})\.txt$",
                    "captures": {"1": "code"},
                }
            },
            "columns": [],
        }
        records = [{"code": "1234"}]

        filename = generator.generate_filename_from_pattern(
            "test_table", umf_data, records
        )
        assert filename == "AAA_1234.txt"

    def test_giftcard_pattern_with_backslash_d(self, generator):
        r"""Test exact giftcard pattern with \d{4} prefix."""
        umf_data = {
            "file_format": {
                "filename_pattern": {
                    "regex": r"^\d{4}_Master_Fulfillment_List_([0-9]{8})\.txt$",
                    "captures": {"1": "file_date_yyyymmdd"},
                }
            },
            "columns": [
                {
                    "name": "file_date_yyyymmdd",
                    "source": "filename",
                    "sample_values": ["20250421"],
                },
            ],
        }
        records = [{}]

        filename = generator.generate_filename_from_pattern(
            "giftcard", umf_data, records
        )
        assert filename == "0000_Master_Fulfillment_List_20250421.txt"
