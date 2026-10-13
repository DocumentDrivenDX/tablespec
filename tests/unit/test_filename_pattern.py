"""Unit tests for FilenamePattern model and functionality."""

from pydantic import ValidationError
import pytest

from tablespec.models import FileFormatSpec, FilenamePattern

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]


class TestFilenamePattern:
    """Test FilenamePattern model."""

    def test_basic_pattern(self):
        """Test basic filename pattern creation."""
        pattern = FilenamePattern(
            regex=r"^([A-Z]+)_([A-Z]{2})_([A-Z]{2})_OutreachList\.txt$",
            captures={1: "source_vendor", 2: "source_state", 3: "source_lob"},
            description="Basic outreach file pattern",
        )

        assert pattern.regex == r"^([A-Z]+)_([A-Z]{2})_([A-Z]{2})_OutreachList\.txt$"
        assert pattern.captures == {
            1: "source_vendor",
            2: "source_state",
            3: "source_lob",
        }
        assert pattern.description == "Basic outreach file pattern"

    def test_pattern_with_mode(self):
        """Test filename pattern with mode field."""
        pattern = FilenamePattern(
            regex=r"^([A-Z]+)_([A-Z]{2})_([A-Z]{2})_OutreachList_([0-9]{8})_([AIRU])\.txt$",
            captures={
                1: "source_vendor",
                2: "source_state",
                3: "source_lob",
                4: "source_date",
                5: "mode",
            },
        )

        assert pattern.captures[5] == "mode"
        assert len(pattern.captures) == 5

    def test_pattern_optional_description(self):
        """Test that description is optional."""
        pattern = FilenamePattern(
            regex=r"^test\.txt$",
            captures={1: "test_field"},
        )

        assert pattern.description is None

    def test_pattern_in_file_format_spec(self):
        """Test FilenamePattern integration with FileFormatSpec."""
        file_format = FileFormatSpec(
            delimiter="|",
            encoding="utf-8",
            header=True,
            filename_pattern=FilenamePattern(
                regex=r"^([A-Z]+)_([0-9]{8})\.txt$",
                captures={1: "vendor", 2: "date"},
            ),
        )

        assert file_format.filename_pattern is not None
        assert file_format.filename_pattern.regex == r"^([A-Z]+)_([0-9]{8})\.txt$"
        assert file_format.filename_pattern.captures == {1: "vendor", 2: "date"}

    def test_pattern_serialization(self):
        """Test FilenamePattern serialization."""
        pattern = FilenamePattern(
            regex=r"^test_([0-9]+)\.txt$",
            captures={1: "file_number"},
            description="Test pattern",
        )

        data = pattern.model_dump()
        assert data["regex"] == r"^test_([0-9]+)\.txt$"
        assert data["captures"] == {1: "file_number"}
        assert data["description"] == "Test pattern"

    def test_pattern_deserialization(self):
        """Test FilenamePattern deserialization."""
        data = {
            "regex": r"^test_([0-9]+)\.txt$",
            "captures": {1: "file_number"},
            "description": "Test pattern",
        }

        pattern = FilenamePattern(**data)
        assert pattern.regex == r"^test_([0-9]+)\.txt$"
        assert pattern.captures == {1: "file_number"}
        assert pattern.description == "Test pattern"

    def test_complex_pattern_with_optional_groups(self):
        """Test complex pattern with optional capture groups."""
        pattern = FilenamePattern(
            regex=r"^([A-Z]+)(?:-([A-Z]+))?_([A-Z]{2})_([A-Z]{2})_OutreachList_([0-9]+)_([0-9]{8})_([AIRU])\.txt$",
            captures={
                1: "source_vendor",
                2: "source_subvendor",
                3: "source_state",
                4: "source_lob",
                5: "source_project_id",
                6: "source_date",
                7: "mode",
            },
            description="Standard outreach file with optional subvendor",
        )

        assert len(pattern.captures) == 7
        assert pattern.captures[2] == "source_subvendor"
        assert pattern.captures[7] == "mode"

    def test_mode_values_documentation(self):
        """Test that mode field is properly documented."""
        pattern = FilenamePattern(
            regex=r"^.*_([AIRU])\.txt$",
            captures={1: "mode"},
            description="Mode values: I=Initial, R=Replace, A=Append, U=Update",
        )

        assert "mode" in pattern.captures.values()
        assert "Initial" in pattern.description
        assert "Replace" in pattern.description
        assert "Append" in pattern.description
        assert "Update" in pattern.description


class TestFilenamePatternValidation:
    """Test FilenamePattern validation rules."""

    def test_requires_regex(self):
        """Test that regex is required."""
        with pytest.raises(ValidationError):
            FilenamePattern(captures={1: "test"})

    def test_requires_captures(self):
        """Test that captures dict is required."""
        with pytest.raises(ValidationError):
            FilenamePattern(regex=r"^test\.txt$")

    def test_captures_must_be_dict(self):
        """Test that captures must be a dictionary."""
        with pytest.raises(ValidationError):
            FilenamePattern(regex=r"^test\.txt$", captures="invalid")


class TestFileFormatSpecWithPattern:
    """Test FileFormatSpec integration with FilenamePattern."""

    def test_file_format_without_pattern(self):
        """Test FileFormatSpec works without filename_pattern."""
        file_format = FileFormatSpec(
            delimiter="|",
            encoding="utf-8",
            header=True,
        )

        assert file_format.filename_pattern is None

    def test_file_format_with_pattern(self):
        """Test FileFormatSpec with filename_pattern."""
        file_format = FileFormatSpec(
            delimiter="|",
            encoding="utf-8",
            header=True,
            filename_pattern=FilenamePattern(
                regex=r"^([A-Z]+)\.txt$",
                captures={1: "vendor"},
            ),
        )

        assert file_format.filename_pattern is not None
        assert isinstance(file_format.filename_pattern, FilenamePattern)

    def test_file_format_serialization_with_pattern(self):
        """Test FileFormatSpec serialization with pattern."""
        file_format = FileFormatSpec(
            delimiter="|",
            filename_pattern=FilenamePattern(
                regex=r"^test_([0-9]+)\.txt$",
                captures={1: "number"},
            ),
        )

        data = file_format.model_dump(exclude_none=True)
        assert "filename_pattern" in data
        assert data["filename_pattern"]["regex"] == r"^test_([0-9]+)\.txt$"
        assert data["filename_pattern"]["captures"] == {1: "number"}
