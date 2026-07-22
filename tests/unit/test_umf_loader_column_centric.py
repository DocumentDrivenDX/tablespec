"""Tests for split UMF format loading (table.yaml + columns/)."""

import pytest

from tablespec.umf_loader import UMFFormat, UMFLoader

pytestmark = [pytest.mark.no_spark, pytest.mark.fast]


class TestColumnCentricFormatDetection:
    """Test format detection for split format structures (table.yaml + columns/)."""

    def test_detect_column_centric_format(self, tmp_path):
        """Test that split format (table.yaml + columns/) is detected correctly."""
        # Create split structure (table.yaml + columns/)
        (tmp_path / "table.yaml").write_text(
            "table_name: test_table\ncanonical_name: TestTable"
        )
        (tmp_path / "columns").mkdir()
        (tmp_path / "columns" / "col1.yaml").write_text("column: {name: col1}")

        loader = UMFLoader()
        detected = loader.detect_format(tmp_path)
        assert detected == UMFFormat.SPLIT

    def test_detect_split_format_legacy(self, tmp_path):
        """Test that format detection fails when only schema.yaml exists (old format not supported)."""
        (tmp_path / "schema.yaml").write_text("table_name: test_table")

        loader = UMFLoader()
        with pytest.raises(FileNotFoundError, match="no table.yaml"):
            loader.detect_format(tmp_path)

    def test_split_with_table_yaml_and_columns(self, tmp_path):
        """Test that split format (table.yaml + columns/) is the standard."""
        (tmp_path / "table.yaml").write_text("table_name: test_table")
        (tmp_path / "columns").mkdir()
        (tmp_path / "columns" / "col1.yaml").write_text("column: {name: col1}")

        loader = UMFLoader()
        detected = loader.detect_format(tmp_path)
        assert detected == UMFFormat.SPLIT

    def test_detect_format_error_on_invalid_dir(self, tmp_path):
        """Test error when directory has no table.yaml or schema.yaml."""
        (tmp_path / "some_file.yaml").write_text("data: value")

        loader = UMFLoader()
        with pytest.raises(FileNotFoundError, match="no table.yaml"):
            loader.detect_format(tmp_path)


class TestColumnCentricLoader:
    """Test loading column-centric format."""

    def test_load_minimal_column_centric(self, tmp_path):
        """Test loading minimal column-centric structure."""
        # Create minimal structure (must have at least 1 column)
        (tmp_path / "table.yaml").write_text(
            "version: '1.0'\ntable_name: test_table\ncanonical_name: TestTable\n"
        )
        (tmp_path / "columns").mkdir()
        (tmp_path / "columns" / "col1.yaml").write_text(
            "column:\n  name: col1\n  data_type: VARCHAR\n"
        )

        loader = UMFLoader()
        umf = loader.load(tmp_path)

        assert umf.table_name == "test_table"
        assert umf.canonical_name == "TestTable"
        assert umf.version == "1.0"
        assert len(umf.columns) == 1

    def test_load_column_centric_with_columns(self, tmp_path):
        """Test loading column-centric with multiple columns."""
        # Create table.yaml
        (tmp_path / "table.yaml").write_text(
            "version: '1.0'\ntable_name: outreach_list\ncanonical_name: OutreachList\n"
        )

        # Create columns
        (tmp_path / "columns").mkdir()
        (tmp_path / "columns" / "member_id.yaml").write_text(
            "column:\n"
            "  name: member_id\n"
            "  canonical_name: MemberId\n"
            "  data_type: VARCHAR\n"
            "  length: 20\n"
            "  nullable:\n"
            "    MD: false\n"
            "    ME: false\n"
            "    MP: false\n"
        )
        (tmp_path / "columns" / "status.yaml").write_text(
            "column:\n"
            "  name: status\n"
            "  canonical_name: Status\n"
            "  data_type: VARCHAR\n"
            "  nullable:\n"
            "    MD: true\n"
            "    ME: true\n"
            "    MP: true\n"
        )

        loader = UMFLoader()
        umf = loader.load(tmp_path)

        assert len(umf.columns) == 2
        assert umf.columns[0].name == "member_id"
        assert umf.columns[0].length == 20
        assert umf.columns[1].name == "status"

    def test_load_column_centric_with_validations(self, tmp_path):
        """Test loading column-centric with column-level validations."""
        (tmp_path / "table.yaml").write_text(
            "version: '1.0'\ntable_name: test_table\ncanonical_name: TestTable\n"
        )

        (tmp_path / "columns").mkdir()
        (tmp_path / "columns" / "email.yaml").write_text(
            "column:\n"
            "  name: email\n"
            "  data_type: VARCHAR\n"
            "validations:\n"
            "  - type: expect_column_values_to_match_regex\n"
            "    kwargs:\n"
            "      column: email\n"
            "      regex: '^[^@]+@[^@]+$'\n"
            "    meta:\n"
            "      severity: warning\n"
            "      description: Email format check\n"
        )

        loader = UMFLoader()
        umf = loader.load(tmp_path)

        assert len(umf.columns) == 1
        assert umf.validation_rules is not None
        assert len(umf.validation_rules.expectations) == 1
        exp = umf.validation_rules.expectations[0]
        assert exp["type"] == "expect_column_values_to_match_regex"
        assert exp["kwargs"]["column"] == "email"

    def test_load_column_centric_with_relationships(self, tmp_path):
        """Test loading column-centric with relationships in table.yaml."""
        (tmp_path / "table.yaml").write_text(
            "version: '1.0'\n"
            "table_name: outreach\n"
            "canonical_name: Outreach\n"
            "relationships:\n"
            "  foreign_keys:\n"
            "    - column: member_id\n"
            "      references_table: members\n"
            "      references_column: id\n"
        )

        (tmp_path / "columns").mkdir()
        (tmp_path / "columns" / "member_id.yaml").write_text(
            "column:\n  name: member_id\n  data_type: VARCHAR\n"
        )

        loader = UMFLoader()
        umf = loader.load(tmp_path)

        assert umf.relationships is not None
        assert len(umf.relationships.foreign_keys) == 1
        assert umf.relationships.foreign_keys[0].column == "member_id"

    def test_load_column_centric_with_validation_rules(self, tmp_path):
        """Test loading column-centric with cross-column validations."""
        (tmp_path / "table.yaml").write_text(
            "version: '1.0'\ntable_name: test_table\ncanonical_name: TestTable\n"
        )

        (tmp_path / "validation_rules.yaml").write_text(
            "expectations:\n"
            "  - type: expect_compound_columns_to_be_unique\n"
            "    kwargs:\n"
            "      column_list:\n"
            "        - id\n"
            "        - date\n"
            "    meta:\n"
            "      severity: critical\n"
            "      description: ID and date must be unique together\n"
        )

        (tmp_path / "columns").mkdir()
        (tmp_path / "columns" / "id.yaml").write_text(
            "column: {name: id, data_type: VARCHAR}"
        )
        (tmp_path / "columns" / "date.yaml").write_text(
            "column: {name: date, data_type: DATE}"
        )

        loader = UMFLoader()
        umf = loader.load(tmp_path)

        assert len(umf.columns) == 2
        assert umf.validation_rules is not None
        assert len(umf.validation_rules.expectations) == 1
        exp = umf.validation_rules.expectations[0]
        assert exp["type"] == "expect_compound_columns_to_be_unique"

    def test_load_column_centric_with_derivations(self, tmp_path):
        """Test loading column-centric with derivations/survivorship."""
        (tmp_path / "table.yaml").write_text(
            "version: '1.0'\ntable_name: test_table\ncanonical_name: TestTable\n"
        )

        (tmp_path / "columns").mkdir()
        (tmp_path / "columns" / "member_id.yaml").write_text(
            "column:\n"
            "  name: member_id\n"
            "  canonical_name: MemberId\n"
            "  data_type: VARCHAR\n"
            "derivation:\n"
            "  candidates:\n"
            "    - table: source1\n"
            "      column: id\n"
            "      priority: 1\n"
            "  survivorship:\n"
            "    strategy: highest_priority\n"
            "    explanation: Use highest priority source\n"
        )

        loader = UMFLoader()
        umf = loader.load(tmp_path)

        # Verify derivation is loaded into column
        assert len(umf.columns) == 1
        col = umf.columns[0]
        assert col.derivation is not None
        assert len(col.derivation.candidates) == 1
        assert col.derivation.candidates[0].table == "source1"
        assert col.derivation.candidates[0].column == "id"
        assert col.derivation.candidates[0].priority == 1
        assert col.derivation.survivorship is not None
        assert col.derivation.survivorship.strategy == "highest_priority"

        # Verify derivation is also in top-level derivations for backward compatibility
        assert umf.derivations is not None
        assert "MemberId" in umf.derivations["mappings"]
        assert len(umf.derivations["mappings"]["MemberId"]["candidates"]) == 1

    def test_detect_format_error_no_files(self, tmp_path):
        """Test format detection fails when no recognized files present."""
        # Create empty directory with only unrelated files
        (tmp_path / "other_file.txt").write_text("not yaml")

        loader = UMFLoader()
        with pytest.raises(FileNotFoundError, match="no table.yaml"):
            loader.load(tmp_path)

    def test_detect_format_requires_both_table_and_columns(self, tmp_path):
        """Test that column-centric format requires both table.yaml AND columns/ directory."""
        # Only create table.yaml without columns/ directory
        (tmp_path / "table.yaml").write_text("table_name: test_table")

        loader = UMFLoader()
        with pytest.raises(FileNotFoundError, match="no columns"):
            loader.load(tmp_path)

    def test_column_centric_preserves_all_metadata(self, tmp_path):
        """Test that column-centric format preserves all important metadata."""
        (tmp_path / "table.yaml").write_text(
            "version: '1.0'\n"
            "table_name: test_table\n"
            "canonical_name: TestTable\n"
            "description: A test table\n"
            "table_type: provided\n"
            "file_format:\n"
            "  delimiter: '|'\n"
            "  encoding: utf-8\n"
        )

        (tmp_path / "columns").mkdir()
        (tmp_path / "columns" / "col1.yaml").write_text(
            "column:\n  name: col1\n  data_type: VARCHAR\n  nullable:\n    MD: false\n"
        )

        loader = UMFLoader()
        umf = loader.load(tmp_path)

        assert umf.description == "A test table"
        assert umf.table_type == "provided"
        assert umf.file_format.delimiter == "|"
        assert umf.columns[0].nullable.MD is False
